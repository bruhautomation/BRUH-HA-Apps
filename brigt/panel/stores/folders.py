"""Which folders under /media BRigt scans for music.

There are two ways to answer that and they are not rivals. The add-on's
`music_folder` and `additional_music_folders` options are configuration:
they survive a reinstall, they are what an automation-minded person edits,
and they are the answer a fresh install starts with. This store is the
*panel's* half — folders someone picked by browsing, without editing YAML
and restarting the add-on to see whether they typed the path right.

`server._music_folders` merges the two, so neither is a second answer to
the same question: the options say where music lives, this says what else
was ticked, and a folder in both is one folder.

Paths are stored **relative to /media** on purpose. The absolute prefix is
not ours — it is where the Supervisor mounted Home Assistant's media share
— and storing it would bake this container's view of the filesystem into a
file that outlives it.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import atomic_write

FOLDERS_FILE = Path(os.environ.get("BRIGT_STATE", "/data")) / "music-folders.json"

# A folder list is a person's choices, not a database. The cap is here so a
# corrupted or hand-edited file cannot make every library scan walk a
# thousand trees.
MAX_FOLDERS = 64


def load() -> list[str]:
    """The picked folders, relative to /media, in the order they were added."""
    try:
        data = json.loads(FOLDERS_FILE.read_text())
    except (OSError, ValueError):
        # No file yet, or an unreadable one. An empty list is the honest
        # answer and the next save rewrites it.
        return []
    folders = data.get("folders") if isinstance(data, dict) else None
    if not isinstance(folders, list):
        return []
    return [f for f in folders if isinstance(f, str) and f][:MAX_FOLDERS]


def _save(folders: list[str]) -> list[str]:
    atomic_write.write_json(FOLDERS_FILE, {"folders": folders}, indent=2)
    return folders


def add(relative: str) -> list[str]:
    """Tick a folder. Idempotent, because ticking twice is one folder."""
    folders = load()
    if relative in folders:
        return folders
    if len(folders) >= MAX_FOLDERS:
        raise ValueError(f"that is more than {MAX_FOLDERS} folders — "
                         f"scan a parent folder instead")
    return _save(folders + [relative])


def remove(relative: str) -> list[str]:
    folders = load()
    if relative not in folders:
        return folders
    return _save([f for f in folders if f != relative])
