#!/bin/bash

# ha-share-login — Share your Claude login with other BRUH add-ons
#
# Runs `claude setup-token` interactively (as the non-root claude user),
# captures the generated long-lived OAuth token, and writes it to the
# shared auth file that other BRUH add-ons (like BRain) read:
#
#   /config/.brain/secrets/claude_auth.json
#   {"type": "oauth_token", "value": "sk-ant-oat...", "saved_at": <epoch>}
#
# Usage:
#   ha-share-login                 Run the interactive OAuth flow and share
#   ha-share-login --token <tok>   Write an already-obtained token directly
#   ha-share-login --status        Show whether a shared login exists
#   ha-share-login --revoke        Delete the shared login file
#   ha-share-login --force         Overwrite an existing shared login

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

AUTH_DIR="${BRAIN_AUTH_DIR:-/config/.brain/secrets}"
AUTH_FILE="$AUTH_DIR/claude_auth.json"

# Must match OAUTH_TOKEN_RE in brain/panel/engine.py
TOKEN_RE='sk-ant-oat[0-9]{2}-[A-Za-z0-9_-]{20,}'

usage() {
    cat << 'EOF'
ha-share-login — Share your Claude login with other BRUH add-ons

Usage:
  ha-share-login                 Interactive: run `claude setup-token`,
                                 capture the token, and write the shared file
  ha-share-login --token <tok>   Write a token you already have (sk-ant-oat...)
  ha-share-login --status        Show whether a shared login exists
  ha-share-login --revoke        Delete the shared login file
  ha-share-login --force         Overwrite an existing shared login

The shared file lives at /config/.brain/secrets/claude_auth.json
(0600, owned by the claude user). Other BRUH add-ons (like BRain)
pick it up automatically — one login for the whole family.
EOF
    exit 0
}

resolve_claude() {
    if [ -n "${BRAIN_CLAUDE_BIN:-}" ]; then
        echo "$BRAIN_CLAUDE_BIN"
    elif [ -x /usr/local/bin/claude-run ]; then
        echo "/usr/local/bin/claude-run"
    elif [ "$(id -u)" = "0" ] && command -v su-exec >/dev/null 2>&1; then
        echo "su-exec claude /root/.local/bin/claude"
    else
        echo "claude"
    fi
}

write_auth_file() {
    local token="$1"

    if ! printf '%s' "$token" | grep -qE "^${TOKEN_RE}\$"; then
        echo -e "${RED}Error: that doesn't look like a Claude OAuth token (expected sk-ant-oat...)${NC}" >&2
        exit 1
    fi

    mkdir -p "$AUTH_DIR"
    chmod 700 "$AUTH_DIR"

    local tmp="${AUTH_FILE}.tmp"
    # Token charset is validated above, so this printf-built JSON is safe.
    printf '{"type": "oauth_token", "value": "%s", "saved_at": %s}\n' \
        "$token" "$(date +%s)" > "$tmp"
    chmod 600 "$tmp"
    mv "$tmp" "$AUTH_FILE"
    chown -R claude:claude "$AUTH_DIR" 2>/dev/null || true

    echo -e "${GREEN}Shared login saved to ${AUTH_FILE}${NC}"
    echo -e "${GREEN}Other BRUH add-ons (like BRain) will now use this login automatically.${NC}"
}

show_status() {
    if [ -f "$AUTH_FILE" ]; then
        local saved_at saved_human=""
        saved_at=$(grep -oE '"saved_at":[ ]*[0-9]+' "$AUTH_FILE" 2>/dev/null | grep -oE '[0-9]+' || true)
        if [ -n "$saved_at" ]; then
            saved_human=$(date -d "@${saved_at}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "epoch ${saved_at}")
        fi
        echo -e "${GREEN}Shared login: ACTIVE${NC}"
        echo -e "  File:  $AUTH_FILE"
        [ -n "$saved_human" ] && echo -e "  Saved: $saved_human"
    else
        echo -e "${YELLOW}Shared login: not set up${NC}"
        echo -e "  Run ${CYAN}ha-share-login${NC} to share your Claude login with other BRUH add-ons."
    fi
    exit 0
}

revoke() {
    if [ -f "$AUTH_FILE" ]; then
        rm -f "$AUTH_FILE"
        echo -e "${GREEN}Shared login file deleted.${NC}"
        echo -e "${YELLOW}Note: the token itself is still valid. To revoke it entirely, visit"
        echo -e "https://console.anthropic.com/settings/keys (or claude.ai settings) and revoke it there.${NC}"
    else
        echo -e "${YELLOW}No shared login file to delete.${NC}"
    fi
    exit 0
}

interactive_login() {
    local claude_cmd
    claude_cmd=$(resolve_claude)

    echo -e "${CYAN}Starting the Claude OAuth token flow...${NC}"
    echo -e "Follow the prompts: open the URL, sign in, and paste the code back here."
    echo ""

    local capture
    capture=$(mktemp)
    # The capture file holds the terminal session INCLUDING the OAuth token.
    # Ctrl-C is the most likely way an interactive flow ends early — without
    # this trap, any interrupt would leave a plaintext long-lived credential
    # sitting in /tmp with nothing scheduled to clean it up.
    trap 'rm -f "$capture"' EXIT INT TERM
    # `script` keeps the session fully interactive (the OAuth URL/code
    # prompts need a real tty) while teeing everything to the capture file.
    # A plain pipe/tee would break the interactive prompt.
    if command -v script >/dev/null 2>&1; then
        script -qec "$claude_cmd setup-token" "$capture" || true
    else
        # No `script` available: run directly (nothing captured).
        $claude_cmd setup-token || true
    fi

    local token=""
    if [ -s "$capture" ]; then
        token=$(grep -oE "$TOKEN_RE" "$capture" | tail -1 || true)
    fi
    rm -f "$capture"
    trap - EXIT INT TERM

    if [ -z "$token" ]; then
        echo ""
        echo -e "${RED}Could not extract the token from the setup-token output.${NC}"
        echo -e "If the flow succeeded and printed a token (sk-ant-oat...), paste it manually:"
        echo -e "  ${CYAN}ha-share-login --token sk-ant-oat...${NC}"
        exit 1
    fi

    write_auth_file "$token"
}

# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------

FORCE=false
TOKEN=""
ACTION="login"

while [ $# -gt 0 ]; do
    case "$1" in
        --help|-h) usage ;;
        --status)  ACTION="status" ;;
        --revoke)  ACTION="revoke" ;;
        --force)   FORCE=true ;;
        --token)
            ACTION="token"
            TOKEN="${2:-}"
            [ -n "$TOKEN" ] || { echo -e "${RED}Error: --token requires a value${NC}" >&2; exit 1; }
            shift
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}" >&2
            usage
            ;;
    esac
    shift
done

case "$ACTION" in
    status) show_status ;;
    revoke) revoke ;;
    token)  write_auth_file "$TOKEN" ;;
    login)
        if [ -f "$AUTH_FILE" ] && [ "$FORCE" != "true" ]; then
            echo -e "${YELLOW}A shared login already exists (${AUTH_FILE}).${NC}"
            if [ -t 0 ]; then
                printf "Overwrite it with a new token? [y/N] "
                read -r answer
                case "$answer" in
                    y|Y|yes|YES) ;;
                    *) echo "Keeping the existing shared login. Use --status to inspect it."; exit 0 ;;
                esac
            else
                echo -e "Re-run with ${CYAN}--force${NC} to overwrite it."
                exit 1
            fi
        fi
        interactive_login
        ;;
esac
