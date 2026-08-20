#!/usr/bin/with-contenv bashio
# ============================================================================
# BRigt — music-driven light show director
#
# Startup order is main() at the bottom. The panel is last because it is the
# foreground process and the ingress target; everything else is either a
# one-shot setup step or a background daemon.
# ============================================================================
set -o pipefail

export BRIGT_HOME="/opt/brigt"
export PANEL_DIR="${BRIGT_HOME}/panel"
export BRIGT_STATE="/data"
export BRIGT_ENV_FILE="/data/.brigt_env"
export BRIGT_SHARED="/config/.brigt"

# ----------------------------------------------------------------------------
# Version: the ADDON_VERSION build arg is not rendered on every Supervisor
# build path, so config.yaml (baked into the image) is authoritative.
# ----------------------------------------------------------------------------
resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] \
       || [ "${candidate}" = "{{ version }}" ] \
       || [ "${candidate}" = "dev" ]; then
        if [ -r "${BRIGT_HOME}/config.yaml" ]; then
            candidate=$(python3 -c '
import yaml
try:
    with open("/opt/brigt/config.yaml") as f:
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
# here, exported into this process tree and written into /data/.brigt_env, so
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
    export BRIGT_PANEL_PORT="${PANEL_PORT}"
}

# ----------------------------------------------------------------------------
# Options are read ONCE here and exported — both into this process tree and
# into /data/.brigt_env, which is the only route an option has into any
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
        echo "export BRIGT_MUSIC_FOLDER='${MUSIC_FOLDER}'"
        echo "export BRIGT_DIRECTOR_MODE='${DIRECTOR_MODE}'"
        echo "export BRIGT_ENABLE_HA_INTEGRATION='${ENABLE_HA_INTEGRATION}'"
        echo "export BRIGT_LOG_LEVEL='${LOG_LEVEL}'"
        echo "export BRIGT_PANEL_PORT='${PANEL_PORT}'"
        echo "export ADDON_VERSION='${ADDON_VERSION}'"
    } > "${BRIGT_ENV_FILE}"
    chown brigt:brigt "${BRIGT_ENV_FILE}" 2>/dev/null || true
}

# ----------------------------------------------------------------------------
# /data layout, created root then handed to the brigt user the panel runs as.
#
# /media/brigt is the same move for a different reason. The calibration click
# track has to live somewhere Home Assistant's local media source can serve
# it from — a media player fetches it over HTTP from Core, not from us — and
# that means under /media. But /media belongs to root, and the panel runs as
# `brigt`: it could not create that folder, the write raised, and the wizard
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
    chown -R brigt:brigt /data 2>/dev/null || true

    if mkdir -p /media/brigt 2>/dev/null; then
        chown brigt:brigt /media/brigt 2>/dev/null || true
    else
        bashio::log.warning \
            "Could not create /media/brigt — the Calibrate tab needs it to " \
            "share the click track with your speaker"
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

    local src="${BRIGT_HOME}/custom_components/brigt"
    local dst="/config/custom_components/brigt"

    if [ ! -d "${src}" ]; then
        bashio::log.warning "Custom integration source missing: ${src}"
        return 0
    fi

    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")

    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying brigt integration (${dst_ver} -> ${src_ver})"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.info "brigt integration up-to-date (${src_ver})"
    fi
}

# ----------------------------------------------------------------------------
# Announce the brigt service to the Supervisor's /discovery endpoint so HA
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
    payload="{\"service\":\"brigt\",\"config\":{\"panel_port\":${PANEL_PORT}}}"
    response=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "http://supervisor/discovery" 2>&1) || true

    http_code="${response: -3}"
    case "${http_code}" in
        200|201|202)
            bashio::log.info "Announced brigt to the Supervisor"
            ;;
        400)
            bashio::log.debug "brigt discovery already active"
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
    mkdir -p "${BRIGT_SHARED}/requests" "${BRIGT_SHARED}/responses"
    chown -R brigt:brigt "${BRIGT_SHARED}" 2>/dev/null || true
    (
        exec su-exec brigt python3 -u "${BRIGT_HOME}/integrations/ha-bridge.py"
    ) >> /data/logs/ha-bridge.log 2>&1 &
    BRIDGE_PID=$!
}

# ----------------------------------------------------------------------------
# Clean shutdown — tear down the watch, the bridge and the panel.
# ----------------------------------------------------------------------------
graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRigt"
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
                        "Panel stopped answering on port ${PANEL_PORT}; restarting BRigt"
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
    bashio::log.info "Starting BRigt panel on 0.0.0.0:${PANEL_PORT}"
    su-exec brigt python3 -u "${PANEL_DIR}/server.py" &
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
    bashio::log.info " BRigt v${ADDON_VERSION:-unknown} starting"
    bashio::log.info "================================================================"

    trap graceful_shutdown TERM INT

    resolve_panel_port
    load_config
    prepare_filesystem
    deploy_custom_integration
    start_ha_bridge
    announce_ha_discovery
    start_panel
}

main "$@"
