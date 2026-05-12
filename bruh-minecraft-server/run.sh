#!/usr/bin/with-contenv bashio
# ============================================================================
# BRUH Minecraft Server - startup orchestrator
# ----------------------------------------------------------------------------
# 1.  Validates the EULA
# 2.  Ensures persistent layout + permissions
# 3.  Renders server.properties + eula.txt + ops.json from add-on options
# 4.  Downloads / updates the selected server jar (paper / purpur / vanilla ...)
# 5.  Installs declared plugins
# 6.  Starts the ingress panel (aiohttp) in the background
# 7.  Starts the backup watcher in the background
# 8.  Starts the stats collector in the background
# 9.  Launches the Minecraft JVM in the foreground with auto-restart on crash
# ============================================================================

set -o pipefail

# ----------------------------------------------------------------------------
# Locations (aligned with Dockerfile ENV)
#
# 1.3.0 introduced switchable server profiles. Each profile lives under
# /config/minecraft-worlds/<name>/ with its own world, plugins, config,
# and backups. /config/minecraft and /config/minecraft-backups are
# symlinks to the active profile's dirs — keeps old scripts / docs
# working unchanged. See scripts/world-manager.sh for the CRUD CLI.
# ----------------------------------------------------------------------------
MC_WORLDS_DIR="/config/minecraft-worlds"
MC_BACKUPS_ROOT="/config/minecraft-backups"
MC_SERVER_DIR="/config/minecraft"
MC_BACKUP_DIR="/config/minecraft-backups"
MC_PANEL_STATE="/data/panel"
MC_LOG_FIFO="/tmp/mc-console.fifo"
MC_INPUT_FIFO="/tmp/mc-stdin.fifo"
MC_CONSOLE_LOG="${MC_PANEL_STATE}/console.log"
MC_STATS_FILE="${MC_PANEL_STATE}/stats.json"
MC_STATE_FILE="${MC_PANEL_STATE}/state.json"
SERVER_CACHE="/data/server-cache"
SCRIPTS_DIR="/opt/bruh-mc/scripts"
PANEL_DIR="/opt/bruh-mc/panel"
INTEGRATIONS_DIR="/opt/bruh-mc/integrations"

export MC_SERVER_DIR MC_BACKUP_DIR MC_WORLDS_DIR MC_BACKUPS_ROOT \
       MC_PANEL_STATE MC_LOG_FIFO MC_INPUT_FIFO \
       MC_CONSOLE_LOG MC_STATS_FILE MC_STATE_FILE SERVER_CACHE

