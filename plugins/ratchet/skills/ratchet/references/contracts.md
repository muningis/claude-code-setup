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
| `PIN` | `R/evidence/<slug>/_state/`: the pins of the state files |
| learnings | `R/learnings.md` |
| goldens | `R/goldens/<target>@<viewport>.png`: the last approved captures |
| refs | `refs/ratchet/<slug>/<cp>/{base,red,review,gated}` |

All paths in JSON are relative to the repo root, unless a field name ends in `Abs`.

Each `EV` holds the pins of its tests (`spec.lock` and `locked/`) and these files:

| Gate | Files |
| --- | --- |
| b0-prep | `0-baseline.txt`, `0-baseline.json` |
| b0 | `0-spec.json`, `0-red.txt`, `0-amendments.md` |
| b1, smoke | `1-impl-r<r>.json`, `1-behavior-r<r>.txt`, `1-smoke-r<r>.txt`, `1-brief-r<r>.md`, `1-attempts.md` |
| b2 | `2-capture-r<r>.json`, the images, `2-visual-r<r>.json`, `2-triage-r<r>.json` |
| b3 | `3-diff-r<r>.patch`, `3-delta-r<r>.patch`, `3-tripwire-r<r>.txt`, `3-check-<id>-r<r>.txt`, `3-prep-r<r>.json`, `3-arch-r<r>.json`, `3-break-r<r>.json`, `3-triage-r<r>.json`, `proofs/` |
| human gate | `4-report.md`, `4-human.md`, `4-replay.md`, `decisions.md` |

A list field that would make the output larger than 1 KB is cut. Then a field
`<name>More` gives the number of items that it leaves out. The evidence file has the full
list.

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

- `ok` is true when the command ran, also when the verdict is `fail`. Only `verdict`
  decides.
- `verdict` is `pass`, `fail`, `error`, or `pending` for a detached gate that still runs.
- The engine checks the `nonce`. `sha256` is for the audit trail: the engine cannot hash
  files.
- The exit code is 0 for `pass`, 1 for `fail` and 2 for `error`. Exit codes 1 and 2 are
  normal results, not crashes.
- Each command that the engine calls takes `--nonce <n>` and echoes it. This includes
  `RS state`.
- A slug and a checkpoint ID match `[A-Za-z0-9][A-Za-z0-9._-]*` and never contain `..`,
  because they go into shell commands.
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
- Gate b1 adds `baselineFailing`, and `RS report` reads it.
- A detached gate keeps its files in `EV/.jobs/<job>.json`, `.err` and `.pid`.

## `RS state <slug> [<cp>]`

When you do not give `<cp>`, the command uses the first open row.

Fields:
- the row: `slug`, `cp`, `kind`, `target`, `reqs` (array), `est` and `status`
- the progress: `stage`, `rounds`, `epoch` and `open`
- `refs`: `base`, `red`, `review` and `gated`, each a SHA or null
- `pins`: `intact` and `changed`
- `visual` (bool), and `harnessError` (a string, or absent)

`ok` is false and `verdict` is `error` when the state cannot be read. `harnessError`
gives the reason.

## `RS gate <gate> <slug> <cp> --nonce <n> [--round <r>]`

Each gate updates `STATE`, writes its evidence and adds one line to `METRICS`.

**Rounds.** The engine passes `--round <r>` to each gate. The gate sets
`STATE.rounds.<gate>` to the larger of the old value and `r`. The engine numbers the
rounds of a gate from `STATE.rounds.<gate> + 1`, so evidence file names never repeat.
Caps count only the rounds of one engine run. `RS decide` does not reset the rounds.

**Detached runs.** A relay's Bash call stops after 10 minutes, and a gate can take longer.
So the engine adds `--detach`:
1. `RS gate … --detach` starts the gate as a background job in its own session. It prints
   `{ "verdict": "pending", "job": "<job id>" }` at once.
2. `RS wait <slug> <cp> <job> --nonce <n> --timeout 480` waits for the job. It prints the
   gate's result with the wait's own nonce, or `pending` after the timeout.
