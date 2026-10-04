"""decide <slug> <cp> <text>: record the human's decision and start the next epoch."""
from __future__ import annotations

import os
import sys

import common
from common import RsError


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("decide", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) < 3:
            raise RsError("usage: decide <slug> <cp> <text>")
        slug = common.check_name("slug", pos[0])
        cp = common.check_name("cp", pos[1])
        text = " ".join(pos[2:]).strip()
        if not text:
            raise RsError("decide needs the decision text")
        root = common.repo_root()
        row = common.pick_row(common.load_plan(root, slug), cp)
        state, _ = common.load_state(root, slug, row)
        state["epoch"] += 1
        path = os.path.join(common.ev_dir(root, slug, cp), "decisions.md")
        head = "" if os.path.isfile(path) else "# Decisions\n\n"
        common.append_text(path, "%s## %s, epoch %d\n%s\n\n" % (head, common.now_iso(), state["epoch"], text))
        common.write_state(root, state)
        return common.emit("decide", "pass", "decision recorded; epoch %d" % state["epoch"],
                           evidence=path, nonce=nonce, root=root, extra={"epoch": state["epoch"]})

    return common.run_guarded("decide", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
