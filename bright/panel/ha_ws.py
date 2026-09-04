"""Home Assistant's WebSocket API — the half of Core the REST API does not serve.

Media sources live only here. That matters because "will this file play?" is
not a question the REST API can answer, and BRight was answering it by
assumption: it built `media-source://media_source/local/<path>` from the file
it found under /media and handed that to `media_player.play_media`. Two
things can be wrong with that guess and neither is visible from here:

* `local` is the *default* id of Home Assistant's local media source. A user
  who sets `media_dirs` in configuration.yaml replaces that default, so the
  id can be anything — and a media id Core cannot resolve comes back as
  Core's own HTTP 500, which arrives as a number about somebody else's
  request.
* The file may simply not be where Core is looking, even though it is where
  we are looking, because the add-on's /media mount and Core's media folder
  are two paths that are *usually* the same directory.

`media_source/resolve_media` is the same call the cast integration makes
before it hands a URL to a speaker, so asking it is the closest thing to
trying it. `media_source/browse_media` answers the other half — what Core
believes it has — which is what makes a source-id mismatch legible instead
of fatal.

aiohttp is already the panel's HTTP server, and its client speaks WebSocket,
so this costs no new dependency.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import aiohttp


HA_BASE_URL = os.environ.get("HA_BASE_URL", "http://supervisor/core/api")
SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")

# Every call is one connection: these are user-initiated, seconds apart at
# most, and a pooled connection would have to be re-authenticated and
# re-checked anyway. Simplicity is worth more here than a saved handshake.
TIMEOUT = 15.0


def ws_url() -> str:
    """`http://supervisor/core/api` → `ws://supervisor/core/websocket`."""
    override = os.environ.get("BRIGHT_HA_WS_URL")
    if override:
        return override
    url = HA_BASE_URL.replace("https://", "wss://").replace("http://", "ws://")
    return url.rsplit("/api", 1)[0] + "/websocket"


async def command(payload: dict, *, timeout: float = TIMEOUT) -> dict:
    """One authenticated command. Answers `{"result": …}` or `{"error": …}`.

    Never raises: every caller here is trying to *diagnose* something, and a
    diagnosis that dies of its own exception is worse than one that reports
    it could not look.
    """
    if not SUPERVISOR_TOKEN:
        return {"error": "SUPERVISOR_TOKEN not set (not running under the "
                         "Supervisor?)"}
    try:
        return await asyncio.wait_for(_exchange(payload, timeout), timeout + 5)
    except TimeoutError:
        return {"error": f"Home Assistant did not answer {payload.get('type')} "
                         f"within {timeout:.0f}s"}
    except (aiohttp.ClientError, OSError, ValueError) as exc:
        return {"error": f"cannot reach Home Assistant's WebSocket API: {exc}"}


async def _exchange(payload: dict, timeout: float) -> dict:
    async with aiohttp.ClientSession() as session:
        # No `timeout=` on the connect: aiohttp has changed that parameter's
        # type across versions (float, then ClientWSTimeout) and this image's
        # aiohttp comes from Alpine, so pinning either shape is a deprecation
        # warning on one and a TypeError on the other. The whole exchange is
        # already bounded by the `wait_for` above, and every receive below
        # carries its own timeout.
        #
        # max_msg_size=0 lifts the 4 MB frame cap: a media browse of a large
        # library is one frame, and a truncated one dies on receive where no
        # amount of later filtering can help.
        async with session.ws_connect(ws_url(), max_msg_size=0) as ws:
            hello = await _next_json(ws, timeout)
            if hello.get("type") != "auth_required":
                return {"error": f"unexpected greeting: {hello.get('type')!r}"}
            await ws.send_json({"type": "auth",
                                "access_token": SUPERVISOR_TOKEN})
            auth = await _next_json(ws, timeout)
            if auth.get("type") != "auth_ok":
                return {"error": f"WebSocket auth refused: "
                                 f"{auth.get('message', auth)}"}
            await ws.send_json({"id": 1, **payload})
            # Core interleaves events with results, so the id is what makes
            # an answer ours rather than the next thing it felt like saying.
            while True:
                message = await _next_json(ws, timeout)
                if message.get("id") != 1 or message.get("type") != "result":
                    continue
                if message.get("success"):
                    return {"result": message.get("result")}
                error = message.get("error") or {}
                return {"error": str(error.get("message") or error
                                     or "command failed")}


async def _next_json(ws: aiohttp.ClientWebSocketResponse, timeout: float) -> dict:
    message = await ws.receive(timeout=timeout)
    if message.type is aiohttp.WSMsgType.TEXT:
        parsed = json.loads(message.data)
        return parsed if isinstance(parsed, dict) else {}
    if message.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING,
                        aiohttp.WSMsgType.CLOSE):
        raise ConnectionError("Home Assistant closed the WebSocket")
    if message.type is aiohttp.WSMsgType.ERROR:
        raise ConnectionError(f"WebSocket error: {ws.exception()}")
    raise ConnectionError(f"unexpected WebSocket frame: {message.type!r}")


async def resolve_media(media_content_id: str) -> dict:
    """What Core would hand a speaker for this media id.

    `{"url": …, "mime_type": …}` — the URL relative, because Core is asked
    with `allow_relative_url=True` and signs the path rather than committing
    to a host. Which host it would prefix is a separate question, and the
    one that actually breaks casting (see `playback_check`).
    """
    answer = await command({"type": "media_source/resolve_media",
                            "media_content_id": media_content_id})
    if "error" in answer:
        return answer
    result = answer.get("result")
    return result if isinstance(result, dict) else {"error": "no answer"}


async def browse_media(media_content_id: str = "") -> dict:
    """One level of Core's media tree. Empty id is the root."""
    answer = await command({"type": "media_source/browse_media",
                            "media_content_id": media_content_id})
    if "error" in answer:
        return answer
    result = answer.get("result")
    return result if isinstance(result, dict) else {"error": "no answer"}


def children_of(browse_result: dict) -> list[dict[str, Any]]:
    children = browse_result.get("children")
    return [c for c in children if isinstance(c, dict)] if isinstance(children, list) else []
