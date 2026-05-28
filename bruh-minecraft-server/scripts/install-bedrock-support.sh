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
# Resolve our own directory so we can invoke sibling helpers (patch-geyser-config.py).
# BRUH_MC_SCRIPTS_DIR is an escape hatch used by the test harness when the
# script is run via `bash -c "<source>"` (in which case $0 = "bash" and the
# cd-dirname trick resolves to the CWD instead of the real scripts dir).
SCRIPT_DIR="${BRUH_MC_SCRIPTS_DIR:-$(cd "$(dirname "${0}")" 2>/dev/null && pwd)}"
SCRIPT_DIR="${SCRIPT_DIR:-/opt/bruh-mc/scripts}"

log()  { printf '[bedrock-support] %s\n' "$*" >&2; }
warn() { printf '[bedrock-support] WARN: %s\n' "$*" >&2; }

# Read a key from the ACTIVE world's server.properties (gameplay settings are
# per-world now — online-mode and motd are no longer add-on env vars). Prints
# the value, or the supplied default when the key/file is absent.
read_prop() {
    local key="$1" default="${2:-}" line
    line=$(grep -E "^${key}=" "${MC_SERVER_DIR}/server.properties" 2>/dev/null | head -n 1 || true)
    if [ -n "${line}" ]; then
        printf '%s' "${line#*=}"
    else
        printf '%s' "${default}"
    fi
}

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

# Resolve the requested auth-type up-front so we know whether to include
# Floodgate. **When auth-type=offline we MUST NOT install Floodgate** —
# Geyser delegates auth to Floodgate whenever it's loaded, and Floodgate
# requires every Bedrock client to have an Xbox XUID. That's the exact
# "Please log into Xbox to join this server." kick users hit even after
# patching the Geyser config to auth-type: offline. See DOCS #troubleshooting.
resolve_auth_type() {
    local requested="${GEYSER_AUTH_TYPE:-auto}"
    case "${requested}" in
        floodgate|online|offline)
            printf '%s' "${requested}"
            ;;
        *)
            # "auto" and any bogus value fall through to the inference path,
            # keyed off the active world's online-mode (per-world setting).
            if [ "$(read_prop online-mode true)" = "true" ]; then
                printf 'floodgate'
            else
                printf 'offline'
            fi
            ;;
    esac
}

AUTH_TYPE=$(resolve_auth_type)
if [ "${AUTH_TYPE}" = "offline" ]; then
    INSTALL_FLOODGATE=0
fi

mkdir -p "${DEST_DIR}"

# Remove any previously-installed Floodgate jar when we're in offline mode.
# Leaving it in place would re-trigger the Xbox-login kick on the next boot
# because Geyser still routes auth through Floodgate whenever the jar is
# present, irrespective of auth-type. Match both Spigot + Fabric naming.
remove_floodgate_jar_if_present() {
    local removed=0
    shopt -s nullglob
    for f in "${PLUGINS_DIR}"/floodgate-*.jar "${MODS_DIR}"/floodgate-*.jar; do
        [ -f "${f}" ] || continue
        log "Removing stale Floodgate jar for offline auth: ${f}"
        rm -f "${f}" && removed=1
    done
    shopt -u nullglob
    return ${removed}
}
if [ "${INSTALL_FLOODGATE}" = "0" ] && [ "${AUTH_TYPE}" = "offline" ]; then
    remove_floodgate_jar_if_present || true
