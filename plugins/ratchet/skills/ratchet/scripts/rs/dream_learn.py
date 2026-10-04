"""Read and change learnings.md one entry at a time. Lines that an edit does not touch stay as they are."""
from __future__ import annotations

import re

import cmd_learnings
from common import RsError

FIELD = re.compile(r"^-\s*(scope|rule|check|source|origin)\s*:\s*(.*?)\s*$", re.I)
COUNTS = re.compile(r"helpful:\s*(\d+)\s*·\s*harmful:\s*(\d+)")
STATUS = re.compile(r"status:\s*([a-z-]+)")
BULLET = re.compile(r"^\s*[-*]\s+(\S.*?)\s*$")
# Where a missing field goes: after the nearest field that comes before it in the entry.
BEFORE = {"scope": (), "rule": ("scope",), "check": ("rule", "scope")}


def parse(text):
    """(lines, entries, bullets). An entry runs from its heading to the next heading of any level.

    Bullets are the version 1 lines that no entry owns, as (line number, text)."""
    lines = text.splitlines(True)
    entries = []
    bullets = []
    cur = None
    for i, line in enumerate(lines):
        m = cmd_learnings.ENTRY.match(line.strip())
        if m:
            if cur is not None:
                cur["end"] = i
            cur = {"id": m.group(1), "start": i, "end": len(lines), "fields": {}, "values": {},
                   "status": "active", "status_line": None, "helpful": 0, "harmful": 0}
            entries.append(cur)
            continue
        if line.startswith("#"):
            if cur is not None:
                cur["end"] = i
                cur = None
            continue
        if cur is None:
            b = BULLET.match(line)
            if b:
                bullets.append((i + 1, b.group(1)))
            continue
        f = FIELD.match(line.strip())
        if f and f.group(1).lower() not in cur["fields"]:
            cur["fields"][f.group(1).lower()] = i
            cur["values"][f.group(1).lower()] = f.group(2)
        # cmd_learnings reads the status from any line of the entry, so this reader does the same.
        s = STATUS.search(line)
        if s:
            cur["status"] = s.group(1)
            cur["status_line"] = i
        c = COUNTS.search(line)
        if c:
            cur["helpful"], cur["harmful"] = int(c.group(1)), int(c.group(2))
    for e in entries:
        e["scope"] = [g.strip() for g in e["values"].get("scope", "").split(",") if g.strip()]
        e["rule"] = e["values"].get("rule", "")
        e["check"] = e["values"].get("check", "")
    return lines, entries, bullets


def find(entries, eid):
    for e in entries:
        if e["id"] == eid:
            return e
    raise RsError("no entry %s in learnings.md" % eid)


def next_id(entries):
    top = 0
    for e in entries:
        m = re.fullmatch(r"L-(\d+)", e["id"])
        if m:
            top = max(top, int(m.group(1)))
    return "L-%03d" % (top + 1)


def v1_rule(bullet):
    """A version 1 bullet without its trailing `(cp5, 2026-10-02)` source."""
    return re.sub(r"\s*\([^()]*\)\s*$", "", bullet)


def _eol(line):
    return "\r\n" if line.endswith("\r\n") else "\n"


def _insert(lines, after, new):
    if not lines[after].endswith("\n"):
        lines[after] += "\n"
    lines.insert(after + 1, new + _eol(lines[after]))


def set_field(text, eid, name, value):
    """Replace one field of an entry, or add it when the entry has none."""
    lines, entries, _ = parse(text)
    e = find(entries, eid)
    idx = e["fields"].get(name)
    if idx is not None:
        lines[idx] = "- %s: %s%s" % (name, value, _eol(lines[idx]))
    else:
        after = max([e["fields"][n] for n in BEFORE[name] if n in e["fields"]] + [e["start"]])
        _insert(lines, after, "- %s: %s" % (name, value))
    return "".join(lines)


def edit(text, eid, scope=None, rule=None, check=None):
    for name, value in (("scope", scope), ("rule", rule), ("check", check)):
        if value is not None:
            text = set_field(text, eid, name, value)
    return text


def retire(text, eid, note=None):
    lines, entries, _ = parse(text)
    e = find(entries, eid)
    if e["status_line"] is not None:
        at = e["status_line"]
        lines[at] = STATUS.sub("status: retired", lines[at], count=1)
    else:
        at = e["end"] - 1
        while at > e["start"] and not lines[at].strip():
            at -= 1
        _insert(lines, at, "- status: retired")
        at += 1
    if note:
        _insert(lines, at, "- note: %s" % note)
    return "".join(lines)


def render(eid, scope, rule, check, source):
    return ("### %s\n- scope: %s\n- rule: %s\n- check: %s\n- source: %s\n- origin: dream\n"
            "- helpful: 0 · harmful: 0 · status: active\n" % (eid, scope, rule, check, source))


def append(text, entry_text):
    """Add an entry at the end. The text before it keeps its bytes, but for one blank line."""
    if text and not text.endswith("\n"):
        text += "\n"
    if text and not text.endswith("\n\n"):
        text += "\n"
    return text + entry_text
