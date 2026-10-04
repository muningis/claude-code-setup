"""Read and change learnings.md one entry at a time. Lines that an edit does not touch stay as they are.

The second half writes the other two targets of a dream: a global rule file, and an auto-memory file."""
from __future__ import annotations

import json
import os
import re

import cmd_learnings
import dream_io
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


# ---------------------------------------------------------------- global rule files

FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n?(.*)\Z", re.S)
GID = re.compile(r"^G-(\d+)")


def slugify(text, words=6, limit=40):
    """A file-name stem from the first words of a text: lowercase letters, digits and hyphens."""
    out = "-".join(re.findall(r"[a-z0-9]+", str(text).lower())[:words])[:limit].strip("-")
    return out or "rule"


def yaml_scalar(text):
    """The text as a YAML value: plain when that is safe, else a double-quoted JSON string."""
    t = " ".join(str(text).split())
    if re.match(r"[A-Za-z0-9(]", t) and not re.search(r":(\s|$)|\s#|\s$", t):
        return t
    return json.dumps(t, ensure_ascii=False)


def render_rule(gid, rule, why, paths, source, added, edited=None):
    """The text of a rule file. Claude Code reads only `paths` from the frontmatter and drops the rest."""
    fm = []
    if paths:
        fm.append("paths:")
        fm.extend("  - %s" % json.dumps(p, ensure_ascii=False) for p in paths)
    fm += ["dream-id: %s" % gid, "source: %s" % source, "added: %s" % added]
    if edited:
        fm.append("edited: %s" % edited)
    body = rule.strip() + ("\n\nWhy: %s" % why.strip() if why and why.strip() else "")
    return "---\n%s\n---\n%s\n" % ("\n".join(fm), body)


def parse_rule(text):
    """{id, paths, source, added, rule, why} of a rule file that the dream wrote, or None for any other file."""
    m = FRONTMATTER.match(text)
    if not m:
        return None
    fields = {}
    paths = []
    in_paths = False
    for line in m.group(1).splitlines():
        item = re.match(r"^\s+-\s+(.*?)\s*$", line)
        if in_paths and item:
            raw = item.group(1)
            try:
                paths.append(json.loads(raw) if raw.startswith('"') else raw.strip("'"))
            except ValueError:
                paths.append(raw)
            continue
        in_paths = False
        if line.startswith("paths:"):
            in_paths = True
            continue
        kv = re.match(r"^([A-Za-z-]+):\s*(.*?)\s*$", line)
        if kv:
            fields[kv.group(1)] = kv.group(2)
    if not re.fullmatch(r"G-\d+", fields.get("dream-id", "")):
        return None
    rule, _, why = m.group(2).strip().partition("\n\nWhy:")
    return {"id": fields["dream-id"], "paths": paths, "source": fields.get("source", ""),
            "added": fields.get("added", ""), "rule": rule.strip(), "why": why.strip()}


def rule_id(text):
    got = parse_rule(text)
    return got["id"] if got else None


def rule_files():
    """[(id, path, parsed)] for each active rule file of the dream folder."""
    base = dream_io.rules_dir()
    out = []
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        path = os.path.join(base, name)
        if name.endswith(".md") and os.path.isfile(path):
            got = parse_rule(dream_io.read_exact(path))
            if got:
                out.append((got["id"], path, got))
    return out


def next_gid(taken=()):
    """The next free rule ID. Retired files count, so that an ID is never used twice."""
    top = 0
    names = []
    for base in (dream_io.rules_dir(), dream_io.retired_dir()):
        names += os.listdir(base) if os.path.isdir(base) else []
    for n in names:
        m = GID.match(n)
        if m:
            top = max(top, int(m.group(1)))
    for t in taken:
        m = GID.match(t)
        if m:
            top = max(top, int(m.group(1)))
    return "G-%03d" % (top + 1)


# ---------------------------------------------------------------- auto-memory files

def memory_description(rule, limit=150):
    """One line of at most `limit` characters from a rule: its first sentence, or the first words."""
    t = " ".join(str(rule).split())
    first = re.split(r"(?<=[.!?])\s", t, maxsplit=1)[0]
    if len(first) <= limit:
        return first
    return t[:limit - 3].rsplit(" ", 1)[0].rstrip(",;:") + "..."


def render_memory(slug, description, rule, why, how):
    return ("---\nname: %s\ndescription: %s\nmetadata:\n  type: feedback\n  origin: dream\n---\n\n"
            "%s\n\n**Why:** %s\n**How to apply:** %s\n" % (slug, yaml_scalar(description), rule.strip(), why.strip(),
                                                          how.strip()))


def index_line(slug, description):
    return "- [%s](%s.md) \u2014 %s" % (slug, slug, " ".join(description.split()))


def append_index(text, line):
    """Add one line at the end of MEMORY.md. The text before it keeps its bytes."""
    if text and not text.endswith("\n"):
        text += "\n"
    return text + line + "\n"


def memory_rules(memory_dir):
    """The rule texts that a project already has: each line of MEMORY.md, and each file that the dream wrote."""
    out = []
    index = dream_io.read_exact(os.path.join(memory_dir, "MEMORY.md"))
    out += [ln.strip().lstrip("-* ").strip() for ln in index.splitlines() if ln.strip() and not ln.startswith("#")]
    for name in sorted(os.listdir(memory_dir)) if os.path.isdir(memory_dir) else []:
        if name.endswith(".md") and name != "MEMORY.md":
            text = dream_io.read_exact(os.path.join(memory_dir, name))
            if re.search(r"^\s+origin:\s*dream\s*$", text, re.M):
                m = FRONTMATTER.match(text)
                out.append((m.group(2) if m else text).strip().split("\n\n")[0])
    return out
