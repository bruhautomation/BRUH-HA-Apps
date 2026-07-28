#!/bin/bash
# ============================================================================
# popular-plugins.sh
# ----------------------------------------------------------------------------
# Read the `install_<name>` add-on options exported as `INSTALL_<NAME>`
# environment variables, resolve each enabled plugin to the latest stable
# Paper-compatible jar via the Modrinth API, and install them through the
# existing install-plugin.sh helper.
#
# Why Modrinth: it has a stable JSON API, all our curated plugins are
# published there, and `versions[].files[].url` resolves to a direct CDN
# download we can hand to curl without User-Agent gymnastics. Hangar (the
# Paper marketplace) and BukkitDev are an option for plugins not on
# Modrinth, but the curated set here is intentionally Modrinth-only so
# we have a single resolution path that's predictable and testable.
#
# The set is small on purpose. Browse marketplaces for anything not in
# the list and add it via the `plugins:` URL list:
#   - Modrinth: https://modrinth.com/plugins
#   - Hangar:   https://hangar.papermc.io
#   - SpigotMC: https://www.spigotmc.org/resources/categories/spigot.4/
# ============================================================================

set -uo pipefail

SCRIPTS_DIR="${SCRIPTS_DIR:-/opt/bruh-mc/scripts}"

log()  { printf '[popular-plugins] %s\n' "$*" >&2; }
warn() { printf '[popular-plugins] WARN: %s\n' "$*" >&2; }

# ----------------------------------------------------------------------------
# Curated plugin -> Modrinth slug mapping. Add entries here as the curated
# list grows. Each `install_<key>: true` add-on option triggers an install
# of the corresponding slug.
# ----------------------------------------------------------------------------
declare -A PLUGIN_SLUGS=(
    [essentialsx]="essentialsx"
    # NOTE: the chat module's Modrinth slug is essentialsx-chat-module —
    # "essentialsxchat" does not exist and 404s on every resolution.
    [essentialsx_chat]="essentialsx-chat-module"
    [luckperms]="luckperms"
    [worldedit]="worldedit"
    [coreprotect]="coreprotect"
    [griefprevention]="griefprevention"
    [mcmmo]="mcmmo"
    [chestsort]="chestsort"
    [veinminer]="veinminer"
    [spark]="spark"
    # ViaVersion bridges newer Java/Bedrock clients (e.g. 26.1) to an
    # older server (e.g. Paper 1.21.11) — the fix for "Outdated server!"
    # / "This server does not support Java Edition X.Y" kicks during
    # the gap between Mojang shipping a new MC release and Paper
    # publishing the matching build. ViaBackwards covers the reverse.
    [viaversion]="viaversion"
    [viabackwards]="viabackwards"
)

# Dependency map: enabling the key auto-enables the value. The user shouldn't
# need to remember that EssentialsX Chat is dead without EssentialsX, or that
# ViaBackwards refuses to load without ViaVersion.
declare -A PLUGIN_DEPS=(
    [essentialsx_chat]="essentialsx"
    [viabackwards]="viaversion"
)

# Auto-enable any plugin whose dependent is on. Logs a one-line notice the
# first time it kicks in so the operator knows why they got an "extra" plugin.
for dependent in "${!PLUGIN_DEPS[@]}"; do
    dep="${PLUGIN_DEPS[${dependent}]}"
    dependent_var="INSTALL_$(echo "${dependent}" | tr '[:lower:]' '[:upper:]')"
    dep_var="INSTALL_$(echo "${dep}" | tr '[:lower:]' '[:upper:]')"
    if [ "${!dependent_var:-false}" = "true" ] && [ "${!dep_var:-false}" != "true" ]; then
        log "Auto-enabling ${dep} (required by ${dependent})"
        printf -v "${dep_var}" '%s' "true"
        export "${dep_var?}"
    fi
done

# Slug-pattern map for the "skip if user already added this via plugins: URL
# list" check. Match jars whose filename starts with any of these patterns
# (case-insensitive). install_plugin.sh has already run before us, so any
# user-listed jars are on disk in plugins/.
declare -A PLUGIN_PATTERNS=(
    [essentialsx]="essentialsx essentials"
    [essentialsx_chat]="essentialsxchat"
    [luckperms]="luckperms"
    [worldedit]="worldedit"
    [coreprotect]="coreprotect"
    [griefprevention]="griefprevention"
    [mcmmo]="mcmmo"
    [chestsort]="chestsort"
    [veinminer]="veinminer"
    [spark]="spark"
    [viaversion]="viaversion"
    [viabackwards]="viabackwards"
)

PLUGINS_DIR="${PLUGINS_DIR:-${MC_SERVER_DIR:-/config/minecraft}/plugins}"

