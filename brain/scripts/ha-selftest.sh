#!/bin/bash
# brAIn — in-situ self-test
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
if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    . /data/.brain_env
fi

HA_BASE_URL="${HA_BASE_URL:-http://supervisor/core/api}"
MCP_SERVER="/opt/ha-mcp-server/ha_mcp_server.py"
INTEGRATION_DIR="/config/custom_components/brain"
MCP_CONFIG="/config/.mcp.json"
SETTINGS="/config/.claude/settings.local.json"
USAGE_FILE="/config/.brain/usage_limits.json"

# --- pretty output ----------------------------------------------------------
# `--json` turns the report into one JSON object on stdout (the same
# checks, the same order) so the panel, the health sensor and `brain report`
# read a verdict rather than scrape a transcript. Every line is recorded
# either way; only the printing changes.
JSON_MODE=0
for arg in "$@"; do
    [ "$arg" = "--json" ] && JSON_MODE=1
done
if [ -t 1 ] && [ "$JSON_MODE" = "0" ]; then
    C_OK=$'\033[32m'; C_BAD=$'\033[31m'; C_WARN=$'\033[33m'; C_DIM=$'\033[2m'; C_RST=$'\033[0m'
else
    C_OK=""; C_BAD=""; C_WARN=""; C_DIM=""; C_RST=""
fi
PASS=0; FAIL=0; WARN=0
CUR_SECTION=""
RECORDS=$(mktemp 2>/dev/null || echo "/tmp/brain-doctor-$$")
: > "$RECORDS"
# One record per line: kind, text, section — separated by a unit separator,
# a byte no check message contains, so a message may carry any punctuation.
record() { printf '%s\x1f%s\x1f%s\n' "$1" "$2" "$CUR_SECTION" >> "$RECORDS"; }
pass() { PASS=$((PASS + 1)); record pass "$1"; [ "$JSON_MODE" = "1" ] || printf '  %s✓%s %s\n' "$C_OK" "$C_RST" "$1"; }
fail() { FAIL=$((FAIL + 1)); record fail "$1"; [ "$JSON_MODE" = "1" ] || printf '  %s✗%s %s\n' "$C_BAD" "$C_RST" "$1"; }
warn() { WARN=$((WARN + 1)); record warn "$1"; [ "$JSON_MODE" = "1" ] || printf '  %s!%s %s\n' "$C_WARN" "$C_RST" "$1"; }
info() { record info "$1"; [ "$JSON_MODE" = "1" ] || printf '    %s%s%s\n' "$C_DIM" "$1" "$C_RST"; }
hdr()  { CUR_SECTION="$1"; [ "$JSON_MODE" = "1" ] || printf '\n%s%s%s\n' "$C_DIM" "$1" "$C_RST"; }

# The verdict as one JSON object. python3 is in the image and is what
# every other script here reaches for to emit JSON safely.
emit_json() {
    python3 - "$RECORDS" "$PASS" "$FAIL" "$WARN" <<'PYEMIT'
import json, sys, time
path, passed, failed, warned = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
checks = []
try:
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            parts = line.rstrip("\n").split("\x1f")
            if len(parts) >= 2:
                checks.append({"kind": parts[0], "text": parts[1],
                               "section": parts[2] if len(parts) > 2 else ""})
except OSError:
    pass
print(json.dumps({
    "ok": failed == 0,
    "passed": passed, "failed": failed, "warnings": warned,
    "generated_at": int(time.time()),
    "checks": checks,
}, indent=1))
PYEMIT
}

[ "$JSON_MODE" = "1" ] || printf '%s\n' "brAIn — self-test"

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

# Disk. A full /data fails in strange, distant ways — a transcript that
# stops persisting, a memory pass that exits 0 having written nothing — so
# it is named here, where the connection to the symptom is still visible.
for mount in /data /config; do
    used=$(df -P "$mount" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}')
    case "$used" in
        ''|*[!0-9]*) warn "could not read disk usage for $mount" ;;
        *)
            if [ "$used" -ge 95 ]; then
                fail "$mount is ${used}% full — writes are about to start failing silently"
            elif [ "$used" -ge 85 ]; then
                warn "$mount is ${used}% full"
            else
                pass "$mount has room (${used}% used)"
            fi
            ;;
    esac
