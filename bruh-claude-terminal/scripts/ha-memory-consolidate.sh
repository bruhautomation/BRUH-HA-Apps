#!/bin/bash

# ha-memory-consolidate — Merge pending memory-inbox facts into memory.md
#
# Two modes:
#   --once      run a single consolidation pass and exit (used by
#               `ha-memory consolidate` and by tests)
#   (default)   daemon loop started by run.sh: consolidates daily, and
#               early whenever the inbox holds more than 20 pending facts
#               (checked every ~5 minutes)
#
# A consolidation pass:
#   1. sweeps external facts from /share/bruh_claude/memory-inbox/ (written
#      by other BRUH add-ons) into the local inbox
#   2. retires questions that sat unanswered for 21+ days
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
# (HOME, auth paths, BRUH_MEMORY_* options) the same way the listeners do.
if [ -r /data/.bruh_claude_env ]; then
    # shellcheck disable=SC1091
    source /data/.bruh_claude_env
fi

MEMORY_DIR="${BRUH_MEMORY_DIR:-/config/.bruh_claude/memory}"
MEMORY_FILE="$MEMORY_DIR/memory.md"
VOICE_FILE="$MEMORY_DIR/voice.md"
INBOX_DIR="$MEMORY_DIR/inbox"
PROCESSED_DIR="$INBOX_DIR/processed"
QUESTIONS_FILE="$MEMORY_DIR/questions.jsonl"
SHARE_INBOX="${BRUH_SHARE_INBOX:-/share/bruh_claude/memory-inbox}"
MARKER_FILE="$MEMORY_DIR/.last_consolidated"

MEMORY_MAX_KB="${BRUH_MEMORY_MAX_KB:-8}"
VOICE_MAX_BYTES=2048
CLAUDE_MODEL="${BRUH_MEMORY_MODEL:-haiku}"
CLAUDE_TIMEOUT="${BRUH_MEMORY_CLAUDE_TIMEOUT:-120}"

CHECK_INTERVAL="${BRUH_MEMORY_CHECK_INTERVAL:-300}"     # daemon poll (s)
DAILY_INTERVAL=86400                                     # forced cadence (s)
INBOX_TRIGGER_LINES=20                                   # early-run threshold
QUESTION_RETIRE_DAYS=21
PROCESSED_PRUNE_DAYS=30

VOICE_SEPARATOR="-----VOICE-----"

log() {
    echo "[ha-memory-consolidate] $*"
}

resolve_claude() {
    if [ -n "${BRUH_CLAUDE_BIN:-}" ]; then
        echo "$BRUH_CLAUDE_BIN"
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

# Questions that surfaced but got no answer within QUESTION_RETIRE_DAYS get
# an auto answer record so they stop showing as open forever.
retire_stale_questions() {
    [ -s "$QUESTIONS_FILE" ] || return 0
    local now cutoff retired
    now=$(date +%s)
    cutoff=$((now - QUESTION_RETIRE_DAYS * 86400))
    retired=$(jq -cs --argjson cutoff "$cutoff" --argjson now "$now" '
        (map(select(has("a")) | .q)) as $answered
        | map(select(has("q") and (has("a") | not))
              | select((.ts // 0) < $cutoff)
              | select(.q as $q | $answered | index($q) | not))
        | .[] | {"q": .q, "a": "(retired unanswered)", "source": "auto", "ts": $now}
    ' "$QUESTIONS_FILE" 2>/dev/null) || return 0
    if [ -n "$retired" ]; then
        printf '%s\n' "$retired" >> "$QUESTIONS_FILE"
        log "retired $(printf '%s\n' "$retired" | wc -l) unanswered question(s)"
    fi
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
    cat << PROMPT
You maintain a small long-term memory file about one household for a smart-home assistant.

CURRENT memory.md:
<<<MEMORY
${current_memory}
MEMORY

NEW candidate facts (JSONL, one per line; each has ts/source/fact/confidence; newest last):
<<<FACTS
${inbox_lines}
FACTS

Output the FULL updated memory.md: merge the new facts into the existing sections (## Preferences, ## Entity nicknames, ## Household patterns, ## Device notes), dedupe, resolve contradictions with newest-wins, and keep the file under ${MEMORY_MAX_KB} KB by dropping the lowest-value and oldest facts first. NEVER include secrets, credentials, transient device states, or one-off commands. Keep the header comment lines.

Then print exactly this separator on its own line:
${VOICE_SEPARATOR}

Then print a voice.md distillate (2 KB maximum): ONLY entity nicknames, the top preferences, and device caveats — what a voice assistant needs on every request. Short markdown bullets.

Output ONLY the two files and the separator — no commentary, no code fences.
PROMPT
}

consolidate_once() {
    mkdir -p "$MEMORY_DIR" "$INBOX_DIR"

    sweep_share_inbox
    retire_stale_questions

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

    # shellcheck disable=SC2086
    if ! output=$(printf '%s' "$prompt" | timeout "$CLAUDE_TIMEOUT" \
            $claude_cmd -p --disallowedTools "*" --max-turns 1 \
            --model "$CLAUDE_MODEL" 2>/dev/null); then
        log "Claude invocation failed (not authenticated?) — inbox left pending"
        return 1
    fi

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
    if [ "${#new_memory}" -gt $((MEMORY_MAX_KB * 1024)) ]; then
        log "updated memory.md exceeds ${MEMORY_MAX_KB} KB — inbox left pending"
        return 1
    fi
    if [ "${#new_voice}" -gt "$VOICE_MAX_BYTES" ]; then
        log "voice.md distillate exceeds ${VOICE_MAX_BYTES} bytes — inbox left pending"
        return 1
    fi

    printf '%s\n' "$new_memory" > "${MEMORY_FILE}.tmp"
    mv "${MEMORY_FILE}.tmp" "$MEMORY_FILE"
    printf '%s\n' "$new_voice" > "${VOICE_FILE}.tmp"
    mv "${VOICE_FILE}.tmp" "$VOICE_FILE"

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
            consolidate_once || true
        fi

        sleep "$CHECK_INTERVAL"
    done
}

case "${1:-}" in
    --once)
        consolidate_once
        ;;
    --help|-h)
        sed -n '3,22p' "$0" | sed 's/^# \{0,1\}//'
        ;;
    *)
        daemon_loop
        ;;
esac