fi

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
# with "Please log into Xbox to join this server." We patch the value based
# on $GEYSER_AUTH_TYPE (already resolved to $AUTH_TYPE at the top of the
# script). Safe to re-run: idempotent and preserves the rest of the user's
# config.
# ----------------------------------------------------------------------------
configure_geyser() {
    # Configure Geyser auth-type + MOTD from add-on options.
    local plugin_dir="${PLUGINS_DIR}/Geyser-Spigot"
    local cfg="${plugin_dir}/config.yml"
    local auth_type="${AUTH_TYPE:-$(resolve_auth_type)}"

    mkdir -p "${plugin_dir}"

    local motd
    motd="$(read_prop motd 'A BRUH Minecraft Server')"
    local motd_sub="Powered by BRUH HA Apps"

    log "Resolved Geyser auth-type: ${auth_type} (requested='${GEYSER_AUTH_TYPE:-auto}', online-mode='$(read_prop online-mode true)')"

    if [ -f "${cfg}" ]; then
        log "Geyser config exists at ${cfg} ($(stat -c '%s bytes, %y' "${cfg}" 2>/dev/null || echo '?'))"
        log "  owner: $(stat -c '%U:%G' "${cfg}" 2>/dev/null || echo '?')  mode: $(stat -c '%a' "${cfg}" 2>/dev/null || echo '?')"
        local before after
        # `|| true` so grep's non-zero "no match" exit doesn't abort under set -e.
        before=$(grep -E '^[[:space:]]*auth-type:' "${cfg}" 2>/dev/null | head -n 1 | sed 's/^[[:space:]]*//' || true)
        if [ -n "${before}" ]; then
            sed -i -E \
                "s/^([[:space:]]*)auth-type:[[:space:]]*.*/\\1auth-type: ${auth_type}/" \
                "${cfg}"
            after=$(grep -E '^[[:space:]]*auth-type:' "${cfg}" 2>/dev/null | head -n 1 | sed 's/^[[:space:]]*//' || true)
            log "  - auth-type: ${before} -> ${after}"
            if [ "${after}" != "auth-type: ${auth_type}" ]; then
                warn "  ! auth-type did NOT end up as '${auth_type}' after patching!"
                warn "  ! current value: ${after}"
                warn "  ! Bedrock clients may still see 'Please log into Xbox'"
            fi
        else
            printf '\nremote:\n  auth-type: %s\n' "${auth_type}" >> "${cfg}"
            log "  - appended remote.auth-type: ${auth_type} (no auth-type line was present)"
        fi

        # The REAL fix for "Please log into Xbox to join this server.":
        # Geyser validates the Bedrock client's signed Xbox Live JWT chain
        # in LoginEncryptionUtils.encryptConnectionWithCert() *before* any
        # auth-type / Floodgate logic runs. The gate is
        # `advanced.bedrock.validate-bedrock-login` (default true). When
        # it's true and the client's chain is unsigned (LAN devices,
        # cracked clients, family Bedrock with no Xbox session), Geyser
        # kicks with the exact message we've been chasing — regardless of
        # auth-type. We flip this key to false in offline mode, and
        # restore the secure default (true) in online / floodgate modes.
        local want_validate
        if [ "${auth_type}" = "offline" ]; then
            want_validate="false"
        else
            want_validate="true"
        fi
        if python3 "${SCRIPT_DIR}/patch-geyser-config.py" \
               "${cfg}" validate-bedrock-login "${want_validate}" advanced.bedrock; then
            log "  - advanced.bedrock.validate-bedrock-login: ${want_validate}"
        else
            warn "  ! failed to patch validate-bedrock-login"
        fi

        # MTU tuning: lowering from 1400 -> 1200 is the #1 fix for the iOS
        # "Connecting multiplayer server..." hang. Wi-Fi routers + cellular
        # hot-spots commonly fragment UDP at ~1400 and RakNet's login
        # handshake silently stalls. Expose as an add-on option so users
        # can dial it down when LAN pings work but joins hang.
        local want_mtu="${GEYSER_MTU:-1400}"
        if python3 "${SCRIPT_DIR}/patch-geyser-config.py" \
               "${cfg}" mtu "${want_mtu}" advanced; then
            log "  - advanced.mtu: ${want_mtu}"
        else
            warn "  ! failed to patch advanced.mtu"
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
        local fresh_validate
        if [ "${auth_type}" = "offline" ]; then
            fresh_validate="false"
        else
            fresh_validate="true"
        fi
        local fresh_mtu="${GEYSER_MTU:-1400}"
        log "Staging fresh Geyser config at ${cfg} (auth-type: ${auth_type}, validate-bedrock-login: ${fresh_validate}, mtu: ${fresh_mtu})"
        cat > "${cfg}" <<YAML
# Managed by BRUH Minecraft Server add-on.
# auth-type, validate-bedrock-login, and mtu are re-asserted on every
# add-on boot from the add-on options. See the README / DOCS for the
# tradeoffs between floodgate / offline / online. Every other key here
# is free for you to edit — Geyser fills in defaults for anything we
# haven't set.
bedrock:
  motd1: "${motd}"
  motd2: "${motd_sub}"
remote:
  auth-type: ${auth_type}
advanced:
  # Lower from 1400 to 1200 if iOS clients hang on "Connecting
  # multiplayer server…" — Wi-Fi routers often fragment UDP at 1400.
  mtu: ${fresh_mtu}
  bedrock:
    # When false, Geyser skips validating the Bedrock client's signed
    # Xbox Live JWT chain — required so family LAN / cracked clients
    # can join a server with auth-type: offline.
    validate-bedrock-login: ${fresh_validate}
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
else
    if [ "${AUTH_TYPE}" = "offline" ]; then
        log "Floodgate NOT installed (auth-type=offline) — Bedrock clients join without any Xbox sign-in"
    elif [ "${SERVER_TYPE}" = "fabric" ]; then
        log "Floodgate skipped — Geyser-${GEYSER_VARIANT^} includes Floodgate support natively"
    fi
fi

# Configure Geyser config on every boot regardless of Floodgate presence —
# that's where auth-type lives, and it needs to match what the user asked
# for even when we didn't touch the Floodgate jar.
configure_geyser

log "Bedrock support ready. Bedrock clients connect to this host on UDP:19132"
