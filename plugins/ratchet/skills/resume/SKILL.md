---
name: resume
description: Picks up a handover from an earlier session. It checks the handover against the repos as they are now, tells what changed since, and starts the first step that still applies. Use it when a session starts with "continue where we left off" or "pick up the handover", or when the user gives a handover file.
argument-hint: "[<handover path>]"
allowed-tools: Bash(python3 ${CLAUDE_SKILL_DIR}/../ratchet/scripts/state.py *)
---

# Resume

Read `${CLAUDE_SKILL_DIR}/../ratchet/references/handover.md` and do its section
"Resume". The argument of this skill is the handover path.

That file writes the ratchet skill directory with a variable. Here, the directory is
`${CLAUDE_SKILL_DIR}/../ratchet`. The state collector is
`python3 ${CLAUDE_SKILL_DIR}/../ratchet/scripts/state.py`.

This skill only reads. It does not resume a stopped process, job or download.
