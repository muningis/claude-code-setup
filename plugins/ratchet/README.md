# ratchet

A checkpoint workflow for Claude Code, modelled on Shopify's
[Helix](https://shopify.engineering/helix).

The rule: **an attempt may be wrong. It may not lock until it isn't**, and the next
checkpoint doesn't start until the current one locks.

```
/ratchet plan <goal>         cut the goal into checkpoints, approve in plan mode, run cp1
/ratchet run [--auto]        push the next checkpoint through the gates (resumes mid-way)
/ratchet review              human gate for checkpoints that --auto locked at green
/ratchet status              every plan's checkpoint table
```

Use `/ratchet:ratchet …` if another `/ratchet` exists. Ratchet is user-invoked only: it
spawns 5–8 agent runs per checkpoint, so Claude never starts it on its own.

## Plan

1. **Config, once per repo.** Detected, then confirmed in one question:
   - the test commands
   - the visual mode (`null` / `render` headless / `browser` against a running app)
   - the reference oracle
   - the architecture doc the reviewers judge against (drafted if missing)
2. **Cut checkpoints.** Skeleton → one deliberately small slice → grow.
   - A few words each, each sized so the real code fits in context.
   - Each has a visual `target` and `scope`, so a skeleton can pass against a
     full-screen reference.
3. **Approve in plan mode.** The plan, architecture and config land in the repo only
   after you approve.

## The gates, per checkpoint

| | Who | Passes when |
| - | --- | ----------- |
| B0 spec | `ratchet:spec` | new test files exist, fail for the right reason, and are pinned (hash + copy) |
| B1 behavior | `ratchet:implement` builds; the main loop runs the tests | spec green, no failures beyond the pre-checkpoint baseline, pinned files intact |
| B2 visual | capture script → `ratchet:visual` | same-state captures, no code-fixable difference in scope; byte-identical captures skip the agent |
| B3 review | `ratchet:review-arch` ∥ `ratchet:review-break` (Opus), blind to each other | both approve in the same round; every finding fixed, B1/B2 re-run |
| B4 human | you, in your own words | you approve; each problem becomes a rule in `learnings.md` |

Every fix loop is capped by `maxRounds`. A capped or erroring gate blocks the row; it
never passes it. Commits per checkpoint happen only with your OK.

## Autonomy is earned

`--auto` defers the human gate: checkpoints lock at `green` and the run moves on.
- It only takes effect once `autoAfter` checkpoints (default 2) have your approval. The
  skeleton and first slice always get your eyes.
- Deferred checkpoints wait for `/ratchet review`. Your feedback there still becomes
  rules.

## Context resets, per checkpoint

Every checkpoint starts from a clean context. When one locks, ratchet writes a baton
of a few lines to `.claude/handovers/ratchet-<slug>.md`: where to resume, plus any
standing OKs or open items that aren't already on disk. Everything else (the plan,
the evidence, the snapshots) is on disk already. Then it ends its turn.

ratchet's relay mod (`hooks/relay.tsx`) then:
1. Runs `/compact`, answering it with the baton itself, so there's no LLM summary.
   The conversation becomes that one message.
2. Under `--auto`, starts `/ratchet run <slug> --auto` again. Interactively, it stops,
   and your next `/ratchet run` picks up from the baton.

The baton keeps baton's handover format, so `/baton:resume` reads it too.
- The mod marks the run by adding `--relay` to it; without the mod (mods off,
  headless, desktop), ratchet runs in one context as before.
- It stops relaying when a baton repeats (no progress), or after 30 relays in a
  session.
- `"relay": false` in `config.json` turns it off.

## What lands in the repo

| `.claude/ratchet/…` | |
| --- | --- |
| `config.json`, `architecture.md` | how the gates run; what the reviewers enforce |
| `plans/<slug>.md`, `<slug>.reference.md` | the checkpoint table; what the reference does |
| `learnings.md` | your feedback as rules, read by every agent: the compounding part |
| `evidence/` (gitignored) | per-gate proof: logs, captures, verdicts, your quoted approval |

Snapshots are git trees, anchored under `refs/ratchet/` while a checkpoint is open, so
each review sees exactly one checkpoint's diff. This works with uncommitted work and with
zero commits, and leaves your index alone. The mechanics are in
`skills/ratchet/scripts/ratchet.sh`.

## Enable it

The `skillz` marketplace installs from GitHub, so push first:

```
git push                                  # in claude-code-setup
claude plugin marketplace update skillz
claude plugin install ratchet@skillz      # all projects (user scope)
#   …or, inside one project only:
claude plugin install ratchet@skillz --scope project
```

Restart Claude Code in the project, then run `/ratchet plan <goal>`.

To try it without pushing, point a session at the checkout:
`claude --plugin-dir ~/workspace/code/muningis/claude-code-setup/plugins/ratchet`.
