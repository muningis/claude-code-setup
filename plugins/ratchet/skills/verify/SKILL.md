---
name: verify
description: Runs the repo's checks on what changed, fixes what fails and runs the full set again. Then it gives the human the checks that only a human can do. Use it after you finish a change, before you call the work done or ready to commit. Also use it when the user asks to verify or check the work.
argument-hint: "[<check id> | <path> | --all]"
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/../ratchet/scripts/ratchet.sh *)
---

# Verify

Read `${CLAUDE_SKILL_DIR}/../ratchet/references/verify.md` and follow it. The arguments
of this skill are its options.

- `RS` is `bash ${CLAUDE_SKILL_DIR}/../ratchet/scripts/ratchet.sh`. Write the full
  command each time. Do not keep it in a shell variable, because zsh does not split it.
- The invariants are in `${CLAUDE_SKILL_DIR}/../ratchet/SKILL.md`, section "Invariants".
