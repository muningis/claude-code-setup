"""Gates b2-capture and b2: take the images, then apply the visual judgment to its findings."""
from __future__ import annotations

import base64
import binascii
import filecmp
import json
import os
import shlex
import shutil
import subprocess
import time
import urllib.error
import urllib.request

import common
from common import RsError
from gatekit import Result, merge_open, regression_waivers

READY_SECONDS = 60


def fill(template, **values):
    out = template
    for key, val in values.items():
        out = out.replace("{%s}" % key, shlex.quote(str(val)) if val is not None else "")
    return out


def goldens_dir(root):
    return os.path.join(common.r_dir(root), "goldens")


def answers(url):
    """True when something serves the URL. A 404 still counts: the server is up."""
    try:
        urllib.request.urlopen(url, timeout=2).close()
        return True
    except urllib.error.HTTPError:
        return True
    except Exception:
        return False


def capture(ctx, template, target, viewport, out_path, url, log):
    vis = ctx.cfg["visual"]
    timeout = common.to_int(vis.get("timeout"), None) or common.to_int(ctx.cfg["behavior"].get("timeout"), 900)
    cmd = fill(template, target=target, viewport=viewport, out=out_path, url=url)
    tmp = ctx.evp(".rs-cap.out")
    rc, ms = common.run_command(cmd, ctx.root, timeout, tmp)
    tail = common.tail_text(common.read_tail(tmp, 20000), 15)
    log.append({"target": target, "viewport": viewport, "exit": rc, "ms": ms, "tail": tail})
    if os.path.exists(tmp):
        os.remove(tmp)
    if rc != 0:
        last = tail.strip().splitlines()[-1][:120] if tail.strip() else "no output"
        raise RsError("capture failed for %s at %s: exit %d (%s)" % (target, viewport, rc, last))
    if not os.path.isfile(out_path) or os.path.getsize(out_path) == 0:
        raise RsError("capture wrote no image for %s at %s" % (target, viewport))


def capture_ref(ctx, target, viewport, out_path, log):
    """Take the reference image. False when the reference kind is `none`."""
    vis = ctx.cfg["visual"]
    ref = vis.get("reference") or {}
    kind = ref.get("kind") or "none"
    if kind == "url":
        capture(ctx, vis["capture"], target, viewport, out_path, ref.get("url"), log)
        return True
    if kind == "command":
        if not ref.get("capture"):
            raise RsError("config: visual.reference.capture is empty")
        capture(ctx, ref["capture"], target, viewport, out_path, None, log)
        return True
    if kind == "dir":
        src = os.path.join(ctx.root, ref.get("path") or "", "%s@%s.png" % (target, viewport))
        if not os.path.isfile(src):
            raise RsError("no reference image: %s" % common.rel(ctx.root, src))
        shutil.copyfile(src, out_path)
        return True
    return False


def start_server(ctx, vis, log_path):
    """Browser mode: start `setup` and wait for `ready`. Returns the process, or None without a setup."""
    if vis.get("mode") != "browser" or not vis.get("setup"):
        return None
    url = vis.get("url")
    if url and answers(url):
        raise RsError("%s already answers: stop that server first, a stale one can serve old code" % url)
    logf = open(log_path, "wb")
    try:
        proc = subprocess.Popen(["/bin/sh", "-c", vis["setup"]], cwd=ctx.root, stdin=subprocess.DEVNULL,
                                stdout=logf, stderr=subprocess.STDOUT, start_new_session=True)
    finally:
        logf.close()
    ready = vis.get("ready") or url
    deadline = time.time() + READY_SECONDS
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RsError("setup exited with code %d before it was ready" % proc.returncode)
        if ready and str(ready).startswith("http"):
            if answers(ready):
                return proc
        elif ready:
            # Each command of the app gets a log. Its output must stay off stdout, which holds the gate result.
            rc, _ = common.run_command(str(ready), ctx.root, 10, ctx.evp("2-ready-r%d.log" % ctx.round))
            if rc == 0:
                return proc
        else:
            return proc
        time.sleep(0.5)
    common.kill_group(proc)
    raise RsError("the app was not ready after %d seconds" % READY_SECONDS)


