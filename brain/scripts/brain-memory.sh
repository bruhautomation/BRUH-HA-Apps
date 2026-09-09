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
#   brain memory reject "<text>" [why]  Reject a guess (becomes a dead end)
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
# The panel. Confirm/reject, export and import all go through its API: the
# panel owns the ledgers the analyst reads (in the add-on's /data, which this
# script cannot see) and is the one writer that can settle a guess in all of
# them at once.
PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"
MEMORY_FILE="$MEMORY_DIR/memory.md"
INBOX_DIR="$MEMORY_DIR/inbox"
HYPOTHESES_FILE="$MEMORY_DIR/hypotheses.jsonl"
LOG_FILE="$MEMORY_DIR/memory.log.jsonl"

# A guess nobody answers is noise: retire it rather than let it linger.
HYPOTHESIS_TTL_DAYS="${BRAIN_HYPOTHESIS_TTL_DAYS:-14}"

usage() {
    cat << 'EOF'
brain memory — what brAIn knows about your home

Usage:
  brain memory add "<fact>"        Teach it something
  brain memory list                Print the memory document
  brain memory edit                Open it in $EDITOR
  brain memory forget "<text>"     Queue a line for removal
  brain memory log [n]             What it learned recently (default 10)
  brain memory undo [n]            Revert change #n from that list

  brain memory hypotheses          Guesses waiting on a yes/no from you
  brain memory confirm "<text>"    Yes — file it as a fact
  brain memory reject "<text>" [why]  No — a dead end; the reason teaches

  brain memory inbox               Facts awaiting consolidation
  brain memory consolidate         Fold the inbox in now
  brain memory clear --confirm     Reset the document (a .bak is kept)

  brain memory export [file]       Everything learned, as one portable file
  brain memory import <file>       Fold an export back in (merges ledgers;
                                   --replace-memory overwrites the document)

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
        echo -e "${GREEN}No guesses pending — brAIn isn't waiting on you.${NC}"
        return
    fi
    local open
    open=$(jq -r 'select(.status == "open") | .text' "$HYPOTHESES_FILE" 2>/dev/null)
    if [ -z "$open" ]; then
        echo -e "${GREEN}No guesses pending — brAIn isn't waiting on you.${NC}"
        return
    fi
    echo -e "${CYAN}brAIn thinks:${NC}"
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

# The panel's own list of open guesses, as JSON — or nothing at all when the
# panel is not answering, which is the one case the JSONL below is for.
#
# Settling a guess is three writes, and only one of them is in this
# directory. The panel's /api/hypothesis/{ts}/confirm queues the memory
# line; its /reject also records the dead end in the knowledge ledger under
# /data, which is what the analyst's prompt reads back — so a `reject` that
# only flipped hypotheses.jsonl retired the guess here and left the analyst
# free to make it again. Same rule as `brain findings`: go through the API
# that every button on the tab presses, and fall back to the file only when
# there is no panel to ask, saying so.
panel_hypotheses() {
    local payload
    payload=$(curl -s -m 10 "$PANEL/api/findings" 2>/dev/null) || return 1
    [ -n "$payload" ] || return 1
    printf '%s' "$payload" | jq -c '.hypotheses // []' 2>/dev/null
}

# resolve_panel_hypothesis <guesses-json> <needle> -> prints "<ts>\t<text>"
# rc 0 found, 1 none, 2 ambiguous (the candidates are printed to stderr).
resolve_panel_hypothesis() {
    local guesses="$1" needle="$2" exact matches count
    exact=$(printf '%s' "$guesses" | jq -r --arg t "$needle" \
        '.[] | select(.text == $t) | "\(.ts)\t\(.text)"' 2>/dev/null | head -1)
    if [ -n "$exact" ]; then
        printf '%s' "$exact"
        return 0
    fi
    matches=$(printf '%s' "$guesses" | jq -r --arg t "$needle" \
        '.[] | select(.text | ascii_downcase | contains($t | ascii_downcase)) | "\(.ts)\t\(.text)"' \
        2>/dev/null)
    count=$(printf '%s' "$matches" | grep -c . || true)
    if [ "${count:-0}" -eq 1 ]; then
        printf '%s' "$matches"
        return 0
    fi
    if [ "${count:-0}" -gt 1 ]; then
        echo -e "${YELLOW}That matches more than one guess:${NC}" >&2
        printf '%s\n' "$matches" | cut -f2 | sed 's/^/  ? /' >&2
        return 2
    fi
    return 1
}

# settle_via_panel <confirm|reject> <needle> [note]
# rc 0 settled, 1 the panel refused (its message printed), 2 ambiguous,
# 3 no open guess matches, 4 the panel is not answering (caller falls back).
settle_via_panel() {
    local verb="$1" needle="$2" note="${3:-}" guesses found ts text body rc
    guesses=$(panel_hypotheses) || return 4
    [ -n "$guesses" ] || return 4
    found=$(resolve_panel_hypothesis "$guesses" "$needle"); rc=$?
    [ $rc -eq 2 ] && return 2
    [ $rc -ne 0 ] && return 3
    ts="${found%%$'\t'*}"
    text="${found#*$'\t'}"
    body=$(jq -cn --arg note "$note" '{note: $note}')
    local response http_code
    response=$(curl -s -m 30 -w '\n%{http_code}' -X POST \
        -H "Content-Type: application/json" -d "$body" \
        "$PANEL/api/hypothesis/${ts}/${verb}" 2>/dev/null)
    http_code="${response##*$'\n'}"
    response="${response%$'\n'*}"
    if [ "$http_code" = "200" ]; then
        SETTLED_TEXT="$text"
        return 0
    fi
    echo -e "${RED}${response:-the panel did not answer}${NC}" >&2
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

SETTLED_TEXT=""

# Only when the panel is not there: flip the JSONL the panel would have
# flipped, and say what that leaves undone.
local_fallback_note() {
    echo -e "${DIM}The panel is not answering on ${PANEL}, so this was recorded in hypotheses.jsonl only — the panel's own ledger was not updated. It settles there once the add-on is running.${NC}" >&2
}

cmd_confirm() {
    require_arg "${1:-}" "'confirm' needs the guess text (a distinctive fragment is enough)"
    local text rc
    settle_via_panel confirm "$1"; rc=$?
    case $rc in
        0)  echo -e "${GREEN}Confirmed and queued as a fact:${NC} $SETTLED_TEXT"; return ;;
        1|2) exit 1 ;;
        3)  echo -e "${RED}No open guess matches that.${NC} See: brain memory hypotheses" >&2; exit 1 ;;
    esac
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
    local_fallback_note
}

