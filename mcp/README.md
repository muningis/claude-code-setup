# On-demand knowledge & docs for coding agents

Two MCP servers, registered at user scope by [`../setup.sh`](../setup.sh), that a
coding agent queries **on demand** instead of front-loading everything into
always-loaded files:

- **Basic Memory** — my own decisions/conventions/gotchas (local, plain-markdown).
- **Context7** — up-to-date, version-correct docs for external libraries/frameworks.

## Why this exists

Every agent session starts with a fresh context window. The usual fix — stuff more
into `CLAUDE.md` and auto-memory — backfires: those files load **in full, every
session**, so knowledge you rarely need still costs tokens every time. Instead,
knowledge lives in MCP servers the model calls only when it needs them:

- **No always-loaded bloat** — queried on demand, not injected at launch.
- **Not siloed to one tool** — the same servers work in any harness (see below).

## Basic Memory — my knowledge

Decisions, conventions, gotchas — the externalized, queryable replacement for "dump
architecture notes into CLAUDE.md." Stores everything as **plain Markdown**
(frontmatter + `[category]` observations + `[[wikilink]]` relations), indexed in
local SQLite with FastEmbed for semantic search. Human-editable,
Obsidian-compatible, git-versionable. Fully local — no API keys, nothing leaves the
machine.

MCP tools: `write_note`, `read_note`, `edit_note`, `move_note`, `delete_note`,
`search` / `search_notes`, `build_context` (walks the wikilink graph),
`list_memory_projects`.

```
write_note(title="edge cache decision", folder="decisions", content="""
- [decision] Cloudflare edge-caches the marketing site HTML
- [ops] CMS purge on publish
relates to [[deploy pipeline]]
""")
search("edge cache")
build_context("memory://decisions/edge-cache-decision")
```

## Context7 — external library docs

Fetches current, version-specific documentation for libraries and frameworks so the
agent stops guessing against stale training data. Run via
`npx -y @upstash/context7-mcp` (a hosted service — not local). Keyless works but is
rate-limited; set `CONTEXT7_API_KEY` (or pass `--api-key`) for higher limits — get
one at <https://context7.com>.

MCP tools: `resolve-library-id` (library name → Context7 ID), then
`query-docs` / `get-library-docs` (fetch docs for that ID).

> In Claude Code this is registered as a **standalone MCP server**, not the
> `context7` plugin — the plugin is disabled to avoid duplicate tools.

## Harness-agnostic wiring

`setup.sh` uses `claude mcp add`, which writes to `~/.claude.json` — but **only
Claude Code reads that**. To reuse the identical servers from Cursor, Codex,
Windsurf, or any harness that reads MCP config, paste this block:

```json
{
  "mcpServers": {
    "basic-memory": { "command": "uvx", "args": ["basic-memory", "mcp"] },
    "context7": { "command": "npx", "args": ["-y", "@upstash/context7-mcp"] }
  }
}
```

Add `"env": { "CONTEXT7_API_KEY": "…" }` to the context7 block for higher limits.

## How this changes CLAUDE.md

`CLAUDE.md` no longer accumulates findings — it keeps only workflow/model/rules and a
pointer: persist decisions into Basic Memory (`write_note`), retrieve with `search` /
`build_context`, never back into always-loaded files.

## Bootstrap

Run the repo-root [`setup.sh`](../setup.sh) — it installs the CLI tools and registers
both MCP servers (idempotent; mutates `~/.claude.json`, no Docker). Review it first.
