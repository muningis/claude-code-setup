# Verify

Run the repo's checks on what changed. Fix what fails. Run the full set again. Then give
the human the checks that only a human can do. This is the rinse flow, inside ratchet.

Options in `$ARGUMENTS`: a check `id` to run alone, a path to limit the scope, `--all` to
ignore the `when` globs.

## 1. The check set

Use the checks in `.claude/ratchet/config.json` whose `gate` list has `verify`, and all
checks of kind `review`, `manual` and `device`.

- When the config has no such checks, but `.claude/rinse.json` exists, use its checks.
- When neither exists, find the checks without changes:
  1. What CI runs is the best signal. Then read the manifest scripts and the tool config.
  2. Confirm the set with one AskUserQuestion.
  3. Ask, in plain words, what only a human can check: a layout, a real device, an email
     that must arrive. Never invent a manual check.
  4. Write the result to `checks` in the config.
- In a clone that the human did not set up, show each `run` command, and confirm one
  time before you run it.

When the change has documents under `docs.root`, and `docs.ste` is not `off`, add
`RS stelint` and `RS doclint` on the changed documents.

## 2. Scope

```bash
git rev-parse --verify HEAD >/dev/null 2>&1 && git diff --name-only HEAD || git diff --name-only --cached
git ls-files --others --exclude-standard
```

The `HEAD` test is necessary: in a repo with no commits, `git diff HEAD` fails, and a
failure looks like an empty diff.

A check runs when a changed file matches its `when` globs. A check without `when` always
runs. When you cannot find the changed files, run all checks. Before you run, state the
scope in one line: what runs, what you skip, and why.

## 3. Run

Run the `command` checks first, the fastest first, with `RS exec --timeout <s> -- <run>`.
Then do the `review` checks: read the changed code and report each violation of the rule
by file and line.

## 4. Fix and run again

When a check fails: fix the cause, then run **each** check in scope again. A fix for one
check can break another. Stop after 3 rounds on one check, and report what you tried in
each round.

- Never edit the config to get a pass. When a check is wrong, say so. The human decides.
- Never weaken a check (see the invariants in `SKILL.md`).
- A check that cannot run is `error`, not `pass`.
- Do not commit, push, deploy or change a version.

## 5. Human checks, last

Do this only after each automated check passes. List each `manual` and `device` check in
scope, with its `instruct` text. Then end your turn.

Judge the reply as free text:
- **It confirms the check:** `CONFIRMED`. Quote the words.
- **It reports a problem**, or passes with a "but": a failure. Go back to step 4, then
  show the check again.
- **It does not address the check** ("ok", a vague "looks good"): `UNVERIFIED`. Say which
  checks still wait. A clear answer for all ("all three work") confirms all of them.

## 6. Report

| Check | Kind | Result | Rounds |
| --- | --- | --- | --- |
| types | command | pass | 2 |
| keyboard | device | CONFIRMED: "field stays visible" | - |

Then list what you fixed. Name each `error`, `UNVERIFIED` check and check that ran out of
rounds. Do not hide them.
