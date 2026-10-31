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

# Read a key from the ACTIVE world's server.properties and undo Java's
# Properties.store() escaping (Minecraft re-saves the file on shutdown using
# that format, which writes `:` as `\:`, `§a` for color codes, etc.).
# Without the unescape, Geyser's MOTD would show a literal `§a` to
# Bedrock players instead of the color code, and any motd with a `:` would
# include a stray backslash.
read_prop() {
    local key="$1" default="${2:-}" line raw
    line=$(grep -E "^${key}=" "${MC_SERVER_DIR}/server.properties" 2>/dev/null | head -n 1 || true)
    if [ -z "${line}" ]; then
        printf '%s' "${default}"
        return
    fi
    raw="${line#*=}"
    # Fast path: no escapes, return as-is.
    case "${raw}" in
        *\\*) ;;
        *) printf '%s' "${raw}"; return ;;
    esac
    # Delegate to Python for proper Java-properties unescape (handles \:,
    # \=, \#, \!, \\, \n, \t, \r, and \uXXXX). Bash's parameter expansion
    # can't do the unicode case cleanly.
    python3 -c '
import sys
def unesc(v):
    out = []; i = 0
    while i < len(v):
        c = v[i]
        if c != "\\" or i + 1 >= len(v):
            out.append(c); i += 1; continue
        n = v[i + 1]
        if n in ":=# !\\": out.append(n); i += 2
        elif n == "n": out.append("\n"); i += 2
        elif n == "t": out.append("\t"); i += 2
        elif n == "r": out.append("\r"); i += 2
        elif n == "u" and i + 5 < len(v):
            try: out.append(chr(int(v[i+2:i+6], 16))); i += 6
            except ValueError: out.append(c); i += 1
        else: out.append(c); i += 1
    return "".join(out)
sys.stdout.write(unesc(sys.argv[1]))
' "${raw}"
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
    local requested="${BRUH_GEYSER_AUTH_TYPE:-auto}"
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
# with "Please log into Xbox to join this server." We write the value from
# $BRUH_GEYSER_AUTH_TYPE (already resolved to $AUTH_TYPE at the top of the
# script), the MTU from $BRUH_GEYSER_MTU, validate-bedrock-login and the
# MOTD into Geyser's config.yml, in whichever layout it is (Geyser 2.9 moved
# `remote.auth-type` to `java.auth-type` and `mtu` under `advanced.bedrock`;
# patch-geyser-config.py --managed knows both). The file is the ONLY place
# they are set: Geyser reads every `GEYSER_*` environment variable as an
# override and warns "does not match any config option" about each one
# that is not, which is what GEYSER_AUTH_TYPE and GEYSER_MTU did up to
# 1.17.7 — hence the BRUH_ prefix, which Geyser ignores. Safe to re-run:
# idempotent and preserves the rest of the user's config.
# ----------------------------------------------------------------------------
configure_geyser() {
    local plugin_dir="${PLUGINS_DIR}/Geyser-Spigot"
    local cfg="${plugin_dir}/config.yml"
    local auth_type="${AUTH_TYPE:-$(resolve_auth_type)}"
    local mtu="${BRUH_GEYSER_MTU:-1400}"

    mkdir -p "${plugin_dir}"

    local motd
    motd="$(read_prop motd 'A BRUH Minecraft')"
    local motd_sub="Powered by BRUH HA Apps"

    log "Resolved Geyser auth-type: ${auth_type} (requested='${BRUH_GEYSER_AUTH_TYPE:-auto}', online-mode='$(read_prop online-mode true)')"

    # The REAL fix for "Please log into Xbox to join this server.":
    # Geyser validates the Bedrock client's signed Xbox Live JWT chain
    # in LoginEncryptionUtils.encryptConnectionWithCert() *before* any
    # auth-type / Floodgate logic runs. The gate is
    # `advanced.bedrock.validate-bedrock-login` (default true). When
    # it's true and the client's chain is unsigned (LAN devices,
    # cracked clients, family Bedrock with no Xbox session), Geyser
    # kicks with the exact message we've been chasing — regardless of
    # auth-type. It is false in offline mode and the secure default
    # (true) in online / floodgate modes.
    local validate="true"
    if [ "${auth_type}" = "offline" ]; then
        validate="false"
    fi

    # MTU tuning: lowering from 1400 -> 1200 is the #1 fix for the iOS
    # "Connecting multiplayer server..." hang. Wi-Fi routers + cellular
    # hot-spots commonly fragment UDP at ~1400 and RakNet's login
    # handshake silently stalls.
    if [ ! -f "${cfg}" ]; then
        # Fresh install: stage a minimal file in Geyser's current layout
        # (2.9+). Geyser fills in defaults for every key we don't specify on
        # first boot, and migrates the file's layout itself if it is older.
        local motd_q sub_q
        motd_q=$(printf '%s' "${motd}" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
        sub_q=$(printf '%s' "${motd_sub}" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g')
        log "Staging fresh Geyser config at ${cfg} (auth-type: ${auth_type}, validate-bedrock-login: ${validate}, mtu: ${mtu})"
        cat > "${cfg}" <<YAML
# Managed by BRUH Minecraft add-on.
# java.auth-type, advanced.bedrock.mtu, advanced.bedrock.validate-bedrock-login
# and the MOTD are re-asserted on every add-on boot from the add-on options.
# See the README / DOCS for the tradeoffs between floodgate / offline /
# online. Every other key here is free for you to edit — Geyser fills in
# defaults for anything we haven't set.
java:
  auth-type: ${auth_type}
motd:
  primary-motd: "${motd_q}"
  secondary-motd: "${sub_q}"
advanced:
  bedrock:
    # Lower from 1400 to 1200 if iOS clients hang on "Connecting
    # multiplayer server…" — Wi-Fi routers often fragment UDP at 1400.
    mtu: ${mtu}
    # When false, Geyser skips validating the Bedrock client's signed
    # Xbox Live JWT chain — required so family LAN / cracked clients
    # can join a server with auth-type: offline.
    validate-bedrock-login: ${validate}
YAML
    else
        log "Geyser config exists at ${cfg} ($(stat -c '%s bytes, %y' "${cfg}" 2>/dev/null || echo '?'))"
        local layout
        if layout=$(python3 "${SCRIPT_DIR}/patch-geyser-config.py" --managed \
                "${cfg}" "${auth_type}" "${mtu}" "${validate}" "${motd}" "${motd_sub}"); then
            log "  - ${layout} layout: auth-type ${auth_type}, mtu ${mtu}, validate-bedrock-login ${validate}, motd \"${motd}\""
        else
            warn "  ! could not write the Geyser options into ${cfg}"
            warn "  ! Bedrock clients may still see 'Please log into Xbox'"
        fi
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
