#!/bin/bash
#
# Nightly dream. One global run: harvest what the sessions of the last days said, let a headless claude
# reflect on it, and curate the result into a proposal. It never commits, never pushes, and never
# applies a change: the human approves each item later.
# bash 3.2-compatible (macOS /bin/bash). `ratchet.sh dream install` runs it from launchd at 03:30.
#
#   RATCHET_HOME           replaces ~ (tests)
#   RATCHET_CLAUDE         the claude binary; tests use a fake one
#   RATCHET_DREAM_TIMEOUT  seconds before a reflection is stopped (default 1800)
#   RS_PYTHON              the python3 that ratchet.sh runs

set -u

HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
RS="$HERE/ratchet.sh"
CLAUDE=${RATCHET_CLAUDE:-claude}
TIMEOUT=${RATCHET_DREAM_TIMEOUT:-1800}
DREAMS="${RATCHET_HOME:-$HOME}/.claude/ratchet/dreams"
status=0
last=""

log() { printf '%s dream: %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*"; }

# One field of the one-line JSON object that an RS command prints.
json_str() { sed -n "s/.*\"$1\":\"\([^\"]*\)\".*/\1/p"; }
json_num() { sed -n "s/.*\"$1\":\([0-9][0-9.]*\).*/\1/p"; }

# Run one RS command. Sets $status, and $last to the final line of its output.
rs_step() {
  local out
  out=$(bash "$RS" "$@" 2>&1)
  status=$?
  last=$(printf '%s\n' "$out" | tail -n 1)
}

# The first 160 characters of a failed step, for the log.
why() { printf '%s' "$last" | cut -c1-160; }

rs_step dream state
if [ "$status" -ne 0 ]; then
  log "error, cannot read the state: $(why)"; exit 1
fi
state=$(printf '%s\n' "$last" | json_str state)
case "$state" in
  due) ;;
  recent) log "skipped, the last dream is under 20 h old"; exit 0 ;;
  pending) log "skipped, a proposal waits for review"; exit 0 ;;
  off) log "skipped, nightly is off in dream.json"; exit 0 ;;
  *) log "skipped, the state is ${state:-unknown}"; exit 0 ;;
esac

rs_step dream harvest
if [ "$status" -ne 0 ]; then
  log "error, harvest failed: $(why)"; exit 1
fi
new=$(printf '%s\n' "$last" | json_num new)
if [ "${new:-0}" -eq 0 ]; then
  log "nothing new"; exit 0
fi
bundle=$(printf '%s\n' "$last" | json_str bundle)
if [ -z "$bundle" ]; then
  log "error, harvest named no bundle: $(why)"; exit 1
fi
bdir="$DREAMS/$bundle"
log "harvested ${new} new fact(s) into dream $bundle"

rs_step dream prompt "$bundle"
if [ "$status" -ne 0 ]; then
  log "error, no prompt: $(why)"; exit 1
fi
model=$(printf '%s\n' "$last" | json_str model)
budget=$(printf '%s\n' "$last" | json_num budgetUsd)
log "reflecting with ${model:-sonnet}, budget ${budget:-2} USD"

# The prompt comes first because --allowedTools takes a list and would swallow a later argument.
# RS exec stops a hung run, which would block every later night. It starts its command in the git top
# above the current folder, so the command changes into the bundle itself. The harvest holds text from
# past sessions, so the run is sealed: no CLAUDE.md, plugin, hook or MCP (--safe-mode), file tools
# confined to the bundle (--restricted), and no transcript that a later dream could read.
bash "$RS" exec --timeout "$TIMEOUT" -- sh -c 'cd "$1" && shift && exec "$@"' sh "$bdir" \
  "$CLAUDE" -p "$(cat "$bdir/prompt.md")" --model "${model:-sonnet}" --max-budget-usd "${budget:-2}" \
  --safe-mode --restricted --no-session-persistence --allowedTools Read Write \
  >"$bdir/reflect.log" 2>&1
claude_status=$?

# Curate takes candidates.json, or the answer in reflect.log when the headless run could not write the file.
rs_step dream curate "$bundle"
if [ "$status" -ne 0 ]; then
  log "error, curate failed (claude exit $claude_status, see $bdir/reflect.log): $(why)"; exit 1
fi
note=""
[ "$claude_status" -eq 0 ] || note=" (claude exit $claude_status)"
items=$(printf '%s\n' "$last" | json_num items)
log "proposed ${items:-0} item(s) in dream $bundle$note"
exit 0
