#!/usr/bin/env bash
# Claude Code statusline. Reads the status JSON on stdin and prints 3 lines:
#   1) current directory
#   2) Model | thinking effort
#   3) context (actual + %) | session $ | 5h usage % | week usage %
# All fields come straight from the statusline JSON (Claude Code >= 2.1).

input=$(cat)

# --- extract everything in one jq pass (one field per line; empties preserved) ---
F=()
while IFS= read -r _line; do F+=("$_line"); done < <(printf '%s' "$input" | jq -r '
  (.workspace.current_dir // .cwd // ""),
  (.model.id // "?"),
  (.effort.level // ""),
  (.context_window.total_input_tokens // 0),
  (.context_window.used_percentage // 0),
  (.cost.total_cost_usd // 0),
  (.rate_limits.five_hour.used_percentage // -1),
  (.rate_limits.seven_day.used_percentage // -1)')
cwd=${F[0]}; model=${F[1]}; effort=${F[2]}
ctx_tokens=${F[3]}; ctx_pct=${F[4]}; cost=${F[5]}; fh=${F[6]}; wk=${F[7]}

# --- colors ---
C_RESET=$'\e[0m'; C_DIM=$'\e[2m'
C_DIR=$'\e[1;34m'; C_MODEL=$'\e[1;36m'; C_EFFORT=$'\e[35m'; C_BRANCH=$'\e[33m'
C_GREEN=$'\e[32m'; C_YELLOW=$'\e[33m'; C_RED=$'\e[31m'; C_COST=$'\e[1;32m'
SEP="${C_DIM} | ${C_RESET}"

# color a value by a 0-100 percentage (green < 50, yellow < 80, red otherwise)
pct_color() { # $1=pct(float)
  awk -v p="$1" 'BEGIN{ if(p<50)print "\033[32m"; else if(p<80)print "\033[33m"; else print "\033[31m" }'
}
round() { awk -v n="$1" 'BEGIN{printf "%d", n+0.5}'; }

# --- line 1: directory (~ for home) + git branch if in a repo ---
dir="${cwd/#$HOME/~}"
[ -z "$dir" ] && dir="?"
branch=""
if [ -n "$cwd" ] && [ -d "$cwd" ]; then
  b=$(git -C "$cwd" rev-parse --abbrev-ref HEAD 2>/dev/null)
  [ -n "$b" ] && branch="${C_DIM} on ${C_RESET}${C_BRANCH} ${b}${C_RESET}"
fi

# --- line 2: model | effort ---
if [ -n "$effort" ]; then
  effort_str="${C_EFFORT}${effort}${C_RESET}"
else
  effort_str="${C_DIM}—${C_RESET}"
fi
line2="${C_MODEL}${model}${C_RESET}${SEP}🧠 ${effort_str}"

# --- line 3: context | cost | 5h | week ---
# context: actual tokens with thousands separators + percentage
tokens_fmt=$(printf "%'d" "${ctx_tokens%.*}" 2>/dev/null || echo "$ctx_tokens")
pctr=$(round "$ctx_pct")
cc=$(pct_color "$ctx_pct")
ctx_str="${cc}${tokens_fmt} (${pctr}%)${C_RESET}"

cost_str="${C_COST}\$$(printf '%.2f' "$cost")${C_RESET}"

fmt_limit() { # $1=pct(-1 if absent) $2=label
  if awk -v v="$1" 'BEGIN{exit !(v<0)}'; then
    printf '%s%s —%s' "$C_DIM" "$2" "$C_RESET"
  else
    printf '%s%s %d%%%s' "$(pct_color "$1")" "$2" "$(round "$1")" "$C_RESET"
  fi
}
fh_str=$(fmt_limit "$fh" "5h")
wk_str=$(fmt_limit "$wk" "wk")

line3="${ctx_str}${SEP}${cost_str}${SEP}${fh_str}${SEP}${wk_str}"

printf '%s%s%s%s\n%s\n%s\n' "$C_DIR" "$dir" "$C_RESET" "$branch" "$line2" "$line3"
