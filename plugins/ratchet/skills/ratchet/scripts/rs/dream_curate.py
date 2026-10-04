"""dream curate <bundle>: keep the few candidates of the reflection that earn a place. Code only.

Reads candidates.json and harvest.json of one bundle. Writes proposal.json, proposal.md and
curate.txt, which lists what it dropped and why.

The model gives the words and the evidence. Code decides the rest: every cite must exist in the
harvest, and the recurrence comes from the resolved cites, never from a count that the model claims."""
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
KINDS = ("global", "project", "ratchet")
STRONG = ("rule", "correction", "declined", "interrupt")
MAX_RULE_WORDS = 40
MAX_WHY_CHARS = 300
MAX_PATHS = 8
DUP = 0.6
CONTAINED = 0.8
NO_TARGET = ("", "NULL", "NONE", "-", "N/A")
HUMAN = re.compile(r"^(?:4-human[^/]*\.md|decisions\.md)$")
TURN_ID = re.compile(r"^[0-9a-f]{8}#\d+$", re.I)
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


def glob_problem(g, braces=False):
    """Why a glob cannot be used, or None. A ratchet scope has no braces; a rule path may have them."""
    if not g:
        return "empty glob"
    if re.search(r"\s", g):
        return "space in a glob"
    if g.startswith("/") or ".." in g.split("/"):
        return "a glob must stay relative"
    if not braces and ("{" in g or "}" in g):
        return "braces are not supported; list each glob"
    if g.count("[") != g.count("]"):
        return "unbalanced brackets"
    if re.search(r"[\x00-\x1f\"'\\]", g):
        return "control character, quote or backslash"
    return None


class Resolver(object):
    """Finds the file that a ratchet evidence string names. The reflection writes `cp5/4-human.md:3`."""

    def __init__(self, root, extra=()):
        r = common.r_dir(root)
        self.root = root
        self.bases = [root, r, os.path.join(r, "evidence")] + list(extra)
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


def id_list(raw):
    """Entry IDs from a string, a comma list or a list. `null` and `-` mean none."""
    items = [str(x) for x in raw] if isinstance(raw, list) else re.split(r"[,\s+&;]+", str(raw or ""))
    out = []
    for t in items:
        t = t.strip().upper()
        if t not in NO_TARGET and t not in out:
            out.append(t)
    return out



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


def words_problem(op, rule, why):
    """Why a global or project rule cannot be written, or None. A RETIRE may carry a reason and no rule."""
    if op != "RETIRE":
        if not rule:
            return "no rule"
        if len(rule.split()) > MAX_RULE_WORDS:
            return "the rule has %d words; the limit is %d" % (len(rule.split()), MAX_RULE_WORDS)
        if not why:
            return "no why"
    if len(why) > MAX_WHY_CHARS:
        return "the why has %d characters; the limit is %d" % (len(why), MAX_WHY_CHARS)
    for label, text in (("rule", rule), ("why", why)):
        if scrub(text) != text:
            return "the %s holds a secret" % label
        if text.lstrip().startswith("---"):
            return "the %s starts with a frontmatter marker" % label
    return None


def paths_of(raw):
    """(paths, problem): globs for a global rule. None means the candidate gave none."""
    if raw is None:
        return None, None
    items = raw if isinstance(raw, list) else [x for x in re.split(r"\s*,\s*", one_line(raw)) if x]
    out = []
    for g in items:
        g = str(g).strip()
        problem = glob_problem(g, braces=True)
        if problem:
            return None, "bad path glob %r: %s" % (g, problem)
        if g not in out:
            out.append(g)
    if len(out) > MAX_PATHS:
        return None, "%d path globs; the limit is %d" % (len(out), MAX_PATHS)
    return out, None


# ---------------------------------------------------------------- the evidence

