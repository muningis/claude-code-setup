# den

A Claude Code mod: pixel-art raccoons act out what Claude and its subagents are
doing, in a pane docked beside the transcript.

- **Calm, in any session.** Claude (the raccoon in the orange scarf) thinks with
  a bubble and holds a prop for the tool in hand: a book for Read, a laptop for
  Edit/Write, a hammer for Bash, a magnifier for search, a telescope for the web,
  a megaphone when it delegates. It naps when idle.
  - Each subagent climbs out of a trash can on the shelf, wearing a hat for its
    type (Explore: explorer hat; Plan: blue cap; the rest: hard hat).
  - It works with a live activity line, waves when done, and hops back in.
- **Hyper, during a [ratchet](../ratchet) run.** Five staggered stations, one per
  crew role (spec, implement, visual, review-arch, review-break). A raccoon stands
  at a station only while that role's agent works, so the den shows exactly who is
  at work. Other agents (Explore, …) run the conveyor as minions. Debris flies off
  the busy stations, and the gear never stops. The beats:
  - **Tamper:** sirens when `ratchet.sh check` catches a changed spec.
  - **Waiting on you:** the den freezes behind a **YOUR TURN!** sign at the human
    gate.
  - **Lock:** a gear CLICK when a checkpoint locks.
  - **Plan done:** confetti.

  Ratchet needs no changes: the den recognizes `ratchet:*` agents, the helper
  script and `.claude/ratchet/plans/`.

```
/den              open or close the pane
/den demo         a one-minute show: calm, then a full ratchet frenzy
/den calm|hyper   force a mode
/den auto off     don't open the pane when a subagent spawns (on by default)
```

- **When it opens on its own:** an unasked pane only seats in a terminal at least
  144 columns wide. `/den` opens it at any width.
- **Closing it:** if you close it, nothing reopens it unasked until you run `/den`.
- **Other surfaces:** the scene is a `Raster` (terminal only); desktop and the
  other surfaces get a text roster.

## Files

- `hooks/register.tsx`: events → `$.state`, the pane, `/den`, the animation timer
  (`$.ui.blit`, about 12 fps hyper / 4 fps calm, only while the pane is shown)
- `hooks/scene.ts`: the compositor (model → pixels → ▀ half-block cells)
- `hooks/sprites.ts`: the pixel art, as palette-coded grids
- `hooks/logic.ts`: pure readers (verdicts, plan tables, tool summaries)
- `hooks/den.test.ts`: `claude plugin test plugins/den`
