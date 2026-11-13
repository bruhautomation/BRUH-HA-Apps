#!/usr/bin/with-contenv bashio
# ============================================================================
# BRUH Browser — brAIn's hands on the web
#
# A real Google Chrome with the Claude in Chrome extension on a virtual
# screen, shown in the sidebar through noVNC, and a panel that runs one
# errand at a time as `claude --chrome -p` for brAIn.
#
# Startup order is main() at the bottom. The panel is last because it is the
# foreground process and the ingress target; it starts and supervises Chrome.
# Everything after the filesystem layout runs as the `browser` user (UID
# 1000). Nothing here opens a device or binds a privileged port.
# ============================================================================
set -o pipefail

export BROWSER_HOME="/opt/bruh-browser"
export PANEL_DIR="${BROWSER_HOME}/panel"
export BROWSER_DATA="/data"
export BROWSER_SHARED="/config/.bruh_browser"
export HOME="/data/home"
export DISPLAY=":1"
# Pinned: the port lives in this container's own namespace (no host
# networking), so it cannot collide, config.yaml's watchdog can name it, and
# brAIn knows where to find it.
export BROWSER_PANEL_PORT=8105
export BROWSER_VNC_PORT=5900
# Claude Code's /login opens its page through xdg-open, which honours
# $BROWSER when there is no desktop: this opens it in the Chrome on screen.
export BROWSER="${BROWSER_HOME}/open-in-chrome.sh"

# An installed add-on is brAIn by its slug tail (the Supervisor puts the
# repository's hash, or `local_`, in front of brAIn's own `brain`) AND its
# name, so a stranger's `_brain` is not taken for it — BRUH Cooking's rule
# and brAIn's own (`devloop/siblings.spec_for`). Answers brAIn's state
# ("started", "stopped", …), or nothing when it is not there.
BRAIN_FILTER='[.data.addons[]? | select(((.slug // "") | test("(^|_)brain$")) and (((.name // "") | ascii_downcase) == "brain"))] | first | select(. != null) | (.state // "unknown")'

as_browser() {
    setpriv --reuid=1000 --regid=1000 --init-groups "$@"
}

resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] || [ "${candidate}" = "{{ version }}" ] || [ "${candidate}" = "dev" ]; then
        candidate=$(sed -n 's/^version:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
            "${BROWSER_HOME}/config.yaml" 2>/dev/null | head -1)
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

# Options are read once and exported into this process tree; the panel is
# started from here and inherits them.
load_config() {
    BROWSER_MODEL=$(bashio::config 'model' 'sonnet')
    BROWSER_MAX_TURNS=$(bashio::config 'max_turns' '80')
    BROWSER_TIMEOUT_MINUTES=$(bashio::config 'task_timeout_minutes' '30')
    BROWSER_TOLERANCE_PERCENT=$(bashio::config 'purchase_tolerance_percent' '0')
    SCREEN_RESOLUTION=$(bashio::config 'screen_resolution' '1366x900')
    BROWSER_LOG_LEVEL=$(bashio::config 'log_level' 'info')
    export BROWSER_MODEL BROWSER_MAX_TURNS BROWSER_TIMEOUT_MINUTES \
           BROWSER_TOLERANCE_PERCENT SCREEN_RESOLUTION BROWSER_LOG_LEVEL
}

supervisor_get() {
    [ -n "${SUPERVISOR_TOKEN:-}" ] || return 0
    curl -fsS --max-time 10 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" "http://supervisor$1" 2>/dev/null || true
}

# ----------------------------------------------------------------------------
# brAIn. This add-on exists for brAIn and does nothing useful without it.
# "I could not ask" is not "it is not there": with no Supervisor to ask, or
# an answer that would not parse, it says so and carries on. Only an answer
# that was read and has no brAIn in it stops it.
# ----------------------------------------------------------------------------
read_brain_state() {
    BRAIN_STATE="unknown"
    [ -n "${SUPERVISOR_TOKEN:-}" ] || return 0
    local info attempt
    for attempt in 1 2 3; do
        info=$(supervisor_get /supervisor/info)
        if [ -n "${info}" ] && jq -e '.data.addons | type == "array"' <<<"${info}" >/dev/null 2>&1; then
            BRAIN_STATE=$(jq -r "${BRAIN_FILTER}" <<<"${info}" 2>/dev/null)
            BRAIN_STATE="${BRAIN_STATE:-absent}"
            return 0
        fi
        sleep "${attempt}"
    done
}

