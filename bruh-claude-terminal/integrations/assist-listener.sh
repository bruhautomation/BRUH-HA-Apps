#!/usr/bin/with-contenv bashio

# Assist Integration Listener
# Bridges Home Assistant conversation agent to Claude Code
#
# Communication with the HA custom integration uses a shared file directory:
#   /config/.bruh_claude/requests/   - incoming conversation requests (JSON)
#   /config/.bruh_claude/responses/  - outgoing conversation responses (JSON)
#   /config/.bruh_claude/sessions/   - conversation_id -> Claude session uuid
#
# Request format:  {"id": "<request-uuid>", "conversation_id": "<conv-id>",
#                   "text": "...", "type": "conversation", "ts": <epoch>,
#                   "timeout": <secs>, "system_prompt": "optional",
#                   "model": "optional", "conversation_history": [...]}
# Response format: {"id": "<request-uuid>", "text": "claude response"}
#
# The response file is named after the request "id", which the integration
# generates uniquely per request. Older integrations used the conversation
# id for both — the listener stays compatible because it always names the
# response after whatever "id" the request carried.
#
# Conversation continuity:
#   First turn of a conversation starts a Claude session with a generated
#   --session-id; the mapping conversation_id -> session uuid is stored in
#   sessions/. Follow-up turns use --resume so Claude keeps full context
#   server-side (faster: no history replay, prompt cache stays warm). If
#   resume fails — or the CLI predates the session flags — the listener
#   falls back to a fresh invocation with the replayed history the
#   integration includes in every request.
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
CACHE_DIR="$SHARED_DIR/cache"
LOG_DIR="$SHARED_DIR/logs"

# Touched when the installed Claude CLI doesn't support --session-id/--resume;
# the listener then sticks to legacy stateless invocations with history replay.
SESSION_FLAGS_MARKER="$CACHE_DIR/session_flags_unsupported"

# Cached area -> controllable entities map, spliced into the system prompt so
# Claude can act on "turn off the kitchen lights" without a get_areas
# round-trip (saves a whole model turn on most voice commands).
AREA_MAP_FILE="$CACHE_DIR/area_map.txt"
AREA_MAP_TTL=300        # seconds before a background refresh is triggered
AREA_MAP_MAX_BYTES=12000

# Maximum number of agentic turns per request.
# Configurable via the add-on's assist_max_turns option.
# Default 5: enough for entity lookup + service call + follow-up + response.
MAX_TURNS="${BRUH_ASSIST_MAX_TURNS:-5}"

# Default process-level timeout for claude -p commands (seconds), used when a
# request doesn't carry its own timeout. Must be shorter than the
# integration's bridge timeout (default 120s) so the listener always has time
# to write an error response file before the bridge gives up polling.
CLAUDE_TIMEOUT="${BRUH_ASSIST_TIMEOUT:-105}"

# Subtracted from a request's bridge timeout to get the claude process limit,
# leaving room to classify errors and write the response file.
TIMEOUT_MARGIN=15

mkdir -p "$REQUESTS_DIR" "$RESPONSES_DIR" "$SESSIONS_DIR" "$CACHE_DIR" "$LOG_DIR"

# Source the Claude environment written by run.sh
# This ensures HOME, ANTHROPIC_CONFIG_DIR, etc. are set correctly
# even when with-contenv shebang reloads the s6 container environment.
if [ -r /data/.bruh_claude_env ]; then
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

bashio::log.info "Assist listener starting (UID=$(id -u), claude=$CLAUDE_BIN, max_turns=$MAX_TURNS, default_timeout=${CLAUDE_TIMEOUT}s)..."
bashio::log.info "Watching $REQUESTS_DIR for conversation requests"
bashio::log.info "Debug logs: $LOG_DIR/assist-*.log"

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
# Runs at startup and after an /api/mcp error is detected — NOT per request
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

    # Check Claude Code's project-level configs for /api/mcp entries
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

# ---------------------------------------------------------------------------
# Area map (cached) — lets Claude skip the get_areas round-trip
# ---------------------------------------------------------------------------

refresh_area_map() {
    [ -n "$SUPERVISOR_TOKEN" ] || return 1

    local template payload rendered
    template=$(cat << 'JINJA'
{% for a in areas() -%}
{%- set ents = area_entities(a) | select('match', '^(light|switch|climate|media_player|cover|fan|lock|vacuum|scene|script|alarm_control_panel|input_boolean)\.') | list -%}
{%- if ents %}{{ area_name(a) }}: {{ ents | join(', ') }}
{% endif -%}
{%- endfor %}
JINJA
)
    payload=$(jq -n --arg t "$template" '{"template": $t}')
    rendered=$(curl -s -m 10 -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$payload" \
        "http://supervisor/core/api/template" 2>/dev/null) || rendered=""

    # Error responses come back as JSON ({"message": ...}); a good render is
    # plain "Area: entity, entity" lines.
    case "$rendered" in
        "{"*|"") return 1 ;;
    esac
    echo "$rendered" | grep -q ":" || return 1

    printf '%s\n' "$rendered" | head -c "$AREA_MAP_MAX_BYTES" > "${AREA_MAP_FILE}.tmp"
    mv "${AREA_MAP_FILE}.tmp" "$AREA_MAP_FILE"
    return 0
}