# ----------------------------------------------------------------------------
# Read add-on configuration once and export to the environment for child procs
# ----------------------------------------------------------------------------
load_config() {
    bashio::log.info "Loading add-on configuration"

    ACTIVE_WORLD=$(bashio::config 'active_world' 'default')
    # Sanitize to [A-Za-z0-9_-]{1,32}; fall back to "default" if invalid.
    if ! printf '%s' "${ACTIVE_WORLD}" | grep -Eq '^[A-Za-z0-9_-]{1,32}$'; then
        bashio::log.warning "active_world '${ACTIVE_WORLD}' is invalid — falling back to 'default'"
        ACTIVE_WORLD="default"
    fi
    export ACTIVE_WORLD

    EULA=$(bashio::config 'eula' 'false')
    SERVER_TYPE=$(bashio::config 'server_type' 'paper')
    MINECRAFT_VERSION=$(bashio::config 'minecraft_version' 'LATEST')
    MOTD=$(bashio::config 'motd' 'A BRUH Minecraft Server')
    DIFFICULTY=$(bashio::config 'difficulty' 'normal')
    GAMEMODE=$(bashio::config 'gamemode' 'survival')
    MAX_PLAYERS=$(bashio::config 'max_players' '20')
    VIEW_DISTANCE=$(bashio::config 'view_distance' '10')
    SIM_DISTANCE=$(bashio::config 'simulation_distance' '10')
    ONLINE_MODE=$(bashio::config 'online_mode' 'true')
    ENFORCE_SECURE_PROFILE=$(bashio::config 'enforce_secure_profile' 'false')
    PVP=$(bashio::config 'pvp' 'true')
    HARDCORE=$(bashio::config 'hardcore' 'false')
    ALLOW_FLIGHT=$(bashio::config 'allow_flight' 'false')
    WHITE_LIST=$(bashio::config 'white_list' 'false')
    SPAWN_PROTECTION=$(bashio::config 'spawn_protection' '16')
    LEVEL_NAME=$(bashio::config 'level_name' 'world')
    LEVEL_SEED=$(bashio::config 'level_seed' '')
    LEVEL_TYPE=$(bashio::config 'level_type' 'minecraft:normal')
    ALLOW_NETHER=$(bashio::config 'allow_nether' 'true')
    GENERATE_STRUCTURES=$(bashio::config 'generate_structures' 'true')
    SPAWN_MONSTERS=$(bashio::config 'spawn_monsters' 'true')
    SPAWN_ANIMALS=$(bashio::config 'spawn_animals' 'true')
    SPAWN_NPCS=$(bashio::config 'spawn_npcs' 'true')
    PREVENT_PROXY_CONNECTIONS=$(bashio::config 'prevent_proxy_connections' 'false')
    HIDE_ONLINE_PLAYERS=$(bashio::config 'hide_online_players' 'false')
    RESOURCE_PACK=$(bashio::config 'resource_pack' '')
    RESOURCE_PACK_SHA1=$(bashio::config 'resource_pack_sha1' '')
    REQUIRE_RESOURCE_PACK=$(bashio::config 'require_resource_pack' 'false')
    MAX_WORLD_SIZE=$(bashio::config 'max_world_size' '29999984')
    NETWORK_COMPRESSION_THRESHOLD=$(bashio::config 'network_compression_threshold' '256')
    ENTITY_BROADCAST_RANGE_PERCENTAGE=$(bashio::config 'entity_broadcast_range_percentage' '100')
    MEMORY_MB=$(bashio::config 'memory_mb' '2048')
    USE_AIKAR_FLAGS=$(bashio::config 'use_aikar_flags' 'true')
    ENABLE_COMMAND_BLOCK=$(bashio::config 'enable_command_block' 'false')
    OP_PERMISSION_LEVEL=$(bashio::config 'op_permission_level' '4')
    ALLOW_CHEATS=$(bashio::config 'allow_cheats' 'false')
    # initial_ops is a list in config.yaml; flatten to newline-separated
    # names so the downstream shell scripts can iterate cleanly.
    if bashio::config.is_empty 'initial_ops'; then
        INITIAL_OPS=""
    else
        INITIAL_OPS=$(bashio::config 'initial_ops' | jq -r '.[]')
    fi
    RCON_PASSWORD_CFG=$(bashio::config 'rcon_password' '')
    AUTO_UPDATE_SERVER=$(bashio::config 'auto_update_server' 'true')
    AUTO_BACKUP=$(bashio::config 'auto_backup' 'true')
    BACKUP_INTERVAL_MINUTES=$(bashio::config 'backup_interval_minutes' '60')
    BACKUP_KEEP_COUNT=$(bashio::config 'backup_keep_count' '48')
    BACKUP_USE_GIT=$(bashio::config 'backup_use_git' 'true')
    AUTO_RESTART_ON_CRASH=$(bashio::config 'auto_restart_on_crash' 'true')
    AUTO_RESTART_SCHEDULE=$(bashio::config 'auto_restart_schedule' '')
    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    ANNOUNCE_HA_EVENTS=$(bashio::config 'announce_ha_events' 'true')
    ENABLE_BEDROCK_SUPPORT=$(bashio::config 'enable_bedrock_support' 'true')
    GEYSER_AUTH_TYPE=$(bashio::config 'geyser_auth_type' 'auto')
    GEYSER_MTU=$(bashio::config 'geyser_mtu' '1400')
    AUTO_KICK_GHOST_SESSIONS=$(bashio::config 'auto_kick_ghost_sessions' 'true')
    CONNECTION_THROTTLE_MS=$(bashio::config 'connection_throttle_ms' '4000')
    PLAYER_IDLE_TIMEOUT_MINUTES=$(bashio::config 'player_idle_timeout_minutes' '0')
    AUTO_QUARANTINE_DUPLICATES=$(bashio::config 'auto_quarantine_duplicates' 'true')
    EXTRA_JVM_ARGS=$(bashio::config 'extra_jvm_args' '')
    LOG_LEVEL=$(bashio::config 'log_level' 'info')

    # Popular-plugin checkboxes (1.4.0). Each `install_<name>` add-on option
    # becomes an `INSTALL_<NAME>` env var consumed by scripts/popular-plugins.sh.
    # Keep this list in sync with PLUGIN_SLUGS in popular-plugins.sh AND
    # the schema entries in config.yaml.
    #
    # `viaversion` and `viabackwards` default to `true` (1.5.2) — they're
    # the protocol bridges that hide the gap between a fresh Mojang
    # release and the matching Paper build (otherwise: "Outdated server!"
    # / "This server does not support Java Edition X.Y").
    for popular in essentialsx essentialsx_chat luckperms worldedit worldguard \
                   coreprotect multiverse_core griefprevention mcmmo \
                   chestsort veinminer spark; do
        var="INSTALL_$(echo "${popular}" | tr '[:lower:]' '[:upper:]')"
        # shellcheck disable=SC2034
        printf -v "${var}" '%s' "$(bashio::config "install_${popular}" 'false')"
        export "${var?}"
    done
    for popular in viaversion viabackwards; do
        var="INSTALL_$(echo "${popular}" | tr '[:lower:]' '[:upper:]')"
        # shellcheck disable=SC2034
        printf -v "${var}" '%s' "$(bashio::config "install_${popular}" 'true')"
        export "${var?}"
    done

    # Apply log level so bashio::log.debug / bashio::log.trace actually render
    case "${LOG_LEVEL}" in
        trace)   export BASHIO_LOG_LEVEL=8 ;;
        debug)   export BASHIO_LOG_LEVEL=7 ;;
        info)    export BASHIO_LOG_LEVEL=5 ;;
        notice)  export BASHIO_LOG_LEVEL=4 ;;
        warning) export BASHIO_LOG_LEVEL=3 ;;
        error)   export BASHIO_LOG_LEVEL=2 ;;
        fatal)   export BASHIO_LOG_LEVEL=1 ;;
    esac

    # NOTE: RCON password is resolved in ensure_rcon_password() AFTER
    # prepare_filesystem has created ${MC_PANEL_STATE}. Doing IO here would
    # fail on first boot (directory doesn't exist yet) and bashio's implicit
    # `set -e` kills the script silently, causing an s6 crash-restart loop.
    RCON_PASSWORD=""

    export EULA SERVER_TYPE MINECRAFT_VERSION MOTD DIFFICULTY GAMEMODE \
           MAX_PLAYERS VIEW_DISTANCE SIM_DISTANCE ONLINE_MODE \
           ENFORCE_SECURE_PROFILE PVP HARDCORE \
           ALLOW_FLIGHT WHITE_LIST SPAWN_PROTECTION LEVEL_NAME LEVEL_SEED \
           LEVEL_TYPE ALLOW_NETHER GENERATE_STRUCTURES SPAWN_MONSTERS \
           SPAWN_ANIMALS SPAWN_NPCS PREVENT_PROXY_CONNECTIONS \
           HIDE_ONLINE_PLAYERS RESOURCE_PACK RESOURCE_PACK_SHA1 \
           REQUIRE_RESOURCE_PACK MAX_WORLD_SIZE \
           NETWORK_COMPRESSION_THRESHOLD ENTITY_BROADCAST_RANGE_PERCENTAGE \
           MEMORY_MB USE_AIKAR_FLAGS ENABLE_COMMAND_BLOCK \
           OP_PERMISSION_LEVEL ALLOW_CHEATS INITIAL_OPS \
           RCON_PASSWORD RCON_PASSWORD_CFG \
           AUTO_UPDATE_SERVER AUTO_BACKUP \
           BACKUP_INTERVAL_MINUTES BACKUP_KEEP_COUNT BACKUP_USE_GIT \
           AUTO_RESTART_ON_CRASH AUTO_RESTART_SCHEDULE ENABLE_HA_INTEGRATION \
           ANNOUNCE_HA_EVENTS ENABLE_BEDROCK_SUPPORT GEYSER_AUTH_TYPE \
           GEYSER_MTU AUTO_KICK_GHOST_SESSIONS CONNECTION_THROTTLE_MS \
           PLAYER_IDLE_TIMEOUT_MINUTES \
           AUTO_QUARANTINE_DUPLICATES \
           EXTRA_JVM_ARGS LOG_LEVEL

    # HA integration — SUPERVISOR_TOKEN is injected by the Supervisor.
    # Default to empty so `set -u` doesn't abort if the runtime hasn't set it.
    export HA_TOKEN="${SUPERVISOR_TOKEN:-}"
    export HA_BASE_URL="http://supervisor/core/api"
    export SUPERVISOR_API_URL="http://supervisor"

    bashio::log.debug "Config loaded: type=${SERVER_TYPE} version=${MINECRAFT_VERSION} memory=${MEMORY_MB}MB"
}

