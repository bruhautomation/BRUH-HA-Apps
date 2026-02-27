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
# Persistent sessions:
#   Each conversation_id maps to a Claude Code session via --resume.
#   The first message creates a new session; subsequent messages resume it.
#   Sessions persist until the user explicitly clears them (via the HA service)
#   or a file in /config/.bruh_claude/clear_sessions/ triggers cleanup.
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
SESSIONS_DIR="$SHARED_DIR/sessions"
CLEAR_DIR="$SHARED_DIR/clear_sessions"
LOG_DIR="$SHARED_DIR/logs"

# Maximum number of agentic turns per request.
# Configurable via the add-on's assist_max_turns option.
# Default 5: enough for entity lookup + service call + follow-up + response.
MAX_TURNS="${BRUH_ASSIST_MAX_TURNS:-5}"

# Process-level timeout for claude -p commands (seconds).
# Must be shorter than the integration's bridge timeout (default 120s) so the
# listener always has time to write an error response file before the bridge
# gives up polling.  Without this, a hung MCP connection causes claude -p to
# block forever and no response file is ever written.
CLAUDE_TIMEOUT="${BRUH_ASSIST_TIMEOUT:-105}"

mkdir -p "$REQUESTS_DIR" "$RESPONSES_DIR" "$SESSIONS_DIR" "$CLEAR_DIR" "$LOG_DIR"

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

bashio::log.info "Assist listener starting (UID=$(id -u), claude=$CLAUDE_BIN, max_turns=$MAX_TURNS, timeout=${CLAUDE_TIMEOUT}s)..."
bashio::log.info "Watching $REQUESTS_DIR for conversation requests"
bashio::log.info "Persistent sessions: $SESSIONS_DIR"
bashio::log.info "Debug logs: $LOG_DIR/assist-*.log"

# ---------------------------------------------------------------------------
# MCP config verification
# ---------------------------------------------------------------------------

