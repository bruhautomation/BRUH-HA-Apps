#!/usr/bin/with-contenv bashio
# ============================================================================
# BRight — music-driven light show director
#
# Startup order is main() at the bottom. The panel is last because it is the
# foreground process and the ingress target; everything else is either a
# one-shot setup step or a background daemon.
# ============================================================================
set -o pipefail

export BRIGHT_HOME="/opt/bright"
export PANEL_DIR="${BRIGHT_HOME}/panel"
export BRIGHT_STATE="/data"
export BRIGHT_ENV_FILE="/data/.bright_env"
export BRIGHT_SHARED="/config/.bright"

# ----------------------------------------------------------------------------
# Version: the ADDON_VERSION build arg is not rendered on every Supervisor
# build path, so config.yaml (baked into the image) is authoritative.
# ----------------------------------------------------------------------------
resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] \
       || [ "${candidate}" = "{{ version }}" ] \
       || [ "${candidate}" = "dev" ]; then
        if [ -r "${BRIGHT_HOME}/config.yaml" ]; then
            candidate=$(python3 -c '
import yaml
try:
    with open("/opt/bright/config.yaml") as f:
        print(yaml.safe_load(f).get("version", ""))
except Exception:
    pass
' 2>/dev/null)
        fi
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

# ----------------------------------------------------------------------------
# The panel's port is the Supervisor's to choose (config.yaml asks with
# `ingress_port: 0`, because host_network makes it a REAL host port and any
# number we pinned was a number somebody's box already had). Resolved ONCE
# here, exported into this process tree and written into /data/.bright_env, so
# the panel, the bridge and this script cannot end up talking about different
# ports. The lookup itself lives in panel/panel_port.py — one implementation,
# no shell copy of it to drift.
# ----------------------------------------------------------------------------
resolve_panel_port() {
    PANEL_PORT=$(python3 -c "
import sys
sys.path.insert(0, '${PANEL_DIR}')
import panel_port
print(panel_port.resolve())
")
    # stderr is deliberately NOT swallowed: panel_port warns there when it
    # could not reach the Supervisor and fell back, and that line is the
    # whole diagnostic if the panel later turns out to be on a port ingress
    # is not proxying to.
    #
    # No fallback number here on purpose. panel_port.resolve() already has
    # one for a machine with no Supervisor to ask; the only way this comes
    # back empty is the module not being importable, which means the panel
    # cannot start either — and a second port literal in this file is a
    # second answer that wins exactly when nobody is looking.
    if ! [ "${PANEL_PORT:-0}" -gt 0 ] 2>/dev/null; then
        bashio::log.error "Could not resolve the panel port (panel_port.py unreadable?)"
        exit 1
    fi
    export PANEL_PORT
    export BRIGHT_PANEL_PORT="${PANEL_PORT}"
}

# ----------------------------------------------------------------------------
# Options are read ONCE here and exported — both into this process tree and
# into /data/.bright_env, which is the only route an option has into any
# process started under `with-contenv` later (the shebang reloads the s6
# container environment and drops whatever we exported). Anything sourcing
# that file must source it BEFORE reading the values (see the brAIn notes on
# aliased reads freezing their fallbacks).
# ----------------------------------------------------------------------------
load_config() {
    bashio::log.info "Loading add-on configuration"

    MUSIC_FOLDER=$(bashio::config 'music_folder' '/media/music')
    DIRECTOR_MODE=$(bashio::config 'director_mode' 'auto')
    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    LOG_LEVEL=$(bashio::config 'log_level' 'info')
    export MUSIC_FOLDER DIRECTOR_MODE ENABLE_HA_INTEGRATION LOG_LEVEL

    {
        echo "export BRIGHT_MUSIC_FOLDER='${MUSIC_FOLDER}'"
        echo "export BRIGHT_DIRECTOR_MODE='${DIRECTOR_MODE}'"
        echo "export BRIGHT_ENABLE_HA_INTEGRATION='${ENABLE_HA_INTEGRATION}'"
        echo "export BRIGHT_LOG_LEVEL='${LOG_LEVEL}'"
        echo "export BRIGHT_PANEL_PORT='${PANEL_PORT}'"
        echo "export ADDON_VERSION='${ADDON_VERSION}'"
    } > "${BRIGHT_ENV_FILE}"
    chown bright:bright "${BRIGHT_ENV_FILE}" 2>/dev/null || true
}

# ----------------------------------------------------------------------------
# /data layout, created root then handed to the bright user the panel runs as.
#
# /media/bright is the same move for a different reason. The calibration click
# track has to live somewhere Home Assistant's local media source can serve
# it from — a media player fetches it over HTTP from Core, not from us — and
# that means under /media. But /media belongs to root, and the panel runs as
# `bright`: it could not create that folder, the write raised, and the wizard
# reported a bare `HTTP 500` with nothing in it about a folder. Root makes it
# here, once, and hands it over. A read-only or absent /media is a warning
# and not a failure — everything except calibration still works, and the
# panel says so in a sentence when someone presses Play.
# ----------------------------------------------------------------------------
prepare_filesystem() {
    mkdir -p \
        /data/shows \
        /data/cache \
        /data/calibration \
        /data/logs
    chown -R bright:bright /data 2>/dev/null || true

    if mkdir -p /media/bright 2>/dev/null; then
        chown bright:bright /media/bright 2>/dev/null || true
    else
        bashio::log.warning \
            "Could not create /media/bright — the Calibrate tab needs it to " \
            "share the click track with your speaker"
    fi
}

# ----------------------------------------------------------------------------
# Retire the misspelled installation.
#
# This add-on shipped as "BRigt" — a typo — through 0.8.4. The fix is a new
# slug, which means Home Assistant treats it as a different add-on: the old
# container's /data is not ours to read and there is nothing to migrate out
# of it. What IS ours is what the old add-on wrote into /config: a
# custom_components/brigt it deployed and a .brigt it shared through. Both
# are dead the moment the old add-on is uninstalled — the integration would
# load, find no add-on announcing itself, and sit there raising in the log —
# and leaving them costs a permanently broken integration entry beside a
# working one with a nearly identical name.
#
# Only the deployed copy is removed. It is a copy of files this add-on
# wrote, byte for byte; anything a person put in /config themselves is left
# exactly where it is.
# ----------------------------------------------------------------------------
retire_old_spelling() {
    local old_integration="/config/custom_components/brigt"
    local old_shared="/config/.brigt"

    if [ -d "${old_integration}" ] && [ -f "${old_integration}/manifest.json" ]; then
        if jq -e '.domain == "brigt"' "${old_integration}/manifest.json" \
               >/dev/null 2>&1; then
            bashio::log.warning \
                "Removing the old misspelled 'brigt' integration — BRigt is " \
                "now BRight. Delete its leftover entry under Settings > " \
                "Devices & Services, then set up BRight from the discovery " \
                "card."
            rm -rf "${old_integration}"
        fi
    fi

    if [ -d "${old_shared}" ]; then
        # Not deleted: the show state and any request files in there are
        # inert once the old add-on is gone, and /config is the user's.
        bashio::log.info \
            "An old ${old_shared} is still on disk from the BRigt spelling; " \
            "it is unused and safe to delete."
    fi
}

# ----------------------------------------------------------------------------
# Deploy the companion HA custom integration to /config/custom_components.
# Idempotent — copies only when the version differs from what's installed.
# The copy is recursive on purpose: it is what carries brand/ along.
# ----------------------------------------------------------------------------
deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; skipping custom_components deploy"
        return 0
    fi

    local src="${BRIGHT_HOME}/custom_components/bright"
    local dst="/config/custom_components/bright"

    if [ ! -d "${src}" ]; then
        bashio::log.warning "Custom integration source missing: ${src}"
        return 0
    fi

    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")

    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying bright integration (${dst_ver} -> ${src_ver})"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.info "bright integration up-to-date (${src_ver})"
    fi
}

# ----------------------------------------------------------------------------
# Announce the bright service to the Supervisor's /discovery endpoint so HA
# Core surfaces a one-click setup tile. 400 means "already announced".
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
    payload="{\"service\":\"bright\",\"config\":{\"panel_port\":${PANEL_PORT}}}"
    response=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "http://supervisor/discovery" 2>&1) || true

    http_code="${response: -3}"
    case "${http_code}" in
        200|201|202)
            bashio::log.info "Announced bright to the Supervisor"
            ;;
        400)
            bashio::log.debug "bright discovery already active"
            ;;
        *)
            bashio::log.debug "Discovery announce returned HTTP ${http_code} (non-fatal)"
            ;;
    esac
}

