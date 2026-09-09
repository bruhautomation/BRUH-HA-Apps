#!/bin/bash

# brain-ask — ask a one-off question about the home from the terminal.
#
# The same engine the panel's Ask card uses: a single bounded Claude run
# with the Home Assistant MCP tools available and the home's memory in
# context, answering in prose rather than building a card.
#
# Usage:
#   brain ask "why is the garage so cold at night"
#   brain ask --json "how many lights are on"     # raw JSON result

set -uo pipefail

RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

# Background invocations lose the environment run.sh set up. Sourced above
# every `${BRAIN_*:-default}` below: an option copied into a local name before
# the source keeps its fallback for good, because the value arrives afterwards
# under its own name and the alias is never re-read.
if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    . /data/.brain_env
fi

MEMORY_DIR="${BRAIN_MEMORY_DIR:-/config/.brain/memory}"
MEMORY_FILE="$MEMORY_DIR/memory.md"
# No turn cap. A real question about the home often needs live state, then
# history, then statistics, then a cross-check, and a cap tight enough to
# matter ran out mid-investigation. The wall clock (BRAIN_ASK_TIMEOUT) is
# the guard. BRAIN_ASK_MAX_TURNS is an override for somebody who sets one by
# hand, and a run that trips it is landed (brain-landing.sh) — resumed with
# two turns and told to answer with what it has — rather than lost.
MAX_TURNS="${BRAIN_ASK_MAX_TURNS:-0}"
TIMEOUT="${BRAIN_ASK_TIMEOUT:-420}"
MODEL="${BRAIN_ASK_MODEL:-${BRAIN_MODEL:-}}"
MEMORY_BUDGET=4000

usage() {
    cat << 'EOF'
brain ask — ask a question about your home

Usage:
  brain ask "<question>"        Answer in prose
  brain ask --json "<question>" Print the raw JSON result

Reads live Home Assistant state, history, and statistics, plus everything
brAIn has learned about the house. For a saved, recurring answer, use the
Ask card in the panel instead.
EOF
    exit "${1:-0}"
}

resolve_claude() {
    if [ -n "${BRAIN_CLAUDE_BIN:-}" ]; then
        echo "$BRAIN_CLAUDE_BIN"
    elif [ -x /usr/local/bin/claude-run ]; then
        echo "/usr/local/bin/claude-run"
    elif [ "$(id -u)" = "0" ] && command -v su-exec > /dev/null 2>&1; then
        echo "su-exec claude /root/.local/bin/claude"
    else
        echo "claude"
    fi
}

json_mode=false
if [ "${1:-}" = "--json" ]; then
    json_mode=true
    shift
fi

case "${1:-}" in
    ""|help|--help|-h) usage ;;
esac

question="$*"

memory=""
if [ -s "$MEMORY_FILE" ]; then
    memory=$(head -c "$MEMORY_BUDGET" "$MEMORY_FILE")
fi

prompt=$(cat << PROMPT
Answer this question about the home you help run.

QUESTION: ${question}

What you already know about this household:
<<<MEMORY
${memory:-(nothing recorded yet)}
MEMORY

Use the Home Assistant tools to check current state, recent history, or
long-term statistics as needed. Answer in plain prose — a few sentences,
no preamble, no markdown headings. Say plainly when the data cannot
answer the question rather than guessing.
PROMPT
)

claude_cmd=$(resolve_claude)
echo -e "${DIM}Thinking…${NC}" >&2

format=(--output-format text)
$json_mode && format=(--output-format json)

turn_args=()
if [ "${MAX_TURNS:-0}" -gt 0 ] 2>/dev/null; then
    turn_args=(--max-turns "$MAX_TURNS")
fi

# The landing library, from /opt/scripts or beside this script (a checkout).
# With it, a run that ends on a turn cap is resumed and told to answer with
# what it has; without it, a tripped cap is what it was before.
here=$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)
for lib in /opt/scripts/brain-landing.sh "${here:-.}/brain-landing.sh"; do
    if [ -r "$lib" ]; then
        # shellcheck disable=SC1091
        . "$lib"
        break
    fi
done
# Named up front so there is a session to land on. Deliberately unclaimed
# in the run-sources ledger: a question you typed is your own conversation,
# and the Chats rail reads an unclaimed id as exactly that.
session_args=()
ask_session=""
if command -v brain_new_session_id > /dev/null 2>&1; then
    ask_session=$(brain_new_session_id)
    [ -n "$ask_session" ] && session_args=(--session-id "$ask_session")
fi

# stderr is kept until the end: it is what tells a tripped turn cap from a
# login problem, and an older CLI rejecting --session-id from either.
err_file=$(mktemp 2>/dev/null || echo "/tmp/brain-ask-err.$$")

run_ask() {
    # shellcheck disable=SC2086
    printf '%s' "$prompt" | timeout "$TIMEOUT" \
        $claude_cmd -p "${turn_args[@]}" "$@" \
        ${MODEL:+--model "$MODEL"} \
        "${format[@]}" 2>"$err_file"
}

rc=0
ask_started=$(date +%s)
output=$(run_ask "${session_args[@]}") || rc=$?
# An older CLI rejects --session-id by name and dies; the label is optional,
# the answer is not.
if [ "$rc" -ne 0 ] && [ "${#session_args[@]}" -gt 0 ] \
    && grep -qi "unknown option\|unrecognized option" "$err_file" 2>/dev/null; then
    session_args=()
    ask_session=""   # a CLI without --session-id has no --resume either
    rc=0
    output=$(run_ask) || rc=$?
fi
# A run that ended on a turn cap is landed rather than reported.
if [ -n "$ask_session" ] && command -v brain_hit_turn_cap > /dev/null 2>&1 \
    && brain_hit_turn_cap "$output" "$err_file"; then
    echo -e "${DIM}Ran out of room — landing the answer with what it has…${NC}" >&2
    # shellcheck disable=SC2086
    if landed=$(brain_land "$ask_session" "$((TIMEOUT - ($(date +%s) - ask_started)))" \
            "$err_file" -- $claude_cmd -p ${MODEL:+--model "$MODEL"} "${format[@]}"); then
        output="$landed"
        rc=0
    fi
fi
rm -f "$err_file"
if [ "$rc" -ne 0 ]; then
    echo -e "${RED}Could not reach Claude.${NC}" >&2
    echo -e "${DIM}Check you're logged in — run 'claude' in the terminal, or open the panel.${NC}" >&2
    exit 1
fi

if [ -z "${output//[[:space:]]/}" ]; then
    echo -e "${RED}Claude returned nothing.${NC}" >&2
    exit 1
fi

printf '%s\n' "$output"
