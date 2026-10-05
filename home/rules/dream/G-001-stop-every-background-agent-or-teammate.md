---
dream-id: G-001
source: 2026-10-04 (cap, added by hand)
added: 2026-10-05
---
Stop every background agent or teammate with TaskStop once its task ends, before reporting. Do not leave idle agents running between steps. Before waiting on a quiet agent, check for file changes or processes.

Why: The human twice asked to close unneeded agents, asked whether agents were stuck, and reported 4-5 idle leftovers (c9ceb1e4#1629, c9ceb1e4#1749, 672cd670#1919). Approved by hand after the 3-item cap dropped it.
