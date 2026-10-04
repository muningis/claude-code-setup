"""dream <step>: the learning loop. See references/dream.md.

harvest, curate, apply, install, uninstall and register are the steps of the loop. Two more serve
dream-nightly.sh: `repos` lists the repos that opted in, and `prompt` writes the reflection prompt."""
from __future__ import annotations

import sys

import common
import dream_apply
import dream_curate
import dream_harvest
import dream_sched

STEPS = {
    "harvest": dream_harvest.main,
    "curate": dream_curate.main,
    "apply": dream_apply.main,
    "install": dream_sched.install,
    "uninstall": dream_sched.uninstall,
    "register": dream_sched.register,
    "repos": dream_sched.repos,
    "prompt": dream_sched.prompt,
}


def main(argv):
    step = STEPS.get(argv[0]) if argv else None
    if step is None:
        msg = "usage: dream %s" % "|".join(STEPS)
        return common.emit("dream", "error", msg, harness_error=msg)
    return step(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
