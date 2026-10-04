# ratchet

A plan-and-verify workflow for Claude Code. It started from Shopify's
[Helix](https://shopify.engineering/helix).

The rule: **an attempt can be wrong. It cannot lock until it is right.** The next
checkpoint does not start before the current one locks.

```
/ratchet <goal>              grill, write the documents, roast, cut checkpoints, approve, run
/ratchet fix <bug or log>    reproduce, catch it in a test, fix, replay the reproduction
/ratchet continue [--auto]   run the next checkpoint through the gates
/ratchet review              the human gate for rows that --auto took to green
/ratchet status              each plan's table
/ratchet verify              run the repo's checks on what changed
/ratchet handover | resume   pass the work to the next session
/ratchet why <question>      why the code is this way
/ratchet dream               propose learnings from past runs
```

`/ratchet` runs only when you call it, because one checkpoint costs 5 to 8 agent runs.
Six parts also start alone, when the request fits them:

| Skill | Starts when |
| --- | --- |
| `ratchet:grill` | you ask to be grilled, and when a plan starts |
| `ratchet:roast` | you ask for a roast of a plan, a design or a diff |
| `ratchet:verify` | a change is finished, or you ask to verify or check it |
| `ratchet:why` | you ask why code is the way it is |
| `ratchet:handover` | the context is nearly full, or you ask to hand over |
| `ratchet:resume` | you ask to continue from a handover |

Ratchet replaces five older plugins: rinse (verify), snare and sniff (fix), baton
(handover and resume) and trail (why). It still reads their files: `.claude/rinse.json`,
`.claude/sniff.json` and the handovers in `.claude/handovers/`.

## Tracks

| Track | For | Documents |
| --- | --- | --- |
| fix | a bug or a regression | a design log with current, expected and unchanged behaviour |
| small | 1 or 2 checkpoints | a design log with requirements |
| full | 3 to 8 checkpoints | a PRD, a spec, a design log, and ADRs for durable decisions |

The documents go in `docs/changes/NNNN-<slug>/`. They use the
[design log](https://www.wix.engineering/post/why-i-stop-prompting-and-start-logging-the-design-log-methodology)
method: write first, answer the questions inline, freeze after approval, and add results
at the end. Requirements use [EARS](https://alistairmavin.com/ears/), and each one names
how it is checked: a test, the visual gate, a smoke check or a device check. The text
follows STE-lite, a subset of ASD-STE100: short sentences, active voice, simple tenses.
`RS doclint` and `RS stelint` check the documents.

## The gates of a checkpoint

A workflow runs gates B0 to B3. Code decides each verdict from command output. A haiku
relay agent runs one `RS` command and returns its JSON, and code checks its nonce. An
agent that says "done" makes a claim, not a verdict.

| Gate | Passes when |
| --- | --- |
| B0 spec | The tests fail on an assertion or a stub, not on a compile error. Each test name starts with its requirement ID. The test files are pinned. |
| B1 behaviour | The pinned tests pass, nothing new fails, and the pins did not change. Then the smoke checks pass. |
| B2 visual | No difference above the tolerance. Differences that the renderer causes never count. |
| B3 review | Two blind reviewers. A break finding blocks only when its proof command reproduces it. An arch finding blocks only when it cites a rule ID. The rest is advice for you. |
| B4 human | You approve in your own words. A problem you report becomes a learnings entry. A bare "go" is recorded as unverified. |
| B5 lock | The snapshot is taken, and the commit follows your standing order: after each lock, in one batch, or ask. |

Each gate stops at its cap. Then you decide. The implementer moves to a stronger model
from round 4.

## Learning

- `learnings.md` holds numbered rules, each with a scope, a check, a source and
  counters. The spec and implement agents get each active rule. The reviewers get only
  the rules whose scope matches the changed files.
- A dream reads past runs and proposes 3 changes or fewer, each with evidence. It runs
  each night through launchd, or when you ask. You approve each item.
- Once a week, a dream can propose one change to an agent prompt. An eval replay must
  show no regression, and you decide.

## Safety

- Pinned tests: only an amendment changes them. `RS check` finds edits, and `RS restore`
  reverses them.
- While a run is active, the guard mod stops subagents from `git stash`, `reset --hard`,
  `checkout --`, `clean`, `commit`, `push` and `--no-verify`.
- No commit before your approval. No push without your OK.
- `caffeinate` keeps the Mac awake during a run.

## Context

The lead stays thin. The workflow does gates B0 to B3, and the lead reads only short
summaries. After each lock, the relay mod resets the context to a minimal baton. A status
line shows `ratchet cp3 · B1 r2 · 4m`. den draws the workflow's agents from
`.claude/ratchet/live.json`.

## What lands in the repo

| Path | What |
| --- | --- |
| `docs/changes/NNNN-<slug>/` | the change documents |
| `docs/architecture.md` | the rules that the reviewers use, with IDs |
| `.claude/ratchet/config.json` | how the gates run (see `references/config.md`) |
| `.claude/ratchet/plans/` | the checkpoint tables |
| `.claude/ratchet/learnings.md` | the rules from your feedback |
| `.claude/ratchet/evidence/` (gitignored) | the proof of each gate |

`references/contracts.md` defines each command and file.

## Enable it

The `skillz` marketplace installs from GitHub, so push first:

```
claude plugin marketplace update skillz
claude plugin install ratchet@skillz
```

Restart Claude Code in the project, then run `/ratchet <goal>`. To try a checkout without
a push: `claude --plugin-dir <path to plugins/ratchet>`.

## Sources

- Helix (Shopify) and grill-me (Matt Pocock).
- The design log (Yoav Abrahami, Wix), EARS (Alistair Mavin), MADR and ASD-STE100.
- The adversarial review patterns of BMAD and compound-engineering.

ratchet 2.0's own design log is
`docs/changes/0001-ratchet-2/design-log.md`.
