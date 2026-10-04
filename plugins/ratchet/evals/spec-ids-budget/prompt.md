---
description: The spec agent writes few tests, names each one with its requirement ID, and skips the device requirement.
tags: [spec, replay]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Agent, Read, Glob, Grep]
---

Use the Agent tool to run the `ratchet:spec` agent on one checkpoint. Give it these inputs,
and nothing else:

- The repo: the current folder. It is empty. Tests run with `node --test <files>`.
- The checkpoint row: `cp1 slugify`, `kind: feature`, `reqs: FR-001,FR-002,FR-003`.
- The requirements, from `resources/requirements.md` in the case folder.
- The test budget: 3 tests for each requirement, 6 for the checkpoint.
- The output file: `.claude/ratchet/evidence/demo/cp1/0-spec.json` in the current folder.

When the agent is done, make sure that the output file exists, and reply with the number of
cases only.
