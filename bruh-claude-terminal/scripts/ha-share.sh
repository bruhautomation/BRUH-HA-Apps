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

Examples:
  ha-share push /config/docs ha-docs
  ha-share pull ha-docs/index.html /config/www/
  ha-share ls
  ha-share ls ha-docs
EOF
    exit 0
}

check_share() {
    if [ ! -d "$SHARE_DIR" ]; then
        echo -e "${RED}Error: /share directory not available. Is the share volume mapped?${NC}" >&2
        exit 1
    fi
}

cmd_push() {
    local source="$1"
    local dest="${SHARE_DIR}/${2}"

    if [ ! -e "$source" ]; then
        echo -e "${RED}Error: Source '${source}' does not exist${NC}" >&2
        exit 1
    fi

    echo -e "${CYAN}Copying ${source} -> ${dest}${NC}"
    if [ -d "$source" ]; then
        mkdir -p "$dest"
        if command -v rsync >/dev/null 2>&1; then
            rsync -av --delete "$source/" "$dest/"
        else
            cp -r "$source"/* "$dest/" 2>/dev/null || cp -r "$source" "$dest"
        fi
    else
        mkdir -p "$(dirname "$dest")"
        cp "$source" "$dest"
    fi
    echo -e "${GREEN}Done. Files available at ${dest}${NC}"
}

cmd_pull() {
    local source="${SHARE_DIR}/${1}"
    local dest="$2"

    if [ ! -e "$source" ]; then
        echo -e "${RED}Error: Source '${source}' does not exist in /share${NC}" >&2
        exit 1
    fi

    echo -e "${CYAN}Copying ${source} -> ${dest}${NC}"
    if [ -d "$source" ]; then
        mkdir -p "$dest"
        if command -v rsync >/dev/null 2>&1; then
            rsync -av "$source/" "$dest/"
        else
            cp -r "$source"/* "$dest/" 2>/dev/null || cp -r "$source" "$dest"
        fi
    else
        mkdir -p "$(dirname "$dest")"
        cp "$source" "$dest"
    fi
    echo -e "${GREEN}Done.${NC}"
}

cmd_ls() {
    local path="${SHARE_DIR}/${1:-}"
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
        usage
        ;;
esac
