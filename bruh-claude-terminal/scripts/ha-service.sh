#!/usr/bin/env bash

# ha-service — Call Home Assistant services
# Usage:
#   ha-service call <domain>.<service> [--data '{"key":"val"}']
#   ha-service list [domain]
# Examples:
#   ha-service call light.turn_on --data '{"entity_id":"light.kitchen"}'
#   ha-service call script.bedtime
#   ha-service call notify.mobile_app_phone --data '{"message":"Hello"}'

set -euo pipefail

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
HA_API="http://supervisor/core/api"

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

usage() {
    cat << 'EOF'
ha-service — Call Home Assistant services

Usage:
  ha-service call <domain>.<service> [--data '{"key":"val"}']
  ha-service list [domain]

Examples:
  ha-service call light.turn_on --data '{"entity_id":"light.kitchen"}'
  ha-service call script.bedtime
  ha-service call notify.mobile_app_phone --data '{"message":"Hello"}'
  ha-service list light
  ha-service list
EOF
    exit 0
}

check_token() {
    if [ -z "$SUPERVISOR_TOKEN" ]; then
        echo -e "${RED}Error: SUPERVISOR_TOKEN not set. Are you running inside the add-on?${NC}" >&2
        exit 1
    fi
}

cmd_call() {
    local service_path="$1"
    shift
    local data="{}"

    # Parse --data argument
    while [ $# -gt 0 ]; do
        case "$1" in
            --data)
                shift
                data="${1:-{}}"
                ;;
            *)
                echo -e "${RED}Unknown argument: $1${NC}" >&2
                exit 1
                ;;
        esac
        shift
    done

    # Split domain.service
    local domain service
    domain="${service_path%%.*}"
    service="${service_path#*.}"

    if [ -z "$domain" ] || [ -z "$service" ] || [ "$domain" = "$service" ]; then
        echo -e "${RED}Error: Service must be in format <domain>.<service> (e.g., light.turn_on)${NC}" >&2
        exit 1
    fi

    # Validate JSON
    if ! echo "$data" | jq . >/dev/null 2>&1; then
        echo -e "${RED}Error: Invalid JSON data: ${data}${NC}" >&2
        exit 1
    fi

    echo -e "${CYAN}Calling ${domain}.${service}...${NC}"
    local response http_code
    http_code=$(curl -s -o /tmp/ha-service-response -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$data" \
        "${HA_API}/services/${domain}/${service}" 2>/dev/null)
    response=$(cat /tmp/ha-service-response 2>/dev/null)
    rm -f /tmp/ha-service-response

    if [ "$http_code" = "200" ] || [ "$http_code" = "201" ]; then
        echo -e "${GREEN}Service ${domain}.${service} called successfully${NC}"
        if [ -n "$response" ] && [ "$response" != "[]" ]; then
            echo "$response" | jq '.' 2>/dev/null || true
        fi
    else
        echo -e "${RED}Failed (HTTP ${http_code}): $(echo "$response" | jq -r '.message // .' 2>/dev/null)${NC}" >&2
        exit 1
    fi
}

cmd_list() {
    local domain="${1:-}"
    local response
    response=$(curl -s -X GET \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "${HA_API}/services" 2>/dev/null)

    if [ -n "$domain" ]; then
        echo -e "${CYAN}Services in domain '${domain}':${NC}"
        echo "$response" | jq -r --arg d "$domain" '
            .[] | select(.domain == $d) |
            .services | to_entries[] |
            "  \(.key): \(.value.description // "No description")"
        ' 2>/dev/null || echo -e "${RED}Failed to list services${NC}" >&2
    else
        echo -e "${CYAN}Available service domains:${NC}"
        echo "$response" | jq -r '
            .[] |
            "  \(.domain) (\(.services | length) services)"
        ' 2>/dev/null | sort || echo -e "${RED}Failed to list services${NC}" >&2
    fi
}

# Main
[ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] && usage
[ $# -lt 1 ] && usage

check_token

action="${1}"
shift

case "$action" in
    call)
        [ $# -lt 1 ] && { echo -e "${RED}Error: 'call' requires <domain>.<service>${NC}" >&2; exit 1; }
        cmd_call "$@"
        ;;
    list)
        cmd_list "${1:-}"
        ;;
    --help|-h)
        usage
        ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage
        ;;
esac
