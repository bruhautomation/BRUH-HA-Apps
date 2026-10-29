#!/usr/bin/env bash

# ha-notify — Send notifications via Home Assistant
# Usage:
#   ha-notify "message" [--title "title"] [--target <name>|all]
# Examples:
#   ha-notify "Docs regenerated" --title "brAIn"
#   ha-notify "Hello" --target all
#   ha-notify "Task done" --target bi17pm

set -euo pipefail

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
HA_API="http://supervisor/core/api"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    cat << 'EOF'
ha-notify — Send notifications via Home Assistant

Usage:
  ha-notify "message" [--title "title"] [--target <name>|all]

Options:
  --title    Notification title (default: "brAIn")
  --target   Notification target: a mobile_app name suffix or "all"
             If omitted, sends a persistent notification to the HA UI

Examples:
  ha-notify "Docs regenerated"
  ha-notify "Hello" --title "Alert" --target all
  ha-notify "Task done" --target bi17pm
EOF
    exit 0
}

check_token() {
    if [ -z "$SUPERVISOR_TOKEN" ]; then
        echo -e "${RED}Error: SUPERVISOR_TOKEN not set. Are you running inside the add-on?${NC}" >&2
        exit 1
    fi
}

# POST and say what Home Assistant answered. `curl -s` alone printed Core's
# body (`[]`) and "sent" whatever the status was, so a refused service or a
# phone that is gone read as delivered. Returns non-zero on a refusal, with
# Core's status and message on stderr.
api_post() {
    local endpoint="$1"
    local data="$2"
    local body code
    body=$(mktemp)
    code=$(curl -s -o "$body" -w '%{http_code}' -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$data" \
        "${HA_API}${endpoint}" 2>/dev/null) || code="000"
    if [[ "$code" != 2* ]]; then
        echo -e "${RED}Home Assistant refused ${endpoint} (HTTP ${code}): $(head -c 300 "$body")${NC}" >&2
        rm -f "$body"
        return 1
    fi
    rm -f "$body"
    return 0
}

# The receipt: which service took it and when, and the part nothing reports.
receipt() {
    local svc="$1"
    echo -e "${GREEN}Home Assistant accepted it for ${svc} at $(date '+%Y-%m-%d %H:%M') with no error.${NC}"
    if [[ "$svc" != persistent_notification.* ]]; then
        echo "Home Assistant does not report whether the phone showed it: check the phone's notifications, or Home Assistant's log for a mobile_app error."
    fi
}

get_notify_services() {
    curl -s -X GET \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "${HA_API}/services" 2>/dev/null | \
    jq -r '.[] | select(.domain == "notify") | .services | keys[]' 2>/dev/null
}

# Main
[ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] && usage
[ $# -lt 1 ] && usage

check_token

message=""
title="brAIn"
target=""

# Parse arguments
while [ $# -gt 0 ]; do
    case "$1" in
        --title)
            shift
            title="${1:-}"
            ;;
        --target)
            shift
            target="${1:-}"
            ;;
        --help|-h)
            usage
            ;;
        *)
            if [ -z "$message" ]; then
                message="$1"
            else
                echo -e "${RED}Unexpected argument: $1${NC}" >&2
                exit 1
            fi
            ;;
    esac
    shift
done

if [ -z "$message" ]; then
    echo -e "${RED}Error: Message is required${NC}" >&2
    usage
fi

if [ -z "$target" ]; then
    # Send persistent notification to HA UI
    echo -e "${CYAN}Sending persistent notification...${NC}"
    local_data=$(jq -n \
        --arg title "$title" \
        --arg msg "$message" \
        --arg nid "brain_$(date +%s)" \
        '{"title": $title, "message": $msg, "notification_id": $nid}')
    api_post "/services/persistent_notification/create" "$local_data" || exit 1
    receipt "persistent_notification.create"
    echo "It is in Home Assistant's notifications (the bell) until dismissed."
elif [ "$target" = "all" ]; then
    # Send to all mobile_app notify services
    echo -e "${CYAN}Sending to all mobile devices...${NC}"
    services=$(get_notify_services)
    sent=0
    failed=0
    while IFS= read -r svc; do
        if [[ "$svc" == mobile_app_* ]]; then
            data=$(jq -n --arg title "$title" --arg msg "$message" \
                '{"title": $title, "message": $msg}')
            if api_post "/services/notify/${svc}" "$data"; then
                receipt "notify.${svc}"
                sent=$((sent + 1))
            else
                failed=$((failed + 1))
            fi
        fi
    done <<< "$services"
    if [ "$sent" -eq 0 ] && [ "$failed" -eq 0 ]; then
        echo -e "${YELLOW}No mobile_app notify services found${NC}"
    fi
    [ "$failed" -eq 0 ] || exit 1
else
    # Send to specific target
    svc_name="mobile_app_${target}"
    echo -e "${CYAN}Sending to ${svc_name}...${NC}"
    data=$(jq -n --arg title "$title" --arg msg "$message" \
        '{"title": $title, "message": $msg}')
    api_post "/services/notify/${svc_name}" "$data" || exit 1
    receipt "notify.${svc_name}"
fi
