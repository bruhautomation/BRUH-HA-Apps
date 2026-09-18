#!/bin/bash

# brain-findings — implementation behind `brain findings`.
#
# The Findings tab, scriptable. The panel owns the store (/data/findings.json
# — deliberately not readable from here), so everything goes through its API
# on 8099, which is the same code path every button on the tab presses. That
# is the point: a CLI that edited the store directly would be a second writer
# racing the panel's own, and would skip the settled ledger, the memory line
# and the undo token those endings exist to write.
#
# Usage:
#   brain findings [list]              What brAIn thinks is broken
#   brain findings fix <id>            Ask what fixing one would change —
#                                      a read-only look that changes nothing
#   brain findings apply <id>          Yes, do exactly that (the only path
#                                      that changes the house)
#   brain findings cancel <id>         No; the plan stays on the card
#   brain findings undo <id>           Put back what a fix changed
#   brain findings done <id> [note]    "I've fixed it myself"
#   brain findings wrong <id> [note]   "That is not a problem here"
#   brain findings ack <id>            "Got it" — after an automated fix
#   brain findings snooze <id> [when]  hour | tomorrow | week | month | now

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"

usage() {
    cat << 'EOF'
brain findings — what brAIn thinks is broken in your home

Usage:
  brain findings                   List open findings (and guesses waiting)
  brain findings fix <id>          Ask what fixing one WOULD change; nothing
                                   is changed until you apply it
  brain findings apply <id>        Make the change it planned — this one does
                                   change the house
  brain findings cancel <id>       Don't; the plan stays, so you can read it
  brain findings undo <id>         Put back the files a fix changed (service
                                   calls it made are listed, not reversed)
  brain findings done <id> [note]  Mark one fixed by you; the note teaches
  brain findings wrong <id> [note] Not a problem here; the note teaches more
  brain findings ack <id>          Acknowledge an automated fix you've read
  brain findings snooze <id> [when]  hour | tomorrow | week | month | now

The <id> is the number printed by `brain findings`. Notes are optional but
valuable: "the cupboard sensor is meant to sit closed" stops every future
report built on the same wrong assumption.
EOF
    exit "${1:-0}"
}

# One GET, pretty-printed. python3 is in the image; the panel's JSON is the
# same payload the tab renders, so what you see here is what it shows.
list_findings() {
    local payload
    payload=$(curl -s -m 10 "$PANEL/api/findings" 2>/dev/null)
    if [ -z "$payload" ]; then
        echo -e "${RED}The panel is not answering on ${PANEL}.${NC}" >&2
        echo -e "${DIM}Is the add-on running? (brain doctor checks this)${NC}" >&2
        exit 1
    fi
    BRAIN_FINDINGS_JSON="$payload" python3 - << 'PYEOF'
import json, os, time

payload = json.loads(os.environ["BRAIN_FINDINGS_JSON"])
findings = payload.get("findings") or []
guesses = payload.get("hypotheses") or []

SEV = {"critical": "\033[0;31m", "serious": "\033[0;31m",
       "warning": "\033[1;33m", "info": "\033[2m"}
STATUS = {"planning": "working out what it would change (nothing yet)",
          "planned": "a plan is waiting on you — see the steps below",
          "fixing": "Claude is fixing it now",
          "fixed": "fixed by brAIn — run `brain findings ack <id>` once read, "
                   "or `brain findings undo <id>` to put it back",
          "failed": "a fix was tried and failed",
          "needs_you": "needs your hands"}
DIM, CYAN, NC = "\033[2m", "\033[0;36m", "\033[0m"

now = time.time()
live = [f for f in findings if f.get("status") in
        ("open", "planning", "planned", "fixing", "fixed", "failed",
         "needs_you")]
if not live and not guesses:
    print(f"{DIM}Nothing waiting on you — the list is empty.{NC}")
    raise SystemExit

for f in live:
    snoozed = (f.get("snoozed_until") or 0) > now
    sev = f.get("severity", "warning")
    color = SEV.get(sev, "")
    line = f"{CYAN}{f['ts']}{NC}  {color}[{sev}]{NC} {f['text']}"
    if snoozed:
        line += f" {DIM}(snoozed){NC}"
    print(line)
    if f.get("detail"):
        print(f"      {DIM}{f['detail']}{NC}")
    if f.get("status") in STATUS:
        print(f"      {DIM}→ {STATUS[f['status']]}{NC}")
    if f.get("status") == "open" and f.get("fix"):
        print(f"      {DIM}suggested: {f['fix']}{NC}")
    # The steps ARE the decision, so `apply` from here is not a press in
    # the dark: what the panel puts on the card is printed here too.
    plan = f.get("plan") or {}
    if f.get("status") == "planned":
        if plan.get("summary"):
            print(f"      {DIM}{plan['summary']}{NC}")
        for i, step in enumerate(plan.get("steps") or [], 1):
            print(f"      {DIM}{i}. {step}{NC}")
        if plan.get("risk"):
            print(f"      {DIM}what could go wrong: {plan['risk']}{NC}")
        if plan.get("can_fix"):
            print(f"      {DIM}-> `brain findings apply {f['ts']}` or "
                  f"`brain findings cancel {f['ts']}`{NC}")
        else:
            print(f"      {DIM}-> brAIn will not make this change itself: "
                  f"`brain findings cancel {f['ts']}`{NC}")
    if f.get("status") == "fixed" and (f.get("fix_files") or f.get("fix_calls")):
        print(f"      {DIM}it changed {f.get('fix_files', 0)} file(s) and made "
              f"{f.get('fix_calls', 0)} service call(s); undo puts the files "
              f"back, not the calls{NC}")

if guesses:
    print(f"\n{DIM}Guesses waiting on a yes/no (answer in the panel's "
          f"Findings tab, or `brain memory hypotheses`):{NC}")
    for g in guesses:
        print(f"  {DIM}- {g.get('text', '')}{NC}")
PYEOF
}

