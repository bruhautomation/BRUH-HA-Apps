#!/bin/bash
# Verify that an addon's CHANGELOG.md documents the version that
# config.yaml actually ships.
#
# Background: Home Assistant reads ONLY `version:` in `config.yaml` to
# decide what the store offers. A changelog entry announcing a release
# that config.yaml doesn't carry (forgotten bump, or bumped to a
# different number) means users read about "2.3.0" while the store still
# offers something older — and nothing fails. This script makes that
# mismatch a CI failure.
#
# Usage: check-changelog-version.sh <addon-dir>
#   addon-dir: path to the addon (e.g. bruh-claude-terminal)
#
# Exit codes:
#   0 — changelog's latest entry matches config.yaml's version
#   1 — mismatch, or version not parseable from either file
#   2 — usage / missing files

set -e

dir="${1:-}"
if [ -z "$dir" ]; then
    echo "usage: $0 <addon-dir>" >&2
    exit 2
fi

config="$dir/config.yaml"
changelog="$dir/CHANGELOG.md"

if [ ! -f "$config" ]; then
    echo "config does not exist: $config" >&2
    exit 2
fi
if [ ! -f "$changelog" ]; then
    echo "changelog does not exist: $changelog" >&2
    exit 2
fi

# Same dependency-free parse as check-version-bump.sh: a YAML scalar
# `version: "x.y.z"` on its own line.
config_version=$(grep -E '^version:' "$config" | head -1 | sed 's/.*"\([^"]*\)".*/\1/')

# Latest changelog entry = first `## <version>` heading. Accept the
# plain form (`## 2.3.0`) and Keep-a-Changelog variants (`## [2.3.0] -
# 2026-01-01`, `## v2.3.0`).
changelog_version=$(
    grep -m1 -E '^##[[:space:]]+\[?v?[0-9]+\.[0-9]+\.[0-9]+' "$changelog" |
        grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -1
) || true

echo "config.yaml version:     ${config_version:-<not parsed>}"
echo "CHANGELOG latest entry:  ${changelog_version:-<not parsed>}"

if [ -z "$config_version" ]; then
    echo "::error file=$config::Could not parse version from $config"
    exit 1
fi

if [ -z "$changelog_version" ]; then
    echo "::error file=$changelog::No version heading (## x.y.z) found in $changelog"
    exit 1
fi

if [ "$config_version" != "$changelog_version" ]; then
    echo
    echo "::error file=$changelog::CHANGELOG's latest entry ($changelog_version) doesn't match $config ($config_version)."
    echo "::error::Home Assistant ships whatever config.yaml says — a changelog announcing a different"
    echo "::error::version means users read about a release the store never offers."
    exit 1
fi

echo "✓ Changelog matches shipped version: $config_version"
exit 0