cmd_reject() {
    require_arg "${1:-}" "'reject' needs the guess text (a distinctive fragment is enough)"
    local text rc note="${2:-}"
    settle_via_panel reject "$1" "$note"; rc=$?
    case $rc in
        0)  echo -e "${GREEN}Rejected.${NC} ${DIM}brAIn won't pursue that line again.${NC}"; return ;;
        1|2) exit 1 ;;
        3)  echo -e "${RED}No open guess matches that.${NC} See: brain memory hypotheses" >&2; exit 1 ;;
    esac
    text=$(resolve_hypothesis "$1"); rc=$?
    if [ $rc -eq 2 ]; then exit 1; fi
    if [ $rc -ne 0 ]; then
        echo -e "${RED}No open guess matches that.${NC} See: brain memory hypotheses" >&2
        exit 1
    fi
    settle_hypothesis "$text" "rejected"
    if [ -n "$note" ]; then
        # The panel would have queued this as a correction; offline, the
        # closest honest thing is the same sentence into the same queue.
        append_inbox_fact "brAIn guessed: \"$text\". The homeowner says that is wrong, because: $note" "correction" "high" > /dev/null
    fi
    echo -e "${GREEN}Rejected.${NC} ${DIM}brAIn won't pursue that line again.${NC}"
    local_fallback_note
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
    echo -e "${CYAN}What brAIn learned recently:${NC}"
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

# -- export / import --------------------------------------------------------
# Both go through the panel's API rather than reading the stores directly:
# the findings and knowledge ledgers live in the add-on's /data, which this
# script cannot see, and the panel is the one writer that can merge safely.

cmd_export() {
    local out="${1:-brain-export-$(date +%Y-%m-%d).json}"
    if curl -s -f -m 30 "$PANEL/api/memory/export" -o "$out" 2>/dev/null; then
        echo -e "${GREEN}Exported to ${out}${NC}"
        jq -r '"  memory: \(.memory_md | length) chars · findings: \(.findings | length) · settled answers: \(.settled | length) · facts: \(.knowledge_facts | length)"' \
            "$out" 2>/dev/null || true
    else
        echo -e "${RED}Export failed — is the panel running? (${PANEL})${NC}" >&2
        exit 1
    fi
}

cmd_import() {
    local file="${1:-}" flag="${2:-}"
    require_arg "$file" "give the export file to import: brain memory import <file>"
    if [ ! -r "$file" ]; then
        echo -e "${RED}Cannot read ${file}${NC}" >&2
        exit 1
    fi
    local payload
    if [ "$flag" = "--replace-memory" ]; then
        payload=$(jq -c '. + {replace_memory: true}' "$file") || {
            echo -e "${RED}${file} is not valid JSON${NC}" >&2; exit 1; }
    else
        payload=$(cat "$file")
    fi
    local response http_code
    response=$(curl -s -m 60 -w '\n%{http_code}' -X POST \
        -H "Content-Type: application/json" --data-binary "$payload" \
        "$PANEL/api/memory/import" 2>/dev/null)
    http_code="${response##*$'\n'}"
    response="${response%$'\n'*}"
    if [ "$http_code" = "200" ]; then
        echo -e "${GREEN}Imported.${NC}"
        echo "$response" | jq -r '"  memory: \(.memory) · findings added: \(.findings) · settled added: \(.settled) · facts added: \(.knowledge_facts)"' 2>/dev/null
        if [ "$(echo "$response" | jq -r '.memory' 2>/dev/null)" = "kept" ]; then
            echo -e "${DIM}The memory document here already has content, so it was kept."
            echo -e "Re-run with --replace-memory to overwrite it with the export's.${NC}"
        fi
    else
        echo -e "${RED}${response:-the panel is not answering on ${PANEL}}${NC}" >&2
        exit 1
    fi
}

case "$action" in
    add)          cmd_add "${1:-}" ;;
    forget)       cmd_forget "${1:-}" ;;
    list)         cmd_list ;;
    inbox)        cmd_inbox ;;
    edit)         cmd_edit ;;
    clear)        cmd_clear "${1:-}" ;;
    hypotheses|guesses) cmd_hypotheses ;;
    confirm)      cmd_confirm "${1:-}" ;;
    reject)       cmd_reject "${1:-}" "${2:-}" ;;
    log)
        if [ "${1:-}" = "--show" ]; then
            shift; cmd_log_show "${1:-}"
        else
            cmd_log "${1:-10}"
        fi
        ;;
    undo)         cmd_undo "${1:-1}" ;;
    consolidate)  cmd_consolidate ;;
    export)       cmd_export "${1:-}" ;;
    import)       cmd_import "${1:-}" "${2:-}" ;;
    help|--help|-h) usage ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage 1
        ;;
esac
