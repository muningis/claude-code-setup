"""dream apply <date> --accept <ids> --reject <ids> [--reason <text>]: write what the human decided.

Edits learnings.md one entry at a time. Then it pins the new learnings.md again in each plan, so
that the next b1 gate does not stop on "state files changed"."""
from __future__ import annotations

import json
import os
import re
import sys

import common
import dream_curate
import dream_io
import dream_learn
from common import RsError
from dream_scrub import clean

LEARNINGS = ".claude/ratchet/learnings.md"


def take_all(argv, flags):
    """(rest, {flag: [values]}): parse_args keeps one value for each flag, and the human may repeat them."""
    rest = []
    got = dict((f, []) for f in flags)
    i = 0
    while i < len(argv):
        a = argv[i]
        m = re.match(r"^(--[a-z-]+)=(.*)$", a, re.S)
        if a in got:
            if i + 1 >= len(argv):
                raise RsError("%s needs a value" % a)
            got[a].append(argv[i + 1])
            i += 2
        elif m and m.group(1) in got:
            got[m.group(1)].append(m.group(2))
            i += 1
        else:
            rest.append(a)
            i += 1
    return rest, got


def ids_of(values, known, label):
    """Item IDs from comma or space lists. `2` and `p2` both mean P2."""
    out = []
    for v in values:
        for t in re.split(r"[,\s]+", v):
            if not t:
                continue
            t = ("P" + t if t.isdigit() else t).upper()
            if t not in known:
                raise RsError("%s names an unknown item %s; the proposal has %s"
                              % (label, t, ", ".join(sorted(known, key=dream_io.natkey))))
            if t not in out:
                out.append(t)
    return out


def source_of(item, bid):
    refs = [dream_curate.one_line(r) for r in item.get("evidence") or [] if r]
    if not refs:
        return "dream %s" % bid
    return ", ".join(refs[:3]) + (" (+%d more)" % (len(refs) - 3) if len(refs) > 3 else "")


def apply_item(text, item, bid):
    """(new text, entry ID) after one accepted item. It checks the item again: the human may have edited it."""
    iid = item.get("id")
    op = str(item.get("op") or "").upper()
    if op not in dream_curate.OPS:
        raise RsError("%s: unknown op %r" % (iid, item.get("op")))
    targets = [] if op == "ADD" else dream_curate.split_targets(item.get("target"))
    if op in ("EDIT", "RETIRE") and len(targets) != 1 or op == "MERGE" and len(targets) < 2:
        raise RsError("%s: %s has the wrong number of targets" % (iid, op))
    _, entries, _ = dream_learn.parse(text)
    live = dict((e["id"], e) for e in entries)
    for t in targets:
        if t not in live or live[t]["status"] != "active":
            raise RsError("%s: %s is not an active entry of learnings.md" % (iid, t))
    scope_list = dream_curate.scope_of(item.get("scope"))
    rule = dream_curate.one_line(item.get("rule"))
    check = dream_curate.one_line(item.get("check"))
    problem = dream_curate.shape_problem(op, rule, check, scope_list)
    if problem:
        raise RsError("%s: %s" % (iid, problem))
    scope = ", ".join(scope_list) if scope_list else None
    if op == "ADD":
        eid = dream_learn.next_id(entries)
        source = source_of(item, bid)
        if re.search(r"status\s*:", source, re.I):
            raise RsError("%s: the evidence holds `status:`" % iid)
        if not text.strip():
            text = "# Learnings\n\n"
        return dream_learn.append(text, dream_learn.render(eid, scope, rule, check, source)), eid
    if op == "RETIRE":
        return dream_learn.retire(text, targets[0]), targets[0]
    text = dream_learn.edit(text, targets[0], scope, rule, check)
    for other in targets[1:]:
        text = dream_learn.retire(text, other, "merged into %s by dream %s" % (targets[0], bid))
    return text, targets[0]


def state_pins(root):
    """[(dir, intact)] for each plan pin that lists learnings.md. Intact: the file still matches the pin."""
    out = []
    base = os.path.join(common.r_dir(root), "evidence")
    if not os.path.isdir(base):
        return out
    now = None
    if os.path.isfile(os.path.join(root, LEARNINGS)):
        rc, h, _ = common.run(["git", "hash-object", "--", LEARNINGS], cwd=root)
        now = h.strip() if rc == 0 else None
    for slug in sorted(os.listdir(base)):
        d = ".claude/ratchet/evidence/%s/_state" % slug
        if not os.path.isfile(os.path.join(root, d, "spec.lock")):
            continue
        for sha, path in common.read_lock(root, d):
            if path == LEARNINGS:
                out.append((d, now is not None and sha == now))
                break
    return out


