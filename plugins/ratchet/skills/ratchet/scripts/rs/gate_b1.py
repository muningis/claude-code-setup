"""Gates b1 and smoke: run the behavior checks, then the smoke checks."""
from __future__ import annotations

import common
from common import RsError
from gatekit import Result, applicable_checks, render_results, run_checks, size_info


def restore_pins(ctx, bad):
    for d in sorted(set(d for _, _, d in bad)):
        rc, out, err = common.rs_run(ctx.root, "restore", d)
        if rc != 0:
            raise RsError("restore failed in %s: %s" % (d, (err.strip() or out.strip())[:200]))


def write_brief(ctx, results, bad, size):
    """The brief for the next implementer round, in EV/1-brief-r<r+1>.md."""
    nxt = ctx.round + 1
    path = ctx.evp("1-brief-r%d.md" % nxt)
    lines = ["# Round %d brief: %s/%s" % (nxt, ctx.slug, ctx.cp), "",
             "Gate b1 failed in round %d. Fix what follows. Do not edit pinned spec files." % ctx.round, ""]
    if bad:
        lines += ["## Pinned files changed", "RS restored these files. Do not edit them again:"]
        lines += ["- %s (%s)" % (p, kind) for kind, p, _ in bad]
        lines.append("")
    for r in results:
        if r["ok"]:
            continue
        lines += ["## %s: exit %d" % (r["id"], r["rc"]), "Command: `%s`" % r["run"], "",
                  "```", common.tail_text(r["text"], 40), "```", ""]
    if size and size["ratio"] and size["ratio"] > 1:
        lines.append("Size: %d production lines against an estimate of %s." % (size["prod"], size["est"]))
    lines.append("Full output: %s" % common.rel(ctx.root, ctx.evp("1-behavior-r%d.txt" % ctx.round)))
    common.write_text(path, "\n".join(lines) + "\n")
    return path


def run_b1(ctx):
    cfg = ctx.cfg
    ctx.base()
    evidence = ctx.evp("1-behavior-r%d.txt" % ctx.round)

    bad = common.check_pins(ctx.root, common.pin_dirs(ctx.root, ctx.slug))
    if bad:
        restore_pins(ctx, bad)
        common.write_text(evidence, "pinned files changed and restored:\n"
                          + "".join("  %s (%s)\n" % (p, k) for k, p, _ in bad))
        brief = write_brief(ctx, [], bad, None)
        res = Result("fail", "%d pinned file(s) changed; restored" % len(bad), evidence,
                     {"checks": [], "failing": [], "pinsChanged": [p for _, p, _ in bad],
                      "brief": common.rel(ctx.root, brief)})
        res.round_key = "b1"
        return res

    runs = list(applicable_checks(ctx, "command", "b1"))
    all_cmd = (cfg["behavior"].get("all") or "").strip()
    if all_cmd:
        runs.append({"id": "behavior", "kind": "command", "run": all_cmd, "when": [], "gate": ["b1"]})
    if not runs:
        raise RsError("no checks to run: set behavior.all or a command check for b1")
    results = run_checks(ctx, runs)
    common.write_text(evidence, render_results(results))

    size, test_lines = size_info(ctx)
    failing = [r["id"] for r in results if not r["ok"]]
    shown = "prod %d/%s" % (size["prod"], size["est"] if size["est"] else "-")
    brief = None
    if failing:
        brief = write_brief(ctx, results, [], size)
        verdict = "fail"
        summary = "%d of %d checks fail (%s); %s" % (len(failing), len(results), ", ".join(failing), shown)
    else:
        verdict = "pass"
        summary = "%d checks pass; %s" % (len(results), shown)
    res = Result(verdict, summary, evidence, {
        "checks": [{"id": r["id"], "ok": r["ok"], "ms": r["ms"]} for r in results],
        "failing": failing, "pinsChanged": [], "size": size,
        "brief": common.rel(ctx.root, brief) if brief else None})
    res.round_key = "b1"
    res.advance = "B2" if ctx.has_visual() else "B3"
    res.prod = size["prod"]
    res.tests = test_lines
    return res


def run_smoke(ctx):
    evidence = ctx.evp("4-smoke.txt")
    checks = applicable_checks(ctx, "smoke")
    if not checks:
        common.write_text(evidence, "no smoke checks\n")
        return Result("pass", "no smoke checks", evidence, {"checks": [], "failing": []})
    results = run_checks(ctx, checks)
    common.write_text(evidence, render_results(results))
    failing = [r["id"] for r in results if not r["ok"]]
    verdict = "fail" if failing else "pass"
    summary = ("%d of %d smoke checks fail (%s)" % (len(failing), len(results), ", ".join(failing))
               if failing else "%d smoke checks pass" % len(results))
    return Result(verdict, summary, evidence, {
        "checks": [{"id": r["id"], "ok": r["ok"], "ms": r["ms"]} for r in results], "failing": failing})
