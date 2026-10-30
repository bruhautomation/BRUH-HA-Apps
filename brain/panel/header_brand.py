"""The mark in the page's header: brAIn's wordmark, the assistant's name, or
the house's own text and/or picture (⚙ › Personality › Header).

The choice itself (`header_brand`, `header_text`) is two panel settings in
`settings_store`. This module is the picture: one file in `/config/.brain/ui/`
(where the house's other layer files live), written atomically, accepted only
when its first bytes say it is a PNG, a JPEG or a WebP, and served from one
fixed route with the content type those bytes give, never one the client
named. SVG is refused on purpose: it can carry script.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import atomic_write

UI_DIR = Path(os.environ.get("BRAIN_HOUSE_UI_DIR", "/config/.brain/ui"))
FILE = "header-logo"
MAX_BYTES = 256 * 1024
MODES = ("logo", "name", "custom")
TEXT_MAX = 24


def _path() -> Path:
    return UI_DIR / FILE


def sniff(data: bytes) -> str | None:
    """The content type the bytes themselves give, or None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def refusal(data: bytes) -> str | None:
    if not data:
        return "Send the picture as the request body."
    if len(data) > MAX_BYTES:
        return f"The picture is at most {MAX_BYTES // 1024} KB."
    if sniff(data) is None:
        return "Use a PNG, JPEG or WebP picture."
    return None


def save(data: bytes) -> str:
    """Write the picture; returns its cache-busting version."""
    why = refusal(data)
    if why:
        raise ValueError(why)
    atomic_write.write_bytes(_path(), data, mode=0o644)
    return hashlib.sha256(data).hexdigest()[:12]


def read() -> tuple[bytes, str] | None:
    """(bytes, content type) of the stored picture, or None. A file that no
    longer looks like one of the three is not served."""
    try:
        path = _path()
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    ctype = sniff(data)
    return (data, ctype) if ctype else None


def remove() -> None:
    try:
        _path().unlink()
    except OSError:
        # Already gone (or never there): either way no picture is stored.
        pass


def version() -> str | None:
    got = read()
    return hashlib.sha256(got[0]).hexdigest()[:12] if got else None


def payload(settings: dict) -> dict:
    """What the page is told: the choice, the text, the picture's address."""
    v = version()
    return {"brand": settings.get("header_brand"),
            "text": settings.get("header_text") or "",
            "image": f"header-logo?v={v}" if v else None}
