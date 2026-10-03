#!/usr/bin/with-contenv bashio

# Automation Integration Listener
# Allows Home Assistant automations to trigger Claude Code tasks
#
# Communication with the HA custom integration uses a shared file directory:
#   /config/.brain/tasks/        - incoming task requests (JSON)
#   /config/.brain/task_results/ - outgoing task results (JSON)
#
# Request format:  {"id": "<uuid>", "prompt": "...", "notify": true,
#                   "notify_entity": "notify.mobile_app", "ts": <epoch>,
#                   "timeout": <secs>}  (+ optional model, tools, schema,
#                   memory, scheduled)
# Response format: {"id": "<uuid>", "result": "claude output",
#                   "status": "completed" | "failed", "error": "<code>"}
#
# `status` is the half of the result that says whether `result` is an
# ANSWER. Until it could say "failed", every task was "completed" — an
# expired login, a timeout and a run that produced nothing included — and
# the sentence about the failure was handed back as if Claude had said it.
# `error` is a closed word beside a failure (refused, paused, budget, auth,
# timeout, permission, max_turns, empty, error), and the text is still the
# sentence a person reads; BRight's director already raised on any status
# but "completed", and the integration's bridge raises on it now too.
#
# The integration sends the window it will wait ("timeout") with each task;
# the listener keeps the claude process comfortably inside that window so a
# result is always written before the bridge stops polling.
#
# Permissions:
#   This listener does NOT use --dangerously-skip-permissions. Instead, tool
#   permissions are granted via /config/.claude/settings.local.json, which
#   pre-approves all MCP, Bash, Read, Write, and Edit tools. This avoids the
#   root-user restrictions of the flag while still allowing non-interactive use.

set -e

# Source the Claude environment written by run.sh — FIRST, before anything
# below copies a BRAIN_* option into a local name. The `with-contenv` shebang
# reloads the s6 container environment and drops the exports run.sh made, so
# this file is the only route an add-on option has into a listener.
#
# Order is load-bearing. A `${BRAIN_x:-default}` that runs before the source
# freezes the fallback: the value arrives afterwards under its own name, but
# the local alias already holds the default and nothing reads it again. That
# is not a variable that is missing, it is a variable that is late — which is
# why it went unnoticed for so long. `automation_max_turns` was pinned to 10
# for everyone, whatever the option said, and the only visible trace was the
# `MaxTurns:` line in the task log.
if [ -r /data/.brain_env ]; then
    # shellcheck disable=SC1091
    source /data/.brain_env
fi

# Which door a Claude run came through, for the MCP server every task
# launches (it inherits this environment): a task is not a voice turn and
# not a person at the terminal, and the server's per-channel rules key on
# the word. Exported here, once, so every invocation below carries it —
# the run, its landing and its post-cleanup retry are one task.
export BRAIN_CHANNEL=task

SUPERVISOR_TOKEN="${SUPERVISOR_TOKEN:-}"
SHARED_DIR="/config/.brain"
TASKS_DIR="$SHARED_DIR/tasks"
RESULTS_DIR="$SHARED_DIR/task_results"
LOG_DIR="$SHARED_DIR/logs"

# The runaway guard on one task — not a budget, and not an add-on option:
# the task's own timeout is what bounds it, and a multi-step config edit
# truncated mid-way leaves the house half-changed, which is worse than a
# slow one. BRAIN_AUTOMATION_MAX_TURNS is an override for somebody who sets
# it by hand. A run that trips it is landed (brain-landing.sh) rather than
# reported as a failure.
MAX_TURNS="${BRAIN_AUTOMATION_MAX_TURNS:-200}"

# Default process-level timeout for claude -p commands (seconds), used when a
# task doesn't carry its own timeout. The integration's task default (300s)
# matches this; per-task timeouts in the payload always take precedence.
CLAUDE_TIMEOUT="${BRAIN_AUTOMATION_TIMEOUT:-300}"

# Subtracted from a task's bridge timeout to get the claude process limit,
# leaving room to write the result file before the bridge gives up.
TIMEOUT_MARGIN=15

mkdir -p "$TASKS_DIR" "$RESULTS_DIR" "$LOG_DIR"

# Lets a task's transcript be labelled "Automation" in the Chats rail
# instead of sitting there looking like something you typed. Optional: an
# image without it just leaves tasks unlabelled.
if [ -r /opt/scripts/brain-run-source.sh ]; then
    # shellcheck disable=SC1091
    source /opt/scripts/brain-run-source.sh
fi
# A task that ends on the turn cap is landed on its own session rather than
# answered with an error (see the library for why). Optional, like the
# ledger above: without it a tripped cap is what it was before.
if [ -r /opt/scripts/brain-landing.sh ]; then
    # shellcheck disable=SC1091
    source /opt/scripts/brain-landing.sh
fi

# Resolve the claude binary (see assist-listener.sh for details).
CLAUDE_BIN="claude-run"
if [ ! -x /usr/local/bin/claude-run ]; then
    if [ "$(id -u)" = "0" ] && command -v su-exec >/dev/null 2>&1; then
        CLAUDE_BIN="su-exec claude /root/.local/bin/claude"
    fi
