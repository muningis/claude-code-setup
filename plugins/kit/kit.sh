#!/usr/bin/env bash
# kit — enable a Claude Code LSP (or any) plugin in THIS repo's settings, safely.
#
# Agent-invoked by the `kit` skill; not meant to be run by hand. Deciding WHICH
# languages/plugins a repo needs is the skill's job — kit.sh only performs the one
# operation that must be deterministic: merging enabledPlugins into the repo's
# settings file without clobbering any other key in it.
#
# Usage (from the target repo root):
#   kit.sh <plugin-id> [--local] [--probe <binary>]
#
#   <plugin-id>   e.g. typescript-lsp@claude-plugins-official
#   --local       write .claude/settings.local.json (gitignored) instead of the
#                 committed .claude/settings.json
#   --probe BIN   also report whether the language-server binary BIN is on PATH
set -euo pipefail

plugin=""
scope="project"
probe=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --local) scope="local"; shift ;;
    --probe) probe="${2:?kit: --probe needs a binary name}"; shift 2 ;;
    -*)      echo "kit: unknown flag $1" >&2; exit 2 ;;
    *)       [[ -z "$plugin" ]] || { echo "kit: unexpected arg $1" >&2; exit 2; }
             plugin="$1"; shift ;;
  esac
done

[[ -n "$plugin" ]] || { echo "kit: missing <plugin-id>" >&2; exit 2; }
command -v jq >/dev/null 2>&1 || { echo "kit: jq is required" >&2; exit 1; }

file=".claude/settings.json"
[[ "$scope" == "local" ]] && file=".claude/settings.local.json"

mkdir -p .claude
[[ -f "$file" ]] || echo '{}' >"$file"
jq empty "$file" 2>/dev/null || {
  echo "kit: $file is not valid JSON — refusing to touch it" >&2; exit 1
}

# Never-clobber, atomic: only enabledPlugins[<plugin>] is set; every other key
# (schema, model, hooks, other plugins) is preserved exactly.
before="$(jq -r --arg p "$plugin" '.enabledPlugins[$p] // "absent"' "$file")"
tmp="$(mktemp)"
jq --arg p "$plugin" '.enabledPlugins[$p] = true' "$file" >"$tmp" && mv "$tmp" "$file"

case "$before" in
  true)  echo "kit: $plugin already enabled in $file (no change)" ;;
  false) echo "kit: $plugin was disabled — flipped to enabled in $file" ;;
  *)     echo "kit: enabled $plugin in $file" ;;
esac

if [[ -n "$probe" ]]; then
  if command -v "$probe" >/dev/null 2>&1; then
    echo "kit: server binary '$probe' found at $(command -v "$probe")"
  else
    echo "kit: server binary '$probe' NOT on PATH — install it before LSP will work"
  fi
fi

if [[ "$scope" == "project" ]]; then
  echo "kit: note — a committed settings.json starts servers only after the workspace is trusted"
fi
