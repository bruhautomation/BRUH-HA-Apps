#!/usr/bin/with-contenv bashio

# Automation Integration Listener
# Allows Home Assistant automations to trigger Claude Code tasks
#
# Communication with the HA custom integration uses a shared file directory:
#   /config/.brain/tasks/        - incoming task requests (JSON)
#   /config/.brain/task_results/ - outgoing task results (JSON)
#
# Request format:  {"id": "<uuid>", "prompt": "...", "notify": true,
#                   "notify_entity": "notify.mobile_app", "ts": <epoch>,
#                   "timeout": <secs>}
# Response format: {"id": "<uuid>", "result": "claude output", "status": "completed"}
#
# The integration sends the window it will wait ("timeout") with each task;
# the listener keeps the claude process comfortably inside that window so a
# result is always written before the bridge stops polling.
#
# Permissions:
#   This listener does NOT use --dangerously-skip-permissions. Instead, tool
#   permissions are granted via /config/.claude/settings.local.json, which
#   pre-approves all MCP, Bash, Read, Write, and Edit tools. This avoids the
#   root-user restrictions of the flag while still allowing non-interactive use.

set -e

# Source the Claude environment written by run.sh — FIRST, before anything
# below copies a BRAIN_* option into a local name. The `with-contenv` shebang
# reloads the s6 container environment and drops the exports run.sh made, so
# this file is the only route an add-on option has into a listener.
#
# Order is load-bearing. A `${BRAIN_x:-default}` that runs before the source
# freezes the fallback: the value arrives afterwards under its own name, but
# the local alias already holds the default and nothing reads it again. That
# is not a variable that is missing, it is a variable that is late — which is
# why it went unnoticed for so long. `automation_max_turns` was pinned to 10
# for everyone, whatever the option said, and the only visible trace was the
# `MaxTurns:` line in the task log.
if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    source /data/.brain_env
fi

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
SHARED_DIR="/config/.brain"
TASKS_DIR="$SHARED_DIR/tasks"
RESULTS_DIR="$SHARED_DIR/task_results"
LOG_DIR="$SHARED_DIR/logs"

# Automation tasks may need more turns than conversation requests (e.g.
# multi-step config edits), so allow a higher limit than the assist listener.
# Configurable via the add-on's automation_max_turns option; the fallback
# matches that option's default in config.yaml on purpose. A fallback that
# disagrees with the shipped default is a second answer to one question, and
# the one that wins is the one nobody configured.
MAX_TURNS="${BRAIN_AUTOMATION_MAX_TURNS:-30}"

# Default process-level timeout for claude -p commands (seconds), used when a
# task doesn't carry its own timeout. The integration's task default (300s)
# matches this; per-task timeouts in the payload always take precedence.
CLAUDE_TIMEOUT="${BRAIN_AUTOMATION_TIMEOUT:-300}"

# Subtracted from a task's bridge timeout to get the claude process limit,
# leaving room to write the result file before the bridge gives up.
TIMEOUT_MARGIN=15

mkdir -p "$TASKS_DIR" "$RESULTS_DIR" "$LOG_DIR"

# Lets a task's transcript be labelled "Automation" in the Chats rail
# instead of sitting there looking like something you typed. Optional: an
# image without it just leaves tasks unlabelled.
if [ -r /opt/scripts/brain-run-source.sh ]; then
    # shellcheck disable=SC1091
    source /opt/scripts/brain-run-source.sh
fi

# Resolve the claude binary (see assist-listener.sh for details).
CLAUDE_BIN="claude-run"
if [ ! -x /usr/local/bin/claude-run ]; then
    if [ "$(id -u)" = "0" ] && command -v su-exec >/dev/null 2>&1; then
        CLAUDE_BIN="su-exec claude /root/.local/bin/claude"
    fi
fi

bashio::log.info "Automation listener starting (UID=$(id -u), claude=$CLAUDE_BIN, max_turns=$MAX_TURNS, default_timeout=${CLAUDE_TIMEOUT}s)..."
bashio::log.info "Watching $TASKS_DIR for automation tasks"
bashio::log.info "Debug logs: $LOG_DIR/automation-*.log"

# ---------------------------------------------------------------------------
# MCP config verification
# ---------------------------------------------------------------------------

