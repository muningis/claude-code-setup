"""Gates b3-prep and b3: prepare the review, then triage what the reviewers found."""
from __future__ import annotations

import os

import cmd_prove
import common
from common import RsError
from gatekit import Result, applicable_checks, merge_open, render_results, role_of, run_checks


def run_prep(ctx):
    root = ctx.root
    r = ctx.round
    base = ctx.base()
    os.makedirs(ctx.ev, exist_ok=True)

    patch = ctx.evp("3-diff-r%d.patch" % r)
    rc, out, err = common.rs_run(root, "diff", base)
    if rc != 0:
        raise RsError("diff failed: %s" % (err.strip() or out.strip())[:200])
    common.write_text(patch, out)

    # Read the previous review snapshot before this round replaces it.
    prev = common.ref_sha(root, ctx.slug, ctx.cp, "review")
    delta = None
    structural = True
    if r >= 2 and prev:
        rc, out, err = common.rs_run(root, "diff", prev)
        if rc != 0:
            raise RsError("diff failed: %s" % (err.strip() or out.strip())[:200])
        delta = ctx.evp("3-delta-r%d.patch" % r)
        common.write_text(delta, out)
        status = common.diff_status(root, prev)
        arch_paths = ctx.cfg["review"].get("archPaths") or []
        # An open architecture finding needs its reviewer again, whatever the delta holds.
        structural = (any(s in ("A", "D") for s, _ in status)
                      or any(common.any_glob(arch_paths, p) for _, p in status)
                      or any(role_of(f) == "A" for f in ctx.state["open"]["blocking"]))

    rc, out, err = common.rs_run(root, "tripwire", base)
    if rc != 0:
        raise RsError("tripwire failed: %s" % (err.strip() or out.strip())[:200])
    tripwire = ctx.evp("3-tripwire-r%d.txt" % r)
    common.write_text(tripwire, out)

    ev_paths = []
    for chk in run_checks(ctx, applicable_checks(ctx, "command", "evidence")):
        p = ctx.evp("3-check-%s-r%d.txt" % (cmd_prove.safe_name(chk["id"]), r))
        common.write_text(p, render_results([chk]))
        ev_paths.append(common.rel(root, p))

    common.snap(root, "%s/%s/review" % (ctx.slug, ctx.cp))

    prep = ctx.evp("3-prep-r%d.json" % r)
    patch_rel = common.rel(root, patch)
    delta_rel = common.rel(root, delta) if delta else None
    tripwire_rel = common.rel(root, tripwire)
    common.write_json(prep, {"round": r, "patch": patch_rel, "delta": delta_rel, "tripwire": tripwire_rel,
                             "checkOutputs": ev_paths, "structural": structural})
    lines = len(common.read_text(patch).splitlines())
    summary = "round %d: patch %d lines; %s" % (r, lines, "full review" if structural else "break review only")
    return Result("pass", summary, patch, {"patch": patch_rel, "delta": delta_rel, "tripwire": tripwire_rel,
                                           "checkOutputs": ev_paths, "structural": structural})


def review_path(ctx, role, rnd):
    for name in ("3-%s-r%d.json" % (role, rnd), "3-review-%s-r%d.json" % (role, rnd)):
        p = ctx.evp(name)
        if os.path.isfile(p):
            return p
    return None


def load_review(ctx, role, rnd):
    """(data, findings) of one reviewer file, or None when there is no file."""
    p = review_path(ctx, role, rnd)
    if p is None:
        return None
    data = common.read_json(p)
    if not isinstance(data, dict):
        raise RsError("%s must hold a JSON object" % common.rel(ctx.root, p))
    findings = data.get("findings")
    if findings is None:
        findings = []
    if not isinstance(findings, list):
        raise RsError("%s: findings must be a list" % common.rel(ctx.root, p))
    return data, [f for f in findings if isinstance(f, dict)]


def standards_text(ctx):
    """architecture.md and learnings.md: the docs.root path, the version 1 path, and config.architecture."""
    docs_root = ctx.cfg["docs"].get("root") or "docs"
    cands = []
    if isinstance(ctx.cfg.get("architecture"), str) and ctx.cfg["architecture"]:
        cands.append(ctx.cfg["architecture"])
    cands += [docs_root + "/architecture.md", ".claude/ratchet/architecture.md",
              docs_root + "/learnings.md", ".claude/ratchet/learnings.md"]
    parts = []
    seen = set()
    for c in cands:
        if c in seen:
            continue
        seen.add(c)
        p = os.path.join(ctx.root, c)
        if os.path.isfile(p):
            parts.append(common.read_text(p))
    return "\n".join(parts)


def earlier_record(ctx, fid):
    """The triage record of a finding from an earlier round, newest round first."""
    for k in range(ctx.round - 1, 0, -1):
        data = common.read_json(ctx.evp("3-triage-r%d.json" % k), default=None)
        if isinstance(data, dict) and isinstance(data.get("findings"), list):
            for f in data["findings"]:
                if isinstance(f, dict) and f.get("id") == fid:
                    return f
    return None


