"""Two-way access to this add-on's own Configuration-tab options.

The Supervisor stores the add-on's options; Home Assistant's Configuration
tab edits them. Historically the panel could only *read* those values
indirectly (as startup environment variables) and kept its own overrides in
/data/settings.json, so the two surfaces drifted: the ⚙ dialog showed
"add-on config: 24" while the Configuration tab showed something else, and
whichever was edited last silently won.

This module makes the Supervisor the single source of truth for the six
generation options:

  * read  — GET  /addons/self/info   → data.options   (cached, polled)
  * write — POST /addons/self/options with the FULL options object

Both endpoints are reachable from inside the add-on with SUPERVISOR_TOKEN
(the add-on may always manage itself). Writes are read-modify-write because
the Supervisor *replaces* the stored options wholesale — a partial POST
would drop log_level and anything else it doesn't mention.

Everything degrades gracefully: with no Supervisor (tests, `python
server.py` on a laptop) `snapshot()` stays None and callers fall back to
the local override store, exactly as before.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

import aiohttp

log = logging.getLogger("brain.options")

SUPERVISOR_URL = os.environ.get("SUPERVISOR_URL", "http://supervisor")
TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
TIMEOUT = aiohttp.ClientTimeout(total=10)

# settings key (panel/settings_store) → add-on option key (config.yaml)
OPTION_KEYS = {
    "refresh_hours": "auto_refresh_hours",
    "history_days": "history_days",
    "history_keep_runs": "history_keep_runs",
    "history_keep_days": "history_keep_days",
    "model": "model",
    "timeout_minutes": "generation_timeout_minutes",
}

CACHE_TTL = 10.0

_options: dict | None = None      # last successful read of data.options
_read_at = 0.0
_lock = asyncio.Lock()


class OptionsError(RuntimeError):
    """The Supervisor refused or could not be reached."""


def available() -> bool:
    """True when we can talk to the Supervisor at all."""
    return bool(TOKEN)


def snapshot() -> dict | None:
    """The last known add-on options, or None if never read successfully."""
    return dict(_options) if _options is not None else None


def get(setting: str):
    """One option by its *settings* name, or None when unknown/unavailable.

    Note "" is a real value for `model` (= let the CLI choose) and is
    returned as-is; only None means "no answer from the Supervisor".
    """
    if _options is None:
        return None
    return _options.get(OPTION_KEYS[setting])


def _headers() -> dict:
    return {"Authorization": f"Bearer {TOKEN}"}


async def refresh(force: bool = False) -> dict | None:
    """Re-read the add-on's options. Returns the options, or None on failure.

    Cheap to call: within CACHE_TTL of the last successful read it just
    hands back the cache unless `force` is set.
    """
    global _options, _read_at
    if not available():
        return None
    if not force and _options is not None and time.time() - _read_at < CACHE_TTL:
        return dict(_options)
    async with _lock:
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.get(
                        f"{SUPERVISOR_URL}/addons/self/info",
                        headers=_headers()) as resp:
                    resp.raise_for_status()
                    body = await resp.json()
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            log.debug("supervisor options read failed: %s", exc)
            return None
        opts = (body.get("data") or {}).get("options")
        if not isinstance(opts, dict):
            log.debug("supervisor options read returned no options object")
            return None
        _options = opts
        _read_at = time.time()
        return dict(opts)


async def write(changes: dict) -> dict:
    """Merge `changes` (settings names) into the add-on's options.

    Returns the resulting full options object. Raises OptionsError when the
    Supervisor is unavailable or rejects the write — callers fall back to
    the local override store so the panel keeps working either way.
    """
    if not available():
        raise OptionsError("no Supervisor token")
    current = await refresh(force=True)
    if current is None:
        raise OptionsError("could not read current add-on options")
    merged = dict(current)
    for key, value in changes.items():
        merged[OPTION_KEYS[key]] = value
    async with _lock:
        try:
            async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
                async with session.post(
                        f"{SUPERVISOR_URL}/addons/self/options",
                        headers=_headers(), json={"options": merged}) as resp:
                    body = await resp.json(content_type=None)
                    if resp.status != 200 or body.get("result") != "ok":
                        raise OptionsError(
                            body.get("message") or f"HTTP {resp.status}")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
            raise OptionsError(str(exc)) from exc
        global _options, _read_at
        _options = merged
        _read_at = time.time()
    return dict(merged)