require_brain() {
    read_brain_state
    case "${BRAIN_STATE}" in
        absent)
            bashio::log.fatal "BRUH Browser requires brAIn, and brAIn is not installed."
            bashio::log.fatal "This app is brAIn's hands on the web: it runs the errands brAIn is asked for and does nothing on its own."
            bashio::log.fatal "Install brAIn from the BRUH HA Apps repository (Settings → Apps → App store), start it, then start BRUH Browser again."
            exit 1
            ;;
        unknown)
            bashio::log.warning "Could not ask the Supervisor whether brAIn is installed; carrying on. BRUH Browser is only useful with brAIn."
            ;;
        started)
            bashio::log.info "brAIn is installed and running"
            ;;
        *)
            bashio::log.warning "brAIn is installed but ${BRAIN_STATE}; start it so it can send errands here."
            ;;
    esac
}

# /data and the shared token, created as root and handed to `browser` before
# anything starts as that user.
#
# The token is what brAIn sends as a bearer token to /api/tasks. It lives in
# /config because brAIn's container has to read it, and it is owned by UID
# 1000 with mode 0600: the panel here runs as 1000, and so does brAIn's MCP
# server (Claude Code runs as its `claude` user, UID 1000), so the two
# processes that use it can and nothing else that runs unprivileged can.
prepare_filesystem() {
    mkdir -p /data/home/errands /data/run /data/logs "${BROWSER_SHARED}"
    chown browser:browser /data /data/home /data/home/errands /data/run /data/logs
    find /data -maxdepth 1 -type f -exec chown browser:browser {} + 2>/dev/null || true
    chown -R browser:browser /data/home 2>/dev/null || true
    chown browser:browser "${BROWSER_SHARED}"
    chmod 0700 "${BROWSER_SHARED}"
    local token="${BROWSER_SHARED}/api_token"
    if [ ! -s "${token}" ]; then
        head -c 48 /dev/urandom | base64 | tr -d '/+=\n' > "${token}"
        bashio::log.info "Wrote a new API token for brAIn at ${token}"
    fi
    chown browser:browser "${token}"
    chmod 0600 "${token}"
    export BROWSER_TOKEN_FILE="${token}"
    # A container restart leaves Chrome's single-instance lock behind, and a
    # Chrome that finds it refuses to start ("profile in use").
    rm -f /data/home/.config/google-chrome/Singleton{Lock,Socket,Cookie} 2>/dev/null || true
    # openbox reads its config from the user's home.
    mkdir -p /data/home/.config/openbox
    cp -f "${BROWSER_HOME}/openbox-rc.xml" /data/home/.config/openbox/rc.xml
    chown -R browser:browser /data/home/.config
}

# Keep one command running: started again two seconds after it exits. The
# X server, the window manager and the VNC server are each one of these.
keep_running() {
    local name=$1; shift
    (
        while true; do
            as_browser "$@" >> "/data/logs/${name}.log" 2>&1
            echo "[$(date '+%H:%M:%S')] ${name} exited ($?); starting it again" \
                >> "/data/logs/${name}.log"
            sleep 2
        done
    ) &
}

# The virtual screen, -nolisten tcp because nothing outside this container
# draws on it. x11vnc listens on LOOPBACK only — the panel's websocket bridge
# is the one way to it, and that is behind ingress (admin-only).
start_screen() {
    bashio::log.info "Starting the virtual screen (${SCREEN_RESOLUTION})"
    rm -f /tmp/.X1-lock /tmp/.X11-unix/X1
    mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix
    keep_running xvfb Xvfb :1 -screen 0 "${SCREEN_RESOLUTION}x24" \
        +render -noreset -nolisten tcp
    local i
    for i in $(seq 1 50); do
        [ -e /tmp/.X11-unix/X1 ] && break
        sleep 0.2
    done
    keep_running openbox openbox --config-file /data/home/.config/openbox/rc.xml
    keep_running x11vnc x11vnc -display :1 -localhost -rfbport "${BROWSER_VNC_PORT}" \
        -forever -shared -nopw -quiet -noxdamage -noxrecord -noxfixes
}

graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRUH Browser"
    [ -n "${PANEL_PID:-}" ] && kill "${PANEL_PID}" 2>/dev/null
    exit 0
}

# The panel: the ingress target, the errand queue, and the process that
# keeps Chrome running. `wait` rather than `exec` so the trap still fires.
start_panel() {
    bashio::log.info "Starting the panel on 0.0.0.0:${BROWSER_PANEL_PORT}"
    as_browser python3 -u "${PANEL_DIR}/server.py" &
    PANEL_PID=$!
    wait "${PANEL_PID}"
    local status=$?
    [ "${status}" -ne 0 ] && bashio::log.error "Panel exited with status ${status}"
    return "${status}"
}

main() {
    resolve_addon_version
    bashio::log.info "================================================================"
    bashio::log.info " BRUH Browser v${ADDON_VERSION} starting (experimental)"
    bashio::log.info "================================================================"
    trap graceful_shutdown TERM INT
    load_config
    require_brain
    prepare_filesystem
    start_screen
    start_panel
}

main "$@"
