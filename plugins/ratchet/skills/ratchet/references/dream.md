# Dream

The dream reads your Claude Code sessions in every project, and the ratchet runs in
them. Then it proposes a few small rules. It never applies a rule by itself. The human
approves each item.

There are two tiers:

| Tier | Changes | How often | Gate |
| --- | --- | --- | --- |
| T1 rules | global rules, project memory, ratchet learnings | each night, or on demand | 3 items or fewer; evidence for each; the human approves |
| T2 prompt | One agent prompt in the ratchet plugin | when the human asks | an eval replay must show no regression; the human approves |

There is one dream for the whole machine. Its files are in `~/.claude/ratchet/`:
- `dream.json`: the settings (see "Settings").
- `dreams/<date>/`: one bundle for each dream, with `harvest.json`, `context/`,
  `candidates.json`, `proposal.json`, `proposal.md` and, after the review, `review.json`.
- `dreams/last.json` (the end of the last window), `dreams/rejected.jsonl` and
  `dreams/pending.json` (the proposals that wait).

Each dream command works in any folder, also outside a git repo.

## Run a dream now

1. `RS dream harvest` collects the facts without a model. It removes secrets and email
   addresses. It reads the session files in `~/.claude/projects/` that are newer than
   the last dream. The first dream reads `sinceDays` days.
   - **Your prompts**, each with what Claude did just before it. The tags are
     `interrupt`, `declined`, `rule`, `correction` and `chore`.
   - **Agent friction**: tool errors from the harness, denials and time-outs. A command
     that fails, such as a red test, is not friction.
   - **Ratchet evidence** of each repo that the sessions worked in.

   `--dry` shows the numbers and writes nothing.
2. `RS dream prompt <date>` writes the reflection prompt into the bundle. Then run the
   reflection in the bundle folder:
   - The nightly job runs headless `claude -p` with `--safe-mode --restricted
     --no-session-persistence --allowedTools Read`. The reflection reads only the
     bundle. A headless run may not write in `~/.claude`, so the answer is the
     candidates JSON, and it goes to `reflect.log`.
   - On demand, you can spawn `ratchet:reflect` with the bundle path instead. Then save
     its answer as `candidates.json` in the bundle.
3. `RS dream curate <date>` is code. It checks each citation against the harvest. It
   counts the recurrence itself, and ignores a count that the model gives. It removes
   duplicates and rejected items, and keeps `maxItems` items or fewer. It writes
   `proposal.json` and `proposal.md`, and only then moves the window.
4. A candidate that only a cap cut waits in `dreams/carried.json`. The next dream checks
   its target again and weighs it with the new candidates. It wins a tie. Apply checks it
   against the harvest of the dream that cut it. After 3 dreams, it expires.

## Targets

| Target | Where an accepted item goes | The evidence that it needs |
| --- | --- | --- |
| `global` | `~/.claude/rules/dream/G-nnn-<slug>.md`. Each session loads it. With `paths`, it loads only when Claude reads or edits a matching file, for example `**/*.swift`. | 2 or more sessions, or one "always" or "never" rule from the human |
| `project` | A `feedback` memory in the auto-memory of that project folder, and its line in `MEMORY.md` | 2 or more human prompts in that project, or one prompt with the tag `rule`, `correction`, `declined` or `interrupt` |
| `ratchet` | The repo's `.claude/ratchet/learnings.md` | 2 or more rows, or a human gate file |

- `~/.claude/rules` is a link to `home/rules/` in claude-code-setup. Thus each new
  global rule is a change that the human can see and commit.
- A global rule is a file that the dream owns. The dream can change it (EDIT) or move
  it to `dreams/retired/` (RETIRE), where it stops loading. There are `globalCap`
  global rules or fewer.
- Curate refuses a `harvest.json` that changed after the harvest, because the reflection
  can write in its bundle. Apply refuses a project or a repo that the harvest did not list.
- The dream only adds project memories. It never changes a memory that a person or a
  session wrote.

## Review

At session start, the relay mod tells the human when proposals wait:
`🦝 3 dream proposals wait for you · /ratchet dream`. Show the items before other work:

