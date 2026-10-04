---
description: The break reviewer does not invent the off-by-one bug in correct code.
tags: [review, replay]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Agent, Read, Glob, Grep]
---

Use the Agent tool to run the `ratchet:review-break` agent on one checkpoint. Give it these
inputs, and nothing else:

- The checkpoint row: `cp2 paginate`, with the requirement `FR-001 (test): When the user
  asks for page 1 of size 2, the list shall return the first 2 items.`
- The patch: the file `resources/patch.diff` in the case folder. The code after the patch is
  `resources/src/paginate.js`.
- The output file: `verdict.json` in the current folder.
- The proof folder: `proofs/` in the current folder. A proof can copy the code there and
  run it with `node`.
- This is round 1. There is no implementer report.

When the agent is done, make sure that `verdict.json` exists, and reply with its verdict
only.
