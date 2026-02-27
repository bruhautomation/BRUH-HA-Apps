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

    # Check for native binary (primary)
    if [ -x /root/.local/bin/claude ]; then
        bashio::log.info "Claude native binary: /root/.local/bin/claude"
    else
        bashio::log.error "Claude native binary not found at /root/.local/bin/claude"
        return 1
    fi

    # Check for claude-run wrapper (used by terminal and listeners)
    if [ -x /usr/local/bin/claude-run ]; then
        bashio::log.info "Claude wrapper: /usr/local/bin/claude-run (OK)"
    else
        bashio::log.warning "Claude wrapper not found at /usr/local/bin/claude-run"
        bashio::log.warning "  (will be created by setup_claude_user)"
    fi

    # Warn about stale /usr/local/bin/claude that causes "multiple installations" diagnostic
    if [ -e /usr/local/bin/claude ]; then
        bashio::log.warning "Stale /usr/local/bin/claude detected (causes 'npm-global' warning)"
        bashio::log.info "  This will be removed during setup"
    fi

    # Check if $HOME/.local/bin/claude symlink exists for the claude user
    local claude_home="/data/home"
    if [ -L "$claude_home/.local/bin/claude" ]; then
        local link_target
        link_target=$(readlink -f "$claude_home/.local/bin/claude" 2>/dev/null || echo "broken")
        bashio::log.info "Claude user symlink: $claude_home/.local/bin/claude -> $link_target"
    else
        bashio::log.info "Claude user symlink not yet created (setup pending)"
    fi
}

check_ha_api_access() {
    bashio::log.info "=== Home Assistant API Check ==="

    if [ -z "$SUPERVISOR_TOKEN" ]; then
        bashio::log.error "SUPERVISOR_TOKEN not set"
        return 1
    fi

    local token_len=${#SUPERVISOR_TOKEN}
    bashio::log.info "SUPERVISOR_TOKEN: available (${token_len} chars)"

    # Test API access via Supervisor proxy
    local result
    result=$(curl -s -o /dev/null -w "%{http_code}" \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        "http://supervisor/core/api/config" 2>/dev/null || echo "000")

    if [ "$result" = "200" ]; then
        bashio::log.info "HA Core API (via Supervisor): accessible"
    else
        bashio::log.warning "HA Core API (via Supervisor): returned HTTP $result"
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
        bashio::log.info "HA MCP server script: present"

        if python3 -c "import json, urllib.request" 2>/dev/null; then
            bashio::log.info "Python dependencies: available"
        else
            bashio::log.warning "Some Python dependencies may be missing"
        fi
    else
        bashio::log.warning "HA MCP server: not found"
    fi

    # Check .mcp.json existence and permissions
    local mcp_config="/config/.mcp.json"
    if [ -f "$mcp_config" ]; then
        local mcp_owner mcp_perms
        mcp_owner=$(stat -c '%U:%G' "$mcp_config" 2>/dev/null || echo "unknown")
        mcp_perms=$(stat -c '%a' "$mcp_config" 2>/dev/null || echo "unknown")
        bashio::log.info ".mcp.json: exists (owner=$mcp_owner, perms=$mcp_perms)"

        # Verify the claude user can read it
        if su-exec claude test -r "$mcp_config" 2>/dev/null; then
            bashio::log.info ".mcp.json: readable by claude user"
        else
            bashio::log.error ".mcp.json: NOT readable by claude user (EACCES)"
            bashio::log.error "  Fix: chown claude:claude $mcp_config"
        fi

        # Validate JSON structure
        if jq -e '.mcpServers["home-assistant"]' "$mcp_config" >/dev/null 2>&1; then
            bashio::log.info ".mcp.json: home-assistant server configured"
        else
            bashio::log.warning ".mcp.json: home-assistant server NOT configured"
        fi
    else
        bashio::log.info ".mcp.json: not yet created (setup pending)"
    fi

    # Check settings.local.json
    local settings="/config/.claude/settings.local.json"
    if [ -f "$settings" ]; then
        local settings_owner
        settings_owner=$(stat -c '%U:%G' "$settings" 2>/dev/null || echo "unknown")
        bashio::log.info "settings.local.json: exists (owner=$settings_owner)"
        if su-exec claude test -r "$settings" 2>/dev/null; then
            bashio::log.info "settings.local.json: readable by claude user"
        else
            bashio::log.error "settings.local.json: NOT readable by claude user"
        fi
    else
        bashio::log.info "settings.local.json: not yet created (setup pending)"
    fi
}

check_auth_status() {
    bashio::log.info "=== Claude Auth Status ==="

    local claude_config="/data/.config/claude"
    local claude_dot="/data/home/.claude"

    # Count credential files
    local config_files
    config_files=$(find "$claude_config" -type f 2>/dev/null | wc -l)
    bashio::log.info "Credential files in $claude_config: $config_files"

    local dot_files
    dot_files=$(find "$claude_dot" -type f 2>/dev/null | wc -l)
    bashio::log.info "Credential files in $claude_dot: $dot_files"

    # Check for OAuth tokens (without revealing content)
    if find "$claude_config" -name "*.json" -exec grep -ql "access_token\|refresh_token" {} \; 2>/dev/null | head -1 | grep -q .; then
        bashio::log.info "OAuth tokens: FOUND in config dir"
    else
        bashio::log.warning "OAuth tokens: NOT found - user needs to authenticate"
    fi

    # Check symlinks
    local symlinks=(
        "/root/.config/claude"
        "/root/.config/anthropic"
        "/data/home/.config/claude"
        "/data/home/.config/anthropic"
        "/root/.claude"
    )

    for link in "${symlinks[@]}"; do
        if [ -L "$link" ]; then
            local target
            target=$(readlink "$link" 2>/dev/null || echo "broken")
            bashio::log.info "Symlink OK: $link -> $target"
        elif [ -d "$link" ]; then
            bashio::log.warning "Real dir (should be symlink): $link"
        fi
    done
}

check_plugin_config() {
    bashio::log.info "=== Claude Code Plugin Check ==="

    local search_dirs=(
        "/data/.config/claude"
        "/data/home/.claude"
        "/config/.claude"
    )

    local found_issues=false
    for dir in "${search_dirs[@]}"; do
        [ -d "$dir" ] || continue
        while IFS= read -r -d '' config_file; do
            if grep -q "claude-homeassistant-plugins\|homeassistant-config" "$config_file" 2>/dev/null; then
                bashio::log.warning "Broken plugin reference in: $config_file"
                bashio::log.warning "  Contains 'claude-homeassistant-plugins' which causes /api/mcp auth errors"
                found_issues=true
            fi
        done < <(find "$dir" -maxdepth 2 -name "*.json" -type f -print0 2>/dev/null)
    done

    if [ "$found_issues" = false ]; then
        bashio::log.info "No broken plugin configurations found"
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
    check_auth_status || ((errors++))
    check_plugin_config || ((errors++))
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
