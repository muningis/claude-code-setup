"""dream harvest [--all]: collect the facts of past runs without a model, and remove secrets.

Writes .claude/ratchet/dreams/<bundle>/harvest.json. Only evidence newer than the last
dream counts as new, so a quiet night costs nothing."""
from __future__ import annotations

import os
import re
import sys
import time

import common
import dream_io
import dream_learn
from common import RsError
from dream_scrub import CAP, clean

MAX_DOCS = 60
MAX_LINES = 40
MAX_FINDINGS = 40
MAX_ROWS = 50
AMENDMENT_CAP = 300
ISSUE_CAP = 400
HUMAN = re.compile(r"^4-human[^/]*\.md$")
REVIEW = re.compile(r"^3-(?:review-)?(arch|break)-r(\d+)\.json$")
PLAIN_REVIEW = re.compile(r"^3-(arch|break)-r(\d+)\.json$")
TRIAGE = re.compile(r"^3-triage-r(\d+)\.json$")
ROUND = re.compile(r"^([123])-[A-Za-z0-9-]+-r(\d+)\.")
NOTE_ROW = re.compile(r"^-\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*·")
NOTE_TAG = re.compile(r"^-\s*(?:waive|blocked)\(([^)]*)\)")
ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")
# Plan notes mostly hold the design. These words mark the ones that hold a human choice or a problem.
SIGNAL = re.compile(r"\b(?:waive[sd]?|blocked|human|user|decision|decided|accepted|superseded|unverified"
                    r"|escalat\w*|overrid\w+|rejected|retire[sd]?|chose|picks?)\b", re.I)


def line_doc(root, slug, cp, path, cap=CAP):
    """A text file as numbered lines, so that the reflection can cite `path:line`."""
    lines = [{"n": n, "text": clean(line.strip(), cap)}
             for n, line in enumerate(common.read_text(path).splitlines(), 1) if line.strip()]
    doc = {"path": common.rel(root, path), "slug": slug, "cp": cp, "lines": lines[:MAX_LINES]}
    if len(lines) > MAX_LINES:
        doc["linesMore"] = len(lines) - MAX_LINES
    return doc


def scan_rows(root):
    """[{slug, cp, dir, names}] for each checkpoint folder under evidence/. Pins and proofs are skipped."""
    base = os.path.join(common.r_dir(root), "evidence")
    out = []
    if not os.path.isdir(base):
        return out
    for slug in sorted(os.listdir(base), key=dream_io.natkey):
        sdir = os.path.join(base, slug)
        if not os.path.isdir(sdir) or slug[0] in "._":
            continue
        for cp in sorted(os.listdir(sdir), key=dream_io.natkey):
            cdir = os.path.join(sdir, cp)
            if not os.path.isdir(cdir) or cp[0] in "._":
                continue
            names = sorted(n for n in os.listdir(cdir) if os.path.isfile(os.path.join(cdir, n)))
            out.append({"slug": slug, "cp": cp, "dir": cdir, "names": names})
    return out


def finding_record(f, role, triage):
    """One finding, cut down to what the reflection needs. The proof command stays out."""
    rule = f.get("rule")
    rec = {"id": str(f.get("id") or ""), "role": str(f.get("role") or role or ""),
           "severity": str(f.get("severity") or ""),
           "class": str(f.get("class") or "unknown") if triage else "unknown",
           "file": clean(f.get("file") or "", 100), "issue": clean(f.get("issue") or "", ISSUE_CAP),
           "fix": clean(f.get("fix") or "", 240), "rule": rule if isinstance(rule, str) and rule else None}
    if f.get("line") is not None:
        rec["line"] = f.get("line")
    if triage:
        pr = f.get("proofResult")
        rec["proof"] = pr.get("result") if isinstance(pr, dict) else None
    else:
        rec["proof"] = "given" if f.get("proof") else None
    return rec


def read_findings(path):
    """(data, findings) of a review or triage file of any schema version. Findings are [] when it is unreadable."""
    try:
        data = common.read_json(path, default=None)
    except RsError:
        return None, []
    items = data.get("findings") if isinstance(data, dict) else data
    return data, [f for f in items if isinstance(f, dict)] if isinstance(items, list) else []


