"""dream curate <date>: keep the few candidates of the reflection that earn a place. Code only.

Reads candidates.json and harvest.json of one bundle. Writes proposal.json, proposal.md and
curate.txt, which lists what it dropped and why."""
from __future__ import annotations

import json
import os
import re
import sys
import time

import common
import dream_io
import dream_learn
from common import RsError
from dream_scrub import scrub

OPS = ("ADD", "EDIT", "MERGE", "RETIRE")
MAX_RULE_WORDS = 40
DUP = 0.6
CONTAINED = 0.8
NO_TARGET = ("", "NULL", "NONE", "-", "N/A")
HUMAN = re.compile(r"^(?:4-human[^/]*\.md|decisions\.md)$")
# Negations stay in: "never X" and "X" are not the same rule.
STOP = frozenset("a an the of to in on for and or is are be it its this that with at as by from into".split())
CATEGORIES = ("invalid", "evidence", "weak", "duplicate", "rejected", "conflict", "cap")


def tokens(text):
    out = set()
    for t in re.findall(r"[a-z0-9]+", str(text).lower()):
        if t in STOP:
            continue
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.add(t)
    return out


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a | b))


def contained(a, b):
    """The share of the tokens of a that b also has."""
    return len(a & b) / float(len(a)) if a else 0.0


def one_line(text):
    return " ".join(str(text if text is not None else "").split())


def glob_problem(g):
    if not g:
        return "empty glob"
    if re.search(r"\s", g):
        return "space in a glob"
    if g.startswith("/") or ".." in g.split("/"):
        return "a glob must stay inside the repo"
    if "{" in g or "}" in g:
        return "braces are not supported; list each glob"
    if g.count("[") != g.count("]"):
        return "unbalanced brackets"
    if re.search(r"[\x00-\x1f]", g):
        return "control character"
    return None


class Resolver(object):
    """Finds the file that an evidence string names. The reflection writes `cp5/4-human.md:3`."""

    def __init__(self, root, bid):
        r = common.r_dir(root)
        self.root = root
        self.bases = [root, r, os.path.join(r, "evidence"), dream_io.bundle_dir(root, bid)]
        self._files = None

    def files(self):
        if self._files is None:
            found = []
            for sub in ("evidence", "plans"):
                top = os.path.join(common.r_dir(self.root), sub)
                for dirpath, dirs, names in os.walk(top):
                    dirs[:] = sorted(d for d in dirs if d not in ("locked", "_state"))
                    for n in sorted(names):
                        found.append(common.rel(self.root, os.path.join(dirpath, n)))
            self._files = found
        return self._files

    @staticmethod
    def split(ref):
        """(path, line, finding ID) of `path:line` or `path#id`. Words after the first are comments."""
        words = str(ref).strip().split()
        tok = words[0].strip("`'\"()[]<>").rstrip(".,;:") if words else ""
        m = re.match(r"^(.*?)(?::(\d+)(?:-\d+)?)?(?:#([\w.:-]+))?$", tok)
        return m.group(1), (int(m.group(2)) if m.group(2) else None), m.group(3)

    def resolve(self, ref):
        """{path, line, short, row, human} for an evidence string, or None when no file matches."""
        path, line, frag = self.split(ref)
        if not path:
            return None
        if os.path.isabs(path):
            path = os.path.relpath(path, self.root)
        parts = path.replace(os.sep, "/").split("/")
        if ".." in parts:
            return None
        suffix = (":%d" % line if line else "") + ("#" + frag if frag else "")
        for base in self.bases:
            cand = os.path.join(base, *parts)
            if os.path.isfile(cand):
                return self.hit(common.rel(self.root, cand), suffix)
        tail = "/" + "/".join(parts)
        matches = [f for f in self.files() if f.endswith(tail)]
        if len(matches) == 1:
            return self.hit(matches[0], suffix)
        if matches:
            # Two plans can share a checkpoint name, as in cp5. The file exists, but the ref does not say
            # which one. It gives no row, and it counts as human only when every match is.
            return {"path": None, "line": line, "row": None, "short": "/".join(parts) + suffix,
                    "human": all(HUMAN.match(m.split("/")[-1]) for m in matches)}
        return None

    @staticmethod
    def hit(found, suffix):
        seg = found.split("/")
        row = (seg[3], seg[4]) if found.startswith(".claude/ratchet/evidence/") and len(seg) >= 6 else None
        short = found
        for prefix in (".claude/ratchet/evidence/", ".claude/ratchet/"):
            if short.startswith(prefix):
                short = short[len(prefix):]
                break
        line = re.match(r":(\d+)", suffix)
        return {"path": found, "line": int(line.group(1)) if line else None, "row": row,
                "human": bool(HUMAN.match(seg[-1])), "short": short + suffix}


