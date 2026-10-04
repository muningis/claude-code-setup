"""red-check <output-file>: say why a spec run failed (assert, stub, compile or runner)."""
from __future__ import annotations

import os
import re
import sys

import common
from common import RsError

# `error:` alone is no Swift rule: Bun and XCTest print it for plain assertion failures.
DEFAULT_KINDS = {
    "compile": [
        r"error TS\d+", r"SyntaxError", r"Cannot find module", r"ModuleNotFoundError",
        r"ImportError", r"cannot find symbol", r"Unresolved reference", r"^\s*e: .*\.kts?\b",
        r"\.swift:\d+(?::\d+)?: error:", r"error\[E\d+\]", r"\[build failed\]",
    ],
    "stub": [r"NotImplementedError", r"NotImplemented", r"not (?:yet )?implemented",
             r"TODO\(\)", r"unimplemented!"],
    "assert": [r"AssertionError", r"Expected", r"expect\(", r"AssertionFailedError",
               r"XCTAssert", r"assert"],
}
# Order decides ties: a file that cannot load never reached its assertions.
FAMILIES = ("compile", "stub", "assert")


def load_kinds(cfg):
    """Compiled regex for each family. behavior.failureKinds replaces a whole family."""
    custom = (cfg.get("behavior") or {}).get("failureKinds") or {}
    kinds = {}
    for fam in FAMILIES:
        pats = custom.get(fam) if isinstance(custom, dict) else None
        if isinstance(pats, str):
            pats = [pats]
        flags = 0
        if not (isinstance(pats, list) and pats):
            pats = DEFAULT_KINDS[fam]
            flags = re.I if fam == "stub" else 0
        try:
            kinds[fam] = re.compile("|".join("(?:%s)" % p for p in pats), flags)
        except re.error as e:
            raise RsError("bad regex in behavior.failureKinds.%s: %s" % (fam, e))
    return kinds


def classify(text, kinds):
    """Returns (kind, counts). counts holds the matching lines per family; runner is 1 when none match."""
    counts = {"assert": 0, "stub": 0, "compile": 0, "runner": 0}
    for line in text.splitlines():
        for fam in FAMILIES:
            if kinds[fam].search(line):
                counts[fam] += 1
                break
    for fam in FAMILIES:
        if counts[fam]:
            return fam, counts
    counts["runner"] = 1
    return "runner", counts


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--exit"))
    except RsError as e:
        return common.emit("red-check", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 1:
            raise RsError("usage: red-check <output-file> [--exit <code>]")
        if not os.path.isfile(pos[0]):
            raise RsError("no such file: %s" % pos[0])
        root = common.repo_root()
        kinds = load_kinds(common.load_config(root, required=False))
        text = common.strip_ansi(common.read_text(pos[0]))
        if "--exit" in opts and common.to_int(opts["--exit"], None) == 0:
            kind, counts = "pass", {"assert": 0, "stub": 0, "compile": 0, "runner": 0}
        else:
            kind, counts = classify(text, kinds)
        verdict = "pass" if kind in ("assert", "stub") else "fail"
        extra = {"kind": kind}
        extra.update(counts)
        summary = "%s: %d compile, %d stub, %d assert lines" % (
            kind, counts["compile"], counts["stub"], counts["assert"])
        return common.emit("red-check", verdict, summary, nonce=nonce, root=root, extra=extra)

    return common.run_guarded("red-check", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
