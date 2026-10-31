#!/bin/bash
# ============================================================================
# backup.sh
# ----------------------------------------------------------------------------
# Create a single backup of the active world set.
#
# Modes:
#   * git   — commits the worlds to a bare-ish git repo at /config/minecraft-backups/git
#             Enables fast incremental diffs and easy restores (git log / git checkout).
#   * tar   — writes a timestamped .tar.gz into /config/minecraft-backups/archives/
#
# Always:
#   * Calls save-off + save-all flush before copying so worlds are consistent.
#   * Calls save-on afterwards so the server resumes saving.
#   * Prunes old archives past BACKUP_KEEP_COUNT.
# ============================================================================

set -o pipefail

MC_SERVER_DIR="${MC_SERVER_DIR:-/config/minecraft}"
MC_BACKUP_DIR="${MC_BACKUP_DIR:-/config/minecraft-backups}"
BACKUP_USE_GIT="${BACKUP_USE_GIT:-true}"
BACKUP_KEEP_COUNT="${BACKUP_KEEP_COUNT:-48}"
# level-name is a per-world server.properties setting now (no global env), so
# read it from the active world's file to find the right world dirs to snapshot.
LEVEL_NAME=$(grep -E '^level-name=' "${MC_SERVER_DIR}/server.properties" 2>/dev/null | head -n 1 | cut -d= -f2-)
LEVEL_NAME="${LEVEL_NAME:-world}"
SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
LOG_PREFIX="[backup ${TIMESTAMP}]"
log() { printf '%s %s\n' "${LOG_PREFIX}" "$*"; }

# The copy tool a git-mode backup needs. 1.x images shipped without rsync, the
# copy step failed on every run, and the backup still said it was done (#570),
# so the tool is checked before anything is flushed or copied, and the check is
# also run once at add-on start (`backup.sh --check`).
copy_tool_ok() {
    if [ "${BACKUP_USE_GIT}" = "true" ]; then
        if ! command -v rsync >/dev/null 2>&1; then
            log "ERROR: rsync is not installed in this add-on image, so world backups cannot copy the world. Update the add-on or reinstall it."
            return 1
        fi
        if ! command -v git >/dev/null 2>&1; then
            log "ERROR: git is not installed in this add-on image, so world backups cannot be stored."
            return 1
        fi
    elif ! command -v tar >/dev/null 2>&1; then
        log "ERROR: tar is not installed in this add-on image, so world backups cannot be written."
        return 1
    fi
    return 0
}

if [ "${1:-}" = "--check" ]; then
    if copy_tool_ok; then
        if [ "${BACKUP_USE_GIT}" = "true" ]; then
            log "Backup self-check passed: rsync and git are available"
        else
            log "Backup self-check passed: tar is available"
        fi
        exit 0
    fi
    exit 1
fi

if [ ! -d "${MC_SERVER_DIR}" ]; then
    log "Server dir missing; nothing to back up"
    exit 0
fi

# Ask the running server to flush worlds to disk (best-effort).
rcon_flush() {
    python3 "${SCRIPTS_DIR}/rcon.py" "save-off"  >/dev/null 2>&1 || true
    python3 "${SCRIPTS_DIR}/rcon.py" "save-all flush" >/dev/null 2>&1 || true
    sleep 2
}
rcon_resume() {
    python3 "${SCRIPTS_DIR}/rcon.py" "save-on" >/dev/null 2>&1 || true
}

