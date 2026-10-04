"""prove <slug> <cp> <finding-id>: run a finding's proof and say whether it reproduces."""
from __future__ import annotations

import os
import re
import shutil
import sys

import common
from common import RsError

FINDING_ID = re.compile(r"^(?P<cp>.+)-(?P<role>[ABV])(?P<round>\d+)-(?P<n>\d+)$")


def safe_name(fid):
    return re.sub(r"[^A-Za-z0-9._-]", "_", fid)


def break_files(ev, fid):
    """The reviewer files that can hold the finding: its own round first, then every other round."""
    names = []
    m = FINDING_ID.match(fid)
    if m and m.group("role") == "B":
        names += ["3-break-r%s.json" % m.group("round"), "3-review-break-r%s.json" % m.group("round")]
    if os.path.isdir(ev):
        for name in sorted(os.listdir(ev)):
            if re.match(r"^3-(?:review-)?break-r\d+\.json$", name) and name not in names:
                names.append(name)
    return [os.path.join(ev, n) for n in names]


def find_finding(ev, fid):
    for path in break_files(ev, fid):
        data = common.read_json(path, default=None)
        if isinstance(data, dict) and isinstance(data.get("findings"), list):
            for f in data["findings"]:
                if isinstance(f, dict) and str(f.get("id")) == fid:
                    return f
    return None


def proof_of(finding):
    """(cmd, pattern) of a version 2 finding. A version 1 proof is free text, so it gives (None, None)."""
    p = finding.get("proof") if isinstance(finding, dict) else None
    if not isinstance(p, dict):
        return None, None
    cmd = p.get("cmd")
    pat = p.get("pattern")
    return (cmd if isinstance(cmd, str) and cmd.strip() else None,
            pat if isinstance(pat, str) and pat != "" else None)


def matches(pattern, text):
    """A reviewer writes the pattern as a regex or as plain text; accept both."""
    try:
        if re.search(pattern, text):
            return True
    except re.error:
        pass
    return pattern in text


def restore_tree(root, tree, changed):
    """Put each changed path back as it was in `tree`. No stash and no reset: both touch the index."""
    back = []
    for status, path in changed:
        abs_path = os.path.join(root, path)
        if status == "A":
            if os.path.lexists(abs_path) and not os.path.isdir(abs_path):
                os.remove(abs_path)
            cur = os.path.dirname(abs_path)
            while cur.startswith(root + os.sep) and os.path.isdir(cur) and not os.listdir(cur):
                os.rmdir(cur)
                cur = os.path.dirname(cur)
        else:
            back.append(path)
    for i in range(0, len(back), 100):
        chunk = back[i:i + 100]
        rc, _, _ = common.run(["git", "--literal-pathspecs", "restore", "--source=" + tree,
                               "--worktree", "--"] + chunk, cwd=root)
        if rc == 0:
            continue
        for path in chunk:  # old git without `restore`: copy the blobs back
            rc2, blob = common.run_raw(["git", "cat-file", "blob", "%s:%s" % (tree, path)], cwd=root)
            if rc2 == 0:
                abs_path = os.path.join(root, path)
                os.makedirs(os.path.dirname(abs_path), exist_ok=True)
                with open(abs_path, "wb") as f:
                    f.write(blob)


def backup_changed(root, dest, changed):
    """Copy each changed file, as it is now, to dest. A person may have edited it while the proof ran."""
    for status, path in changed:
        src = os.path.join(root, path)
        if status != "D" and os.path.isfile(src):
            copy = os.path.join(dest, *path.split("/"))
            os.makedirs(os.path.dirname(copy), exist_ok=True)
            shutil.copyfile(src, copy)


def run_proof(root, cfg, slug, cp, fid, cmd, pattern):
    """Run one proof from the repo root. Returns a dict with result, exit, ms, out and changed."""
    out_path = os.path.join(common.ev_dir(root, slug, cp), "proofs", "%s.out" % safe_name(fid))
    timeout = common.to_int(cfg["review"].get("proofTimeout"), 120)
    before = common.snap(root)
    rc, ms = common.run_command(cmd, root, timeout, out_path)
    changed = common.diff_status(root, before)
    res = {"exit": rc, "ms": ms, "out": out_path, "changed": [p for _, p in changed],
           "timeout": rc == 124}
    if changed:
        res["backup"] = os.path.join(os.path.dirname(out_path), "%s.backup" % safe_name(fid))
        backup_changed(root, res["backup"], changed)
        restore_tree(root, before, changed)
        res["result"] = "invalid"
        res["restored"] = not common.diff_status(root, before)
        return res
    text = common.strip_ansi(common.read_text(out_path))
    if rc == 124 or not pattern:
        res["result"] = "unproven"
    elif rc != 0 and matches(pattern, text):
        res["result"] = "reproduced"
    else:
        res["result"] = "unproven"
    return res


def main(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce", "--cmd", "--pattern"))
    except RsError as e:
        return common.emit("prove", "error", str(e), harness_error=str(e))
    nonce = opts.get("--nonce")

    def go():
        if len(pos) != 3:
            raise RsError("usage: prove <slug> <cp> <finding-id>")
        slug = common.check_name("slug", pos[0])
        cp = common.check_name("cp", pos[1])
        fid = common.check_name("finding id", pos[2])
        root = common.repo_root()
        cfg = common.load_config(root, required=False)
        cmd, pattern = opts.get("--cmd"), opts.get("--pattern")
        if not cmd:
            finding = find_finding(common.ev_dir(root, slug, cp), fid)
            if finding is None:
                raise RsError("no break finding %s under %s/%s" % (fid, slug, cp))
            cmd, pattern = proof_of(finding)
        if not cmd:
            return common.emit("prove", "fail", "%s: unproven, the finding has no proof command" % fid,
                               nonce=nonce, root=root,
                               extra={"id": fid, "result": "unproven", "exit": None, "ms": 0})
        res = run_proof(root, cfg, slug, cp, fid, cmd, pattern)
        extra = {"id": fid, "result": res["result"], "exit": res["exit"], "ms": res["ms"]}
        if res["result"] == "invalid":
            extra["changed"] = res["changed"]
            extra["restored"] = res["restored"]
            extra["backup"] = common.rel(root, res["backup"])
        verdict = "pass" if res["result"] == "reproduced" else "fail"
        return common.emit("prove", verdict, "%s: %s" % (fid, res["result"]), evidence=res["out"],
                           nonce=nonce, root=root, extra=extra)

    return common.run_guarded("prove", nonce, go)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
