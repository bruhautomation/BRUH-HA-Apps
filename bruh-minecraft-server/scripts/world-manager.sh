#!/bin/bash
# ============================================================================
# world-manager.sh — switchable server profiles CLI
# ----------------------------------------------------------------------------
# Each profile is a full server root under ${MC_WORLDS_DIR:-/config/minecraft-worlds}/<name>/
# plus its own backup tree under ${MC_BACKUPS_ROOT:-/config/minecraft-backups}/<name>/.
#
# Subcommands:
#   list                    — print one profile per line: name<TAB>size<TAB>active?
#   create <name> [seed]    — stage an empty profile, optionally with a fixed seed
#   switch <name>           — writes active_world=<name> to the add-on options
#                              via the Supervisor API, then exits. Caller must
#                              restart the add-on for the change to take effect.
#   delete <name>           — remove a profile + its backups (refuses the
#                              currently-active profile)
#   rename <old> <new>      — move a profile (and its level folders, its
#                              level-name and its backups) to a new name. The
#                              caller stops the server first when <old> is the
#                              active profile, and updates the active_world
#                              add-on option afterwards.
#   active                  — print the currently-active profile name
#
# Profile name constraints: 1-32 chars, [A-Za-z0-9_-].
#
# Exit codes:
#   0  success
#   1  generic failure
#   2  bad input / validation error
#   3  refused (e.g. delete active profile)
# ============================================================================
set -o pipefail

MC_WORLDS_DIR="${MC_WORLDS_DIR:-/config/minecraft-worlds}"
MC_BACKUPS_ROOT="${MC_BACKUPS_ROOT:-/config/minecraft-backups}"
MC_SERVER_LINK="${MC_SERVER_LINK:-/config/minecraft}"

log()  { printf '[world-manager] %s\n' "$*" >&2; }
die()  { log "ERROR: $*"; exit "${2:-1}"; }

valid_name() {
    printf '%s' "$1" | grep -Eq '^[A-Za-z0-9_-]{1,32}$'
}

MC_OPTIONS_FILE="${MC_OPTIONS_FILE:-/data/options.json}"

# The active world is whatever the add-on option says (the source of truth
# run.sh boots from), falling back to the live /config/minecraft symlink and
# finally "default". Reading the option first fixes a stale-state bug: on a
# legacy install /config/minecraft is still a plain directory (not yet a
# symlink), so the old symlink-only logic always returned the literal
# "default" even when the operator had switched to another profile.
active_world() {
    local from_option=""
    if [ -r "${MC_OPTIONS_FILE}" ]; then
        from_option=$(jq -r '.active_world // empty' "${MC_OPTIONS_FILE}" 2>/dev/null || true)
    fi
    if [ -n "${from_option}" ] && valid_name "${from_option}"; then
        printf '%s' "${from_option}"
    elif [ -L "${MC_SERVER_LINK}" ]; then
        basename "$(readlink "${MC_SERVER_LINK}")"
    else
        printf 'default'
    fi
}

