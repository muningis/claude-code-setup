"""Gate b0, the spec gate: the new tests must fail for the right reasons and cover every requirement."""
from __future__ import annotations

import os

import cmd_red_check
import cmd_trace
import common
from common import RsError
from gatekit import Result, render_results, run_checks

TEXT_CAP = 1000000


def case_names(ctx, tests, texts):
    """Case names from 0-spec.json. Without them, the test lines that cite a requirement ID."""
    spec = common.read_json(ctx.evp("0-spec.json"), default=None)
    names = []
    if isinstance(spec, dict) and isinstance(spec.get("cases"), list):
        for c in spec["cases"]:
            if isinstance(c, dict) and c.get("name") and c.get("kind", "test") == "test":
                names.append(str(c["name"]))
    if names:
        return names
    for f in tests:
        for line in texts[f].splitlines():
            if common.REQ_ID_RE.search(line):
                names.append(line.strip()[:160])
    return names


def state_files(ctx):
    """The files that set how the gates judge. They are pinned in the plan's _state dir."""
    docs_root = ctx.cfg["docs"].get("root") or "docs"
    cands = [".claude/ratchet/config.json", ".claude/ratchet/learnings.md",
             docs_root + "/architecture.md", ".claude/ratchet/architecture.md"]
    if isinstance(ctx.cfg.get("architecture"), str) and ctx.cfg["architecture"]:
        cands.append(ctx.cfg["architecture"])
    out = []
    for c in cands:
        if c not in out and os.path.isfile(os.path.join(ctx.root, c)):
            out.append(c)
    return out


def run_prep(ctx):
    """Gate b0-prep: the base snapshot, the baseline run and the state pins, before the spec agent.

    Gate b0 finds the spec set as the files changed since base, so base must exist first."""
    root = ctx.root
    os.makedirs(ctx.ev, exist_ok=True)
    base = common.resolve_base(root, ctx.slug, ctx.row)
    created = not base
    # A resumed checkpoint keeps its base. A new snapshot would hide the work done since.
    if created:
        base = common.snap(root, "%s/%s/base" % (ctx.slug, ctx.cp))

    baseline_json = ctx.evp("0-baseline.json")
    if not os.path.isfile(baseline_json):
        # Every b1 check runs here, whatever its `when` globs: nothing has changed yet.
        runs = [c for c in ctx.cfg["checks"] if c["kind"] == "command" and "b1" in c["gate"]]
        all_cmd = (ctx.cfg["behavior"].get("all") or "").strip()
        if all_cmd:
            runs.append({"id": "behavior", "kind": "command", "run": all_cmd, "when": [], "gate": ["b1"]})
        results = run_checks(ctx, runs) if runs else []
        common.write_text(ctx.evp("0-baseline.txt"), render_results(results) or "no checks\n")
        common.write_json(baseline_json, {r["id"]: r["ok"] for r in results})
    baseline = common.read_json(baseline_json, default={}) or {}
    failing = sorted(k for k, ok in baseline.items() if ok is False)

    pinned = state_files(ctx)
    if pinned:
        listing = ctx.evp(".rs-state.txt")
        common.write_text(listing, "".join(p + "\n" for p in pinned))
        rc, out, err = common.rs_run(root, "lock", ".claude/ratchet/evidence/%s/_state" % ctx.slug, "--from", listing)
        os.remove(listing)
        if rc != 0:
            raise RsError("pinning the state files failed: %s" % (err.strip() or out.strip())[:200])

    common.write_json(common.live_path(root), {
        "active": True, "slug": ctx.slug, "cp": ctx.cp, "gate": "B0", "round": ctx.round,
        "roles": [], "updated": common.now_iso()})

    summary = "base %s%s; baseline %s" % (base[:7], " (new)" if created else "",
                                          "clean" if not failing else "already failing: " + ", ".join(failing))
    return Result("pass", summary, ctx.evp("0-baseline.txt"),
                  {"base": base, "baselineFailing": failing, "statePins": pinned})


