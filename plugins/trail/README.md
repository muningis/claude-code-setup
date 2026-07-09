# trail

Decision archaeology for Claude Code.

`trail` reconstructs **why** a piece of code is the way it is — not just what it
does — by following its trail through two sources:

- **git** — *what* changed and *when* (commits, line-history, blame). Authoritative
  on facts, thin on reasoning.
- **session transcripts** (`~/.claude/projects`) — *why*: the prompt that asked for
  it, the rationale, and **the alternatives that were weighed and rejected** — the
  part a commit message never captures.

The skill weaves both into one chronological narrative: how the code got here, the
roads not taken, and what to keep in mind before changing it.

## How it works

- `skills/trail/SKILL.md` — invokable as `/trail:trail`. Orchestrates the git
  commands and the transcript miner, then synthesizes the timeline.
- `skills/trail/scripts/trail.py` — mines the transcripts. Given query tokens, it
  finds the sessions that touched the target and pulls the relevant turns (human
  asks, assistant reasoning, edits/commands), in chronological order:

  ```
  python3 skills/trail/scripts/trail.py "problem+json" --cwd /path/to/repo
  python3 skills/trail/scripts/trail.py PGlite tests --all-projects --since 90d
  ```

  Flags: `--cwd PATH` (scope to a repo) / `--all-projects` (default, search all),
  `--since Nd|Nh|Nw|ISO`, `--max-sessions N`, `--max-hits N`, `--context CHARS`.

## Pairs with

`recap` answers *what did I work on lately*; `trail` answers *how did this one thing
get the way it is*. Both mine the same session transcripts.

## Install

Add the parent `skillz` marketplace, then enable the `trail` plugin:

```
/plugin marketplace add muningis/skillz
/plugin install trail@skillz
```