def reviewer_statuses(loaded):
    """{finding id: STATUS} from a reviewer's `addressed` list."""
    out = {}
    if loaded is not None and isinstance(loaded[0].get("addressed"), list):
        for e in loaded[0]["addressed"]:
            if isinstance(e, dict) and e.get("id") is not None:
                out[str(e["id"])] = str(e.get("status") or "").upper()
    return out


def run_triage(ctx):
    root = ctx.root
    cfg = ctx.cfg
    r = ctx.round
    prep = common.read_json(ctx.evp("3-prep-r%d.json" % r), default=None)
    if ctx.skip_arch:
        arch_expected = False
    else:
        arch_expected = not (isinstance(prep, dict) and prep.get("structural") is False)
    arch = load_review(ctx, "arch", r)
    brk = load_review(ctx, "break", r)
    if brk is None:
        raise RsError("missing 3-break-r%d.json" % r)
    if arch is None and arch_expected:
        raise RsError("missing 3-arch-r%d.json" % r)

    standards = standards_text(ctx)
    findings = []
    for role, loaded in (("arch", arch), ("break", brk)):
        if loaded is None:
            continue
        letter = "A" if role == "arch" else "B"
        for n, f in enumerate(loaded[1], 1):
            fid = str(f.get("id") or "%s-%s%d-%d" % (ctx.cp, letter, r, n))
            rec = {"id": fid, "role": role, "severity": f.get("severity") or "medium", "file": f.get("file"),
                   "line": f.get("line"), "target": f.get("target"), "issue": f.get("issue"), "fix": f.get("fix")}
            if role == "arch":
                rule = f.get("rule") if isinstance(f.get("rule"), str) and f.get("rule") else None
                rec["rule"] = rule
                rec["ruleExists"] = bool(rule) and common.has_id(standards, rule)
                rec["class"] = "blocking" if rec["ruleExists"] else "advisory"
            else:
                cmd, pattern = cmd_prove.proof_of(f)
                rec["proof"] = {"cmd": cmd, "pattern": pattern} if cmd else None
                rec["class"] = "advisory"
                if cmd:
                    pr = cmd_prove.run_proof(root, cfg, ctx.slug, ctx.cp, fid, cmd, pattern)
                    rec["proofResult"] = {"result": pr["result"], "exit": pr["exit"], "ms": pr["ms"],
                                          "out": common.rel(root, pr["out"])}
                    if pr["result"] == "reproduced":
                        rec["class"] = "blocking"
            findings.append(rec)

    previous = []
    if r >= 2:
        arch_status = reviewer_statuses(arch)
        break_status = reviewer_statuses(brk)
        for fid in ctx.state["open"]["blocking"]:
            if role_of(fid) not in ("A", "B"):
                continue  # visual findings belong to b2
            old = earlier_record(ctx, fid)
            entry = {"id": fid, "addressed": False, "via": "none"}
            if old and old.get("role") == "break" and isinstance(old.get("proof"), dict) and old["proof"].get("cmd"):
                pr = cmd_prove.run_proof(root, cfg, ctx.slug, ctx.cp, fid, old["proof"]["cmd"],
                                         old["proof"].get("pattern"))
                entry["via"] = "proof"
                entry["proofResult"] = pr["result"]
                # A timeout says nothing about the fix, so the finding stays open.
                entry["addressed"] = pr["result"] == "unproven" and not pr["timeout"]
            elif role_of(fid) == "A":
                entry["via"] = "reviewer"
                entry["addressed"] = arch_status.get(fid) == "ADDRESSED"
            else:
                entry["via"] = "reviewer"
                entry["addressed"] = break_status.get(fid) == "ADDRESSED"
            previous.append(entry)

    def unique(seq):
        out = []
        for x in seq:
            if x not in out:
                out.append(x)
        return out

    new_blocking = [f["id"] for f in findings if f["class"] == "blocking"]
    advisory = unique(f["id"] for f in findings if f["class"] == "advisory")
    unproven = unique(f["id"] for f in findings if f["role"] == "break" and f["class"] == "advisory")
    addressed = [p["id"] for p in previous if p["addressed"]]
    not_addressed = [p["id"] for p in previous if not p["addressed"]]
    blocking = unique(not_addressed + new_blocking)

    evidence = ctx.evp("3-triage-r%d.json" % r)
    common.write_json(evidence, {
        "round": r, "archRan": arch is not None, "findings": findings, "previous": previous,
        "blocking": blocking, "advisory": advisory, "unproven": unproven,
        "addressed": addressed, "notAddressed": not_addressed})

    extra = {"triage": common.rel(root, evidence), "blocking": blocking, "advisory": advisory,
             "unproven": unproven, "addressed": addressed, "notAddressed": not_addressed}
    if blocking:
        res = Result("fail", "%d blocking (%s); %d advisory" % (len(blocking), ", ".join(blocking), len(advisory)),
                     evidence, extra)
    else:
        common.snap(root, "%s/%s/gated" % (ctx.slug, ctx.cp))
        res = Result("pass", "no blocking findings; %d advisory, %d addressed" % (len(advisory), len(addressed)),
                     evidence, extra)
        res.advance = "B4"
    res.round_key = "b3"
    res.open = merge_open(ctx.state["open"], ("A", "B"), blocking, advisory)
    res.blocking = len(blocking)
    res.advisory = len(advisory)
    return res
