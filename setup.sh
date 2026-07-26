#!/usr/bin/env bash
# Bootstrap the tooling this Claude Code setup relies on: local CLI tools the agent
# drives via Bash, the Basic Memory and Context7 MCP servers, and the ~/.claude
# config itself (linked from home/).
# Idempotent — safe to re-run. Review before running: it installs Homebrew formulae,
# a uv tool, and mutates your global Claude Code MCP config (~/.claude.json).
#
# Usage:
#   ./setup.sh              full bootstrap
#   ./setup.sh --sync-only  just re-link ~/.claude from home/, skipping brew and MCP
set -euo pipefail

SYNC_ONLY=false
[[ "${1:-}" == "--sync-only" ]] && SYNC_ONLY=true

if [[ "$SYNC_ONLY" == false ]]; then

echo "==> CLI tools (Homebrew)"
# All invoked by the agent via Bash — no MCP, no daemon, no index:
#   - ast-grep    structural (AST) code search & rewrite across 20+ languages — beats regex for code-shaped queries
#   - shellcheck  lint the shell the agent generates (hooks, one-off commands) before it runs
#   - yq          edit YAML/JSON/TOML/XML (k8s manifests, compose, workflows) without wrecking formatting
#   - gitleaks    scan working tree + git history for secrets — pre-PR safety gate (--report-format json)
#   - semgrep     multi-language static analysis (--config auto) — post-edit security/antipattern sweep beyond shellcheck
#   - tokei       instant LOC-by-language repo overview — orientation before exploring
#   - gron        flatten JSON to greppable a.b.c=v lines — grep an unknown schema instead of guessing jq paths
#   - typos-cli   code-aware spell check (typos --format json) — cheap pre-PR catch on identifiers/strings/comments
command -v brew >/dev/null 2>&1 || { echo "MISSING: brew (Homebrew) — install from https://brew.sh"; exit 1; }
brew install ast-grep shellcheck yq gitleaks semgrep tokei gron typos-cli

echo "==> MCP servers (registered at user scope in ~/.claude.json)"
for bin in uvx npx claude; do
  command -v "$bin" >/dev/null 2>&1 || { echo "MISSING: $bin — install it first."; exit 1; }
done

# Basic Memory — local plain-markdown knowledge store + semantic search (no cloud,
# no Docker; embedding models auto-download on first use, cached locally).
uv tool install basic-memory || true   # uvx fetches on demand even if this is skipped
claude mcp list 2>/dev/null | grep -q '^basic-memory:' \
  || claude mcp add --scope user basic-memory -- uvx basic-memory mcp

# Context7 — up-to-date library/framework docs (Upstash cloud service, run via npx).
# Registered standalone (not the context7 plugin) so it's harness-agnostic. Keyless
# works but is rate-limited; for higher limits append `--api-key <KEY>` below or
# export CONTEXT7_API_KEY (get one at https://context7.com).
claude mcp list 2>/dev/null | grep -q '^context7:' \
  || claude mcp add --scope user context7 -- npx -y @upstash/context7-mcp

fi  # end of full-bootstrap section

echo "==> ~/.claude config (from home/)"
# home/ is deliberately NOT named .claude: a .claude directory here would be loaded
# as this repo's *project* config on top of the user config it's meant to be the
# source of — CLAUDE.md would load twice, and settings.json would shadow itself.
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC="$REPO_DIR/home"
DEST="$HOME/.claude"
mkdir -p "$DEST/hooks"

# Files you author are symlinked, so editing either path edits the same file and the
# repo can never drift from the live config.
T='~'
link() {
  local src="$1" dst="$2" short="${2/#$HOME/$T}"
  if [[ -L "$dst" && "$(readlink "$dst")" == "$src" ]]; then
    echo "    ok    $short"
    return
  fi
  if [[ -e "$dst" || -L "$dst" ]]; then
    mv "$dst" "$dst.bak.$(date +%Y%m%d%H%M%S)"
    echo "    saved $short.bak.*"
  fi
  ln -s "$src" "$dst"
  echo "    link  $short -> $src"
}

link "$SRC/CLAUDE.md"       "$DEST/CLAUDE.md"
link "$SRC/statusline.sh"   "$DEST/statusline.sh"
# notify.sh is linked individually, not the whole hooks/ dir: the hook appends to
# ~/.claude/hooks/notify.log at runtime, which must not land inside the repo.
link "$SRC/hooks/notify.sh" "$DEST/hooks/notify.sh"

chmod +x "$SRC/statusline.sh" "$SRC/hooks/notify.sh"

# settings.json is copied, never linked: Claude Code rewrites it whenever you switch
# model or effort or toggle a plugin, so a symlink would dirty the repo constantly.
# That means it CAN drift — so never clobber a newer live file, just report it.
if [[ ! -f "$DEST/settings.json" ]]; then
  cp "$SRC/settings.json" "$DEST/settings.json"
  echo "    copy  ~/.claude/settings.json"
elif diff -q <(jq -S . "$SRC/settings.json") <(jq -S . "$DEST/settings.json") >/dev/null 2>&1; then
  echo "    ok    ~/.claude/settings.json"
else
  echo "    WARN  ~/.claude/settings.json differs from home/settings.json — NOT overwritten."
  echo "          diff:      diff <(jq -S . $SRC/settings.json) <(jq -S . $DEST/settings.json)"
  echo "          adopt live: cp $DEST/settings.json $SRC/settings.json"
  echo "          push repo:  cp $SRC/settings.json $DEST/settings.json"
fi

echo
echo "==> Done. Verify:"
if [[ "$SYNC_ONLY" == false ]]; then
  echo "    ast-grep --version && shellcheck --version && yq --version"
  echo "    claude mcp list        # basic-memory + context7 should be connected/green"
fi
echo "    ls -l ~/.claude/CLAUDE.md ~/.claude/statusline.sh ~/.claude/hooks/notify.sh   # all symlinks into this repo"
