---
type: llm
focus: { source: file, path: .claude/ratchet/evidence/demo/cp1/0-spec.json }
---

PASS if the `cases` list has 6 entries or fewer, each case name starts with `FR-001` or
`FR-002`, and `stubs` names a stub file for `src/slug.js`.
FAIL if there are more than 6 cases, a case name has no requirement ID, or there is no stub.