# POST one verb at one finding; the panel's own error text is the message.
act() {
    local method_path="$1" body="$2" ok_msg="$3"
    local response http_code
    response=$(curl -s -m 30 -w '\n%{http_code}' -X POST \
        -H "Content-Type: application/json" -d "$body" \
        "$PANEL$method_path" 2>/dev/null)
    http_code="${response##*$'\n'}"
    response="${response%$'\n'*}"
    if [ "$http_code" = "200" ]; then
        echo -e "${GREEN}${ok_msg}${NC}"
    else
        echo -e "${RED}${response:-the panel did not answer}${NC}" >&2
        exit 1
    fi
}

require_id() {
    if ! [[ "${1:-}" =~ ^[0-9]+$ ]]; then
        echo -e "${RED}Give the finding's id — the number \`brain findings\` prints.${NC}" >&2
        exit 1
    fi
}

action="${1:-list}"
shift 2>/dev/null || true

case "$action" in
    list|"")
        list_findings ;;
    fix)
        require_id "${1:-}"
        act "/api/finding/$1/fix" '{}' \
            "Queued. Claude is working out what it would change — nothing is being changed. Run \`brain findings\` again to read the plan." ;;
    apply)
        require_id "${1:-}"
        act "/api/finding/$1/apply" '{}' \
            "Queued. Claude is making that change — watch the Findings tab, or run \`brain findings\` again." ;;
    cancel)
        require_id "${1:-}"
        act "/api/finding/$1/cancel" '{}' \
            "Left alone. The plan is still on the finding, so reading it again costs nothing." ;;
    undo)
        # `undo` here, `unfix` on the wire: the word a person types is the
        # one they already use for taking something back, and the route is
        # named for what it undoes so it cannot be read as the toast's.
        require_id "${1:-}"
        act "/api/finding/$1/unfix" '{}' \
            "Put back — run \`brain findings\` to read what came back and what did not." ;;
    done)
        require_id "${1:-}"
        note=$(printf '%s' "${2:-}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
        act "/api/finding/$1/done" "{\"note\": $note}" "Marked as fixed by you — brAIn will remember."
        ;;
    wrong)
        require_id "${1:-}"
        note=$(printf '%s' "${2:-}" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')
        act "/api/finding/$1/wrong" "{\"note\": $note}" "Settled — brAIn won't raise that again."
        ;;
    ack)
        require_id "${1:-}"
        act "/api/finding/$1/ack" '{}' "Acknowledged."
        ;;
    snooze)
        require_id "${1:-}"
        act "/api/finding/$1/snooze" "{\"for\": \"${2:-tomorrow}\"}" \
            "Snoozed — it comes back by itself."
        ;;
    help|--help|-h)
        usage ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage 1 ;;
esac