done

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

# --- 3a. CLI tools ----------------------------------------------------------
# The MCP path above is validated end-to-end; without this section the CLI
# path shipped completely untested — which is how `column`-dependent commands
# reached production dead. One dependency sweep + one cheap smoke invocation
# per verb, asserting exit 0 AND non-empty output.
hdr "CLI tools (dependencies + smoke tests)"
missing_bins=""
for bin in curl jq awk sed find grep python3 git; do
    command -v "$bin" >/dev/null 2>&1 || missing_bins="$missing_bins $bin"
done
if [ -z "$missing_bins" ]; then
    pass "external binaries present (curl jq awk sed find grep python3 git)"
else
    fail "missing binaries:${missing_bins} — ha-* commands will break mid-pipeline"
fi

# The Claude CLI itself. Everything above can be green while the one binary
# the add-on exists to run is missing or broken — a bad self-update is
# exactly the strange bug this test is for.
if command -v claude >/dev/null 2>&1; then
    cli_ver=$(claude --version 2>&1 | head -1)
    if [ -n "$cli_ver" ]; then
        pass "Claude CLI runs ($cli_ver)"
    else
        fail "Claude CLI is installed but 'claude --version' said nothing"
    fi
else
    fail "Claude CLI not found — the terminal, chat, insights and listeners all need it"
fi

smoke() {
    local desc="$1"; shift
    if ! command -v "$1" >/dev/null 2>&1; then
        warn "smoke: $desc skipped ($1 not installed)"
        return
    fi
    local out rc
    out=$("$@" 2>&1); rc=$?
    if [ "$rc" -eq 0 ] && [ -n "$out" ]; then
        pass "smoke: $desc"
    else
        fail "smoke: $desc (exit ${rc})"
        info "   ↳ $(echo "$out" | tail -1 | head -c 160)"
    fi
}
smoke "ha entity list"          ha entity list
smoke "ha entity search sun"    ha entity search sun
smoke "ha addon list"           ha addon list
smoke "ha service list"         ha service list
# Validate a file that uses HA's custom tags — this is the exact shape that
# used to false-fail (yaml.safe_load doesn't know !secret/!include).
# busybox mktemp requires the template to END in Xs, and `ha check` only
# looks at *.yaml/*.yml files — so make a temp dir and name the file inside.
smoke_dir=$(mktemp -d /tmp/selftest-XXXXXX)
smoke_yaml="$smoke_dir/smoke.yaml"
printf 'homeassistant:\n  name: !secret home_name\nautomation: !include automations.yaml\n' > "$smoke_yaml"
smoke "ha check (HA tags)"      ha check "$smoke_yaml"
rm -rf "$smoke_dir"

# --- 3b. panel, chat & terminal ---------------------------------------------
# The panel is the ingress target — if it is down the add-on has no face at
# all — and the chat's state endpoint carries the error text of a session
# that failed to spawn, which is otherwise only in the add-on log.
hdr "Panel, chat & terminal"
panel_health=$(curl -s -m 5 "http://127.0.0.1:8099/api/health" 2>/dev/null)
if [ "$(echo "$panel_health" | jq -r '.ok // empty' 2>/dev/null)" = "true" ]; then
    pass "Panel answering (:8099/api/health)"
    # The panel's own roll-call of its sibling daemons. Section 5 below
    # pgreps the same processes from this shell; the panel's view is the
    # one an outside caller (or the HA integration) would see, so the two
    # disagreeing is itself a finding.
    consolidated_h=$(echo "$panel_health" \
        | jq -r '.daemons.memory_consolidator.last_pass_hours_ago // empty' 2>/dev/null)
    if [ -n "$consolidated_h" ]; then
        info "last memory consolidation landed ${consolidated_h}h ago"
    fi
    dead=$(echo "$panel_health" | jq -r \
        '.daemons // {} | to_entries | map(select(.value.running == false) | .key) | join(", ")' \
        2>/dev/null)
    if [ -n "$dead" ]; then
        info "panel reports not running: ${dead} (fine if disabled in config — section 5 interprets)"
    fi
