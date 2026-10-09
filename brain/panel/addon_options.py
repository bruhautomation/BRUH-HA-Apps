"""Two-way access to this add-on's own Configuration-tab options.

The Supervisor stores the add-on's options; Home Assistant's Configuration
tab edits them. Historically the panel could only *read* those values
indirectly (as startup environment variables) and kept its own overrides in
/data/settings.json, so the two surfaces drifted: the ⚙ dialog showed
"add-on config: 24" while the Configuration tab showed something else, and
whichever was edited last silently won.

This module makes the Supervisor the single source of truth for the six
generation options, and for the one switch that decides whether the
terminal and the chat ask before acting (`dangerously_skip_permissions`):

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
import re
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
    # Not a generation option, and mirrored the same way so ⚙ → Terminal &
    # chat and the Configuration tab are one switch (permission_mode.py).
    "dangerously_skip_permissions": "dangerously_skip_permissions",
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


# What `/addons/self/info` said about the add-on itself, beyond its
# options. Filled by `refresh`; read by `panel_path`.
_info: dict = {}


def panel_path() -> str | None:
    """The Home Assistant route to this add-on's panel, or None.

    `/hassio/ingress/<slug>` is where the sidebar entry points, and it is
    the path a companion-app notification can open (`notify_router.
    open_link`). None until the Supervisor has answered once — a dev
    checkout and a box the Supervisor cannot be reached from both have no
    slug, and a guessed one would open the wrong add-on or nothing.
    `BRAIN_ADDON_SLUG` pins it, for a test or a box that knows better.
    """
    slug = os.environ.get("BRAIN_ADDON_SLUG", "").strip() or _info.get("slug")
    return f"/hassio/ingress/{slug}" if slug else None


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
        # The add-on's own slug rides in the same answer, and it is what a
        # notification needs to open this panel (`panel_path`). Kept only
        # when it is a real string: a link built on a missing slug is a
        # link to nowhere, and no link is the honest answer for that.
        slug = (body.get("data") or {}).get("slug")
        if isinstance(slug, str) and slug.strip():
            _info["slug"] = slug.strip()
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


# The release notes are a few hundred kilobytes at most; anything past this
# is not a changelog and is not shown.
CHANGELOG_MAX_BYTES = 2_000_000


# The Supervisor answers a changelog request it cannot serve with HTTP 200
# and a sentence (its frontend cannot show an error response there), so the
# sentence has to be recognised as a refusal rather than shown as notes.
_CHANGELOG_REFUSAL = re.compile(
    r"^\s*(?:no changelog found\b|(?:add-?on|app)\s+\S+\s+does not exist\b)",
    re.I)


async def _own_slug(session: aiohttp.ClientSession) -> str | None:
    """This add-on's real slug — `<repo hash>_brain` for a store install.

    The store's changelog route looks the slug up literally and does NOT
    resolve `self` (it answered `/addons/self/changelog` with "Addon self
    does not exist", as a 200), so the notes are asked for by name.
    """
    slug = os.environ.get("BRAIN_ADDON_SLUG", "").strip() or _info.get("slug")
    if slug:
        return slug
    try:
        async with session.get(f"{SUPERVISOR_URL}/addons/self/info",
                               headers=_headers()) as resp:
            if resp.status != 200:
                return None
            body = await resp.json()
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        log.debug("supervisor self info read failed: %s", exc)
        return None
    slug = ((body or {}).get("data") or {}).get("slug")
    if isinstance(slug, str) and slug.strip():
        _info["slug"] = slug.strip()
        return _info["slug"]
    return None


async def changelog() -> tuple[str | None, str]:
    """This add-on's release notes, as the Supervisor serves them.

    `CHANGELOG.md` is not in the image; the Supervisor keeps the copy the
    store installed from and serves it as plain text at
    `/store/addons/<slug>/changelog` (and the legacy `/addons/<slug>/
    changelog`). Both look the slug up literally, so the real slug is read
    off `/addons/self/info` first; `self` is tried only when it cannot be. Returns ``(text, "")``, or ``(None, sentence)``
    naming why there is none, because "the Supervisor would not answer"
    and "there are no notes" are different things to tell somebody.
    """
    if not available():
        return None, "brAIn cannot reach the Supervisor from here."
    error = "The Supervisor did not answer."
    headers = {**_headers(), "Accept": "text/plain"}
    try:
        async with aiohttp.ClientSession(timeout=TIMEOUT) as session:
            slug = await _own_slug(session)
            # `self` only when the slug could not be read: asked after a
            # real slug, its "does not exist" would replace the true reason.
            paths = ([f"/store/addons/{slug}/changelog",
                      f"/addons/{slug}/changelog"] if slug
                     else ["/addons/self/changelog"])
            for path in paths:
                try:
                    async with session.get(f"{SUPERVISOR_URL}{path}",
                                           headers=headers) as resp:
                        if resp.status != 200:
                            error = (f"The Supervisor would not hand over the "
                                     f"release notes (HTTP {resp.status}).")
                            continue
                        raw = await resp.content.read(CHANGELOG_MAX_BYTES + 1)
                except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                    log.debug("supervisor changelog read failed: %s", exc)
                    error = "The Supervisor did not answer."
                    continue
                if len(raw) > CHANGELOG_MAX_BYTES:
                    return None, "The release notes were too large to show."
                text = raw.decode("utf-8", errors="replace")
                if text.lstrip().startswith("{"):
                    # A JSON error envelope where text was asked for.
                    error = "The Supervisor answered with no release notes."
                    continue
                if not text.strip():
                    error = "The Supervisor has no release notes for this add-on."
                    continue
                if _CHANGELOG_REFUSAL.match(text):
                    error = ("The Supervisor would not hand over the release "
                             "notes: " + text.strip().splitlines()[0][:160])
                    continue
                return text, ""
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as exc:
        log.debug("supervisor changelog read failed: %s", exc)
        return None, "The Supervisor did not answer."
    return None, error