class Evidence(object):
    """The facts that a cite may name: the human turns and the friction groups of the harvest, and each
    repo's ratchet files. A cite that names nothing here is dropped."""

    def __init__(self, harvest):
        listed = lambda key: [x for x in harvest.get(key) or [] if isinstance(x, dict) and x.get("id")]
        self.turns = dict((t["id"].lower(), t) for t in listed("turns"))
        self.friction = dict((g["id"].upper(), g) for g in listed("friction"))
        self.examples = {}
        for g in self.friction.values():
            for ex in g.get("examples") or []:
                if isinstance(ex, dict) and ex.get("ref"):
                    self.examples[str(ex["ref"]).lower()] = g["id"].upper()
        self.projects = harvest.get("projects") if isinstance(harvest.get("projects"), dict) else {}
        ratchet = harvest.get("ratchet")
        self.repos = sorted(r for r in ratchet if isinstance(r, str)) if isinstance(ratchet, dict) else []
        self._resolvers = {}

    def resolver(self, repo):
        if repo not in self._resolvers:
            self._resolvers[repo] = Resolver(repo)
        return self._resolvers[repo]

    def by_id(self, token):
        t = token.strip("`'\"()[]<>").rstrip(".,;:")
        low = t.lower()
        if low in self.turns:
            return {"kind": "turn", "key": low, "turn": self.turns[low], "short": self.turns[low]["id"]}
        fid = low.upper() if low.upper() in self.friction else self.examples.get(low)
        if fid:
            return {"kind": "friction", "key": fid, "friction": self.friction[fid], "short": fid}
        return None

    def resolve(self, ref, repo):
        """([cites], missing) for one evidence string. A string of IDs gives one cite for each ID."""
        text = one_line(ref)
        hits = [h for h in (self.by_id(t) for t in re.split(r"[\s,;]+", text) if t) if h]
        if hits:
            return hits, False
        repos = [repo] if repo else self.repos
        found = []
        for r in repos:
            if r not in self.repos:
                continue
            hit = self.resolver(r).resolve(text)
            if hit is not None:
                found.append({"kind": "ratchet", "key": "%s|%s" % (r, hit["short"]), "repo": r, "hit": hit,
                              "short": hit["short"]})
        # Without a repo, a ref that two repos can resolve names no single one.
        if len(found) == 1:
            return found, False
        return [], True


class Context(object):
    """What curate checks the candidates against."""

    def __init__(self, harvest, cfg):
        self.ev = Evidence(harvest)
        self.cfg = cfg
        self.rules = dict((gid, parsed) for gid, _, parsed in dream_learn.rule_files())
        self.rejected = dream_io.read_jsonl(dream_io.rejected_path())
        self._learn = {}
        self._memory = {}

    def learnings(self, repo):
        """(entries, active IDs, bullets) of one repo's learnings.md."""
        if repo not in self._learn:
            _, entries, bullets = dream_learn.parse(common.read_text(dream_io.learnings_path(repo)))
            self._learn[repo] = (entries, set(e["id"] for e in entries if e["status"] == "active"), bullets)
        return self._learn[repo]

    def memory(self, project):
        """The rule texts that a project's memory already holds."""
        if project not in self._memory:
            self._memory[project] = dream_learn.memory_rules(
                os.path.join(dream_io.projects_dir(), project, "memory"))
        return self._memory[project]


# ---------------------------------------------------------------- one candidate

