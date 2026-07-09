#!/usr/bin/env python3
"""Collect Claude Code sessions since the last standup, as raw material for a
standup summary. Walks ~/.claude/projects/<slug>/*.jsonl, picks sessions whose
activity falls in the window, and emits one JSON record per session:
project, branch, title, the human-typed prompts, time span, and a few counts.

The model turns this JSON into standup bullets — this script only gathers facts.

Usage:
  sessions.py [--since ISO|Nd|Nh|Nm] [--cwd PATH] [--all-projects]
              [--state PATH] [--no-update] [--json]

Window:
  default      from the saved last-run timestamp (state file) to now;
               first ever run falls back to the last 24h.
  --since      override the cutoff: an ISO8601 instant, or a relative span like
               2d / 12h / 90m / 1w. Does not touch the state file unless you
               also let it update.
Scope:
  default      only sessions whose cwd is the current directory or below it.
  --cwd PATH   scope to PATH and below instead of the current directory.
  --all-projects   every project, no cwd filter (whole-day cross-repo standup).

State:
  --state PATH  state file location (default ~/.claude/standup-state.json).
  --no-update   don't advance the saved last-run timestamp (dry run / re-run).
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"
DEFAULT_STATE = Path.home() / ".claude" / "standup-state.json"
MAX_PROMPT_CHARS = 2000  # keep huge pasted blobs from bloating the output


def parse_ts(s):
    """Parse an ISO8601 timestamp from the transcript into aware UTC datetime."""
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except (ValueError, AttributeError):
        return None


def resolve_since(value, now):
    """Turn a --since value into a UTC datetime. Accepts ISO or Nd/Nh/Nm/Nw."""
    m = re.fullmatch(r"(\d+)\s*([smhdw])", value.strip(), re.IGNORECASE)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = {
            "s": dt.timedelta(seconds=n),
            "m": dt.timedelta(minutes=n),
            "h": dt.timedelta(hours=n),
            "d": dt.timedelta(days=n),
            "w": dt.timedelta(weeks=n),
        }[unit]
        return now - delta
    ts = parse_ts(value)
    if ts is None:
        sys.exit(f"error: --since '{value}' is neither ISO8601 nor a span like 2d/12h/90m/1w")
    return ts


def text_of(content):
    """A user message's content is a string (typed prompt) or a list of blocks
    (tool results, attachments). Return the plain text, or None if it carries no
    real text (e.g. a pure tool_result)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b.get("text", "") for b in content
                 if isinstance(b, dict) and b.get("type") == "text"]
        joined = "\n".join(p for p in parts if p)
        return joined or None
    return None


def is_human_prompt(rec):
    """A genuine thing the user typed — not a tool result, meta line, sidechain
    sub-agent turn, or slash-command stdout."""
    if rec.get("type") != "user":
        return False
    if rec.get("isMeta") or rec.get("isSidechain"):
        return False
    if rec.get("toolUseResult") is not None:
        return False
    if rec.get("origin", {}).get("kind") != "human":
        return False
    # promptSource is "typed" for real input; tool/queue-driven turns differ.
    if rec.get("promptSource") not in (None, "typed"):
        return False
    txt = text_of(rec.get("message", {}).get("content"))
    if not txt:
        return False
    t = txt.strip()
    # Local-command echoes the harness injects; not user intent.
    if t.startswith("<local-command") or t.startswith("<command-"):
        return False
    return True


