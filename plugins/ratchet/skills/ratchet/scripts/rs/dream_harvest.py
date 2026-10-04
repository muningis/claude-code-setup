"""dream harvest [--since <Nd|ISO>] [--all] [--dry [--out <file>]]: collect the facts of the window without a model.

One global harvest. It reads every Claude Code session under ~/.claude/projects, and the ratchet
evidence of each repo that those sessions worked in. It removes secrets, and it writes
~/.claude/ratchet/dreams/<bundle>/harvest.json with a context/ folder that the reflection may read.
Only records newer than the last dream count as new, so a quiet night costs nothing."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time

import common
import dream_io
import dream_learn
import dream_sessions
from common import RsError
from dream_scrub import CAP, clean, scrub

SIZE_CAP = 150000
MAX_DOCS_REPO = 15
# The keys that build() adds after the cut need room, so the file as a whole stays under SIZE_CAP.
HEADROOM = 2000
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
    doc = {"path": common.rel(root, path), "slug": slug, "cp": cp, "updated": dream_io.iso_of(os.path.getmtime(path)),
           "lines": lines[:MAX_LINES]}
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
               "kind": "triage" if triage else "review", "updated": dream_io.iso_of(os.path.getmtime(path))}
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


def choose_bundle(date):
    """Today's newest bundle when no proposal came from it yet, else the next one (date-2, date-3...)."""
    top = None
    for bid in dream_io.bundle_ids():
        m = re.match(r"^%s(?:-(\d+))?$" % re.escape(date), bid)
        if m and (top is None or int(m.group(1) or 1) > top[0]):
            top = (int(m.group(1) or 1), bid)
    if top is None:
        return date
    if not os.path.isfile(os.path.join(dream_io.bundle_dir(top[1]), "proposal.json")):
        return top[1]
    return "%s-%d" % (date, top[0] + 1)


def keep_newest(items, limit=MAX_DOCS):
    """(kept docs, number cut) from [(mtime, doc)]: the newest `limit`, in path order."""
    items = sorted(items, key=lambda t: -t[0])
    kept = sorted((d for _, d in items[:limit]), key=lambda d: dream_io.natkey(d["path"]))
    return kept, max(0, len(items) - limit)


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




# ---------------------------------------------------------------- the repos behind the sessions

