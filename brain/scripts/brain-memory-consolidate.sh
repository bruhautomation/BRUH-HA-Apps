#!/bin/bash

# brain-memory-consolidate — merge pending inbox facts into memory.md.
#
# Two modes:
#   --once      run a single consolidation pass and exit (used by
#               `brain memory consolidate` and by tests)
#   (default)   daemon loop started by run.sh: consolidates daily, and
#               early whenever the inbox holds more than 20 pending facts
#               (checked every ~5 minutes)
#
# A consolidation pass:
#   1. sweeps external facts from /share/brain/memory-inbox/ (written
#      by other BRUH add-ons) into the local inbox
#   2. retires hypotheses that sat unanswered for 14+ days
#   3. if the inbox is non-empty, runs ONE cheap Claude pass (haiku, no
#      tools, one turn) that outputs the full updated memory.md, a
#      -----VOICE----- separator, and a <=2 KB voice.md distillate
#   4. sanity-checks the output, writes both files atomically, archives the
#      processed inbox files to inbox/processed/ (pruned after 30 days)
#
# On ANY failure (not authenticated, parse failure, oversized output) the
# existing memory files are left untouched and the inbox stays pending.

set -uo pipefail

# Background processes may lose env vars; pick up the persisted environment
# (HOME, auth paths, BRAIN_MEMORY_* options) the same way the listeners do.
if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    source /data/.brain_env
fi

MEMORY_DIR="${BRAIN_MEMORY_DIR:-/config/.brain/memory}"
MEMORY_FILE="$MEMORY_DIR/memory.md"
VOICE_FILE="$MEMORY_DIR/voice.md"
INBOX_DIR="$MEMORY_DIR/inbox"
PROCESSED_DIR="$INBOX_DIR/processed"
HYPOTHESES_FILE="$MEMORY_DIR/hypotheses.jsonl"
LOG_FILE="$MEMORY_DIR/memory.log.jsonl"
SNAPSHOT_DIR="$MEMORY_DIR/snapshots"
SHARE_INBOX="${BRAIN_SHARE_INBOX:-/share/brain/memory-inbox}"
MARKER_FILE="$MEMORY_DIR/.last_consolidated"

MEMORY_MAX_KB="${BRAIN_MEMORY_MAX_KB:-8}"
VOICE_MAX_BYTES=2048
CLAUDE_MODEL="${BRAIN_MEMORY_MODEL:-haiku}"
# A pass rewrites the WHOLE document plus the voice distillate — up to
# 10 KB of output in one turn, not a one-line answer. At 120s that was a
# coin flip on a full document, and every loss looked identical to a
# failure: `timeout` kills the CLI, the pass reports "not authenticated?",
# the inbox stays pending, and the daemon does it again five minutes later
# forever. The queue in the panel never moved and the log filled up.
# 480s is what an insight run gets, for the same reason.
CLAUDE_TIMEOUT="${BRAIN_MEMORY_CLAUDE_TIMEOUT:-480}"

CHECK_INTERVAL="${BRAIN_MEMORY_CHECK_INTERVAL:-300}"     # daemon poll (s)
DAILY_INTERVAL=86400                                     # forced cadence (s)
INBOX_TRIGGER_LINES=20                                   # early-run threshold
HYPOTHESIS_TTL_DAYS=14
LOG_KEEP=200
PROCESSED_PRUNE_DAYS=30

VOICE_SEPARATOR="-----VOICE-----"

# The shrink guard: how much of the document a single consolidation is
# allowed to lose before we assume the model rewrote it instead of merging
# into it. 60% keeps room for real dedup work — merging a week of inbox
# facts genuinely does collapse near-duplicates — while catching the case
# that matters, which is coming back with the bare template.
SHRINK_GUARD_PERCENT="${BRAIN_MEMORY_SHRINK_PERCENT:-60}"
# Below this there is nothing worth protecting, and an early document
# legitimately doubles and halves as it finds its shape.
SHRINK_GUARD_MIN_LINES=6

