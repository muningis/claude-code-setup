---
name: sniff
description: >-
  Pull a real error from an app or service's logs, normalize it into a
  reproduction recipe, and hand it to the snare skill to fix. Figures out
  where the logs live by inspecting the repo (Kubernetes/kubectl, Sentry or
  other error trackers, Cloudflare/wrangler, Docker, local logfiles), confirms
  with the user, then caches that to .claude/sniff.json and injects it on
  later runs. Use when asked to check or pull error logs, triage a production
  or runtime error, see what an app is throwing, or start a fix from a
  crash/stacktrace in the logs. Not for fixing a bug you can already reproduce
  locally — use snare directly for that.
allowed-tools: Bash(cat:*), Bash(kubectl logs:*), Bash(docker logs:*), Bash(tail:*), Bash(journalctl:*)
---

# Sniff

Pull a real error from the logs, turn it into a reproduction recipe, and invoke
`/snare:snare` to fix it — sniff never fixes anything itself.

Optional `$ARGUMENTS`: a hint — service name, namespace, an error substring to
grep for — or `--refresh` to ignore the cache and re-detect.

## Step 1 — Resolve the log source

```!
cat .claude/sniff.json 2>/dev/null && echo '[sniff: cache HIT — use the JSON above unless --refresh was passed]' || echo '[sniff: cache MISS — no .claude/sniff.json; detect the source, ask once, then write it]'
```

- **HIT** and no `--refresh` → announce `using cached source: <source>` and skip
  to Step 2 with its `retrieve` command.
- **MISS**, invalid JSON, or `--refresh` → detect below. If you weren't in the
  repo root, Read `.claude/sniff.json` directly first — it may be a false miss.

1. **Detect candidates** by inspecting the repo, read-only: deployment or
   orchestration manifests, error-tracker SDKs and DSN env vars, container
   config, log directories, logging libraries, service files, dev/start
   scripts. Prefer whatever the repo itself already defines over a generic
   guess, and read off every knob you can (namespace, selector,
   container/service name, logfile path, DSN) so the question is pre-filled,
   not blank.

2. **Confirm with one AskUserQuestion**: offer the detected source(s), most
   likely first, and capture only the knobs you couldn't read from the repo
   (plus a time window). If detection is unambiguous and complete, state the
   source and proceed — but never guess silently when a knob is missing.

3. **Build the retrieve command** for the resolved source, e.g.
   `kubectl logs -n <ns> -l <selector> --tail=500 --since=<window> --previous`
   (`--previous` also catches a crashed/restarted pod). For an API-based
   tracker, pull newest issues first and note any auth/token the user must
   supply — never invent secrets.

4. **Write the cache** to `.claude/sniff.json` (create `.claude/` if needed) so
   later runs inject it. Stamp `resolvedAt` with the real date
   (`date -u +%FT%TZ` via the shell — you cannot compute time yourself).

```json
{
  "version": 1,
  "source": "kubernetes",
  "retrieve": "kubectl logs -n default -l app=gulbe --tail=500 --since=1h --previous",
  "errorPattern": "(?i)(error|exception|panic|traceback|fatal|unhandled)",
  "config": { "namespace": "default", "selector": "app=gulbe", "context": "garazas" },
  "resolvedAt": "2026-01-01T00:00:00Z",
  "notes": "free text — auth needed, quirks, etc."
}
```

## Step 2 — Retrieve the error logs

Run the resolved `retrieve` command and filter to errors with `errorPattern`
(stacktraces, exceptions, non-zero exits, 5xx). Keep surrounding context lines,
not just the matched line.

- Several **distinct** errors → don't silently pick one: surface the short list
  (newest / most frequent first) and use **AskUserQuestion** to let the user
  choose, defaulting to the most recent if they don't care.
- Nothing matches → report that plainly (source reachable, no errors in
  window) and offer to widen the time window or adjust the pattern. Do not
  fabricate an error to keep going.

## Step 3 — Normalize into a reproduction recipe

Extract exactly what `snare` step 1 needs:

- **Entry point** — the command / request / job / interaction that triggered it
  (infer from the log: route, handler, CLI args, message). State it concretely.
- **Inputs / env** — payload, params, relevant config/feature flags, runtime
  version, the affected service/namespace.
- **The concrete failure** — verbatim error message + stacktrace, timestamps,
  and frequency (one-off vs recurring). Real text, not a paraphrase.
- **Suspected location** — the file/function the trace points at, mapped into
  this repo if possible.

## Step 4 — Hand off to snare

Invoke **`/snare:snare`** with the recipe (entry point, inputs/env, verbatim
failure) as its starting context, so it opens at its Step 1 with the
reproduction already filled in; `snare` owns reproduction → red test → fix →
1:1 re-run from there.

If `snare` isn't installed, say so and prompt the user to enable it (it's a
declared dependency) rather than attempting the fix here.
