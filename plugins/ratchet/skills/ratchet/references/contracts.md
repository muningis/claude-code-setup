# Contracts

This file defines every command, file and agent output that two parts of ratchet share.
To change a contract, change this file first. Then change both sides in the same commit.

## Paths

| Name | Path |
| --- | --- |
| `RS` | `bash ${CLAUDE_SKILL_DIR}/scripts/ratchet.sh` |
| `R` | `.claude/ratchet/` in the repo root |
| `PLAN` | `R/plans/<slug>.md` |
| `EV` | `R/evidence/<slug>/<cp>/` |
| `STATE` | `EV/state.json` |
| `LIVE` | `R/live.json` |
| `METRICS` | `R/metrics.jsonl` |
| refs | `refs/ratchet/<slug>/<cp>/{base,red,review,gated}` |

All paths in JSON are relative to the repo root, unless a field name ends in `Abs`.

## Plan table, version 2

```markdown
| id | checkpoint | kind | target | reqs | est | status | base |
| -- | ---------- | ---- | ------ | ---- | --- | ------ | ---- |
| cp1 | screen skeleton | harness | profile | FR-001 | 80 | todo | |
```

- `kind`: `harness`, `feature`, `refactor`, `fix` or `choice`.
- `target`: `-`, or a name that matches `[a-z0-9-]+`.
- `reqs`: a comma list of requirement IDs (`FR-001,FR-004`), or `-`.
- `est`: the estimated production lines, as an integer, or `-`.
- `status`: `todo`, `red`, `green`, `approved`, `approved-unverified`, `blocked` or
  `superseded`.
- A version 1 table (`| id | checkpoint | target | status | base |`) also parses. Then
  `kind` is `feature`, and `reqs` and `est` are `-`.
- A row is open when its status is `todo`, `red`, `green` or `blocked`.

## Command output

Each `RS` command that the engine calls prints one JSON object on stdout. The object is
1 KB or less. Details go to an evidence file, never to stdout.

```json
{
  "ok": true,
  "cmd": "gate b1",
  "nonce": "<the value of --nonce, or null>",
  "verdict": "pass",
  "summary": "12 checks pass; prod 140/150",
  "evidence": ".claude/ratchet/evidence/s/cp2/1-behavior-r2.txt",
  "sha256": "<hex digest of the evidence file>"
}
```

- `verdict` is `pass`, `fail` or `error`.
- The exit code is 0 for `pass`, 1 for `fail` and 2 for `error`.
- `error` means that the harness cannot run the gate, for example a missing tool or a bad
  config. It is never a pass.
- Each command adds its own fields to this object.

## State file

`STATE` holds the progress of one checkpoint. Only `RS` writes it.

```json
{
  "version": 2,
  "slug": "s",
  "cp": "cp2",
  "stage": "B1",
  "rounds": { "b0": 1, "b1": 2, "b2": 0, "b3": 0 },
  "epoch": 3,
  "open": { "blocking": ["cp2-B1-1"], "advisory": ["cp2-A1-2"] },
  "updated": "2026-10-04T10:00:00Z"
}
```

- `stage` is `B0`, `B1`, `B2`, `B3`, `B4`, `B5` or `done`.
- When `STATE` does not exist, `RS state` derives the stage from the row status:
  `todo` gives `B0`, `red` gives `B1`, `green` gives `B4`, `approved` gives `done`.

## `RS state <slug> [<cp>]`

When you do not give `<cp>`, the command uses the first open row.

Fields: `slug`, `cp`, `kind`, `target`, `reqs` (array), `est`, `status`, `stage`,
`rounds`, `epoch`, `refs` (`base`, `red`, `review`, `gated`: a SHA or null), `pins`
(`intact`, `changed`), `open`, `visual` (bool), `harnessError` (a string, or absent).

`ok` is false and `verdict` is `error` when the state cannot be read. `harnessError`
gives the reason.

## `RS gate <gate> <slug> <cp> --nonce <n> [--round <r>]`

Each gate updates `STATE`, writes its evidence and adds one line to `METRICS`.

### `b0`: the spec gate

Run this gate after the spec agent returns.

1. Find the spec set: the files that changed since `base`. Classify each file as a test
   or a stub, with `tests.globs`.
2. Run `behavior.one` on the test files. Classify each failure with `RS red-check`.
3. Trace: each case name contains a requirement ID from the row's `reqs`. Each ID in
   `reqs` that has coverage kind `test` has one or more cases.
4. Compare the case count with `tests.perRequirement` and `tests.perCheckpoint`.
5. Pin the test files. Snapshot `red`. Set the stage to `B1`.

