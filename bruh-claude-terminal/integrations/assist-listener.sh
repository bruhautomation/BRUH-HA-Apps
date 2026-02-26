#!/usr/bin/with-contenv bashio

# Assist Integration Listener
# Bridges Home Assistant Assist (conversation agent) to Claude Code
# Listens for conversation intents and routes them to Claude

set -e

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
HA_WS_URL="ws://supervisor/core/websocket"
TASK_DIR="/data/tasks"
RESPONSE_DIR="/data/assist-responses"

mkdir -p "$TASK_DIR" "$RESPONSE_DIR"

bashio::log.info "Assist listener starting..."

# Register as a conversation agent via the HA API
register_conversation_agent() {
    bashio::log.info "Registering BRUH Claude as conversation agent..."

    # Create a webhook for receiving conversation requests
    # The webhook URL will be: http://supervisor/core/api/webhook/bruh_claude_conversation
    local webhook_id="bruh_claude_conversation"

    bashio::log.info "Conversation webhook ready: $webhook_id"
    bashio::log.info "To use: Set up an automation that forwards assist intents to this webhook"
}

# Process a conversation request
process_conversation() {
    local text="$1"
    local conversation_id="${2:-$(date +%s)}"

    bashio::log.info "Assist request: $text"

    # Run Claude with the prompt and capture output
    local output_file="$RESPONSE_DIR/${conversation_id}.txt"

    # Use Claude in print mode for one-shot responses
    claude -p "You are a Home Assistant assistant. The user said: '$text'.
Respond helpfully. If they want to control devices, use the Home Assistant MCP tools available to you.
Keep responses concise and conversational." > "$output_file" 2>&1 || true

    local response
    response=$(cat "$output_file" 2>/dev/null || echo "I had trouble processing that request.")

    # Send response back to HA via the REST API
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"text\": \"$(echo "$response" | head -5 | sed 's/"/\\"/g' | tr '\n' ' ')\"}" \
        "http://supervisor/core/api/events/bruh_claude_response" 2>/dev/null || true

    bashio::log.info "Assist response sent for conversation: $conversation_id"
}

# Listen for conversation events via polling
# In production, this would use WebSocket, but for simplicity we poll
listen_for_requests() {
    bashio::log.info "Listening for Assist conversation requests..."
    bashio::log.info "Fire event 'bruh_claude_request' with data {\"text\": \"your question\"}"

    local last_check
    last_check=$(date +%s)

    while true; do
        # Check for pending request files
        for req_file in "$TASK_DIR"/assist_*.pending 2>/dev/null; do
            if [ -f "$req_file" ]; then
                local text
                text=$(cat "$req_file")
                local conv_id
                conv_id=$(basename "$req_file" .pending | sed 's/assist_//')
                rm -f "$req_file"
                process_conversation "$text" "$conv_id" &
            fi
        done

        sleep 2
    done
}

# Main
register_conversation_agent
listen_for_requests
