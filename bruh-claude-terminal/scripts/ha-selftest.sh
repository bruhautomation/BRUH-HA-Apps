#!/bin/bash
# BRUH Claude Terminal — in-situ self-test
#
# Run this INSIDE the add-on terminal (`ha-selftest`) to verify the moving
# parts end-to-end: HA API auth, the MCP server (driven over stdio JSON-RPC
# exactly the way Claude Code drives it), every HA tool, the deployed custom
# integration, and the background listeners. Anything that needs fixing shows
# up as a red FAIL with a hint.
#
# Exit code is non-zero if any check FAILs, so it's also usable in scripts.

# Pull in HOME / SUPERVISOR_TOKEN / HA_BASE_URL the way the listeners do, in
# case this is run from a context that didn't source the shell profile.
# Use `-r` (readable), not `-f`: the env file is root-owned 0600, so when this
# runs as the non-root `claude` user it exists but isn't readable — `-f` would
# then try to source it and print "Permission denied". `claude` already
# inherits these vars from its parent, so skipping the source here is correct.
if [ -r /data/.bruh_claude_env ]; then
    # shellcheck disable=SC1091
    . /data/.bruh_claude_env
fi

HA_BASE_URL="${HA_BASE_URL:-http://supervisor/core/api}"
MCP_SERVER="/opt/ha-mcp-server/ha_mcp_server.py"
INTEGRATION_DIR="/config/custom_components/bruh_claude"
MCP_CONFIG="/config/.mcp.json"
SETTINGS="/config/.claude/settings.local.json"
USAGE_FILE="/config/.bruh_claude/usage_limits.json"

# --- pretty output ----------------------------------------------------------
if [ -t 1 ]; then
    C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_WARN=$'\033[33m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
    C_OK=""; C_BAD=""; C_WARN=""; C_DIM=""; C_RST=""
fi
PASS=0; FAIL=0; WARN=0
pass() { PASS=$((PASS + 1)); printf '  %s✓%s %s\n' "$C_OK" "$C_RST" "$1"; }
fail() { FAIL=$((FAIL + 1)); printf '  %s✗%s %s\n' "$C_BAD" "$C_RST" "$1"; }
warn() { WARN=$((WARN + 1)); printf '  %s!%s %s\n' "$C_WARN" "$C_RST" "$1"; }
info() { printf '    %s%s%s\n' "$C_DIM" "$1" "$C_RST"; }
hdr()  { printf '\n%s%s%s\n' "$C_DIM" "$1" "$C_RST"; }

printf '%s\n' "BRUH Claude Terminal — self-test"

# --- 1. environment & auth --------------------------------------------------
hdr "Environment & Home Assistant API"
if [ -n "${SUPERVISOR_TOKEN:-}" ]; then
    pass "SUPERVISOR_TOKEN present (${#SUPERVISOR_TOKEN} chars)"
else
    fail "SUPERVISOR_TOKEN missing — MCP server and HA API calls will fail"
fi

api_code=$(curl -s -o /dev/null -w '%{http_code}' \
    -H "Authorization: Bearer ${SUPERVISOR_TOKEN:-}" \
    "${HA_BASE_URL}/" 2>/dev/null)
if [ "$api_code" = "200" ]; then
    pass "HA REST API reachable (${HA_BASE_URL} → 200)"
else
    fail "HA REST API not reachable (${HA_BASE_URL}/ → HTTP ${api_code:-none})"
fi

# --- 2. MCP config & permissions -------------------------------------------
hdr "MCP config & tool permissions"
if [ -f "$MCP_CONFIG" ]; then
    if grep -q "/api/mcp" "$MCP_CONFIG" 2>/dev/null; then
        fail "$MCP_CONFIG contains a stale /api/mcp entry — restart the add-on"
    else
        pass "$MCP_CONFIG present and clean"
    fi
else
    fail "$MCP_CONFIG missing — Claude has no HA tools"
fi
if [ -f "$SETTINGS" ]; then
    pass "Tool allowlist present ($SETTINGS)"
else
    warn "$SETTINGS missing — background listeners may hit permission prompts"
fi

# --- 3. MCP server end-to-end (stdio JSON-RPC) ------------------------------
hdr "MCP server (driven over stdio, like Claude Code does)"
if [ ! -f "$MCP_SERVER" ]; then
    fail "MCP server not found at $MCP_SERVER"
else
    # The python helper speaks the MCP protocol to the server and prints one
    # "PASS|desc" / "FAIL|desc" / "INFO|detail" line per sub-check; we fold
    # those into this script's counters below.
    while IFS='|' read -r kind desc; do
        case "$kind" in
            PASS) pass "$desc" ;;
            FAIL) fail "$desc" ;;
            INFO) info "$desc" ;;
        esac
    done < <(MCP_SERVER="$MCP_SERVER" python3 - <<'PY'
import json, os, subprocess, sys

server = ["python3", os.environ["MCP_SERVER"]]
reqs = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "get_ha_config", "arguments": {}}},
    {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
     "params": {"name": "get_all_states", "arguments": {"domain": "light"}}},
    {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
     "params": {"name": "get_areas", "arguments": {}}},
]

def emit(ok, desc):
    print(("PASS" if ok else "FAIL") + "|" + desc)

try:
    proc = subprocess.run(
        server,
        input="\n".join(json.dumps(r) for r in reqs) + "\n",
        capture_output=True, text=True, timeout=90,
    )
except Exception as exc:  # noqa: BLE001
    emit(False, f"MCP server did not run: {exc}")
    sys.exit(0)

resp = {}
for line in proc.stdout.splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        obj = json.loads(line)
    except json.JSONDecodeError:
        continue
    if isinstance(obj, dict) and "id" in obj:
        resp[obj["id"]] = obj