# ----------------------------------------------------------------------------
# Resolve the RCON password *after* the panel state dir exists
# ----------------------------------------------------------------------------
ensure_rcon_password() {
    local secret_file="${MC_PANEL_STATE}/rcon.secret"

    if [ -n "${RCON_PASSWORD_CFG}" ] && [ "${RCON_PASSWORD_CFG}" != "null" ]; then
        # User supplied an explicit password — persist it
        RCON_PASSWORD="${RCON_PASSWORD_CFG}"
        printf '%s' "${RCON_PASSWORD}" > "${secret_file}"
    elif [ -s "${secret_file}" ]; then
        # Reuse the previously-generated secret
        RCON_PASSWORD=$(cat "${secret_file}")
    else
        # Generate a fresh 32-char random password
        RCON_PASSWORD=$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 32 || true)
        if [ -z "${RCON_PASSWORD}" ]; then
            # Extremely unlikely fallback — still deterministic-enough for RCON
            RCON_PASSWORD=$(date +%s%N | sha256sum | head -c 32)
        fi
        printf '%s' "${RCON_PASSWORD}" > "${secret_file}"
    fi

    chmod 600 "${secret_file}" || true
    chown minecraft:minecraft "${secret_file}" 2>/dev/null || true
    export RCON_PASSWORD
    bashio::log.info "RCON password resolved (${#RCON_PASSWORD} chars)"
}

# ----------------------------------------------------------------------------
# Hard-stop if the user has not accepted the Minecraft EULA
# ----------------------------------------------------------------------------
check_eula() {
    if [ "${EULA}" != "true" ]; then
        bashio::log.fatal "================================================================"
        bashio::log.fatal "The Minecraft EULA has NOT been accepted."
        bashio::log.fatal "Set 'eula: true' in the add-on configuration to continue."
        bashio::log.fatal "See https://www.minecraft.net/eula"
        bashio::log.fatal "================================================================"
        exit 1
    fi
    bashio::log.info "Minecraft EULA accepted"
}

