#!/usr/bin/with-contenv bashio

# BRUH Claude Terminal - Enhanced startup script
# Features: HA MCP server, auto-backup, context generation, config reload, log access

set -e
set -o pipefail

# ============================================================================
# Environment Initialization
# ============================================================================

# Helper: Replace a real directory with a symlink, salvaging any files first.
# This is needed because the Claude Code installer may create real directories
# at paths we need to symlink to persistent storage. `ln -sfn` cannot replace
# a real directory, so we must remove it first.
_replace_dir_with_symlink() {
    local dir_path="$1"
    local link_dest="$2"

    if [ -d "$dir_path" ] && [ ! -L "$dir_path" ]; then
        # Real directory found — salvage any auth files to persistent storage
        if [ "$(ls -A "$dir_path" 2>/dev/null)" ]; then
            bashio::log.info "  - Salvaging credentials from $dir_path to persistent storage"
            cp -a "$dir_path"/* "$link_dest/" 2>/dev/null || true
        fi
        rm -rf "$dir_path"
    fi
    ln -sfn "$link_dest" "$dir_path"
}

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

    # Disable Claude Code's built-in auto-updater — the add-on handles
    # updates at startup via update_claude_code() running as root.
    # The auto-updater fails when Claude Code runs as the non-root claude
    # user because it cannot write to npm global dirs or /root/.local/bin.
    export DISABLE_AUTOUPDATER=1

    # HA API environment - make SUPERVISOR_TOKEN easily accessible
    export HA_TOKEN="${SUPERVISOR_TOKEN}"
    export HA_BASE_URL="http://supervisor/core/api"
    export SUPERVISOR_API_URL="http://supervisor"

    # Adopt Home Assistant's timezone so Claude (terminal, voice, tasks)
    # reasons in local time instead of the container default (UTC). Cached
    # to a shared file the listeners/pool read; falls back to the previous
    # cache if HA Core isn't answering yet at boot.
    local ha_tz=""
    ha_tz=$(curl -s -m 5 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        "http://supervisor/core/api/config" 2>/dev/null | jq -r '.time_zone // empty') || true
    mkdir -p /config/.bruh_claude/cache
    if [ -n "$ha_tz" ]; then
        printf '%s' "$ha_tz" > /config/.bruh_claude/cache/ha_timezone
    elif [ -r /config/.bruh_claude/cache/ha_timezone ]; then
        ha_tz=$(cat /config/.bruh_claude/cache/ha_timezone)
    fi
    if [ -n "$ha_tz" ]; then
        export TZ="$ha_tz"
        bashio::log.info "  - Timezone: $ha_tz (from HA config)"
    fi

    # Volume mount directories — only export if enabled in config
    local access_share access_media access_backup access_addon_configs access_addons
    access_share=$(bashio::config 'access_share' 'true')
    access_media=$(bashio::config 'access_media' 'true')
    access_backup=$(bashio::config 'access_backup' 'true')
    access_addon_configs=$(bashio::config 'access_addon_configs' 'true')
    access_addons=$(bashio::config 'access_addons' 'true')

    if [ "$access_share" = "true" ] && [ -d "/share" ]; then
        export SHARE_DIR="/share"
    fi
    if [ "$access_media" = "true" ] && [ -d "/media" ]; then
        export MEDIA_DIR="/media"
    fi
    if [ "$access_backup" = "true" ] && [ -d "/backup" ]; then
        export BACKUP_DIR="/backup"
    fi
    if [ "$access_addon_configs" = "true" ] && [ -d "/addon_configs" ]; then
        export ADDON_CONFIG_DIR="/addon_configs"
    fi
    if [ "$access_addons" = "true" ] && [ -d "/addons" ]; then
        export ADDONS_DIR="/addons"
    fi

    # Migrate any existing authentication files from legacy locations
    migrate_legacy_auth_files "$claude_config_dir"

    # Ensure auth symlinks always point to persistent storage.
    # On add-on updates the container is rebuilt fresh, so any symlinks from the
    # previous container are gone. Re-create them every startup so Claude Code
    # can find auth credentials regardless of which path it checks.
    #
    # CRITICAL: The Claude Code installer may create real directories at these
    # paths during the Docker build. `ln -sfn` CANNOT replace a real directory
    # with a symlink — it either fails silently or creates a link inside the
    # directory. We must explicitly remove any real directories first, salvaging
    # any credential files they might contain.
    mkdir -p /root/.config "$data_home/.config"

    local symlink_targets=(
        "/root/.config/claude"
        "/root/.config/anthropic"
        "$data_home/.config/claude"
        "$data_home/.config/anthropic"
    )

    for target in "${symlink_targets[@]}"; do
        _replace_dir_with_symlink "$target" "$claude_config_dir"
    done

    # Claude Code also checks $HOME/.claude/ for settings and credentials.
    # This directory lives directly in persistent storage (/data/home/.claude/).
    mkdir -p "$data_home/.claude"
    # Symlink from /root/.claude → persistent storage
    _replace_dir_with_symlink "/root/.claude" "$data_home/.claude"

    bashio::log.info "  - Auth symlinks refreshed for persistent OAuth"

    # Log credential status for debugging
    local cred_count
    cred_count=$(find "$claude_config_dir" -type f 2>/dev/null | wc -l)
    local claude_dot_count
    claude_dot_count=$(find "$data_home/.claude" -type f 2>/dev/null | wc -l)
    bashio::log.info "  - Credential files: $cred_count in $claude_config_dir, $claude_dot_count in $data_home/.claude"

    # Install tmux configuration
    if [ -f "/opt/scripts/tmux.conf" ]; then
        cp /opt/scripts/tmux.conf "$data_home/.tmux.conf"
        chmod 644 "$data_home/.tmux.conf"
    fi

    # Read the permissions toggle.  This controls the interactive terminal ONLY.
    # Background listeners (Assist, Automation) do NOT use this flag — they get
    # tool permissions from /config/.claude/settings.local.json instead.
    local skip_perms
    skip_perms=$(bashio::config 'dangerously_skip_permissions' 'false')
    local perms_flag=""
    if [ "$skip_perms" = "true" ]; then
        perms_flag="--dangerously-skip-permissions"
    fi

    # Write environment file for background processes (listeners, etc.)
    # These processes may lose env vars due to with-contenv shebang reloading
    # the s6 container environment, so we persist the critical vars to a file.
    #
    # SUPERVISOR_TOKEN is included so that the MCP server and HA API calls
    # always have valid auth, even if the listener process doesn't inherit
    # the token from the s6 environment for any reason.
    #
    # NOTE: BRUH_CLAUDE_PERMS_FLAG is used by the interactive terminal only.
    local assist_max_turns
    assist_max_turns=$(bashio::config 'assist_max_turns' '5')
    local automation_max_turns
    automation_max_turns=$(bashio::config 'automation_max_turns' '10')
    local assist_tool_access
    assist_tool_access=$(bashio::config 'assist_tool_access' 'mcp_only')

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
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_BASE_URL="http://supervisor/core/api"
export SUPERVISOR_API_URL="http://supervisor"
export BRUH_ASSIST_MAX_TURNS="${assist_max_turns}"
export BRUH_AUTOMATION_MAX_TURNS="${automation_max_turns}"
export BRUH_ASSIST_TOOL_ACCESS="${assist_tool_access}"
export TZ="${TZ:-}"
export CLAUDE_CODE_DISABLE_MCP_DISCOVERY=1
export CLAUDE_MCP_SERVERS_OVERRIDE="/config/.mcp.json"
export DISABLE_AUTOUPDATER=1
ENVEOF

    # Append enabled directory env vars to the env file
    [ -n "${SHARE_DIR:-}" ] && echo "export SHARE_DIR=\"${SHARE_DIR}\"" >> "$env_file"
    [ -n "${MEDIA_DIR:-}" ] && echo "export MEDIA_DIR=\"${MEDIA_DIR}\"" >> "$env_file"
    [ -n "${BACKUP_DIR:-}" ] && echo "export BACKUP_DIR=\"${BACKUP_DIR}\"" >> "$env_file"
    [ -n "${ADDON_CONFIG_DIR:-}" ] && echo "export ADDON_CONFIG_DIR=\"${ADDON_CONFIG_DIR}\"" >> "$env_file"
    [ -n "${ADDONS_DIR:-}" ] && echo "export ADDONS_DIR=\"${ADDONS_DIR}\"" >> "$env_file"

    # Handle additional user-configured directories
    if bashio::config.has_value 'additional_directories'; then
        local additional_dirs
        additional_dirs=$(bashio::config 'additional_directories')
        local dir_index=0
        for dir_path in $(echo "$additional_dirs" | jq -r '.[]? // empty' 2>/dev/null); do
            if [ -d "$dir_path" ]; then
                echo "export ADDITIONAL_DIR_${dir_index}=\"${dir_path}\"" >> "$env_file"
                dir_index=$((dir_index + 1))
                bashio::log.info "  - Additional directory: $dir_path"
            else
                bashio::log.warning "  - Additional directory not found: $dir_path (skipped)"
            fi
        done
    fi
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

    # Grant ownership of enabled volume mounts
    [ -n "${SHARE_DIR:-}" ] && chown claude:claude /share 2>/dev/null || true
    [ -n "${MEDIA_DIR:-}" ] && chown claude:claude /media 2>/dev/null || true
    [ -n "${ADDON_CONFIG_DIR:-}" ] && chown -R claude:claude /addon_configs 2>/dev/null || true
    [ -n "${ADDONS_DIR:-}" ] && chown -R claude:claude /addons 2>/dev/null || true

    # Grant ownership of additional user-configured directories
    if bashio::config.has_value 'additional_directories'; then
        local add_dirs
        add_dirs=$(bashio::config 'additional_directories')
        for dir_path in $(echo "$add_dirs" | jq -r '.[]? // empty' 2>/dev/null); do
            if [ -d "$dir_path" ]; then
                chown claude:claude "$dir_path" 2>/dev/null || true
            fi
        done
    fi

    # Create a wrapper script so `claude` always runs as the non-root user.
    # This satisfies Claude Code's security requirement that
    # --dangerously-skip-permissions cannot be used as root (UID 0).
    #
    # The wrapper lives at /usr/local/bin/claude-run (NOT /usr/local/bin/claude)
    # to prevent Claude Code diagnostics from detecting it as a conflicting
    # "npm-global" installation.  The interactive terminal and background
    # listeners reference this wrapper directly.
    # npm install -g puts the claude binary at /usr/local/bin/claude which
    # triggers a misleading "npm-global" diagnostic warning. We need to remove
    # it, but /root/.local/bin/claude may be a symlink pointing to it.
    # Resolve the real path first so we can re-point the symlink.
    if [ -e /usr/local/bin/claude ]; then
        local real_claude
        real_claude=$(readlink -f /usr/local/bin/claude 2>/dev/null || echo "")
        rm -f /usr/local/bin/claude
        if [ -n "$real_claude" ] && [ -f "$real_claude" ]; then
            mkdir -p /root/.local/bin
            ln -sf "$real_claude" /root/.local/bin/claude
        fi
    fi
    rm -f /usr/local/bin/claude-run      # clean slate
    cat > /usr/local/bin/claude-run << 'WRAPPER'
#!/bin/bash
# Source HA environment (SUPERVISOR_TOKEN, DISABLE_AUTOUPDATER, etc.)
# This ensures env vars reach Claude Code even if tmux/su-exec don't
# fully propagate the parent environment.
if [ -r /data/.bruh_claude_env ]; then
    . /data/.bruh_claude_env
fi
if [ "$(id -u)" = "0" ]; then
    exec su-exec claude /root/.local/bin/claude "$@"
else
    exec /root/.local/bin/claude "$@"
fi
WRAPPER
    chmod +x /usr/local/bin/claude-run

    # Set up shell profile for the claude user so that:
    # 1. $HOME/.local/bin is in PATH (fixes "not in PATH" diagnostic warning)
    # 2. SUPERVISOR_TOKEN and HA env vars are available in interactive shells
    # 3. The `claude` command resolves to the native binary
    local profile="/data/home/.bashrc"
    cat > "$profile" << 'PROFILE'
# BRUH Claude Terminal shell profile (auto-generated at startup)
export PATH="$HOME/.local/bin:$PATH"

# Source HA environment if available
if [ -r /data/.bruh_claude_env ]; then
    . /data/.bruh_claude_env
fi

# HA API token (inherited from add-on environment)
if [ -z "$SUPERVISOR_TOKEN" ] && [ -n "$HA_TOKEN" ]; then
    export SUPERVISOR_TOKEN="$HA_TOKEN"
fi
PROFILE
    chown claude:claude "$profile"
    chmod 644 "$profile"

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

# Claude Code version to install. Defaults to "latest".
#
# The @anthropic-ai/claude-code npm package installs a prebuilt NATIVE
# binary (…-linux-*-musl optional dependencies + a postinstall,
# install.cjs). Those musl builds need posix_getdents — a symbol musl added
# in 1.2.6 — so they only run on Alpine 3.24+ (this add-on's base image;
# see the Dockerfile's BUILD_FROM default). On older bases (3.19 = musl
# 1.2.4 … 3.21 = musl 1.2.5) the
# binary fails to relocate ("posix_getdents: symbol not found"), `claude
# --version` prints nothing, and the web terminal opens then exits instantly.
# Now that we build on 3.24 we track upstream again. Pin a specific version
# with BRUH_CLAUDE_CODE_VERSION (kept in sync with the Dockerfile's
# CLAUDE_CODE_VERSION build arg) if a future release ever regresses.
CLAUDE_CODE_DEFAULT_VERSION="latest"

# Print Claude Code's version and return 0 only if the binary actually RUNS.
# A broken native build installs fine but exits non-zero with no version
# string, so this probe cleanly distinguishes "works" from "bricked".
claude_version_or_empty() {
    local v
    v=$(/root/.local/bin/claude --version 2>/dev/null | head -1 | awk '{print $1}') || true
    if printf '%s' "$v" | grep -qE '^[0-9]+\.[0-9]+\.[0-9]+'; then
        printf '%s' "$v"
        return 0
    fi
    return 1
}

update_claude_code() {
    local target_version="${BRUH_CLAUDE_CODE_VERSION:-$CLAUDE_CODE_DEFAULT_VERSION}"
    bashio::log.info "Checking Claude Code (target: ${target_version})..."

    local current_version
    current_version=$(claude_version_or_empty || echo "unknown")
    bashio::log.info "  - Current Claude Code version: ${current_version}"

    # "latest" always reinstalls so auto-updates keep flowing. A pinned,
    # specific version that's already installed and runs takes the fast path
    # and skips the reinstall.
    if [ "$target_version" = "latest" ] || [ "$current_version" != "$target_version" ]; then
        local install_output=""
        local attempt
        local install_success=false
        for attempt in 1 2 3 4; do
            if install_output=$(npm install -g "@anthropic-ai/claude-code@${target_version}" 2>&1); then
                install_success=true
                break
            fi
            bashio::log.info "  - npm install attempt ${attempt}/4 failed, retrying in $((attempt * 2))s..."
            sleep $((attempt * 2))
        done

        if [ "$install_success" = "true" ]; then
            # Re-point /root/.local/bin/claude at whatever npm just installed
            # (resolve the real file, not the /usr/local/bin symlink that
            # setup_claude_user removes).
            local npm_claude_bin
            npm_claude_bin=$(readlink -f "$(command -v claude 2>/dev/null)" 2>/dev/null || echo "")
            if [ -n "$npm_claude_bin" ] && [ -f "$npm_claude_bin" ]; then
                mkdir -p /root/.local/bin
                ln -sf "$npm_claude_bin" /root/.local/bin/claude
            fi

            # CRITICAL: verify the freshly-installed binary actually RUNS.
            # A native musl build that needs a symbol this base image lacks
            # installs cleanly but dies on exec — which is exactly what makes
            # the web terminal open and vanish. Catch it and say so loudly
            # instead of leaving a bricked terminal.
            local new_version
            if new_version=$(claude_version_or_empty); then
                bashio::log.info "  - Claude Code ready: ${current_version} -> v${new_version}"
            else
                bashio::log.error "Claude Code (${target_version}) installed but won't run on this system."
                bashio::log.error "  The native binary likely needs a newer musl than the base image"
                bashio::log.error "  provides. The web terminal will open and exit instantly. Pin a"
                bashio::log.error "  known-good version with the BRUH_CLAUDE_CODE_VERSION env var."
            fi
        else
            bashio::log.warning "Claude Code install failed after 4 attempts - continuing with current version"
            bashio::log.warning "Last npm output: ${install_output}"
        fi
    else
        bashio::log.info "  - Claude Code is up to date (v${current_version})"
    fi

    # Keep the persistent symlink + perms correct on every path.
    local native_bin_dir="/data/home/.local/bin"
    mkdir -p "$native_bin_dir"
    ln -sf /root/.local/bin/claude "$native_bin_dir/claude"
    chmod 755 /root /root/.local /root/.local/bin 2>/dev/null || true
}

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

    # New CLI tools: ha-addon, ha-entity, ha-service, ha-notify, ha-share, ha-selftest
    for script in ha-addon ha-entity ha-service ha-notify ha-share ha-selftest; do
        if [ -f "/opt/scripts/${script}.sh" ]; then
            cp "/opt/scripts/${script}.sh" "/usr/local/bin/${script}"
            chmod +x "/usr/local/bin/${script}"
        fi
    done

    bashio::log.info "CLI tools installed: ha-reload, ha-log, ha-context-gen, ha-backup, ha-yaml-check, ha-addon, ha-entity, ha-service, ha-notify, ha-share, ha-selftest"
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
# Claude Code Plugin / Config Cleanup
# ============================================================================

cleanup_all_mcp_references() {
    bashio::log.info "Deep cleaning ALL /api/mcp references..."

    # -------------------------------------------------------------------------
    # 1. Clear persistent conversation sessions so --resume starts fresh.
    #    This is the critical fix for the v1.8.0 regression: resumed sessions
    #    cache stale MCP server connection state that survives .mcp.json cleanup.
    # -------------------------------------------------------------------------
    local sessions_dir="/config/.bruh_claude/sessions"
    if [ -d "$sessions_dir" ]; then
        local session_count
        session_count=$(find "$sessions_dir" -name "*.session" -type f 2>/dev/null | wc -l)
        if [ "$session_count" -gt 0 ]; then
            rm -f "$sessions_dir"/*.session
            bashio::log.info "  Cleared $session_count persistent conversation sessions"
        fi
    fi

    # -------------------------------------------------------------------------
    # 2. Clean Claude Code's internal project state that caches MCP connections.
    #    Project configs live in hashed subdirectories like
    #    ~/.claude/projects/<sha256-hash>/settings.json and .mcp.json.
    #    The previous maxdepth-4 search could miss deeply nested entries.
    # -------------------------------------------------------------------------
    local claude_projects="/data/home/.claude/projects"
    if [ -d "$claude_projects" ]; then
        find "$claude_projects" -type f -name "*.json" -print0 2>/dev/null | \
        while IFS= read -r -d '' f; do
            if grep -q "/api/mcp\|homeassistant-config\|claude-homeassistant-plugins" "$f" 2>/dev/null; then
                bashio::log.info "  Cleaning project config: $f"
                local tmp
                tmp=$(mktemp)
                if jq '
                    # Remove mcpServers entries pointing to /api/mcp
                    if .mcpServers then
                        .mcpServers |= with_entries(
                            select(
                                .key != "homeassistant-config" and
                                ((.value | tostring) | contains("/api/mcp") | not)
                            )
                        )
                    else . end |
                    # Remove stale permission entries for old plugins
                    if .permissions?.allow then
                        .permissions.allow |= map(
                            select(
                                contains("homeassistant-config") | not
                            ) | select(
                                contains("claude-homeassistant-plugins") | not
                            )
                        )
                    else . end |
                    # Remove plugin/extension marketplace references
                    del(.plugins) | del(.extensions)
                ' "$f" > "$tmp" 2>/dev/null; then
                    mv "$tmp" "$f"
                    chown claude:claude "$f" 2>/dev/null || true
                else
                    rm -f "$tmp"
                fi
            fi
        done
    fi

    # -------------------------------------------------------------------------
    # 3. Clean ALL settings/config directories (broader search than before).
    #    Use unlimited depth to catch configs in deeply nested project hashes.
    # -------------------------------------------------------------------------
    local search_dirs=(
        "/data/.config/claude"
        "/data/home/.config/claude"
        "/config/.claude"
        "/root/.claude"
        "/root/.config/claude"
    )

    for dir in "${search_dirs[@]}"; do
        [ -d "$dir" ] || continue

        while IFS= read -r -d '' config_file; do
            if grep -q "claude-homeassistant-plugins\|homeassistant-config\|/api/mcp" "$config_file" 2>/dev/null; then
                bashio::log.info "  Found stale reference in: $config_file"
                local tmp_file
                tmp_file=$(mktemp)
                if jq '
                    if .mcpServers then
                        .mcpServers |= with_entries(
                            select(
                                .key != "homeassistant-config" and
                                ((.value | tostring) | contains("/api/mcp") | not)
                            )
                        )
                    else . end |
                    if .permissions?.allow then
                        .permissions.allow |= map(
                            select(
                                contains("homeassistant-config") | not
                            ) | select(
                                contains("claude-homeassistant-plugins") | not
                            )
                        )
                    else . end |
                    del(.plugins) | del(.extensions)
                ' "$config_file" > "$tmp_file" 2>/dev/null; then
                    mv "$tmp_file" "$config_file"
                    chown claude:claude "$config_file" 2>/dev/null || true
                else
                    rm -f "$tmp_file"
                fi
            fi
        done < <(find "$dir" -name "*.json" -type f -print0 2>/dev/null)
    done

    # -------------------------------------------------------------------------
    # 4. Clean ALL .mcp.json files anywhere in /data, /config, /root.
    #    Our canonical config at /config/.mcp.json is skipped — it gets
    #    overwritten clean by setup_mcp_server() later in the startup flow.
    # -------------------------------------------------------------------------
    find /data /config /root -name ".mcp.json" -type f -print0 2>/dev/null | \
    while IFS= read -r -d '' f; do
        [ "$f" = "/config/.mcp.json" ] && continue
        if grep -q "/api/mcp\|homeassistant-config" "$f" 2>/dev/null; then
            bashio::log.info "  Removing stale MCP config: $f"
            rm -f "$f"
        fi
    done

    # -------------------------------------------------------------------------
    # 5. Remove the broken npm plugin package from ALL possible locations.
    #    Use find to catch any installation path, not just hardcoded ones.
    # -------------------------------------------------------------------------
    find /data /root -type d -name "claude-homeassistant-plugins" -print0 2>/dev/null | \
    while IFS= read -r -d '' d; do
        bashio::log.info "  Removing plugin directory: $d"
        rm -rf "$d"
    done

    # -------------------------------------------------------------------------
    # 6. Clean ~/.claude.json (Claude Code's global config).
    #    This is the PRIMARY hiding spot for stale /api/mcp MCP server entries
    #    added by marketplace plugins. Previous cleanup steps missed this file
    #    because it's not in the searched directories and not named .mcp.json.
    # -------------------------------------------------------------------------
    local claude_json="/data/home/.claude.json"
    if [ -f "$claude_json" ] && grep -q "/api/mcp\|homeassistant-config\|claude-homeassistant-plugins" "$claude_json" 2>/dev/null; then
        bashio::log.info "  Cleaning stale entries from ~/.claude.json"
        local tmp
        tmp=$(mktemp)
        if jq '
            if .mcpServers then
                .mcpServers |= with_entries(
                    select(
                        .key != "homeassistant-config" and
                        ((.value | tostring) | contains("/api/mcp") | not) and
                        ((.value | tostring) | contains("claude-homeassistant-plugins") | not)
                    )
                )
            else . end |
            if .permissions?.allow then
                .permissions.allow |= map(
                    select(
                        contains("homeassistant-config") | not
                    ) | select(
                        contains("claude-homeassistant-plugins") | not
                    )
                )
            else . end |
            del(.plugins) | del(.extensions)
        ' "$claude_json" > "$tmp" 2>/dev/null; then
            mv "$tmp" "$claude_json"
            chown claude:claude "$claude_json" 2>/dev/null || true
            bashio::log.info "  ~/.claude.json cleaned"
        else
            rm -f "$tmp"
        fi
    fi

    bashio::log.info "Deep MCP cleanup complete"
}

# ============================================================================
# HA MCP Server
# ============================================================================

setup_mcp_server() {
    local enable_mcp
    enable_mcp=$(bashio::config 'enable_ha_mcp_server' 'true')

    if [ "$enable_mcp" != "true" ]; then
        bashio::log.info "HA MCP server disabled"
        # Still write project settings — background listeners need the allowlist
        setup_claude_settings
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

    # ALWAYS write a clean config — do NOT merge with existing entries.
    # The add-on owns this file. The only valid MCP server is the BRUH Claude
    # stdio server. Merging risks preserving stale entries from broken
    # marketplace plugins that cause /api/mcp auth errors.
    echo "$mcp_entry" > "$project_config"
    bashio::log.info "MCP server config written to $project_config (clean overwrite)"

    # Safety check: verify the file is clean after write
    if grep -q "/api/mcp" "$project_config" 2>/dev/null; then
        bashio::log.error "CRITICAL: /api/mcp still found in $project_config after clean write!"
        echo "$mcp_entry" > "$project_config"
    fi

    # CRITICAL: Claude Code runs as the 'claude' user (UID 1000) but this
    # script runs as root.  Without this chown, Claude Code gets EACCES
    # trying to read .mcp.json and the HA MCP server never loads.
    chown claude:claude "$project_config" 2>/dev/null || true
    chmod 644 "$project_config"

    # Log the final state for diagnostics
    local mcp_owner mcp_perms
    mcp_owner=$(stat -c '%U:%G' "$project_config" 2>/dev/null || echo "unknown")
    mcp_perms=$(stat -c '%a' "$project_config" 2>/dev/null || echo "unknown")
    bashio::log.info "HA MCP server configured (owner=$mcp_owner, perms=$mcp_perms)"
    bashio::log.info "  Token available: $([ -n "$SUPERVISOR_TOKEN" ] && echo "yes (${#SUPERVISOR_TOKEN} chars)" || echo "NO")"

    # Log all configured MCP servers for diagnostic purposes
    bashio::log.info "Configured MCP servers in $project_config:"
    jq -r '.mcpServers | to_entries[] | "  - \(.key): \(.value.command // .value.url // "unknown") \(.value.args // [] | join(" "))"' "$project_config" 2>/dev/null || true

    # Clean stale entries from additional MCP configs (don't just warn — fix them).
    for extra_mcp in "/data/home/.mcp.json" "/root/.mcp.json"; do
        if [ -f "$extra_mcp" ] && grep -q "/api/mcp\|homeassistant-config" "$extra_mcp" 2>/dev/null; then
            bashio::log.warning "Removing stale MCP config: $extra_mcp"
            rm -f "$extra_mcp"
        fi
    done

    # ~/.claude.json needs surgical cleaning (contains OAuth creds and other config)
    local global_claude="/data/home/.claude.json"
    if [ -f "$global_claude" ] && grep -q "/api/mcp\|homeassistant-config\|claude-homeassistant-plugins" "$global_claude" 2>/dev/null; then
        bashio::log.warning "Cleaning stale MCP entries from ~/.claude.json"
        local tmp
        tmp=$(mktemp)
        if jq '
            if .mcpServers then
                .mcpServers |= with_entries(
                    select(
                        .key != "homeassistant-config" and
                        ((.value | tostring) | contains("/api/mcp") | not) and
                        ((.value | tostring) | contains("claude-homeassistant-plugins") | not)
                    )
                )
            else . end
        ' "$global_claude" > "$tmp" 2>/dev/null; then
            mv "$tmp" "$global_claude"
            chown claude:claude "$global_claude" 2>/dev/null || true
            bashio::log.info "  ~/.claude.json cleaned"
        else
            rm -f "$tmp"
        fi
    fi

    # Write project-level Claude Code settings that pre-allow all necessary
    # tools.  This is the PRIMARY permission mechanism for background listeners
    # (Assist, Automation) — they rely on this allowlist instead of
    # --dangerously-skip-permissions, which has issues running as root/su-exec.
    # The interactive terminal also benefits: matching tools are auto-approved.
    setup_claude_settings
}

# Voice tool scoping: the assist channel loads this deny-list via --settings
# when assist_tool_access is mcp_only (default). Deny wins over the project
# allowlist, so voice keeps every MCP device tool but can't run shell
# commands, edit files, or reach the web. Automations keep full access.
setup_assist_scoping() {
    mkdir -p /config/.bruh_claude
    cat > /config/.bruh_claude/assist_settings.json << 'SCOPE'
{
  "permissions": {
    "deny": [
      "Bash",
      "Bash(*)",
      "Read",
      "Glob",
      "Grep",
      "Write",
      "Edit",
      "NotebookEdit",
      "WebFetch",
      "WebSearch",
      "Agent",
      "Skill"
    ]
  }
}
SCOPE
    chown claude:claude /config/.bruh_claude/assist_settings.json 2>/dev/null || true
    chmod 644 /config/.bruh_claude/assist_settings.json
    bashio::log.info "Assist tool scoping file written (mode: $(bashio::config 'assist_tool_access' 'mcp_only'))"
}

setup_claude_settings() {
    local claude_settings_dir="/config/.claude"
    mkdir -p "$claude_settings_dir"
    cat > "$claude_settings_dir/settings.local.json" << 'SETTINGS'
{
  "permissions": {
    "allow": [
      "mcp__home-assistant__*",
      "mcp__claude_ai_Home_Assistant__*",
      "mcp__claude_ai_Vercel__*",
      "Bash(*)",
      "Read",
      "Write",
      "Edit",
      "Glob",
      "Grep",
      "Agent",
      "Skill",
      "WebFetch",
      "WebSearch",
      "NotebookEdit",
      "TaskCreate",
      "TaskUpdate",
      "TaskGet",
      "TaskList",
      "TodoWrite",
      "TodoRead"
    ]
  }
}
SETTINGS
    chown -R claude:claude "$claude_settings_dir" 2>/dev/null || true
    bashio::log.info "Claude Code project settings written to $claude_settings_dir/settings.local.json"
}

# Start a background watchdog that monitors for /api/mcp entries being
# re-created by Claude Code or plugins after our cleanup.  This helps
# pinpoint the root cause if the broken entry keeps coming back.
start_mcp_watchdog() {
    bashio::log.info "Starting MCP watchdog (checks every 30s for /api/mcp re-creation)..."
    touch /tmp/.mcp_watchdog_marker
    (
        while true; do
            sleep 30
            # Check all MCP/settings configs modified since last check
            find /data /config /root -name "*.json" \
                -newer /tmp/.mcp_watchdog_marker \
                -type f -print0 2>/dev/null | \
            while IFS= read -r -d '' f; do
                if grep -q "/api/mcp" "$f" 2>/dev/null; then
                    bashio::log.error "MCP WATCHDOG: /api/mcp found in $f (modified after startup)"
                    bashio::log.error "  Content: $(head -20 "$f" 2>/dev/null)"
                    # Auto-clean: remove the offending entry immediately
                    if echo "$f" | grep -q "\.mcp\.json$"; then
                        # For .mcp.json files, remove and let setup_mcp_server() pattern rewrite
                        if [ "$f" != "/config/.mcp.json" ]; then
                            rm -f "$f"
                            bashio::log.info "MCP WATCHDOG: Removed $f"
                        else
                            # Rewrite the canonical config clean
                            cat > "$f" << 'WATCHDOG_MCP'
{
  "mcpServers": {
    "home-assistant": {
      "command": "python3",
      "args": ["/opt/ha-mcp-server/ha_mcp_server.py"]
    }
  }
}
WATCHDOG_MCP
                            chown claude:claude "$f" 2>/dev/null || true
                            chmod 644 "$f"
                            bashio::log.info "MCP WATCHDOG: Rewrote $f clean"
                        fi
                    else
                        # For settings/project files, clean with jq
                        local tmp
                        tmp=$(mktemp)
                        if jq '
                            if .mcpServers then
                                .mcpServers |= with_entries(
                                    select((.value | tostring) | contains("/api/mcp") | not)
                                )
                            else . end
                        ' "$f" > "$tmp" 2>/dev/null; then
                            mv "$tmp" "$f"
                            chown claude:claude "$f" 2>/dev/null || true
                            bashio::log.info "MCP WATCHDOG: Cleaned /api/mcp from $f"
                        else
                            rm -f "$tmp"
                        fi
                    fi
                fi
            done
            touch /tmp/.mcp_watchdog_marker
        done
    ) &
    bashio::log.info "MCP watchdog running (PID=$!)"
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
             /config/.bruh_claude/task_results \
             /config/.bruh_claude/sessions \
             /config/.bruh_claude/logs

    # Rotate old debug logs (keep last 7 days)
    find /config/.bruh_claude/logs -name "*.log" -mtime +7 -delete 2>/dev/null || true

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
# Token Stats Tracker (disabled — token usage sensors removed in v1.9.0)
# ============================================================================

# ============================================================================
# Usage Limits Tracker (real Anthropic account data)
# ============================================================================

start_usage_limits_tracker() {
    bashio::log.info "Starting Anthropic usage limits tracker..."

    if [ -f "/opt/scripts/usage-limits-tracker.py" ]; then
        # Run as the claude user so it can read OAuth credentials from ~/.claude/
        su-exec claude python3 /opt/scripts/usage-limits-tracker.py &
        bashio::log.info "Usage limits tracker started (writes to /config/.bruh_claude/usage_limits.json)"
    else
        bashio::log.warning "Usage limits tracker script not found, skipping"
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

    # Fast mode keeps pre-warmed Claude processes alive (worker pool) so
    # voice turns skip the CLI boot + MCP handshake. The classic listener
    # remains as the opt-out (assist_fast_mode: false) and the pool itself
    # falls back to one-shot invocations when a worker misbehaves.
    local fast_mode
    fast_mode=$(bashio::config 'assist_fast_mode' 'true')

    if [ "$fast_mode" = "true" ] && [ -f /opt/integrations/assist-worker-pool.py ]; then
        bashio::log.info "Starting Assist worker pool (fast mode)..."
        # Babysitter: restart the pool if it ever exits (self-healing; the
        # Supervisor watchdog key is deliberately NOT used because it can't
        # be conditional on assist/fast-mode being enabled).
        (
            while true; do
                python3 /opt/integrations/assist-worker-pool.py
                bashio::log.warning "Assist worker pool exited — restarting in 5s"
                sleep 5
            done
        ) &
        bashio::log.info "Assist integration active (worker pool + HTTP API)"
    else
        bashio::log.info "Starting Assist integration listener (classic)..."
        # Remove a stale fast-mode endpoint so the integration doesn't try
        # (and have to fail over from) an API that isn't running.
        rm -f /config/.bruh_claude/api_endpoint.json
        /opt/integrations/assist-listener.sh &
        bashio::log.info "Assist integration active"
    fi
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
# This flag controls the INTERACTIVE TERMINAL only. Background listeners
# (Assist conversation agents, Automation tasks) get their tool permissions
# from /config/.claude/settings.local.json, which pre-approves MCP tools,
# Bash, Read, Write, and Edit — so they never need this flag.
#
# The flag is OFF by default.  The project-level settings.local.json already
# grants the permissions Claude Code needs to work with Home Assistant, so
# most users do not need to enable this.  Turning it on skips ALL permission
# prompts, including for operations not in the allowlist.
#
# SECURITY NOTE: Even with this flag enabled, Claude Code still runs as a
# non-root user (UID 1000) inside an isolated container. It cannot access the
# host OS or other add-ons.
get_permissions_flag() {
    local skip_perms
    skip_perms=$(bashio::config 'dangerously_skip_permissions' 'false')

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
        echo "tmux new-session -A -s claude '/usr/local/bin/claude-run ${perms_flag}'"
    else
        if [ -f /usr/local/bin/claude-session-picker ]; then
            echo "tmux new-session -A -s claude-picker '/usr/local/bin/claude-session-picker'"
        else
            bashio::log.warning "Session picker not found, falling back to auto-launch"
            echo "tmux new-session -A -s claude '/usr/local/bin/claude-run ${perms_flag}'"
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
    bashio::log.info "  Skip permissions: $(bashio::config 'dangerously_skip_permissions' 'false')"

    local launch_command
    launch_command=$(get_claude_launch_command)

    local auto_launch_claude
    auto_launch_claude=$(bashio::config 'auto_launch_claude' 'true')
    bashio::log.info "Auto-launch Claude: ${auto_launch_claude}"

    export TTYD=1

    # Mobile toolbar + iOS dictation diff-fix.  Opt-in via `enable_mobile_ui`
    # (default on).  build-mobile-index.py probes ttyd locally, fetches the
    # full inlined HTML it serves at `/`, and splices our toolbar + iOS
    # input-capture script into <head> so it runs before ttyd's bundle.
    # On any probe error we log the builder's stderr verbatim and fall
    # back to ttyd's stock UI — no more silent "black screen" regressions.
    local index_arg=()
    local enable_mobile_ui
    enable_mobile_ui=$(bashio::config 'enable_mobile_ui' 'true')
    if [ "$enable_mobile_ui" = "true" ] \
        && [ -f /opt/scripts/build-mobile-index.py ] \
        && [ -f /opt/ttyd-assets/inject.html ]; then
        local build_log="/tmp/bruh-mobile-ui.log"
        if python3 /opt/scripts/build-mobile-index.py >"$build_log" 2>&1; then
            if [ -f /opt/ttyd-assets/index.html ]; then
                # ttyd refuses to start if --index target isn't readable by
                # the process.  Belt-and-suspenders chmod + log.
                chmod 644 /opt/ttyd-assets/index.html
                index_arg=(--index /opt/ttyd-assets/index.html)
                bashio::log.info "  Mobile UI: enabled ($(sed -n 's/^\[bruh-mobile-ui\] //p' "$build_log" | tail -1))"
            else
                bashio::log.warning "  Mobile UI: builder reported success but index.html missing; using stock UI"
            fi
        else
            bashio::log.warning "  Mobile UI: probe failed, using stock ttyd UI"
            while IFS= read -r line; do bashio::log.warning "    $line"; done <"$build_log"
        fi
    elif [ "$enable_mobile_ui" = "true" ]; then
        bashio::log.warning "  Mobile UI: assets not present in image, using stock UI"
    else
        bashio::log.info "  Mobile UI: disabled via enable_mobile_ui=false"
    fi

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
        --client-option 'fontFamily=SF Mono, Menlo, Consolas, monospace' \
        --client-option 'theme={"background":"#1a1613","foreground":"#e8ddd4","cursor":"#d97757","cursorAccent":"#1a1613","selectionBackground":"#d9775766"}' \
        "${index_arg[@]}" \
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
    bashio::log.info "  BRUH Claude Terminal v2.2.1"
    bashio::log.info "  Enhanced Claude Code for Home Assistant"
    bashio::log.info "============================================"

    run_health_check
    init_environment
    update_claude_code
    setup_claude_user
    install_tools
    install_cli_tools
    install_persistent_packages
    setup_auto_backup
    setup_context_generation
    cleanup_all_mcp_references
    setup_mcp_server
    start_mcp_watchdog
    setup_assist_scoping
    deploy_custom_integration
    start_usage_limits_tracker
    setup_assist_integration
    setup_automation_integration
    start_web_terminal
}

main "$@"