def stop_server(ctx, vis, proc):
    if proc is not None:
        common.kill_group(proc)
    if vis.get("mode") == "browser" and vis.get("teardown"):
        common.run_command(vis["teardown"], ctx.root, 60, ctx.evp("2-teardown-r%d.log" % ctx.round))


def promote(ctx, target, viewports):
    """The impl images become the last approved captures that later checkpoints compare against."""
    os.makedirs(goldens_dir(ctx.root), exist_ok=True)
    for vp in viewports:
        src = ctx.evp("2-impl-%s-r%d.png" % (vp, ctx.round))
        if os.path.isfile(src):
            shutil.copyfile(src, os.path.join(goldens_dir(ctx.root), "%s@%s.png" % (target, vp)))


def not_applicable(ctx, name, extra):
    evidence = ctx.evp(name)
    common.write_json(evidence, {"round": ctx.round, "note": "n/a"})
    res = Result("pass", "n/a: no visual gate for this checkpoint", evidence, extra)
    res.advance = "B3"
    return res


def run_capture(ctx):
    if not ctx.has_visual():
        return not_applicable(ctx, "2-capture-r%d.json" % ctx.round,
                              {"images": [], "identical": True, "regressChanged": []})
    vis = ctx.cfg["visual"]
    viewports = vis.get("viewports") or []
    if not viewports:
        raise RsError("config: visual.viewports is empty")
    if not vis.get("capture"):
        raise RsError("config: visual.capture is empty")
    os.makedirs(ctx.ev, exist_ok=True)
    target = ctx.row["target"]
    other_targets = []
    for row in ctx.plan["rows"]:
        t = row["target"]
        if row["status"] in ("approved", "approved-unverified") and t != "-" and t != target \
                and t not in other_targets:
            other_targets.append(t)

    log = []
    images = []
    identical = True
    regress = []
    proc = start_server(ctx, vis, ctx.evp("2-setup-r%d.log" % ctx.round))
    try:
        for vp in viewports:
            impl = ctx.evp("2-impl-%s-r%d.png" % (vp, ctx.round))
            ref = ctx.evp("2-ref-%s-r%d.png" % (vp, ctx.round))
            capture(ctx, vis["capture"], target, vp, impl, vis.get("url"), log)
            have_ref = capture_ref(ctx, target, vp, ref, log)
            identical = identical and have_ref and filecmp.cmp(impl, ref, shallow=False)
            images.append({"impl": common.rel(ctx.root, impl),
                           "ref": common.rel(ctx.root, ref) if have_ref else None, "viewport": vp})
        for other in other_targets:
            for vp in viewports:
                golden = os.path.join(goldens_dir(ctx.root), "%s@%s.png" % (other, vp))
                if not os.path.isfile(golden):
                    continue
                new = ctx.evp("2-regress-%s-%s-r%d.png" % (other, vp, ctx.round))
                capture(ctx, vis["capture"], other, vp, new, vis.get("url"), log)
                regress.append({"target": other, "viewport": vp, "changed": not filecmp.cmp(new, golden, shallow=False),
                                "new": common.rel(ctx.root, new), "golden": common.rel(ctx.root, golden)})
    finally:
        stop_server(ctx, vis, proc)

    changed_targets = []
    for r in regress:
        if r["changed"] and r["target"] not in changed_targets:
            changed_targets.append(r["target"])
    evidence = ctx.evp("2-capture-r%d.json" % ctx.round)
    common.write_json(evidence, {"round": ctx.round, "images": images, "identical": identical,
                                 "regressChanged": changed_targets, "regress": regress, "log": log})
    extra = {"images": images, "identical": identical, "regressChanged": changed_targets}
    if identical and not changed_targets:
        promote(ctx, target, viewports)
        res = Result("pass", "images identical; no regression", evidence, extra)
        res.round_key = "b2"
        res.advance = "B3"
        return res
    # Not a pass: the engine now runs the visual agent on these images.
    why = "images differ" if not identical else "earlier targets changed"
    return Result("fail", "%s: visual judgment needed" % why, evidence, extra)


