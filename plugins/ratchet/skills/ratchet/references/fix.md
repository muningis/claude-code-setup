# Fix

The fix track. The reproduction is the spec. Reproduce the bug first. Capture it in a
test that fails for the right reason. Fix the cause. Then run the same reproduction again,
without change, to prove that the bug is gone. This is the snare and sniff flow, inside
ratchet.

Do the steps in order. Do not skip ahead to "just patch it".

## 1. Intake

**From a report:** take the steps, the inputs and the error from the human.

**From logs** (`fix logs`, or the human points at an error in production):
1. Find the log source: `fix.logs` in the config, or a legacy `.claude/sniff.json`.
   With neither, look in the repo without changes: deploy manifests, error tracker SDKs,
   container config, log folders. Confirm the source with one AskUserQuestion. Write it
   to `fix.logs` in the config, with the time from `date -u +%FT%TZ`.
2. Get the logs. Keep only the errors, with the lines around them.
3. With several different errors, list them, newest or most frequent first, and let the
   human choose. With no errors, say so. Do not invent an error.

## 2. Reproduce locally

1. Find the entry point: a command, a request, a UI action, a function call.
2. Run the flow. Write down the **exact** recipe: the command, the inputs, the
   environment and the fixtures. Step 6 runs this recipe again.
3. Watch the bug happen. Record the real error text or the wrong value.
4. **When you cannot reproduce it, stop.** Report what you tried, and ask for the inputs
   that are missing.

## 3. Write the design log

Write `docs/changes/NNNN-<slug>/design-log.md` with `track: fix` (see `docs.md`):
- `### Current behaviour`: the failure, with the real text.
- `### Expected behaviour`: one requirement, `FR-001 (test)`.
- `### Unchanged behaviour`: the behaviour near the bug that must not change, as `UB`
  requirements.
- The recipe, in `## Design`.

Run `RS doclint` and `RS stelint` on it.

## 4. Plan one row

Add a plan `.claude/ratchet/plans/<slug>.md` with one row: `kind: fix`, `reqs` with the
`FR` and `UB` IDs, and a small `est`. Show the recipe and the row in 8 lines or fewer.
Continue when the human does not object. A fix needs no plan mode.

## 5. Run the gates

Follow `run.md` from step 3. For a `fix` row:
- **B0:** the spec agent writes the test that reproduces the bug. It must fail now, on an
  assertion. Because the base is the code before the fix, this proves that the test
  catches the bug.
- **B1:** the implementer makes the smallest change that fixes the cause. Do not
  special-case the inputs of the test.
- When no automated test can reach the bug, say so. Then the recipe becomes a `smoke`
  check, and it is the gate instead.

## 6. Replay the recipe, before the human gate

Run the recipe from step 2 again, without change: the same command, inputs, environment
and fixtures. A different flow is not a proof. Write the before and after output to
`EV/4-replay.md`.

When the bug still happens, the fix is not complete. Run `RS decide <slug> <cp> "<what
still fails>" --reopen b1`, and start the engine again.

Then do the human gate, `run.md` step 5. Show the recipe, the test, the fix and the
replay.
