#!/usr/bin/with-contenv bashio
# ============================================================================
# Morph — the dashboard brAIn designs with you
#
# main() is at the bottom. The service is last because it is the foreground
# process; everything before it is a one-shot setup step.
# ============================================================================
set -o pipefail

export MORPH_HOME="/opt/morph"
export MORPH_DATA="/data"
export MORPH_DIR="/config/morph"
export MORPH_SHARED="/config/.morph"
export MORPH_HEALTH_PORT=8096

resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] \
       || [ "${candidate}" = "{{ version }}" ] \
       || [ "${candidate}" = "dev" ]; then
        candidate=$(python3 -c '
import yaml
try:
    with open("/opt/morph/config.yaml") as f:
        print(yaml.safe_load(f).get("version", ""))
except Exception:
    pass
' 2>/dev/null)
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

load_config() {
    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    MORPH_OPT_LEARNING=$(bashio::config 'learning' 'true')
    MORPH_OPT_REPORT=$(bashio::config 'report_code_issues' 'true')
    MORPH_LOG_LEVEL=$(bashio::config 'log_level' 'info')
    export ENABLE_HA_INTEGRATION MORPH_OPT_LEARNING MORPH_OPT_REPORT MORPH_LOG_LEVEL
}

# ----------------------------------------------------------------------------
# The integration is what puts Morph in the sidebar. Deployed by version, so
# an unchanged release does not make Home Assistant ask for a restart.
# ----------------------------------------------------------------------------
deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "Integration disabled; Morph will not appear in the sidebar"
        return 0
    fi
    local src="${MORPH_HOME}/custom_components/morph"
    local dst="/config/custom_components/morph"
    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")
    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying the morph integration (${dst_ver} -> ${src_ver})"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
        if [ "${dst_ver}" != "none" ]; then
            bashio::log.warning "Restart Home Assistant to load Morph ${src_ver}"
        fi
    else
        bashio::log.info "morph integration up to date (${src_ver})"
    fi
}

announce_ha_discovery() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ] || [ -z "${SUPERVISOR_TOKEN:-}" ]; then
        return 0
    fi
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d '{"service":"morph","config":{}}' \
        "http://supervisor/discovery" 2>/dev/null) || true
    case "${code}" in
        200|201|202) bashio::log.info "Announced morph to the Supervisor" ;;
        *) bashio::log.debug "Discovery announce returned HTTP ${code} (non-fatal)" ;;
    esac
}

# ----------------------------------------------------------------------------
# The service is watched from in here (BRight's arrangement): its health
# server binds 127.0.0.1, so the Supervisor cannot reach it and a `watchdog:`
# URL would poll nothing. Four misses thirty seconds apart and the service is
# stopped, which ends the container, which the Supervisor restarts.
# ----------------------------------------------------------------------------
watch_service() {
    local misses=0
    sleep 60
    while kill -0 "${SERVICE_PID}" 2>/dev/null; do
        if curl -fsS -m 10 "http://127.0.0.1:${MORPH_HEALTH_PORT}/api/health" >/dev/null 2>&1; then
            misses=0
        else
            misses=$((misses + 1))
            if [ "${misses}" -ge 4 ]; then
                bashio::log.error "Morph's service stopped answering; restarting it"
                kill "${SERVICE_PID}" 2>/dev/null
                return
            fi
        fi
        sleep 30
    done
}

graceful_shutdown() {
    bashio::log.info "Stopping Morph"
    [ -n "${WATCH_PID:-}" ] && kill "${WATCH_PID}" 2>/dev/null
    [ -n "${SERVICE_PID:-}" ] && kill "${SERVICE_PID}" 2>/dev/null
    exit 0
}

main() {
    resolve_addon_version
    bashio::log.info "Morph v${ADDON_VERSION} starting"
    trap graceful_shutdown TERM INT
    load_config
    mkdir -p "${MORPH_SHARED}" "${MORPH_DIR}" /data
    deploy_custom_integration
    announce_ha_discovery
    python3 -u "${MORPH_HOME}/service/morphd.py" &
    SERVICE_PID=$!
    watch_service &
    WATCH_PID=$!
    wait "${SERVICE_PID}"
    local status=$?
    [ "${status}" -ne 0 ] && bashio::log.error "Morph's service exited with status ${status}"
    return "${status}"
}

main "$@"
