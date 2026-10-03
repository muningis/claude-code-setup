---
name: ratchet
description: Helix-style checkpoint workflow. Plan a goal as small checkpoints, then push each one through four gates (red-first tests, a visual diff, two blind adversarial reviewers, human approval) before the next starts.
argument-hint: "plan <goal> | run [<slug>] [--auto] | review [<slug>] | status"
disable-model-invocation: true
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/ratchet.sh *)
---

# Ratchet

An attempt may be wrong. It may not lock until it isn't, and the next checkpoint
doesn't start until the current one locks.

`$ARGUMENTS`:
- `plan <goal>`: Read `${CLAUDE_SKILL_DIR}/references/plan.md` and follow it
  (`--refresh` re-detects the config).
- `run [<slug>] [--auto]`: **Run**, below. `--relay` is added by ratchet's relay mod, not
  typed: it means the run hands over at each checkpoint's end (B5).
- `review [<slug>]`: B4 for every `green` row, as one batch.
- `status`, or no arguments: print each plan's table. With no plan, ask for a goal.

## Invariants

1. The order is B0 spec → B1 behavior → B2 visual → B3 review → B4 human → B5 lock.
   Only B4 can be deferred (`--auto`), and only after `autoAfter` human approvals.
2. **You run every gate.** A worker's "green" is a claim, not evidence. Run each command
   from the repo root; full output goes to the evidence file and only the tail into
   context: `cmd > F 2>&1; echo "exit=$?" >> F; tail -n 40 F`.
3. Never weaken a check. That means none of these:
   - deleting, skipping, focusing or loosening a test
   - regenerating snapshots to get a pass
   - adding `@ts-ignore` / `eslint-disable` / `type: ignore` / `noqa`
   - `--no-verify`
   - editing `config.json`, `architecture.md`, `learnings.md` or a verdict to get a pass
4. Specs are pinned from B0 on, this checkpoint's and every earlier one's. After each
   implementer round, run `RS check .claude/ratchet/evidence/<slug>/*`. A changed spec
   file fails the round and is put back with `RS restore`. Only an amendment changes a
   spec.
   - A changed `PIN` file is different. Show it to the user (`diff -u` against its copy
     in `PIN/locked/`): keep it → re-lock; otherwise restore it.
   - When you change a state file with the user's OK, re-lock `PIN` right away.
5. A gate that can't run (missing tool, failed capture, app won't start) is `error`,
   never pass.
6. Each fix loop stops at `maxRounds`. Then the row becomes `blocked`, with the reason in
   its Notes. Report each round's attempt, then stop. Never pass an unlocked row.
7. Agents get absolute paths, never pasted diffs or logs.
8. No commit or push without the user's OK. Stage only with `RS stage`.
9. The human gate is free text: no AskUserQuestion, no pass/fail options.

`RS` = `bash ${CLAUDE_SKILL_DIR}/scripts/ratchet.sh`: the deterministic mechanics
(`snap [<name>]`, `drop`, `diff`, `size`, `changed`, `tripwire`, `stage`, `lock`,
`check`, `restore`, `baton`). Its header documents each one. Call it; don't
re-derive. Write the full `bash …/ratchet.sh <cmd>` in every command. Never keep it in
a shell variable: the shell may be zsh, which won't split it.
When `config.models.<role>` is set, pass it as the agent's `model:`.

## State

Ratchet needs git, and every path is relative to the repo root.
- Not inside a repo → ask which project. Never `git init` a parent folder.
- The state block at the end missed because the session started elsewhere → read the
  root's `.claude/ratchet/` directly.
- A config you didn't see written here (a fresh clone) → show its commands and confirm
  once.

Under `.claude/ratchet/`:
- `config.json`: gate commands, capture, caps (schema in
  `${CLAUDE_SKILL_DIR}/references/config.md`)
- `architecture.md`: what the reviewers enforce
- `learnings.md`: the human's feedback as rules
- `plans/<slug>.md` and `<slug>.reference.md`: the checkpoint table, and what the
  reference does
- `evidence/<slug>/<cp>/`: `EV`, gitignored proof, `-r<n>` per round

`.claude/handovers/ratchet-<slug>.md` is the baton: the few lines a context reset would
otherwise lose (standing OKs, open items). Everything else is on disk already.

Rows go `todo` → `red` (spec pinned) → `green` (gates 1–3 passed) → `approved` (by the
human), or `blocked`.
- `BASE` = `refs/ratchet/<slug>/<cp>/base`
- `GATED` = `refs/ratchet/<slug>/<cp>/gated`
- `PIN` = `.claude/ratchet/evidence/<slug>/_state`, which pins `config.json`,
  `architecture.md` and `learnings.md`

## Run