def run_judge(ctx):
    if not ctx.has_visual():
        return not_applicable(ctx, "2-triage-r%d.json" % ctx.round,
                              {"blocking": [], "advisory": [], "engine": 0})
    src = ctx.evp("2-visual-r%d.json" % ctx.round)
    if not os.path.isfile(src) and ctx.verdict_b64:
        # The visual agent sometimes returns its verdict without writing the file; the engine hands it over here.
        try:
            text = base64.b64decode(ctx.verdict_b64, validate=True).decode("utf-8")
            data = json.loads(text)
        except (binascii.Error, ValueError) as e:
            raise RsError("--verdict-b64 is not base64 of JSON: %s" % e)
        if not isinstance(data, dict):
            raise RsError("--verdict-b64 must hold a JSON object")
        common.write_text(src, text)
    if not os.path.isfile(src):
        raise RsError("missing 2-visual-r%d.json" % ctx.round)
    data = common.read_json(src)
    if not isinstance(data, dict):
        raise RsError("2-visual-r%d.json must hold a JSON object" % ctx.round)
    if str(data.get("verdict", "")).upper() == "INVALID":
        # The engine matches this prefix to capture again instead of ending the run.
        raise RsError("invalid capture: the visual agent judged the image pair INVALID")
    tol = ctx.cfg["visual"]["tolerance"]
    blocking = []
    advisory = []
    engine = []
    detail = []
    diffs = data.get("differences") if isinstance(data.get("differences"), list) else []
    for n, d in enumerate(diffs, 1):
        if not isinstance(d, dict):
            continue
        fid = str(d.get("id") or "%s-V%d-%d" % (ctx.cp, ctx.round, n))
        kind = str(d.get("kind") or "other")
        if d.get("engine") is True:
            cls = "engine"
            engine.append(fid)
        elif d.get("deferred") is True or d.get("waived") is True:
            # Outside the row's scope, or covered by a human waiver: shown at B4, never blocking.
            cls = "advisory"
            advisory.append(fid)
        elif kind in ("missing", "extra", "text"):
            cls = "blocking"
            blocking.append(fid)
        else:
            delta = d.get("delta") if isinstance(d.get("delta"), dict) else {}
            px = delta.get("px")
            color = delta.get("color")
            over = (isinstance(px, (int, float)) and px > common.to_int(tol.get("px"), 4)) \
                or (isinstance(color, (int, float)) and color > common.to_int(tol.get("color"), 8))
            cls = "blocking" if over else "advisory"
            (blocking if over else advisory).append(fid)
        detail.append({"id": fid, "kind": kind, "class": cls, "element": d.get("element"),
                       "severity": d.get("severity"), "location": d.get("location")})

    # An earlier target whose capture changed is a regression, whatever the visual agent saw.
    cap = common.read_json(ctx.evp("2-capture-r%d.json" % ctx.round), default=None)
    regressed = cap.get("regressChanged") if isinstance(cap, dict) else None
    waived = regression_waivers(ctx.root, ctx.slug, ctx.cp)
    for n, target in enumerate(regressed if isinstance(regressed, list) else [], 1):
        fid = "%s-V%d-%d" % (ctx.cp, ctx.round, 100 + n)
        cls = "advisory" if str(target) in waived else "blocking"
        (advisory if cls == "advisory" else blocking).append(fid)
        detail.append({"id": fid, "kind": "regression", "class": cls, "element": str(target),
                       "severity": "high", "location": "an earlier target"})
    evidence = ctx.evp("2-triage-r%d.json" % ctx.round)
    common.write_json(evidence, {"round": ctx.round, "tolerance": tol, "differences": detail,
                                 "blocking": blocking, "advisory": advisory, "engine": engine})
    verdict = "fail" if blocking else "pass"
    if blocking:
        summary = "%d blocking visual difference(s): %s" % (len(blocking), ", ".join(blocking))
    else:
        summary = "no blocking differences; %d advisory, %d engine" % (len(advisory), len(engine))
    res = Result(verdict, summary, evidence, {"blocking": blocking, "advisory": advisory, "renderer": len(engine)})
    # Engine-only differences never count toward the round cap.
    res.round_key = None if (engine and not blocking and not advisory) else "b2"
    res.open = merge_open(ctx.state["open"], ("V",), blocking, advisory)
    res.blocking = len(blocking)
    res.advisory = len(advisory)
    if verdict == "pass":
        res.advance = "B3"
        promote(ctx, ctx.row["target"], ctx.cfg["visual"].get("viewports") or [])
    return res
