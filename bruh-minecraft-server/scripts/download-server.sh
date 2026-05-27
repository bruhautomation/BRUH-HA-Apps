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

JAR_PATH="${MC_SERVER_DIR}/server.jar"
META_PATH="${MC_SERVER_DIR}/.server-meta.json"

log() { printf '[download-server] %s\n' "$*" >&2; }

# Read the version + build of the jar that's currently installed (if any),
# so we can emit a clear "X -> Y" line when auto-update bumps the server.
read_installed_version() {
    [ -f "${META_PATH}" ] || { printf 'none'; return; }
    local v b
    v=$(jq -r '.version // empty' < "${META_PATH}" 2>/dev/null)
    b=$(jq -r '.build   // empty' < "${META_PATH}" 2>/dev/null)
    if [ -n "${v}" ] && [ -n "${b}" ] && [ "${b}" != "null" ]; then
        printf '%s build %s' "${v}" "${b}"
    elif [ -n "${v}" ]; then
        printf '%s' "${v}"
    else
        printf 'unknown'
    fi
}

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

# PaperMC's v2 API (api.papermc.io/v2) is deprecated in favour of the v3
# "fill" API (fill.papermc.io/v3). v3 enforces a descriptive User-Agent and
# returns full download URLs + sha256 checksums per build. We resolve through
# v3 first and fall back to v2 if anything about the v3 response surprises us,
# so a download never silently fails while v2 is still served.
PAPER_V3="https://fill.papermc.io/v3/projects"
PAPER_V2="https://api.papermc.io/v2/projects"
PAPER_UA="BRUH-Minecraft-Server/${ADDON_VERSION:-dev} (+https://github.com/bruhautomation/BRUH-HA-Apps)"

# Pick the version string to install for a paper-like project, given the v3
# project JSON on stdin. LATEST/SNAPSHOT resolve to the highest MC-shaped
# (1.x[.y]) version; an explicit version passes through unchanged.
# Exposed as a function so tests can feed it captured API JSON.
paper_pick_version() {
    # Reads project JSON on stdin. v3 shape: {"versions":{"1.21":["1.21.4",...]}}
    # (object of arrays). v2 shape: {"versions":["1.21","1.21.1",...]} (flat
    # array). Flatten both, keep MC-shaped releases, pick the highest semver.
    jq -r '
        (.versions
            | if type == "object" then [.[][]] else . end)
        | map(select(type == "string" and test("^1\\.[0-9]+(\\.[0-9]+)?$")))
        | sort_by(split(".") | map(tonumber))
        | last // empty
    '
}