# ----------------------------------------------------------------------------
# Ensure switchable-world layout under /config/minecraft-worlds/<name>/ and
# point the canonical /config/minecraft + /config/minecraft-backups symlinks
# at the active profile.
#
# Migration (1.3.0): existing users have a real /config/minecraft/ directory
# that predates the profile system. On first boot we:
#   1. mkdir -p /config/minecraft-worlds
#   2. If /config/minecraft/ is a plain directory (not a symlink), move
#      it to /config/minecraft-worlds/${ACTIVE_WORLD}/ wholesale.
#   3. Same for /config/minecraft-backups/ -> /config/minecraft-backups/
#      flattened into <active>/git + <active>/archives.
#   4. Create the /config/minecraft symlink pointing at the active profile.
#
# Subsequent boots: just ensure the symlink exists and points at the current
# active profile. Switching worlds is a matter of updating the `active_world`
# add-on option + restarting; this function handles the relinking.
# ----------------------------------------------------------------------------
ensure_worlds_layout() {
    mkdir -p "${MC_WORLDS_DIR}" "${MC_BACKUPS_ROOT}"

    local active="${ACTIVE_WORLD:-default}"
    local world_dir="${MC_WORLDS_DIR}/${active}"
    local backup_dir="${MC_BACKUPS_ROOT}/${active}"

    # --- Migration: legacy /config/minecraft/ is a real directory -----------
    if [ -d "/config/minecraft" ] && [ ! -L "/config/minecraft" ]; then
        bashio::log.notice "Migrating legacy /config/minecraft -> ${MC_WORLDS_DIR}/${active}"
        if [ -e "${world_dir}" ]; then
            bashio::log.warning "${world_dir} already exists; not overwriting. Please inspect manually."
        else
            mv "/config/minecraft" "${world_dir}"
        fi
    fi

    # --- Migration: legacy /config/minecraft-backups/ with no profile dir ---
    # Detect the old shape (direct git/ and archives/ children) and flatten
    # it into the active profile.
    if [ -d "${MC_BACKUPS_ROOT}" ] && [ ! -L "${MC_BACKUPS_ROOT}" ]; then
        if [ -d "${MC_BACKUPS_ROOT}/git" ] || [ -d "${MC_BACKUPS_ROOT}/archives" ]; then
            bashio::log.notice "Migrating legacy ${MC_BACKUPS_ROOT}/{git,archives} -> ${backup_dir}/"
            mkdir -p "${backup_dir}"
            for sub in git archives; do
                if [ -d "${MC_BACKUPS_ROOT}/${sub}" ] && [ ! -e "${backup_dir}/${sub}" ]; then
                    mv "${MC_BACKUPS_ROOT}/${sub}" "${backup_dir}/${sub}"
                fi
            done
        fi
    fi

    # Make sure the active profile's dirs exist
    mkdir -p "${world_dir}" "${backup_dir}"

    # --- Symlinks: point /config/minecraft + /config/minecraft-backups at
    # the active profile. Replace wrong-target symlinks silently.
    for pair in "/config/minecraft:${world_dir}" "/config/minecraft-backups:${backup_dir}"; do
        local link="${pair%%:*}"
        local target="${pair##*:}"
        if [ -L "${link}" ]; then
            local current
            current=$(readlink "${link}")
            if [ "${current}" != "${target}" ]; then
                bashio::log.info "Relinking ${link} -> ${target} (was ${current})"
                rm -f "${link}"
                ln -s "${target}" "${link}"
            fi
        elif [ -e "${link}" ]; then
            # Shouldn't reach here after migration — but if we do, get out
            # of the way with a loud warning rather than clobbering data.
            bashio::log.error "${link} is not a symlink but should be after migration. Refusing to overwrite."
        else
            ln -s "${target}" "${link}"
            bashio::log.info "Linked ${link} -> ${target}"
        fi
    done

    chown -R minecraft:minecraft "${MC_WORLDS_DIR}" "${MC_BACKUPS_ROOT}" 2>/dev/null || true
    bashio::log.info "Active world: ${active}  (dir: ${world_dir})"
}

