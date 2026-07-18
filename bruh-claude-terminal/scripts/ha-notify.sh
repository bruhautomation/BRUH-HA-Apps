#!/usr/bin/env bash

# ha-notify — Send notifications via Home Assistant
# Usage:
#   ha-notify "message" [--title "title"] [--target <name>|all]
# Examples:
#   ha-notify "Docs regenerated" --title "BRUH Claude"
#   ha-notify "Hello" --target all
#   ha-notify "Task done" --target bi17pm

set -euo pipefail

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
HA_API="http://supervisor/core/api"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    cat << 'EOF'
ha-notify — Send notifications via Home Assistant

Usage:
  ha-notify "message" [--title "title"] [--target <name>|all]

Options:
  --title    Notification title (default: "BRUH Terminal")
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

api_post() {
    local endpoint="$1"
    local data="$2"
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$data" \
        "${HA_API}${endpoint}" 2>/dev/null
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
title="BRUH Terminal"
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
        --arg nid "bruh_claude_$(date +%s)" \
        '{"title": $title, "message": $msg, "notification_id": $nid}')
    api_post "/services/persistent_notification/create" "$local_data"
    echo -e "${GREEN}Persistent notification sent${NC}"
elif [ "$target" = "all" ]; then
    # Send to all mobile_app notify services
    echo -e "${CYAN}Sending to all mobile devices...${NC}"
    services=$(get_notify_services)
    sent=0
    while IFS= read -r svc; do
        if [[ "$svc" == mobile_app_* ]]; then
            data=$(jq -n --arg title "$title" --arg msg "$message" \
                '{"title": $title, "message": $msg}')
            api_post "/services/notify/${svc}" "$data"
            echo -e "  ${GREEN}Sent to ${svc}${NC}"
            sent=$((sent + 1))
        fi
    done <<< "$services"
    if [ "$sent" -eq 0 ]; then
        echo -e "${YELLOW}No mobile_app notify services found${NC}"
    else
        echo -e "${GREEN}Notification sent to ${sent} device(s)${NC}"
    fi
else
    # Send to specific target
    svc_name="mobile_app_${target}"
    echo -e "${CYAN}Sending to ${svc_name}...${NC}"
    data=$(jq -n --arg title "$title" --arg msg "$message" \
        '{"title": $title, "message": $msg}')
    api_post "/services/notify/${svc_name}" "$data"
    echo -e "${GREEN}Notification sent to ${svc_name}${NC}"
fi