3. The engine sends `RS wait` again, 15 times or fewer, until the verdict is not
   `pending`.

**Plan rows and live roles.** A gate that passes `b0` sets the row to `red`. A gate that
passes `b3` sets it to `green`. After each gate, `LIVE.roles` names the role or roles that
work next.

### `b0-prep`: before the spec agent

The engine runs this gate when it starts a row at `B0`, before the spec agent writes a
file. Gate `b0` needs the base, because it finds the spec set as the files changed since
`base`.

1. Run the baseline once: each check with `"b1"` in its `gate` list (whatever its `when`
   globs), then `behavior.all`. Write `0-baseline.txt` and `0-baseline.json`
   (`{ "<check id>": true | false }`).
2. Snapshot `base`, unless it exists. A resumed row keeps its base. The baseline runs
   first, so the files that the tests leave behind are part of the base.
3. Put the short base SHA in the row's `base` column.
4. Pin the state files in `PIN`: `config.json`, `learnings.md` and `architecture.md`.
5. Write `EV/context.md` for the agents. It holds these items:
   - the plan path, the row, and its lines from `## Notes` (scope, done when, waivers)
   - the change documents and the architecture path
   - the test commands, the test budget and the visual tolerance

   `b1`, `b2-capture` and `b3-prep` write the file again when it exists, so a waiver that
   the human adds after B0 reaches the agents.
6. Write `EV/learnings.md`: all active learnings, and the text outside the entries.
7. Write `LIVE` with `active: true`.

Added fields: `base`, `baselineFailing` (the checks that failed before the row started),
`statePins`.

### `b0`: the spec gate

Run this gate after the spec agent returns.

1. Find the spec set: the files that changed since `base`. Classify each file as a test
   or a stub, with `tests.globs`.
2. Run `behavior.one` on the test files. Classify each failure with `RS red-check`.
3. Trace: each case name contains a requirement ID from the row's `reqs`. Each ID in
   `reqs` that has coverage kind `test` has one or more cases.
4. Compare the case count with `tests.perRequirement` and `tests.perCheckpoint`.
5. An earlier test that this spec changed is an amendment. Lock it again in the older
   checkpoint's `EV`, and add `- <path>: <reason>` to `EV/0-amendments.md`. Else the older
   pin would undo the change in every round.
6. Pin the test files. Snapshot `red`. Set the stage to `B1`.

Added fields: `cases`, `red` (`assert`, `stub`, `compile`, `runner`, `pass`: counts),
`trace` (`missing`, `unknown`), `budget` (`cases`, `limit`, `over`), `tests`, `stubs`,
`amended`.

The verdict is `fail` when `compile`, `runner` or `pass` is above zero, or when
`trace.missing` is not empty. For a `refactor` row, each case must pass.

### `b1`: the behavior gate

1. Run `RS check` on the test pins of the plan. If a pinned test changed, restore it and
   fail.
2. Run `RS check` on `PIN`. When a state file changed, stop with `error`. Do not restore
   it: the human decides (see `run.md`).
3. Run the check `pinned`: `behavior.one` on the tests that this checkpoint pinned. They
   must pass. The baseline never exempts them.
4. Run each check with `"b1"` in its `gate` list, in order, when a changed file matches
   its `when` globs. Then run `behavior.all`. Each command runs through `RS exec` with
   its timeout.
5. A check other than `pinned` that also failed in the baseline does not fail the gate.
   It goes into `baselineFailing`, and the B4 report shows it. The comparison is for
   each check, because test names cannot be compared across runners.
6. Count production lines (`RS size --prod`) and compare them with the row's `est`. This
   result is advisory.
7. When a check fails, write the brief for the next round to `EV/1-brief-r<r+1>.md`.

Added fields:
- `checks` (`id`, `ok`, `ms`), `failing`, `baselineFailing` and `pinsChanged`
- `size` (`prod`, `est`, `ratio`)
- `brief`: the path of the next brief, or null when the gate passes