# ----------------------------------------------------------------------------
# Ensure directory layout + correct ownership for the 'minecraft' user
# ----------------------------------------------------------------------------
prepare_filesystem() {
    bashio::log.info "Preparing server filesystem"

    mkdir -p \
        "${MC_SERVER_DIR}" \
        "${MC_SERVER_DIR}/plugins" \
        "${MC_SERVER_DIR}/mods" \
        "${MC_SERVER_DIR}/world" \
        "${MC_BACKUP_DIR}" \
        "${MC_PANEL_STATE}" \
        "${SERVER_CACHE}"

    : > "${MC_CONSOLE_LOG}"

    # Ensure FIFOs used for console streaming exist and are owned by minecraft
    [ -p "${MC_LOG_FIFO}" ]   || mkfifo -m 0660 "${MC_LOG_FIFO}"   2>/dev/null || true
    [ -p "${MC_INPUT_FIFO}" ] || mkfifo -m 0660 "${MC_INPUT_FIFO}" 2>/dev/null || true

    chown -R minecraft:minecraft \
        "${MC_SERVER_DIR}" \
        "${MC_BACKUP_DIR}" \
        "${MC_PANEL_STATE}" \
        "${SERVER_CACHE}" \
        "${MC_LOG_FIFO}" \
        "${MC_INPUT_FIFO}" 2>/dev/null || true

    # eula.txt lives in the server dir; we render it from config every boot
    printf 'eula=%s\n' "${EULA}" > "${MC_SERVER_DIR}/eula.txt"
}

# ----------------------------------------------------------------------------
# Write state.json so the panel can know current config without re-reading bashio
# ----------------------------------------------------------------------------
write_state() {
    local status="$1"
    python3 - <<PY
import json, os, time
state = {
    "status": "${status}",
    "server_type": os.environ["SERVER_TYPE"],
    "minecraft_version": os.environ["MINECRAFT_VERSION"],
    "motd": os.environ["MOTD"],
    "max_players": int(os.environ["MAX_PLAYERS"]),
    "memory_mb": int(os.environ["MEMORY_MB"]),
    "difficulty": os.environ["DIFFICULTY"],
    "gamemode": os.environ["GAMEMODE"],
    "hardcore": os.environ["HARDCORE"] == "true",
    "online_mode": os.environ["ONLINE_MODE"] == "true",
    "rcon_port": 25575,
    "mc_port": 25565,
    "started_at": int(time.time()),
}
with open("${MC_STATE_FILE}", "w") as f:
    json.dump(state, f, indent=2)
PY
}

# ----------------------------------------------------------------------------
# Download / update the server jar. Writes ${MC_SERVER_DIR}/server.jar
# ----------------------------------------------------------------------------
download_server_jar() {
    bashio::log.info "Resolving ${SERVER_TYPE} jar for Minecraft version '${MINECRAFT_VERSION}'"

    if "${SCRIPTS_DIR}/download-server.sh"; then
        bashio::log.info "Server jar ready: ${MC_SERVER_DIR}/server.jar"
    else
        bashio::log.error "Failed to download server jar"
        return 1
    fi
}

# ----------------------------------------------------------------------------
# Render server.properties from current config
# ----------------------------------------------------------------------------
render_server_properties() {
    bashio::log.info "Rendering server.properties"
    "${SCRIPTS_DIR}/setup-server-properties.sh"
}

# ----------------------------------------------------------------------------
# Install any plugins declared in options.plugins (Paper / Purpur only).
#
# Robustness: individual plugin download failures (bad URL, 404, timeout,
# GitHub rate-limit) MUST NOT bring the whole add-on down. Before 1.2.5,
# install-plugin.sh exited 1 on failure and bashio's implicit `set -e`
# killed run.sh mid-startup — users saw the add-on exit silently right
# after "Installing configured plugins" with no Minecraft server launch.
# Now we isolate the pipeline in a subshell and swallow per-plugin
# failures with a loud warning so the server still comes up.
# ----------------------------------------------------------------------------
install_plugins() {
    if bashio::config.is_empty 'plugins'; then
        bashio::log.debug "No plugins declared"
        return 0
    fi

    case "${SERVER_TYPE}" in
        paper|purpur|folia)
            bashio::log.info "Installing configured plugins"
            (
                # Intentionally disable pipefail here so a single failing
                # plugin can't abort the add-on. Each plugin result is
                # logged individually below.
                set +o pipefail
                local failures=0
                bashio::config 'plugins' | jq -c '.[]' | while IFS= read -r plugin; do
                    local url name entry_type
                    # Plugin entries accept two shapes:
                    #   - { url: "...", name: "..." }  — canonical object form
                    #   - "https://..."                — shorthand URL string
                    # The shorthand is common when users paste a URL into the
                    # HA Configuration tab's YAML editor without wrapping it.
                    # Before 1.2.7 this raised `jq: Cannot index string with
                    # string "url"` on every entry.
                    entry_type=$(echo "${plugin}" | jq -r 'type')
                    if [ "${entry_type}" = "string" ]; then
                        url=$(echo "${plugin}" | jq -r '.')
                        name=""
                    else
                        url=$(echo "${plugin}" | jq -r '.url // empty')
                        name=$(echo "${plugin}" | jq -r '.name // empty')
                    fi
                    if [ -z "${url}" ] || [ "${url}" = "null" ]; then
                        bashio::log.warning "Skipping plugin entry with empty URL"
                        continue
                    fi
                    bashio::log.info "Plugin: ${name:-<derived from url>} -> ${url}"
                    if ! "${SCRIPTS_DIR}/install-plugin.sh" "${url}" "${name}"; then
                        bashio::log.warning "Plugin install failed for ${url} — continuing"
                        failures=$((failures + 1))
                    fi
                done
                if [ "${failures:-0}" -gt 0 ]; then
                    bashio::log.warning "${failures} plugin(s) failed; see logs above. Server will start anyway."
                fi
            ) || bashio::log.warning "Plugin install loop returned non-zero; continuing"
            ;;
        *)
            bashio::log.warning "server_type=${SERVER_TYPE} does not support Bukkit plugins; skipping"
            ;;
    esac
    return 0
}

