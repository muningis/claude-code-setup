# scruff

Mentor mode for Claude Code. Teach, don't type.

`/scruff` flips Claude from *doing the work* to *making you do it* — and then holding
you to it. You're the kit; Scruff carries you through the design, keeps its paws off
your files, and grabs you by the scruff at review time.

Two phases, one hard rule the whole way through: **Scruff never touches your files**,
and **no criticism ships without proof**.

## How it works

- **Brief** — `/scruff lets implement a sqlite persistence layer`
  Claude refuses to write the code. Instead it lays out the structure and changes
  needed, the decisions and trade-offs, the exact spots in your codebase where the
  work lands, and **verified** links to the docs/spec you'll need (checked via
  context7 / WebFetch — no URLs from memory). Then it hands you the keyboard.
  The brief is persisted to `.claude/scruff.json` so the review works even if you
  come back in a fresh session.

- **Review** — `/scruff done` (or just tell it you're done)
  Claude reads what you built against the brief and grills it. Sharp and unsparing,
  but every hit lands with proof it can produce *now* — a Big-O argument, a runnable
  benchmark or a failing input, or a quoted spec line — not vibes. It points at the
  fixes; it doesn't type them. You get a verdict: what must change, what's just ugly,
  and what you nailed.

It's opt-in by design — it withholds code on purpose, so it only ever runs when you
invoke it, never on an ordinary "implement X" request.

## Pairs with

`snare` fixes a bug *for* you (red→green). `scruff` makes *you* fix it, then tells
you how badly you did.

## Install

Add the parent `skillz` marketplace, then enable the `scruff` plugin:

```
/plugin marketplace add muningis/skillz
/plugin install scruff@skillz
```
