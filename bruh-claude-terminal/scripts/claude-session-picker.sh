#!/bin/bash

# BRUH Claude Terminal - Enhanced Session Picker
# Adds background task support, multi-session via tmux windows

TMUX_SESSION_NAME="claude"
TASK_DIR="/data/tasks"
mkdir -p "$TASK_DIR"

# Read the permissions flag from the shared env file written by run.sh.
# Defaults to --dangerously-skip-permissions if the env file is missing
# (backwards compatibility with older run.sh versions).
PERMS_FLAG="--dangerously-skip-permissions"
if [ -f /data/.bruh_claude_env ]; then
    # shellcheck disable=SC1091
    source /data/.bruh_claude_env
    PERMS_FLAG="${BRUH_CLAUDE_PERMS_FLAG:-$PERMS_FLAG}"
fi

show_banner() {
    clear
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║             BRUH Claude Terminal                           ║"
    echo "║             Enhanced Session Picker                        ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
}

check_existing_session() {
    tmux has-session -t "$TMUX_SESSION_NAME" 2>/dev/null
}

count_tmux_windows() {
    if check_existing_session; then
        tmux list-windows -t "$TMUX_SESSION_NAME" 2>/dev/null | wc -l
    else
        echo "0"
    fi
}

show_running_tasks() {
    local tasks
    tasks=$(ls "$TASK_DIR"/*.running 2>/dev/null | wc -l)
    if [ "$tasks" -gt 0 ]; then
        echo "  Background tasks running: $tasks"
        ls "$TASK_DIR"/*.running 2>/dev/null | while read -r f; do
            local name
            name=$(basename "$f" .running)
            echo "    - $name"
        done
        echo ""
    fi
}

show_menu() {
    echo "Choose your session type:"
    echo ""

    if check_existing_session; then
        local windows
        windows=$(count_tmux_windows)
        echo "  0) Reconnect to existing session ($windows window(s))"
        echo ""
    fi

    echo "  1) New interactive session (default)"
    echo "  2) Continue most recent conversation (-c)"
    echo "  3) Resume from conversation list (-r)"
    echo "  4) Custom Claude command (manual flags)"
    echo "  5) New window in existing session"
    echo "  6) Background task (Claude works autonomously)"
    echo "  7) Authentication helper"
    echo "  8) Bash shell"
    echo "  9) HA Tools menu"
    echo "  q) Exit"
    echo ""

    show_running_tasks
}

get_user_choice() {
    local choice
    local default="1"

    if check_existing_session; then
        default="0"
    fi

    printf "Enter your choice (default: %s): " "$default" >&2
    read -r choice

    if [ -z "$choice" ]; then
        choice="$default"
    fi

    choice=$(echo "$choice" | tr -d '[:space:]')
    echo "$choice"
}

attach_existing_session() {
    echo "Reconnecting to existing Claude session..."
    sleep 1
    exec tmux attach-session -t "$TMUX_SESSION_NAME"
}

launch_claude_new() {
    echo "Starting new Claude session..."

    if check_existing_session; then
        echo "   (closing previous session)"
        tmux kill-session -t "$TMUX_SESSION_NAME" 2>/dev/null
    fi

    sleep 1
    exec tmux new-session -s "$TMUX_SESSION_NAME" "claude ${PERMS_FLAG}"
}

launch_claude_continue() {
    echo "Continuing most recent conversation..."

    if check_existing_session; then
        tmux kill-session -t "$TMUX_SESSION_NAME" 2>/dev/null
    fi

    sleep 1
    exec tmux new-session -s "$TMUX_SESSION_NAME" "claude ${PERMS_FLAG} -c"
}

launch_claude_resume() {
    echo "Opening conversation list..."

    if check_existing_session; then
        tmux kill-session -t "$TMUX_SESSION_NAME" 2>/dev/null
    fi

    sleep 1
    exec tmux new-session -s "$TMUX_SESSION_NAME" "claude ${PERMS_FLAG} -r"
}

launch_claude_custom() {
    echo ""
    echo "Enter your Claude command:"
    echo "Available flags: -c (continue), -r (resume), -p (print), --model, etc."
    echo -n "> claude "
    read -r custom_args

    if [ -z "$custom_args" ]; then
        launch_claude_new
    else
        # Validate: only allow flags and simple arguments (no shell metacharacters)
        if echo "$custom_args" | grep -qE '[;&|$`\\()\{}<>!]'; then
            echo "Error: Shell metacharacters are not allowed in arguments."
            echo "Only Claude CLI flags and their values are permitted."
            sleep 2
            return
        fi

        echo "Running: claude $custom_args"

        if check_existing_session; then
            tmux kill-session -t "$TMUX_SESSION_NAME" 2>/dev/null
        fi

        sleep 1
        exec tmux new-session -s "$TMUX_SESSION_NAME" "claude $custom_args"
    fi
}

launch_new_window() {
    if ! check_existing_session; then
        echo "No existing session. Starting new session..."
        sleep 1
        exec tmux new-session -s "$TMUX_SESSION_NAME" "claude ${PERMS_FLAG}"
    fi

    echo "Opening new Claude window in existing session..."
    tmux new-window -t "$TMUX_SESSION_NAME" "claude ${PERMS_FLAG}"
    sleep 1
    exec tmux attach-session -t "$TMUX_SESSION_NAME"
}

launch_background_task() {
    echo ""
    echo "Enter a prompt for Claude to work on in the background:"
    echo "(Claude will work autonomously and save output to /data/tasks/)"
    echo ""
    echo -n "> "
    read -r task_prompt

    if [ -z "$task_prompt" ]; then
        echo "No prompt provided"
        sleep 1
        return
    fi

    local task_id
    task_id="task_$(date +%s)"
    local task_file="$TASK_DIR/${task_id}"

    echo "Starting background task: $task_id"
    touch "${task_file}.running"

    # Run Claude in background with the prompt
    (
        claude ${PERMS_FLAG} -p "$task_prompt" > "${task_file}.output" 2>&1
        rm -f "${task_file}.running"
        touch "${task_file}.done"
        echo "Task $task_id completed at $(date)" >> "${task_file}.output"
    ) &

    echo "Task $task_id started in background"
    echo "Output will be saved to: ${task_file}.output"
    echo "Check status: ls /data/tasks/"
    echo ""
    printf "Press Enter to continue..." >&2
    read -r
}

launch_auth_helper() {
    echo "Starting authentication helper..."
    sleep 1
    exec /opt/scripts/claude-auth-helper.sh
}

launch_bash_shell() {
    echo "Dropping to bash shell..."
    echo "Tip: Run 'tmux new-session -A -s claude \"claude\"' to start with persistence"
    sleep 1
    exec bash
}

show_ha_tools_menu() {
    clear
    echo "╔══════════════════════════════════════════════════════════════╗"
    echo "║             Home Assistant Tools                           ║"
    echo "╚══════════════════════════════════════════════════════════════╝"
    echo ""
    echo "  1) Reload automations"
    echo "  2) Reload scripts"
    echo "  3) Reload all configurations"
    echo "  4) Validate configuration"
    echo "  5) View core logs"
    echo "  6) View error logs"
    echo "  7) Regenerate Claude context"
    echo "  8) Create config backup"
    echo "  9) Back to main menu"
    echo ""
    printf "Choice: " >&2
    read -r ha_choice

    case "$ha_choice" in
        1) ha-reload automations ;;
        2) ha-reload scripts ;;
        3) ha-reload all ;;
        4) ha-reload check ;;
        5) ha-log core -n 50 ;;
        6) ha-log errors ;;
        7) ha-context-gen ;;
        8) ha-backup ;;
        9) return ;;
        *) echo "Invalid choice" ;;
    esac

    echo ""
    printf "Press Enter to continue..." >&2
    read -r
}

# Main execution flow
main() {
    while true; do
        show_banner
        show_menu
        choice=$(get_user_choice)

        case "$choice" in
            0)
                if check_existing_session; then
                    attach_existing_session
                else
                    echo "No existing session found"
                    sleep 1
                fi
                ;;
            1) launch_claude_new ;;
            2) launch_claude_continue ;;
            3) launch_claude_resume ;;
            4) launch_claude_custom ;;
            5) launch_new_window ;;
            6) launch_background_task ;;
            7) launch_auth_helper ;;
            8) launch_bash_shell ;;
            9) show_ha_tools_menu ;;
            q|Q) echo "Goodbye!"; exit 0 ;;
            *)
                echo ""
                echo "Invalid choice: '$choice'"
                printf "Press Enter to continue..." >&2
                read -r
                ;;
        esac
    done
}

trap 'echo ""; exit 0' EXIT INT TERM

main "$@"