# Prints the cached map (possibly empty). Stale-while-revalidate: an old
# cache is served immediately and refreshed in the background.
get_area_map() {
    if [ -f "$AREA_MAP_FILE" ]; then
        local now mtime age
        now=$(date +%s)
        mtime=$(stat -c %Y "$AREA_MAP_FILE" 2>/dev/null || echo 0)
        age=$((now - mtime))
        if [ "$age" -gt "$AREA_MAP_TTL" ]; then
            (refresh_area_map >/dev/null 2>&1 || true) &
        fi
    else
        # First request pays the one-time render (~100-300ms)
        refresh_area_map >/dev/null 2>&1 || true
    fi
    cat "$AREA_MAP_FILE" 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Housekeeping
# ---------------------------------------------------------------------------

# Orphaned files no longer poison conversations (request/response names are
# unique per request), but they still accumulate — sweep them periodically.
cleanup_stale_files() {
    find "$RESPONSES_DIR" -name '*.json' -mmin +30 -delete 2>/dev/null || true
    find "$RESPONSES_DIR" -name '*.tmp' -mmin +30 -delete 2>/dev/null || true
    find "$REQUESTS_DIR" -name '*.work.*' -mmin +30 -delete 2>/dev/null || true
    # Session mappings older than 7 days — Claude Code's own session cleanup
    # will have removed the underlying session by then anyway.
    find "$SESSIONS_DIR" -type f -mmin +10080 -delete 2>/dev/null || true
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    local prompt_chars="$4"
    local session_mode="$5"
    local log_file="$LOG_DIR/assist-$(date +%Y%m%d).log"

    {
        echo "================================================================"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] REQUEST $req_id"
        echo "  Channel:  conversation_agent"
        echo "  Text:     $text"
        echo "  Model:    ${model:-default}"
        echo "  Session:  ${session_mode}"
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
        echo "  Duration:  ${duration}s"
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

# Run claude -p once. Uses the caller's locals (bash dynamic scoping):
#   output_file, stderr_file, final_system_prompt, model_flag
# Args: $1=process timeout (s), $2=session spec ("resume:<id>", "new:<id>",
#       or "" for legacy stateless), $3=user message
invoke_claude() {
    local limit="$1" session_spec="$2" message="$3"
    local session_args=()
    case "$session_spec" in
        resume:*) session_args=(--resume "${session_spec#resume:}") ;;
        new:*)    session_args=(--session-id "${session_spec#new:}") ;;
    esac

    # Run Claude in print mode from /config so it finds .mcp.json for HA tools
    # and .claude/settings.local.json for pre-approved tool permissions.
    # Plain text output (no --output-format json) — proven reliable here.
    # shellcheck disable=SC2086
    (cd /config && printf '%s' "$message" | timeout "$limit" \
        ${CLAUDE_BIN} -p --verbose --max-turns "$MAX_TURNS" \
        --system-prompt "$final_system_prompt" \
        "${session_args[@]}" \
        ${model_flag} > "$output_file" 2>"$stderr_file")
}