# Given builds JSON on stdin (v3), emit "<build_id>\t<url>\t<sha256>" for the
# newest STABLE build (or newest of any channel when no stable exists, e.g.
# right after a fresh MC release). v3 builds endpoint returns either a bare
# array or {"builds":[...]}; handle both.
paper_pick_build_v3() {
    jq -r '
        (if type == "object" then (.builds // []) else . end)
        | (map(select(.channel == "STABLE"))) as $stable
        | (if ($stable | length) > 0 then $stable else . end)
        | sort_by(.id)
        | last
        | (.downloads["server:default"] // .downloads.application) as $d
        | "\(.id)\t\($d.url)\t\($d.checksums.sha256 // "")"
    '
}

download_paper_v3() {
    local project="$1" version="$2"
    local builds_json line build url sha256
    builds_json=$(curl -fsSL -A "${PAPER_UA}" \
        "${PAPER_V3}/${project}/versions/${version}/builds" 2>/dev/null) || return 1
    line=$(printf '%s' "${builds_json}" | paper_pick_build_v3) || return 1
    build=$(printf '%s' "${line}" | cut -f1)
    url=$(printf '%s' "${line}" | cut -f2)
    sha256=$(printf '%s' "${line}" | cut -f3)
    [ -n "${build}" ] && [ "${build}" != "null" ] && [ -n "${url}" ] && [ "${url}" != "null" ] \
        || return 1

    local jar_name="${project}-${version}-${build}.jar"
    local cache="${SERVER_CACHE}/${jar_name}"
    if [ ! -f "${cache}" ]; then
        log "Downloading ${project} ${version} build ${build} (v3)"
        curl -fsSL -A "${PAPER_UA}" -o "${cache}.tmp" "${url}" || return 1
        if [ -n "${sha256}" ] && command -v sha256sum >/dev/null 2>&1; then
            if ! echo "${sha256}  ${cache}.tmp" | sha256sum -c - >/dev/null 2>&1; then
                log "Checksum mismatch for ${jar_name}; discarding"
                rm -f "${cache}.tmp"
                return 1
            fi
        fi
        mv "${cache}.tmp" "${cache}"
    else
        log "Using cached ${jar_name}"
    fi
    cp -f "${cache}" "${JAR_PATH}"
    write_meta "${version}" "${build}" "${url}"
}

download_paper_v2() {
    local project="$1" version="$2"
    local build url
    build=$(curl -fsSL "${PAPER_V2}/${project}/versions/${version}" \
            | jq -r '.builds[-1]')
    [ -n "${build}" ] && [ "${build}" != "null" ] \
        || { log "Could not resolve ${project} build for ${version} (v2)"; return 1; }
    local jar_name="${project}-${version}-${build}.jar"
    url="${PAPER_V2}/${project}/versions/${version}/builds/${build}/downloads/${jar_name}"
    local cache="${SERVER_CACHE}/${jar_name}"
    if [ ! -f "${cache}" ]; then
        log "Downloading ${project} ${version} build ${build} (v2 fallback)"
        curl -fsSL -o "${cache}.tmp" "${url}" || return 1
        mv "${cache}.tmp" "${cache}"
    else
        log "Using cached ${jar_name}"
    fi
    cp -f "${cache}" "${JAR_PATH}"
    write_meta "${version}" "${build}" "${url}"
}

download_paper_like() {
    local project="$1"  # paper | folia
    local version proj_json

    if [ "${VERSION_REQ}" = "LATEST" ] || [ "${VERSION_REQ}" = "SNAPSHOT" ]; then
        proj_json=$(curl -fsSL -A "${PAPER_UA}" "${PAPER_V3}/${project}" 2>/dev/null)
        version=$(printf '%s' "${proj_json}" | paper_pick_version 2>/dev/null)
        if [ -z "${version}" ]; then
            # v3 unreachable / shape changed — resolve the version off v2.
            version=$(curl -fsSL "${PAPER_V2}/${project}" | paper_pick_version)
        fi
    else
        version="${VERSION_REQ}"
    fi
    [ -n "${version}" ] || { log "Could not resolve ${project} version"; return 1; }

    if download_paper_v3 "${project}" "${version}"; then
        return 0
    fi
    log "v3 download failed for ${project} ${version}; trying deprecated v2 API"
    download_paper_v2 "${project}" "${version}"
}

download_purpur() {
    local version build url
    # Purpur's `versions` array is not strictly chronological and can include
    # non-MC-shaped entries (e.g. an internal `26.1.2` rebuild marker that
    # currently sits AFTER `1.21.11`). The 1.5.0 filter `^[0-9]+\.[0-9]+(\.[0-9]+)?$`
    # was too loose — it matched `26.1.2` and `[-1]` returned the bogus
    # marker, breaking LATEST resolution. Restrict to MC-shaped 1.x entries
    # and pick the highest by numeric semver instead of array position.
    if [ "${VERSION_REQ}" = "LATEST" ]; then
        version=$(curl -fsSL "https://api.purpurmc.org/v2/purpur" \
            | jq -r '[.versions[] | select(test("^1\\.[0-9]+(\\.[0-9]+)?$"))]
                     | sort_by(split(".") | map(tonumber)) | .[-1]')
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

main() {
    mkdir -p "${MC_SERVER_DIR}" "${SERVER_CACHE}"
    local installed_before
    installed_before=$(read_installed_version)
    log "Currently installed: ${installed_before} (request: ${SERVER_TYPE} ${VERSION_REQ})"

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
    local installed_after
    installed_after=$(read_installed_version)
    if [ "${installed_before}" != "${installed_after}" ] && [ "${installed_before}" != "none" ]; then
        log "Updated: ${installed_before} -> ${installed_after}"
    else
        log "Active: ${installed_after}"
    fi
    log "Installed $(basename "${JAR_PATH}") ($(du -h "${JAR_PATH}" | cut -f1))"
}

# Only run the downloader when executed directly — sourcing (e.g. from the
# test suite) just loads the resolver functions.
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi
