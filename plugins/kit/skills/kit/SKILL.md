---
name: kit
description: >-
  Kit out a repository with language-server (LSP) support: detect the languages it
  actually uses, install the matching language servers, and enable the LSP plugins
  in the repo's own .claude/settings.json. Use when setting up LSP for a project,
  "enable LSP here", "add a language server", "turn on code intelligence", or
  onboarding a repo to code navigation. Not for editing global ~/.claude config —
  that is the workspace setup.sh.
---

# Kit

Give a repo working code intelligence in one pass: find its languages, get the
servers installed, and switch on the LSP plugins scoped to that repo — nothing
global, nothing you hand-edit.

Optional `$ARGUMENTS`: language names to force the set (`kit rust python`),
`--local` to write the gitignored settings file instead of the committed one.

## 1 — Detect the languages that actually matter

From the repo root, read-only. Weight real source over stray files:

```bash
tokei 2>/dev/null | head -40           # LOC by language — the primary signal
ls package.json tsconfig.json pyproject.toml Cargo.toml go.mod \
   build.gradle.kts Package.swift 2>/dev/null   # manifests confirm intent
```

A language counts when it has a manifest or a real share of the LOC — not one
stray `.py` script in a TS repo. In a monorepo or when the signal is mixed, list
what you found and confirm the set with one AskUserQuestion before touching
anything. THIS judgment is why kit is a skill and not just a script.

## 2 — Map each language to its official LSP plugin

| Language | Signals | Plugin (`@claude-plugins-official`) | Server binary | Install |
| --- | --- | --- | --- | --- |
| TypeScript / JS | `tsconfig.json`, `package.json`, `.ts/.tsx` | `typescript-lsp` | `typescript-language-server` | `npm i -g typescript-language-server typescript` |
| Python | `pyproject.toml`, `.py` | `pyright-lsp` | `pyright` | `npm i -g pyright` (or `pip install pyright`) |
| Rust | `Cargo.toml` | `rust-analyzer-lsp` | `rust-analyzer` | `rustup component add rust-analyzer` |
| Kotlin | `build.gradle.kts`, `.kt` | `kotlin-lsp` | (bundled) | see the plugin's README |
| Swift | `Package.swift` | `swift-lsp` | `sourcekit-lsp` | ships with the Swift toolchain |

Plugin availability changes, so confirm the id exists before enabling — never
invent one:

```bash
claude plugin marketplace list 2>/dev/null | grep -i lsp || true
```

If a detected language has no official LSP plugin, say so and skip it.

## 3 — Ensure the server, then enable the plugin

For each confirmed language:

1. **Probe the binary.** If `command -v <server>` finds it, skip install.
2. **Install if missing.** Run the table's install command. It mutates global
   npm/pip/rustup state, so confirm once before running; if it fails (a
   toolchain-bound server like SourceKit-LSP), print the manual step rather than
   fighting it.
3. **Enable the plugin — always via `kit.sh`, never by editing settings.json by
   hand.** It does the one thing that must be exact: merge `enabledPlugins` into
   the repo's settings without clobbering any other key, atomically.

```bash
"$CLAUDE_PLUGIN_ROOT/kit.sh" typescript-lsp@claude-plugins-official \
  --probe typescript-language-server
# add --local to target .claude/settings.local.json (gitignored) instead
```

`kit.sh` is agent-invoked only — the user never runs it. Its `--probe` line tells
you whether the server is on PATH so you can install before reporting success.

## 4 — Report

Per language: server installed or already present, plugin enabled or already on,
and which file was written. Then the one caveat kit can't automate:

> A committed `.claude/settings.json` starts servers only after you **trust the
> workspace** — reopen the repo and accept the trust prompt.

If you wrote the committed `.claude/settings.json`, note it's a team-shared change
worth a commit; `--local` keeps it to this machine.

## Not this

- Global `~/.claude` config, MCP servers, CLI tools → the workspace `setup.sh`.
- Verifying a change you just made → `rinse`.