cmd_list() {
    mkdir -p "${MC_WORLDS_DIR}"
    local active
    active=$(active_world)
    shopt -s nullglob
    for d in "${MC_WORLDS_DIR}"/*/; do
        local name size is_active
        name=$(basename "${d%/}")
        size=$(du -sb "${d}" 2>/dev/null | cut -f1 || printf '0')
        is_active="false"
        [ "${name}" = "${active}" ] && is_active="true"
        printf '%s\t%s\t%s\n' "${name}" "${size}" "${is_active}"
    done
    shopt -u nullglob
}

cmd_create() {
    local name="${1:-}"
    local seed="${2:-}"
    valid_name "${name}" || die "invalid name (1-32 chars, [A-Za-z0-9_-])" 2
    local dir="${MC_WORLDS_DIR}/${name}"
    if [ -e "${dir}" ]; then
        die "profile already exists: ${name}" 2
    fi
    mkdir -p "${dir}" "${dir}/plugins" "${dir}/mods" "${MC_BACKUPS_ROOT}/${name}"
    # Minimal server.properties so a switch+restart has something to boot.
    # The add-on's setup-server-properties.sh overwrites managed keys on
    # every boot, so only the UI-only defaults matter here.
    {
        printf '# staged by world-manager create\n'
        printf 'level-name=world\n'
        [ -n "${seed}" ] && printf 'level-seed=%s\n' "${seed}"
    } > "${dir}/server.properties"
    printf 'eula=false\n' > "${dir}/eula.txt"
    chown -R minecraft:minecraft "${dir}" "${MC_BACKUPS_ROOT}/${name}" 2>/dev/null || true
    log "Created profile: ${name} at ${dir}"
}

cmd_switch() {
    local name="${1:-}"
    valid_name "${name}" || die "invalid name" 2
    [ -d "${MC_WORLDS_DIR}/${name}" ] || die "profile '${name}' does not exist — create it first" 2

    # Write active_world back to the add-on options through the Supervisor.
    # The caller must restart the add-on afterwards; the ensure_worlds_layout
    # step in run.sh will relink /config/minecraft to the new target.
    if [ -z "${SUPERVISOR_TOKEN:-}" ]; then
        die "SUPERVISOR_TOKEN not set; cannot update options from this context" 1
    fi
    local supervisor_base="${SUPERVISOR_API_URL:-http://supervisor}"

    # Supervisor's POST /addons/self/options REPLACES the options object and
    # runs the full add-on schema validation against the new payload. A bare
    # {"active_world": "<name>"} is rejected with
    #   "Missing option 'allow_nether' in root in BRUH Minecraft…"
    # because every required field that isn't in the payload is treated as
    # missing. Fetch the current options first, merge in the new
    # active_world, then POST the merged object so the rest of the config
    # survives the round-trip.
    local info_code
    info_code=$(curl -sS -o /tmp/world-manager-info.out -w "%{http_code}" \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        "${supervisor_base}/addons/self/info" 2>&1) || true
    if [ "${info_code}" != "200" ]; then
        log "Supervisor /addons/self/info returned HTTP ${info_code}:"
        cat /tmp/world-manager-info.out >&2 || true
        rm -f /tmp/world-manager-info.out
        exit 1
    fi
    local payload
    payload=$(jq -c --arg w "${name}" \
        '{options: ((.data.options // {}) + {active_world: $w})}' \
        /tmp/world-manager-info.out)
    rm -f /tmp/world-manager-info.out
    if [ -z "${payload}" ]; then
        die "failed to build merged options payload" 1
    fi

    local http_code
    http_code=$(curl -sS -o /tmp/world-manager-switch.out -w "%{http_code}" \
        -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "${payload}" \
        "${supervisor_base}/addons/self/options" 2>&1) || true
    if [ "${http_code}" != "200" ]; then
        log "Supervisor options update returned HTTP ${http_code}:"
        cat /tmp/world-manager-switch.out >&2 || true
        exit 1
    fi
    rm -f /tmp/world-manager-switch.out
    log "active_world set to '${name}'. Restart the add-on to activate."
}

cmd_delete() {
    local name="${1:-}"
    valid_name "${name}" || die "invalid name" 2
    local active
    active=$(active_world)
    [ "${name}" = "${active}" ] && die "refusing to delete the active profile '${name}'" 3
    [ -d "${MC_WORLDS_DIR}/${name}" ] || die "profile '${name}' does not exist" 2
    rm -rf "${MC_WORLDS_DIR:?}/${name}"
    rm -rf "${MC_BACKUPS_ROOT:?}/${name}"
    log "Deleted profile: ${name}"
}

# Move a profile to a new name. Every step is undone if a later one fails, so
# a refusal or an error never leaves half a world behind.
cmd_rename() {
    local old="${1:-}" new="${2:-}"
    valid_name "${old}" || die "invalid current name" 2
    valid_name "${new}" || die "invalid new name (1-32 characters: letters, digits, _ and -)" 2
    [ "${old}" != "${new}" ] || die "the new name is the same as the current one" 2
    [ -d "${MC_WORLDS_DIR}/${old}" ] || die "world '${old}' does not exist" 2
    [ ! -e "${MC_WORLDS_DIR}/${new}" ] || die "a world named '${new}' already exists" 2
    [ ! -e "${MC_BACKUPS_ROOT}/${new}" ] || die "a backup folder named '${new}' already exists" 2

    local src="${MC_WORLDS_DIR}/${old}" dst="${MC_WORLDS_DIR}/${new}"
    local props="${dst}/server.properties" level=""
    local moved_backups=0 moved_level=0 relinked=0 link_was=""

    undo() {
        [ "${relinked}" -eq 1 ] && ln -sfn "${link_was}" "${MC_SERVER_LINK}" 2>/dev/null
        if [ "${moved_level}" -eq 1 ]; then
            for sfx in "" _nether _the_end; do
                [ -d "${dst}/${new}${sfx}" ] && mv "${dst}/${new}${sfx}" "${dst}/${old}${sfx}"
            done
            [ -f "${props}.bak" ] && mv -f "${props}.bak" "${props}"
        fi
        [ "${moved_backups}" -eq 1 ] && mv "${MC_BACKUPS_ROOT}/${new}" "${MC_BACKUPS_ROOT}/${old}"
        [ -d "${dst}" ] && [ ! -e "${src}" ] && mv "${dst}" "${src}"
        return 0
    }

    mv "${src}" "${dst}" || die "could not move the world folder" 1

    if [ -f "${props}" ]; then
        level=$(grep -E '^level-name=' "${props}" | head -n 1 | cut -d= -f2-)
    fi
    # Only a level folder that carries the world's own name is renamed with it;
    # one called "world" (the default) keeps its name, because it is the
    # server's, not the profile's.
    if [ "${level}" = "${old}" ]; then
        cp -f "${props}" "${props}.bak" || { undo; die "could not read server.properties" 1; }
        moved_level=1
        for sfx in "" _nether _the_end; do
            if [ -d "${dst}/${old}${sfx}" ]; then
                mv "${dst}/${old}${sfx}" "${dst}/${new}${sfx}" || { undo; die "could not rename the level folder '${old}${sfx}'" 1; }
            fi
        done
        if ! sed "s/^level-name=.*/level-name=${new}/" "${props}.bak" > "${props}.tmp" \
                || ! mv -f "${props}.tmp" "${props}"; then
            rm -f "${props}.tmp"
            undo; die "could not update level-name in server.properties" 1
        fi
    fi

    if [ -d "${MC_BACKUPS_ROOT}/${old}" ]; then
        mv "${MC_BACKUPS_ROOT}/${old}" "${MC_BACKUPS_ROOT}/${new}" \
            || { undo; die "could not move the backups folder" 1; }
        moved_backups=1
    fi

    if [ -L "${MC_SERVER_LINK}" ] && [ "$(readlink "${MC_SERVER_LINK}")" = "${src}" ]; then
        link_was="${src}"
        ln -sfn "${dst}" "${MC_SERVER_LINK}" || { undo; die "could not repoint ${MC_SERVER_LINK}" 1; }
        relinked=1
    fi
    rm -f "${props}.bak"
    log "Renamed world '${old}' to '${new}'"
}

cmd_active() {
    active_world
}

sub="${1:-}"
shift || true
case "${sub}" in
    list)    cmd_list "$@" ;;
    create)  cmd_create "$@" ;;
    switch)  cmd_switch "$@" ;;
    delete)  cmd_delete "$@" ;;
    rename)  cmd_rename "$@" ;;
    active)  cmd_active "$@" ;;
    *)       die "usage: world-manager.sh {list|create|switch|delete|rename|active} [args]" 2 ;;
esac
