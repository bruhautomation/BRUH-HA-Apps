#!/usr/bin/with-contenv bashio

# Assist Integration Listener
# Bridges Home Assistant conversation agent to Claude Code
#
# Communication with the HA custom integration uses a shared file directory:
#   /config/.bruh_claude/requests/   - incoming conversation requests (JSON)
#   /config/.bruh_claude/responses/  - outgoing conversation responses (JSON)
#
# Request format:  {"id": "<uuid>", "text": "user message", "type": "conversation", "system_prompt": "optional"}
# Response format: {"id": "<uuid>", "text": "claude response"}
#
# Permissions:
#   This listener does NOT use --dangerously-skip-permissions. Instead, tool
#   permissions are granted via /config/.claude/settings.local.json, which
#   pre-approves all MCP, Bash, Read, Write, and Edit tools. This avoids the
#   root-user restrictions of the flag while still allowing non-interactive use.

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
SHARED_DIR="/config/.bruh_claude"
REQUESTS_DIR="$SHARED_DIR/requests"
RESPONSES_DIR="$SHARED_DIR/responses"
LOG_DIR="$SHARED_DIR/logs"

# Maximum number of agentic turns per request.  Keeps responses fast:
# typically 1 turn to read entities + 1 turn to call a service + 1 to respond.
MAX_TURNS=3

mkdir -p "$REQUESTS_DIR" "$RESPONSES_DIR" "$LOG_DIR"

# Source the Claude environment written by run.sh
# This ensures HOME, ANTHROPIC_CONFIG_DIR, etc. are set correctly
# even when with-contenv shebang reloads the s6 container environment.
if [ -f /data/.bruh_claude_env ]; then
    # shellcheck disable=SC1091
    source /data/.bruh_claude_env
fi

# Resolve the claude binary.  The wrapper at /usr/local/bin/claude-run
# drops to the non-root 'claude' user via su-exec so that Claude Code runs
# as UID 1000 inside the container.  If the wrapper doesn't exist yet, fall
# back to calling the native binary through su-exec directly.
CLAUDE_BIN="claude-run"
if [ ! -x /usr/local/bin/claude-run ]; then
    if [ "$(id -u)" = "0" ] && command -v su-exec >/dev/null 2>&1; then
        CLAUDE_BIN="su-exec claude /root/.local/bin/claude"
    fi
fi

bashio::log.info "Assist listener starting (UID=$(id -u), claude=$CLAUDE_BIN, max_turns=$MAX_TURNS)..."
bashio::log.info "Watching $REQUESTS_DIR for conversation requests"
bashio::log.info "Debug logs: $LOG_DIR/assist-*.log"

# Format conversation history from JSON array into a readable transcript
format_history() {
    local history_json="$1"
    if [ -z "$history_json" ] || [ "$history_json" = "null" ] || [ "$history_json" = "[]" ]; then
        echo ""
        return
    fi
    # Convert each entry to "Role: content" format
    echo "$history_json" | jq -r '.[] | "\(.role | ascii_upcase): \(.content)"' 2>/dev/null || echo ""
}

# Log debug information for a request
log_request_debug() {
    local req_id="$1"
    local text="$2"
    local model="$3"
    local history_turns="$4"
    local prompt_chars="$5"
    local log_file="$LOG_DIR/assist-$(date +%Y%m%d).log"

    {
        echo "================================================================"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] REQUEST $req_id"
        echo "  Channel:  conversation_agent"
        echo "  Text:     $text"
        echo "  Model:    ${model:-default}"
        echo "  History:  $history_turns turns"
        echo "  Prompt:   $prompt_chars chars"
        echo "  MaxTurns: $MAX_TURNS"
    } >> "$log_file"
}

# Log debug information for a response
log_response_debug() {
    local req_id="$1"
    local response="$2"
    local duration="$3"
    local stderr_output="$4"
    local log_file="$LOG_DIR/assist-$(date +%Y%m%d).log"

    local response_chars=${#response}
    local response_lines
    response_lines=$(echo "$response" | wc -l)

    # Extract token/cost info from stderr if available (Claude Code outputs stats to stderr)
    local token_info=""
    if [ -n "$stderr_output" ]; then
        token_info=$(echo "$stderr_output" | grep -iE 'token|cost|usage|input|output' | head -5) || true
    fi

    {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] RESPONSE $req_id"
        echo "  Duration: ${duration}s"
        echo "  Response: $response_chars chars, $response_lines lines"
        if [ -n "$token_info" ]; then
            echo "  Tokens:   $token_info"
        fi
        echo "  Preview:  ${response:0:200}"
        if [ -n "$stderr_output" ]; then
            echo "  Stderr:   ${stderr_output:0:500}"
        fi
        echo "----------------------------------------------------------------"
    } >> "$log_file"
}

