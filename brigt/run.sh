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
        echo "export ADDON_VERSION='${ADDON_VERSION}'"
    } > "${BRIGT_ENV_FILE}"
    chown brigt:brigt "${BRIGT_ENV_FILE}" 2>/dev/null || true
}

# ----------------------------------------------------------------------------
# /data layout, created root then handed to the brigt user the panel runs as.
# ----------------------------------------------------------------------------
prepare_filesystem() {
    mkdir -p \
        /data/shows \
        /data/cache \
        /data/calibration \
        /data/logs
    chown -R brigt:brigt /data 2>/dev/null || true
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
    payload='{"service":"brigt","config":{"panel_port":8095}}'
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
# Clean shutdown — tear down the bridge and the panel.
# ----------------------------------------------------------------------------
graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRigt"
    if [ -n "${BRIDGE_PID:-}" ]; then
        kill "${BRIDGE_PID}" 2>/dev/null || true
    fi
    if [ -n "${PANEL_PID:-}" ]; then
        kill "${PANEL_PID}" 2>/dev/null || true
    fi
    exit 0
}

# ----------------------------------------------------------------------------
# The ingress panel — the foreground process. `wait` rather than `exec` so
# the SIGTERM trap above still fires and tears the bridge down with it.
# ----------------------------------------------------------------------------
start_panel() {
    bashio::log.info "Starting BRigt panel on 0.0.0.0:8095"
    su-exec brigt python3 -u "${PANEL_DIR}/server.py" &
    PANEL_PID=$!
    wait "${PANEL_PID}"
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

    load_config
    prepare_filesystem
    deploy_custom_integration
    start_ha_bridge
    announce_ha_discovery
    start_panel
}

main "$@"
