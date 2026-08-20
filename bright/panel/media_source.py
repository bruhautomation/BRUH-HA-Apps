"""Which of Core's media sources is the /media this add-on can see.

BRight builds a media id from a path: a file at `/media/bright/x.wav`
becomes `media-source://media_source/local/bright/x.wav` and goes to a
speaker. The `local` in the middle was a **guess** — it is the id Home
Assistant gives its local media source *by default*, and the default is
only the default. Set `media_dirs` in configuration.yaml and the source
is called whatever the key says; Core then answers every id BRight builds
with `Unknown source directory`, and nothing plays: not the calibration
click track, not a single song.

A guard that refuses has to change the next attempt, and a constant
cannot change anything. So the id is **discovered** instead:

1. Browse the media-source root. Its children are the directories Core
   actually has, and their ids carry the real keys.
2. Try each one against a file we know is there, with the same
   `media_source/resolve_media` call the cast integration makes. The one
   that resolves is the one that maps to our /media.
3. Remember it.

Empirical rather than declarative on purpose: Core does not publish the
filesystem path behind a source, so "which of these is /media" is not a
question that can be *read* — only tried. The probe file is the click
track, which BRight writes itself and can therefore always count on.

The answer is cached because it changes only when someone edits
configuration.yaml and restarts Core, and dropped the moment a resolve
fails, so a config change costs one failed play and not a restart.
"""
from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path

import ha_ws

log = logging.getLogger("bright.media_source")

MEDIA_ROOT = Path(os.environ.get("BRIGHT_MEDIA", "/media"))
PREFIX = "media-source://media_source"

# The id Home Assistant uses when nobody has said otherwise. Still tried
# first — it is right on the large majority of installs, and being right
# first time costs one resolve instead of one browse plus several.
DEFAULT_ID = "local"

# What BRight writes itself and can always probe with.
PROBE_RELATIVE = "bright/calibration.wav"

_lock = asyncio.Lock()
_cached: str | None = None
_last_error: str = ""
_candidates: list[str] = []


def build(source_id: str, relative: str) -> str:
    """`local` + `bright/x.wav` → the media id. No I/O."""
    return f"{PREFIX}/{source_id}/{relative.lstrip('/')}"


def relative_to_media(path: str | Path) -> str | None:
    """A path under /media as Core would name it, or None if it is not
    under /media at all — which is a real answer: a folder outside Core's
    media root analyses perfectly and can never be served."""
    try:
        return str(Path(path).relative_to(MEDIA_ROOT))
    except ValueError:
        return None


def current_id() -> str:
    """The best id known right now, without asking Core.

    Sync, because the callers that build ids while a show is being
    dispatched cannot await — and by then discovery has already run. It
    is the default until something learns better, which is exactly the old
    behaviour and therefore never worse than it.
    """
    return _cached or DEFAULT_ID


def content_id(path: str | Path) -> str | None:
    """The media id for a file on disk, using what is known so far."""
    relative = relative_to_media(path)
    return None if relative is None else build(current_id(), relative)


def forget() -> None:
    """Drop the cached id. Called when a resolve fails, so the next play
    re-discovers rather than repeating a wrong answer forever."""
    global _cached
    _cached = None


def state() -> dict:
    """What the panel shows: the id in use, what else Core offers, and why
    discovery failed if it did."""
    return {"source_id": current_id(), "discovered": _cached is not None,
            "candidates": list(_candidates), "error": _last_error,
            "media_root": str(MEDIA_ROOT)}


async def _resolves(source_id: str, relative: str) -> bool:
    answer = await ha_ws.resolve_media(build(source_id, relative))
    return "error" not in answer and bool(answer.get("url"))


async def discover(probe_relative: str = PROBE_RELATIVE,
                   *, force: bool = False) -> dict:
    """Find the source id whose directory is our /media. Returns `state()`.

    Never raises: this runs on the way to playing something, and a
    diagnosis that dies of its own exception is worse than one that
    reports it could not look.
    """
    global _cached, _last_error, _candidates
    async with _lock:
        if _cached is not None and not force:
            return state()
        _last_error = ""

        # The default first: right nearly everywhere, and one call.
        if await _resolves(DEFAULT_ID, probe_relative):
            _cached = DEFAULT_ID
            return state()

        root = await ha_ws.browse_media(PREFIX)
        if "error" in root:
            _last_error = str(root["error"])
            return state()

        found = []
        for child in ha_ws.children_of(root):
            child_id = str(child.get("media_content_id") or "")
            if not child_id.startswith(PREFIX + "/"):
                continue
            key = child_id[len(PREFIX) + 1:].split("/", 1)[0]
            if key:
                found.append(key)
        _candidates = found

        for key in found:
            if key == DEFAULT_ID:
                continue  # already tried, and it did not resolve
            if await _resolves(key, probe_relative):
                _cached = key
                log.info("Home Assistant's media source for %s is %r, not "
                         "the default %r", MEDIA_ROOT, key, DEFAULT_ID)
                return state()

        # Nothing resolved. That is a real finding and it has a shape: the
        # directories Core has are not the directory this add-on is looking
        # at. Naming them is the whole of the fix, because the person has
        # to recognise their own configuration.yaml in the answer.
        _last_error = (
            f"none of Home Assistant's media sources resolve "
            f"{MEDIA_ROOT}/{probe_relative}. "
            + (f"Core offers: {', '.join(found)}. " if found
               else "Core offers no media directories at all. ")
            + "If you set `media_dirs` in configuration.yaml, one of its "
              "entries has to point at the same folder this add-on sees as "
              f"{MEDIA_ROOT} — that is the folder BRight writes to and the "
              "one Home Assistant has to serve from.")
        return state()


async def ensure(probe_relative: str = PROBE_RELATIVE) -> dict:
    """Discover if we have not yet. The call sites use this."""
    return await discover(probe_relative)