emit(resp.get(1, {}).get("result", {}).get("protocolVersion") == "2024-11-05",
     "initialize handshake")

tools = resp.get(2, {}).get("result", {}).get("tools", [])
names = {t.get("name") for t in tools}
emit(len(tools) >= 28, f"tools/list returned {len(tools)} tools")
emit("get_areas" in names, "get_areas tool registered (area-aware control)")

def tool_ok(call_id, label):
    r = resp.get(call_id, {})
    res = r.get("result", {})
    is_err = bool(res.get("isError")) or ("error" in r)
    emit(not is_err, label)
    if is_err:
        try:
            detail = res["content"][0]["text"]
        except Exception:  # noqa: BLE001
            detail = json.dumps(r)
        print("INFO|   ↳ " + " ".join(detail.split())[:200])

tool_ok(3, "tools/call get_ha_config")
tool_ok(4, "tools/call get_all_states(domain=light)")
tool_ok(5, "tools/call get_areas")

if proc.stderr.strip():
    last = proc.stderr.strip().splitlines()[-1]
    print("INFO|MCP stderr: " + last[:200])
PY
    )
fi

# --- 4. custom integration --------------------------------------------------
hdr "Home Assistant custom integration"
if [ -f "$INTEGRATION_DIR/manifest.json" ]; then
    ver=$(jq -r '.version // "?"' "$INTEGRATION_DIR/manifest.json" 2>/dev/null)
    pass "Integration deployed (v${ver})"
    if [ -f /config/.bruh_claude/restart_required ]; then
        warn "restart_required marker present — restart Home Assistant to load the new version"
    fi
else
    warn "Integration not deployed yet at $INTEGRATION_DIR (first install needs an HA restart)"
fi

# --- 5. background listeners ------------------------------------------------
hdr "Background listeners"
running() {
    if command -v pgrep >/dev/null 2>&1; then
        pgrep -f "$1" >/dev/null 2>&1
    else
        ps 2>/dev/null | grep -v grep | grep -q "$1"
    fi
}
if running assist-worker-pool; then
    pass "assist worker pool running (fast mode)"
elif running assist-listener; then
    pass "assist-listener running (classic mode)"
else
    warn "assist listener not running (disabled in config, or check the add-on log)"
fi
if running automation-listener; then
    pass "automation-listener running"
else
    warn "automation-listener not running (disabled in config, or check the add-on log)"
fi

# --- 5a. assist API (fast mode) ----------------------------------------------
hdr "Assist API (worker pool)"
api_health=$(curl -s -m 5 "http://127.0.0.1:8099/health" 2>/dev/null)
case "$api_health" in
    *'"status": "ok"'*|*'"status":"ok"'*)
        pass "Worker pool API healthy (:8099/health)"
        info "$(echo "$api_health" | head -c 160)"
        ;;
    "")
        warn "Worker pool API not responding (classic mode, or pool starting up)"
        ;;
    *)
        fail "Worker pool API responded abnormally: $(echo "$api_health" | head -c 160)"
        ;;
esac

# --- 5b. assist area map (voice fast-path) ----------------------------------
hdr "Assist area map (voice fast-path)"
AREA_MAP=/config/.bruh_claude/cache/area_map.txt
if [ -s "$AREA_MAP" ]; then
    map_age=$(( $(date +%s) - $(stat -c %Y "$AREA_MAP" 2>/dev/null || date +%s) ))
    pass "Area map cached ($(wc -c < "$AREA_MAP") bytes, ${map_age}s old)"
    info "$(head -2 "$AREA_MAP")"
else
    warn "Area map cache missing — every fresh voice command pays an extra discovery turn"
    # Probe the template engine the same way the listener renders the map.
    probe=$(curl -s -m 10 -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN:-}" \
        -H "Content-Type: application/json" \
        -d '{"template": "{{ areas() | count }}"}' \
        "${HA_BASE_URL}/template" 2>/dev/null)
    case "$probe" in
        ''|'{'*) fail "Template API probe failed: ${probe:-no response} — area map cannot render" ;;
        *)       info "Template API OK (${probe} areas) — map will be cached on the next voice request" ;;
    esac
fi

# --- 6. Claude auth & usage sensors ----------------------------------------
hdr "Claude login & usage sensors"
if [ -f "${HOME:-/data/home}/.claude/.credentials.json" ] \
    || [ -f /data/.config/claude/.credentials.json ]; then
    pass "Claude OAuth credentials found (logged in)"
else
    warn "No Claude credentials found — run 'claude' and complete login for Assist/automations"
fi
if [ -f "$USAGE_FILE" ]; then
    uerr=$(jq -r '.error // empty' "$USAGE_FILE" 2>/dev/null)
    if [ -n "$uerr" ]; then
        warn "Usage sensors unavailable: ${uerr} (needs OAuth/subscription login, not an API key)"
    else
        sess=$(jq -r '.five_hour.utilization // "?"' "$USAGE_FILE" 2>/dev/null)
        pass "Usage limits fetched (session ${sess}%)"
    fi
else
    info "Usage limits not fetched yet (tracker polls every ~2 min after login)"
fi

# --- summary ----------------------------------------------------------------
hdr "Summary"
printf '  %s%d passed%s, %s%d failed%s, %s%d warnings%s\n' \
    "$C_OK" "$PASS" "$C_RST" "$C_BAD" "$FAIL" "$C_RST" "$C_WARN" "$WARN" "$C_RST"
if [ "$FAIL" -gt 0 ]; then
    printf '  %sSome checks failed — see the hints above.%s\n' "$C_BAD" "$C_RST"
    exit 1
fi
printf '  %sAll critical checks passed.%s\n' "$C_OK" "$C_RST"
exit 0