# Fast check used on the hot path before each Claude invocation: only the
# canonical project config, a single grep on a tiny file.
verify_mcp_config_fast() {
    local mcp_file="/config/.mcp.json"

    if [ ! -f "$mcp_file" ]; then
        bashio::log.warning "MCP config missing: $mcp_file — Claude may lack HA tools"
        return
    fi

    if grep -q "/api/mcp\|homeassistant-config" "$mcp_file" 2>/dev/null; then
        bashio::log.warning "Stale MCP entry found in $mcp_file — rewriting clean config"
        cat > "$mcp_file" << 'MCP_CLEAN'
{
  "mcpServers": {
    "home-assistant": {
      "command": "python3",
      "args": ["/opt/ha-mcp-server/ha_mcp_server.py"]
    }
  }
}
MCP_CLEAN
        chown claude:claude "$mcp_file" 2>/dev/null || true
        chmod 644 "$mcp_file"
        bashio::log.info "MCP config restored to clean state"
    fi
}

# Deep cleanup of every config a broken marketplace plugin can poison.
# Runs at startup and after an /api/mcp error is detected — NOT per task
# (the find over ~/.claude/projects grows with session count).
verify_mcp_config_full() {
    verify_mcp_config_fast

    # Check ~/.claude.json — the most common hiding spot for stale /api/mcp
    # entries added by marketplace plugins.
    local claude_json="/data/home/.claude.json"
    if [ -f "$claude_json" ] && grep -q "/api/mcp\|homeassistant-config\|claude-homeassistant-plugins" "$claude_json" 2>/dev/null; then
        bashio::log.warning "Stale MCP entry in ~/.claude.json — cleaning"
        local tmp
        tmp=$(mktemp)
        if jq '
            if .mcpServers then
                .mcpServers |= with_entries(
                    select(
                        .key != "homeassistant-config" and
                        ((.value | tostring) | contains("/api/mcp") | not) and
                        ((.value | tostring) | contains("claude-homeassistant-plugins") | not)
                    )
                )
            else . end
        ' "$claude_json" > "$tmp" 2>/dev/null; then
            mv "$tmp" "$claude_json"
            chown claude:claude "$claude_json" 2>/dev/null || true
            bashio::log.info "~/.claude.json cleaned"
        else
            rm -f "$tmp"
        fi
    fi

    # Also check Claude Code's project-level configs for /api/mcp entries
    local claude_projects="/data/home/.claude/projects"
    if [ -d "$claude_projects" ]; then
        find "$claude_projects" -name "*.json" -type f -print0 2>/dev/null | \
        while IFS= read -r -d '' f; do
            if grep -q "/api/mcp" "$f" 2>/dev/null; then
                bashio::log.warning "Stale /api/mcp in project config: $f — cleaning"
                local tmp
                tmp=$(mktemp)
                if jq '
                    if .mcpServers then
                        .mcpServers |= with_entries(
                            select((.value | tostring) | contains("/api/mcp") | not)
                        )
                    else . end
                ' "$f" > "$tmp" 2>/dev/null; then
                    mv "$tmp" "$f"
                    chown claude:claude "$f" 2>/dev/null || true
                else
                    rm -f "$tmp"
                fi
            fi
        done
    fi
}

