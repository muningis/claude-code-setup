# claude-code-setup

My personal Claude Code configuration.

## Models & workflow

Three-tier model split (see [`home/CLAUDE.md`](./home/CLAUDE.md) for the full
workflow contract):

| Model | Role |
| --- | --- |
| `claude-opus-4-8[1m]` | Planning, orchestration, task delegation — the main loop |
| `claude-sonnet-4-6` | Research, code exploration, implementation, review |
| `claude-haiku-4-5` | Trivial tasks — lint, tests, static analysis, docs |

Guiding principle: **cheap-and-parallel to understand → concentrate Opus once →
cheap to verify.** Spend Opus on judgment, not on discovery or mechanics. Default
effort is `high` (`~/.claude/settings.json`), always-thinking is on.

## Layout

```
setup.sh               # idempotent bootstrap — CLI tools, the Basic Memory & Context7 MCP servers, and the ~/.claude sync
home/                  # source for ~/.claude — deliberately not named .claude, or it
                       # would also load as THIS repo's project config, on top of the
                       # user config it's meant to be the source of
  settings.json        # model, plugins, statusline, notif channel, hooks, effort, auto-mode
  CLAUDE.md            # global workflow contract Opus follows
  statusline.sh        # custom 3-line status line (dir/branch · model/effort · ctx/cost/limits)
  hooks/
    notify.sh          # native macOS notifications (see below)
.claude-plugin/        # this repo IS a plugin marketplace (name: skillz)
  marketplace.json     # manifest listing the plugins below
plugins/               # vendored Claude Code plugins (skills)
  snare/ sniff/ trail/ recap/ rinse/ scruff/ kit/ baton/ ratchet/ den/
mcp/                   # on-demand knowledge/docs MCP servers (Basic Memory, Context7)
  README.md            # rationale, per-server usage, portable config for other harnesses
setup.md               # maintenance & cleanup runbook (every removal is gated by a question)
```

The single source of truth is `~/.claude/settings.json`: model (`opus[1m]`),
statusline, enabled plugins + marketplaces, notif channel (`iterm2`), fullscreen
TUI, `effortLevel: high`, `advisorModel: opus`, agent-teams env flag,
`teammateMode: auto`, `disableArtifact`, `autoUpdatesChannel: stable`, auto-mode
soft-denies (`$defaults` + never run `terraform apply`), and the notification
hooks. Cross-session decisions/gotchas live in the auto-memory at
`~/.claude/projects/-Users-muningis-workspace/memory/` (one fact per file + a
`MEMORY.md` index) — not versioned here (machine/private state).

## CLI tools

The agent reaches for a handful of local CLIs (installed by `setup.sh`, invoked
via Bash — no MCP, no daemon, no index):

- **`ast-grep`** — structural (AST) code search & rewrite across 20+ languages.
  The tier above `rg` for code-shaped queries (call sites, a syntax pattern) where
  regex is fragile — the "beyond grep" structural search tier.
- **`shellcheck`** — lints the shell the agent generates (hooks, one-off commands)
  before it runs — cheap insurance against a destructive command.
- **`yq`** — edits YAML/JSON/TOML/XML (k8s manifests, compose, CI workflows)
  without wrecking formatting.
- **`gitleaks`** — scans the working tree + git history for secrets; a pre-PR
  safety gate (matters since I version config/hooks).
- **`semgrep`** — multi-language static analysis (`--config auto`) as a post-edit
  security/antipattern sweep — reaches past `shellcheck` into TS/JS/Python/Go/Terraform.
- **`tokei`** — instant LOC-by-language repo overview for orientation.
- **`gron`** — flattens JSON to greppable `a.b.c = v;` lines, so I grep an unknown
  schema instead of guessing jq paths.
- **`typos`** — code-aware spell check (`typos-cli`), a cheap pre-PR catch.

## Context / knowledge tooling (MCP)

Both are registered at user scope by `setup.sh` (`claude mcp add`):

- **Basic Memory** — the live decisions/conventions/gotchas store (local,
  plain-markdown). Persist with `write_note`, retrieve with `search` /
  `build_context`. Code search uses `grep`/`rg`/`find` + `ast-grep` + Explore agents.
- **Context7** — up-to-date, version-correct docs for external libraries/frameworks
  (`resolve-library-id` → `query-docs`). Registered as a standalone server, not the
  `context7` plugin (disabled to avoid duplicate tools); keyless free tier, optional
  `CONTEXT7_API_KEY` for higher limits.
- Chrome automation, Figma, and Slack MCP servers are available on demand.

See [`mcp/README.md`](./mcp/README.md) for the rationale (why knowledge lives in
on-demand MCP servers instead of always-loaded files), per-server usage, and a
portable config block for other harnesses.

## Plugins (marketplace)

This repo doubles as the `skillz` plugin marketplace, consolidated from the former
standalone `muningis/skillz` repo. `.claude-plugin/marketplace.json` lists the
plugins under `plugins/`:

