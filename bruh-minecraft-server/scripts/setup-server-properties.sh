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

# Secure-profile enforcement only makes sense when the server is authenticating
# players against Mojang (online-mode=true). With online-mode=false nobody has
# a signed profile, and leaving enforce-secure-profile=true bounces every
# client with "You are not permitted to join due to the enforce-secure-profile
# setting." Auto-force it false in offline mode regardless of the raw option.
ONLINE_MODE_VALUE="${ONLINE_MODE:-true}"
ENFORCE_SECURE_PROFILE_VALUE="${ENFORCE_SECURE_PROFILE:-false}"
if [ "${ONLINE_MODE_VALUE}" != "true" ]; then
    ENFORCE_SECURE_PROFILE_VALUE="false"
fi

# Hardcore mode forces every player into survival regardless of `gamemode`.
# Warn loudly if the operator asked for a non-survival gamemode AND hardcore,
# so a "creative world that stays survival" isn't a silent mystery.
GAMEMODE_VALUE="${GAMEMODE:-survival}"
if [ "${HARDCORE:-false}" = "true" ] && [ "${GAMEMODE_VALUE}" != "survival" ]; then
    printf '[setup-server-properties] WARNING: hardcore=true forces survival; gamemode=%s will be ignored by Minecraft.\n' \
        "${GAMEMODE_VALUE}" >&2
fi

# allow_cheats is a convenience knob: flip it on and the "cheat" commands
# (/gamemode, /give, /tp, /summon, /fill, …) will actually be usable for OP'd
# players. Translate it into the two underlying server.properties keys.
ALLOW_CHEATS_VALUE="${ALLOW_CHEATS:-false}"
ENABLE_COMMAND_BLOCK_VALUE="${ENABLE_COMMAND_BLOCK:-false}"
OP_PERMISSION_LEVEL_VALUE="${OP_PERMISSION_LEVEL:-4}"
if [ "${ALLOW_CHEATS_VALUE}" = "true" ]; then
    ENABLE_COMMAND_BLOCK_VALUE="true"
    if [ "${OP_PERMISSION_LEVEL_VALUE}" -lt 2 ] 2>/dev/null; then
        OP_PERMISSION_LEVEL_VALUE=2
    fi
fi

declare -A MANAGED=(
    [motd]="${MOTD:-A BRUH Minecraft Server}"
    [difficulty]="${DIFFICULTY:-normal}"
    [gamemode]="${GAMEMODE:-survival}"
    # force-gamemode puts returning players back into the configured gamemode
    # on every join. Without it, Minecraft only applies `gamemode` to players
    # who have never joined — so a world flipped to creative kept loading as
    # survival for everyone who'd already played. Default true.
    [force-gamemode]="${FORCE_GAMEMODE:-true}"
    [max-players]="${MAX_PLAYERS:-20}"
    [view-distance]="${VIEW_DISTANCE:-10}"
    [simulation-distance]="${SIM_DISTANCE:-10}"
    [online-mode]="${ONLINE_MODE_VALUE}"
    [enforce-secure-profile]="${ENFORCE_SECURE_PROFILE_VALUE}"
    [pvp]="${PVP:-true}"
    [hardcore]="${HARDCORE:-false}"
    [allow-flight]="${ALLOW_FLIGHT:-false}"
    [white-list]="${WHITE_LIST:-false}"
    [enforce-whitelist]="${WHITE_LIST:-false}"
    [spawn-protection]="${SPAWN_PROTECTION:-16}"
    [level-name]="${LEVEL_NAME:-world}"
    [level-type]="${LEVEL_TYPE:-minecraft:normal}"
    # Experimental feature flags. Mojang gates new/experimental content —
    # and the game rules that come with it — behind "feature packs" that the
    # server enables at world-generation time via initial-enabled-packs
    # (comma-separated, e.g. "vanilla,minecart_improvements,redstone_experiments").
    # Must always include "vanilla" or the base game pack is disabled, so the
    # default falls back to "vanilla" when the option is blank.
    [initial-enabled-packs]="${INITIAL_ENABLED_PACKS:-vanilla}"
    [initial-disabled-packs]="${INITIAL_DISABLED_PACKS:-}"
    [enable-command-block]="${ENABLE_COMMAND_BLOCK_VALUE}"
    [op-permission-level]="${OP_PERMISSION_LEVEL_VALUE}"
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
    [network-compression-threshold]="${NETWORK_COMPRESSION_THRESHOLD:-256}"
    [max-world-size]="${MAX_WORLD_SIZE:-29999984}"
    [spawn-monsters]="${SPAWN_MONSTERS:-true}"
    [spawn-animals]="${SPAWN_ANIMALS:-true}"
    [spawn-npcs]="${SPAWN_NPCS:-true}"
    [generate-structures]="${GENERATE_STRUCTURES:-true}"
    [allow-nether]="${ALLOW_NETHER:-true}"
    [entity-broadcast-range-percentage]="${ENTITY_BROADCAST_RANGE_PERCENTAGE:-100}"
    [enable-jmx-monitoring]="false"
    [prevent-proxy-connections]="${PREVENT_PROXY_CONNECTIONS:-false}"
    [hide-online-players]="${HIDE_ONLINE_PLAYERS:-false}"
    [connection-throttle]="${CONNECTION_THROTTLE_MS:-4000}"
    [player-idle-timeout]="${PLAYER_IDLE_TIMEOUT_MINUTES:-0}"
    [resource-pack]="${RESOURCE_PACK:-}"
    [resource-pack-sha1]="${RESOURCE_PACK_SHA1:-}"
    [require-resource-pack]="${REQUIRE_RESOURCE_PACK:-false}"
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

# level-seed is handled out-of-band so a per-world seed survives. When the
# global LEVEL_SEED option is set, it wins (managed). When it's blank, we
# DON'T overwrite a seed that world-manager staged into the profile's
# server.properties at create time — otherwise the seed typed into the
# panel's "Create world" form was silently discarded on first boot and the
# world generated random terrain instead.
if [ -n "${LEVEL_SEED:-}" ]; then
    CURRENT["level-seed"]="${LEVEL_SEED}"
elif [ -z "${CURRENT[level-seed]:-}" ]; then
    CURRENT["level-seed"]=""
fi

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
