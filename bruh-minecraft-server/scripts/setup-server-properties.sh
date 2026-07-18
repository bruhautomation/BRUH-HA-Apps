#!/bin/bash
# ============================================================================
# setup-server-properties.sh
# ----------------------------------------------------------------------------
# Maintain the ACTIVE world's server.properties.
#
# As of 1.8.0 gameplay settings are PER-WORLD: each world owns its own
# server.properties (gamemode, difficulty, world-gen, etc.), edited from the
# ingress panel. This script therefore:
#
#   * Always (re)writes the INFRA keys (RCON / query / ports / transport) —
#     these are container-level and must stay correct so the panel + HA can
#     talk to the server. They are NOT user-editable.
#   * SEEDS each gameplay key with a sensible default ONLY when it is absent
#     (a brand-new world). Existing values are PRESERVED untouched — that's
#     what lets a panel edit stick and lets a creative world and a survival
#     world keep different settings.
#   * Preserves any unknown / hand-edited keys.
#
# The add-on no longer renders gameplay from global options (there are none) —
# server.properties is the source of truth for the active world.
# ============================================================================

set -euo pipefail

MC_SERVER_DIR="${MC_SERVER_DIR:-/config/minecraft}"
PROPS="${MC_SERVER_DIR}/server.properties"

# Infra keys — always enforced from the container, never user-editable.
declare -A INFRA=(
    [server-port]="25565"
    [query.port]="25565"
    [enable-rcon]="true"
    [rcon.port]="25575"
    [rcon.password]="${RCON_PASSWORD:-}"
    [broadcast-rcon-to-ops]="true"
    [enable-query]="true"
    [enable-status]="true"
    [sync-chunk-writes]="true"
    [function-permission-level]="2"
    [max-tick-time]="60000"
    [use-native-transport]="true"
    [enable-jmx-monitoring]="false"
)

# Gameplay defaults — seeded ONLY when the key is absent from the world's
# existing server.properties. Edit these from the panel per world; they are
# never overwritten here once present.
declare -A DEFAULTS=(
    [motd]="A BRUH Minecraft"
    [difficulty]="normal"
    [gamemode]="survival"
    [force-gamemode]="true"
    [max-players]="20"
    [view-distance]="10"
    [simulation-distance]="10"
    [online-mode]="true"
    [enforce-secure-profile]="false"
    [pvp]="true"
    [hardcore]="false"
    [allow-flight]="false"
    [white-list]="false"
    [spawn-protection]="16"
    [level-name]="world"
    [level-seed]=""
    [level-type]="minecraft:normal"
    [initial-enabled-packs]="vanilla"
    [initial-disabled-packs]=""
    [allow-nether]="true"
    [generate-structures]="true"
    [spawn-monsters]="true"
    [spawn-animals]="true"
    [spawn-npcs]="true"
    [prevent-proxy-connections]="false"
    [hide-online-players]="false"
    [resource-pack]=""
    [resource-pack-sha1]=""
    [require-resource-pack]="false"
    [max-world-size]="29999984"
    [network-compression-threshold]="256"
    [entity-broadcast-range-percentage]="100"
    [enable-command-block]="false"
    [op-permission-level]="4"
    [connection-throttle]="4000"
    [player-idle-timeout]="0"
)

# Load existing properties so we can preserve everything already set.
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

# Seed gameplay defaults only where the key is not already present (a missing
# key, not merely an empty value — an explicit `resource-pack=` is preserved).
for k in "${!DEFAULTS[@]}"; do
    if [ -z "${CURRENT[$k]+set}" ]; then
        CURRENT["${k}"]="${DEFAULTS[$k]}"
    fi
done

# Infra keys always win.
for k in "${!INFRA[@]}"; do
    CURRENT["${k}"]="${INFRA[$k]}"
done

# enforce-whitelist always mirrors white-list — it has no independent meaning
# for this add-on, so it's derived rather than editable.
CURRENT["enforce-whitelist"]="${CURRENT[white-list]:-false}"

# Secure-profile enforcement only makes sense with online-mode=true. In
# offline mode nobody has a Mojang-signed profile, so enforce-secure-profile
# MUST be false or every client is kicked with "You are not permitted to join
# due to the enforce-secure-profile setting". Force it regardless of the
# stored value.
if [ "${CURRENT[online-mode]:-true}" != "true" ]; then
    CURRENT["enforce-secure-profile"]="false"
fi

# Hardcore forces survival regardless of gamemode — warn so a "creative world
# that stays survival" isn't a silent mystery.
if [ "${CURRENT[hardcore]:-false}" = "true" ] && [ "${CURRENT[gamemode]:-survival}" != "survival" ]; then
    printf '[setup-server-properties] WARNING: hardcore=true forces survival; gamemode=%s will be ignored by Minecraft.\n' \
        "${CURRENT[gamemode]}" >&2
fi

{
    printf '# server.properties — active world is the source of truth.\n'
    printf '# Gameplay keys are seeded once then preserved; edit them from the panel.\n'
    printf '# Infra keys (rcon/query/ports) are managed by the add-on.\n'
    printf '# Last rendered: %s\n' "$(date -Iseconds)"
    for k in $(printf '%s\n' "${!CURRENT[@]}" | sort); do
        # Strip any CR/LF from values defensively so a stray newline can't
        # inject extra server.properties lines.
        printf '%s=%s\n' "${k}" "${CURRENT[$k]//[$'\r\n']/}"
    done
} > "${PROPS}.tmp"

mv "${PROPS}.tmp" "${PROPS}"
chmod 600 "${PROPS}"
chown minecraft:minecraft "${PROPS}" 2>/dev/null || true
