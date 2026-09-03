#!/usr/bin/with-contenv bashio
# ============================================================================
# BRUH Print — label designer and DYMO LabelWriter driver
#
# Startup order is main() at the bottom. The panel is last because it is the
# foreground process and the ingress target; everything before it is either a
# one-shot setup step or a background daemon.
# ============================================================================
set -o pipefail

export BRUH_PRINT_HOME="/opt/bruh-print"
export PANEL_DIR="${BRUH_PRINT_HOME}/panel"
export BRUH_PRINT_DATA="/data"
export BRUH_PRINT_ENV_FILE="/data/.bruh_print_env"
export BRUH_PRINT_SHARED="/config/.bruh_print"

# The panel's port is pinned rather than assigned. BRight has to ask the
# Supervisor because host_network makes its port a REAL host port that
# something else may own; nothing here needs host networking — a LabelWriter
# is on USB — so the port lives inside the container's own namespace, cannot
# collide with anything, and config.yaml's watchdog can name it.
export PANEL_PORT=8097
export BRUH_PRINT_PANEL_PORT="${PANEL_PORT}"

# ----------------------------------------------------------------------------
# Version: the ADDON_VERSION build arg is not rendered on every Supervisor
# build path, so config.yaml (baked into the image) is authoritative.
# ----------------------------------------------------------------------------
resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] \
       || [ "${candidate}" = "{{ version }}" ] \
       || [ "${candidate}" = "dev" ]; then
        if [ -r "${BRUH_PRINT_HOME}/config.yaml" ]; then
            candidate=$(python3 -c '
import yaml
try:
    with open("/opt/bruh-print/config.yaml") as f:
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
# into /data/.bruh_print_env, which is the only route an option has into any
# process started under `with-contenv` later (that shebang reloads the s6
# container environment and drops whatever we exported).
#
# Anything sourcing that file must source it BEFORE reading the values. An
# aliased read above the source freezes its own fallback for the life of the
# process and the real value lands afterwards under its own name with nothing
# reading it again — silently, which is how it goes unnoticed. See the brAIn
# notes on `MAX_TURNS` for the version of this bug that shipped.
# ----------------------------------------------------------------------------
load_config() {
    bashio::log.info "Loading add-on configuration"

    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    INSTALL_LOVELACE_CARD=$(bashio::config 'install_lovelace_card' 'true')
    DEFAULT_STOCK=$(bashio::config 'default_stock' 'edcc-082wh')
    ENFORCE_STOCK=$(bashio::config 'enforce_stock' 'true')
    LOG_LEVEL=$(bashio::config 'log_level' 'info')
    export ENABLE_HA_INTEGRATION INSTALL_LOVELACE_CARD DEFAULT_STOCK \
           ENFORCE_STOCK LOG_LEVEL
    # Exported under the name the panel and the bridge actually read. The
    # bashio names above are this script's; a value that only exists under a
    # local name is a setting nothing downstream can see.
    export BRUH_PRINT_LOG_LEVEL="${LOG_LEVEL}"

    # Wrapped in { } so the SHELL's own "cannot open" is redirected too —
    # `cmd >> file 2>/dev/null` hides the command's stderr, not the shell's,
    # which is how a failed write to this file goes unreported.
    {
        {
            echo "export BRUH_PRINT_ENABLE_HA_INTEGRATION='${ENABLE_HA_INTEGRATION}'"
            echo "export BRUH_PRINT_INSTALL_LOVELACE_CARD='${INSTALL_LOVELACE_CARD}'"
            echo "export BRUH_PRINT_DEFAULT_STOCK='${DEFAULT_STOCK}'"
            echo "export BRUH_PRINT_ENFORCE_STOCK='${ENFORCE_STOCK}'"
            echo "export BRUH_PRINT_LOG_LEVEL='${LOG_LEVEL}'"
            echo "export BRUH_PRINT_PANEL_PORT='${PANEL_PORT}'"
            echo "export ADDON_VERSION='${ADDON_VERSION}'"
        } > "${BRUH_PRINT_ENV_FILE}"
    } || bashio::log.warning "Could not write ${BRUH_PRINT_ENV_FILE}"
    chown bruhprint:bruhprint "${BRUH_PRINT_ENV_FILE}" 2>/dev/null || true
}

# ----------------------------------------------------------------------------
# /data layout and the shared folder, created as root and handed to the
# bruhprint user the panel runs as. Root can write a bruhprint-owned file and
# not the reverse, so the ownership has to be set before either process
# starts — the failure is otherwise silent.
# ----------------------------------------------------------------------------
prepare_filesystem() {
    mkdir -p /data/assets /data/logs

    # The shared folder is handed to the bridge's user, and /data is not:
    # the panel is root and the bridge is not, and root can write into a
    # bruhprint-owned directory where the reverse does not hold. The
    # ownership has to be set before either process starts, because the
    # failure is silent.
    mkdir -p "${BRUH_PRINT_SHARED}/requests" "${BRUH_PRINT_SHARED}/responses"
    chown -R bruhprint:bruhprint "${BRUH_PRINT_SHARED}" 2>/dev/null || true

    # The first run has no settings file, so the add-on options seed one.
    # After that the panel owns these — changing the default stock from the
    # panel must not be undone by the next restart — which is why this only
    # ever creates and never overwrites.
    if [ ! -f /data/settings.json ]; then
        local enforce="true"
        [ "${ENFORCE_STOCK}" = "true" ] || enforce="false"
        printf '{"default_stock": "%s", "enforce_stock": %s}\n' \
            "${DEFAULT_STOCK}" "${enforce}" > /data/settings.json
    fi
}

# ----------------------------------------------------------------------------
# USB: report what is actually visible, at startup, in one line.
#
# "BRUH Print cannot see my printer" is the failure this add-on will be asked
# about most, and it has three causes that look identical from the panel: the
# printer is off (a LabelWriter with no power does not enumerate at all), the
# `usb: true` permission has not been granted, or it was granted without the
# restart that makes it take effect. Saying which at boot is the cheapest
# diagnostic there is — and it costs one bus walk.
# ----------------------------------------------------------------------------
report_usb() {
    if [ ! -d /dev/bus/usb ]; then
        bashio::log.warning \
            "/dev/bus/usb is not mapped into this container, so no printer " \
            "can be reached. Enable USB access for BRUH Print in the add-on " \
            "configuration and RESTART the add-on — the Supervisor only " \
            "applies it on a restart."
        return 0
    fi
    local found
    found=$(python3 -c "
import sys
sys.path.insert(0, '${PANEL_DIR}')
from dymo import usb_link
try:
    found = usb_link.discover()
except Exception as exc:
    print(f'error: {exc}')
else:
    print('; '.join(f'{p.model.name} ({p.key})' for p in found) or 'none')
" 2>&1)
    if [ "${found}" = "none" ]; then
        bashio::log.warning \
            "No DYMO printer on the USB bus. Check the cable and the power " \
            "brick — a LabelWriter with no power does not appear at all."
    else
        bashio::log.info "USB printers: ${found}"
    fi
}

# ----------------------------------------------------------------------------
# Deploy the companion HA custom integration to /config/custom_components.
# Idempotent — copies only when the version differs from what is installed.
# The copy is recursive on purpose: it is what carries brand/ along.
# ----------------------------------------------------------------------------
deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; skipping custom_components deploy"
        return 0
    fi

    local src="${BRUH_PRINT_HOME}/custom_components/bruh_print"
    local dst="/config/custom_components/bruh_print"

    if [ ! -d "${src}" ]; then
        bashio::log.warning "Custom integration source missing: ${src}"
        return 0
    fi

    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")

    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying bruh_print integration (${dst_ver} -> ${src_ver})"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.info "bruh_print integration up-to-date (${src_ver})"
    fi
}

# ----------------------------------------------------------------------------
# The Lovelace card.
#
# A custom card is a JavaScript file the browser fetches, so it has to live
# under /config/www (served as /local/). Copying it is this function's job;
# REGISTERING it as a dashboard resource is the integration's, because
# `frontend.add_extra_js_url` is a Core call and only Core can make it — and
# doing it there means it works in storage mode and YAML mode alike, where
# editing .storage from a shell script works in neither.
#
# The copy is unconditional on version rather than skipped when the file
# exists: the card ships with the add-on and an old card against a new API is
# a dashboard that quietly stops working.
# ----------------------------------------------------------------------------
install_lovelace_card() {
    if [ "${INSTALL_LOVELACE_CARD}" != "true" ]; then
        bashio::log.info "Lovelace card install disabled"
        return 0
    fi
    local src="${BRUH_PRINT_HOME}/lovelace/bruh-print-card.js"
    local dir="/config/www/bruh_print"
    if [ ! -f "${src}" ]; then
        bashio::log.warning "Lovelace card missing from the image: ${src}"
        return 0
    fi
    if ! mkdir -p "${dir}" 2>/dev/null; then
        bashio::log.warning \
            "Could not create ${dir}; the Lovelace card was not installed."
        return 0
    fi
    cp -f "${src}" "${dir}/bruh-print-card.js"
    bashio::log.info "Lovelace card at /local/bruh_print/bruh-print-card.js"
}

# ----------------------------------------------------------------------------
# Announce to the Supervisor's /discovery endpoint so HA Core surfaces a
# one-click setup tile. 400 means "already announced".
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
    payload="{\"service\":\"bruh_print\",\"config\":{\"panel_port\":${PANEL_PORT}}}"
    response=$(curl -sS -o /dev/null -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "http://supervisor/discovery" 2>&1) || true

    http_code="${response: -3}"
    case "${http_code}" in
        200|201|202) bashio::log.info "Announced bruh_print to the Supervisor" ;;
        400) bashio::log.debug "bruh_print discovery already active" ;;
        *) bashio::log.debug "Discovery announce returned HTTP ${http_code} (non-fatal)" ;;
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
    (
        exec su-exec bruhprint python3 -u \
            "${BRUH_PRINT_HOME}/integrations/ha-bridge.py"
    ) >> /data/logs/ha-bridge.log 2>&1 &
    BRIDGE_PID=$!
}

graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRUH Print"
    [ -n "${BRIDGE_PID:-}" ] && kill "${BRIDGE_PID}" 2>/dev/null
    [ -n "${PANEL_PID:-}" ] && kill "${PANEL_PID}" 2>/dev/null
    exit 0
}

# ----------------------------------------------------------------------------
# The ingress panel — the foreground process. `wait` rather than `exec` so the
# SIGTERM trap above still fires and takes the bridge down with it.
#
# It runs as ROOT, and that is a decision rather than an oversight.
#
# There is no udev in this container. /dev/bus/usb is the HOST's device tree
# bind-mounted in, so the nodes carry the host's ownership — root:root, mode
# 0664 on every Home Assistant OS install — and a process at UID 1000 cannot
# open them for writing. Both ways round that are worse than this one:
# chmod-ing the tree at startup writes to the host's real device inodes and
# still misses any printer plugged in afterwards, because a new node arrives
# with the host's defaults and nothing in here is watching for it; and a
# setuid helper to do the bulk write is a setuid binary to get right.
#
# What it costs is bounded. No port is published, so the panel is reachable
# only through ingress — which is authenticated, and `panel_admin: true` means
# the caller is a Home Assistant ADMIN, who already holds the Supervisor API
# and can therefore already do anything root-in-a-container can. The AppArmor
# profile beside this file denies the host-escape set either way.
#
# The bridge is the other process and it stays at UID 1000: it reads request
# files written from outside this container, and it never touches USB.
# ----------------------------------------------------------------------------
start_panel() {
    bashio::log.info "Starting BRUH Print panel on 0.0.0.0:${PANEL_PORT}"
    python3 -u "${PANEL_DIR}/server.py" &
    PANEL_PID=$!
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
    bashio::log.info " BRUH Print v${ADDON_VERSION:-unknown} starting"
    bashio::log.info "================================================================"

    trap graceful_shutdown TERM INT

    load_config
    prepare_filesystem
    report_usb
    deploy_custom_integration
    install_lovelace_card
    start_ha_bridge
    announce_ha_discovery
    start_panel
}

main "$@"