Added fields: `cases`, `red` (`assert`, `stub`, `compile`, `runner`, `pass`: counts),
`trace` (`missing`, `unknown`), `budget` (`cases`, `limit`, `over`), `tests`, `stubs`.

The verdict is `fail` when `compile`, `runner` or `pass` is above zero, or when
`trace.missing` is not empty. For a `refactor` row, each case must pass.

### `b1`: the behavior gate

1. Run `RS check` on all pins. If a pinned file changed, restore it and fail.
2. Run each check with `"b1"` in its `gate` list, in order, when a changed file matches
   its `when` globs. Then run `behavior.all`. Each command runs through `RS exec` with
   its timeout.
3. Count production lines (`RS size --prod`) and compare them with the row's `est`. This
   result is advisory.
4. When a check fails, write the brief for the next round to `EV/1-brief-r<r+1>.md`.

Added fields: `checks` (`id`, `ok`, `ms`), `failing`, `pinsChanged`, `size` (`prod`,
`est`, `ratio`), `brief`.

### `b2-capture`: before the visual judgment

Run the impl and reference captures for each viewport, with `RS exec`. Then capture each
earlier approved target again, for the regression check.

Added fields: `images` (`impl`, `ref`, `viewport`), `identical` (bool: each impl and ref
pair is byte-identical), `regressChanged` (the targets whose new capture differs from
their last approved capture).

When `identical` is true and `regressChanged` is empty, the verdict is `pass`, and the
engine skips the visual agent.

### `b2`: after the visual judgment

The gate reads `EV/2-visual-r<r>.json` in the visual schema below. It applies
`visual.tolerance` (see `config.md`).

Added fields: `blocking`, `advisory`, `engine` (the count of engine differences).

The verdict is `pass` when `blocking` is empty.

### `smoke`: before the human gate

Run each check of kind `smoke` whose `when` globs match a changed file. When no smoke
check applies, the verdict is `pass` and `summary` says `no smoke checks`.

Added fields: `checks` (`id`, `ok`, `ms`), `failing`.

### `b3-prep`: before review

Write the patch since `base`, the tripwire output and the outputs of the checks that
have `"evidence"` in their `gate` list. Snapshot `review`. In round 2 and later, also
write the patch since the previous `review` snapshot.

Added fields: `patch`, `delta` (a path or null), `tripwire`, `evidence` (paths),
`structural` (bool).

`structural` is true when the delta adds or removes a file, or touches a path in
`review.archPaths`. When it is false in round 2 or later, the engine skips the
architecture reviewer.

### `b3`: triage after review

The gate reads `EV/3-arch-r<r>.json` and `EV/3-break-r<r>.json`, in the verdict schema
below. A missing file for a reviewer that ran is an `error`.

- A break finding blocks only when its `proof` reproduces (see `RS prove`).
- An architecture finding blocks only when its `rule` names a rule ID that exists in
  `architecture.md` or `learnings.md`.
- All other findings are advisory.
- In round 2 and later, the gate runs each open blocking proof again. A proof that does
  not reproduce marks its finding as addressed.

Added fields: `blocking`, `advisory`, `unproven`, `addressed`, `notAddressed`.

The verdict is `pass` when `blocking` is empty. Then the gate snapshots `gated` and sets
the stage to `B4`.

## `RS prove <slug> <cp> <finding-id>`

The command runs `proof.cmd` from the repo root, with the timeout in
`review.proofTimeout` (default 120 seconds).

- The proof reproduces when the command exits non-zero and its output matches
  `proof.pattern`.
- A timeout, or a missing pattern, gives `unproven`.
- After the proof runs, the command checks that the tree outside `EV/` did not change.
  If it changed, the command restores the tree and marks the proof `invalid`.

Added fields: `id`, `result` (`reproduced`, `unproven` or `invalid`), `exit`, `ms`.

## Other commands

| Command | Does | Output |
| --- | --- | --- |
| `RS red-check <output-file>` | Classifies each failure as `assert`, `stub`, `compile` or `runner`, with `behavior.failureKinds` | JSON counts |
| `RS size --prod <tree>` | Counts the added and deleted lines since `<tree>`. It ignores tests, lockfiles, binaries, generated files and `R/`. | JSON `prod`, `tests` |
| `RS exec --timeout <s> -- <cmd>` | Runs `<cmd>` in a shell, and stops it after `<s>` seconds | The exit code of `<cmd>`, or 124 on a timeout |
| `RS lock <dir> --from <file>` | Pins the paths that `<file>` lists, one path for each line | text |
| `RS live start <slug> <cp>` | Writes `LIVE` with `active: true` | JSON |
| `RS live set <key> <value>` | Updates one `LIVE` field | JSON |
| `RS live stop` | Sets `active: false` | JSON |
| `RS metrics add <json>` | Adds one line to `METRICS` | JSON |
| `RS report <slug> <cp>` | Writes `EV/4-report.md` | 10 lines of text or fewer, for the human |
| `RS decide <slug> <cp> <text>` | Adds the human's decision to `EV/decisions.md` and increments `epoch` | JSON |
| `RS retire <slug> <cp> <path> --reason <text>` | Unpins one test file. It records the reason in `EV/0-amendments.md`. | JSON |

