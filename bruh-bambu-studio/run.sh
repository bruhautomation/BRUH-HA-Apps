#!/usr/bin/with-contenv bashio
# ============================================================================
# BRUH Bambu Studio — Bambu Studio in the sidebar, and the printers under HA
#
# Startup order is main() at the bottom. The panel is last because it is the
# foreground process and the ingress target. It downloads Bambu Studio on
# first start (in the background — the panel answers straight away and shows
# the progress) and keeps it running on the virtual screen.
#
# Everything after the filesystem layout runs as the `bambu` user (UID 1000).
# Nothing here opens a device or binds a privileged port, so nothing needs
# root once /data is laid out.
# ============================================================================
set -o pipefail

export BAMBU_HOME="/opt/bruh-bambu"
export PANEL_DIR="${BAMBU_HOME}/panel"
export BAMBU_DATA="/data"
export BAMBU_ENV_FILE="/data/.bruh_bambu_env"
export BAMBU_SHARED="/config/.bruh_bambu"
export BAMBU_LIBRARY="/share/bambu"
export HOME="/data/home"
export DISPLAY=":1"
# Pinned: the port lives in this container's own namespace (no host
# networking), so it cannot collide and config.yaml's watchdog can name it.
export BAMBU_PANEL_PORT=8093
export BAMBU_VNC_PORT=5900

as_bambu() {
    setpriv --reuid=1000 --regid=1000 --init-groups "$@"
}

resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] || [ "${candidate}" = "{{ version }}" ] \
       || [ "${candidate}" = "dev" ]; then
        candidate=$(python3 -c '
import yaml
try:
    with open("/opt/bruh-bambu/config.yaml") as f:
        print(yaml.safe_load(f).get("version", ""))
except Exception:
    pass
' 2>/dev/null)
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

# Options are read once and exported, into this process tree and into the
# env file — the only route an option has into a process started later
# under `with-contenv`, which reloads the s6 environment.
load_config() {
    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    INSTALL_LOVELACE_CARD=$(bashio::config 'install_lovelace_card' 'true')
    INSTALL_MORPH_CARD=$(bashio::config 'install_morph_card' 'true')
    BAMBU_STUDIO_VERSION=$(bashio::config 'bambu_studio_version' 'latest')
    BAMBU_APPIMAGE_URL=$(bashio::config 'appimage_url' '')
    SCREEN_RESOLUTION=$(bashio::config 'screen_resolution' '1600x900')
    BAMBU_LOG_LEVEL=$(bashio::config 'log_level' 'info')
    [ "${BAMBU_APPIMAGE_URL}" = "null" ] && BAMBU_APPIMAGE_URL=""
    export ENABLE_HA_INTEGRATION INSTALL_LOVELACE_CARD INSTALL_MORPH_CARD BAMBU_STUDIO_VERSION BAMBU_APPIMAGE_URL \
           SCREEN_RESOLUTION BAMBU_LOG_LEVEL
    {
        {
            echo "export BAMBU_STUDIO_VERSION='${BAMBU_STUDIO_VERSION}'"
            echo "export BAMBU_APPIMAGE_URL='${BAMBU_APPIMAGE_URL}'"
            echo "export BAMBU_LOG_LEVEL='${BAMBU_LOG_LEVEL}'"
            echo "export BAMBU_PANEL_PORT='${BAMBU_PANEL_PORT}'"
            echo "export ADDON_VERSION='${ADDON_VERSION}'"
        } > "${BAMBU_ENV_FILE}"
    } || bashio::log.warning "Could not write ${BAMBU_ENV_FILE}"
}

# /data, the shared folder and the library, created as root and handed to
# `bambu` before anything starts as that user: root can write a bambu-owned
# file and the reverse does not hold, and the failure is silent.
prepare_filesystem() {
    mkdir -p /data/home /data/secrets /data/bambu-studio /data/logs \
             "${BAMBU_SHARED}/requests" "${BAMBU_SHARED}/responses"
    chmod 700 /data/secrets
    # Not recursive over bambu-studio/: the installer already wrote it as
    # bambu, and walking 200 MB of slicer on every boot buys nothing.
    chown bambu:bambu /data /data/home /data/secrets /data/bambu-studio /data/logs
    find /data -maxdepth 1 -type f -exec chown bambu:bambu {} + 2>/dev/null || true
    chown -R bambu:bambu /data/home /data/secrets "${BAMBU_SHARED}" 2>/dev/null || true
    if mkdir -p "${BAMBU_LIBRARY}/sliced" 2>/dev/null; then
        chown bambu:bambu "${BAMBU_LIBRARY}" "${BAMBU_LIBRARY}/sliced" 2>/dev/null || true
    else
        bashio::log.warning "Could not create ${BAMBU_LIBRARY}; is /share mapped?"
    fi
    # openbox reads its config from the user's home.
    mkdir -p /data/home/.config/openbox
    cp -f "${BAMBU_HOME}/openbox-rc.xml" /data/home/.config/openbox/rc.xml
    chown -R bambu:bambu /data/home/.config
}

deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; skipping custom_components deploy"
        return 0
    fi
    local src="${BAMBU_HOME}/custom_components/bruh_bambu"
    local dst="/config/custom_components/bruh_bambu"
    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")
    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying bruh_bambu integration (${dst_ver} -> ${src_ver})"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.info "bruh_bambu integration up-to-date (${src_ver})"
    fi
}

