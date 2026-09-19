#!/bin/bash
# brain-memory-lock — the shell half of panel/atomic_write.py's `locked`.
#
# Sourced, not run: it is a library, not a command.
#
#   source /opt/scripts/brain-memory-lock.sh
#   brain_with_store_lock "$HYPOTHESES_FILE" append_the_guesses
#
# WHY THIS EXISTS. `/config/.brain/memory/hypotheses.jsonl` has three
# writers in three processes: the panel (read the whole file, change one
# entry, write it all back), this script's caller `brain-learn.sh`
# (appending a proposed guess with a bare `>>`), and the consolidator's
# `retire_stale_hypotheses` (rewriting the file to age entries out). An
# atomic replace — which is what both Python and the `jq`+`mv` here do —
# makes each of those writes indivisible and does NOTHING for the window
# between a read and its rename. A guess appended in that window is not
# corrupted; it is gone, and nothing anywhere raises, because the file the
# winner wrote is complete, correct, and simply predates it. The homeowner
# sees a study session that said it queued three guesses and a queue
# holding two.
#
# The lock has to be the SAME lock the panel takes or it is decoration, so
# two things are pinned rather than described, and `tests/test_store_locking.py`
# reads both out of these files:
#
#   * the name — `<store>.lock`, beside the store. A sidecar rather than
#     the store itself because `os.replace`/`mv` swaps in a new inode: a
#     lock held on the store is released into a file nobody can reach the
#     moment the write lands, and the next writer locks a different inode.
#   * flock, and only flock — advisory, held by the open file description,
#     released by the kernel when the process dies, and the one kind of
#     lock a Python module and a shell script can both take.
#
# Three details are the difference between a lock and a lock-shaped file:
#
#   * `7<`, never `7>`. `>` truncates the holder's file at open, and it
#     also needs write permission on a file the OTHER user may have created
#     — the panel is root and this runs as `claude`. flock wants a file
#     description, not write access, so read-only is both correct and the
#     only thing that works for both halves.
#   * fd 7 on purpose. The consolidator already holds its own pass lock on
#     fd 9 and probes on fd 8 while this runs inside it; reusing either
#     would drop the lock that says only one consolidation runs at a time.
#   * `-n` and poll, never `-w`. This image is Alpine, whose flock is
#     BusyBox's and takes only -sxnu: it answers `-w` by printing usage and
#     exiting 1, which is the SAME status as "the lock is held". That
#     mistake once stopped memory updating at all, so the probe below asks
#     with the same `-n` the real call uses — and asks it on a scratch file
#     of its own, never on the real lock, or a lock somebody is honestly
#     holding would read as "flock does not work here" and every caller
#     would talk itself into running unlocked at exactly the moment the
#     lock was doing its job.
#
# A lock that cannot be taken NEVER refuses the work — it runs unlocked,
# which is precisely what every one of these writers did before this file
# existed. Losing a homeowner's study session to a stale lock on a
# filesystem that does not support locking is a worse failure than the race
# this closes.

# Kept identical to atomic_write.LOCK_SUFFIX / LOCK_TIMEOUT_S.
BRAIN_STORE_LOCK_SUFFIX=".lock"
BRAIN_STORE_LOCK_WAIT="${BRAIN_STORE_LOCK_WAIT:-10}"
BRAIN_STORE_LOCK_POLL="${BRAIN_STORE_LOCK_POLL:-1}"

brain_store_lock_path() {  # brain_store_lock_path <store> -> <store>.lock
    printf '%s%s' "$1" "$BRAIN_STORE_LOCK_SUFFIX"
}

# Can flock in THIS image take a lock at all? Asked with the same flag the
# real call uses, on a scratch file of its own — see the header for why it
# may not be asked of the real one.
brain_store_flock_usable() {  # brain_store_flock_usable <lockfile>
    command -v flock > /dev/null 2>&1 || return 1
    local probe="$1.probe" rc=0
    ( exec 6> "$probe" && flock -n 6 ) > /dev/null 2>&1 || rc=1
    rm -f "$probe" 2>/dev/null
    return "$rc"
}

# Run a command while holding a store's lock. The command runs in THIS
# shell, so anything it assigns is still assigned afterwards — the callers
# count what they filed.
brain_with_store_lock() {  # brain_with_store_lock <store> <command...>
    local store="$1"
    shift
    [ -n "$store" ] || { "$@"; return $?; }

    local lock
    lock=$(brain_store_lock_path "$store")
    mkdir -p "$(dirname "$lock")" 2>/dev/null

    if ! brain_store_flock_usable "$lock"; then
        "$@"
        return $?
    fi
    # Append-create rather than truncate: whichever half gets here first
    # makes the file, and the other may only be able to read it.
    # Owner-only, and root hands it to the `claude` user —
    # atomic_write.LOCK_MODE's rule, so the two halves make the same file
    # whichever gets there first: root opens anything, so a lock the other
    # user owns is one both can take, and no group or world bit is needed.
    if [ ! -e "$lock" ]; then
        { : >> "$lock" && chmod 600 "$lock"; } 2>/dev/null
        [ "$(id -u)" = "0" ] && chown claude "$lock" 2>/dev/null
    fi
    # The braces are load-bearing: `exec 7< f 2>/dev/null` with no command
    # applies BOTH redirections to this shell for good, and the second one
    # sent every later line the caller wrote to stderr — the consolidator's
    # log, `brain memory`'s "the panel is not answering" — into /dev/null.
    # Grouped, the stderr redirect ends with the group and only fd 7 stays.
    if ! { exec 7< "$lock"; } 2>/dev/null; then
        "$@"
        return $?
    fi

    local waited=0
    until flock -n 7; do
        if [ "$waited" -ge "$BRAIN_STORE_LOCK_WAIT" ]; then
            # Past any honest holder. Run anyway — see the header.
            exec 7<&-
            "$@"
            return $?
        fi
        sleep "$BRAIN_STORE_LOCK_POLL"
        waited=$((waited + BRAIN_STORE_LOCK_POLL))
    done

    "$@"
    local rc=$?
    # Released here, not at exit: the consolidator's daemon is one process
    # that outlives every pass it runs, and a lock held for the process
    # instead of the pass is a lock nobody else can ever take.
    exec 7<&-
    return "$rc"
}
