# recap

A standup generator for Claude Code.

`recap` reads your local session transcripts (`~/.claude/projects`), gathers what
you worked on **since the last recap**, and writes it up as standup bullets —
grouped by project, phrased as completed work.

- It tracks a watermark (`~/.claude/standup-state.json`), so a plain `recap`
  always means "since I last asked" and advances the mark.
- Ad-hoc windows (`recap this week`, `since friday`, `yesterday`) query a fixed
  span and leave the watermark alone.
- Headless / eval / subagent sessions (no human-typed prompt) are filtered out as
  noise by default.

## How it works

A helper script does the parsing; the skill does the summarizing.

- `skills/recap/SKILL.md` — invocable as `/recap:recap`.
- `skills/recap/scripts/sessions.py` — walks the transcripts, applies the window
  and scope, and emits one JSON record per session (title, your prompts, time
  span, project). Run it directly to see the raw material:

  ```
  python3 skills/recap/scripts/sessions.py --all-projects --since 7d --no-update
  ```

  Flags: `--since Nd|Nh|Nw|ISO`, `--cwd PATH`, `--all-projects`, `--include-empty`,
  `--no-update`, `--state PATH`.

## Install

Add the parent `skillz` marketplace, then enable the `recap` plugin:

```
/plugin marketplace add muningis/skillz
/plugin install recap@skillz
```
