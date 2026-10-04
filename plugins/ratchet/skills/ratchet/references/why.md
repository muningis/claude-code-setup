# Why

Find out **why** code is the way it is, not only what it does. Use two sources: git
history (what changed, and when) and past Claude Code sessions (the request, the reasons,
and the options that were rejected).

`$ARGUMENTS`: what to trace: a file, a symbol, a config key, or a decision in words.

## 1. Pin the target

- **Search words** for the session miner: the specific strings, such as a symbol, a file
  name or a config key. The miner needs all of them in a turn.
- **A git target:** the files, a function, or a string to search for.
- **The repo.** For a file, it is the repo of that file.

When the question is vague, find the real code first, so that you have real names.

## 2. Git history: what and when

- A file over time: `git log --follow --oneline -- <file>`
- A function: `git log -L :<function>:<file>`
- When a string came or went: `git log -S'<string>' --oneline -- <path>`
- A key commit: `git show <sha>`
- Who wrote the lines now: `git blame -L <start>,<end> <file>`

Commit messages are good for facts, but they seldom give the reason. Step 3 finds it.

## 3. Sessions: the reason

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/trail.py <words> --cwd <repo-path>
```

- When the result is thin, drop `--cwd`. A decision is often made in a session that ran
  in another folder.
- Use `--since 90d` for a large result, and `--max-hits N` or `--context CHARS` to tune.
- The output lists sessions, oldest first. Each has its `goal` and its `hits`: the human
  prompts, the reasons, and the edits and commands on the target. The reasons hold the
  rejected options. Read them closely.
- When the miner finds nothing, say so, and use git only. Do not invent a reason.

## 4. Tell the story

Oldest first. Match each key commit with the reason that you found. Show, when there is
evidence:
- the first intent: the problem that the first version solved
- why this approach, and **which options were rejected, and why**. Put this first.
- how it changed since, and why
- the gaps: a change with no reason found, or a reason with no change

```markdown
## Why: <target>

**Today:** <one line>

**How it got here:**
- `<sha>` <date>: <what changed>. Why: <the reason, or "no reason found">

**Options not taken:** <the options, and why they were dropped>

**Bottom line:** <what to keep in mind before you change this>
```

Leave out each section without evidence. Give the `sha` or the session for each claim.

In ratchet planning, put the result in the design log, under `## Prior art`.
