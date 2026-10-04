# `.claude/ratchet/config.json`, version 2

Ratchet writes this file once per repo, after you approve the first plan. It is meant to
be committed.

```json
{
  "version": 2,
  "behavior": {
    "one": "bun test {files}",
    "all": "bun test",
    "timeout": 900,
    "failureKinds": {}
  },
  "checks": [
    { "id": "types", "kind": "command", "run": "bun run check-types",
      "when": ["**/*.ts", "**/*.tsx"], "gate": ["b1", "evidence", "verify"], "timeout": 300 },
    { "id": "lint", "kind": "command", "run": "bun run lint", "gate": ["b1", "verify"] },
    { "id": "keyboard", "kind": "device", "when": ["mobile/**"],
      "instruct": "Open each text field on a phone. The keyboard must not cover it." }
  ],
  "tests": { "globs": ["**/*.test.ts", "**/test/**"], "perRequirement": 3, "perCheckpoint": 20 },
  "size": { "prodLines": 400 },
  "visual": null,
  "review": { "proofTimeout": 120, "archPaths": [] },
  "caps": { "b1": 5, "b2": 3, "b3": 3 },
  "autoAfter": 2,
  "models": {},
  "standing": { "commit": "ask", "afterLock": [], "notify": true },
  "docs": { "root": "docs", "ste": "lite" },
  "relay": true,
  "fix": { "logs": null },
  "dream": { "nightly": false, "maxItems": 3, "budgetUsd": 2, "stacks": [] }
}
```

| Key | Meaning |
| --- | --- |
| `behavior.one` | Runs only the given test files. `{files}` is a list of shell-quoted paths, relative to the repo root. |
| `behavior.all` | Runs the full suite. |
| `behavior.timeout` | Seconds before `RS exec` stops a behavior command. |
| `behavior.failureKinds` | Optional regex lists that replace the defaults in `RS red-check`: `compile`, `stub`, `assert`. |
| `checks` | The checks for each gate. Each check has the fields in the next table. |
| `tests.globs` | Which changed files are tests. Other spec files are stubs. |
| `tests.perRequirement`, `tests.perCheckpoint` | The test budget. A spec over budget needs a reason. The net test delta through B3 is shown at B4. |
| `size.prodLines` | The production-line estimate that a row uses when it has no `est`. The size check is advisory. |
| `visual` | `null` for a product with no UI. Then gate 2 reads `n/a`. See below. |
| `review.proofTimeout` | Seconds for each `RS prove` run. |
| `review.archPaths` | Globs whose change makes a round structural. Then the architecture reviewer runs again. |
| `caps` | The rounds for each gate. Then the row needs a decision from you. |
| `autoAfter` | `--auto` keeps the human gate until this many rows are `approved`. `approved-unverified` rows do not count. |
| `models` | Optional model per role: `spec`, `implement`, `implementEscalate`, `visual`, `reviewArch`, `reviewBreak`, `relay`. |
| `standing.commit` | `ask`, `each` or `batch`. Ratchet asks you once, then keeps your answer. |
| `standing.afterLock` | Commands to run after each lock, for example an install or a server restart. |
| `standing.notify` | Send a push notification at B4, at a block and at an escalation. |
| `docs.root` | Where the change documents go. |
| `docs.ste` | `lite` (length rules block, style rules warn), `full` (all rules warn and length rules block) or `off`. |
| `relay` | Reset the context after each checkpoint. This needs ratchet's relay mod. |
| `fix.logs` | Where the fix track reads the logs: `{ source, retrieve, errorPattern, config, resolvedAt, notes }`. See `fix.md`. |
| `dream` | The learning loop: `nightly`, `maxItems`, `budgetUsd`, and `stacks` (the names of the stack libraries of this repo). See `dream.md`. |

## Checks

