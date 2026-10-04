"""The scheduling side of the dream: the launchd job, the state of the dream, and the reflection prompt."""
from __future__ import annotations

import os
import plistlib
import re
import shlex
import shutil
import time

import common
import dream_io
from common import RsError

LABEL = "com.ratchet.dream"
HOUR, MINUTE = 3, 30
PROMPT_TAIL = """
## Files for this run

You run inside the dream folder, and you can read only inside it. Every path is relative to it.

- harvest.json: the facts of the window. It can be long: read it in parts, with offset and limit.
- context/global-rules.md: the active global rules, each with its id
- context/memory-<project>.md: the MEMORY.md index of each project that has human turns
- context/ratchet-<n>-learnings.md: the learnings of one repo (context/ratchet-map.json names the repo of each n)
- context/rejected.jsonl: items that the human rejected

Do not write a file. Your final answer is the candidates JSON, and nothing else.
"""


def skill_dir():
    return os.path.dirname(os.path.dirname(common.rs_script()))


def plist_path():
    return os.path.join(dream_io.home_dir(), "Library", "LaunchAgents", LABEL + ".plist")


def domain():
    return "gui/%d" % os.getuid()


def launchd_env():
    """launchd starts a job with PATH=/usr/bin:/bin:/usr/sbin:/sbin, so name claude and its runtime here.

    No token goes in: Claude Code reads its own login from the keychain."""
    env = {}
    dirs = []
    claude = shutil.which(os.environ.get("RATCHET_CLAUDE") or "claude")
    if claude:
        claude = os.path.abspath(claude)
        env["RATCHET_CLAUDE"] = claude
        dirs += [os.path.dirname(claude), os.path.dirname(os.path.realpath(claude))]
    dirs += [os.path.join(dream_io.home_dir(), ".local", "bin"), "/opt/homebrew/bin", "/usr/local/bin",
             "/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    env["PATH"] = ":".join(d for i, d in enumerate(dirs) if d not in dirs[:i])
    # python3 resolves through PATH. A versioned path such as .../python@3.14/bin would break on an upgrade.
    for name in ("RS_PYTHON", "RATCHET_HOME"):
        if os.environ.get(name):
            env[name] = os.environ[name]
    return env, claude


LAUNCHER = """#!/bin/bash
# Written by `ratchet.sh dream install`. The installed plugin path holds its version, and an
# upgrade removes the old one, so look for the newest dream-nightly.sh each night.
set -u
pick=""
for f in "$HOME"/.claude/plugins/cache/*/ratchet/*/skills/ratchet/scripts/dream-nightly.sh; do
  [ -f "$f" ] || continue
  if [ -z "$pick" ] || [ "$f" -nt "$pick" ]; then pick="$f"; fi
done
[ -n "$pick" ] || pick=%s
exec /bin/bash "$pick"
"""


def write_launcher(script):
    path = os.path.join(dream_io.ratchet_home(), "dream-launch.sh")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    common.write_text(path, LAUNCHER % shlex.quote(script))
    os.chmod(path, 0o755)
    return path


def install(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",), bool_flags=("--load",))
    except RsError as e:
        return common.emit("dream install", "error", str(e), harness_error=str(e))

    def go():
        if pos:
            raise RsError("usage: dream install [--load]")
        script = os.path.join(os.path.dirname(common.rs_script()), "dream-nightly.sh")
        if not os.path.isfile(script):
            raise RsError("missing %s" % script)
        log = os.path.join(dream_io.ratchet_home(), "dream.log")
        launcher = write_launcher(script)
        plist = plist_path()
        env, claude = launchd_env()
        data = {"Label": LABEL, "ProgramArguments": ["/bin/bash", launcher],
                "StartCalendarInterval": {"Hour": HOUR, "Minute": MINUTE},
                # launchd does not expand ~ and does not create the folder of a log file.
                "StandardOutPath": log, "StandardErrorPath": log, "EnvironmentVariables": env}
        os.makedirs(os.path.dirname(plist), exist_ok=True)
        os.makedirs(os.path.dirname(log), exist_ok=True)
        tmp = plist + ".tmp%d" % os.getpid()
        with open(tmp, "wb") as f:
            plistlib.dump(data, f)
        os.replace(tmp, plist)
        created = dream_io.write_default_config()
        cfg = dream_io.load_config()

        command = "launchctl bootstrap %s %s" % (domain(), shlex.quote(plist))
        warnings = []
        if not claude:
            warnings.append("claude not found: set RATCHET_CLAUDE and run install again")
        if cfg["nightly"] is not True:
            warnings.append("nightly is not true in dream.json, so the job skips every night")
        loaded = False
        if opts.get("--load"):
            # bootstrap fails on a label that is loaded already, so unload it first.
            common.run(["launchctl", "bootout", "%s/%s" % (domain(), LABEL)])
            rc, out, err = common.run(["launchctl", "bootstrap", domain(), plist])
            if rc != 0:
                raise RsError("launchctl bootstrap failed: %s" % (err.strip() or out.strip())[:160])
            loaded = True
        summary = "wrote the plist for %02d:%02d" % (HOUR, MINUTE)
        summary += "; the job is loaded" if loaded else "; load it with: %s" % command
        return common.emit("dream install", "pass", summary, nonce=opts.get("--nonce"),
                           extra={"plistAbs": plist, "logAbs": log, "configAbs": dream_io.config_path(),
                                  "configCreated": created, "loaded": loaded, "command": command,
                                  "warnings": warnings})

    return common.run_guarded("dream install", opts.get("--nonce"), go)


def uninstall(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",), bool_flags=("--unload",))
    except RsError as e:
        return common.emit("dream uninstall", "error", str(e), harness_error=str(e))

    def go():
        if pos:
            raise RsError("usage: dream uninstall [--unload]")
        plist = plist_path()
        removed = os.path.isfile(plist)
        if removed:
            os.remove(plist)
        command = "launchctl bootout %s/%s" % (domain(), LABEL)
        unloaded = False
        if opts.get("--unload"):
            unloaded = common.run(["launchctl", "bootout", "%s/%s" % (domain(), LABEL)])[0] == 0
        summary = "removed the plist" if removed else "no plist to remove"
        # Removing the file does not stop a job that launchd loaded already.
        summary += "; the job is unloaded" if unloaded else "; stop a loaded job with: %s" % command
        return common.emit("dream uninstall", "pass", summary, nonce=opts.get("--nonce"),
                           extra={"plistAbs": plist, "removed": removed, "unloaded": unloaded,
                                  "command": command})

    return common.run_guarded("dream uninstall", opts.get("--nonce"), go)


def state(argv):
    """One line: due, recent, pending or off, with the number of proposals that wait for a review."""
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("dream state", "error", str(e), harness_error=str(e))

    def go():
        if pos:
            raise RsError("usage: dream state")
        cfg = dream_io.load_config()
        pending = dream_io.pending_bundles()
        last = dream_io.last_epoch(dream_io.read_last())
        if pending:
            st = "pending"
        elif cfg["nightly"] is not True:
            st = "off"
        elif last is not None and (time.time() - last) < dream_io.NIGHTLY_HOURS * 3600:
            st = "recent"
        else:
            st = "due"
        dream_io.refresh_pending()
        waiting = sum(dream_io.pending_items(b) for b in pending)
        return common.emit("dream state", "pass", "the dream is %s" % st, nonce=opts.get("--nonce"),
                           root=dream_io.home_dir(),
                           extra={"state": st, "pending": waiting, "bundle": pending[0] if pending else None,
                                  "budgetUsd": cfg["budgetUsd"], "last": dream_io.iso_of(last) if last else None})

    return common.run_guarded("dream state", opts.get("--nonce"), go)


def reflect_parts():
    """(body, model) of agents/reflect.md. The frontmatter holds the model and is not part of the prompt."""
    path = os.path.normpath(os.path.join(skill_dir(), "..", "..", "agents", "reflect.md"))
    text = common.read_text(path)
    if not text.strip():
        raise RsError("missing %s" % path)
    model = "sonnet"
    m = re.match(r"^---[ \t]*\n(.*?)\n---[ \t]*\n", text, re.S)
    if m:
        text = text[m.end():]
        mm = re.search(r"^model:[ \t]*(\S+)", m.group(1), re.M)
        if mm and re.fullmatch(r"[A-Za-z0-9._\[\]-]+", mm.group(1)):
            model = mm.group(1)
    return text.strip(), model


def prompt(argv):
    try:
        pos, opts = common.parse_args(argv, value_flags=("--nonce",))
    except RsError as e:
        return common.emit("dream prompt", "error", str(e), harness_error=str(e))

    def go():
        if len(pos) != 1:
            raise RsError("usage: dream prompt <bundle>")
        cfg = dream_io.load_config()
        bid = dream_io.check_bundle(pos[0])
        bdir = dream_io.bundle_dir(bid)
        if not os.path.isfile(os.path.join(bdir, "harvest.json")):
            raise RsError("no harvest.json in dream %s" % bid)
        body, model = reflect_parts()
        out = os.path.join(bdir, "prompt.md")
        common.write_text(out, body + "\n" + PROMPT_TAIL)
        return common.emit("dream prompt", "pass", "prompt written for dream %s" % bid, evidence=out,
                           nonce=opts.get("--nonce"), root=dream_io.home_dir(),
                           extra={"bundle": bid, "model": model, "budgetUsd": cfg["budgetUsd"]})

    return common.run_guarded("dream prompt", opts.get("--nonce"), go)
