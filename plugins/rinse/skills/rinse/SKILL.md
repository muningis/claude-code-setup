---
name: rinse
description: >-
  Verification loop for work that was just done: run the repo's checks (typecheck,
  lint, tests, project rules), fix what fails, re-run the whole set, then hand the
  user the checks only a human can confirm. The check set is detected once and
  cached to .claude/rinse.json. Use after finishing a change, before declaring
  anything done or ready to commit, when asked to verify or check work, or at the
  end of another skill's work. Not for hunting an unknown bug — use snare.
---

# Rinse

Run the repo's checks against what changed, fix what fails, re-run, then defer to the
user for what can't be checked automatically.

Optional `$ARGUMENTS`: a check `id` to run alone, a path to restrict to, `--all` to
ignore `when` filters, `--refresh` to re-detect the check set.

## 0 — Load the check set

```!
cat .claude/rinse.json 2>/dev/null && echo '[rinse: config HIT — use the JSON above unless --refresh was passed]' || echo '[rinse: config MISS — no .claude/rinse.json; detect the checks, ask once, then write it]'
```

- **HIT** and no `--refresh` → use it, go to Step 1.
- **MISS**, invalid JSON, or `--refresh` → Step 2 first. If you weren't in the repo
  root, Read `.claude/rinse.json` directly — it may be a false miss.

If the config wasn't written by the user in this repo (a fresh clone), show its `run`
strings and confirm once before executing them. It's a repo file; it can carry
arbitrary commands.

## 1 — Scope

```bash
git rev-parse --verify HEAD >/dev/null 2>&1 \
  && git diff --name-only HEAD \
  || git diff --name-only --cached
git ls-files --others --exclude-standard
```

The `HEAD` guard matters: in a repo with no commits `git diff HEAD` errors, and an
errored command looks identical to an empty diff.

A check runs if a changed file matches one of its `when` globs; a check without `when`
always runs; `--all` runs everything. If you can't determine what changed — not a git
repo, no `git` — run every check rather than none.

State the scope in one line before executing: what's running, what was skipped, why.
Stop only if the working tree is genuinely clean.

## 2 — First run in a repo: detect, ask once, write it

Only on a cache MISS or `--refresh`.

1. **Infer the checks from the project**, read-only. Prefer commands the repo already
   defines — its manifest scripts, task runner, tooling config — over any you compose
   yourself. What CI runs is the strongest signal: that set is what the repo already
   treats as "must pass", and rinse's job is to catch it before CI does.

2. **Confirm the automated set** with one AskUserQuestion, pre-filled from what you
   found.

3. **Ask what a human has to check.** Detection cannot find `manual` checks — they
   exist because no command covers them. Ask plainly (visual/responsive, a real
   device, an email that must arrive, a deploy smoke test) and record the answer.
   Never invent one; if they say none, write none.

4. **Write `.claude/rinse.json`**, creating `.claude/` if needed.

```json
{
  "version": 1,
  "maxAttempts": 3,
  "checks": [
    { "id": "types", "kind": "command", "run": "bun run check-types",
      "when": ["**/*.ts", "**/*.tsx"], "autofix": true },
    { "id": "lint", "kind": "command", "run": "bun run lint", "autofix": true },
    { "id": "tests", "kind": "command", "run": "bun test", "autofix": true },

    { "id": "log-hygiene", "kind": "review",
      "rule": "Every error log includes the request ID and never the request body or headers.",
      "when": ["src/server/**/*.ts"], "autofix": true },

    { "id": "mobile-nav", "kind": "manual",
      "instruct": "Open http://localhost:5173 at 375px wide and check that the nav collapses to a hamburger with no text overflow.",
      "when": ["app/ui/**", "**/*.css"] }
  ]
}
```

| Field | Meaning |
| ----- | ------- |
| `kind: command` | Run `run`. Non-zero exit is a fail. |
| `kind: review` | No command exists. Read the changed code, judge it against `rule`, report violations by file and line. |
| `kind: manual` | You cannot verify it. See Step 5. |
| `when` | Glob list; check runs only if the diff touches a match. Omit = always. |
| `autofix` | May you fix and re-loop? Never applies to `manual`. |
| `maxAttempts` | Fix rounds per check before stopping. Default 3. |

## 3 — Run the automated checks

`command` first, then `review`. Cheapest first — a typecheck failing in 3s saves a 90s
test run.

## 4 — Fix, then re-run the whole set

On a failure with `autofix: true`: fix the root cause, then re-run **every in-scope
check**, not just the one that failed — fixing the type error is how you break the
test. Repeat until the set is clean or `maxAttempts` is spent on one check.

With `autofix: false`: report and stop. That check is hands-off on purpose.

At `maxAttempts`: stop and report what you tried each round. Do not keep going.

Hard rules:

- Never edit `.claude/rinse.json` to make a check pass. If a check is genuinely wrong,
  say so and let the user decide.
- Never weaken a check: no deleting or skipping a failing test, no `eslint-disable` /
  `@ts-ignore` / `# type: ignore` added to silence a finding, no `--no-verify`, no
  loosening an assertion to fit current output.
- A check that can't run — missing script, tool absent — is `error`, not `pass`.
- Do not commit, push, deploy, or bump a version, even when everything is green.

## 5 — Manual checks, last

Only once every automated check is green.

List each in-scope `manual` check with its `instruct` text. **Then your turn ends.**
No summary, no next steps, and no Step 6 report — that comes after the user answers.

Do not use AskUserQuestion and do not offer pass/fail options. Judge the free-text
reply they give:

- **Confirms the check** → `CONFIRMED`; quote their words in the report.
- **Reports a problem**, including a qualified pass like *"works, but the logo sits 2px
  low"* → a failure with detail. Back to Step 4, then re-present the check.
- **Doesn't address it** — silence, "ok", a vague "looks good", an unrelated
  follow-up → `UNVERIFIED`. Say which checks are still pending.
- **Ambiguous which check they meant** → ask. An unambiguous blanket affirmation
  ("all three work") counts for all pending; a bare "looks good" does not.

## 6 — Report

| Check | Kind | Result | Attempts |
| ----- | ---- | ------ | -------- |
| types | command | pass | 2 |
| log-hygiene | review | pass | 1 |
| mobile-nav | manual | CONFIRMED — "collapses fine at 375, no overflow" | — |

Then what you fixed, and every `error`, `UNVERIFIED`, or exhausted check stated
plainly rather than glossed.
