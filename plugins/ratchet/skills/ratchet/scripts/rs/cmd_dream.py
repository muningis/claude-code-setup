"""dream <step>: the learning loop. See references/dream.md.

harvest, curate, apply, install, uninstall are the steps of the loop. Two more serve dream-nightly.sh and
the router: `prompt` writes the reflection prompt, and `state` says whether a dream is due. Every step
runs from any folder: the dream is global, and its files live under the home folder."""
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
    "prompt": dream_sched.prompt,
    "state": dream_sched.state,
}


def main(argv):
    step = STEPS.get(argv[0]) if argv else None
    if step is None:
        msg = "usage: dream %s" % "|".join(STEPS)
        return common.emit("dream", "error", msg, harness_error=msg)
    return step(argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
