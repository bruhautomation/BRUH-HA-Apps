#!/bin/bash

# ha login / brain login — sign in to Claude, and share that login with the
# rest of the BRUH family.
#
# There are three places a Claude credential can live, and this script is
# what makes them one answer:
#
#   1. the CLI's own   $BRAIN_HOME/.claude/.credentials.json  (`claude /login`)
#   2. the panel's     $BRAIN_SECRETS/claude_auth.json        (the ✨ Connect screen)
#   3. the shared      $BRAIN_AUTH_DIR/claude_auth.json       (this script)
#
# Only the third is on the /config volume, which is why it is the one other
# BRUH add-ons can read. The shape contract, shared with the panel's store:
#
#   {"type": "oauth_token"|"api_key", "value": "sk-ant-…", "saved_at": <epoch int>}
#
# Usage:
#   ha login                       Run the interactive OAuth flow and share
#   ha login --share               Publish a login you already have
#   ha login --token <tok>         Write an already-obtained token directly
#   ha login --status              Show every store, and which one is in use
#   ha login --revoke              Delete the shared login file
#   ha login --force               Overwrite an existing shared login

# Deliberately not `-e`: the status report calls each store's reporter for
# its exit status ("did this store hold a usable credential?"), and under
# `-e` the first store that does not would end the script mid-report. Every
# operation that must not fail silently carries its own `|| exit` instead.
set -uo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
DIM='\033[0;90m'
NC='\033[0m'

# The shared file — the only one of the three on /config, and so the only
# one another add-on can read.
AUTH_DIR="${BRAIN_AUTH_DIR:-/config/.brain/secrets}"
AUTH_FILE="$AUTH_DIR/claude_auth.json"
# The other two stores. Read for --status and --share, never written here:
# the panel owns its own file and the CLI owns its own.
PANEL_FILE="${BRAIN_SECRETS:-/data/secrets}/claude_auth.json"
CLI_FILE="${BRAIN_HOME:-/data/home}/.claude/.credentials.json"

# Must match OAUTH_TOKEN_RE in brain/panel/engine.py
TOKEN_RE='sk-ant-oat[0-9]{2}-[A-Za-z0-9_-]{20,}'
# An API key is the other credential the shape contract accepts. Anchored
# away from `oat` so the two can never be classified as each other.
APIKEY_RE='sk-ant-(api|admin)[0-9]{2}-[A-Za-z0-9_-]{20,}'

