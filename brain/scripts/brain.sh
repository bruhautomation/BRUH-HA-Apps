#!/bin/bash

# brain — brAIn's own faculties: memory, learning, and undo.
#
# Home Assistant operations live under the sibling `ha` command; the split
# keeps "brain log" (which log?) from ever being a question someone has to
# ask. Each subcommand delegates to a script in /opt/scripts.
#
# Usage:
#   brain memory <action> [args]   Long-term home memory (add/list/edit/...)
#   brain learn [topic]            Run a study session on the home
#   brain ask "<question>"         One-shot question, same engine as the Ask card
#   brain undo [n]                 Review and revert Claude's file edits
#   brain doctor                   End-to-end diagnostic
#   brain help                     This help

set -uo pipefail

SCRIPTS_DIR="${BRAIN_SCRIPTS_DIR:-/opt/scripts}"

CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    cat << 'EOF'
brain — brAIn's own faculties

Usage:
  brain memory <action>          Long-term home memory
      add "<fact>"               Teach it something
      list                       Print what it knows
      edit                       Open the memory file in $EDITOR
      forget "<text>"            Drop a remembered line
      log [n]                    What it learned recently
      undo [n]                   Revert a memory change
      hypotheses                 Pending guesses awaiting your yes/no
      confirm "<text>"           Confirm a pending guess
      reject "<text>"            Reject a pending guess
      consolidate                Fold pending facts in now

  brain learn [topic]            Study the home and write down what it finds
  brain ask "<question>"         Ask about the home (same engine as the Ask card)
  brain undo [n]                 Review and revert Claude's edits to /config
  brain doctor                   End-to-end diagnostic
  brain help                     This help

Home Assistant operations live under `ha` (ha log, ha reload, ha entity, ...).
EOF
    exit "${1:-0}"
}

# Run a script from /opt/scripts, or explain clearly if the image lacks it.
delegate() {
    local script="$1"; shift
    local path="${SCRIPTS_DIR}/${script}"
    if [ ! -f "$path" ]; then
        echo -e "${RED}Error: ${script} is not installed in this image${NC}" >&2
        exit 1
    fi
    exec bash "$path" "$@"
}

[ $# -lt 1 ] && usage

action="$1"
shift

case "$action" in
    memory)     delegate brain-memory.sh "$@" ;;
    learn)      delegate brain-learn.sh "$@" ;;
    ask)        delegate brain-ask.sh "$@" ;;
    undo)       delegate brain-undo.sh "$@" ;;
    doctor)     delegate ha-selftest.sh "$@" ;;
    help|--help|-h) usage ;;
    *)
        echo -e "${RED}Unknown subcommand: ${action}${NC}" >&2
        echo -e "Did you mean ${CYAN}ha ${action}${NC}? Home Assistant operations live there." >&2
        usage 1
        ;;
esac
