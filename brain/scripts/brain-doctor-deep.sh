#!/bin/bash

# brain doctor --deep / --rehearse — implementation behind the two costed
# self-checks.
#
# `brain doctor` on its own is unchanged and lives in ha-selftest.sh: it
# answers "is the plumbing connected" and spends nothing. These two answer
# "does each face work end to end on this install" and "do the checks and
# the analyst find a defect planted in this house", and both spend real
# Claude turns — so both are opt-in, both are started by hand, and neither
# is ever on a timer.
#
# Everything goes through the panel's API on 8099 for the same reason
# `brain check` and `brain findings` do: the panel owns the stores, the
# generation queue and the one-Claude-run-at-a-time rule, and a second
# driver would race all three.
#
# Usage:
#   brain doctor --deep [--json]
#   brain doctor --rehearse [--yes] [--json]

set -uo pipefail

RED='\033[0;31m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"
# A deep run is eight round trips, several of them a whole Claude turn, and
# the rehearsal writes to automations.yaml and waits for Core twice. The
# poll is what keeps the wait honest — nothing here holds one long request
# open, because ingress cuts those and the absence of a reply is the one
# failure mode a self-check must not have.
POLL_S="${BRAIN_DOCTOR_POLL_S:-3}"
MAX_WAIT_S="${BRAIN_DOCTOR_MAX_WAIT_S:-3600}"

usage() {
    cat << 'EOF'
brain doctor --deep / --rehearse — the two costed self-checks

Usage:
  brain doctor                 The free one: is the plumbing connected
  brain doctor --deep          Every face, one real round trip each
  brain doctor --deep --json   The whole object

  brain doctor --rehearse      Plant a few defects under a brain_test_
                               prefix, run the checks and the analyst
                               against them, score both, remove everything
  brain doctor --rehearse --yes    Skip the confirmation
  brain doctor --rehearse --json   The whole object

--deep spends a handful of Claude turns (roughly five: a no-tool run, an
analyst run, one chat turn, one automation task, one consolidation pass and
one fix run). --rehearse spends one analyst run and writes to
automations.yaml through the same path an accepted proposal uses, then
takes it back out again. Neither ever runs on a timer.
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

# Print the stages that have landed since the last call. Reads the whole
# payload on stdin and the count already printed in $1; echoes the new
# count so the caller can carry it.
print_new_stages() {
    python3 -c '
import json, sys
already = int(sys.argv[1])
try:
    data = json.load(sys.stdin)
except ValueError:
    print(already)
    sys.exit(0)
stages = data.get("stages") or []
mark = {"ok": "\033[0;32m✓\033[0m", "failed": "\033[0;31m✗\033[0m",
        "skipped": "\033[0;33m–\033[0m"}
for s in stages[already:]:
    secs = f" ({s.get(\"seconds\", 0):.0f}s)" if s.get("seconds") else ""
    sys.stderr.write(f"  {mark.get(s[\"state\"], \" \")} {s.get(\"title\", s[\"name\"])}{secs}\n")
    sys.stderr.write(f"      {s.get(\"sentence\", \"\")}\n")
    if s.get("detail"):
        sys.stderr.write(f"      \033[2m{s[\"detail\"]}\033[0m\n")
print(len(stages))
' "$1"
}

# The verdict line, and the exit code. Reads the finished payload on stdin.
print_verdict() {
    python3 -c '
import json, sys
data = json.load(sys.stdin)
last = data.get("last") or data
counts = last.get("counts") or {}
verdict = last.get("verdict") or "?"
print()
print(f"  {counts.get(\"ok\", 0)} passed, {counts.get(\"failed\", 0)} failed, "
      f"{counts.get(\"skipped\", 0)} skipped")
if verdict == "failed":
    print(f"  First failure: {last.get(\"failed_stage\") or \"?\"}")
    sys.exit(1)
sys.exit(0)
'
}

run_deep() {
    local raw="${1:-}" payload started printed=0 waited=0
    started=$(curl -s -m 30 -X POST "$PANEL/api/doctor/deep" 2>/dev/null)
    need_panel "$started"
    if printf '%s' "$started" | grep -q '"error"'; then
        # Already running is not a failure of this invocation: watch the
        # run that is going rather than starting a second one.
        printf '%s' "$started" | python3 -c '
import json, sys
print("Already running: " + str(json.load(sys.stdin).get("error") or ""))
' >&2
    fi

    [ "$raw" = "--json" ] || echo "brAIn — deep check (this spends Claude turns)" >&2
    while [ "$waited" -lt "$MAX_WAIT_S" ]; do
        payload=$(curl -s -m 30 "$PANEL/api/doctor/deep" 2>/dev/null)
        need_panel "$payload"
        if [ "$raw" != "--json" ]; then
            printed=$(printf '%s' "$payload" | print_new_stages "$printed")
        fi
        if ! printf '%s' "$payload" | grep -q '"running": *true'; then
            break
        fi
        sleep "$POLL_S"
        waited=$((waited + POLL_S))
    done

    if [ "$raw" = "--json" ]; then
        printf '%s\n' "$payload"
        printf '%s' "$payload" | python3 -c '
import json, sys
last = (json.load(sys.stdin).get("last") or {})
sys.exit(1 if last.get("verdict") == "failed" else 0)
'
        return
    fi
    printf '%s' "$payload" | print_verdict
}

run_rehearsal() {
    local yes="" raw=""
    for arg in "$@"; do
        case "$arg" in
            --yes|-y) yes=1 ;;
            --json) raw=--json ;;
        esac
    done

    # Consent is a named step: the panel answers 428 with the exact list of
    # what it would create, and nothing is created until this comes back
    # with {"consent": true}.
    local plan
    plan=$(curl -s -m 30 -X POST -H 'Content-Type: application/json' \
        -d '{}' "$PANEL/api/doctor/rehearse" 2>/dev/null)
    need_panel "$plan"
    if printf '%s' "$plan" | grep -q '"refused"'; then
        printf '%s' "$plan" | python3 -c '