def repo_of(cwd):
    """The repo root that a working folder belongs to, or None. A ratchet or worktree folder maps to its repo."""
    p = str(cwd or "").rstrip("/")
    if not p.startswith("/"):
        return None
    for marker in ("/.claude/ratchet", "/.claude/worktrees"):
        i = p.find(marker)
        if i > 0 and (len(p) == i + len(marker) or p[i + len(marker)] == "/"):
            return p[:i]
    cur = p
    for _ in range(60):
        if os.path.exists(os.path.join(cur, ".git")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent
    return None


def repos_of(cwds):
    """The repos with ratchet state behind the working folders of the window, sorted. Home is never a repo."""
    home = os.path.realpath(dream_io.home_dir())
    found = {}
    for cwd in cwds:
        repo = repo_of(cwd)
        if not repo or not os.path.isdir(os.path.join(repo, ".claude", "ratchet")):
            continue
        real = os.path.realpath(repo)
        if real != home:
            found.setdefault(real, repo)
    return sorted(found.values())


def recount(section):
    counts = dict((k, len(section[k])) for k in ("human", "decisions", "amendments", "reviews"))
    counts["findings"] = sum(len(d["findings"]) for d in section["reviews"])
    section["counts"] = counts


def repo_section(repo, since):
    """(section, new) for one repo: the 2.0 evidence harvest, cut to the evidence newer than `since`."""
    cfg = common.load_config(repo, required=False)
    buckets, by_row, triage_raw, choice_texts = collect(repo, since)
    plans, waivers, warnings = read_plans(repo, cfg, since, by_row)
    choice_texts.extend(waivers)
    _, entries, _ = dream_learn.parse(common.read_text(dream_io.learnings_path(repo)))
    cites = tally(triage_raw, [e["id"] for e in entries])
    section = {"more": {}}
    for name, items in buckets.items():
        section[name], cut = keep_newest(items, MAX_DOCS_REPO)
        if cut:
            section["more"][name] = cut
    recount(section)
    # Plans, learnings, and metrics are context: they cannot back a proposal without a new evidence file.
    new = sum(section["counts"][k] for k in ("human", "decisions", "amendments", "reviews"))
    section.update({"plans": plans, "metrics": read_metrics(repo, since),
                    "learnings": read_learnings(repo, cites, choice_texts), "ruleCitations": cites,
                    "warnings": warnings})
    return section, new


# ---------------------------------------------------------------- the size cap

def encoded(obj):
    return json.dumps(obj, ensure_ascii=False, indent=1)


def size_of(obj):
    return len(encoded(obj).encode("utf-8"))


def shrink(payload, cap=SIZE_CAP):
    """Cut the harvest to `cap` bytes. Returns ({category: items dropped}, final size).

    Human turns are the main signal, and they are small. Bulky ratchet files go first. The order, lowest
    value first, oldest first inside a tier:
      1 ratchet amendments, 2 ratchet reviews and decisions, 3 the examples of a friction group beyond its
      first, 4 turns with no tag, 5 the first example of each friction group, 6 turns tagged only chore,
      7 friction groups seen once, 8 ratchet human gate replies, 9 the rest of the turns."""
    dropped = {"turns": 0, "ratchet": 0, "friction": 0}
    size = size_of(payload)
    if size <= cap:
        return dropped, size
    turns, groups = payload["turns"], payload["friction"]
    sections = list(payload["ratchet"].values())

    def by_turns(pred):
        return [("turns", t, turns) for t in sorted(turns, key=lambda t: t["ts"]) if pred(t)]

    def by_docs(kinds):
        found = [("ratchet", d, sec[k]) for sec in sections for k in kinds for d in sec[k]]
        return sorted(found, key=lambda x: x[1].get("updated") or "")

    tiers = [
        lambda: by_docs(("amendments",)),
        lambda: by_docs(("reviews", "decisions")),
        lambda: [("friction", e, g["examples"]) for g in groups for e in g["examples"][1:]],
        lambda: by_turns(lambda t: not t["tags"]),
        lambda: [("friction", e, g["examples"]) for g in groups for e in g["examples"]],
        lambda: by_turns(lambda t: t["tags"] == ["chore"]),
        lambda: [("friction", g, groups) for g in sorted(groups, key=lambda g: g["count"]) if g["count"] == 1],
        lambda: by_docs(("human",)),
        lambda: by_turns(lambda t: True),
    ]
    for make in tiers:
        for cat, item, owner in make():
            if size <= cap:
                size = size_of(payload)
                if size <= cap:
                    break
            owner.remove(item)
            dropped[cat] += 1
            size -= len(encoded(item).encode("utf-8")) + 6
        if size <= cap and size_of(payload) <= cap:
            break
    for sec in sections:
        recount(sec)
    return dropped, size_of(payload)


# ---------------------------------------------------------------- the harvest

def window(opts, cfg, now):
    """The lower bound of the window as epoch seconds, or None for no bound.

    An explicit --since wins. Then --all. Then the end of the last dream. Then sinceDays."""
    if opts.get("--since"):
        return dream_io.parse_since(opts["--since"], now)
    if opts.get("--all"):
        return None
    last = dream_io.last_epoch(dream_io.read_last())
    return last if last is not None else now - cfg["sinceDays"] * 86400


def build(since, started, cfg, all_flag):
    """The harvest of the window as a dict, and the number of new facts in it. It writes nothing."""
    sess = dream_sessions.scan_sessions(since, started, cfg["exclude"])
    ratchet = {}
    ratchet_new = 0
    warnings = []
    for repo in repos_of(sess["cwds"]):
        try:
            section, new = repo_section(repo, since)
        except (RsError, OSError, ValueError) as e:
            warnings.append("ratchet %s: %s" % (repo, e))
            continue
        if new:
            ratchet[repo] = section
            ratchet_new += new
    turns = [dict((k, v) for k, v in t.items() if not k.startswith("_")) for t in sess["turns"]]
    since_iso = dream_io.iso_of(since) if since is not None else None
    payload = {
        "version": 2, "generated": dream_io.iso_of(started), "generatedEpoch": started, "since": since_iso,
        "all": all_flag,
        "cite": "Cite a human turn by its id (<session>#<line>) and agent friction by its id (F<n>). "
                "Cite ratchet evidence as <path>:<line> or <path>#<finding id>, and name its repo in `repo`.",
        "projects": sess["projects"], "turns": turns, "friction": sess["friction"], "ratchet": ratchet,
        "warnings": warnings}
    new = sess["totalTurns"] + sess["frictionEvents"] + ratchet_new
    dropped, _ = shrink(payload, SIZE_CAP - HEADROOM)
    tags = {}
    for t in payload["turns"]:
        for tag in t["tags"]:
            tags[tag] = tags.get(tag, 0) + 1
    payload["counts"] = {
        "turns": len(payload["turns"]), "sessions": sess["stats"].get("sessions", 0),
        "frictionGroups": len(payload["friction"]), "frictionEvents": sess["frictionEvents"],
        "ratchetRepos": len(ratchet), "ratchetNew": ratchet_new}
    payload["new"] = new
    payload["tags"] = dict((k, tags.get(k, 0)) for k in ("interrupt", "declined", "rule", "correction", "chore"))
    payload["dropped"] = {"perSession": sess["dropped"]["perSession"], "size": sum(dropped.values()),
                          "sizeBy": dropped, "frictionGroups": sess["dropped"]["frictionGroups"]}
    payload["skipped"] = {"unclassifiedErrors": sess["stats"].get("unclassified", 0),
                          "sdkFiles": sess["stats"].get("sdkFiles", 0), "unreadableFiles": sess["stats"].get("unreadable", 0),
                          "badRecords": sess["stats"].get("badRecords", 0)}
    return payload, size_of(payload)


# ---------------------------------------------------------------- what the reflection may read

def write_context(bdir, payload):
    """Copy what the sealed reflection may read into <bundle>/context/. It reads only inside the bundle."""
    cdir = os.path.join(bdir, "context")
    if os.path.isdir(cdir):
        shutil.rmtree(cdir)
    os.makedirs(cdir)
    # The files are the human's own, but they go to a model, so the copies are scrubbed like the harvest.
    parts = ["## %s (%s)\n\n%s" % (gid, os.path.basename(path), scrub(dream_io.read_exact(path).strip(), 30000))
             for gid, path, _ in dream_learn.rule_files()]
    common.write_text(os.path.join(cdir, "global-rules.md"),
                      "# Active global rules\n\n%s\n" % ("\n\n".join(parts) if parts else "(none)"))
    for project in payload["projects"]:
        text = common.read_text(os.path.join(dream_io.projects_dir(), project, "memory", "MEMORY.md"))
        if text.strip():
            common.write_text(os.path.join(cdir, "memory-%s.md" % project), scrub(text[:20000], 20000))
    mapping = {}
    for n, repo in enumerate(sorted(payload["ratchet"]), 1):
        mapping[str(n)] = repo
        text = common.read_text(dream_io.learnings_path(repo))
        if text.strip():
            common.write_text(os.path.join(cdir, "ratchet-%d-learnings.md" % n), scrub(text[:30000], 30000))
    common.write_json(os.path.join(cdir, "ratchet-map.json"), mapping)
    rejected = [{"date": r.get("date"), "op": r.get("op"), "target": r.get("target"), "entry": r.get("entry"),
                 "rule": clean(r.get("rule") or ""), "reason": clean(r.get("reason") or "")}
                for r in dream_io.read_jsonl(dream_io.rejected_path())][-50:]
    common.write_text(os.path.join(cdir, "rejected.jsonl"),
                      "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rejected))


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--since", "--out"), bool_flags=("--all", "--dry"))
    except RsError as e:
        return common.emit("dream harvest", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        usage = "usage: dream harvest [--since <Nd|ISO>] [--all] [--dry [--out <file>]]"
        if pos:
            raise RsError(usage)
        if opts.get("--out") and not opts.get("--dry"):
            raise RsError("--out needs --dry. " + usage)
        home = dream_io.home_dir()
        cfg = dream_io.load_config()
        started = time.time()
        since = window(opts, cfg, started)
        payload, size = build(since, started, cfg, bool(opts.get("--all")))
        extra = {"bundle": None, "new": payload["new"], "counts": payload["counts"], "tags": payload["tags"],
                 "since": payload["since"], "size": size,
                 "dropped": {"perSession": payload["dropped"]["perSession"], "size": payload["dropped"]["size"]},
                 "ms": int((time.time() - started) * 1000)}
        c = payload["counts"]
        summary = "%d turns, %d friction groups, %d ratchet repos, %d KB%s" % (
            c["turns"], c["frictionGroups"], c["ratchetRepos"], (size + 512) // 1024,
            " since %s" % payload["since"] if payload["since"] else "")
        if opts.get("--dry"):
            # A dry run leaves no bundle and no marker. It may write the harvest where the caller says.
            if opts.get("--out"):
                common.write_text(opts["--out"], encoded(dict(payload, bundle=None)) + "\n")
                extra["out"] = os.path.abspath(opts["--out"])
            extra["dry"] = True
            return common.emit("dream harvest", "pass", "dry run: " + summary, nonce=nonce, root=home, extra=extra)
        extra["pending"] = dream_io.pending_bundles()
        if payload["new"] == 0:
            return common.emit("dream harvest", "pass",
                               "nothing new%s" % (" since %s" % payload["since"] if payload["since"] else ""),
                               nonce=nonce, root=home, extra=extra)
        bid = choose_bundle(dream_io.utc_date())
        bdir = dream_io.bundle_dir(bid)
        for stale in ("candidates.json", "reflect.log"):
            if os.path.isfile(os.path.join(bdir, stale)):
                os.remove(os.path.join(bdir, stale))
        payload["bundle"] = bid
        out = os.path.join(bdir, "harvest.json")
        common.write_text(out, encoded(payload) + "\n")
        common.write_text(dream_io.harvest_hash_path(bid), common.sha256_file(out) + "\n")
        write_context(bdir, payload)
        extra["bundle"] = bid
        return common.emit("dream harvest", "pass", summary, evidence=out, nonce=nonce, root=home, extra=extra)

    return common.run_guarded("dream harvest", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
