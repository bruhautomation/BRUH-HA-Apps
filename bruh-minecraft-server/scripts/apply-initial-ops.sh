#!/bin/bash
# ============================================================================
# apply-initial-ops.sh
# ----------------------------------------------------------------------------
# Run in the background after the Minecraft JVM launches. Waits for RCON to
# come online, then issues `op <name>` for every name in $INITIAL_OPS (a
# newline-separated string supplied by run.sh from the `initial_ops` config
# option). Using RCON instead of writing ops.json directly lets the server
# handle the UUID lookup — works cleanly in both online and offline mode.
#
# Environment:
#   INITIAL_OPS  newline-separated list of player names, possibly empty
#   ALLOW_CHEATS "true" prints a friendly reminder in the log
# ============================================================================
set -o pipefail

SCRIPTS_DIR="$(cd "$(dirname "${0}")" && pwd)"
RCON_CLI="python3 ${SCRIPTS_DIR}/rcon.py"

log() { printf '[initial-ops %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

if [ -z "${INITIAL_OPS:-}" ]; then
    if [ "${ALLOW_CHEATS:-false}" = "true" ]; then
        log "allow_cheats is on, but initial_ops is empty."
        log "OP yourself from the panel → Players tab once you've joined."
    fi
    exit 0
fi

log "Waiting up to 180s for RCON to accept commands"
deadline=$(( $(date +%s) + 180 ))
while [ "$(date +%s)" -lt "${deadline}" ]; do
    if ${RCON_CLI} "list" >/dev/null 2>&1; then
        log "RCON ready"
        break
    fi
    sleep 2
done

if [ "$(date +%s)" -ge "${deadline}" ]; then
    log "RCON never came online — skipping initial OP application"
    exit 0
fi

while IFS= read -r name; do
    name="${name//[[:space:]]/}"
    [ -z "${name}" ] && continue
    # Minecraft usernames are 1-16 chars, alphanumeric+underscore; refuse
    # anything else so we never pass arbitrary input into an RCON command.
    if ! printf '%s' "${name}" | grep -Eq '^[A-Za-z0-9_]{1,16}$'; then
        log "Skipping invalid name: ${name}"
        continue
    fi
    reply=$(${RCON_CLI} "op ${name}" 2>&1 || true)
    log "op ${name} → ${reply}"
done <<< "${INITIAL_OPS}"

log "Initial OPs applied"
