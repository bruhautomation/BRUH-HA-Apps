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
#
# A heredoc rather than `python3 -c '...'`: shell single quotes leave no
# way to put a `"` inside an f-string expression except a backslash, and a
# backslash in one is a SyntaxError before Python 3.12 — code that parses
# only on the interpreter the image happens to ship is code nobody can
# test anywhere else. `tests/test_doctor_deep.py` drives both of these.
print_new_stages() {
    python3 - "$1" "$2" <<'PYSTAGES'
import json, sys
already = int(sys.argv[1])
try:
    data = json.loads(sys.argv[2])
except ValueError:
    print(already)
    sys.exit(0)
stages = data.get("stages") or []
mark = {"ok": "\033[0;32m\u2713\033[0m", "failed": "\033[0;31m\u2717\033[0m",
        "skipped": "\033[0;33m\u2013\033[0m"}
for s in stages[already:]:
    secs = s.get("seconds") or 0
    took = f" ({secs:.0f}s)" if secs else ""
    glyph = mark.get(s.get("state", ""), " ")
    title = s.get("title") or s.get("name") or "?"
    sys.stderr.write(f"  {glyph} {title}{took}\n")
    sys.stderr.write("      " + str(s.get("sentence") or "") + "\n")
    if s.get("detail"):
        sys.stderr.write("      \033[2m" + str(s["detail"]) + "\033[0m\n")
print(len(stages))
PYSTAGES
}

# The verdict line, and the exit code. Reads the finished payload on stdin.
print_verdict() {
    python3 - "$1" <<'PYVERDICT'
import json, sys
data = json.loads(sys.argv[1])
last = data.get("last") or data
counts = last.get("counts") or {}
print()
print(f"  {counts.get('ok', 0)} passed, {counts.get('failed', 0)} failed, "
      f"{counts.get('skipped', 0)} skipped")
if last.get("verdict") == "failed":
    print("  First failure: " + str(last.get("failed_stage") or "?"))
    sys.exit(1)
sys.exit(0)
PYVERDICT
}

# The consent offer, as a person reads it before answering y/N.
print_plan() {
    python3 - "$1" <<'PYPLAN'
import json, sys
d = json.loads(sys.argv[1])
print("A rehearsal creates these in your Home Assistant, runs the checks "
      "and the analyst against them, and then removes them:")
for row in d.get("plan") or []:
    print("  " + str(row.get("id") or "?"))
    print("      " + str(row.get("what") or ""))
    print("      \033[2mfor " + str(row.get("proves") or "") + "\033[0m")
for row in d.get("not_rehearsable") or []:
    print("  \033[2m" + str(row.get("check") or "?")
          + " cannot be rehearsed in one pass: "
          + str(row.get("why") or "") + "\033[0m")
PYPLAN
}

# What the rehearsal scored, and the exit code. `$1` is "--json" when the
# raw object has already been printed and this is only here for the code.
print_score() {
    python3 - "${1:-}" "$2" <<'PYSCORE'
import json, sys
raw = sys.argv[1] == "--json"
last = (json.loads(sys.argv[2]).get("last") or {})
checks = last.get("checks") or {}
analyst = last.get("analyst") or {}
cleanup = last.get("cleanup") or {}
if not raw:
    print()
    print(f"  Checks:  {checks.get('found', 0)} of "
          f"{checks.get('planted', 0)} planted defects found, "
          f"{checks.get('extra', 0)} reported that were not planted")
    for row in checks.get("rows") or []:
        verdict = str(row.get("verdict") or "?")
        print(f"    {verdict:<15} {row.get('id', '')}"
              f"  ({row.get('check', '')})")
    if analyst.get("ran"):
        print(f"  Analyst: found {analyst.get('found', 0)} of "
              f"{analyst.get('planted', 0)} "
              f"(recall {analyst.get('recall', 0):.0%}, "
              f"precision {analyst.get('precision', 0):.0%}) "
              f"on {analyst.get('model') or 'the default model'}")
    else:
        print("  Analyst: did not run - "
              + str(analyst.get("error") or "?"))
    print("  Cleanup: " + str(cleanup.get("sentence") or "?"))
sys.exit(0 if cleanup.get("ok") and not last.get("error") else 1)
PYSCORE
}

run_deep() {
    local raw="${1:-}" payload started printed=0 waited=0
    started=$(curl -s -m 30 -X POST "$PANEL/api/doctor/deep" 2>/dev/null)
    need_panel "$started"
    if printf '%s' "$started" | grep -q '"error"'; then
        # Already running is not a failure of this invocation: watch the
        # run that is going rather than starting a second one.
        python3 - "$started" >&2 <<'PYBUSY'
import json, sys
print("Already running: " + str(json.loads(sys.argv[1]).get("error") or ""))
PYBUSY
    fi

    [ "$raw" = "--json" ] || echo "brAIn — deep check (this spends Claude turns)" >&2
    while [ "$waited" -lt "$MAX_WAIT_S" ]; do
        payload=$(curl -s -m 30 "$PANEL/api/doctor/deep" 2>/dev/null)
        need_panel "$payload"
        if [ "$raw" != "--json" ]; then
            printed=$(print_new_stages "$printed" "$payload")
        fi
        if ! printf '%s' "$payload" | grep -q '"running": *true'; then
            break
        fi
        sleep "$POLL_S"
        waited=$((waited + POLL_S))
    done

    if [ "$raw" = "--json" ]; then
        printf '%s\n' "$payload"
        python3 - "$payload" <<'PYRC'
import json, sys
last = (json.loads(sys.argv[1]).get("last") or {})
sys.exit(1 if last.get("verdict") == "failed" else 0)
PYRC
        return
    fi
    print_verdict "$payload"
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
        python3 - "$plan" >&2 <<'PYREFUSED'
import json, sys
print(json.loads(sys.argv[1]).get("refused") or "refused")
PYREFUSED
        exit 1
    fi
    if [ -z "$yes" ]; then
        print_plan "$plan"
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
    print_score "$raw" "$payload"
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
