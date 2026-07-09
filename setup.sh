#!/usr/bin/env bash
# Bootstrap the tooling this Claude Code setup relies on: local CLI tools the agent
# drives via Bash, plus the Basic Memory and Context7 MCP servers.
# Idempotent — safe to re-run. Review before running: it installs Homebrew formulae,
# a uv tool, and mutates your global Claude Code MCP config (~/.claude.json).
set -euo pipefail

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

echo
echo "==> Done. Verify:"
echo "    ast-grep --version && shellcheck --version && yq --version"
echo "    claude mcp list        # basic-memory + context7 should be connected/green"
