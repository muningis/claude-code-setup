"""decide <slug> <cp> <text> [--reopen b1|b3]: record the human's decision and start the next epoch."""
from __future__ import annotations

import os
import sys

import common
from common import RsError

REOPEN = {"b1": "B1", "b3": "B3"}


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--reopen"))
    except RsError as e:
        return common.emit("decide", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) < 3:
            raise RsError("usage: decide <slug> <cp> <text> [--reopen b1|b3]")
        slug = common.check_name("slug", pos[0])
        cp = common.check_name("cp", pos[1])
        text = " ".join(pos[2:]).strip()
        if not text:
            raise RsError("decide needs the decision text")
        reopen = opts.get("--reopen")
        if reopen is not None and reopen not in REOPEN:
            raise RsError("--reopen takes b1 or b3")
        root = common.repo_root()
        row = common.pick_row(common.load_plan(root, slug), cp)
        state, _ = common.load_state(root, slug, row)
        state["epoch"] += 1
        ev = common.ev_dir(root, slug, cp)
        path = os.path.join(ev, "decisions.md")
        head = "" if os.path.isfile(path) else "# Decisions\n\n"
        common.append_text(path, "%s## %s, epoch %d\n%s\n\n" % (head, common.now_iso(), state["epoch"], text))
        extra = {"epoch": state["epoch"]}
        if reopen:
            state["stage"] = REOPEN[reopen]
            if reopen == "b1":
                # The engine gives the next implementer this brief. The decision goes on top of what the
                # last failed gate wrote there; the gate that fails next keeps the whole text at its top.
                brief = os.path.join(ev, "1-brief-r%d.md" % (state["rounds"].get("b1", 0) + 1))
                old = common.read_text(brief).strip("\n")
                top = "## Decision from the human\n%s\n" % text
                common.write_text(brief, top + ("\n" + old + "\n" if old else ""))
                extra["brief"] = common.rel(root, brief)
            extra["stage"] = state["stage"]
        common.write_state(root, state)
        summary = "decision recorded; epoch %d" % state["epoch"]
        if reopen:
            summary += "; reopened at %s" % state["stage"]
        return common.emit("decide", "pass", summary, evidence=path, nonce=nonce, root=root, extra=extra)

    return common.run_guarded("decide", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
