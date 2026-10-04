#!/bin/bash
# Sourced, not run: whether a terminal session starting NOW may act without
# asking.
#
#   source /opt/scripts/brain-permissions.sh
#   flag=$(brain_perms_flag)     # "--dangerously-skip-permissions" or ""
#
# The switch is the add-on option `dangerously_skip_permissions` ("Let brAIn
# act without asking"), which ⚙ → Terminal & chat edits too. It used to reach
# the terminal as a flag baked into the command ttyd was started with, so a
# change needed an add-on restart. Now the panel publishes the current value
# to one file whenever it moves (panel/permission_mode.py), run.sh writes the
# same file at boot before ttyd starts, and the two launchers —
# brain-terminal-start and the session picker — ask this function when a
# session starts.
#
# A security default may only fail closed, so:
#
#   * the file holding exactly `bypass` is the only thing that means act.
#     `ask`, an empty file, a half-written one, garbage, a directory, a file
#     this user cannot read — all of those print nothing, which is asking.
#   * only an ABSENT file falls back, to the flag run.sh wrote into
#     /data/.brain_env at boot, and only the exact flag counts there too.
#     Something at the path that cannot be read is not the same claim as
#     nothing having been written yet.
#
# Never fails and never prints anything but the flag: it is called inside a
# `$( )` on the way to starting somebody's session.

BRAIN_PERMISSIONS_FILE="${BRAIN_PERMISSIONS_FILE:-/data/brain-permissions}"
BRAIN_PERMS_ENV_FILE="${BRAIN_PERMS_ENV_FILE:-/data/.brain_env}"

brain_perms_flag() {
    local file="$BRAIN_PERMISSIONS_FILE" word=""
    if [ -e "$file" ] || [ -L "$file" ]; then
        word=$(head -c 32 "$file" 2>/dev/null | tr -d '[:space:]')
        if [ "$word" = "bypass" ]; then
            printf '%s\n' "--dangerously-skip-permissions"
        fi
        return 0
    fi
    if [ -r "$BRAIN_PERMS_ENV_FILE" ]; then
        # Read, not sourced: the one value is all this needs, and a reader
        # that executes a file to learn a word inherits everything else in it.
        word=$(sed -n 's/^export BRAIN_CLAUDE_PERMS_FLAG="\([^"]*\)"$/\1/p' \
            "$BRAIN_PERMS_ENV_FILE" 2>/dev/null | tail -n 1)
        if [ "$word" = "--dangerously-skip-permissions" ]; then
            printf '%s\n' "$word"
        fi
    fi
    return 0
}
