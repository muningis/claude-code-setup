---
name: sniff
description: >-
  Pull a real error from an app or service's logs, normalize it into a
  reproduction recipe, and hand it to the snare skill to fix. Figures out WHERE the
  logs live by inspecting the repo (Kubernetes/kubectl, Sentry or other error
  trackers, Cloudflare/wrangler, Docker, local logfiles), confirms with one
  question, then caches that to .claude/sniff.json and injects it on later runs.
  Use when asked to check or pull error logs, triage a production or runtime error,
  see what an app is throwing, or start a fix from a crash/stacktrace in the logs.
  Hands off to snare for the actual fix — not for fixing a bug you can already
  reproduce locally (use snare directly for that).
allowed-tools: Bash(cat:*), Bash(kubectl logs:*), Bash(docker logs:*), Bash(tail:*), Bash(journalctl:*)
---

# Sniff

Find the scent, then hand it to the snare. `sniff` turns "the app is throwing
something" into a concrete reproduction recipe and invokes `/snare:snare` to fix
it. It does **not** fix anything itself.

Optional argument (`$ARGUMENTS`): a hint — service name, namespace, an error
substring to grep for, or `--refresh` to ignore the cache and re-detect.

## Step 1 — Resolve the log source (cache-first)

The source is figured out **once per repo**, then cached to `.claude/sniff.json`
and injected on later runs. The block below runs at load time and pastes the
cached source (or a miss marker) into context — no tool call needed:

```!
cat .claude/sniff.json 2>/dev/null && echo '[sniff: cache HIT — use the JSON above unless --refresh was passed]' || echo '[sniff: cache MISS — no .claude/sniff.json; detect the source, ask once, then write it]'
```

1. **Read that cache block.**
   - **HIT** (and no `--refresh`): use it — announce `using cached source: <source>`
     and skip to Step 2 with its `retrieve` command. Don't re-detect or ask.
   - **MISS**, invalid JSON, or `--refresh`: continue to detection. (If you weren't
     in the repo root, Read `.claude/sniff.json` directly first — it may be a false
     miss.)

2. **Detect candidates** by inspecting the repo (read-only). Use these signals:

   | Source | Signals in the repo |
   | ------ | ------------------- |
   | `kubernetes` | `k8s/`, `*.yaml` with `kind: Deployment`/`Service`, `kustomization.yaml`, helm `Chart.yaml`, `Deployment` labels/namespace, references to `kubectl` |
   | `sentry` (or other tracker) | `@sentry/*` in package.json, `sentry-sdk` in requirements, `sentry.properties`, `SENTRY_DSN` in `.env*` |
   | `cloudflare` | `wrangler.toml`/`wrangler.jsonc`, Cloudflare in Terraform, Logpush config |
   | `docker` | `docker-compose.yml`/`compose.yaml`, `Dockerfile` (→ `docker logs <container>`) |
   | `local` | a `logs/` dir, a dev/start script in package.json, logging libs (pino/winston/bunyan, structlog), a `Procfile`, `journalctl`/`*.service` for systemd |

   Read off whatever you can (app label, namespace, container/service name,
   logfile path, DSN env var) so the question is pre-filled, not blank.

3. **Confirm with one question** via **AskUserQuestion**: offer the detected
   source(s) (most likely first) and capture only the knobs you couldn't read from
   the repo (namespace, selector, container, logfile path, DSN, time window). If
   detection is unambiguous and complete, state the source and proceed — but never
   guess silently when a knob is missing.

4. **Build the retrieve command** for the resolved source. Examples:
   - kubernetes: `kubectl logs -n <ns> -l <selector> --tail=500 --since=<window>`
     (add `--previous` to also catch a crashed/restarted pod)
   - docker: `docker logs --tail=500 --since=<window> <container>`
   - local file: `tail -n 1000 <logfile>` (or read the dev process output)
   - sentry/cloudflare: the API/CLI call for the project, newest issues first
     (note any auth/token the user must supply — never invent secrets)

5. **Write the cache** to `.claude/sniff.json` (create `.claude/` if needed) using
   the schema below, so the next run injects it. Stamp `resolvedAt` with the real
   date (`date -u +%FT%TZ` via the shell — you cannot compute time yourself).

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

Run the resolved `retrieve` command and pull recent log lines.

- Filter to errors with `errorPattern` (stacktraces, exceptions, non-zero exits,
  5xx). Keep surrounding context lines, not just the matched line.
- If several **distinct** errors show up, don't silently pick one — surface the
  short list (newest / most frequent first) and use **AskUserQuestion** to let the
  user choose which to chase, defaulting to the most recent if they don't care.
- If nothing matches, report that plainly (source reachable, no errors in window),
  and offer to widen the time window or adjust the pattern. Do not fabricate an
  error to keep going.

## Step 3 — Normalize into a reproduction recipe

Turn the chosen error into exactly what `snare` step 1 needs. Extract:

- **Entry point** — the command / request / job / interaction that triggered it
  (infer from the log: route, handler, CLI args, message). State it concretely.
- **Inputs / env** — payload, params, relevant config/feature flags, runtime
  version, the affected service/namespace.
- **The concrete failure** — verbatim error message + stacktrace, timestamps, and
  frequency (one-off vs recurring). Real text, not a paraphrase.
- **Suspected location** — the file/function the trace points at, mapped into this
  repo if possible.

## Step 4 — Hand off to snare

Invoke **`/snare:snare`** with the normalized recipe (entry point, inputs/env,
verbatim failure) as its starting context, so `snare` opens at its Step 1 with the
reproduction already filled in. `snare` owns reproduction → red test → fix → 1:1
re-run from there.

If `snare` isn't installed, say so and prompt the user to enable it (it's a
declared dependency) rather than attempting the fix here.

## Done means

- [ ] Log source resolved from cache, or detected + confirmed and **written** to
      `.claude/sniff.json`.
- [ ] Real error logs retrieved (or a clean "no errors in window" reported).
- [ ] One error normalized into a complete reproduction recipe.
- [ ] `/snare:snare` invoked with that recipe (or its absence reported).
