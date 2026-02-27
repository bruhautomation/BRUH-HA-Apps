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
#
# Permissions:
#   This listener does NOT use --dangerously-skip-permissions. Instead, tool
#   permissions are granted via /config/.claude/settings.local.json, which
#   pre-approves all MCP, Bash, Read, Write, and Edit tools. This avoids the
#   root-user restrictions of the flag while still allowing non-interactive use.

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
SHARED_DIR="/config/.bruh_claude"
TASKS_DIR="$SHARED_DIR/tasks"
RESULTS_DIR="$SHARED_DIR/task_results"
LOG_DIR="$SHARED_DIR/logs"

# Automation tasks may need more turns than conversation requests (e.g.
# multi-step config edits), so allow a higher limit than the assist listener.
# Configurable via the add-on's automation_max_turns option.
MAX_TURNS="${BRUH_AUTOMATION_MAX_TURNS:-10}"

# Process-level timeout for claude -p commands (seconds).
# Automation tasks can be longer than conversation requests, so default is
# higher.  Without this, a hung MCP connection causes claude -p to block
# forever and no result file is ever written.
CLAUDE_TIMEOUT="${BRUH_AUTOMATION_TIMEOUT:-300}"

mkdir -p "$TASKS_DIR" "$RESULTS_DIR" "$LOG_DIR"

# Source the Claude environment written by run.sh
# This ensures HOME, ANTHROPIC_CONFIG_DIR, etc. are set correctly
# even when with-contenv shebang reloads the s6 container environment.
if [ -f /data/.bruh_claude_env ]; then
    # shellcheck disable=SC1091
    source /data/.bruh_claude_env
fi

# Resolve the claude binary (see assist-listener.sh for details).
CLAUDE_BIN="claude-run"
if [ ! -x /usr/local/bin/claude-run ]; then
    if [ "$(id -u)" = "0" ] && command -v su-exec >/dev/null 2>&1; then
        CLAUDE_BIN="su-exec claude /root/.local/bin/claude"
    fi
fi

bashio::log.info "Automation listener starting (UID=$(id -u), claude=$CLAUDE_BIN, max_turns=$MAX_TURNS, timeout=${CLAUDE_TIMEOUT}s)..."
bashio::log.info "Watching $TASKS_DIR for automation tasks"
bashio::log.info "Debug logs: $LOG_DIR/automation-*.log"

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

    # Log request for debugging
    local log_file="$LOG_DIR/automation-$(date +%Y%m%d).log"
    {
        echo "================================================================"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] TASK REQUEST $task_id"
        echo "  Channel:  automation"
        echo "  Prompt:   ${prompt:0:500}"
        echo "  Chars:    ${#prompt}"
        echo "  Notify:   $notify"
        echo "  MaxTurns: $MAX_TURNS"
    } >> "$log_file"

    local output_file stderr_file
    output_file=$(mktemp)
    stderr_file=$(mktemp)

    # Run Claude in print mode from /config so it finds .mcp.json for HA tools
    # and .claude/settings.local.json for pre-approved tool permissions.
    # --max-turns prevents runaway agentic loops.
    # No --dangerously-skip-permissions: permissions come from settings.local.json.
    local start_time
    start_time=$(date +%s)

    # shellcheck disable=SC2086
    (cd /config && printf '%s' "$prompt" | timeout "$CLAUDE_TIMEOUT" ${CLAUDE_BIN} -p --verbose --max-turns "$MAX_TURNS" > "$output_file" 2>"$stderr_file") || true

    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    local result stderr_output
    result=$(cat "$output_file" 2>/dev/null || echo "")
    stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
    rm -f "$output_file" "$stderr_file"

    # If result is empty, something went wrong — check stderr for clues
    if [ -z "$result" ]; then
        bashio::log.error "Empty result for task [$task_id] after ${duration}s"
        bashio::log.error "Stderr: ${stderr_output:0:500}"
        if [ "$duration" -ge "$((CLAUDE_TIMEOUT - 5))" ] 2>/dev/null; then
            result="Claude task timed out after ${duration}s. This may be caused by a broken MCP server connection. Try restarting the BRUH Claude Terminal add-on."
            bashio::log.error "Claude process timed out (limit=${CLAUDE_TIMEOUT}s)"
        elif echo "$stderr_output" | grep -qi "not logged in\|please log in\|authentication"; then
            result="Claude is not logged in. Please open the BRUH Claude Terminal sidebar and complete the OAuth login first."
        elif echo "$stderr_output" | grep -qi "permission\|not allowed\|denied"; then
            result="Claude encountered a permission error. Check the add-on logs for details."
        else
            result="Task failed — Claude didn't produce a result. Check the BRUH Claude Terminal add-on logs."
        fi
    fi

    # Log response for debugging
    {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] TASK RESPONSE $task_id"
        echo "  Duration: ${duration}s"
        echo "  Result:   ${#result} chars"
        if [ -n "$stderr_output" ]; then
            local token_info
            token_info=$(echo "$stderr_output" | grep -iE 'token|cost|usage|input|output' | head -5) || true
            if [ -n "$token_info" ]; then
                echo "  Tokens:   $token_info"
            fi
            echo "  Stderr:   ${stderr_output:0:500}"
        fi
        echo "  Preview:  ${result:0:200}"
        echo "----------------------------------------------------------------"
    } >> "$log_file"

    bashio::log.info "Task completed [$task_id]: ${duration}s, ${#result} chars"

    # Check for auth errors in the result text
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
