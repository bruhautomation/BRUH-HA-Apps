#!/usr/bin/with-contenv bashio

# BRUH Claude Terminal - Enhanced startup script
# Features: HA MCP server, auto-backup, context generation, config reload, log access

set -e
set -o pipefail

# ============================================================================
# Environment Initialization
# ============================================================================

init_environment() {
    local data_home="/data/home"
    local config_dir="/data/.config"
    local cache_dir="/data/.cache"
    local state_dir="/data/.local/state"
    local claude_config_dir="/data/.config/claude"

    bashio::log.info "Initializing BRUH Claude Terminal environment..."

    if ! mkdir -p \
        "$data_home" \
        "$config_dir/claude" \
        "$cache_dir" \
        "$state_dir" \
        "/data/.local/share" \
        "/data/backups" \
        "/data/tasks"; then
        bashio::log.error "Failed to create directories in /data"
        exit 1
    fi

    chmod 755 "$data_home" "$config_dir" "$cache_dir" "$state_dir" "$claude_config_dir"

    # Ensure Claude native binary is available at $HOME/.local/bin/claude
    local native_bin_dir="$data_home/.local/bin"
    if [ ! -d "$native_bin_dir" ]; then
        mkdir -p "$native_bin_dir"
    fi
    if [ -f /root/.local/bin/claude ] && [ ! -f "$native_bin_dir/claude" ]; then
        ln -sf /root/.local/bin/claude "$native_bin_dir/claude"
        bashio::log.info "  - Claude native binary linked: $native_bin_dir/claude"
    fi

    # Set XDG and application environment variables
    export HOME="$data_home"
    export XDG_CONFIG_HOME="$config_dir"
    export XDG_CACHE_HOME="$cache_dir"
    export XDG_STATE_HOME="$state_dir"
    export XDG_DATA_HOME="/data/.local/share"

    # Claude-specific environment variables
    export ANTHROPIC_CONFIG_DIR="$claude_config_dir"
    export ANTHROPIC_HOME="/data"

    # HA API environment - make SUPERVISOR_TOKEN easily accessible
    export HA_TOKEN="${SUPERVISOR_TOKEN}"
    export HA_BASE_URL="http://supervisor/core/api"
    export SUPERVISOR_API_URL="http://supervisor"

    # Migrate any existing authentication files from legacy locations
    migrate_legacy_auth_files "$claude_config_dir"

    # Ensure auth symlinks always point to persistent storage.
    # On add-on updates the container is rebuilt fresh, so any symlinks from the
    # previous container are gone. Re-create them every startup so Claude Code
    # can find auth credentials regardless of which path it checks.
    mkdir -p /root/.config "$data_home/.config"
    ln -sfn "$claude_config_dir" /root/.config/claude
    ln -sfn "$claude_config_dir" /root/.config/anthropic
    ln -sfn "$claude_config_dir" "$data_home/.config/claude"
    ln -sfn "$claude_config_dir" "$data_home/.config/anthropic"

    # Claude Code also checks $HOME/.claude/ for settings and credentials
    mkdir -p "$data_home/.claude"

    bashio::log.info "  - Auth symlinks refreshed for persistent OAuth"

    # Install tmux configuration
    if [ -f "/opt/scripts/tmux.conf" ]; then
        cp /opt/scripts/tmux.conf "$data_home/.tmux.conf"
        chmod 644 "$data_home/.tmux.conf"
    fi

    # Read the permissions toggle so we can persist it for background listeners.
    # This must happen before writing the env file below.
    local skip_perms
    skip_perms=$(bashio::config 'dangerously_skip_permissions' 'true')
    local perms_flag=""
    if [ "$skip_perms" = "true" ]; then
        perms_flag="--dangerously-skip-permissions"
    fi

    # Write environment file for background processes (listeners, etc.)
    # These processes may lose env vars due to with-contenv shebang reloading
    # the s6 container environment, so we persist the critical vars to a file.
    local env_file="/data/.bruh_claude_env"
    cat > "$env_file" << ENVEOF
export HOME="${data_home}"
export XDG_CONFIG_HOME="${config_dir}"
export XDG_CACHE_HOME="${cache_dir}"
export XDG_STATE_HOME="${state_dir}"
export XDG_DATA_HOME="/data/.local/share"
export ANTHROPIC_CONFIG_DIR="${claude_config_dir}"
export ANTHROPIC_HOME="/data"
export PATH="${data_home}/.local/bin:\${PATH}"
export BRUH_CLAUDE_PERMS_FLAG="${perms_flag}"
ENVEOF
    chmod 600 "$env_file"

    bashio::log.info "Environment initialized:"
    bashio::log.info "  - Home: $HOME"
    bashio::log.info "  - Config: $XDG_CONFIG_HOME"
    bashio::log.info "  - Claude config: $ANTHROPIC_CONFIG_DIR"
    bashio::log.info "  - Env file: $env_file"
}

