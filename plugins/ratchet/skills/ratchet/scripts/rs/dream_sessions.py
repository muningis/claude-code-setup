"""Read the Claude Code session transcripts: what the human said, and where agents struggled. No model.

A transcript is a JSON Lines file under ~/.claude/projects/<project>/. The files are large, so this
module reads each one in two cheap steps. A byte scan decides what the file can hold. Then a line
stream parses only the lines that can matter, and skips the lines that fall outside the window."""
from __future__ import annotations

import fnmatch
import json
import os
import re
from collections import Counter

import dream_io
from dream_scrub import SESSION_PRE_CAP, clean, scrub

TURN_CAP = 800
PREV_TEXT_CAP = 300
TOOL_CAP = 120
EXAMPLE_CAP = 200
HEAD_CAP = 80
PER_SESSION = 20
DUP_SECONDS = 5
MAX_TOOLS = 6
LOOKBACK = 12
MAX_GROUPS = 40
MAX_EXAMPLES = 3
MAX_GROUP_SESSIONS = 10
CHORE_LEN = 60
STRONG = ("rule", "correction", "declined", "interrupt")

HUMAN_MARK = b'"kind":"human"'
SLASH_MARK = b"<command-name>"
ENTRY_RX = re.compile(rb'"entrypoint":"([A-Za-z-]+)"')
# A line of a human file is parsed only when it holds one of these.
USER_MARKS = ('"kind":"human"', "<command-name>", "[Request interrupted by user", '"is_error":true')

RULE_RX = re.compile(r"\b(?:always|never|from now on|going forward|from here on|remember|every time|each time"
                     r"|don'?t ever|do not ever|stop (?:doing|using|adding|making|writing)|in the future)\b", re.I)
CORRECTION_RX = re.compile(
    r"^\W*(?:no\b(?![ -]?(?:problem|worries|thanks|need|rush))|nope\b|wrong\b|stop\b|wait\b|don'?t\b|do not\b"
    r"|why did you\b|why are you\b|that'?s not\b|that is not\b|not what\b|i said\b|i told you\b|instead\b"
    r"|revert\b|undo\b)", re.I)
TRIVIAL = frozenset("yes y no ok okay continue go go-on proceed thanks thank-you do-it sure yep yup lgtm looks-good "
                    "go-ahead next done stop approve approved retry again".split())
WRAPPER_RX = re.compile(r"<(system-reminder|ide_[a-z_]+|local-command-[a-z]+|bash-[a-z]+|task-notification"
                        r"|teammate-message)\b[^>]*>.*?</\1>", re.S | re.I)
SLASH_RX = re.compile(r"<command-name>\s*(/?[^<\s]+)\s*</command-name>", re.I)
ARGS_RX = re.compile(r"<command-args>(.*?)</command-args>", re.S | re.I)
NOTE_RX = re.compile(r"\s*Note: The user's next message may contain.*$", re.S)

# Agent friction. Tool errors that no agent can blame on a red test: the harness refused the call,
# a hook or a classifier denied it, it timed out, or the shell could not parse it.
SHELL_RX = re.compile(r"parse error|no matches found|command not found|\(eval\):\d+:|bad substitution"
                      r"|syntax error near unexpected token|unexpected eof while looking for|unterminated substitute"
                      r"|\bsed: \d+:|zsh:\d+:|zsh: unmatched|bash: line \d+:|not a valid identifier"
                      r"|ambiguous redirect|bad pattern", re.I)
DENIAL_RX = re.compile(r"permission for this action was denied|permission denied|was denied|denied by|hook error"
                       r"|pretooluse|auto mode|classifier|this session is isolated in the worktree"
                       r"|blocked by (?:a )?hook", re.I)
# These name a harness refusal. They come before the timeout test: a bad argument may mention a timeout.
STRICT_HARNESS_RX = re.compile(r"inputvalidationerror|file has not been read yet|string to replace not found"
                               r"|found \d+ matches", re.I)
