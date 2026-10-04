"""state <slug> [<cp>]: where a checkpoint stands. Reads only; never writes STATE."""
from __future__ import annotations

import sys

import common
from common import RsError


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("state", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if not pos or len(pos) > 2:
            raise RsError("usage: state <slug> [<cp>]")
        slug = pos[0]
        cp = pos[1] if len(pos) > 1 else None
        root = common.repo_root()
        plan = common.load_plan(root, slug)
        cfg = common.load_config(root, required=False)
        try:
            row = common.pick_row(plan, cp)
        except RsError as e:
            if cp is None:
                return common.emit("state", "error", str(e), nonce=nonce, root=root,
                                   extra={"slug": slug, "allDone": True}, harness_error=str(e))
            raise
        state, _ = common.load_state(root, slug, row)
        if row["status"] in ("approved", "approved-unverified", "superseded"):
            state["stage"] = "done"  # no gate writes B5 or done, so the row status says it
        refs = {"base": common.resolve_base(root, slug, row)}
        for name in ("red", "review", "gated"):
            refs[name] = common.ref_sha(root, slug, row["id"], name)
        intact, bad = common.pin_status(root, slug)
        extra = {
            "slug": slug, "cp": row["id"], "kind": row["kind"], "target": row["target"],
            "reqs": row["reqs"], "est": row["est"], "status": row["status"],
            "stage": state["stage"], "rounds": state["rounds"], "epoch": state["epoch"],
            "refs": refs, "pins": {"intact": intact, "changed": len(bad)},
            "open": state["open"],
            "visual": bool(cfg.get("visual")) and row["target"] != "-",
            "caps": cfg["caps"],
        }
        if bad:
            extra["pinsChanged"] = [p for _, p, _ in bad]
        summary = "%s %s: %s" % (row["id"], row["status"], state["stage"])
        return common.emit("state", "pass", summary, nonce=nonce, root=root, extra=extra)

    return common.run_guarded("state", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
