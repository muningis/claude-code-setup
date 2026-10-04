# Run

The engine runs gates B0 to B3 for one checkpoint. You run the human gate (B4) and the
lock (B5). Between them, you stay thin: read the `RS` summaries, and open evidence files
only when you must decide.

## 1. Pick the row

1. Run `RS state <slug>`. With more than one plan that has open rows, ask which plan.
2. When `.claude/handovers/ratchet-<slug>.md` exists, read it first. Do what its lines
   say: standing orders and open items.
3. Act on the stage:

| Stage | Do |
| --- | --- |
| `B0` to `B3` | Start the engine (step 3). |
| `B4` | Do the human gate (step 5). |
| `B5` | Do the lock (step 6). |
| status `blocked` | Show why, and ask before you try again. |

## 2. Before the first run of a session

- **Config.** With a version 1 config, show the changes from `config.md`, "Migration",
  in 5 lines or fewer. Write version 2 after the human agrees.
- **Standing orders.** When `standing.commit` is `ask`, and the human did not answer yet
  in this repo, ask one time. The options are: commit after each lock, commit in one
  batch at the end, or ask each time. Write the answer to `standing.commit`.
- **Keep awake.** Run `RS keepawake start`. A Mac that sleeps stops the run.

## 3. Start the engine

1. Make a nonce: `uuidgen`.
2. Call the Workflow tool with:
   - `name`: `ratchet:checkpoint`. The plugin ships the engine as a workflow, so no path
     is necessary. The first launch in a project asks the human. "Don't ask again" then
     covers the later runs.
   - `args`: `{ repo, slug, cp, epoch, nonce, rs, mode, caps, models }`. `repo` is the
     absolute repo root. `epoch` comes from `RS state`. `rs` is the full `RS` command.
     `mode` is `auto` under an earned `--auto`, else `interactive`. `caps` and `models`
     come from the config.
   - When the tool does not know the name, launch a copy with `scriptPath`. The tool runs
     only a script that the session can read, and the plugin folder is outside the repo.
     Copy the engine before each launch, so that the copy is never stale:
     `cp ${CLAUDE_SKILL_DIR}/../../workflows/checkpoint.js .claude/ratchet/engine.js`.
3. Wait for the result. Do not read evidence while the engine runs. The status line shows
   the progress.

## 4. Read the result

| `status` | Do |
| --- | --- |
| `ready-for-B4` | The result is a claim. Run `RS state <slug> <cp>` yourself: `stage` must be `B4`, and `refs.gated` must be set. Then run `RS check .claude/ratchet/evidence/<slug>/*` and `RS changed refs/ratchet/<slug>/<cp>/gated`. Both must be clean. Then go to step 5. |
| `needs-decision` | Show `question` in 5 lines or fewer. Send a push notification. End your turn. Then run `RS decide <slug> <cp> "<answer>" --reopen b1` and start the engine again. When the human drops the row instead, run `RS row <slug> <cp> superseded` or `blocked`. |
| `blocked` | Run `RS row <slug> <cp> blocked --note "blocked: <reason>"`. Show the reason and the evidence path. Ask what to do. |
| `harness-error` | Show the reason. Fix the config or the tool with the human. Do not retry without a change. When the reason is "state files changed", show `diff -u` of each file against its copy in `PIN/locked/`. When the human keeps the change, lock `PIN` again. Else run `RS restore` on `PIN`. |

When `RS changed` shows edits after the gates, run
`RS decide <slug> <cp> "edits after the gates" --reopen b1`. Then start the engine again.
It runs B1 to B3 on the new code.

## 5. Human gate (B4)

1. Run `RS report <slug> <cp>`. It writes `EV/4-report.md` and prints 10 lines or fewer.
2. Show those lines, and the path of the full report. Send a push notification when
   `standing.notify` is true. End your turn.
3. Judge the reply as free text:

