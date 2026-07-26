# kit

One pass to give a repository working code intelligence: detect the languages it
actually uses, install the matching language servers, and enable the LSP plugins
in that repo's own `.claude/settings.json`.

The rule: **LSP is a per-repo fact, not a global one.** "This is a Rust project"
belongs in the Rust project's config, enabled there and nowhere else — so kit
writes to the repo in front of it and leaves your global `~/.claude` alone.

1. **Detect** — languages by LOC (`tokei`) and manifests (`Cargo.toml`,
   `tsconfig.json`, …); ambiguous sets are confirmed with you, not guessed.
2. **Map** — each language to its official `@claude-plugins-official` LSP plugin
   and server binary; a language with no official plugin is skipped, not invented.
3. **Ensure the server** — probe for the binary, install it only if missing, only
   with your ok.
4. **Enable the plugin** — merged into the repo's `.claude/settings.json` without
   clobbering any other key, atomically.

Project scope beats your global config, so kit turning a plugin **on** here
overrides it being **off** in `~/.claude/settings.json` — for this repo only.

## Skill

- `skills/kit/SKILL.md` — invokable as `/kit:kit`.
- `kit.sh` — the deterministic settings-merge primitive. **Agent-invoked only**;
  you never run it. The skill detects and adjudicates, then calls `kit.sh` for the
  one step that must be exact.

## Install

Add the parent `skillz` marketplace, then enable the `kit` plugin:

```
/plugin marketplace add muningis/skillz
/plugin install kit@skillz
```

## Using it

Open a repo and ask — *"enable LSP here"*, *"set up language servers"*, or
`/kit:kit`. kit detects the languages, installs what's missing, and enables the
plugins scoped to that repo.

- `--local` — write the gitignored `.claude/settings.local.json` (just your
  machine) instead of the committed `.claude/settings.json` (the whole team).
- `kit rust python` — force the language set instead of detecting it.

## Two caveats it surfaces but can't automate

- **Server binaries live outside Claude.** The plugin wires up the connection; the
  language server itself has to be on `PATH`. kit installs the common ones on your
  ok and prints the manual step for toolchain-bound ones (SourceKit-LSP, Kotlin).
- **A committed config needs trust.** A `.claude/settings.json` checked into the
  repo starts servers only after you trust the workspace — reopen and accept.

## Not this

- Global `~/.claude` config, MCP servers, CLI tools → the workspace `setup.sh`.
- Verifying a change you just made → `rinse`.