The engine always names the brief of the next round, "if it exists". `RS decide --reopen
b1` can write one before round 1. In a fix round for B2 or B3, the brief is the visual
file or the triage file.

### `b2-capture`: before the visual judgment

Run the impl and reference captures for each viewport, with `RS exec`. Then capture each
earlier approved target again, for the regression check.

Added fields:
- `images`: a list of `{ viewport, impl, ref }` paths
- `identical`: true when each impl and ref pair is byte-identical
- `regressChanged`: the targets whose new capture differs from their last approved
  capture

- When `identical` is true and `regressChanged` is empty, the verdict is `pass`, and the
  engine skips the visual agent.
- A target in `regressChanged` blocks, unless the plan notes have
  `waive(<cp>): regression <target> — <reason>`. Only the human writes that waiver. The
  evidence file lists the changed targets, and it is the brief for the fix round.

### `b2`: after the visual judgment

The gate reads `EV/2-visual-r<r>.json` in the visual schema below. If the file is missing,
`--verdict-b64 <base64 of the verdict JSON>` supplies it: the gate validates it as a JSON
object and writes the file. An existing file wins. The engine passes the visual agent's
returned object this way. It applies
`visual.tolerance` (see `config.md`). It also reads `EV/2-capture-r<r>.json`: each target
in `regressChanged` without a waiver blocks, with the ID `<cp>-V<r>-<100+n>` and the kind
`regression`.

Added fields: `blocking`, `advisory`, `renderer` (the count of differences that the
renderer causes).

The verdict is `pass` when `blocking` is empty. When the visual verdict is `INVALID`, the
verdict is `error` and `summary` starts with `invalid capture`. Then the engine runs
`b2-capture` again, two times or fewer, and then stops with `harness-error`.

### `smoke`: after each green `b1`

Run each check of kind `smoke` whose `when` globs match a changed file. When no smoke
check applies, the verdict is `pass` and `summary` says `no smoke checks`.

A smoke failure counts as a failed B1 round. The gate adds the failures to the next brief,
`EV/1-brief-r<r+1>.md`.

Added fields: `checks` (`id`, `ok`, `ms`), `failing`, `brief`.

### `b3-prep`: before review

Write the patch since `base`, the tripwire output and the outputs of the checks that
have `"evidence"` in their `gate` list. Snapshot `review`. In round 2 and later, also
write the patch since the previous `review` snapshot.

`evidence` is the patch path. Added fields: `patch`, `delta` (a path or null),
`tripwire`, `checkOutputs` (the paths of the check outputs), `structural` (bool).

`structural` is true when the delta adds or removes a file, or touches a path in
`review.archPaths`. The engine skips the architecture reviewer in a round when these
three facts are true:
- The round is 2 or later.
- `structural` is false.
- The last triage had no blocking arch finding.

### `b3`: triage after review

The gate reads `EV/3-arch-r<r>.json` and `EV/3-break-r<r>.json`, in the verdict schema
below. A missing file for a reviewer that ran is an `error`. When the engine skipped the
architecture reviewer, it passes `--skip-arch`. If a file is missing, `--arch-b64 <base64
of the verdict JSON>` or `--break-b64 <...>` supplies it: the gate validates the copy as a
JSON object and writes the file. An existing file wins, and a missing file with no copy is
still an `error`. The engine passes the returned object of each reviewer that ran, and no
copy for a skipped one. The gate writes the full triage to `EV/3-triage-r<r>.json`.

- A break finding blocks only when its `proof` reproduces (see `RS prove`).
- An architecture finding blocks only when its `rule` names a rule ID that exists in
  `architecture.md` or `learnings.md`.
- All other findings are advisory.
- In round 2 and later, the gate runs each open blocking proof again. A proof that does
  not reproduce marks its finding as addressed.
- A finding ID that does not match `<cp>-<A|B><round>-<n>` gets a new ID
  `<cp>-<A|B><r>-<900+n>`, and the triage keeps the old one as `rawId`. Later rounds
  match a finding by either ID, so a bad ID cannot stay open for good.
