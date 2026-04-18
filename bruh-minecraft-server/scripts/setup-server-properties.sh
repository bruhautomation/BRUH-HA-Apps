#!/bin/bash
# ============================================================================
# setup-server-properties.sh
# ----------------------------------------------------------------------------
# Render /config/minecraft/server.properties from the add-on options.
# - Preserves unknown keys on subsequent runs so operators can hand-edit
#   exotic settings without losing them on reload.
# - Always (re)writes the managed keys so the UI is the source of truth.
# ============================================================================

set -euo pipefail

MC_SERVER_DIR="${MC_SERVER_DIR:-/config/minecraft}"
PROPS="${MC_SERVER_DIR}/server.properties"

declare -A MANAGED=(
    [motd]="${MOTD:-A BRUH Minecraft Server}"
    [difficulty]="${DIFFICULTY:-normal}"
    [gamemode]="${GAMEMODE:-survival}"
    [max-players]="${MAX_PLAYERS:-20}"
    [view-distance]="${VIEW_DISTANCE:-10}"
    [simulation-distance]="${SIM_DISTANCE:-10}"
    [online-mode]="${ONLINE_MODE:-true}"
    [pvp]="${PVP:-true}"
    [hardcore]="${HARDCORE:-false}"
    [allow-flight]="${ALLOW_FLIGHT:-false}"
    [white-list]="${WHITE_LIST:-false}"
    [enforce-whitelist]="${WHITE_LIST:-false}"
    [spawn-protection]="${SPAWN_PROTECTION:-16}"
    [level-name]="${LEVEL_NAME:-world}"
    [level-seed]="${LEVEL_SEED:-}"
    [level-type]="${LEVEL_TYPE:-minecraft:normal}"
    [enable-command-block]="${ENABLE_COMMAND_BLOCK:-false}"
    [op-permission-level]="${OP_PERMISSION_LEVEL:-4}"
    [server-port]="25565"
    [query.port]="25565"
    [enable-rcon]="true"
    [rcon.port]="25575"
    [rcon.password]="${RCON_PASSWORD}"
    [broadcast-rcon-to-ops]="true"
    [enable-query]="true"
    [enable-status]="true"
    [sync-chunk-writes]="true"
    [function-permission-level]="2"
    [max-tick-time]="60000"
    [use-native-transport]="true"
    [network-compression-threshold]="256"
    [max-world-size]="29999984"
    [spawn-monsters]="true"
    [spawn-animals]="true"
    [spawn-npcs]="true"
    [generate-structures]="true"
    [allow-nether]="true"
    [entity-broadcast-range-percentage]="100"
    [enable-jmx-monitoring]="false"
    [prevent-proxy-connections]="false"
)

# Load any existing properties into a map so we can preserve hand-edited keys
declare -A CURRENT
if [ -f "${PROPS}" ]; then
    while IFS= read -r line || [ -n "${line}" ]; do
        case "${line}" in
            \#*|"") continue ;;
            *=*)
                key="${line%%=*}"
                value="${line#*=}"
                CURRENT["${key}"]="${value}"
                ;;
        esac
    done < "${PROPS}"
fi

# Merge managed keys into the current set
for k in "${!MANAGED[@]}"; do
    CURRENT["${k}"]="${MANAGED[$k]}"
done

{
    printf '# server.properties — managed by BRUH Minecraft Server add-on\n'
    printf '# Hand-edited keys not managed by the UI are preserved on restart.\n'
    printf '# Last rendered: %s\n' "$(date -Iseconds)"
    for k in $(printf '%s\n' "${!CURRENT[@]}" | sort); do
        printf '%s=%s\n' "${k}" "${CURRENT[$k]}"
    done
} > "${PROPS}.tmp"

mv "${PROPS}.tmp" "${PROPS}"
chmod 600 "${PROPS}"
chown minecraft:minecraft "${PROPS}" 2>/dev/null || true
