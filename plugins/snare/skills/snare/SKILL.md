---
name: snare
description: >-
  Reproduction-driven, red→green bugfix loop where the reproduction is the spec.
  Reproduce the bug locally and confirm it FIRST, capture it in a failing test
  (red), write the smallest root-cause fix (green), then replay the exact same
  reproduction 1:1 to prove it's gone. Use whenever fixing a reported bug, chasing
  a regression, told something "is broken" / "errors when…" / "worked before",
  or the user wants a fix that's actually verified rather than a hopeful patch.
  Not for greenfield features or pure refactors where there's no bug to reproduce.
---

# Snare

Reproduce a reported bug, capture it in a failing test, fix the root cause, then
replay the identical reproduction to prove it's gone. Work the five steps **in
order** — do not skip ahead, even under pressure to "just patch it."

## 1. Run the flow locally

Get the affected code path running locally the way the bug is hit.

- Identify the entry point: a CLI command, an HTTP request, a UI interaction, a
  function call, a test harness.
- Confirm you can run the flow at all before claiming anything about the bug.
- Record the **exact** invocation verbatim — command, inputs, env, fixtures.
  This recipe is what step 5 replays.

## 2. Confirm reproduction of the issue

Observe the bug actually happening. Do not proceed on a hypothesis.

- Run the recorded flow and capture the concrete failure — the error, the wrong
  output, the bad state — with its real text/values, not a paraphrase.
- Compare against the expected behavior so the gap is unambiguous.
- **If you cannot reproduce it, stop.** Report what you tried and what you saw,
  and ask for the missing inputs (version, data, config, exact steps).

## 3. Add a test — red team

Capture the bug in an automated test that fails *because of this bug*.

- Write it at the tightest level that still exercises the real defect (unit if
  the bug is local; integration/e2e if it only appears across the flow).
- Assert the **correct** expected behavior, so the test fails today.
- Run it and confirm it fails **red** for the *right reason* — the actual bug,
  not a typo or setup error.

Only if an automated test is genuinely impractical (no harness, untestable I/O,
a flaky external dependency): say so explicitly and use a **scripted manual
reproduction** — the exact commands/inputs from step 1 plus expected vs. actual
output — as the red/green check instead. An automated test is what stops the
bug from silently returning later.

## 4. Write a fix — green team

Make the red test pass with the smallest change that addresses the root cause.

- Fix the cause, not the symptom; do not special-case the test's inputs.
- Confirm the new test is **green**.
- Run the surrounding/existing test suite and confirm no new reds.

## 5. Replay the same flow 1:1

Re-run the **exact** reproduction recorded in step 1, unchanged — same command,
same inputs, same env, same fixtures. A different flow is not a confirmation.

- Confirm the original failure no longer occurs and the expected behavior is
  now observed.
- If it still reproduces, the fix is incomplete: return to step 4 (or step 2 if
  your understanding of the bug was wrong). Loop until the 1:1 re-run is clean.

Report the recorded reproduction recipe, the test you added, the fix, and the
before/after of the 1:1 re-run. If any step was not completed, say so plainly
rather than declaring success.