fi

bashio::log.info "Automation listener starting (UID=$(id -u), claude=$CLAUDE_BIN, max_turns=$MAX_TURNS, default_timeout=${CLAUDE_TIMEOUT}s)..."
bashio::log.info "Watching $TASKS_DIR for automation tasks"
bashio::log.info "Debug logs: $LOG_DIR/automation-*.log"

# ---------------------------------------------------------------------------
# MCP config verification
# ---------------------------------------------------------------------------

# Fast check used on the hot path before each Claude invocation: only the
# canonical project config, a single grep on a tiny file.
verify_mcp_config_fast() {
    local mcp_file="/config/.mcp.json"

    if [ ! -f "$mcp_file" ]; then
        bashio::log.warning "MCP config missing: $mcp_file — Claude may lack HA tools"
        return
    fi

    if grep -q "/api/mcp\|homeassistant-config" "$mcp_file" 2>/dev/null; then
        bashio::log.warning "Stale MCP entry found in $mcp_file — rewriting clean config"
        cat > "$mcp_file" << 'MCP_CLEAN'
{
  "mcpServers": {
    "home-assistant": {
      "command": "python3",
      "args": ["/opt/ha-mcp-server/ha_mcp_server.py"]
    }
  }
}
MCP_CLEAN
        chown claude:claude "$mcp_file" 2>/dev/null || true
        chmod 644 "$mcp_file"
        bashio::log.info "MCP config restored to clean state"
    fi
}

# Deep cleanup of every config a broken marketplace plugin can poison.
# Runs at startup and after an /api/mcp error is detected — NOT per task
# (the find over ~/.claude/projects grows with session count).
verify_mcp_config_full() {
    verify_mcp_config_fast

    # Check ~/.claude.json — the most common hiding spot for stale /api/mcp
    # entries added by marketplace plugins.
    local claude_json="/data/home/.claude.json"
    if [ -f "$claude_json" ] && grep -q "/api/mcp\|homeassistant-config\|claude-homeassistant-plugins" "$claude_json" 2>/dev/null; then
        bashio::log.warning "Stale MCP entry in ~/.claude.json — cleaning"
        local tmp
        tmp=$(mktemp)
        if jq '
            if .mcpServers then
                .mcpServers |= with_entries(
                    select(
                        .key != "homeassistant-config" and
                        ((.value | tostring) | contains("/api/mcp") | not) and
                        ((.value | tostring) | contains("claude-homeassistant-plugins") | not)
                    )
                )
            else . end
        ' "$claude_json" > "$tmp" 2>/dev/null; then
            mv "$tmp" "$claude_json"
            chown claude:claude "$claude_json" 2>/dev/null || true
            bashio::log.info "~/.claude.json cleaned"
        else
            rm -f "$tmp"
        fi
    fi

    # Also check Claude Code's project-level configs for /api/mcp entries
    local claude_projects="/data/home/.claude/projects"
    if [ -d "$claude_projects" ]; then
        find "$claude_projects" -name "*.json" -type f -print0 2>/dev/null | \
        while IFS= read -r -d '' f; do
            if grep -q "/api/mcp" "$f" 2>/dev/null; then
                bashio::log.warning "Stale /api/mcp in project config: $f — cleaning"
                local tmp
                tmp=$(mktemp)
                if jq '
                    if .mcpServers then
                        .mcpServers |= with_entries(
                            select((.value | tostring) | contains("/api/mcp") | not)
                        )
                    else . end
                ' "$f" > "$tmp" 2>/dev/null; then
                    mv "$tmp" "$f"
                    chown claude:claude "$f" 2>/dev/null || true
                else
                    rm -f "$tmp"
                fi
            fi
        done
    fi
}