- A rule of a retired learnings entry does not count as an existing rule.

Added fields: `triage` (its path), `blocking`, `advisory`, `unproven`, `addressed`,
`notAddressed`.

The verdict is `pass` when `blocking` is empty. Then the gate snapshots `gated` and sets
the stage to `B4`.

Before review, `b3-prep` writes `EV/learnings.md` again, with only the learnings whose
scope matches the files that changed since `base`.

## `RS prove <slug> <cp> <finding-id>`

The command runs `proof.cmd` from the repo root, with the timeout in
`review.proofTimeout` (default 120 seconds).

- The proof reproduces when the command exits non-zero and its output matches
  `proof.pattern`.
- A timeout, or a missing pattern, gives `unproven`.
- After the proof runs, the command checks that the tree outside `EV/` did not change.
  If it changed, the command copies each changed file to `EV/proofs/<id>.backup/`, then
  restores the tree and marks the proof `invalid`. The backup keeps an edit that a human
  made during the proof.

Added fields: `id`, `result` (`reproduced`, `unproven` or `invalid`), `exit`, `ms`.

## Other commands

| Command | Does | Output |
| --- | --- | --- |
| `RS wait <slug> <cp> <job> --nonce <n> [--timeout <s>]` | Waits for a detached gate, 540 seconds or fewer. See "Detached runs". | the gate's JSON, or `pending` |
| `RS red-check <output-file>` | Classifies each failure as `assert`, `stub`, `compile` or `runner`, with `behavior.failureKinds` | JSON counts |
| `RS size --prod <tree>` | Counts the added and deleted lines since `<tree>`. It ignores tests, lockfiles, binaries, generated files and `R/`. | JSON `prod`, `tests` |
| `RS check <dir>...`, `RS restore <dir>` | Version 1 commands: find changed pinned files, and put them back. They keep their text output. | text |
| `RS row <slug> <cp> [<status>] [--base <sha>] [--note <text>]` | Changes one row of the plan table, and adds a note line under `## Notes`. Use it instead of a hand edit of the table. | JSON |
| `RS config` | Prints the config, normalized to version 2. | JSON |
| `RS exec --timeout <s> -- <cmd>` | Runs `<cmd>` in a shell, and stops it after `<s>` seconds | The exit code of `<cmd>`, or 124 on a timeout |
| `RS lock <dir> --from <file>` | Pins the paths that `<file>` lists, one path for each line | text |
| `RS live start <slug> <cp>` | Writes `LIVE` with `active: true` | JSON |
| `RS live set <key> <value>` | Updates one `LIVE` field | JSON |
| `RS live stop` | Sets `active: false` | JSON |
| `RS metrics add <json>` | Adds one line to `METRICS` | JSON |
| `RS report <slug> <cp>` | Writes `EV/4-report.md`. The short form names the files, the judgment calls, the advisory findings, the device checks, the size, and the checks that failed before the row started. | 10 lines of text or fewer, for the human |
| `RS decide <slug> <cp> <text> [--reopen b1\|b3]` | Adds the human's decision to `EV/decisions.md` and increments `epoch`. With `--reopen`, it sets the stage, and puts the decision at the top of the next brief. It keeps the rest of that brief. | JSON |
| `RS retire <slug> <cp> <path> --reason <text>` | Unpins one test file. It records the reason in `EV/0-amendments.md`. | JSON |
| `RS keepawake start\|stop` | Starts or stops `caffeinate`, so that the Mac does not sleep during a run. It does nothing on other systems. | JSON |
| `RS learnings --scope <path>...` or `RS learnings --all` | Prints the active learnings entries whose scope matches one of the paths (or all of them), the text outside the entries, and the matching stack rules | markdown |
| `RS stelint <path>...` | Checks the STE-lite rules in `docs.md` | JSON |
| `RS doclint <path>... [--approval] [--approve <file>]` | Checks the document rules in `docs.md`. `--approve` records the approved body. | JSON |
| `RS dream <step> ...` | `harvest [--dry]`, `prompt <date>`, `curate <date>`, `apply <date> ...`, `state`, `install`, `uninstall`. They work in any folder. See `dream.md`. | JSON |

