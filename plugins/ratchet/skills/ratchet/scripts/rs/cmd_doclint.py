#!/usr/bin/env python3
"""RS doclint: check the structure of ratchet's change documents (docs.md).

Usage: cmd_doclint.py PATH... [--approval] [--approve FILE] [--lock-file PATH]
       [--out FILE] [--format json|text] [--nonce N]
Exit code: 0 pass, 1 block findings, 2 error.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import sys
import traceback


def _load_sibling(name):
    # rs is not a package when a script runs directly, so load the sibling by path.
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name + ".py")
    spec = importlib.util.spec_from_file_location("_rs_" + name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    keep = sys.dont_write_bytecode
    sys.dont_write_bytecode = True  # keep __pycache__ out of the plugin folder
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.dont_write_bytecode = keep
    return mod


ste = _load_sibling("cmd_stelint")
UsageError = ste.UsageError

CMD = "doclint"
DOC_TYPES = ("design-log", "prd", "spec", "adr", "architecture")
TRACKS = ("fix", "small", "full")
STATUSES = ("draft", "approved", "done")
ADR_STATUS = re.compile(r"^(?:proposed|accepted|rejected|deprecated|superseded by ADR-\d{4})$")
KINDS = ("test", "visual", "smoke", "device")
REQUIRED_KEYS = {"design-log": ("track", "change", "status"), "prd": ("change", "status"),
                 "spec": ("change", "status"), "adr": ("status", "date"), "architecture": ()}

DL_ORDER = ("Decisions for the implementer", "Background", "Problem", "Prior art", "Requirements",
            "Questions and answers", "Design", "Plan", "Trade-offs", "Results")
DL_REQUIRED = ("Decisions for the implementer", "Problem", "Questions and answers", "Design")
FIX_SUBSECTIONS = ("Current behaviour", "Expected behaviour", "Unchanged behaviour")
PRD_SECTIONS = ("Problem", "Outcome", "Non-goals", "Scenarios", "Success criteria", "Risks")
ADR_SECTIONS = ("Context and Problem Statement", "Considered Options", "Decision Outcome")
BUDGETS = {"prd": 300, "spec": 1200, "design-log": 2000, "adr": 600}

DECISIONS_RANGE = (3, 7)
PROBLEM_RANGE = (2, 4)

_BOLD_REQ = re.compile(r"^\*\*(?:FR|UB)-")
_CLARIFY = re.compile(r"\[NEEDS CLARIFICATION(?::[^\]]*)?\]", re.I)
_CODE_SPAN = re.compile(r"(`+).+?\1", re.S)
_QUOTED = re.compile(r"\"[^\"]*\"|\u201c[^\u201d]*\u201d")


# ------------------------------------------------------------------ model

class Doc(object):
    def __init__(self, path, data):
        self.path = path
        self.data = data
        self.fm_text, self.body_at = ste.split_front_matter(data)
        self.fm = ste.parse_front_matter(self.fm_text) if self.fm_text is not None else None
        self.lines = ste.scan(data.decode("utf-8", "replace"))
        self.findings = []

    def add(self, severity, rule, line, message):
        self.findings.append(ste.finding(self.path, line, severity, rule, message))

    @property
    def body_line(self):
        return sum(1 for ln in self.lines if ln.kind == "front") + 1

    def fm_line(self, key):
        if self.fm_text is not None:
            for i, ln in enumerate(self.fm_text.split("\n")):
                if re.match(r"^%s\s*:" % re.escape(key), ln):
                    return i + 2
        return 1


def count_of(n, noun):
    return "%d %s%s" % (n, noun, "" if n == 1 else "s")


def sections(lines, level=2):
    """List the sections of one heading level. A section ends at the next heading of that level or above."""
    heads = [(i, ln) for i, ln in enumerate(lines) if ln.kind == "heading" and ln.level <= level]
    out = []
    for n, (i, ln) in enumerate(heads):
        if ln.level == level:
            end = heads[n + 1][0] if n + 1 < len(heads) else len(lines)
            out.append({"name": " ".join(ln.text.split()), "idx": i, "end": end, "no": ln.no})
    return out


def find(secs, name):
    for s in secs:
        if s["name"] == name:
            return s
    return None


def has_content(lines, lo, hi):
    return any(ln.kind not in ("blank", "comment", "heading", "rule") for ln in lines[lo:hi])


def top_items(lines, lo, hi):
    """Items at the shallowest indent of lines[lo:hi]."""
    items = ste.collect_items(lines, lo, hi)
    if not items:
        return []
    base = min(i[1] for i in items)
    return [i for i in items if i[1] == base]


def count_words(doc, stop_no=None):
    n = 0
    for ln in doc.lines:
        if stop_no is not None and ln.no >= stop_no:
            break
        if ln.kind in ("text", "item"):
            n += sum(1 for t in ln.text.split() if any(c.isalnum() for c in t))
    return n


# ------------------------------------------------------------------- lock

def lock_key(path):
    real = os.path.realpath(path)
    root = ste.find_git_root(os.path.dirname(real))
    return os.path.relpath(real, root) if root else real


def default_lock_path(path):
    root = ste.find_git_root(os.path.dirname(os.path.realpath(path)))
    root = root or ste.find_git_root(os.getcwd()) or os.getcwd()
    return os.path.join(root, ".claude", "ratchet", "docs.lock")


def read_lock(path):
    """Read the lock file. The last record of a path wins."""
    recs = {}
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except FileNotFoundError:
        return recs
    for n, ln in enumerate(raw.split(b"\n"), 1):
        if not ln.strip():
            continue
        try:
            r = json.loads(ln.decode("utf-8"))
            recs[r["path"]] = {"bytes": int(r["bytes"]), "sha256": str(r["sha256"])}
        except (ValueError, KeyError, TypeError):
            raise UsageError("bad record on line %d of %s" % (n, path))
    return recs


def body_of(doc):
    return doc.data[doc.body_at:]


def check_lock(doc, recs):
    rec = recs.get(lock_key(doc.path))
    if not rec:
        return
    body = body_of(doc)
    n = rec["bytes"]
    if len(body) < n or hashlib.sha256(body[:n]).hexdigest() != rec["sha256"]:
        doc.add("block", "DOC-LOCK", doc.body_line,
                "The approved text changed. Restore it. Add new text only below it.")


def write_lock(lockpath, doc):
    key = lock_key(doc.path)
    body = body_of(doc)
    rec = {"path": key, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    if read_lock(lockpath).get(key) == {"bytes": rec["bytes"], "sha256": rec["sha256"]}:
        return rec
    os.makedirs(os.path.dirname(os.path.abspath(lockpath)), exist_ok=True)
    with open(lockpath, "ab") as fh:
        fh.write((json.dumps(rec) + "\n").encode("utf-8"))
    return rec


# ----------------------------------------------------------- front matter

def check_front(doc):
    """Check the front matter. Return the document type, or None when it is unusable."""
    if doc.fm is None:
        if doc.lines and doc.lines[0].kind == "rule":
            doc.add("block", "DOC-FM-MISSING", 1, "Front matter has no closing ---.")
        else:
            doc.add("block", "DOC-FM-MISSING", 1,
                    "No front matter. Start the file with --- and the keys type, change and status.")
        return None
    t = doc.fm.get("type")
    if t not in DOC_TYPES:
        what = "type is missing" if not t else "type '%s' is unknown" % t
        doc.add("block", "DOC-FM-TYPE", doc.fm_line("type"),
                "Front matter: %s. Use design-log, prd, spec, adr or architecture." % what)
        return None
    for key in REQUIRED_KEYS[t]:
        if not doc.fm.get(key):
            doc.add("block", "DOC-FM-KEY", 1, "Front matter of a %s needs the key '%s'." % (t, key))
    track = doc.fm.get("track")
    if track and t == "design-log" and track not in TRACKS:
        doc.add("block", "DOC-FM-VALUE", doc.fm_line("track"), "track '%s' is not fix, small or full." % track)
    status = doc.fm.get("status")
    if status:
        if t == "adr":
            if not ADR_STATUS.match(status):
                doc.add("block", "DOC-FM-VALUE", doc.fm_line("status"),
                        "ADR status '%s' is unknown. Use proposed, accepted, rejected, deprecated or superseded by ADR-NNNN."
                        % status)
        elif t != "architecture" and status not in STATUSES:
            doc.add("block", "DOC-FM-VALUE", doc.fm_line("status"),
                    "status '%s' is not draft, approved or done." % status)
    extra = []
    if t != "design-log" and "track" in doc.fm:
        extra.append("track")
    if t == "adr" and "change" in doc.fm:
        extra.append("change")
    if t == "architecture":
        extra.extend(k for k in doc.fm if k != "type")
    for key in extra:
        doc.add("warn", "DOC-FM-EXTRA", doc.fm_line(key), "Remove the key '%s'. Type %s does not use it." % (key, t))
    change = doc.fm.get("change")
    if change and t in ("design-log", "prd", "spec"):
        if not re.match(r"^\d{4}-[a-z0-9][a-z0-9-]*$", change):
            doc.add("warn", "DOC-FM-FORMAT", doc.fm_line("change"), "change '%s' is not NNNN-slug." % change)
        folder = os.path.basename(os.path.dirname(os.path.abspath(doc.path)))
        if re.match(r"^\d{4}-", folder) and folder != change:
            doc.add("warn", "DOC-FM-FORMAT", doc.fm_line("change"),
                    "change '%s' differs from the folder '%s'." % (change, folder))
    date = doc.fm.get("date")
    if date and not re.match(r"^\d{4}-\d{2}-\d{2}$", date):
        doc.add("warn", "DOC-FM-FORMAT", doc.fm_line("date"), "date '%s' is not YYYY-MM-DD." % date)
    return t


# ----------------------------------------------------------- requirements

def ears_pattern(text):
    """Return the EARS pattern name of a requirement that has one shall, or None."""
    m = re.search(r"\bshall\b", text, re.I)
    left = text[:m.start()].strip()
    right = text[m.end():].strip().rstrip(".").strip()
    if not right:
        return None
    clauses = re.split(r",\s+", left)
    last = clauses[-1].strip().lower()
    merged = []
    for c in clauses[:-1]:
        first = c.split()[0].lower() if c.split() else ""
        if first in ("while", "when", "where", "if") or not merged:
            merged.append(c.strip())
        else:
            merged[-1] += ", " + c  # a comma inside a trigger does not start a new clause
    seq = [c.split()[0].lower() if c.split() else "" for c in merged]
    the = re.match(r"^the\s+\S", last) is not None
    then_the = re.match(r"^then\s+the\s+\S", last) is not None
    table = {(): ("Ubiquitous", the), ("while",): ("State", the), ("when",): ("Event", the),
             ("where",): ("Option", the), ("if",): ("Unwanted", then_the),
             ("while", "when"): ("Complex", the), ("while", "if"): ("Complex", then_the)}
    hit = table.get(tuple(seq))
    return hit[0] if hit and hit[1] else None


def check_req_line(doc, ids, item, kind):
    no, _indent, _numbered, text = item
    m = re.match(r"^\*\*([^*]+)\*\*\s*(.*)$", text)
    if not m:
        doc.add("block", "DOC-REQ-FORMAT", no, "A requirement starts with a bold ID, as in **FR-001**.")
        return
    rid = m.group(1).strip()
    rest = m.group(2)
    tag = rid if re.match(r"^(?:FR|UB)-\d{3}$", rid) else "Requirement"
    if not re.match(r"^(?:FR|UB)-\d{3}$", rid):
        doc.add("block", "DOC-REQ-ID", no, "ID '%s' is not FR- or UB- plus three digits." % rid)
    else:
        if rid in ids:
            first = ids[rid]
            doc.add("block", "DOC-REQ-DUP", no, "ID %s repeats the one at %s:%d." % (rid, first[0], first[1]))
        else:
            ids[rid] = (doc.path, no)
        if kind and not rid.startswith(kind):
            doc.add("warn", "DOC-REQ-ID", no, "This section uses %s- IDs, not %s-." % (kind, rid[:2]))
    km = re.match(r"^\(([^)]*)\)\s*(:?)\s*(.*)$", rest)
    if not km:
        doc.add("block", "DOC-REQ-KIND", no,
                "%s has no coverage kind. Write (test), (visual), (smoke) or (device) after the ID." % tag)
        body = rest.lstrip(": ")
    else:
        if km.group(1) not in KINDS:
            doc.add("block", "DOC-REQ-KIND", no,
                    "%s: coverage kind '%s' is not test, visual, smoke or device." % (tag, km.group(1)))
        if not km.group(2):
            doc.add("block", "DOC-REQ-FORMAT", no, "%s: put a colon after the coverage kind." % tag)
        body = km.group(3)
    masked = _QUOTED.sub("X", _CODE_SPAN.sub("X", body)).replace("*", "")
    shalls = len(re.findall(r"\bshall\b", masked, re.I))
    if shalls != 1:
        doc.add("block", "DOC-REQ-SHALL", no, "%s has %d 'shall'. It needs exactly one." % (tag, shalls))
    elif not ears_pattern(masked):
        doc.add("block", "DOC-REQ-EARS", no,
                "%s is not an EARS pattern. Use 'The <system> shall ...', or start with While, When, Where or If ... then."
                % tag)


def check_requirements(doc, ids, secs, designated, required=None):
    """Check requirement lines. `designated` maps a section name to its ID prefix (FR or UB)."""
    lines = doc.lines
    items = ste.collect_items(lines, 0, len(lines))
    done = set()
    count = {}
    for name, prefix in designated.items():
        s = find(secs, name)
        if not s:
            continue
        own = [i for i in items if s["idx"] < i[0] - 1 < s["end"]]
        base = min([i[1] for i in own]) if own else 0
        count[name] = 0
        for it in own:
            if it[1] == base:
                check_req_line(doc, ids, it, prefix)
                done.add(it[0])
                count[name] += 1
        cont = False
        for ln in lines[s["idx"] + 1:s["end"]]:
            if ln.kind == "item":
                cont = True
            elif ln.kind == "text" and not cont and _BOLD_REQ.match(ln.text):
                doc.add("block", "DOC-REQ-FORMAT", ln.no, "Write each requirement as one list item.")
            elif ln.kind != "text":
                cont = False
    for it in items:
        if it[0] not in done and _BOLD_REQ.match(it[3]):
            check_req_line(doc, ids, it, None)
    if required and required in count and count[required] == 0:
        doc.add("block", "DOC-REQ-NONE", find(secs, required)["no"], "Section '%s' has no requirement lines." % required)


# ------------------------------------------------------------ design log

def check_qa(doc, lo, hi, approval):
    lines = doc.lines
    qs = [i for i in range(lo, hi) if lines[i].kind == "text" and re.match(r"^Q\d+:", lines[i].text)]
    for n, qi in enumerate(qs):
        qn = re.match(r"^Q(\d+):", lines[qi].text).group(1)
        j = qi + 1
        while j < hi and lines[j].kind == "blank":
            j += 1
        answer = None
        if j < hi and lines[j].kind == "text":
            m = re.match(r"^A:\s*(.*)$", lines[j].text)
            if m:
                stop = qs[n + 1] if n + 1 < len(qs) else hi
                parts = [m.group(1)]
                for k in range(j + 1, stop):
                    if lines[k].kind == "heading":
                        break
                    if lines[k].kind in ("text", "item"):
                        parts.append(lines[k].text)
                answer = " ".join(p for p in parts if p).strip()
        if approval:
            if answer is None:
                why = "no A: line follows"
            elif not answer:
                why = "the answer is empty"
            elif re.match(r"open\b", answer, re.I):
                why = "the answer says open"
            else:
                continue
            doc.add("block", "DOC-QA-OPEN", lines[qi].no, "Q%s is open: %s. Answer it before approval." % (qn, why))


def check_design_log(doc, approval, ids):
    lines = doc.lines
    track = doc.fm.get("track")
    status = doc.fm.get("status")
    secs = sections(lines, 2)
    required = list(DL_REQUIRED)
    if track == "small":
        required.append("Requirements")
    if status == "done":
        required.append("Results")
    seen = {}
    top = -1
    for s in secs:
        name = s["name"]
        if name not in DL_ORDER:
            doc.add("warn", "DOC-SECTION-UNKNOWN", s["no"], "Unknown section '%s'. Use the sections that docs.md lists." % name)
            continue
        if name in seen:
            doc.add("block", "DOC-SECTION-DUP", s["no"], "Section '%s' appears twice." % name)
            continue
        seen[name] = s
        pos = DL_ORDER.index(name)
        if pos < top:
            later = DL_ORDER[top]
            doc.add("block", "DOC-SECTION-ORDER", s["no"], "Section '%s' must come before '%s'." % (name, later))
        top = max(top, pos)
        if name not in required and not has_content(lines, s["idx"] + 1, s["end"]):
            doc.add("warn", "DOC-SECTION-EMPTY", s["no"], "Section '%s' is empty. Leave it out." % name)
    for name in required:
        if name not in seen:
            doc.add("block", "DOC-SECTION-MISSING", doc.body_line, "Missing section '## %s'." % name)

    s = seen.get("Decisions for the implementer")
    if s:
        n = len(top_items(lines, s["idx"] + 1, s["end"]))
        if not DECISIONS_RANGE[0] <= n <= DECISIONS_RANGE[1]:
            doc.add("warn", "DOC-DECISIONS-COUNT", s["no"], "Decisions has %s. Use %d to %d."
                    % (count_of(n, "bullet"), DECISIONS_RANGE[0], DECISIONS_RANGE[1]))
    s = seen.get("Problem")
    if s:
        subs = [i for i in range(s["idx"] + 1, s["end"]) if lines[i].kind == "heading"]
        lead_end = subs[0] if subs else s["end"]
        n = sum(len(u.sents) for u in ste.units_of(lines[s["idx"] + 1:lead_end]))
        if not PROBLEM_RANGE[0] <= n <= PROBLEM_RANGE[1]:
            doc.add("warn", "DOC-PROBLEM-SENTENCES", s["no"], "Problem has %s. Use %d to %d."
                    % (count_of(n, "sentence"), PROBLEM_RANGE[0], PROBLEM_RANGE[1]))
        if track == "fix":
            names = [" ".join(lines[i].text.split()) for i in subs if lines[i].level == 3]
            for want in FIX_SUBSECTIONS:
                if want not in names:
                    doc.add("block", "DOC-FIX-SECTIONS", s["no"], "A fix needs the subsection '### %s' under Problem." % want)
    s = seen.get("Questions and answers")
    if s:
        check_qa(doc, s["idx"] + 1, s["end"], approval)
    check_requirements(doc, ids, secs, {"Requirements": None, "Unchanged behaviour": "UB"},
                       "Requirements" if track == "small" else None)
    s = seen.get("Results")
    if s:
        entries = [i for i in range(s["idx"] + 1, s["end"]) if lines[i].kind == "heading" and lines[i].level == 3]
        for i in entries:
            if not re.match(r"^\d{4}-\d{2}-\d{2}\b", lines[i].text):
                doc.add("block", "DOC-RESULTS-DATE", lines[i].no, "A Results entry starts with a date, as in ### 2026-10-04.")
        if status == "done":
            last = entries[-1] if entries else None
            body = [ln.text for ln in lines[last + 1:s["end"]]] if last is not None else []
            if not any(re.search(r"\b\d+\s*/\s*\d+\s+requirements?\s+verified\b", t, re.I) for t in body):
                doc.add("block", "DOC-RESULTS-FINAL", lines[last].no if last is not None else s["no"],
                        "The last Results entry needs a line 'X/Y requirements verified'.")


# -------------------------------------------------- other document types

def check_prd(doc):
    lines = doc.lines
    secs = sections(lines, 2)
    for name in PRD_SECTIONS:
        if not find(secs, name):
            doc.add("block", "DOC-SECTION-MISSING", doc.body_line, "Missing section '## %s'." % name)
    s = find(secs, "Risks")
    if s:
        tier = re.compile(r"(?<![\w])(?:high|medium|low)(?![\w])", re.I)
        for no, _i, _n, text in top_items(lines, s["idx"] + 1, s["end"]):
            if not tier.search(text):
                doc.add("block", "DOC-PRD-RISK-TIER", no, "Risk has no tier. Add high, medium or low.")
        prev = None
        rows = 0
        for ln in lines[s["idx"] + 1:s["end"]]:
            if ln.kind == "table":
                rows = rows + 1 if prev == "table" else 1
                if rows > 2 and not tier.search(ln.text):
                    doc.add("block", "DOC-PRD-RISK-TIER", ln.no, "Risk has no tier. Add high, medium or low.")
            prev = ln.kind
    s = find(secs, "Scenarios")
    if s and not any(i[2] for i in ste.collect_items(lines, s["idx"] + 1, s["end"])):
        doc.add("warn", "DOC-PRD-SCENARIOS", s["no"], "Scenarios are not a numbered list.")


def check_spec(doc, ids):
    secs = sections(doc.lines, 2)
    if not find(secs, "Requirements"):
        doc.add("block", "DOC-SECTION-MISSING", doc.body_line, "Missing section '## Requirements'.")
    check_requirements(doc, ids, secs, {"Requirements": None, "Unchanged behaviour": "UB"}, "Requirements")
    s = find(secs, "Unchanged behaviour")
    if s and not has_content(doc.lines, s["idx"] + 1, s["end"]):
        doc.add("warn", "DOC-SECTION-EMPTY", s["no"], "Section 'Unchanged behaviour' is empty. Leave it out.")


def check_adr(doc):
    lines = doc.lines
    secs = sections(lines, 2)
    for name in ADR_SECTIONS:
        if not find(secs, name):
            doc.add("block", "DOC-SECTION-MISSING", doc.body_line, "Missing section '## %s'." % name)
    s = find(secs, "Considered Options")
    if s:
        end = next((i for i in range(s["idx"] + 1, s["end"]) if lines[i].kind == "heading"), s["end"])
        n = len(top_items(lines, s["idx"] + 1, end))
        if n < 2:
            doc.add("block", "DOC-ADR-OPTIONS", s["no"],
                    "Considered Options has %s. List two or more options." % count_of(n, "bullet"))
    if not re.match(r"^\d{4}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$", os.path.basename(doc.path)):
        doc.add("warn", "DOC-ADR-NAME", 1, "ADR file name is not NNNN-title-with-dashes.md.")


def check_architecture(doc):
    seen = {}
    for ln in doc.lines:
        if ln.kind != "heading" or ln.level != 3:
            continue
        text = ln.text.replace("`", "").strip()
        m = re.match(r"^(ARCH-[A-Z0-9]+(?:-[A-Z0-9]+)*)(?:\s|$)", text)
        if not m:
            if text.upper().startswith("ARCH"):
                doc.add("block", "DOC-ARCH-ID", ln.no, "Rule ID '%s' does not match ARCH- plus capitals, digits and hyphens." % text)
            else:
                doc.add("warn", "DOC-ARCH-ID", ln.no, "Level-3 heading '%s' is not a rule ID." % text)
        elif m.group(1) in seen:
            doc.add("block", "DOC-ARCH-DUP", ln.no, "Rule ID %s repeats line %d." % (m.group(1), seen[m.group(1)]))
        else:
            seen[m.group(1)] = ln.no
    if not seen:
        doc.add("warn", "DOC-ARCH-NONE", 1, "No '### ARCH-...' rule headings.")


def check_clarify(doc):
    for ln in doc.lines:
        if ln.kind in ("heading", "text", "item", "table") and _CLARIFY.search(_CODE_SPAN.sub(" ", ln.text)):
            doc.add("block", "DOC-CLARIFY", ln.no, "An open point remains: [NEEDS CLARIFICATION]. Settle it before approval.")


def lint_doc(doc, approval, ids, recs):
    t = check_front(doc)
    check_lock(doc, recs)
    if approval:
        check_clarify(doc)
    if t == "design-log":
        check_design_log(doc, approval, ids)
    elif t == "prd":
        check_prd(doc)
    elif t == "spec":
        check_spec(doc, ids)
    elif t == "adr":
        check_adr(doc)
    elif t == "architecture":
        check_architecture(doc)
    if t in BUDGETS:
        stop = None
        if t == "design-log":
            s = find(sections(doc.lines, 2), "Results")
            stop = s["no"] if s else None
        words = count_words(doc, stop)
        if words > BUDGETS[t]:
            doc.add("block" if approval else "warn", "DOC-BUDGET", 1,
                    "The %s has %d words. The budget is %d." % (t, words, BUDGETS[t]))
    doc.findings.sort(key=lambda f: (f["line"], f["rule"]))


def check_folder(folder, docs):
    """Check that a change folder holds the documents of its track."""
    here = os.path.abspath(folder)
    names = dict((os.path.basename(d.path), d) for d in docs
                 if os.path.dirname(os.path.abspath(d.path)) == here)
    if not any(n in names for n in ("design-log.md", "prd.md", "spec.md")):
        return []
    out = []
    log = names.get("design-log.md")
    if not log:
        out.append(ste.finding(folder, 1, "block", "DOC-FILE-MISSING", "The change folder has no design-log.md."))
        return out
    track = (log.fm or {}).get("track")
    if track == "full":
        for need in ("prd.md", "spec.md"):
            if need not in names:
                out.append(ste.finding(folder, 1, "block", "DOC-FILE-MISSING", "A full change needs %s." % need))
    elif track in TRACKS:
        for extra in ("prd.md", "spec.md"):
            if extra in names:
                out.append(ste.finding(names[extra].path, 1, "warn", "DOC-FILE-EXTRA",
                                       "%s is for the full track. This change is %s." % (extra, track)))
    return out


# -------------------------------------------------------------------- cli

def build_parser():
    p = ste._Parser(prog="cmd_doclint.py", allow_abbrev=False,
                    description="Check the structure of ratchet change documents.")
    p.add_argument("paths", nargs="*", help="document files or a change folder")
    p.add_argument("--approval", action="store_true", help="apply the approval-time checks")
    p.add_argument("--approve", metavar="FILE", help="check FILE for approval, then lock its body")
    p.add_argument("--lock-file", help="lock file (default: <git root>/.claude/ratchet/docs.lock)")
    p.add_argument("--out", help="write the full findings to this file")
    p.add_argument("--format", choices=("json", "text"), default="json")
    p.add_argument("--nonce", help="echo this value in the result")
    return p


def run(args):
    if not args.paths and not args.approve:
        raise UsageError("give one or more files or folders")
    pairs = [(f, g) for f, g in ste.expand_paths(args.paths)
             if g is None or os.path.basename(f) != "index.md"]
    approve_real = None
    if args.approve:
        if not os.path.isfile(args.approve):
            raise UsageError("no such file: %s" % args.approve)
        approve_real = os.path.realpath(args.approve)
        if not any(os.path.realpath(f) == approve_real for f, _ in pairs):
            pairs.append((args.approve, None))
    findings = []
    docs = {}
    ids = {}
    locks = {}
    groups = {}
    for f, group in pairs:
        with open(f, "rb") as fh:
            doc = Doc(f, fh.read())
        lockpath = args.lock_file or default_lock_path(f)
        if lockpath not in locks:
            locks[lockpath] = read_lock(lockpath)
        approval = args.approval or os.path.realpath(f) == approve_real
        lint_doc(doc, approval, ids.setdefault(group or f, {}), locks[lockpath])
        findings.extend(doc.findings)
        docs[os.path.realpath(f)] = (doc, lockpath)
        if group is not None:
            groups.setdefault(group, []).append(doc)
    for group, members in groups.items():
        findings.extend(check_folder(group, members))
    blocking, warns = ste.tally(findings)
    extra = {"files": len(pairs), "blocking": blocking, "warnings": warns}
    summary = "%d block, %d warn in %d files" % (blocking, warns, len(pairs))
    if args.approve and not blocking:
        doc, lockpath = docs[approve_real]
        rec = write_lock(lockpath, doc)
        extra["approved"] = ste.repo_rel(args.approve)
        extra["lock"] = ste.repo_rel(lockpath)
        summary = "approved %s (%d bytes); %d warn" % (rec["path"], rec["bytes"], warns)
    return ste.emit(CMD, args.nonce, args.format, args.out, "fail" if blocking else "pass",
                    summary, findings, extra)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    nonce = ste.peek_option(argv, "--nonce")
    fmt = "text" if ste.peek_option(argv, "--format") == "text" else "json"
    try:
        return run(build_parser().parse_intermixed_args(argv))
    except UsageError as e:
        return ste.fail(CMD, nonce, fmt, str(e))
    except OSError as e:
        return ste.fail(CMD, nonce, fmt, "cannot read or write a file: %s" % e)
    except Exception as e:  # the engine needs a JSON error, never a bare traceback
        traceback.print_exc()
        return ste.fail(CMD, nonce, fmt, "internal error: %s" % e)


if __name__ == "__main__":
    sys.exit(main())