# Process a conversation request file
process_request() {
    local req_file="$1"
    local req_id
    local text
    local system_prompt
    local history_json

    req_id=$(jq -r '.id // empty' "$req_file" 2>/dev/null)
    text=$(jq -r '.text // empty' "$req_file" 2>/dev/null)
    system_prompt=$(jq -r '.system_prompt // empty' "$req_file" 2>/dev/null)
    history_json=$(jq -c '.conversation_history // []' "$req_file" 2>/dev/null)
    local model
    model=$(jq -r '.model // empty' "$req_file" 2>/dev/null)

    if [ -z "$req_id" ] || [ -z "$text" ]; then
        bashio::log.warning "Invalid request file: $req_file"
        rm -f "$req_file"
        return
    fi

    bashio::log.info "Assist request [$req_id]: $text"

    # Remove request file immediately so we don't re-process it
    rm -f "$req_file"

    # Format conversation history if present
    local history_text
    history_text=$(format_history "$history_json")
    local history_turns=0
    if [ -n "$history_text" ]; then
        history_turns=$(echo "$history_json" | jq 'length / 2 | floor' 2>/dev/null || echo 0)
    fi

    # System prompt for Claude: kept concise for speed.
    # MCP tool details are discovered automatically from the server;
    # we only need to tell Claude its role and style.
    local base_system_prompt="You are a Home Assistant voice assistant. You have FULL authorization to control all devices — never ask for permission or confirmation. Act immediately, then briefly confirm what you did.
Use your MCP tools (control_light, control_climate, control_media_player, control_cover, control_fan, control_switch, control_lock, control_alarm, control_vacuum, call_service, get_all_states, activate_scene, run_script, send_notification, get_service_details).
If unsure of an entity_id, call get_all_states with a domain filter first.
Keep responses concise."

    # Merge custom system prompt (from the conversation agent config) if provided
    local final_system_prompt="$base_system_prompt"
    if [ -n "$system_prompt" ]; then
        final_system_prompt="${system_prompt}

${base_system_prompt}"
    fi

    # Build the user message, including conversation history for context
    local user_message
    if [ -n "$history_text" ]; then
        user_message="Previous conversation:
${history_text}

USER: ${text}"
    else
        user_message="$text"
    fi

    # Build model flag (each conversation agent can specify its own model)
    local model_flag=""
    if [ -n "$model" ] && [ "$model" != "default" ]; then
        model_flag="--model $model"
    fi

    # Log the request for debugging
    log_request_debug "$req_id" "$text" "$model" "$history_turns" "${#user_message}"

    local output_file stderr_file
    output_file=$(mktemp)
    stderr_file=$(mktemp)

    # Run Claude in print mode from /config so it finds .mcp.json for HA tools
    # and .claude/settings.local.json for pre-approved tool permissions.
    # --max-turns keeps responses fast by limiting agentic loops.
    # No --dangerously-skip-permissions: permissions come from settings.local.json.
    local start_time
    start_time=$(date +%s)

    # shellcheck disable=SC2086
    (cd /config && printf '%s' "$user_message" | ${CLAUDE_BIN} -p --verbose --max-turns "$MAX_TURNS" --system-prompt "$final_system_prompt" ${model_flag} > "$output_file" 2>"$stderr_file") || true

    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    local response stderr_output
    response=$(cat "$output_file" 2>/dev/null || echo "")
    stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
    rm -f "$output_file" "$stderr_file"

    # If response is empty, something went wrong — check stderr for clues
    if [ -z "$response" ]; then
        bashio::log.error "Empty response for [$req_id] after ${duration}s"
        bashio::log.error "Stderr: ${stderr_output:0:500}"
        if echo "$stderr_output" | grep -qi "not logged in\|please log in\|authentication"; then
            response="Claude is not logged in. Please open the BRUH Claude Terminal sidebar and complete the OAuth login first."
        elif echo "$stderr_output" | grep -qi "permission\|not allowed\|denied"; then
            response="Claude encountered a permission error. Check the add-on logs for details."
        else
            response="Sorry, Claude didn't produce a response. Check the BRUH Claude Terminal add-on logs for details."
        fi
    fi

    # Log the response for debugging
    log_response_debug "$req_id" "$response" "$duration" "$stderr_output"

    bashio::log.info "Assist response [$req_id]: ${duration}s, ${#response} chars"

    # Check for auth errors in the response text
    if echo "$response" | grep -qi "not logged in\|please log in\|authentication required"; then
        response="Claude is not logged in. Please open the BRUH Claude Terminal sidebar and complete the OAuth login first."
        bashio::log.error "Claude auth error - user needs to log in via the terminal"
    fi

    # Write response file (atomic via tmp + rename)
    local resp_file="$RESPONSES_DIR/${req_id}.json"
    local tmp_file="${resp_file}.tmp"
    jq -n --arg id "$req_id" --arg text "$response" \
        '{"id": $id, "text": $text}' > "$tmp_file"
    mv "$tmp_file" "$resp_file"

    bashio::log.info "Assist response sent [$req_id]"
}

# Watch for new request files using inotifywait if available, fall back to polling
listen_for_requests() {
    if command -v inotifywait >/dev/null 2>&1; then
        bashio::log.info "Using inotifywait for efficient file watching"

        # Process any files that arrived before we started watching
        for req_file in "$REQUESTS_DIR"/*.json; do
            [ -f "$req_file" ] || continue
            process_request "$req_file" &
        done

        # Watch for new files
        inotifywait -m -e close_write -e moved_to --format '%w%f' "$REQUESTS_DIR" 2>/dev/null | while read -r filepath; do
            case "$filepath" in
                *.json)
                    process_request "$filepath" &
                    ;;
            esac
        done
    else
        bashio::log.info "inotifywait not available, falling back to polling (2s)"

        while true; do
            for req_file in "$REQUESTS_DIR"/*.json; do
                [ -f "$req_file" ] || continue
                process_request "$req_file" &
            done
            sleep 2
        done
    fi
}

# Main
listen_for_requests
