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
    [essentialsx_chat]="essentialsxchat"
    [luckperms]="luckperms"
    [worldedit]="worldedit"
    [worldguard]="worldguard"
    [coreprotect]="coreprotect"
    [multiverse_core]="multiverse-core"
    [dynmap]="dynmap"
    [bluemap]="bluemap"
    [spark]="spark"
    [simple_voice_chat]="simple-voice-chat"
)

# Loader filter: prefer Paper-family loaders. Modrinth tags vary, so we
# accept any of paper/spigot/purpur/folia. The API supports facets but
# its loader-filter syntax is finicky in shell quoting; instead we filter
# client-side from the unfiltered version list, which is also more
# resilient to Modrinth schema tweaks.
PAPER_LOADERS_REGEX='^(paper|spigot|purpur|folia)$'

resolve_url() {
    local slug="$1"
    local versions
    versions=$(curl -fsSL --max-time 30 \
        "https://api.modrinth.com/v2/project/${slug}/version" 2>/dev/null) \
        || { warn "Modrinth lookup failed for ${slug}"; return 1; }

    # Pick the first version that lists at least one Paper-family loader
    # AND has a primary file with a URL. .files[] is sorted by Modrinth
    # with the primary jar first, so .files[0] is the right pick.
    printf '%s' "${versions}" | jq -r --arg loaders "${PAPER_LOADERS_REGEX}" '
        [ .[] | select(any(.loaders[]; test($loaders))) ][0]
        | .files[0].url // empty
    '
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
