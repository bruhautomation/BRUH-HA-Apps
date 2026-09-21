#!/bin/bash

# brain why — implementation behind `brain why`.
#
# What brAIn is curious about, what it has worked out, and — with `ask` —
# the next question asked now rather than on the next checks pass.
#
# Everything goes through the panel's API on 8099 for the reason `brain
# findings` and `brain check` do: the panel owns the two stores, and a
# second writer would race the settling that makes the budget a budget.
#
# Usage:
#   brain why                   What it is curious about, and what it learned
#   brain why ask               Ask the next question now — SPENDS a Claude run
#   brain why --json            The raw payload

set -uo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"

usage() {
    cat << 'EOF'
brain why — why somebody did something by hand

Usage:
  brain why              What brAIn is curious about, and what it worked out
  brain why ask          Ask the next question now — this spends a Claude run
  brain why --json       The raw payload

brAIn keeps the things somebody here does by hand and, once a day at most,
spends one Claude run working out WHY — the weather and the sun at that
moment, the season, the history around it. What it works out becomes a
plain fact in memory; what it can only guess at becomes one short question
on the Findings tab. It never asks twice about the same thing, and it will
not ask about locks, alarms or where anybody is.

`ask` ignores the one-a-day budget, because that budget is about what an
unattended schedule may spend and you have just asked. It does not ignore
the settling: something already asked about stays asked about.
EOF
    exit "${1:-0}"
}

need_panel() {
    if [ -z "$1" ]; then
        echo -e "${RED}The panel is not answering on ${PANEL}.${NC}" >&2
        echo -e "${DIM}Is the add-on running? (brain doctor checks this)${NC}" >&2
        exit 1
    fi
}

# A heredoc rather than `python3 -c '...'`, and the payload as an ARGUMENT
# rather than on stdin — see the long note in brain-check.sh: shell single
# quotes leave no way to put a `"` inside an f-string expression except a
# backslash, which is a SyntaxError before 3.12, so a block written that
# way parses on the image and nowhere else; and a heredoc IS stdin, so
# piping the payload in delivers nothing and reads as an empty answer
# rather than as an error. `tests/test_cli_report_blocks.py` drives it.
print_state() {
    python3 - "$1" <<'PYSTATE'
import json
import sys

try:
    d = json.loads(sys.argv[1] or "{}")
except ValueError:
    print("The panel answered something that is not JSON.")
    raise SystemExit(1)

if d.get("error"):
    print(f"Could not read it: {d['error']}")
    raise SystemExit(1)

if not d.get("enabled"):
    print("Off. Turn on 'Ask why you did something' in the add-on")
    print("configuration to let brAIn work out why things happen here.")
    raise SystemExit(0)

ev = d.get("evidence") or {}
if ev.get("state") == "collecting":
    print(f"Watching — {ev.get('note') or 'not enough days yet'}.")
else:
    kept = d.get("manual_actions") or 0
    print(f"{kept} manual action{'' if kept == 1 else 's'} kept; "
          f"{d.get('curious_total') or 0} brAIn cannot account for.")

b = d.get("budget") or {}
print(f"Asked {b.get('day', 0)} of {b.get('per_day', 1)} today, "
      f"{b.get('week', 0)} of {b.get('per_week', 3)} this week.")
if d.get("holding"):
    print(f"  {d['holding']}.")
if d.get("running"):
    print("  Working one out right now.")

counts = d.get("counts") or {}
print(f"Worked out {counts.get('explained', 0)}, asked you about "
      f"{counts.get('guessed', 0)}, could not tell "
      f"{counts.get('unknown', 0)}.")

queue = d.get("curious_about") or []
if queue:
    print("\nCurious about:")
    for row in queue[:5]:
        line = row.get("why") or row.get("subject") or ""
        print(f"  - {line}")
        # Why this one will NOT be asked is the half somebody reading
        # this wants: "not now" and "never again" are different silences.
        if row.get("skip"):
            print(f"      {row['skip']}")
        elif row.get("hold"):
            print(f"      waiting: {row['hold']}")

learned = d.get("learned") or []
if learned:
    print("\nLately:")
    for row in learned[:6]:
        name = row.get("name") or row.get("subject") or "?"
        filed = row.get("filed")
        where = {"memory": "into memory",
                 "hypothesis": "asked you on the Findings tab",
                 "hypothesis-refused": "not asked — the question queue is full",
                 }.get(filed, "nothing filed")
        print(f"  - {name}: {row.get('because') or row.get('error') or '?'}")
        print(f"      {where}")
PYSTATE
}

# What the route said it was going to ask about. A heredoc and an argument
# for the same two reasons print_state is: `python3 -c` cannot hold a `"`
# inside an f-string expression on the image's interpreter, and a heredoc
# IS stdin, so a piped payload arrives empty — which here would read as a
# run that named nothing rather than as a bug.
print_why() {
    python3 - "$1" <<'PYWHY'
import json
import sys

try:
    print(json.loads(sys.argv[1] or "{}").get("why") or "")
except ValueError:
    pass
PYWHY
}

case "${1:-}" in
    -h|--help|help) usage 0 ;;
esac

if [ "${1:-}" = "ask" ]; then
    echo -e "${BLUE}Asking the next question — this spends a Claude run.${NC}"
    body=$(curl -sf -m 30 -X POST "${PANEL}/api/curiosity/ask" 2>/dev/null)
    if [ -z "$body" ]; then
        # A 409 is an answer rather than an error: either one is already
        # running, or there is nothing brAIn cannot already account for.
        state=$(curl -sf -m 15 "${PANEL}/api/curiosity" 2>/dev/null)
        need_panel "$state"
        echo -e "${YELLOW}Nothing was asked.${NC}" >&2
        print_state "$state"
        exit 1
    fi
    why=$(print_why "$body")
    [ -n "$why" ] && echo -e "${DIM}${why}${NC}"
    echo -e "${GREEN}Started.${NC} It takes a few minutes; run 'brain why' to see"
    echo "what it made of it."
    exit 0
fi

state=$(curl -sf -m 15 "${PANEL}/api/curiosity" 2>/dev/null)
need_panel "$state"

if [ "${1:-}" = "--json" ]; then
    printf '%s\n' "$state"
    exit 0
fi
print_state "$state"
