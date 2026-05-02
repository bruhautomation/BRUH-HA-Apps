#!/bin/bash
# ============================================================================
# download-server.sh
# ----------------------------------------------------------------------------
# Resolve the requested SERVER_TYPE + MINECRAFT_VERSION to a concrete jar URL,
# download it (with caching + checksum) and install it at server.jar.
#
# Supported server types:
#   paper   - PaperMC  (https://api.papermc.io/v2/projects/paper)
#   purpur  - PurpurMC (https://api.purpurmc.org/v2/purpur)
#   folia   - PaperMC  (https://api.papermc.io/v2/projects/folia)
#   vanilla - Mojang   (piston-meta version manifest)
#   fabric  - Fabric installer (https://meta.fabricmc.net)
#   forge   - Forge installer (https://files.minecraftforge.net)
# ============================================================================

set -euo pipefail

SERVER_TYPE="${SERVER_TYPE:-paper}"
VERSION_REQ="${MINECRAFT_VERSION:-LATEST}"
MC_SERVER_DIR="${MC_SERVER_DIR:-/config/minecraft}"
SERVER_CACHE="${SERVER_CACHE:-/data/server-cache}"
MC_PANEL_STATE="${MC_PANEL_STATE:-/data/panel}"

mkdir -p "${MC_SERVER_DIR}" "${SERVER_CACHE}"
JAR_PATH="${MC_SERVER_DIR}/server.jar"
META_PATH="${MC_SERVER_DIR}/.server-meta.json"

log() { printf '[download-server] %s\n' "$*" >&2; }

write_meta() {
    local version="$1" build="$2" src_url="$3"
    cat > "${META_PATH}" <<JSON
{
  "server_type": "${SERVER_TYPE}",
  "version": "${version}",
  "build": "${build}",
  "source_url": "${src_url}",
  "installed_at": $(date +%s)
}
JSON
}

# ------------------------- version resolvers -------------------------

resolve_paper_version() {
    local project="$1"  # paper | folia
    # PaperMC publishes pre-releases (`1.21.11-pre5`) and release candidates
    # (`1.21.11-rc3`) into the same `versions[]` array as stable releases,
    # in chronological order. A naive `.versions[-1]` therefore grabs a
    # pre-release whenever one is out — whose network protocol differs from
    # the stable client on the same MC version, so vanilla clients reject
    # the server with "Outdated server! I'm still on X.Y.Z".
    # For LATEST we filter to stable-shaped strings (`X.Y` / `X.Y.Z`).
    # SNAPSHOT preserves the old behaviour and opts into pre-releases.
    if [ "${VERSION_REQ}" = "LATEST" ]; then
        curl -fsSL "https://api.papermc.io/v2/projects/${project}" \
            | jq -r '[.versions[] | select(test("^[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))] | .[-1]'
    elif [ "${VERSION_REQ}" = "SNAPSHOT" ]; then
        curl -fsSL "https://api.papermc.io/v2/projects/${project}" \
            | jq -r '.versions[-1]'
    else
        echo "${VERSION_REQ}"
    fi
}

download_paper_like() {
    local project="$1"  # paper | folia
    local version build url
    version=$(resolve_paper_version "${project}")
    [ -n "${version}" ] || { log "Could not resolve ${project} version"; return 1; }
    build=$(curl -fsSL "https://api.papermc.io/v2/projects/${project}/versions/${version}" \
            | jq -r '.builds[-1]')
    [ -n "${build}" ] && [ "${build}" != "null" ] \
        || { log "Could not resolve ${project} build for ${version}"; return 1; }

    local jar_name="${project}-${version}-${build}.jar"
    url="https://api.papermc.io/v2/projects/${project}/versions/${version}/builds/${build}/downloads/${jar_name}"
    local cache="${SERVER_CACHE}/${jar_name}"

    if [ ! -f "${cache}" ]; then
        log "Downloading ${project} ${version} build ${build}"
        curl -fsSL -o "${cache}.tmp" "${url}"
        mv "${cache}.tmp" "${cache}"
    else
        log "Using cached ${jar_name}"
    fi

    cp -f "${cache}" "${JAR_PATH}"
    write_meta "${version}" "${build}" "${url}"
}

