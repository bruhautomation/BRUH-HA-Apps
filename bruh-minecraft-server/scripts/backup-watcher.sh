#!/bin/bash
# Periodically invoke backup.sh on a fixed interval.
# The interval is read once at start — change the add-on option and restart
# the add-on to take effect.

set -o pipefail

SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
INTERVAL_MIN="${BACKUP_INTERVAL_MINUTES:-60}"
SLEEP_SEC=$(( INTERVAL_MIN * 60 ))

# Wait one full interval on boot so the server is online first
sleep "${SLEEP_SEC}"

while true; do
    if ! "${SCRIPTS_DIR}/backup.sh"; then
        echo "[backup-watcher] backup failed" >&2
    fi
    sleep "${SLEEP_SEC}"
done
