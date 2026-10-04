#!/usr/bin/env python3
"""Decision archaeology: mine Claude Code session transcripts for the *reasoning*
behind a piece of code. Git tells you what changed and when; the transcripts hold
the why — the prompts that asked for it, the rationale, the alternatives that were
weighed and dropped. This finds the sessions that touched a file/symbol/topic and
pulls the relevant turns, so the model can reconstruct how the code got this way.

Usage:
  trail.py QUERY [QUERY ...] [--cwd PATH | --all-projects] [--since SPAN]
           [--max-sessions N] [--max-hits N] [--context CHARS]

QUERY     one or more tokens, ANDed. A path, a symbol, a feature name, an error
          string — whatever you're tracing. Matching is case-insensitive; every
          token must appear (in a session, then in a turn) for it to count.

Scope:
  --all-projects   (default) search every project's transcripts.
  --cwd PATH       only sessions whose working dir is PATH or below — use this to
                   stay within one repo when tracing a file there.
  --since SPAN     ignore sessions older than SPAN (Nd/Nh/Nw/Nm or ISO date).

Output: JSON. Sessions in chronological order (the trail of how it evolved), each
with the session's goal (first human prompt) and the matching turns: human asks,
assistant reasoning, and the edits/commands that touched the target.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path

PROJECTS = Path.home() / ".claude" / "projects"


def parse_ts(s):
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(dt.timezone.utc)
    except (ValueError, AttributeError):
        return None


def resolve_since(value, now):
    import re
    m = re.fullmatch(r"(\d+)\s*([smhdw])", value.strip(), re.IGNORECASE)
    if m:
        n, unit = int(m.group(1)), m.group(2).lower()
        delta = {"s": dt.timedelta(seconds=n), "m": dt.timedelta(minutes=n),
                 "h": dt.timedelta(hours=n), "d": dt.timedelta(days=n),
                 "w": dt.timedelta(weeks=n)}[unit]
        return now - delta
    ts = parse_ts(value)
    if ts is None:
        sys.exit(f"error: --since '{value}' is neither ISO8601 nor a span like 2d/12h/1w")
    return ts


def snippet(text, tokens, context):
    """A window of `text` centered on the first token hit, collapsed to one line."""
    flat = " ".join(text.split())
    low = flat.lower()
    pos = min((low.find(t) for t in tokens if t in low), default=-1)
    if pos < 0:
        return flat[:context * 2] + (" …" if len(flat) > context * 2 else "")
    start = max(0, pos - context // 2)
    end = min(len(flat), pos + context)
    out = flat[start:end]
    if start > 0:
        out = "… " + out
    if end < len(flat):
        out = out + " …"
    return out


def assistant_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def human_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") for b in content
                         if isinstance(b, dict) and b.get("type") == "text")
    return ""


def tool_uses(content):
    """Yield (name, input_dict) for each tool_use block in an assistant message."""
    if isinstance(content, list):
        for b in content:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                yield b.get("name", ""), b.get("input", {}) or {}


def line_matches(low_line, tokens):
    return all(t in low_line for t in tokens)


def scan(path, tokens, context, max_hits):
    """Full structured scan of a candidate transcript. Returns a session dict or
    None. Records the session goal (first human prompt) plus matching turns:
    human prompts, assistant reasoning, and edits/commands hitting the target."""
    title = goal = cwd = branch = None
    first_ts = last_ts = None
    hits = []

    with path.open(encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            raw = raw.strip()
            if not raw:
                continue
            low = raw.lower()
            # Cheap gate: only parse lines that could matter (a token line, or a
            # user record we might need for the goal/timespan). json.loads is the
            # expensive part, so skip it for the bulk of non-matching lines.
            tok_hit = line_matches(low, tokens)
            is_user = '"type":"user"' in low or '"type": "user"' in low
            if not (tok_hit or is_user or '"ai-title"' in low):
                continue
            try:
                rec = json.loads(raw)
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

            msg = rec.get("message", {}) or {}
            content = msg.get("content")

            # Session goal: first genuine human-typed prompt.
            if (goal is None and rtype == "user"
                    and not rec.get("isMeta") and not rec.get("isSidechain")
                    and rec.get("toolUseResult") is None
                    and rec.get("origin", {}).get("kind") == "human"):
                gt = human_text(content).strip()
                if gt and not gt.startswith(("<local-command", "<command-")):
                    goal = gt[:500]

            if not tok_hit:
                continue

            tss = rec.get("timestamp")
            if rtype == "user":
                if rec.get("toolUseResult") is not None or rec.get("isMeta"):
                    continue  # tool output / meta, not a human turn
                if rec.get("origin", {}).get("kind") != "human":
                    continue
                txt = human_text(content)
                if line_matches(txt.lower(), tokens):
                    hits.append({"ts": tss, "role": "human", "kind": "prompt",
                                 "text": snippet(txt, tokens, context)})
            elif rtype == "assistant":
                txt = assistant_text(content)
                if txt and line_matches(txt.lower(), tokens):
                    hits.append({"ts": tss, "role": "assistant", "kind": "reasoning",
                                 "text": snippet(txt, tokens, context)})
                for name, inp in tool_uses(content):
                    blob = json.dumps(inp).lower()
                    if not line_matches(blob, tokens):
                        continue
                    if name in ("Edit", "Write", "NotebookEdit"):
                        fp = inp.get("file_path") or inp.get("notebook_path") or "?"
                        hits.append({"ts": tss, "role": "assistant", "kind": "edit",
                                     "text": f"{name} {fp}"})
                    elif name == "Bash":
                        cmd = " ".join((inp.get("command") or "").split())
                        hits.append({"ts": tss, "role": "assistant", "kind": "command",
                                     "text": cmd[:context]})

    if not hits:
        return None
    if len(hits) > max_hits:
        hits = hits[:max_hits]
    return {
        "sessionId": path.stem,
        "title": title,
        "project": Path(cwd).name if cwd else None,
        "projectPath": cwd,
        "gitBranch": branch if branch and branch != "HEAD" else None,
        "started": first_ts.isoformat() if first_ts else None,
        "ended": last_ts.isoformat() if last_ts else None,
        "goal": goal,
        "hitCount": len(hits),
        "hits": hits,
        "_last_ts": last_ts,
    }


def file_is_candidate(path, tokens):
    """Whole-file cheap gate: every token must appear somewhere in the file."""
    try:
        seen = {t: False for t in tokens}
        remaining = len(tokens)
        with path.open(encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                low = raw.lower()
                for t in tokens:
                    if not seen[t] and t in low:
                        seen[t] = True
                        remaining -= 1
                        if remaining == 0:
                            return True
        return remaining == 0
    except OSError:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="+")
    ap.add_argument("--cwd")
    ap.add_argument("--all-projects", action="store_true")
    ap.add_argument("--since")
    ap.add_argument("--max-sessions", type=int, default=40)
    ap.add_argument("--max-hits", type=int, default=10)
    ap.add_argument("--context", type=int, default=240)
    args = ap.parse_args()

    tokens = [t.lower() for t in args.query if t.strip()]
    if not tokens:
        sys.exit("error: empty query")

    now = dt.datetime.now(dt.timezone.utc)
    cutoff = resolve_since(args.since, now) if args.since else None

    scope = None
    if not args.all_projects and args.cwd:
        scope = Path(args.cwd).resolve()
    # NOTE: trail defaults to ALL projects — a decision may have been discussed in
    # a session with a different cwd. Pass --cwd to stay within one repo.

    if not PROJECTS.exists():
        sys.exit(f"error: {PROJECTS} not found — is this Claude Code?")

    sessions = []
    for jsonl in PROJECTS.glob("*/*.jsonl"):
        if cutoff is not None:
            try:
                if dt.datetime.fromtimestamp(jsonl.stat().st_mtime, dt.timezone.utc) < cutoff:
                    continue
            except OSError:
                continue
        if not file_is_candidate(jsonl, tokens):
            continue
        s = scan(jsonl, tokens, args.context, args.max_hits)
        if not s:
            continue
        if cutoff is not None and (s["_last_ts"] is None or s["_last_ts"] < cutoff):
            continue
        if scope is not None:
            if not s["projectPath"]:
                continue
            try:
                sp = Path(s["projectPath"]).resolve()
            except OSError:
                continue
            if sp != scope and scope not in sp.parents:
                continue
        sessions.append(s)

    sessions.sort(key=lambda s: (s["_last_ts"] or now))
    truncated = len(sessions) > args.max_sessions
    if truncated:
        sessions = sessions[-args.max_sessions:]  # keep the most recent N
    for s in sessions:
        del s["_last_ts"]

    print(json.dumps({
        "query": args.query,
        "scope": "all-projects" if scope is None else str(scope),
        "since": cutoff.isoformat() if cutoff else None,
        "sessionCount": len(sessions),
        "truncated": truncated,
        "sessions": sessions,
    }, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