| Field | Meaning |
| --- | --- |
| `id` | A unique name. |
| `kind` | `command` runs `run`. `review` gives a rule to the architecture reviewer. `manual` and `device` give an instruction to you at B4. `smoke` runs `run` before B4. |
| `run`, `rule`, `instruct` | The command, the rule or the instruction. |
| `when` | Globs. The check applies only when a changed file matches. When there are no globs, the check always applies. |
| `gate` | Where a `command` check runs: `b1`, `evidence` (its output goes to the reviewers) and `verify`. The default is `["b1", "verify"]`. |
| `timeout` | Seconds. The default is `behavior.timeout`. |

## Migration

Ratchet reads older files and writes version 2 when you approve the next plan:

| Old | New |
| --- | --- |
| `maxRounds` | each value in `caps` |
| `maxDiffLines` | `size.prodLines`, as advice only |
| `behavior.extra[]` | `checks[]` with `kind: command` and `gate: ["b1", "verify"]` |
| `architecture` | `docs.root/architecture.md`. The old path still works. |
| `.claude/rinse.json` | its checks join `checks[]` |
| `.claude/sniff.json` | `fix.logs` (see `fix.md`) |

## `visual`

Gate 2 compares image files, because `ratchet:visual` can only read files. Each capture
writes a PNG to disk.

```json
{
  "mode": "render",
  "capture": "bun scripts/capture.tsx {target} {viewport} {out}",
  "reference": { "kind": "command", "capture": "bun scripts/capture.tsx --legacy {target} {viewport} {out}" },
  "viewports": [375, 1280],
  "tolerance": { "px": 4, "color": 8 }
}
```

| `mode` | How the capture is made |
| --- | --- |
| `render` | `capture` renders `{target}` headless to `{out}`. Use this when the UI renders without a running app. |
| `browser` | `capture` drives a real browser to `{url}`, sets the state of `{target}`, and saves a screenshot to `{out}`. Use this when the state needs a running app, real data or interaction. |

| Placeholder | Meaning |
| --- | --- |
| `{target}` | The row's `target`. The script maps it to a route, a story or a state. |
| `{viewport}` | One width from `viewports`. The capture runs once for each width. |
| `{out}` | An absolute PNG path. |
| `{url}` | Browser mode only: `visual.url` for the implementation, or the reference URL. |

**Tolerance.** The visual agent reports each difference with a numeric delta. The engine
applies `tolerance`:
- `missing`, `extra` and `text` differences always block.
- Other differences block only when the delta is above `tolerance.px` or
  `tolerance.color`.
- A difference that the agent marks `engine: true` never blocks. Such a difference
  comes from a different render engine, for example font metrics or anti-aliasing.

**Reference kinds.**

| `kind` | Where the reference image comes from |
| --- | --- |
| `url` | `capture` with `{url}` set to `reference.url`, for example a live legacy app. |
| `command` | Its own `capture` command, which renders the old implementation. |
| `dir` | `<path>/<target>@<viewport>.png`: designs or mockups that you exported. |
| `none` | No image. The agent judges against the row's expectation and the design rules. This gate is weaker, and the plan must say so. |

**Browser mode** adds `url`, an optional `setup` command (for example `bun run dev`), an
optional `ready` URL or command, and an optional `teardown`.
1. Before `setup`, check `url`. If it already answers, stop and ask. A stale server can
   serve old code.
2. Start `setup` in the background.
3. Poll `ready` for up to 60 seconds. If it does not answer, the gate result is `error`.
4. Restart the server after each fix round, unless it reloads by itself.
5. Stop the server when the checkpoint leaves B2 or the run stops.

**Determinism.** The capture must freeze data, the clock, randomness, animations,
transitions and the caret. Fonts must load before the capture. Before the first real
use, capture one target two times and compare the files with `cmp -s`. When the files
differ, fix the script before gate 2 counts.

**Regression.** The engine captures each earlier approved target again. It compares the
new capture with the last approved capture of the same engine. Only these same-engine
comparisons use exact goldens.