def scan_session(path):
    """Read one transcript; return a session summary dict, or None if it has no
    human activity at all."""
    title = None
    prompts = []
    first_ts = last_ts = None
    cwd = branch = None
    assistant_turns = 0

    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rtype = rec.get("type")
            if rtype == "ai-title":
                title = rec.get("aiTitle") or title
                continue
            ts = parse_ts(rec.get("timestamp"))
            if ts:
                if first_ts is None or ts < first_ts:
                    first_ts = ts
                if last_ts is None or ts > last_ts:
                    last_ts = ts
            if rec.get("cwd"):
                cwd = rec["cwd"]
            if rec.get("gitBranch"):
                branch = rec["gitBranch"]
            if rtype == "assistant":
                assistant_turns += 1
            elif rtype == "user" and is_human_prompt(rec):
                txt = text_of(rec["message"]["content"]).strip()
                if len(txt) > MAX_PROMPT_CHARS:
                    txt = txt[:MAX_PROMPT_CHARS] + " …[truncated]"
                prompts.append({"ts": rec.get("timestamp"), "text": txt})

    if not prompts and not title:
        return None
    return {
        "sessionId": path.stem,
        "title": title,
        "cwd": cwd,
        "gitBranch": branch if branch and branch != "HEAD" else None,
        "started": first_ts.isoformat() if first_ts else None,
        "ended": last_ts.isoformat() if last_ts else None,
        "promptCount": len(prompts),
        "assistantTurns": assistant_turns,
        "prompts": prompts,
        "_last_ts": last_ts,  # internal, stripped before output
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since")
    ap.add_argument("--cwd")
    ap.add_argument("--all-projects", action="store_true")
    ap.add_argument("--state", default=str(DEFAULT_STATE))
    ap.add_argument("--no-update", action="store_true")
    ap.add_argument("--include-empty", action="store_true",
                    help="keep sessions with no human-typed prompt (headless / "
                         "eval / subagent runs); excluded by default as noise")
    ap.add_argument("--json", action="store_true", help="emit raw JSON only")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    state_path = Path(args.state)

    # Resolve the cutoff.
    explicit_since = args.since is not None
    if explicit_since:
        cutoff = resolve_since(args.since, now)
        source = f"--since {args.since}"
    else:
        last_run = None
        if state_path.exists():
            try:
                last_run = parse_ts(json.loads(state_path.read_text()).get("lastRun"))
            except (json.JSONDecodeError, OSError):
                last_run = None
        if last_run:
            cutoff = last_run
            source = "saved last-run"
        else:
            cutoff = now - dt.timedelta(hours=24)
            source = "no saved state → last 24h"

    # Scope by cwd unless --all-projects.
    scope = None
    if not args.all_projects:
        scope = Path(args.cwd).resolve() if args.cwd else Path.cwd().resolve()

    if not PROJECTS.exists():
        sys.exit(f"error: {PROJECTS} not found — is this Claude Code?")

    sessions = []
    for jsonl in PROJECTS.glob("*/*.jsonl"):
        try:
            if dt.datetime.fromtimestamp(jsonl.stat().st_mtime, dt.timezone.utc) < cutoff:
                continue  # cheap mtime prefilter before parsing
        except OSError:
            continue
        s = scan_session(jsonl)
        if not s:
            continue
        if s["_last_ts"] is None or s["_last_ts"] < cutoff:
            continue
        # A standup is about work the human drove. Sessions with no typed prompt
        # are headless/eval/subagent runs — skip unless explicitly asked for.
        if s["promptCount"] == 0 and not args.include_empty:
            continue
        if scope is not None:
            if not s["cwd"]:
                continue
            try:
                sp = Path(s["cwd"]).resolve()
            except OSError:
                continue
            if sp != scope and scope not in sp.parents:
                continue
        sessions.append(s)

    sessions.sort(key=lambda s: s["_last_ts"])
    for s in sessions:
        del s["_last_ts"]

    out = {
        "generatedAt": now.isoformat(),
        "since": cutoff.isoformat(),
        "sinceSource": source,
        "scope": "all-projects" if scope is None else str(scope),
        "sessionCount": len(sessions),
        "sessions": sessions,
    }

    # Advance the watermark unless asked not to, or unless this was an ad-hoc
    # --since query (which shouldn't move the standup boundary).
    if not args.no_update and not explicit_since:
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            state_path.write_text(json.dumps({"lastRun": now.isoformat()}, indent=2))
            out["stateUpdated"] = now.isoformat()
        except OSError as e:
            out["stateUpdateError"] = str(e)

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