```text
Dream 2026-10-05: 3 proposals
1. ADD global G-004 (**/*.swift): Check each text field with the keyboard open.
   Why: the human found a covered field after the gates passed, in 2 sessions.
   Evidence: 3 turns in 2 sessions: 241452aa#5120, 9c01d2e3#88, 9c01d2e3#140
2. ADD memory of -Users-muningis-workspace-code-muningis-epstein-against-humanity reinstall-after-lock: After an approved checkpoint, reinstall the app on the phone.
   Why: the human asked for it after each lock.
   Evidence: 6 turns: 241452aa#3301, 241452aa#4420, 241452aa#5012 +3 more
3. RETIRE ratchet in epstein-against-humanity L-004: no finding cited it in 9 rows.
   Evidence: cited: ios-app/cp9/3-triage-r1.json
Reply per item: yes, no, or a change.
```

Judge the reply as free text, for each item. Then run
`RS dream apply <date> --accept <ids> --reject <ids> --reason "<text>"`. It writes each
accepted item to its target, with `origin: dream`. It adds each rejected item to
`rejected.jsonl`, and the next reflection reads that file.

## Nightly

`RS dream install --load` writes the launchd user agent
`~/Library/LaunchAgents/com.ratchet.dream.plist`, and `dream.json` when it does not
exist. The job runs at 03:30 local time.
- It skips the night when a proposal still waits, when the last dream is less than 20
  hours old, or when nothing is new.
- The reflection costs `budgetUsd` or less, and only on a night when it runs.
- The plist holds no token. Claude Code reads its own login.
- The plist starts `~/.claude/ratchet/dream-launch.sh`. Each night, it finds the newest
  installed ratchet, because a plugin upgrade changes the plugin path.
- When the Mac sleeps at 03:30, launchd runs the job when the Mac wakes.
- The log is `~/.claude/ratchet/dream.log`. `RS dream state` tells whether a dream is
  due. `RS dream uninstall --unload` removes the job.

## Settings

`~/.claude/ratchet/dream.json`:

| Key | Default | Meaning |
| --- | --- | --- |
| `nightly` | `true` | The job runs. |
| `maxItems` | `3` | The items in one proposal. |
| `budgetUsd` | `2` | The cost limit of one reflection. |
| `sinceDays` | `7` | The days that the first dream reads. |
| `exclude` | `[]` | Project folders or working folders to skip, as globs. |
| `globalCap` | `25` | The most global rules. At the cap, an ADD needs a RETIRE. |

## Learnings v2

Each entry has an ID, a scope, a rule, a check, a source, an origin, counters and a
status (see `run.md`, step 5). The counters change in two ways:
- `helpful` goes up by 1 when a confirmed finding cites the rule.
- `harmful` goes up by 1 when the human waives or rejects a finding that cites the rule.

Agents get only the entries whose scope matches the files of the row: `RS learnings
--scope <paths>`. Never write the file again from the start. Change it one entry at a
time.

A rule for a whole stack, for more than one repo, is a global rule with `paths`.

## T2: one prompt proposal

In 2.x this is a manual procedure. The eval suite is in the plugin's `evals/` folder.
Run it with `claude plugin eval <plugin dir> --allow-tools Bash Write --runs 3
--max-cost-usd 5`. Each run costs money, so run it only for a proposal.

1. Pick the agent with the most harm signal: agent friction, escaped defects, waived
   findings, or rounds over the cap.
2. Propose one small change to its prompt.
3. Run the eval replay two times: `claude plugin eval` with the current prompt, and with
   the proposal. The cases come from past evidence: findings that the reviewer must
   find, and approved diffs that it must pass. Use only cases newer than the evidence
   that the proposal used.
4. Reject the proposal when one case goes from pass to fail. Else show the diff and the
   eval table. The human decides.
5. When the human approves, change the prompt on a branch of the plugin repo. Change the
   version, and ask the human to merge.

Do not give the reflection the `evals/` folder. An agent that sees the graders can fit
its proposal to them, and then the eval proves nothing.
