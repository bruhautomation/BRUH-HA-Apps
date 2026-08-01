#!/bin/bash
# brain-run-source — the shell half of panel/run_sources.py.
#
# Sourced, not run: it is a library, not a command. Background callers that
# drive `claude -p` from /config use it to mint a session id and claim it,
# so the Chats rail can say who a conversation belongs to instead of
# showing a person their own chats buried in machine ones.
#
#   source /opt/scripts/brain-run-source.sh
#   sid=$(brain_new_session memory)      # "" if uuids aren't available
#   [ -n "$sid" ] && args=(--session-id "$sid")
#
# Every failure here is silent and returns empty: this is bookkeeping about
# a run, and it must never be the reason the run doesn't happen.

BRAIN_RUN_SOURCES="${BRAIN_RUN_SOURCES:-/data/run-sources.jsonl}"

# Kept in step with SOURCES in panel/run_sources.py. An unknown source is
# refused here rather than written and silently ignored on the way out.
_brain_known_source() {
    case "$1" in
        voice|automation|memory|study) return 0 ;;
        *) return 1 ;;
    esac
}

# Claim an id we already have (the assist listener mints its own, so that
# the conversation_id -> session mapping stays its business, not ours).
brain_claim_session() {
    local sid="$1" source="$2"
    [ -n "$sid" ] || return 0
    _brain_known_source "$source" || return 0
    mkdir -p "$(dirname "$BRAIN_RUN_SOURCES")" 2>/dev/null || return 0
    # The braces are load-bearing. `cmd >> file 2>/dev/null` silences the
    # COMMAND's stderr, but a redirection that fails to open the file is
    # reported by the shell before the command runs at all — which is how a
    # library documented as silent printed "brain-run-source.sh: line 34:
    # /data/run-sources.jsonl: Permission denied" into the add-on log on
    # every pass. Redirecting the group covers the shell's own message too.
    { printf '{"id":"%s","source":"%s","ts":%s}\n' \
        "$sid" "$source" "$(date +%s)" >> "$BRAIN_RUN_SOURCES"; } 2>/dev/null || return 0
    _brain_prune_sources
    return 0
}

# Mint one and claim it. Prints the id, or nothing when the kernel's uuid
# source isn't readable — callers treat "" as "run without --session-id".
brain_new_session() {
    local sid
    sid=$(cat /proc/sys/kernel/random/uuid 2>/dev/null || true)
    [ -n "$sid" ] || return 0
    brain_claim_session "$sid" "$1"
    printf '%s' "$sid"
}

# An index, not a queue: capped rather than drained. Matched to
# run_sources.MAX_ENTRIES / PRUNE_SLACK so both halves let it drift equally.
_brain_prune_sources() {
    local lines
    lines=$(wc -l < "$BRAIN_RUN_SOURCES" 2>/dev/null || echo 0)
    [ "$lines" -gt 5000 ] 2>/dev/null || return 0
    { tail -n 4000 "$BRAIN_RUN_SOURCES" > "${BRAIN_RUN_SOURCES}.tmp"; } 2>/dev/null \
        && mv "${BRAIN_RUN_SOURCES}.tmp" "$BRAIN_RUN_SOURCES" 2>/dev/null
    rm -f "${BRAIN_RUN_SOURCES}.tmp" 2>/dev/null
    return 0
}
