#!/bin/bash

# brain-memory — implementation behind `brain memory`.
#
# The store lives at /config/.brain/memory/:
#   memory.md        canonical, user-editable document — the ONLY memory
#   voice.md         short distillate spliced into voice prompts (derived)
#   inbox/           pending candidate facts (JSONL); every writer goes here
#   hypotheses.jsonl guesses awaiting a yes/no, capped and short-lived
#   memory.log.jsonl what changed, when, and why — powers `log` and `undo`
#   curriculum.json  when each study topic was last covered
#
# The design rule: memory.md is the only thing that is "memory". The inbox
# is a queue, hypotheses are a queue, and the log is an audit trail. None
# of them are injected into prompts.
#
# Usage:
#   brain memory add "<fact>"           Queue a fact for the next consolidation
#   brain memory list                   Print the memory document
#   brain memory edit                   Open it in $EDITOR
#   brain memory forget "<text>"        Queue a line for removal
#   brain memory log [n]                What it learned recently
#   brain memory undo [n]               Revert a memory change
#   brain memory hypotheses             Pending guesses awaiting your yes/no
#   brain memory confirm "<text>"       Confirm a guess (becomes a fact)
#   brain memory reject "<text>"        Reject a guess (becomes a dead end)
#   brain memory inbox                  Facts awaiting consolidation
#   brain memory consolidate            Run one consolidation pass now
#   brain memory clear --confirm        Reset the document (.bak kept)

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

MEMORY_DIR="${BRAIN_MEMORY_DIR:-/config/.brain/memory}"
MEMORY_FILE="$MEMORY_DIR/memory.md"
INBOX_DIR="$MEMORY_DIR/inbox"
HYPOTHESES_FILE="$MEMORY_DIR/hypotheses.jsonl"
LOG_FILE="$MEMORY_DIR/memory.log.jsonl"

# A guess nobody answers is noise: retire it rather than let it linger.
HYPOTHESIS_TTL_DAYS="${BRAIN_HYPOTHESIS_TTL_DAYS:-14}"

usage() {
    cat << 'EOF'
brain memory — what BRain knows about your home

Usage:
  brain memory add "<fact>"        Teach it something
  brain memory list                Print the memory document
  brain memory edit                Open it in $EDITOR
  brain memory forget "<text>"     Queue a line for removal
  brain memory log [n]             What it learned recently (default 10)
  brain memory undo [n]            Revert change #n from that list

  brain memory hypotheses          Guesses waiting on a yes/no from you
  brain memory confirm "<text>"    Yes — file it as a fact
  brain memory reject "<text>"     No — record it as a dead end

  brain memory inbox               Facts awaiting consolidation
  brain memory consolidate         Fold the inbox in now
  brain memory clear --confirm     Reset the document (a .bak is kept)

The document is plain markdown and yours to edit — your edits are the
source of truth. Everything else here is a queue or an audit trail.
EOF
    exit "${1:-0}"
}

emit_template() {
    cat << 'MEMORYMD'
# Home Memory

<!-- This file is user-editable — add, correct, or delete anything. -->
<!-- It is also auto-consolidated: new facts from the inbox get merged in
     (newest wins on contradictions). -->

## Preferences

## Entity nicknames

## Household patterns

## Device notes
MEMORYMD
}

append_inbox_fact() {
    local fact="$1" source="$2" confidence="$3" ts file
    ts=$(date +%s)
    mkdir -p "$INBOX_DIR"
    file="$INBOX_DIR/${ts}-${source}.jsonl"
    jq -cn --arg fact "$fact" --arg source "$source" --arg conf "$confidence" \
        --argjson ts "$ts" \
        '{"ts": $ts, "source": $source, "fact": $fact, "confidence": $conf}' >> "$file"
    echo "$file"
}

require_arg() {
    if [ -z "${1:-}" ]; then
        echo -e "${RED}Error: ${2}${NC}" >&2
        exit 1
    fi
}

# --------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------

cmd_add() {
    require_arg "${1:-}" "'add' needs a fact, e.g. brain memory add \"We call the office lamp the beacon\""
    append_inbox_fact "$1" "terminal" "high" > /dev/null
    echo -e "${GREEN}Queued:${NC} $1"
    echo -e "${DIM}It lands in the document at the next consolidation (brain memory consolidate to do it now).${NC}"
}

cmd_forget() {
    require_arg "${1:-}" "'forget' needs the text to remove"
    append_inbox_fact "FORGET: $1" "terminal-forget" "high" > /dev/null
    echo -e "${GREEN}Queued for removal:${NC} $1"
}

cmd_list() {
    if [ -s "$MEMORY_FILE" ]; then
        cat "$MEMORY_FILE"
    else
        echo -e "${YELLOW}Nothing learned yet.${NC} Teach it something: brain memory add \"...\""
    fi
}

