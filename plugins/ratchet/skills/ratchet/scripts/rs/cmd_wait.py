"""wait <slug> <cp> <job> --nonce <n> [--timeout <s>]: wait for a detached gate and print its result."""
from __future__ import annotations

import json
import os
import sys
import time

import common
from common import RsError

DEFAULT_TIMEOUT = 480
MAX_TIMEOUT = 540  # the relay's Bash call stops after 600 s
POLL_SECONDS = 2


def read_result(path):
    """The gate's JSON object once the job has written all of it, else None.

    Only the last line counts, and only when it has the shape of a result. A command that the gate
    starts may write to the same stdout, and its output can be JSON too."""
    lines = [ln for ln in common.read_text(path).splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        obj = json.loads(lines[-1])
    except ValueError:
        return None
    return obj if isinstance(obj, dict) and isinstance(obj.get("verdict"), str) and "cmd" in obj else None


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--timeout"))
    except RsError as e:
        return common.emit("wait", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 3:
            raise RsError("usage: wait <slug> <cp> <job> --nonce <n> [--timeout <s>]")
        slug = common.check_name("slug", pos[0])
        cp = common.check_name("cp", pos[1])
        job = common.check_name("job", pos[2])
        if ".." in job:
            raise RsError("bad job: %r" % job)
        timeout = DEFAULT_TIMEOUT
        if "--timeout" in opts:
            timeout = common.to_int(opts["--timeout"], None)
            if timeout is None or timeout < 0:
                raise RsError("--timeout needs a number of seconds")
        timeout = min(timeout, MAX_TIMEOUT)
        root = common.repo_root()
        base = os.path.join(common.jobs_dir(root, slug, cp), job)
        pid = common.to_int(common.read_text(base + ".pid").strip(), None)
        if pid is None and not os.path.exists(base + ".json"):
            raise RsError("no such job: %s" % job)

        deadline = time.monotonic() + timeout
        while True:
            # Ask about the process first. A job that ends after this call has written its result before.
            alive = common.pid_alive(pid)
            result = read_result(base + ".json")
            if result is not None:
                result["nonce"] = nonce
                result["job"] = job
                return common.print_result(result)
            if not alive:
                errors = base + ".err"
                return common.emit("wait", "error", "job ended without output", nonce=nonce, root=root,
                                   evidence=errors if os.path.isfile(errors) and os.path.getsize(errors) else None,
                                   extra={"job": job}, harness_error="job ended without output")
            left = deadline - time.monotonic()
            if left <= 0:
                return common.emit("wait", "pending", "still running after %d s" % timeout, nonce=nonce,
                                   root=root, extra={"job": job})
            time.sleep(min(POLL_SECONDS, left))

    return common.run_guarded("wait", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
