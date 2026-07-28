#!/usr/bin/env bash

# ha-share — Sync files to/from /share for cross-addon access
# Usage:
#   ha-share push <source_path> <share_dest>   — Copy files to /share/
#   ha-share pull <share_source> <dest_path>   — Copy files from /share/
#   ha-share ls [path]                          — List /share/ contents
# Examples:
#   ha-share push /config/docs ha-docs
#   ha-share pull ha-docs/index.html /config/www/
#   ha-share ls

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
NC='\033[0m'

SHARE_DIR="/share"

usage() {
    cat << 'EOF'
ha-share — Sync files to/from /share for cross-addon access

Usage:
  ha-share push <source_path> <share_dest>   Copy files to /share/<share_dest>
  ha-share pull <share_source> <dest_path>   Copy files from /share/<share_source>
  ha-share ls [path]                          List /share/ contents

The /share directory is accessible by any add-on that maps the share volume.
Use it for cross-addon file operations.

Paths are contained to /share (".." escapes are refused), and files that
look like credentials (secrets.yaml, .storage, keys, tokens) are refused
unless --force is given — anything pushed to /share is readable by every
other add-on.

Examples:
  ha-share push /config/docs ha-docs
  ha-share pull ha-docs/index.html /config/www/
  ha-share ls
  ha-share ls ha-docs
EOF
    exit "${1:-0}"
}

check_share() {
    if [ ! -d "$SHARE_DIR" ]; then
        echo -e "${RED}Error: /share directory not available. Is the share volume mapped?${NC}" >&2
        exit 1
    fi
}