# Verify /config/.mcp.json is clean before each Claude invocation.
# A broken marketplace plugin can re-register an SSE MCP server entry
# pointing to /api/mcp with invalid auth, causing conversation failures.
verify_mcp_config() {
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

# ---------------------------------------------------------------------------
# Session management
# ---------------------------------------------------------------------------

# Get the Claude session ID for a conversation, or empty string if none.
get_session_id() {
    local conv_id="$1"
    local session_file="$SESSIONS_DIR/${conv_id}.session"
    if [ -f "$session_file" ]; then
        cat "$session_file"
    fi
}

# Save the Claude session ID for a conversation.
save_session_id() {
    local conv_id="$1"
    local session_id="$2"
    echo "$session_id" > "$SESSIONS_DIR/${conv_id}.session"
}

# Clear a session for a conversation.
clear_session() {
    local conv_id="$1"
    rm -f "$SESSIONS_DIR/${conv_id}.session"
    bashio::log.info "Cleared session for conversation: $conv_id"
}

# Process any pending session clear requests.
process_clear_requests() {
    for clear_file in "$CLEAR_DIR"/*.clear; do
        [ -f "$clear_file" ] || continue
        local conv_id
        conv_id=$(basename "$clear_file" .clear)
        if [ "$conv_id" = "_all" ]; then
            rm -f "$SESSIONS_DIR"/*.session
            bashio::log.info "Cleared ALL conversation sessions"
        else
            clear_session "$conv_id"
        fi
        rm -f "$clear_file"
    done
}

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
    local session_id="$4"
    local is_resume="$5"
    local prompt_chars="$6"
    local log_file="$LOG_DIR/assist-$(date +%Y%m%d).log"

    {
        echo "================================================================"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] REQUEST $req_id"
        echo "  Channel:  conversation_agent"
        echo "  Text:     $text"
        echo "  Model:    ${model:-default}"
        echo "  Session:  ${session_id:-new}"
        echo "  Resume:   $is_resume"
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
    local session_id="$5"
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
        echo "  Duration:  ${duration}s"
        echo "  Session:   ${session_id:-unknown}"
        echo "  Response:  $response_chars chars, $response_lines lines"
        if [ -n "$token_info" ]; then
            echo "  Tokens:    $token_info"
        fi
        echo "  Preview:   ${response:0:200}"
        if [ -n "$stderr_output" ]; then
            echo "  Stderr:    ${stderr_output:0:500}"
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

    # Ensure MCP config is clean before invoking Claude
    verify_mcp_config

    # Process any pending session clear requests
    process_clear_requests

    # Check for an existing Claude session for this conversation
    local claude_session
    claude_session=$(get_session_id "$req_id")
    local is_resume="false"

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

    # Build the user message and Claude flags depending on session state
    local user_message
    local resume_flag=""
    local system_flag=""

    if [ -n "$claude_session" ]; then
        # Resume existing session — Claude already has conversation history
        user_message="$text"
        resume_flag="--resume $claude_session"
        is_resume="true"
        bashio::log.info "Resuming session [$claude_session] for [$req_id]"
    else
        # New session — include conversation history if present for first message
        local history_text
        history_text=$(format_history "$history_json")
        if [ -n "$history_text" ]; then
            user_message="Previous conversation:
${history_text}

USER: ${text}"
        else
            user_message="$text"
        fi
        system_flag="--system-prompt"
    fi

    # Build model flag (each conversation agent can specify its own model)
    local model_flag=""
    if [ -n "$model" ] && [ "$model" != "default" ]; then
        model_flag="--model $model"
    fi

    # Log the request for debugging
    log_request_debug "$req_id" "$text" "$model" "$claude_session" "$is_resume" "${#user_message}"

    local output_file stderr_file
    output_file=$(mktemp)
    stderr_file=$(mktemp)

    # Run Claude in print mode from /config so it finds .mcp.json for HA tools
    # and .claude/settings.local.json for pre-approved tool permissions.
    # Use --output-format json to capture the session_id for persistence.
    # --max-turns keeps responses fast by limiting agentic loops.
    # No --dangerously-skip-permissions: permissions come from settings.local.json.
    local start_time
    start_time=$(date +%s)

    local exit_code=0
    if [ -n "$resume_flag" ]; then
        # Resume existing session — no system prompt needed
        # shellcheck disable=SC2086
        (cd /config && printf '%s' "$user_message" | timeout "$CLAUDE_TIMEOUT" ${CLAUDE_BIN} -p --output-format json --verbose --max-turns "$MAX_TURNS" ${resume_flag} ${model_flag} > "$output_file" 2>"$stderr_file") || exit_code=$?
    else
        # New session — include system prompt
        # shellcheck disable=SC2086
        (cd /config && printf '%s' "$user_message" | timeout "$CLAUDE_TIMEOUT" ${CLAUDE_BIN} -p --output-format json --verbose --max-turns "$MAX_TURNS" ${system_flag} "$final_system_prompt" ${model_flag} > "$output_file" 2>"$stderr_file") || exit_code=$?
    fi

    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    local raw_output stderr_output response new_session_id
    raw_output=$(cat "$output_file" 2>/dev/null || echo "")
    stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
    rm -f "$output_file" "$stderr_file"

    # Parse JSON output to extract result and session_id
    response=$(echo "$raw_output" | jq -r '.result // empty' 2>/dev/null)
    new_session_id=$(echo "$raw_output" | jq -r '.session_id // empty' 2>/dev/null)

    # If JSON parsing failed, treat the raw output as plain text (fallback)
    if [ -z "$response" ] && [ -n "$raw_output" ]; then
        response="$raw_output"
    fi

    # Save the session ID for future requests
    if [ -n "$new_session_id" ]; then
        save_session_id "$req_id" "$new_session_id"
        bashio::log.info "Session saved: $req_id -> $new_session_id"
    fi

    # If resume failed (empty response + non-zero exit), retry as new session
    if [ -z "$response" ] && [ "$is_resume" = "true" ]; then
        bashio::log.warning "Resume failed for [$req_id], retrying as new session..."
        clear_session "$req_id"

        output_file=$(mktemp)
        stderr_file=$(mktemp)
        start_time=$(date +%s)

        # shellcheck disable=SC2086
        (cd /config && printf '%s' "$text" | timeout "$CLAUDE_TIMEOUT" ${CLAUDE_BIN} -p --output-format json --verbose --max-turns "$MAX_TURNS" --system-prompt "$final_system_prompt" ${model_flag} > "$output_file" 2>"$stderr_file") || true

        end_time=$(date +%s)
        duration=$((end_time - start_time))

        raw_output=$(cat "$output_file" 2>/dev/null || echo "")
        stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
        rm -f "$output_file" "$stderr_file"

        response=$(echo "$raw_output" | jq -r '.result // empty' 2>/dev/null)
        new_session_id=$(echo "$raw_output" | jq -r '.session_id // empty' 2>/dev/null)

        if [ -z "$response" ] && [ -n "$raw_output" ]; then
            response="$raw_output"
        fi
        if [ -n "$new_session_id" ]; then
            save_session_id "$req_id" "$new_session_id"
        fi
    fi

    # If response is still empty, something went wrong — check stderr for clues
    if [ -z "$response" ]; then
        bashio::log.error "Empty response for [$req_id] after ${duration}s (exit=$exit_code)"
        bashio::log.error "Stderr: ${stderr_output:0:500}"
        if [ "$exit_code" -ge 124 ] 2>/dev/null && [ "$duration" -ge "$((CLAUDE_TIMEOUT - 5))" ] 2>/dev/null; then
            response="Claude timed out after ${duration}s. This may be caused by a broken MCP server connection. Try restarting the BRUH Claude Terminal add-on."
            bashio::log.error "Claude process timed out (exit=$exit_code, limit=${CLAUDE_TIMEOUT}s)"
        elif echo "$stderr_output" | grep -qi "not logged in\|please log in\|authentication"; then
            response="Claude is not logged in. Please open the BRUH Claude Terminal sidebar and complete the OAuth login first."
        elif echo "$stderr_output" | grep -qi "permission\|not allowed\|denied"; then
            response="Claude encountered a permission error. Check the add-on logs for details."
        else
            response="Sorry, Claude didn't produce a response. Check the BRUH Claude Terminal add-on logs for details."
        fi
    fi

    # Log the response for debugging
    log_response_debug "$req_id" "$response" "$duration" "$stderr_output" "${new_session_id:-$claude_session}"

    bashio::log.info "Assist response [$req_id]: ${duration}s, ${#response} chars (session=${new_session_id:-$claude_session:-new})"

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