else
    fail "Panel not answering (:8099/api/health) — check the add-on log"
fi

# The panel's own verdict on itself. This script walks the plumbing and the
# panel watches it over time, so the two answer different questions and both
# belong on one report: a doctor run at 9am cannot see the listener that died
# at 3am, and the verdict can.
diag=$(curl -s -m 10 "http://127.0.0.1:8099/api/diagnostics" 2>/dev/null)
health_state=$(echo "$diag" | jq -r '.health.state // empty' 2>/dev/null)
health_reason=$(echo "$diag" | jq -r '.health.reason // empty' 2>/dev/null)
case "$health_state" in
    ok)       pass "brAIn reports itself healthy" ;;
    degraded) warn "brAIn reports itself degraded: ${health_reason}" ;;
    failed)   fail "brAIn reports itself failed: ${health_reason}" ;;
    *)        info "the panel did not report a health verdict (older add-on?)" ;;
esac
if [ "$health_state" = "degraded" ] || [ "$health_state" = "failed" ]; then
    echo "$diag" | jq -r '.health.fix // empty' 2>/dev/null | while read -r line; do
        [ -n "$line" ] && info "$line"
    done
fi

chat_state=$(curl -s -m 5 "http://127.0.0.1:8099/api/chat/state" 2>/dev/null)
if [ -n "$chat_state" ]; then
    cstate=$(echo "$chat_state" | jq -r '.state // empty' 2>/dev/null)
    cerror=$(echo "$chat_state" | jq -r '.error // empty' 2>/dev/null)
    case "$cstate" in
        error)
            fail "Chat session in error state"
            info "   ↳ ${cerror:-no detail recorded}"
            ;;
        idle|ready|busy|starting)
            pass "Chat session state: ${cstate}"
            ;;
        "")
            fail "Chat state endpoint answered without a state: $(echo "$chat_state" | head -c 120)"
            ;;
        *)
            warn "Chat session in unexpected state '${cstate}'"
            ;;
    esac
else
    warn "Chat state endpoint not answering (panel down, or still starting)"
fi

# The terminal's credential gate. ttyd on 7681 must ask for a password —
# an unauthenticated 200 means a root shell with /config and a signed-in
# Claude is answering the LAN, which is the exact exposure the generated
# credential exists to close.
ttyd_code=$(curl -s -m 5 -o /dev/null -w '%{http_code}' \
    "http://127.0.0.1:7681/" 2>/dev/null)
case "$ttyd_code" in
    401)
        pass "Terminal credential gate on (:7681 asks for a password)"
        ;;
    200)
        fail "Terminal on :7681 answers WITHOUT a password — restart the add-on; report this if it persists"
        ;;
    ''|000)
        info "Terminal not answering on :7681 (enable_terminal off, or ttyd starting)"
        ;;
    *)
        warn "Terminal on :7681 answered HTTP ${ttyd_code} (expected 401)"
        ;;
esac

# --- 4. custom integration --------------------------------------------------
hdr "Home Assistant custom integration"
if [ -f "$INTEGRATION_DIR/manifest.json" ]; then
    ver=$(jq -r '.version // "?"' "$INTEGRATION_DIR/manifest.json" 2>/dev/null)
    pass "Integration deployed (v${ver})"
    if [ -f /config/.brain/restart_required ]; then
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
# The three daemons run.sh always starts. Unlike the listeners these have
# no config switch, so one missing is a crash, not a choice.
if running usage-limits-tracker; then
    pass "usage-limits tracker running"
else
    warn "usage-limits tracker not running — the usage sensors will go stale"
fi
if running brain-memory-consolidate; then
    pass "memory consolidator running"
