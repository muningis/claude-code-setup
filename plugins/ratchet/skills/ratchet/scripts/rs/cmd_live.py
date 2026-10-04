"""live start|set|stop: the LIVE file that shows what runs now."""
from __future__ import annotations

import json
import sys

import common
from common import RsError


def parse_value(text):
    try:
        return json.loads(text)
    except ValueError:
        return text


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("live", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")
    sub = pos[0] if pos else ""
    cmd = ("live " + sub).strip()

    def go():
        root = common.repo_root()
        path = common.live_path(root)
        if sub == "start":
            if len(pos) != 3:
                raise RsError("usage: live start <slug> <cp>")
            slug = common.check_name("slug", pos[1])
            cp = common.check_name("cp", pos[2])
            gate = None
            try:
                row = common.pick_row(common.load_plan(root, slug), cp)
                gate = common.load_state(root, slug, row)[0]["stage"]
            except RsError:
                pass  # a missing plan must not stop the run from showing itself
            live = {"active": True, "slug": slug, "cp": cp, "gate": gate, "round": 0,
                    "roles": [], "updated": common.now_iso()}
            common.write_json(path, live)
            return common.emit(cmd, "pass", "live on for %s/%s" % (slug, cp), nonce=nonce, root=root,
                               extra={"active": True})
        if sub == "set":
            if len(pos) != 3:
                raise RsError("usage: live set <key> <value>")
            live = common.read_json(path, default=None)
            if not isinstance(live, dict):
                raise RsError("no LIVE file: run live start first")
            if pos[1] == "updated":
                raise RsError("updated is set by the command")
            live[pos[1]] = parse_value(pos[2])
            live["updated"] = common.now_iso()
            common.write_json(path, live)
            return common.emit(cmd, "pass", "set %s" % pos[1], nonce=nonce, root=root, extra={"key": pos[1]})
        if sub == "stop":
            live = common.read_json(path, default=None)
            if not isinstance(live, dict):
                return common.emit(cmd, "pass", "no LIVE file", nonce=nonce, root=root, extra={"active": False})
            live["active"] = False
            live["updated"] = common.now_iso()
            common.write_json(path, live)
            return common.emit(cmd, "pass", "live off", nonce=nonce, root=root, extra={"active": False})
        raise RsError("usage: live start <slug> <cp> | live set <key> <value> | live stop")

    return common.run_guarded(cmd or "live", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
