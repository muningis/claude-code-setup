---
name: handover
description: Writes a handover, so that the next session can continue the work. It holds the mission, the state of the repos, the decisions and the rejected options, the dead ends and the next steps. Use it when the context is full or nearly full, or when the user asks to hand over, wrap up or continue later.
argument-hint: "[<root> ...]"
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/../ratchet/scripts/state.py *), Bash(date *)
---

# Handover

Read `${CLAUDE_SKILL_DIR}/../ratchet/references/handover.md` and do its section
"Handover". The arguments of this skill are the roots to collect.

That file writes the ratchet skill directory with a variable. Here, the directory is
`${CLAUDE_SKILL_DIR}/../ratchet`. The state collector is
`python3 ${CLAUDE_SKILL_DIR}/../ratchet/scripts/state.py`.

To pick a handover up again, use the `resume` skill.
