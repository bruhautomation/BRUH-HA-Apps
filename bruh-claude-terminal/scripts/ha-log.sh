#!/usr/bin/with-contenv bashio

# ha-log - View Home Assistant logs
# Usage: ha-log [target] [options]
# Targets: core, supervisor, host, addons, errors, all

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

api_get() {
    local endpoint="$1"
    curl -s -X GET \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "http://supervisor${endpoint}" 2>/dev/null
}

show_core_logs() {
    local lines="${1:-100}"
    echo -e "${BLUE}=== Home Assistant Core Logs (last ${lines} lines) ===${NC}"
    echo ""
    local log_content
    log_content=$(api_get "/core/api/error_log")
    if [ -n "$log_content" ]; then
        echo "$log_content" | tail -n "$lines"
    else
        echo -e "${YELLOW}No log content available${NC}"
    fi
}

show_supervisor_logs() {
    local lines="${1:-100}"
    echo -e "${BLUE}=== Supervisor Logs (last ${lines} lines) ===${NC}"
    echo ""
    local log_content
    log_content=$(api_get "/supervisor/logs" 2>/dev/null)
    if [ -n "$log_content" ]; then
        echo "$log_content" | tail -n "$lines"
    else
        echo -e "${YELLOW}No supervisor log content available${NC}"
    fi
}

show_host_logs() {
    local lines="${1:-100}"
    echo -e "${BLUE}=== Host Logs (last ${lines} lines) ===${NC}"
    echo ""
    local log_content
    log_content=$(api_get "/host/logs" 2>/dev/null)
    if [ -n "$log_content" ]; then
        echo "$log_content" | tail -n "$lines"
    else
        echo -e "${YELLOW}No host log content available${NC}"
    fi
}

show_addon_logs() {
    local addon_slug="${1:-self}"
    local lines="${2:-100}"
    echo -e "${BLUE}=== Add-on Logs: ${addon_slug} (last ${lines} lines) ===${NC}"
    echo ""
    local log_content
    log_content=$(api_get "/addons/${addon_slug}/logs" 2>/dev/null)
    if [ -n "$log_content" ]; then
        echo "$log_content" | tail -n "$lines"
    else
        echo -e "${YELLOW}No add-on log content available${NC}"
    fi
}

show_errors() {
    local hours="${1:-1}"
    echo -e "${RED}=== Recent Errors (last ${hours}h) ===${NC}"
    echo ""
    local log_content
    log_content=$(api_get "/core/api/error_log")
    if [ -n "$log_content" ]; then
        echo "$log_content" | grep -i -E "(error|exception|traceback|warning|critical|fatal)" | tail -50
    else
        echo -e "${YELLOW}No error content available${NC}"
    fi
}

show_all() {
    local lines="${1:-30}"
    show_core_logs "$lines"
    echo ""
    show_supervisor_logs "$lines"
    echo ""
    show_errors 1
}

follow_logs() {
    local target="${1:-core}"
    echo -e "${CYAN}Following ${target} logs (Ctrl+C to stop)...${NC}"
    echo ""

    local last_line_count=0
    while true; do
        local log_content
        case "$target" in
            core)
                log_content=$(api_get "/core/api/error_log")
                ;;
            supervisor)
                log_content=$(api_get "/supervisor/logs" 2>/dev/null)
                ;;
            *)
                log_content=$(api_get "/addons/${target}/logs" 2>/dev/null)
                ;;
        esac

        if [ -n "$log_content" ]; then
            local current_line_count
            current_line_count=$(echo "$log_content" | wc -l)
            if [ "$current_line_count" -gt "$last_line_count" ]; then
                if [ "$last_line_count" -eq 0 ]; then
                    # First fetch: show last 20 lines
                    echo "$log_content" | tail -20
                else
                    # Show only new lines since last fetch
                    local new_lines=$((current_line_count - last_line_count))
                    echo "$log_content" | tail -"$new_lines"
                fi
                last_line_count=$current_line_count
            fi
        fi
        sleep 5
    done
}

show_help() {
    echo -e "${BLUE}ha-log${NC} - View Home Assistant logs"
    echo ""
    echo "Usage: ha-log <target> [options]"
    echo ""
    echo "Targets:"
    echo "  core           Home Assistant core logs"
    echo "  supervisor     Supervisor logs"
    echo "  host           Host system logs"
    echo "  addon <slug>   Specific add-on logs (default: self)"
    echo "  errors         Filter for errors and warnings"
    echo "  all            Show core + supervisor + errors"
    echo ""
    echo "Options:"
    echo "  -f, --follow   Follow logs in real-time"
    echo "  -n <lines>     Number of lines to show (default: 100)"
    echo ""
    echo "Examples:"
    echo "  ha-log core"
    echo "  ha-log core -f"
    echo "  ha-log core -n 50"
    echo "  ha-log errors"
    echo "  ha-log addon mosquitto"
    echo "  ha-log all"
}

# Parse arguments
target="${1:-}"
shift || true

follow=false
lines=100
addon_slug=""

while [ $# -gt 0 ]; do
    case "$1" in
        -f|--follow)
            follow=true
            shift
            ;;
        -n)
            lines="${2:-100}"
            shift 2
            ;;
        *)
            addon_slug="$1"
            shift
            ;;
    esac
done

if [ -z "$target" ] || [ "$target" = "help" ] || [ "$target" = "--help" ] || [ "$target" = "-h" ]; then
    show_help
    exit 0
fi

if [ "$follow" = true ]; then
    follow_logs "$target"
else
    case "$target" in
        core)
            show_core_logs "$lines"
            ;;
        supervisor)
            show_supervisor_logs "$lines"
            ;;
        host)
            show_host_logs "$lines"
            ;;
        addon|addons)
            show_addon_logs "${addon_slug:-self}" "$lines"
            ;;
        errors|error)
            show_errors 1
            ;;
        all)
            show_all "$lines"
            ;;
        *)
            echo -e "${RED}Unknown target: ${target}${NC}"
            echo ""
            show_help
            exit 1
            ;;
    esac
fi