def check_candidate(raw, ctx):
    """(candidate, None) or (None, (category, reason)). A candidate has a clean shape and found evidence."""
    if not isinstance(raw, dict):
        return None, ("invalid", "the candidate is not an object")
    kind = str(raw.get("target") or "").strip().lower()
    if kind not in KINDS:
        return None, ("invalid", "unknown target %r: use global, project or ratchet" % raw.get("target"))
    op = str(raw.get("op") or "").strip().upper()
    if op not in OPS:
        return None, ("invalid", "unknown op %r" % raw.get("op"))
    if kind == "project" and op != "ADD":
        return None, ("invalid", "a project memory supports ADD only")
    if kind == "global" and op == "MERGE":
        return None, ("invalid", "a global rule supports ADD, EDIT and RETIRE")
    ids = [] if op == "ADD" else id_list(raw.get("id"))
    if op in ("EDIT", "RETIRE") and len(ids) != 1:
        return None, ("invalid", "%s needs exactly one id" % op)
    if op == "MERGE" and len(ids) < 2:
        return None, ("invalid", "MERGE needs two ids or more")
    rule = one_line(raw.get("rule"))
    why = one_line(raw.get("why"))
    c = {"op": op, "kind": kind, "ids": ids, "rule": rule, "why": why, "project": None, "repo": None,
         "paths": None, "scope": None, "check": "", "apply": one_line(raw.get("apply")), "keys": []}

    if kind == "global":
        for t in ids:
            if t not in ctx.rules:
                return None, ("invalid", "rule %s not found among the active global rules" % t)
        problem = words_problem(op, rule, why)
        if problem:
            return None, ("invalid", problem)
        c["paths"], problem = paths_of(raw.get("paths"))
        if problem:
            return None, ("invalid", problem)
        c["keys"] = ids
    elif kind == "project":
        project = str(raw.get("project") or "")
        if project not in ctx.ev.projects:
            return None, ("invalid", "project %r has no human turn in this harvest" % project)
        problem = words_problem(op, rule, why)
        if not problem and len(c["apply"].split()) > MAX_RULE_WORDS:
            problem = "the apply text has more than %d words" % MAX_RULE_WORDS
        if not problem and scrub(c["apply"]) != c["apply"]:
            problem = "the apply text holds a secret"
        if problem:
            return None, ("invalid", problem)
        c["project"] = project
    else:
        repo = str(raw.get("repo") or "")
        if repo not in ctx.ev.repos:
            return None, ("invalid", "repo %r has no ratchet evidence in this harvest" % repo)
        entries, active, _ = ctx.learnings(repo)
        known = set(e["id"] for e in entries)
        for t in ids:
            if t not in known:
                return None, ("invalid", "entry %s not found in the learnings of that repo" % t)
            if t not in active:
                return None, ("invalid", "entry %s is retired" % t)
        scope_list = scope_of(raw.get("scope"))
        c["check"] = one_line(raw.get("check"))
        if op == "RETIRE":
            rule = c["rule"] = rule[:300]
        problem = shape_problem(op, rule, c["check"], scope_list)
        if problem:
            return None, ("invalid", problem)
        c["repo"] = repo
        c["scope"] = scope_list if scope_list and op != "RETIRE" else None
        c["keys"] = ["%s|%s" % (repo, t) for t in ids]

    ev_raw = raw.get("evidence")
    ev_raw = [ev_raw] if isinstance(ev_raw, str) else ev_raw if isinstance(ev_raw, list) else []
    cites = {}
    missing = []
    for ref in ev_raw:
        got, bad = ctx.ev.resolve(ref, c["repo"])
        if bad:
            missing.append(one_line(ref)[:80])
        for cite in got:
            cites.setdefault(cite["key"], cite)
    if not cites:
        return None, ("evidence", "no evidence found%s" % (": " + ", ".join(missing[:3]) if missing else ""))
    counter = raw.get("counter")
    c["counter"] = [one_line(x)[:200] for x in counter] if isinstance(counter, list) else []
    c["evidence"] = list(cites.values())
    c["missing"] = missing
    gate(c, ctx.ev)
    return c, None


def gate(c, ev):
    """Count the recurrence from the resolved cites. Sets recurrence, strong, ok and why for each candidate.

    A count that the model claims is never read."""
    turns = [x["turn"] for x in c["evidence"] if x["kind"] == "turn"]
    frictions = [x["friction"] for x in c["evidence"] if x["kind"] == "friction"]
    hits = [x["hit"] for x in c["evidence"] if x["kind"] == "ratchet"]
    tags = lambda ts: sorted(set(t for turn in ts for t in turn["tags"] if t in STRONG))
    if c["kind"] == "project":
        mine = [t for t in turns if t["project"] == c["project"]]
        strong = tags(mine)
        c["recurrence"] = len(mine)
        c["ok"] = len(mine) >= 2 or bool(strong)
        c["strong"] = bool(strong)
        c["why_not"] = "%d turn%s in that project and none is tagged %s" % (
            len(mine), "" if len(mine) == 1 else "s", "/".join(STRONG))
        c["reason"] = "%d turn%s%s" % (len(mine), "" if len(mine) == 1 else "s",
                                       ", tagged " + "/".join(strong) if strong else "")
    elif c["kind"] == "global":
        sessions = set(t["session"] for t in turns) | set(s for g in frictions for s in g.get("sessions") or [])
        rules = [t for t in turns if "rule" in t["tags"]]
        c["recurrence"] = len(sessions)
        c["ok"] = len(sessions) >= 2 or bool(rules)
        c["strong"] = bool(rules)
        c["why_not"] = "%d session%s and no turn tagged rule" % (len(sessions), "" if len(sessions) == 1 else "s")
        c["reason"] = "%d session%s%s" % (len(sessions), "" if len(sessions) == 1 else "s",
                                          ", a rule turn" if rules else "")
    else:
        rows = set(tuple(h["row"]) for h in hits if h["row"])
        strong = tags(turns)
        human = any(h["human"] for h in hits) or bool(strong)
        c["recurrence"] = len(rows) + len(turns)
        c["ok"] = c["recurrence"] >= 2 or human
        c["strong"] = human
        c["why_not"] = "one row and no human evidence (rows %d)" % c["recurrence"]
        bits = []
        if c["recurrence"]:
            bits.append("%d row%s" % (c["recurrence"], "" if c["recurrence"] == 1 else "s"))
        if human:
            bits.append("human evidence")
        c["reason"] = ", ".join(bits)