# ----------------------------------------------------------------------------
# Install curated popular plugins (1.4.0).
#
# The `install_<name>: true` add-on options drive scripts/popular-plugins.sh,
# which resolves each enabled plugin's latest Paper-compatible jar via the
# Modrinth API and installs through install-plugin.sh. Same per-plugin
# isolation: a single failure logs a warning and the boot continues.
#
# Skipped on Fabric/Forge/Vanilla because the curated set is Bukkit-API
# (Paper / Purpur / Folia). Mods for those platforms still go in mods/
# manually or via the Dockerfile.
# ----------------------------------------------------------------------------
install_popular_plugins() {
    case "${SERVER_TYPE}" in
        paper|purpur|folia) ;;
        *)
            bashio::log.debug "server_type=${SERVER_TYPE} doesn't support Bukkit plugins; skipping popular plugins"
            return 0
            ;;
    esac
    bashio::log.info "Resolving any enabled popular plugins"
    "${SCRIPTS_DIR}/popular-plugins.sh" \
        || bashio::log.warning "popular-plugins.sh returned non-zero (continuing)"
    return 0
}

# ----------------------------------------------------------------------------
# Auto-install Geyser + Floodgate so Bedrock clients (iOS/Android/consoles)
# can connect. See scripts/install-bedrock-support.sh for the implementation.
# ----------------------------------------------------------------------------
install_bedrock_support() {
    if [ "${ENABLE_BEDROCK_SUPPORT}" != "true" ]; then
        bashio::log.debug "Bedrock support disabled; skipping Geyser install"
        return 0
    fi
    bashio::log.info "Installing Bedrock support (Geyser + Floodgate)"
    "${SCRIPTS_DIR}/install-bedrock-support.sh" \
        || bashio::log.warning "Bedrock support install had errors (continuing)"
}

# ----------------------------------------------------------------------------
# Quarantine duplicate plugin jars so Paper doesn't log "Ambiguous plugin
# name" / "Could not load" errors on every boot. Runs AFTER plugin
# installs so we never quarantine a freshly-downloaded jar — the new
# stable version always wins over a stale -pre / -snapshot copy.
# ----------------------------------------------------------------------------
cleanup_duplicate_plugins() {
    if [ "${AUTO_QUARANTINE_DUPLICATES}" != "true" ]; then
        bashio::log.debug "Duplicate-plugin quarantine disabled; skipping"
        return 0
    fi
    PLUGINS_DIR="${MC_SERVER_DIR}/plugins" \
        python3 "${SCRIPTS_DIR}/cleanup-plugins.py" \
        || bashio::log.warning "cleanup-plugins.py returned non-zero (continuing)"
    return 0
}

# ----------------------------------------------------------------------------
# Background helpers — started before the JVM so the panel is reachable ASAP
# ----------------------------------------------------------------------------
start_ingress_panel() {
    bashio::log.info "Starting ingress panel on 0.0.0.0:8099"
    (
        cd "${PANEL_DIR}" || exit 1
        exec su-exec minecraft python3 -u "${PANEL_DIR}/server.py"
    ) >> "${MC_PANEL_STATE}/panel.log" 2>&1 &
    echo $! > "${MC_PANEL_STATE}/panel.pid"
}

start_backup_watcher() {
    if [ "${AUTO_BACKUP}" != "true" ]; then
        bashio::log.info "Auto-backup disabled"
        return 0
    fi
    bashio::log.info "Starting backup watcher (interval=${BACKUP_INTERVAL_MINUTES}m)"
    (
        exec su-exec minecraft "${SCRIPTS_DIR}/backup-watcher.sh"
    ) >> "${MC_PANEL_STATE}/backup.log" 2>&1 &
    echo $! > "${MC_PANEL_STATE}/backup.pid"
}

start_stats_collector() {
    bashio::log.info "Starting stats collector (RCON -> HA)"
    (
        exec su-exec minecraft python3 -u "${SCRIPTS_DIR}/stats-collector.py"
    ) >> "${MC_PANEL_STATE}/stats.log" 2>&1 &
    echo $! > "${MC_PANEL_STATE}/stats.pid"
}

start_ghost_watcher() {
    # Auto-kick ghost sessions so iOS Bedrock retries don't get stuck on
    # "You are already connected to this server!" See
    # scripts/ghost-session-watcher.py for the full rationale.
    if [ "${AUTO_KICK_GHOST_SESSIONS:-true}" != "true" ]; then
        bashio::log.info "auto_kick_ghost_sessions disabled; skipping watcher"
        return 0
    fi
    bashio::log.info "Starting ghost-session watcher (auto-kick duplicate-login rejects)"
    (
        exec su-exec minecraft python3 -u "${SCRIPTS_DIR}/ghost-session-watcher.py"
    ) >> "${MC_PANEL_STATE}/ghost-watcher.log" 2>&1 &
    echo $! > "${MC_PANEL_STATE}/ghost-watcher.pid"
}

