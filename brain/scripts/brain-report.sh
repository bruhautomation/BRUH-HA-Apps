#!/bin/bash

# brain report — one redacted diagnostics bundle for a bug report.
#
# A field report used to arrive as prose: "the card didn't generate". This
# writes the evidence that turns it into a bug — the self-test's verdict as
# JSON, the panel's diagnostics (versions, options, the run journal's last
# day, findings and memory statistics, the producer scorecard), and the tail
# of the add-on log — into one archive under /share/brain/reports/, which
# is visible from the Home Assistant file editor and the Samba share.
#
# Redaction is not optional and not clever: anything credential-shaped
# (sk-ant-…, Bearer …, JWT-looking strings, token fields) is replaced with
# [redacted] in every file before it is archived. Prompts and replies are
# never in these files in the first place (see panel/journal.py). Entity
# names ARE in them, because a report about "a sensor" is not a report;
# --no-names hashes every entity id if that matters to you.
#
# Usage:
#   brain report [--no-names]     Write the bundle and print its path

set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
DIM='\033[2m'
NC='\033[0m'

PANEL="${BRAIN_PANEL_URL:-http://127.0.0.1:8099}"
OUT_ROOT="${BRAIN_REPORTS_DIR:-/share/brain/reports}"
SELFTEST="${BRAIN_SCRIPTS_DIR:-/opt/scripts}/ha-selftest.sh"

if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    . /data/.brain_env
fi

hash_names=0
for arg in "$@"; do
    case "$arg" in
        --no-names) hash_names=1 ;;
        help|--help|-h)
            sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
done

stamp=$(date +%Y%m%d-%H%M%S)
dir="$OUT_ROOT/brain-report-$stamp"
if ! mkdir -p "$dir"; then
    echo -e "${RED}Cannot write to $OUT_ROOT${NC}" >&2
    exit 1
fi

# --- 1. the self-test, as JSON --------------------------------------------
if [ -f "$SELFTEST" ]; then
    bash "$SELFTEST" --json > "$dir/doctor.json" 2> "$dir/doctor.stderr" || true
else
    echo '{"error": "ha-selftest.sh not installed"}' > "$dir/doctor.json"
fi

# --- 2. the panel's diagnostics ---------------------------------------------
if ! curl -s -m 30 "$PANEL/api/diagnostics" > "$dir/diagnostics.json" 2>/dev/null \
        || [ ! -s "$dir/diagnostics.json" ]; then
    echo '{"error": "panel not answering"}' > "$dir/diagnostics.json"
fi

# --- 3. the add-on log tail ---------------------------------------------------
if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    curl -s -m 30 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        "http://supervisor/addons/self/logs" 2>/dev/null | tail -n 500 > "$dir/addon.log" || true
fi
[ -s "$dir/addon.log" ] || echo "(add-on log not readable from here)" > "$dir/addon.log"

# --- 4. versions ------------------------------------------------------------
{
    echo "generated: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "addon: ${ADDON_VERSION:-unknown}"
    echo "claude: $(claude --version 2>/dev/null | head -1 || echo unknown)"
    echo "python: $(python3 --version 2>&1)"
    echo "arch: $(uname -m)"
    if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
        curl -s -m 10 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            "http://supervisor/core/info" 2>/dev/null \
            | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data",{}); print("core:", d.get("version")); print("arch:", d.get("arch"))' 2>/dev/null || true
        curl -s -m 10 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            "http://supervisor/supervisor/info" 2>/dev/null \
            | python3 -c 'import json,sys; d=json.load(sys.stdin).get("data",{}); print("supervisor:", d.get("version"))' 2>/dev/null || true
    fi
} > "$dir/versions.txt" 2>/dev/null

# --- 5. redact, then archive ------------------------------------------------
# Applied to every file, every time, whether or not anything matched: a
# regex that is skipped for a file "that can't have a token in it" is the
# regex that misses the day it does.
redact() {
    sed -E -i \
        -e 's/sk-ant-[A-Za-z0-9_-]{8,}/[redacted]/g' \
        -e 's/(Bearer[ =:]+)[A-Za-z0-9._-]{8,}/\1[redacted]/g' \
        -e 's/eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/[redacted]/g' \
        -e 's/("(access_token|refresh_token|token|api_key|oauth_token|value)"[ ]*:[ ]*")[^"]{8,}"/\1[redacted]"/g' \
        "$1"
}
for f in "$dir"/*; do
    [ -f "$f" ] && redact "$f"
done

if [ "$hash_names" = "1" ]; then
    python3 - "$dir" <<'PY'
import hashlib, os, re, sys
d = sys.argv[1]
pat = re.compile(r"\b([a-z_]+)\.([a-z0-9_]{3,})\b")
def h(m):
    dom, obj = m.group(1), m.group(2)
    if dom in ("brain", "notify", "homeassistant") or "." in obj:
        return m.group(0)
    return f"{dom}.{hashlib.sha256(obj.encode()).hexdigest()[:8]}"
for name in os.listdir(d):
    p = os.path.join(d, name)
    if not os.path.isfile(p):
        continue
    with open(p, encoding="utf-8", errors="replace") as fh:
        text = fh.read()
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(pat.sub(h, text))
PY
fi

archive="$dir.tar.gz"
if tar -czf "$archive" -C "$OUT_ROOT" "$(basename "$dir")" 2>/dev/null; then
    echo -e "${GREEN}Report written:${NC} $archive"
    echo -e "${DIM}Also unpacked at $dir — read it before attaching it to an issue.${NC}"
else
    echo -e "${GREEN}Report written:${NC} $dir"
    echo -e "${DIM}(tar is not available; attach the folder's files instead)${NC}"
fi
