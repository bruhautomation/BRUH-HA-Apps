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
    # HA and its ecosystem use custom tags (!secret, !include, !input,
    # ESPHome's !lambda, ...) that plain safe_load rejects — accept ANY
    # unknown tag via a catch-all multi-constructor, since /config sweeps
    # also walk ESPHome/other tools' files and this is a syntax check,
    # not a schema check.
    LAST_YAML_ERROR=$(python3 -c "
import sys, yaml

class HALoader(yaml.SafeLoader):
    pass

def _stub(loader, tag_suffix, node):
    return None

HALoader.add_multi_constructor('', _stub)

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
    # The endpoint is check_config (POST /api/config/core/check is a 404,
    # whose HTML body then breaks jq — which set -e turns into a silent
    # mid-function death). Check the HTTP status before parsing.
    local http_code body_file result
    body_file=$(mktemp)
    http_code=$(curl -s -o "$body_file" -w "%{http_code}" -X POST \
        -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" \
        -H "Content-Type: application/json" \
        "http://supervisor/core/api/config/core/check_config" 2>/dev/null) || http_code="000"
    result=$(cat "$body_file" 2>/dev/null)
    rm -f "$body_file"

    if [ "$http_code" != "200" ]; then
        echo -e "${RED}Config check API call failed (HTTP ${http_code})${NC}"
        if [ -n "$result" ]; then
            echo "$result" | head -c 300
            echo ""
        fi
        return 1
    fi

    local valid errors
    valid=$(echo "$result" | jq -r '.result // "unknown"' 2>/dev/null) || valid="unknown"
    errors=$(echo "$result" | jq -r '.errors // empty' 2>/dev/null) || errors=""

    if [ "$valid" = "valid" ]; then
        echo -e "${GREEN}Home Assistant configuration is valid${NC}"
        return 0
    else
        echo -e "${RED}Home Assistant configuration has errors:${NC}"
        if [ -n "$errors" ] && [ "$errors" != "null" ]; then
            echo "$errors"
        else
            echo "$result"
        fi
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
        # Don't let a syntax failure (return 1 + set -e) abort before the
        # API check runs — collect both results, then exit.
        rc=0
        validate_directory "$CONFIG_DIR" || rc=1
        echo ""
        validate_ha_config || rc=1
        exit $rc
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
