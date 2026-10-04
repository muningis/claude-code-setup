"""Gates b1 and smoke: run the behavior checks, then the smoke checks."""
from __future__ import annotations

import common
from common import RsError
from gatekit import Result, applicable_checks, render_results, run_checks, size_info

PINNED = "pinned"


def pinned_check(ctx):
    """behavior.one on the tests that this checkpoint pinned, or None when it pinned none."""
    files = [p for _, p in common.read_lock(ctx.root, ctx.ev_rel())]
    if not files:
        return None
    one = (ctx.cfg["behavior"].get("one") or "").strip()
    if not one:
        raise RsError("config: behavior.one is empty")
    return {"id": PINNED, "kind": "command", "run": common.fill_files(one, files), "when": [], "gate": ["b1"]}


def restore_pins(ctx, bad):
    for d in sorted(set(d for _, _, d in bad)):
        rc, out, err = common.rs_run(ctx.root, "restore", d)
        if rc != 0:
            raise RsError("restore failed in %s: %s" % (d, (err.strip() or out.strip())[:200]))


def write_brief(ctx, results, bad, size):
    """The brief for the next implementer round, in EV/1-brief-r<r+1>.md."""
    nxt = ctx.round + 1
    path = ctx.evp("1-brief-r%d.md" % nxt)
    # A decision from the human (RS decide --reopen) waits at the top of this brief. Keep it.
    head = common.read_text(path)
    lines = ([head.rstrip("\n"), ""] if head.strip() else []) + [
        "# Round %d brief: %s/%s" % (nxt, ctx.slug, ctx.cp), "",
        "Gate %s failed in round %d. Fix what follows. Do not edit pinned spec files." % (ctx.gate, ctx.round), ""]
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

    dirs = common.pin_dirs(ctx.root, ctx.slug)
    # The state files (config, architecture, learnings) change with the human's OK, so a change
    # is a question for the human, not something to undo. An agent can also weaken a gate there.
    state_bad = common.check_pins(ctx.root, [d for d in dirs if d == ctx.state_dir()])
    if state_bad:
        raise RsError("state files changed: %s; show the diff to the human, then re-lock or restore %s"
                      % (", ".join(p for _, p, _ in state_bad), ctx.state_dir()))
    bad = common.check_pins(ctx.root, [d for d in dirs if d != ctx.state_dir()])
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
    pinned = pinned_check(ctx)
    if pinned:
        runs.insert(0, pinned)
    if not runs:
        raise RsError("no checks to run: set behavior.all or a command check for b1")
    results = run_checks(ctx, runs)
    common.write_text(evidence, render_results(results))

    size, test_lines = size_info(ctx)
    # A check that failed before the checkpoint started is not this checkpoint's failure. The
    # comparison is per check, because test names are not comparable across runners. The pinned
    # tests are new, so the baseline never excuses them. It excuses behavior.all, which holds them too.
    baseline =common.read_json(ctx.evp("0-baseline.json"), default={}) or {}
    baseline_failing = [r["id"] for r in results
                        if not r["ok"] and r["id"] != PINNED and baseline.get(r["id"]) is False]
    failing = [r["id"] for r in results if not r["ok"] and r["id"] not in baseline_failing]
    shown = "prod %d/%s" % (size["prod"], size["est"] if size["est"] else "-")
    if baseline_failing:
        shown += "; failing before the checkpoint: %s" % ", ".join(baseline_failing)
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
        "failing": failing, "baselineFailing": baseline_failing, "pinsChanged": [], "size": size,
        "brief": common.rel(ctx.root, brief) if brief else None})
    res.round_key = "b1"
    res.advance = "B2" if ctx.has_visual() else "B3"
    res.state = {"baselineFailing": baseline_failing}  # the B4 report shows it
    res.prod = size["prod"]
    res.tests = test_lines
    return res


def run_smoke(ctx):
    evidence = ctx.evp("1-smoke-r%d.txt" % ctx.round)
    checks = applicable_checks(ctx, "smoke")
    if not checks:
        common.write_text(evidence, "no smoke checks\n")
        return Result("pass", "no smoke checks", evidence, {"checks": [], "failing": [], "brief": None})
    results = run_checks(ctx, checks)
    common.write_text(evidence, render_results(results))
    failing = [r["id"] for r in results if not r["ok"]]
    verdict = "fail" if failing else "pass"
    brief = None
    if failing:
        # A smoke failure counts as a failed B1 round, so it feeds the same next-round brief.
        brief = write_brief(ctx, results, [], None)
    summary = ("%d of %d smoke checks fail (%s)" % (len(failing), len(results), ", ".join(failing))
               if failing else "%d smoke checks pass" % len(results))
    return Result(verdict, summary, evidence, {
        "checks": [{"id": r["id"], "ok": r["ok"], "ms": r["ms"]} for r in results], "failing": failing,
        "brief": common.rel(ctx.root, brief) if brief else None})
