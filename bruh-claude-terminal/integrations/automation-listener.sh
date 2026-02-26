#!/usr/bin/with-contenv bashio

# Automation Integration Listener
# Allows Home Assistant automations to trigger Claude Code tasks
# Monitors a webhook/event for automation-driven Claude requests

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
TASK_DIR="/data/tasks"
AUTOMATION_DIR="/data/automation-tasks"

mkdir -p "$TASK_DIR" "$AUTOMATION_DIR"

bashio::log.info "Automation listener starting..."

# Process an automation task
process_automation_task() {
    local task_file="$1"
    local task_name
    task_name=$(basename "$task_file" .json)

    bashio::log.info "Processing automation task: $task_name"

    # Read task configuration
    local prompt
    prompt=$(jq -r '.prompt // empty' "$task_file" 2>/dev/null)

    local notify
    notify=$(jq -r '.notify // "false"' "$task_file" 2>/dev/null)

    local entity_id
    entity_id=$(jq -r '.notify_entity // empty' "$task_file" 2>/dev/null)

    if [ -z "$prompt" ]; then
        bashio::log.warning "Task $task_name has no prompt, skipping"
        return
    fi

    # Mark as processing
    mv "$task_file" "${task_file%.json}.processing"

    local output_file="$AUTOMATION_DIR/${task_name}.output"

    # Run Claude
    claude -p "$prompt" > "$output_file" 2>&1 || true

    local result
    result=$(cat "$output_file" 2>/dev/null || echo "Task failed")

    # Send notification if requested
    if [ "$notify" = "true" ] && [ -n "$entity_id" ]; then
        local message
        message=$(echo "$result" | head -10 | sed 's/"/\\"/g' | tr '\n' ' ')
        curl -s -X POST \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "{\"entity_id\": \"$entity_id\", \"message\": \"Claude task '$task_name' completed: $message\"}" \
            "http://supervisor/core/api/services/notify/persistent_notification" 2>/dev/null || true
    fi

    # Fire completion event
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"task_name\": \"$task_name\", \"status\": \"completed\"}" \
        "http://supervisor/core/api/events/bruh_claude_task_complete" 2>/dev/null || true

    # Clean up
    rm -f "${task_file%.json}.processing"
    touch "$AUTOMATION_DIR/${task_name}.done"

    bashio::log.info "Automation task completed: $task_name"
}

# Monitor for new automation tasks
listen_for_tasks() {
    bashio::log.info "Monitoring for automation tasks..."
    bashio::log.info "Drop JSON files in /data/automation-tasks/ to trigger Claude tasks"
    bashio::log.info "Format: {\"prompt\": \"...\", \"notify\": true, \"notify_entity\": \"notify.mobile_app\"}"

    while true; do
        # Check for new task files
        for task_file in "$AUTOMATION_DIR"/*.json 2>/dev/null; do
            if [ -f "$task_file" ]; then
                process_automation_task "$task_file" &
            fi
        done

        sleep 5
    done
}

# Main
listen_for_tasks
