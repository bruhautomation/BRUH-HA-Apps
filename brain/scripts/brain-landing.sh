#!/bin/bash
# brain-landing — the shell half of engine.py's landing.
#
# Sourced, not run: it is a library, not a command. A turn cap is a runaway
# guard and never a budget, and a guard that trips has to change what
# happens next — otherwise every token the run spent is thrown away with
# the answer. So a `claude -p` run that ended on the CLI's own turn cap is
# LANDED: one more invocation, `--resume` on the same session, two turns,
# and a prompt that says finish now with what you have. The resumed
# conversation still holds everything the run read, so what comes back is
# the answer in the task's own format plus one sentence about what it did
# not get to — a partial that files, instead of a thorough one that never
# did.
#
#   source /opt/scripts/brain-landing.sh
#   if brain_hit_turn_cap "$output" "$err_file"; then
#       landed=$(brain_land "$sid" "$seconds_left" "$err_file" -- \
#                    $claude_cmd -p <the run's own flags, minus --max-turns>) \
#           && output="$landed"
#   fi
#
# One implementation for every shell path (study, ask, both listeners), and
# the numbers match engine.py's LANDING_TURNS / LANDING_MIN_S: two answers
# to "what does landing look like" is the drift this file exists to avoid.
# Every failure here is silent and returns non-zero — the caller keeps the
# run's own ending, which is what it had before this existed.

BRAIN_LANDING_TURNS="${BRAIN_LANDING_TURNS:-2}"
# Below this many seconds left on the run's own wall clock, no landing is
# attempted: a landing that is itself killed by the timeout costs a second
# run and answers nothing.
BRAIN_LANDING_MIN_S="${BRAIN_LANDING_MIN_S:-20}"
BRAIN_LANDING_PROMPT="You have run out of room for further investigation. Do not call any more tools. Finish NOW with what you already have, in exactly the format the task asked for, and end with one sentence saying what you did not get to."

# How the CLI says it: the envelope's own subtype under --output-format
# json, and its stderr line otherwise. Kept in step with journal.classify.
_BRAIN_CAP_RE='error_max_turns|reached (the )?max(imum)? (number of )?turns|max[_ ]turns|turn limit'

# brain_hit_turn_cap <stdout> [<stderr file>]
# 0 when the run ended on the turn cap. A JSON envelope is judged by its
# subtype and never by its words — an answer that happens to mention turns
# is an answer; plain output and stderr are matched on the CLI's wording.
brain_hit_turn_cap() {
    local output="${1:-}" err_file="${2:-}" subtype=""
    if [ -n "$output" ]; then
        subtype=$(printf '%s' "$output" \
            | jq -r 'if type == "object" then (.subtype // "") else "not-json" end' 2>/dev/null)
        case "$subtype" in
            error_max_turns) return 0 ;;
            ""|not-json)
                printf '%s' "$output" | grep -qiE "$_BRAIN_CAP_RE" && return 0 ;;
            *) return 1 ;;
        esac
    fi
    if [ -n "$err_file" ] && [ -r "$err_file" ]; then
        grep -qiE "$_BRAIN_CAP_RE" "$err_file" && return 0
    fi
    return 1
}

# brain_session_from_output <stdout>
# The session id a --output-format json envelope carries, or nothing. A
# run that tripped the cap still names its conversation, and that id is
# what the landing resumes.
brain_session_from_output() {
    printf '%s' "${1:-}" \
        | jq -r 'if type == "object" then (.session_id // empty) else empty end' 2>/dev/null \
        | tr -cd 'A-Za-z0-9._-'
}

# brain_new_session_id
# A fresh id to pass as --session-id, so a text-mode run has one to land
# on. Deliberately unclaimed: whose the session is stays the caller's
# business (brain-run-source.sh), and an unclaimed id reads as the
# person's own.
brain_new_session_id() {
    cat /proc/sys/kernel/random/uuid 2>/dev/null || true
}

# brain_land <session id> <seconds left> <stderr file> -- <claude command and flags…>
# Re-runs the command with --resume and the landing cap, the landing prompt
# on stdin, and prints what came back. The caller's flags must not carry
# --max-turns of their own. Returns the CLI's exit status, or 1 without
# running anything when there is no session to resume or no time to do it.
brain_land() {
    local sid="${1:-}" limit="${2:-0}" err_file="${3:-/dev/null}"
    [ $# -ge 3 ] || return 1
    shift 3
    [ "${1:-}" = "--" ] && shift
    [ -n "$sid" ] || return 1
    [ $# -gt 0 ] || return 1
    [ "$limit" -ge "$BRAIN_LANDING_MIN_S" ] 2>/dev/null || return 1
    printf '%s' "$BRAIN_LANDING_PROMPT" | timeout "$limit" "$@" \
        --resume "$sid" --max-turns "$BRAIN_LANDING_TURNS" 2>"$err_file"
}