# The printer card: one file, two hosts. /config/www is what Core serves as
# /local (the integration registers it with the frontend); Morph loads every
# file in /config/morph/cards by itself. Copied on every start, because an
# old card against a new integration is a dashboard that quietly breaks.
install_cards() {
    local src="${BAMBU_HOME}/lovelace/bruh-bambu-card.js"
    [ -f "${src}" ] || return 0
    if [ "${INSTALL_LOVELACE_CARD}" = "true" ] && mkdir -p /config/www/bruh_bambu 2>/dev/null; then
        cp -f "${src}" /config/www/bruh_bambu/bruh-bambu-card.js
        bashio::log.info "Printer card at /local/bruh_bambu/bruh-bambu-card.js"
    fi
    if [ "${INSTALL_MORPH_CARD}" = "true" ] && [ -d /config/morph ]; then
        mkdir -p /config/morph/cards
        cp -f "${src}" /config/morph/cards/bruh-bambu-printer.js
        # Morph's own user edits these files; hand it over like the rest.
        chown --reference=/config/morph /config/morph/cards/bruh-bambu-printer.js 2>/dev/null || true
        bashio::log.info "Morph printer card at /config/morph/cards (custom:morph-bambu-printer)"
    fi
}

announce_ha_discovery() {
    [ "${ENABLE_HA_INTEGRATION}" = "true" ] || return 0
    [ -n "${SUPERVISOR_TOKEN:-}" ] || return 0
    local code
    code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"service\":\"bruh_bambu\",\"config\":{\"panel_port\":${BAMBU_PANEL_PORT}}}" \
        "http://supervisor/discovery" 2>/dev/null) || true
    case "${code}" in
        200|201|202) bashio::log.info "Announced bruh_bambu to the Supervisor" ;;
        *) bashio::log.debug "Discovery announce returned HTTP ${code} (non-fatal)" ;;
    esac
}

# Keep one command running: started again two seconds after it exits. The
# X server, the window manager and the VNC server are each one of these,
# because any of them dying would otherwise leave a black panel until the
# whole add-on restarted.
keep_running() {
    local name=$1; shift
    (
        while true; do
            as_bambu "$@" >> "/data/logs/${name}.log" 2>&1
            echo "[$(date '+%H:%M:%S')] ${name} exited ($?); starting it again" \
                >> "/data/logs/${name}.log"
            sleep 2
        done
    ) &
}

# The virtual screen. Xvfb with GLX so Mesa can give Bambu Studio its
# OpenGL in software; -nolisten tcp because nothing outside this container
# draws on it. x11vnc listens on LOOPBACK only — the panel's websocket
# bridge is the one way to it, and that is behind ingress.
start_screen() {
    bashio::log.info "Starting the virtual screen (${SCREEN_RESOLUTION})"
    rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
    mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
    keep_running xvfb Xvfb :1 -screen 0 "${SCREEN_RESOLUTION}x24" \
        +extension GLX +render -noreset -nolisten tcp
    local i
    for i in $(seq 1 50); do
        [ -e /tmp/.X11-unix/X1 ] && break
        sleep 0.2
    done
    keep_running openbox openbox --config-file /data/home/.config/openbox/rc.xml
    keep_running x11vnc x11vnc -display :1 -localhost -rfbport "${BAMBU_VNC_PORT}" \
        -forever -shared -nopw -quiet -noxdamage -noxrecord -noxfixes
}

start_ha_bridge() {
    [ "${ENABLE_HA_INTEGRATION}" = "true" ] || return 0
    bashio::log.info "Starting HA file-IPC bridge"
    ( exec setpriv --reuid=1000 --regid=1000 --init-groups \
        python3 -u "${BAMBU_HOME}/integrations/ha-bridge.py" ) \
        >> /data/logs/ha-bridge.log 2>&1 &
    BRIDGE_PID=$!
}

graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRUH Bambu Studio"
    [ -n "${BRIDGE_PID:-}" ] && kill "${BRIDGE_PID}" 2>/dev/null
    [ -n "${PANEL_PID:-}" ] && kill "${PANEL_PID}" 2>/dev/null
    exit 0
}

# The panel: the ingress target, the printers' one owner, and the process
# that downloads Bambu Studio and keeps it running. `wait` rather than
# `exec` so the trap above still fires. The Supervisor's watchdog polls
# /api/health on this port.
start_panel() {
    bashio::log.info "Starting the panel on 0.0.0.0:${BAMBU_PANEL_PORT}"
    as_bambu python3 -u "${PANEL_DIR}/server.py" &
    PANEL_PID=$!
    wait "${PANEL_PID}"
    local status=$?
    [ "${status}" -ne 0 ] && bashio::log.error "Panel exited with status ${status}"
    return "${status}"
}

main() {
    resolve_addon_version
    bashio::log.info "================================================================"
    bashio::log.info " BRUH Bambu Studio v${ADDON_VERSION} starting (experimental)"
    bashio::log.info "================================================================"
    trap graceful_shutdown TERM INT
    load_config
    prepare_filesystem
    deploy_custom_integration
    install_cards
    start_screen
    start_ha_bridge
    announce_ha_discovery
    start_panel
}

main "$@"