import json, sys
print(json.load(sys.stdin).get("refused") or "refused")
' >&2
        exit 1
    fi
    if [ -z "$yes" ]; then
        printf '%s' "$plan" | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("A rehearsal creates these in your Home Assistant, runs the checks "
      "and the analyst against them, and then removes them:")
for row in d.get("plan") or []:
    print(f"  {row.get(\"id\", \"?\")}")
    print(f"      {row.get(\"what\", \"\")}")
    print(f"      \033[2mfor {row.get(\"proves\", \"\")}\033[0m")
for row in d.get("not_rehearsable") or []:
    print(f"  \033[2m{row.get(\"check\", \"?\")} cannot be rehearsed in one "
          f"pass: {row.get(\"why\", \"\")}\033[0m")
'
        printf 'Go ahead? [y/N] '
        read -r reply
        case "$reply" in
            y|Y|yes|YES) ;;
            *) echo "Nothing was created."; exit 0 ;;
        esac
    fi

    local started payload waited=0
    started=$(curl -s -m 30 -X POST -H 'Content-Type: application/json' \
        -d '{"consent": true}' "$PANEL/api/doctor/rehearse" 2>/dev/null)
    need_panel "$started"
    [ "$raw" = "--json" ] || echo "Rehearsing…" >&2
    while [ "$waited" -lt "$MAX_WAIT_S" ]; do
        payload=$(curl -s -m 30 "$PANEL/api/doctor/rehearse" 2>/dev/null)
        need_panel "$payload"
        printf '%s' "$payload" | grep -q '"running": *true' || break
        sleep "$POLL_S"
        waited=$((waited + POLL_S))
    done

    if [ "$raw" = "--json" ]; then
        printf '%s\n' "$payload"
    fi
    printf '%s' "$payload" | python3 -c '
import json, sys
last = (json.load(sys.stdin).get("last") or {})
raw = "'"$raw"'" == "--json"
checks = last.get("checks") or {}
analyst = last.get("analyst") or {}
cleanup = last.get("cleanup") or {}
if not raw:
    print()
    print(f"  Checks:  {checks.get(\"found\", 0)} of "
          f"{checks.get(\"planted\", 0)} planted defects found, "
          f"{checks.get(\"extra\", 0)} reported that were not planted")
    for row in checks.get("rows") or []:
        print(f"    {row.get(\"verdict\", \"?\"):<7} {row.get(\"id\", \"\")}"
              f"  ({row.get(\"check\", \"\")})")
    if analyst.get("ran"):
        print(f"  Analyst: found {analyst.get(\"found\", 0)} of "
              f"{analyst.get(\"planted\", 0)} "
              f"(recall {analyst.get(\"recall\", 0):.0%}, "
              f"precision {analyst.get(\"precision\", 0):.0%}) "
              f"on {analyst.get(\"model\") or \"the default model\"}")
    else:
        print(f"  Analyst: did not run — {analyst.get(\"error\") or \"?\"}")
    print(f"  Cleanup: {cleanup.get(\"sentence\") or \"?\"}")
sys.exit(0 if cleanup.get("ok") and not last.get("error") else 1)
'
}

case "${1:-}" in
    --deep)     shift; run_deep "${1:-}" ;;
    --rehearse) shift; run_rehearsal "$@" ;;
    help|--help|-h|"") usage ;;
    *)
        echo -e "${RED}Unknown flag: $1${NC}" >&2
        usage 1
        ;;
esac