def candidates_from_log(path):
    """The last {"candidates": [...]} object in the output of the reflection, or None.

    A headless claude may be unable to write the file. The reflect agent also returns the same JSON
    as its answer, and the script keeps that answer in reflect.log."""
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


# ---------------------------------------------------------------- screening and ranking

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


def similar(mine, text):
    theirs = tokens(text)
    sim = jaccard(mine, theirs)
    return sim if sim >= DUP or (len(mine) >= 6 and contained(mine, theirs) >= CONTAINED) else None


def screen(c, ctx):
    """(category, reason) when the candidate must go, else None."""
    if not c["ok"]:
        return "weak", c["why_not"]
    mine = tokens(c["rule"])
    if c["kind"] == "global":
        if c["op"] == "EDIT":
            old = ctx.rules[c["ids"][0]]
            if c["rule"] == old["rule"] and c["why"] == old["why"] and c["paths"] in (None, old["paths"]):
                return "invalid", "no change to %s" % old["id"]
        if c["op"] != "RETIRE":
            for gid, old in sorted(ctx.rules.items()):
                if gid not in c["ids"] and similar(mine, old["rule"]) is not None:
                    return "duplicate", "near-duplicate of the global rule %s" % gid
    elif c["kind"] == "project":
        for line in ctx.memory(c["project"]):
            if similar(mine, line) is not None:
                return "duplicate", "near-duplicate of a memory line of that project"
    else:
        entries, active, bullets = ctx.learnings(c["repo"])
        if c["op"] == "EDIT":
            e = dream_learn.find(entries, c["ids"][0])
            scope = c["scope"] if c["scope"] is not None else e["scope"]
            if c["rule"] == e["rule"] and c["check"] == e["check"] and scope == e["scope"]:
                return "invalid", "no change to %s" % e["id"]
        if c["op"] != "RETIRE":
            why = duplicate_of(mine, set(c["ids"]), entries, active, bullets)
            if why:
                return "duplicate", why
    for r in ctx.rejected:
        if c["op"] == "RETIRE":
            same = r.get("op") == "RETIRE" and str(r.get("entry") or r.get("target") or "").upper() == c["ids"][0]
        else:
            same = r.get("op") != "RETIRE" and jaccard(mine, tokens(r.get("rule") or "")) >= DUP
        if same:
            return "rejected", "matches an item that the human rejected on %s" % (r.get("date") or "an earlier date")
    return None


def rank(c):
    return (-c["recurrence"], 0 if c["strong"] else 1, c["idx"])


def over_cap(survivors, active, cap):
    """(kept, cut): a global ADD needs room. Active files plus ADDs minus RETIREs may not pass the cap."""
    adds = sorted((c for c in survivors if c["kind"] == "global" and c["op"] == "ADD"), key=rank)
    retires = sum(1 for c in survivors if c["kind"] == "global" and c["op"] == "RETIRE")
    room = max(0, cap - active + retires)
    cut = adds[room:]
    kept = [c for c in survivors if not any(c is x for x in cut)]
    return kept, [("cap", c, "the global rules are capped at %d, and %d are active" % (cap, active)) for c in cut]


