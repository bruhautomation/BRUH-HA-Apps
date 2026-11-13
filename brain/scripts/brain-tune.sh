#!/bin/bash

# brain tune — implementation behind `brain tune`.
#
# Records one thing the household settled about how brAIn should be: the
# question that was asked and what they answered. It lands with the answers
# given in ⚙ › Personality ("What you have told it"), where each can be
# removed, and the next nightly reflection revises the learned paragraph
# from them.
#
# It exists for the conversation brAIn leads from ⚙ › Personality › Talk it
# through, which runs it once per thing it learned. Through the panel's API
# on 8099 for the reason `brain findings` is: the panel owns the store, and
# a second writer would race its own.
#
# Usage:
#   brain tune "<what was asked>" "<what they answered>"

set -uo pipefail

RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"

usage() {
    cat << 'EOF'
brain tune — record how the household wants brAIn to be

Usage:
  brain tune "<what was asked>" "<what they answered>"

One answer per call, in their words. It is kept in ⚙ › Personality under
"What you have told it", where it can be removed, and the next nightly
reflection (or Take this in now) revises how brAIn is from it. Needs
Personality and the Learning loop switched on in ⚙ › Features.
EOF
    exit "${1:-0}"
}

case "${1:-}" in
    help|--help|-h) usage ;;
esac
[ $# -eq 2 ] || usage 1

# The two texts ride as arguments into a heredoc'd script (a heredoc IS
# stdin, and `python3 -c` cannot hold a quote inside an f-string before
# 3.12), which builds the JSON so no quoting of theirs can break it.
payload=$(python3 - "$1" "$2" <<'PYBODY'
import json
import sys

print(json.dumps({"question": sys.argv[1], "answer": sys.argv[2]}))
PYBODY
)

reply=$(curl -s -m 20 -w '\n%{http_code}' -X POST \
    -H 'Content-Type: application/json' -d "$payload" \
    "${PANEL}/api/presence/tuning" 2>/dev/null)
code="${reply##*$'\n'}"
body="${reply%$'\n'*}"

if [ -z "$code" ] || [ "$code" = "000" ]; then
    echo -e "${RED}The panel is not answering on ${PANEL}.${NC}" >&2
    echo -e "${DIM}Is the add-on running? (brain doctor checks this)${NC}" >&2
    exit 1
fi
if [ "$code" != "200" ]; then
    echo -e "${RED}Not recorded: ${body:-the panel answered ${code}}${NC}" >&2
    exit 1
fi
echo "Recorded. It is in ⚙ › Personality under What you have told it."