# Returns 0 if a jar matching any of `$2`-listed patterns already exists in
# PLUGINS_DIR (so the user supplied this plugin via the `plugins:` URL list).
user_supplied_already() {
    local patterns="$1" pat
    [ -d "${PLUGINS_DIR}" ] || return 1
    for pat in ${patterns}; do
        # shellcheck disable=SC2010
        ls "${PLUGINS_DIR}" 2>/dev/null \
            | grep -i -E "^${pat}.*\.jar$" -q && return 0
    done
    return 1
}

# Loader filter: prefer Paper-family loaders. Modrinth tags vary, so we
# accept any of paper/spigot/purpur/folia. The API supports facets but
# its loader-filter syntax is finicky in shell quoting; instead we filter
# client-side from the unfiltered version list, which is also more
# resilient to Modrinth schema tweaks.
PAPER_LOADERS_REGEX='^(paper|spigot|purpur|folia)$'

# The Minecraft version the installed server.jar actually runs, written by
# download-server.sh (which runs before us). Resolution MUST filter on it:
# Modrinth lists versions newest-first, so the unfiltered pick on e.g. a
# 1.20.1 server is a jar built for the current MC release, which Paper then
# refuses to load ("Unsupported API version 1.21.4").
SERVER_META="${SERVER_META:-${MC_SERVER_DIR:-/config/minecraft}/.server-meta.json}"
MC_GAME_VERSION=""
if [ -f "${SERVER_META}" ]; then
    MC_GAME_VERSION=$(jq -r '.version // empty' < "${SERVER_META}" 2>/dev/null) || MC_GAME_VERSION=""
fi
if [ -n "${MC_GAME_VERSION}" ]; then
    log "Filtering plugin builds for Minecraft ${MC_GAME_VERSION}"
else
    warn "Server version unknown (no ${SERVER_META}); installing latest plugin builds unfiltered"
fi

resolve_url() {
    local slug="$1"
    local versions
    versions=$(curl -fsSL --max-time 30 \
        "https://api.modrinth.com/v2/project/${slug}/version" 2>/dev/null) \
        || { warn "Modrinth lookup failed for ${slug}"; return 1; }

    # Pick the first version that lists at least one Paper-family loader,
    # supports the server's MC version (when known), AND has a primary file
    # with a URL. Prefer release-channel builds over alpha/beta when any
    # release matches. .files[] is sorted by Modrinth with the primary jar
    # first, so .files[0] is the right pick.
    local url
    url=$(printf '%s' "${versions}" | jq -r \
        --arg loaders "${PAPER_LOADERS_REGEX}" --arg mc "${MC_GAME_VERSION}" '
        [ .[] | select(any(.loaders[]; test($loaders)))
              | select($mc == "" or (.game_versions | index($mc))) ]
        | (map(select(.version_type == "release"))) as $releases
        | (if ($releases | length) > 0 then $releases else . end)
        | .[0].files[0].url // empty
    ')
    if [ -z "${url}" ] && [ -n "${MC_GAME_VERSION}" ]; then
        # Distinguish "no compatible build" from a lookup failure so the
        # operator knows the plugin exists but doesn't support this server.
        warn "No build of ${slug} supports Minecraft ${MC_GAME_VERSION}; not installing an incompatible jar"
        return 1
    fi
    printf '%s' "${url}"
}

# ----------------------------------------------------------------------------
# Iterate the curated list. For each enabled plugin, resolve a URL and
# hand it to install-plugin.sh (which handles If-Modified-Since caching,
# ZIP-magic-byte validation, etc.). Per-plugin failures are logged but
# never abort the loop — same posture as the existing `plugins:` list
# install path in run.sh.
# ----------------------------------------------------------------------------
installed=0
skipped=0
failed=0

for name in "${!PLUGIN_SLUGS[@]}"; do
    var="INSTALL_$(echo "${name}" | tr '[:lower:]' '[:upper:]')"
    enabled="${!var:-false}"
    if [ "${enabled}" != "true" ]; then
        skipped=$((skipped + 1))
        continue
    fi

    # Proactive de-dupe: if the user already supplied this plugin via the
    # `plugins:` URL list (its jar is on disk by now — install_plugins ran
    # before us), skip the popular install so we don't download a second
    # copy that auto_quarantine would just shove into .quarantine/.
    patterns="${PLUGIN_PATTERNS[${name}]:-${name}}"
    if user_supplied_already "${patterns}"; then
        log "Skipping ${name}: already supplied via plugins: URL list"
        skipped=$((skipped + 1))
        continue
    fi

    slug="${PLUGIN_SLUGS[${name}]}"
    log "Resolving ${name} (modrinth: ${slug})"

    url=$(resolve_url "${slug}")
    if [ -z "${url:-}" ]; then
        warn "Could not resolve a Paper-compatible jar for ${name}; skipping"
        failed=$((failed + 1))
        continue
    fi

    if "${SCRIPTS_DIR}/install-plugin.sh" "${url}" ""; then
        installed=$((installed + 1))
    else
        warn "${name} install failed — continuing"
        failed=$((failed + 1))
    fi
done

log "Done: ${installed} installed, ${skipped} skipped, ${failed} failed"
exit 0