usage() {
    cat << 'EOF'
ha login — sign in to Claude, and share that login with other BRUH add-ons

Usage:
  ha login                 Interactive: run `claude setup-token`, capture the
                           token, and write the shared file. Needs a terminal.
  ha login --share         Publish a login you already have (from the panel's
                           own store) without signing in again
  ha login --token <tok>   Write a token you already have (sk-ant-oat…)
  ha login --status        Show all three credential stores and which is in use
  ha login --revoke        Delete the shared login file
  ha login --force         Overwrite an existing shared login

`brain login` is the same command. Signing in from the panel (the ✨ Connect
screen, or ⚙ Settings → Claude account) does all of this with a button.

The shared file lives at /config/.brain/secrets/claude_auth.json (0600, owned
by the claude user). Note that /config is included in Home Assistant backups,
which are not encrypted unless you turn that on — so a shared login travels
with your backups.
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

# Classify a credential by shape. Echoes the type, or nothing when the value
# is neither — "looks like a token" is the only check available here, and it
# is deliberately the same one the panel makes.
classify() {
    local value="$1"
    if printf '%s' "$value" | grep -qE "^${TOKEN_RE}\$"; then
        echo "oauth_token"
    elif printf '%s' "$value" | grep -qE "^${APIKEY_RE}\$"; then
        echo "api_key"
    fi
}

write_auth_file() {
    local token="$1"
    local kind
    kind=$(classify "$token")

    if [ -z "$kind" ]; then
        echo -e "${RED}Error: that doesn't look like a Claude credential.${NC}" >&2
        echo -e "Expected a long-lived OAuth token (${CYAN}sk-ant-oat…${NC}, from" >&2
        echo -e "\`claude setup-token\`) or an API key (${CYAN}sk-ant-api…${NC})." >&2
        echo -e "${DIM}Note: the accessToken inside .credentials.json is NOT one of these —" >&2
        echo -e "it is a short-lived session token, and the shared file has no way to" >&2
        echo -e "refresh it, so sharing it would break every add-on within hours.${NC}" >&2
        exit 1
    fi

    mkdir -p "$AUTH_DIR" || exit 1
    chmod 700 "$AUTH_DIR"

    local tmp="${AUTH_FILE}.tmp"
    # Token charset is validated above, so this printf-built JSON is safe.
    printf '{"type": "%s", "value": "%s", "saved_at": %s}\n' \
        "$kind" "$token" "$(date +%s)" > "$tmp" || exit 1
    chmod 600 "$tmp"
    mv "$tmp" "$AUTH_FILE"
    chown -R claude:claude "$AUTH_DIR" 2>/dev/null || true

    echo -e "${GREEN}Shared login saved to ${AUTH_FILE}${NC}"
    if [ "$kind" = "api_key" ]; then
        echo -e "${YELLOW}That is an API key: it bills per token and has no subscription window.${NC}"
    fi
    echo -e "${GREEN}Other BRUH add-ons will now use this login automatically.${NC}"
}

# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------
# Reports all three stores rather than only the shared one. That is the whole
# point of the rewrite: `--status` used to answer "not set up" to somebody who
# had signed in perfectly well through the panel, because it only ever looked
# at the file it writes itself. "Signed in" and "signed in AND shared" are
# different states, and only one of them is a problem.

human_time() {
    local epoch="$1"
    [ -n "$epoch" ] || return 0
    date -d "@${epoch}" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo "epoch ${epoch}"
}

# Report one of the two shape-contract files (the panel's or the shared one).
report_contract_file() {
    local label="$1" path="$2"
    if [ ! -f "$path" ]; then
        echo -e "  ${DIM}${label}: —${NC}"
        return 1
    fi
    local kind value saved
    kind=$(jq -r '.type // ""' "$path" 2>/dev/null)
    value=$(jq -r '.value // ""' "$path" 2>/dev/null)
    saved=$(jq -r '.saved_at // empty' "$path" 2>/dev/null | grep -oE '^[0-9]+' || true)
    if [ -z "$value" ] || [ -z "$kind" ]; then
        echo -e "  ${YELLOW}${label}: unreadable or malformed${NC}"
        return 1
    fi
    local when=""
    [ -n "$saved" ] && when=" ${DIM}(saved $(human_time "$saved"))${NC}"
    echo -e "  ${GREEN}${label}: ${kind}${NC}${when}"
    return 0
}

# The CLI's own store is a different shape and the only one that records an
# expiry — so it is the only one whose liveness can actually be checked.
# Being shaped like a credential is not being one.
report_cli_file() {
    if [ ! -f "$CLI_FILE" ]; then
        echo -e "  ${DIM}Claude Code's own login: —${NC}"
        return 1
    fi
    local token expires now
    token=$(jq -r '.claudeAiOauth.accessToken // ""' "$CLI_FILE" 2>/dev/null)
    expires=$(jq -r '.claudeAiOauth.expiresAt // 0' "$CLI_FILE" 2>/dev/null)
    now=$(date +%s)
    if [ -z "$token" ]; then
        echo -e "  ${YELLOW}Claude Code's own login: unreadable${NC}"
        return 1
    fi
    # A missing or zero expiresAt means the file records none, not that the
    # token is past it.
    if [ "${expires%%.*}" -gt 0 ] 2>/dev/null; then
        local secs
        secs=$(( expires / 1000 - now ))
        if [ "$secs" -le 60 ]; then
            echo -e "  ${RED}Claude Code's own login: EXPIRED${NC} ${DIM}($(human_time $(( expires / 1000 ))))${NC}"
            return 1
        fi
        echo -e "  ${GREEN}Claude Code's own login: active${NC} ${DIM}(expires in $(( secs / 3600 ))h $(( (secs % 3600) / 60 ))m)${NC}"
        return 0
    fi
    echo -e "  ${GREEN}Claude Code's own login: active${NC} ${DIM}(no expiry recorded)${NC}"
    return 0
}

show_status() {
    echo -e "${CYAN}Claude credentials${NC}"
    report_cli_file;                                       local cli=$?
    report_contract_file "Panel sign-in" "$PANEL_FILE";     local panel=$?
    report_contract_file "Shared with other add-ons" "$AUTH_FILE"; local shared=$?
    echo ""

    if [ "$shared" -eq 0 ]; then
        echo -e "${GREEN}Shared login: ACTIVE${NC} — other BRUH add-ons can use it."
        echo -e "  File: $AUTH_FILE"
        echo -e "  ${DIM}ha login --revoke removes it.${NC}"
        exit 0
    fi

    echo -e "${YELLOW}Shared login: not set up${NC}"
    if [ "$panel" -eq 0 ]; then
        # The case that used to read as "you are not signed in".
        echo -e "You ${GREEN}are${NC} signed in — through the panel — it just isn't shared yet."
        echo -e "  Publish it with: ${CYAN}ha login --share${NC}"
    elif [ "$cli" -eq 0 ]; then
        echo -e "You ${GREEN}are${NC} signed in — Claude Code holds its own login — but that one"
        echo -e "cannot be shared: it is a short-lived session token that refreshes itself,"
        echo -e "and the shared file has no way to refresh anything."
        echo -e "  Mint a long-lived token to share: ${CYAN}ha login${NC}"
    else
        echo -e "No Claude credential found anywhere."
        echo -e "  Sign in here:      ${CYAN}ha login${NC}   ${DIM}(or just: claude)${NC}"
        echo -e "  Or in the panel:   ${DIM}brAIn → ⚙ Settings → Claude account${NC}"
    fi
    exit 0
}

revoke() {
    if [ -f "$AUTH_FILE" ]; then
        rm -f "$AUTH_FILE"
        echo -e "${GREEN}Shared login file deleted.${NC}"
        echo -e "${YELLOW}Note: the token itself is still valid. To revoke it entirely, visit"
        echo -e "https://claude.ai/settings (or console.anthropic.com for an API key) and revoke it there.${NC}"
    else
        echo -e "${YELLOW}No shared login file to delete.${NC}"
    fi
    exit 0
}

# ---------------------------------------------------------------------------
# --share: publish a login that already exists
# ---------------------------------------------------------------------------
# Signing in twice to get one credential into two files is the sort of chore
# people do once and then stop trusting the tool over. The panel's store
# already holds exactly the shape the shared file wants, so copying it is the
# whole operation.
#
# What is deliberately NOT copied is Claude Code's own .credentials.json: its
# accessToken is a session token the CLI refreshes for itself, the shared file
# records no refresh token and nothing reads one, so publishing it would work
# for a few hours and then break every add-on reading it — with nothing to say
# why. That failure is worth a sentence rather than a silent success.
share_existing() {
    if [ -f "$AUTH_FILE" ] && [ "$FORCE" != "true" ]; then
        echo -e "${YELLOW}A shared login already exists (${AUTH_FILE}).${NC}"
        echo -e "Re-run with ${CYAN}--force${NC} to replace it, or ${CYAN}ha login --status${NC} to inspect it."
        exit 1
    fi

    if [ -f "$PANEL_FILE" ]; then
        local value
        value=$(jq -r '.value // ""' "$PANEL_FILE" 2>/dev/null)
        if [ -n "$value" ] && [ -n "$(classify "$value")" ]; then
            echo -e "${CYAN}Publishing the panel's login to the shared file…${NC}"
            write_auth_file "$value"
            exit 0
        fi
        if [ -n "$value" ]; then
            echo -e "${RED}The panel's stored credential is not a shareable shape.${NC}" >&2
            echo -e "Only a long-lived ${CYAN}sk-ant-oat…${NC} token or an ${CYAN}sk-ant-api…${NC} key can be shared." >&2
            exit 1
        fi
    fi

    echo -e "${YELLOW}Nothing to share.${NC}" >&2
    if [ -f "$CLI_FILE" ]; then
        echo -e "Claude Code has its own login here, but it cannot be shared: that is a" >&2
        echo -e "short-lived session token which the CLI refreshes itself, and the shared" >&2
        echo -e "file has nowhere to record a refresh — every add-on reading it would break" >&2
        echo -e "within hours, silently." >&2
        echo -e "Run ${CYAN}ha login${NC} to mint a long-lived token that can be shared." >&2
    else
        echo -e "Sign in first: ${CYAN}ha login${NC}, or from the panel's ⚙ Settings → Claude account." >&2
    fi
    exit 1
}

# ---------------------------------------------------------------------------
# Interactive OAuth
# ---------------------------------------------------------------------------

# `claude setup-token` is an interactive OAuth round trip: it prints a URL,
# then BLOCKS reading a code from stdin. Without a terminal there is nothing
# to read from and nothing to type into, so it blocks forever — which is not
# a hang anybody can diagnose from the outside: the last thing printed is
# "Starting the Claude OAuth token flow…" and then silence until something
# kills it. Refusing up front, by name, with the two routes that do work
# without a terminal, is the whole of the fix.
require_tty() {
    if [ -t 0 ] && [ -t 1 ]; then
        return 0
    fi
    echo -e "${RED}ha login needs a real terminal, and this isn't one.${NC}" >&2
    echo "" >&2
    echo -e "Signing in is an OAuth round trip: it prints a link, you open it, and it" >&2
    echo -e "waits for you to paste a code back. With no terminal attached there is" >&2
    echo -e "nothing to paste into, so it would sit here until something killed it." >&2
    echo "" >&2
    echo -e "${CYAN}Where this does work:${NC}" >&2
    echo -e "  • brAIn's panel → ${GREEN}Terminal${NC} tab, then run ${CYAN}ha login${NC} there." >&2
    echo -e "    (Not the separate Terminal & SSH add-on — that is a different container," >&2
    echo -e "     and its \`ha\` is the Supervisor CLI, an unrelated tool.)" >&2
    echo -e "  • brAIn's panel → ${GREEN}⚙ Settings → Claude account → Sign in${NC}, which runs" >&2
    echo -e "    the same flow with the panel holding the terminal for you." >&2
    echo "" >&2
    echo -e "${CYAN}Without any terminal at all:${NC}" >&2
    echo -e "  • ${CYAN}ha login --share${NC}   publish a login you have already made" >&2
    echo -e "  • ${CYAN}ha login --token sk-ant-oat…${NC}   paste a token minted elsewhere" >&2
    echo -e "  • ${CYAN}ha login --status${NC}   see what you already have" >&2
    exit 2
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
        echo -e "  ${CYAN}ha login --token sk-ant-oat...${NC}"
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
        --status|status)  ACTION="status" ;;
        --revoke|revoke)  ACTION="revoke" ;;
        --share|share)    ACTION="share" ;;
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
    share)  share_existing ;;
    token)  write_auth_file "$TOKEN" ;;
    login)
        # Before anything else: a flow that cannot possibly complete should
        # say so instead of starting. The overwrite prompt below reads stdin
        # too, so this guard has to come first either way.
        require_tty
        if [ -f "$AUTH_FILE" ] && [ "$FORCE" != "true" ]; then
            echo -e "${YELLOW}A shared login already exists (${AUTH_FILE}).${NC}"
            printf "Overwrite it with a new token? [y/N] "
            read -r answer
            case "$answer" in
                y|Y|yes|YES) ;;
                *) echo "Keeping the existing shared login. Use --status to inspect it."; exit 0 ;;
            esac
        fi
        interactive_login
        ;;
esac