# Resolve a /share-relative path and refuse anything that escapes /share.
# Without this, "ha-share ls .." lists the container root and
# "ha-share push x ../config/..." writes outside the shared volume.
resolve_share_path() {
    local rel="$1"
    local candidate="${SHARE_DIR}/${rel}"
    local resolved
    # Resolve the deepest existing ancestor so containment holds even for
    # not-yet-created destinations (push creates parents itself).
    local probe="$candidate"
    while [ ! -e "$probe" ]; do
        probe="$(dirname "$probe")"
    done
    resolved="$(realpath "$probe" 2>/dev/null)" || {
        echo -e "${RED}Error: could not resolve path '${rel}'${NC}" >&2
        exit 1
    }
    if [ "$resolved" != "$SHARE_DIR" ] && [[ "$resolved" != "$SHARE_DIR"/* ]]; then
        echo -e "${RED}Error: '${rel}' resolves outside ${SHARE_DIR} — refusing${NC}" >&2
        exit 1
    fi
    # Re-append the non-existing suffix, if any.
    printf '%s%s' "$resolved" "${candidate#"$probe"}"
}

# Files that must never land in /share: it is readable by any add-on that
# maps the share volume, so pushing credentials there exposes them to
# everything. Override only with an explicit --force.
is_sensitive_source() {
    local src="$1"
    local resolved base
    resolved="$(realpath "$src" 2>/dev/null || echo "$src")"
    base="$(basename "$resolved")"
    case "$resolved" in
        /config/secrets.yaml|/config/.storage/auth*|/config/.storage/*) return 0 ;;
        /config/.bruh_claude/secrets/*|*/.bruh_claude/secrets/*) return 0 ;;
        /config/.cloud/*|/ssl/*) return 0 ;;
    esac
    case "$base" in
        secrets.yaml|*.pem|*.key|id_rsa*|id_ed25519*|*token*|*credential*) return 0 ;;
    esac
    # Directories: refuse if they contain an obvious secrets file.
    if [ -d "$resolved" ]; then
        if find "$resolved" -maxdepth 2 \( -name secrets.yaml -o -name "*.key" \
            -o -path "*/.storage/*" -o -path "*/.bruh_claude/secrets/*" \) \
            2>/dev/null | head -1 | grep -q .; then
            return 0
        fi
    fi
    return 1
}

# Copy a directory's CONTENTS into dest, dotfiles included. The old
# `cp -r "$src"/* "$dest/" || cp -r "$src" "$dest"` fallback silently
# switched between copying contents and copying the directory itself, and
# `*` skipped dotfiles without a word.
copy_dir_contents() {
    local src="$1" dest="$2"
    mkdir -p "$dest"
    if command -v rsync >/dev/null 2>&1; then
        rsync -a "$src/" "$dest/"
    else
        # `.` after the source path copies contents including dotfiles.
        cp -a "$src/." "$dest/"
    fi
}

cmd_push() {
    local source="$1"
    local dest
    dest="$(resolve_share_path "$2")"

    if [ ! -e "$source" ]; then
        echo -e "${RED}Error: Source '${source}' does not exist${NC}" >&2
        exit 1
    fi

    if [ "$FORCE" != "true" ] && is_sensitive_source "$source"; then
        echo -e "${RED}Error: '${source}' looks like credentials/secrets. /share is readable" >&2
        echo -e "by every add-on that maps the share volume — refusing to copy it there." >&2
        echo -e "If you are certain, re-run with --force.${NC}" >&2
        exit 1
    fi

    echo -e "${CYAN}Copying ${source} -> ${dest}${NC}"
    if [ -d "$source" ]; then
        if command -v rsync >/dev/null 2>&1; then
            mkdir -p "$dest"
            rsync -a --delete "$source/" "$dest/"
        else
            copy_dir_contents "$source" "$dest"
        fi
    else
        mkdir -p "$(dirname "$dest")"
        cp "$source" "$dest"
    fi
    echo -e "${GREEN}Done. Files available at ${dest}${NC}"
}

cmd_pull() {
    local source
    source="$(resolve_share_path "$1")"
    local dest="$2"

    if [ ! -e "$source" ]; then
        echo -e "${RED}Error: Source '${source}' does not exist in /share${NC}" >&2
        exit 1
    fi

    echo -e "${CYAN}Copying ${source} -> ${dest}${NC}"
    if [ -d "$source" ]; then
        copy_dir_contents "$source" "$dest"
    else
        mkdir -p "$(dirname "$dest")"
        cp "$source" "$dest"
    fi
    echo -e "${GREEN}Done.${NC}"
}

cmd_ls() {
    local path
    path="$(resolve_share_path "${1:-}")"
    if [ ! -e "$path" ]; then
        echo -e "${RED}Error: '${path}' does not exist${NC}" >&2
        exit 1
    fi

    echo -e "${CYAN}Contents of ${path}:${NC}"
    if command -v tree >/dev/null 2>&1; then
        tree -L 2 --dirsfirst "$path"
    else
        ls -la "$path"
    fi
}

# Main
[ "${1:-}" = "--help" ] || [ "${1:-}" = "-h" ] && usage
[ $# -lt 1 ] && usage

check_share

# Strip --force anywhere in the arg list (needed to push secret-looking files).
FORCE=false
args=()
for arg in "$@"; do
    if [ "$arg" = "--force" ]; then
        FORCE=true
    else
        args+=("$arg")
    fi
done
set -- "${args[@]}"
[ $# -lt 1 ] && usage

action="${1}"
shift

case "$action" in
    push)
        [ $# -lt 2 ] && { echo -e "${RED}Error: 'push' requires <source_path> <share_dest>${NC}" >&2; exit 1; }
        cmd_push "$1" "$2"
        ;;
    pull)
        [ $# -lt 2 ] && { echo -e "${RED}Error: 'pull' requires <share_source> <dest_path>${NC}" >&2; exit 1; }
        cmd_pull "$1" "$2"
        ;;
    ls)
        cmd_ls "${1:-}"
        ;;
    --help|-h)
        usage
        ;;
    *)
        echo -e "${RED}Unknown action: ${action}${NC}" >&2
        usage 1
        ;;
esac
