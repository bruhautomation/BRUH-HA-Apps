#!/bin/bash
# ============================================================================
# server-launcher.sh
# ----------------------------------------------------------------------------
# Runs the JVM in the foreground. Stdin is attached to a named FIFO so the
# ingress panel can inject commands without touching the JVM process directly.
# Stdout is tee'd to console.log for the panel log viewer.
# ============================================================================

set -o pipefail

MC_SERVER_DIR="${MC_SERVER_DIR:-/config/minecraft}"
MC_PANEL_STATE="${MC_PANEL_STATE:-/data/panel}"
MC_INPUT_FIFO="${MC_INPUT_FIFO:-/tmp/mc-stdin.fifo}"
MC_CONSOLE_LOG="${MC_CONSOLE_LOG:-${MC_PANEL_STATE}/console.log}"
MEMORY_MB="${MEMORY_MB:-2048}"
USE_AIKAR_FLAGS="${USE_AIKAR_FLAGS:-true}"
EXTRA_JVM_ARGS="${EXTRA_JVM_ARGS:-}"
SERVER_TYPE="${SERVER_TYPE:-paper}"

log() { printf '[server-launcher] %s\n' "$*" >&2; }

cd "${MC_SERVER_DIR}" || {
    log "Server directory missing: ${MC_SERVER_DIR}"
    exit 1
}

[ -s "${MC_SERVER_DIR}/server.jar" ] || {
    log "server.jar is missing; cannot start"
    exit 1
}

# Aikar-style G1GC flags — widely regarded as the best-practice tuning for
# Minecraft servers. Reference: https://docs.papermc.io/paper/aikars-flags
build_aikar_flags() {
    local xms="${MEMORY_MB}M"
    local xmx="${MEMORY_MB}M"
    local flags=(
        -Xms"${xms}" -Xmx"${xmx}"
        -XX:+UseG1GC
        -XX:+ParallelRefProcEnabled
        -XX:MaxGCPauseMillis=200
        -XX:+UnlockExperimentalVMOptions
        -XX:+DisableExplicitGC
        -XX:+AlwaysPreTouch
        -XX:G1HeapWastePercent=5
        -XX:G1MixedGCCountTarget=4
        -XX:InitiatingHeapOccupancyPercent=15
        -XX:G1MixedGCLiveThresholdPercent=90
        -XX:G1RSetUpdatingPauseTimePercent=5
        -XX:SurvivorRatio=32
        -XX:+PerfDisableSharedMem
        -XX:MaxTenuringThreshold=1
        -Dusing.aikars.flags=https://mcflags.emc.gs
        -Daikars.new.flags=true
    )
    if [ "${MEMORY_MB}" -ge 12288 ]; then
        flags+=(-XX:G1NewSizePercent=40 -XX:G1MaxNewSizePercent=50 \
                -XX:G1HeapRegionSize=16M -XX:G1ReservePercent=15)
    else
        flags+=(-XX:G1NewSizePercent=30 -XX:G1MaxNewSizePercent=40 \
                -XX:G1HeapRegionSize=8M -XX:G1ReservePercent=20)
    fi
    printf '%s\n' "${flags[@]}"
}

build_basic_flags() {
    printf -- '-Xms%dM\n-Xmx%dM\n-XX:+UseG1GC\n' "${MEMORY_MB}" "${MEMORY_MB}"
}

mapfile -t JVM_FLAGS < <( \
    if [ "${USE_AIKAR_FLAGS}" = "true" ]; then build_aikar_flags; else build_basic_flags; fi \
)
# Shell-split extra JVM args safely
IFS=' ' read -ra EXTRA_ARGS <<< "${EXTRA_JVM_ARGS}"

# Ensure FIFOs exist (created by run.sh but be defensive)
[ -p "${MC_INPUT_FIFO}" ] || mkfifo -m 0660 "${MC_INPUT_FIFO}"

# Rotate the console log on launch so it doesn't grow without bound
if [ -f "${MC_CONSOLE_LOG}" ] && [ "$(stat -c%s "${MC_CONSOLE_LOG}" 2>/dev/null || echo 0)" -gt 10485760 ]; then
    mv "${MC_CONSOLE_LOG}" "${MC_CONSOLE_LOG}.1"
fi
: > "${MC_CONSOLE_LOG}"

log "JVM flags: ${JVM_FLAGS[*]}"
log "Memory: ${MEMORY_MB}MB   Server type: ${SERVER_TYPE}"

# Pick launch target per server type
LAUNCH_TARGET=(-jar server.jar nogui)
case "${SERVER_TYPE}" in
    forge)
        # Newer Forge releases ship a user_jvm_args.txt + run.sh. Prefer the
        # jar that exists at server.jar (symlink installed by download-server.sh).
        LAUNCH_TARGET=(-jar server.jar nogui)
        ;;
esac

# Persist PID so graceful_shutdown can signal the JVM from run.sh
printf '%s' "$$" > "${MC_PANEL_STATE}/launcher.pid"

# Open the input FIFO on FD 3 so writers don't get EOF'd between commands
exec 3<> "${MC_INPUT_FIFO}"

# Run the JVM. Panel appends commands to MC_INPUT_FIFO; JVM sees them on stdin.
# tee forwards everything the JVM prints to the console log ring-buffer.
java "${JVM_FLAGS[@]}" "${EXTRA_ARGS[@]}" "${LAUNCH_TARGET[@]}" <&3 2>&1 \
    | tee -a "${MC_CONSOLE_LOG}"
rc=${PIPESTATUS[0]}

exec 3<&-
rm -f "${MC_PANEL_STATE}/launcher.pid"

exit "${rc}"
