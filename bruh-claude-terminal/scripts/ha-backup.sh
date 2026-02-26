#!/usr/bin/with-contenv bashio

# ha-backup - Manual backup trigger for /config git versioning
# Usage: ha-backup [commit-message]

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CONFIG_DIR="/config"
COMMIT_MSG="${1:-Manual backup via ha-backup}"

do_backup() {
    if [ ! -d "$CONFIG_DIR/.git" ]; then
        echo -e "${YELLOW}Git repository not initialized in /config${NC}"
        echo -e "Initializing now..."

        cd "$CONFIG_DIR"
        git init
        git config user.email "bruh-claude@homeassistant.local"
        git config user.name "BRUH Claude Terminal"

        if [ ! -f "$CONFIG_DIR/.gitignore" ]; then
            cat > "$CONFIG_DIR/.gitignore" << 'GITIGNORE'
# BRUH Claude Terminal auto-backup gitignore
secrets.yaml
.storage/auth*
.storage/onboarding*
*.db
*.db-shm
*.db-wal
home-assistant_v2.db*
*.log
*.log.*
__pycache__/
*.pyc
.cache/
tts/
*.tmp
claude-config/
.claude/
www/
media/
custom_components/__pycache__/
GITIGNORE
        fi

        git add -A
        git commit -m "Initial backup" --allow-empty || true
        echo -e "${GREEN}Git repository initialized${NC}"
    fi

    cd "$CONFIG_DIR"

    # Check for changes
    local changes
    changes=$(git status --porcelain 2>/dev/null || echo "")

    if [ -z "$changes" ]; then
        echo -e "${BLUE}No changes to back up${NC}"
        return 0
    fi

    # Show what changed
    echo -e "${BLUE}Changes detected:${NC}"
    echo "$changes" | head -20
    local total_changes
    total_changes=$(echo "$changes" | wc -l)
    if [ "$total_changes" -gt 20 ]; then
        echo "  ... and $((total_changes - 20)) more files"
    fi
    echo ""

    # Stage and commit
    git add -A
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    git commit -m "${COMMIT_MSG} (${timestamp})" || {
        echo -e "${RED}Commit failed${NC}"
        return 1
    }

    echo -e "${GREEN}Backup committed successfully${NC}"

    # Show recent backups
    echo ""
    echo -e "${BLUE}Recent backups:${NC}"
    git log --oneline -5
}

show_history() {
    if [ ! -d "$CONFIG_DIR/.git" ]; then
        echo -e "${RED}No git repository in /config${NC}"
        return 1
    fi

    cd "$CONFIG_DIR"
    echo -e "${BLUE}Backup history:${NC}"
    git log --oneline -20
}

show_diff() {
    if [ ! -d "$CONFIG_DIR/.git" ]; then
        echo -e "${RED}No git repository in /config${NC}"
        return 1
    fi

    cd "$CONFIG_DIR"
    local ref="${1:-HEAD~1}"
    echo -e "${BLUE}Changes since ${ref}:${NC}"
    git diff "$ref" --stat
}

restore_file() {
    local file="$1"
    local ref="${2:-HEAD~1}"

    if [ ! -d "$CONFIG_DIR/.git" ]; then
        echo -e "${RED}No git repository in /config${NC}"
        return 1
    fi

    if [ -z "$file" ]; then
        echo -e "${RED}Usage: ha-backup restore <file> [commit-ref]${NC}"
        return 1
    fi

    cd "$CONFIG_DIR"
    echo -e "${YELLOW}Restoring ${file} from ${ref}...${NC}"
    git checkout "$ref" -- "$file"
    echo -e "${GREEN}Restored ${file}${NC}"
}

show_help() {
    echo -e "${BLUE}ha-backup${NC} - Git-based config backup for Home Assistant"
    echo ""
    echo "Usage:"
    echo "  ha-backup                     Create a backup with default message"
    echo "  ha-backup \"message\"           Create a backup with custom message"
    echo "  ha-backup history             Show backup history"
    echo "  ha-backup diff [ref]          Show changes since ref (default: HEAD~1)"
    echo "  ha-backup restore <file> [ref] Restore a file from a previous backup"
    echo "  ha-backup help                Show this help message"
    echo ""
    echo "Examples:"
    echo "  ha-backup \"Updated living room automations\""
    echo "  ha-backup history"
    echo "  ha-backup diff HEAD~3"
    echo "  ha-backup restore automations.yaml HEAD~1"
}

# Main
case "${1:-}" in
    history|log)
        show_history
        ;;
    diff)
        shift
        show_diff "$@"
        ;;
    restore)
        shift
        restore_file "$@"
        ;;
    help|--help|-h)
        show_help
        ;;
    *)
        do_backup
        ;;
esac
