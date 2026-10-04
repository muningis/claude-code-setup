"""Shared helpers for the rs commands: paths, config, plan, STATE, LIVE, METRICS, output."""
from __future__ import annotations

import datetime
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
import traceback

STAGES = ["B0", "B1", "B2", "B3", "B4", "B5", "done"]
OPEN_STATUSES = ("todo", "red", "green", "blocked")
STAGE_BY_STATUS = {
    "todo": "B0",
    "red": "B1",
    "green": "B4",
    "approved": "done",
    "approved-unverified": "done",
    "superseded": "done",
    "blocked": "B0",
}
ENVELOPE = ("ok", "cmd", "nonce", "verdict", "summary", "evidence", "sha256")
MAX_STDOUT = 1000  # contracts.md: stdout is one object of 1 KB or less
EXIT_CODE = {"pass": 0, "fail": 1, "error": 2, "pending": 0}
REQ_ID_RE = re.compile(r"\b(?:FR|UB)-\d{3}\b")
NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
DEFAULT_TEST_GLOBS = [
    "**/*.test.*", "**/*.spec.*", "**/test/**", "**/tests/**", "**/__tests__/**",
    "**/test_*.py", "**/*_test.*", "**/*Test.kt", "**/*Tests.swift",
]


class RsError(Exception):
    """The harness cannot do what was asked: bad config, missing file, missing tool."""


# ---------------------------------------------------------------- basics

def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def to_int(value, default):
    if isinstance(value, bool):
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def run(args, cwd=None, input_text=None, timeout=None):
    """Run argv without a shell. Returns (rc, stdout, stderr) as text; rc 127 when the tool is missing."""
    kwargs = {"cwd": cwd, "stdout": subprocess.PIPE, "stderr": subprocess.PIPE, "timeout": timeout}
    if input_text is None:
        kwargs["stdin"] = subprocess.DEVNULL
    else:
        kwargs["input"] = input_text.encode("utf-8")
    try:
        p = subprocess.run(args, **kwargs)
    except FileNotFoundError:
        return 127, "", "not found: %s" % args[0]
    except subprocess.TimeoutExpired:
        return 124, "", "timeout"
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


