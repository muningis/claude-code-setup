# Plan

Planning turns a goal into change documents and a short plan of checkpoints. The human
approves the plan in plan mode. The run starts after that.

**Git first.** Ratchet needs a git repo. When the session is not in one, ask which
project. Never run `git init` in a parent folder.

## 1. Config

When `.claude/ratchet/config.json` exists and sets `behavior.all`, use it. A version 1
config gets migrated after approval (see `config.md`, "Migration").

With no config, or with a config that has only `checks` (verify writes these), find the
facts without changes. Keep the checks that the config has.
- **Tests.** What CI runs is the best signal. Then the manifest scripts and the test
  runner. When a legacy `.claude/rinse.json` exists, take its checks.
- **UI.** Does the product have one? Can a target render headless, or does it need a
  running app? Is there a reference: an old app, a design export, an old component?
- **Architecture.** Look for `ARCHITECTURE.md`, `docs/` and the conventions in
  `CLAUDE.md`. When there is nothing, read the code.

Then ask one AskUserQuestion with: the behavior commands, the visual mode and reference,
the architecture source, and `standing.commit`.

## 2. Track

Propose a track in one line, with the reason. The human can change it.

| Track | When |
| --- | --- |
| `fix` | A bug or a regression. Follow `fix.md` instead of this file. |
| `small` | 1 or 2 rows. |
| `full` | 3 to 8 rows. More than 8 rows means two plans. |

For a change that is one obvious edit, say that plain plan mode is cheaper, and let the
human choose.

## 3. Grill

Use the `ratchet:grill` skill with the goal. It asks in rounds until no question is open
and the human confirms. For the `small` track, ask only the questions that block the
design. Keep the questions and answers for the design log.

## 4. Read before you write

- **A reference implementation** is the spec. Read it. Note for each row the states, the
  texts that users see, the data shapes, the edge and error cases, and the source paths.
  Step 9 writes these notes to `.claude/ratchet/plans/<slug>.reference.md`.
- **Prior art.** For code that the goal touches, follow `why.md` when the reason for the
  current design is not clear. Put what you learn in the design log, under
  `## Prior art`.
- For a broad search, use one Explore agent. Ask for conclusions and paths, not file
  contents.

## 5. Documents

When the session is in plan mode already, you cannot write files. Then put the drafts in
the harness plan file, and do steps 1 to 4 after approval, before step 9.

1. Make the folder `docs/changes/NNNN-<slug>/`, with the next free number.
2. Write the documents of the track, as `docs.md` says, with `status: draft`.
3. Write each requirement with an `FR` ID and a coverage kind. Each success criterion
   needs one or more requirements. A fix or a refactor needs `UB` requirements for the
   behaviour that must not change.
4. Run `RS doclint --approval docs/changes/NNNN-<slug>` and
   `RS stelint docs/changes/NNNN-<slug>`. With `--approval`, open questions and word
   budgets block now, not after the human approves. Fix each `block` finding.

## 6. Cut the checkpoints

- **Skeleton first, then a small slice, then grow.** The first rows settle the decisions
  that the later rows use. Keep them small, so that the human reviews them well.
- **Harness first.** When gate 1 has no fast headless way to read the state, or gate 2
  has no capture script, the first row builds it (`kind: harness`).
- **Choose before you build.** When the goal has variants (themes, layouts, two
  approaches), add a `kind: choice` row first. It builds a cheap prototype or a board of
  the variants. The human picks one. The later rows build only the pick.
- **A few words for each row.** When a title needs a paragraph, split the row.
- **Testable alone.** When you cannot say what its tests check, it is not a row yet.
- **The product builds and runs after each row.** Stubs are fine. Broken is not.
- **Size.** Give each row an `est` of production lines, not counting tests. A row with
  an `est` above `size.prodLines` is too big. Split it.
- **Coverage.** Each `FR` ID is in one or more rows. Each coverage kind needs a gate that
  can see it: `visual` needs `config.visual`, and `smoke` needs a smoke check.
- **Risk first.** Put the risky unknowns early.
- **Refactor rows** get `kind: refactor`. Their tests pin the current behaviour.

Write the table in the format of `contracts.md`, "Plan table". Add notes when a row needs
them, one line each: `cp2 · scope: header band only`, `cp3 · done when: …`.

## 7. Roast

Use the `ratchet:roast` skill on the documents and the draft table. Give it the settled
decisions from the grill. Then:
- Fix each finding, or write in `## Trade-offs` why you do not fix it.
- `NEEDS_REWORK`: change the plan, then roast it one more time.
- `INVESTIGATE`: add a spike row, or ask the human.

## 8. Approve in plan mode

Enter plan mode. Write into the harness plan file:
- the table and its notes
- the document paths, with one line about each document
- the roast verdict, and what you changed because of it
- the config, when it is new or migrated, and `standing.commit`
- one cost line: "about 5 to 8 agent runs for each row × N rows; review rounds add more"

Then call ExitPlanMode. The human approves or edits.

## 9. After approval

1. Write `.claude/ratchet/plans/<slug>.md` and `<slug>.reference.md`.
2. Write `config.json` version 2, when it is new or migrated.
3. When `docs.root/architecture.md` does not exist, write it. Use the default rules from
   `docs.md`, plus the rules that you found in the repo.
4. Write `.claude/ratchet/.gitignore` with `evidence/`, `live.json`, `metrics.jsonl`,
   `dreams/` and `engine.js`.
5. For each change document, set `status: approved` and run `RS doclint --approve <file>`.
6. Add the change to `docs/changes/index.md`.
7. Continue with `run.md` for the first row. Run interactive, unless the human asked for
   `--auto`. Do not ask for approval again.