download_purpur() {
    local version build url
    # Purpur's `versions` array is not strictly chronological and can include
    # non-MC-shaped entries (e.g. internal rebuild markers). Mirror the Paper
    # logic: filter to stable-shaped strings (`X.Y` / `X.Y.Z`) for LATEST
    # so we never try to download a bogus "26.1.2" jar.
    if [ "${VERSION_REQ}" = "LATEST" ]; then
        version=$(curl -fsSL "https://api.purpurmc.org/v2/purpur" \
            | jq -r '[.versions[] | select(test("^[0-9]+\\.[0-9]+(\\.[0-9]+)?$"))] | .[-1]')
    elif [ "${VERSION_REQ}" = "SNAPSHOT" ]; then
        version=$(curl -fsSL "https://api.purpurmc.org/v2/purpur" | jq -r '.versions[-1]')
    else
        version="${VERSION_REQ}"
    fi
    [ -n "${version}" ] || { log "Could not resolve purpur version"; return 1; }
    build=$(curl -fsSL "https://api.purpurmc.org/v2/purpur/${version}" | jq -r '.builds.latest')
    [ -n "${build}" ] && [ "${build}" != "null" ] \
        || { log "Could not resolve purpur build for ${version}"; return 1; }

    local jar_name="purpur-${version}-${build}.jar"
    url="https://api.purpurmc.org/v2/purpur/${version}/${build}/download"
    local cache="${SERVER_CACHE}/${jar_name}"

    if [ ! -f "${cache}" ]; then
        log "Downloading purpur ${version} build ${build}"
        curl -fsSL -o "${cache}.tmp" "${url}"
        mv "${cache}.tmp" "${cache}"
    else
        log "Using cached ${jar_name}"
    fi
    cp -f "${cache}" "${JAR_PATH}"
    write_meta "${version}" "${build}" "${url}"
}

download_vanilla() {
    local manifest version entry url_meta sha1 url jar_name cache
    manifest=$(curl -fsSL "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json")

    if [ "${VERSION_REQ}" = "LATEST" ]; then
        version=$(echo "${manifest}" | jq -r '.latest.release')
    elif [ "${VERSION_REQ}" = "SNAPSHOT" ]; then
        version=$(echo "${manifest}" | jq -r '.latest.snapshot')
    else
        version="${VERSION_REQ}"
    fi
    [ -n "${version}" ] || { log "Could not resolve vanilla version"; return 1; }

    entry=$(echo "${manifest}" | jq -r --arg v "${version}" \
        '.versions[] | select(.id == $v) | .url')
    [ -n "${entry}" ] && [ "${entry}" != "null" ] \
        || { log "Vanilla version '${version}' not found"; return 1; }

    url_meta=$(curl -fsSL "${entry}")
    url=$(echo "${url_meta}" | jq -r '.downloads.server.url')
    sha1=$(echo "${url_meta}" | jq -r '.downloads.server.sha1')

    jar_name="minecraft_server.${version}.jar"
    cache="${SERVER_CACHE}/${jar_name}"

    if [ ! -f "${cache}" ] || ! echo "${sha1}  ${cache}" | sha1sum -c - >/dev/null 2>&1; then
        log "Downloading vanilla ${version}"
        curl -fsSL -o "${cache}.tmp" "${url}"
        mv "${cache}.tmp" "${cache}"
    else
        log "Using cached ${jar_name}"
    fi

    cp -f "${cache}" "${JAR_PATH}"
    write_meta "${version}" "${sha1}" "${url}"
}

