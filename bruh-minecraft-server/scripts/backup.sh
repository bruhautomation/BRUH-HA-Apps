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
LEVEL_NAME="${LEVEL_NAME:-world}"
SCRIPTS_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"

TIMESTAMP=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
LOG_PREFIX="[backup ${TIMESTAMP}]"
log() { printf '%s %s\n' "${LOG_PREFIX}" "$*"; }

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

    # Copy live worlds (and critical config) into the repo with rsync
    local worlds=( "${LEVEL_NAME}" "${LEVEL_NAME}_nether" "${LEVEL_NAME}_the_end" )
    for w in "${worlds[@]}"; do
        [ -d "${MC_SERVER_DIR}/${w}" ] || continue
        rsync -a --delete \
            --exclude='session.lock' \
            --exclude='*.lock' \
            "${MC_SERVER_DIR}/${w}/" "${repo}/${w}/"
    done

    for f in server.properties ops.json whitelist.json banned-players.json banned-ips.json bukkit.yml spigot.yml paper-global.yml; do
        [ -f "${MC_SERVER_DIR}/${f}" ] || continue
        mkdir -p "${repo}/_config"
        cp -f "${MC_SERVER_DIR}/${f}" "${repo}/_config/${f}"
    done

    git -C "${repo}" add -A
    if git -C "${repo}" diff --cached --quiet; then
        log "No changes to commit"
        return 0
    fi
    git -C "${repo}" commit -q -m "backup ${TIMESTAMP}" \
        -m "Players online at backup: $(get_player_count)"
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
    [ "${#worlds[@]}" -gt 0 ] || { log "No world dirs found"; return 0; }

    tar -C "${MC_SERVER_DIR}" -czf "${out}" "${worlds[@]}"
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
    rcon_flush
    if [ "${BACKUP_USE_GIT}" = "true" ]; then
        backup_worlds_git
    else
        backup_worlds_tar
    fi
    rcon_resume
}

main
