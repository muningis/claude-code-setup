"""gate <gate> <slug> <cp> --nonce <n> [--round <r>]: run one gate; update STATE, LIVE and METRICS."""
from __future__ import annotations

import sys
import time

import common
import gate_b0
import gate_b1
import gate_b2
import gate_b3
from common import RsError
from gatekit import Ctx, Result

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


def finish(ctx, res, started):
    ms = int((time.time() - started) * 1000)
    st = ctx.state
    if res.verdict in ("pass", "fail"):
        if res.round_key:
            st["rounds"][res.round_key] = max(st["rounds"].get(res.round_key, 0), ctx.round)
        if res.verdict == "pass" and res.advance:
            common.advance_stage(st, res.advance)
        if res.open is not None:
            st["open"] = res.open
        common.write_state(ctx.root, st)
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


def main(argv):
    started = time.time()
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--round"), bool_flags=("--skip-arch",))
    except RsError as e:
        return common.emit("gate", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")
    gate = pos[0].lower() if pos else ""
    cmd = ("gate " + gate).strip()

    def go():
        if len(pos) != 3 or gate not in RUNNERS:
            raise RsError("usage: gate <%s> <slug> <cp> --nonce <n> [--round <r>]" % "|".join(sorted(RUNNERS)))
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
