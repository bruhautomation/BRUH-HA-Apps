#!/usr/bin/with-contenv bashio

# ha-backup-watcher - Background process that auto-commits /config changes
# Runs as a background daemon started by run.sh

set -e

INTERVAL_MINUTES="${1:-30}"
INTERVAL_SECONDS=$((INTERVAL_MINUTES * 60))
CONFIG_DIR="/config"

bashio::log.info "Backup watcher started (interval: ${INTERVAL_MINUTES}m)"

# Wait for initial setup to complete
sleep 30

while true; do
    if [ -d "$CONFIG_DIR/.git" ]; then
        # Check for changes (use git -C instead of cd)
        changes=$(git -C "$CONFIG_DIR" status --porcelain 2>/dev/null || echo "")

        if [ -n "$changes" ]; then
            # Count changed files
            change_count=$(echo "$changes" | wc -l)
            timestamp=$(date '+%Y-%m-%d %H:%M:%S')

            # Get a summary of what changed
            changed_files=$(echo "$changes" | awk '{print $2}' | head -5 | tr '\n' ', ' | sed 's/,$//')

            git -C "$CONFIG_DIR" add -A 2>/dev/null || true
            git -C "$CONFIG_DIR" commit -m "Auto-backup: ${change_count} file(s) changed (${timestamp})" \
                -m "Files: ${changed_files}" 2>/dev/null || true

            # Plain commits never garbage-collect; without this the repo
            # accumulates loose objects forever (observed: 3000+, never packed).
            git -C "$CONFIG_DIR" gc --auto --quiet 2>/dev/null || true

            bashio::log.info "Auto-backup: ${change_count} file(s) committed"
        fi
    fi

    sleep "$INTERVAL_SECONDS"
done