## Live file

`LIVE` shows what runs now. The status line reads it. The guard trusts it only
when `active` is true and `updated` is less than 6 hours old.

- The file is `.claude/ratchet/live.json` in the repo root. The mods read it relative to
  the session folder, so start Claude Code in the repo root.
- `gate` is the stage name from `STATE`: `B0` to `B5`.
- `round` is the current round of that gate.
- `roles[].role` is `spec`, `implement`, `visual`, `arch`, `break` or `relay`.
  `roles[].status` is `working`, `done`, `failed` or `idle`.
- Each `RS live` command and each gate sets `updated` to the current time.
- `RS live stop` sets `active` to false and clears `roles`.

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

The engine passes these schemas to `agent()`. Each agent also writes its JSON output to
the evidence path that the engine gives it. `RS` reads these files, and the engine cannot
write files:

| Agent | File |
| --- | --- |
| spec | `EV/0-spec.json` |
| implement | `EV/1-impl-r<r>.json` |
| visual | `EV/2-visual-r<r>.json` |
| review-arch | `EV/3-arch-r<r>.json` |
| review-break | `EV/3-break-r<r>.json` |

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
    "delta": { "px": 6, "color": 0 }, "engine": false, "deferred": false,
    "waived": false, "severity": "medium", "location": "top, y 0-50" }] }
```

- `kind` is `position`, `size`, `color`, `missing`, `extra`, `text` or `other`.
- The `b2` gate decides which differences block:
  - A `missing`, `extra` or `text` difference blocks.
  - Any other kind blocks only when its delta is above `visual.tolerance`.
  - A difference with `engine: true` comes from the renderer. It never blocks, and it
    never counts toward a round.
  - A difference with `deferred: true` (outside the row's scope) or `waived: true` (a
    human waiver covers it) is advisory.

### relay

The relay agent returns the `RS` JSON object without change. The engine checks that
`nonce` matches the value it sent.

## Engine arguments

The lead starts the workflow with these `args`:

```json
{ "repo": "/abs/repo", "slug": "s", "cp": "cp2", "epoch": 3, "nonce": "<uuid>",
  "rs": "bash /abs/skill/scripts/ratchet.sh", "mode": "interactive",
  "caps": { "b1": 5, "b2": 3, "b3": 3 }, "models": {} }
```

- The engine appends `--root <repo>` to every RS command. `ratchet.sh` honours `--root`
  before a literal `--`, so a relay can run it from any folder without `cd`.
- Use a new `nonce` for each run. A resumed workflow replays cached results for the same
  prompts, so an old nonce runs no gate again.
- `epoch` from `STATE` wins over `args.epoch`.
- `mode` is `interactive` or `auto`. In 2.0 the engine only logs it.
- From implement round 4, the engine uses `models.implementEscalate` (default `opus`).

## Engine result

The checkpoint workflow returns one object:

```json
{ "status": "ready-for-B4", "slug": "s", "cp": "cp2", "epoch": 3,
  "rounds": { "b0": 1, "b1": 2, "b2": 0, "b3": 1 },
  "summary": "…", "question": null, "evidence": ["path"] }
```

- `status` is `ready-for-B4`, `needs-decision`, `blocked` or `harness-error`.
- `ready-for-B4`: gates B0 to B3 passed. Also returned at once when the stage is `B4`.
- `needs-decision`: a cap ran out, or the implementer returned `NEEDS_CONTEXT`,
  `BLOCKED` or `SPEC_CONFLICT`. `question` gives the decision that the human must make.
- `blocked`: the spec failed `b0` two times. `question` gives the reason. The lead marks
  the row `blocked`.
- `harness-error`: a gate returned `error`, a relay nonce did not match, an agent
  returned nothing, or the stage is `B5` or `done`.
- The result is a claim from the workflow. Before the human gate, the lead runs
  `RS state` itself and checks `stage` `B4` and `refs.gated`.
