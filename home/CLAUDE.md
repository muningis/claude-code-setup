# Workspace

## Models
- `claude-opus-5[1m]` — planning, orchestration, delegation (main loop; judgment only).
- `claude-sonnet-5` — research, exploration, implementation, review.
- `claude-haiku-4-5` — trivial: lint, tests, static analysis, docs.

## Workflow — cheap to understand → Opus decides once → cheap to verify
1. **Orient.** CLI tools (below) for targeted lookups; ONE Explore agent for broad discovery (conclusions + paths, not dumps); `search` Basic Memory for prior decisions.
2. **Decide once — in Plan Mode.** Sessions boot in Auto Mode; for any non-trivial work, ENTER Plan Mode first (present the plan, get approval) before editing — Opus makes the plan/architecture call from the distilled findings. Only trivial/mechanical work proceeds straight through Auto Mode.
3. **Implement by coupling.** Coupled work + small in-context edits → inline (one-line reason if non-trivial). Self-contained → ONE sub-agent, cheaper `model:` (`sonnet`; `haiku` trivial). Parallel independent edits → a team, each `isolation: worktree`. Downgrade workers; prefer one (multi-agent ≈15× tokens). Every delegation states objective, output, tools, boundaries, and a done-condition.
4. **Verify once.** `/rinse:rinse` at the end — once, not per-edit; trust a worker's green report. Keep it on the main loop: its manual checks have to reach you. Quality-critical → a Sonnet reviewer with concrete criteria.
5. **Persist.** Decisions/conventions/gotchas → Basic Memory (`write_note`); keep this file and `MEMORY.md` thin.

Orchestration/config edits (this file, `.claude/**`, plans, memory) are always Opus's own, inline.

## CLI tools (via Bash — prefer over MCP servers or subagents for local, targeted work)
- **`rg` / `find`** — text/file search; first reach for any lookup.
- **`ast-grep`** — structural (AST) search & rewrite; code-shaped queries where regex is fragile.
- **`yq`** — edit YAML/JSON/TOML/XML without breaking formatting.
- **`gron`** — flatten JSON to greppable lines when the schema is unknown.
- **`tokei`** — LOC-by-language repo overview for orientation.
- **`shellcheck`** — lint generated shell before running it.
- **`gitleaks`** — scan for secrets before commit/PR.
- **`semgrep --config auto`** — multi-language static-analysis sweep after edits.
- **`typos`** — code-aware spell check before PR.

## Core rules
1. Comment only the non-obvious "why", matching the file's density — never restate code.
2. Red-Green: failing test first, implement to green; verify with real tooling (browser/curl/CLI), not only unit tests.
3. Research on demand — findings go to Basic Memory, never back into always-loaded files.
