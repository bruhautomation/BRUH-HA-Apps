#!/usr/bin/with-contenv bashio

# Home Assistant API Examples for BRUH Claude Terminal
# Demonstrates how to interact with Home Assistant APIs

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║          Home Assistant API Examples                        ║"
echo "║          BRUH Claude Terminal                               ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"
if [ -z "$SUPERVISOR_TOKEN" ]; then
    echo -e "${RED}Error: Supervisor token not found${NC}"
    exit 1
fi

echo -e "${GREEN}Supervisor token available${NC}"
echo ""

api_call() {
    local endpoint=$1
    local method=${2:-GET}
    local data=${3:-}

    if [ "$method" = "GET" ]; then
        curl -s -X GET \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            "http://supervisor/${endpoint}"
    else
        curl -s -X "$method" \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "$data" \
            "http://supervisor/${endpoint}"
    fi
}

echo "1. Getting current add-on information:"
api_call "addons/self/info" | jq '.data | {name, version, state}'
echo ""

echo "2. Getting Home Assistant information:"
api_call "core/info" | jq '.data | {version, machine, operating_system}'
echo ""

echo "3. Listing installed add-ons:"
api_call "addons" | jq '.data.addons[] | {name, slug, version, state}'
echo ""

echo "4. Getting all entity states (first 10):"
api_call "core/api/states" | jq '.[0:10] | .[] | {entity_id, state}'
echo ""

echo "5. Getting system health:"
api_call "core/api/system_health/info" | jq '.'
echo ""

echo "════════════════════════════════════════════════════════════════"
echo -e "${BLUE}BRUH Claude Terminal enhanced tools:${NC}"
echo ""
echo "  ha-reload automations  - Reload automations after YAML edit"
echo "  ha-reload all          - Reload all configurations"
echo "  ha-reload check        - Validate configuration"
echo "  ha-log core            - View HA core logs"
echo "  ha-log errors          - View error logs"
echo "  ha-log core -f         - Follow logs in real-time"
echo "  ha-backup              - Create a config backup"
echo "  ha-backup history      - View backup history"
echo "  ha-context-gen         - Regenerate Claude context"
echo ""
echo "  The HA MCP server gives Claude Code direct API access."
echo "  Claude can get entity states, call services, and more."
echo ""
