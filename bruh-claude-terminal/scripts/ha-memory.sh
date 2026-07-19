#!/bin/bash

# ha-memory — Inspect and manage Claude's long-term home memory
#
# The memory store lives at /config/.bruh_claude/memory/:
#   memory.md        canonical, user-editable knowledge file
#   voice.md         short distillate spliced into voice prompts
#   inbox/           pending candidate facts (JSONL, one fact per line)
#   questions.jsonl  open questions Claude wants answered + their answers
#
# Facts flow in from voice conversations (remember_fact / reflection), the
# terminal (ha-memory add), HA services (bruh_claude.add_memory), and other
# BRUH add-ons via /share. The consolidator (ha-memory-consolidate) merges
# the inbox into memory.md + voice.md with a cheap Claude pass.
#
# Usage:
#   ha-memory add "<fact>"                Queue a fact for the next consolidation
#   ha-memory list                        Print memory.md
#   ha-memory inbox                       Print pending (unconsolidated) facts
#   ha-memory questions                   Print open (unanswered) questions
#   ha-memory answer "<question>" "<answer>"   Answer an open question
#   ha-memory consolidate                 Run one consolidation pass now
#   ha-memory edit                        Open memory.md in $EDITOR
#   ha-memory clear --confirm             Reset memory.md (old file kept as .bak)

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

MEMORY_DIR="${BRUH_MEMORY_DIR:-/config/.bruh_claude/memory}"
MEMORY_FILE="$MEMORY_DIR/memory.md"
INBOX_DIR="$MEMORY_DIR/inbox"
QUESTIONS_FILE="$MEMORY_DIR/questions.jsonl"

usage() {
    cat << 'EOF'
ha-memory — Inspect and manage Claude's long-term home memory

Usage:
  ha-memory add "<fact>"                     Queue a fact (e.g. a nickname or preference)
  ha-memory list                             Print the current memory file
  ha-memory inbox                            Print pending facts awaiting consolidation
  ha-memory questions                        Print open questions without an answer
  ha-memory answer "<question>" "<answer>"   Record an answer (also queued as a fact)
  ha-memory consolidate                      Run one consolidation pass now
  ha-memory edit                             Open memory.md in $EDITOR (default nano)
  ha-memory clear --confirm                  Reset memory.md to the template (.bak kept)

Memory lives in /config/.bruh_claude/memory/ and is injected into voice
conversations, insight jobs, and the generated CLAUDE.md context.
EOF
    exit 0
}

emit_template() {
    cat << 'MEMORYMD'
# Home Memory

<!-- This file is user-editable — add, correct, or delete anything. -->
<!-- It is also auto-consolidated: the ha-memory consolidator merges new
     facts from the inbox into it (newest wins on contradictions). -->

## Preferences

## Entity nicknames

## Household patterns

## Device notes
MEMORYMD
}

append_inbox_fact() {
    local fact="$1" source="$2" confidence="$3"
    local ts
    ts=$(date +%s)
    mkdir -p "$INBOX_DIR"
    local file="$INBOX_DIR/${ts}-${source}.jsonl"
    jq -cn --arg fact "$fact" --arg source "$source" --arg conf "$confidence" \
        --argjson ts "$ts" \
        '{"ts": $ts, "source": $source, "fact": $fact, "confidence": $conf}' >> "$file"
    echo "$file"
}

cmd_add() {
    local fact="${1:-}"
    if [ -z "$fact" ]; then
        echo -e "${RED}Error: 'add' requires a fact, e.g. ha-memory add \"We call the office lamp 'the beacon'\"${NC}" >&2
        exit 1
    fi
    local file
    file=$(append_inbox_fact "$fact" "terminal" "high")
    echo -e "${GREEN}Fact queued for the next consolidation:${NC} $fact"
    echo -e "  (inbox file: $file)"
}

cmd_list() {
    if [ -s "$MEMORY_FILE" ]; then
        cat "$MEMORY_FILE"
    else
        echo -e "${YELLOW}No memory yet. Add facts with: ha-memory add \"...\"${NC}"
    fi
}

