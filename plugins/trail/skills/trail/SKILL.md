---
name: trail
description: >-
  Decision archaeology — reconstruct WHY a piece of code is the way it is, not
  just what it does. Follows the trail through two sources: git history (when it
  changed, in which commits) and your past Claude Code session transcripts (the
  prompts that asked for it, the reasoning, and the alternatives that were weighed
  and rejected — the why that never lands in a commit message). Use when asked
  "why is this like this / why do we do it this way", "how did this come to be",
  "what was the reasoning / thinking behind X", "the history of this decision",
  "why did we choose A over B", "what were we trying to do here", or to understand
  unfamiliar/surprising code before changing it. For a fix use snare; for "what
  did I work on lately" use recap — trail explains how one thing got the way it is.
allowed-tools: Bash(python3:*), Bash(git log:*), Bash(git blame:*), Bash(git show:*), Bash(git diff:*)
---

# Trail

Reconstruct how a piece of code got the way it is by weaving two sources into one
chronological narrative: git history (the *what*/*when*) and past Claude Code
session transcripts (the *why*, mined by a helper script).

Argument (`$ARGUMENTS`): what to trace — a file path, a symbol/function, a config
key, a feature or decision in words ("the problem+json error format", "why PGlite
for tests").

## Step 1 — Pin the target

Turn the ask into:
- **query tokens** for the transcript miner — the distinctive string(s): a symbol,
  a path basename, an RFC number, a config key, a feature name. Prefer specific
  tokens; multiple tokens are ANDed.
- **a git target** — the file(s), or a function, or a distinctive string to pickaxe.
- **scope** — which repo. If tracing a file, that file's repo.

If the ask is vague ("why is the auth like this"), first locate the actual code
(grep/read) so you have real symbols and files to trace, then proceed.

## Step 2 — git archaeology (the *what* / *when*)

Pick what fits the target:

- File over time: `git log --follow --oneline -- <file>`
- A function/line range: `git log -L :<function>:<file>` (or `-L <start>,<end>:<file>`)
- When a string/symbol entered or left: `git log -S'<string>' --oneline -- <path>`
  (pickaxe — great for "when did we start doing X")
- Read the commits that look pivotal: `git show <sha>` for the diff + full message.
- Current attribution: `git blame -L <start>,<end> <file>`

Note the pivotal commits (sha, date, one-line intent) — the spine of the timeline.
Don't stop here: commit messages are authoritative on facts but rarely explain the
*why*; that comes from Step 3.

## Step 3 — transcript archaeology (the *why*)

```
python3 ${CLAUDE_SKILL_DIR}/scripts/trail.py <tokens> --cwd <repo-path>
```

- Scope to the repo with `--cwd <repo-path>` when tracing a file there. If that
  comes back thin, **drop `--cwd`** (defaults to all projects) — a decision is
  often discussed in a session whose working dir was elsewhere.
- Narrow huge results by time with `--since 90d` (Nd/Nh/Nw or ISO date).
- Tune with `--max-hits N` (turns per session) and `--context CHARS` if snippets
  are too tight.

The script prints JSON: sessions in chronological order, each with its `goal` (the
first human prompt — what that whole session was for) and `hits`: matching `human`
prompts, `assistant` `reasoning`, and the `edit`/`command` turns that touched the
target. The `reasoning` hits are where the rejected alternatives and trade-offs
live — read those closely.

If the miner finds nothing (transcripts only cover work done through Claude Code
on this machine), say so and lean on git alone — don't invent intent.

## Step 4 — Synthesize the trail

Tell the story oldest → newest, lining up each pivotal commit with the reasoning
found for it. Surface, when the evidence shows it:

- **The original intent** — what problem the first version was solving.
- **Why this approach** — and explicitly, **what was considered and rejected**, with
  the stated reason. This is the highest-value output; lead with it when present.
- **How it changed since** — later commits that revised the decision, and why.
- **Gaps** — where git shows a change but no reasoning was found (or vice-versa).
  Be honest about what's evidenced vs inferred.

## Output structure

```markdown
## Trail: <target>

**Today:** <one line — what the code does now / current state>

**How it got here:**
- `<sha>` <date> — <what changed>. _Why:_ <reasoning from transcripts, or "no
  rationale found in transcripts">
- `<sha>` <date> — <what changed>. _Why:_ …

**Roads not taken:** <alternatives that were weighed and dropped, + the reason>

**Bottom line:** <the why, in one or two sentences — what to keep in mind before
changing this>
```

Drop any section with no evidence rather than padding it. If the trail is short
(one commit, one session), a couple of sentences beat the full template. Anchor
claims to the `sha` or session so the user can verify.