TIMEOUT_RX = re.compile(r"timed out|timeout|did not respond within|deadline exceeded", re.I)
EXIT_TIMEOUT_RX = re.compile(r"^exit code 124\b|command timed out|\[rs\] stopped after \d+s", re.I)
HARNESS_RX = re.compile(r"exceeds maximum|file too large|too large to read|file does not exist|eisdir|enoent"
                        r"|no such tool available|isolation context|protocol frame|<tool_use_error>"
                        r"|modified since|multiple matches", re.I)

ROLE_BY_NAME = (("spec", "spec"), ("impl", "implement"), ("implement", "implement"), ("builder", "implement"),
                ("arch", "review-arch"), ("break", "review-break"), ("visual", "visual"), ("roast", "roaster"),
                ("fix", "fix"))
ROLE_BY_PROMPT = (
    (re.compile(r"^(?:try to break|break\b|edge case)"), "review-break"),
    (re.compile(r"^(?:review|judge)\b"), "review-arch"),
    (re.compile(r"^roast|^contrarian"), "roaster"),
    (re.compile(r"^(?:compare|regression check|please do a regression|round \d+ visual)"), "visual"),
    (re.compile(r"^(?:write|add|amend|strengthen|make spec|spec)\b.*\b(?:spec|tests?|assertion|cases?)\b"), "spec"),
    (re.compile(r"^fix\b"), "fix"),
    (re.compile(r"^(?:implement|build|you are implementing|make the pinned)"), "implement"),
)


# ---------------------------------------------------------------- small helpers

