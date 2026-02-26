#!/usr/bin/with-contenv bashio

# ha-reload - Reload Home Assistant configurations
# Usage: ha-reload [target]
# Targets: automations, scripts, scenes, groups, input_booleans, input_numbers,
#          input_selects, input_texts, input_datetimes, timers, counters, core, all

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

reload_target() {
    local target="$1"
    local domain=""
    local service=""

    case "$target" in
        automations|automation)
            domain="automation"; service="reload"
            ;;
        scripts|script)
            domain="script"; service="reload"
            ;;
        scenes|scene)
            domain="scene"; service="reload"
            ;;
        groups|group)
            domain="group"; service="reload"
            ;;
        input_booleans|input_boolean)
            domain="input_boolean"; service="reload"
            ;;
        input_numbers|input_number)
            domain="input_number"; service="reload"
            ;;
        input_selects|input_select)
            domain="input_select"; service="reload"
            ;;
        input_texts|input_text)
            domain="input_text"; service="reload"
            ;;
        input_datetimes|input_datetime)
            domain="input_datetime"; service="reload"
            ;;
        timers|timer)
            domain="timer"; service="reload"
            ;;
        counters|counter)
            domain="counter"; service="reload"
            ;;
        core)
            domain="homeassistant"; service="reload_core_config"
            ;;
        all)
            domain="homeassistant"; service="reload_all"
            ;;
        check|validate)
            echo -e "${BLUE}Checking configuration...${NC}"
            local result
            result=$(curl -s -X POST \
                -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
                -H "Content-Type: application/json" \
                "http://supervisor/core/api/config/core/check")
            local errors
            errors=$(echo "$result" | jq -r '.errors // empty' 2>/dev/null)
            if [ -z "$errors" ] || [ "$errors" = "null" ]; then
                echo -e "${GREEN}Configuration valid${NC}"
            else
                echo -e "${RED}Configuration errors:${NC}"
                echo "$errors"
            fi
            return
            ;;
        *)
            echo -e "${RED}Unknown target:${NC} $target"
            echo ""
            show_help
            exit 1
            ;;
    esac

    echo -e "${BLUE}Reloading ${target}...${NC}"

    local http_code
    local body
    body=$(curl -s -w "\n%{http_code}" -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "http://supervisor/core/api/services/${domain}/${service}" \
        -d '{}')

    http_code=$(echo "$body" | tail -1)
    body=$(echo "$body" | sed '$d')

    if [ "$http_code" -ge 200 ] 2>/dev/null && [ "$http_code" -lt 300 ] 2>/dev/null; then
        echo -e "${GREEN}Successfully reloaded ${target}${NC}"
    else
        echo -e "${RED}Failed to reload ${target} (HTTP ${http_code})${NC}"
        echo "$body"
        exit 1
    fi
}

show_help() {
    echo -e "${BLUE}ha-reload${NC} - Reload Home Assistant configurations"
    echo ""
    echo "Usage: ha-reload <target>"
    echo ""
    echo "Targets:"
    echo "  automations    Reload automation configurations"
    echo "  scripts        Reload script configurations"
    echo "  scenes         Reload scene configurations"
    echo "  groups         Reload group configurations"
    echo "  input_booleans Reload input boolean helpers"
    echo "  input_numbers  Reload input number helpers"
    echo "  input_selects  Reload input select helpers"
    echo "  input_texts    Reload input text helpers"
    echo "  input_datetimes Reload input datetime helpers"
    echo "  timers         Reload timer helpers"
    echo "  counters       Reload counter helpers"
    echo "  core           Reload core configuration"
    echo "  all            Reload all configurations"
    echo "  check          Validate configuration without reloading"
    echo ""
    echo "Examples:"
    echo "  ha-reload automations"
    echo "  ha-reload all"
    echo "  ha-reload check"
}

# Main
target="${1:-}"

if [ -z "$target" ] || [ "$target" = "help" ] || [ "$target" = "--help" ] || [ "$target" = "-h" ]; then
    show_help
    exit 0
fi

reload_target "$target"
