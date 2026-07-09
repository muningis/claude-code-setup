---
name: recap
description: >-
  Summarize what you worked on across your Claude Code sessions since the last
  recap — a ready-to-paste standup of the tasks you actually drove, grouped by
  project. Reads the local session transcripts (~/.claude/projects), pulls each
  session's title and your typed prompts since a saved watermark, and turns them
  into concise "what I did" bullets. Use whenever asked for a standup, a daily or
  weekly summary, "what did I do / get done / work on" yesterday/this week/since
  Friday, "what have I been up to", a recap of recent sessions, or notes to bring
  to standup. Not for summarizing the current conversation alone, and not for
  reading another machine's history.
allowed-tools: Bash(python3:*)
---

# Recap

Turn your recent Claude Code sessions into a standup. This skill reads the local
session transcripts, gathers what you worked on since the last recap, and writes
it up as the kind of bullets you'd actually say out loud: "yesterday I…", grouped
by project.

A helper script does the parsing; you do the summarizing. Don't reimplement the
parsing in `jq` — the script already handles the transcript schema, the time
window, and the "since last time" watermark.

Optional argument (`$ARGUMENTS`): a time hint (`this week`, `since friday`,
`yesterday`, `7d`, `36h`), a project/path to scope to, or `everything` to ignore
the watermark and look at a fixed window.

## Step 1 — Gather the sessions

Run the collector. Pick flags from what was asked:

```
python3 ${CLAUDE_SKILL_DIR}/scripts/sessions.py [flags]
```

- **Plain "recap" / "standup" / "what did I do since last time"** → run it with
  **`--all-projects`** and no `--since`. This uses the saved watermark (everything
  since your last recap) and **advances it**, so the next recap picks up where this
  one ends. A standup spans everything you touched, hence `--all-projects`.

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/sessions.py --all-projects
  ```

- **A specific window** ("this week", "yesterday", "since Friday") → translate it
  to a span and pass `--since`. With `--since` the watermark is **not** moved (it's
  an ad-hoc query, not the rolling standup boundary). Spans: `Nd` `Nh` `Nm` `Nw`,
  or an ISO date. You compute the span — the script can't read "yesterday".

  ```
  python3 ${CLAUDE_SKILL_DIR}/scripts/sessions.py --all-projects --since 7d
  ```

- **Scoped to one project** ("what did I do in gulbe", or you're clearly working
  in one repo and ask about "this project") → drop `--all-projects` (defaults to
  the current directory and below) or pass `--cwd <path>`.

- **Re-running / just previewing** without consuming the window → add `--no-update`.

The script prints JSON: `since`, `scope`, `sessionCount`, and a `sessions` array
(each with `title`, `cwd`, `gitBranch`, `started`/`ended`, `promptCount`, and the
`prompts` you typed). Sessions with no human prompt (headless/eval/subagent runs)
are excluded by default as noise — pass `--include-empty` only if explicitly asked.

If `sessionCount` is 0, say so plainly ("nothing logged since the last recap" /
"no sessions in that window") and offer to widen the window — don't invent work.

## Step 2 — Write the standup

Read the JSON and synthesize. The session `title` is an auto-generated one-liner;
the `prompts` are what you actually asked for and carry the real detail and any
mid-session pivots. Lead from the prompts, use the title as a backstop.

Group by **project** (basename of `cwd`, note the `gitBranch` if not default).
Within a project, give **one bullet per real task or outcome** — not one per
session and not one per prompt. Collapse a long back-and-forth ("fix it" → "now
this" → "sorry go ahead") into the thing that got done. Phrase as completed work
in past tense, concrete and skimmable.

Prefer outcomes over transcript play-by-play: "migrated ks-kvk to Postgres +
Drizzle and split Terraform into infra/app" beats "ran a workflow, then debugged a
port conflict, then…". Keep it to what a teammate would care about hearing.

## Output structure

Use this shape (drop the time line if a window wasn't specified):

```markdown
## Standup — <window, e.g. "since Thu" / "this week">

**<project> (<branch if notable>)**
- <task / outcome>
- <task / outcome>

**<project>**
- <task / outcome>

_<N> sessions across <M> projects._
```

If everything was in one project, skip the grouping and just give the bullets.
Keep the whole thing tight — this is something to glance at before a meeting, not
a changelog.

## Notes

- The watermark lives at `~/.claude/standup-state.json`. Only a plain run (no
  `--since`) moves it; that's deliberate so ad-hoc "what did I do this week"
  queries don't disturb your rolling standup boundary.
- This reads only local transcripts on this machine. It can't see work done on
  another machine or in the web app.
