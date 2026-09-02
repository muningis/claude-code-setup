---
name: handover
description: >-
  Write a handover so the next Claude Code session can pick this work up: the
  mission, the state observed in the repos right now, the decisions taken and the
  alternatives rejected, dead ends, open questions, and ordered next steps starting
  with one concrete first action. Covers a single repository, a workspace spanning
  several repositories, or an exploration workspace where notes and ideas are the
  artifact. Use when a session is out of context or nearly, when asked to hand over,
  wrap up, "write continuation notes / a prompt for a new session", or "let's
  continue this tomorrow". To pick a handover back up use the resume skill; for
  "what did I work on lately" use recap.
allowed-tools: Read, Write, Glob, Grep, AskUserQuestion, Bash(python3:*), Bash(git status:*), Bash(git log:*), Bash(git diff:*), Bash(git branch:*), Bash(date:*), Bash(mkdir:*)
---

# Handover

Write down what the next session needs and nothing else, so it starts where this
one stopped instead of re-deriving it.

**The handover comes from this session, not from the repo.** State is observed by
the script below; the mission, the reasoning and the dead ends exist only in this
conversation and vanish with it. If a fact is in neither, it doesn't go in.

Optional `$ARGUMENTS`: `repo` / `workspace` / `explore` to force the scope, one or
more paths to hand over, `--dry` to draft in chat and write nothing.

## 1 — Scope

```bash
python3 "$CLAUDE_PLUGIN_ROOT/scripts/state.py" [ROOT ...]
```

No `ROOT` reports the repo you're in and counts the repos beside it; with roots it
reports each, searching a non-repo root for repos below it.

`suggestedScope` is a starting point — the real question is what *this session*
worked on:

- **repo** — one repository. Leads with its state, file pointers and check commands.
- **workspace** — several repos moved together. Leads with the seam between them.
- **explore** — ideas, research, design, with no repo the work belongs to. Leads
  with the thinking.

Take the obvious reading. Ask one AskUserQuestion only if genuinely torn (a high
`siblingRepoCount` where you can't tell if a sibling is in play), never when
`$ARGUMENTS` named a scope. For workspace scope, re-run the script with every root
so no repo's state is guessed.

## 2 — Gather

The script gives branches, upstream ahead/behind, HEAD, uncommitted and untracked
files, stashes, unpushed and recent commits. Add, cheaply:

- `git diff --stat` (and `--cached`) per dirty repo — *what* the uncommitted work
  is, not just which files.
- Any pushed branch or open PR that came up in this session.
- The commands that prove things work, with their last result.

Then mine **this conversation** for what no command can produce: the goal and why
it matters; decisions and the alternatives dropped, with the reason; dead ends
already paid for; constraints the user stated; what's still open.

## 3 — Write it

Stamp from the shell (`date -u +%Y-%m-%d-%H%M`) — you can't compute the time. Write
to `.claude/handovers/<stamp>-<slug>.md` under the repo root, the workspace root
(the common parent), or the notes root — `~/.claude/handovers/` if the work has no
home on disk. `<slug>` is 2–4 kebab-case words naming the work
(`pglite-test-harness`, not `handover`). Keep the `roots` line accurate: `resume`
re-runs the collector against it.

```markdown
# Handover — <what the work is>

<!-- scope: repo|workspace|explore · roots: <absolute path(s), space-separated>
     · written: <UTC stamp> -->

**Start here:** <the single first action, concrete enough to act on without
re-reading anything: the file, the command, the question to ask.>

## Mission
<2–4 sentences: what we're doing and why. The goal, not the changelog.>

## State
<Per repo — path, branch, HEAD sha + subject, ahead/behind, uncommitted work and
what it contains, stashes.>

## Decisions (and what was rejected)
- <decision> — because <reason>. Rejected <alternative>: <why>.

## Next steps
1. <ordered, concrete, one outcome each>

## Dead ends
- <tried X, failed because Y — don't retry blind>

## Open questions
- <unresolved or for the user, and what it blocks>

## Pointers
- `path/to/file.ts:120` — <why it matters>
- Checks: `<the real command>` — <last known result>
```

Drop any section with nothing real in it — a padded handover gets skimmed, and a
skimmed handover fails. Scope shifts the weight:

- **workspace** — one State block per repo, plus a **Seam** section: what spans
  them, which side lands first, what breaks if they land out of order. That
  ordering is the thing a new session cannot re-derive.
- **explore** — replace State with **Where the thinking stands**: live options, the
  criteria they're judged on, what's ruled out and why, the next experiment. No
  invented code state.

Rules: never write a secret (name the env var, never its value); never assert state
you didn't observe; never invent a next step — "ask the user" is a valid one. Don't
commit or push the file unasked, and if it lands inside a repo that doesn't ignore
it, say so once.

## 4 — Hand it back

Report the path, the scope and what's in flight, then the kickoff line to paste
into the new session:

```
/baton:resume <path>
```

Add a 3–5 sentence plain-text version of the mission and first action, for a
session started where this plugin isn't installed. With `--dry`, print the draft
and write nothing.
