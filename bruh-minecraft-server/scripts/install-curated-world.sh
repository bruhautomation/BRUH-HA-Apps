#!/bin/bash
# ============================================================================
# install-curated-world.sh — one-click installer for "featured" worlds
# ----------------------------------------------------------------------------
# Stages a curated world (e.g. Drehmal: APOTHEOSIS) as a brand-new switchable
# world profile, ENTIRELY SERVER-SIDE so Bedrock clients (iPad/iPhone via
# Geyser) can join and explore with zero local installs:
#
#   1. Downloads the world save (with its bundled datapacks) and extracts it
#      into /config/minecraft-worlds/<name>/world/.
#   2. Writes the world's server.properties from the catalog recipe.
#   3. Records a .curated.json marker so a later "switch" can pin the server
#      software + Minecraft version the world requires (Drehmal needs Paper
#      1.20.1) and turn Bedrock support on.
#   4. Downloads the (Java) resource pack and hosts it globally for Java
#      players.
#   5. Best-effort converts the Java pack to a Bedrock pack and drops it into
#      the world's plugins/Geyser-Spigot/packs/ folder so Geyser auto-pushes
#      it to Bedrock clients on join — textures with no manual step.
#
# Usage:
#   install-curated-world.sh <curated_id> [profile_name]
#
# Env overrides (the panel sets these; defaults match production):
#   CURATED_WORLDS_FILE  catalog JSON (default: alongside this script)
#   MC_WORLDS_DIR        /config/minecraft-worlds
#   MC_BACKUPS_ROOT      /config/minecraft-backups
#   MC_RESOURCE_PACKS    /config/resource-packs
#   SERVER_CACHE         /data/server-cache  (download cache)
#
# Exit codes: 0 ok, 1 generic failure, 2 bad input, 3 profile already exists.
# ============================================================================
set -o pipefail

SCRIPT_DIR="${BRUH_MC_SCRIPTS_DIR:-$(cd "$(dirname "${0}")" 2>/dev/null && pwd)}"
SCRIPT_DIR="${SCRIPT_DIR:-/opt/bruh-mc/scripts}"

CURATED_WORLDS_FILE="${CURATED_WORLDS_FILE:-${SCRIPT_DIR}/curated-worlds.json}"
MC_WORLDS_DIR="${MC_WORLDS_DIR:-/config/minecraft-worlds}"
MC_BACKUPS_ROOT="${MC_BACKUPS_ROOT:-/config/minecraft-backups}"
MC_RESOURCE_PACKS="${MC_RESOURCE_PACKS:-/config/resource-packs}"
SERVER_CACHE="${SERVER_CACHE:-/data/server-cache}"
J2B_CONVERTER="${J2B_CONVERTER:-${SCRIPT_DIR}/convert-java-pack-to-bedrock.py}"
J2B_MAP="${J2B_MAP:-${SCRIPT_DIR}/java2bedrock-map.json}"
CURATED_CACHE="${SERVER_CACHE}/curated"

log()  { printf '[curated] %s\n' "$*" >&2; }
die()  { log "ERROR: $*"; exit "${2:-1}"; }

valid_name() { printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_-]{1,32}$'; }

# A file is a zip if it starts with the "PK" local-file-header magic. Google
# Drive hands back a small HTML interstitial for large files instead of the
# bytes, so this is how we tell a real download from the "can't scan for
# viruses" page.
is_zip() {
    [ -s "$1" ] || return 1
    [ "$(dd if="$1" bs=1 count=2 2>/dev/null)" = "PK" ]
}

cat_field() { jq -r "$1 // empty" "${CURATED_WORLDS_FILE}" 2>/dev/null; }

# ---------------------------------------------------------------------------
# Downloaders
# ---------------------------------------------------------------------------
download_plain() {
    local url="$1" out="$2"
    curl -fsSL --retry 3 --retry-delay 2 -o "${out}.tmp" "${url}" || return 1
    mv -f "${out}.tmp" "${out}"
}