# What counts as a fact for the guard: lines that carry content, not the
# headings and comments that survive any rewrite. Counting raw lines would
# make a template full of headings look like a full document.
count_content_lines() {
    printf '%s\n' "$1" | grep -cvE '^[[:space:]]*(#|<!--|-->|$)' || true
}

log() {
    echo "[brain-memory] $*"
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

# Move externally-contributed facts (other BRUH add-ons writing to /share
# when the HA integration isn't installed) into the local inbox.
sweep_share_inbox() {
    [ -d "$SHARE_INBOX" ] || return 0
    local moved=0
    for f in "$SHARE_INBOX"/*.jsonl; do
        [ -f "$f" ] || continue
        mkdir -p "$INBOX_DIR"
        if mv "$f" "$INBOX_DIR/$(basename "$f")" 2>/dev/null; then
            moved=$((moved + 1))
        fi
    done
    [ "$moved" -gt 0 ] && log "swept $moved external fact file(s) from $SHARE_INBOX"
    return 0
}

# A guess nobody answers is noise. Expired ones stop being offered but
# stay on record, so the same guess is never floated a second time.
retire_stale_hypotheses() {
    [ -s "$HYPOTHESES_FILE" ] || return 0
    local now cutoff
    now=$(date +%s)
    cutoff=$((now - HYPOTHESIS_TTL_DAYS * 86400))
    if jq -c --argjson cutoff "$cutoff" \
        'if .status == "open" and (.ts // 0) < $cutoff
         then .status = "expired" else . end' \
        "$HYPOTHESES_FILE" > "${HYPOTHESES_FILE}.tmp" 2>/dev/null; then
        mv "${HYPOTHESES_FILE}.tmp" "$HYPOTHESES_FILE"
    else
        rm -f "${HYPOTHESES_FILE}.tmp"
    fi
    return 0
}

# Rejected guesses are the one part of the queue worth showing the model:
# they mark lines of inquiry that turned out to be dead ends. Capped, so
# they can never grow into the wall of text this design replaced.
dead_ends_block() {
    [ -s "$HYPOTHESES_FILE" ] || return 0
    jq -r 'select(.status == "rejected") | .text' "$HYPOTHESES_FILE" 2>/dev/null \
        | tail -20
}

# Record what this pass changed so `brain memory log` can show it and
# `brain memory undo` can put it back.
record_change() {
    local before="$1" after="$2" snapshot="$3" source="$4"
    local added removed
    added=$(comm -13 <(printf '%s\n' "$before" | grep '^- ' | sort -u) \
                     <(printf '%s\n' "$after"  | grep '^- ' | sort -u) 2>/dev/null)
    removed=$(comm -23 <(printf '%s\n' "$before" | grep '^- ' | sort -u) \
                       <(printf '%s\n' "$after"  | grep '^- ' | sort -u) 2>/dev/null)
    # Nothing actually changed: don't clutter the log with a no-op entry.
    if [ -z "${added//[[:space:]]/}" ] && [ -z "${removed//[[:space:]]/}" ]; then
        return 0
    fi
    jq -cn --argjson ts "$(date +%s)" --arg snapshot "$snapshot" --arg source "$source" \
        --arg added "$added" --arg removed "$removed" \
        '{ts: $ts, snapshot: $snapshot, source: $source,
          added:   ($added   | split("\n") | map(select(length > 0) | ltrimstr("- "))),
          removed: ($removed | split("\n") | map(select(length > 0) | ltrimstr("- ")))}' \
        >> "$LOG_FILE" 2>/dev/null || true
    # Keep the log (and its snapshots) bounded.
    if [ "$(wc -l < "$LOG_FILE" 2>/dev/null || echo 0)" -gt "$LOG_KEEP" ]; then
        tail -n "$LOG_KEEP" "$LOG_FILE" > "${LOG_FILE}.tmp" && mv "${LOG_FILE}.tmp" "$LOG_FILE"
    fi
    find "$SNAPSHOT_DIR" -name '*.md' -mtime +90 -delete 2>/dev/null || true
    return 0
}

pending_inbox_files() {
    for f in "$INBOX_DIR"/*.jsonl; do
        [ -f "$f" ] || continue
        echo "$f"
    done
}

count_pending_lines() {
    local files count
    files=$(pending_inbox_files)
    if [ -z "$files" ]; then
        echo 0
        return
    fi
    # shellcheck disable=SC2086
    count=$(cat $files 2>/dev/null | grep -c . || true)
    echo "${count:-0}"
}

build_prompt() {
    local current_memory="$1" inbox_lines="$2"
    local dead_ends
    dead_ends=$(dead_ends_block)
    cat << PROMPT
You maintain a small long-term memory file about one household for a smart-home assistant.

Today's date is $(date -u +%Y-%m-%d).

CURRENT memory.md:
<<<MEMORY
${current_memory}
MEMORY

NEW candidate facts (JSONL, one per line; each has ts/source/fact/confidence; newest last):
<<<FACTS
${inbox_lines}
FACTS

Lines beginning "FORGET: " are removal requests, not facts: drop the matching content from the document (including rewordings of it) and do not record the request itself.

${dead_ends:+Lines of inquiry the homeowner has already rejected — do not reintroduce them or build on them:
${dead_ends}
}
Output the FULL updated memory.md: merge the new facts into the existing sections (## Preferences, ## Entity nicknames, ## Household patterns, ## Device notes), dedupe, resolve contradictions with newest-wins, and keep the file under ${MEMORY_MAX_KB} KB by dropping the lowest-value and oldest facts first. NEVER include secrets, credentials, transient device states, or one-off commands. Keep the header comment lines.

Dating rules — facts must never masquerade as timeless truths:
- End EVERY fact line with an observed-at marker: (observed YYYY-MM-DD). Carry existing markers forward unchanged; date new facts from their ts field; give undated existing facts today's date.
- Device-health observations (dead battery, offline/unavailable, frozen sensor, unreachable device) are snapshots, not permanent facts: phrase them "as of <date>" and append "— re-verify before asserting". A battery replaced weeks ago must not still be reported dead.
- DROP device-health observations whose observed date is older than 30 days — stale health claims are worse than none.

Then print exactly this separator on its own line:
${VOICE_SEPARATOR}

Then print a voice.md distillate (2 KB maximum): ONLY entity nicknames, the top preferences, and device caveats — what a voice assistant needs on every request. Short markdown bullets.

Output ONLY the two files and the separator — no commentary, no code fences.
PROMPT
}

consolidate_once() {
    mkdir -p "$MEMORY_DIR" "$INBOX_DIR"

    sweep_share_inbox
    retire_stale_hypotheses

    local files
    files=$(pending_inbox_files)
    if [ -z "$files" ]; then
        log "inbox empty — nothing to consolidate"
        touch "$MARKER_FILE" 2>/dev/null || true
        return 0
    fi

    local inbox_lines current_memory
    # shellcheck disable=SC2086
    inbox_lines=$(cat $files 2>/dev/null | grep . || true)
    current_memory=$(cat "$MEMORY_FILE" 2>/dev/null || echo "")

    local prompt output
    prompt=$(build_prompt "$current_memory" "$inbox_lines")

    local claude_cmd
    claude_cmd=$(resolve_claude)
    log "consolidating $(printf '%s\n' "$inbox_lines" | wc -l) fact(s) with model ${CLAUDE_MODEL}..."

    # The pass claims its session id before running, so the Chats rail can
    # label the transcript the CLI is about to leave behind as this rather
    # than as something you typed. An older CLI without --session-id is
    # handled below: the run is what matters, the label is bookkeeping.
    local session_args=() session_id="" source_lib
    source_lib="${BRAIN_RUN_SOURCE_LIB:-/opt/scripts/brain-run-source.sh}"
    if [ -r "$source_lib" ]; then
        # shellcheck disable=SC1090
        . "$source_lib"
        session_id=$(brain_new_session memory)
        [ -n "$session_id" ] && session_args=(--session-id "$session_id")
    fi

    # stderr is kept, not discarded. Throwing it away is what made every
    # failure — timeout, rate limit, a malformed prompt — report itself as
    # "not authenticated?", which sent people to re-do a sign-in that was
    # fine while the real cause stayed invisible.
    local err_file rc=0
    err_file=$(mktemp 2>/dev/null || echo "/tmp/brain-memory-err.$$")
    # shellcheck disable=SC2086
    output=$(printf '%s' "$prompt" | timeout "$CLAUDE_TIMEOUT" \
            $claude_cmd -p --disallowedTools "*" --max-turns 1 \
            "${session_args[@]}" \
            --model "$CLAUDE_MODEL" 2>"$err_file") || rc=$?

    # An older CLI answers an unknown flag with usage and a non-zero exit.
    # Drop the label and run the pass — a conversation nobody can attribute
    # beats a consolidation that never happens.
    if [ "$rc" != 0 ] && [ "${#session_args[@]}" -gt 0 ] \
       && grep -qi "unknown option\|unrecognized option" "$err_file" 2>/dev/null; then
        log "this Claude CLI has no --session-id — running unlabelled"
        rc=0
        # shellcheck disable=SC2086
        output=$(printf '%s' "$prompt" | timeout "$CLAUDE_TIMEOUT" \
                $claude_cmd -p --disallowedTools "*" --max-turns 1 \
                --model "$CLAUDE_MODEL" 2>"$err_file") || rc=$?
    fi

    if [ "$rc" != 0 ]; then
        local why detail
        # 124 is `timeout`'s, and it is the failure this pass actually has:
        # say so, with the number to raise, instead of blaming the login.
        if [ "$rc" = 124 ]; then
            why="Claude did not finish inside ${CLAUDE_TIMEOUT}s (raise BRAIN_MEMORY_CLAUDE_TIMEOUT)"
        else
            why="Claude exited ${rc}"
        fi
        detail=$(grep -v '^[[:space:]]*$' "$err_file" 2>/dev/null | tail -n 1 | cut -c1-200)
        rm -f "$err_file"
        log "${why}${detail:+ — $detail} — inbox left pending"
        return 1
    fi
    rm -f "$err_file"

    if ! printf '%s\n' "$output" | grep -qxF -- "$VOICE_SEPARATOR"; then
        log "output missing the ${VOICE_SEPARATOR} separator — inbox left pending"
        return 1
    fi

    local new_memory new_voice
    new_memory=$(printf '%s\n' "$output" | sed "/^${VOICE_SEPARATOR}\$/,\$d")
    new_voice=$(printf '%s\n' "$output" | sed "1,/^${VOICE_SEPARATOR}\$/d")

    # Sanity checks: both parts non-empty, memory keeps its section
    # structure, and neither blows its size cap. On failure, keep the old
    # files and leave the inbox pending for the next attempt.
    if [ -z "$(printf '%s' "$new_memory" | tr -d '[:space:]')" ] || \
       [ -z "$(printf '%s' "$new_voice" | tr -d '[:space:]')" ]; then
        log "empty memory or voice section in output — inbox left pending"
        return 1
    fi
    if ! printf '%s' "$new_memory" | grep -q "##"; then
        log "updated memory.md lost its section headings — inbox left pending"
        return 1
    fi

    # The document must not come back mostly empty.
    #
    # Every check above passes for a memory.md that is nothing but its four
    # headings: it is non-empty, it has "##", and it is well under the cap.
    # So a pass where the model rewrote instead of merging — or summarised
    # the whole house down to three lines — would replace a year of learned
    # facts with a blank template, and every guard would wave it through.
    # That is the shape of "my memory got erased".
    #
    # Consolidation ADDS: it merges the inbox in, dedupes, and only drops
    # anything when the document is near its size cap. So losing a large
    # share of the content lines in one pass is not a merge, whatever it
    # says. Refuse it, keep both the document and the inbox, and let the
    # next pass try again — a stale memory is recoverable, a wiped one is
    # not.
    local old_content new_content shrink_floor
    old_content=$(count_content_lines "$current_memory")
    new_content=$(count_content_lines "$new_memory")

    # Coming back with nothing but headings is erasure, at any size. There
    # is no document small enough for this to be a legitimate merge, so it
    # is refused before the proportional guard gets a say.
    if [ "$old_content" -gt 0 ] && [ "$new_content" -eq 0 ]; then
        log "REFUSED: consolidation returned an empty template over ${old_content} existing fact(s) — inbox left pending, document untouched"
        return 1
    fi

    # Proportional guard for the partial case. Skipped while the document is
    # small enough that it legitimately doubles and halves as it finds its
    # shape, and skipped when it is at its cap, where shrinking is the job
    # we asked for.
    if [ "$old_content" -ge "$SHRINK_GUARD_MIN_LINES" ] \
       && [ "${#current_memory}" -lt $((MEMORY_MAX_KB * 1024 * 9 / 10)) ]; then
        shrink_floor=$((old_content * SHRINK_GUARD_PERCENT / 100))
        if [ "$new_content" -lt "$shrink_floor" ]; then
            log "REFUSED: consolidation would cut memory.md from ${old_content} to ${new_content} facts — inbox left pending, document untouched"
            return 1
        fi
    fi
    if [ "${#new_memory}" -gt $((MEMORY_MAX_KB * 1024)) ]; then
        log "updated memory.md exceeds ${MEMORY_MAX_KB} KB — inbox left pending"
        return 1
    fi
    if [ "${#new_voice}" -gt "$VOICE_MAX_BYTES" ]; then
        log "voice.md distillate exceeds ${VOICE_MAX_BYTES} bytes — inbox left pending"
        return 1
    fi

    # Snapshot the pre-merge document BEFORE overwriting it — this is what
    # `brain memory undo` restores, and it has to exist even if the write
    # below is the thing that goes wrong.
    local snapshot=""
    mkdir -p "$SNAPSHOT_DIR"
    snapshot="$(date +%s).md"
    if [ -f "$MEMORY_FILE" ]; then
        cp "$MEMORY_FILE" "$SNAPSHOT_DIR/$snapshot" 2>/dev/null || snapshot=""
    else
        : > "$SNAPSHOT_DIR/$snapshot" 2>/dev/null || snapshot=""
    fi

    # The write has to be checked, not assumed. This script runs without
    # `set -e`, so a full disk or a permission problem here used to fall
    # straight through to the archive step below — which moves the inbox
    # away. The document would be unchanged and the facts gone: the one
    # combination where nothing on screen says anything went wrong.
    if ! printf '%s\n' "$new_memory" > "${MEMORY_FILE}.tmp" \
       || ! mv "${MEMORY_FILE}.tmp" "$MEMORY_FILE"; then
        rm -f "${MEMORY_FILE}.tmp"
        log "could not write memory.md — inbox left pending, document untouched"
        return 1
    fi
    if ! printf '%s\n' "$new_voice" > "${VOICE_FILE}.tmp" \
       || ! mv "${VOICE_FILE}.tmp" "$VOICE_FILE"; then
        rm -f "${VOICE_FILE}.tmp"
        # memory.md already landed, so this pass DID happen — voice.md is a
        # derived distillate and the next pass rebuilds it.
        log "memory.md updated but voice.md could not be written — it will be rebuilt next pass"
    fi

    record_change "$current_memory" "$new_memory" "snapshots/$snapshot" "consolidation"

    # Archive the processed inbox files; prune old archives.
    mkdir -p "$PROCESSED_DIR"
    local f
    while IFS= read -r f; do
        [ -n "$f" ] || continue
        mv "$f" "$PROCESSED_DIR/$(basename "$f")" 2>/dev/null || rm -f "$f"
    done <<< "$files"
    find "$PROCESSED_DIR" -type f -mtime +"$PROCESSED_PRUNE_DAYS" -delete 2>/dev/null || true

    touch "$MARKER_FILE" 2>/dev/null || true
    log "memory.md (${#new_memory} bytes) and voice.md (${#new_voice} bytes) updated"
    return 0
}

daemon_loop() {
    log "daemon started (check every ${CHECK_INTERVAL}s, daily consolidation, early at >${INBOX_TRIGGER_LINES} pending facts)"
    # Give startup (auth restore, tool install) time to settle.
    sleep 60

    while true; do
        local pending last_run now age
        pending=$(count_pending_lines)
        now=$(date +%s)
        last_run=$(stat -c %Y "$MARKER_FILE" 2>/dev/null || echo 0)
        age=$((now - last_run))

        if [ "$pending" -gt "$INBOX_TRIGGER_LINES" ] || [ "$age" -ge "$DAILY_INTERVAL" ]; then
            with_lock consolidate_once || true
        fi

        sleep "$CHECK_INTERVAL"
    done
}

# One consolidation at a time, whoever asked for it. Three callers can want
# a pass at once — the daemon's 5-minute poll, `brain memory consolidate`,
# and the panel's "File into memory now" — and two of them running together
# means two processes rewriting memory.md and archiving each other's inbox
# files. "Only the consolidator writes memory.md" is the rule; this is what
# makes it mean "only one consolidator".
LOCK_FILE="$MEMORY_DIR/.consolidate.lock"
# Skipped-because-busy is not a failed pass, but it is not a completed one
# either: exiting 0 let the panel's "File into memory now" report facts as
# filed while they sat untouched in the queue. Its own exit code lets the
# caller tell "nothing to do" from "somebody else is doing it".
LOCK_BUSY_RC=75

# How long to wait for a pass that is genuinely in flight, and how often to
# look. Polling, not `flock -w`: see below.
LOCK_WAIT_S="${BRAIN_MEMORY_LOCK_WAIT:-600}"
LOCK_POLL_S="${BRAIN_MEMORY_LOCK_POLL:-2}"

# Can flock in THIS image actually take a lock, with the flags we use?
#
# Asked rather than assumed, and this is the whole lesson of the bug it
# fixes. The add-on runs on Alpine, whose flock is BusyBox's: it accepts
# only -sxnu. `-w SECS` is util-linux's, and BusyBox answers an unknown
# option by printing usage and exiting 1 — the SAME status flock uses for
# "the lock is held". So `flock -w 600 9` never locked anything, always
# failed, and was read as contention. Every consolidation pass reported
# "another consolidation is already running" and did nothing, for weeks,
# while the inbox grew and memory quietly stopped being updated at all.
#
# The probe uses the same flag the real call uses, on a scratch file, so
# "flock works here" means the exact thing we are about to do works here.
flock_usable() {
    command -v flock > /dev/null 2>&1 || return 1
    ( exec 8> "${LOCK_FILE}.probe" && flock -n 8 ) > /dev/null 2>&1
}

with_lock() {
    mkdir -p "$MEMORY_DIR"
    if ! flock_usable; then
        # No usable flock: running is better than refusing, and it is said
        # out loud rather than inferred from a pass that never happens.
        log "no usable flock in this image — running without a lock"
        "$@"
        return $?
    fi
    if ! exec 9> "$LOCK_FILE"; then
        log "could not open the lock file — running without a lock"
        "$@"
        return $?
    fi

    # -n and poll, never -w. Only the portable flag is used, and because the
    # probe above proved -n works, a failure here means one thing: somebody
    # else holds it. That is what makes LOCK_BUSY_RC honest.
    local waited=0
    until flock -n 9; do
        if [ "$waited" -ge "$LOCK_WAIT_S" ]; then
            log "another consolidation is already running — skipping this pass"
            return "$LOCK_BUSY_RC"
        fi
        sleep "$LOCK_POLL_S"
        waited=$((waited + LOCK_POLL_S))
    done
    "$@"
}

case "${1:-}" in
    --once)
        with_lock consolidate_once
        ;;
    --help|-h)
        sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'
        ;;
    *)
        daemon_loop
        ;;
esac