def decide(many, by_id):
    """(accept, reject) from the flags. Each item needs one answer, so a vague reply cannot half-apply."""
    accept = ids_of(many["--accept"], by_id, "--accept")
    reject = ids_of(many["--reject"], by_id, "--reject")
    both = [i for i in accept if i in reject]
    if both:
        raise RsError("%s is in --accept and in --reject" % ", ".join(both))
    undecided = [i for i in by_id if i not in accept and i not in reject]
    if undecided:
        raise RsError("no decision for %s: accept or reject each item" % ", ".join(undecided))
    return accept, reject


def relock(root, bdir, pins):
    """(pinned, stale, problem): pin learnings.md again where its pin was intact before the change.

    A pin that was stale holds a change that nobody reviewed, so it stays stale."""
    pinned = []
    stale = []
    listing = os.path.join(bdir, ".rs-lock.txt")
    try:
        for d, intact in pins:
            if not intact:
                stale.append(d)
                continue
            common.write_text(listing, LEARNINGS + "\n")
            rc, out, err = common.rs_run(root, "lock", d, "--from", listing)
            if rc != 0:
                return pinned, stale, "pinning learnings.md in %s failed: %s" % (d, (err.strip() or out.strip())[:160])
            pinned.append(d)
    except OSError as e:
        return pinned, stale, "pinning learnings.md failed: %s" % e
    finally:
        if os.path.exists(listing):
            os.remove(listing)
    return pinned, stale, None


def main(argv):
    try:
        rest, many = take_all(argv, ("--accept", "--reject"))
        pos, opts = common.parse_args(rest, value_flags=("--nonce", "--reason"))
    except RsError as e:
        return common.emit("dream apply", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 1:
            raise RsError("usage: dream apply <date> --accept <ids> --reject <ids> [--reason <text>]")
        root = common.repo_root()
        bid = dream_io.check_bundle(pos[0])
        bdir = dream_io.bundle_dir(root, bid)
        review = os.path.join(bdir, "review.json")
        if os.path.isfile(review):
            raise RsError("dream %s is reviewed already" % bid)
        proposal = common.read_json(os.path.join(bdir, "proposal.json"), default=None)
        if not isinstance(proposal, dict) or not isinstance(proposal.get("items"), list):
            raise RsError("no proposal.json in dream %s: run dream curate first" % bid)
        items = [it for it in proposal["items"] if isinstance(it, dict) and it.get("id")]
        by_id = dict((it["id"], it) for it in items)
        accept, reject = decide(many, by_id)

        path = dream_io.learnings_path(root)
        before = dream_io.read_exact(path)
        pins = state_pins(root)
        text = before
        done = []
        for it in items:
            if it["id"] in accept:
                text, eid = apply_item(text, it, bid)
                done.append({"id": it["id"], "op": str(it["op"]).upper(), "entry": eid})
        # Nothing is written before every item passed its checks, so a bad item changes nothing.
        if text != before:
            dream_io.write_exact(path, text)

        reason = clean(opts.get("--reason") or "") or "no reason given"
        lines = [json.dumps({"date": dream_io.utc_date(), "bundle": bid, "op": str(by_id[i].get("op") or "").upper(),
                             "target": by_id[i].get("target"), "rule": clean(by_id[i].get("rule") or ""),
                             "reason": reason}, ensure_ascii=False, separators=(",", ":")) + "\n" for i in reject]
        if lines:
            common.append_text(dream_io.rejected_path(root), "".join(lines))

        pinned, stale, problem = relock(root, bdir, pins) if text != before else ([], [], None)
        # The review file comes before any error: the learnings changed, so a second apply must not run.
        common.write_json(review, {
            "bundle": bid, "reviewed": common.now_iso(), "reason": reason if reject else None,
            "accepted": done, "rejected": reject, "relocked": pinned, "stalePins": stale})
        if problem:
            raise RsError("applied, but %s; run RS lock on it, with learnings.md in a list file" % problem)

        summary = "accepted %d, rejected %d" % (len(done), len(reject))
        if done:
            summary += " (%s)" % ", ".join("%s %s" % (d["op"], d["entry"]) for d in done)
        if stale:
            summary += "; %d stale pin left alone" % len(stale)
        # RS learnings reads entries only. Once one exists, bullets outside entries (version 1) stop reaching agents.
        _, entries, bullets = dream_learn.parse(text)
        warnings = []
        if entries and bullets:
            warnings.append("%d bullet(s) of learnings.md sit outside any entry, and RS learnings ignores them"
                            % len(bullets))
        return common.emit("dream apply", "pass", summary, evidence=review, nonce=nonce, root=root,
                           extra={"bundle": bid, "accepted": done, "rejected": reject, "relocked": len(pinned),
                                  "stalePins": stale, "warnings": warnings})

    return common.run_guarded("dream apply", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
