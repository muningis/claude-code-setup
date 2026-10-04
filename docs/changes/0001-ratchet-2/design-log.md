---
type: design-log
track: small
change: 0001-ratchet-2
status: draft
---

# ratchet 2.0

## Decisions for the implementer

- Code decides each gate. The workflow engine runs B0 to B3. An agent's claim is never a
  verdict.
- A finding blocks only with evidence: a reproduced proof (break) or a cited rule ID
  (arch).
- Tests are few. Each test name starts with its requirement ID.
- The ported flows (verify, fix, handover, why) have no model trigger. The original
  plugins stay as they are.
- Each prose file follows STE-lite. Comments follow `ARCH-COMMENTS`.

## Background

Ratchet 0.2 ran 16 real checkpoints in epstein-against-humanity. Seven research tracks
studied that run, 151 local sessions, and similar tools. The notes are in Basic Memory:
"ratchet 2.0 research and design decisions (2026-10-04)".

## Problem

The lead used half of the cost, mostly on idle wake-ups. Review loops took 68% of the
active time, and no finding was ever rejected. The spec wrote 39 tests per checkpoint,
and 7 defects still escaped every gate.

## Prior art

- `plugins/ratchet/skills/ratchet/scripts/ratchet.sh`: git-tree snapshots and pins.
- `plugins/ratchet/hooks/relay.tsx`: the context reset at each checkpoint.
- `~/workspace/code/muningis/raccoon/src/workflows/raccoon-run.ts`: a workflow where code
  decides from a deterministic verify.

## Requirements

- **FR-001** (test): When a gate command finishes, the engine shall take the verdict from the RS output only.
- **FR-002** (test): When a relay result has a different nonce, the engine shall stop with harness-error.
- **FR-003** (test): If a break finding has no reproduced proof, then the triage shall mark it advisory.
- **FR-004** (test): If an arch finding cites no existing rule ID, then the triage shall mark it advisory.
- **FR-005** (test): When a B1 round passes 3, the engine shall use the escalation model.
- **FR-006** (test): When a pinned test file changes, the b1 gate shall restore it and fail.
- **FR-007** (test): When the spec run shows a compile error, the b0 gate shall fail.
- **FR-008** (test): While a run is active, the guard shall deny destructive git commands from subagents.
- **FR-009** (test): The stelint check shall block a sentence that has more than 25 words.
- **FR-010** (test): If an approved document body changes, then the doclint check shall block it.
- **FR-011** (smoke): When the human runs `/ratchet <goal>`, the plugin shall produce documents and a plan table that pass doclint.
- **FR-012** (smoke): When a dream runs on recorded evidence, the dream shall propose 3 items or fewer, each with evidence.
- **FR-013** (test): When a check fails in the baseline and in b1, the b1 gate shall not fail on it.
- **FR-014** (test): When a state file changes during a run, the b1 gate shall stop with an error and keep the change.

## Questions and answers

Q1: Which plugins fold into ratchet?
A: rinse, snare and sniff, baton, and trail. The originals keep working.

Q2: What happens to the original plugins?
A: They stay in the marketplace and keep working. Ratchet's ports have no model trigger.

Q3: Are the raccoon agents in scope?
A: No. The raccoon repo stays out of 2.0.

Q4: How far does the dream go?
A: A nightly local run proposes 3 items or fewer. A weekly run proposes one prompt change.
The human approves each item.

## Design

The plan file is `~/.claude/plans/composed-jumping-cerf.md`. In short:
- One plugin with three skills: the `ratchet` router, `grill` and `roast`.
- The workflow `workflows/checkpoint.js` runs B0 to B3. A haiku relay agent runs one `RS`
  gate command and returns its JSON. Code checks the nonce and decides.
- `RS` adds state, gates, proofs, size, timeouts, live status, metrics, linters and
  dream commands. `references/contracts.md` defines each one.
- The guard mod stops destructive git while a run is active. den reads `live.json`.
- Learnings v2 entries have IDs, scopes and counters. The dream proposes changes to them.

## Plan

| Phase | Result |
| --- | --- |
| P0 | Cost baseline of 0.2.1 |
| P1 | Walking skeleton: engine, gates b0, b1 and b3, guard, live status |
| P2 | Gate quality: proofs, rule IDs, test budget, visual tolerance, standing orders |
| P3 | Planning: router, grill, roast, documents, linters |
| P4 | Ported flows: verify, fix, handover, why |
| P5 | Dream: harvest, reflect, curate, nightly agent, weekly eval |
| P6 | Release 2.0.0 |

## Trade-offs

- **An LLM validator for findings.** Rejected for 2.0. Proofs and rule IDs are
  deterministic and cheaper. Reviewers inflate severity when severity alone decides.
- **One design log for every track.** Rejected. The user asked for a PRD and a spec, so
  the full track keeps them, with word budgets.
- **Remove the original plugins.** Rejected by the user. Both stay.

## Results

### 2026-10-04 · P0 baseline of 0.2.1

The data is the epstein-against-humanity run, rows cp7 to cp10, which started after 0.2.1
landed. Four rows give ranges, not statistics. The scripts are in `/tmp/p0-baseline/`.

| Measure, per checkpoint | 0.2.1 (mean) | Before 0.2.1 (median) | 2.0 target |
| --- | --- | --- | --- |
| Total cost | $9.30 | about $11 | below $9.30 |
| Lead cost | $3.80 | $5.69 | $1.50 or less |
| Lead wake-ups | 12 | 14 | 3 or fewer |
| Lead context, mean / peak | 107K / 160K | 369K / 396K | lower, also at the human gate |
| Handover resets that work | 3 of 4 | - | 4 of 4 |
| Idle agent minutes after a lock | 0 | 152 | 0 |
| Rounds B1 / B2 / B3 | 3 / 3 / 2 | 4 / 2 / 2 | 3 / 3 / 2 or fewer |

- The context reset cut the lead context and the lead cost. The wake-ups, the rounds and
  the gate time did not change.
- One reset failed, because a hand-typed marker had no path. The relay now accepts the
  slug alone.

### 2026-10-04 · One plugin

The human reversed the trade-off "Both stay". Ratchet is now the one workflow plugin.

- rinse, snare, sniff, baton and trail are gone from the marketplace.
- `verify`, `why`, `handover` and `resume` are ratchet skills that start alone when a
  request fits them. Each skill reads its reference. Plans and the fix track start only
  when the human types them.
- Ratchet still reads the old files: `.claude/rinse.json`, `.claude/sniff.json` and the
  handovers that baton wrote.
- Step 1 of `plan.md` treats a config with only `checks` as no config, because verify
  can write such a config.

### 2026-10-04 · 2.1: the dream reads every session

The human asked the dream to read all sessions in `~/.claude`, not one registered repo.
Only one repo had ratchet evidence, and most work never goes through a ratchet run.

- The harvest reads `~/.claude/projects/` after the last dream. It takes the human
  prompts with tags, the agent friction, and the ratchet evidence of those repos.
- Approved rules go to `~/.claude/rules/dream/` (each session, or matching files with
  `paths`), to the auto-memory of one project, or to a repo's `learnings.md`.
- The reflection runs sealed: `--safe-mode --restricted --no-session-persistence`, in
  the bundle folder. A live check under launchd proved these flags and the login.
- Code counts the recurrence from the cited harvest items. It never uses a model count.
- `repos.json`, `dream register` and the per-repo `dream` config are gone.