# Orphaned results accumulate when nothing consumes them — sweep periodically.
cleanup_stale_files() {
    find "$RESULTS_DIR" -name '*.json' -mmin +120 -delete 2>/dev/null || true
    find "$RESULTS_DIR" -name '*.tmp' -mmin +120 -delete 2>/dev/null || true
    find "$TASKS_DIR" -name '*.work.*' -mmin +120 -delete 2>/dev/null || true
    # Debug logs hold full task prompts: age them out (default 7 days,
    # BRAIN_LOG_RETENTION_DAYS overrides) and keep them owner-only — they
    # live under /config and would otherwise ride into every HA full backup.
    local retention_days="${BRAIN_LOG_RETENTION_DAYS:-7}"
    find "$LOG_DIR" -name '*.log' -mtime "+${retention_days}" -delete 2>/dev/null || true
    chmod 700 "$LOG_DIR" 2>/dev/null || true
    chmod 600 "$LOG_DIR"/*.log 2>/dev/null || true
}

# Extract the assistant's final text from a `claude -p --output-format json`
# result file. That mode emits a single JSON object whose .result field holds
# the final text. Falls back to the raw file for any non-JSON output (older
# CLI, hard errors) so genuine error text still surfaces.
#
# This replaces scraping the CLI's `--verbose` text stdout wholesale: newer
# Claude Code builds pad that stream with diagnostics — including "MCP server
# ... unavailable" connection notices — which leaked into automation results.
extract_claude_result() {
    local out_file="$1" text
    text=$(jq -r 'if (type == "object" and (.result | type) == "string" and (.result | length) > 0) then .result else empty end' "$out_file" 2>/dev/null)
    if [ -n "$text" ]; then
        printf '%s' "$text"
    else
        cat "$out_file" 2>/dev/null || true
    fi
}

# The same result object carries the session id, which is the id of the
# transcript Claude Code has just written into /config. Claiming it is what
# lets the Chats rail say "Automation" beside it instead of listing an
# automation's task among the conversations you had.
#
# Claimed after the run rather than before because this path never had to
# name its own session — --output-format json hands it back for free, and
# a flag we don't need is a flag that can be unsupported.
claim_task_session() {
    local out_file="$1" sid
    command -v brain_claim_session > /dev/null 2>&1 || return 0
    sid=$(jq -r 'if type == "object" then (.session_id // empty) else empty end' \
        "$out_file" 2>/dev/null | tr -cd 'A-Za-z0-9._-')
    [ -n "$sid" ] && brain_claim_session "$sid" automation
    return 0
}

# ---------------------------------------------------------------------------
# Per-task tool scoping
# ---------------------------------------------------------------------------

# `tools` in the task JSON, translated into claude argv.
#
# The default is `full` and it is today's behaviour exactly: no tool flags
# at all, so the run inherits the project grant in
# /config/.claude/settings.local.json — Bash, Write, Edit, WebFetch,
# WebSearch and every MCP tool. That grant is what BRight's director drives
# this same folder with, so the default may not narrow.
#
# `house` and `read_only` are the two narrower answers, and BOTH are
# derived from engine.py's own lists rather than typed here. Two answers to
# "what may an unattended run touch" is the drift that lets an acting tool
# reach one of them — brain-learn.sh reads the same lists for the same
# reason, and this is a second READER rather than a second copy.
#
#   read_only  the analyst's pair, verbatim: reads only, and every acting
#              tool named in the deny list rather than merely left out,
#              because an un-listed tool FAILS where a denied one is
#              refused, and those are not the same guarantee.
#   house      every MCP tool the server registers — each is in exactly one
#              of the two lists, which is what makes the union complete —
#              denying the non-MCP half of the analyst's deny list: Bash,
#              Write, Edit, NotebookEdit, WebFetch, WebSearch.
#
# A scoping that cannot be read REFUSES the run rather than widening it: a
# task asked for read-only that runs with Bash is worse than a task that
# does not run at all, and the caller is told which.
task_tool_flags() {
    local mode="$1"

    case "$mode" in
        ''|full) return 0 ;;
        house|read_only) ;;
        *) return 1 ;;
    esac

    local panel_dir lists allow deny
    panel_dir="${BRAIN_PANEL_DIR:-/opt/panel}"
    if ! lists=$(BRAIN_PANEL_DIR="$panel_dir" python3 - <<'PYTOOLS' 2>/dev/null
import os
import sys
sys.path.insert(0, os.environ.get("BRAIN_PANEL_DIR", "/opt/panel"))
try:
    import engine
except Exception:
    raise SystemExit(1)
allow, deny = list(engine.ANALYST_TOOLS), list(engine.ANALYST_DENIED)
if not allow or not deny:
    raise SystemExit(1)
seen, house_allow = set(), []
for tool in allow + deny:
    if tool.startswith("mcp__") and tool not in seen:
        seen.add(tool)
        house_allow.append(tool)
house_deny = [t for t in deny if not t.startswith("mcp__")]
if not house_allow or not house_deny:
    raise SystemExit(1)
print(",".join(allow))
print(",".join(deny))
print(",".join(house_allow))
print(",".join(house_deny))
PYTOOLS
    ); then
        return 1
    fi

    if [ "$mode" = "read_only" ]; then
        allow=$(printf '%s' "$lists" | sed -n '1p')
        deny=$(printf '%s' "$lists" | sed -n '2p')
    else
        allow=$(printf '%s' "$lists" | sed -n '3p')
        deny=$(printf '%s' "$lists" | sed -n '4p')
    fi
    [ -n "$allow" ] && [ -n "$deny" ] || return 1

    printf '%s\n%s\n%s\n%s\n' \
        "--allowedTools" "$allow" "--disallowedTools" "$deny"
}

# The one place a task's answer is written. A refusal owes the bridge a
# result file exactly as a finished run does — a task dropped in silence is
# a service call that times out with nothing to read.
#
# Args: id, text, [data], [error code]. An error code makes the status
# `failed`; without one it is `completed`, and the file is byte-for-byte
# what a completed task always wrote, so a reader that predates the field
# reads every answer exactly as before.
write_task_result() {
    local task_id="$1" text="$2" data="${3:-}" error="${4:-}"
    local result_file="$RESULTS_DIR/${task_id}.json"
    local tmp_file="${result_file}.tmp"
    if [ -n "$error" ]; then
        # A failure carries no data: the validated object is an answer's,
        # and a failed run has none however it ended.
        jq -n --arg id "$task_id" --arg result "$text" --arg status "failed" \
            --arg error "$error" \
            '{"id": $id, "result": $result, "status": $status, "error": $error}' > "$tmp_file"
    elif [ -n "$data" ]; then
        # `data` is the object the CLI validated against the task's schema,
        # as compact JSON. Written beside the text and never instead of it:
        # the bridge reads `.result` as it always has, and `.data` is what
        # `brain.ask` hands back as structured output.
        jq -n --arg id "$task_id" --arg result "$text" --arg status "completed" \
            --argjson data "$data" \
            '{"id": $id, "result": $result, "status": $status, "data": $data}' > "$tmp_file"
    else
        jq -n --arg id "$task_id" --arg result "$text" --arg status "completed" \
            '{"id": $id, "result": $result, "status": $status}' > "$tmp_file"
    fi
    mv "$tmp_file" "$result_file"
}

# What a person does about a credential that will not work. The panel's
# button and never `/login` in a terminal: `enable_terminal` can remove the
# Terminal tab, and its default face is a chat with no shell in it, so a
# remedy that names a shell command is one somebody may have no way to do.
AUTH_REMEDY="Open brAIn from the sidebar and press ⚙ → Claude account → Sign in again — background tasks and insights pick up the fresh sign-in automatically."

# Whether a run nobody pressed may happen now, by the panel's own two
# switches: the pause (`auto_enabled`) and the usage budget. Prints nothing
# and succeeds when it may; prints `<code>` then a sentence and fails when
# it may not. `scheduled` on a task is the integration saying nobody
# pressed anything — an insight job's timer — and every other unattended
# Claude run in the add-on answers to these same two gates.
#
# Read off the panel's own modules rather than a copy of their rules, for
# `task_tool_flags`' reason. A panel that cannot be read lets the run go:
# the gate is a budget, not a safety scope, and "I could not read the
# settings" must not silently stop every scheduled report a house has.
task_gate() {
    local panel_dir="${BRAIN_PANEL_DIR:-/opt/panel}"
    BRAIN_PANEL_DIR="$panel_dir" python3 - <<'PYGATE' 2>/dev/null || true
import os
import sys
sys.path.insert(0, os.environ.get("BRAIN_PANEL_DIR", "/opt/panel"))
try:
    import settings_store
    import usage_store
    settings = settings_store.load()
except Exception:
    raise SystemExit(0)
if not settings.get("auto_enabled", True):
    print("paused")
    print("brAIn's automatic runs are paused (⚙ → Insights → Automatic "
          "insights in the panel), so this scheduled run was skipped. Running "
          "it by hand (brain.run_insight) always runs.")
    raise SystemExit(0)
try:
    budget = usage_store.budget_state(settings)
except Exception:
    raise SystemExit(0)
if budget.get("blocked"):
    print("budget")
    print("The session's usage ({:.0f}%) has reached the budget brAIn keeps "
          "for automatic runs ({}%), so this scheduled run was skipped until "
          "the window resets. Running it by hand (brain.run_insight) always "
          "runs.".format(float(budget.get("used_percent") or 0),
                         budget.get("budget_percent")))
PYGATE
}

# What brAIn knows about the house, for a task that asked for it (`memory`
# on the task: an insight job). The panel's own retrieval — the core facts,
# the facts about any entity the prompt names, the head of memory.md, and
# the whole document where there are no facts yet — through the function
# every card's bundle uses, rather than the first 2 KB of memory.md cut
# mid-fact by the integration. Empty when the panel cannot be read: memory
# is context and not a gate, so a run without it is the run there was
# before this existed. Arg: a file holding the prompt (a heredoc is stdin).
task_memory_block() {
    local prompt_file="$1"
    local panel_dir="${BRAIN_PANEL_DIR:-/opt/panel}"
    BRAIN_PANEL_DIR="$panel_dir" python3 - "$prompt_file" <<'PYMEM' 2>/dev/null || true
import os
import re
import sys
sys.path.insert(0, os.environ.get("BRAIN_PANEL_DIR", "/opt/panel"))
try:
    import ha_data
    with open(sys.argv[1], encoding="utf-8", errors="replace") as fh:
        text = fh.read()
except Exception:
    raise SystemExit(0)
ids = sorted({m for m in re.findall(r"\b[a-z_]+\.[a-z0-9_]+\b", text)
              if ha_data.ENTITY_ID_RE.match(m)})[:50]
try:
    block = ha_data._memory_for(entities=ids)
except Exception:
    raise SystemExit(0)
if block and block.strip():
    # The heading the integration's own byte-cut used, so a prompt that
    # was written against it reads the same.
    print("Known about this home:\n" + block.strip())
PYMEM
}

# One journal row for a task, through the panel's own journal (and the
# usage nudge, when a model ran) — brain_run_journal.py says why that is
# one module and not a copy. In the background and after the result is
# written: accounting may cost the run nothing, least of all time the
# bridge is waiting on. Args: outcome, duration, envelope file (or ""),
# model, error text, scheduled flag.
journal_task() {
    local outcome="$1" duration="$2" envelope="$3" model="$4" error="$5" scheduled="$6"
    local journal_py="${BRAIN_SCRIPTS_DIR:-/opt/scripts}/brain_run_journal.py"
    [ -r "$journal_py" ] || { [ -n "$envelope" ] && rm -f "$envelope"; return 0; }
    local extra=()
    [ "$scheduled" = "true" ] && extra=(--extra scheduled=1)
    (
        python3 "$journal_py" record task "$outcome" --duration "$duration" \
            ${envelope:+--envelope "$envelope"} --model "$model" \
            --error "$error" "${extra[@]}" > /dev/null 2>&1 || true
        [ -n "$envelope" ] && rm -f "$envelope"
    ) &
}

# The validated object out of a `--json-schema` run's envelope, compact,
# or nothing: a reply that did not validate carries none, and so does a
# CLI too old for the flag. Read off the same envelope the text is.
extract_claude_data() {
    local out_file="$1"
    jq -c 'if (type == "object" and (.structured_output | type) == "object") then .structured_output else empty end' "$out_file" 2>/dev/null || true
}

# Process an automation task file
process_task() {
    local task_file="$1"

    # Claim the task atomically so the startup-backlog scan, inotify events,
    # and the polling fallback can never double-process one file.
    local work_file="${task_file%.json}.work.${BASHPID:-$$}"
    mv "$task_file" "$work_file" 2>/dev/null || return 0

    local task_id prompt notify notify_entity task_ts task_timeout task_model
    local task_tools task_schema task_memory task_scheduled

    task_id=$(jq -r '.id // empty' "$work_file" 2>/dev/null)
    prompt=$(jq -r '.prompt // empty' "$work_file" 2>/dev/null)
    notify=$(jq -r '.notify // false' "$work_file" 2>/dev/null)
    notify_entity=$(jq -r '.notify_entity // empty' "$work_file" 2>/dev/null)
    task_ts=$(jq -r '.ts // empty' "$work_file" 2>/dev/null)
    task_timeout=$(jq -r '.timeout // empty' "$work_file" 2>/dev/null)
    task_model=$(jq -r '.model // empty' "$work_file" 2>/dev/null)
    task_tools=$(jq -r '.tools // empty' "$work_file" 2>/dev/null)
    # A JSON Schema the answer must fit (`brain.ask`). Compact so it rides
    # one argv entry; empty when the task carries none, and then no flag
    # is passed — a flag the CLI may not know is only ever asked for.
    task_schema=$(jq -c 'if (.schema | type) == "object" then .schema else empty end' "$work_file" 2>/dev/null)
    # Two flags an insight job sets (see task_gate / task_memory_block);
    # read as the literal `true` and nothing else, so a task that does not
    # carry them — BRight's, every older one — runs exactly as before.
    task_memory=$(jq -r 'if .memory == true then "true" else "" end' "$work_file" 2>/dev/null)
    task_scheduled=$(jq -r 'if .scheduled == true then "true" else "" end' "$work_file" 2>/dev/null)

    # A task that names no model takes the plan's tier for a task
    # (`BRAIN_MODEL_TASK`, off panel/model_plan.py via /data/.brain_env);
    # "default" is the request saying the same thing in a word.
    if [ -z "$task_model" ] || [ "$task_model" = "default" ]; then
        task_model="${BRAIN_MODEL_TASK:-}"
    fi
    local model_flag=""
    if [ -n "$task_model" ]; then
        model_flag="--model $task_model"
    fi

    if [ -z "$task_id" ] || [ -z "$prompt" ]; then
        bashio::log.warning "Invalid task file: $task_file"
        rm -f "$work_file"
        return
    fi

    # Bridge wait window for this task (drives staleness + process limit)
    local has_task_timeout=1
    case "$task_timeout" in
        ''|*[!0-9]*) task_timeout="$CLAUDE_TIMEOUT"; has_task_timeout=0 ;;
    esac
    case "$task_ts" in
        *[!0-9.]*) task_ts="" ;;
    esac

    # Discard tasks nobody is waiting for anymore (add-on was stopped,
    # bridge already timed out).
    local now age
    now=$(date +%s)
    if [ -n "$task_ts" ]; then
        age=$((now - ${task_ts%.*}))
    else
        age=$((now - $(stat -c %Y "$work_file" 2>/dev/null || echo "$now")))
    fi
    if [ "$age" -gt $((task_timeout + 30)) ] 2>/dev/null; then
        bashio::log.warning "Discarding stale task [$task_id] (${age}s old > ${task_timeout}s window)"
        rm -f "$work_file"
        return
    fi

    bashio::log.info "Processing task [$task_id]: ${prompt:0:80}..."
    rm -f "$work_file"

    # Resolved before anything is spent on the task, and a refusal is an
    # answer rather than a silence: the bridge is already polling for a
    # result file and would otherwise wait out its whole window.
    local tool_flags=() tool_flags_out schema_flags=()
    if [ -n "$task_schema" ]; then
        schema_flags=(--json-schema "$task_schema")
    fi
    if ! tool_flags_out=$(task_tool_flags "$task_tools"); then
        bashio::log.error "Task [$task_id] asked for tools='${task_tools}' and it could not be honoured"
        write_task_result "$task_id" "brAIn refused this task: tools='${task_tools}' is not one of full, house or read_only, or the analyst's tool lists could not be read from the panel. A task that cannot be scoped is not run with the full grant." "" refused
        journal_task error 0 "" "${task_model:-}" "tools scope could not be honoured" "$task_scheduled"
        return
    fi
    if [ -n "$tool_flags_out" ]; then
        mapfile -t tool_flags <<< "$tool_flags_out"
    fi

    # A scheduled run answers to the panel's pause and budget before it
    # spends anything. A skip is a failure to the caller — the insight
    # sensor shows the sentence rather than a report — and is NOT a fault:
    # nothing ran, so nothing is journaled, which is a refusal doing its job.
    if [ "$task_scheduled" = "true" ]; then
        local gate_out gate_code
        gate_out=$(task_gate)
        if [ -n "$gate_out" ]; then
            gate_code=$(printf '%s\n' "$gate_out" | sed -n '1p')
            bashio::log.info "Scheduled task [$task_id] skipped: ${gate_code}"
            write_task_result "$task_id" "$(printf '%s\n' "$gate_out" | sed -n '2,$p')" "" "$gate_code"
            return
        fi
    fi

    # What brAIn knows, in front of the prompt, for a task that asked.
    if [ "$task_memory" = "true" ]; then
        local prompt_file memory_block
        prompt_file=$(mktemp)
        printf '%s' "$prompt" > "$prompt_file"
        memory_block=$(task_memory_block "$prompt_file")
        rm -f "$prompt_file"
        if [ -n "$memory_block" ]; then
            prompt="${memory_block}

${prompt}"
        fi
    fi

    cleanup_stale_files

    # Cheap canonical-config check only — the deep cleanup runs at startup
    # and after detected /api/mcp errors.
    verify_mcp_config_fast

    # Claude process limit: stay inside the bridge's polling window so the
    # result file always lands before the integration gives up. Tasks without
    # a timeout (older integration) keep the configured default.
    local claude_limit
    if [ "$has_task_timeout" = "1" ]; then
        claude_limit=$((task_timeout - TIMEOUT_MARGIN))
        [ "$claude_limit" -lt 30 ] && claude_limit=30
    else
        claude_limit="$CLAUDE_TIMEOUT"
    fi

    # Log request for debugging
    local log_file="$LOG_DIR/automation-$(date +%Y%m%d).log"
    {
        echo "================================================================"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] TASK REQUEST $task_id"
        echo "  Channel:  automation"
        echo "  Prompt:   ${prompt:0:500}"
        echo "  Chars:    ${#prompt}"
        echo "  Notify:   $notify"
        echo "  Timeout:  ${claude_limit}s (bridge window ${task_timeout}s)"
        echo "  MaxTurns: $MAX_TURNS"
        echo "  Tools:    ${task_tools:-full}"
    } >> "$log_file"

    local output_file stderr_file
    output_file=$(mktemp)
    stderr_file=$(mktemp)

    # Run Claude in print mode from /config so it finds .mcp.json for HA tools
    # and .claude/settings.local.json for pre-approved tool permissions.
    # --max-turns prevents runaway agentic loops.
    # No --dangerously-skip-permissions: permissions come from settings.local.json.
    local start_time
    start_time=$(date +%s)

    # --output-format json: capture the structured result and pull .result,
    # instead of scraping verbose stdout (which now carries MCP/diagnostic
    # lines). See extract_claude_result().
    # shellcheck disable=SC2086
    (cd /config && printf '%s' "$prompt" | timeout "$claude_limit" ${CLAUDE_BIN} -p --output-format json --max-turns "$MAX_TURNS" ${model_flag} "${tool_flags[@]}" "${schema_flags[@]}" > "$output_file" 2>"$stderr_file") || true

    # A task that ended on the turn cap is landed, not failed: resumed on
    # the session the envelope names, with two turns and a prompt to answer
    # with what it has. The landing's envelope replaces the run's.
    if command -v brain_hit_turn_cap > /dev/null 2>&1 \
        && brain_hit_turn_cap "$(cat "$output_file" 2>/dev/null)" "$stderr_file"; then
        local land_sid land_left
        land_sid=$(brain_session_from_output "$(cat "$output_file" 2>/dev/null)")
        land_left=$(( claude_limit - ( $(date +%s) - start_time ) ))
        bashio::log.info "Task [$task_id] ran out of room — landing it (${land_left}s left)"
        # Into a scratch file, moved over only on success: a landing refused
        # for want of time or a session must not take the run's own
        # envelope (and the session id it names) with it.
        # shellcheck disable=SC2086
        if (cd /config && brain_land "$land_sid" "$land_left" "$stderr_file" -- \
            ${CLAUDE_BIN} -p --output-format json ${model_flag} "${tool_flags[@]}" "${schema_flags[@]}" > "${output_file}.land"); then
            mv -f "${output_file}.land" "$output_file"
        else
            rm -f "${output_file}.land"
        fi
    fi

    local end_time duration
    end_time=$(date +%s)
    duration=$((end_time - start_time))

    local result stderr_output task_data
    result=$(extract_claude_result "$output_file")
    task_data=$(extract_claude_data "$output_file")
    claim_task_session "$output_file"
    stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
    # The envelope is kept until the journal has read it (journal_task
    # removes it); everything else goes now.
    local envelope_file="${output_file}.envelope"
    mv -f "$output_file" "$envelope_file" 2>/dev/null || envelope_file=""
    rm -f "$stderr_file"

    # Check for /api/mcp auth errors in stderr — deep-clean configs and retry
    # within the remaining time budget.
    if echo "$stderr_output" | grep -qi "/api/mcp\|invalid authentication.*mcp"; then
        bashio::log.error "Detected /api/mcp auth error in task [$task_id] — cleaning and retrying"
        verify_mcp_config_full

        local remaining=$((claude_limit - duration))
        if [ "$remaining" -ge 30 ]; then
            output_file=$(mktemp)
            stderr_file=$(mktemp)

            # shellcheck disable=SC2086
            (cd /config && printf '%s' "$prompt" | timeout "$remaining" ${CLAUDE_BIN} -p --output-format json --max-turns "$MAX_TURNS" ${model_flag} "${tool_flags[@]}" "${schema_flags[@]}" > "$output_file" 2>"$stderr_file") || true

            end_time=$(date +%s)
            duration=$((end_time - start_time))

            result=$(extract_claude_result "$output_file")
            task_data=$(extract_claude_data "$output_file")
            claim_task_session "$output_file"
            stderr_output=$(cat "$stderr_file" 2>/dev/null || echo "")
            # The retry's envelope is the one that answers the task.
            [ -n "$envelope_file" ] && rm -f "$envelope_file"
            envelope_file="${output_file}.envelope"
            mv -f "$output_file" "$envelope_file" 2>/dev/null || envelope_file=""
            rm -f "$stderr_file"
            bashio::log.info "Retried task [$task_id] after /api/mcp cleanup"
        else
            bashio::log.warning "No time budget left to retry task [$task_id] (${remaining}s remaining)"
        fi
    fi

    # Whether this run FAILED, as a closed word, decided here once and
    # carried to the result file, the event and the journal alike. Empty
    # means it answered.
    local fail_code=""

    # The CLI's own verdict on its envelope, read before any words are:
    # an `is_error` result is a failure whatever its text says ("API Error:
    # 529 Overloaded" is not an answer), and a turn cap that the landing
    # could not rescue is that and not a mystery.
    if [ -n "$envelope_file" ] && [ -n "$result" ]; then
        local env_error env_subtype
        env_error=$(jq -r 'if type == "object" then (.is_error // false) else false end' "$envelope_file" 2>/dev/null)
        env_subtype=$(jq -r 'if type == "object" then (.subtype // "") else "" end' "$envelope_file" 2>/dev/null)
        if [ "$env_error" = "true" ]; then
            fail_code="error"
            [ "$env_subtype" = "error_max_turns" ] && fail_code="max_turns"
            # An error envelope with no text of its own reaches here as the
            # raw JSON (extract_claude_result's fallback), which is nobody's
            # sentence — say what happened instead.
            if [ -z "$(jq -r 'if type == "object" then (.result // "") else "" end' "$envelope_file" 2>/dev/null)" ]; then
                if [ "$fail_code" = "max_turns" ]; then
                    result="The task ran out of room before it could answer: it reached its turn limit and could not be wrapped up in the time left. Ask for less in one go, or give it a longer timeout."
                else
                    result="Claude's run ended with an error (${env_subtype:-unknown}) and no answer. Check the brAIn add-on logs."
                fi
            fi
        fi
    fi

    # Auth failures come back as the result text in -p mode ("Failed to
    # authenticate: OAuth session expired and could not be refreshed").
    # Replace the raw CLI error with something the user can act on — the
    # panel's own sign-in, which every background channel picks up
    # automatically on its next spawn.
    if printf '%s' "$result" | grep -qiE "OAuth session expired|OAuth token (refresh failed|revoked)|failed to authenticate|please run /login|invalid api key"; then
        bashio::log.error "Claude auth failure in task [$task_id]: ${result:0:200}"
        result="Claude's saved login has expired and could not be refreshed automatically. ${AUTH_REMEDY}"
        fail_code="auth"
    fi

    # If result is empty, something went wrong — check stderr for clues
    if [ -z "$result" ]; then
        bashio::log.error "Empty result for task [$task_id] after ${duration}s"
        bashio::log.error "Stderr: ${stderr_output:0:500}"
        if [ "$duration" -ge "$((claude_limit - 5))" ] 2>/dev/null; then
            result="Claude task timed out after ${duration}s. This may be caused by a broken MCP server connection. Try restarting the brAIn add-on."
            bashio::log.error "Claude process timed out (limit=${claude_limit}s)"
            fail_code="timeout"
        elif echo "$stderr_output" | grep -qi "not logged in\|please log in\|authentication"; then
            result="Claude is not signed in. ${AUTH_REMEDY}"
            fail_code="auth"
        elif echo "$stderr_output" | grep -qi "permission\|not allowed\|denied"; then
            result="Claude encountered a permission error. Check the add-on logs for details."
            fail_code="permission"
        else
            result="Task failed — Claude didn't produce a result. Check the brAIn add-on logs."
            fail_code="empty"
        fi
    fi

    # Log response for debugging
    {
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] TASK RESPONSE $task_id"
        echo "  Duration: ${duration}s"
        echo "  Result:   ${#result} chars"
        if [ -n "$stderr_output" ]; then
            local token_info
            token_info=$(echo "$stderr_output" | grep -iE 'token|cost|usage|input|output' | head -5) || true
            if [ -n "$token_info" ]; then
                echo "  Tokens:   $token_info"
            fi
            echo "  Stderr:   ${stderr_output:0:500}"
        fi
        echo "  Preview:  ${result:0:200}"
        echo "----------------------------------------------------------------"
    } >> "$log_file"

    bashio::log.info "Task completed [$task_id]: ${duration}s, ${#result} chars"

    # Check for auth errors in the result text
    if echo "$result" | grep -qi "not logged in\|please log in\|authentication required"; then
        result="Claude is not signed in. ${AUTH_REMEDY}"
        fail_code="auth"
        bashio::log.error "Claude auth error - user needs to sign in from the panel"
    fi

    # Write result file (atomic via tmp + rename)
    write_task_result "$task_id" "$result" "${task_data:-}" "$fail_code"

    if [ -n "$fail_code" ]; then
        bashio::log.warning "Task failed [$task_id]: ${fail_code}"
    else
        bashio::log.info "Task completed [$task_id]"
    fi

    # The journal's word for how it ended (journal.OUTCOMES), and the row.
    local outcome="ok"
    case "$fail_code" in
        '') outcome="ok" ;;
        auth|timeout|max_turns) outcome="$fail_code" ;;
        permission) outcome="denied" ;;
        *) outcome="error" ;;
    esac
    journal_task "$outcome" "$duration" "$envelope_file" "${task_model:-}" \
        "$([ -n "$fail_code" ] && printf '%s' "${result:0:200}")" "$task_scheduled"

    # Send notification if requested. notify_entity names the notify
    # *service* ("notify.mobile_app_phone" or "mobile_app_phone"), so the
    # entity picks the endpoint and the payload carries only the message —
    # the old shape posted an extra entity_id key to persistent_notification,
    # which HA's notify schema rejects with a 400 the `|| true` swallowed:
    # no push, no persistent notification, nothing in the log.
    if [ "$notify" = "true" ] && [ -n "$notify_entity" ]; then
        local message notify_service notify_payload
        message=$(echo "$result" | head -10 | tr '\n' ' ')
        notify_service="${notify_entity#notify.}"
        local verb="completed"
        [ -n "$fail_code" ] && verb="failed"
        notify_payload=$(jq -n \
            --arg msg "Claude task ${verb}: ${message}" \
            '{"message": $msg}')
        curl -s -X POST \
            -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "$notify_payload" \
            "http://supervisor/core/api/services/notify/${notify_service}" 2>/dev/null || true
    fi

    # Fire completion event on the HA event bus — with the same status the
    # result file carries, so an automation listening for the event can
    # tell a failed task from an answered one.
    local event_payload event_status="completed"
    [ -n "$fail_code" ] && event_status="failed"
    event_payload=$(jq -n \
        --arg id "$task_id" \
        --arg status "$event_status" \
        --arg error "$fail_code" \
        '{"task_id": $id, "status": $status} + (if $error != "" then {"error": $error} else {} end)')
    curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "$event_payload" \
        "http://supervisor/core/api/events/brain_task_complete" 2>/dev/null || true
}

# Watch for new task files
listen_for_tasks() {
    if command -v inotifywait >/dev/null 2>&1; then
        bashio::log.info "Using inotifywait for efficient file watching"

        # Process any files that arrived before we started watching
        # (process_task claims by rename, so the watcher can't double-pick)
        for task_file in "$TASKS_DIR"/*.json; do
            [ -f "$task_file" ] || continue
            process_task "$task_file" &
        done

        # Watch for new files
        inotifywait -m -e close_write -e moved_to --format '%w%f' "$TASKS_DIR" 2>/dev/null | while read -r filepath; do
            case "$filepath" in
                *.json)
                    process_task "$filepath" &
                    ;;
            esac
        done
    else
        bashio::log.info "inotifywait not available, falling back to polling (5s)"

        while true; do
            for task_file in "$TASKS_DIR"/*.json; do
                [ -f "$task_file" ] || continue
                process_task "$task_file" &
            done
            sleep 5
        done
    fi
}

# Main
verify_mcp_config_full
cleanup_stale_files
listen_for_tasks
