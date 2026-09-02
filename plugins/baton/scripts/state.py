#!/usr/bin/env python3
"""Collect the machine-checkable half of a handover: where the work physically
stands right now. Finds the git repos in scope and emits, per repo, the branch,
upstream divergence, HEAD, uncommitted files, stashes, unpushed commits and the
last few commits — plus, when a root holds no repo at all, the loose files that
an idea/exploration workspace is actually made of.

The model writes the handover; this script only gathers facts, so the "State"
section is observed rather than remembered. Remote URLs are stripped of any
embedded credentials before they are printed.

Usage:
  state.py [ROOT ...] [--depth N] [--commits N] [--files N] [--no-parent-scan]

Scope:
  no ROOT      auto: if the cwd is inside a git repo, report that repo (and count
               sibling repos next to it, so the caller can tell a single-repo
               handover from a workspace one); otherwise scan the cwd for repos,
               and fall back to listing loose material if there are none.
  ROOT ...     scan each ROOT: a root that is itself a repo is reported as one,
               a root that isn't is searched (up to --depth) for repos below it.

Tuning:
  --depth N          how deep to search a non-repo root for repos (default 3).
  --commits N        recent commits listed per repo (default 5).
  --files N          cap on changed/untracked files listed per repo (default 40).
  --no-parent-scan   skip the sibling-repo count in auto scope.

Output: one JSON object on stdout. Anything that could not be read becomes a
`notes` entry rather than a crash — a partial state is still worth handing over.
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

SKIP_DIRS = {
    "node_modules", "vendor", "target", "dist", "build", "out", ".venv",
    "venv", "__pycache__", ".next", ".turbo", ".cache", "Library",
}
LOOSE_SUFFIXES = {".md", ".markdown", ".txt", ".org", ".canvas"}
MAX_LOOSE = 30
UNIT = "\x1f"  # %x1f field separator inside git --format


def run(args, cwd=None):
    """Run a git command, returning (ok, stdout). Never raises."""
    try:
        p = subprocess.run(
            args, cwd=cwd, capture_output=True, text=True, timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
    if p.returncode != 0:
        return False, (p.stderr or p.stdout).strip()
    return True, p.stdout


def git(repo, *args):
    return run(["git", "-C", str(repo), *args])


def git_out(repo, *args, default=""):
    ok, out = git(repo, *args)
    return out.strip() if ok else default


def sanitize_url(url):
    """Drop any credentials embedded in a remote URL — a handover gets pasted,
    committed and read by other people; a token in it is a leaked token."""
    if not url:
        return url
    return re.sub(r"(?<=://)[^/@\s]+@", "", url)


def toplevel(path):
    ok, out = run(["git", "-C", str(path), "rev-parse", "--show-toplevel"])
    if not ok:
        return None
    try:
        return Path(out.strip()).resolve()
    except OSError:
        return None


def find_repos(root, depth):
    """Repos at or below root. A repo is not descended into — a submodule or a
    nested clone is somebody else's checkout, not part of this handover."""
    root = Path(root)
    if (root / ".git").exists():
        top = toplevel(root)
        return [top] if top else []

    found, stack = [], [(root, 0)]
    while stack:
        d, level = stack.pop()
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        if (d / ".git").exists():
            top = toplevel(d)
            if top:
                found.append(top)
            continue
        if level >= depth:
            continue
        for e in entries:
            if not e.is_dir() or e.is_symlink():
                continue
            if e.name in SKIP_DIRS or (e.name.startswith(".") and e.name != ".git"):
                continue
            stack.append((e, level + 1))
    return found


def parse_status(repo, cap):
    """Parse `git status --porcelain=v1 -z` into staged / unstaged / untracked."""
    ok, out = git(repo, "status", "--porcelain=v1", "-z", "--untracked-files=normal")
    if not ok:
        return None, out

    staged, unstaged, untracked = [], [], []
    fields = out.split("\0")
    i = 0
    while i < len(fields):
        entry = fields[i]
        i += 1
        if len(entry) < 4:
            continue
        x, y, path = entry[0], entry[1], entry[3:]
        if x in "RC":  # rename/copy: the source path is the next NUL field
            src = fields[i] if i < len(fields) else ""
            i += 1
            path = f"{src} -> {path}" if src else path
        if x == "?" and y == "?":
            untracked.append(path)
            continue
        if x != " ":
            staged.append(path)
        if y != " ":
            unstaged.append(path)

    def clip(xs):
        return {"count": len(xs), "files": sorted(xs)[:cap], "truncated": len(xs) > cap}

    return {"staged": clip(staged), "unstaged": clip(unstaged),
            "untracked": clip(untracked)}, None


def commit_list(repo, revs, limit):
    ok, out = git(repo, "log", f"-n{limit}",
                  f"--format=%h{UNIT}%aI{UNIT}%an{UNIT}%s", *revs)
    if not ok:
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split(UNIT)
        if len(parts) == 4:
            commits.append({"sha": parts[0], "date": parts[1],
                            "author": parts[2], "subject": parts[3]})
    return commits


