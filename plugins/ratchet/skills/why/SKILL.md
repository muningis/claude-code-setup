---
name: why
description: Finds out why code is the way it is, from git history and past Claude Code sessions, with the options that were rejected. Use it when the user asks why something is like this, how it came to be, or what the reasons for a decision were. Also use it before you change code that looks wrong or surprising.
argument-hint: "<file, symbol, config key or decision>"
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/../ratchet/scripts/trail.py *), Bash(git log *), Bash(git blame *), Bash(git show *)
---

# Why

Read `${CLAUDE_SKILL_DIR}/../ratchet/references/why.md` and follow it. The arguments of
this skill are what to trace.

That file writes the ratchet skill directory with a variable. Here, the directory is
`${CLAUDE_SKILL_DIR}/../ratchet`. The session miner is
`python3 ${CLAUDE_SKILL_DIR}/../ratchet/scripts/trail.py`.
