# Dream

The dream reads what happened in past runs and proposes small improvements. It never
applies a change by itself. The human approves each item.

There are two tiers:

| Tier | Changes | How often | Gate |
| --- | --- | --- | --- |
| T1 data | Entries in `learnings.md` and in the stack library | each night, or on demand | 3 items or fewer; evidence for each; the human approves |
| T2 prompt | One agent prompt in the ratchet plugin | once each week | an eval replay must show no regression; the human approves |

## Run a dream now

1. `RS dream harvest` collects the facts without a model. It reads the metrics, the
   human gate files (`4-human*.md`), the findings and their triage, the amendments, the
   learnings counters, and the defects that the human found after the gates passed. It
   removes secrets. It writes `.claude/ratchet/dreams/<date>/harvest.json`.
2. Spawn `ratchet:reflect` with the harvest path, the learnings, the stack library and
   `.claude/ratchet/dreams/rejected.jsonl`. It writes `candidates.json`. It only reads.
3. `RS dream curate <date>` is code. It removes duplicates and contradictions. It keeps a
   candidate only when it repeats in 2 or more rows, or when a human gave it. It keeps
   `dream.maxItems` items or fewer. It allows only learnings and stack entries. It writes
   `proposal.json` and a short `proposal.md`.

## Review

When a bundle has `proposal.json` and no `review.json`, show its items at the start of
the next `/ratchet`, before other work:

```text
Dream 2026-10-05: 2 proposals
1. ADD L-013 (mobile/**): check insets with the keyboard open. Evidence: 3 human reports.
2. RETIRE L-004: no finding cited it in 9 rows, and the human waived it 2 times.
Reply per item: yes, no, or a change.
```

Judge the reply as free text, for each item. Then run
`RS dream apply <date> --accept <ids> --reject <ids> --reason "<text>"`. It writes the
accepted entries with `origin: dream`, and it adds the rejected items to
`rejected.jsonl`. The next reflection reads that file.

## Learnings v2

Each entry has an ID, a scope, a rule, a check, a source, an origin, counters and a
status (see `run.md`, step 5). The counters change in two ways:
- `helpful` goes up by 1 when a confirmed finding cites the rule.
- `harmful` goes up by 1 when the human waives or rejects a finding that cites the rule.

Agents get only the entries whose scope matches the files of the row: `RS learnings
--scope <paths>`. Never write the file again from the start. Change it one entry at a
time.

**Stack library.** `~/.claude/ratchet/stacks/<stack>.md` holds rules for more than one
repo, for example `compose-multiplatform`. The config lists the stacks of the repo in
`dream.stacks`. A rule moves to the stack library when it repeats in 2 or more repos.

## Nightly

`RS dream install` writes a launchd user agent at
`~/Library/LaunchAgents/com.ratchet.dream.plist`. It runs at 03:30 local time, for each
repo in `~/.claude/ratchet/repos.json`. A repo joins that list at its first plan.
- It runs `claude -p` with `--max-budget-usd` from `dream.budgetUsd` and a short
  `--allowedTools` list.
- The plist holds no token. Claude Code reads its own login.
- When the Mac sleeps at 03:30, launchd runs the job when the Mac wakes.
- `RS dream uninstall` removes it.

## T2: one prompt proposal each week

1. Pick the agent with the most harm signal: escaped defects, waived findings, or
   rounds over the cap.
2. Propose one small change to its prompt.
3. Run the eval replay two times: `claude plugin eval` with the current prompt, and with
   the proposal. The cases come from past evidence: findings that the reviewer must
   find, and approved diffs that it must pass. Use only cases newer than the evidence
   that the proposal used.
4. Reject the proposal when one case goes from pass to fail. Else show the diff and the
   eval table. The human decides.
5. When the human approves, change the prompt on a branch of the plugin repo, change the
   version, and ask the human to merge.

Dream agents cannot read `evals/`. The guard stops them, so they cannot fit the graders.
