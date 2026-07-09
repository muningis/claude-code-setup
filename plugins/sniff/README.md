# sniff

Find the scent, hand it to the [`snare`](../snare). `sniff` pulls a real error
from an app/service's logs, normalizes it into a reproduction recipe, and invokes
`/snare:snare` to fix it. It doesn't fix anything itself.

## How it resolves where the logs live (cache-first dynamic injection)

1. **Cache check** — a ```` ```! ```` bash-injection block in `SKILL.md` runs
   `cat .claude/sniff.json` at skill-load time, so the cached source lands in
   context with no tool call; if present, sniff skips straight to retrieval.
2. **Detect** — inspects the repo for signals (k8s manifests, Sentry SDK,
   `wrangler.toml`, Docker, local logfiles) and pre-fills what it can read.
3. **Ask once** — `AskUserQuestion` confirms the source and fills the blanks
   (namespace, selector, logfile path, DSN, time window).
4. **Cache it** — writes the resolved source + ready-to-run `retrieve` command to
   `.claude/sniff.json`, so future runs skip the question.

Re-detect with the `--refresh` argument.

## Flow

`resolve source → retrieve errors → normalize one into a repro recipe → /snare:snare`

## Skill

- `skills/sniff/SKILL.md` — invokable as `/sniff:sniff` (optional arg: a hint, a
  service/namespace, an error substring, or `--refresh`).

## Depends on

- [`snare`](../snare) — declared in `plugin.json` `dependencies`; install both.
