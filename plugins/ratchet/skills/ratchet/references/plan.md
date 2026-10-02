# Part A — Plan

**Write nothing to the repo until the user approves in A4**: no config, no architecture,
no plan. Plan mode only allows edits to the harness plan file, and a rejected cut
shouldn't leave files behind.

**Git first.** Ratchet needs a git repo, because snapshots, diffs and staging are all
git. If the session isn't inside one, ask which project, and do it before reading
anything else. Never `git init` a parent folder.

## A1 — Config (first run, or `plan --refresh`)

Skip this if `.claude/ratchet/config.json` loaded. Otherwise infer what you can,
read-only:
- **Tests.** What CI runs is the strongest signal, then manifest scripts and the test
  runner. If `.claude/rinse.json` exists, take its `command` checks.
- **UI.** Does the product have one? If so, can a target render headless, or does it
  need a running app? Is there a reference to compare against: a legacy app, a design
  export, the old component?
- **Architecture.** Look for `ARCHITECTURE.md`, `docs/`, the repo's CLAUDE.md
  conventions. Failing those, read the code.

Confirm everything with **one** AskUserQuestion covering:
- the behavior commands
- the visual mode and reference
- the source of the architecture

The schema is in `${CLAUDE_SKILL_DIR}/references/config.md`.

If the repo has no architecture doc, draft one from the code you read: layering, where
state lives, naming, error handling, testing conventions. Keep it under a page and
specific to this repo. The reviewers are only as good as this file.

## A2 — Read before cutting

If there's a reference implementation, read it. It is the spec. Otherwise read the code
the goal touches. For broad discovery, use ONE Explore agent and ask for conclusions and
paths, not file dumps.

Keep what you learn for `plans/<slug>.reference.md`: for each checkpoint, the states,
user-visible strings, data shapes, edge and error cases, and source paths or URLs. The
spec agent and the reviewers read this instead of re-deriving the reference, and it
survives compaction.

## A3 — Cut checkpoints

- **Skeleton first, then one deliberately small slice, then grow.** The early checkpoints
  settle decisions that everything after them inherits. Keep them small enough that the
  human really reviews those decisions.
- **A few words per checkpoint.** If a title needs a paragraph, split the checkpoint.
  Nobody reviews a wall of generated text, and that includes the plan.
- **Sized to context.** The implementer must hold the relevant real code and its
  reference in context. If it can't, split.
- **Testable on its own.** If you can't say what its tests would assert, it isn't a
  checkpoint yet.
- **Each one leaves the product building and running.** Stubs are fine; broken is not.
  The human gate reviews a running app.
- **Harness first.** If gate 1 has no fast, headless way to read state and trigger
  actions, or gate 2 has no capture script, `cp0` builds it. Its own gate 2 is a smoke
  check: the PNG files exist, aren't blank, and pass the determinism check in `config.md`.
- **Refactors are flagged.** A checkpoint that moves code without changing behavior gets
  `kind: refactor`. Its spec is characterization tests that pass before and after, plus
  a structural assertion that fails until the move lands, if one exists.
- **Small goals don't need this.** If the goal cuts into fewer than 3 checkpoints, say
  so: plain plan mode plus `/rinse:rinse` is cheaper. Let the user choose.
- **3–8 is the cost sweet spot.** More than that means the goal is two plans.

The slug is the goal in kebab-case, at most 40 characters, with `-2` appended if that
name is taken. The plan file is `.claude/ratchet/plans/<slug>.md`:

```markdown
# <goal>
slug: <slug> · created: <YYYY-MM-DD>

| id | checkpoint | target | status | base |
| -- | ---------- | ------ | ------ | ---- |
| cp1 | screen skeleton | profile | todo | |
| cp2 | header only | profile | todo | |
| cp3 | date formatting helper | - | todo | |
| cp4 | list rows, static data | profile | todo | |
| cp5 | list loading + error states | profile-error | todo | |

## Notes
- cp2 · scope: header band only
- cp4 · scope: whole screen
- cp3 · done when: relative dates match the legacy formatter for the reference cases
```

- **`target`** is what gate 2 captures: a short `[a-z0-9-]` name that the capture script
  maps to a route, story or state. `-` means the checkpoint has nothing visible, so gate
  2 reads `n/a` for it.
- **`scope:`** narrows the visual judgment. Differences outside it are deferred, not
  blocking, so a skeleton can pass against a full-screen reference. The last checkpoint
  on each target must judge the whole target.
- **Other notes**, one line each and only when needed: `kind: refactor`, `done when:`,
  and later `waive(...)` and `blocked:` lines.
- **`reference:`** in the plan header overrides `config.visual.reference` for this plan,
  in the same `kind value` form (e.g. `reference: url https://legacy.example.com`).

## A4 — Approve in plan mode

Enter plan mode if you aren't in it already. Put the following in the harness plan file:
- the checkpoint table with its notes
- the `architecture.md` draft (if new) and the config (if new)
- one cost line: "≈ 5–8 agent runs per checkpoint (spec, implement, visual, two
  reviewers; more on fix rounds) × N checkpoints"

Then ExitPlanMode. The user approves or edits.

After approval, write:
- `.claude/ratchet/plans/<slug>.md` and `<slug>.reference.md`
- `config.json` and `architecture.md`, if new
- `.claude/ratchet/.gitignore` containing `evidence/`. Proof stays local; the gate
  summary goes into commit bodies.

Plans, config, architecture and learnings are meant to be committed.

Then continue straight into **Run** for cp1: interactive, unless the user asked for
`--auto`. The plan is approved; don't ask again.
