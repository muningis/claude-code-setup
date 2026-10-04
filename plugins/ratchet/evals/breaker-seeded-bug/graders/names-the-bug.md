---
type: llm
focus: { source: file, path: verdict.json }
weight: 2
---

PASS if a finding says that page numbering is off by one: page 1 skips the first items,
because the start index uses `number * size` instead of `(number - 1) * size`.
FAIL if no finding names this defect.
