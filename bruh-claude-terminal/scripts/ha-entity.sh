#!/usr/bin/env bash

# ha-entity — Get/set Home Assistant entity states
# Usage:
#   ha-entity get <entity_id>           — Get current state
#   ha-entity set <entity_id> <state>   — Set state
#   ha-entity list [domain]             — List entities, optionally filtered
#   ha-entity search <pattern>          — Search entities by name/id

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
ha-entity — Get/set Home Assistant entity states

Usage:
  ha-entity get <entity_id>           Get current state and attributes
  ha-entity set <entity_id> <state>   Set entity state
  ha-entity list [domain]             List entities, optionally filtered by domain
  ha-entity search <pattern>          Search entities by name or ID

Examples:
  ha-entity get light.kitchen
  ha-entity set input_boolean.guest_mode on
  ha-entity list light
  ha-entity search kitchen
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
        "${HA_API}${endpoint}" 2>/dev/null
}

api_post() {
    local endpoint="$1"
    local data="${2:-{}}"
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$data" \
        "${HA_API}${endpoint}" 2>/dev/null
}

cmd_get() {
    local entity_id="$1"
    local response
    response=$(api_get "/states/${entity_id}")

    # Check for error
    if echo "$response" | jq -e '.message' >/dev/null 2>&1; then
        echo -e "${RED}Error: $(echo "$response" | jq -r '.message')${NC}" >&2
        exit 1
    fi

    echo -e "${CYAN}Entity: ${entity_id}${NC}"
    echo "$response" | jq -r '
        "State: \(.state)",
        "Last changed: \(.last_changed)",
        "Last updated: \(.last_updated)",
        "",
        "Attributes:",
        (.attributes | to_entries[] | "  \(.key): \(.value)")
    ' 2>/dev/null || echo "$response"
}

cmd_set() {
    local entity_id="$1"
    local state="$2"
    local data
    data=$(jq -n --arg state "$state" '{"state": $state}')

    echo -e "${CYAN}Setting ${entity_id} to '${state}'...${NC}"
    local response
    response=$(api_post "/states/${entity_id}" "$data")

    if echo "$response" | jq -e '.state' >/dev/null 2>&1; then
        local new_state
        new_state=$(echo "$response" | jq -r '.state')
        echo -e "${GREEN}State set: ${entity_id} = ${new_state}${NC}"
    else
        echo -e "${RED}Failed to set state: $(echo "$response" | jq -r '.message // "unknown error"' 2>/dev/null)${NC}" >&2
        exit 1
    fi
}

cmd_list() {
    local domain="${1:-}"
    local response
    response=$(api_get "/states")

    if [ -n "$domain" ]; then
        echo -e "${CYAN}Entities in domain '${domain}':${NC}"
        echo "$response" | jq -r --arg d "${domain}." '
            [.[] | select(.entity_id | startswith($d))] |
            sort_by(.entity_id) |
            .[] |
            "\(.entity_id)\t\(.state)\t\(.attributes.friendly_name // "")"
        ' 2>/dev/null | column -t -s $'\t'
    else
        echo -e "${CYAN}All entities by domain:${NC}"
        echo "$response" | jq -r '
            [.[].entity_id] |
            map(split(".")[0]) |
            group_by(.) |
            map({domain: .[0], count: length}) |
            sort_by(-.count) |
            .[] |
            "  \(.domain): \(.count) entities"
        ' 2>/dev/null
    fi
}

cmd_search() {
    local pattern="$1"
    echo -e "${CYAN}Searching for '${pattern}':${NC}"
    local response
    response=$(api_get "/states")
    echo "$response" | jq -r --arg p "$pattern" '
        [.[] | select(
            (.entity_id | ascii_downcase | contains($p | ascii_downcase)) or
            ((.attributes.friendly_name // "") | ascii_downcase | contains($p | ascii_downcase))
        )] |
        sort_by(.entity_id) |
        .[] |
        "\(.entity_id)\t\(.state)\t\(.attributes.friendly_name // "")"
    ' 2>/dev/null | column -t -s $'\t'
}

# Main
[ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] && usage
[ $# -lt 1 ] && usage

check_token

action="${1}"
shift

case "$action" in
    get)
        [ $# -lt 1 ] && { echo -e "${RED}Error: 'get' requires an <entity_id>${NC}" >&2; exit 1; }
        cmd_get "$1"
        ;;
    set)
        [ $# -lt 2 ] && { echo -e "${RED}Error: 'set' requires <entity_id> <state>${NC}" >&2; exit 1; }
        cmd_set "$1" "$2"
        ;;
    list)
        cmd_list "${1:-}"
        ;;
    search)
        [ $# -lt 1 ] && { echo -e "${RED}Error: 'search' requires a <pattern>${NC}" >&2; exit 1; }
        cmd_search "$1"
        ;;
    --help|-h)
        usage
        ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage
        ;;
esac
