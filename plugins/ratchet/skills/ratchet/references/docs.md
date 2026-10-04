# Change documents

Ratchet writes these documents in the repo, under `docs.root` (default `docs`). They are
meant to be committed. `RS doclint` checks them. A `block` finding stops the approval. A
`warn` finding is advice.

Keep each document short. A long document gets skimmed, and a skimmed document fails.

## Which documents each track writes

| Track | Documents |
| --- | --- |
| fix | `design-log.md`, with the bug sections |
| small | `design-log.md`, with a Requirements section |
| full | `prd.md`, `spec.md` and `design-log.md`. Add an ADR only for a durable decision that affects more than this change. |

The folder is `docs/changes/NNNN-<slug>/`. `NNNN` is the next free number, with four
digits. `docs/changes/index.md` has one line for each change.

## Front matter

Each change document starts with front matter:

```markdown
---
type: design-log
track: small
change: 0007-profile-header
status: draft
---
```

- `type` is `design-log`, `prd`, `spec`, `adr` or `architecture`.
- `track` is `fix`, `small` or `full`. Only the design log has it.
- `status` is `draft`, `approved` or `done`. An ADR uses the MADR status values instead.
- An ADR has `status` and `date`. It can also have `decision-makers`. It has no `change`.
- `architecture.md` has only `type`.

## Approval lock

`RS doclint --approve <file>` records the length and hash of the file body: the text
after the front matter. After that, the approved body must stay the same. Add new text
only below it. The front matter can change, so the status can go from `approved` to
`done`.

## `design-log.md`

The sections, in this order. Leave out a section that has no content, except the
required sections.

| Section | Required | Holds |
| --- | --- | --- |
| `## Decisions for the implementer` | yes | 3 to 7 bullets (warn when outside this range). The implementer reads this section first. |
| `## Background` | no | What exists now, and why the change is necessary. |
| `## Problem` | yes | The problem, in 2 to 4 sentences (warn when outside this range). The fix track adds `### Current behaviour`, `### Expected behaviour` and `### Unchanged behaviour`. |
| `## Prior art` | no | Code and decisions that exist already, with `path:line` links. |
| `## Requirements` | track `small` | The requirement lines. The full track keeps them in `spec.md`. |
| `## Questions and answers` | yes | The grill rounds. |
| `## Design` | yes | How the change works. |
| `## Plan` | no | The checkpoint table summary. |
| `## Trade-offs` | no | The options that you did not choose, and why. |
| `## Results` | when `status: done` | Append-only. Each entry has a date. |

For track `fix`, the three bug sections under `## Problem` are required.

**Questions and answers.** Each question is one line that starts with `Q<n>:`. Its answer
starts on the next line with `A:`. The answer can continue on more lines, up to the next
`Q<n>:` line or the next heading. An answer that starts with `A: open` (in any letter
case) is open. At approval, no answer can be open.

```markdown
Q1: Does the header show the user's avatar?
A: Yes. Use the 40px avatar from the profile API.
```

**Results.** Each lock adds one entry under `## Results`:

```markdown
### 2026-10-04 · cp2 header only
- 4/4 requirements verified (FR-001, FR-002, FR-003, FR-004)
- Deviation: the avatar is 36px, because the API has no 40px size.
```

The last entry of a finished change has a line `X/Y requirements verified`.

## `prd.md` (full track only)

| Section | Holds |
| --- | --- |
| `## Problem` | Who has the problem, and what it costs them. |
| `## Outcome` | A result that you can measure. |
| `## Non-goals` | What this change does not do. |
| `## Scenarios` | Numbered user scenarios, in priority order. |
| `## Success criteria` | Measurable criteria, with no technology names. |
| `## Risks` | Each risk, with a tier: `high`, `medium` or `low`. |

All six sections are required. Mark each open point with `[NEEDS CLARIFICATION]`. At
approval, no such marker can remain.

## `spec.md` (full track only)

