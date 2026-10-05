"""Context, result and helpers shared by the gate modules."""
from __future__ import annotations

import os
import re

import cmd_size
import common
from common import RsError

EVIDENCE_CAP = 400000  # bytes of one command's output kept in an evidence file


class Ctx(object):
    def __init__(self, root, cfg, slug, plan, row, state, rnd, nonce, gate):
        self.root = root
        self.cfg = cfg
        self.slug = slug
        self.plan = plan
        self.row = row
        self.cp = row["id"]
        self.state = state
        self.round = rnd
        self.nonce = nonce
        self.gate = gate
        self.ev = common.ev_dir(root, slug, row["id"])
        self._base = None
        self._changed = None
        self.skip_arch = False
        self.verdict_b64 = None  # b2 only: the visual agent's verdict, for when it wrote no file

    def evp(self, name):
        return os.path.join(self.ev, name)

    def ev_rel(self):
        return ".claude/ratchet/evidence/%s/%s" % (self.slug, self.cp)

    def base(self):
        """The base tree. A gate that diffs against it stops with an error when it is missing."""
        if self._base is None:
            self._base = common.resolve_base(self.root, self.slug, self.row)
        if not self._base:
            raise RsError("no base snapshot for %s/%s: run snap %s/%s/base first"
                          % (self.slug, self.cp, self.slug, self.cp))
        return self._base

    def changed(self):
        """[(status, path)] changed since base. Taken once per gate."""
        if self._changed is None:
            self._changed = common.diff_status(self.root, self.base())
        return self._changed

    def changed_paths(self):
        return [p for _, p in self.changed()]

    def has_visual(self):
        return bool(self.cfg.get("visual")) and self.row["target"] != "-"

    def state_dir(self):
        """The pins of the state files, as a repo-relative path."""
        return ".claude/ratchet/evidence/%s/_state" % self.slug


class Result(object):
    def __init__(self, verdict, summary, evidence=None, extra=None):
        self.verdict = verdict
        self.summary = summary
        self.evidence = evidence
        self.extra = extra or {}
        self.evidence_list = None  # b3-prep only: its `evidence` field is an array
        self.advance = None        # stage to move to when the verdict is pass
        self.row_status = None     # plan row status to set when the verdict is pass
        self.round_key = None      # key of STATE.rounds that this run counts toward
        self.open = None           # new STATE.open
        self.state = None          # more STATE fields to set
        self.blocking = 0
        self.advisory = 0
        self.prod = 0
        self.tests = 0


def role_of(fid):
    m = re.search(r"-([ABV])\d+-\d+$", fid)
    return m.group(1) if m else None


def merge_open(old, roles, blocking, advisory):
    """New STATE.open. A gate replaces only the blocking IDs of its own reviewers; advisory IDs accumulate.

    An ID with no role (a malformed one) belongs to no gate and no later round could close it, so it goes."""
    keep = [f for f in old["blocking"] if role_of(f) and role_of(f) not in roles]
    adv = list(old["advisory"])
    for f in advisory:
        if f not in adv:
            adv.append(f)
    return {"blocking": keep + [f for f in blocking if f not in keep], "advisory": adv}


def applicable_checks(ctx, kind, tag=None):
    """Checks of this kind (and gate tag) whose `when` globs match a changed file. No globs: always."""
    changed = None
    out = []
    for c in ctx.cfg["checks"]:
        if c["kind"] != kind:
            continue
        if tag is not None and tag not in c["gate"]:
            continue
        if c["when"]:
            if changed is None:
                changed = ctx.changed_paths()
            if not any(common.glob_match(g, p) for g in c["when"] for p in changed):
                continue
        out.append(c)
    return out


def run_checks(ctx, checks):
    """Run command checks in order, all of them. Returns [{id, ok, ms, rc, run, text}]."""
    os.makedirs(ctx.ev, exist_ok=True)
    tmp = ctx.evp(".rs-run.out")
    default_timeout = common.to_int(ctx.cfg["behavior"].get("timeout"), 900)
    results = []
    for c in checks:
        if not c.get("run"):
            raise RsError("check %s has no run command" % c["id"])
        rc, ms = common.run_command(c["run"], ctx.root, common.to_int(c.get("timeout"), default_timeout), tmp)
        results.append({"id": c["id"], "ok": rc == 0, "ms": ms, "rc": rc, "run": c["run"],
                        "text": common.read_tail(tmp, EVIDENCE_CAP)})
    if os.path.exists(tmp):
        os.remove(tmp)
    return results


def render_results(results):
    parts = []
    for r in results:
        parts.append("=== %s: exit %d, %d ms ===\n$ %s\n%s\n"
                     % (r["id"], r["rc"], r["ms"], r["run"], r["text"].rstrip("\n")))
    return "\n".join(parts)


def size_info(ctx):
    """({"prod", "est", "ratio"}, test lines). The estimate is advisory: the row's `est`, else size.prodLines."""
    est = ctx.row["est"] or common.to_int(ctx.cfg["size"].get("prodLines"), None)
    prod, tests, _ = cmd_size.prod_size(ctx.root, ctx.cfg, ctx.base())
    ratio = round(prod / float(est), 2) if est else None
    return {"prod": prod, "est": est, "ratio": ratio}, tests


WAIVE_RE = re.compile(r"waive\(([^)]*)\)")
RANGE_RE = re.compile(r"(\D*?)(\d+)\s*[–-]\s*(\D*?)(\d+)")


def plan_notes(root, slug):
    """The lines after the `## Notes` heading, up to the end of the file: `RS row --note` appends at the end."""
    out = []
    inside = False
    for line in common.read_text(common.plan_path(root, slug)).splitlines():
        if line.strip() == "## Notes":
            inside = True
        elif inside and line.strip():
            out.append(line.strip())
    return out


def waive_covers(spec, cp):
    """True when the list in `waive(<spec>)` names cp. An item can be a range, as in `cp5–cp8`."""
    mine = re.fullmatch(r"(\D*?)(\d+)", cp)
    for item in re.split(r"[,\s]+", spec.strip()):
        rng = RANGE_RE.fullmatch(item)
        if item == cp or (rng and mine and rng.group(1) == mine.group(1) == rng.group(3)
                          and int(rng.group(2)) <= int(mine.group(2)) <= int(rng.group(4))):
            return True
    return False


def row_notes(root, slug, cp):
    """The notes about this row: lines that start with its ID, and waivers that name it."""
    out = []
    for line in plan_notes(root, slug):
        waiver = WAIVE_RE.search(line)
        if waiver:
            if waive_covers(waiver.group(1), cp):
                out.append(line)
        elif re.match(r"(?:[-*]\s*)?%s(?![A-Za-z0-9-])" % re.escape(cp), line):
            out.append(line)
    return out


def regression_waivers(root, slug, cp):
    """The targets that the human let regress: `waive(<cp>): regression <target>`."""
    targets = set()
    for line in plan_notes(root, slug):
        m = re.search(r"waive\(([^)]*)\)\s*:\s*regression\s+([a-z0-9-]+)", line)
        if m and waive_covers(m.group(1), cp):
            targets.add(m.group(2))
    return targets
