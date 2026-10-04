"""gate <gate> <slug> <cp> --nonce <n> [--round <r>] [--detach]: run one gate; update STATE, LIVE and METRICS."""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time

import cmd_row
import common
import gate_b0
import gate_b1
import gate_b2
import gate_b3
from common import RsError
from gatekit import Ctx, Result

HERE = os.path.dirname(os.path.abspath(__file__))

RUNNERS = {
    "b0-prep": gate_b0.run_prep,
    "b0": gate_b0.run,
    "b1": gate_b1.run_b1,
    "b2-capture": gate_b2.run_capture,
    "b2": gate_b2.run_judge,
    "smoke": gate_b1.run_smoke,
    "b3-prep": gate_b3.run_prep,
    "b3": gate_b3.run_triage,
}
# The key of STATE.rounds that the gate counts toward. smoke has none.
ROUND_KEY = {"b0-prep": None, "b0": "b0", "b1": "b1", "b2-capture": "b2", "b2": "b2", "smoke": None,
             "b3-prep": "b3", "b3": "b3"}
LIVE_GATE = {"b0-prep": "B0", "b0": "B0", "b1": "B1", "b2-capture": "B2", "b2": "B2", "smoke": "B1",
             "b3-prep": "B3", "b3": "B3"}
REVIEW = ["arch", "break"]
# gate: (the roles that work next after a pass, after a fail). None leaves LIVE.roles as it is.
NEXT_ROLES = {
    "b0-prep": (["spec"], ["spec"]),
    "b0": (["implement"], ["spec"]),
    "b1": (None, ["implement"]),
    "b2-capture": (None, ["visual"]),
    "b2": (REVIEW, ["implement"]),
    "b3-prep": (REVIEW, REVIEW),
    "b3": ([], ["implement"]),
}


def next_roles(ctx, ok):
    if ctx.gate == "smoke":
        return (["visual"] if ctx.has_visual() else REVIEW) if ok else ["implement"]
    return NEXT_ROLES[ctx.gate][0 if ok else 1]


def finish(ctx, res, started):
    ms = int((time.time() - started) * 1000)
    st = ctx.state
    if res.verdict in ("pass", "fail"):
        ok = res.verdict == "pass"
        if res.round_key:
            st["rounds"][res.round_key] = max(st["rounds"].get(res.round_key, 0), ctx.round)
        if ok and res.advance:
            common.advance_stage(st, res.advance)
        if res.open is not None:
            st["open"] = res.open
        st.update(res.state or {})
        if ok and res.row_status:
            cmd_row.update_plan(ctx.root, ctx.slug, ctx.cp, {"status": res.row_status})
        common.write_state(ctx.root, st)
        roles = next_roles(ctx, ok)
        if roles is not None:
            now = common.now_iso()
            live = {"roles": [{"role": r, "status": "working", "since": now} for r in roles]}
            if ctx.gate == "b3" and ok:
                live["gate"] = "B4"  # no engine gate follows: the human gate is next
            common.live_update(ctx.root, **live)
    common.metrics_append(ctx.root, {
        "ts": common.now_iso(), "slug": ctx.slug, "cp": ctx.cp, "gate": ctx.gate, "round": ctx.round,
        "verdict": res.verdict, "ms": ms, "blocking": res.blocking, "advisory": res.advisory,
        "prod": res.prod, "tests": res.tests})
    extra = dict(res.extra)
    extra["round"] = ctx.round
    extra["stage"] = st["stage"]
    return common.emit("gate " + ctx.gate, res.verdict, res.summary, evidence=res.evidence,
                       nonce=ctx.nonce, root=ctx.root, extra=extra,
                       harness_error=res.summary if res.verdict == "error" else None,
                       evidence_list=res.evidence_list)


def start_job(root, slug, cp, gate, rnd, nonce, argv):
    """Run the gate as a background job and print `pending` at once. The job outlives this command."""
    job = "%s-r%d-%s" % (gate, rnd, re.sub(r"[^A-Za-z0-9_-]", "_", nonce or "none"))
    jobs = common.jobs_dir(root, slug, cp)
    os.makedirs(jobs, exist_ok=True)
    out_path, err_path, pid_path = (os.path.join(jobs, job + ext) for ext in (".json", ".err", ".pid"))
    # A second start with the same job ID (a retried relay) must not run the gate twice on one evidence dir.
    if not common.pid_alive(common.to_int(common.read_text(pid_path).strip(), None)):
        cmd = [sys.executable, os.path.join(HERE, "main.py"), "gate"] + [a for a in argv if a != "--detach"]
        # No stream may stay open to the caller: its Bash call would wait until the gate ends.
        with open(out_path, "wb") as out, open(err_path, "wb") as err:
            proc = subprocess.Popen(cmd, cwd=root, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                                    start_new_session=True)
        common.write_text(pid_path, "%d\n" % proc.pid)
    return common.emit("gate " + gate, "pending", "started", nonce=nonce, root=root, extra={"job": job})


def main(argv):
    started = time.time()
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--round"),
                                      bool_flags=("--skip-arch", "--detach"))
    except RsError as e:
        return common.emit("gate", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")
    gate = pos[0].lower() if pos else ""
    cmd = ("gate " + gate).strip()

    def go():
        if len(pos) != 3 or gate not in RUNNERS:
            raise RsError("usage: gate <%s> <slug> <cp> --nonce <n> [--round <r>] [--detach]"
                          % "|".join(sorted(RUNNERS)))
        slug = common.check_name("slug", pos[1])
        common.check_name("cp", pos[2])
        root = common.repo_root()
        cfg = common.load_config(root)
        plan = common.load_plan(root, slug)
        row = common.pick_row(plan, pos[2])
        state, _ = common.load_state(root, slug, row)
        if "--round" in opts:
            rnd = common.to_int(opts["--round"], None)
            if rnd is None or rnd < 1:
                raise RsError("--round needs a whole number from 1")
        else:
            key = ROUND_KEY[gate]
            rnd = state["rounds"].get(key, 0) + 1 if key else 1
        if opts.get("--detach"):
            return start_job(root, slug, row["id"], gate, rnd, nonce, argv)
        ctx = Ctx(root, cfg, slug, plan, row, state, rnd, nonce, gate)
        ctx.skip_arch = bool(opts.get("--skip-arch"))
        common.live_update(root, slug=slug, cp=row["id"], gate=LIVE_GATE[gate], round=rnd)
        try:
            res = RUNNERS[gate](ctx)
        except RsError as e:
            res = Result("error", str(e))
        return finish(ctx, res, started)

    return common.run_guarded(cmd, nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
