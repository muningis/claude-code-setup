"""size --prod <tree>: changed production and test lines since <tree>."""
from __future__ import annotations

import re
import sys

import common
from common import RsError

LOCK_RE = re.compile(r"(\.lockb?|package-lock\.json|pnpm-lock\.yaml|go\.sum)$")
# contracts.md says "generated files" without a definition. These are the unambiguous cases;
# size.generated in config.json adds more globs.
GENERATED = [
    "**/node_modules/**", "**/dist/**", "**/coverage/**", "**/.next/**", "**/__generated__/**",
    "**/*.generated.*", "**/*.min.js", "**/*.min.css", "**/*.map", "**/*.snap",
    "**/__snapshots__/**", "**/*.pb.go", "**/*_pb2.py", "**/DerivedData/**", "**/Pods/**",
    "**/.gradle/**", ".claude/ratchet/**",
]


def is_generated(cfg, path):
    extra = (cfg.get("size") or {}).get("generated")
    pats = GENERATED + ([str(x) for x in extra] if isinstance(extra, list) else [])
    return common.any_glob(pats, path)


def prod_size(root, cfg, tree):
    """Returns (prod, tests, test_net): changed lines in production and in test files, and net test growth."""
    prod = tests = test_net = 0
    for added, deleted, path in common.diff_numstat(root, tree):
        if added is None or deleted is None:
            continue  # binary
        if LOCK_RE.search(path) or is_generated(cfg, path):
            continue
        if common.is_test(cfg, path):
            tests += added + deleted
            test_net += added - deleted
        else:
            prod += added + deleted
    return prod, tests, test_net


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",), bool_flags=("--prod",))
    except RsError as e:
        return common.emit("size --prod", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if "--prod" not in opts or len(pos) != 1:
            raise RsError("usage: size --prod <tree>")
        root = common.repo_root()
        cfg = common.load_config(root, required=False)
        prod, tests, _ = prod_size(root, cfg, pos[0])
        return common.emit("size --prod", "pass", "prod %d, tests %d" % (prod, tests),
                           nonce=nonce, root=root, extra={"prod": prod, "tests": tests})

    return common.run_guarded("size --prod", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