# Process a conversation request file
process_request() {
    local req_file="$1"

    # Claim the request atomically so the startup-backlog scan, inotify
    # events, and the polling fallback can never double-process one file.
    # The .work.<pid> name doesn't match the *.json watch patterns.
    local work_file="${req_file%.json}.work.${BASHPID:-$$}"
    mv "$req_file" "$work_file" 2>/dev/null || return 0

    local req_id text system_prompt history_json model conv_id req_ts req_timeout

    req_id=$(jq -r '.id // empty' "$work_file" 2>/dev/null)
    text=$(jq -r '.text // empty' "$work_file" 2>/dev/null)
    system_prompt=$(jq -r '.system_prompt // empty' "$work_file" 2>/dev/null)
    history_json=$(jq -c '.conversation_history // []' "$work_file" 2>/dev/null)
    model=$(jq -r '.model // empty' "$work_file" 2>/dev/null)
    # Older integrations used the conversation id as the request id
    conv_id=$(jq -r '.conversation_id // .id // empty' "$work_file" 2>/dev/null | tr -cd 'A-Za-z0-9_-')
    req_ts=$(jq -r '.ts // empty' "$work_file" 2>/dev/null)
    req_timeout=$(jq -r '.timeout // empty' "$work_file" 2>/dev/null)

    if [ -z "$req_id" ] || [ -z "$text" ]; then
        bashio::log.warning "Invalid request file: $req_file"
        rm -f "$work_file"
        return
    fi

    # Bridge wait window for this request (drives staleness + process limit)
    local has_req_timeout=1
    case "$req_timeout" in
        ''|*[!0-9]*) req_timeout=120; has_req_timeout=0 ;;
    esac
    case "$req_ts" in
        *[!0-9.]*) req_ts="" ;;
    esac

    # Discard requests nobody is waiting for anymore (add-on was stopped,
    # bridge already timed out). Answering them would waste a Claude run.
    local now age
    now=$(date +%s)
    if [ -n "$req_ts" ]; then
        age=$((now - ${req_ts%.*}))
    else
        age=$((now - $(stat -c %Y "$work_file" 2>/dev/null || echo "$now")))
    fi
    if [ "$age" -gt $((req_timeout + 10)) ] 2>/dev/null; then
        bashio::log.warning "Discarding stale request [$req_id] (${age}s old > ${req_timeout}s window)"
        rm -f "$work_file"
        return
    fi

    bashio::log.info "Assist request [$req_id]: $text"
    rm -f "$work_file"

    cleanup_stale_files

    # Cheap canonical-config check only — the deep cleanup runs at startup
    # and after detected /api/mcp errors, not on every request.
    verify_mcp_config_fast

    # Claude process limit: leave margin to classify errors and write the
    # response before the bridge stops polling. Requests without a timeout
    # (older integration) keep the configured default.
    local claude_limit
    if [ "$has_req_timeout" = "1" ]; then
        claude_limit=$((req_timeout - TIMEOUT_MARGIN))
        [ "$claude_limit" -lt 30 ] && claude_limit=30
    else
        claude_limit="$CLAUDE_TIMEOUT"
    fi

    # System prompt for Claude: kept concise for speed.
    # MCP tool details are discovered automatically from the server;
    # we only need to tell Claude its role and style.
    local base_system_prompt="You are a Home Assistant voice assistant. You have FULL authorization to control all devices — never ask for permission or confirmation. Act immediately, then briefly confirm what you did in one short sentence.
Use your MCP tools (control_light, control_climate, control_media_player, control_cover, control_fan, control_switch, control_lock, control_alarm, control_vacuum, call_service, get_all_states, get_areas, activate_scene, run_script, send_notification, get_service_details)."

    # Splice in the cached area map so room commands need zero lookup turns
    local area_map
    area_map=$(get_area_map)
    if [ -n "$area_map" ]; then
        base_system_prompt="${base_system_prompt}

Known areas and their controllable entity_ids:
${area_map}

Use these entity_ids directly — only call get_areas if something you need is missing above.
For entities not listed, use get_all_states with the domain and name_filter arguments."
    else
        base_system_prompt="${base_system_prompt}
For room/area requests (e.g. 'turn off the bedroom lights') call get_areas to resolve the room to entity_ids first.
If unsure of an entity_id, call get_all_states with a domain filter first."
    fi
    base_system_prompt="${base_system_prompt}
Keep responses concise."

    # Merge custom system prompt (from the conversation agent config) if provided
    local final_system_prompt="$base_system_prompt"
    if [ -n "$system_prompt" ]; then
        final_system_prompt="${system_prompt}

${base_system_prompt}"
    fi

    # Two message variants: resumed sessions already hold the prior turns
    # server-side, fresh sessions get the replayed transcript.
    local message_resume="$text"
    local message_fresh="$text"
    local history_text
    history_text=$(format_history "$history_json")
    if [ -n "$history_text" ]; then
        message_fresh="Previous conversation:
${history_text}