## Live file

`LIVE` shows what runs now. den and the status line read it. The guard trusts it only
when `active` is true and `updated` is less than 6 hours old.

```json
{
  "active": true,
  "slug": "s",
  "cp": "cp2",
  "gate": "B1",
  "round": 2,
  "roles": [{ "role": "implement", "status": "working", "since": "2026-10-04T10:00:00Z" }],
  "updated": "2026-10-04T10:02:00Z"
}
```

## Metrics line

Each line in `METRICS` is one JSON object:

```json
{ "ts": "2026-10-04T10:02:00Z", "slug": "s", "cp": "cp2", "gate": "b1", "round": 2,
  "verdict": "fail", "ms": 81234, "blocking": 0, "advisory": 0, "prod": 140, "tests": 60 }
```

## Agent outputs

The engine passes these schemas to `agent()`. Reviewers also write their verdict to the
evidence path that the engine gives them.

### spec

```json
{ "tests": ["path"], "stubs": ["path"], "amendments": [{ "path": "…", "reason": "…" }],
  "cases": [{ "name": "FR-001 rejects an empty title", "req": "FR-001", "kind": "test" }],
  "note": "" }
```

### implement

```json
{ "status": "DONE", "summary": "…", "files": ["path"], "concerns": ["…"],
  "judgmentCalls": ["chose X over Y because Z"] }
```

`status` is `DONE`, `DONE_WITH_CONCERNS`, `NEEDS_CONTEXT`, `BLOCKED` or `SPEC_CONFLICT`.

### review (arch and break)

```json
{
  "role": "break",
  "round": 1,
  "verdict": "CHANGES",
  "findings": [{
    "id": "cp2-B1-1",
    "severity": "high",
    "file": "src/x.ts",
    "line": 42,
    "target": "code",
    "issue": "…",
    "scenario": "…",
    "fix": "…",
    "rule": "ARCH-COMMENTS",
    "proof": { "cmd": "bun test .claude/ratchet/evidence/s/cp2/proofs/p1.test.ts",
               "pattern": "expected 3, received 2" }
  }],
  "addressed": [{ "id": "cp2-B1-1", "status": "ADDRESSED" }],
  "declined": ["what the reviewer did not judge, and why"]
}
```

- A finding ID is `<cp>-<A|B|V><round>-<n>`. `A` is arch, `B` is break, `V` is visual.
- `severity` is `high`, `medium` or `low`. Severity sets the fix order. Evidence decides
  whether a finding blocks.
- `target` is `code`, `tests` or `docs`.
- `rule` is optional. Only arch findings use it.
- `proof` is optional. Only break findings use it. Proof files go in `EV/proofs/`.
- Version 1 verdicts (`{verdict, findings[{id, severity, file, issue, fix}]}`) also
  parse. Their findings have no proof and no rule, so they are advisory.

### visual

```json
{ "verdict": "FAIL", "differences": [{
    "id": "cp2-V1-1", "element": "header", "kind": "position",
    "delta": { "px": 6, "color": 0 }, "engine": false, "severity": "medium",
    "fixable": true, "location": "top, y 0–50" }] }
```

- `kind` is `position`, `size`, `color`, `missing`, `extra`, `text` or `other`.
- The engine decides which differences block:
  - A `missing`, `extra` or `text` difference blocks.
  - Any other kind blocks only when its delta is above `visual.tolerance`.
  - A difference with `engine: true` never blocks, and it never counts toward a round.

### relay

The relay agent returns the `RS` JSON object without change. The engine checks that
`nonce` matches the value it sent.

## Engine result

The checkpoint workflow returns one object:

```json
{ "status": "ready-for-B4", "slug": "s", "cp": "cp2", "epoch": 3,
  "rounds": { "b0": 1, "b1": 2, "b2": 0, "b3": 1 },
  "summary": "…", "question": null, "evidence": ["path"] }
```

- `status` is `ready-for-B4`, `needs-decision`, `blocked` or `harness-error`.
- For `needs-decision`, `question` gives the decision that the human must make.
