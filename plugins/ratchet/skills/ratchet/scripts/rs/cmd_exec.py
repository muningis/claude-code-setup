"""exec --timeout <s> -- <cmd>: run a shell command; on a timeout stop its process group and exit 124."""
from __future__ import annotations

import shlex
import sys

import common
from common import RsError


def main(argv):
    if "--" in argv:
        cut = argv.index("--")
        head, words = argv[:cut], argv[cut + 1:]
    else:
        head, words = argv, None
    try:
        pos, opts = common.parse_args(head, value_flags=("--timeout",))
    except RsError as e:
        sys.stderr.write("ratchet: %s\n" % e)
        return 2
    if words is None:
        words = pos
    elif pos:
        words = []
    if not words:
        sys.stderr.write("ratchet: usage: exec --timeout <s> -- <cmd>\n")
        return 2
    timeout = 900
    if "--timeout" in opts:
        timeout = common.to_int(opts["--timeout"], None)
        if timeout is None or timeout < 0:
            sys.stderr.write("ratchet: --timeout needs a number of seconds\n")
            return 2
    cmd = words[0] if len(words) == 1 else shlex.join(words)
    rc, _ = common.run_command(cmd, common.repo_root(), timeout)
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
