#!/bin/bash

# ha — Home Assistant operations from inside brAIn.
#
# One command in place of the old ha-* script pile. brAIn's own faculties
# (memory, learning, undo) live under the sibling `brain` command.
#
# Usage:
#   ha log [args]          Tail / filter the HA log
#   ha reload [domain]     Reload HA configuration
#   ha check [path]        Validate YAML
#   ha context             Regenerate /config/CLAUDE.md
#   ha entity <action>     Inspect and control entities
#   ha service <action>    Call services
#   ha addon <action>      Manage add-ons
#   ha notify <args>       Send a notification
#   ha share <args>        Share a file / message with other BRUH add-ons
#   ha login               Authenticate the shared Claude credential
#   ha help                This help

set -uo pipefail

SCRIPTS_DIR="${BRAIN_SCRIPTS_DIR:-/opt/scripts}"

CYAN='\033[0;36m'
RED='\033[0;31m'
NC='\033[0m'

usage() {
    cat << 'EOF'
ha — Home Assistant operations

Usage:
  ha log [args]            Tail / filter the Home Assistant log
  ha reload [domain]       Reload configuration (automations, scripts, ...)
  ha check [path]          Validate YAML
  ha context               Regenerate /config/CLAUDE.md home context
  ha entity <action>       Inspect and control entities
  ha service <action>      Call Home Assistant services
  ha addon <action>        Manage add-ons
  ha notify <args>         Send a notification
  ha share <args>          Share with other BRUH add-ons
  ha login                 Authenticate the shared Claude credential
  ha help                  This help

brAIn's memory and learning live under `brain` (brain memory, brain learn, ...).
EOF
    exit "${1:-0}"
}

delegate() {
    local script="$1"; shift
    local path="${SCRIPTS_DIR}/${script}"
    if [ ! -f "$path" ]; then
        echo -e "${RED}Error: ${script} is not installed in this image${NC}" >&2
        exit 1
    fi
    exec bash "$path" "$@"
}

[ $# -lt 1 ] && usage

action="$1"
shift

case "$action" in
    log)        delegate ha-log.sh "$@" ;;
    reload)     delegate ha-reload.sh "$@" ;;
    check|yaml) delegate ha-yaml-check.sh "$@" ;;
    context)    delegate ha-context-gen.sh "$@" ;;
    entity)     delegate ha-entity.sh "$@" ;;
    service)    delegate ha-service.sh "$@" ;;
    addon)      delegate ha-addon.sh "$@" ;;
    notify)     delegate ha-notify.sh "$@" ;;
    share)      delegate ha-share.sh "$@" ;;
    login)      delegate ha-share-login.sh "$@" ;;
    memory|learn|ask|undo|doctor)
        echo -e "${RED}'${action}' is a brAIn faculty, not a Home Assistant operation.${NC}" >&2
        echo -e "Run: ${CYAN}brain ${action}${NC}" >&2
        exit 1
        ;;
    help|--help|-h) usage ;;
    *)
        echo -e "${RED}Unknown subcommand: ${action}${NC}" >&2
        usage 1
        ;;
esac