def pick(survivors, max_items):
    """(kept, [(category, candidate, reason)]): the best candidates first, one change for each entry."""
    survivors = sorted(survivors, key=rank)
    ranked = []
    out = []
    used = set()
    for c in survivors:
        clash = [t for t in c["keys"] if t in used]
        if clash:
            out.append(("conflict", c, "%s is also changed by a better candidate" % clash[0].split("|")[-1]))
        elif c["op"] != "RETIRE" and any(
                k["op"] != "RETIRE" and jaccard(tokens(c["rule"]), tokens(k["rule"])) >= DUP for k in ranked):
            out.append(("duplicate", c, "near-duplicate of a better candidate"))
        else:
            used.update(c["keys"])
            ranked.append(c)
    out.extend(("cap", c, "over the limit of %d items" % max_items) for c in ranked[max_items:])
    return ranked[:max_items], out


# ---------------------------------------------------------------- the proposal

def entry_of(c):
    if c["op"] == "MERGE":
        return c["ids"]
    return c["ids"][0] if c["ids"] else None


def new_slug(c, taken, memory_dir):
    base = dream_learn.slugify(c["rule"])
    slug, n = base, 1
    while slug in taken or os.path.exists(os.path.join(memory_dir, slug + ".md")):
        n += 1
        slug = "%s-%d" % (base, n)
    return slug


def make_items(kept, ctx):
    """The proposal items, with the ID that each ADD will get. Apply allocates again and warns on a clash."""
    items = []
    gids, lids, slugs = [], {}, {}
    for n, c in enumerate(kept, 1):
        new_id = None
        if c["op"] == "ADD":
            if c["kind"] == "global":
                new_id = dream_learn.next_gid(gids)
                gids.append(new_id)
            elif c["kind"] == "ratchet":
                entries = ctx.learnings(c["repo"])[0]
                top = lids.get(c["repo"]) or int(dream_learn.next_id(entries)[2:])
                new_id = "L-%03d" % top
                lids[c["repo"]] = top + 1
            else:
                taken = slugs.setdefault(c["project"], set())
                new_id = new_slug(c, taken, os.path.join(dream_io.projects_dir(), c["project"], "memory"))
                taken.add(new_id)
        items.append({
            "id": "P%d" % n, "op": c["op"], "target": c["kind"], "entry": entry_of(c), "newId": new_id,
            "project": c["project"], "repo": c["repo"], "paths": c["paths"],
            "scope": ", ".join(c["scope"]) if c["scope"] else None, "rule": c["rule"], "why": c["why"],
            "check": c["check"] or None, "apply": c["apply"] or None,
            "evidence": [x["short"] for x in c["evidence"]], "counter": c["counter"],
            "recurrence": c["recurrence"], "strong": c["strong"], "reason": c["reason"]})
    return items


def render_md(bid, items):
    lines = ["Dream %s: %d proposal%s" % (bid, len(items), "" if len(items) == 1 else "s")]
    for n, it in enumerate(items, 1):
        if it["target"] == "global":
            where = "global"
        elif it["target"] == "project":
            where = "memory of %s" % it["project"]
        else:
            where = "ratchet in %s" % os.path.basename(str(it["repo"] or "").rstrip("/"))
        if it["op"] == "ADD":
            ident = it["newId"]
        elif it["op"] == "MERGE":
            ident = "%s into %s" % ("+".join(it["entry"]), it["entry"][0])
        else:
            ident = it["entry"]
        scope = it["scope"] or (", ".join(it["paths"]) if it["paths"] else "")
        # A RETIRE has no new rule. Its reason sits in `rule` for a ratchet entry, and in `why` for a global rule.
        said = it["rule"] or (it["why"] if it["op"] == "RETIRE" else "")
        lines.append("%d. %s %s %s%s: %s" % (n, it["op"], where, ident, " (%s)" % scope if scope else "",
                                            said or "the reflection gave no reason"))
        if it["target"] == "ratchet" and it["op"] != "RETIRE":
            lines.append("   Check: %s" % it["check"])
        elif it["why"] and it["why"] != said:
            lines.append("   Why: %s" % it["why"])
        refs = it["evidence"]
        more = " +%d more" % (len(refs) - 3) if len(refs) > 3 else ""
        lines.append("   Evidence: %s: %s%s" % (it["reason"] or "cited", ", ".join(refs[:3]), more))
    lines.append("Reply per item: yes, no, or a change.")
    return "\n".join(lines) + "\n"


