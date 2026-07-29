#!/bin/bash

# brain-learn — run a study session: a bounded agentic pass whose
# deliverable is KNOWLEDGE, not a dashboard card.
#
# Claude mines the registry, live state, history, and long-term statistics
# for one topic and emits:
#   - durable facts        -> the memory inbox, for the consolidator
#   - up to 3 hypotheses   -> pending guesses awaiting a yes/no
#   - a short field report -> printed, and kept as the topic's last report
#
# Facts never bypass the inbox, so a bad study session can't corrupt the
# memory document: the consolidator's checks still gate everything.
#
# A curriculum tracks when each topic was last studied, so `brain learn`
# with no argument picks whatever has gone stalest.
#
# Usage:
#   brain learn                 Study the stalest topic
#   brain learn energy          Study a named topic
#   brain learn --list          Show the curriculum and when each was studied
#   brain learn "<free text>"   Study something not in the curriculum

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

MEMORY_DIR="${BRAIN_MEMORY_DIR:-/config/.brain/memory}"
INBOX_DIR="$MEMORY_DIR/inbox"
HYPOTHESES_FILE="$MEMORY_DIR/hypotheses.jsonl"
CURRICULUM_FILE="$MEMORY_DIR/curriculum.json"
REPORTS_DIR="$MEMORY_DIR/reports"
MEMORY_FILE="$MEMORY_DIR/memory.md"

MAX_TURNS="${BRAIN_LEARN_MAX_TURNS:-14}"
TIMEOUT="${BRAIN_LEARN_TIMEOUT:-600}"
MODEL="${BRAIN_LEARN_MODEL:-${BRAIN_MODEL:-}}"
MEMORY_BUDGET=4000
# The hypothesis queue is deliberately tiny: a long list of open questions
# is what made the old design unusable.
MAX_OPEN_HYPOTHESES="${BRAIN_MAX_HYPOTHESES:-3}"

if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    . /data/.brain_env
fi

# topic-id|Human label|what to actually look at
CURRICULUM=(
    "naming|Naming and areas|How entities, areas, and floors are named and organised; which names are inconsistent or misleading."
    "presence|Occupancy rhythms|When the house is occupied, when people wake and sleep, weekday vs weekend patterns."
    "energy|Energy patterns|Baseline consumption, the biggest consumers, unusual draw, and how usage varies by day and season."
    "climate|Comfort and climate|How temperature and humidity behave per room, which rooms drift, how heating and cooling actually run."
    "devices|Device reliability|Which devices go unavailable, drop off, report implausible values, or have failing batteries."
    "automations|Automation behaviour|Which automations fire often, which never fire, and which appear to fight each other."
    "lighting|Lighting habits|Which lights are used, when, at what brightness, and which are effectively unused."
)

usage() {
    cat << 'EOF'
brain learn — study the home and write down what it finds

Usage:
  brain learn                 Study whatever has gone stalest
  brain learn <topic>         Study a named topic
  brain learn "<free text>"   Study something off-curriculum
  brain learn --list          Show the curriculum

Topics: naming, presence, energy, climate, devices, automations, lighting

A session reads live state, history, and long-term statistics, then files
durable facts into the memory inbox and leaves at most a few hypotheses
for you to confirm. Nothing it finds reaches the memory document without
going through the usual consolidation checks.
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

topic_field() {  # topic_field <id> <1=label|2=brief>
    local id="$1" field="$2" entry
    for entry in "${CURRICULUM[@]}"; do
        if [ "${entry%%|*}" = "$id" ]; then
            case "$field" in
                1) echo "$entry" | cut -d'|' -f2 ;;
                2) echo "$entry" | cut -d'|' -f3 ;;
            esac
            return 0
        fi
    done
    return 1
}

last_studied() {  # epoch seconds, 0 if never
    [ -s "$CURRICULUM_FILE" ] || { echo 0; return; }
    jq -r --arg t "$1" '.[$t].ts // 0' "$CURRICULUM_FILE" 2>/dev/null || echo 0
}

record_studied() {
    local topic="$1" now
    now=$(date +%s)
    mkdir -p "$MEMORY_DIR"
    local existing='{}'
    [ -s "$CURRICULUM_FILE" ] && existing=$(cat "$CURRICULUM_FILE")
    printf '%s' "$existing" | jq --arg t "$topic" --argjson ts "$now" \
        '.[$t] = {"ts": $ts}' > "${CURRICULUM_FILE}.tmp" 2>/dev/null \
        && mv "${CURRICULUM_FILE}.tmp" "$CURRICULUM_FILE"
}

