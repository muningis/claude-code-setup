# setup.md — maintenance & cleanup runbook

Periodic hygiene for this Claude Code setup. Follow this whenever asked to
"clean up", "purge", "tidy", or "prune" the setup.

## ⛔ Golden rule — confirm every removal

**Nothing here is auto-delete.** For EVERY purge / removal / overwrite / migration
candidate, STOP and use **AskUserQuestion** to confirm before acting. Show:
what you found, why it's a candidate, and the exact effect of removing it.

- Ask **per removal** — one decision per item. Batch only tightly-related items
  into a single question, and even then list each item explicitly.
- Never delete, overwrite, or migrate on assumption or "it looked stale".
- Explicit user-requested edits are exempt from the gate; **discovery-driven
  cleanup is always gated.**
- Prefer reversible moves (archive / migrate) over hard delete; offer them as options.

## What to check

### 1. Memory hygiene
- **Stale / contradictory notes** in the file auto-memory
  (`~/.claude/projects/*/memory/*.md`) and its `MEMORY.md` index — notes that
  reference a tool, decision, or status that has since changed (e.g. a store
  marked "unverified" that is now live, or advice that contradicts current
  `CLAUDE.md`). → Ask before editing or removing each.
- **Completed project notes** — gotchas for work already shipped/deployed.
  → Ask whether to archive, migrate to Basic Memory, or delete.
- **Duplication** between the file auto-memory and Basic Memory (the live
  decisions store). The goal is ONE store. → Ask before migrating a note into
  Basic Memory and removing the file copy.
- **Basic Memory config** — confirm a project exists and points where you want
  notes versioned (`list_memory_projects`). An empty or mis-pointed store is a
  silent blocker to fix, never something to delete.

### 2. Parked / disabled / removed tooling references
- Search `CLAUDE.md`, `MEMORY.md`, memory notes, and repo docs for references to
  tooling that has been parked, disabled, or removed. → Ask before stripping
  each reference.

### 3. Debug / temporary code
- `~/.claude/hooks/notify.sh` `NOTIFY_DEBUG` block + `~/.claude/hooks/notify.log`
  — meant to be removed once notification behavior is trusted.
  → Ask before removing.

### 4. Backup / superseded files
- `~/.claude/*.bak` (e.g. `settings.json.bak`) and any local scratch/source
  directories whose content is now captured in this repo.
  → Ask before deleting each.

### 5. Config drift
- `CLAUDE.md`, `statusline.sh` and `hooks/notify.sh` are symlinks into this repo's
  `home/`, so they cannot drift — verify with `ls -l ~/.claude`. Only
  `settings.json` is copied and can diverge: `bash setup.sh --sync-only` reports
  the difference without overwriting. Re-sync by **copying, not deleting**; if the
  live config changed intentionally, update `home/settings.json` and commit.

## After any confirmed cleanup
- Re-sync affected config into this repo and commit.
- Keep always-loaded files (`CLAUDE.md`, `MEMORY.md`) thin — a pointer, not a store.
