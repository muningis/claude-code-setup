#!/usr/bin/env python3
"""Dispatch `main.py <command> ...` to cmd_<command>.py. A hyphen in the command becomes `_`."""
import importlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def available():
    names = []
    for f in os.listdir(HERE):
        if f.startswith("cmd_") and f.endswith(".py"):
            names.append(f[4:-3].replace("_", "-"))
    return sorted(names)


def main(argv):
    if HERE not in sys.path:
        sys.path.insert(0, HERE)
    if not argv or argv[0] in ("-h", "--help", "help"):
        sys.stderr.write("usage: ratchet.sh <command> [args]\npython commands: %s\n" % " ".join(available()))
        return 2
    name = argv[0]
    module = "cmd_" + name.replace("-", "_")
    if not re.match(r"^[a-z][a-z0-9-]*$", name) or not os.path.isfile(os.path.join(HERE, module + ".py")):
        msg = "unknown command: %s" % name
        print(json.dumps({"ok": False, "cmd": name, "nonce": None, "verdict": "error",
                          "summary": msg, "evidence": None, "sha256": None, "harnessError": msg}))
        return 2
    return importlib.import_module(module).main(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