cmd_list() {
    echo -e "${CYAN}Curriculum${NC}"
    echo ""
    local entry id label ts
    for entry in "${CURRICULUM[@]}"; do
        id="${entry%%|*}"
        label=$(echo "$entry" | cut -d'|' -f2)
        ts=$(last_studied "$id")
        if [ "${ts:-0}" -gt 0 ] 2>/dev/null; then
            printf "  %-12s %-24s ${DIM}studied %s${NC}\n" "$id" "$label" \
                "$(date -d "@$ts" '+%b %d' 2>/dev/null || echo '?')"
        else
            printf "  %-12s %-24s ${YELLOW}never studied${NC}\n" "$id" "$label"
        fi
    done
    echo ""
    echo -e "Study one with: ${CYAN}brain learn <topic>${NC}"
}

# The stalest topic: never-studied first, then oldest.
pick_stalest() {
    local best="" best_ts="" entry id ts
    for entry in "${CURRICULUM[@]}"; do
        id="${entry%%|*}"
        ts=$(last_studied "$id")
        [ -z "${ts//[0-9]/}" ] || ts=0
        if [ -z "$best" ] || [ "$ts" -lt "$best_ts" ]; then
            best="$id"
            best_ts="$ts"
        fi
    done
    echo "$best"
}

open_hypothesis_count() {
    [ -s "$HYPOTHESES_FILE" ] || { echo 0; return; }
    jq -s '[.[] | select(.status == "open")] | length' "$HYPOTHESES_FILE" 2>/dev/null || echo 0
}

case "${1:-}" in
    --list|list)     cmd_list; exit 0 ;;
    help|--help|-h)  usage ;;
esac

# ---------------------------------------------------------------------------
# Resolve the topic
# ---------------------------------------------------------------------------
topic_id=""
topic_label=""
topic_brief=""

