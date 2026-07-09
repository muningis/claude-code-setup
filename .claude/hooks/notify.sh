#!/usr/bin/env bash
# Claude Code notifier — native macOS banner that tells you WHICH of your
# parallel sessions needs attention. Wired to the Stop and Notification hooks.
# stdin: hook JSON { hook_event_name, cwd, message?(Notification), ... }
# Always exits 0 so it can never block or delay a session.

input=$(cat)

# Debug capture — one compact line per invocation so we can see exactly what
# each event delivers (event, notification_type, stop_reason, keys present).
# Remove this block once the notification logic is dialed in.
event=$(printf '%s' "$input" | jq -r '.hook_event_name // empty')
cwd=$(printf '%s'   "$input" | jq -r '.cwd // empty')
msg=$(printf '%s'   "$input" | jq -r '.message // empty')
# Stop carries the final reply in .assistant_message, not .message.
reply=$(printf '%s' "$input" | jq -r '.assistant_message // empty' | tr '\n' ' ')
# Stop also reports still-running background work; used to gate the "done" ping.
bg=$(printf '%s'    "$input" | jq -r '(.background_tasks // []) | length')
crons=$(printf '%s' "$input" | jq -r '(.session_crons // []) | length')

# Debug capture — one compact line per invocation so we can see exactly what
# each event delivers. Remove this block once the notification logic is proven.
if [ -n "${NOTIFY_DEBUG:-1}" ]; then
  printf '%s\t%s\n' "$(date '+%H:%M:%S')" \
    "$(printf '%s' "$input" | jq -c '{event:.hook_event_name, ntype:.notification_type, stop_reason, bg:((.background_tasks//[])|length), crons:((.session_crons//[])|length), cwd:(.cwd|split("/")|last)}' 2>/dev/null)" \
    >> ~/.claude/hooks/notify.log
fi

proj=$(basename "${cwd:-$PWD}")

case "$event" in
  Stop)
    # A turn ended, but if background tasks or crons are still in flight the
    # session isn't actually done — it will wake itself back up. Stay quiet.
    if [ "${bg:-0}" -gt 0 ] || [ "${crons:-0}" -gt 0 ]; then
      exit 0
    fi
    title="✅ ${proj} — done"
    body="${reply:-Finished responding.}"
    # Keep the banner short.
    [ "${#body}" -gt 140 ] && body="${body:0:137}..."
    sound="Glass"
    ;;
  Notification)
    title="🔔 ${proj} — needs you"
    body="${msg:-Waiting for your input.}"
    sound="Funk"
    ;;
  *)
    title="${proj}"
    body="${msg:-$event}"
    sound="Ping"
    ;;
esac

# Escape backslashes then double quotes for the AppleScript string literals.
esc() { printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }

osascript -e "display notification \"$(esc "$body")\" with title \"$(esc "$title")\" sound name \"$sound\"" >/dev/null 2>&1

exit 0