def default_branch(repo):
    head = git_out(repo, "symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    if head.startswith("origin/"):
        return head[len("origin/"):]
    for cand in ("main", "master", "develop"):
        ok, _ = git(repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{cand}")
        if ok:
            return cand
    return None


def describe_repo(path, commits, files):
    repo = {"path": str(path), "name": path.name}

    has_head, _ = git(repo["path"], "rev-parse", "--verify", "--quiet", "HEAD")
    repo["hasCommits"] = has_head

    branch = git_out(path, "symbolic-ref", "--quiet", "--short", "HEAD")
    repo["branch"] = branch or None
    repo["detached"] = has_head and not branch
    repo["defaultBranch"] = default_branch(path)

    if has_head:
        line = git_out(path, "log", "-1", f"--format=%h{UNIT}%H{UNIT}%aI{UNIT}%an{UNIT}%s")
        parts = line.split(UNIT)
        if len(parts) == 5:
            repo["head"] = {"sha": parts[0], "fullSha": parts[1], "date": parts[2],
                            "author": parts[3], "subject": parts[4]}
        repo["recentCommits"] = commit_list(path, [], commits)
    else:
        repo["head"] = None
        repo["recentCommits"] = []

    upstream = git_out(path, "rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    repo["upstream"] = upstream or None
    if upstream:
        counts = git_out(path, "rev-list", "--left-right", "--count", f"{upstream}...HEAD")
        nums = counts.split()
        if len(nums) == 2:
            repo["behind"], repo["ahead"] = int(nums[0]), int(nums[1])
        repo["unpushedCommits"] = commit_list(path, [f"{upstream}..HEAD"], commits)
    else:
        repo["unpushedCommits"] = []

    status, err = parse_status(path, files)
    if status is None:
        repo["statusError"] = err
        repo["dirty"] = None
    else:
        repo.update(status)
        repo["dirty"] = any(status[k]["count"] for k in ("staged", "unstaged", "untracked"))

    stash = git_out(path, "stash", "list", "--format=%gd")
    repo["stashes"] = len(stash.splitlines()) if stash else 0
    repo["remote"] = sanitize_url(git_out(path, "remote", "get-url", "origin")) or None

    ok, out = git(path, "rev-parse", "--git-path", "MERGE_HEAD")
    if ok and Path(path, out.strip()).exists():
        repo["midMerge"] = True

    return repo


def loose_material(root):
    """What an exploration workspace is made of when there is no repo: the notes
    and folders at the top, newest first — enough to point the next session at."""
    root = Path(root)
    items = []
    try:
        entries = list(root.iterdir())
    except OSError:
        return items
    for e in entries:
        if e.name.startswith("."):
            continue
        try:
            st = e.stat()
        except OSError:
            continue
        kind = "dir" if e.is_dir() else "file"
        if kind == "file" and e.suffix.lower() not in LOOSE_SUFFIXES:
            continue
        items.append({
            "path": str(e),
            "kind": kind,
            "modified": dt.datetime.fromtimestamp(st.st_mtime, dt.timezone.utc).isoformat(),
        })
    items.sort(key=lambda i: i["modified"], reverse=True)
    return items[:MAX_LOOSE]


def main():
    ap = argparse.ArgumentParser(add_help=True, description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("roots", nargs="*", help="roots to scan (default: the cwd)")
    ap.add_argument("--depth", type=int, default=3)
    ap.add_argument("--commits", type=int, default=5)
    ap.add_argument("--files", type=int, default=40)
    ap.add_argument("--no-parent-scan", action="store_true")
    args = ap.parse_args()

    now = dt.datetime.now(dt.timezone.utc)
    cwd = Path.cwd()
    notes = []
    auto = not args.roots

    roots, repo_paths = [], []
    if auto:
        top = toplevel(cwd)
        if top:
            roots = [top]
            repo_paths = [top]
        else:
            roots = [cwd]
            repo_paths = find_repos(cwd, args.depth)
    else:
        for r in args.roots:
            p = Path(r).expanduser()
            if not p.exists():
                notes.append(f"root not found, skipped: {p}")
                continue
            p = p.resolve()
            roots.append(p)
            repo_paths.extend(find_repos(p, args.depth))

    seen, unique = set(), []
    for p in repo_paths:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    unique.sort(key=lambda p: str(p))

    repos = []
    for p in unique:
        try:
            repos.append(describe_repo(p, args.commits, args.files))
        except Exception as e:  # a broken checkout must not sink the handover
            notes.append(f"could not read repo {p}: {e}")

    if len(repos) > 1:
        scope = "workspace"
    elif len(repos) == 1:
        scope = "repo"
    else:
        scope = "explore"

    out = {
        "generatedAt": now.isoformat(),
        "cwd": str(cwd),
        "roots": [str(r) for r in roots],
        "suggestedScope": scope,
        "repoCount": len(repos),
        "repos": repos,
    }

    # In auto scope inside a repo, a single repo may still be one of many the
    # session touched — count the siblings so the caller can ask the right
    # question instead of assuming a single-repo handover.
    if auto and scope == "repo" and not args.no_parent_scan:
        parent = Path(out["repos"][0]["path"]).parent
        siblings = [p for p in find_repos(parent, 1) if str(p) != out["repos"][0]["path"]]
        out["parentDir"] = str(parent)
        out["siblingRepos"] = [Path(p).name for p in siblings][:MAX_LOOSE]
        out["siblingRepoCount"] = len(siblings)

    if scope == "explore":
        out["looseMaterial"] = [i for r in roots for i in loose_material(r)]

    if notes:
        out["notes"] = notes

    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    sys.exit(main())
