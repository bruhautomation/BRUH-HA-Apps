#!/usr/bin/with-contenv bashio

# ha-yaml-check - Validate Home Assistant YAML configuration files
# Usage: ha-yaml-check [file|directory]

set -e

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

CONFIG_DIR="/config"

# Holds the parser diagnostic for the last failed file so callers can show it.
LAST_YAML_ERROR=""

validate_yaml_syntax() {
    local file="$1"

    # Use Python for reliable YAML parsing.
    # Pass filename via sys.argv to avoid shell injection through filenames.
    # Home Assistant YAML uses custom tags (!secret, !include, !env_var,
    # !input, !include_dir_*) that plain safe_load rejects — register stub
    # constructors so idiomatic HA config files validate instead of
    # false-failing on every tagged line.
    LAST_YAML_ERROR=$(python3 -c "
import sys, yaml

class HALoader(yaml.SafeLoader):
    pass

def _stub(loader, node):
    return None

for tag in ('!secret', '!env_var', '!input', '!include',
            '!include_dir_list', '!include_dir_named',
            '!include_dir_merge_list', '!include_dir_merge_named'):
    HALoader.add_constructor(tag, _stub)

try:
    with open(sys.argv[1], 'r') as f:
        yaml.load(f, Loader=HALoader)
    sys.exit(0)
except yaml.YAMLError as e:
    print(f'YAML error: {e}', file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f'Error: {e}', file=sys.stderr)
    sys.exit(1)
" "$file" 2>&1 >/dev/null) && return 0 || return 1
}

validate_file() {
    local file="$1"
    local basename
    basename=$(basename "$file")

    # Skip non-YAML files
    case "$basename" in
        *.yaml|*.yml) ;;
        *) return 0 ;;
    esac

    # Skip secrets
    if [ "$basename" = "secrets.yaml" ]; then
        echo -e "  ${YELLOW}SKIP${NC} $file (secrets)"
        return 0
    fi

    if validate_yaml_syntax "$file"; then
        echo -e "  ${GREEN}OK${NC}   $file"
        return 0
    else
        echo -e "  ${RED}FAIL${NC} $file"
        # Show the parser diagnostic — a bare FAIL is not actionable.
        if [ -n "$LAST_YAML_ERROR" ]; then
            echo "$LAST_YAML_ERROR" | sed 's/^/         /'
        fi
        return 1
    fi
}

validate_directory() {
    local dir="${1:-$CONFIG_DIR}"
    local errors=0
    local checked=0

    echo -e "${BLUE}Validating YAML files in ${dir}...${NC}"
    echo ""

    # Find all YAML files (non-recursive in hidden dirs).
    # NOTE: increments must use var=$((var+1)); ((var++)) returns exit
    # status 1 when the pre-increment value is 0, which kills the whole
    # script under `set -e` after the very first file.
    while IFS= read -r -d '' file; do
        validate_file "$file" || errors=$((errors+1))
        checked=$((checked+1))
    done < <(find "$dir" -maxdepth 2 \( -name "*.yaml" -o -name "*.yml" \) | sort | tr '\n' '\0')

    echo ""
    echo -e "${BLUE}Checked ${checked} files, ${errors} error(s)${NC}"

    if [ "$errors" -gt 0 ]; then
        echo -e "${RED}YAML validation failed${NC}"
        return 1
    else
        echo -e "${GREEN}All YAML files valid${NC}"
        return 0
    fi
}

# Also check HA config via API
validate_ha_config() {
    echo -e "${BLUE}Checking Home Assistant configuration via API...${NC}"
    local result
    result=$(curl -s -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "http://supervisor/core/api/config/core/check" 2>/dev/null)

    local valid
    valid=$(echo "$result" | jq -r '.result // "unknown"' 2>/dev/null)
    local errors
    errors=$(echo "$result" | jq -r '.errors // empty' 2>/dev/null)

    if [ "$valid" = "valid" ] || [ -z "$errors" ] || [ "$errors" = "null" ]; then
        echo -e "${GREEN}Home Assistant configuration is valid${NC}"
        return 0
    else
        echo -e "${RED}Home Assistant configuration has errors:${NC}"
        echo "$errors"
        return 1
    fi
}

show_help() {
    echo -e "${BLUE}ha-yaml-check${NC} - Validate YAML configuration files"
    echo ""
    echo "Usage:"
    echo "  ha-yaml-check                 Validate all YAML in /config"
    echo "  ha-yaml-check <file>          Validate a specific file"
    echo "  ha-yaml-check <directory>     Validate all YAML in directory"
    echo "  ha-yaml-check --ha            Check via HA API (runtime check)"
    echo "  ha-yaml-check --all           Both YAML syntax and HA API check"
    echo ""
    echo "Examples:"
    echo "  ha-yaml-check"
    echo "  ha-yaml-check automations.yaml"
    echo "  ha-yaml-check --all"
}

# Main
case "${1:-}" in
    --ha|--api)
        validate_ha_config
        ;;
    --all)
        validate_directory "$CONFIG_DIR"
        echo ""
        validate_ha_config
        ;;
    help|--help|-h)
        show_help
        ;;
    "")
        validate_directory "$CONFIG_DIR"
        ;;
    *)
        if [ -f "$1" ]; then
            validate_file "$1"
        elif [ -d "$1" ]; then
            validate_directory "$1"
        else
            # Try relative to /config
            if [ -f "$CONFIG_DIR/$1" ]; then
                validate_file "$CONFIG_DIR/$1"
            else
                echo -e "${RED}Not found: $1${NC}"
                exit 1
            fi
        fi
        ;;
esac
