# snare

A reproduction-driven, red→green bugfix loop for Claude Code.

The rule: **the reproduction is the spec.** A fix isn't trusted until the *exact*
flow that exposed the bug comes back clean.

1. **Run the flow locally** — get the affected path running; record the exact recipe.
2. **Confirm reproduction** — observe the real failure; don't fix a bug you can't reproduce.
3. **Add a test (red team)** — capture the bug in a test that fails for the right reason.
4. **Write a fix (green team)** — smallest root-cause fix; test goes green, nothing else breaks.
5. **Repeat the same flow 1:1** — replay the recorded reproduction unchanged to prove it's gone.

## Skill

- `skills/snare/SKILL.md` — invokable as `/snare:snare`.

## Install

Add the parent `skillz` marketplace, then enable the `snare` plugin:

```
/plugin marketplace add muningis/skillz
/plugin install snare@skillz
```
