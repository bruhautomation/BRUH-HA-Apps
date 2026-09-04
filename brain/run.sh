#!/usr/bin/with-contenv bashio

# brAIn - Enhanced startup script
# Features: HA MCP server, edit snapshots (brain undo), context generation,
# config reload, log access

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
        # Real directory found — salvage any auth files to persistent storage.
        # NOTE: the glob must include dotfiles (.credentials.json!) and must
        # never clobber newer files already in persistent storage — an image-
        # baked default overwriting a real credential file logs the user out.
        if [ "$(ls -A "$dir_path" 2>/dev/null)" ]; then
            bashio::log.info "  - Salvaging credentials from $dir_path to persistent storage"
            (
                shopt -s dotglob nullglob
                for entry in "$dir_path"/*; do
                    base=$(basename "$entry")
                    if [ ! -e "$link_dest/$base" ]; then
                        cp -a "$entry" "$link_dest/" 2>/dev/null || true
                    elif [ "$base" = ".credentials.json" ] && [ "$entry" -nt "$link_dest/$base" ]; then
                        # Two credential files = two OAuth refresh-token
                        # lineages, and rotation means only the most recently
                        # refreshed one is still usable. Keeping the older
                        # copy here is what caused "OAuth session expired and
                        # could not be refreshed" in background channels
                        # after the 3.3.1 unification — take the newer file.
                        cp -a "$link_dest/$base" "$link_dest/$base.stale" 2>/dev/null || true
                        cp -a "$entry" "$link_dest/$base" 2>/dev/null || true
                        bashio::log.warning "  - Newer .credentials.json in $dir_path wins (old copy kept as .credentials.json.stale)"
                    fi
                done
            )
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

    bashio::log.info "Initializing brAIn environment..."

    if ! mkdir -p \
        "$data_home" \
        "$config_dir/claude" \
        "$cache_dir" \
        "$state_dir" \
        "/data/.local/share" \
        "/data/backups" \
        "/data/.brain/edits/snapshots" \
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

    # Pin Claude Code's config/credential directory to persistent storage.
    # Without this, Claude Code resolves ~/.claude from the process HOME —
    # and any launch path that loses or resets HOME (tmux respawns, su/login
    # shells, passwd-home lookups) silently reads/writes credentials in the
    # container layer instead, which survives restarts but is wiped on every
    # add-on update ("I have to re-login after every update", issue #102).
    # CLAUDE_CONFIG_DIR is the documented override and removes the HOME
    # dependency entirely. /data/home/.claude is where HOME-based resolution
    # already put existing logins, so no credential migration is needed.
    export CLAUDE_CONFIG_DIR="$data_home/.claude"

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
    mkdir -p /config/.brain/cache
    if [ -n "$ha_tz" ]; then
        printf '%s' "$ha_tz" > /config/.brain/cache/ha_timezone
    elif [ -r /config/.brain/cache/ha_timezone ]; then
        ha_tz=$(cat /config/.brain/cache/ha_timezone)
    fi
    if [ -n "$ha_tz" ]; then
        export TZ="$ha_tz"
        bashio::log.info "  - Timezone: $ha_tz (from HA config)"
    fi

    # Shared secrets directory for cross-add-on auth (ha-share-login writes
    # /config/.brain/secrets/claude_auth.json for e.g. brAIn).
    mkdir -p /config/.brain/secrets
    chmod 700 /config/.brain/secrets

    # Long-term home memory store (brain memory / the memory consolidator).
    mkdir -p /config/.brain/memory/inbox
    # Findings hand-off: study sessions run on the CLI side and drop anything
    # they found broken here, where the panel's Findings tab sweeps it up.
    # Same shape and same reason as the memory inbox.
    mkdir -p /config/.brain/findings/inbox
    if [ ! -f /config/.brain/memory/memory.md ]; then
        cat > /config/.brain/memory/memory.md << 'MEMORYMD'
# Home Memory

<!-- This file is user-editable — add, correct, or delete anything. -->
<!-- It is also auto-consolidated: the brain memory consolidator merges new
     facts from the inbox into it (newest wins on contradictions). -->

## Preferences

## Entity nicknames

## Household patterns

## Device notes
MEMORYMD
        bashio::log.info "  - Memory store seeded at /config/.brain/memory/"
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

    # If a previous session wrote credentials to the claude user's passwd
    # home (/home/claude — container layer, wiped on update), rescue them
    # into persistent storage before they're lost to the next update.
    mkdir -p /home/claude
    _replace_dir_with_symlink "/home/claude/.claude" "$data_home/.claude"

    # With CLAUDE_CONFIG_DIR set, Claude Code keeps its global config at
    # $CLAUDE_CONFIG_DIR/.claude.json rather than ~/.claude.json. Carry the
    # existing file over once so onboarding state and OAuth account metadata
    # survive the switch (never overwrite — the new location wins once used).
    if [ -f "$data_home/.claude.json" ] && [ ! -f "$data_home/.claude/.claude.json" ]; then
        cp -a "$data_home/.claude.json" "$data_home/.claude/.claude.json"
        bashio::log.info "  - Migrated ~/.claude.json to CLAUDE_CONFIG_DIR"
    fi

    # Credential backup / restore safety net. Claude Code deletes or
    # truncates .credentials.json in some failure modes (e.g. a token
    # refresh that errors out mid-flight at boot). Keep the last known
    # good copy in /data and restore it when the live file has vanished —
    # worst case the restored token is stale and the user logs in anyway,
    # best case a re-login is avoided entirely.
    local auth_backup_dir="/data/.brain_auth_backup"
    mkdir -p "$auth_backup_dir"
    chmod 700 "$auth_backup_dir"
    # Only ever restore a credential that is still live. "Worst case the
    # restored token is stale and the user logs in anyway" was the original
    # reasoning and it was wrong: the CLI's own file outranks every other
    # store for the terminal, so restoring a dead one puts the add-on back
    # into "the chat works but the terminal asks me to log in" on every
    # single boot, with no way for it to clear.
    _credential_is_live() {
        jq -e --argjson now "$(date +%s)" '
            (.claudeAiOauth // {}) as $o
            | (($o.accessToken // "") | startswith("sk-ant-"))
              and (($o.expiresAt // 0) <= 0
                   or (($o.expiresAt / 1000) > ($now + 60)))
        ' "$1" > /dev/null 2>&1
    }
    if [ -s "$data_home/.claude/.credentials.json" ]; then
        cp -a "$data_home/.claude/.credentials.json" "$auth_backup_dir/.credentials.json"
    elif [ -s "$auth_backup_dir/.credentials.json" ]; then
        if _credential_is_live "$auth_backup_dir/.credentials.json"; then
            cp -a "$auth_backup_dir/.credentials.json" "$data_home/.claude/.credentials.json"
            chmod 600 "$data_home/.claude/.credentials.json"
            bashio::log.warning "  - .credentials.json was missing — restored last known good copy"
        else
            rm -f "$auth_backup_dir/.credentials.json"
            bashio::log.warning "  - Discarded an expired .credentials.json backup rather than restoring it"
        fi
    fi
    unset -f _credential_is_live

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
    # NOTE: BRAIN_CLAUDE_PERMS_FLAG is used by the interactive terminal only.
    local assist_max_turns
    assist_max_turns=$(bashio::config 'assist_max_turns' '8')
    local automation_max_turns
    automation_max_turns=$(bashio::config 'automation_max_turns' '30')
    local assist_tool_access
    assist_tool_access=$(bashio::config 'assist_tool_access' 'mcp_only')
    # Exported as well as written to the env file: the bash listeners
    # re-source /data/.brain_env, but the worker pool — the *default*
    # assist path — is plain python3 launched from this script and reads
    # os.environ only. Without these exports assist_max_turns and
    # assist_tool_access were dead options in fast mode.
    export BRAIN_ASSIST_MAX_TURNS="$assist_max_turns"
    export BRAIN_AUTOMATION_MAX_TURNS="$automation_max_turns"
    export BRAIN_ASSIST_TOOL_ACCESS="$assist_tool_access"

    # Memory / learning options — exported here too (not just written to the
    # env file) so the worker pool and listeners launched by this script
    # inherit them directly.
    local assist_learning memory_injection memory_max_kb edit_journal_days
    assist_learning=$(bashio::config 'learning' 'true')
    memory_injection=$(bashio::config 'memory_injection' 'true')
    memory_max_kb=$(bashio::config 'memory_max_kb' '32')
    edit_journal_days=$(bashio::config 'edit_journal_days' '14')
    export BRAIN_ASSIST_LEARNING="$assist_learning"
    export BRAIN_MEMORY_INJECTION="$memory_injection"
    export BRAIN_MEMORY_MAX_KB="$memory_max_kb"
    export BRAIN_EDIT_JOURNAL_DAYS="$edit_journal_days"

    # Findings notifications. The panel prefers the live Supervisor options
    # (a Configuration-tab edit lands without a restart); these exports are
    # its fallback for when the Supervisor cannot be read.
    local findings_notify findings_notify_sev
    findings_notify=$(bashio::config 'findings_notify_service' '')
    findings_notify_sev=$(bashio::config 'findings_notify_min_severity' 'serious')
    export BRAIN_FINDINGS_NOTIFY="$findings_notify"
    export BRAIN_FINDINGS_NOTIFY_MIN_SEVERITY="$findings_notify_sev"
    local quiet_start quiet_end
    quiet_start=$(bashio::config 'notify_quiet_start' '22')
    quiet_end=$(bashio::config 'notify_quiet_end' '7')
    export BRAIN_NOTIFY_QUIET_START="$quiet_start"
    export BRAIN_NOTIFY_QUIET_END="$quiet_end"
    local morning_brief morning_brief_hour
    morning_brief=$(bashio::config 'morning_brief' 'false')
    morning_brief_hour=$(bashio::config 'morning_brief_hour' '7')
    export BRAIN_MORNING_BRIEF="$morning_brief"
    export BRAIN_MORNING_BRIEF_HOUR="$morning_brief_hour"
    local weekly_report weekly_report_day
    weekly_report=$(bashio::config 'weekly_report' 'false')
    weekly_report_day=$(bashio::config 'weekly_report_day' 'sunday')
    export BRAIN_WEEKLY_REPORT="$weekly_report"
    export BRAIN_WEEKLY_REPORT_DAY="$weekly_report_day"

    # Study sessions are where depth actually matters, and --max-turns
    # truncates rather than degrading — a session that hits the cap files
    # nothing at all. Generous by default; 0 removes the cap entirely.
    local study_max_turns study_timeout_min
    study_max_turns=$(bashio::config 'study_max_turns' '60')
    study_timeout_min=$(bashio::config 'study_timeout_minutes' '30')
    local study_timeout_s=$((study_timeout_min * 60))
    export BRAIN_LEARN_MAX_TURNS="$study_max_turns"
    export BRAIN_LEARN_TIMEOUT="$study_timeout_s"

    # House checks and the protected-entity policy. The checks interval
    # is the panel's; the protected list is the MCP server's, and the MCP
    # server is launched by whichever Claude process is asking — the panel's
    # fixer, the worker pool, the listeners, the terminal — so it has to be
    # in the environment ALL of them inherit, which is this export plus the
    # env file. bashio prints a list option one item per line; joined on
    # commas because an entity id cannot contain one.
    local checks_interval_hours protected_entities
    checks_interval_hours=$(bashio::config 'checks_interval_hours' '6')
    protected_entities=$(bashio::config 'protected_entities' 2>/dev/null \
        | grep -v '^null$' | paste -sd, - || true)
    export BRAIN_CHECKS_INTERVAL_HOURS="$checks_interval_hours"
    export BRAIN_PROTECTED_ENTITIES="$protected_entities"

    local env_file="/data/.brain_env"
    cat > "$env_file" << ENVEOF
export HOME="${data_home}"
export XDG_CONFIG_HOME="${config_dir}"
export XDG_CACHE_HOME="${cache_dir}"
export XDG_STATE_HOME="${state_dir}"
export XDG_DATA_HOME="/data/.local/share"
export ANTHROPIC_CONFIG_DIR="${claude_config_dir}"
export ANTHROPIC_HOME="/data"
export CLAUDE_CONFIG_DIR="${data_home}/.claude"
export PATH="${data_home}/.local/bin:\${PATH}"
export BRAIN_CLAUDE_PERMS_FLAG="${perms_flag}"
export SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN}"
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_BASE_URL="http://supervisor/core/api"
export SUPERVISOR_API_URL="http://supervisor"
export BRAIN_ASSIST_MAX_TURNS="${assist_max_turns}"
export BRAIN_AUTOMATION_MAX_TURNS="${automation_max_turns}"
export BRAIN_ASSIST_TOOL_ACCESS="${assist_tool_access}"
export BRAIN_ASSIST_LEARNING="${assist_learning}"
export BRAIN_MEMORY_INJECTION="${memory_injection}"
export BRAIN_MEMORY_MAX_KB="${memory_max_kb}"
export BRAIN_EDIT_JOURNAL_DAYS="${edit_journal_days}"
export BRAIN_LEARN_MAX_TURNS="${study_max_turns}"
export BRAIN_LEARN_TIMEOUT="${study_timeout_s}"
export BRAIN_CHECKS_INTERVAL_HOURS="${checks_interval_hours}"
export BRAIN_PROTECTED_ENTITIES="${protected_entities}"
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

    # Create user if not present (may already exist from Dockerfile).
    # The passwd home MUST be the persistent /data/home: anything that
    # resolves the home from /etc/passwd instead of $HOME (login shells,
    # `su`, some libc/homedir fallbacks) would otherwise land credentials
    # and state in /home/claude — container layer, wiped on every update.
    if ! id -u claude >/dev/null 2>&1; then
        adduser -D -s /bin/bash -u 1000 -h /data/home claude
    elif [ "$(getent passwd claude | cut -d: -f6)" != "/data/home" ]; then
        sed -i 's|^\(claude:[^:]*:[^:]*:[^:]*:[^:]*:\)[^:]*\(:.*\)$|\1/data/home\2|' /etc/passwd
        bashio::log.info "  - claude user home repointed to /data/home"
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
        /data/.brain \
        /data/tasks 2>/dev/null || true

    # The run-source ledger is written by BOTH sides: the panel (root) and
    # the background callers the panel does not run — the consolidator and
    # the study watcher, which start under `su-exec claude`. Whoever created
    # it first owned it, and root won, so every daemon pass failed to claim
    # its session id with "Permission denied" and ran unlabelled. That is
    # the whole point of the ledger: an unlabelled consolidation shows up in
    # the Chats rail as if somebody typed it, and `adopt` picks it up.
    # Create it claude-owned and group-writable up front — root can write a
    # claude-owned file regardless, so only this direction needs arranging.
    touch /data/run-sources.jsonl 2>/dev/null || true
    chown claude:claude /data/run-sources.jsonl 2>/dev/null || true
    chmod 664 /data/run-sources.jsonl 2>/dev/null || true

    # Claude Code needs write access to /config for editing HA configuration.
    # This is safe within the add-on container; HA Core runs in its own container.
    chown claude:claude /config 2>/dev/null || true
    chown -R claude:claude /config/.brain 2>/dev/null || true
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
if [ -r /data/.brain_env ]; then
    . /data/.brain_env
fi
# A sign-in done in the panel has to reach the CLI too, or the terminal
# asks you to log in again for no reason.
if [ -r /opt/scripts/brain-auth-env.sh ]; then
    . /opt/scripts/brain-auth-env.sh
fi
if [ "$(id -u)" = "0" ]; then
    exec su-exec claude \
        env ${ANTHROPIC_API_KEY:+ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY"} \
            ${CLAUDE_CODE_OAUTH_TOKEN:+CLAUDE_CODE_OAUTH_TOKEN="$CLAUDE_CODE_OAUTH_TOKEN"} \
        /root/.local/bin/claude "$@"
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
# brAIn shell profile (auto-generated at startup)
export PATH="$HOME/.local/bin:$PATH"

# Source HA environment if available
if [ -r /data/.brain_env ]; then
    . /data/.brain_env
fi

# HA API token (inherited from add-on environment)
if [ -z "$SUPERVISOR_TOKEN" ] && [ -n "$HA_TOKEN" ]; then
    export SUPERVISOR_TOKEN="$HA_TOKEN"
fi

# Pick up a credential saved from the panel, so a bare `claude` in this
# shell is already signed in rather than prompting a second time.
if [ -r /opt/scripts/brain-auth-env.sh ]; then
    . /opt/scripts/brain-auth-env.sh
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
# with BRAIN_CLAUDE_CODE_VERSION (kept in sync with the Dockerfile's
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
    local target_version="${BRAIN_CLAUDE_CODE_VERSION:-$CLAUDE_CODE_DEFAULT_VERSION}"
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
                bashio::log.error "  known-good version with the BRAIN_CLAUDE_CODE_VERSION env var."
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
    bashio::log.info "Installing brAIn CLI..."

    # Two dispatchers replace the old ha-* script pile: `brain` for brAIn's
    # own faculties (memory, learning, undo) and `ha` for Home Assistant
    # operations. Both delegate to the scripts already in /opt/scripts, so
    # nothing else needs to land on PATH.
    local installed=""

    if [ -f "/opt/scripts/brain.sh" ]; then
        cp /opt/scripts/brain.sh /usr/local/bin/brain
        chmod +x /usr/local/bin/brain
        installed="brain"
    fi

    # `ha` is also the name of the Supervisor CLI on the HA OS host. It is
    # not normally present inside an add-on container, but if some base
    # image ever ships it, shadowing it would be a nasty surprise — so we
    # check first and fall back to `hass`.
    if [ -f "/opt/scripts/ha.sh" ]; then
        local ha_target="/usr/local/bin/ha"
        if command -v ha >/dev/null 2>&1; then
            ha_target="/usr/local/bin/hass"
            bashio::log.warning "A pre-existing 'ha' command was found; installing brAIn's as 'hass' instead"
        fi
        cp /opt/scripts/ha.sh "$ha_target"
        chmod +x "$ha_target"
        installed="${installed}, $(basename "$ha_target")"
    fi

    # Kept on PATH in their own right: neither is a brAIn faculty nor an HA
    # operation, and both are typed directly by users and by Claude.
    for script in persist-install brain-menu brain-terminal-start; do
        if [ -f "/opt/scripts/${script}.sh" ]; then
            cp "/opt/scripts/${script}.sh" "/usr/local/bin/${script}"
            chmod +x "/usr/local/bin/${script}"
        fi
    done

    if [ -f "/opt/scripts/brain-auth-helper.sh" ]; then
        chmod +x /opt/scripts/brain-auth-helper.sh
    fi

    # Everything the dispatchers delegate to must be executable in place.
    find /opt/scripts -name "*.sh" -exec chmod +x {} \; 2>/dev/null || true
    find /opt/scripts -name "*.py" -exec chmod +x {} \; 2>/dev/null || true

    bashio::log.info "CLI installed: ${installed}, persist-install (try 'brain help' / 'ha help')"
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
    # Session mappings are stored as bare <conversation_id> files (no
    # extension) by both the worker pool and the classic listener — a
    # "*.session" glob matches nothing and leaves every stale mapping alive.
    local sessions_dir="/config/.brain/sessions"
    if [ -d "$sessions_dir" ]; then
        local session_count
        session_count=$(find "$sessions_dir" -type f 2>/dev/null | wc -l)
        if [ "$session_count" -gt 0 ]; then
            find "$sessions_dir" -type f -delete 2>/dev/null || true
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
    local claude_json
    for claude_json in "/data/home/.claude.json" "/data/home/.claude/.claude.json"; do
    if [ -f "$claude_json" ] && grep -q "/api/mcp\|homeassistant-config\|claude-homeassistant-plugins" "$claude_json" 2>/dev/null; then
        bashio::log.info "  Cleaning stale entries from ${claude_json}"
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
            bashio::log.info "  ${claude_json} cleaned"
        else
            rm -f "$tmp"
        fi
    fi
    done

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
    # The add-on owns this file. The only valid MCP server is the brAIn
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
    local global_claude
    for global_claude in "/data/home/.claude.json" "/data/home/.claude/.claude.json"; do
    if [ -f "$global_claude" ] && grep -q "/api/mcp\|homeassistant-config\|claude-homeassistant-plugins" "$global_claude" 2>/dev/null; then
        bashio::log.warning "Cleaning stale MCP entries from ${global_claude}"
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
            bashio::log.info "  ${global_claude} cleaned"
        else
            rm -f "$tmp"
        fi
    fi
    done

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
    mkdir -p /config/.brain
    cat > /config/.brain/assist_settings.json << 'SCOPE'
{
  "enableAllProjectMcpServers": true,
  "enabledMcpjsonServers": ["home-assistant"],
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
    chown claude:claude /config/.brain/assist_settings.json 2>/dev/null || true
    chmod 644 /config/.brain/assist_settings.json
    bashio::log.info "Assist tool scoping file written (mode: $(bashio::config 'assist_tool_access' 'mcp_only'))"
}

setup_claude_settings() {
    local claude_settings_dir="/config/.claude"
    mkdir -p "$claude_settings_dir"
    # enableAllProjectMcpServers / enabledMcpjsonServers pre-APPROVE the
    # project-scoped home-assistant server declared in /config/.mcp.json.
    # Current Claude Code requires project .mcp.json servers to be trusted
    # before they load; in non-interactive `-p` runs (Automation tasks,
    # classic Assist) an unapproved server is silently skipped, so Claude
    # reports "MCP server unavailable" and can't touch HA. Approving it here
    # (a non-checked-in local settings file — the documented way to skip the
    # interactive trust dialog) makes the HA tools load in every headless run.
    # NOTE: this is separate from the permissions.allow entry below, which
    # only governs whether an already-loaded tool may run without a prompt.
    cat > "$claude_settings_dir/settings.local.json" << 'SETTINGS'
{
  "enableAllProjectMcpServers": true,
  "enabledMcpjsonServers": ["home-assistant"],
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
  },
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 /opt/scripts/brain-edit-snapshot.py"
          }
        ]
      }
    ]
  }
}
SETTINGS
    chown -R claude:claude "$claude_settings_dir" 2>/dev/null || true
    # Slash commands. /learn is the terminal-native face of a study session:
    # you watch it work and can correct it mid-flight, which a scheduled run
    # can't offer. Regenerated each start so an updated add-on ships updated
    # commands.
    local commands_dir="$claude_settings_dir/commands"
    mkdir -p "$commands_dir"
    cat > "$commands_dir/learn.md" << 'LEARNCMD'
---
description: Study one aspect of this home and write down what you find
---

Run a study session on: $ARGUMENTS

If no topic was given, run `brain learn --list` first and pick whichever has
gone stalest.

Investigate properly before writing anything down — the registries for
structure, current state for a snapshot, history for recent behaviour, and
long-term statistics for patterns over weeks. Depth is the point; there is no
prize for finishing early.

Then file what you found with `brain memory add "<fact>"`, one call per fact.
Only durable properties of this home — things that will still be true next
month. "The dryer draws ~3 kWh per cycle" is a fact; "the dryer is on" is not.
Never re-record something `brain memory list` already shows.

Finish with a two-to-four sentence summary of what you learned. If you learned
nothing new, say so plainly rather than padding.
LEARNCMD

    cat > "$commands_dir/memory.md" << 'MEMCMD'
---
description: Show what brAIn knows about this home
---

Run `brain memory list` and summarise what the home memory currently holds.
Then run `brain memory hypotheses` and, if anything is waiting, show it and
offer to settle it with `brain memory confirm` / `brain memory reject`.

If the user gave arguments ($ARGUMENTS), treat them as a fact to remember and
queue it with `brain memory add` instead.
MEMCMD

    chown -R claude:claude "$commands_dir" 2>/dev/null || true
    bashio::log.info "Slash commands installed: /learn, /memory"

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
            # Only files that can actually hold MCP server config. This
            # was `-name "*.json"`, which swept up transcripts, stores and
            # state files: a chat that merely *mentioned* /api/mcp got its
            # transcript rewritten by root while the panel was writing it.
            find /data /config /root \
                \( -name ".mcp.json" -o -name ".claude.json" \
                   -o -name "settings.json" -o -name "settings.local.json" \) \
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
                        # For settings/project files, clean with jq — but
                        # only when the offending string is actually in an
                        # mcpServers entry; a mention elsewhere in the file
                        # is not ours to rewrite.
                        local tmp
                        tmp=$(mktemp)
                        if jq -e '.mcpServers | tostring | contains("/api/mcp")' \
                                "$f" >/dev/null 2>&1 \
                            && jq '
                            if .mcpServers then
                                .mcpServers |= with_entries(
                                    select((.value | tostring) | contains("/api/mcp") | not)
                                )
                            else . end
                        ' "$f" > "$tmp" 2>/dev/null; then
                            # cat, not mv: mv swaps the inode, which both
                            # crosses filesystems from mktemp's /tmp and
                            # hands the file to root whatever it was before.
                            cat "$tmp" > "$f" && rm -f "$tmp"
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
    local src="/opt/custom_components/brain"
    local dest="/config/custom_components/brain"
    local first_install=false
    local is_fresh_install=false
    local src_version

    bashio::log.info "Deploying brAIn custom integration..."

    # Create shared communication directories
    mkdir -p /config/.brain/requests \
             /config/.brain/responses \
             /config/.brain/tasks \
             /config/.brain/task_results \
             /config/.brain/sessions \
             /config/.brain/logs

    # Rotate old debug logs (keep last 7 days)
    find /config/.brain/logs -name "*.log" -mtime +7 -delete 2>/dev/null || true

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
            bashio::log.info "Updating brAIn integration: $dest_version -> $src_version"
            rm -rf "$dest"
            cp -r "$src" "$dest"
            bashio::log.info "Integration updated - Home Assistant will need to restart to apply"
            first_install=true
        else
            bashio::log.info "brAIn integration is up to date (v${dest_version})"
        fi
    else
        cp -r "$src" "$dest"
        bashio::log.info "brAIn integration installed to $dest"
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
        addon "brain" \
        addon_name "brAIn" \
        version "${addon_version}" \
    )

    # Use bashio::discovery to POST to the Supervisor discovery API
    if bashio::discovery "brain" "$config" 2>/dev/null; then
        bashio::log.info "Discovery message sent - integration will appear in Settings > Devices & Services"
    else
        # Fallback: direct curl to Supervisor API
        bashio::log.info "Retrying discovery via direct API call..."
        local payload
        payload=$(bashio::var.json \
            service "brain" \
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
            bashio::log.info "You can set up the integration manually: Settings > Devices & Services > Add Integration > brAIn"
        fi
    fi
}

notify_restart_required() {
    local version="${1:-unknown}"
    local fresh_install="${2:-false}"

    bashio::log.info "============================================"
    bashio::log.info "  New integration files deployed (v${version})!"
    bashio::log.info "  Home Assistant needs a restart to load"
    bashio::log.info "  the brAIn integration."
    bashio::log.info "============================================"

    # Write a marker file so the integration can detect the pending restart
    local marker_payload
    marker_payload=$(jq -n --arg v "$version" '{"required_version": $v}')
    echo "$marker_payload" > /config/.brain/restart_required

    # Fire an event so the running integration (if loaded) can create a repair issue
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{}' \
        "http://supervisor/core/api/events/brain_restart_required" 2>/dev/null || true

    if [ "$fresh_install" = "true" ]; then
        # First install: no integration loaded yet, use persistent notification as fallback
        bashio::log.info "First install - sending persistent notification"
        bashio::log.info "Please restart Home Assistant from:"
        bashio::log.info "  Settings > System > Restart"
        bashio::log.info "Then check Settings > Devices & Services for brAIn"

        local notify_payload
        notify_payload=$(jq -n \
            --arg title "brAIn: Restart Required" \
            --arg msg "The brAIn integration has been installed. Please restart Home Assistant to load it.\n\nGo to **Settings > System > Restart**, then check **Settings > Devices & Services** for brAIn." \
            --arg nid "brain_restart_needed" \
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
        # The tracker has to read whichever store the person actually signed
        # in to, and two of the three are root-owned 0700 directories: the
        # panel's /data/secrets and the shared /config/.brain/secrets. Run as
        # the claude user and it can read the CLI's own credential and
        # nothing else — which is how a panel sign-in ended up reported as
        # "not authenticated". Root reads all three; the claude user cannot
        # be given the other two without opening the token files up.
        export BRAIN_HOME="${BRAIN_HOME:-/data/home}"
        export BRAIN_SECRETS="${BRAIN_SECRETS:-/data/secrets}"
        export BRAIN_SHARED_AUTH="${BRAIN_SHARED_AUTH:-/config/.brain/secrets/claude_auth.json}"
        python3 /opt/scripts/usage-limits-tracker.py &
        bashio::log.info "Usage limits tracker started (writes to /config/.brain/usage_limits.json)"
    else
        bashio::log.warning "Usage limits tracker script not found, skipping"
    fi
}

# ============================================================================
# Memory Consolidator (learned home knowledge)
# ============================================================================

start_study_watcher() {
    local learning
    learning=$(bashio::config 'learning' 'true')
    if [ "$learning" != "true" ]; then
        bashio::log.info "Study watcher disabled (learning: false)"
        return
    fi
    if [ -f "/opt/scripts/brain-study-watcher.sh" ]; then
        su-exec claude bash /opt/scripts/brain-study-watcher.sh &
        bashio::log.info "Study watcher started (runs brain.study requests from HA)"
    fi
}

start_memory_consolidator() {
    # One-line hint (independent of the learning toggle): logged in, but the
    # login isn't shared with other BRUH add-ons yet — ha-share-login makes
    # that a one-command fix.
    if [ ! -f /config/.brain/secrets/claude_auth.json ]; then
        if [ -f /data/home/.claude/.credentials.json ] || [ -f /data/.config/claude/.credentials.json ]; then
            bashio::log.info "Tip: run 'ha-share-login' in the terminal to share this Claude login with other BRUH add-ons (like brAIn)."
        fi
    fi

    local learning
    learning=$(bashio::config 'learning' 'true')

    if [ "$learning" != "true" ]; then
        bashio::log.info "Memory consolidator disabled (learning: false)"
        return
    fi

    if [ -f "/opt/scripts/brain-memory-consolidate.sh" ]; then
        # Run as the claude user so memory files stay claude-owned and the
        # Claude CLI can read its OAuth credentials.
        su-exec claude bash /opt/scripts/brain-memory-consolidate.sh &
        bashio::log.info "Memory consolidator started (merges /config/.brain/memory/inbox daily or at >20 pending facts)"
    else
        bashio::log.warning "Memory consolidator script not found, skipping"
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
        rm -f /config/.brain/api_endpoint.json
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

# The terminal starts in /config, explicitly.
#
# This is not cosmetic. Claude Code files every conversation under
# ~/.claude/projects/<escaped-cwd>/, and `claude --resume` (and /resume)
# only lists the ones belonging to the directory you are standing in. The
# panel's chat terminal runs in /config; if the tmux session inherits some
# other directory from the add-on's init, the two faces of the same tab keep
# their conversations in different places and neither can see the other's.
#
# The same cwd is what makes /config/CLAUDE.md load and what makes
# /config/.claude/settings.local.json the project settings — the permission
# set the whole add-on is documented as running under. Inheriting that by
# luck was never a good idea; -c says it.
CLAUDE_PROJECT_DIR="/config"

get_claude_launch_command() {
    local auto_launch_claude
    auto_launch_claude=$(bashio::config 'auto_launch_claude' 'true')
    local perms_flag
    perms_flag=$(get_permissions_flag)

    if [ "$auto_launch_claude" = "true" ]; then
        # brain-terminal-start, not claude-run directly: it checks whether the
        # chat tab has handed a conversation over and resumes it if so, then
        # execs claude-run with these same flags.
        echo "tmux new-session -A -s claude -c '${CLAUDE_PROJECT_DIR}' '/usr/local/bin/brain-terminal-start ${perms_flag}'"
    else
        if [ -f /usr/local/bin/brain-menu ]; then
            echo "tmux new-session -A -s claude-picker -c '${CLAUDE_PROJECT_DIR}' '/usr/local/bin/brain-menu'"
        else
            bashio::log.warning "Session picker not found, falling back to auto-launch"
            echo "tmux new-session -A -s claude -c '${CLAUDE_PROJECT_DIR}' '/usr/local/bin/brain-terminal-start ${perms_flag}'"
        fi
    fi
}

# ============================================================================
# Web Terminal
# ============================================================================

# The password ttyd asks for on its own port.
#
# ttyd is a shell. Anyone who reaches it gets /config read-write and a
# Claude Code already signed in to the user's account — so it is the one
# thing in this add-on that must never answer an unauthenticated request.
# Ingress authenticates its own callers, but 7681 is a plain TCP port a
# user can publish to the LAN from the add-on's Network panel, and until
# now that published port had no password at all.
#
# The credential is generated once and kept in /data (persistent, so it
# survives restarts and the terminal proxy can read it back). The panel
# forwards it upstream on every proxied request, so ingress users never
# see a login prompt — this exists for the direct port only.
setup_terminal_credential() {
    local cred_file="/data/terminal-credential"

    if [ -s "$cred_file" ]; then
        TTYD_CREDENTIAL=$(cat "$cred_file")
        return
    fi

    local password
    password=$(head -c 24 /dev/urandom | base64 | tr -d '/+=' | head -c 24)
    if [ -z "$password" ]; then
        bashio::log.error "  Terminal: could not generate a password — refusing to start ttyd unprotected"
        return 1
    fi

    TTYD_CREDENTIAL="brain:${password}"
    # 0600 root-only: the panel runs as root and is the only reader.
    (umask 077 && printf '%s' "$TTYD_CREDENTIAL" > "$cred_file")
    bashio::log.info "  Terminal: generated a password for direct access on :7681"
}

start_web_terminal() {
    local port=7681

    local enable_terminal
    enable_terminal=$(bashio::config 'enable_terminal' 'true')
    if [ "$enable_terminal" != "true" ]; then
        bashio::log.info "Terminal disabled (enable_terminal: false) — panel only"
        return
    fi

    if ! setup_terminal_credential; then
        bashio::log.error "Terminal not started (no credential)"
        return
    fi

    bashio::log.info "Starting the terminal on port ${port}..."

    bashio::log.info "Environment:"
    bashio::log.info "  CLAUDE_CONFIG_DIR=${CLAUDE_CONFIG_DIR}"
    bashio::log.info "  HOME=${HOME}"
    bashio::log.info "  HA MCP Server: $(bashio::config 'enable_ha_mcp_server' 'true')"
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

    # Backgrounded: the panel is this add-on's foreground process now, and
    # it reverse-proxies /terminal/ through to this ttyd. The cleanup trap
    # tears both down on SIGTERM.
    # --debug is libwebsockets' log mask, and ttyd's default (7) includes
    # NOTICE: three lines every time a socket opens or closes, plus one per
    # process started and killed. With the terminal tab open that is the
    # bulk of the add-on log and none of it is ever read. 3 keeps ERR and
    # WARN — the levels that mean something went wrong — and log_level:
    # debug in the add-on options turns the rest back on.
    local ttyd_debug=3
    [ "$(bashio::config 'log_level' 'info')" = "debug" ] && ttyd_debug=7

    ttyd \
        --port "${port}" \
        --interface 0.0.0.0 \
        --credential "${TTYD_CREDENTIAL}" \
        --writable \
        --debug "${ttyd_debug}" \
        --ping-interval 30 \
        --client-option enableReconnect=true \
        --client-option reconnect=10 \
        --client-option reconnectInterval=5 \
        --client-option 'fontFamily=SF Mono, Menlo, Consolas, monospace' \
        --client-option 'theme={"background":"#1a1613","foreground":"#e8ddd4","cursor":"#d97757","cursorAccent":"#1a1613","selectionBackground":"#d9775766"}' \
        "${index_arg[@]}" \
        bash -c "$launch_command" &

    TTYD_PID=$!
    bashio::log.info "  Terminal ready (proxied at /terminal/)"
    bashio::log.info "  Direct access on :${port} needs a password — see the panel's Settings, or /data/terminal-credential"
}

# ============================================================================
# Ingress Panel — the add-on's foreground process
# ============================================================================

start_panel() {
    export BRAIN_REFRESH_HOURS="$(bashio::config 'auto_refresh_hours' '24')"
    export BRAIN_HISTORY_DAYS="$(bashio::config 'history_days' '7')"
    export BRAIN_HISTORY_KEEP_RUNS="$(bashio::config 'history_keep_runs' '40')"
    export BRAIN_HISTORY_KEEP_DAYS="$(bashio::config 'history_keep_days' '30')"
    export BRAIN_MODEL="$(bashio::config 'model' '')"
    export BRAIN_TIMEOUT_MIN="$(bashio::config 'generation_timeout_minutes' '8')"
    export BRAIN_LOG_LEVEL="$(bashio::config 'log_level' 'info')"
    # One switch for "tell me everything": at debug the panel logs every
    # request again, polls included. At any other level a successful poll
    # is silent — see QuietAccessLogger.
    export BRAIN_ACCESS_LOG="$([ "$BRAIN_LOG_LEVEL" = "debug" ] && echo true || echo false)"
    export BRAIN_ENABLE_INSIGHTS="$(bashio::config 'enable_insights' 'true')"
    export BRAIN_ENABLE_TERMINAL="$(bashio::config 'enable_terminal' 'true')"
    export BRAIN_DIR="/data/insights"
    export BRAIN_HOME="/data/home"
    export BRAIN_SECRETS="/data/secrets"
    mkdir -p "$BRAIN_DIR" "$BRAIN_SECRETS"
    chmod 700 "$BRAIN_SECRETS"

    if bashio::supervisor.ping 2>/dev/null; then
        export ADDON_VERSION="$(bashio::addon.version 2>/dev/null || echo 'dev')"
    else
        export ADDON_VERSION="dev"
    fi

    bashio::log.info "Starting the panel on 0.0.0.0:8099 (ingress)"

    # Foreground via `wait` rather than `exec` so the cleanup trap still
    # fires on SIGTERM and tears down ttyd, the listeners, and the
    # consolidator with us.
    python3 /opt/panel/server.py &
    PANEL_PID=$!
    wait "$PANEL_PID"
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
    bashio::log.info "  brAIn v$(bashio::addon.version 2>/dev/null || echo '1.0.0')"
    bashio::log.info "  Your home's brain — terminal, insights, memory"
    bashio::log.info "============================================"

    run_health_check
    init_environment
    update_claude_code
    setup_claude_user
    install_tools
    install_cli_tools
    install_persistent_packages
    setup_context_generation
    cleanup_all_mcp_references
    setup_mcp_server
    start_mcp_watchdog
    setup_assist_scoping
    deploy_custom_integration
    start_usage_limits_tracker
    start_memory_consolidator
    start_study_watcher
    setup_assist_integration
    setup_automation_integration
    start_web_terminal
    start_panel
}

main "$@"
