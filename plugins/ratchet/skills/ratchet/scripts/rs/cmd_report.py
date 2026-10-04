"""report <slug> <cp>: write EV/4-report.md and print at most 10 lines for the human."""
from __future__ import annotations

import os
import re
import sys

import cmd_size
import common
from common import RsError


def short(text, n=90):
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[:n - 3] + "..."


def numbered(ev, pattern):
    """[(round, data)] for the JSON files in ev that match pattern, in round order."""
    found = []
    if os.path.isdir(ev):
        for name in os.listdir(ev):
            m = re.match(pattern, name)
            if not m:
                continue
            try:
                data = common.read_json(os.path.join(ev, name))
            except RsError:
                continue
            if isinstance(data, dict):
                found.append((int(m.group(1)), data))
    return sorted(found, key=lambda t: t[0])


def main(argv):
    try:
        pos, _ = common.parse_args(argv)
        if len(pos) != 2:
            raise RsError("usage: report <slug> <cp>")
        slug = common.check_name("slug", pos[0])
        cp = common.check_name("cp", pos[1])
        root = common.repo_root()
        cfg = common.load_config(root, required=False)
        row = common.pick_row(common.load_plan(root, slug), cp)
        state, _ = common.load_state(root, slug, row)
        ev = common.ev_dir(root, slug, cp)
        base = common.resolve_base(root, slug, row)
        files = common.diff_status(root, base) if base else []
        prod, _, net = cmd_size.prod_size(root, cfg, base) if base else (0, 0, 0)
        spec = common.read_json(os.path.join(ev, "0-spec.json"), default=None)
    except RsError as e:
        sys.stderr.write("ratchet: %s\n" % e)
        return 2

    paths = [p for _, p in files]
    test_files = [p for p in paths if common.is_test(cfg, p)]
    est = row["est"] or common.to_int(cfg["size"].get("prodLines"), None)

    calls = []
    for _, data in numbered(ev, r"^1-impl-r(\d+)\.json$"):
        for c in data.get("judgmentCalls") or []:
            if isinstance(c, str) and c not in calls:
                calls.append(c)

    issues = {}
    for _, data in numbered(ev, r"^3-triage-r(\d+)\.json$"):
        for f in data.get("findings") or []:
            if isinstance(f, dict) and f.get("id"):
                issues[str(f["id"])] = short(f.get("issue") or "", 120)
    advisory = state["open"]["advisory"]
    # The last b1 result: the checks that failed before the row and fail still. b1 passed over them.
    baseline_failing = [str(c) for c in state.get("baselineFailing") or []]

    manual = [c for c in cfg["checks"] if c["kind"] in ("device", "manual")
              and (not c["when"] or any(common.glob_match(g, p) for g in c["when"] for p in paths))]

    cases = len(spec["cases"]) if isinstance(spec, dict) and isinstance(spec.get("cases"), list) else None

    ratio = " (%.2f)" % (prod / float(est)) if est else ""
    size_line = "Prod size: %d lines against an estimate of %s%s" % (prod, est if est else "none", ratio)
    tests_line = "Tests: net %+d lines in %d test file(s)" % (net, len(test_files))
    if cases is not None:
        tests_line += ", %d cases" % cases
    rounds = state["rounds"]
    report_path = os.path.join(ev, "4-report.md")

    md = ["# Report: %s/%s, %s" % (slug, cp, row["checkpoint"]), "",
          "Stage %s, epoch %d. Rounds: b0 %d, b1 %d, b2 %d, b3 %d." % (
              state["stage"], state["epoch"], rounds["b0"], rounds["b1"], rounds["b2"], rounds["b3"]),
          "", "## Files changed (%d)" % len(files)]
    md += ["- %s %s%s" % (s, p, " (test)" if p in test_files else "") for s, p in files] or ["- none"]
    md += ["", "## Judgment calls (%d)" % len(calls)] + ["- " + c for c in calls]
    md += ["", "## Advisory findings (%d)" % len(advisory)]
    md += ["- %s%s" % (i, ": " + issues[i] if i in issues else "") for i in advisory]
    md += ["", "## Failed before the row started, and still fail (%d)" % len(baseline_failing)]
    md += ["- " + c for c in baseline_failing]
    md += ["", "## Checks for you"]
    md += ["- %s (%s): %s" % (c["id"], c["kind"], c.get("instruct") or c.get("run") or "") for c in manual] or ["- none"]
    md += ["", "## Tests", "- " + tests_line, "", "## Size", "- " + size_line]
    common.write_text(report_path, "\n".join(md) + "\n")

    shown = ", ".join(paths[:4]) + (" +%d more" % (len(paths) - 4) if len(paths) > 4 else "")
    out = ["%s/%s %s: stage %s" % (slug, cp, row["checkpoint"], state["stage"]),
           "Files: %d changed (%d tests): %s" % (len(files), len(test_files), shown or "none")]
    if calls:
        out.append("Judgment calls (%d): %s" % (len(calls), "; ".join(short(c, 60) for c in calls[:2])))
    # One line for both: the output keeps 10 lines, and a longer list would cut the report path.
    line = "Advisory findings: %d" % len(advisory)
    if baseline_failing:
        line += "; failed before the row: %s" % short(", ".join(baseline_failing), 60)
    out.append(line)
    for c in manual[:2]:
        out.append("Check yourself: %s: %s" % (c["id"], short(c.get("instruct") or c.get("run") or "", 80)))
    if len(manual) > 2:
        out.append("(%d more checks in the report)" % (len(manual) - 2))
    out += [tests_line, size_line, "Report: %s" % common.rel(root, report_path)]
    print("\n".join(out[:10]))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
