#!/usr/bin/with-contenv bashio

# Automation Integration Listener
# Allows Home Assistant automations to trigger Claude Code tasks
#
# Communication with the HA custom integration uses a shared file directory:
#   /config/.bruh_claude/tasks/        - incoming task requests (JSON)
#   /config/.bruh_claude/task_results/ - outgoing task results (JSON)
#
# Request format:  {"id": "<uuid>", "prompt": "...", "notify": true, "notify_entity": "notify.mobile_app"}
# Response format: {"id": "<uuid>", "result": "claude output", "status": "completed"}

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
SHARED_DIR="/config/.bruh_claude"
TASKS_DIR="$SHARED_DIR/tasks"
RESULTS_DIR="$SHARED_DIR/task_results"

mkdir -p "$TASKS_DIR" "$RESULTS_DIR"

# Source the Claude environment written by run.sh
# This ensures HOME, ANTHROPIC_CONFIG_DIR, etc. are set correctly
# even when with-contenv shebang reloads the s6 container environment.
if [ -f /data/.bruh_claude_env ]; then
    # shellcheck disable=SC1091
    source /data/.bruh_claude_env
fi

bashio::log.info "Automation listener starting..."
bashio::log.info "Watching $TASKS_DIR for automation tasks"

# Process an automation task file
process_task() {
    local task_file="$1"
    local task_id
    local prompt
    local notify
    local notify_entity

    task_id=$(jq -r '.id // empty' "$task_file" 2>/dev/null)
    prompt=$(jq -r '.prompt // empty' "$task_file" 2>/dev/null)
    notify=$(jq -r '.notify // false' "$task_file" 2>/dev/null)
    notify_entity=$(jq -r '.notify_entity // empty' "$task_file" 2>/dev/null)

    if [ -z "$task_id" ] || [ -z "$prompt" ]; then
        bashio::log.warning "Invalid task file: $task_file"
        rm -f "$task_file"
        return
    fi

    bashio::log.info "Processing task [$task_id]: ${prompt:0:80}..."

    # Remove task file immediately
    rm -f "$task_file"

    local output_file
    output_file=$(mktemp)

    # Run Claude with --dangerously-skip-permissions for non-interactive use
    printf '%s' "$prompt" | claude -p --dangerously-skip-permissions > "$output_file" 2>&1 || true

    local result
    result=$(cat "$output_file" 2>/dev/null || echo "Task failed")
    rm -f "$output_file"

    # Check for auth errors and return a helpful message
    if echo "$result" | grep -qi "not logged in\|please log in\|authentication required"; then
        result="Claude is not logged in. Please open the BRUH Claude Terminal sidebar and complete the OAuth login first."
        bashio::log.error "Claude auth error - user needs to log in via the terminal"
    fi

    # Write result file (atomic via tmp + rename)
    local result_file="$RESULTS_DIR/${task_id}.json"
    local tmp_file="${result_file}.tmp"
    jq -n --arg id "$task_id" --arg result "$result" --arg status "completed" \
        '{"id": $id, "result": $result, "status": $status}' > "$tmp_file"
    mv "$tmp_file" "$result_file"

    bashio::log.info "Task completed [$task_id]"

    # Send notification if requested
    if [ "$notify" = "true" ] && [ -n "$notify_entity" ]; then
        local message
        message=$(echo "$result" | head -10 | tr '\n' ' ')
        local notify_payload
        notify_payload=$(jq -n \
            --arg entity "$notify_entity" \
            --arg msg "Claude task completed: ${message}" \
            '{"entity_id": $entity, "message": $msg}')
        curl -s -X POST \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "$notify_payload" \
            "http://supervisor/core/api/services/notify/persistent_notification" 2>/dev/null || true
    fi

    # Fire completion event on the HA event bus
    local event_payload
    event_payload=$(jq -n \
        --arg id "$task_id" \
        --arg status "completed" \
        '{"task_id": $id, "status": $status}')
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$event_payload" \
        "http://supervisor/core/api/events/bruh_claude_task_complete" 2>/dev/null || true
}

# Watch for new task files
listen_for_tasks() {
    if command -v inotifywait >/dev/null 2>&1; then
        bashio::log.info "Using inotifywait for efficient file watching"

        # Process any files that arrived before we started watching
        for task_file in "$TASKS_DIR"/*.json; do
            [ -f "$task_file" ] || continue
            process_task "$task_file" &
        done

        # Watch for new files
        inotifywait -m -e close_write -e moved_to --format '%w%f' "$TASKS_DIR" 2>/dev/null | while read -r filepath; do
            case "$filepath" in
                *.json)
                    process_task "$filepath" &
                    ;;
            esac
        done
    else
        bashio::log.info "inotifywait not available, falling back to polling (5s)"

        while true; do
            for task_file in "$TASKS_DIR"/*.json; do
                [ -f "$task_file" ] || continue
                process_task "$task_file" &
            done
            sleep 5
        done
    fi
}

# Main
listen_for_tasks