# ============================================================================
# Non-root User Setup (for --dangerously-skip-permissions)
# ============================================================================

setup_claude_user() {
    bashio::log.info "Setting up non-root Claude user..."

    # Create user if not present (may already exist from Dockerfile)
    if ! id -u claude >/dev/null 2>&1; then
        adduser -D -s /bin/bash -u 1000 claude
    fi

    # Ensure Claude binary is accessible to non-root user
    chmod 755 /root /root/.local /root/.local/bin 2>/dev/null || true

    # Give claude user ownership of persistent data directories
    chown -R claude:claude \
        /data/home \
        /data/.config \
        /data/.cache \
        /data/.local \
        /data/backups \
        /data/tasks 2>/dev/null || true

    # Claude Code needs write access to /config for editing HA configuration.
    # This is safe within the add-on container; HA Core runs in its own container.
    chown claude:claude /config 2>/dev/null || true
    chown -R claude:claude /config/.bruh_claude 2>/dev/null || true
    chown -R claude:claude /config/custom_components 2>/dev/null || true

    # Create a wrapper script so `claude` always runs as the non-root user.
    # This satisfies Claude Code's security requirement that
    # --dangerously-skip-permissions cannot be used as root (UID 0).
    rm -f /usr/local/bin/claude
    cat > /usr/local/bin/claude << 'WRAPPER'
#!/bin/bash
if [ "$(id -u)" = "0" ]; then
    exec su-exec claude /root/.local/bin/claude "$@"
else
    exec /root/.local/bin/claude "$@"
fi
WRAPPER
    chmod +x /usr/local/bin/claude

    bashio::log.info "Claude user configured - claude commands run as non-root (UID 1000)"
}

# ============================================================================
# Legacy Auth Migration
# ============================================================================

