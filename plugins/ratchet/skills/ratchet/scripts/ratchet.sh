#!/usr/bin/env bash
# shellcheck disable=SC2001  # prefixing each line of a multi-line value is sed's job
#
# ratchet — the deterministic parts of the gates, so the model never re-derives them.
# bash 3.2-compatible (macOS /bin/bash). Run from anywhere inside the repo; all paths
# are relative to the repo root. <tree> is any tree-ish: a SHA or refs/ratchet/<name>.
#
#   snap [<name>]              tree SHA of the working tree: tracked + untracked files,
#                              .gitignore respected, the user's index untouched, works
#                              with zero commits; <name> anchors it at refs/ratchet/<name>
#                              so gc can't prune it
#   drop <prefix>              delete the anchors under refs/ratchet/<prefix>
#   diff <tree> [git-diff-opt] changes since <tree>, minus .claude/ratchet; a plain patch
#                              also omits lockfiles (listed at the end instead)
#   size <tree>                changed lines (added + deleted) since <tree>, minus
#                              .claude/ratchet, lockfiles and binaries
#   changed <tree>             exit 1 listing what changed outside .claude/ratchet since
#                              <tree>; exit 0 "unchanged" otherwise
#   tripwire <tree>            added lines that skip, focus or silence checks
#   stage <tree> [path...]     git add exactly what changed since <tree>, plus the given
#                              paths; warns when a file also held the user's uncommitted
#                              edits from before <tree>
#   lock <dir> <file>...       pin files: hash in <dir>/spec.lock, copy in <dir>/locked/
#   lock <dir> --from <file>   the same; <file> lists the paths, one for each line. Use it
#                              instead of `lock <dir> $FILES`, which zsh does not split.
#   check <dir>...             exit 1 listing pinned files that changed or vanished
#   restore <dir>              put changed or vanished pinned files back from the copies
#   baton <slug> continue|stop <start> [<line>...]
#                              write the minimal handover .claude/handovers/ratchet-<slug>.md
#                              (start = the resume command and next gate; lines = only what
#                              isn't on disk) and print the marker the relay mod acts on
#   baton <slug> clear         delete it: the plan is done
#
# These commands run in Python (python3 3.9 or newer; RS_PYTHON names another one). Each
# prints one JSON object of 1 KB or less and puts the detail in an evidence file. The exit
# code is 0 for pass, 1 for fail and 2 for error. Any rs/cmd_<name>.py also runs as <name>.
#
#   state <slug> [<cp>]        where a checkpoint stands; without <cp>, the first open row
#   gate <gate> <slug> <cp> --nonce <n> [--round <r>] [--skip-arch]
#                              run b0-prep, b0, b1, b2-capture, b2, smoke, b3-prep or b3; then
#                              update STATE and LIVE and add one line to METRICS
#   prove <slug> <cp> <id>     run a finding's proof: reproduced, unproven or invalid
#   red-check <output-file>    say why a spec run failed: assert, stub, compile or runner
#   size --prod <tree>         changed production and test lines since <tree>; skips lockfiles,
#                              binaries and generated files (plain `size` stays in bash)
#   exec --timeout <s> -- <cmd>
#                              run <cmd> in a shell; after <s> seconds stop its process
#                              group and exit 124
#   live start <slug> <cp>     write LIVE with active true
#   live set <key> <value>     update one LIVE field; <value> is JSON, else text
#   live stop                  set active false
#   metrics add <json>         append one line to metrics.jsonl
#   report <slug> <cp>         write EV/4-report.md; print 10 lines or fewer for the human
#   decide <slug> <cp> <text> [--reopen b1|b3]
#                              log the human's decision and start the next epoch
#   retire <slug> <cp> <path> --reason <text>
#                              unpin one test file and log the reason in 0-amendments.md
#   row <slug> <cp> [<status>] [--base <sha>] [--note <text>]
#                              change one plan row and add a note under ## Notes
#   trace <slug> [<cp>]        requirement IDs against plan rows and test names
#   config                     print config.json as version 2, with defaults filled in
#   stelint | doclint <path>...
#                              the STE-lite and document checks of references/docs.md
#   learnings --scope <path>...
#                              the learnings that apply to these paths (markdown, not JSON)
#   keepawake start|stop       keep a Mac awake during a run, with caffeinate
#   dream harvest|curate|apply|install|uninstall|register ...
#                              the learning loop of references/dream.md

set -euo pipefail

STATE=':(exclude).claude/ratchet'
LOCKS=(':(exclude)*.lock' ':(exclude)*.lockb' ':(exclude)package-lock.json'
       ':(exclude)pnpm-lock.yaml' ':(exclude)go.sum')
