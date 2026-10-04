"""Paths and small file helpers that the dream commands share.

The dream is global: its state lives under the home folder, not in a repo.
RATCHET_HOME replaces ~, so that tests never touch the real home."""
from __future__ import annotations

import calendar
import datetime
import json
import os
import re
import shutil
import time

import common
from common import RsError

BUNDLE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:-\d+)?$")
ISO = "%Y-%m-%dT%H:%M:%SZ"
NIGHTLY_HOURS = 20
DEFAULTS = {"nightly": True, "maxItems": 3, "budgetUsd": 2, "sinceDays": 7, "exclude": [], "globalCap": 25}
_TS = re.compile(r"^(\d{4})-(\d\d)-(\d\d)[T ](\d\d):(\d\d):(\d\d)(?:\.(\d+))?(?:Z|[+-]00:?00)?$")
_DATE = re.compile(r"^(\d{4})-(\d\d)-(\d\d)$")


def home_dir():
    return os.environ.get("RATCHET_HOME") or os.path.expanduser("~")


def ratchet_home():
    return os.path.join(home_dir(), ".claude", "ratchet")


def projects_dir():
    return os.path.join(home_dir(), ".claude", "projects")


def rules_dir():
    """Where claude loads the user rules. The dream owns the files of this subfolder."""
    return os.path.join(home_dir(), ".claude", "rules", "dream")


def dreams_dir():
    return os.path.join(ratchet_home(), "dreams")


def retired_dir():
    return os.path.join(dreams_dir(), "retired")


def config_path():
    return os.path.join(ratchet_home(), "dream.json")


def pending_path():
    return os.path.join(dreams_dir(), "pending.json")


def harvest_hash_path(bid):
    """The SHA-256 of a bundle's harvest.json, written beside the bundle folder, not inside it."""
    return os.path.join(dreams_dir(), "%s.harvest.sha256" % check_bundle(bid))


def check_bundle(bid):
    if not isinstance(bid, str) or not BUNDLE_RE.match(bid):
        raise RsError("bad dream date: %r (expected YYYY-MM-DD)" % (bid,))
    return bid


def bundle_dir(bid):
    return os.path.join(dreams_dir(), check_bundle(bid))


def learnings_path(repo):
    """The learnings of one repo: the ratchet target of a dream writes here."""
    return os.path.join(common.r_dir(repo), "learnings.md")


def rejected_path():
    return os.path.join(dreams_dir(), "rejected.jsonl")


def utc_date():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")


def iso_of(epoch):
    return datetime.datetime.fromtimestamp(epoch, tz=datetime.timezone.utc).strftime(ISO)


def ms_key(epoch):
    """An epoch as the timestamp format of a session record (`2026-10-04T19:12:33.123Z`).

    Records share one fixed-width UTC format, so two of them compare as strings."""
    ms = int(round((epoch - int(epoch)) * 1000))
    if ms >= 1000:
        epoch, ms = epoch + 1, 0
    return datetime.datetime.fromtimestamp(int(epoch), tz=datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") \
        + "%03dZ" % ms


def epoch_of(text):
    """Epoch seconds of an ISO time, with or without milliseconds. None when the text is no time."""
    m = _TS.match(str(text).strip())
    if not m:
        return None
    y, mo, d, h, mi, s = (int(m.group(i)) for i in range(1, 7))
    try:
        base = calendar.timegm((y, mo, d, h, mi, s, 0, 0, 0))
    except (ValueError, OverflowError):
        return None
    return base + (float("0." + m.group(7)) if m.group(7) else 0.0)


def parse_since(text, now):
    """Epoch seconds for `7d`, `36h`, a date, or an ISO time. Raises RsError for anything else."""
    t = str(text).strip()
    m = re.fullmatch(r"(\d+)\s*([dh])", t, re.I)
    if m:
        return now - int(m.group(1)) * (86400 if m.group(2).lower() == "d" else 3600)
    d = _DATE.match(t)
    if d:
        t = "%s-%s-%sT00:00:00Z" % d.groups()
    got = epoch_of(t)
    if got is None:
        raise RsError("bad --since %r: use 7d, 36h, a date, or an ISO time" % text)
    return got


def bundle_ids():
    d = dreams_dir()
    if not os.path.isdir(d):
        return []
    return sorted(n for n in os.listdir(d) if BUNDLE_RE.match(n) and os.path.isdir(os.path.join(d, n)))


def pending_bundles():
    """Bundles with a proposal that no review closed yet."""
    out = []
    for bid in bundle_ids():
        d = bundle_dir(bid)
        if os.path.isfile(os.path.join(d, "proposal.json")) and not os.path.isfile(os.path.join(d, "review.json")):
            out.append(bid)
    return out


def pending_items(bid):
    try:
        data = common.read_json(os.path.join(bundle_dir(bid), "proposal.json"), default=None)
    except RsError:
        return 0
    items = data.get("items") if isinstance(data, dict) else None
    return len(items) if isinstance(items, list) else 0


def refresh_pending():
    """Write pending.json from the folders, so that a mod can read it without a scan. Empty means no file."""
    bundles = [{"bundle": b, "items": pending_items(b)} for b in pending_bundles()]
    path = pending_path()
    if bundles:
        common.write_json(path, {"bundles": bundles})
    elif os.path.isfile(path):
        os.remove(path)
    return bundles


def last_path():
    return os.path.join(dreams_dir(), "last.json")


def read_last():
    try:
        data = common.read_json(last_path(), default=None)
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


def write_last(bid, epoch, items):
    """Record the end of a dream. The time never moves back: an older bundle must not re-open a newer window."""
    prev = last_epoch(read_last())
    if prev is not None and prev >= epoch:
        return
    common.write_json(last_path(), {"bundle": bid, "ts": iso_of(epoch), "epoch": epoch, "items": items})


def _num(value, default, low, whole):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    if whole:
        value = int(value)
    return value if value >= low else default


def load_config():
    """dream.json over the defaults. A wrong type falls back to the default for that key."""
    raw = common.read_json(config_path(), default=None)
    cfg = dict(DEFAULTS)
    cfg["exclude"] = []
    if raw is None:
        return cfg
    if not isinstance(raw, dict):
        raise RsError("dream.json must hold a JSON object")
    if isinstance(raw.get("nightly"), bool):
        cfg["nightly"] = raw["nightly"]
    cfg["maxItems"] = _num(raw.get("maxItems"), DEFAULTS["maxItems"], 0, True)
    cfg["budgetUsd"] = _num(raw.get("budgetUsd"), DEFAULTS["budgetUsd"], 0.01, False)
    cfg["sinceDays"] = _num(raw.get("sinceDays"), DEFAULTS["sinceDays"], 1, True)
    cfg["globalCap"] = _num(raw.get("globalCap"), DEFAULTS["globalCap"], 1, True)
    ex = raw.get("exclude")
    if isinstance(ex, list):
        cfg["exclude"] = [str(x) for x in ex if isinstance(x, str) and x]
    return cfg


def write_default_config():
    """Create dream.json with the defaults when it is missing. Returns True when it wrote the file."""
    path = config_path()
    if os.path.isfile(path):
        return False
    common.write_json(path, DEFAULTS)
    return True


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


def natkey(text):
    """Sort key where cp2 comes before cp10. The odd items of the split are the digit runs."""
    return [int(t) if i % 2 else t for i, t in enumerate(re.split(r"(\d+)", text))]


def hours_since(epoch):
    return (time.time() - epoch) / 3600.0
