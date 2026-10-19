#!/usr/bin/with-contenv bashio
# ============================================================================
# GardenRX — a spray decision engine for a home orchard and garden
#
# Startup order is main() at the bottom. Two processes run for the life of
# the add-on: the Next.js app on loopback, and the gateway on the ingress port
# in front of it. If either exits, the other is stopped and the add-on exits,
# so the Supervisor restarts the pair rather than leaving half of it up.
# ============================================================================
set -o pipefail

export GARDENRX_HOME="/opt/gardenrx"
export GARDENRX_SHARED="/config/.gardenrx"

# The ingress port is pinned (config.yaml's watchdog names it): the network is
# bridged and nothing is published, so the port lives in the container's own
# namespace and cannot collide with anything on the host.
export GARDENRX_PORT=8101
export GARDENRX_APP_PORT=3000

APP_BUILD="${GARDENRX_HOME}/app-build"
APP_DIR="${GARDENRX_HOME}/app"

resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] || [ "${candidate}" = "{{ version }}" ] || [ "${candidate}" = "dev" ]; then
        candidate=$(sed -n 's/^version:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
            "${GARDENRX_HOME}/config.yaml" 2>/dev/null | head -1)
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

load_config() {
    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    INSTALL_MORPH_CARDS=$(bashio::config 'install_morph_cards' 'true')
    USE_HA_LOCATION=$(bashio::config 'use_home_assistant_location' 'true')
    local level
    level=$(bashio::config 'log_level' 'info')
    bashio::log.level "${level}"
}

# ----------------------------------------------------------------------------
# Supervisor lookups. Each answers empty rather than failing, so the add-on
# still starts (at `/`, with its own location) on a machine with no
# Supervisor to ask — a local `docker run`, say.
# ----------------------------------------------------------------------------
supervisor_get() {
    [ -n "${SUPERVISOR_TOKEN:-}" ] || return 0
    curl -fsS --max-time 10 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" "http://supervisor$1" 2>/dev/null || true
}

resolve_ingress() {
    local info
    info=$(supervisor_get /addons/self/info)
    GARDENRX_BASE_PATH=$(jq -r '.data.ingress_entry // empty' <<<"${info}" 2>/dev/null)
    ADDON_HOSTNAME=$(jq -r '.data.hostname // empty' <<<"${info}" 2>/dev/null)
    # The app was built under a placeholder; this path goes over it. Anything
    # that is not a plain path is refused here and again in prepare-base.mjs.
    if [ -n "${GARDENRX_BASE_PATH}" ] && ! [[ "${GARDENRX_BASE_PATH}" =~ ^(/[A-Za-z0-9_.-]+)+$ ]]; then
        bashio::log.error "The Supervisor gave an ingress path GardenRX will not use: ${GARDENRX_BASE_PATH}"
        GARDENRX_BASE_PATH=""
    fi
    export GARDENRX_BASE_PATH
    bashio::log.info "Panel path: ${GARDENRX_BASE_PATH:-/}"
}

resolve_location() {
    if [ "${USE_HA_LOCATION}" != "true" ]; then
        bashio::log.info "Using GardenRX's built-in location (use_home_assistant_location is off)"
        return 0
    fi
    local cfg lat lon tz
    cfg=$(supervisor_get /core/api/config)
    lat=$(jq -r '.latitude // empty' <<<"${cfg}" 2>/dev/null)
    lon=$(jq -r '.longitude // empty' <<<"${cfg}" 2>/dev/null)
    tz=$(jq -r '.time_zone // empty' <<<"${cfg}" 2>/dev/null)
    if [ -n "${lat}" ] && [ -n "${lon}" ]; then
        export GARDENRX_LATITUDE="${lat}" GARDENRX_LONGITUDE="${lon}"
        bashio::log.info "Forecasts for Home Assistant's location"
    else
        bashio::log.warning "Could not read Home Assistant's location; using GardenRX's built-in one"
    fi
    if [ -n "${tz}" ]; then
        export GARDENRX_TIMEZONE="${tz}" TZ="${tz}"
    fi
}

# ----------------------------------------------------------------------------
# The database and the token. The database is /data/gardenrx.db — in every
# Home Assistant backup, which is why it lives there. The token is what the
# gardenrx integration sends to /api/ha/*; it lives in /config because Core
# has to read it, and it is regenerated if it goes missing.
# ----------------------------------------------------------------------------
prepare_filesystem() {
    mkdir -p /data "${GARDENRX_SHARED}"
    chown gardenrx:gardenrx /data
    chown gardenrx:gardenrx "${GARDENRX_SHARED}"
    chmod 0700 "${GARDENRX_SHARED}"
    local token="${GARDENRX_SHARED}/api_token"
    if [ ! -s "${token}" ]; then
        head -c 48 /dev/urandom | base64 | tr -d '/+=\n' > "${token}"
        bashio::log.info "Wrote a new API token for the gardenrx integration"
    fi
    chown gardenrx:gardenrx "${token}"
    chmod 0600 "${token}"
    export GARDENRX_HA_TOKEN_FILE="${token}"
    export GARDENRX_DB_PATH=/data/gardenrx.db
    export GARDENRX_CHANGELOG="${GARDENRX_HOME}/CHANGELOG.md"
}

