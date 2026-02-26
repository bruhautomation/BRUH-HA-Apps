#!/usr/bin/with-contenv bashio

# BRUH Claude Terminal - Health check script
# Validates environment and provides diagnostic information

check_system_resources() {
    bashio::log.info "=== System Resources Check ==="

    local mem_total=$(awk '/MemTotal/ {print int($2/1024)}' /proc/meminfo)
    local mem_free=$(awk '/MemAvailable/ {print int($2/1024)}' /proc/meminfo)
    bashio::log.info "Memory: ${mem_free}MB free of ${mem_total}MB total"

    if [ "$mem_free" -lt 256 ]; then
        bashio::log.error "Low memory warning: Less than 256MB available"
    fi

    local disk_free=$(df -m /data | tail -1 | awk '{print $4}')
    bashio::log.info "Disk space in /data: ${disk_free}MB free"

    if [ "$disk_free" -lt 100 ]; then
        bashio::log.error "Low disk space warning: Less than 100MB in /data"
    fi
}

check_directory_permissions() {
    bashio::log.info "=== Directory Permissions Check ==="

    if [ -w "/data" ]; then
        bashio::log.info "/data directory: Writable"
    else
        bashio::log.error "/data directory: Not writable"
        return 1
    fi

    local test_dir="/data/.test_$$"
    if mkdir -p "$test_dir" 2>/dev/null; then
        bashio::log.info "Can create directories in /data"
        rmdir "$test_dir"
    else
        bashio::log.error "Cannot create directories in /data"
        return 1
    fi
}

check_node_installation() {
    bashio::log.info "=== Node.js Installation Check ==="

    if command -v node >/dev/null 2>&1; then
        local node_version=$(node --version)
        bashio::log.info "Node.js installed: $node_version"
    else
        bashio::log.error "Node.js not found"
        return 1
    fi

    if command -v npm >/dev/null 2>&1; then
        local npm_version=$(npm --version)
        bashio::log.info "npm installed: $npm_version"
    else
        bashio::log.error "npm not found"
        return 1
    fi
}

check_claude_cli() {
    bashio::log.info "=== Claude CLI Check ==="

    if command -v claude >/dev/null 2>&1; then
        bashio::log.info "Claude CLI found at: $(which claude)"

        if [ -x "$(which claude)" ]; then
            bashio::log.info "Claude CLI is executable"
        else
            bashio::log.error "Claude CLI is not executable"
            return 1
        fi
    else
        bashio::log.error "Claude CLI not found"
        return 1
    fi
}

check_ha_api_access() {
    bashio::log.info "=== Home Assistant API Check ==="

    if [ -z "$SUPERVISOR_TOKEN" ]; then
        bashio::log.error "SUPERVISOR_TOKEN not set"
        return 1
    fi

    bashio::log.info "SUPERVISOR_TOKEN: available"

    # Test API access
    local result
    result=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        "http://supervisor/core/api/config" 2>/dev/null || echo "000")

    if [ "$result" = "200" ]; then
        bashio::log.info "HA Core API: accessible"
    else
        bashio::log.warning "HA Core API: returned HTTP $result"
    fi

    result=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        "http://supervisor/core/info" 2>/dev/null || echo "000")

    if [ "$result" = "200" ]; then
        bashio::log.info "Supervisor API: accessible"
    else
        bashio::log.warning "Supervisor API: returned HTTP $result"
    fi
}

check_mcp_server() {
    bashio::log.info "=== MCP Server Check ==="

    if [ -f "/opt/ha-mcp-server/ha_mcp_server.py" ]; then
        bashio::log.info "HA MCP server: present"

        if python3 -c "import json, urllib.request" 2>/dev/null; then
            bashio::log.info "Python dependencies: available"
        else
            bashio::log.warning "Some Python dependencies may be missing"
        fi
    else
        bashio::log.warning "HA MCP server: not found"
    fi
}

check_network_connectivity() {
    bashio::log.info "=== Network Connectivity Check ==="

    if curl -s --head --connect-timeout 10 --max-time 15 https://api.anthropic.com > /dev/null; then
        bashio::log.info "Can reach Anthropic API"
    else
        bashio::log.warning "Cannot reach Anthropic API"
    fi
}

run_diagnostics() {
    bashio::log.info "========================================="
    bashio::log.info "BRUH Claude Terminal Health Check"
    bashio::log.info "========================================="

    local errors=0

    check_system_resources || ((errors++))
    check_directory_permissions || ((errors++))
    check_node_installation || ((errors++))
    check_claude_cli || ((errors++))
    check_ha_api_access || ((errors++))
    check_mcp_server || ((errors++))
    check_network_connectivity || ((errors++))

    bashio::log.info "========================================="

    if [ "$errors" -eq 0 ]; then
        bashio::log.info "All checks passed"
    else
        bashio::log.error "$errors check(s) failed"
    fi

    return $errors
}

if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    run_diagnostics
fi
