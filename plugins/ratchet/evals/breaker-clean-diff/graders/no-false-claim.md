---
type: llm
focus: { source: file, path: verdict.json }
weight: 2
---

PASS if no finding claims that page 1 returns the wrong items, or that the start index is
off by one. Findings about other edge cases are allowed.
FAIL if any finding claims an off-by-one error in the page start.
