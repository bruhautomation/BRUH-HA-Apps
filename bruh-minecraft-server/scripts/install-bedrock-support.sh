#!/bin/bash
# ============================================================================
# install-bedrock-support.sh
# ----------------------------------------------------------------------------
# Install Geyser + Floodgate so Minecraft Bedrock Edition clients (iOS, Android,
# Windows 10/11, Xbox, Switch, PS) can connect to our Java Edition server.
#
# * Geyser     — protocol bridge: Bedrock UDP:19132 <-> Java TCP:25565
# * Floodgate  — lets Bedrock players join without a Java (Mojang/MSFT) account
#
# Downloads the latest build straight from GeyserMC's v2 API. The API always
# redirects to the newest stable jar for the requested loader + project, so
# existing installs stay current automatically on every add-on restart.
#
# Behaviour matrix:
#   server_type=paper|purpur|folia  -> downloads the "paper" variant
#   server_type=fabric              -> downloads the "fabric" variant
#   server_type=vanilla|forge       -> not supported; logs a warning and exits 0
# ============================================================================

set -o pipefail

MC_SERVER_DIR="${MC_SERVER_DIR:-/config/minecraft}"
SERVER_TYPE="${SERVER_TYPE:-paper}"
PLUGINS_DIR="${MC_SERVER_DIR}/plugins"
MODS_DIR="${MC_SERVER_DIR}/mods"

log()  { printf '[bedrock-support] %s\n' "$*" >&2; }
warn() { printf '[bedrock-support] WARN: %s\n' "$*" >&2; }

# Map our server_type to Geyser's platform slug. Also pick the right
# destination dir (plugins/ for Bukkit-API servers, mods/ for Fabric).
case "${SERVER_TYPE}" in
    paper|purpur|folia)
        GEYSER_VARIANT="paper"
        FLOODGATE_VARIANT="paper"
        DEST_DIR="${PLUGINS_DIR}"
        ;;
    fabric)
        GEYSER_VARIANT="fabric"
        FLOODGATE_VARIANT="fabric"
        DEST_DIR="${MODS_DIR}"
        ;;
    *)
        warn "server_type=${SERVER_TYPE} doesn't support Geyser auto-install."
        warn "For vanilla/forge, run Geyser-Standalone as a separate proxy and"
        warn "disable 'enable_bedrock_support' to stop seeing this message."
        exit 0
        ;;
esac

mkdir -p "${DEST_DIR}"

install_jar() {
    local project="$1" variant="$2" filename="$3"
    local dest="${DEST_DIR}/${filename}"
    local url="https://download.geysermc.org/v2/projects/${project}/versions/latest/builds/latest/downloads/${variant}"
    local tmp="${dest}.tmp"

    log "Fetching ${project} (${variant}) -> ${filename}"
    # --remote-time + -z lets the server skip the body if we already have
    # the newest build, so restarts don't redownload unchanged plugins.
    if ! curl -fsSL --retry 3 --retry-delay 2 --remote-time \
             -z "${dest}" -o "${tmp}" "${url}"; then
        warn "download failed for ${url}"
        rm -f "${tmp}"
        return 1
    fi

    if [ -s "${tmp}" ]; then
        mv -f "${tmp}" "${dest}"
        chown minecraft:minecraft "${dest}" 2>/dev/null || true
        log "installed ${filename} ($(du -h "${dest}" | cut -f1))"
    else
        rm -f "${tmp}"
        log "${filename} already up-to-date"
    fi
}

# The two jars are named by convention so Paper picks them up automatically.
install_jar geyser    "${GEYSER_VARIANT}"    "Geyser-${GEYSER_VARIANT^}.jar" \
    || warn "Geyser install failed; Bedrock clients will not be able to connect"
install_jar floodgate "${FLOODGATE_VARIANT}" "floodgate-${FLOODGATE_VARIANT}.jar" \
    || warn "Floodgate install failed; Bedrock players will need a Java account to log in"

log "Bedrock support ready. Bedrock clients connect to this host on UDP:19132"
