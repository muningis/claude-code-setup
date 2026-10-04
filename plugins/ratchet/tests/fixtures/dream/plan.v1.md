# iOS settings, native tab bar
slug: ios · created: 2026-10-03

| id | checkpoint | target | status | base |
| -- | ---------- | ------ | ------ | ---- |
| cp1 | settings store | - | approved | 2f078cd |
| cp2 | native tab bar + settings screen | settings | blocked | f537653 |
| cp3 | theme system | - | todo | |

## Notes
- cp1 · done when: the settings store persists a name and a theme.
- cp2 · blocked: maxRounds (3) spent; break CHANGES r3 with B8 (high). Needs human decision.
- cp2 · human (2026-10-02): retry with option (a), one more fix round.
- waive(cp1): V12 row highlight is 1dp smaller per side — human: "waive it" (2026-10-02)
- known server issue (out of scope): handlers await Redis.
