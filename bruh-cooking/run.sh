#!/usr/bin/with-contenv bashio
# ============================================================================
# BRUH Cooking — Breville+ and Sage cooking appliances in Home Assistant and
# brAIn.
#
# The appliances are driven by the bruh_cooking integration inside Home
# Assistant Core, over Breville's cloud. This add-on is what puts that
# integration there and keeps it there: it checks brAIn is installed (BRUH
# Cooking is built to be driven by brAIn, and refuses to run without it),
# copies the integration into /config, announces it for one-click setup, and
# then watches — every WATCH_INTERVAL seconds it puts the integration back if
# it went missing, and stops if brAIn was removed.
#
# Startup order is main() at the bottom.
# ============================================================================
set -o pipefail

export COOKING_HOME="/opt/bruh-cooking"
INTEGRATION="bruh_cooking"
WATCH_INTERVAL=600

# An installed add-on is brAIn by its slug tail (the Supervisor puts the
# repository's hash, or `local_`, in front of brAIn's own `brain`) AND its
# name, so a stranger's `_brain` is not taken for it — the rule brAIn's own
# devloop uses for the BRUH add-ons (`devloop/siblings.spec_for`). Answers
# brAIn's state ("started", "stopped", …), or nothing when it is not there.
# tests/test_cooking_addon.py drives this filter through jq.
BRAIN_FILTER='[.data.addons[]? | select(((.slug // "") | test("(^|_)brain$")) and (((.name // "") | ascii_downcase) == "brain"))] | first | select(. != null) | (.state // "unknown")'

resolve_addon_version() {
    local candidate="${ADDON_VERSION:-}"
    if [ -z "${candidate}" ] || [ "${candidate}" = "{{ version }}" ] || [ "${candidate}" = "dev" ]; then
        candidate=$(sed -n 's/^version:[[:space:]]*"\{0,1\}\([^"]*\)"\{0,1\}[[:space:]]*$/\1/p' \
            "${COOKING_HOME}/config.yaml" 2>/dev/null | head -1)
    fi
    ADDON_VERSION="${candidate:-unknown}"
    export ADDON_VERSION
}

load_config() {
    ENABLE_HA_INTEGRATION=$(bashio::config 'enable_ha_integration' 'true')
    local level
    level=$(bashio::config 'log_level' 'info')
    bashio::log.level "${level}"
}

supervisor_get() {
    [ -n "${SUPERVISOR_TOKEN:-}" ] || return 0
    curl -fsS --max-time 10 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" "http://supervisor$1" 2>/dev/null || true
}

# ----------------------------------------------------------------------------
# brAIn. "I could not ask" is not "it is not there": with no Supervisor to ask
# (a local `docker run`) or an answer that would not parse, the add-on says so
# and carries on. Only an answer that was read and has no brAIn in it stops it.
# Sets BRAIN_STATE: the state, "absent", or "unknown".
# ----------------------------------------------------------------------------
read_brain_state() {
    BRAIN_STATE="unknown"
    if [ -z "${SUPERVISOR_TOKEN:-}" ]; then
        return 0
    fi
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
            bashio::log.fatal "BRUH Cooking requires brAIn, and brAIn is not installed."
            bashio::log.fatal "Install brAIn from the BRUH HA Apps repository (Settings → Apps → App store), start it, then start BRUH Cooking again."
            exit 1
            ;;
        unknown)
            bashio::log.warning "Could not ask the Supervisor whether brAIn is installed; carrying on. BRUH Cooking needs brAIn to be driven by voice and chat."
            ;;
        started)
            bashio::log.info "brAIn is installed and running"
            ;;
        *)
            bashio::log.warning "brAIn is installed but ${BRAIN_STATE}; start it so it can drive the cooking appliances."
            ;;
    esac
}

# ----------------------------------------------------------------------------
# The integration. Copied when the shipped version differs from the deployed
# one, so an update reaches Core with the add-on update and a restart of the
# add-on alone touches nothing.
# ----------------------------------------------------------------------------
deploy_custom_integration() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ]; then
        bashio::log.info "HA integration disabled; skipping custom_components deploy"
        return 0
    fi
    local src="${COOKING_HOME}/custom_components/${INTEGRATION}"
    local dst="/config/custom_components/${INTEGRATION}"
    mkdir -p /config/custom_components
    local src_ver dst_ver
    src_ver=$(jq -r '.version' "${src}/manifest.json" 2>/dev/null || echo "unknown")
    dst_ver=$(jq -r '.version' "${dst}/manifest.json" 2>/dev/null || echo "none")
    if [ "${src_ver}" != "${dst_ver}" ]; then
        bashio::log.info "Deploying ${INTEGRATION} integration (${dst_ver} -> ${src_ver}); restart Home Assistant to load it"
        rm -rf "${dst}"
        cp -a "${src}" "${dst}"
    else
        bashio::log.debug "${INTEGRATION} integration up-to-date (${src_ver})"
    fi
}

# Announce to the Supervisor so HA Core offers a one-click setup tile. The
# integration needs nothing from the add-on to reach Breville, so the config
# only names it.
announce_ha_discovery() {
    if [ "${ENABLE_HA_INTEGRATION}" != "true" ] || [ -z "${SUPERVISOR_TOKEN:-}" ]; then
        return 0
    fi
    local payload code
    payload=$(jq -nc --arg version "${ADDON_VERSION}" \
        '{service: "bruh_cooking", config: {addon: "BRUH Cooking", version: $version}}')
    code=$(curl -sS -o /dev/null -w "%{http_code}" -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" -H "Content-Type: application/json" \
        -d "${payload}" "http://supervisor/discovery" 2>/dev/null) || true
    case "${code}" in
        200|201|202) bashio::log.info "Announced bruh_cooking to the Supervisor" ;;
        *) bashio::log.debug "Discovery announce returned HTTP ${code} (non-fatal)" ;;
    esac
}

graceful_shutdown() {
    bashio::log.info "Shutdown signal received; stopping BRUH Cooking"
    [ -n "${SLEEP_PID:-}" ] && kill "${SLEEP_PID}" 2>/dev/null
    exit 0
}

watch() {
    bashio::log.info "BRUH Cooking is running; the appliances are in Home Assistant's BRUH Cooking integration and sidebar panel"
    while true; do
        sleep "${WATCH_INTERVAL}" &
        SLEEP_PID=$!
        wait "${SLEEP_PID}"
        read_brain_state
        if [ "${BRAIN_STATE}" = "absent" ]; then
            bashio::log.fatal "brAIn was removed. BRUH Cooking requires brAIn; stopping. The integration stays in Home Assistant until you remove it."
            exit 1
        fi
        deploy_custom_integration
    done
}

main() {
    resolve_addon_version
    bashio::log.info "================================================================"
    bashio::log.info " BRUH Cooking v${ADDON_VERSION} starting"
    bashio::log.info "================================================================"
    trap graceful_shutdown TERM INT

    load_config
    require_brain
    deploy_custom_integration
    announce_ha_discovery
    watch
}

main "$@"