if [ $# -eq 0 ]; then
    topic_id=$(pick_stalest)
    topic_label=$(topic_field "$topic_id" 1)
    topic_brief=$(topic_field "$topic_id" 2)
    echo -e "${DIM}No topic given — studying the stalest: ${topic_label}${NC}" >&2
elif topic_label=$(topic_field "$1" 1 2>/dev/null) && [ -n "$topic_label" ]; then
    topic_id="$1"
    topic_brief=$(topic_field "$topic_id" 2)
else
    # Free-text topic: still studied, just not tracked in the curriculum.
    topic_id=""
    topic_label="$*"
    topic_brief="$*"
fi

open_count=$(open_hypothesis_count)
remaining=$((MAX_OPEN_HYPOTHESES - open_count))
[ "$remaining" -lt 0 ] && remaining=0

memory=""
[ -s "$MEMORY_FILE" ] && memory=$(head -c "$MEMORY_BUDGET" "$MEMORY_FILE")

hypothesis_rule="You may propose up to ${remaining} hypotheses."
if [ "$remaining" -eq 0 ]; then
    hypothesis_rule="The homeowner already has ${open_count} guesses waiting on them. Propose NO hypotheses this run — return an empty list."
fi

prompt=$(cat << PROMPT
You are studying one aspect of a home in order to LEARN it. Your output is
knowledge, not advice and not a report for its own sake.

TOPIC: ${topic_label}
WHAT TO LOOK AT: ${topic_brief}

Today is $(date -u +%Y-%m-%d).

What you already know about this household:
<<<MEMORY
${memory:-(nothing recorded yet)}
MEMORY

Investigate with the Home Assistant tools: the registries for structure,
current state for a snapshot, history for recent behaviour, and long-term
statistics for patterns over weeks. Look for what is TRUE of this specific
house and would still be true next month.

Then output ONE JSON object and nothing else — no prose, no code fences:

{
  "report": "2-4 sentences a person would actually want to read",
  "facts": ["durable, specific, one sentence each"],
  "hypotheses": ["a guess you are fairly confident of, phrased so it can be answered yes or no"]
}

Rules for "facts":
- Durable properties of this home, not the current snapshot. "The dryer
  draws ~3 kWh per cycle" is a fact; "the dryer is on" is not.
- Specific and checkable. No advice, no recommendations, no hedging.
- Never restate something already in the memory above.
- Omit rather than pad. Zero facts is a valid, honest result.

Rules for "hypotheses":
- ${hypothesis_rule}
- Only things you genuinely believe and that would change how you read
  this home, phrased for a yes/no answer: "The garage fridge is meant to
  run 24/7 — right?"
- Never ask an open-ended question, and never ask what the data can tell
  you on its own.
PROMPT
)

claude_cmd=$(resolve_claude)
echo -e "${CYAN}Studying: ${topic_label}${NC}" >&2
echo -e "${DIM}This runs a bounded agentic session and may take a minute…${NC}" >&2

# shellcheck disable=SC2086
if ! output=$(printf '%s' "$prompt" | timeout "$TIMEOUT" \
        $claude_cmd -p --max-turns "$MAX_TURNS" \
        ${MODEL:+--model "$MODEL"} 2>/dev/null); then
    echo -e "${RED}Study session failed — could not reach Claude, or it timed out.${NC}" >&2
    echo -e "${DIM}Nothing was written. Check you're logged in and try again.${NC}" >&2
    exit 1
fi

# Tolerate a stray code fence even though we asked for none.
json=$(printf '%s' "$output" | sed -e 's/^```\(json\)\?$//' -e 's/^```$//' \
    | jq -c 'if type == "object" then . else empty end' 2>/dev/null | head -1)

if [ -z "$json" ]; then
    echo -e "${RED}Study session returned something unparseable — nothing written.${NC}" >&2
    exit 1
fi

report=$(printf '%s' "$json" | jq -r '.report // ""')
mapfile -t facts < <(printf '%s' "$json" | jq -r '(.facts // [])[]' 2>/dev/null)
mapfile -t hypotheses < <(printf '%s' "$json" | jq -r '(.hypotheses // [])[]' 2>/dev/null)

# ---------------------------------------------------------------------------
# File the results. Facts go to the inbox — never straight to memory.md.
# ---------------------------------------------------------------------------
now=$(date +%s)
written=0
if [ "${#facts[@]}" -gt 0 ]; then
    mkdir -p "$INBOX_DIR"
    inbox_file="$INBOX_DIR/${now}-study-${topic_id:-adhoc}.jsonl"
    for fact in "${facts[@]}"; do
        [ -n "${fact//[[:space:]]/}" ] || continue
        jq -cn --arg fact "$fact" --arg source "study:${topic_id:-adhoc}" \
            --argjson ts "$now" \
            '{"ts": $ts, "source": $source, "fact": $fact, "confidence": "medium"}' \
            >> "$inbox_file"
        written=$((written + 1))
    done
fi

queued=0
if [ "${#hypotheses[@]}" -gt 0 ] && [ "$remaining" -gt 0 ]; then
    mkdir -p "$MEMORY_DIR"
    for h in "${hypotheses[@]}"; do
        [ -n "${h//[[:space:]]/}" ] || continue
        [ "$queued" -lt "$remaining" ] || break
        # Don't re-ask something already pending or already settled.
        if [ -s "$HYPOTHESES_FILE" ] && \
           jq -e --arg t "$h" 'select(.text == $t)' "$HYPOTHESES_FILE" > /dev/null 2>&1; then
            continue
        fi
        jq -cn --arg text "$h" --arg topic "${topic_id:-adhoc}" --argjson ts "$now" \
            '{"ts": $ts, "text": $text, "topic": $topic, "status": "open"}' \
            >> "$HYPOTHESES_FILE"
        queued=$((queued + 1))
    done
fi

if [ -n "$topic_id" ]; then
    record_studied "$topic_id"
fi

if [ -n "$report" ]; then
    mkdir -p "$REPORTS_DIR"
    printf '%s\n' "$report" > "$REPORTS_DIR/${topic_id:-adhoc}.md"
fi

# ---------------------------------------------------------------------------
# Tell the user what just happened
# ---------------------------------------------------------------------------
echo ""
[ -n "$report" ] && { echo -e "${CYAN}${topic_label}${NC}"; echo "$report"; echo ""; }

if [ "$written" -gt 0 ]; then
    echo -e "${GREEN}Learned ${written} thing(s)${NC} ${DIM}— queued for the next consolidation${NC}"
    for fact in "${facts[@]}"; do
        [ -n "${fact//[[:space:]]/}" ] && echo "  · $fact"
    done
else
    echo -e "${DIM}Nothing new learned this run.${NC}"
fi

if [ "$queued" -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}${queued} guess(es) waiting on you:${NC}"
    printf '%s\n' "${hypotheses[@]:0:$queued}" | sed 's/^/  ? /'
    echo -e "  ${DIM}Answer with: brain memory confirm \"<text>\" / reject \"<text>\"${NC}"
elif [ "$remaining" -eq 0 ] && [ "${#hypotheses[@]}" -gt 0 ]; then
    echo ""
    echo -e "${DIM}Held back new guesses — ${open_count} are already waiting on you.${NC}"
fi
