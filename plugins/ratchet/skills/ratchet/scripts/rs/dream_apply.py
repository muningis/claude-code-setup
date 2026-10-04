"""dream apply <bundle> --accept <ids> --reject <ids> [--reason <text>]: write what the human decided.

An accepted item goes to one of three targets:
  global   a rule file in ~/.claude/rules/dream/, which claude loads in every project
  project  a feedback memory file in the auto-memory folder of one project, with its MEMORY.md line
  ratchet  an entry of learnings.md in one repo, which is then pinned again in each plan

Every accepted item is checked before any file changes, so a bad item changes nothing."""
from __future__ import annotations

import json
import os
import re
import shutil
import sys

import common
import dream_curate
import dream_io
import dream_learn
from common import RsError
from dream_scrub import clean, scrub

LEARNINGS = ".claude/ratchet/learnings.md"
SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,60}$")


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


def apply_learnings(text, item, bid):
    """(new text, entry ID) after one accepted ratchet item. It checks the item again: the human may have edited it."""
    iid = item.get("id")
    op = str(item.get("op") or "").upper()
    if op not in dream_curate.OPS:
        raise RsError("%s: unknown op %r" % (iid, item.get("op")))
    ids = [] if op == "ADD" else dream_curate.id_list(item.get("entry"))
    if op in ("EDIT", "RETIRE") and len(ids) != 1 or op == "MERGE" and len(ids) < 2:
        raise RsError("%s: %s has the wrong number of entries" % (iid, op))
    _, entries, _ = dream_learn.parse(text)
    live = dict((e["id"], e) for e in entries)
    for t in ids:
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
        return dream_learn.retire(text, ids[0]), ids[0]
    text = dream_learn.edit(text, ids[0], scope, rule, check)
    for other in ids[1:]:
        text = dream_learn.retire(text, other, "merged into %s by dream %s" % (ids[0], bid))
    return text, ids[0]


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


class Plan(object):
    """The writes of one apply. An item adds its writes after it passed its checks; commit() makes them."""

    def __init__(self, bid, known):
        self.bid = bid
        self.today = dream_io.utc_date()
        self.known = known
        self.learn = {}
        self.files = {}
        self.index = {}
        self.moves = []
        self.gids = []
        self.skipped = []

    def learnings_text(self, repo):
        if repo not in self.learn:
            before = dream_io.read_exact(dream_io.learnings_path(repo))
            self.learn[repo] = [before, before]
        return self.learn[repo][1]

    def index_text(self, mdir):
        if mdir not in self.index:
            before = dream_io.read_exact(os.path.join(mdir, "MEMORY.md"))
            self.index[mdir] = [before, before]
        return self.index[mdir][1]

    def commit(self):
        for repo, (before, text) in self.learn.items():
            if text != before:
                dream_io.write_exact(dream_io.learnings_path(repo), text)
        for path, text in self.files.items():
            dream_io.write_exact(path, text)
        for mdir, (before, text) in self.index.items():
            if text != before:
                dream_io.write_exact(os.path.join(mdir, "MEMORY.md"), text)
        for src, dst in self.moves:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            shutil.move(src, dst)


def retired_name(path):
    """Where a retired rule file goes. A name that is taken gets a number, so no file is overwritten."""
    base = os.path.join(dream_io.retired_dir(), os.path.basename(path))
    out, n = base, 1
    while os.path.exists(out):
        n += 1
        out = "%s.%d" % (base, n)
    return out


