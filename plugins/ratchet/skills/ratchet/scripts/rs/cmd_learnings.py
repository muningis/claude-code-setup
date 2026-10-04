"""learnings --scope <path>... | --all: the learnings entries and stack rules that apply to these paths.

Prints markdown for an agent prompt, not JSON. A version 1 file (plain bullets, no entry IDs)
has no scopes, so all of it applies."""
from __future__ import annotations

import os
import re
import sys

import common
from common import RsError

ENTRY = re.compile(r"^###\s+(L-\d+|[A-Z][A-Z0-9]*-\d+)\s*$")
FIELD = re.compile(r"^-\s*(scope|rule|check|status)\s*:\s*(.*)$", re.I)


def entries(text):
    """[{id, scope: [globs], status, lines}] of each `### L-nnn` entry."""
    out = []
    cur = None
    for line in text.splitlines():
        m = ENTRY.match(line.strip())
        if m:
            cur = {"id": m.group(1), "scope": [], "status": "active", "lines": [line]}
            out.append(cur)
            continue
        if cur is None:
            continue
        if line.startswith("#"):
            cur = None
            continue
        cur["lines"].append(line)
        f = FIELD.match(line.strip())
        if f:
            key, val = f.group(1).lower(), f.group(2).strip()
            if key == "scope":
                cur["scope"] = [g.strip() for g in val.split(",") if g.strip()]
            elif key == "status":
                cur["status"] = val.split("·")[0].strip().lower() or "active"
        # The counters line also carries the status: "helpful: 0 · harmful: 0 · status: active".
        s = re.search(r"status:\s*([a-z-]+)", line)
        if s:
            cur["status"] = s.group(1).lower()
    return out


def applies(entry, paths):
    """paths None means every path."""
    if paths is None or not entry["scope"]:
        return True
    return any(common.glob_match(g, p) for g in entry["scope"] for p in paths)


def loose_text(text):
    """The text outside every entry, without the title. In a version 1 file, or a file that a
    dream changed, these are the old rules with no ID and no scope, so they always apply."""
    out = []
    in_entry = False
    for line in text.splitlines():
        if ENTRY.match(line.strip()):
            in_entry = True
            continue
        if in_entry and line.startswith("#"):
            in_entry = False
        if in_entry or re.match(r"^#\s", line):
            continue
        out.append(line)
    return "\n".join(out).strip()


def digest(title, text, paths):
    found = entries(text)
    if not found:
        return ("## %s\n\n%s\n" % (title, text.strip())) if text.strip() else ""
    keep = [e for e in found if e["status"] == "active" and applies(e, paths)]
    parts = []
    loose = loose_text(text)
    if loose:
        parts.append(loose)
    parts += ["\n".join(e["lines"]).rstrip() for e in keep]
    if not parts:
        return ""
    return "## %s\n\n%s\n" % (title, "\n\n".join(parts))


def render(root, cfg, paths=None):
    """The learnings and the stack rules that apply to these paths, as markdown. paths None means all."""
    parts = [digest("Learnings", common.read_text(os.path.join(common.r_dir(root), "learnings.md")), paths)]
    stacks_dir = os.path.join(os.path.expanduser("~"), ".claude", "ratchet", "stacks")
    for name in (cfg.get("dream") or {}).get("stacks") or []:
        if re.fullmatch(r"[A-Za-z0-9._-]+", str(name)):
            parts.append(digest("Stack rules: %s" % name,
                                common.read_text(os.path.join(stacks_dir, "%s.md" % name)), paths))
    return "\n".join(p for p in parts if p)


def main(argv):
    try:
        pos, opts = common.parse_args(argv, bool_flags=("--scope", "--all"))
    except RsError as e:
        sys.stderr.write("ratchet: %s\n" % e)
        return 2
    if not opts.get("--all") and (not opts.get("--scope") or not pos):
        sys.stderr.write("usage: learnings --scope <path>... | learnings --all\n")
        return 2
    try:
        root = common.repo_root()
        cfg = common.load_config(root, required=False)
    except RsError as e:
        sys.stderr.write("ratchet: %s\n" % e)
        return 2
    text = render(root, cfg, None if opts.get("--all") else pos)
    sys.stdout.write(text if text else "No learnings apply to these paths.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