def run_raw(args, cwd=None):
    """Like run, but stdout stays bytes: for blobs that are not text."""
    try:
        p = subprocess.run(args, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError:
        return 127, b""
    return p.returncode, p.stdout


def repo_root():
    env = os.environ.get("RS_ROOT")
    if env and os.path.isdir(env):
        return env
    rc, out, _ = run(["git", "rev-parse", "--show-toplevel"])
    if rc == 0 and out.strip():
        return out.strip()
    return os.getcwd()


def check_name(what, value):
    if not isinstance(value, str) or not NAME_RE.match(value):
        raise RsError("bad %s: %r" % (what, value))
    return value


def rel(root, path):
    if not os.path.isabs(path):
        return path.replace(os.sep, "/")
    return os.path.relpath(path, root).replace(os.sep, "/")


def r_dir(root):
    return os.path.join(root, ".claude", "ratchet")


def config_path(root):
    return os.path.join(r_dir(root), "config.json")


def plan_path(root, slug):
    return os.path.join(r_dir(root), "plans", slug + ".md")


def ev_dir(root, slug, cp):
    return os.path.join(r_dir(root), "evidence", slug, cp)


def state_path(root, slug, cp):
    return os.path.join(ev_dir(root, slug, cp), "state.json")


def jobs_dir(root, slug, cp):
    """Where a detached gate writes its result, its pid and its errors."""
    return os.path.join(ev_dir(root, slug, cp), ".jobs")


def live_path(root):
    return os.path.join(r_dir(root), "live.json")


def metrics_path(root):
    return os.path.join(r_dir(root), "metrics.jsonl")


def read_text(path, default=""):
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return default


def write_text(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = "%s.tmp%d" % (path, os.getpid())
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def append_text(path, text):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(text)


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default
    except (ValueError, OSError) as e:
        raise RsError("cannot read %s: %s" % (path, e))


def write_json(path, obj):
    write_text(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def read_tail(path, max_bytes):
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as f:
            prefix = ""
            if size > max_bytes:
                f.seek(size - max_bytes)
                prefix = "[... %d earlier bytes cut ...]\n" % (size - max_bytes)
            data = f.read()
    except OSError:
        return ""
    return prefix + data.decode("utf-8", "replace")


def tail_text(text, n):
    lines = text.splitlines()
    if len(lines) <= n:
        return "\n".join(lines)
    return "[... %d earlier lines cut ...]\n%s" % (len(lines) - n, "\n".join(lines[-n:]))


def strip_ansi(text):
    return ANSI_RE.sub("", text)


def fill_files(template, files):
    quoted = " ".join(shlex.quote(f) for f in files)
    if "{files}" in template:
        return template.replace("{files}", quoted)
    return template + " " + quoted


def has_id(text, rid):
    return re.search(r"(?<![A-Za-z0-9-])%s(?![A-Za-z0-9-])" % re.escape(rid), text) is not None


# ---------------------------------------------------------------- arguments

def parse_args(argv, value_flags=(), bool_flags=()):
    """Split argv into positionals and options. An unknown --flag is an error."""
    pos = []
    opts = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            pos.extend(argv[i + 1:])
            break
        if a in value_flags:
            if i + 1 >= len(argv):
                raise RsError("%s needs a value" % a)
            opts[a] = argv[i + 1]
            i += 2
            continue
        if a in bool_flags:
            opts[a] = True
            i += 1
            continue
        if a.startswith("--") and "=" in a and a.split("=", 1)[0] in value_flags:
            key, val = a.split("=", 1)
            opts[key] = val
            i += 1
            continue
        if a.startswith("--") and len(a) > 2:
            raise RsError("unknown option: %s" % a)
        pos.append(a)
        i += 1
    return pos, opts


# ---------------------------------------------------------------- output

def _size(obj):
    return len(json.dumps(obj, separators=(",", ":")).encode("utf-8"))


def _cut_lists(node, limit):
    """Cut every list under node to limit entries; a sibling <key>More keeps the true count."""
    if not isinstance(node, dict):
        return
    for key in list(node.keys()):
        val = node[key]
        if isinstance(val, list) and len(val) > limit:
            more = node.get(key + "More", 0) + len(val) - limit
            node[key] = val[:limit]
            node[key + "More"] = more
        elif isinstance(val, dict):
            _cut_lists(val, limit)


def _fit(obj):
    if _size(obj) <= MAX_STDOUT:
        return
    for key in ("summary", "harnessError"):
        val = obj.get(key)
        if isinstance(val, str) and len(val) > 160:
            obj[key] = val[:157] + "..."
    for limit in (20, 10, 5, 3, 1, 0):
        if _size(obj) <= MAX_STDOUT:
            return
        _cut_lists(obj, limit)
    if _size(obj) > MAX_STDOUT:
        obj["summary"] = str(obj.get("summary", ""))[:60]
    if _size(obj) > MAX_STDOUT:
        for key in list(obj.keys()):
            if key not in ENVELOPE and key != "harnessError":
                del obj[key]
                if _size(obj) <= MAX_STDOUT:
                    return


def emit(cmd, verdict, summary, evidence=None, nonce=None, root=None, extra=None,
         harness_error=None, evidence_list=None):
    """Print the one JSON object a gate command owes its caller. Returns the exit code."""
    obj = {"ok": verdict != "error", "cmd": cmd, "nonce": nonce, "verdict": verdict,
           "summary": summary, "evidence": None, "sha256": None}
    if evidence:
        base = root or repo_root()
        abs_path = evidence if os.path.isabs(evidence) else os.path.join(base, evidence)
        obj["evidence"] = rel(base, abs_path)
        if os.path.isfile(abs_path):
            obj["sha256"] = sha256_file(abs_path)
    for key, val in (extra or {}).items():
        if key not in ENVELOPE:
            obj[key] = val
    if evidence_list is not None:
        # contracts.md gives b3-prep an `evidence` array that shares its name with the envelope field.
        obj["evidence"] = evidence_list
    if harness_error:
        obj["harnessError"] = harness_error
    return print_result(obj)


def print_result(obj):
    """Print obj as the one JSON line of a command, cut to 1 KB. Returns the exit code of its verdict."""
    _fit(obj)
    sys.stdout.write(json.dumps(obj, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return EXIT_CODE.get(obj.get("verdict"), 2)


def run_guarded(cmd, nonce, fn):
    """Call fn(). A harness failure becomes an error object and exit code 2."""
    try:
        return fn()
    except RsError as e:
        return emit(cmd, "error", str(e), nonce=nonce, harness_error=str(e))
    except Exception as e:  # a bug must not end as a bare traceback with no JSON
        traceback.print_exc(file=sys.stderr)
        msg = "internal error: %s: %s" % (type(e).__name__, e)
        return emit(cmd, "error", msg, nonce=nonce, harness_error=msg)


# ---------------------------------------------------------------- config

def default_config():
    return {
        "version": 2,
        "behavior": {"one": "", "all": "", "timeout": 900, "failureKinds": {}},
        "checks": [],
        "tests": {"globs": list(DEFAULT_TEST_GLOBS), "perRequirement": 3, "perCheckpoint": 20},
        "size": {"prodLines": 400},
        "visual": None,
        "review": {"proofTimeout": 120, "archPaths": []},
        "caps": {"b1": 5, "b2": 3, "b3": 3},
        "autoAfter": 2,
        "models": {},
        "standing": {"commit": "ask", "afterLock": [], "notify": True},
        "docs": {"root": "docs", "ste": "lite"},
        "relay": True,
        "dream": {"nightly": False, "maxItems": 3, "budgetUsd": 2},
    }


_MERGED_KEYS = ("behavior", "tests", "size", "review", "caps", "standing", "docs", "dream")


def _normalize_check(check, n):
    c = dict(check)
    if not c.get("id"):
        c["id"] = "check-%d" % n
    c["id"] = str(c["id"])
    c["kind"] = str(c.get("kind") or "command")
    when = c.get("when")
    if isinstance(when, str):
        when = [when]
    c["when"] = [str(w) for w in when] if isinstance(when, list) else []
    gate = c.get("gate")
    if isinstance(gate, str):
        gate = [gate]
    if not isinstance(gate, list) or not gate:
        gate = ["b1", "verify"]
    c["gate"] = [str(g) for g in gate]
    return c


def normalize_config(raw):
    """Fill defaults and migrate a version 1 file to version 2 (see config.md, Migration)."""
    if not isinstance(raw, dict):
        raise RsError("config.json must hold a JSON object")
    cfg = default_config()
    for key, val in raw.items():
        if key in _MERGED_KEYS and isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        elif isinstance(val, list):
            cfg[key] = list(val)
        else:
            cfg[key] = val
    cfg["version"] = 2
    for key in _MERGED_KEYS:
        if not isinstance(cfg[key], dict):
            raise RsError("config: %s must be an object" % key)

    mr = raw.get("maxRounds")
    if "caps" not in raw and mr is not None:
        if isinstance(mr, dict):
            for k, v in mr.items():
                if to_int(v, None) is not None:
                    cfg["caps"][str(k).lower()] = to_int(v, 0)
        elif to_int(mr, None) is not None:
            n = to_int(mr, 0)
            cfg["caps"] = {"b1": n, "b2": n, "b3": n}
    cfg.pop("maxRounds", None)

    mdl = raw.get("maxDiffLines")
    size_raw = raw.get("size")
    has_prod = isinstance(size_raw, dict) and "prodLines" in size_raw
    if mdl is not None and not has_prod and to_int(mdl, None) is not None:
        cfg["size"]["prodLines"] = to_int(mdl, 400)
    cfg.pop("maxDiffLines", None)

    extra = cfg["behavior"].pop("extra", None)
    if isinstance(extra, list):
        for n, item in enumerate(extra, 1):
            if isinstance(item, str) and item.strip():
                cfg["checks"].append({"id": "extra-%d" % n, "kind": "command", "run": item,
                                      "gate": ["b1", "verify"]})
            elif isinstance(item, dict) and item.get("run"):
                cfg["checks"].append(dict(item))

    cfg["checks"] = [_normalize_check(c, n) for n, c in enumerate(cfg["checks"], 1)
                     if isinstance(c, dict)]
    if not isinstance(cfg["tests"].get("globs"), list) or not cfg["tests"]["globs"]:
        cfg["tests"]["globs"] = list(DEFAULT_TEST_GLOBS)
    if isinstance(cfg.get("visual"), dict):
        tol = cfg["visual"].get("tolerance")
        if not isinstance(tol, dict):
            tol = {}
        cfg["visual"]["tolerance"] = {"px": tol.get("px", 4), "color": tol.get("color", 8)}
    return cfg


def load_config(root, required=True):
    raw = read_json(config_path(root), default=None)
    if raw is None:
        if required:
            raise RsError("no config: .claude/ratchet/config.json")
        return normalize_config({})
    return normalize_config(raw)


# ---------------------------------------------------------------- plan

_KIND_NOTE = re.compile(
    r"^\s*[-*]\s*(\S+)[^:\n]*?\bkind:\s*(harness|feature|refactor|fix|choice)\b", re.I)


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_separator(cells):
    return bool(cells) and all(re.fullmatch(r":?-+:?", c) for c in cells)


def _plan_row(d):
    reqs_raw = d.get("reqs", "").strip()
    reqs = []
    if reqs_raw not in ("", "-"):
        reqs = [x.strip() for x in reqs_raw.split(",") if x.strip()]
    est_raw = d.get("est", "").strip()
    return {
        "id": d.get("id", "").strip(),
        "checkpoint": d.get("checkpoint", "").strip(),
        "kind": d.get("kind", "").strip().lower() or "feature",
        "target": d.get("target", "").strip() or "-",
        "reqs": reqs,
        "est": int(est_raw) if re.fullmatch(r"\d+", est_raw) else None,
        "status": d.get("status", "").strip().lower(),
        "base": d.get("base", "").strip(),
    }


def parse_plan_text(text):
    """Parse the checkpoint table, version 1 or 2. Returns {"version": n, "rows": [...]}."""
    lines = text.splitlines()
    header = None
    raw_rows = []
    after = []
    i = 0
    while i < len(lines) - 1:
        if lines[i].lstrip().startswith("|"):
            cells = [c.lower() for c in _split_row(lines[i])]
            if "id" in cells and "status" in cells and "checkpoint" in cells \
                    and _is_separator(_split_row(lines[i + 1])):
                header = cells
                j = i + 2
                while j < len(lines) and lines[j].lstrip().startswith("|"):
                    raw_rows.append(_split_row(lines[j]))
                    j += 1
                after = lines[j:]
                break
        i += 1
    if header is None:
        raise RsError("no checkpoint table in the plan")
    version = 2 if "kind" in header else 1
    rows = []
    for cells in raw_rows:
        d = {}
        for idx, name in enumerate(header):
            d[name] = cells[idx] if idx < len(cells) else ""
        row = _plan_row(d)
        if row["id"]:
            rows.append(row)
    if version == 1:
        # Version 1 keeps `kind: refactor` in the Notes, so honour it for real v1 plans.
        kinds = {}
        for line in after:
            m = _KIND_NOTE.match(line)
            if m:
                kinds[m.group(1)] = m.group(2).lower()
        for row in rows:
            if row["id"] in kinds:
                row["kind"] = kinds[row["id"]]
    return {"version": version, "rows": rows}


def load_plan(root, slug):
    check_name("slug", slug)
    path = plan_path(root, slug)
    if not os.path.isfile(path):
        raise RsError("no plan: %s" % rel(root, path))
    return parse_plan_text(read_text(path))


def pick_row(plan, cp):
    """The row for <cp>, or the first open row when cp is empty."""
    if cp:
        for row in plan["rows"]:
            if row["id"] == cp:
                return row
        raise RsError("no row %s in the plan" % cp)
    for row in plan["rows"]:
        if row["status"] in OPEN_STATUSES:
            return row
    raise RsError("no open row in the plan")


# ---------------------------------------------------------------- STATE

def stage_index(stage):
    return STAGES.index(stage) if stage in STAGES else -1


def advance_stage(state, stage):
    """Move the stage forward only: a re-run of an earlier gate must not rewind it."""
    if stage_index(stage) > stage_index(state.get("stage")):
        state["stage"] = stage


def normalize_state(raw, slug, cp, row):
    st = dict(raw) if isinstance(raw, dict) else {}
    st["version"] = 2
    st["slug"] = slug
    st["cp"] = cp
    if st.get("stage") not in STAGES:
        st["stage"] = STAGE_BY_STATUS.get(row["status"] if row else "", "B0")
    rounds = {"b0": 0, "b1": 0, "b2": 0, "b3": 0}
    if isinstance(st.get("rounds"), dict):
        for k, v in st["rounds"].items():
            rounds[k] = to_int(v, 0)
    st["rounds"] = rounds
    st["epoch"] = to_int(st.get("epoch"), 1)
    op = {"blocking": [], "advisory": []}
    if isinstance(st.get("open"), dict):
        for k in ("blocking", "advisory"):
            if isinstance(st["open"].get(k), list):
                op[k] = [str(x) for x in st["open"][k]]
    st["open"] = op
    if not st.get("updated"):
        st["updated"] = now_iso()
    return st


def load_state(root, slug, row):
    """Returns (state, existed). Without a STATE file the stage comes from the row status."""
    raw = read_json(state_path(root, slug, row["id"]), default=None)
    return normalize_state(raw, slug, row["id"], row), raw is not None


def write_state(root, state):
    state["updated"] = now_iso()
    write_json(state_path(root, state["slug"], state["cp"]), state)


# ---------------------------------------------------------------- LIVE and METRICS

def live_update(root, **fields):
    """Update LIVE while a run is active. A missing or inactive file stays as it is."""
    try:
        live = read_json(live_path(root), default=None)
    except RsError:
        return
    if not isinstance(live, dict) or not live.get("active"):
        return
    live.update(fields)
    live["updated"] = now_iso()
    write_json(live_path(root), live)


def metrics_append(root, entry):
    append_text(metrics_path(root), json.dumps(entry, separators=(",", ":"), ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- globs

_GLOB_CACHE = {}


def _glob_regex(pat):
    cached = _GLOB_CACHE.get(pat)
    if cached is not None:
        return cached
    out = []
    i = 0
    n = len(pat)
    while i < n:
        c = pat[i]
        if c == "*":
            j = i
            while j < n and pat[j] == "*":
                j += 1
            if j - i >= 2:
                if j < n and pat[j] == "/":
                    out.append("(?:.*/)?")  # `**/` also matches zero directories
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i = j
        elif c == "?":
            out.append("[^/]")
            i += 1
        elif c == "[":
            j = i + 1
            if j < n and pat[j] in "!^":
                j += 1
            if j < n and pat[j] == "]":
                j += 1
            while j < n and pat[j] != "]":
                j += 1
            if j >= n:
                out.append(re.escape(c))
                i += 1
            else:
                body = pat[i + 1:j].replace("\\", "\\\\")
                if body[:1] in ("!", "^"):
                    body = "^" + body[1:]
                out.append("[" + body + "]")
                i = j + 1
        else:
            out.append(re.escape(c))
            i += 1
    rx = re.compile("".join(out) + r"\Z")
    _GLOB_CACHE[pat] = rx
    return rx


def glob_match(pattern, path):
    """Glob with `**`. A pattern without a slash matches the file name at any depth."""
    p = pattern.strip()
    if p.startswith("./"):
        p = p[2:]
    if p.startswith("/"):
        p = p[1:]
    if p.endswith("/"):
        p += "**"
    target = path if "/" in p else os.path.basename(path)
    return _glob_regex(p).match(target) is not None


def any_glob(patterns, path):
    return any(glob_match(g, path) for g in patterns)


def is_test(cfg, path):
    return any_glob(cfg["tests"]["globs"], path)


# ---------------------------------------------------------------- the bash helpers

def rs_script():
    env = os.environ.get("RS_SH")
    if env and os.path.isfile(env):
        return env
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ratchet.sh")


def rs_run(root, *args):
    return run(["bash", rs_script()] + list(args), cwd=root)


def snap(root, name=None):
    args = ["snap"] + ([name] if name else [])
    rc, out, err = rs_run(root, *args)
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if rc != 0 or not lines:
        raise RsError("snapshot failed: %s" % (err.strip() or out.strip())[:200])
    return lines[-1].strip()


def ref_sha(root, slug, cp, name):
    rc, out, _ = run(["git", "rev-parse", "--verify", "--quiet",
                      "refs/ratchet/%s/%s/%s" % (slug, cp, name)], cwd=root)
    if rc == 0 and out.strip():
        return out.strip()
    return None


def resolve_base(root, slug, row):
    """The base tree: the ref first, then the SHA in the plan row."""
    sha = ref_sha(root, slug, row["id"], "base")
    if sha:
        return sha
    col = row.get("base", "")
    if re.fullmatch(r"[0-9a-f]{7,40}", col):
        rc, out, _ = run(["git", "rev-parse", "--verify", "--quiet", col + "^{tree}"], cwd=root)
        if rc == 0 and out.strip():
            return out.strip()
    return None


def diff_status(root, tree):
    """[(status, path)] changed since <tree>, minus .claude/ratchet. NUL output keeps odd names intact."""
    rc, out, err = rs_run(root, "diff", tree, "--name-status", "-z", "--no-renames")
    if rc != 0:
        raise RsError("diff failed: %s" % (err.strip() or out.strip())[:200])
    toks = out.split("\0")
    res = []
    i = 0
    while i + 1 < len(toks):
        res.append((toks[i], toks[i + 1]))
        i += 2
    return res


def diff_numstat(root, tree):
    """[(added, deleted, path)] since <tree>. Binary files report None counts."""
    rc, out, err = rs_run(root, "diff", tree, "--numstat", "-z", "--no-renames")
    if rc != 0:
        raise RsError("diff failed: %s" % (err.strip() or out.strip())[:200])
    res = []
    for rec in out.split("\0"):
        parts = rec.strip("\n").split("\t", 2)
        if len(parts) != 3:
            continue
        added = None if parts[0] == "-" else to_int(parts[0], 0)
        deleted = None if parts[1] == "-" else to_int(parts[1], 0)
        res.append((added, deleted, parts[2]))
    return res


def pin_dirs(root, slug):
    """Every evidence dir of the plan that holds a spec.lock, as repo-relative paths."""
    base = os.path.join(r_dir(root), "evidence", slug)
    found = []
    if os.path.isdir(base):
        for name in sorted(os.listdir(base)):
            if os.path.isfile(os.path.join(base, name, "spec.lock")):
                found.append(".claude/ratchet/evidence/%s/%s" % (slug, name))
    return found


def read_lock(root, d):
    """The (hash, path) entries of <d>/spec.lock."""
    entries = []
    text = read_text(os.path.join(root, d, "spec.lock"))
    for line in text.splitlines():
        if "\t" in line:
            sha, path = line.split("\t", 1)
            entries.append((sha, path))
    return entries


def check_pins(root, dirs):
    """[(kind, path, dir)] for pinned files that changed or vanished."""
    if not dirs:
        return []
    rc, out, err = rs_run(root, "check", *dirs)
    if rc not in (0, 1):
        raise RsError("pin check failed: %s" % (err.strip() or out.strip())[:200])
    bad = []
    for line in out.splitlines():
        for prefix, kind in (("CHANGED  ", "changed"), ("VANISHED ", "vanished")):
            if not line.startswith(prefix):
                continue
            rest = line[len(prefix):]
            for d in dirs:
                suffix = "  (%s)" % d
                if rest.endswith(suffix):
                    bad.append((kind, rest[:-len(suffix)], d))
                    break
            break
    return bad


def pin_status(root, slug):
    """(intact count, changed entries) over every pin of the plan."""
    dirs = pin_dirs(root, slug)
    total = sum(len(read_lock(root, d)) for d in dirs)
    bad = check_pins(root, dirs)
    return total - len(bad), bad


# ---------------------------------------------------------------- running commands

def pid_alive(pid):
    if not pid or pid < 1:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # the process exists; it belongs to another user
    return True


def kill_group(proc):
    """Stop the command and every child it started. TERM first, then KILL."""
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    proc.wait()


def run_command(cmd, cwd, timeout, out_path=None):
    """Run cmd in a shell, in its own process group. Returns (exit code, ms); 124 on a timeout.

    With out_path, stdout and stderr go to that file. A file, not a pipe: a child that
    outlives the shell cannot keep us waiting for EOF.
    """
    start = time.time()
    out = None
    if out_path:
        d = os.path.dirname(out_path)
        if d:
            os.makedirs(d, exist_ok=True)
        out = open(out_path, "wb")
    try:
        proc = subprocess.Popen(
            ["/bin/sh", "-c", cmd], cwd=cwd, stdin=subprocess.DEVNULL,
            stdout=out, stderr=subprocess.STDOUT if out else None, start_new_session=True)
        wait = timeout if timeout and timeout > 0 else None
        try:
            rc = proc.wait(timeout=wait)
        except subprocess.TimeoutExpired:
            kill_group(proc)
            rc = 124
            note = "\n[rs] stopped after %ss: the command timed out\n" % timeout
            if out:
                out.write(note.encode("utf-8"))
            else:
                sys.stderr.write(note)
    finally:
        if out:
            out.close()
    if rc < 0:
        rc = 128 - rc  # shell convention for death by signal
    return rc, int((time.time() - start) * 1000)
