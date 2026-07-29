#!/bin/bash

# brain-study-watcher — run study sessions requested from Home Assistant.
#
# The `brain.study` service drops a JSON request on the shared volume; this
# picks it up and runs `brain learn`. Split that way because a study session
# can run for many minutes, which is far longer than a service call should
# block — so the service queues and returns, and whatever the session finds
# arrives through the memory inbox like everything else.
#
# Requests are claimed by rename before being run, so two passes can never
# execute the same one, and a request whose session dies is not retried
# forever — a study session is expensive, and silently re-running a failing
# one every minute is worse than dropping it.

set -uo pipefail

if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    . /data/.brain_env
fi

SHARED_DIR="${BRAIN_SHARED_DIR:-/config/.brain}"
REQUESTS_DIR="$SHARED_DIR/study_requests"
PROCESSED_DIR="$REQUESTS_DIR/processed"
LEARN_SCRIPT="${BRAIN_LEARN_SCRIPT:-/opt/scripts/brain-learn.sh}"

POLL_INTERVAL="${BRAIN_STUDY_POLL:-30}"
PROCESSED_PRUNE_DAYS=7

log() {
    echo "[brain-study] $*"
}

run_request() {
    local file="$1" topic claimed
    claimed="${file}.running"
    # Claim by rename: atomic, so a second pass can't pick up the same one.
    mv "$file" "$claimed" 2>/dev/null || return 0

    topic=$(jq -r '.topic // ""' "$claimed" 2>/dev/null)

    if [ -n "$topic" ]; then
        log "studying '${topic}' (requested from Home Assistant)"
        bash "$LEARN_SCRIPT" "$topic" 2>&1 | sed 's/^/[brain-study] /'
    else
        log "studying the stalest topic (requested from Home Assistant)"
        bash "$LEARN_SCRIPT" 2>&1 | sed 's/^/[brain-study] /'
    fi

    mkdir -p "$PROCESSED_DIR"
    mv "$claimed" "$PROCESSED_DIR/$(basename "$claimed")" 2>/dev/null || rm -f "$claimed"
    find "$PROCESSED_DIR" -type f -mtime +"$PROCESSED_PRUNE_DAYS" -delete 2>/dev/null || true
}

main() {
    if [ ! -f "$LEARN_SCRIPT" ]; then
        log "brain-learn.sh not present in this image — watcher not starting"
        exit 0
    fi

    mkdir -p "$REQUESTS_DIR"
    log "watcher started (polling ${REQUESTS_DIR} every ${POLL_INTERVAL}s)"

    # Let startup settle before the first pass: a study session launched
    # while the MCP server is still coming up just wastes a run.
    sleep 90

    while true; do
        for f in "$REQUESTS_DIR"/*.json; do
            [ -f "$f" ] || continue
            run_request "$f"
        done
        sleep "$POLL_INTERVAL"
    done
}

case "${1:-}" in
    --once)
        for f in "$REQUESTS_DIR"/*.json; do
            [ -f "$f" ] || continue
            run_request "$f"
        done
        ;;
    *)
        main
        ;;
esac
