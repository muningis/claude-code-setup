"""trace <slug> [<cp>]: requirement IDs against plan rows and test names."""
from __future__ import annotations

import os
import re
import sys

import common
from common import RsError

# docs.md: `- **FR-001** (test): When ...`
REQ_LINE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+\*\*([A-Z]{2,}-\d+)\*\*\s*\(([A-Za-z]+)\)")
MAX_SCAN = 1000000
# plan header: `slug: a · created: … · change: docs/changes/0001-a-and-b (…)`
CHANGE_KEY = re.compile(r"(?:^|·)\s*change:\s*([^\s·(]+)")


def header_change(root, base, slug):
    """The folder named by `change:` in the plan header, as a path or a bare folder name."""
    path = common.plan_path(root, slug)
    if not os.path.isfile(path):
        return None
    for line in common.read_text(path).splitlines():
        if line.lstrip().startswith("|"):
            break
        m = CHANGE_KEY.search(line)
        if m:
            ref = m.group(1).rstrip("/")
            full = os.path.normpath(os.path.join(root if "/" in ref else base, ref))
            if full.startswith(os.path.normpath(root) + os.sep) and os.path.isdir(full):
                return full
    return None


def change_dirs(root, cfg, slug):
    """The plan header's `change:` folder, plus each docs/changes/NNNN-<slug>/ folder."""
    base = os.path.join(root, cfg["docs"].get("root") or "docs", "changes")
    named = header_change(root, base, slug)
    found = [named] if named else []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            full = os.path.join(base, name)
            if os.path.isdir(full) and (name == slug or name.endswith("-" + slug)) and full != named:
                found.append(full)
    return found


def load_requirements(root, cfg, slug):
    """{id: {"kind", "file"}} from the change spec and design log. Empty when there are no docs."""
    reqs = {}
    for d in change_dirs(root, cfg, slug):
        for fname in ("spec.md", "design-log.md"):
            path = os.path.join(d, fname)
            if not os.path.isfile(path):
                continue
            for line in common.read_text(path).splitlines():
                m = REQ_LINE.match(line)
                if m and m.group(1) not in reqs:
                    reqs[m.group(1)] = {"kind": m.group(2).lower(), "file": common.rel(root, path)}
    return reqs


def scan_lines(root, files):
    """The lines of files that cite a requirement ID, as (path, trimmed line)."""
    hits = []
    for f in files:
        path = os.path.join(root, f)
        try:
            if os.path.getsize(path) > MAX_SCAN:
                continue
        except OSError:
            continue
        for line in common.read_text(path).splitlines():
            if common.REQ_ID_RE.search(line):
                hits.append((f, line.strip()[:160]))
    return hits


def check_row(docs, row, names, test_text):
    """{"missing", "unknown"} for one row. A requirement without docs counts as kind test."""
    reqs = row["reqs"]
    need = [rid for rid in reqs if docs.get(rid, {}).get("kind", "test") == "test"]
    missing = [rid for rid in need
               if not any(common.has_id(n, rid) for n in names) or not common.has_id(test_text, rid)]
    cited = set()
    for n in names:
        cited.update(common.REQ_ID_RE.findall(n))
    return {"missing": missing, "unknown": sorted(cited - set(reqs))}


def repo_tests(root, cfg):
    rc, out, _ = common.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=root)
    return [f for f in out.split("\0") if f and common.is_test(cfg, f)]


def row_test_files(root, cfg, slug, row):
    """The checkpoint's pinned tests, else its tests changed since base, else every test."""
    pinned = [p for _, p in common.read_lock(root, ".claude/ratchet/evidence/%s/%s" % (slug, row["id"]))]
    if pinned:
        return pinned
    base = common.resolve_base(root, slug, row)
    if base:
        try:
            return [p for s, p in common.diff_status(root, base) if s != "D" and common.is_test(cfg, p)]
        except RsError:
            pass
    return repo_tests(root, cfg)


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("trace", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if not pos or len(pos) > 2:
            raise RsError("usage: trace <slug> [<cp>]")
        slug = pos[0]
        cp = pos[1] if len(pos) > 1 else None
        root = common.repo_root()
        cfg = common.load_config(root, required=False)
        plan = common.load_plan(root, slug)
        docs = load_requirements(root, cfg, slug)
        if cp:
            rows = [common.pick_row(plan, cp)]
        else:
            rows = [r for r in plan["rows"] if r["status"] != "superseded"]

        report = {}
        missing = []
        unknown = []
        all_tests = None
        for row in rows:
            if cp:
                files = row_test_files(root, cfg, slug, row)
            else:
                if all_tests is None:
                    all_tests = repo_tests(root, cfg)
                files = all_tests
            names = [text for _, text in scan_lines(root, files)]
            res = check_row(docs, row, names, "\n".join(names))
            report[row["id"]] = {"reqs": row["reqs"], "cases": len(names),
                                 "missing": res["missing"], "unknown": res["unknown"]}
            prefix = "" if cp else row["id"] + ":"
            missing.extend(prefix + rid for rid in res["missing"])
            unknown.extend(prefix + rid for rid in res["unknown"])

        cited = set()
        for r in plan["rows"]:
            cited.update(r["reqs"])
        uncited = sorted(set(docs) - cited)
        if cp:
            ev = os.path.join(common.ev_dir(root, slug, cp), "trace.json")
        else:
            ev = os.path.join(common.r_dir(root), "evidence", slug, "trace.json")
        common.write_json(ev, {"slug": slug, "cp": cp, "requirements": docs, "rows": report, "uncited": uncited})
        verdict = "fail" if missing else "pass"
        summary = "missing: %s" % ", ".join(missing) if missing else "every requirement has a case"
        return common.emit("trace", verdict, summary, evidence=ev, nonce=nonce, root=root,
                           extra={"missing": missing, "unknown": unknown, "uncited": uncited})

    return common.run_guarded("trace", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