cmd_inbox() {
    local found=false
    for f in "$INBOX_DIR"/*.jsonl; do
        [ -f "$f" ] || continue
        found=true
        jq -r '"[\(.confidence)] (\(.source)) \(.fact)"' "$f" 2>/dev/null || cat "$f"
    done
    if [ "$found" = "false" ]; then
        echo -e "${GREEN}Inbox empty — nothing pending consolidation.${NC}"
    fi
}

cmd_questions() {
    if [ ! -s "$QUESTIONS_FILE" ]; then
        echo -e "${GREEN}No open questions.${NC}"
        return
    fi
    # Open = question records whose "q" has no matching answer record.
    local open
    open=$(jq -rs '
        (map(select(has("a")) | .q)) as $answered
        | map(select(has("q") and (has("a") | not))
              | select(.q as $q | $answered | index($q) | not))
        | .[] | "- \(.q)  (asked by \(.asked_by // "unknown"))"
    ' "$QUESTIONS_FILE" 2>/dev/null || true)
    if [ -n "$open" ]; then
        echo -e "${CYAN}Open questions:${NC}"
        echo "$open"
        echo ""
        echo -e "Answer one with: ${CYAN}ha-memory answer \"<question>\" \"<answer>\"${NC}"
    else
        echo -e "${GREEN}No open questions.${NC}"
    fi
}

cmd_answer() {
    local question="${1:-}" answer="${2:-}"
    if [ -z "$question" ] || [ -z "$answer" ]; then
        echo -e "${RED}Error: 'answer' requires a question and an answer${NC}" >&2
        exit 1
    fi
    local ts
    ts=$(date +%s)
    mkdir -p "$MEMORY_DIR"
    jq -cn --arg q "$question" --arg a "$answer" --argjson ts "$ts" \
        '{"q": $q, "a": $a, "source": "terminal", "ts": $ts}' >> "$QUESTIONS_FILE"
    append_inbox_fact "Q: ${question} → A: ${answer}" "terminal" "high" > /dev/null
    echo -e "${GREEN}Answer recorded and queued as a fact.${NC}"
}

cmd_consolidate() {
    local consolidator=""
    for candidate in /usr/local/bin/ha-memory-consolidate \
                     /opt/scripts/ha-memory-consolidate.sh \
                     "$(dirname "$0")/ha-memory-consolidate.sh"; do
        if [ -x "$candidate" ] || [ -f "$candidate" ]; then
            consolidator="$candidate"
            break
        fi
    done
    if [ -z "$consolidator" ]; then
        echo -e "${RED}Error: ha-memory-consolidate not found${NC}" >&2
        exit 1
    fi
    bash "$consolidator" --once
}

cmd_edit() {
    mkdir -p "$MEMORY_DIR"
    [ -f "$MEMORY_FILE" ] || emit_template > "$MEMORY_FILE"
    "${EDITOR:-nano}" "$MEMORY_FILE"
}

cmd_clear() {
    if [ "${1:-}" != "--confirm" ]; then
        echo -e "${YELLOW}This resets memory.md to the empty template (a .bak copy is kept).${NC}"
        echo -e "Run: ${CYAN}ha-memory clear --confirm${NC}"
        exit 1
    fi
    mkdir -p "$MEMORY_DIR"
    if [ -f "$MEMORY_FILE" ]; then
        cp "$MEMORY_FILE" "${MEMORY_FILE}.bak"
    fi
    local tmp="${MEMORY_FILE}.tmp"
    emit_template > "$tmp"
    mv "$tmp" "$MEMORY_FILE"
    echo -e "${GREEN}Memory reset. Previous content saved to ${MEMORY_FILE}.bak${NC}"
}

# Main
[ $# -lt 1 ] && usage

action="$1"
shift

case "$action" in
    add)         cmd_add "${1:-}" ;;
    list)        cmd_list ;;
    inbox)       cmd_inbox ;;
    questions)   cmd_questions ;;
    answer)      cmd_answer "${1:-}" "${2:-}" ;;
    consolidate) cmd_consolidate ;;
    edit)        cmd_edit ;;
    clear)       cmd_clear "${1:-}" ;;
    --help|-h|help) usage ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage
        ;;
esac