else
    warn "memory consolidator not running — queued facts will never reach memory.md"
fi
if running brain-study-watcher; then
    pass "study watcher running"
else
    warn "study watcher not running — 'brain learn' requests will sit unprocessed"
fi

# --- 5c. memory & run-source plumbing ---------------------------------------
hdr "Memory & run-source plumbing"
# Written by root (the panel) AND the claude user (consolidator, study
# watcher) — so it must be claude-owned, or the claude half fails silently
# by design and the Chats rail slowly fills with machine runs labelled as
# yours. This is the exact failure that went unnoticed once already.
RUN_SOURCES=/data/run-sources.jsonl
if [ -e "$RUN_SOURCES" ]; then
    rs_owner=$(stat -c %u "$RUN_SOURCES" 2>/dev/null)
    if [ "$rs_owner" = "1000" ]; then
        pass "run-sources ledger claude-owned ($RUN_SOURCES)"
    else
        fail "run-sources ledger owned by uid ${rs_owner:-?}, not claude (1000) — background runs will show as yours in the Chats rail"
        info "Fix: chown claude:claude $RUN_SOURCES (run.sh does this at startup)"
    fi
else
    info "run-sources ledger not created yet (first background run makes it)"
fi
# Is a consolidation pass running right now — and if so, has it outlived any
# plausible one? Both questions are answered by PROBING THE FLOCK, and
# neither can be answered by the lock file at all.
#
# `with_lock` in brain-memory-consolidate.sh takes the lock with `exec 9>`
# and releases it with `exec 9>&-`, which drops the flock and leaves the file
# on disk for good. So its presence means "a pass has run at some point" and
# its mtime means "when the last pass started" — and this check used to stat
# that mtime and warn past 900s, which fires on every home that has not
# consolidated in the last quarter of an hour, i.e. nearly every run. Worse,
# the remedy it named could not work: it sent people to restart the add-on
# over a file under /config, which survives the restart, so the warning came
# back and taught them to stop reading the report. The panel has always asked
# the right question (`_consolidation_running()` in server.py) and this is the
# same probe in shell.
#
# It also means a warning here is worth acting on: an flock dies with the
# process holding it, so a lock held past any plausible pass is a live
# process genuinely stuck, and restarting really is the remedy.
consolidator_lock_check() {
    local dir="${BRAIN_MEMORY_DIR:-/config/.brain/memory}"
    local lock="$dir/.consolidate.lock"
    local marker="$dir/.consolidating"
    local stamp="$dir/.last_consolidated"
    local now started age mins ago pending probe rc=0

    now=$(date +%s)
    # When a pass last LANDED. This is the number people were reading the
    # lock's age as, and it lives in a different file.
    if [ -e "$stamp" ]; then
        mins=$(( (now - $(stat -c %Y "$stamp" 2>/dev/null || echo "$now")) / 60 ))
        ago="${mins}m"
        [ "$mins" -ge 120 ] && ago="$((mins / 60))h"
        info "last consolidation landed ${ago} ago"
        # A queue nothing has filed for longer than a day is the failure the
        # old check was pretending to look for: the daemon consolidates
        # daily, so anything past 26h is a consolidator that is not working,
        # not a busy one. Same threshold the panel's stale-queue check uses.
        pending=$(cat "$dir/inbox"/*.jsonl 2>/dev/null | grep -c . || true)
        if [ "${pending:-0}" -gt 0 ] && [ "$mins" -gt 1560 ]; then
            warn "${pending} fact(s) have been queued for ${ago} with nothing filing them — check the add-on log for the consolidator"
        fi
    fi

    [ -e "$lock" ] || { info "no consolidator lock file yet (no pass has run)"; return; }
    # Unreadable is its own answer, not contention — the probe below opens the
    # file, and a refusal to open must not be reported as somebody holding it.
    [ -r "$lock" ] || { info "consolidator lock not readable as $(id -un) — cannot tell whether a pass is running"; return; }
    command -v flock > /dev/null 2>&1 || {
        info "no flock in this image — the consolidator runs unlocked here"
        return
    }

    # Ask whether flock can do what we are about to ask of it, on a scratch
    # file, before reading a refusal as contention. That confusion is the
    # exact bug that once stopped memory updating at all: BusyBox answers an
    # unsupported flag with the same exit status as "the lock is held".
    probe=$(mktemp 2>/dev/null) || probe=""
    if [ -n "$probe" ]; then
        ( exec 8< "$probe" && flock -sn 8 ) > /dev/null 2>&1 || rc=1
        rm -f "$probe"
        if [ "$rc" -ne 0 ]; then
            info "flock is unusable in this image — the consolidator runs unlocked here"
            return
        fi
    fi

    # A SHARED, non-blocking probe: shared so that asking the question can
    # never be something a real pass blocks on, non-blocking so this check
    # cannot become the stall it is looking for. Read-only `9<` and never
    # `9>`, which would truncate the holder's lock file at open.
    if ( exec 9< "$lock" && flock -sn 9 ) > /dev/null 2>&1; then
        pass "consolidator lock free (no pass in flight)"
        return
    fi

    # Held, so a pass really is running. `.consolidating` is stamped after
    # the lock is taken and removed when the pass ends, so while the lock is
    # held its mtime is that pass's own start.
    started=0
    [ -e "$marker" ] && started=$(stat -c %Y "$marker" 2>/dev/null || echo 0)
    if [ "$started" -gt 0 ]; then
        age=$(( now - started ))
        if [ "$age" -gt 900 ]; then
            warn "a consolidation pass has held the lock for ${age}s (one caps at ~480s) — it is stuck; restart the add-on and report this"
        else
            info "a consolidation pass is running (${age}s so far)"
        fi
    else
        info "a consolidation pass is running (just started)"
    fi
}
consolidator_lock_check
MEMORY_DOC="${BRAIN_MEMORY_DIR:-/config/.brain/memory}/memory.md"
if [ -s "$MEMORY_DOC" ]; then
    pass "memory.md present ($(wc -c < "$MEMORY_DOC") bytes)"
else
    info "memory.md not written yet (facts appear after the first consolidation)"
fi

# --- 5a. assist API (fast mode) ----------------------------------------------
hdr "Assist API (worker pool)"
# Send the pool token when readable: unauthenticated /health only returns
# liveness, the full telemetry (worker counts etc.) is token-gated.
pool_token=""
[ -r /config/.brain/api_token ] && pool_token=$(cat /config/.brain/api_token 2>/dev/null)
# Read the port the pool published rather than assuming one. It moved from
# 8099 to 8098 when the panel took the ingress port, and a probe pinned to
# the old number reaches the PANEL — which answers, with a 404, so the
# check fails while the pool is perfectly healthy.
pool_port=8098
if [ -r /config/.brain/api_endpoint.json ]; then
    pool_port=$(jq -r '.port // 8098' /config/.brain/api_endpoint.json 2>/dev/null || echo 8098)
fi
api_health=$(curl -s -m 5 -H "X-BRUH-Token: ${pool_token}" "http://127.0.0.1:${pool_port}/health" 2>/dev/null)
case "$api_health" in
    *'"status": "ok"'*|*'"status":"ok"'*)
        pass "Worker pool API healthy (:${pool_port}/health)"
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
AREA_MAP=/config/.brain/cache/area_map.txt
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
# All three stores, in the order engine.get_auth and brain-auth-env walk
# them. Checking only the CLI's own file reports a panel sign-in as "not
# logged in", which is the exact misdiagnosis this self-test exists to avoid.
auth_where=""
for candidate in \
    "${CLAUDE_CONFIG_DIR:-/nonexistent}/.credentials.json:Claude CLI" \
    "${HOME:-/data/home}/.claude/.credentials.json:Claude CLI" \
    "/data/.config/claude/.credentials.json:Claude CLI" \
    "${BRAIN_SECRETS:-/data/secrets}/claude_auth.json:panel sign-in" \
    "${BRAIN_SHARED_AUTH:-/config/.brain/secrets/claude_auth.json}:ha login"; do
    if [ -s "${candidate%:*}" ]; then
        auth_where="${candidate##*:}"
        break
    fi
done
if [ -n "$auth_where" ]; then
    pass "Claude credentials found (${auth_where})"
else
    warn "No Claude credentials found — sign in from the panel, run 'claude', or use 'ha login'"
fi
# The CLI's own credential outranks the others for the terminal, so a dead
# one there is worth naming even when a working credential exists elsewhere:
# that combination is exactly "the chat works but the terminal asks me to
# log in", and nothing else in the output would say so.
cli_cred="${CLAUDE_CONFIG_DIR:-${HOME:-/data/home}/.claude}/.credentials.json"
[ -r "$cli_cred" ] || cli_cred="${HOME:-/data/home}/.claude/.credentials.json"
if [ -r "$cli_cred" ]; then
    exp=$(jq -r '.claudeAiOauth.expiresAt // 0' "$cli_cred" 2>/dev/null)
    case "$exp" in
        ''|0|null) info "Claude CLI credential records no expiry" ;;
        *)
            if [ "$((exp / 1000))" -le "$(date +%s)" ]; then
                warn "The Claude CLI's own credential EXPIRED $(date -d "@$((exp / 1000))" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "at ${exp}") — the terminal prefers this one, so it will keep asking you to log in"
                info "Fix: rm -f '$cli_cred' /data/.brain_auth_backup/.credentials.json && restart (the backup restores it otherwise)"
            else
                info "Claude CLI credential valid until $(date -d "@$((exp / 1000))" '+%Y-%m-%d %H:%M' 2>/dev/null || echo "${exp}")"
            fi
            ;;
    esac
fi
if [ -f "$USAGE_FILE" ]; then
    uerr=$(jq -r '.error // empty' "$USAGE_FILE" 2>/dev/null)
    if [ "$uerr" = "api_key_has_no_usage_limits" ]; then
        warn "Usage sensors need a subscription login — an API key bills per token and has no usage window"
    elif [ -n "$uerr" ]; then
        warn "Usage sensors unavailable: ${uerr}"
        udetail=$(jq -r '.detail // empty' "$USAGE_FILE" 2>/dev/null)
        [ -n "$udetail" ] && info "   ↳ $udetail"
    else
        sess=$(jq -r '.five_hour.utilization // "?"' "$USAGE_FILE" 2>/dev/null)
        # Readings expire after two hours (usage_store applies the same
        # window), so a stale file means the sensors are about to blank —
        # the tracker died, or every poll is failing quietly.
        usage_age=$(( $(date +%s) - $(stat -c %Y "$USAGE_FILE" 2>/dev/null || date +%s) ))
        if [ "$usage_age" -gt 7200 ]; then
            warn "Usage reading is ${usage_age}s old (expires at 7200s) — the tracker may have died; check the add-on log"
        else
            pass "Usage limits fetched (session ${sess}%, ${usage_age}s old)"
        fi
    fi
else
    info "Usage limits not fetched yet (the tracker polls every 30 min after login)"
fi

# --- summary ----------------------------------------------------------------
if [ "$JSON_MODE" = "1" ]; then
    emit_json
    rm -f "$RECORDS"
    [ "$FAIL" -gt 0 ] && exit 1
    exit 0
fi
rm -f "$RECORDS"
hdr "Summary"
printf '  %s%d passed%s, %s%d failed%s, %s%d warnings%s\n' \
    "$C_OK" "$PASS" "$C_RST" "$C_BAD" "$FAIL" "$C_RST" "$C_WARN" "$WARN" "$C_RST"
if [ "$FAIL" -gt 0 ]; then
    printf '  %sSome checks failed — see the hints above.%s\n' "$C_BAD" "$C_RST"
    exit 1
fi
printf '  %sAll critical checks passed.%s\n' "$C_OK" "$C_RST"
exit 0