cmd_inbox() {
    local found=false f
    for f in "$INBOX_DIR"/*.jsonl; do
        [ -f "$f" ] || continue
        found=true
        jq -r '"[\(.confidence)] (\(.source)) \(.fact)"' "$f" 2>/dev/null || cat "$f"
    done
    [ "$found" = "false" ] && echo -e "${GREEN}Inbox empty — nothing pending.${NC}"
    return 0
}

cmd_edit() {
    mkdir -p "$MEMORY_DIR"
    [ -f "$MEMORY_FILE" ] || emit_template > "$MEMORY_FILE"
    "${EDITOR:-nano}" "$MEMORY_FILE"
}

cmd_clear() {
    if [ "${1:-}" != "--confirm" ]; then
        echo -e "${YELLOW}This resets the memory document to an empty template.${NC}"
        echo -e "A .bak copy is kept. Run: ${CYAN}brain memory clear --confirm${NC}"
        exit 1
    fi
    mkdir -p "$MEMORY_DIR"
    [ -f "$MEMORY_FILE" ] && cp "$MEMORY_FILE" "${MEMORY_FILE}.bak"
    emit_template > "${MEMORY_FILE}.tmp"
    mv "${MEMORY_FILE}.tmp" "$MEMORY_FILE"
    echo -e "${GREEN}Memory reset.${NC} Previous content: ${MEMORY_FILE}.bak"
}

# --------------------------------------------------------------------------
# Hypotheses — the replacement for the old open-ended question list
# --------------------------------------------------------------------------

retire_stale_hypotheses() {
    [ -s "$HYPOTHESES_FILE" ] || return 0
    local now cutoff
    now=$(date +%s)
    cutoff=$((now - HYPOTHESIS_TTL_DAYS * 86400))
    jq -c --argjson cutoff "$cutoff" \
        'if .status == "open" and (.ts // 0) < $cutoff
         then .status = "expired" else . end' \
        "$HYPOTHESES_FILE" > "${HYPOTHESES_FILE}.tmp" 2>/dev/null \
        && mv "${HYPOTHESES_FILE}.tmp" "$HYPOTHESES_FILE"
}

cmd_hypotheses() {
    retire_stale_hypotheses
    if [ ! -s "$HYPOTHESES_FILE" ]; then
        echo -e "${GREEN}No guesses pending — BRain isn't waiting on you.${NC}"
        return
    fi
    local open
    open=$(jq -r 'select(.status == "open") | .text' "$HYPOTHESES_FILE" 2>/dev/null)
    if [ -z "$open" ]; then
        echo -e "${GREEN}No guesses pending — BRain isn't waiting on you.${NC}"
        return
    fi
    echo -e "${CYAN}BRain thinks:${NC}"
    printf '%s\n' "$open" | sed 's/^/  ? /'
    echo ""
    echo -e "  ${CYAN}brain memory confirm \"<text>\"${NC}   yes, that's right"
    echo -e "  ${CYAN}brain memory reject  \"<text>\"${NC}   no, wrong track"
}

# Match a hypothesis by exact text, or by unique substring so the user
# doesn't have to retype a whole sentence.
resolve_hypothesis() {
    local needle="$1"
    [ -s "$HYPOTHESES_FILE" ] || return 1
    local exact
    exact=$(jq -r --arg t "$needle" \
        'select(.status == "open" and .text == $t) | .text' "$HYPOTHESES_FILE" 2>/dev/null | head -1)
    if [ -n "$exact" ]; then
        printf '%s' "$exact"
        return 0
    fi
    local matches count
    matches=$(jq -r --arg t "$needle" \
        'select(.status == "open" and (.text | ascii_downcase | contains($t | ascii_downcase))) | .text' \
        "$HYPOTHESES_FILE" 2>/dev/null)
    count=$(printf '%s' "$matches" | grep -c . || true)
    if [ "${count:-0}" -eq 1 ]; then
        printf '%s' "$matches"
        return 0
    fi
    if [ "${count:-0}" -gt 1 ]; then
        echo -e "${YELLOW}That matches more than one guess:${NC}" >&2
        printf '%s\n' "$matches" | sed 's/^/  ? /' >&2
        return 2
    fi
    return 1
}

settle_hypothesis() {  # settle_hypothesis <text> <confirmed|rejected>
    local text="$1" status="$2" now
    now=$(date +%s)
    jq -c --arg t "$text" --arg s "$status" --argjson now "$now" \
        'if .text == $t and .status == "open"
         then .status = $s | .settled_at = $now else . end' \
        "$HYPOTHESES_FILE" > "${HYPOTHESES_FILE}.tmp" 2>/dev/null \
        && mv "${HYPOTHESES_FILE}.tmp" "$HYPOTHESES_FILE"
}

cmd_confirm() {
    require_arg "${1:-}" "'confirm' needs the guess text (a distinctive fragment is enough)"
    local text rc
    text=$(resolve_hypothesis "$1"); rc=$?
    if [ $rc -eq 2 ]; then exit 1; fi
    if [ $rc -ne 0 ]; then
        echo -e "${RED}No open guess matches that.${NC} See: brain memory hypotheses" >&2
        exit 1
    fi
    settle_hypothesis "$text" "confirmed"
    # The confirmation is the durable part — it becomes a plain fact, and
    # the guess itself is never spoken of again.
    append_inbox_fact "$text" "hypothesis-confirmed" "high" > /dev/null
    echo -e "${GREEN}Confirmed and queued as a fact:${NC} $text"
}

cmd_reject() {
    require_arg "${1:-}" "'reject' needs the guess text (a distinctive fragment is enough)"
    local text rc
    text=$(resolve_hypothesis "$1"); rc=$?
    if [ $rc -eq 2 ]; then exit 1; fi
    if [ $rc -ne 0 ]; then
        echo -e "${RED}No open guess matches that.${NC} See: brain memory hypotheses" >&2
        exit 1
    fi
    settle_hypothesis "$text" "rejected"
    echo -e "${GREEN}Rejected.${NC} ${DIM}BRain won't pursue that line again.${NC}"
}

# --------------------------------------------------------------------------
# Change log
# --------------------------------------------------------------------------

cmd_log() {
    local limit="${1:-10}"
    if [ ! -s "$LOG_FILE" ]; then
        echo -e "${GREEN}No changes recorded yet.${NC}"
        return
    fi
    echo -e "${CYAN}What BRain learned recently:${NC}"
    echo ""
    jq -cs --argjson limit "$limit" 'reverse | .[:$limit]' "$LOG_FILE" 2>/dev/null \
        | jq -r 'to_entries[] | "\(.key + 1)|\(.value.ts)|\(.value.added | length)|\(.value.removed | length)|\(.value.source // "consolidation")"' \
        | while IFS='|' read -r n ts added removed source; do
            printf "  ${YELLOW}%2s${NC}  %s  ${GREEN}+%s${NC} ${RED}-%s${NC}  ${DIM}%s${NC}\n" \
                "$n" "$(date -d "@${ts%.*}" '+%b %d %H:%M' 2>/dev/null || echo '?')" \
                "$added" "$removed" "$source"
        done
    echo ""
    echo -e "Detail: ${CYAN}brain memory log --show <n>${NC}   Revert: ${CYAN}brain memory undo <n>${NC}"
}

cmd_log_show() {
    require_arg "${1:-}" "'log --show' needs an entry number"
    local entry
    entry=$(jq -cs --argjson n "$1" 'reverse | .[$n - 1] // empty' "$LOG_FILE" 2>/dev/null)
    if [ -z "$entry" ]; then
        echo -e "${RED}No log entry #${1}.${NC}" >&2
        exit 1
    fi
    printf '%s' "$entry" | jq -r '(.added // [])[] | "  + \(.)"'
    printf '%s' "$entry" | jq -r '(.removed // [])[] | "  - \(.)"'
}

cmd_undo() {
    local n="${1:-1}"
    if [ ! -s "$LOG_FILE" ]; then
        echo -e "${GREEN}Nothing to undo.${NC}"
        return
    fi
    local entry snapshot
    entry=$(jq -cs --argjson n "$n" 'reverse | .[$n - 1] // empty' "$LOG_FILE" 2>/dev/null)
    if [ -z "$entry" ]; then
        echo -e "${RED}No change #${n} — run 'brain memory log' to see the list.${NC}" >&2
        exit 1
    fi
    snapshot=$(printf '%s' "$entry" | jq -r '.snapshot // ""')
    if [ -z "$snapshot" ] || [ ! -f "$MEMORY_DIR/$snapshot" ]; then
        echo -e "${RED}No snapshot retained for that change.${NC}" >&2
        exit 1
    fi
    cp "$MEMORY_FILE" "${MEMORY_FILE}.bak" 2>/dev/null || true
    cp "$MEMORY_DIR/$snapshot" "$MEMORY_FILE"
    echo -e "${GREEN}Reverted the memory document to before that change.${NC}"
    echo -e "${DIM}The version you just replaced is at ${MEMORY_FILE}.bak${NC}"
}

cmd_consolidate() {
    local candidate consolidator=""
    for candidate in /opt/scripts/brain-memory-consolidate.sh \
                     "$(dirname "$0")/brain-memory-consolidate.sh"; do
        if [ -f "$candidate" ]; then
            consolidator="$candidate"
            break
        fi
    done
    if [ -z "$consolidator" ]; then
        echo -e "${RED}Error: the consolidator is not installed in this image${NC}" >&2
        exit 1
    fi
    bash "$consolidator" --once
}

# --------------------------------------------------------------------------

[ $# -lt 1 ] && usage

action="$1"
shift

case "$action" in
    add)          cmd_add "${1:-}" ;;
    forget)       cmd_forget "${1:-}" ;;
    list)         cmd_list ;;
    inbox)        cmd_inbox ;;
    edit)         cmd_edit ;;
    clear)        cmd_clear "${1:-}" ;;
    hypotheses|guesses) cmd_hypotheses ;;
    confirm)      cmd_confirm "${1:-}" ;;
    reject)       cmd_reject "${1:-}" ;;
    log)
        if [ "${1:-}" = "--show" ]; then
            shift; cmd_log_show "${1:-}"
        else
            cmd_log "${1:-10}"
        fi
        ;;
    undo)         cmd_undo "${1:-1}" ;;
    consolidate)  cmd_consolidate ;;
    help|--help|-h) usage ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage 1
        ;;
esac
