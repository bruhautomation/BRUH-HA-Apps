#!/bin/bash

# brain-undo — review and revert the file edits Claude made under /config.
#
# Reads the journal that brain-edit-snapshot.py writes on every Write/Edit
# (see /data/.brain/edits/). This is the replacement for the old git
# auto-backup: scoped to what Claude actually touched, in plain English,
# with a one-command revert.
#
# Usage:
#   brain undo              List recent edits (newest first)
#   brain undo <n>          Revert edit #n from that list
#   brain undo --all-today  Revert every edit made today (asks first)

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

JOURNAL_DIR="${BRAIN_EDIT_JOURNAL:-/data/.brain/edits}"
INDEX="$JOURNAL_DIR/index.jsonl"
SNAPSHOTS="$JOURNAL_DIR/snapshots"
LIST_LIMIT="${BRAIN_UNDO_LIST_LIMIT:-20}"

usage() {
    cat << 'EOF'
brain undo — revert Claude's edits to /config

Usage:
  brain undo              List recent edits, newest first
  brain undo <n>          Revert edit #n
  brain undo --all-today  Revert everything Claude changed today

Each entry shows when the edit happened, which file, and whether the file
was created or modified. Reverting restores the file exactly as it was
immediately before that edit.
EOF
    exit "${1:-0}"
}

require_journal() {
    if [ ! -s "$INDEX" ]; then
        echo -e "${GREEN}No edits recorded — Claude hasn't changed anything under /config.${NC}"
        exit 0
    fi
}

# Newest-first slice of the journal, numbered for the user.
recent_json() {
    jq -cs --argjson limit "$LIST_LIMIT" \
        'reverse | .[:$limit]' "$INDEX" 2>/dev/null
}

cmd_list() {
    require_journal
    local rows
    rows=$(recent_json)
    if [ -z "$rows" ] || [ "$rows" = "[]" ]; then
        echo -e "${GREEN}No edits recorded.${NC}"
        return
    fi

    echo -e "${CYAN}Claude's recent edits to /config:${NC}"
    echo ""
    printf '%s' "$rows" | jq -r '
        to_entries[]
        | "\(.key + 1)|\(.value.ts)|\(.value.path)|\(if .value.existed then "modified" else "created" end)"
    ' | while IFS='|' read -r n ts path kind; do
        local_when=$(date -d "@${ts%.*}" '+%b %d %H:%M' 2>/dev/null || echo "?")
        printf "  ${YELLOW}%2s${NC}  %s  %-9s %s\n" "$n" "$local_when" "$kind" "$path"
    done

    echo ""
    echo -e "Revert one with: ${CYAN}brain undo <n>${NC}"
}

# Restore a single journal entry (JSON object on stdin).
restore_entry() {
    local entry="$1"
    local path snapshot existed
    path=$(printf '%s' "$entry" | jq -r '.path')
    snapshot=$(printf '%s' "$entry" | jq -r '.snapshot // ""')
    existed=$(printf '%s' "$entry" | jq -r '.existed')

    if [ "$existed" = "false" ]; then
        # The edit created this file, so undoing it means removing the file.
        if [ -e "$path" ]; then
            rm -f "$path" && echo -e "${GREEN}Removed${NC} $path ${DIM}(it was created by that edit)${NC}"
        else
            echo -e "${YELLOW}Already gone:${NC} $path"
        fi
        return 0
    fi

    if [ -z "$snapshot" ] || [ ! -f "$SNAPSHOTS/$snapshot" ]; then
        echo -e "${RED}No snapshot retained for${NC} $path" >&2
        echo -e "${DIM}(it may have aged out of the journal)${NC}" >&2
        return 1
    fi

    mkdir -p "$(dirname "$path")"
    if cp -a "$SNAPSHOTS/$snapshot" "$path"; then
        echo -e "${GREEN}Restored${NC} $path"
    else
        echo -e "${RED}Could not write${NC} $path" >&2
        return 1
    fi
}

cmd_revert() {
    require_journal
    local n="$1"
    local entry
    entry=$(recent_json | jq -c --argjson n "$n" '.[$n - 1] // empty' 2>/dev/null)
    if [ -z "$entry" ]; then
        echo -e "${RED}No edit #${n} — run 'brain undo' to see the list.${NC}" >&2
        exit 1
    fi
    restore_entry "$entry"
}

cmd_all_today() {
    require_journal
    local midnight entries count
    midnight=$(date -d 'today 00:00:00' +%s 2>/dev/null || echo 0)
    entries=$(jq -cs --argjson since "$midnight" \
        'map(select(.ts >= $since)) | reverse' "$INDEX" 2>/dev/null)
    count=$(printf '%s' "$entries" | jq 'length' 2>/dev/null || echo 0)

    if [ "${count:-0}" -eq 0 ]; then
        echo -e "${GREEN}Nothing changed today.${NC}"
        return
    fi

    echo -e "${YELLOW}This reverts ${count} edit(s) made today.${NC}"
    printf '%s' "$entries" | jq -r '.[] | "  - \(.path)"' | sort -u
    echo ""
    printf "Type 'yes' to continue: "
    read -r reply
    if [ "$reply" != "yes" ]; then
        echo "Cancelled."
        return
    fi

    # Newest first, so a file edited repeatedly ends up at its oldest state.
    local i=0
    while [ "$i" -lt "$count" ]; do
        restore_entry "$(printf '%s' "$entries" | jq -c ".[$i]")" || true
        i=$((i + 1))
    done
}

case "${1:-}" in
    "")            cmd_list ;;
    --all-today)   cmd_all_today ;;
    help|--help|-h) usage ;;
    *[!0-9]*)
        echo -e "${RED}Expected an edit number.${NC}" >&2
        usage 1
        ;;
    *)             cmd_revert "$1" ;;
esac
