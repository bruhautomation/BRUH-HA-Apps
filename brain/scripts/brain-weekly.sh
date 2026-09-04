#!/bin/bash

# brain weekly — implementation behind `brain weekly`.
#
# The week's own numbers, and the last report that went out. Everything
# goes through the panel's API on 8099 for the same reason `brain check`
# and `brain findings` do: the panel owns the findings store, the energy
# fetch and the send stamp, and a second route to any of them is a second
# answer waiting to disagree.
#
# Usage:
#   brain weekly                What this week holds, and the last report
#   brain weekly send           Write and send this week's report now
#   brain weekly --json         The raw payload

set -uo pipefail

RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"

usage() {
    cat << 'EOF'
brain weekly — the week's report

Usage:
  brain weekly           The week's numbers and the last report sent
  brain weekly send      Write and send this week's report now
  brain weekly --json    The raw payload

Sending one by hand moves the week: the next scheduled report is a week
from now, not a week from Sunday. That is deliberate — two reports about
overlapping weeks make the numbers in both meaningless.
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

show() {
    local raw="${1:-}"
    local payload
    payload=$(curl -s -m 120 "$PANEL/api/weekly" 2>/dev/null)
    need_panel "$payload"
    if [ "$raw" = "--json" ]; then
        printf '%s\n' "$payload"
        return
    fi
    printf '%s' "$payload" | python3 -c '
import json, sys, time
d = json.load(sys.stdin)
state = "on" if d.get("enabled") else "off"
print(f"Weekly report: {state}, {d.get(\"day\", \"?\")}s -> "
      f"{d.get(\"notify_service\") or \"no notify service set\"}")
if d.get("last_sent"):
    days = (time.time() - d["last_sent"]) / 86400
    print(f"Last sent {days:.1f} days ago")
else:
    print("Never sent")
if d.get("last_error"):
    print("Last error: " + str(d["last_error"]))
print()

power = d.get("energy") or {}
if not power.get("available"):
    print("Energy: " + str(power.get("reason") or "not available"))
else:
    for name, key in (("Electricity", "energy"), ("Cost", "cost")):
        half = power.get(key)
        if not half:
            continue
        unit = half.get("unit") or ""
        line = f"{name}: {half[\"this\"]}{unit} over 7 days"
        if half.get("comparable"):
            pct = half.get("change_pct")
            line += (f" vs {half[\"last\"]}{unit} before"
                     + (f" ({pct:+.1f}%)" if pct is not None else ""))
        else:
            line += f" ({half[\"days\"]}/7 days complete — no comparison)"
        print(line)

f = d.get("findings") or {}
print(f"Findings: {f.get(\"settled\", 0)} answered this week "
      f"({f.get(\"confirmed\", 0)} real, {f.get(\"wrong\", 0)} misread), "
      f"{f.get(\"still_open\", 0)} raised and still open, "
      f"{f.get(\"open_now\", 0)} open in total")
for title, count in f.get("by_source") or []:
    print(f"  {count} from {title}")

lore = d.get("learned") or {}
if not lore.get("available"):
    print("Learned: the memory log could not be read")
else:
    print(f"Learned: {lore.get(\"total\", 0)} new, "
          f"{lore.get(\"removed\", 0)} corrected")
    for line in lore.get("added") or []:
        print("  - " + line)

pick = d.get("one_thing")
if pick:
    print(f"\nOne thing to do: [{pick.get(\"severity\", \"?\")}] "
          f"{pick.get(\"text\", \"\")}")
else:
    print("\nOne thing to do: nothing open")

if not d.get("worth_reporting"):
    print("\nThis week holds nothing worth a report; none would be sent.")
if d.get("last_text"):
    print("\nLast report sent:\n" + d["last_text"])
'
}

send() {
    local payload
    payload=$(curl -s -m 400 -X POST "$PANEL/api/weekly/run" 2>/dev/null)
    need_panel "$payload"
    printf '%s' "$payload" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if d.get("error"):
    print("Not sent: " + str(d["error"]))
    sys.exit(1)
if not d.get("sent"):
    print("Nothing was worth reporting this week, so nothing was sent.")
    sys.exit(0)
print(d.get("text") or "")
'
}

case "${1:-show}" in
    show) show "${2:-}" ;;
    send) send ;;
    --json) show --json ;;
    help|--help|-h) usage ;;
    *)
        echo -e "${RED}Unknown action: $1${NC}" >&2
        usage 1
        ;;
esac
