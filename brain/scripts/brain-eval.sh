#!/bin/bash

# brain eval — implementation behind `brain eval`.
#
# How brAIn's own judgement has held up against what the household did,
# and a replay of its captured first looks against today's prompt. Both go
# through the panel's API on 8099 for the reason `brain check` and
# `brain weekly` do: the panel owns the verdict log, the stores the join
# reads and the runner a replay spends through, and a second route to any
# of them is a second answer waiting to disagree.
#
# Usage:
#   brain eval outcomes [--nightly] [--json]
#   brain eval first_look [--days N] [--max-tokens N] [--max-batches N] [--json]

set -uo pipefail

RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"
# How long `first_look` waits for its replay before printing what it has.
# A replay is minutes of runs and the panel starts it rather than holding
# the request, so this polls.
WAIT_S="${BRAIN_EVAL_WAIT_S:-900}"

usage() {
    cat << 'EOF'
brain eval — how brAIn's judgement has held up

Usage:
  brain eval outcomes            What the Resident decided and what the
                                 household did next: per producer, per
                                 entity, and how its stated confidence held
  brain eval outcomes --nightly  Run the nightly grading pass now
  brain eval first_look          Replay captured first looks against today's
                                 prompt and report agreement with what the
                                 household did. Spends real runs, capped
      --days N                   Captures from the last N days (default 14)
      --max-tokens N             Stop asking past this many tokens (60000)
      --max-batches N            Replay at most this many looks (20)
  --json                         The raw payload

Nothing here changes a prompt or a model. A replay is a number for a person
to read before they change one — promotion is never automatic.
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

# The graded record, as a person reads it.
#
# A heredoc with the payload as an ARGUMENT, never `python3 -c` and never a
# pipe: `tests/test_cli_report_blocks.py` says why for its two siblings, and
# `tests/test_outcomes.py` drives this one out of this file.
print_outcomes() {
    python3 - "$1" <<'PYOUT'
import json, sys
try:
    d = json.loads(sys.argv[1])
except ValueError:
    print("The panel's answer was not JSON.")
    sys.exit(1)
if d.get("error"):
    print("Could not grade: " + str(d["error"]))
    sys.exit(1)
by = d.get("by_outcome") or {}
print(f"{d.get('rows', 0)} verdict(s) on record, {d.get('items', 0)} thing(s) judged")
words = ", ".join(f"{n} {k}" for k, n in by.items() if n)
print("What happened next: " + (words or "nothing yet"))
for stage, row in sorted((d.get("by_stage") or {}).items()):
    print(f"  {stage}: {row.get('agreed', 0)} agreed with the household, "
          f"{row.get('disagreed', 0)} did not")
line = d.get("calibration_line") or ""
print()
print("Calibration: " + (line or "not enough answered investigations yet"))
src = (d.get("tallies") or {}).get("source") or {}
if src:
    print()
    print("By producer (confirmed / wrong / missed of judged):")
    for name, t in list(src.items())[:12]:
        print(f"  {name}: {t.get('confirmed', 0)} / {t.get('wrong', 0)} / "
              f"{t.get('missed', 0)} of {t.get('items', 0)}")
judged = d.get("judgements") or []
print()
if judged:
    print("Judgements standing:")
    for j in judged:
        print(f"  [{j.get('subject')}] {j.get('text')}")
else:
    print("Judgements standing: none")
cands = d.get("candidates") or []
if cands:
    print("Patterns the next reflect run would look at:")
    for c in cands:
        print(f"  {c.get('direction')} — {c.get('subject')} ({c.get('counts')})")
state = d.get("state") or {}
reflect = state.get("reflect") or {}
if reflect.get("held"):
    print("Last reflect run held: " + str(reflect["held"]))
elif reflect.get("error"):
    print("Last reflect run failed: " + str(reflect["error"]))
PYOUT
}

# A replay's report.
print_replay() {
    python3 - "$1" <<'PYEVAL'
import json, sys
try:
    d = json.loads(sys.argv[1])
except ValueError:
    print("The panel's answer was not JSON.")
    sys.exit(1)
if d.get("error"):
    print("Replay failed: " + str(d["error"]))
    sys.exit(1)
rep = d.get("report") or {}
if d.get("running") or not rep:
    print("The replay is still running; ask again with `brain eval first_look --json`.")
    sys.exit(0)
t = rep.get("total") or {}
def pct(x):
    return "n/a" if x is None else f"{x:.0%}"
print(f"Replayed {t.get('batches', 0)} first look(s) against today's prompt, "
      f"{t.get('tokens', 0)} tokens spent")
print(f"  Agreement with the household now:  {t.get('agreed', 0)}/{t.get('labels', 0)} "
      f"({pct(t.get('agreement'))})")
print(f"  Agreement when it was captured:    {pct(t.get('then_agreement'))}")
print(f"  Safety signals kept at their floor: {t.get('safety_held', 0)}/{t.get('safety', 0)}")
if t.get("errors"):
    print(f"  {t['errors']} replay(s) did not come back and are not scored")
if rep.get("skipped"):
    print(f"  {rep['skipped']} look(s) not replayed: the spend cap or the batch cap")
for row in rep.get("rows") or []:
    if row.get("error"):
        print(f"  ✗ {row.get('id')}: {row['error']}")
        continue
    print(f"  {row.get('id')}: {row.get('agreed', 0)}/{row.get('labels', 0)} agree")
print()
print(rep.get("promotion") or "")
if t.get("safety") and t.get("safety_held") != t.get("safety"):
    print("A SAFETY SIGNAL WAS LEFT BELOW ITS FLOOR — that is a bug in the guard.")
    sys.exit(2)
PYEVAL
}

outcomes_cmd() {
    local raw="" nightly=""
    for arg in "$@"; do
        case "$arg" in
            --json) raw=1 ;;
            --nightly) nightly="?nightly=1" ;;
            *) echo -e "${RED}Unknown option: $arg${NC}" >&2; usage 1 ;;
        esac
    done
    local payload
    payload=$(curl -s -m 600 "$PANEL/api/resident/outcomes${nightly}" 2>/dev/null)
    need_panel "$payload"
    if [ -n "$raw" ]; then
        printf '%s\n' "$payload"
        return
    fi
    print_outcomes "$payload"
}

