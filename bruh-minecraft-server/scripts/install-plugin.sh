#!/bin/bash
# ============================================================================
# install-plugin.sh <url> [name]
# ----------------------------------------------------------------------------
# Downloads a plugin jar to /config/minecraft/plugins/. Skips unchanged files
# by ETag/size. Only meaningful for Paper / Purpur / Folia / Spigot-like servers.
#
# Failure policy: exits 1 on bad URL / download failure, but the caller in
# run.sh (install_plugins) MUST isolate the failure so the whole add-on
# doesn't crash just because one plugin URL 404'd. See 1.2.5 changelog.
# ============================================================================

set -uo pipefail

URL="${1:-}"
NAME="${2:-}"

if [ -z "${URL}" ] || [ "${URL}" = "null" ]; then
    echo "[install-plugin] url required (got empty/null)" >&2
    exit 1
fi
case "${URL}" in
    http://*|https://*) ;;
    *)
        echo "[install-plugin] refusing non-http(s) URL: ${URL}" >&2
        exit 1
        ;;
esac

PLUGINS_DIR="${MC_SERVER_DIR:-/config/minecraft}/plugins"
mkdir -p "${PLUGINS_DIR}"

if [ -z "${NAME}" ] || [ "${NAME}" = "null" ]; then
    NAME="$(basename "${URL%%\?*}")"
fi
case "${NAME}" in
    *.jar) ;;
    *)     NAME="${NAME}.jar" ;;
esac

DEST="${PLUGINS_DIR}/${NAME}"
TMP="${DEST}.tmp"

echo "[install-plugin] fetching ${NAME} from ${URL}"

# --max-time caps total wall-clock at 60s so a dead URL can't hang startup.
# --location follows redirects (GitHub release "latest" URLs in particular).
# --remote-time preserves mtime; -z does If-Modified-Since so we don't
# re-download on every start.
if curl -fsSL --retry 3 --retry-delay 2 --max-time 60 --remote-time \
        -z "${DEST}" -o "${TMP}" "${URL}"; then
    if [ -s "${TMP}" ]; then
        # Reject HTML bodies that curl -f didn't catch (e.g. 200 OK
        # rate-limit pages from GitHub). A valid jar starts with "PK"
        # (ZIP signature).
        if ! head -c 2 "${TMP}" 2>/dev/null | grep -q 'PK'; then
            echo "[install-plugin] ${NAME} download isn't a valid jar (got HTML/error body) — discarding" >&2
            rm -f "${TMP}"
            exit 1
        fi
        mv -f "${TMP}" "${DEST}"
        chown minecraft:minecraft "${DEST}" 2>/dev/null || true
        echo "[install-plugin] installed ${NAME}"
    else
        rm -f "${TMP}"
        echo "[install-plugin] ${NAME} up-to-date"
    fi
else
    rc=$?
    rm -f "${TMP}"
    echo "[install-plugin] failed to fetch ${NAME} (curl exit ${rc})" >&2
    exit 1
fi