LOCKS_RE='(\.lockb?|package-lock\.json|pnpm-lock\.yaml|go\.sum)$'
# Ignores the user's diff.external / noprefix / color config, so output is parseable.
DIFF=(diff --no-color --no-ext-diff --src-prefix=a/ --dst-prefix=b/)
TRIP='\.(skip|only|todo)[(.]|(^|[^A-Za-z0-9_])(x(it|describe|test)|f(it|describe))\(|@ts-(ignore|nocheck|expect-error)|eslint-disable|type: *ignore|noqa|mark\.skip|unittest\.skip|pytest\.skip|#\[ignore\]|t\.Skip\('
TAB=$(printf '\t')

die() { echo "ratchet: $*" >&2; exit 2; }

to_top() {
  local top
  top=$(git rev-parse --show-toplevel 2>/dev/null) || die "not a git repository — ratchet needs one"
  cd "$top"
}

# Outside a repo, lock/check/restore still work relative to the current directory.
to_top_soft() { local top; if top=$(git rev-parse --show-toplevel 2>/dev/null); then cd "$top"; fi; }

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
SELF="$HERE/$(basename "${BASH_SOURCE[0]}")"
PY=${RS_PYTHON:-python3}

# The Python core calls back into this script for snapshots, diffs and pins.
py() {
  command -v "$PY" >/dev/null 2>&1 || die "$PY not found: the $cmd command needs Python 3.9 or newer"
  to_top_soft
  # No .pyc files: the plugin directory may be read-only, and a cache would dirty the repo.
  export RS_SH="$SELF" RS_ROOT="$PWD" PYTHONDONTWRITEBYTECODE=1
  "$PY" "$HERE/rs/main.py" "$cmd" "$@"
  exit $?
}

snap() {
  local tmp sha
  tmp="$(git rev-parse --absolute-git-dir)/ratchet-snap.$$.index"
  # Seed from the real index so unchanged files aren't re-hashed on big repos.
  cp "$(git rev-parse --git-path index)" "$tmp" 2>/dev/null || true
  if GIT_INDEX_FILE="$tmp" git add -A >/dev/null && sha=$(GIT_INDEX_FILE="$tmp" git write-tree); then
    rm -f "$tmp"; echo "$sha"
  else
    rm -f "$tmp" "$tmp.lock"; die "snapshot failed"
  fi
}

need_tree() {
  [ -n "${1:-}" ] || die "missing <tree> argument"
  git cat-file -e "$1^{tree}" 2>/dev/null || die "unknown tree: $1 (garbage-collected, or from another clone?)"
}