USER: ${text}"
    fi

    # Build model flag (each conversation agent can specify its own model)
    local model_flag=""
    if [ -n "$model" ] && [ "$model" != "default" ]; then
        model_flag="--model $model"
    fi

    # Resolve the Claude session for this conversation
    local session_file="" resume_session="" new_session="" session_mode="legacy"
    if [ -n "$conv_id" ]; then
        session_file="$SESSIONS_DIR/$conv_id"
    fi
    if [ ! -f "$SESSION_FLAGS_MARKER" ]; then
        if [ -n "$session_file" ] && [ -f "$session_file" ]; then
            resume_session=$(tr -cd 'a-f0-9-' < "$session_file" 2>/dev/null)
            if [ "${#resume_session}" = "36" ]; then
                session_mode="resume"
            else
                resume_session=""
            fi
        fi
        if [ -z "$resume_session" ]; then
            new_session=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || true)
            [ -n "$new_session" ] && session_mode="new"
        fi
    fi

    # Log the request for debugging
    log_request_debug "$req_id" "$text" "$model" "${#message_fresh}" "$session_mode"

    local output_file stderr_file
    output_file=$(mktemp)
    stderr_file=$(mktemp)

    local start_time
    start_time=$(date +%s)

    local exit_code=0
    case "$session_mode" in
        resume) invoke_claude "$claude_limit" "resume:$resume_session" "$message_resume" || exit_code=$? ;;
        new)    invoke_claude "$claude_limit" "new:$new_session" "$message_fresh" || exit_code=$? ;;
        *)      invoke_claude "$claude_limit" "" "$message_fresh" || exit_code=$? ;;
    esac

    local response stderr_output
    response=$(cat "$output_file" 2>/dev/null || echo "")
    stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")

    # Recovery: one retry within the remaining time budget when the first
    # attempt produced nothing.
    if [ -z "$response" ]; then
        local elapsed remaining
        elapsed=$(( $(date +%s) - start_time ))
        remaining=$(( claude_limit - elapsed ))

        if echo "$stderr_output" | grep -qi "unknown option\|unrecognized option"; then
            # CLI predates --session-id/--resume: remember and go legacy
            bashio::log.warning "Claude CLI lacks session flags — falling back to stateless mode permanently"
            touch "$SESSION_FLAGS_MARKER"
            rm -f "$session_file" 2>/dev/null || true
            session_mode="legacy"
            new_session=""
            if [ "$remaining" -ge 20 ]; then
                exit_code=0
                invoke_claude "$remaining" "" "$message_fresh" || exit_code=$?
                response=$(cat "$output_file" 2>/dev/null || echo "")
                stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
            fi
        elif [ "$session_mode" = "resume" ] && [ "$remaining" -ge 20 ]; then
            # Stored session is gone (cleanup, CLI update) — start fresh
            bashio::log.warning "Resume of session failed for [$req_id] — retrying with a fresh session"
            rm -f "$session_file" 2>/dev/null || true
            resume_session=""
            new_session=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || true)
            exit_code=0
            if [ -n "$new_session" ]; then
                session_mode="new"
                invoke_claude "$remaining" "new:$new_session" "$message_fresh" || exit_code=$?
            else
                session_mode="legacy"
                invoke_claude "$remaining" "" "$message_fresh" || exit_code=$?
            fi
            response=$(cat "$output_file" 2>/dev/null || echo "")
            stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
        fi
    fi

    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))
    rm -f "$output_file" "$stderr_file"

    # Remember the session so the next turn of this conversation resumes it
    if [ -n "$response" ] && [ "$session_mode" = "new" ] && [ -n "$new_session" ] && [ -n "$session_file" ]; then
        printf '%s' "$new_session" > "$session_file" 2>/dev/null || true
    fi

    # If response is empty, something went wrong — check stderr for clues
    if [ -z "$response" ]; then
        bashio::log.error "Empty response for [$req_id] after ${duration}s (exit=$exit_code)"
        bashio::log.error "Stderr: ${stderr_output:0:500}"
        if [ "$exit_code" -ge 124 ] 2>/dev/null && [ "$duration" -ge "$((claude_limit - 5))" ] 2>/dev/null; then
            response="Claude timed out after ${duration}s. This may be caused by a broken MCP server connection. Try restarting the BRUH Claude Terminal add-on."
            bashio::log.error "Claude process timed out (exit=$exit_code, limit=${claude_limit}s)"
        elif echo "$stderr_output" | grep -qi "not logged in\|please log in\|authentication"; then
            response="Claude is not logged in. Please open the BRUH Claude Terminal sidebar and complete the OAuth login first."
        elif echo "$stderr_output" | grep -qi "/api/mcp\|invalid authentication.*mcp"; then
            response="Claude encountered a broken MCP server connection (/api/mcp auth error). Restart the BRUH Claude Terminal add-on to clean it up."
            bashio::log.error "Detected /api/mcp auth error — running deep MCP cleanup for the next request"
            verify_mcp_config_full
        elif echo "$stderr_output" | grep -qi "permission\|not allowed\|denied"; then
            response="Claude encountered a permission error. Check the add-on logs for details."
        else
            response="Sorry, Claude didn't produce a response. Check the BRUH Claude Terminal add-on logs for details."
        fi
    fi

    # Log the response for debugging
    log_response_debug "$req_id" "$response" "$duration" "$stderr_output"

    bashio::log.info "Assist response [$req_id]: ${duration}s, ${#response} chars (session=$session_mode)"

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
        # (process_request claims by rename, so the watcher can't double-pick)
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
verify_mcp_config_full
cleanup_stale_files
# Pre-warm the area map so the first voice command doesn't pay for it
(refresh_area_map >/dev/null 2>&1 || true) &
listen_for_requests
