#!/bin/bash

# What the terminal actually launches.
#
# Its whole job is one question: is there a conversation waiting to be
# picked up? The panel's chat tab writes one here when you press "Continue
# in the terminal", so the terminal opens *inside* that conversation rather
# than opening fresh and leaving you to paste a resume command — which is
# the difference between two views of one Claude Code and two Claude Codes.
#
# The handoff is a file rather than injected keystrokes because the terminal
# may be running an interactive REPL, a shell, or nothing at all, and typing
# into whichever of those happens to be in front is a guess. A file is read
# at exactly one moment, by exactly the process that can act on it.
#
# It expires. A stale id would silently reopen last week's conversation the
# next time the add-on restarted, which is worse than starting fresh.
#
# Every argument is passed through to claude-run, so the permissions flag
# the add-on decides on still applies.

set -uo pipefail

HANDOFF_FILE="${BRAIN_TERMINAL_HANDOFF:-/data/terminal-handoff.json}"
HANDOFF_MAX_AGE=600     # seconds

resume_id=""

if [ -r "$HANDOFF_FILE" ]; then
    # Consume it first, whatever happens next: a handoff that fails to
    # launch must not be retried forever.
    handoff=$(cat "$HANDOFF_FILE" 2>/dev/null)
    rm -f "$HANDOFF_FILE"

    age=$(( $(date +%s) - $(printf '%s' "$handoff" \
        | sed -n 's/.*"ts"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p') ))
    candidate=$(printf '%s' "$handoff" \
        | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([A-Za-z0-9._-]*\)".*/\1/p')

    if [ -n "$candidate" ] && [ "$age" -ge 0 ] && [ "$age" -le "$HANDOFF_MAX_AGE" ]; then
        resume_id="$candidate"
        echo "Picking up the conversation from the chat tab…"
    fi
fi

if [ -n "$resume_id" ]; then
    # --resume can fail (the CLI pruned it, or it is from an incompatible
    # version). Falling through to a normal session beats a terminal that
    # exits on open.
    /usr/local/bin/claude-run "$@" --resume "$resume_id" && exit 0
    echo "That conversation could not be resumed — starting a new session."
fi

exec /usr/local/bin/claude-run "$@"
