---
name: ratchet
description: Plan a goal as small checkpoints and build each one through gates (red tests, behaviour, visual, two blind reviewers, your approval). Also fixes bugs, verifies, hands work over and learns from past runs.
argument-hint: "<goal> | fix <bug or log> | continue [--auto] | status | review | verify | handover | resume | why <question> | dream"
disable-model-invocation: true
allowed-tools: Bash(bash ${CLAUDE_SKILL_DIR}/scripts/ratchet.sh *)
---

# Ratchet

An attempt can be wrong. It cannot lock until it is right. The next checkpoint does not
start before the current one locks.

## Route the request

Read `$ARGUMENTS`. Pick one row. When the request is not clear, ask one question.

| Request | Read and follow |
| --- | --- |
| A goal or a feature | `references/plan.md` |
| `fix …`, a bug, an error or a log | `references/fix.md` |
| `continue`, `run`, or nothing while a plan has open rows | `references/run.md` |
| `review` | `references/run.md`, section "Batch review" |
| `status`, or nothing while no plan exists | Print each plan table and the next step. With no plan, ask for a goal. |
| `verify` | `references/verify.md` |
| `handover` or `resume` | `references/handover.md` |
| `why …` | `references/why.md` |
| `dream` | `references/dream.md` |

All references are in `${CLAUDE_SKILL_DIR}/references/`. `contracts.md` defines each
command and file. `config.md` defines the config. `docs.md` defines the change
documents.

**Before you route:** when the state block below shows dream proposals, show them first,
as `references/dream.md` says in "Review". Then continue with the request. Skip this when
`$ARGUMENTS` has `--relay`: an automatic run must not wait for a reply.

## Invariants

1. **Code decides.** A gate passes only when `RS` returns `"verdict": "pass"`. An agent
   that reports success makes a claim, not evidence.
2. **Never weaken a check.** Do not delete, skip, focus or loosen a test. Do not
   regenerate snapshots to get a pass. Do not add `@ts-ignore`, `eslint-disable`,
   `type: ignore` or `noqa`. Do not use `--no-verify`. Do not edit the config, the
   architecture, the learnings or a verdict to get a pass.
3. **Pins hold.** Only an amendment changes a pinned test. `RS check` finds changes, and
   `RS restore` puts the pinned files back.
4. **A gate that cannot run is `error`.** It is never a pass.
5. **Caps hold.** Each gate stops at its cap in `config.caps`. Then the human decides.
6. **Paths, not content.** Give agents absolute paths. Never paste a diff or a log into
   a prompt.
7. **No commit before approval.** After approval, `standing.commit` decides. Never push
   without the human's OK.
8. **The human gate is free text.** Do not use AskUserQuestion for it. Do not offer
   pass/fail options.
9. **No `cd`.** Use absolute paths. Write the full `RS` command each time. Never keep it
   in a shell variable, because zsh does not split it.
10. **Keep the lead thin.** The engine runs gates B0 to B3. Read `RS` summaries. Open an
    evidence file only when you must decide something.

`RS` = `bash ${CLAUDE_SKILL_DIR}/scripts/ratchet.sh`. The engine is the plugin
workflow `ratchet:checkpoint`, from `${CLAUDE_SKILL_DIR}/../../workflows/checkpoint.js`.

## State at invocation

This is a snapshot from when the skill started. The files are the truth. Read them again
when you resume.

```!
test -f .claude/ratchet/config.json && { echo '[ratchet] config:'; head -c 1500 .claude/ratchet/config.json; echo; } || echo '[ratchet] no config yet'
find .claude/ratchet/plans -name '*.md' ! -name '*.reference.md' -exec grep -H '^| cp' {} + 2>/dev/null || echo '[ratchet] no plans yet'
test -f .claude/ratchet/live.json && { echo '[ratchet] live:'; cat .claude/ratchet/live.json; echo; }
find .claude/ratchet/dreams -name proposal.json -exec sh -c 'test -f "$(dirname "$1")/review.json" || echo "[ratchet] dream proposal: $1"' _ {} \; 2>/dev/null | head -3
find .claude/handovers -name 'ratchet-*.md' 2>/dev/null | sed 's/^/[ratchet] baton: /'
true
```