- **snare** — reproduction-driven red→green bugfix loop.
- **sniff** — pull a real error from an app/service's logs into a repro recipe.
- **trail** — decision archaeology: reconstruct *why* code is the way it is.
- **recap** — cross-session standup of what you actually drove.
- **rinse** — verification loop for finished work: run the repo's checks, fix, re-run the whole set, then hand you what only a human can confirm.
- **baton** — pass a session on, in two skills: `/baton:handover` writes what the
  next session needs (mission, observed git state, decisions and rejected
  alternatives, dead ends, ordered next steps) for a single repo, a multi-repo
  workspace, or an exploration workspace; `/baton:resume` reads one back, re-checks
  it against the repos as they are now, and leads with what has drifted since.
- **ratchet** — Helix-style checkpoint workflow: plan a feature as small checkpoints, then push each through pinned red-first tests, a visual diff, two blind adversarial reviewers and your approval before the next starts (`/ratchet plan <goal>`; user-invoked).
- **den** — a mod (function hooks): pixel-art raccoons act out Claude and its subagents in a docked pane, and go full frenzy during ratchet runs (`/den demo`).
- **scruff** — mentor mode: briefs you to build it yourself, then grills what you built (with proof).
- **kit** — kit out a repo with code intelligence: detect its languages, install the language servers, and enable the LSP plugins in that repo's own `.claude/settings.json`.
  - *Why:* the enabled LSP lets Claude navigate by symbol — go-to-definition, find-references, type-on-hover — which is more precise and cheaper in tokens than reading whole files to answer a symbol-level question. It's the symbol layer; for plain text and non-code files, `rg` still wins.

Enabled via `<plugin>@skillz` in `~/.claude/settings.json` (`enabledPlugins`);
`extraKnownMarketplaces.skillz` points at this repo. The plugins are consumed as a
marketplace, not copied — point Claude Code at the repo and enable what you want.

## Notifications

Because I run 3–4 sessions at once, each session pings a native macOS banner (with
sound) when it needs me — so I know *which* one and *why* without watching.

- **Script:** `home/hooks/notify.sh` — reads the hook JSON on stdin, titles the
  banner with the project folder name (`basename $cwd`), and plays a distinct sound
  per event. Uses the absolute `$HOME/.claude/hooks/notify.sh` path since it's a
  global hook running from any project's cwd. Always `exit 0`s and never blocks a
  session; `osascript` is the delivery mechanism (no `terminal-notifier` needed).
- **Wired in** `~/.claude/settings.json` (global → fires for every project) via two
  hooks:
  - `Stop` → **✅ `<project>` — done**, sound `Glass`, body = the assistant's final
    line (`.assistant_message`, truncated). `Stop` fires at *every* turn end, so the
    script **suppresses the ping when `background_tasks` or `session_crons` is
    non-empty** — otherwise a background subagent finishing would falsely report the
    main work as "done." Needs Claude Code ≥ 2.1.145 (these payload fields).
  - `Notification` → **🔔 `<project>` — needs you**, sound `Funk`, body = the
    notification `message`. Matched to
    `permission_prompt|agent_needs_input|elicitation_dialog` only — events that
    genuinely block on you. `idle_prompt` is deliberately **excluded**: it means
    "done, waiting for your next prompt," not "needs action," and firing on it
    produced false "needs attention" alerts.
- **Debug log:** each invocation appends a compact JSON line (event,
  notification_type, bg/cron counts, project) to `~/.claude/hooks/notify.log`,
  guarded by `NOTIFY_DEBUG` (default on); remove the block in `notify.sh` once
  behavior is confirmed.

**Test a hook manually:**
```bash
# genuine finish (banner):
printf '{"hook_event_name":"Stop","cwd":"'"$PWD"'","assistant_message":"all green","background_tasks":[],"session_crons":[]}' \
  | bash "$HOME/.claude/hooks/notify.sh"
# background work still running (silent):
printf '{"hook_event_name":"Stop","cwd":"'"$PWD"'","background_tasks":[{"status":"running"}]}' \
  | bash "$HOME/.claude/hooks/notify.sh"
```

## Statusline

`~/.claude/statusline.sh` (`bash`) renders the custom 3-line status line
(dir/branch · model/effort · ctx/cost/limits).

## Restore / install

```bash
bash setup.sh            # review it first — brew-installs the CLI tools, installs Basic Memory,
                         # edits ~/.claude.json, and links ~/.claude to home/

bash setup.sh --sync-only  # just re-link ~/.claude, skipping brew and MCP
```

`CLAUDE.md`, `statusline.sh` and `hooks/notify.sh` are **symlinked** into this repo,
so editing either path edits the same file and the two can't drift. Anything already
at those paths is renamed to `*.bak.<timestamp>` first, never deleted.

`settings.json` is **copied**, not linked — Claude Code rewrites it whenever you
switch model or effort or toggle a plugin, which would otherwise dirty the repo
constantly. So it can drift: if the live file differs, setup.sh reports it and
prints the copy command for whichever direction you want, rather than overwriting.

Only `hooks/notify.sh` is linked, not the whole `hooks/` directory — the hook
appends to `~/.claude/hooks/notify.log` at runtime, which must not land in the repo.

Then restart any running Claude Code sessions to pick up the new config.

> Not included here: the per-conversation auto-memory
> (`~/.claude/projects/**/memory/`) and `~/.claude.json` (MCP registrations /
> tokens) — those are machine/private state, not portable setup.
</content>
