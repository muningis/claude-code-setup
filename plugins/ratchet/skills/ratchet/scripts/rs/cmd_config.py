"""config: print config.json as version 2, with a version 1 file migrated and defaults filled in."""
from __future__ import annotations

import json
import sys

import common
from common import RsError


def main(argv):
    try:
        common.parse_args(argv)
        cfg = common.load_config(common.repo_root())
    except RsError as e:
        sys.stderr.write("ratchet: %s\n" % e)
        return 2
    print(json.dumps(cfg, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