# ----------------------------------------------------------------------------
# Background file-IPC bridge for the HA integration.
# ----------------------------------------------------------------------------
start_ha_bridge() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; bridge not started"
        return 0
    fi
    bashio::log.info "Starting HA file-IPC bridge"
    mkdir -p "${BRIGHT_SHARED}/requests" "${BRIGHT_SHARED}/responses"
    chown -R bright:bright "${BRIGHT_SHARED}" 2>/dev/null || true
    (
        exec su-exec bright python3 -u "${BRIGHT_HOME}/integrations/ha-bridge.py"
    ) >> /data/logs/ha-bridge.log 2>&1 &
    BRIDGE_PID=$!
}

# ----------------------------------------------------------------------------
# Clean shutdown — tear down the watch, the bridge and the panel.
# ----------------------------------------------------------------------------
graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRight"
    if [ -n "${WATCH_PID:-}" ]; then
        kill "${WATCH_PID}" 2>/dev/null || true
    fi
    if [ -n "${BRIDGE_PID:-}" ]; then
        kill "${BRIDGE_PID}" 2>/dev/null || true
    fi
    if [ -n "${PANEL_PID:-}" ]; then
        kill "${PANEL_PID}" 2>/dev/null || true
    fi
    exit 0
}

# ----------------------------------------------------------------------------
# The health watch — what config.yaml's `watchdog:` URL used to be, moved in
# here because it is the only place that knows the port the Supervisor
# assigned. A hung panel is otherwise a dead add-on that still reads as
# started: the process is alive, so nothing exits and nothing restarts.
#
# It polls loopback, so it is unaffected by the LAN gate, and it needs FOUR
# consecutive misses before it acts — a single slow poll during a heavy
# analysis pass must not take a working add-on down. Acting means killing the
# panel, which ends the `wait` below, which ends this script and the
# container with it; the Supervisor's restart-on-stop brings it back, exactly
# as it does for a crash.
# ----------------------------------------------------------------------------
PANEL_WATCH_GRACE=60
PANEL_WATCH_INTERVAL=30
PANEL_WATCH_MISSES=4

