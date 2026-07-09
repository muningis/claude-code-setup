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

Trap the bug before you fix it. The discipline of this skill is that **the
reproduction is the spec**: you do not trust a fix until the *identical* flow that
exposed the bug comes back clean. No reproducing → no fixing. No red test → no
green fix. No re-run of the same flow → not done.

Work the five steps **in order**. Do not skip ahead, even under pressure to "just
patch it."

## 1. Run the flow locally

Get the affected code path running on the local machine the way the bug is hit.

- Identify the entry point: a CLI command, an HTTP request, a UI interaction, a
  function call, a test harness.
- Establish a baseline: confirm you can run the flow at all before claiming
  anything about the bug.
- Write down the **exact** invocation (command, inputs, env, fixtures). This exact
  recipe is what you will replay in step 5 — record it verbatim now.

## 2. Confirm reproduction of the issue

Observe the bug actually happening. Do not proceed on a hypothesis.

- Run the recorded flow and capture the concrete failure: the error, the wrong
  output, the bad state — with its real text/values, not a paraphrase.
- Compare against the expected behavior so the gap is unambiguous.
- **If you cannot reproduce it, stop.** Report what you tried and what you saw.
  Ask for missing inputs (version, data, config, exact steps). A fix for a bug you
  never reproduced is a guess.

## 3. Add a test — red team

Capture the bug in an automated test that fails *because of this bug*.

- Write the test at the tightest level that still exercises the real defect (unit
  if the bug is local; integration/e2e if it only appears across the flow).
- Assert the **correct** expected behavior, so the test fails today.
- Run it and confirm it **fails red** — and that it fails for the *right reason*
  (the actual bug), not a typo or setup error. A test that was never red proves
  nothing.

If the bug genuinely resists an automated test (no harness, untestable I/O, a
flaky external dependency), say so explicitly and fall back to a **scripted manual
reproduction** — the exact commands/inputs from step 1 plus the expected vs. actual
output — and treat that script as the red/green check. Reach for this only when an
automated test is truly impractical; an automated test is what stops the bug from
silently returning later.

## 4. Write a fix — green team

Make the red test pass with the smallest change that addresses the root cause.

- Fix the cause, not the symptom; avoid special-casing the test's inputs.
- Run the new test and confirm it is **green**.
- Run the surrounding/existing test suite and confirm you did not break anything
  else (no new reds).

## 5. Repeat the same flow 1:1 — confirm it's gone

Re-run the **exact** reproduction from steps 1–2, unchanged.

- Use the verbatim invocation, inputs, env, and fixtures you recorded in step 1 —
  same command, same data. This is the whole point: a different flow is not a
  confirmation.
- Confirm the original failure no longer occurs and the expected behavior is now
  observed.
- If it still reproduces, the fix is incomplete: return to step 4 (or step 2 if
  your understanding of the bug was wrong). Loop until the 1:1 re-run is clean.

## Done means

- [ ] Bug was reproduced locally before any fix (step 2).
- [ ] A test was added that failed red because of this bug (step 3).
- [ ] The fix makes that test green and breaks no existing tests (step 4).
- [ ] The **same** reproduction flow, replayed unchanged, is now clean (step 5).

Report the recorded reproduction recipe, the test you added, the fix, and the
before/after of the 1:1 re-run. If any box is unchecked, say so plainly rather
than declaring success.