backup_worlds_git() {
    local repo="${MC_BACKUP_DIR}/git"
    mkdir -p "${repo}"
    if [ ! -d "${repo}/.git" ]; then
        log "Initialising git repo at ${repo}"
        git -C "${repo}" init -q
        git -C "${repo}" config user.email "bruh-minecraft@homeassistant.local"
        git -C "${repo}" config user.name  "BRUH Minecraft"
        git -C "${repo}" config gc.auto    0
        {
            echo "*.log"
            echo "cache/"
            echo "logs/"
            echo "crash-reports/"
            echo "*.pid"
            echo "*.lock"
            echo "session.lock"
        } > "${repo}/.gitignore"
    fi

    # Copy live worlds (and critical config) into the repo with rsync. A world
    # that was not copied is a failed backup, never a done one.
    if [ ! -d "${MC_SERVER_DIR}/${LEVEL_NAME}" ]; then
        log "ERROR: there is no world folder '${LEVEL_NAME}' in ${MC_SERVER_DIR}, so there is nothing to back up"
        return 1
    fi
    local worlds=( "${LEVEL_NAME}" "${LEVEL_NAME}_nether" "${LEVEL_NAME}_the_end" )
    for w in "${worlds[@]}"; do
        [ -d "${MC_SERVER_DIR}/${w}" ] || continue
        if ! rsync -a --delete \
                --exclude='session.lock' \
                --exclude='*.lock' \
                "${MC_SERVER_DIR}/${w}/" "${repo}/${w}/"; then
            log "ERROR: copying world '${w}' failed, so this backup does not hold it"
            return 1
        fi
        if [ -f "${MC_SERVER_DIR}/${w}/level.dat" ] && [ ! -f "${repo}/${w}/level.dat" ]; then
            log "ERROR: level.dat of '${w}' is missing from the copy, so this backup does not hold it"
            return 1
        fi
    done

    for f in server.properties ops.json whitelist.json banned-players.json banned-ips.json bukkit.yml spigot.yml paper-global.yml; do
        [ -f "${MC_SERVER_DIR}/${f}" ] || continue
        mkdir -p "${repo}/_config"
        cp -f "${MC_SERVER_DIR}/${f}" "${repo}/_config/${f}"
    done

    if ! git -C "${repo}" add -A; then
        log "ERROR: could not stage the copied world in the backup repository"
        return 1
    fi
    if git -C "${repo}" diff --cached --quiet; then
        log "No changes to commit"
        return 0
    fi
    if ! git -C "${repo}" commit -q -m "backup ${TIMESTAMP}" \
            -m "Players online at backup: $(get_player_count)"; then
        log "ERROR: could not commit the snapshot to the backup repository"
        return 1
    fi
    log "Committed snapshot $(git -C "${repo}" rev-parse --short HEAD)"

    # Trim history past keep-count (best effort — rewrites refs, not blobs)
    local keep="${BACKUP_KEEP_COUNT}"
    local total
    total=$(git -C "${repo}" rev-list --count HEAD)
    if [ "${total}" -gt "${keep}" ]; then
        local drop=$((total - keep))
        log "Pruning ${drop} old commits (keeping ${keep})"
        local new_root
        new_root=$(git -C "${repo}" rev-list --max-parents=0 HEAD~${drop} 2>/dev/null | head -n1 || true)
        if [ -n "${new_root}" ]; then
            git -C "${repo}" update-ref refs/heads/main "${new_root}" 2>/dev/null || true
        fi
    fi
}

backup_worlds_tar() {
    local archives="${MC_BACKUP_DIR}/archives"
    mkdir -p "${archives}"
    local out="${archives}/world-${TIMESTAMP}.tar.gz"
    log "Writing archive ${out}"

    local worlds=()
    for w in "${LEVEL_NAME}" "${LEVEL_NAME}_nether" "${LEVEL_NAME}_the_end"; do
        [ -d "${MC_SERVER_DIR}/${w}" ] && worlds+=( "${w}" )
    done
    [ "${#worlds[@]}" -gt 0 ] || { log "ERROR: no world folder found in ${MC_SERVER_DIR}, so there is nothing to back up"; return 1; }

    if ! tar -C "${MC_SERVER_DIR}" -czf "${out}" "${worlds[@]}"; then
        log "ERROR: writing the archive failed, so this backup does not hold the world"
        rm -f "${out}"
        return 1
    fi
    log "Archive size $(du -h "${out}" | cut -f1)"

    # Prune
    mapfile -t all_archives < <(ls -1t "${archives}"/world-*.tar.gz 2>/dev/null || true)
    local keep="${BACKUP_KEEP_COUNT}"
    if [ "${#all_archives[@]}" -gt "${keep}" ]; then
        for old in "${all_archives[@]:${keep}}"; do
            log "Pruning $(basename "${old}")"
            rm -f "${old}"
        done
    fi
}

get_player_count() {
    local reply
    reply=$(python3 "${SCRIPTS_DIR}/rcon.py" "list" 2>/dev/null || echo "")
    echo "${reply}" | grep -oE 'There are [0-9]+' | awk '{print $3}' | head -n1
}

main() {
    # Check the tool before save-off, so a missing one never leaves saving off.
    copy_tool_ok || return 1
    rcon_flush
    local rc=0
    if [ "${BACKUP_USE_GIT}" = "true" ]; then
        backup_worlds_git || rc=$?
    else
        backup_worlds_tar || rc=$?
    fi
    rcon_resume
    if [ "${rc}" -ne 0 ]; then
        log "Backup FAILED"
        return "${rc}"
    fi
    return 0
}

main
exit $?
