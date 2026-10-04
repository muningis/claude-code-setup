"""metrics add <json>: append one line to METRICS."""
from __future__ import annotations

import json
import sys

import common
from common import RsError


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("metrics add", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 2 or pos[0] != "add":
            raise RsError("usage: metrics add <json>")
        text = sys.stdin.read() if pos[1] == "-" else pos[1]
        try:
            entry = json.loads(text)
        except ValueError as e:
            raise RsError("metrics add: not valid JSON: %s" % e)
        if not isinstance(entry, dict):
            raise RsError("metrics add: the value must be a JSON object")
        entry.setdefault("ts", common.now_iso())
        root = common.repo_root()
        common.metrics_append(root, entry)
        return common.emit("metrics add", "pass", "added one line", nonce=nonce, root=root)

    return common.run_guarded("metrics add", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