# Google Drive large-file download: the first hit returns an HTML confirm page
# (virus-scan warning) carrying hidden form fields. We parse `uuid` + `confirm`
# and re-request the real bytes. Tries the no-interstitial `confirm=t` form
# first, which often works on its own.
download_gdrive() {
    local id="$1" out="$2"
    local base="https://drive.usercontent.google.com/download"
    local cookies page
    cookies=$(mktemp); page=$(mktemp)

    curl -fsSL -c "${cookies}" -b "${cookies}" \
        "${base}?id=${id}&export=download&confirm=t" -o "${out}" 2>/dev/null || true
    if is_zip "${out}"; then rm -f "${cookies}" "${page}"; return 0; fi

    # Not the bytes — must be the interstitial. Re-fetch it as text and parse.
    cp -f "${out}" "${page}" 2>/dev/null || true
    local uuid confirm
    uuid=$(grep -oE 'name="uuid" value="[^"]+"' "${page}" 2>/dev/null \
           | sed -E 's/.*value="([^"]+)".*/\1/' | head -n1)
    confirm=$(grep -oE 'name="confirm" value="[^"]+"' "${page}" 2>/dev/null \
           | sed -E 's/.*value="([^"]+)".*/\1/' | head -n1)
    [ -z "${confirm}" ] && confirm=t
    if [ -n "${uuid}" ]; then
        log "Resolving Google Drive confirm token…"
        curl -fsSL -c "${cookies}" -b "${cookies}" \
            "${base}?id=${id}&export=download&confirm=${confirm}&uuid=${uuid}" \
            -o "${out}" 2>/dev/null || true
    fi
    rm -f "${cookies}" "${page}"
    is_zip "${out}"
}

# Resolve the world archive into ${CURATED_CACHE}/<id>-world.zip (cached so a
# retry after a failed extract doesn't re-pull ~1.5 GB).
fetch_world_archive() {
    local id="$1" out="$2"
    if is_zip "${out}"; then
        log "Using cached world archive ($(du -h "${out}" | cut -f1))"
        return 0
    fi
    local gdrive_id world_url
    gdrive_id=$(cat_field ".worlds.\"${id}\".world.gdrive_id")
    world_url=$(cat_field ".worlds.\"${id}\".world.url")

    if [ -n "${gdrive_id}" ]; then
        log "Downloading world from Google Drive (${gdrive_id}) — this is large, please wait…"
        if download_gdrive "${gdrive_id}" "${out}"; then return 0; fi
        log "Google Drive download did not yield a zip; trying the catalog URL…"
    fi
    if [ -n "${world_url}" ]; then
        log "Downloading world from ${world_url}"
        download_plain "${world_url}" "${out}" || return 1
        is_zip "${out}" && return 0
    fi
    return 1
}

# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------
ID="${1:-}"
NAME="${2:-${ID}}"

[ -n "${ID}" ] || die "usage: install-curated-world.sh <curated_id> [profile_name]" 2
[ -r "${CURATED_WORLDS_FILE}" ] || die "catalog not readable: ${CURATED_WORLDS_FILE}" 1
valid_name "${ID}" || die "invalid curated id" 2
valid_name "${NAME}" || die "invalid profile name (1-32 chars, [A-Za-z0-9_-])" 2

exists=$(cat_field ".worlds.\"${ID}\".name")
[ -n "${exists}" ] || die "unknown curated world '${ID}'" 2

WORLD_DIR="${MC_WORLDS_DIR}/${NAME}"
[ -e "${WORLD_DIR}" ] && die "profile '${NAME}' already exists — delete it first or pick another name" 3

DISPLAY_NAME=$(cat_field ".worlds.\"${ID}\".name")
VERSION=$(cat_field ".worlds.\"${ID}\".version")
SERVER_TYPE=$(cat_field ".worlds.\"${ID}\".server_type")
MC_VERSION=$(cat_field ".worlds.\"${ID}\".minecraft_version")

log "Installing '${DISPLAY_NAME}' v${VERSION} as world profile '${NAME}'"
log "Requires: ${SERVER_TYPE} ${MC_VERSION} (will be pinned when you switch to it)"

mkdir -p "${CURATED_CACHE}" "${MC_RESOURCE_PACKS}"

# --- 1. World save ----------------------------------------------------------
ARCHIVE="${CURATED_CACHE}/${ID}-world.zip"
fetch_world_archive "${ID}" "${ARCHIVE}" \
    || die "failed to download the world archive for '${ID}'. If this is a Google Drive link it may be rate-limited; try again later or import the world manually." 1

log "Extracting world…"
EXTRACT_DIR=$(mktemp -d)
trap 'rm -rf "${EXTRACT_DIR}"' EXIT
if ! unzip -q "${ARCHIVE}" -d "${EXTRACT_DIR}"; then
    die "world archive is corrupt; delete ${ARCHIVE} and retry" 1
fi

# The world root is whatever directory holds level.dat.
LEVEL_DAT=$(find "${EXTRACT_DIR}" -maxdepth 6 -name level.dat -print 2>/dev/null | head -n1)
[ -n "${LEVEL_DAT}" ] || die "no level.dat found in the archive — not a Minecraft world" 1
WORLD_SRC=$(dirname "${LEVEL_DAT}")

