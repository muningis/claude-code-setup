---
name: roast
description: Contrarian review of a plan, a design, documents or a diff. Finds the most likely ways it fails, with evidence and a fix for each finding. Use when the user asks to roast, stress-test or find the holes in something, and when ratchet plans a goal.
---

# Roast

A roast tests the work before reality does. It does not attack the author.

## Steps

1. **Collect** the absolute paths of the work to roast, the goal, and the settled
   decisions. Settled decisions come from the grill answers or from the human. The
   roast does not argue them again without new evidence.
2. **Spawn `ratchet:roaster`** with those paths and the settled decisions. A fresh agent
   does not share the author's reasons, so it sees what the author does not.
3. **Check each finding** before you show it. Open the evidence that it cites. Drop a
   finding when its evidence does not exist, and say how many you dropped.
4. **Show the result** in 15 lines or fewer:
   - the verdict: `SOUND`, `NEEDS_REWORK` or `INVESTIGATE`
   - the main strength, in one line
   - the findings, high severity first, each as: claim · evidence · fix

## After the roast

- Outside ratchet: propose the fixes. Apply them only when the human asks.
- Inside ratchet planning: `plan.md` says what to do with each verdict.
- `SOUND` is a real result. Do not search for problems that are not there.