def load_candidates(bdir, bid, log):
    """The list in candidates.json, or else the reflection's answer in reflect.log.

    The nightly run answers in reflect.log: its folder is in ~/.claude, where a headless
    run may not write. A lead that spawns ratchet:reflect saves the answer as candidates.json."""
    path = os.path.join(bdir, "candidates.json")
    raw = common.read_json(path, default=None)
    if raw is None:
        raw = candidates_from_log(os.path.join(bdir, "reflect.log"))
        if raw is None:
            raise RsError("no candidates in dream %s: the reflection gave no JSON answer" % bid)
        common.write_json(path, raw)
        log.append("note: the candidates come from the reflection's answer in reflect.log")
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
            raise RsError("usage: dream curate <bundle>")
        home = dream_io.home_dir()
        cfg = dream_io.load_config()
        bid = dream_io.check_bundle(pos[0])
        bdir = dream_io.bundle_dir(bid)
        if os.path.isfile(os.path.join(bdir, "review.json")):
            raise RsError("dream %s is reviewed already" % bid)
        harvest = common.read_json(os.path.join(bdir, "harvest.json"), default=None)
        if not isinstance(harvest, dict):
            raise RsError("no harvest.json in dream %s: run dream harvest first" % bid)
        # The reflection may write inside its folder. The harvest hash lives beside the folder, out of its reach.
        expected = common.read_text(dream_io.harvest_hash_path(bid)).strip()
        if expected and expected != common.sha256_file(os.path.join(bdir, "harvest.json")):
            raise RsError("harvest.json of dream %s changed after the harvest: run dream harvest again" % bid)
        log = []
        cands = load_candidates(bdir, bid, log)
        ctx = Context(harvest, cfg)
        dropped = dict((k, 0) for k in CATEGORIES)

        def drop(cat, op, text, why):
            dropped[cat] += 1
            log.append("drop %s %s: %s - %s" % (cat, op, why, one_line(text)[:80]))

        survivors = []
        for idx, item in enumerate(cands):
            c, bad = check_candidate(item, ctx)
            if c is not None:
                c["idx"] = idx
                log.extend("note: evidence not found, left out: %s" % m for m in c["missing"])
                bad = screen(c, ctx)
            if bad:
                shown = c if c is not None else item if isinstance(item, dict) else {}
                drop(bad[0], str(shown.get("op", "?")), shown.get("rule", ""), bad[1])
            else:
                survivors.append(c)
        active = len(ctx.rules)
        survivors, cut = over_cap(survivors, active, cfg["globalCap"])
        for cat, c, why in cut:
            drop(cat, c["op"], c["rule"], why)
        kept, cut = pick(survivors, cfg["maxItems"])
        for cat, c, why in cut:
            drop(cat, c["op"], c["rule"], why)
        # A RETIRE that pick cut may have made room for an ADD that stayed. Check the cap once more.
        kept, cut = over_cap(kept, active, cfg["globalCap"])
        for cat, c, why in cut:
            drop(cat, c["op"], c["rule"], why)

        items = make_items(kept, ctx)
        keep_lines = ["keep %s %s %s: %s - %s" % (it["id"], it["op"], it["target"], it["reason"], it["rule"][:80])
                      for it in items]
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
            "version": 2, "bundle": bid, "generated": dream_io.iso_of(now), "maxItems": cfg["maxItems"],
            "items": items})
        if not items:
            # Nothing to decide, so no review is due. This keeps an empty proposal off the human's screen.
            common.write_json(os.path.join(bdir, "review.json"),
                              {"bundle": bid, "reviewed": dream_io.iso_of(now), "accepted": [], "rejected": [],
                               "note": "no items to review"})
        # The window moves only here, after the proposal exists. A failed night is read again the next night.
        dream_io.write_last(bid, float(generated), len(items))
        dream_io.refresh_pending()
        return common.emit("dream curate", "pass", summary, evidence=report, nonce=nonce, root=home,
                           extra={"bundle": bid, "items": len(items), "candidates": len(cands),
                                  "dropped": dict((k, v) for k, v in dropped.items() if v),
                                  "proposal": common.rel(home, os.path.join(bdir, "proposal.json"))})

    return common.run_guarded("dream curate", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
