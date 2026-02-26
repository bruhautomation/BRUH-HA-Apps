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

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
SHARED_DIR="/config/.bruh_claude"
REQUESTS_DIR="$SHARED_DIR/requests"
RESPONSES_DIR="$SHARED_DIR/responses"

mkdir -p "$REQUESTS_DIR" "$RESPONSES_DIR"

# Source the Claude environment written by run.sh
# This ensures HOME, ANTHROPIC_CONFIG_DIR, etc. are set correctly
# even when with-contenv shebang reloads the s6 container environment.
if [ -f /data/.bruh_claude_env ]; then
    # shellcheck disable=SC1091
    source /data/.bruh_claude_env
fi

bashio::log.info "Assist listener starting..."
bashio::log.info "Watching $REQUESTS_DIR for conversation requests"

# Check if Claude is authenticated
check_claude_auth() {
    # Try a quick claude command to see if auth is available
    local auth_check
    auth_check=$(claude -p "hello" 2>&1 | head -5) || true
    if echo "$auth_check" | grep -qi "not logged in\|please log in\|authentication\|unauthorized"; then
        return 1
    fi
    return 0
}

# Process a conversation request file
process_request() {
    local req_file="$1"
    local req_id
    local text
    local system_prompt

    req_id=$(jq -r '.id // empty' "$req_file" 2>/dev/null)
    text=$(jq -r '.text // empty' "$req_file" 2>/dev/null)
    system_prompt=$(jq -r '.system_prompt // empty' "$req_file" 2>/dev/null)

    if [ -z "$req_id" ] || [ -z "$text" ]; then
        bashio::log.warning "Invalid request file: $req_file"
        rm -f "$req_file"
        return
    fi

    bashio::log.info "Assist request [$req_id]: $text"

    # Remove request file immediately so we don't re-process it
    rm -f "$req_file"

    # Build the prompt for Claude
    local full_prompt
    if [ -n "$system_prompt" ]; then
        full_prompt="${system_prompt}

User said: ${text}
Respond helpfully. If they want to control devices, use the Home Assistant MCP tools available to you.
Keep responses concise and conversational."
    else
        full_prompt="You are a Home Assistant voice assistant. The user said: ${text}
Respond helpfully. If they want to control devices, use the Home Assistant MCP tools available to you.
Keep responses concise and conversational."
    fi

    local output_file
    output_file=$(mktemp)

    # Run Claude in print mode. The permissions flag is controlled by the
    # dangerously_skip_permissions app config option (persisted in the env file).
    # shellcheck disable=SC2086
    printf '%s' "$full_prompt" | claude -p ${BRUH_CLAUDE_PERMS_FLAG:-} > "$output_file" 2>&1 || true

    local response
    response=$(cat "$output_file" 2>/dev/null || echo "I had trouble processing that request.")
    rm -f "$output_file"

    # Check for auth errors and return a helpful message
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
