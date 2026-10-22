#!/usr/bin/with-contenv bashio
# ============================================================================
# BRUH Task Manager — CPU and memory per app, and (Level 2) per process
#
# Startup order is main() at the bottom. The panel is last because it is the
# foreground process and the ingress target.
# ============================================================================
set -o pipefail

export TASK_MANAGER_HOME="/opt/bruh-task-manager"
export PANEL_DIR="${TASK_MANAGER_HOME}/panel"
export TASK_MANAGER_SHARED="/config/.bruh_task_manager"

# Pinned: no host networking, so the port lives in this container's own
# namespace and config.yaml's watchdog can name it.
export PANEL_PORT=8103

resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] \
       || [ "${candidate}" = "{{ version }}" ] \
       || [ "${candidate}" = "dev" ]; then
        candidate=$(python3 -c '
import yaml
try:
    with open("/opt/bruh-task-manager/config.yaml") as f:
        print(yaml.safe_load(f).get("version", ""))
except Exception:
    pass
' 2>/dev/null)
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

# ----------------------------------------------------------------------------
# Options are NOT exported here. The panel reads them itself, live, from the
# Supervisor (and /data/options.json when it cannot ask), because the Level 2
# switch is pressed from the panel and must take effect without a restart.
# Only the one option this script acts on is read.
# ----------------------------------------------------------------------------
load_config() {
    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    LOG_LEVEL=$(bashio::config 'log_level' 'info')
    export TASK_MANAGER_LOG_LEVEL="${LOG_LEVEL}"
}

prepare_filesystem() {
    mkdir -p /data "${TASK_MANAGER_SHARED}" 2>/dev/null \
        || bashio::log.warning "Could not create ${TASK_MANAGER_SHARED}; the sensors will have nothing to read"
}

# ----------------------------------------------------------------------------
# Say at boot which level this run can offer. "Why do I only see apps?" is
# the question this add-on will be asked most, and the answer is one line.
# ----------------------------------------------------------------------------
report_level() {
    local process_view protected
    process_view=$(bashio::config 'process_view' 'false')
    protected=$(bashio::addon.protected 2>/dev/null || echo "unknown")
    if [ "${process_view}" != "true" ]; then
        if [ "${protected}" = "false" ]; then
            bashio::log.warning \
                "Protection mode is OFF but Level 2 is switched off, so nothing " \
                "reads the other processes. Turn Protection mode back on unless " \
                "you are about to use Level 2."
        else
            bashio::log.info "Level 1: every app, through the Supervisor's API"
        fi
        return 0
    fi
    if [ "${protected}" = "false" ]; then
        bashio::log.info "Level 2: every process on the machine"
    else
        bashio::log.warning \
            "Level 2 is switched on, but Protection mode is still ON, so this " \
            "add-on can only see its own processes. Turn Protection mode off on " \
            "the add-on's Info page and restart it."
    fi
}

deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; skipping custom_components deploy"
        return 0
    fi
    local src="${TASK_MANAGER_HOME}/custom_components/bruh_task_manager"
    local dst="/config/custom_components/bruh_task_manager"
    if [ ! -d "${src}" ]; then
        bashio::log.warning "Custom integration source missing: ${src}"
        return 0
    fi
    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")
    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying bruh_task_manager integration (${dst_ver} -> ${src_ver})"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.info "bruh_task_manager integration up-to-date (${src_ver})"
    fi
}

announce_ha_discovery() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ] || [ -z "${SUPERVISOR_TOKEN:-}" ]; then
        return 0
    fi
    local http_code
    http_code=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"service\":\"bruh_task_manager\",\"config\":{}}" \
        "http://supervisor/discovery" 2>/dev/null) || true
    case "${http_code}" in
        200|201|202) bashio::log.info "Announced bruh_task_manager to the Supervisor" ;;
        *) bashio::log.debug "Discovery announce returned HTTP ${http_code} (non-fatal)" ;;
    esac
}

graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRUH Task Manager"
    [ -n "${PANEL_PID:-}" ] && kill "${PANEL_PID}" 2>/dev/null
    exit 0
}

# ----------------------------------------------------------------------------
# The panel runs as ROOT, which is a decision: End process sends a signal to
# a process in another container, and most of those run as root, so a process
# at UID 1000 could end nothing. No port is published, ingress is
# authenticated and `panel_admin: true` means only an administrator — who
# already holds the Supervisor API — can reach it. The AppArmor profile
# beside this file denies reading other processes' secrets either way.
# ----------------------------------------------------------------------------
start_panel() {
    bashio::log.info "Starting the panel"
    python3 -u "${PANEL_DIR}/server.py" &
    PANEL_PID=$!
    wait "${PANEL_PID}"
    PANEL_STATUS=$?
    if [ "${PANEL_STATUS}" -ne 0 ]; then
        bashio::log.error "Panel exited with status ${PANEL_STATUS}"
    fi
    return "${PANEL_STATUS}"
}

main() {
    resolve_addon_version
    bashio::log.info "================================================================"
    bashio::log.info " BRUH Task Manager v${ADDON_VERSION:-unknown} starting"
    bashio::log.info "================================================================"
    trap graceful_shutdown TERM INT
    load_config
    prepare_filesystem
    report_level
    deploy_custom_integration
    announce_ha_discovery
    start_panel
}

main "$@"