def scope_of(raw):
    if isinstance(raw, list):
        raw = ",".join(str(x) for x in raw)
    return [g.strip() for g in one_line(raw).split(",") if g.strip()]


def shape_problem(op, rule, check, scope_list):
    """Why this rule, check and scope cannot go into learnings.md, or None. The apply step asks too."""
    if op in ("ADD", "MERGE") and not scope_list:
        return "no scope"
    if op != "RETIRE":
        for g in scope_list:
            problem = glob_problem(g)
            if problem:
                return "bad glob %r: %s" % (g, problem)
        if not rule:
            return "no rule"
        if len(rule.split()) > MAX_RULE_WORDS:
            return "the rule has %d words; the limit is %d" % (len(rule.split()), MAX_RULE_WORDS)
        if not check:
            return "no check"
    for label, text in (("rule", rule), ("check", check)):
        if scrub(text) != text:
            return "the %s holds a secret" % label
        # cmd_learnings reads the status from any line of an entry, so this text could retire it.
        if re.search(r"status\s*:", text, re.I):
            return "the %s holds `status:`" % label
    return None


def split_targets(raw):
    items = [str(x) for x in raw] if isinstance(raw, list) else re.split(r"[,\s+&;]+", str(raw or ""))
    out = []
    for t in items:
        t = t.strip().upper()
        if t not in NO_TARGET and t not in out:
            out.append(t)
    return out


def check_candidate(raw, active, resolver, ids):
    """(candidate, None) or (None, (category, reason)). A candidate has a clean shape and found evidence."""
    if not isinstance(raw, dict):
        return None, ("invalid", "the candidate is not an object")
    op = str(raw.get("op") or "").strip().upper()
    if op not in OPS:
        return None, ("invalid", "unknown op %r" % raw.get("op"))
    targets = [] if op == "ADD" else split_targets(raw.get("target"))
    if op in ("EDIT", "RETIRE") and len(targets) != 1:
        return None, ("invalid", "%s needs exactly one target" % op)
    if op == "MERGE" and len(targets) < 2:
        return None, ("invalid", "MERGE needs two targets or more")
    for t in targets:
        if t not in ids:
            return None, ("invalid", "target %s not found" % t)
        if t not in active:
            return None, ("invalid", "target %s is retired" % t)

    scope_list = scope_of(raw.get("scope"))
    rule = one_line(raw.get("rule"))
    check = one_line(raw.get("check"))
    if op == "RETIRE":
        rule = rule[:300]
    problem = shape_problem(op, rule, check, scope_list)
    if problem:
        return None, ("invalid", problem)

    ev_raw = raw.get("evidence")
    ev_raw = [ev_raw] if isinstance(ev_raw, str) else ev_raw if isinstance(ev_raw, list) else []
    resolved = []
    missing = []
    for ref in ev_raw:
        hit = resolver.resolve(ref)
        if hit is None:
            missing.append(one_line(ref)[:80])
        elif hit["short"] not in [r["short"] for r in resolved]:
            resolved.append(hit)
    if not resolved:
        return None, ("evidence", "no evidence file found%s" % (": " + ", ".join(missing[:3]) if missing else ""))

    claimed = common.to_int(raw.get("rows"), 0)
    derived = len(set(r["row"] for r in resolved if r["row"]))
    counter = raw.get("counter")
    counter = [one_line(c)[:200] for c in counter] if isinstance(counter, list) else []
    return {"op": op, "targets": targets, "scope": scope_list if scope_list and op != "RETIRE" else None,
            "rule": rule, "check": check, "evidence": resolved, "missing": missing, "counter": counter,
            "rows": max(claimed, derived), "human": any(r["human"] for r in resolved)}, None


def candidates_from_log(path):
    """The last {"candidates": [...]} object in the output of the reflection, or None.

    A headless claude may be unable to write under .claude/. The reflect agent also returns the
    same JSON as its answer, and the script keeps that answer in reflect.log."""
    text = common.read_text(path)
    dec = json.JSONDecoder()
    found = None
    i = text.find("{")
    while i != -1:
        try:
            obj, end = dec.raw_decode(text, i)
        except ValueError:
            i = text.find("{", i + 1)
            continue
        if isinstance(obj, dict) and isinstance(obj.get("candidates"), list):
            found = obj
        i = text.find("{", end)
    return found


def reason_kept(c):
    bits = []
    if c["rows"]:
        bits.append("%d row%s" % (c["rows"], "" if c["rows"] == 1 else "s"))
    if c["human"]:
        bits.append("human evidence")
    return ", ".join(bits)


