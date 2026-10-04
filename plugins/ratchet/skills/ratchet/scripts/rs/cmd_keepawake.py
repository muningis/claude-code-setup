"""keepawake start|stop: keep a Mac awake during a run, with caffeinate."""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys

import common
from common import RsError

# caffeinate stops by itself after this time, so a lost stop never keeps the Mac awake for good.
LIMIT_SECONDS = 12 * 3600


def pid_path(root):
    return os.path.join(common.r_dir(root), ".keepawake.pid")


def running(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("keepawake", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 1 or pos[0] not in ("start", "stop"):
            raise RsError("usage: keepawake start|stop")
        root = common.repo_root()
        path = pid_path(root)
        old = common.to_int(common.read_text(path).strip(), None)
        if pos[0] == "stop":
            if old and running(old):
                os.kill(old, signal.SIGTERM)
            if os.path.exists(path):
                os.remove(path)
            return common.emit("keepawake", "pass", "stopped", nonce=nonce, root=root)
        if old and running(old):
            return common.emit("keepawake", "pass", "already on (pid %d)" % old, nonce=nonce, root=root)
        tool = shutil.which("caffeinate")
        if sys.platform != "darwin" or not tool:
            return common.emit("keepawake", "pass", "not needed on this system", nonce=nonce, root=root)
        # -i stops idle sleep; -s stops system sleep on AC power. The display may still sleep.
        proc = subprocess.Popen([tool, "-i", "-s", "-t", str(LIMIT_SECONDS)],
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL, start_new_session=True)
        common.write_text(path, "%d\n" % proc.pid)
        return common.emit("keepawake", "pass", "on (pid %d, %d h at most)" % (proc.pid, LIMIT_SECONDS // 3600),
                           nonce=nonce, root=root)

    return common.run_guarded("keepawake", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