# Orphaned results accumulate when nothing consumes them — sweep periodically.
cleanup_stale_files() {
    find "$RESULTS_DIR" -name '*.json' -mmin +120 -delete 2>/dev/null || true
    find "$RESULTS_DIR" -name '*.tmp' -mmin +120 -delete 2>/dev/null || true
    find "$TASKS_DIR" -name '*.work.*' -mmin +120 -delete 2>/dev/null || true
    # Debug logs hold full task prompts: age them out (default 7 days,
    # BRAIN_LOG_RETENTION_DAYS overrides) and keep them owner-only — they
    # live under /config and would otherwise ride into every HA full backup.
    local retention_days="${BRAIN_LOG_RETENTION_DAYS:-7}"
    find "$LOG_DIR" -name '*.log' -mtime "+${retention_days}" -delete 2>/dev/null || true
    chmod 700 "$LOG_DIR" 2>/dev/null || true
    chmod 600 "$LOG_DIR"/*.log 2>/dev/null || true
}

# Extract the assistant's final text from a `claude -p --output-format json`
# result file. That mode emits a single JSON object whose .result field holds
# the final text. Falls back to the raw file for any non-JSON output (older
# CLI, hard errors) so genuine error text still surfaces.
#
# This replaces scraping the CLI's `--verbose` text stdout wholesale: newer
# Claude Code builds pad that stream with diagnostics — including "MCP server
# ... unavailable" connection notices — which leaked into automation results.
extract_claude_result() {
    local out_file="$1" text
    text=$(jq -r 'if (type == "object" and (.result | type) == "string" and (.result | length) > 0) then .result else empty end' "$out_file" 2>/dev/null)
    if [ -n "$text" ]; then
        printf '%s' "$text"
    else
        cat "$out_file" 2>/dev/null || true
    fi
}

# The same result object carries the session id, which is the id of the
# transcript Claude Code has just written into /config. Claiming it is what
# lets the Chats rail say "Automation" beside it instead of listing an
# automation's task among the conversations you had.
#
# Claimed after the run rather than before because this path never had to
# name its own session — --output-format json hands it back for free, and
# a flag we don't need is a flag that can be unsupported.
claim_task_session() {
    local out_file="$1" sid
    command -v brain_claim_session > /dev/null 2>&1 || return 0
    sid=$(jq -r 'if type == "object" then (.session_id // empty) else empty end' \
        "$out_file" 2>/dev/null | tr -cd 'A-Za-z0-9._-')
    [ -n "$sid" ] && brain_claim_session "$sid" automation
    return 0
}

# Process an automation task file
process_task() {
    local task_file="$1"

    # Claim the task atomically so the startup-backlog scan, inotify events,
    # and the polling fallback can never double-process one file.
    local work_file="${task_file%.json}.work.${BASHPID:-$$}"
    mv "$task_file" "$work_file" 2>/dev/null || return 0

    local task_id prompt notify notify_entity task_ts task_timeout task_model

    task_id=$(jq -r '.id // empty' "$work_file" 2>/dev/null)
    prompt=$(jq -r '.prompt // empty' "$work_file" 2>/dev/null)
    notify=$(jq -r '.notify // false' "$work_file" 2>/dev/null)
    notify_entity=$(jq -r '.notify_entity // empty' "$work_file" 2>/dev/null)
    task_ts=$(jq -r '.ts // empty' "$work_file" 2>/dev/null)
    task_timeout=$(jq -r '.timeout // empty' "$work_file" 2>/dev/null)
    task_model=$(jq -r '.model // empty' "$work_file" 2>/dev/null)

    local model_flag=""
    if [ -n "$task_model" ] && [ "$task_model" != "default" ]; then
        model_flag="--model $task_model"
    fi

    if [ -z "$task_id" ] || [ -z "$prompt" ]; then
        bashio::log.warning "Invalid task file: $task_file"
        rm -f "$work_file"
        return
    fi

    # Bridge wait window for this task (drives staleness + process limit)
    local has_task_timeout=1
    case "$task_timeout" in
        ''|*[!0-9]*) task_timeout="$CLAUDE_TIMEOUT"; has_task_timeout=0 ;;
    esac
    case "$task_ts" in
        *[!0-9.]*) task_ts="" ;;
    esac

    # Discard tasks nobody is waiting for anymore (add-on was stopped,
    # bridge already timed out).
    local now age
    now=$(date +%s)
    if [ -n "$task_ts" ]; then
        age=$((now - ${task_ts%.*}))
    else
        age=$((now - $(stat -c %Y "$work_file" 2>/dev/null || echo "$now")))
    fi
    if [ "$age" -gt $((task_timeout + 30)) ] 2>/dev/null; then
        bashio::log.warning "Discarding stale task [$task_id] (${age}s old > ${task_timeout}s window)"
        rm -f "$work_file"
        return
    fi

    bashio::log.info "Processing task [$task_id]: ${prompt:0:80}..."
    rm -f "$work_file"

    cleanup_stale_files

    # Cheap canonical-config check only — the deep cleanup runs at startup
    # and after detected /api/mcp errors.
    verify_mcp_config_fast

    # Claude process limit: stay inside the bridge's polling window so the
    # result file always lands before the integration gives up. Tasks without
    # a timeout (older integration) keep the configured default.
    local claude_limit
    if [ "$has_task_timeout" = "1" ]; then
        claude_limit=$((task_timeout - TIMEOUT_MARGIN))
        [ "$claude_limit" -lt 30 ] && claude_limit=30
    else
        claude_limit="$CLAUDE_TIMEOUT"
    fi

    # Log request for debugging
    local log_file="$LOG_DIR/automation-$(date +%Y%m%d).log"
    {
        echo "================================================================"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] TASK REQUEST $task_id"
        echo "  Channel:  automation"
        echo "  Prompt:   ${prompt:0:500}"
        echo "  Chars:    ${#prompt}"
        echo "  Notify:   $notify"
        echo "  Timeout:  ${claude_limit}s (bridge window ${task_timeout}s)"
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

    # --output-format json: capture the structured result and pull .result,
    # instead of scraping verbose stdout (which now carries MCP/diagnostic
    # lines). See extract_claude_result().
    # shellcheck disable=SC2086
    (cd /config && printf '%s' "$prompt" | timeout "$claude_limit" ${CLAUDE_BIN} -p --output-format json --max-turns "$MAX_TURNS" ${model_flag} > "$output_file" 2>"$stderr_file") || true

    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    local result stderr_output
    result=$(extract_claude_result "$output_file")
    claim_task_session "$output_file"
    stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
    rm -f "$output_file" "$stderr_file"

    # Check for /api/mcp auth errors in stderr — deep-clean configs and retry
    # within the remaining time budget.
    if echo "$stderr_output" | grep -qi "/api/mcp\|invalid authentication.*mcp"; then
        bashio::log.error "Detected /api/mcp auth error in task [$task_id] — cleaning and retrying"
        verify_mcp_config_full

        local remaining=$((claude_limit - duration))
        if [ "$remaining" -ge 30 ]; then
            output_file=$(mktemp)
            stderr_file=$(mktemp)

            # shellcheck disable=SC2086
            (cd /config && printf '%s' "$prompt" | timeout "$remaining" ${CLAUDE_BIN} -p --output-format json --max-turns "$MAX_TURNS" ${model_flag} > "$output_file" 2>"$stderr_file") || true

            end_time=$(date +%s)
            duration=$((end_time - start_time))

            result=$(extract_claude_result "$output_file")
            claim_task_session "$output_file"
            stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
            rm -f "$output_file" "$stderr_file"
            bashio::log.info "Retried task [$task_id] after /api/mcp cleanup"
        else
            bashio::log.warning "No time budget left to retry task [$task_id] (${remaining}s remaining)"
        fi
    fi

    # Auth failures come back as the result text in -p mode ("Failed to
    # authenticate: OAuth session expired and could not be refreshed").
    # Replace the raw CLI error with something the user can act on — the
    # fix is a one-time /login in the interactive terminal, which every
    # background channel picks up automatically on its next spawn.
    if printf '%s' "$result" | grep -qiE "OAuth session expired|OAuth token (refresh failed|revoked)|failed to authenticate|please run /login|invalid api key"; then
        bashio::log.error "Claude auth failure in task [$task_id]: ${result:0:200}"
        result="Claude's saved login has expired and could not be refreshed automatically. Open the brAIn add-on from the sidebar and run /login once — background tasks and insights pick up the fresh login automatically."
    fi

    # If result is empty, something went wrong — check stderr for clues
    if [ -z "$result" ]; then
        bashio::log.error "Empty result for task [$task_id] after ${duration}s"
        bashio::log.error "Stderr: ${stderr_output:0:500}"
        if [ "$duration" -ge "$((claude_limit - 5))" ] 2>/dev/null; then
            result="Claude task timed out after ${duration}s. This may be caused by a broken MCP server connection. Try restarting the brAIn add-on."
            bashio::log.error "Claude process timed out (limit=${claude_limit}s)"
        elif echo "$stderr_output" | grep -qi "not logged in\|please log in\|authentication"; then
            result="Claude is not logged in. Please open the brAIn sidebar and complete the OAuth login first."
        elif echo "$stderr_output" | grep -qi "permission\|not allowed\|denied"; then
            result="Claude encountered a permission error. Check the add-on logs for details."
        else
            result="Task failed — Claude didn't produce a result. Check the brAIn add-on logs."
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
        result="Claude is not logged in. Please open the brAIn sidebar and complete the OAuth login first."
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
        "http://supervisor/core/api/events/brain_task_complete" 2>/dev/null || true
}

# Watch for new task files
listen_for_tasks() {
    if command -v inotifywait >/dev/null 2>&1; then
        bashio::log.info "Using inotifywait for efficient file watching"

        # Process any files that arrived before we started watching
        # (process_task claims by rename, so the watcher can't double-pick)
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
verify_mcp_config_full
cleanup_stale_files
listen_for_tasks