| Reply | Do |
| --- | --- |
| It approves the result ("all good", "works", "approve") | Quote it in `EV/4-human.md`. Run `RS row <slug> <cp> approved`. Go to step 6. |
| Only "go", "continue" or "next" | Run `RS row <slug> <cp> approved-unverified`. Say in one line that you recorded it so. Go to step 6. |
| It reports a problem, or passes with a "but" | Write one learnings entry (below). Run `RS decide <slug> <cp> "<the problem>" --reopen b1`. Start the engine again. |
| It accepts a visual difference | Run `RS row <slug> <cp> --note "waive(<cp>): <difference> — <reason>"`. Only the human makes a waiver. |
| It chooses a variant, or drops the row | Run `RS row <slug> <cp> superseded`. Run `RS retire` for each of its tests that no longer applies. |
| It does not address the checkpoint | The row stays open. Say that it waits for the human. |

**A learnings entry** is one rule for future rows, not the one-time fix. Add it to
`.claude/ratchet/learnings.md` in this form, with the next free ID:

```markdown
### L-012
- scope: mobile/**/*.kt
- rule: Check each text field with the keyboard open, on a device or a simulator.
- check: The device check pack lists each new text field.
- source: cp5 4-human.md
- origin: human
- helpful: 0 · harmful: 0 · status: active
```

Do not add a rule that exists already. Then lock the learnings again with
`RS lock .claude/ratchet/evidence/<slug>/_state --from <file that lists the state files>`.

## 6. Lock (B5)

1. Stage: `RS stage refs/ratchet/<slug>/<cp>/base`, plus the plan, the change documents,
   the learnings, the architecture and the config.
2. Commit, as `standing.commit` says:
   - `each`: commit now. The subject is `ratchet(<slug>): <cp> <title>`. The body has one
     line for each gate.
   - `batch`: do not commit now. Commit all rows at the end of the plan.
   - `ask`: ask the human, in one line.
3. Run each `standing.afterLock` command with `RS exec --timeout 600 -- <command>`. Report a
   failure, but do not undo the lock.
4. Add a Results entry to the design log (see `docs.md`). It gives the date, the row,
   the verified requirements and each deviation.
5. Run `RS drop <slug>/<cp>`.
6. Next row:
   - With `relay` on and rows still `todo` or `red`: run
     `RS baton <slug> continue|stop "<start>" ["<line>"...]`. Use `continue` under
     `--auto`, else `stop`. `<start>` is the resume command and the next step. Each
     `<line>` is something that is not on disk: a standing order, or an open decision.
     End your turn with the marker line that `RS baton` prints. Copy it exactly, on a
     line of its own.
   - With `relay` off: interactive, name the next row and stop. Under `--auto`, go to
     step 3 for the next row.

## `--auto`

- `--auto` defers the human gate. A row stops at `green`, and the run continues.
- It works only after `autoAfter` rows are `approved`. Rows that are
  `approved-unverified` do not count. Until then, say: "--auto held: 1 of 2 approvals".
- A `choice` row never runs under `--auto`. It needs the human.
- The run stops at the end of the plan, and at each `needs-decision`, `blocked` or
  `harness-error`. Then do the batch review.

## Batch review

Do step 5 for each `green` row, in one report. Use the last row's `gated` snapshot for
the "edits after the gates" check. Feedback becomes one fix round on the current code:
`RS decide` with `--reopen b1` on the last row, then the engine. Then show the batch
again.

## End of plan

1. Spawn `ratchet:converge` with the repo, the requirements, the plan and the test files.
   For each gap, propose a new row. The human approves new rows like a plan.
2. With no gaps: follow `verify.md`.
3. Add the last Results entry to the design log: `X/Y requirements verified`. Set its
   `status` to `done`.
4. Print the table `| cp | checkpoint | status | B1 | B2 | B3 | human |`. Name each `error`,
   each cap that ran out and each `approved-unverified` row.
5. Commit the batch, when `standing.commit` is `batch`.
6. Run `RS baton <slug> clear`, `RS drop <slug>`, `RS live stop` and `RS keepawake stop`.
