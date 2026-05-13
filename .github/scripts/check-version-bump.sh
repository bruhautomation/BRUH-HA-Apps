#!/bin/bash
# Verify that if any version-relevant files in an addon directory changed
# between $1 (base ref) and HEAD, the addon's version in config.yaml has
# also bumped.
#
# Background: Home Assistant only pulls a new add-on image when
# `version:` in `config.yaml` changes. Shipping a fix without bumping
# the version means users don't get the update. This script enforces
# the bump on every PR that touches addon code.
#
# Usage: check-version-bump.sh <base-ref> <addon-dir>
#   base-ref:  git ref of the base branch (e.g. origin/main)
#   addon-dir: path to the addon (e.g. bruh-claude-terminal)
#
# Exit codes:
#   0 — no version-relevant changes, OR version bumped
#   1 — version-relevant changes without a version bump
#   2 — usage / parse error

set -e

base="${1:-}"
dir="${2:-}"
if [ -z "$base" ] || [ -z "$dir" ]; then
    echo "usage: $0 <base-ref> <addon-dir>" >&2
    exit 2
fi

if [ ! -d "$dir" ]; then
    echo "addon dir does not exist: $dir" >&2
    exit 2
fi

# Files inside the addon dir that DON'T require a version bump when
# they change. CHANGELOG.md is bumped *as part of* the version change so
# requiring a bump to change CHANGELOG would be circular; README/DOCS
# are pure documentation. When in doubt, force a bump — contributors
# can always make it a no-op patch.
excluded_basenames=(CHANGELOG.md README.md DOCS.md)

# Build a list of changed files inside $dir that are NOT in the exclude list.
mapfile -t changed < <(
    git diff --name-only "$base"...HEAD -- "$dir/" |
        while IFS= read -r f; do
            base_name=$(basename "$f")
            skip=0
            for e in "${excluded_basenames[@]}"; do
                if [ "$base_name" = "$e" ]; then
                    skip=1
                    break
                fi
            done
            if [ $skip -eq 0 ]; then
                printf '%s\n' "$f"
            fi
        done
)

if [ "${#changed[@]}" -eq 0 ]; then
    echo "✓ No version-relevant changes in $dir; bump not required."
    exit 0
fi

echo "Version-relevant changes detected in $dir:"
printf '  %s\n' "${changed[@]}"
echo

# Parse the version from config.yaml at base and head. The format is a
# YAML scalar `version: "x.y.z"` on its own line. We pull it via grep/sed
# rather than parsing YAML to keep this script dependency-free.
parse_version() {
    grep -E '^version:' | head -1 | sed 's/.*"\([^"]*\)".*/\1/'
}

# `git show` for a path that doesn't exist on base returns nonzero — we
# silence that with `|| true` and let the empty version fall through to
# the "different" branch (a brand-new addon must declare a version).
base_version=$(git show "$base:$dir/config.yaml" 2>/dev/null | parse_version || true)
head_version=$(parse_version <"$dir/config.yaml" || true)

echo "Base version: ${base_version:-<not present>}"
echo "Head version: ${head_version:-<not parsed>}"

if [ -z "$head_version" ]; then
    echo "::error file=$dir/config.yaml::Could not parse version from $dir/config.yaml"
    exit 1
fi

if [ "$base_version" = "$head_version" ]; then
    echo
    echo "::error file=$dir/config.yaml::Addon files changed but version is unchanged ($head_version)."
    echo "::error::Bump the version in $dir/config.yaml (and matching custom_components/.../manifest.json)"
    echo "::error::so Home Assistant picks up the update."
    exit 1
fi

echo "✓ Version bumped: $base_version → $head_version"
exit 0