first_look_cmd() {
    local raw="" days=14 tokens=60000 batches=20
    while [ $# -gt 0 ]; do
        case "$1" in
            --json) raw=1 ;;
            --days) days="${2:-14}"; shift ;;
            --max-tokens) tokens="${2:-60000}"; shift ;;
            --max-batches) batches="${2:-20}"; shift ;;
            *) echo -e "${RED}Unknown option: $1${NC}" >&2; usage 1 ;;
        esac
        shift
    done
    case "$days$tokens$batches" in
        *[!0-9]*) echo -e "${RED}--days, --max-tokens and --max-batches take whole numbers${NC}" >&2; exit 1 ;;
    esac
    local started
    started=$(curl -s -m 30 -X POST -H 'Content-Type: application/json' \
        -d "{\"kind\": \"first_look\", \"days\": $days, \"max_tokens\": $tokens, \"max_batches\": $batches}" \
        "$PANEL/api/resident/eval" 2>/dev/null)
    need_panel "$started"
    if printf '%s' "$started" | grep -q '"error"'; then
        if [ -n "$raw" ]; then printf '%s\n' "$started"; exit 1; fi
        print_replay "$started"
        exit 1
    fi
    echo -e "${DIM}Replaying… (up to ${WAIT_S}s)${NC}" >&2
    local waited=0 payload=""
    while [ "$waited" -lt "$WAIT_S" ]; do
        payload=$(curl -s -m 30 "$PANEL/api/resident/eval" 2>/dev/null)
        need_panel "$payload"
        if ! printf '%s' "$payload" | grep -q '"running": true'; then
            break
        fi
        sleep 3
        waited=$((waited + 3))
    done
    if [ -n "$raw" ]; then
        printf '%s\n' "$payload"
        return
    fi
    print_replay "$payload"
}

case "${1:-}" in
    outcomes) shift; outcomes_cmd "$@" ;;
    first_look|first-look) shift; first_look_cmd "$@" ;;
    ""|help|--help|-h) usage 0 ;;
    *)
        echo -e "${RED}Unknown eval: $1${NC}" >&2
        usage 1
        ;;
esac