def render_md(bid, items):
    lines = ["Dream %s: %d proposal%s" % (bid, len(items), "" if len(items) == 1 else "s")]
    for n, it in enumerate(items, 1):
        t = it["target"]
        scope = " (%s)" % it["scope"] if it["scope"] else ""
        if it["op"] == "ADD":
            head = "ADD %s%s: %s" % (it["newId"], scope, it["rule"])
        elif it["op"] == "MERGE":
            head = "MERGE %s into %s%s: %s" % ("+".join(t), t[0], scope, it["rule"])
        elif it["op"] == "EDIT":
            head = "EDIT %s%s: %s" % (t, scope, it["rule"])
        else:
            head = "RETIRE %s: %s" % (t, it["rule"] or "the reflection gave no reason")
        lines.append("%d. %s" % (n, head))
        if it["op"] != "RETIRE":
            lines.append("   Check: %s" % it["check"])
        refs = it["evidence"]
        more = " +%d more" % (len(refs) - 3) if len(refs) > 3 else ""
        lines.append("   Evidence: %s: %s%s" % (it["reason"] or "cited", ", ".join(refs[:3]), more))
    lines.append("Reply per item: yes, no, or a change.")
    return "\n".join(lines) + "\n"


def duplicate_of(mine, own, entries, active, bullets):
    """Why this rule repeats an active entry or a version 1 bullet, or None. The entries it changes do not count."""
    for e in entries:
        if e["id"] in own or e["id"] not in active:
            continue
        sim = jaccard(mine, tokens(e["rule"]))
        if sim >= DUP:
            return "near-duplicate of %s (%.2f)" % (e["id"], sim)
    for n, b in bullets:
        theirs = tokens(dream_learn.v1_rule(b))
        sim = jaccard(mine, theirs)
        # A version 1 bullet is a long paragraph, so a short rule that restates it has a low Jaccard
        # score. The share of the rule's own words that the bullet holds catches that case.
        if sim >= DUP or (len(mine) >= 6 and contained(mine, theirs) >= CONTAINED):
            return "near-duplicate of a version 1 learning (line %d, %.2f)" % (n, sim)
    return None


def screen(c, entries, active, bullets, rejected):
    """(category, reason) when the candidate must go, else None."""
    if c["rows"] < 2 and not c["human"]:
        return "weak", "one row and no human evidence (rows %d)" % c["rows"]
    mine = tokens(c["rule"])
    if c["op"] == "EDIT":
        e = dream_learn.find(entries, c["targets"][0])
        if c["rule"] == e["rule"] and c["check"] == e["check"] and c["scope"] in (None, e["scope"]):
            return "invalid", "no change to %s" % e["id"]
    if c["op"] != "RETIRE":
        why = duplicate_of(mine, set(c["targets"]), entries, active, bullets)
        if why:
            return "duplicate", why
    for r in rejected:
        if c["op"] == "RETIRE":
            same = r.get("op") == "RETIRE" and str(r.get("target") or "").upper() == c["targets"][0]
        else:
            same = r.get("op") != "RETIRE" and jaccard(mine, tokens(r.get("rule") or "")) >= DUP
        if same:
            return "rejected", "matches an item that the human rejected on %s" % (r.get("date") or "an earlier date")
    return None


def pick(survivors, max_items):
    """(kept, [(category, candidate, reason)]): the best candidates first, one change for each target."""
    survivors = sorted(survivors, key=lambda c: (-c["rows"], 0 if c["human"] else 1, c["idx"]))
    ranked = []
    out = []
    used = set()
    for c in survivors:
        clash = [t for t in c["targets"] if t in used]
        if clash:
            out.append(("conflict", c, "%s is also changed by a better candidate" % clash[0]))
        elif c["op"] != "RETIRE" and any(
                k["op"] != "RETIRE" and jaccard(tokens(c["rule"]), tokens(k["rule"])) >= DUP for k in ranked):
            out.append(("duplicate", c, "near-duplicate of a better candidate"))
        else:
            used.update(c["targets"])
            ranked.append(c)
    out.extend(("cap", c, "over the limit of %d items" % max_items) for c in ranked[max_items:])
    return ranked[:max_items], out


def target_of(c):
    if c["op"] == "MERGE":
        return c["targets"]
    return c["targets"][0] if c["targets"] else None


