# iOS settings, native tab bar, marker & slips theme (4 document themes explored, slips chosen)
slug: ios-settings-themes · created: 2026-10-03
reference: command bun mobile/scripts/capture-mock.ts {target} {viewport} {out}

| id | checkpoint | target | status | base |
| -- | ---------- | ------ | ------ | ---- |
| cp8 | theme D marker slips | sheet-slips | approved | f8937d7 |
| cp9 | slips-only theme + settings without picker | settings | approved | b466827 |
| cp10 | slips buttons app-wide | home | red | 3b52794 |
| cp11 | player hand (chosen variant) | sheet-slips | todo | |
| cp12 | czar pick screen (chosen variant) | judging-slips | todo | |

## Notes
- decision: the pre-redesign look is removed; the 4 designs are the only themes, default MEMO. iOS only — web untouched.
- cp10 · done when: one slips button composable replaces DorButton's rounded look at every call site.
- cp11 · kind: refactor
- waive(cp5–cp8): submission chrome layout differs from the mocks — user chose "restyle, keep layout" (2026-10-03).
