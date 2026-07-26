# rinse

A verification loop for Claude Code, to run when the work is done.

The rule: **a check set that hasn't been re-run since your last edit proves nothing.**
Fixing the type error is how you break the test — so every fix re-runs the whole set,
not just the check that failed.

1. **Load the check set** — cached per repo in `.claude/rinse.json`; detected and
   confirmed once on the first run.
2. **Scope it** — only checks whose `when` globs match the working diff.
3. **Run the automated checks** — commands first, then project-specific review rules.
4. **Fix and re-run everything** — bounded by `maxAttempts`, never by weakening a check.
5. **Hand you what only a human can confirm** — and wait for you to say it in your own
   words.

## Skill

- `skills/rinse/SKILL.md` — invokable as `/rinse:rinse`.

## Install

Add the parent `skillz` marketplace, then enable the `rinse` plugin:

```
/plugin marketplace add muningis/skillz
/plugin install rinse@skillz
```

## Wiring it into a repo

`rinse` is standalone — `/rinse:rinse` after finishing a change is the whole story.
To make it fire without being asked, add **one line** to that repo's `CLAUDE.md`:

```markdown
Before declaring any work done, run `/rinse:rinse`.
```

A pointer, not the procedure. `CLAUDE.md` is loaded into every session, so the
procedure belongs in the skill and the check commands belong in `.claude/rinse.json` —
neither costs you resident context. This one line is also in context while another
skill is running, which is how a finished `snare` bugfix ends up rinsed without
coupling the two plugins.

## `.claude/rinse.json`

Written for you on the first run. Commit it — it's the repo's definition of "done".

```json
{
  "version": 1,
  "maxAttempts": 3,
  "checks": [
    { "id": "types", "kind": "command", "run": "bun run check-types",
      "when": ["**/*.ts", "**/*.tsx"], "autofix": true },
    { "id": "lint", "kind": "command", "run": "bun run lint", "autofix": true },
    { "id": "tests", "kind": "command", "run": "bun test", "autofix": true },

    { "id": "log-hygiene", "kind": "review",
      "rule": "Every error log includes the request ID and never the request body or headers.",
      "when": ["src/server/**/*.ts"], "autofix": true },

    { "id": "mobile-nav", "kind": "manual",
      "instruct": "Open http://localhost:5173 at 375px wide and check that the nav collapses to a hamburger with no text overflow.",
      "when": ["app/ui/**", "**/*.css"] }
  ]
}
```

| Field | Meaning |
| ----- | ------- |
| `kind: command` | Claude runs `run`. Non-zero exit is a fail. |
| `kind: review` | No command exists — Claude reads the changed code and judges it against `rule`. For deterministic project rules no linter catches. |
| `kind: manual` | Claude **cannot** verify it. It states `instruct`, stops, and waits for you. |
| `when` | Glob list; the check runs only if the diff touches a match. Omit = always. |
| `autofix` | May Claude fix and re-loop? `manual` checks are never autofixed. |
| `maxAttempts` | Fix rounds per check before Claude stops and reports. Default 3. |

### Manual checks

The kind that exists because some things a model genuinely cannot check: whether the
layout looks right, whether the email actually arrived, whether it works on a real
phone.

Claude states what to check, then **stops and waits**. No buttons, no pass/fail
prompt, no sentence to recite — you reply however you normally would, and Claude
judges whether that message confirms the check:

- *"mobile nav collapses fine at 375, no overflow"* → confirmed, quoted in the report
- *"works, but the logo sits 2px low"* → a failure with detail; back into the fix loop
- *"looks good, what's next?"* → still `UNVERIFIED`, and the report says so

Silence is never a pass. A click would be a reflex and a scripted phrase would be a
formality; your actual words are the only version that can tell "works" from "works,
but".

## Arguments

`/rinse:rinse <hint>` — a check `id` to run alone, a path to restrict to, `--all` to
ignore `when` filters, or `--refresh` to re-detect the check set.

## Not this

- Hunting an unknown bug → `snare` (reproduce → red test → fix → 1:1 replay).
- Pulling an error out of production logs first → `sniff`.

`rinse` checks work you just did against checks the repo already has.
