---
name: grill
description: Interviews the user in rounds until each decision in a plan, design or idea is settled, with a recommended answer for each question. Use when the user asks to be grilled or to stress-test their thinking, and when ratchet plans a goal.
---

# Grill

The goal is a shared understanding before anyone builds. Treat the plan as a tree of
decisions: each decision has the decisions that depend on it.

## Rounds

1. **Find the facts yourself.** Read the code and the docs. For a broad search, use an
   Explore agent. Never ask the human a fact that you can find. While a search runs, only
   the questions that depend on it wait.
2. **Ask the frontier.** The frontier is each decision whose prerequisites are settled.
   Ask all of it in one round. Number the questions. Give a recommended answer for each.
3. **Wait for the answers.** Then mark the answered decisions as settled, add the new
   questions that the answers open, and find the next frontier.
4. A question that depends on another question of the same round waits for a later
   round.

Write each question in this form:

```markdown
**Q3 · Offline edits**: Can the user edit a note while offline? If yes, what happens on
a conflict: last write wins, or a merge prompt?
→ Recommended: yes, last write wins. Notes are personal, and conflicts are rare.
```

## Stop

Stop when the frontier is empty: each branch has an answer, and nothing is assumed
without saying so. Then:
1. List the settled decisions in the `Q<n>:` and `A:` format of ratchet's `docs.md`.
2. Ask the human to confirm this list in their own words. Do not act before they do.

## Keep it useful

- Count rounds, not questions. Five rounds are a lot. When you need more, the goal is
  probably too big. Propose a split.
- Ask only questions whose answer changes the design.
- When only a prototype can answer a question, say so. Propose a `choice` row or a spike
  instead of a guess.
- The decisions belong to the human. Recommend, but do not decide for them.
