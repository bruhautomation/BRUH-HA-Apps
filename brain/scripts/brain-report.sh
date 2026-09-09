#!/bin/bash

# brain report — one redacted, plain-text report for a bug report.
#
# A field report used to arrive as prose: "the card didn't generate". This
# writes the evidence that turns it into a bug — as ONE text file under
# /share/brain/reports/, which is visible from the Home Assistant file
# editor and the Samba share, and is the same file the panel's ⚙ → Problems
# section lists and copies. The panel writes it when it is up (POST
# /api/reports/run: what happened, the last 80 lines of the add-on log, the
# full diagnostics payload); when the panel is down this script assembles
# the same shape itself from the self-test, the diagnostics mirror and the
# Supervisor's log, because "the panel is down" is exactly when a report is
# most needed.
#
# Redaction is not optional and not clever: anything credential-shaped
# (sk-ant-…, Bearer …, JWT-looking strings, token fields) is replaced with
# [redacted] before the file is left anywhere. Prompts and replies are
# never in these files in the first place (see panel/journal.py). Entity
# names ARE in them, because a report about "a sensor" is not a report;
# --no-names hashes every entity id if that matters to you.
#
# Usage:
#   brain report [--no-names]     Write the report and print its path

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
            sed -n '3,25p' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
    esac
done

# --- redaction, applied to the whole file every time --------------------------
# A regex that is skipped for a file "that can't have a token in it" is the
# regex that misses the day it does. panel/reports.py's redact() is the same
# four rules in Python; tests/test_reports.py drives both over one fixture.
redact() {
    sed -E -i \
        -e 's/sk-ant-[A-Za-z0-9_-]{8,}/[redacted]/g' \
        -e 's/Bearer[[:space:]]+[A-Za-z0-9._-]{8,}/[redacted]/g' \
        -e 's/eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}/[redacted]/g' \
        -e 's/("(access_token|refresh_token|token|api_key|oauth_token|value)"[ ]*:[ ]*")[^"]{8,}"/\1[redacted]"/g' \
        "$1"
}

# --no-names: every entity id becomes domain.<8 hex of its sha256>. The file
# is an argument, never stdin — a heredoc IS stdin.
hash_names_in() {
    python3 - "$1" <<'PY'
import hashlib, re, sys
p = sys.argv[1]
pat = re.compile(r"\b([a-z_]+)\.([a-z0-9_]{3,})\b")
def h(m):
    dom, obj = m.group(1), m.group(2)
    if dom in ("brain", "notify", "homeassistant") or "." in obj:
        return m.group(0)
    return f"{dom}.{hashlib.sha256(obj.encode()).hexdigest()[:8]}"
with open(p, encoding="utf-8", errors="replace") as fh:
    text = fh.read()
with open(p, "w", encoding="utf-8") as fh:
    fh.write(pat.sub(h, text))
PY
}

# The panel's answer to POST /api/reports/run is {"name": "...txt"}; anything
# else (a refusal, an error page, nothing) is an empty name. The body is an
# argument for the reason above.
report_name_from() {
    python3 - "$1" <<'PY'
import json, os, sys
try:
    d = json.loads(sys.argv[1] or "{}")
except ValueError:
    d = {}
name = d.get("name") if isinstance(d, dict) else None
# A name off the wire is a filename: bare, and a .txt.
if isinstance(name, str) and name == os.path.basename(name) and name.endswith(".txt") \
        and ".." not in name:
    print(name)
PY
}

finish() {
    redact "$1"
    if [ "$hash_names" = "1" ]; then
        hash_names_in "$1"
    fi
    echo -e "${GREEN}Report written:${NC} $1"
    echo -e "${DIM}Read it before attaching it to an issue. It is also listed under ⚙ → Problems in the panel.${NC}"
}

if ! mkdir -p "$OUT_ROOT" 2>/dev/null; then
    echo -e "${RED}Cannot write to $OUT_ROOT${NC}" >&2
    exit 1
fi

# --- 1. ask the panel ----------------------------------------------------------
resp=$(curl -s -m 90 -X POST -H 'Content-Type: application/json' -d '{}' \
    "$PANEL/api/reports/run" 2>/dev/null || true)
name=$(report_name_from "$resp")
if [ -n "$name" ]; then
    path="$OUT_ROOT/$name"
    if [ ! -s "$path" ]; then
        # The panel keeps its reports somewhere this shell does not see
        # (a different BRAIN_REPORTS_DIR); fetch the text and keep a copy here.
        curl -s -m 30 "$PANEL/api/reports/$name" -o "$path" 2>/dev/null || true
    fi
    if [ -s "$path" ]; then
        finish "$path"
        exit 0
    fi
    echo -e "${DIM}The panel wrote $name but it is not readable from here; assembling one instead.${NC}" >&2
fi

# --- 2. the panel is down: assemble the same shape here -----------------------
stamp=$(date +%Y-%m-%d-%H%M)
out="$OUT_ROOT/$stamp-manual.txt"
n=2
while [ -e "$out" ]; do
    out="$OUT_ROOT/$stamp-manual-$n.txt"
    n=$((n + 1))
done

{
    echo "$(date '+%Y-%m-%d %H:%M') · brAIn ${ADDON_VERSION:-unknown} · report requested (panel not answering)"
    echo
    echo "What happened:"
    echo "brain report was run and the panel at $PANEL did not answer, so this file was"
    echo "assembled by the shell from the self-test, the diagnostics mirror and the add-on log."
    echo
    echo "Where to look:"
    echo "The add-on log below is the first place: a panel that is not answering has usually"
    echo "said why in its last lines. \`brain doctor\` walks the rest."
    echo
    echo "--- doctor ---"
    if [ -f "$SELFTEST" ]; then
        bash "$SELFTEST" --json 2>/dev/null || echo '{"error": "ha-selftest.sh failed"}'
    else
        echo "(ha-selftest.sh not installed)"
    fi
    echo
    echo "--- versions ---"
    echo "addon: ${ADDON_VERSION:-unknown}"
    echo "claude: $(claude --version 2>/dev/null | head -1 || echo unknown)"
    echo "python: $(python3 --version 2>&1)"
    echo "arch: $(uname -m)"
    echo
    echo "--- add-on log, last 80 lines ---"
    if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
        curl -s -m 30 -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            "http://supervisor/addons/self/logs" 2>/dev/null | tail -n 80 \
            || echo "(log unavailable)"
    else
        echo "(no Supervisor token in this shell; run \`ha log\` in the terminal)"
    fi
    echo
    echo "--- diagnostics (the panel's last published mirror) ---"
    mirror="${BRAIN_DIAGNOSTICS_FILE:-/config/.brain/diagnostics.json}"
    if [ -r "$mirror" ]; then
        head -c 200000 "$mirror"
        echo
    else
        echo "(panel not answering and no mirror at $mirror)"
    fi
} > "$out" 2>/dev/null

finish "$out"
