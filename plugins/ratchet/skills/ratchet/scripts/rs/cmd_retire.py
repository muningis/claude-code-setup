"""retire <slug> <cp> <path> --reason <text>: unpin one test file and log why."""
from __future__ import annotations

import os
import sys

import common
from common import RsError


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--reason"))
    except RsError as e:
        return common.emit("retire", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 3:
            raise RsError("usage: retire <slug> <cp> <path> --reason <text>")
        reason = (opts.get("--reason") or "").strip()
        if not reason:
            raise RsError("retire needs --reason <text>")
        slug = common.check_name("slug", pos[0])
        cp = common.check_name("cp", pos[1])
        root = common.repo_root()
        path = pos[2]
        if os.path.isabs(path):
            path = os.path.relpath(path, root)
        path = path.replace(os.sep, "/")
        if path.startswith("./"):
            path = path[2:]

        hits = []
        for d in common.pin_dirs(root, slug):
            entries = common.read_lock(root, d)
            if any(p == path for _, p in entries):
                hits.append((d, entries))
        if not hits:
            raise RsError("not pinned: %s" % path)

        for d, entries in hits:
            kept = "".join("%s\t%s\n" % (s, p) for s, p in entries if p != path)
            common.write_text(os.path.join(root, d, "spec.lock"), kept)
            locked = os.path.join(root, d, "locked")
            copy = os.path.join(locked, *path.split("/"))
            if os.path.isfile(copy):
                os.remove(copy)
            cur = os.path.dirname(copy)
            while cur.startswith(locked + os.sep) and os.path.isdir(cur) and not os.listdir(cur):
                os.rmdir(cur)
                cur = os.path.dirname(cur)

        amend = os.path.join(common.ev_dir(root, slug, cp), "0-amendments.md")
        head = "" if os.path.isfile(amend) else "# Amendments\n\n"
        common.append_text(amend, "%s- %s retired %s: %s\n" % (head, common.now_iso(), path, reason))
        return common.emit("retire", "pass", "unpinned %s" % path, evidence=amend, nonce=nonce,
                           root=root, extra={"path": path, "pins": [d for d, _ in hits]})

    return common.run_guarded("retire", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
