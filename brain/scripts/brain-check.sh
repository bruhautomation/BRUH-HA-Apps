#!/bin/bash

# brain check — implementation behind `brain check`.
#
# The house checks, run now. They cost nothing (no Claude run — registry,
# states, statistics, traces and dashboards read straight from Home
# Assistant) and file what they find on the Findings tab, exactly as the
# scheduled pass does. Everything goes through the panel's API on 8099 for
# the same reason `brain findings` does: the panel owns the findings store,
# and a second writer would race it.
#
# Usage:
#   brain check                 Run every check now and print what changed
#   brain check list            The catalog, and when each last ran
#   brain check --json          The raw result

set -uo pipefail

RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"

usage() {
    cat << 'EOF'
brain check — the house checks, run now

Usage:
  brain check            Run every check and print what it filed or cleared
  brain check list       The catalog of checks and the last run
  brain check --json     The raw result of a run

The checks read Home Assistant directly and never call Claude. What they
find lands on the Findings tab under a "check" label and rides into the
next analysis, so Claude judges rather than searches.
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

list_checks() {
    local payload
    payload=$(curl -s -m 10 "$PANEL/api/checks" 2>/dev/null)
    need_panel "$payload"
    printf '%s' "$payload" | python3 -c '
import json, sys, time
d = json.load(sys.stdin)
last = d.get("last") or {}
if last.get("finished_at"):
    ago = int(time.time() - last["finished_at"])
    unit = "s" if ago < 120 else "m" if ago < 7200 else "h"
    n = ago if unit == "s" else ago // 60 if unit == "m" else ago // 3600
    print(f"Last run {n}{unit} ago: {last.get(\"created\", 0)} filed, "
          f"{last.get(\"cleared\", 0)} cleared, {len(last.get(\"ran\", []))} checks ran")
else:
    print("No run yet (the first one starts two minutes after the panel).")
print()
per = last.get("per_check") or {}
errs = last.get("errors") or {}
skipped = last.get("skipped") or {}
for c in d.get("catalog") or []:
    cid = c["id"]
    if cid in errs:
        state = "ERROR " + errs[cid]
    elif cid in skipped:
        state = "skipped: " + skipped[cid]
    elif cid in per:
        state = f"{per[cid]} found"
    else:
        state = "-"
    print(f"  {cid:<32} {c[\"title\"]:<44} {state}")
'
}

run_checks() {
    local raw="${1:-}"
    local payload
    payload=$(curl -s -m 300 -X POST "$PANEL/api/checks/run" 2>/dev/null)
    need_panel "$payload"
    if [ "$raw" = "--json" ]; then
        printf '%s\n' "$payload"
        return
    fi
    printf '%s' "$payload" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if d.get("error"):
    print("Checks did not run: " + str(d["error"]))
    sys.exit(1)
ran = d.get("ran") or []
print(f"{len(ran)} checks ran in {d.get(\"duration_s\", 0):.1f}s: "
      f"{len(d.get(\"created\") or [])} new finding(s), "
      f"{d.get(\"refreshed\", 0)} refreshed, {len(d.get(\"cleared\") or [])} cleared")
for f in d.get("created") or []:
    print(f"  + [{f.get(\"severity\", \"?\")}] {f.get(\"text\", \"\")}")
for f in d.get("cleared") or []:
    print(f"  - {f.get(\"text\", \"\")}")
for cid, why in (d.get("skipped") or {}).items():
    print(f"  skipped {cid}: {why}")
for cid, err in (d.get("errors") or {}).items():
    print(f"  ERROR {cid}: {err}")
snap = d.get("snapshot_errors") or {}
for key, err in snap.items():
    print(f"  could not fetch {key}: {err}")
'
}

case "${1:-run}" in
    run) run_checks "${2:-}" ;;
    list) list_checks ;;
    --json) run_checks --json ;;
    help|--help|-h) usage ;;
    *)
        echo -e "${RED}Unknown action: $1${NC}" >&2
        usage 1
        ;;
esac
