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

In addition to duplicates, jars whose `api-version` targets a NEWER
Minecraft version than the running server are quarantined too: Paper
hard-refuses to load them ("Unsupported API version 1.21.4"), so they
can only ever produce a boot error. Quarantining converts a cryptic
stack trace on every start into one clear log line and a manifest entry
telling the user to install a build for their server version.

Environment variables:
  PLUGINS_DIR   defaults to /config/minecraft/plugins
  SERVER_META   defaults to /config/minecraft/.server-meta.json
                (written by download-server.sh; used for the
                api-version compatibility pass — skipped if missing)
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
SERVER_META = Path(
    os.environ.get("SERVER_META", "/config/minecraft/.server-meta.json")
)

# Match common pre-release markers anywhere in a filename or version string.
# Word boundary at the start so "presence" doesn't match "pre".
PRE_RELEASE_RE = re.compile(
    r"(?:^|[\W_])(?:pre|snapshot|rc|beta|alpha|dev|nightly)(?:\d+)?(?:\W|$)",
    re.IGNORECASE,
)


def log(msg: str) -> None:
    print(f"[plugin-cleanup] {msg}", file=sys.stderr, flush=True)


def read_plugin_meta(jar_path: Path) -> Optional[tuple[str, str, Optional[str]]]:
    """Return (name, version, api_version) from a plugin jar.

    Reads paper-plugin.yml first (Paper's modern format), then falls
    back to plugin.yml (the Bukkit/Spigot legacy format). Returns None
    if the jar is unreadable, isn't a plugin, or doesn't declare a name.
    api_version is None when the descriptor doesn't declare one (legacy
    Bukkit plugins).
    """
    try:
        with zipfile.ZipFile(jar_path) as zf:
            for candidate in ("paper-plugin.yml", "plugin.yml"):
                try:
                    raw = zf.read(candidate).decode("utf-8", errors="replace")
                except KeyError:
                    continue
                # Tiny YAML parser — we only need top-level `name:`,
                # `version:` and `api-version:` keys, so we don't need full
                # YAML semantics (and don't want a PyYAML dependency).
                name = version = api_version = None
                for line in raw.splitlines():
                    line = line.split("#", 1)[0].rstrip()
                    if not line or line.startswith((" ", "\t")):
                        continue  # nested keys / continuations
                    m = re.match(
                        r"^(name|version|api-version)\s*:\s*[\"']?(.+?)[\"']?\s*$",
                        line,
                    )
                    if m:
                        if m.group(1) == "name" and name is None:
                            name = m.group(2).strip()
                        elif m.group(1) == "version" and version is None:
                            version = m.group(2).strip()
                        elif m.group(1) == "api-version" and api_version is None:
                            api_version = m.group(2).strip()
                if name:
                    return (name, version or "0", api_version)
    except (zipfile.BadZipFile, OSError):
        pass
    return None


def _mc_tuple(version: str) -> Optional[tuple[int, int, int]]:
    """Parse an MC-shaped version ("1.20.1", "1.21") into a sortable tuple."""
    m = re.match(r"^(\d+)\.(\d+)(?:\.(\d+))?$", version.strip())
    if not m:
        return None
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))


def read_server_version() -> Optional[tuple[int, int, int]]:
    """The MC version of the installed server.jar, from download-server.sh's
    metadata file. None when unknown (no meta yet, or unparseable)."""
    try:
        meta = json.loads(SERVER_META.read_text())
    except (OSError, ValueError):
        return None
    return _mc_tuple(str(meta.get("version", "")))


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


def append_incompat_manifest(incompatible: list[dict]) -> None:
    """Manifest section for api-version quarantines."""
    if not incompatible:
        return
    QUARANTINE_DIR.mkdir(parents=True, exist_ok=True)
    manifest = QUARANTINE_DIR / "QUARANTINE.md"
    with open(manifest, "a") as f:
        f.write(
            f"\n## {time.strftime('%Y-%m-%d %H:%M:%S %Z')} — "
            "incompatible with this server version\n\n"
        )
        for q in incompatible:
            f.write(
                f"- **{q['plugin']}**: `{q['from']}` targets Minecraft "
                f"{q['api_version']} but the server runs {q['server']} — "
                f"Paper refuses to load it. Moved to `{q['to']}`. "
                f"Install a build of this plugin for {q['server']} "
                f"(or upgrade the server) and it will work again.\n"
            )


def main() -> int:
    if not PLUGINS_DIR.is_dir():
        log(f"plugins dir doesn't exist yet: {PLUGINS_DIR}")
        return 0

    server_version = read_server_version()

    # Pass 1: read metadata from every jar at the top level. Jars whose
    # api-version targets a NEWER Minecraft than the server runs are
    # quarantined immediately — Paper can never load them, and letting one
    # into the duplicate grouping below could make it "win" on higher
    # semver and quarantine the compatible copy instead.
    by_name: dict[str, list[tuple[Path, str]]] = {}
    incompatible: list[dict] = []
    for entry in PLUGINS_DIR.iterdir():
        if not entry.is_file() or entry.suffix.lower() != ".jar":
            continue
        meta = read_plugin_meta(entry)
        if meta is None:
            continue
        name, version, api_version = meta
        api_tuple = _mc_tuple(api_version) if api_version else None
        if server_version and api_tuple and api_tuple > server_version:
            server_str = ".".join(str(p) for p in server_version)
            log(
                f"{name}: api-version {api_version} needs a newer server "
                f"than {server_str}; quarantining {entry.name} "
                f"(install a build for Minecraft {server_str})"
            )
            try:
                dest = quarantine(entry)
            except OSError as e:
                log(f"  ! failed to move {entry.name}: {e}")
                by_name.setdefault(name, []).append((entry, version))
                continue
            incompatible.append(
                {
                    "plugin": name,
                    "from": entry.name,
                    "api_version": api_version,
                    "server": server_str,
                    "to": dest.name,
                }
            )
            continue
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
    append_incompat_manifest(incompatible)

    if quarantined:
        # Surface which plugins had duplicates so the boot log makes it
        # obvious what the add-on cleaned up (instead of just a silent count).
        affected = sorted({q["plugin"] for q in quarantined})
        log(
            f"Done. Quarantined {len(quarantined)} duplicate jar(s) "
            f"for: {', '.join(affected)}."
        )
    if incompatible:
        affected = sorted({q["plugin"] for q in incompatible})
        log(
            f"Quarantined {len(incompatible)} jar(s) built for a newer "
            f"Minecraft than this server: {', '.join(affected)}. "
            "See plugins/.quarantine/QUARANTINE.md."
        )
    if not quarantined and not incompatible:
        log("No duplicate plugin jars found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