def run(ctx):
    cfg = ctx.cfg
    row = ctx.row
    ctx.base()
    template = (cfg["behavior"].get("one") or "").strip()
    if not template:
        raise RsError("config: behavior.one is empty")
    timeout = common.to_int(cfg["behavior"].get("timeout"), 900)
    kinds = cmd_red_check.load_kinds(cfg)

    files = [p for s, p in ctx.changed() if s != "D"]
    tests = [p for p in files if common.is_test(cfg, p)]
    stubs = [p for p in files if p not in tests]
    os.makedirs(ctx.ev, exist_ok=True)

    texts = {}
    for f in tests:
        texts[f] = common.read_tail(os.path.join(ctx.root, f), TEXT_CAP)
    names = case_names(ctx, tests, texts)
    docs = cmd_trace.load_requirements(ctx.root, cfg, ctx.slug)
    trace = cmd_trace.check_row(docs, row, names, "\n".join(texts[f] for f in tests))
    need = [rid for rid in row["reqs"] if docs.get(rid, {}).get("kind", "test") == "test"]
    cases = len(names) or len(tests)
    per_cp = common.to_int(cfg["tests"].get("perCheckpoint"), 20)
    per_req = common.to_int(cfg["tests"].get("perRequirement"), 3)
    limit = min(per_cp, per_req * len(need)) if need else per_cp
    budget = {"cases": cases, "limit": limit, "over": cases > limit}

    # One run on every test file, as behavior.one expects. A fixture or helper in the list must not
    # fail the gate, and a touched old file may keep passing cases, so only the exit code says "pass".
    red = {"assert": 0, "stub": 0, "compile": 0, "runner": 0, "pass": 0}
    evidence = ctx.evp("0-red.txt")
    if not tests:
        common.write_text(evidence, "no test files changed since base\n")
    else:
        tmp = ctx.evp(".rs-red.out")
        rc, ms = common.run_command(common.fill_files(template, tests), ctx.root, timeout, tmp)
        text = common.strip_ansi(common.read_tail(tmp, 400000))
        os.remove(tmp)
        if rc == 0:
            red["pass"] = cases
        elif rc == 124:
            red["runner"] = 1
        else:
            red.update(cmd_red_check.classify(text, kinds)[1])
        common.write_text(evidence, "=== behavior.one on %d file(s): exit %d, %d ms ===\n%s\n"
                          % (len(tests), rc, ms, common.tail_text(text, 400)))

    problems = []
    if not tests:
        problems.append("no test files changed since base")
    if row["kind"] == "refactor":
        for k in ("assert", "stub", "compile", "runner"):
            if red[k]:
                problems.append("%d %s: a refactor spec must pass" % (red[k], k))
    else:
        for k in ("compile", "runner", "pass"):
            if red[k]:
                problems.append("%d %s" % (red[k], k))
    if trace["missing"]:
        problems.append("trace missing %s" % ", ".join(trace["missing"]))

    extra = {"cases": cases, "red": red, "trace": trace, "budget": budget, "tests": tests, "stubs": stubs}
    if problems:
        res = Result("fail", "spec rejected: %s" % "; ".join(problems), evidence, extra)
        res.round_key = "b0"
        return res

    listing = ctx.evp(".rs-pins.txt")
    common.write_text(listing, "".join(p + "\n" for p in tests))
    rc, out, err = common.rs_run(ctx.root, "lock", ctx.ev_rel(), "--from", listing)
    os.remove(listing)
    if rc != 0:
        raise RsError("pinning failed: %s" % (err.strip() or out.strip())[:200])
    common.snap(ctx.root, "%s/%s/red" % (ctx.slug, ctx.cp))

    shown = ", ".join("%d %s" % (red[k], k) for k in ("assert", "stub", "pass") if red[k])
    summary = "spec ok: %s; %d cases; %d files pinned" % (shown, cases, len(tests))
    if budget["over"]:
        summary += "; over budget (%d > %d)" % (cases, limit)
    res = Result("pass", summary, evidence, extra)
    res.round_key = "b0"
    res.advance = "B1"
    return res
