#!/usr/bin/env bash

# ha-addon — Manage Home Assistant add-ons via the Supervisor API
# Usage:
#   ha-addon list                    — List all installed add-ons
#   ha-addon info <slug>             — Get add-on details
#   ha-addon restart <slug>          — Restart an add-on
#   ha-addon stop <slug>             — Stop an add-on
#   ha-addon start <slug>            — Start an add-on
#   ha-addon logs <slug>             — View add-on logs
#   ha-addon options <slug>          — View add-on config options

set -euo pipefail

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
SUPERVISOR_API="http://supervisor"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    cat << 'EOF'
ha-addon — Manage Home Assistant add-ons

Usage:
  ha-addon list                    List all installed add-ons
  ha-addon info <slug>             Get add-on details
  ha-addon restart <slug>          Restart an add-on
  ha-addon stop <slug>             Stop an add-on
  ha-addon start <slug>            Start an add-on
  ha-addon logs <slug>             View add-on logs
  ha-addon options <slug>          View add-on config options

Examples:
  ha-addon list
  ha-addon info core_mosquitto
  ha-addon restart core_mosquitto
  ha-addon logs core_mosquitto
EOF
    exit 0
}

check_token() {
    if [ -z "$SUPERVISOR_TOKEN" ]; then
        echo -e "${RED}Error: SUPERVISOR_TOKEN not set. Are you running inside the add-on?${NC}" >&2
        exit 1
    fi
}

api_get() {
    local endpoint="$1"
    curl -s -X GET \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "${SUPERVISOR_API}${endpoint}" 2>/dev/null
}

api_post() {
    local endpoint="$1"
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "${SUPERVISOR_API}${endpoint}" 2>/dev/null
}

cmd_list() {
    echo -e "${CYAN}Installed add-ons:${NC}"
    local response
    response=$(api_get "/addons")
    if [ $? -ne 0 ] || [ -z "$response" ]; then
        echo -e "${RED}Failed to fetch add-on list${NC}" >&2
        exit 1
    fi

    echo "$response" | jq -r '
        .data.addons[]? |
        select(.installed == true or .state == "started" or .state == "stopped") |
        "\(.slug)\t\(.name)\tv\(.version)\t[\(.state)]"
    ' 2>/dev/null | column -t -s $'\t' || echo -e "${RED}Failed to parse add-on list${NC}" >&2
}

cmd_info() {
    local slug="$1"
    echo -e "${CYAN}Add-on info: ${slug}${NC}"
    local response
    response=$(api_get "/addons/${slug}/info")
    echo "$response" | jq -r '.data // .' 2>/dev/null || echo "$response"
}

cmd_restart() {
    local slug="$1"
    echo -e "${YELLOW}Are you sure you want to restart '${slug}'? [y/N]${NC}"
    read -r confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        return
    fi
    echo -e "${CYAN}Restarting ${slug}...${NC}"
    local response
    response=$(api_post "/addons/${slug}/restart")
    local result
    result=$(echo "$response" | jq -r '.result // "unknown"' 2>/dev/null)
    if [ "$result" = "ok" ]; then
        echo -e "${GREEN}Add-on '${slug}' restarted successfully${NC}"
    else
        echo -e "${RED}Failed to restart '${slug}': $(echo "$response" | jq -r '.message // "unknown error"' 2>/dev/null)${NC}" >&2
        exit 1
    fi
}

cmd_stop() {
    local slug="$1"
    echo -e "${YELLOW}Are you sure you want to stop '${slug}'? [y/N]${NC}"
    read -r confirm
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        echo "Cancelled."
        return
    fi
    echo -e "${CYAN}Stopping ${slug}...${NC}"
    local response
    response=$(api_post "/addons/${slug}/stop")
    local result
    result=$(echo "$response" | jq -r '.result // "unknown"' 2>/dev/null)
    if [ "$result" = "ok" ]; then
        echo -e "${GREEN}Add-on '${slug}' stopped${NC}"
    else
        echo -e "${RED}Failed to stop '${slug}': $(echo "$response" | jq -r '.message // "unknown error"' 2>/dev/null)${NC}" >&2
        exit 1
    fi
}

cmd_start() {
    local slug="$1"
    echo -e "${CYAN}Starting ${slug}...${NC}"
    local response
    response=$(api_post "/addons/${slug}/start")
    local result
    result=$(echo "$response" | jq -r '.result // "unknown"' 2>/dev/null)
    if [ "$result" = "ok" ]; then
        echo -e "${GREEN}Add-on '${slug}' started${NC}"
    else
        echo -e "${RED}Failed to start '${slug}': $(echo "$response" | jq -r '.message // "unknown error"' 2>/dev/null)${NC}" >&2
        exit 1
    fi
}

cmd_logs() {
    local slug="$1"
    echo -e "${CYAN}Logs for ${slug}:${NC}"
    curl -s -X GET \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        "${SUPERVISOR_API}/addons/${slug}/logs" 2>/dev/null || \
        echo -e "${RED}Failed to fetch logs for '${slug}'${NC}" >&2
}

cmd_options() {
    local slug="$1"
    echo -e "${CYAN}Options for ${slug}:${NC}"
    local response
    response=$(api_get "/addons/${slug}/info")
    echo "$response" | jq -r '.data.options // {}' 2>/dev/null || echo "$response"
}

# Main
[ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] && usage
[ $# -lt 1 ] && usage

check_token

action="${1}"
shift

case "$action" in
    list)
        cmd_list
        ;;
    info|restart|stop|start|logs|options)
        if [ $# -lt 1 ]; then
            echo -e "${RED}Error: '${action}' requires a <slug> argument${NC}" >&2
            echo "Run 'ha-addon list' to see available slugs." >&2
            exit 1
        fi
        "cmd_${action}" "$1"
        ;;
    --help|-h)
        usage
        ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage
        ;;
esac