def block_text(content):
    """The text of a message content: a string, or the text blocks of a list."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text") or "" for b in content if isinstance(b, dict) and isinstance(b.get("text"), str))
    return ""


def content_of(rec):
    """The content of the message of a record, or None when the record has the wrong shape."""
    msg = rec.get("message") if isinstance(rec, dict) else None
    return msg.get("content") if isinstance(msg, dict) else None


def line_value(line, key, width):
    """The text after `"key":"` in a raw line, up to `width` characters, or None. No JSON parse."""
    i = line.find(key)
    return line[i + len(key):i + len(key) + width] if i >= 0 else None


def ts_epoch(ts):
    return dream_io.epoch_of(ts)


def tool_label(block):
    """`Bash: <command>`, `Edit: <path>`, or the plain tool name."""
    name = str(block.get("name") or "?")
    inp = block.get("input") if isinstance(block.get("input"), dict) else {}
    if name == "Bash":
        return "Bash: " + clean(inp.get("command") or "", TOOL_CAP, SESSION_PRE_CAP)
    if name in ("Edit", "Write", "MultiEdit", "NotebookEdit"):
        return "%s: %s" % (name, clean(inp.get("file_path") or inp.get("notebook_path") or "", TOOL_CAP))
    return name[:60]


def role_of(agent_name, prompt):
    """A role name for a teammate session: the agent name first, then the first words of its prompt."""
    head = re.split(r"[-_ .:/0-9]", str(agent_name or "").lower(), maxsplit=1)[0]
    for key, role in ROLE_BY_NAME:
        if head == key:
            return role
    text = re.sub(r"^<teammate-message[^>]*>\s*", "", prompt or "")
    text = re.sub(r"^repo root:\s*\S+?[.,]?\s+", "", text, flags=re.I)
    text = " ".join(text.lower().split())[:200]
    for rx, role in ROLE_BY_PROMPT:
        if rx.search(text):
            return role
    return "other"


def classify(text, denial_kind):
    """The friction class of a tool error, or None when it is not friction (a plain exit code, or unknown)."""
    if denial_kind:
        return "denial"
    low = text.lower()
    exit_code = low.lstrip().startswith("exit code")
    # The shell reports its own errors first. A test log may hold these words much later.
    if SHELL_RX.search(text[:1500] if exit_code else text):
        return "shell"
    if exit_code:
        # A Bash call that exited with a code is a failed command, often a red test. Only a stop is friction.
        return "timeout" if EXIT_TIMEOUT_RX.search(low.lstrip()) else None
    if DENIAL_RX.search(text):
        return "denial"
    if STRICT_HARNESS_RX.search(text):
        return "harness"
    if TIMEOUT_RX.search(text):
        return "timeout"
    if HARNESS_RX.search(text):
        return "harness"
    return None


def norm_head(text):
    """The first words of an error without the parts that change from one run to the next."""
    t = scrub(text[:2000])
    t = re.sub(r"</?tool_use_error>", "", t)
    t = re.sub(r"^\s*error:\s*", "", " ".join(t.split()), flags=re.I)
    t = re.sub(r"(?<![\w])/[^\s:'\"()<>]+", "<path>", t)
    t = re.sub(r"\btoolu_[A-Za-z0-9]+\b", "<id>", t)
    t = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", t)
    t = re.sub(r"\d+", "N", t)
    return t[:HEAD_CAP].rstrip()


def chore_key(text):
    """A short, normalised request, or None when it is too long or only an acknowledgement."""
    norm = " ".join(re.sub(r"[^a-z0-9/ ]+", " ", text.lower()).split())
    if not norm or len(norm) > CHORE_LEN or norm.replace(" ", "-") in TRIVIAL:
        return None
    return norm


def human_text(content):
    """The words of a human prompt: its text blocks, without the wrappers that the harness adds."""
    text = WRAPPER_RX.sub("", block_text(content)).strip()
    slash = SLASH_RX.search(text)
    if slash:
        args = ARGS_RX.search(text)
        args = " ".join(args.group(1).split()) if args else ""
        return ("%s %s" % (slash.group(1), args)).strip() if args else "", True
    return text, False


def declined_text(text, feedback):
    """What the human told the agent when they declined a tool use."""
    if isinstance(feedback, str) and feedback.strip():
        return feedback.strip()
    if "the user said:" not in text:
        return ""
    return NOTE_RX.sub("", text.split("the user said:", 1)[1]).strip()


# ---------------------------------------------------------------- reading one file

def prescan(path):
    """(skip, has_human) from one pass over the bytes. skip: the file came from `claude -p` (sdk-cli).

    Raises OSError when the file cannot be read."""
    sdk = None
    has_human = False
    carry = b""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(1 << 22)
            if not chunk:
                break
            data = carry + chunk
            if sdk is None:
                m = ENTRY_RX.search(data)
                if m:
                    sdk = m.group(1) == b"sdk-cli"
            if sdk:
                return True, False
            if not has_human and (HUMAN_MARK in data or SLASH_MARK in data):
                has_human = True
            if has_human and sdk is not None:
                break
            carry = data[-32:]
    return False, has_human


def peek_prompt(path):
    """(first prompt, agent name) from the first lines of a top-level session that has no human prompt."""
    name = None
    try:
        with open(path, "r", encoding="utf-8", errors="replace", newline="\n") as fh:
            for i, line in enumerate(fh):
                if i >= 60:
                    break
                if name is None:
                    name = line_value(line, '"agentName":"', 80)
                    name = name.split('"')[0] if name else None
                if '"type":"user"' in line and '"tool_use_id"' not in line:
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    text = block_text(content_of(rec)).strip()
                    if text:
                        return text, name
    except OSError:
        pass
    return "", name


class FileState(object):
    """What one file needs while it streams: who it is, and the context of the next human turn."""

    def __init__(self, entry, project, human, role):
        self.path = entry["path"]
        self.project = project
        self.human = human
        self.role = role
        self.sess8 = entry["session"][:8]
        agent = entry.get("agent")
        self.tag = self.sess8 if not agent else "%s/%s" % (self.sess8, agent.replace("agent-", "")[:8])
        self.assistant = []
        self.interrupt = False
        self.recent = {}
        self.active = False
        self.got_cwd = False


class Scan(object):
    """The result of reading every session in the window."""

    def __init__(self, since, until, exclude):
        self.since_key = dream_io.ms_key(since) if since is not None else None
        self.until_key = dream_io.ms_key(until) if until is not None else None
        self.exclude = [os.path.expanduser(p) if p.startswith("~") else p for p in exclude]
        self._ex = {}
        self.turns = []
        self.friction = {}
        self.cwds = Counter()
        self.seen = set()
        self.stats = Counter()

    def excluded(self, name):
        if not self.exclude or not name:
            return False
        got = self._ex.get(name)
        if got is None:
            got = any(fnmatch.fnmatchcase(name, p) for p in self.exclude)
            self._ex[name] = got
        return got

    def in_window(self, ts):
        if not ts:
            return False
        if len(ts) == 24 and ts.endswith("Z") and ts[10] == "T":
            return (self.since_key is None or ts > self.since_key) and (self.until_key is None or ts <= self.until_key)
        e = ts_epoch(ts)
        if e is None:
            return False
        s = ts_epoch(self.since_key) if self.since_key else None
        u = ts_epoch(self.until_key) if self.until_key else None
        return (s is None or e > s) and (u is None or e <= u)

    # ---- friction

    def add_friction(self, st, cls, text, n, example_ok=True):
        head = norm_head(text)
        if not head:
            return
        g = self.friction.setdefault((st.role, cls, head), {
            "role": st.role, "class": cls, "head": head, "count": 0, "sessions": [], "examples": []})
        g["count"] += 1
        if st.sess8 not in g["sessions"]:
            g["sessions"].append(st.sess8)
        if example_ok and len(g["examples"]) < MAX_EXAMPLES:
            g["examples"].append({"ref": "%s#%d" % (st.tag, n), "text": clean(text, EXAMPLE_CAP, SESSION_PRE_CAP)})

    # ---- human turns

    def prev_of(self, st):
        """The assistant action before a human turn: its last text, and the tools that it used."""
        text, tools = "", []
        for raw in st.assistant:
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            content = content_of(rec)
            for b in content if isinstance(content, list) else []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and isinstance(b.get("text"), str) and b["text"].strip():
                    text = b["text"]
                elif b.get("type") == "tool_use":
                    label = tool_label(b)
                    if not tools or tools[-1] != label:
                        tools.append(label)
        st.assistant = []
        return {"text": clean(text, PREV_TEXT_CAP, SESSION_PRE_CAP), "tools": tools[-MAX_TOOLS:]}

    def add_turn(self, st, rec, n, text, declined=False):
        uuid = rec.get("uuid")
        if uuid:
            if uuid in self.seen:
                return
            self.seen.add(uuid)
        norm = " ".join(text.split()).lower()
        when = ts_epoch(rec.get("timestamp") or "")
        before = st.recent.get(norm)
        if when is not None and before is not None and abs(when - before) <= DUP_SECONDS:
            return
        if when is not None:
            st.recent[norm] = when
        tags = []
        if st.interrupt:
            tags.append("interrupt")
            st.interrupt = False
        if declined:
            tags.append("declined")
        if RULE_RX.search(text):
            tags.append("rule")
        if CORRECTION_RX.search(text):
            tags.append("correction")
        ts = (rec.get("timestamp") or "")[:19] + "Z"
        self.turns.append({
            "id": "%s#%d" % (st.sess8, n), "session": st.sess8, "project": st.project,
            "cwd": clean(rec.get("cwd") or "", 200), "ts": ts, "text": clean(text, TURN_CAP, SESSION_PRE_CAP),
            "prev": self.prev_of(st), "tags": tags, "_n": n, "_norm": text})

    # ---- one parsed user record

    def user_record(self, st, rec, n):
        # The line prefilter read the first timestamp of the line. This one is the record's own.
        if not self.in_window(rec.get("timestamp")):
            return
        cwd = rec.get("cwd") or ""
        if self.excluded(cwd):
            return
        if cwd:
            self.cwds[cwd] += 1
        content = content_of(rec)
        results = [b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"] \
            if isinstance(content, list) else []
        if results:
            kind = rec.get("toolDenialKind")
            for b in results:
                if not b.get("is_error"):
                    continue
                text = block_text(b.get("content"))
                if kind == "user-rejected" or ("doesn't want to proceed" in text and "the user said" in text):
                    # The human declined the call. Their words are a turn; the decline is not agent friction.
                    said = declined_text(text, rec.get("userFeedback"))
                    if st.human and said:
                        self.add_turn(st, rec, n, said, declined=True)
                    continue
                cls = classify(text, kind)
                if cls is None:
                    self.stats["unclassified"] += 1
                else:
                    self.add_friction(st, cls, text, n)
            return
        if rec.get("isCompactSummary") or rec.get("isMeta") or rec.get("toolUseResult") is not None:
            return
        raw = block_text(content)
        if raw.lstrip().startswith("[Request interrupted by user"):
            st.interrupt = True
            return
        origin = rec.get("origin")
        kind = origin.get("kind") if isinstance(origin, dict) else None
        text, slash = human_text(content)
        # A typed slash command has no origin in the transcript; any other prompt must say it is human.
        if not text or (kind != "human" and not (kind is None and slash)):
            return
        if text.startswith("<teammate-message") or not st.human:
            return
        self.add_turn(st, rec, n, text)


def read_file(scan, entry, project):
    """Stream one transcript into the scan. Returns False when the file is not read at all."""
    try:
        skip, human = prescan(entry["path"])
    except OSError:
        scan.stats["unreadable"] += 1
        return False
    if skip:
        scan.stats["sdkFiles"] += 1
        return False
    agent = entry.get("agent")
    if agent:
        role = str((entry.get("meta") or {}).get("agentType") or "subagent")[:40]
    elif human:
        role = "main"
    else:
        prompt, name = peek_prompt(entry["path"])
        role = role_of(name, prompt) if prompt.startswith("<teammate-message") else "other"
    st = FileState(entry, project, human and not agent, role)
    try:
        fh = open(entry["path"], "r", encoding="utf-8", errors="replace", newline="\n")
    except OSError:
        return False
    with fh:
        for n, line in enumerate(fh, 1):
            ts = line_value(line, '"timestamp":"', 24)
            if ts is None or not scan.in_window(ts):
                continue
            if not st.got_cwd:
                cwd = line_value(line, '"cwd":"', 400)
                if cwd is not None:
                    cwd = cwd.split('"')[0]
                    if "\\" not in cwd and not scan.excluded(cwd):
                        scan.cwds[cwd] += 1
                    st.got_cwd = True
            st.active = True
            if '"type":"user"' in line:
                if st.human:
                    if not any(m in line for m in USER_MARKS):
                        continue
                elif '"is_error":true' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if isinstance(rec, dict) and rec.get("type") == "user":
                    try:
                        scan.user_record(st, rec, n)
                    except (AttributeError, TypeError, KeyError, ValueError):
                        # A record of an unknown shape costs that record, not the whole harvest.
                        scan.stats["badRecords"] += 1
            elif st.human and '"type":"assistant"' in line:
                st.assistant.append(line)
                if len(st.assistant) > LOOKBACK:
                    del st.assistant[0]
    return st.active


def list_files(scan, since):
    """The transcripts that could hold a record newer than `since`. The file time is only a prefilter."""
    base = dream_io.projects_dir()
    out = []
    try:
        projects = sorted(os.listdir(base))
    except OSError:
        return out

    def fresh(path):
        try:
            return since is None or os.path.getmtime(path) > since
        except OSError:
            return False

    for project in projects:
        pdir = os.path.join(base, project)
        if not os.path.isdir(pdir) or scan.excluded(project):
            continue
        try:
            names = sorted(os.listdir(pdir))
        except OSError:
            continue
        for name in names:
            path = os.path.join(pdir, name)
            if name.endswith(".jsonl") and os.path.isfile(path):
                if fresh(path):
                    out.append(({"path": path, "session": name[:-6]}, project))
            elif os.path.isdir(path):
                sub = os.path.join(path, "subagents")
                try:
                    subs = sorted(os.listdir(sub))
                except OSError:
                    continue
                for s in subs:
                    sp = os.path.join(sub, s)
                    if s.startswith("agent-") and s.endswith(".jsonl") and fresh(sp):
                        meta = {}
                        try:
                            with open(sp[:-6] + ".meta.json", "r", encoding="utf-8") as mf:
                                meta = json.load(mf)
                        except (OSError, ValueError):
                            pass
                        out.append(({"path": sp, "session": name, "agent": s[:-6],
                                     "meta": meta if isinstance(meta, dict) else {}}, project))
    return out


# ---------------------------------------------------------------- the whole window

def priority(turn):
    if any(t in STRONG for t in turn["tags"]):
        return 3
    return 2 if "chore" in turn["tags"] else 1


def finish(scan):
    """Tag the chores, cap each session, and number the friction groups."""
    counts = Counter(k for k in (chore_key(t["_norm"]) for t in scan.turns) if k)
    for t in scan.turns:
        k = chore_key(t["_norm"])
        if k and counts[k] >= 2:
            t["tags"].append("chore")
    by_session = {}
    for t in scan.turns:
        by_session.setdefault(t["session"], []).append(t)
    kept = []
    cut = 0
    for turns in by_session.values():
        if len(turns) > PER_SESSION:
            # The strongest turns stay; among equals the later ones win, so a long session keeps its end.
            ranked = sorted(turns, key=lambda t: (-priority(t), -t["_n"]))
            cut += len(turns) - PER_SESSION
            turns = sorted(ranked[:PER_SESSION], key=lambda t: t["_n"])
        kept.extend(turns)
    first = {}
    for t in kept:
        first.setdefault(t["session"], t["ts"])
    kept.sort(key=lambda t: (first[t["session"]], t["session"], t["_n"]))
    groups = sorted(scan.friction.values(), key=lambda g: (-g["count"], g["class"], g["head"]))
    extra_groups = max(0, len(groups) - MAX_GROUPS)
    groups = groups[:MAX_GROUPS]
    for i, g in enumerate(groups, 1):
        g["id"] = "F%d" % i
        g["sessions"] = g["sessions"][:MAX_GROUP_SESSIONS]
    return kept, groups, {"perSession": cut, "frictionGroups": extra_groups}


def projects_of(turns):
    """{project: {cwd, turns, sessions}} for each project folder that holds a human turn."""
    out = {}
    cwds = {}
    for t in turns:
        p = out.setdefault(t["project"], {"turns": 0, "sessions": set()})
        p["turns"] += 1
        p["sessions"].add(t["session"])
        cwds.setdefault(t["project"], Counter())[t["cwd"]] += 1
    return dict((k, {"cwd": cwds[k].most_common(1)[0][0], "turns": v["turns"], "sessions": len(v["sessions"])})
                for k, v in sorted(out.items()))


def scan_sessions(since, until, exclude):
    """Everything that the sessions of the window say. `since` None means no lower bound."""
    scan = Scan(since, until, exclude)
    entries = list_files(scan, since)
    for entry, project in entries:
        if read_file(scan, entry, project):
            scan.stats["files"] += 1
            if not entry.get("agent"):
                scan.stats["sessions"] += 1
    total_turns = len(scan.turns)
    events = sum(g["count"] for g in scan.friction.values())
    turns, groups, dropped = finish(scan)
    return {"turns": turns, "friction": groups, "cwds": scan.cwds, "projects": projects_of(turns),
            "totalTurns": total_turns, "frictionEvents": events, "dropped": dropped, "stats": dict(scan.stats)}
