"""row <slug> <cp> [<status>] [--base <sha>] [--note <text>]: change one row of the plan table."""
from __future__ import annotations

import sys

import common
from common import RsError

STATUSES = ("todo", "red", "green", "approved", "approved-unverified", "blocked", "superseded")


def set_cells(line, header, changes):
    """The table line with the named cells replaced. Other cells keep their text and order."""
    cells = common._split_row(line)
    while len(cells) < len(header):
        cells.append("")
    for name, value in changes.items():
        if name in header:
            cells[header.index(name)] = value
    return "| " + " | ".join(cells) + " |"


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--base", "--note"))
    except RsError as e:
        return common.emit("row", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) not in (2, 3):
            raise RsError("usage: row <slug> <cp> [<status>] [--base <sha>] [--note <text>]")
        slug = common.check_name("slug", pos[0])
        cp = common.check_name("cp", pos[1])
        changes = {}
        if len(pos) == 3:
            if pos[2] not in STATUSES:
                raise RsError("status must be one of: %s" % ", ".join(STATUSES))
            changes["status"] = pos[2]
        if "--base" in opts:
            changes["base"] = opts["--base"][:12]
        note = (opts.get("--note") or "").strip()
        if not changes and not note:
            raise RsError("nothing to change: give a status, --base or --note")
        root = common.repo_root()
        path = common.plan_path(root, slug)
        lines = common.read_text(path).splitlines()
        header = None
        done = False
        for i, line in enumerate(lines):
            if not line.lstrip().startswith("|"):
                continue
            cells = [c.lower() for c in common._split_row(line)]
            if header is None and "id" in cells and "status" in cells:
                header = cells
                continue
            if header is not None and common._split_row(line)[:1] == [cp]:
                lines[i] = set_cells(line, header, changes)
                done = True
                break
        if not done:
            raise RsError("no row %s in %s" % (cp, common.rel(root, path)))
        if note:
            if not any(l.strip() == "## Notes" for l in lines):
                lines += ["", "## Notes"]
            lines.append("- %s · %s" % (cp, note))
        common.write_text(path, "\n".join(lines) + "\n")
        # Parse again, so that a broken table fails here and not in the next gate.
        common.parse_plan_text(common.read_text(path))
        summary = "%s: %s" % (cp, ", ".join("%s=%s" % kv for kv in sorted(changes.items())) or "note added")
        return common.emit("row", "pass", summary, evidence=path, nonce=nonce, root=root,
                           extra={"cp": cp, "changes": changes})

    return common.run_guarded("row", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
