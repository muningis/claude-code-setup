# baton

Pass the baton to the next Claude Code session. Two skills, one each way:

| Skill | Does |
| ----- | ---- |
| `/baton:handover` | writes what the next session needs |
| `/baton:resume` | reads it back, and leads with what has drifted since |

A session ends — context exhausted, day over, a fresh start wanted — and everything
that mattered goes with it: what we were actually trying to do, which alternatives
were already weighed and dropped, what was tried and failed, which of five repos
moves first.

The rule: **the handover comes from the session, not from the repo.** Git state is
observed by a script so it's factual; the reasoning exists only in the conversation,
and is the part worth carrying.

## Three scopes

| Scope | For | Leads with |
| ----- | --- | ---------- |
| `repo` | work inside one repository | that repo's state, file pointers, check commands |
| `workspace` | several repositories moving together | the **seam** — what spans them and which side lands first |
| `explore` | ideas, research, design; notes and scratch, no repo it belongs to | where the thinking stands: live options, what was ruled out, the next experiment |

Scope is auto-detected from what the session touched; force it with
`/baton:handover workspace`, or name roots explicitly.

## Usage

```
/baton:handover                        # for the current scope
/baton:handover workspace ~/workspace  # force the scope, explicit root
/baton:handover --dry                  # draft in chat, write nothing

/baton:resume                          # newest handover: read it, re-verify, start
/baton:resume <path>                   # a specific one
```

Handovers are written to `.claude/handovers/<stamp>-<slug>.md` under the repo,
workspace, or notes root (falling back to `~/.claude/handovers/`), and never
committed for you.

`resume` matters as much as writing: a handover ages. It re-runs the state
collector against the roots the document records and **leads with the drift** —
branches merged, steps already done, stashes popped — before picking up the first
action still standing.

## How it works

- `skills/handover/SKILL.md` — scope → gather → write → hand back the kickoff line.
- `skills/resume/SKILL.md` — find → check against reality → brief and start.
- `scripts/state.py` — shared by both (`$CLAUDE_PLUGIN_ROOT/scripts/state.py`).
  Gathers the machine-checkable half: repos in scope, branch, upstream ahead/behind,
  HEAD, uncommitted and untracked files, stashes, unpushed and recent commits — plus
  loose notes when a root holds no repo. Remote URLs are stripped of embedded
  credentials.

  ```
  python3 scripts/state.py               # the repo you're in
  python3 scripts/state.py ~/workspace   # every repo below a root
  ```

  Flags: `--depth N` (repo search depth, default 3), `--commits N`, `--files N`,
  `--no-parent-scan`.

## Pairs with

`recap` answers *what did I work on lately* (backwards, for you); `trail` answers
*why is this code like this* (backwards, from history); `baton` carries *this*
session forward, to the next Claude. `ratchet` writes minimal batons of its own, one per
checkpoint, and resets the context to them.

## Install

Add the parent `skillz` marketplace, then enable the `baton` plugin:

```
/plugin marketplace add muningis/skillz
/plugin install baton@skillz
```