prepare_app() {
    if ! node "${GARDENRX_HOME}/gateway/prepare-base.mjs" "${APP_BUILD}" "${APP_DIR}" "${GARDENRX_BASE_PATH}"; then
        bashio::log.fatal "Could not mount the app at ${GARDENRX_BASE_PATH:-/}"
        exit 1
    fi
    # Next writes its own cache under .next.
    chown -R gardenrx:gardenrx "${APP_DIR}"
}

deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; skipping custom_components deploy"
        return 0
    fi
    local src="${GARDENRX_HOME}/custom_components/gardenrx"
    local dst="/config/custom_components/gardenrx"
    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")
    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying gardenrx integration (${dst_ver} -> ${src_ver}); restart Home Assistant to load it"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.info "gardenrx integration up-to-date (${src_ver})"
    fi
}

# Morph loads every file in /config/morph/cards by itself. Copied on every
# start so a card update reaches Morph with the add-on update.
install_morph_cards() {
    if [ "${INSTALL_MORPH_CARDS}" != "true" ] || [ ! -d /config/morph ]; then
        return 0
    fi
    local src="${GARDENRX_HOME}/custom_components/gardenrx/frontend/gardenrx-cards.js"
    mkdir -p /config/morph/cards
    cp -f "${src}" /config/morph/cards/gardenrx.js
    chown --reference=/config/morph /config/morph/cards/gardenrx.js 2>/dev/null || true
    bashio::log.info "Morph cards at /config/morph/cards (custom:morph-gardenrx-harvest, -spray, -inventory)"
}

# Announce to the Supervisor so HA Core offers a one-click setup tile. The
# integration reaches the add-on by this hostname on the internal network.
announce_ha_discovery() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ] || [ -z "${SUPERVISOR_TOKEN:-}" ] || [ -z "${ADDON_HOSTNAME:-}" ]; then
        return 0
    fi
    local payload code
    payload=$(jq -nc --arg host "${ADDON_HOSTNAME}" --argjson port "${GARDENRX_PORT}" \
        '{service: "gardenrx", config: {host: $host, port: $port}}')
    code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" -H "Content-Type: application/json" \
        -d "${payload}" "http://supervisor/discovery" 2>/dev/null) || true
    case "${code}" in
        200|201|202) bashio::log.info "Announced gardenrx to the Supervisor" ;;
        *) bashio::log.debug "Discovery announce returned HTTP ${code} (non-fatal)" ;;
    esac
}

graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping GardenRX"
    [ -n "${GATEWAY_PID:-}" ] && kill "${GATEWAY_PID}" 2>/dev/null
    [ -n "${APP_PID:-}" ] && kill "${APP_PID}" 2>/dev/null
    exit 0
}

start() {
    bashio::log.info "Starting GardenRX"
    (
        cd "${APP_DIR}" || exit 1
        exec su-exec gardenrx env HOSTNAME=127.0.0.1 PORT="${GARDENRX_APP_PORT}" \
            node --disable-warning=ExperimentalWarning server.js
    ) &
    APP_PID=$!
    su-exec gardenrx node "${GARDENRX_HOME}/gateway/gateway.mjs" &
    GATEWAY_PID=$!

    # Whichever exits first takes the other down: a gateway with no app behind
    # it answers every request with a 502, and an app with no gateway is
    # unreachable, and either is better restarted whole.
    wait -n "${APP_PID}" "${GATEWAY_PID}"
    local status=$?
    bashio::log.error "GardenRX stopped (status ${status}); exiting so the Supervisor restarts it"
    kill "${APP_PID}" "${GATEWAY_PID}" 2>/dev/null
    exit 1
}

main() {
    resolve_addon_version
    bashio::log.info "================================================================"
    bashio::log.info " GardenRX v${ADDON_VERSION} starting"
    bashio::log.info "================================================================"
    trap graceful_shutdown TERM INT

    load_config
    resolve_ingress
    resolve_location
    prepare_filesystem
    prepare_app
    deploy_custom_integration
    install_morph_cards
    announce_ha_discovery
    start
}

main "$@"
