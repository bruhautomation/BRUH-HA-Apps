#!/usr/bin/env python3
"""The fonts a label may use, and where they actually are.

A font list that names files is a font list that is wrong on the next base
image, so each family is a list of candidate paths and the first one that
exists wins. A family with no file at all is *dropped from the catalog*
rather than falling back silently: the panel builds its font picker from
what this returns, so a missing font is a name that never appears, not a
name that appears and renders as something else. Somebody choosing
"Monospace" for a lot number and getting proportional digits would find out
on the label.
"""
from __future__ import annotations

import functools
from pathlib import Path

# Ordered candidates per family. Alpine's font-dejavu and ttf-liberation
# packages first, then the Debian layout, so a dev checkout renders the same
# thing the container does.
FAMILIES: dict[str, tuple[str, list[str]]] = {
    "sans": ("Sans", [
        "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]),
    "sans-bold": ("Sans Bold", [
        "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ]),
    "sans-condensed": ("Sans Condensed", [
        "/usr/share/fonts/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed.ttf",
        "/usr/share/fonts/liberation/LiberationSansNarrow-Regular.ttf",
    ]),
    "sans-condensed-bold": ("Sans Condensed Bold", [
        "/usr/share/fonts/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSansNarrow-Bold.ttf",
    ]),
    "serif": ("Serif", [
        "/usr/share/fonts/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
        "/usr/share/fonts/liberation/LiberationSerif-Regular.ttf",
    ]),
    "serif-bold": ("Serif Bold", [
        "/usr/share/fonts/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationSerif-Bold.ttf",
    ]),
    "mono": ("Monospace", [
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/liberation/LiberationMono-Regular.ttf",
    ]),
    "mono-bold": ("Monospace Bold", [
        "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
        "/usr/share/fonts/liberation/LiberationMono-Bold.ttf",
    ]),
}

# A label with no font at all is not a label, so the very last resort is
# Pillow's built-in bitmap font — tiny and ugly, and the panel says so
# rather than shipping a blank label.
FALLBACK_KEY = "sans-bold"


def _first_existing(paths: list[str]) -> str | None:
    return next((p for p in paths if Path(p).is_file()), None)


@functools.lru_cache(maxsize=1)
def catalog() -> dict[str, dict]:
    """The families that exist on this machine, keyed as the panel sees them."""
    out: dict[str, dict] = {}
    for key, (label, paths) in FAMILIES.items():
        path = _first_existing(paths)
        if path:
            out[key] = {"key": key, "name": label, "path": path}
    return out


def path_for(key: str) -> str | None:
    found = catalog()
    entry = found.get(key) or found.get(FALLBACK_KEY)
    if entry is None:
        entry = next(iter(found.values()), None)
    return entry["path"] if entry else None


@functools.lru_cache(maxsize=256)
def load(key: str, size_px: int):
    """A PIL font, cached — a fit search asks for dozens of sizes per label.

    The cache is on (family, size) and both are small integers, so a busy
    autofit pass costs one FreeType open per distinct size rather than one
    per probe. Without it, fitting a word is ~10 font loads and fitting a
    template with six text boxes is sixty.
    """
    from PIL import ImageFont  # noqa: PLC0415

    path = path_for(key)
    size_px = max(1, int(size_px))
    if path is None:  # pragma: no cover - an image with no fonts at all
        return ImageFont.load_default()
    try:
        return ImageFont.truetype(path, size_px)
    except OSError:  # pragma: no cover
        return ImageFont.load_default()