start_initial_ops() {
    # Auto-OP the configured names once the JVM is actually listening on
    # RCON. The helper waits and exits on its own if there's nothing to do.
    if [ -z "${INITIAL_OPS:-}" ] && [ "${ALLOW_CHEATS:-false}" != "true" ]; then
        return 0
    fi
    bashio::log.info "Scheduling initial OP application (names='${INITIAL_OPS//$'\n'/ }')"
    (
        exec su-exec minecraft "${SCRIPTS_DIR}/apply-initial-ops.sh"
    ) >> "${MC_PANEL_STATE}/initial-ops.log" 2>&1 &
    echo $! > "${MC_PANEL_STATE}/initial-ops.pid"
}

start_ha_bridge() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; bridge not started"
        return 0
    fi
    bashio::log.info "Starting HA file-IPC bridge"
    mkdir -p /config/.bruh_minecraft/requests /config/.bruh_minecraft/responses
    chown -R minecraft:minecraft /config/.bruh_minecraft 2>/dev/null || true
    (
        exec su-exec minecraft python3 -u "/opt/bruh-mc/integrations/ha-bridge.py"
    ) >> "${MC_PANEL_STATE}/ha-bridge.log" 2>&1 &
    echo $! > "${MC_PANEL_STATE}/ha-bridge.pid"
}

# ----------------------------------------------------------------------------
# Deploy the companion HA custom integration to /config/custom_components
# Idempotent — copies only when the version differs from what's installed.
# ----------------------------------------------------------------------------
deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; skipping custom_components deploy"
        return 0
    fi

    local src="/opt/bruh-mc/custom_components/bruh_minecraft"
    local dst="/config/custom_components/bruh_minecraft"

    if [ ! -d "${src}" ]; then
        bashio::log.warning "Custom integration source missing: ${src}"
        return 0
    fi

    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")

    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying bruh_minecraft integration (${dst_ver} -> ${src_ver})"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.info "bruh_minecraft integration up-to-date (${src_ver})"
    fi
}

# ----------------------------------------------------------------------------
# Announce the bruh_minecraft service to the Supervisor's /discovery endpoint.
# HA Core sees this and surfaces a one-click "Discovered: BRUH Minecraft"
# tile on Settings → Devices & Services. Already-configured instances are
# left alone; the Supervisor dedupes by service + uuid.
# ----------------------------------------------------------------------------
announce_ha_discovery() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        return 0
    fi
    if [ -z "${SUPERVISOR_TOKEN:-}" ]; then
        bashio::log.warning "SUPERVISOR_TOKEN not set; skipping discovery announcement"
        return 0
    fi

    local payload response http_code
    payload='{"service":"bruh_minecraft","config":{"host":"homeassistant.local","port":25565}}'
    response=$(curl -sS -o /tmp/discovery-response.json -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "http://supervisor/discovery" 2>&1) || true

    http_code="${response: -3}"
    case "${http_code}" in
        200|201|202)
            bashio::log.info "Announced bruh_minecraft to Supervisor — HA should show a 1-click setup tile"
            ;;
        400)
            # Already announced — Supervisor returns 400 if the service is live
            bashio::log.debug "bruh_minecraft discovery already active (Supervisor returned 400)"
            ;;
        *)
            bashio::log.debug "Discovery announce returned HTTP ${http_code} (non-fatal)"
            ;;
    esac
    rm -f /tmp/discovery-response.json
}

# ----------------------------------------------------------------------------
# Clean shutdown — RCON-stop the server so worlds save cleanly
# ----------------------------------------------------------------------------
graceful_shutdown() {
    bashio::log.warning "Shutdown signal received; saving and stopping the server"

    if [ -f "${MC_PANEL_STATE}/server.pid" ]; then
        local pid
        pid=$(cat "${MC_PANEL_STATE}/server.pid")
        if kill -0 "${pid}" 2>/dev/null; then
            python3 "${SCRIPTS_DIR}/rcon.py" "save-all" >/dev/null 2>&1 || true
            python3 "${SCRIPTS_DIR}/rcon.py" "stop" >/dev/null 2>&1 || true
            # Wait up to 60s for clean exit
            local waited=0
            while kill -0 "${pid}" 2>/dev/null && [ "${waited}" -lt 60 ]; do
                sleep 1
                waited=$((waited + 1))
            done
            kill -0 "${pid}" 2>/dev/null && kill "${pid}" 2>/dev/null || true
        fi
    fi

    for helper in panel backup stats ha-bridge ghost-watcher initial-ops; do
        [ -f "${MC_PANEL_STATE}/${helper}.pid" ] \
            && kill "$(cat "${MC_PANEL_STATE}/${helper}.pid")" 2>/dev/null || true
    done

    write_state "stopped"
    exit 0
}
trap graceful_shutdown SIGTERM SIGINT SIGHUP

