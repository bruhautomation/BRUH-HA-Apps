#!/bin/bash

# brain-auth-env — resolve the stored Claude credential and emit the export
# line that hands it to the CLI. Meant to be SOURCED, not run:
#
#     . /opt/scripts/brain-auth-env.sh
#
# Why this exists: signing in through the panel and signing in through the
# terminal used to be two different add-ons, and the sharing only ran one
# way — the terminal's `ha login` published a credential the panel read.
# Merged into one add-on the panel became the primary sign-in surface, so
# the arrow now has to point both ways: a panel login must reach the CLI
# too, or the terminal asks you to log in again for no reason.
#
# Resolution order:
#   1. the CLI's own ~/.claude/.credentials.json  — it authenticates itself,
#      so emit nothing and let it, but only while that credential is still
#      live (see below)
#   2. the panel's store                          — a pasted token or API key
#   3. the shared file on /config                 — written by `ha login`
#
# Note this is NOT the panel's order: engine.get_auth prefers its own store
# and consults the CLI last. The two differ on purpose — a `claude /login`
# done in this terminal is the most recent thing the person did here, and
# overriding it with an older pasted token would be wrong. What is not
# allowed is preferring a CLI credential that is *dead*, which is what step
# 1 used to do.
#
# Emits nothing at all when there is no credential: an unset variable is
# the correct state for "not signed in", and exporting an empty one makes
# the CLI fail with a confusing auth error instead of prompting to log in.

# Never echo a credential into a trace.
set +x

_brain_auth_home="${BRAIN_HOME:-/data/home}"
_brain_auth_local="${BRAIN_SECRETS:-/data/secrets}/claude_auth.json"
_brain_auth_shared="${BRAIN_SHARED_AUTH:-/config/.brain/secrets/claude_auth.json}"
_brain_auth_cli="${_brain_auth_home}/.claude/.credentials.json"

# 1. The CLI holds its own OAuth credential — it refreshes that itself, and
#    injecting a stale token over the top would break the refresh.
#
#    Only while it is still live, though. `startswith("sk-ant-")` says a
#    token is *shaped* like a credential, not that it is one: a revoked
#    session, a container that was down past the expiry, or a refresh that
#    errored mid-flight all leave a well-formed dead token behind. Deferring
#    to it emits nothing, so the CLI tries the dead token and prompts for a
#    login — while a working credential sits unread ten lines below. That is
#    self-perpetuating, because run.sh restores .credentials.json from its
#    backup whenever the live file goes missing.
#
#    A missing or zero expiresAt is treated as live: it means the file does
#    not record one, not that the token is past it.
if [ -r "$_brain_auth_cli" ] \
    && jq -e --argjson now "$(date +%s)" '
        (.claudeAiOauth // {}) as $o
        | (($o.accessToken // "") | startswith("sk-ant-"))
          and (($o.expiresAt // 0) <= 0
               or (($o.expiresAt / 1000) > ($now + 60)))
    ' "$_brain_auth_cli" > /dev/null 2>&1; then
    unset _brain_auth_home _brain_auth_local _brain_auth_shared _brain_auth_cli
    return 0 2>/dev/null || exit 0
fi

_brain_auth_file=""
for _candidate in "$_brain_auth_local" "$_brain_auth_shared"; do
    if [ -r "$_candidate" ]; then
        _brain_auth_file="$_candidate"
        break
    fi
done

if [ -n "$_brain_auth_file" ]; then
    _brain_auth_type=$(jq -r '.type // ""' "$_brain_auth_file" 2>/dev/null)
    _brain_auth_value=$(jq -r '.value // ""' "$_brain_auth_file" 2>/dev/null)

    if [ -n "$_brain_auth_value" ]; then
        case "$_brain_auth_type" in
            api_key)
                export ANTHROPIC_API_KEY="$_brain_auth_value"
                unset CLAUDE_CODE_OAUTH_TOKEN
                ;;
            oauth_token)
                export CLAUDE_CODE_OAUTH_TOKEN="$_brain_auth_value"
                unset ANTHROPIC_API_KEY
                ;;
        esac
    fi
    unset _brain_auth_type _brain_auth_value
fi

unset _brain_auth_home _brain_auth_local _brain_auth_shared _brain_auth_cli \
      _brain_auth_file _candidate
return 0 2>/dev/null || exit 0
