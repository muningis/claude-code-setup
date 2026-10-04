#!/bin/bash
#
# Nightly dream. For each repo that opted in (dream.nightly), harvest the new evidence, let a
# headless claude reflect on it, and curate the result into a proposal. It never commits,
# never pushes, and never applies a change: the human approves each item later.
# bash 3.2-compatible (macOS /bin/bash). `ratchet.sh dream install` runs it from launchd at 03:30.
#
#   RATCHET_HOME           replaces ~ (tests)
#   RATCHET_CLAUDE         the claude binary; tests use a fake one
#   RATCHET_DREAM_TIMEOUT  seconds before a reflection is stopped (default 1800)
#   RS_PYTHON              the python3 that ratchet.sh runs

set -u

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RS="$HERE/ratchet.sh"
CLAUDE=${RATCHET_CLAUDE:-claude}
TIMEOUT=${RATCHET_DREAM_TIMEOUT:-1800}
failed=0

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# One field of the one-line JSON object that an RS command prints.
json_str() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; }
json_num() { sed -n "s/.*\"$1\":\([0-9][0-9]*\).*/\1/p"; }

# Run one RS command in the current repo. Sets $status, and $last to the final line of its output.
rs_step() {
  local out
  out=$(bash "$RS" "$@" 2>&1)
  status=$?
  last=$(printf '%s\n' "$out" | tail -n 1)
}

dream_repo() {
  local repo=$1 budget=$2 state=$3
  local status last new bundle model prompt_file bdir claude_status items note=""

  case "$state" in
    due) ;;
    recent) log "$repo: skipped, the last dream is under 20 h old"; return 0 ;;
    pending) log "$repo: skipped, a proposal waits for review"; return 0 ;;
    *) log "$repo: skipped, $state"; return 0 ;;
  esac
  if ! cd "$repo"; then
    log "$repo: error, cannot enter the repo"; failed=1; return 0
  fi

  rs_step dream harvest
  if [ "$status" -ne 0 ]; then
    log "$repo: error, harvest failed: $(printf '%s' "$last" | cut -c1-160)"; failed=1; return 0
  fi
  new=$(printf '%s\n' "$last" | json_num new)
  if [ "${new:-0}" -eq 0 ]; then
    log "$repo: nothing new"; return 0
  fi
  bundle=$(printf '%s\n' "$last" | json_str bundle)
  bdir=".claude/ratchet/dreams/$bundle"

  rs_step dream prompt "$bundle"
  if [ "$status" -ne 0 ]; then
    log "$repo: error, no prompt: $(printf '%s' "$last" | cut -c1-160)"; failed=1; return 0
  fi
  model=$(printf '%s\n' "$last" | json_str model)
  prompt_file=$(printf '%s\n' "$last" | json_str evidence)

  # The prompt comes first because --allowedTools takes a list and would swallow a later argument.
  # RS exec stops a hung run, which would otherwise block this repo and every later night.
  bash "$RS" exec --timeout "$TIMEOUT" -- "$CLAUDE" -p "$(cat "$prompt_file")" \
    --model "${model:-sonnet}" --max-budget-usd "$budget" --allowedTools "Read Write" \
    >"$bdir/reflect.log" 2>&1
  claude_status=$?

  # Curate takes candidates.json, or the answer in reflect.log when the headless run could not write the file.
  rs_step dream curate "$bundle"
  if [ "$status" -ne 0 ]; then
    log "$repo: error, curate failed (claude exit $claude_status, see $bdir/reflect.log): $(printf '%s' "$last" | cut -c1-120)"
    failed=1; return 0
  fi
  [ "$claude_status" -eq 0 ] || note=" (claude exit $claude_status)"
  items=$(printf '%s\n' "$last" | json_num items)
  log "$repo: proposed ${items:-0} item(s) in dream $bundle$note"
}

if ! repos=$(bash "$RS" dream repos 2>/dev/null); then
  log "error, cannot read the repo list: run 'ratchet.sh dream repos' by hand to see why"
  exit 1
fi
if [ -z "$repos" ]; then
  log "no repo has dream.nightly set"
  exit 0
fi

while IFS=$'\t' read -r repo budget state; do
  [ -n "$repo" ] || continue
  dream_repo "$repo" "$budget" "$state" </dev/null
done <<EOF
$repos
EOF

exit "$failed"
