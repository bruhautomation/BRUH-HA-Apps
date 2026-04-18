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
#
# NOTES on GeyserMC's v2 API slugs (ground truth: the `downloads` keys in
# https://download.geysermc.org/v2/projects/{geyser,floodgate}/versions/latest/builds/latest):
# * Geyser:    spigot | fabric | bungeecord | velocity | neoforge | standalone | viaproxy
# * Floodgate: spigot | bungee  | velocity  | neoforge
#   -> There is NO `floodgate/fabric`. Geyser-Fabric bundles Floodgate support
#      internally, so we install Geyser only when running Fabric.
# Using "paper" was the 1.0.3 bug — it returns HTTP 404.
INSTALL_FLOODGATE=1
case "${SERVER_TYPE}" in
    paper|purpur|folia)
        GEYSER_VARIANT="spigot"
        FLOODGATE_VARIANT="spigot"
        DEST_DIR="${PLUGINS_DIR}"
        ;;
    fabric)
        GEYSER_VARIANT="fabric"
        FLOODGATE_VARIANT=""
        INSTALL_FLOODGATE=0
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

# ----------------------------------------------------------------------------
# Geyser's default auth-type is "online", which prompts every Bedrock client
# with "Please log into Xbox to join this server." Since we're shipping
# Floodgate alongside to handle Bedrock logins without a Microsoft account,
# we flip Geyser to auth-type: floodgate so iOS / Switch / etc. can join.
# Safe to re-run: idempotent and preserves the rest of the user's config.
# ----------------------------------------------------------------------------
configure_geyser_for_floodgate() {
    # Configure Geyser: auth-type=floodgate (no Xbox login) + MOTD from add-on.
    local plugin_dir="${PLUGINS_DIR}/Geyser-Spigot"
    local cfg="${plugin_dir}/config.yml"

    mkdir -p "${plugin_dir}"

    local motd="${MOTD:-A BRUH Minecraft Server}"
    local motd_sub="Powered by BRUH HA Apps"

    if [ -f "${cfg}" ]; then
        log "Geyser config exists at ${cfg} ($(stat -c '%s bytes, %y' "${cfg}" 2>/dev/null || echo '?'))"
        log "  owner: $(stat -c '%U:%G' "${cfg}" 2>/dev/null || echo '?')  mode: $(stat -c '%a' "${cfg}" 2>/dev/null || echo '?')"
        local before after
        # `|| true` so grep's non-zero "no match" exit doesn't abort under set -e.
        before=$(grep -E '^[[:space:]]*auth-type:' "${cfg}" 2>/dev/null | head -n 1 | sed 's/^[[:space:]]*//' || true)
        if [ -n "${before}" ]; then
            sed -i -E \
                's/^([[:space:]]*)auth-type:[[:space:]]*.*/\1auth-type: floodgate/' \
                "${cfg}"
            after=$(grep -E '^[[:space:]]*auth-type:' "${cfg}" 2>/dev/null | head -n 1 | sed 's/^[[:space:]]*//' || true)
            log "  - auth-type: ${before} -> ${after}"
            if [ "${after}" != "auth-type: floodgate" ]; then
                warn "  ! auth-type did NOT end up as 'floodgate' after patching!"
                warn "  ! current value: ${after}"
                warn "  ! Bedrock clients will still see 'Please log into Xbox'"
            fi
        else
            printf '\nremote:\n  auth-type: floodgate\n' >> "${cfg}"
            log "  - appended remote.auth-type: floodgate (no auth-type line was present)"
        fi

        # Patch bedrock MOTD lines (motd1 + motd2) to match the add-on motd
        local motd_escaped sub_escaped
        motd_escaped=$(printf '%s' "${motd}"     | sed -e 's/[\/&]/\\&/g')
        sub_escaped=$( printf '%s' "${motd_sub}" | sed -e 's/[\/&]/\\&/g')
        if grep -qE '^[[:space:]]*motd1:' "${cfg}"; then
            sed -i -E \
                "s/^([[:space:]]*)motd1:[[:space:]]*.*/\\1motd1: \"${motd_escaped}\"/" \
                "${cfg}"
            log "  - motd1 -> \"${motd}\""
        fi
        if grep -qE '^[[:space:]]*motd2:' "${cfg}"; then
            sed -i -E \
                "s/^([[:space:]]*)motd2:[[:space:]]*.*/\\1motd2: \"${sub_escaped}\"/" \
                "${cfg}"
            log "  - motd2 -> \"${motd_sub}\""
        fi
    else
        # Fresh install: stage a minimal file. Geyser fills in defaults for
        # every key we don't specify on first boot.
        log "Staging fresh Geyser config at ${cfg}"
        cat > "${cfg}" <<YAML
# Managed by BRUH Minecraft Server add-on.
# Bedrock clients authenticate through Floodgate — no Microsoft / Xbox
# account required to join. Edit freely; auth-type + MOTD are re-asserted
# on every add-on boot so the defaults stay consistent.
bedrock:
  motd1: "${motd}"
  motd2: "${motd_sub}"
remote:
  auth-type: floodgate
YAML
    fi

    chown -R minecraft:minecraft "${plugin_dir}" 2>/dev/null || true
}

# The jars are named by convention so the server picks them up automatically.
install_jar geyser "${GEYSER_VARIANT}" "Geyser-${GEYSER_VARIANT^}.jar" \
    || warn "Geyser install failed; Bedrock clients will not be able to connect"

if [ "${INSTALL_FLOODGATE}" = "1" ]; then
    install_jar floodgate "${FLOODGATE_VARIANT}" "floodgate-${FLOODGATE_VARIANT}.jar" \
        || warn "Floodgate install failed; Bedrock players will need a Java account to log in"
    # Only meaningful when we've installed Floodgate
    configure_geyser_for_floodgate
else
    log "Floodgate skipped — Geyser-${GEYSER_VARIANT^} includes Floodgate support natively"
fi

log "Bedrock support ready. Bedrock clients connect to this host on UDP:19132"