**Pick.** If one plan has open rows, use it; if several do, ask which. Read its baton
first if there is one, and honor its lines. Take the first row that isn't `approved`:
- `todo` → B0
- `red` → B1
- `green` → B4 (under an earned `--auto`, the next row)
- `blocked` → show why, and ask before retrying

Never re-snapshot an existing `BASE`: resuming relies on it. Round numbers continue from
`EV`'s highest `-r<n>`.

**`--auto`** defers B4: rows lock at `green` and the run moves on.
- Until `autoAfter` rows (default 2) are `approved`, B4 still runs per checkpoint. Say
  so in one line: "--auto held: 1 of 2 human approvals".
- It stops at the plan's end, on any `error`, `blocked` or escalation, or at the size
  guard. Then it runs B4 once for all `green` rows.

### B0: Spec (red)
1. **Baseline.** Run `behavior.all` and each `extra` → `EV/0-baseline.txt`. Failures
   already there aren't this checkpoint's; B4 reports them.
2. Run `RS snap <slug>/<cp>/base` and put the short SHA in the row's `base`. Run
   `RS lock PIN` with whichever of the three state files exist.
3. Spawn `ratchet:spec` with: the row and its Notes, the reference notes and reference
   source paths, `architecture.md`, `learnings.md`, and the behavior commands.
4. **Pin the spec.**
   - `RS diff BASE --name-only` is the spec set: test files, fixtures and helpers only.
     Anything else goes back.
   - An edit to an earlier checkpoint's spec is an amendment. Log it with its reason in
     `EV/0-amendments.md` and re-lock it in that checkpoint's `EV`.
   - Then `RS lock EV <spec set>`, and save the agent's `cases:` to `EV/0-cases.md`.
5. **Confirm red.** Run `behavior.one` on the spec files → `EV/0-red.txt`. Each case
   must fail for the right reason.
   - Right: a failing assertion, or the module this checkpoint creates not existing yet.
   - Wrong: a syntax error, a wrong import of existing code, a runner error.
   - A passing case specifies nothing. Send it back once with the output; if it happens
     again, the row is `blocked`.
   - `kind: refactor` inverts this: characterization cases pass now.
6. Row → `red`.

### B1: Gate 1, behavior
Spawn `ratchet:implement` named `impl-<slug>-<cp>`. Give it:
- the row and `EV`
- the spec set and `.claude/ratchet/**`, both forbidden
- the reference paths, `architecture.md` and `learnings.md`

When it reports:
1. `RS check .claude/ratchet/evidence/<slug>/*`. Anything changed → `RS restore`, and
   the round fails.
2. `behavior.one` → `behavior.all` → each `extra`, into `EV/1-behavior-r<n>.txt`. Green
   means the spec passes and nothing fails that the baseline didn't.
3. Failing → SendMessage the same implementer the evidence path, then re-run it all. If
   it's gone, spawn a fresh one with the failure and an `RS diff BASE` output path.
4. `RS size BASE` over `maxDiffLines` → too big to review. Interactive: propose
   splitting the row. Under `--auto`: the row is `blocked`.

### B2: Gate 2, visual
`n/a` when `visual` is null or the row's target is `-`. Captures, placeholders,
reference kinds and the dev server are in `${CLAUDE_SKILL_DIR}/references/config.md`.
1. Capture impl and ref for the row's target at each viewport →
   `EV/2-{impl,ref}-<vp>-r<n>.png`.
2. `cmp -s` impl and ref identical → pass with no agent. Impl identical to the previous
   round → reuse that verdict.
3. Otherwise spawn `ratchet:visual` with the image paths, target, scope, waivers and
   expectation → `EV/2-visual-r<n>.json`.
   - `INVALID` → recapture, at most twice, then `error`.
   - A `fixable: true` finding blocks: the implementer fixes it, then B1's checks and
     B2 run again.
   - `deferred` and `waived` entries don't block.
4. **Regression.** Recapture each earlier `approved` row's target. If it isn't
   byte-identical to its last capture, it joins this round's review.

### B3: Gate 3, adversarial review
1. Prepare the round: `RS diff BASE > EV/3-diff-r<n>.patch`,
   `RS tripwire BASE > EV/3-tripwire-r<n>.txt`, and `RS snap <slug>/<cp>/review`.
2. Spawn `ratchet:review-arch` (named `arch-<slug>-<cp>`) and `ratchet:review-break`
   (named `break-<slug>-<cp>`) in one message. Give each: the patch, the tripwire, the
   row, the spec set, the reference notes, `architecture.md` and `learnings.md`.
   - Wait for both before acting on either.
   - Then run `RS changed refs/ratchet/<slug>/<cp>/review`. Clean up run artifacts; a
     source edit by a reviewer is `error`.