mkdir -p "${WORLD_DIR}" "${WORLD_DIR}/plugins" "${WORLD_DIR}/mods" "${MC_BACKUPS_ROOT}/${NAME}"
mv "${WORLD_SRC}" "${WORLD_DIR}/world"
log "World staged at ${WORLD_DIR}/world ($(du -sh "${WORLD_DIR}/world" 2>/dev/null | cut -f1))"
if [ -d "${WORLD_DIR}/world/datapacks" ]; then
    log "Bundled datapacks: $(find "${WORLD_DIR}/world/datapacks" -maxdepth 1 -mindepth 1 | wc -l | tr -d ' ') (server-side)"
fi

# --- 2. server.properties ---------------------------------------------------
PROPS="${WORLD_DIR}/server.properties"
{
    printf '# server.properties — staged by install-curated-world.sh (%s)\n' "$(date +%Y-%m-%dT%H:%M:%S%z)"
    printf '# Curated world: %s v%s\n' "${DISPLAY_NAME}" "${VERSION}"
    printf 'level-name=world\n'
    jq -r ".worlds.\"${ID}\".properties // {} | to_entries[] | \"\(.key)=\(.value)\"" \
        "${CURATED_WORLDS_FILE}" 2>/dev/null
} > "${PROPS}"
printf 'eula=true\n' > "${WORLD_DIR}/eula.txt"

# --- 3. .curated.json marker (read by the panel's switch handler) -----------
jq -n \
    --arg id "${ID}" --arg name "${DISPLAY_NAME}" --arg version "${VERSION}" \
    --arg server_type "${SERVER_TYPE}" --arg mc "${MC_VERSION}" \
    '{id:$id, name:$name, version:$version, server_type:$server_type,
      minecraft_version:$mc, requires_bedrock_support:true,
      installed_at:(now|floor)}' \
    > "${WORLD_DIR}/.curated.json" 2>/dev/null \
    || printf '{"id":"%s","server_type":"%s","minecraft_version":"%s","requires_bedrock_support":true}\n' \
        "${ID}" "${SERVER_TYPE}" "${MC_VERSION}" > "${WORLD_DIR}/.curated.json"

# --- 4 & 5. Resource pack: host for Java + convert for Bedrock --------------
RP_URL=$(cat_field ".worlds.\"${ID}\".resource_pack.url")
RP_NAME=$(cat_field ".worlds.\"${ID}\".resource_pack.name")
RP_CONVERT=$(cat_field ".worlds.\"${ID}\".resource_pack.convert_to_bedrock")
[ -n "${RP_NAME}" ] || RP_NAME="${ID}-resource-pack.zip"

if [ -n "${RP_URL}" ]; then
    log "Downloading resource pack…"
    RP_CACHE="${CURATED_CACHE}/${RP_NAME}"
    if is_zip "${RP_CACHE}" || download_plain "${RP_URL}" "${RP_CACHE}"; then
        if is_zip "${RP_CACHE}"; then
            # Host the Java pack globally (panel sets resource-pack URL on switch/apply).
            cp -f "${RP_CACHE}" "${MC_RESOURCE_PACKS}/${RP_NAME}"
            log "Java resource pack hosted at ${MC_RESOURCE_PACKS}/${RP_NAME}"
            # Convert to a Bedrock pack so Geyser auto-pushes it to iPads/iPhones.
            if [ "${RP_CONVERT}" = "true" ] && [ -r "${J2B_CONVERTER}" ]; then
                GEYSER_PACKS="${WORLD_DIR}/plugins/Geyser-Spigot/packs"
                mkdir -p "${GEYSER_PACKS}"
                MCPACK="${GEYSER_PACKS}/${ID}.mcpack"
                log "Converting resource pack to Bedrock (.mcpack) for Geyser auto-push…"
                if python3 "${J2B_CONVERTER}" "${RP_CACHE}" "${MCPACK}" "${DISPLAY_NAME}" "${J2B_MAP}"; then
                    log "Bedrock pack ready: ${MCPACK} — Geyser sends it to Bedrock clients on join."
                else
                    log "WARN: Bedrock conversion failed; Bedrock clients will see default textures (map is still fully playable)."
                fi
            fi
        else
            log "WARN: resource pack download was not a zip; skipping (world still installs fine)."
        fi
    else
        log "WARN: resource pack download failed; skipping (world still installs fine)."
    fi
fi

chown -R minecraft:minecraft "${WORLD_DIR}" "${MC_BACKUPS_ROOT}/${NAME}" "${MC_RESOURCE_PACKS}" 2>/dev/null || true

log "Done. '${DISPLAY_NAME}' is installed as world '${NAME}'."
log "Switch to it from the panel's Worlds tab — the add-on will pin ${SERVER_TYPE} ${MC_VERSION}, enable Bedrock, and restart."
printf '%s\n' "${NAME}"