download_fabric() {
    local game_ver loader_ver installer_ver url jar_name cache meta
    meta=$(curl -fsSL "https://meta.fabricmc.net/v2/versions")
    if [ "${VERSION_REQ}" = "LATEST" ] || [ "${VERSION_REQ}" = "SNAPSHOT" ]; then
        game_ver=$(echo "${meta}" | jq -r '[.game[] | select(.stable == true)][0].version')
    else
        game_ver="${VERSION_REQ}"
    fi
    loader_ver=$(echo "${meta}" | jq -r '[.loader[] | select(.stable == true)][0].version')
    installer_ver=$(echo "${meta}" | jq -r '[.installer[] | select(.stable == true)][0].version')

    jar_name="fabric-server-mc.${game_ver}-loader.${loader_ver}-launcher.${installer_ver}.jar"
    url="https://meta.fabricmc.net/v2/versions/loader/${game_ver}/${loader_ver}/${installer_ver}/server/jar"
    cache="${SERVER_CACHE}/${jar_name}"

    if [ ! -f "${cache}" ]; then
        log "Downloading Fabric server (${game_ver} / loader ${loader_ver})"
        curl -fsSL -o "${cache}.tmp" "${url}"
        mv "${cache}.tmp" "${cache}"
    else
        log "Using cached ${jar_name}"
    fi
    cp -f "${cache}" "${JAR_PATH}"
    write_meta "${game_ver}" "${loader_ver}" "${url}"
}

download_forge() {
    # Forge ships an installer, not a server jar. We run the installer once
    # to bootstrap, then rely on the generated run.sh at launch time.
    local version promo url jar_name cache promo_json
    promo_json=$(curl -fsSL "https://files.minecraftforge.net/net/minecraftforge/forge/promotions_slim.json")

    if [ "${VERSION_REQ}" = "LATEST" ] || [ "${VERSION_REQ}" = "SNAPSHOT" ]; then
        # Pick the highest key like "1.21.1-recommended" (fallback to -latest)
        version=$(echo "${promo_json}" | jq -r \
            '.promos | to_entries | map(select(.key | endswith("-recommended"))) | .[-1].key' \
            | sed 's/-recommended$//')
    else
        version="${VERSION_REQ}"
    fi
    promo=$(echo "${promo_json}" | jq -r --arg v "${version}-recommended" \
        '.promos[$v] // empty')
    [ -z "${promo}" ] && promo=$(echo "${promo_json}" | jq -r --arg v "${version}-latest" \
        '.promos[$v] // empty')
    [ -n "${promo}" ] || { log "Could not resolve Forge build for ${version}"; return 1; }

    jar_name="forge-${version}-${promo}-installer.jar"
    url="https://maven.minecraftforge.net/net/minecraftforge/forge/${version}-${promo}/${jar_name}"
    cache="${SERVER_CACHE}/${jar_name}"

    if [ ! -f "${cache}" ]; then
        log "Downloading Forge installer ${version}-${promo}"
        curl -fsSL -o "${cache}.tmp" "${url}"
        mv "${cache}.tmp" "${cache}"
    fi
    cp -f "${cache}" "${MC_SERVER_DIR}/forge-installer.jar"

    # Run installer once; it produces the real server jar + libraries.
    if [ ! -f "${MC_SERVER_DIR}/.forge-installed" ]; then
        log "Running Forge installer (one-time)"
        ( cd "${MC_SERVER_DIR}" && java -jar forge-installer.jar --installServer ) >&2
        touch "${MC_SERVER_DIR}/.forge-installed"
    fi

    # Locate the real server jar produced by the installer
    local real_jar
    real_jar=$(ls "${MC_SERVER_DIR}"/forge-*.jar 2>/dev/null \
        | grep -v installer | head -n 1 || true)
    if [ -n "${real_jar}" ]; then
        ln -sf "$(basename "${real_jar}")" "${JAR_PATH}"
    fi
    write_meta "${version}" "${promo}" "${url}"
}

# ------------------------- dispatch -------------------------

case "${SERVER_TYPE}" in
    paper)   download_paper_like paper ;;
    folia)   download_paper_like folia ;;
    purpur)  download_purpur ;;
    vanilla) download_vanilla ;;
    fabric)  download_fabric ;;
    forge)   download_forge ;;
    *)
        log "Unsupported server_type: ${SERVER_TYPE}"
        exit 1
        ;;
esac

if [ ! -s "${JAR_PATH}" ]; then
    log "server.jar is missing or empty after download"
    exit 1
fi
log "Installed $(basename "${JAR_PATH}") ($(du -h "${JAR_PATH}" | cut -f1))"
