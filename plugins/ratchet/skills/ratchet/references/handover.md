# Handover and resume

Pass work to the next session. This is the baton flow, inside ratchet. The file format is
the same as baton's, so baton's `resume` can read ratchet's files, and the other way.

`state.py` collects the facts from git. The reasons exist only in this conversation, and
they are the part that has value.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/state.py [ROOT ...]
```

## Handover

1. **Scope.** Run `state.py`. Use `suggestedScope` as a start: `repo` (one repository),
   `workspace` (several repositories that change together) or `explore` (ideas, with no
   repository). For `workspace`, run it again with each root.
2. **Collect.** Add `git diff --stat` for each dirty repo, each pushed branch or open PR
   from this session, and the commands that prove that the work runs, with their last
   result. Then take from the conversation: the goal, the decisions and the options that
   you did not choose, the dead ends, the constraints, and the open questions.
3. **Write** `.claude/handovers/<stamp>-<slug>.md`. Get the stamp from
   `date -u +%Y-%m-%d-%H%M`. Use the repo root, the workspace root, or
   `~/.claude/handovers/` when the work has no folder.

```markdown
# Handover — <what the work is>

<!-- scope: repo|workspace|explore · roots: <absolute paths> · written: <UTC stamp> -->

**Start here:** <the first action, concrete enough to do without more reading>

## Mission
## State
## Decisions (and what was rejected)
## Next steps
## Dead ends
## Open questions
## Pointers
```

Leave out each section that has no real content. Never write a secret: name the
environment variable, not its value. Never state a fact that you did not see. "Ask the
human" is a valid next step. Do not commit the file.

4. **Hand it back.** Give the path, the scope and the kickoff line:
   `/ratchet resume <path>`.

## Resume

1. **Find it.** A path in `$ARGUMENTS` comes first. Else take the newest file in
   `.claude/handovers/`, the workspace root, then `~/.claude/handovers/`. With no file,
   ask for the path.
2. **Check it.** Run `state.py` again for the roots that the file records. Compare: a
   branch that was merged or deleted, commits that landed, work that was committed or
   lost, steps that are done already. A handover is a note from the last session, not
   an instruction.
3. **Brief, then start.** Give the mission in two sentences. Lead with what changed
   since the handover. Then do the first action that still applies. When it is a
   question for the human, ask it.

## The per-checkpoint baton

A ratchet run writes a minimal baton, `.claude/handovers/ratchet-<slug>.md`, with
`RS baton` (see `run.md`, step 6). It holds only what is not on disk. The relay mod resets
the context to it.
