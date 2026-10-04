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
# Every other argument is passed through to claude-run. The permissions
# flag is NOT one of them any more: it is decided HERE, when the session
# starts, from the switch's current value (brain-permissions.sh) — the flag
# used to be baked into the command ttyd was started with at boot, so
# "Let brAIn act without asking" needed an add-on restart to reach a new
# session, and a window the chat opened on a handoff never carried it at
# all. A flag handed in by an older launch command is dropped and decided
# again, so what the switch says now is the only answer.

set -uo pipefail

HANDOFF_FILE="${BRAIN_TERMINAL_HANDOFF:-/data/terminal-handoff.json}"
HANDOFF_MAX_AGE=600     # seconds
CLAUDE_RUN="${BRAIN_CLAUDE_RUN:-/usr/local/bin/claude-run}"

perms_lib="${BRAIN_PERMS_LIB:-/opt/scripts/brain-permissions.sh}"
if [ ! -r "$perms_lib" ]; then
    perms_lib="$(dirname "${BASH_SOURCE[0]}")/brain-permissions.sh"
fi

args=()
for arg in "$@"; do
    [ "$arg" = "--dangerously-skip-permissions" ] || args+=("$arg")
done
# No library is no flag: a session that cannot ask the switch asks you.
if [ -r "$perms_lib" ]; then
    # shellcheck disable=SC1090
    . "$perms_lib"
    perms_flag=$(brain_perms_flag)
    if [ -n "$perms_flag" ]; then
        args=("$perms_flag" ${args[@]+"${args[@]}"})
    fi
fi
set -- ${args[@]+"${args[@]}"}

resume_id=""

if [ -r "$HANDOFF_FILE" ]; then
    # Consume it first, whatever happens next: a handoff that fails to
    # launch must not be retried forever.
    handoff=$(cat "$HANDOFF_FILE" 2>/dev/null)
    rm -f "$HANDOFF_FILE"

    # A handoff missing its ts must read as too old, not abort the shell:
    # an empty substitution inside $(( )) is an arithmetic error, and this
    # script opening is the terminal session starting.
    ts=$(printf '%s' "$handoff" \
        | sed -n 's/.*"ts"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/p')
    age=$(( $(date +%s) - ${ts:-0} ))
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
    "$CLAUDE_RUN" "$@" --resume "$resume_id" && exit 0
    echo "That conversation could not be resumed — starting a new session."
fi

exec "$CLAUDE_RUN" "$@"