cmd=${1:-}; shift || true
case "$cmd" in
  snap)
    to_top; sha=$(snap)
    if [ -n "${1:-}" ]; then git update-ref "refs/ratchet/$1" "$sha"; fi
    echo "$sha"
    ;;
  drop)
    to_top; [ -n "${1:-}" ] || die "usage: drop <prefix>"
    git for-each-ref --format='%(refname)' "refs/ratchet/$1" | while IFS= read -r ref; do
      git update-ref -d "$ref"; echo "dropped $ref"
    done
    ;;
  diff)
    to_top; need_tree "${1:-}"; base=$1; shift; now=$(snap)
    if [ $# -eq 0 ]; then
      git "${DIFF[@]}" "$base" "$now" -- . "$STATE" "${LOCKS[@]}"
      omitted=$(git diff --name-only "$base" "$now" -- . "$STATE" | grep -E "$LOCKS_RE" || true)
      [ -z "$omitted" ] || { echo; echo "# lockfiles changed (patch omitted):"; echo "$omitted" | sed 's/^/#   /'; }
    else
      git "${DIFF[@]}" "$@" "$base" "$now" -- . "$STATE"
    fi
    ;;
  size)
    if [ "${1:-}" = "--prod" ]; then py "$@"; fi
    to_top; need_tree "${1:-}"; now=$(snap)
    git diff --numstat "$1" "$now" -- . "$STATE" "${LOCKS[@]}" |
      awk '$1 != "-" { n += $1 + $2 } END { print n + 0 }'
    ;;
  changed)
    to_top; need_tree "${1:-}"; now=$(snap)
    if git diff --no-ext-diff --quiet "$1" "$now" -- . "$STATE"; then
      echo unchanged
    else
      echo "changed since $1:"; git diff --name-only "$1" "$now" -- . "$STATE" | sed 's/^/  /'; exit 1
    fi
    ;;
  tripwire)
    to_top; need_tree "${1:-}"; now=$(snap)
    git "${DIFF[@]}" -U0 "$1" "$now" -- . "$STATE" "${LOCKS[@]}" |
      awk '/^\+\+\+ / { f = substr($0, 7); next } /^\+/ { print f ": " substr($0, 2) }' |
      grep -E "$TRIP" || echo "tripwire: clean"
    ;;
  stage)
    to_top; need_tree "${1:-}"; base=$1; shift; now=$(snap)
    files=$(git diff --name-only --no-renames "$base" "$now" -- . "$STATE")
    if git rev-parse -q --verify HEAD >/dev/null; then
      overlap=$(comm -12 <(git diff --name-only --no-renames HEAD "$base" | sort) \
                         <(printf '%s\n' "$files" | sort) | sed '/^$/d')
      if [ -n "$overlap" ]; then
        echo "ratchet: WARNING — these also held the user's uncommitted edits from before the checkpoint; check them before committing:" >&2
        echo "$overlap" | sed 's/^/  /' >&2
      fi
    fi
    printf '%s\n' "$files" | sed '/^$/d' | while IFS= read -r f; do
      # A file that was untracked at <tree> and is gone now has nothing to stage.
      if git add -A -- "$f" 2>/dev/null; then echo "staged  $f"; else echo "skipped $f (untracked, now deleted)"; fi
    done
    for p in "$@"; do
      [ -e "$p" ] || continue
      if git add -A -- "$p" 2>/dev/null; then echo "staged  $p"; else echo "skipped $p (gitignored)"; fi
    done
    ;;
  lock)
    dir=${1:-}; [ -n "$dir" ] || die "usage: lock <dir> <file>... | lock <dir> --from <file>"; shift
    if [ "${1:-}" = "--from" ]; then
      list=${2:-}; [ -f "$list" ] || die "lock --from: no such file: ${list:-<file>}"
      set --
      while IFS= read -r line || [ -n "$line" ]; do
        if [ -n "$line" ]; then set -- "$@" "$line"; fi
      done < "$list"
    fi
    [ $# -gt 0 ] || die "lock needs at least one file"
    to_top_soft; mkdir -p "$dir"; touch "$dir/spec.lock"
    for f in "$@"; do
      [ -f "$f" ] || die "no such file (paths are repo-root relative): $f"
      # Re-locking a file replaces its entry; other entries stay.
      awk -F'\t' -v p="$f" '$2 != p' "$dir/spec.lock" > "$dir/spec.lock.tmp"
      mv "$dir/spec.lock.tmp" "$dir/spec.lock"
      printf '%s\t%s\n' "$(git hash-object -- "$f")" "$f" >> "$dir/spec.lock"
      mkdir -p "$dir/locked/$(dirname "$f")"; cp -p "$f" "$dir/locked/$f"
    done
    echo "locked $# file(s) in $dir/spec.lock"
    ;;
  check)
    [ $# -gt 0 ] || die "usage: check <dir>..."
    to_top_soft; bad=0; n=0
    for dir in "$@"; do
      [ -f "$dir/spec.lock" ] || continue
      n=$((n + 1))
      while IFS="$TAB" read -r sha f; do
        if [ ! -f "$f" ]; then echo "VANISHED $f  ($dir)"; bad=1
        elif [ "$(git hash-object -- "$f")" != "$sha" ]; then echo "CHANGED  $f  ($dir)"; bad=1; fi
      done < "$dir/spec.lock"
    done
    [ $n -gt 0 ] || die "no spec.lock under: $*"
    if [ $bad -eq 0 ]; then echo "pinned files intact ($n lock(s))"; else exit 1; fi
    ;;
  restore)
    dir=${1:-}; to_top_soft; [ -f "$dir/spec.lock" ] || die "no spec.lock in ${dir:-<dir>}"
    while IFS="$TAB" read -r sha f; do
      if [ ! -f "$f" ] || [ "$(git hash-object -- "$f")" != "$sha" ]; then
        mkdir -p "$(dirname "$f")"; cp -p "$dir/locked/$f" "$f"; echo "restored $f"
      fi
    done < "$dir/spec.lock"
    ;;
  baton)
    to_top; slug=${1:-}; how=${2:-}
    [ -n "$slug" ] && [ -n "$how" ] || die "usage: baton <slug> continue|stop <start> [<line>...] | baton <slug> clear"
    file="$PWD/.claude/handovers/ratchet-$slug.md"
    if [ "$how" = clear ]; then rm -f "$file"; echo "baton cleared"; exit 0; fi
    case "$how" in continue|stop) ;; *) die "baton: expected continue, stop or clear, got $how" ;; esac
    [ -n "${3:-}" ] || die "baton needs <start>"
    mkdir -p "$(dirname "$file")"
    {
      echo "# Handover — ratchet $slug"
      echo "<!-- scope: repo · roots: $PWD · written: $(date -u +%Y-%m-%d-%H%M) -->"
      echo "**Start here:** $3"
      shift 3
      for line in "$@"; do echo "- $line"; done
    } > "$file"
    echo "[ratchet] baton $file $how"
    ;;
  state|gate|prove|red-check|exec|live|metrics|report|decide|retire|trace|config|stelint|doclint)
    py "$@"
    ;;
  *)
    case "$cmd" in
      ''|*[!a-z0-9-]*) ;;
      *) [ ! -f "$HERE/rs/cmd_${cmd//-/_}.py" ] || py "$@" ;;
    esac
    sed -n '/^# ratchet/,/^$/p' "$0" >&2; exit 2
    ;;
esac
