#!/bin/bash

# brain devloop — the development loop, from the terminal or the chat.
#
# Everything goes through the panel's API on 8099, which owns the queue
# and the token; this script never sees the token.
#
# Usage:
#   brain devloop                 Status: what is on, what ran, what is queued
#   brain devloop run [stream]    Run every switched-on stream now, or one
#   brain devloop look "<topic>"  Investigate one thing and file what is found

set -uo pipefail

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"

usage() {
    cat << 'EOF'
brain devloop — file what brAIn gets wrong as issues in your private repo

Usage:
  brain devloop                 What is on, what ran last, what is queued
  brain devloop run [stream]    Run now: every switched-on stream, or one
                                (faults, scorecard, wrongs, unmet, snapshot,
                                gaps, ideas)
  brain devloop look "<topic>"  One read-only Claude run looking into what
                                you name; what it finds is filed as issues

Switch it on and set the repository in ⚙ → Diagnostics → Developer.
EOF
    exit "${1:-0}"
}

call() {
    # $1 method, $2 path, $3 optional JSON body
    if [ -n "${3:-}" ]; then
        curl -sS --noproxy '*' -X "$1" -H 'Content-Type: application/json' \
            --data "$3" "${PANEL}/$2"
    else
        curl -sS --noproxy '*' -X "$1" "${PANEL}/$2"
    fi
}

show() {
    python3 - "$1" << 'PY'
import json, sys
try:
    data = json.loads(sys.argv[1])
except ValueError:
    print(sys.argv[1]); sys.exit(1)
if "error" in data and len(data) == 1:
    print("refused: " + str(data["error"])); sys.exit(1)
s = data.get("settings") or {}
print("on" if s.get("enabled") else "off",
      "· repo " + (s.get("repo") or "(none)"),
      "· token " + ("set" if data.get("token_set") else "missing"))
last = (data.get("status") or {}).get("last_run") or {}
for st in data.get("streams") or []:
    name = st.get("name")
    mark = "x" if (s.get("streams") or {}).get(name) else " "
    hours = (s.get("schedule") or {}).get(name)
    print(f"  [{mark}] {name:<10} every {hours}h" if hours else
          f"  [{mark}] {name:<10} when asked")
err = (data.get("status") or {}).get("error")
if err:
    print("last error: " + str(err))
queue = data.get("queue") or []
print(str(len(queue)) + " in the queue")
for r in data.get("ran", {}).items() if isinstance(data.get("ran"), dict) else []:
    print("ran " + str(r[0]) + ": " + json.dumps(r[1]))
PY
}

case "${1:-}" in
    ""|status) show "$(call GET api/devloop)" ;;
    run)
        if [ -n "${2:-}" ]; then
            body=$(python3 - "$2" << 'PY'
import json, sys
print(json.dumps({"stream": sys.argv[1]}))
PY
)
            show "$(call POST api/devloop/run "$body")"
        else
            show "$(call POST api/devloop/run '{}')"
        fi
        ;;
    look)
        shift
        [ $# -lt 1 ] && usage 1
        body=$(python3 - "$*" << 'PY'
import json, sys
print(json.dumps({"topic": sys.argv[1]}))
PY
)
        show "$(call POST api/devloop/look "$body")"
        ;;
    help|--help|-h) usage ;;
    *) usage 1 ;;
esac
