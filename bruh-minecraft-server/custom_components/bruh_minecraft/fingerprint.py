"""What Home Assistant would have to restart to load: one hash of it.

Home Assistant loads a custom integration's Python when it starts and never
again, so a restart is owed only when the code it is running differs from
the code on disk. The manifest's ``version`` is not that: every add-on
release moves it, including the ones that did not change a byte of the
integration. So the question is asked of the files themselves.

The fingerprint covers what Core reads when it loads the integration: every
``*.py``, ``*.json`` and ``*.yaml`` file (``services.yaml``, ``strings.json``,
``icons.json``, ``translations/``), with the release's version left out: the
manifest's ``"version":`` line, and a module's ``VERSION = "x.y.z"`` line,
which GardenRX's const.py carries in step with the release (it names the
device's software version and nothing Core has to reload). It leaves out
the browser's files (``frontend/``, ``www/``, ``static/``), ``brand/``,
caches and hidden files, because a page reload picks those up and a restart
adds nothing.

The integration takes its own fingerprint as it is imported
(``LOADED_FINGERPRINT``) and writes it where its add-on reads it
(``record_loaded``, or the integration's own record writer). Every BRUH
add-on with an integration carries this file unchanged (an add-on
is a self-contained image, so it is copied rather than shared), and each
add-on's run.sh carries ``integration_fingerprint``, the same hash in shell
for images without Python. ``tests/test_integration_fingerprint.py`` holds
the copies identical and the two implementations to one answer.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time

# A change to what is hashed changes every fingerprint, which reads as a
# restart owed once; the prefix says which rule made a fingerprint.
SCHEME = "f1"
SKIP_DIRS = frozenset({"__pycache__", "frontend", "brand", "www", "static"})
SUFFIXES = (".py", ".json", ".yaml", ".yml")
_MANIFEST_VERSION = re.compile(rb'^\s*"version"\s*:')
_MODULE_VERSION = re.compile(rb'^VERSION\s*=\s*["\'][^"\']*["\']\s*$')


def _files(directory: str) -> list[str]:
    found = []
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.startswith(".") or not name.endswith(SUFFIXES):
                continue
            rel = os.path.relpath(os.path.join(root, name), directory)
            found.append(rel.replace(os.sep, "/"))
    return sorted(found)


def _content(directory: str, rel: str) -> bytes:
    with open(os.path.join(directory, rel), "rb") as fh:
        data = fh.read()
    if rel == "manifest.json":
        skip = _MANIFEST_VERSION
    elif rel.endswith(".py"):
        skip = _MODULE_VERSION
    else:
        return data
    lines = data.split(b"\n")
    if lines and lines[-1] == b"":
        lines.pop()
    return b"".join(line + b"\n" for line in lines if not skip.match(line))


def fingerprint(directory: str) -> str | None:
    """The fingerprint of the integration in ``directory``, or None when it
    cannot be read (which is a restart owed, never one waved through)."""
    if not os.path.isfile(os.path.join(directory, "manifest.json")):
        return None
    try:
        files = _files(directory)
        listing = "".join(
            f"{rel} {hashlib.sha256(_content(directory, rel)).hexdigest()}\n"
            for rel in files)
    except OSError:
        return None
    return SCHEME + "-" + hashlib.sha256(listing.encode("utf-8")).hexdigest()[:16]


# The code this Home Assistant loaded: taken as the integration is imported,
# because the add-on may overwrite the files on disk afterwards.
LOADED_FINGERPRINT = fingerprint(os.path.dirname(os.path.abspath(__file__)))


def record_loaded(path: str, version: str | None = None) -> None:
    """Write what Home Assistant loaded where the add-on reads it (its
    run.sh or panel). Best effort: a record that cannot be written is a
    restart asked for that was not owed, never a setup that fails."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        scratch = f"{path}.tmp"
        with open(scratch, "w", encoding="utf-8") as fh:
            json.dump({"version": version, "fingerprint": LOADED_FINGERPRINT,
                       "at": int(time.time())}, fh)
        os.replace(scratch, path)
    except OSError:
        pass  # a read-only /config: the add-on asks for a restart it did not need