def finding_docs(root, row):
    """[(mtime, doc, raw findings, is triage)] for one checkpoint. A triage file wins over the reviews of its round.

    A v2 name (3-break-r1.json) wins over the v1 name (3-review-break-r1.json), as gate_b3 reads them."""
    triage_rounds = {}
    review_files = {}
    for n in row["names"]:
        t = TRIAGE.match(n)
        if t:
            triage_rounds[int(t.group(1))] = n
        m = REVIEW.match(n)
        if m:
            key = (m.group(1), int(m.group(2)))
            if key not in review_files or PLAIN_REVIEW.match(n):
                review_files[key] = n
    todo = [(name, rnd, None, True) for rnd, name in sorted(triage_rounds.items())]
    for (role, rnd), name in sorted(review_files.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if rnd not in triage_rounds:
            todo.append((name, rnd, role, False))
    docs = []
    for name, rnd, role, triage in todo:
        path = os.path.join(row["dir"], name)
        data, raw = read_findings(path)
        doc = {"path": common.rel(root, path), "slug": row["slug"], "cp": row["cp"], "round": rnd,
               "kind": "triage" if triage else "review"}
        if role:
            doc["role"] = role
        if isinstance(data, dict) and data.get("verdict"):
            doc["verdict"] = str(data.get("verdict"))[:20]
        recs = [finding_record(f, role, triage) for f in raw]
        doc["findings"] = recs[:MAX_FINDINGS]
        if len(recs) > MAX_FINDINGS:
            doc["findingsMore"] = len(recs) - MAX_FINDINGS
        docs.append((os.path.getmtime(path), doc, raw, triage))
    return docs


def rounds_of(row, state):
    """The highest round of each gate, from the file names and from STATE when it exists."""
    rounds = {}
    for n in row["names"]:
        m = ROUND.match(n)
        if m:
            g = "b" + m.group(1)
            rounds[g] = max(rounds.get(g, 0), int(m.group(2)))
    if isinstance(state, dict) and isinstance(state.get("rounds"), dict):
        for g, v in state["rounds"].items():
            if g in ("b1", "b2", "b3") and common.to_int(v, 0) > rounds.get(g, 0):
                rounds[g] = common.to_int(v, 0)
    return rounds


def read_metrics(root, since):
    gates = {}
    rows = {}
    lines = 0
    for m in dream_io.read_jsonl(common.metrics_path(root)):
        ts = dream_io.epoch_of(m.get("ts"))
        if since is not None and ts is not None and ts <= since:
            continue
        lines += 1
        g = str(m.get("gate") or "?")
        gate = gates.setdefault(g, {"runs": 0, "fail": 0, "error": 0})
        gate["runs"] += 1
        if m.get("verdict") in ("fail", "error"):
            gate[m["verdict"]] += 1
        key = "%s/%s" % (m.get("slug"), m.get("cp"))
        row = rows.setdefault(key, {"runs": 0, "fail": 0, "ms": 0, "maxRound": {}})
        row["runs"] += 1
        row["fail"] += 1 if m.get("verdict") in ("fail", "error") else 0
        row["ms"] += common.to_int(m.get("ms"), 0)
        row["maxRound"][g] = max(row["maxRound"].get(g, 0), common.to_int(m.get("round"), 0))
    keep = sorted(rows)[:MAX_ROWS]
    out = {"lines": lines, "gates": gates, "rows": dict((k, rows[k]) for k in keep)}
    if len(rows) > len(keep):
        out["rowsMore"] = len(rows) - len(keep)
    return out


def plan_notes(text, row_ids):
    """[(line, row ids, text)] for the bullets under `## Notes` that mark a human choice or a problem."""
    out = []
    inside = False
    for n, line in enumerate(text.splitlines(), 1):
        if re.match(r"^##\s+Notes\s*$", line):
            inside = True
            continue
        if inside and re.match(r"^##\s", line):
            break
        if not inside or not line.lstrip().startswith("- "):
            continue
        body = line.strip()[2:]
        ids = []
        m = NOTE_ROW.match(line.strip())
        if m:
            ids = [m.group(1)]
        else:
            t = NOTE_TAG.match(line.strip())
            if t:
                ids = ID_TOKEN.findall(t.group(1))
        out.append((n, [i for i in ids if i in row_ids], body))
    return [x for x in out if SIGNAL.search(x[2])]


def read_plans(root, cfg, since, by_row):
    plans = []
    waivers = []
    warnings = []
    pdir = os.path.join(common.r_dir(root), "plans")
    names = sorted(os.listdir(pdir), key=dream_io.natkey) if os.path.isdir(pdir) else []
    caps = cfg.get("caps") or {}
    for name in names:
        # A .reference.md file holds the visual references, not a checkpoint table.
        if not name.endswith(".md") or name.endswith(".reference.md"):
            continue
        path = os.path.join(pdir, name)
        slug = name[:-3]
        text = common.read_text(path)
        try:
            plan = common.parse_plan_text(text)
        except RsError as e:
            warnings.append("plan %s: %s" % (name, e))
            continue
        row_ids = set(r["id"] for r in plan["rows"])
        signal = plan_notes(text, row_ids)
        waivers.extend(body for _, _, body in signal if body.startswith("waive("))
        notes = signal if since is None or os.path.getmtime(path) > since else []
        rows = []
        counts = {}
        for r in plan["rows"]:
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            info = by_row.get((slug, r["id"]), {})
            rec = {"id": r["id"], "checkpoint": clean(r["checkpoint"], 120), "kind": r["kind"],
                   "target": r["target"], "status": r["status"]}
            mine = [{"n": n, "text": clean(body)} for n, ids, body in notes if r["id"] in ids]
            if mine:
                rec["notes"] = mine[:10]
            if info.get("rounds"):
                rec["rounds"] = info["rounds"]
                over = [g for g in ("b1", "b2", "b3") if info["rounds"].get(g, 0) >= common.to_int(caps.get(g), 99)]
                if over:
                    rec["overCap"] = over
            if info.get("human"):
                rec["human"] = info["human"]
            rows.append(rec)
        plan_rec = {"path": common.rel(root, path), "slug": slug, "version": plan["version"],
                    "counts": counts, "rows": rows}
        general = [{"n": n, "text": clean(body)} for n, ids, body in notes if not ids]
        if general:
            plan_rec["notes"] = general[:30]
        plans.append(plan_rec)
    return plans, waivers, warnings


def tally(triage_docs, known_ids):
    """{rule: {blocking, advisory}}: findings that cite a rule, each counted once per row and finding ID."""
    seen = set()
    counts = {}
    for slug, cp, raw in triage_docs:
        for k, f in enumerate(raw):
            fid = str(f.get("id") or "#%d" % k)
            cited = set()
            if isinstance(f.get("rule"), str) and f["rule"].strip():
                cited.add(f["rule"].strip())
            text = "%s %s" % (f.get("issue") or "", f.get("fix") or "")
            cited.update(rid for rid in known_ids if common.has_id(text, rid))
            cls = "blocking" if f.get("class") == "blocking" else "advisory"
            for rid in cited:
                key = (rid, slug, cp, fid)
                if key in seen:
                    continue
                seen.add(key)
                counts.setdefault(rid, {"blocking": 0, "advisory": 0})[cls] += 1
    return counts


def read_learnings(root, cites, choice_texts):
    path = dream_io.learnings_path(root)
    text = common.read_text(path)
    _, entries, bullets = dream_learn.parse(text)
    out = []
    for e in entries:
        c = cites.get(e["id"], {"blocking": 0, "advisory": 0})
        waived = sum(1 for t in choice_texts if common.has_id(t, e["id"]))
        out.append({"id": e["id"], "scope": e["scope"], "rule": clean(e["rule"]), "check": clean(e["check"]),
                    "status": e["status"], "origin": clean(e["values"].get("origin", ""), 40),
                    "helpful": c["blocking"], "cited": c, "waived": waived,
                    "fileCounters": {"helpful": e["helpful"], "harmful": e["harmful"]}})
    v1 = [{"n": n, "text": clean(dream_learn.v1_rule(b))} for n, b in bullets][:100]
    return {"path": common.rel(root, path), "entries": out, "v1": v1}


def choose_bundle(root, date):
    """Today's newest bundle when no proposal came from it yet, else the next one (date-2, date-3...)."""
    top = None
    for bid in dream_io.bundle_ids(root):
        m = re.match(r"^%s(?:-(\d+))?$" % re.escape(date), bid)
        if m and (top is None or int(m.group(1) or 1) > top[0]):
            top = (int(m.group(1) or 1), bid)
    if top is None:
        return date
    if not os.path.isfile(os.path.join(dream_io.bundle_dir(root, top[1]), "proposal.json")):
        return top[1]
    return "%s-%d" % (date, top[0] + 1)


def keep_newest(items):
    """(kept docs, number cut) from [(mtime, doc)]: the newest MAX_DOCS, in path order."""
    items = sorted(items, key=lambda t: -t[0])
    kept = sorted((d for _, d in items[:MAX_DOCS]), key=lambda d: dream_io.natkey(d["path"]))
    return kept, max(0, len(items) - MAX_DOCS)


def collect(root, since):
    """Walk the evidence once.

    Returns four things: the docs newer than `since`, by kind; the facts of each row; the raw
    triage findings of every round; and the text of the human's decisions."""
    buckets = {"human": [], "decisions": [], "amendments": [], "reviews": []}
    by_row = {}
    triage_raw = []
    choice_texts = []
    for row in scan_rows(root):
        state = None
        if "state.json" in row["names"]:
            try:
                state = common.read_json(os.path.join(row["dir"], "state.json"), default=None)
            except RsError:
                state = None
        by_row[(row["slug"], row["cp"])] = {"rounds": rounds_of(row, state),
                                            "human": [n for n in row["names"] if HUMAN.match(n)]}
        for n in row["names"]:
            kind = "human" if HUMAN.match(n) else "decisions" if n == "decisions.md" \
                else "amendments" if n == "0-amendments.md" else None
            if kind is None:
                continue
            path = os.path.join(row["dir"], n)
            if kind == "decisions":
                choice_texts.extend(clean(ln) for ln in common.read_text(path).splitlines() if ln.strip())
            mtime = os.path.getmtime(path)
            if since is None or mtime > since:
                cap = AMENDMENT_CAP if kind == "amendments" else CAP
                buckets[kind].append((mtime, line_doc(root, row["slug"], row["cp"], path, cap)))
        for mtime, doc, raw, triage in finding_docs(root, row):
            if triage:
                triage_raw.append((row["slug"], row["cp"], raw))
            if since is None or mtime > since:
                buckets["reviews"].append((mtime, doc))
    return buckets, by_row, triage_raw, choice_texts


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",), bool_flags=("--all",))
    except RsError as e:
        return common.emit("dream harvest", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if pos:
            raise RsError("usage: dream harvest [--all]")
        root = common.repo_root()
        cfg = common.load_config(root, required=False)
        started = time.time()
        since = None if opts.get("--all") else dream_io.last_epoch(dream_io.read_last(root))

        buckets, by_row, triage_raw, choice_texts = collect(root, since)
        plans, waivers, warnings = read_plans(root, cfg, since, by_row)
        choice_texts.extend(waivers)
        _, entries, _ = dream_learn.parse(common.read_text(dream_io.learnings_path(root)))
        cites = tally(triage_raw, [e["id"] for e in entries])

        kept = {}
        more = {}
        for name, items in buckets.items():
            kept[name], cut = keep_newest(items)
            if cut:
                more[name] = cut
        counts = dict((k, len(v)) for k, v in kept.items())
        counts["findings"] = sum(len(d["findings"]) for d in kept["reviews"])
        # Only evidence files newer than the last dream make a night worth a model run. Plans, learnings,
        # the rejected list and the metrics are context: they cannot back a proposal by themselves.
        new = sum(counts[k] for k in kept)
        since_iso = dream_io.iso_of(since) if since is not None else None
        extra = {"bundle": None, "new": new, "counts": counts, "since": since_iso,
                 "pending": dream_io.pending_bundles(root)}
        if new == 0:
            return common.emit("dream harvest", "pass",
                               "nothing new%s" % (" since %s" % since_iso if since_iso else ""),
                               nonce=nonce, root=root, extra=extra)

        bid = choose_bundle(root, dream_io.utc_date())
        bdir = dream_io.bundle_dir(root, bid)
        stale = os.path.join(bdir, "candidates.json")
        if os.path.isfile(stale):
            os.remove(stale)
        rejected = [{"date": r.get("date"), "op": r.get("op"), "target": r.get("target"),
                     "rule": clean(r.get("rule") or ""), "reason": clean(r.get("reason") or "")}
                    for r in dream_io.read_jsonl(dream_io.rejected_path(root))][-50:]
        data = {
            "version": 1, "bundle": bid, "generated": dream_io.iso_of(started), "generatedEpoch": started,
            "since": since_iso, "all": bool(opts.get("--all")),
            "cite": "Cite evidence as <path>:<line> for a line, or <path>#<id> for a finding. "
                    "Use the path fields of this file.",
            "counts": counts, "new": new, "more": more,
            "human": kept["human"], "decisions": kept["decisions"], "amendments": kept["amendments"],
            "reviews": kept["reviews"], "plans": plans, "metrics": read_metrics(root, since),
            "learnings": read_learnings(root, cites, choice_texts), "ruleCitations": cites,
            "rejected": rejected, "warnings": warnings,
        }
        out = os.path.join(bdir, "harvest.json")
        common.write_json(out, data)
        extra["bundle"] = bid
        summary = "%d human, %d decisions, %d amendments, %d reviews (%d findings)%s" % (
            counts["human"], counts["decisions"], counts["amendments"], counts["reviews"], counts["findings"],
            " since %s" % since_iso if since_iso else "")
        return common.emit("dream harvest", "pass", summary, evidence=out, nonce=nonce, root=root, extra=extra)

    return common.run_guarded("dream harvest", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
