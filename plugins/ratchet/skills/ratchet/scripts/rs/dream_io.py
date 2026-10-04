"""Paths and small file helpers that the dream commands share."""
from __future__ import annotations

import datetime
import json
import os
import re
import shutil

import common
from common import RsError

BUNDLE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-\d+)?$")
ISO = "%Y-%m-%dT%H:%M:%SZ"
NIGHTLY_HOURS = 20


def home_dir():
    """RATCHET_HOME replaces ~, so that tests never touch the real home."""
    return os.environ.get("RATCHET_HOME") or os.path.expanduser("~")


def ratchet_home():
    return os.path.join(home_dir(), ".claude", "ratchet")


def repos_path():
    return os.path.join(ratchet_home(), "repos.json")


def dreams_dir(root):
    return os.path.join(common.r_dir(root), "dreams")


def check_bundle(bid):
    if not isinstance(bid, str) or not BUNDLE_RE.match(bid):
        raise RsError("bad dream date: %r (expected YYYY-MM-DD)" % (bid,))
    return bid


def bundle_dir(root, bid):
    return os.path.join(dreams_dir(root), check_bundle(bid))


def learnings_path(root):
    return os.path.join(common.r_dir(root), "learnings.md")


def rejected_path(root):
    return os.path.join(dreams_dir(root), "rejected.jsonl")


def utc_date():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def iso_of(epoch):
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).strftime(ISO)


def epoch_of(text):
    try:
        t = datetime.datetime.strptime(str(text), ISO).replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return None
    return t.timestamp()


def bundle_ids(root):
    d = dreams_dir(root)
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d) if BUNDLE_RE.match(n) and os.path.isdir(os.path.join(d, n)))


def pending_bundles(root):
    """Bundles with a proposal that no review closed yet."""
    out = []
    for bid in bundle_ids(root):
        d = bundle_dir(root, bid)
        if os.path.isfile(os.path.join(d, "proposal.json")) and not os.path.isfile(os.path.join(d, "review.json")):
            out.append(bid)
    return out


def last_path(root):
    return os.path.join(dreams_dir(root), "last.json")


def read_last(root):
    try:
        data = common.read_json(last_path(root), default=None)
    except RsError:
        return None
    return data if isinstance(data, dict) else None


def last_epoch(last):
    """The time of the last dream as epoch seconds, or None."""
    if not last:
        return None
    val = last.get("epoch")
    if isinstance(val, (int, float)) and not isinstance(val, bool):
        return float(val)
    return epoch_of(last.get("ts"))


def write_last(root, bid, epoch, items):
    """Record the end of a dream. The time never moves back: an older bundle must not re-open a newer window."""
    prev = last_epoch(read_last(root))
    if prev is not None and prev >= epoch:
        return
    common.write_json(last_path(root), {"bundle": bid, "ts": iso_of(epoch), "epoch": epoch, "items": items})


def read_jsonl(path):
    """The JSON objects of a JSON Lines file. A broken line is skipped, not fatal."""
    out = []
    for line in common.read_text(path).splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def read_exact(path):
    """The text of a file with every byte kept: no newline translation, and odd bytes survive."""
    try:
        with open(path, "r", encoding="utf-8", errors="surrogateescape", newline="") as f:
            return f.read()
    except OSError:
        return ""


def write_exact(path, text):
    """Write text that read_exact returned. The file keeps its mode, and the swap is atomic."""
    tmp = "%s.tmp%d" % (path, os.getpid())
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(tmp, "w", encoding="utf-8", errors="surrogateescape", newline="") as f:
        f.write(text)
    if os.path.exists(path):
        shutil.copymode(path, tmp)
    os.replace(tmp, path)


def read_repos():
    data = common.read_json(repos_path(), default=None)
    items = data.get("repos") if isinstance(data, dict) else data
    return [str(p) for p in items if isinstance(p, str) and p] if isinstance(items, list) else []


def write_repos(repos):
    common.write_json(repos_path(), {"version": 1, "repos": repos})


def natkey(text):
    """Sort key where cp2 comes before cp10. The odd items of the split are the digit runs."""
    return [int(t) if i % 2 else t for i, t in enumerate(re.split(r"(\d+)", text))]