3. A reviewer approves only when its `findings` is empty. Unparsable output → ask
   once more, then `error`.
4. **Fix every finding.** Severity sets the order, not whether it gets fixed.
   - Code findings go to the implementer.
   - Test findings go to `ratchet:spec` as an amendment, which is logged, re-locked and
     shown at B4.
   - A finding you think is wrong: write why in `EV/3-response-r<n>.md` and let its
     reviewer re-judge. Never drop one silently.
   - Escalate to the user now, in both modes, when the reviewers contradict each other
     or a finding survives two fix rounds.
5. **Next round.** Re-run B1's checks, and B2 if rendering could have changed. Then
   SendMessage each reviewer the new patch and your responses.
   - They review only the delta plus their open findings. A new finding outside the
     delta must say why it wasn't raised before.
   - A reviewer that's gone gets a fresh spawn with its last verdict.
6. Both approve in one round → `RS snap <slug>/<cp>/gated`, and the row → `green`.

### B4: Gate 4, human
If `RS changed GATED` shows edits made after the gates, re-run B1–B3 first. Then report
and **end your turn**:
- the checkpoint, and 3–5 lines on what changed (files, not the diff)
- what "proven" means: `0-cases.md` one line each, amendments, non-blocking visual
  findings, baseline failures
- one line per gate with its evidence path, and how to see it running

Judge the reply:
- **Approves** → quote it to `EV/4-human.md`, then B5.
- **Reports a problem**, including a qualified pass:
  - Append one generalized rule to `learnings.md`: the rule a future checkpoint should
    follow, not the one-off fix. No duplicates. Then re-lock `PIN`.
  - Past ~30 rules, propose folding the stable ones into `architecture.md`; propose that
    edit directly for architectural feedback.
  - Fix, run B1–B3, and return to B4.
- **Explicitly accepts a visual difference** (here, or when a blocked gate 2 is shown to
  them) → add
  `waive(<cp>): <difference> — <reason>` to the plan Notes. Only the human creates
  waivers.
- **Doesn't address it** → the checkpoint stays open; say it's waiting on them.

**Batch** (`review`, or the end of `--auto`): the same report for each `green` row. The
edits-after-gates check uses the last row's `GATED`, since later rows changed code by
design. Feedback becomes one fix round on the current tree: `RS snap <slug>/fix-<n>/base`,
fix, B1–B3 against that base. Then the batch again.

### B5: Lock
Row → `approved`. Then offer the commit:
1. `RS stage BASE`, plus these files under `.claude/ratchet/`: `plans/<slug>.md`,
   `plans/<slug>.reference.md`, `learnings.md`, `architecture.md`, `config.json`,
   `.gitignore`.
2. `git commit` with the subject `ratchet(<slug>): <cp> <title>` and one line per gate in
   the body.

Commit only with the user's OK, given here or as a standing "commit each one". Under
`--auto`, a standing OK commits at `green`. After a commit, run `RS drop <slug>/<cp>`.

Then, once the commit is settled (made, declined, or covered by a standing OK):
- **With `--relay`**, and rows still `todo` or `red`: hand over. Run
  `RS baton <slug> continue|stop "<start>" ["<line>"...]`, where:
  - `continue` is for an `--auto` run, `stop` for an interactive one.
  - `<start>` is the resume command and next step, such as
    `/ratchet run <slug> --auto  (next: cp3 → B0)`.
  - Each `<line>` is something not on disk: a standing OK, an escalation or dispute
    still open. Write nothing that the plan or `EV` already records.

  End your turn with its marker as the last line. The relay mod then resets the context
  to the baton and, on `continue`, starts the next run.
- **Without `--relay`**: interactive, name the next checkpoint and stop. `--auto`: go
  to B0 for the next one.

## End of plan

Print `| cp | checkpoint | status | B1 | B2 | B3 rounds | human |`. Then plainly state
every `error`, spent cap and unverified human gate. Run `RS drop <slug>` and
`RS baton <slug> clear`. If the repo uses rinse, its review and manual checks weren't
gates, so suggest `/rinse:rinse` once.

## State at invocation

This is a snapshot taken at invocation, kept last on purpose. The files are the source of
truth: re-read them whenever you resume.

```!
test -f .claude/ratchet/config.json && { echo '[ratchet] config:'; cat .claude/ratchet/config.json; } || echo '[ratchet] no config yet — first run'
grep -H '^| cp' .claude/ratchet/plans/*.md 2>/dev/null || echo '[ratchet] no plans yet'
test -f .claude/ratchet/learnings.md && { echo '[ratchet] learnings:'; cat .claude/ratchet/learnings.md; } || echo '[ratchet] no learnings yet'
```
