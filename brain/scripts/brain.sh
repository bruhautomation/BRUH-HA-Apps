#!/bin/bash

# brain — brAIn's own faculties: memory, learning, and undo.
#
# Home Assistant operations live under the sibling `ha` command; the split
# keeps "brain log" (which log?) from ever being a question someone has to
# ask. Each subcommand delegates to a script in /opt/scripts.
#
# Usage:
#   brain memory <action> [args]   Long-term home memory (add/list/edit/...)
#   brain findings <action> [args] The work list (list/fix/done/wrong/...)
#   brain learn [topic]            Run a study session on the home
#   brain ask "<question>"         One-shot question, same engine as the Ask card
#   brain undo [n]                 Review and revert Claude's file edits
#   brain login                    Sign in to Claude (same as `ha login`)
#   brain check                    Run the house checks now (no Claude run)
#   brain doctor [--json]          End-to-end diagnostic
#   brain doctor --deep            Every face, one real round trip each
#   brain doctor --rehearse        Plant defects, score the checks, clean up
#   brain report                   Redacted diagnostics bundle for a bug report
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
      inbox                      Facts queued, not yet filed into memory
      log [n]                    What it learned recently
      undo [n]                   Revert a memory change
      hypotheses                 Pending guesses awaiting your yes/no
      confirm "<text>"           Confirm a pending guess
      reject "<text>"            Reject a pending guess
      consolidate                Fold pending facts in now
      clear --confirm            Reset the document to an empty template
      export [file]              Everything learned, as one portable file
      import <file>              Fold an export back in

  brain findings <action>        What brAIn thinks is broken
      list                       Print the work list (default)
      fix <id>                   Let Claude fix one
      done <id> ["note"]         Mark one fixed by you
      wrong <id> ["note"]        Not a problem here — never raise it again
      ack <id>                   Acknowledge an automated fix
      snooze <id> [when]         hour | tomorrow | week | month | now

  brain learn [topic]            Study the home and write down what it finds
  brain ask "<question>"         Ask about the home (same engine as the Ask card)
  brain undo [n]                 Review and revert Claude's edits to /config
  brain check [list]             Run the house checks now — no Claude run,
                                 findings land on the Findings tab
  brain weekly [send]            The week's report: energy, findings, what was
                                 learned, and the one thing to do
  brain doctor [--json]          End-to-end diagnostic of brAIn itself —
                                 free, and never calls Claude
  brain doctor --deep [--json]   Every face of brAIn, one real round trip
                                 each: a plain Claude run, the analyst's
                                 tools, a chat turn, an automation task,
                                 Assist, memory, findings and one fix.
                                 Spends about five Claude turns; only ever
                                 runs when you ask for it
  brain doctor --rehearse [--yes]
                                 Plant a few defects under a brain_test_
                                 prefix, run the checks and the analyst
                                 against them, score both, then remove
                                 everything. Asks first, and says exactly
                                 what it would create
  brain report [--no-names]      Write a redacted diagnostics bundle to
                                 /share/brain/reports for a bug report
  brain login [--status|--share] Sign in to Claude, and share that login with
                                 other BRUH add-ons. Same command as `ha login`
                                 — it is listed here because the credential is
                                 brAIn's, not Home Assistant's, and this is
                                 where people look for it. Also on the panel:
                                 ⚙ Settings → Claude account.
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
    # Exec the file itself so its shebang runs it: `bash "$path"` ignored
    # `#!/usr/bin/with-contenv bashio`, so any delegated script calling
    # bashio:: functions died with 127 on its first log line.
    if [ -x "$path" ]; then
        exec "$path" "$@"
    fi
    exec bash "$path" "$@"
}

[ $# -lt 1 ] && usage

action="$1"
shift

case "$action" in
    memory)     delegate brain-memory.sh "$@" ;;
    findings)   delegate brain-findings.sh "$@" ;;
    learn)      delegate brain-learn.sh "$@" ;;
    ask)        delegate brain-ask.sh "$@" ;;
    undo)       delegate brain-undo.sh "$@" ;;
    check)      delegate brain-check.sh "$@" ;;
    weekly)     delegate brain-weekly.sh "$@" ;;
    doctor)
        # Plain `brain doctor` is unchanged: it is the free one, and the
        # two costed checks are a different script rather than a flag
        # inside it, so nothing about the free one can drift.
        case "${1:-}" in
            --deep|--rehearse) delegate brain-doctor-deep.sh "$@" ;;
            *)                 delegate ha-selftest.sh "$@" ;;
        esac
        ;;
    report)     delegate brain-report.sh "$@" ;;
    login)      delegate ha-share-login.sh "$@" ;;
    help|--help|-h) usage ;;
    *)
        echo -e "${RED}Unknown subcommand: ${action}${NC}" >&2
        echo -e "Did you mean ${CYAN}ha ${action}${NC}? Home Assistant operations live there." >&2
        usage 1
        ;;
esac
