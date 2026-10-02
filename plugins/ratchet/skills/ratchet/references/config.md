# `.claude/ratchet/config.json`

Written once per repo, in Part A, after the plan is approved.

```json
{
  "version": 1,
  "maxRounds": 3,
  "maxDiffLines": 600,
  "autoAfter": 2,
  "behavior": {
    "one": "bun test {files}",
    "all": "bun test",
    "extra": ["bun run check-types", "bun run lint"]
  },
  "visual": {
    "mode": "render",
    "capture": "bun scripts/ratchet-capture.tsx {target} {viewport} {out}",
    "reference": { "kind": "command", "capture": "bun scripts/ratchet-capture.tsx --legacy {target} {viewport} {out}" },
    "viewports": [375, 1280]
  },
  "architecture": ".claude/ratchet/architecture.md",
  "models": {}
}
```

| Key | Meaning |
| --- | ------- |
| `maxRounds` | Fix rounds per gate per checkpoint. When they run out, the row is `blocked`. |
| `maxDiffLines` | The size guard. A checkpoint whose `RS size` exceeds this is too big to review: split it instead. |
| `autoAfter` | `--auto` still holds the human gate on each checkpoint until this many rows of the plan are human-`approved`. `0` trusts `--auto` from cp1. |
| `behavior.one` | Runs only the given spec files. `{files}` is a space-separated list of shell-quoted, repo-root-relative paths. |
| `behavior.all`, `behavior.extra` | The full suite, then cheap static checks (types, lint). Each must exit 0, or fail only where the baseline already did. |
| `visual` | `null` for products without a UI; gate 2 then reads `n/a`. Otherwise, see below. |
| `architecture` | The standard both reviewers judge against. Part A drafts it when the repo has none. |
| `models` | Optional per-role model overrides, passed as the Agent `model:` parameter: `spec`, `implement`, `visual`, `reviewArch`, `reviewBreak`. Empty means each agent's own default; `review-break` defaults to Opus. |

## `visual`

Gate 2 compares **image files**: `ratchet:visual` can only read files. Every capture
must therefore write a PNG to disk.

| `mode` | How the capture is made | When |
| ------ | ----------------------- | ---- |
| `render` | `capture` renders `{target}` headless to `{out}` | the UI renders without a running app |
| `browser` | `capture` drives a real browser to `{url}`, puts it in `{target}`'s state, and screenshots to `{out}` | the state needs a running app, real data or interaction |

Placeholders:

| Placeholder | Meaning |
| ----------- | ------- |
| `{target}` | the row's `target` (a `[a-z0-9-]` name the script maps to a route, story or state) |
| `{viewport}` | one width from `viewports`; capture runs once per width |
| `{out}` | an absolute PNG path |
| `{url}` | browser mode only: `visual.url` for the implementation, the reference URL for the reference |

**Browser mode** adds these keys:
- `"url": "http://localhost:5173"`
- `"setup": "bun run dev"` (optional)
- `"ready"` (optional): a URL or command to poll. Defaults to `url`.
- `"teardown"` (optional). Defaults to killing the `setup` process.

The dev server's lifecycle:
1. **Before `setup`:** if `url` already answers, something else holds the port. It could
   be a stale server serving old code. Stop and ask; don't capture against it.
2. Start `setup` in the background (Bash `run_in_background`).
3. Poll `ready` for up to 60 s. If it never answers, that's `error`.
4. Restart it after each fix round, unless it hot-reloads.
5. Tear it down when the checkpoint leaves B2 or the run stops.

**Tooling.** For "render the JSX", the most faithful approach is mounting the real
component in Playwright: Playwright CT, or a Storybook story URL. satori + resvg needs no
browser, but it supports only a CSS subset. That's fine for simple components and
misleading for complex layouts.

If the capture script doesn't exist yet, building it is the plan's `cp0`. Use
claude-in-chrome there to work out how to reach each state, then write those steps into
the script. Gate 2 always runs the script; a screenshot that lives only in your context
isn't evidence.

**Determinism.** The capture must freeze everything that varies between runs: data, the
clock, randomness, animations and transitions, the caret. Fonts must load before the
shot.

Before the first real use, capture one target twice and `cmp -s` the two files.
- **Byte-identical:** the script is deterministic. This is what makes the cheap paths in
  gate 2 work: skipping the agent on identical captures, and the regression sweep.
- **Not identical:** compare the two captures with `ratchet:visual`. Any finding means
  the script is flaky. Fix it before gate 2 counts.

### `reference`: the oracle

| `kind` | Where the reference image comes from |
| ------ | ------------------------------------ |
| `url` | `capture` run with `{url}` = `reference.url`, e.g. a live legacy app, as in Helix |
| `command` | its own `capture` command, same placeholders; it renders the old implementation |
| `dir` | `<path>/<target>@<viewport>.png`: designs or mockups exported to files |
| `none` | there's no image. `ratchet:visual` judges against the checkpoint's expectation and the design rules in `architecture.md`, and returns `"oracle": "none"`. That's a weaker gate; the plan should say so. |