def load_candidates(bdir, bid, log):
    """The list in candidates.json, or the one in reflect.log when the file is missing."""
    path = os.path.join(bdir, "candidates.json")
    raw = common.read_json(path, default=None)
    if raw is None:
        raw = candidates_from_log(os.path.join(bdir, "reflect.log"))
        if raw is None:
            raise RsError("no candidates.json in dream %s: the reflection wrote nothing" % bid)
        common.write_json(path, raw)
        log.append("note: candidates.json was missing, so these candidates come from reflect.log")
    cands = raw.get("candidates") if isinstance(raw, dict) else raw
    if not isinstance(cands, list):
        raise RsError('candidates.json must hold {"candidates": [...]}')
    return cands


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("dream curate", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 1:
            raise RsError("usage: dream curate <date>")
        root = common.repo_root()
        cfg = common.load_config(root, required=False)
        bid = dream_io.check_bundle(pos[0])
        bdir = dream_io.bundle_dir(root, bid)
        if os.path.isfile(os.path.join(bdir, "review.json")):
            raise RsError("dream %s is reviewed already" % bid)
        harvest = common.read_json(os.path.join(bdir, "harvest.json"), default=None)
        if not isinstance(harvest, dict):
            raise RsError("no harvest.json in dream %s: run dream harvest first" % bid)
        log = []
        cands = load_candidates(bdir, bid, log)

        max_items = max(0, common.to_int((cfg.get("dream") or {}).get("maxItems"), 3))
        _, entries, bullets = dream_learn.parse(common.read_text(dream_io.learnings_path(root)))
        ids = set(e["id"] for e in entries)
        active = set(e["id"] for e in entries if e["status"] == "active")
        rejected = dream_io.read_jsonl(dream_io.rejected_path(root))
        resolver = Resolver(root, bid)

        dropped = dict((k, 0) for k in CATEGORIES)

        def drop(cat, op, text, why):
            dropped[cat] += 1
            log.append("drop %s %s: %s - %s" % (cat, op, why, one_line(text)[:80]))

        survivors = []
        for idx, item in enumerate(cands):
            c, bad = check_candidate(item, active, resolver, ids)
            if c is not None:
                c["idx"] = idx
                log.extend("note: evidence not found, left out: %s" % m for m in c["missing"])
                bad = screen(c, entries, active, bullets, rejected)
            if bad:
                shown = c if c is not None else item if isinstance(item, dict) else {}
                drop(bad[0], str(shown.get("op", "?")), shown.get("rule", ""), bad[1])
            else:
                survivors.append(c)
        kept, cut = pick(survivors, max_items)
        for cat, c, why in cut:
            drop(cat, c["op"], c["rule"], why)

        n_id = int(dream_learn.next_id(entries)[2:])
        items = []
        keep_lines = []
        for n, c in enumerate(kept, 1):
            new_id = None
            if c["op"] == "ADD":
                new_id = "L-%03d" % n_id
                n_id += 1
            items.append({
                "id": "P%d" % n, "op": c["op"], "target": target_of(c), "newId": new_id,
                "scope": ", ".join(c["scope"]) if c["scope"] else None, "rule": c["rule"], "check": c["check"],
                "evidence": [r["short"] for r in c["evidence"]], "counter": c["counter"], "rows": c["rows"],
                "human": c["human"], "reason": reason_kept(c)})
            keep_lines.append("keep P%d %s: %s - %s" % (n, c["op"], reason_kept(c), c["rule"][:80]))

        now = time.time()
        generated = harvest.get("generatedEpoch")
        if not isinstance(generated, (int, float)) or isinstance(generated, bool):
            generated = now
        summary = "kept %d of %d candidates" % (len(items), len(cands))
        cut_text = ", ".join("%d %s" % (v, k) for k, v in dropped.items() if v)
        if cut_text:
            summary += "; dropped %s" % cut_text
        report = os.path.join(bdir, "curate.txt")
        common.write_text(report, "Dream %s curate: %s\n%s\n" % (bid, summary, "\n".join(keep_lines + log)))
        common.write_text(os.path.join(bdir, "proposal.md"), render_md(bid, items))
        common.write_json(os.path.join(bdir, "proposal.json"), {
            "version": 1, "bundle": bid, "generated": dream_io.iso_of(now), "maxItems": max_items, "items": items})
        if not items:
            # Nothing to decide, so no review is due. This keeps an empty proposal off the human's screen.
            common.write_json(os.path.join(bdir, "review.json"),
                              {"bundle": bid, "reviewed": dream_io.iso_of(now), "accepted": [], "rejected": [],
                               "note": "no items to review"})
        dream_io.write_last(root, bid, float(generated), len(items))
        return common.emit("dream curate", "pass", summary, evidence=report, nonce=nonce, root=root,
                           extra={"bundle": bid, "items": len(items), "candidates": len(cands),
                                  "dropped": dict((k, v) for k, v in dropped.items() if v),
                                  "proposal": common.rel(root, os.path.join(bdir, "proposal.json"))})

    return common.run_guarded("dream curate", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