migrate_legacy_auth_files() {
    local target_dir="$1"
    local migrated=false

    bashio::log.info "Checking for existing authentication files to migrate..."

    local legacy_locations=(
        "/root/.config/anthropic"
        "/root/.anthropic"
        "/config/claude-config"
        "/tmp/claude-config"
    )

    for legacy_path in "${legacy_locations[@]}"; do
        if [ -d "$legacy_path" ] && [ "$(ls -A "$legacy_path" 2>/dev/null)" ]; then
            bashio::log.info "Migrating auth files from: $legacy_path"
            if cp -r "$legacy_path"/* "$target_dir/" 2>/dev/null; then
                find "$target_dir" -type f -exec chmod 600 {} \;
                if [[ "$legacy_path" == "/root/.config/anthropic" ]] || [[ "$legacy_path" == "/root/.anthropic" ]]; then
                    rm -rf "$legacy_path"
                    ln -sf "$target_dir" "$legacy_path"
                fi
                migrated=true
                bashio::log.info "Migration completed from: $legacy_path"
            fi
        fi
    done

    if [ "$migrated" = false ]; then
        bashio::log.info "No existing authentication files found to migrate"
    fi
}

# ============================================================================
# Tool Installation
# ============================================================================

install_tools() {
    bashio::log.info "Verifying tools..."

    # ttyd and other runtime tools should be in the Docker image already
    # but install if missing (for dev/testing)
    local missing_tools=()
    for tool in ttyd jq curl tmux git inotifywait websocat; do
        if ! command -v "$tool" >/dev/null 2>&1; then
            missing_tools+=("$tool")
        fi
    done

    if [ ${#missing_tools[@]} -gt 0 ]; then
        bashio::log.info "Installing missing tools: ${missing_tools[*]}"
        apk add --no-cache "${missing_tools[@]}" 2>/dev/null || true
    fi

    bashio::log.info "Tools verified"
}

# ============================================================================
# CLI Tools Installation
# ============================================================================

install_cli_tools() {
    bashio::log.info "Installing BRUH CLI tools..."

    # ha-reload - reload HA configurations
    if [ -f "/opt/scripts/ha-reload.sh" ]; then
        cp /opt/scripts/ha-reload.sh /usr/local/bin/ha-reload
        chmod +x /usr/local/bin/ha-reload
    fi

    # ha-log - tail HA logs
    if [ -f "/opt/scripts/ha-log.sh" ]; then
        cp /opt/scripts/ha-log.sh /usr/local/bin/ha-log
        chmod +x /usr/local/bin/ha-log
    fi

    # ha-context-gen - generate CLAUDE.md context
    if [ -f "/opt/scripts/ha-context-gen.sh" ]; then
        cp /opt/scripts/ha-context-gen.sh /usr/local/bin/ha-context-gen
        chmod +x /usr/local/bin/ha-context-gen
    fi

    # ha-backup - manual backup trigger
    if [ -f "/opt/scripts/ha-backup.sh" ]; then
        cp /opt/scripts/ha-backup.sh /usr/local/bin/ha-backup
        chmod +x /usr/local/bin/ha-backup
    fi

    # Session picker
    if [ -f "/opt/scripts/claude-session-picker.sh" ]; then
        cp /opt/scripts/claude-session-picker.sh /usr/local/bin/claude-session-picker
        chmod +x /usr/local/bin/claude-session-picker
    fi

    # Auth helper
    if [ -f "/opt/scripts/claude-auth-helper.sh" ]; then
        chmod +x /opt/scripts/claude-auth-helper.sh
    fi

    # ha-yaml-check - YAML validation
    if [ -f "/opt/scripts/ha-yaml-check.sh" ]; then
        cp /opt/scripts/ha-yaml-check.sh /usr/local/bin/ha-yaml-check
        chmod +x /usr/local/bin/ha-yaml-check
    fi

    # Persist-install
    if [ -f "/opt/scripts/persist-install.sh" ]; then
        cp /opt/scripts/persist-install.sh /usr/local/bin/persist-install
        chmod +x /usr/local/bin/persist-install
    fi

    bashio::log.info "CLI tools installed: ha-reload, ha-log, ha-context-gen, ha-backup, ha-yaml-check"
}

# ============================================================================
# Persistent Packages
# ============================================================================

install_persistent_packages() {
    bashio::log.info "Checking for persistent packages..."

    local persist_config="/data/persistent-packages.json"
    local apk_packages=""
    local pip_packages=""

    # bashio::config returns JSON arrays for list options - parse with jq
    if bashio::config.has_value 'persistent_apk_packages'; then
        local config_apk
        config_apk=$(bashio::config 'persistent_apk_packages')
        if [ -n "$config_apk" ] && [ "$config_apk" != "null" ]; then
            # Parse JSON array to space-separated string
            apk_packages=$(echo "$config_apk" | jq -r '.[]? // empty' 2>/dev/null | tr '\n' ' ')
            # Fallback: if not a JSON array, use as-is
            if [ -z "$apk_packages" ]; then
                apk_packages="$config_apk"
            fi
        fi
    fi

    if bashio::config.has_value 'persistent_pip_packages'; then
        local config_pip
        config_pip=$(bashio::config 'persistent_pip_packages')
        if [ -n "$config_pip" ] && [ "$config_pip" != "null" ]; then
            # Parse JSON array to space-separated string
            pip_packages=$(echo "$config_pip" | jq -r '.[]? // empty' 2>/dev/null | tr '\n' ' ')
            # Fallback: if not a JSON array, use as-is
            if [ -z "$pip_packages" ]; then
                pip_packages="$config_pip"
            fi
        fi
    fi

    if [ -f "$persist_config" ]; then
        local local_apk
        local_apk=$(jq -r '.apk_packages | join(" ")' "$persist_config" 2>/dev/null || echo "")
        if [ -n "$local_apk" ]; then
            apk_packages="$apk_packages $local_apk"
        fi

        local local_pip
        local_pip=$(jq -r '.pip_packages | join(" ")' "$persist_config" 2>/dev/null || echo "")
        if [ -n "$local_pip" ]; then
            pip_packages="$pip_packages $local_pip"
        fi
    fi

    apk_packages=$(echo "$apk_packages" | tr ' ' '\n' | sort -u | tr '\n' ' ' | xargs)
    pip_packages=$(echo "$pip_packages" | tr ' ' '\n' | sort -u | tr '\n' ' ' | xargs)

    if [ -n "$apk_packages" ]; then
        bashio::log.info "Installing persistent APK packages: $apk_packages"
        # shellcheck disable=SC2086
        apk add --no-cache $apk_packages || bashio::log.warning "Some APK packages failed to install"
    fi

    if [ -n "$pip_packages" ]; then
        bashio::log.info "Installing persistent pip packages: $pip_packages"
        # shellcheck disable=SC2086
        pip3 install --break-system-packages --no-cache-dir $pip_packages || bashio::log.warning "Some pip packages failed to install"
    fi

    if [ -z "$apk_packages" ] && [ -z "$pip_packages" ]; then
        bashio::log.info "No persistent packages configured"
    fi
}

# ============================================================================
# Auto-Backup System (git versioning of /config)
# ============================================================================

setup_auto_backup() {
    local auto_backup
    auto_backup=$(bashio::config 'auto_backup' 'true')

    if [ "$auto_backup" != "true" ]; then
        bashio::log.info "Auto-backup disabled"
        return
    fi

    bashio::log.info "Setting up auto-backup for /config..."

    # Initialize git repo in /config if not present
    if [ ! -d "/config/.git" ]; then
        bashio::log.info "Initializing git repository in /config..."
        git -C /config init
        git -C /config config user.email "bruh-claude@homeassistant.local"
        git -C /config config user.name "BRUH Claude Terminal"

        # Create .gitignore for HA config
        if [ ! -f "/config/.gitignore" ]; then
            cat > /config/.gitignore << 'GITIGNORE'
# BRUH Claude Terminal auto-backup gitignore
# Secrets and sensitive files
secrets.yaml
.storage/
.cloud/

# Large/binary files
*.db
*.db-shm
*.db-wal
home-assistant_v2.db*
*.log
*.log.*

# Temporary files
__pycache__/
*.pyc
.cache/
tts/
*.tmp

# Add-on data and Claude config (contains tokens)
claude-config/
.claude/
.claude.json
.mcp.json

# BRUH Claude integration communication (transient files)
.bruh_claude/

# Media and large directories
www/
media/
custom_components/__pycache__/
deps/
GITIGNORE
        fi

        git -C /config add -A
        git -C /config commit -m "Initial BRUH Claude Terminal backup" --allow-empty || true
        bashio::log.info "Git repository initialized in /config"
    fi

    # Start the background backup watcher
    local interval
    interval=$(bashio::config 'backup_interval_minutes' '30')
    /opt/scripts/ha-backup-watcher.sh "$interval" &
    bashio::log.info "Auto-backup watcher started (interval: ${interval}m)"
}

# ============================================================================
# Context Generation
# ============================================================================

setup_context_generation() {
    local auto_gen
    auto_gen=$(bashio::config 'auto_generate_context' 'true')

    if [ "$auto_gen" != "true" ]; then
        bashio::log.info "Auto context generation disabled"
        return
    fi

    bashio::log.info "Generating Home Assistant context for Claude..."
    /opt/scripts/ha-context-gen.sh || bashio::log.warning "Context generation had issues but continuing..."
    bashio::log.info "Context generation complete"
}

# ============================================================================
# HA MCP Server
# ============================================================================

setup_mcp_server() {
    local enable_mcp
    enable_mcp=$(bashio::config 'enable_ha_mcp_server' 'true')

    if [ "$enable_mcp" != "true" ]; then
        bashio::log.info "HA MCP server disabled"
        return
    fi

    bashio::log.info "Configuring HA MCP server for Claude Code..."

    # SECURITY: Do NOT write SUPERVISOR_TOKEN to disk.
    # The MCP server reads it from the environment at runtime.
    # SUPERVISOR_TOKEN is already exported and inherited by child processes.

    # Write MCP config to .mcp.json (Claude Code's project-level MCP config)
    # No tokens in the file - the server inherits SUPERVISOR_TOKEN from the environment
    local project_config="/config/.mcp.json"
    local mcp_entry='{
  "mcpServers": {
    "home-assistant": {
      "command": "python3",
      "args": ["/opt/ha-mcp-server/ha_mcp_server.py"]
    }
  }
}'

    if [ ! -f "$project_config" ]; then
        echo "$mcp_entry" > "$project_config"
        bashio::log.info "MCP server config written to $project_config"
    else
        # Merge MCP config into existing file, preserving other servers
        local tmp_config
        tmp_config=$(mktemp)
        jq '.mcpServers["home-assistant"] = {
          "command": "python3",
          "args": ["/opt/ha-mcp-server/ha_mcp_server.py"]
        }' "$project_config" > "$tmp_config" 2>/dev/null && mv "$tmp_config" "$project_config" || {
            bashio::log.warning "Could not merge MCP config, writing fresh config"
            rm -f "$tmp_config"
            echo "$mcp_entry" > "$project_config"
        }
        bashio::log.info "MCP server config merged into $project_config"
    fi

    bashio::log.info "HA MCP server configured - Claude Code will have real-time HA access"
}

# ============================================================================
# Custom Integration Deployment
# ============================================================================

deploy_custom_integration() {
    local src="/opt/custom_components/bruh_claude"
    local dest="/config/custom_components/bruh_claude"
    local first_install=false
    local is_fresh_install=false
    local src_version

    bashio::log.info "Deploying BRUH Claude custom integration..."

    # Create shared communication directories
    mkdir -p /config/.bruh_claude/requests \
             /config/.bruh_claude/responses \
             /config/.bruh_claude/tasks \
             /config/.bruh_claude/task_results

    if [ ! -d "$src" ]; then
        bashio::log.warning "Custom integration source not found at $src, skipping"
        return
    fi

    src_version=$(jq -r '.version // "0"' "$src/manifest.json" 2>/dev/null || echo "0")
    mkdir -p /config/custom_components

    # Deploy or update the integration files
    if [ -d "$dest" ]; then
        local dest_version
        dest_version=$(jq -r '.version // "0"' "$dest/manifest.json" 2>/dev/null || echo "0")

        if [ "$src_version" != "$dest_version" ]; then
            bashio::log.info "Updating BRUH Claude integration: $dest_version -> $src_version"
            rm -rf "$dest"
            cp -r "$src" "$dest"
            bashio::log.info "Integration updated - Home Assistant will need to restart to apply"
            first_install=true
        else
            bashio::log.info "BRUH Claude integration is up to date (v${dest_version})"
        fi
    else
        cp -r "$src" "$dest"
        bashio::log.info "BRUH Claude integration installed to $dest"
        first_install=true
        is_fresh_install=true
    fi

    # Send discovery via the Supervisor API using bashio.
    # The 'discovery' field in config.yaml authorizes the add-on to use this service
    # name; the add-on must explicitly POST to trigger the actual discovery flow.
    send_discovery_message

    # On first install or update, HA Core needs to restart to load the custom component.
    if [ "$first_install" = "true" ]; then
        notify_restart_required "$src_version" "$is_fresh_install"
    fi
}

send_discovery_message() {
    bashio::log.info "Sending discovery message to Home Assistant..."

    # Build the discovery config payload with add-on metadata
    local addon_version
    addon_version=$(bashio::addon.version 2>/dev/null || echo "1.2.0")
    local config
    config=$(bashio::var.json \
        addon "bruh_claude_terminal" \
        addon_name "BRUH Claude Terminal" \
        version "${addon_version}" \
    )

    # Use bashio::discovery to POST to the Supervisor discovery API
    if bashio::discovery "bruh_claude" "$config" 2>/dev/null; then
        bashio::log.info "Discovery message sent - integration will appear in Settings > Devices & Services"
    else
        # Fallback: direct curl to Supervisor API
        bashio::log.info "Retrying discovery via direct API call..."
        local payload
        payload=$(bashio::var.json \
            service "bruh_claude" \
            config "^${config}" \
        )

        local response
        response=$(curl -s -o /dev/null -w "%{http_code}" \
            -X POST \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "${payload}" \
            "http://supervisor/discovery" 2>/dev/null) || true

        if [ "$response" = "200" ] || [ "$response" = "201" ]; then
            bashio::log.info "Discovery message sent via fallback"
        else
            bashio::log.warning "Discovery API returned HTTP ${response} - auto-discovery may not trigger"
            bashio::log.info "You can set up the integration manually: Settings > Devices & Services > Add Integration > BRUH Claude"
        fi
    fi
}

notify_restart_required() {
    local version="${1:-unknown}"
    local fresh_install="${2:-false}"

    bashio::log.info "============================================"
    bashio::log.info "  New integration files deployed (v${version})!"
    bashio::log.info "  Home Assistant needs a restart to load"
    bashio::log.info "  the BRUH Claude integration."
    bashio::log.info "============================================"

    # Write a marker file so the integration can detect the pending restart
    local marker_payload
    marker_payload=$(jq -n --arg v "$version" '{"required_version": $v}')
    echo "$marker_payload" > /config/.bruh_claude/restart_required

    # Fire an event so the running integration (if loaded) can create a repair issue
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{}' \
        "http://supervisor/core/api/events/bruh_claude_restart_required" 2>/dev/null || true

    if [ "$fresh_install" = "true" ]; then
        # First install: no integration loaded yet, use persistent notification as fallback
        bashio::log.info "First install - sending persistent notification"
        bashio::log.info "Please restart Home Assistant from:"
        bashio::log.info "  Settings > System > Restart"
        bashio::log.info "Then check Settings > Devices & Services for BRUH Claude"

        local notify_payload
        notify_payload=$(jq -n \
            --arg title "BRUH Claude: Restart Required" \
            --arg msg "The BRUH Claude integration has been installed. Please restart Home Assistant to load it.\n\nGo to **Settings > System > Restart**, then check **Settings > Devices & Services** for BRUH Claude." \
            --arg nid "bruh_claude_restart_needed" \
            '{"title": $title, "message": $msg, "notification_id": $nid}')
        curl -s -X POST \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "$notify_payload" \
            "http://supervisor/core/api/services/persistent_notification/create" 2>/dev/null || true
    else
        # Update: integration is loaded, it will show the repair in Settings > System > Repairs
        bashio::log.info "Update detected - repair issue will appear in Settings > System > Repairs"
    fi
}

# ============================================================================
# Assist Integration
# ============================================================================

setup_assist_integration() {
    local enable_assist
    enable_assist=$(bashio::config 'enable_assist_integration' 'true')

    if [ "$enable_assist" != "true" ]; then
        bashio::log.info "Assist integration disabled (enable in app config)"
        return
    fi

    bashio::log.info "Starting Assist integration listener..."
    /opt/integrations/assist-listener.sh &
    bashio::log.info "Assist integration active"
}

# ============================================================================
# Automation Integration
# ============================================================================

setup_automation_integration() {
    local enable_auto
    enable_auto=$(bashio::config 'enable_automation_integration' 'true')

    if [ "$enable_auto" != "true" ]; then
        bashio::log.info "Automation integration disabled (enable in app config)"
        return
    fi

    bashio::log.info "Starting automation webhook listener..."
    /opt/integrations/automation-listener.sh &
    bashio::log.info "Automation integration active"
}

# ============================================================================
# Session Launch
# ============================================================================

# Returns "--dangerously-skip-permissions" if the user has opted in via config,
# or an empty string if disabled. This flag tells Claude Code to execute tool
# calls (file edits, shell commands, etc.) without interactive confirmation.
#
# WHY THIS EXISTS: Inside the HA add-on container, Claude Code runs in a
# sandboxed environment where the only files it can reach are /config and /data.
# Skipping the per-action permission prompts makes the terminal and background
# integrations (Assist, Automations) usable without manual approval of every
# action. The flag is ON by default to preserve the current user experience,
# but can be disabled in the app configuration if you prefer to approve each
# action manually.
#
# SECURITY NOTE: Even with this flag enabled, Claude Code still runs as a
# non-root user (UID 1000) inside an isolated container. It cannot access the
# host OS or other add-ons. Disabling the flag adds an extra confirmation step
# before Claude modifies files or runs commands.
get_permissions_flag() {
    local skip_perms
    skip_perms=$(bashio::config 'dangerously_skip_permissions' 'true')

    if [ "$skip_perms" = "true" ]; then
        echo "--dangerously-skip-permissions"
    else
        echo ""
    fi
}

get_claude_launch_command() {
    local auto_launch_claude
    auto_launch_claude=$(bashio::config 'auto_launch_claude' 'true')
    local perms_flag
    perms_flag=$(get_permissions_flag)

    if [ "$auto_launch_claude" = "true" ]; then
        echo "tmux new-session -A -s claude 'claude ${perms_flag}'"
    else
        if [ -f /usr/local/bin/claude-session-picker ]; then
            echo "tmux new-session -A -s claude-picker '/usr/local/bin/claude-session-picker'"
        else
            bashio::log.warning "Session picker not found, falling back to auto-launch"
            echo "tmux new-session -A -s claude 'claude ${perms_flag}'"
        fi
    fi
}

# ============================================================================
# Web Terminal
# ============================================================================

start_web_terminal() {
    local port=7681
    bashio::log.info "Starting BRUH Claude Terminal on port ${port}..."

    bashio::log.info "Environment:"
    bashio::log.info "  ANTHROPIC_CONFIG_DIR=${ANTHROPIC_CONFIG_DIR}"
    bashio::log.info "  HOME=${HOME}"
    bashio::log.info "  HA MCP Server: $(bashio::config 'enable_ha_mcp_server' 'true')"
    bashio::log.info "  Auto-backup: $(bashio::config 'auto_backup' 'true')"
    bashio::log.info "  Skip permissions: $(bashio::config 'dangerously_skip_permissions' 'true')"

    local launch_command
    launch_command=$(get_claude_launch_command)

    local auto_launch_claude
    auto_launch_claude=$(bashio::config 'auto_launch_claude' 'true')
    bashio::log.info "Auto-launch Claude: ${auto_launch_claude}"

    export TTYD=1

    # Use wait instead of exec so the cleanup trap can fire on SIGTERM
    # and properly terminate background processes (backup watcher, listeners)
    ttyd \
        --port "${port}" \
        --interface 0.0.0.0 \
        --writable \
        --ping-interval 30 \
        --client-option enableReconnect=true \
        --client-option reconnect=10 \
        --client-option reconnectInterval=5 \
        bash -c "$launch_command" &

    wait $!
}

# ============================================================================
# Health Check
# ============================================================================

run_health_check() {
    if [ -f "/opt/scripts/health-check.sh" ]; then
        bashio::log.info "Running system health check..."
        chmod +x /opt/scripts/health-check.sh
        /opt/scripts/health-check.sh || bashio::log.warning "Some health checks failed but continuing..."
    fi
}

# ============================================================================
# Main
# ============================================================================

# Clean up background processes on exit
cleanup() {
    bashio::log.info "Shutting down background processes..."
    # Kill all child processes
    kill $(jobs -p) 2>/dev/null || true
    wait 2>/dev/null || true
    bashio::log.info "Cleanup complete"
}

trap cleanup SIGTERM SIGINT EXIT

main() {
    bashio::log.info "============================================"
    bashio::log.info "  BRUH Claude Terminal v1.5.1"
    bashio::log.info "  Enhanced Claude Code for Home Assistant"
    bashio::log.info "============================================"

    run_health_check
    init_environment
    setup_claude_user
    install_tools
    install_cli_tools
    install_persistent_packages
    setup_auto_backup
    setup_context_generation
    setup_mcp_server
    deploy_custom_integration
    setup_assist_integration
    setup_automation_integration
    start_web_terminal
}

main "$@"
