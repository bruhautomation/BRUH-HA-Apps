#!/bin/bash
# PreToolUse hook: one line per tool call a TASK makes, so whoever handed
# brAIn the task can show what it is doing while it does it.
#
# A task is a `claude -p` run with nobody watching it; the only thing the
# caller (Morph's Tell, BRight's director, a `brain.run_task`) used to see
# between "claimed" and "answered" was nothing, for up to fifteen minutes.
# The automation listener sets BRAIN_TASK_PROGRESS to a file per task
# (/config/.brain/task_progress/<id>.jsonl) and this appends
# {at, tool, what} to it before each call.
#
# Three rules:
# * It never decides anything. It prints nothing and always exits 0, so the
#   call goes on exactly as if the hook were not there.
# * Without the variable it exits on its first line. It is wired into every
#   headless run (voice workers, `brain ask`), and a hook every tool call
#   pays for has to cost nothing where it is not wanted — which is why it is
#   a shell script and not Python.
# * `what` is the call's subject (a file, a pattern, an entity, a command's
#   first 120 characters), never its content: what an Edit writes is not
#   progress, and the file sits under /config.
[ -n "${BRAIN_TASK_PROGRESS:-}" ] || exit 0
command -v jq > /dev/null 2>&1 || exit 0
jq -c --arg at "$(date +%s)" '{
    at: ($at | tonumber),
    tool: (.tool_name // "" | tostring | .[0:80]),
    what: ((.tool_input // {}) as $i
           | ($i.file_path // $i.notebook_path // $i.path // $i.pattern
              // $i.entity_id // $i.url // $i.query // $i.description
              // $i.command // $i.domain // "")
           | tostring | gsub("[\\r\\n]+"; " ") | .[0:120])
}' 2> /dev/null >> "$BRAIN_TASK_PROGRESS" || true
exit 0