# ----------------------------------------------------------------------------
# Run the Minecraft server with auto-restart on crash
# ----------------------------------------------------------------------------
run_server_loop() {
    local max_crash_restarts=5
    local crash_window_seconds=300
    local crash_count=0
    local crash_window_start=0
    local first_iteration=1

    while true; do
        # Re-load config from /data/options.json and re-render server.properties
        # on every JVM start AFTER the first. Without this, the panel's Restart
        # button (which RCON-stops the JVM and lets this loop relaunch it)
        # would keep the previous env vars and the previous server.properties —
        # so changes made in the HA Configuration tab would only take effect on
        # a full Supervisor-level container restart. The first iteration skips
        # this work because main() already ran load_config + render_server_properties
        # right before entering the loop.
        if [ "${first_iteration}" -eq 0 ]; then
            bashio::log.info "Reloading add-on configuration for restart"
            load_config
            ensure_rcon_password
            render_server_properties
        fi
        first_iteration=0

        write_state "starting"
        bashio::log.info "Launching Minecraft server"

        # Launch server; script exits with the JVM's exit code
        su-exec minecraft "${SCRIPTS_DIR}/server-launcher.sh"
        local rc=$?

        write_state "stopped"
        bashio::log.warning "Minecraft server exited with code ${rc}"

        # Honour an explicit "no_restart" request from the panel / HA bridge.
        # The flag is cleared after we act on it so future lifecycle events work.
        if [ -f "${MC_PANEL_STATE}/no_restart" ]; then
            rm -f "${MC_PANEL_STATE}/no_restart"
            bashio::log.info "Stop requested; not restarting"
            return 0
        fi

        if [ "${AUTO_RESTART_ON_CRASH}" != "true" ]; then
            bashio::log.info "auto_restart_on_crash disabled; exiting"
            return "${rc}"
        fi

        # Clean exits (0) restart automatically — this is the code path the
        # "Restart" button uses (RCON stop = rc 0). Crashes (non-zero) also
        # restart but are rate-limited by the crash-window logic below.
        if [ "${rc}" -eq 0 ]; then
            bashio::log.info "Clean exit — restarting in 3s"
            sleep 3
            continue
        fi

        local now
        now=$(date +%s)
        if [ $((now - crash_window_start)) -gt "${crash_window_seconds}" ]; then
            crash_window_start=${now}
            crash_count=0
        fi
        crash_count=$((crash_count + 1))

        if [ "${crash_count}" -ge "${max_crash_restarts}" ]; then
            bashio::log.fatal "Server crashed ${crash_count} times in ${crash_window_seconds}s; giving up"
            return "${rc}"
        fi

        bashio::log.warning "Restarting in 10s (crash ${crash_count}/${max_crash_restarts})"
        sleep 10
    done
}

# ----------------------------------------------------------------------------
# Resolve the add-on version for the startup banner.
#
# build.yaml passes `ADDON_VERSION: "{{ version }}"` as a Docker ARG, which
# the HA Supervisor is supposed to render to the real version from
# config.yaml. Some Supervisor build paths (and most local-build flows) skip
# that Jinja rendering, leaving the literal string `{{ version }}` — which
# then shows up in the banner as "BRUH Minecraft Server v{{ version }}".
#
# The Dockerfile bakes config.yaml into /opt/bruh-mc/config.yaml, so we can
# read the authoritative version with a lightweight YAML parse. Fallback
# chain: env ARG -> config.yaml -> "unknown".
# ----------------------------------------------------------------------------
resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] \
       || [ "${candidate}" = "{{ version }}" ] \
       || [ "${candidate}" = "dev" ]; then
        if [ -r /opt/bruh-mc/config.yaml ]; then
            candidate=$(python3 -c '
import sys, yaml
try:
    with open("/opt/bruh-mc/config.yaml") as f:
        print(yaml.safe_load(f).get("version", ""))
except Exception:
    pass
' 2>/dev/null)
        fi
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

# ============================================================================
# Main
# ============================================================================
main() {
    resolve_addon_version
    bashio::log.info "================================================================"
    bashio::log.info " BRUH Minecraft Server v${ADDON_VERSION:-unknown} starting"
    bashio::log.info "================================================================"

    load_config
    check_eula
    ensure_worlds_layout
    prepare_filesystem
    ensure_rcon_password

    # Stats / panel rely on a running (or cached) jar; start them first so the
    # user can see progress even while the jar is downloading
    start_ingress_panel
    deploy_custom_integration

    if [ "${AUTO_UPDATE_SERVER}" = "true" ] || [ ! -s "${MC_SERVER_DIR}/server.jar" ]; then
        download_server_jar
    else
        bashio::log.info "Auto-update disabled; reusing existing server.jar"
    fi

    render_server_properties
    install_plugins
    install_popular_plugins
    install_bedrock_support
    cleanup_duplicate_plugins

    start_backup_watcher
    start_stats_collector
    start_ha_bridge
    start_ghost_watcher
    start_initial_ops
    announce_ha_discovery

    run_server_loop
}

main "$@"