start_health_watch() {
    (
        sleep "${PANEL_WATCH_GRACE}"
        local misses=0
        while kill -0 "${PANEL_PID}" 2>/dev/null; do
            if curl -sf -m 5 -o /dev/null \
                    "http://127.0.0.1:${PANEL_PORT}/api/health"; then
                misses=0
            else
                misses=$((misses + 1))
                bashio::log.warning \
                    "Panel did not answer /api/health (${misses}/${PANEL_WATCH_MISSES})"
                if [ "${misses}" -ge "${PANEL_WATCH_MISSES}" ]; then
                    bashio::log.error \
                        "Panel stopped answering on port ${PANEL_PORT}; restarting BRight"
                    kill "${PANEL_PID}" 2>/dev/null || true
                    return 0
                fi
            fi
            sleep "${PANEL_WATCH_INTERVAL}"
        done
    ) &
    WATCH_PID=$!
}

# ----------------------------------------------------------------------------
# The ingress panel — the foreground process. `wait` rather than `exec` so
# the SIGTERM trap above still fires and tears the bridge down with it.
# ----------------------------------------------------------------------------
start_panel() {
    bashio::log.info "Starting BRight panel on 0.0.0.0:${PANEL_PORT}"
    su-exec bright python3 -u "${PANEL_DIR}/server.py" &
    PANEL_PID=$!
    start_health_watch
    wait "${PANEL_PID}"
    PANEL_STATUS=$?
    if [ "${PANEL_STATUS}" -ne 0 ]; then
        bashio::log.error "Panel exited with status ${PANEL_STATUS}"
    fi
    return "${PANEL_STATUS}"
}

# ============================================================================
# Main
# ============================================================================
main() {
    resolve_addon_version
    bashio::log.info "================================================================"
    bashio::log.info " BRight v${ADDON_VERSION:-unknown} starting"
    bashio::log.info "================================================================"

    trap graceful_shutdown TERM INT

    resolve_panel_port
    load_config
    prepare_filesystem
    retire_old_spelling
    deploy_custom_integration
    start_ha_bridge
    announce_ha_discovery
    start_panel
}

main "$@"
