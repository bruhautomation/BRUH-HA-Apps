#!/bin/bash
# ============================================================================
# install-plugin.sh <url> [name]
# ----------------------------------------------------------------------------
# Downloads a plugin jar to /config/minecraft/plugins/. Skips unchanged files
# by ETag/size. Only meaningful for Paper / Purpur / Folia / Spigot-like servers.
# ============================================================================

set -euo pipefail

URL="${1:-}"
NAME="${2:-}"

[ -n "${URL}" ] || { echo "[install-plugin] url required" >&2; exit 1; }

PLUGINS_DIR="${MC_SERVER_DIR:-/config/minecraft}/plugins"
mkdir -p "${PLUGINS_DIR}"

if [ -z "${NAME}" ]; then
    NAME="$(basename "${URL%%\?*}")"
fi
case "${NAME}" in
    *.jar) ;;
    *)     NAME="${NAME}.jar" ;;
esac

DEST="${PLUGINS_DIR}/${NAME}"
TMP="${DEST}.tmp"

echo "[install-plugin] fetching ${NAME} from ${URL}"

# --remote-time preserves mtime; -z does If-Modified-Since so we don't
# re-download on every start.
if curl -fsSL --retry 3 --retry-delay 2 --remote-time \
        -z "${DEST}" -o "${TMP}" "${URL}"; then
    if [ -s "${TMP}" ]; then
        mv -f "${TMP}" "${DEST}"
        chown minecraft:minecraft "${DEST}" 2>/dev/null || true
        echo "[install-plugin] installed ${NAME}"
    else
        rm -f "${TMP}"
        echo "[install-plugin] ${NAME} up-to-date"
    fi
else
    rm -f "${TMP}"
    echo "[install-plugin] failed to fetch ${NAME}" >&2
    exit 1
fi