def plan_global(plan, item):
    iid, op = item["id"], str(item.get("op") or "").upper()
    rule = dream_curate.one_line(item.get("rule"))
    why = dream_curate.one_line(item.get("why"))
    problem = dream_curate.words_problem(op, rule, why)
    if problem:
        raise RsError("%s: %s" % (iid, problem))
    paths, problem = dream_curate.paths_of(item.get("paths"))
    if problem:
        raise RsError("%s: %s" % (iid, problem))
    if op == "ADD":
        gid = dream_learn.next_gid(plan.gids)
        plan.gids.append(gid)
        path = os.path.join(dream_io.rules_dir(), "%s-%s.md" % (gid, dream_learn.slugify(rule)))
        if os.path.exists(path) or path in plan.files:
            raise RsError("%s: %s exists already" % (iid, path))
        plan.files[path] = dream_learn.render_rule(gid, rule, why, paths or [], plan.bid, plan.today)
        return gid
    ids = dream_curate.id_list(item.get("entry"))
    if op not in ("EDIT", "RETIRE") or len(ids) != 1:
        raise RsError("%s: a global rule supports ADD, EDIT and RETIRE of one rule" % iid)
    found = [(path, parsed) for gid, path, parsed in dream_learn.rule_files() if gid == ids[0]]
    if not found:
        raise RsError("%s: %s is not an active global rule" % (iid, ids[0]))
    path, old = found[0]
    if op == "RETIRE":
        plan.moves.append((path, retired_name(path)))
        return ids[0]
    plan.files[path] = dream_learn.render_rule(
        ids[0], rule, why, old["paths"] if paths is None else paths, plan.bid, old["added"] or plan.today,
        edited=plan.today)
    return ids[0]


def plan_project(plan, item):
    iid = item["id"]
    project = str(item.get("project") or "")
    if str(item.get("op") or "").upper() != "ADD":
        raise RsError("%s: a project memory supports ADD only" % iid)
    if not project or project in (".", "..") or "/" in project or "\\" in project:
        raise RsError("%s: bad project folder %r" % (iid, project))
    if plan.known is not None and project not in plan.known["projects"]:
        raise RsError("%s: project %r has no human turn in this harvest" % (iid, project))
    if not os.path.isdir(os.path.join(dream_io.projects_dir(), project)):
        raise RsError("%s: no project folder %r" % (iid, project))
    rule = dream_curate.one_line(item.get("rule"))
    why = dream_curate.one_line(item.get("why"))
    how = dream_curate.one_line(item.get("apply")) or rule
    problem = dream_curate.words_problem("ADD", rule, why)
    if problem:
        raise RsError("%s: %s" % (iid, problem))
    if scrub(how) != how:
        raise RsError("%s: the apply text holds a secret" % iid)
    mdir = os.path.join(dream_io.projects_dir(), project, "memory")
    slug = item.get("newId") if SLUG.match(str(item.get("newId") or "")) else dream_learn.slugify(rule)
    path = os.path.join(mdir, slug + ".md")
    if os.path.exists(path) or path in plan.files:
        plan.skipped.append({"id": iid, "reason": "the memory file %s exists already" % slug})
        return None
    desc = dream_learn.memory_description(rule)
    plan.files[path] = dream_learn.render_memory(slug, desc, rule, why, how)
    plan.index_text(mdir)
    plan.index[mdir][1] = dream_learn.append_index(plan.index[mdir][1], dream_learn.index_line(slug, desc))
    return slug


def plan_ratchet(plan, item):
    iid = item["id"]
    repo = str(item.get("repo") or "")
    if not os.path.isabs(repo) or not os.path.isdir(os.path.join(repo, ".claude", "ratchet")):
        raise RsError("%s: %r is not a repo with ratchet state" % (iid, repo))
    if plan.known is not None and repo not in plan.known["repos"]:
        raise RsError("%s: repo %s has no ratchet evidence in this harvest" % (iid, repo))
    text, eid = apply_learnings(plan.learnings_text(repo), item, plan.bid)
    plan.learn[repo][1] = text
    return eid


PLANNERS = {"global": plan_global, "project": plan_project, "ratchet": plan_ratchet}


def main(argv):
    try:
        rest, many = take_all(argv, ("--accept", "--reject"))
        pos, opts = common.parse_args(rest, value_flags=("--nonce", "--reason"))
    except RsError as e:
        return common.emit("dream apply", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 1:
            raise RsError("usage: dream apply <bundle> --accept <ids> --reject <ids> [--reason <text>]")
        home = dream_io.home_dir()
        bid = dream_io.check_bundle(pos[0])
        bdir = dream_io.bundle_dir(bid)
        review = os.path.join(bdir, "review.json")
        if os.path.isfile(review):
            raise RsError("dream %s is reviewed already" % bid)
        proposal = common.read_json(os.path.join(bdir, "proposal.json"), default=None)
        if not isinstance(proposal, dict) or not isinstance(proposal.get("items"), list):
            raise RsError("no proposal.json in dream %s: run dream curate first" % bid)
        items = [it for it in proposal["items"] if isinstance(it, dict) and it.get("id")]
        by_id = dict((it["id"], it) for it in items)
        accept, reject = decide(many, by_id)

        # The harvest says which projects and repos this dream saw. A proposal may not name another one.
        harvest = common.read_json(os.path.join(bdir, "harvest.json"), default=None)
        known = None
        if isinstance(harvest, dict):
            known = {"projects": set(harvest.get("projects") or {}), "repos": set(harvest.get("ratchet") or {})}
        plan = Plan(bid, known)
        pins = {}
        for it in items:
            if it["id"] in accept and it.get("target") == "ratchet" and it.get("repo") not in pins:
                pins[it.get("repo")] = state_pins(str(it.get("repo")))
        done = []
        for it in items:
            if it["id"] not in accept:
                continue
            planner = PLANNERS.get(it.get("target"))
            if planner is None:
                raise RsError("%s: unknown target %r" % (it["id"], it.get("target")))
            got = planner(plan, it)
            if got is not None:
                done.append({"id": it["id"], "op": str(it["op"]).upper(), "target": it["target"], "entry": got})
        # Nothing is written before every item passed its checks, so a bad item changes nothing.
        plan.commit()

        reason = clean(opts.get("--reason") or "") or "no reason given"
        lines = [json.dumps({"date": dream_io.utc_date(), "bundle": bid, "op": str(by_id[i].get("op") or "").upper(),
                             "target": by_id[i].get("target"), "entry": by_id[i].get("entry"),
                             "rule": clean(by_id[i].get("rule") or ""), "reason": reason},
                            ensure_ascii=False, separators=(",", ":")) + "\n" for i in reject]
        if lines:
            common.append_text(dream_io.rejected_path(), "".join(lines))

        pinned, stale, problem = [], [], None
        for repo, repo_pins in pins.items():
            if plan.learn.get(repo) and plan.learn[repo][0] != plan.learn[repo][1]:
                p, s, prob = relock(repo, bdir, repo_pins)
                pinned += p
                stale += s
                problem = problem or prob
        # The review file comes before any error: the files changed, so a second apply must not run.
        common.write_json(review, {
            "bundle": bid, "reviewed": common.now_iso(), "reason": reason if reject else None,
            "accepted": done, "rejected": reject, "skipped": plan.skipped, "relocked": pinned, "stalePins": stale})
        dream_io.refresh_pending()
        if problem:
            raise RsError("applied, but %s; run RS lock on it, with learnings.md in a list file" % problem)

        summary = "accepted %d, rejected %d" % (len(done), len(reject))
        if done:
            summary += " (%s)" % ", ".join("%s %s" % (d["op"], d["entry"]) for d in done)
        if plan.skipped:
            summary += "; skipped %d (already there)" % len(plan.skipped)
        if stale:
            summary += "; %d stale pin left alone" % len(stale)
        # RS learnings reads entries only. Once one exists, bullets outside entries (version 1) stop reaching agents.
        warnings = []
        for repo, (before, text) in plan.learn.items():
            _, entries, bullets = dream_learn.parse(text)
            if entries and bullets:
                warnings.append("%d bullet(s) of learnings.md sit outside any entry, and RS learnings ignores them"
                                % len(bullets))
        return common.emit("dream apply", "pass", summary, evidence=review, nonce=nonce, root=home,
                           extra={"bundle": bid, "accepted": done, "rejected": reject, "skipped": plan.skipped,
                                  "relocked": len(pinned), "stalePins": stale, "warnings": warnings})

    return common.run_guarded("dream apply", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
