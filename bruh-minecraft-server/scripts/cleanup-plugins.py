#!/usr/bin/env python3
"""Quarantine duplicate plugin jars before Paper sees them.

Plugin folders accumulate stale jars over time:

  * The user installed Multiverse-Core 5.6.2-pre at some point, then
    later 5.6.2 stable shipped via the popular-plugin auto-installer.
    Both jars now live in `plugins/` and Paper logs an "Ambiguous plugin
    name 'Multiverse-Core'" error on every boot. One copy gets disabled
    randomly.

  * A user typo (`MultiverseCore.jar` next to `multiverse-core.jar`)
    leaves the old copy behind when the canonical filename changes.

  * A plugin author renames their build artefact between versions
    (e.g. `EssentialsX-2.20.1.jar` -> `EssentialsX-2.21.2.jar`) and the
    older file just sits.

For each duplicate-name group, this script keeps the "best" jar and
moves the rest to `plugins/.quarantine/`. They're not deleted — the
user can restore one by moving it back, or delete the quarantine
folder when they're satisfied. A `QUARANTINE.md` log records every
move with timestamps.

"Best" is defined as:
  1. A jar without a pre-release marker (-pre, -snapshot, -rc, -beta,
     -alpha, -dev) in either its filename or its `version:` field
     beats one with a pre-release marker.
  2. Higher numeric semver wins.
  3. Newer file mtime wins (tiebreaker).

The script is intentionally read-only outside `plugins/` and exits
cleanly when no duplicates are found, so calling it on every boot is
safe and fast.

Environment variables:
  PLUGINS_DIR   defaults to /config/minecraft/plugins
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import time
import zipfile
from pathlib import Path
from typing import Optional

PLUGINS_DIR = Path(os.environ.get("PLUGINS_DIR", "/config/minecraft/plugins"))
QUARANTINE_DIR = PLUGINS_DIR / ".quarantine"

# Match common pre-release markers anywhere in a filename or version string.
# Word boundary at the start so "presence" doesn't match "pre".
PRE_RELEASE_RE = re.compile(
    r"(?:^|[\W_])(?:pre|snapshot|rc|beta|alpha|dev|nightly)(?:\d+)?(?:\W|$)",
    re.IGNORECASE,
)


def log(msg: str) -> None:
    print(f"[plugin-cleanup] {msg}", file=sys.stderr, flush=True)


def read_plugin_meta(jar_path: Path) -> Optional[tuple[str, str]]:
    """Return (name, version) from a plugin jar.

    Reads paper-plugin.yml first (Paper's modern format), then falls
    back to plugin.yml (the Bukkit/Spigot legacy format). Returns None
    if the jar is unreadable, isn't a plugin, or doesn't declare a name.
    """
    try:
        with zipfile.ZipFile(jar_path) as zf:
            for candidate in ("paper-plugin.yml", "plugin.yml"):
                try:
                    raw = zf.read(candidate).decode("utf-8", errors="replace")
                except KeyError:
                    continue
                # Tiny YAML parser — we only need top-level `name:` and
                # `version:` keys, so we don't need full YAML semantics
                # (and don't want to take a dependency on PyYAML).
                name = version = None
                for line in raw.splitlines():
                    line = line.split("#", 1)[0].rstrip()
                    if not line or line.startswith((" ", "\t")):
                        continue  # nested keys / continuations
                    m = re.match(
                        r"^(name|version)\s*:\s*[\"']?(.+?)[\"']?\s*$", line
                    )
                    if m:
                        if m.group(1) == "name" and name is None:
                            name = m.group(2).strip()
                        elif m.group(1) == "version" and version is None:
                            version = m.group(2).strip()
                if name:
                    return (name, version or "0")
    except (zipfile.BadZipFile, OSError):
        pass
    return None


def parse_semver(version: str) -> tuple[int, int, int, int, str]:
    """Coarse semver parse: (major, minor, patch, is_pre, suffix).

    `is_pre` is 0 for clean versions and 1 for anything with a
    suffix (so clean versions sort higher when we negate it).
    """
    v = version.lstrip("vV")
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?(?:[-+](.+))?", v)
    if not m:
        return (0, 0, 0, 1, version)
    major = int(m.group(1))
    minor = int(m.group(2))
    patch = int(m.group(3) or 0)
    suffix = m.group(4) or ""
    is_pre = 1 if suffix else 0
    return (major, minor, patch, is_pre, suffix)


def jar_score(jar_path: Path, version: str) -> tuple:
    """Sort key — higher tuple wins (i.e. the one we KEEP)."""
    semver = parse_semver(version)
    semver_key = (semver[0], semver[1], semver[2])
    is_release_version = -semver[3]  # release (0) > pre-release (-1)
    has_pre_in_filename = -1 if PRE_RELEASE_RE.search(jar_path.name) else 0
    mtime = jar_path.stat().st_mtime
    # Tuple ordering: clean filename > release version > higher semver > newer
    return (has_pre_in_filename, is_release_version, semver_key, mtime)


def quarantine(jar: Path) -> Path:
    """Move a jar into the quarantine folder. Returns the destination path."""
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    dest = QUARANTINE_DIR / jar.name
    if dest.exists():
        # Don't clobber an existing quarantined file with the same name —
        # add a unix timestamp.
        dest = QUARANTINE_DIR / f"{jar.stem}.{int(time.time())}.jar"
    shutil.move(str(jar), str(dest))
    return dest


def append_manifest(quarantined: list[dict]) -> None:
    """Write a human-readable log of what just got quarantined."""
    if not quarantined:
        return
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = QUARANTINE_DIR / "QUARANTINE.md"
    new_file = not manifest.exists()
    with open(manifest, "a") as f:
        if new_file:
            f.write(
                "# Quarantined plugin jars\n\n"
                "This folder holds duplicate plugin jars that the BRUH "
                "Minecraft Server add-on moved out of `plugins/` to keep "
                "Paper from logging \"Ambiguous plugin name\" errors on "
                "every boot. The jars are NOT deleted — to restore one, "
                "move it back into `plugins/` and restart. To free disk "
                "space, delete the whole `.quarantine/` folder.\n"
            )
        f.write(f"\n## {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n")
        for q in quarantined:
            f.write(
                f"- **{q['plugin']}** (kept `{q['kept']}` v{q['kept_version']}): "
                f"moved `{q['from']}` v{q['from_version']} -> "
                f"`{q['to']}`\n"
            )


def main() -> int:
    if not PLUGINS_DIR.is_dir():
        log(f"plugins dir doesn't exist yet: {PLUGINS_DIR}")
        return 0

    # Pass 1: read metadata from every jar at the top level.
    by_name: dict[str, list[tuple[Path, str]]] = {}
    for entry in PLUGINS_DIR.iterdir():
        if not entry.is_file() or entry.suffix.lower() != ".jar":
            continue
        meta = read_plugin_meta(entry)
        if meta is None:
            continue
        name, version = meta
        by_name.setdefault(name, []).append((entry, version))

    # Pass 2: quarantine duplicates.
    quarantined: list[dict] = []
    for name, jars in by_name.items():
        if len(jars) < 2:
            continue
        # Sort ascending so the WINNER is at the end.
        jars.sort(key=lambda jv: jar_score(jv[0], jv[1]))
        winner_jar, winner_ver = jars[-1]
        for loser_jar, loser_ver in jars[:-1]:
            log(
                f"{name}: keeping {winner_jar.name} v{winner_ver}; "
                f"quarantining {loser_jar.name} v{loser_ver}"
            )
            try:
                dest = quarantine(loser_jar)
            except OSError as e:
                log(f"  ! failed to move {loser_jar.name}: {e}")
                continue
            quarantined.append(
                {
                    "plugin": name,
                    "kept": winner_jar.name,
                    "kept_version": winner_ver,
                    "from": loser_jar.name,
                    "from_version": loser_ver,
                    "to": dest.name,
                }
            )

    append_manifest(quarantined)

    if quarantined:
        log(f"Done. Quarantined {len(quarantined)} duplicate jar(s).")
    else:
        log("No duplicate plugin jars found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