| Section | Required | Holds |
| --- | --- | --- |
| `## Requirements` | yes | The requirement lines. |
| `## Unchanged behaviour` | no | Requirements that state what must not change, with the IDs `UB-001` and up. |

## Requirement lines

Write each requirement as one list item:

```markdown
- **FR-001** (test): When the user saves an empty title, the editor shall show "Title is required".
- **FR-002** (device): While the keyboard is open, the form shall keep the focused field visible.
- **FR-003** (visual): The header shall match the reference at 375px and 1280px.
```

- The ID is `FR-` or `UB-` and three digits. Each ID is unique in the change.
- The coverage kind in parentheses is `test`, `visual`, `smoke` or `device`:
  - `test`: one or more test names contain the ID.
  - `visual`: gate 2 checks the requirement.
  - `smoke`: a smoke check covers it.
  - `device`: the human checks it at B4.
- Each requirement contains `shall` exactly one time, and uses one EARS pattern. The
  keywords are not case-sensitive.

| Pattern | Form |
| --- | --- |
| Ubiquitous | `The <system> shall <response>.` |
| State | `While <state>, the <system> shall <response>.` |
| Event | `When <trigger>, the <system> shall <response>.` |
| Option | `Where <feature>, the <system> shall <response>.` |
| Unwanted | `If <trigger>, then the <system> shall <response>.` |
| Complex | `While <state>, when <trigger>, the <system> shall <response>.` or `While <state>, if <trigger>, then the <system> shall <response>.` |

## ADR: `docs/decisions/NNNN-title-with-dashes.md`

Use MADR 4. The required sections are `## Context and Problem Statement`, `## Considered
Options` and `## Decision Outcome`. The list directly under `## Considered Options` has
two or more bullets. The `status` is `proposed`, `accepted`, `rejected`, `deprecated` or
`superseded by ADR-NNNN`. Lock an accepted ADR with `RS doclint --approve`. Do not edit
it after that. Write a new ADR that supersedes it.

## `architecture.md`

The standard that the architecture reviewer uses. Each rule is a level-3 heading with a
unique ID:

```markdown
### ARCH-COMMENTS
A comment explains behaviour that the code cannot show: implicit behaviour, a dependency
outside our control, or code that is not intuitive. A comment never repeats the code.
```

A finding from the architecture reviewer blocks only when it cites a rule ID from this
file or from `learnings.md`. Ratchet adds these default rules to a new
`architecture.md`: `ARCH-COMMENTS`, `ARCH-NO-WEAKEN` (no skipped tests or silenced
checks without a reason), `ARCH-SCOPE` (only the work of the row) and `ARCH-REUSE` (use
the helper that exists).

## Writing rules (STE-lite)

These rules come from ASD-STE100. Ratchet does not ship the ASD dictionary, because it is
licensed.

| Rule | Check |
| --- | --- |
| A sentence has 25 words or fewer. | block |
| A procedure step has 20 words or fewer. | block |
| A paragraph has 6 sentences or fewer. | block |
| Use the active voice. | warn |
| Use simple tenses: no perfect and no progressive forms. | warn |
| A noun cluster has 3 words or fewer. | warn |
| One word has one meaning. Use the same name for the same thing. | review |
| Do not leave out articles, verbs or subjects. | review |

A procedure step is a numbered list item, an item under a heading that contains the whole
word `step`, `steps`, `procedure`, `how to`, `install` or `setup`, or a paragraph after
`<!-- ste: procedural -->`.

`RS stelint` checks the block and warn rules. It ignores front matter, code, URLs, tables
and headings. With `docs.ste: off`, it does not run.

## Word budgets

| Document | Budget |
| --- | --- |
| `prd.md` | 300 words |
| `spec.md` | 1200 words |
| `design-log.md`, before `## Results` | 2000 words |
| ADR | 600 words |

Front matter, headings, code blocks and tables do not count. Over budget is a `warn`. At
approval (`--approval`), it is a `block`.
