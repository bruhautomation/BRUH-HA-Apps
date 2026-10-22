"""The phone's microphone, for Claude Code's own `/voice`.

Claude Code's voice mode records the machine it runs on. With no sound
card it runs `arecord -f S16_LE -r 16000 -c 1 -t raw -q -` and reads raw
PCM from its stdout (read off the 2.1.307 bundle: the native module is
only tried when /proc/asound/cards lists a card, and Docker masks that
path). This container has no microphone, so the CLI's voice mode had
nothing to hear, and the microphone the person is holding is the phone's.

So there are two ends and this module is the middle:

* The terminal page (ttyd-assets/inject.html) captures the phone's mic
  with getUserMedia, converts it to 16 kHz mono S16LE and sends it here
  over `GET /api/voice/mic` (a WebSocket, behind ingress like every
  other panel route).
* `scripts/brain-arecord.py`, installed as /usr/local/bin/arecord, is
  what the CLI spawns. It reads `GET /api/voice/listen` — loopback only,
  read off the socket the way `ownership.from_loopback` reads it — and
  writes what arrives to its stdout.

One source at a time (a newer page replaces an older one), any number of
listeners, and a short pre-roll so the first syllable said between the
tap and the CLI starting `arecord` is not lost. Nothing is written to
disk, and audio only flows while the page is sending it: the mic is on
only while somebody has pressed the button.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections import deque

from aiohttp import WSMsgType, web

import ownership

log = logging.getLogger("brain.voice")

RATE = 16000
BYTES_PER_S = RATE * 2  # S16LE, mono
# What a listener gets the moment it connects: the audio the page sent in
# the moment before. The tap sends the CLI a space and the CLI spawns
# `arecord`, which then has to connect here; speech in that gap is
# otherwise dropped. Half a second is longer than that gap and short
# enough not to replay something said before the tap.
PRE_ROLL_BYTES = BYTES_PER_S // 2
# A frame larger than this is not audio from our page.
MAX_FRAME_BYTES = BYTES_PER_S
# How long a listener waits for a page to start sending. A space pressed
# on a desktop keyboard with voice on spawns `arecord` with no phone
# behind it; that has to end, not hang the CLI's recording.
WAIT_FOR_SOURCE_S = float(os.environ.get("BRAIN_VOICE_WAIT_S", "3"))
# A source that has sent nothing for this long is treated as gone.
SOURCE_IDLE_S = 5.0
# A runaway guard, not a budget: the page stops itself well before this.
MAX_SOURCE_S = 600.0
LISTENER_QUEUE = 64

SOURCE_BUSY = "Another page took over the microphone."
NO_SOURCE = ("No microphone is connected. Tap the mic button on the "
             "terminal's toolbar to talk from your phone.")


class Hub:
    """One microphone page, the arecord stand-ins listening to it."""

    def __init__(self) -> None:
        self.source: web.WebSocketResponse | None = None
        self.source_since = 0.0
        self.last_audio = 0.0
        self.pre_roll: deque[bytes] = deque()
        self.pre_roll_bytes = 0
        self.listeners: set[asyncio.Queue] = set()
        self.source_ready = asyncio.Event()

    # -- the page --------------------------------------------------------

    def attach(self, ws: web.WebSocketResponse) -> web.WebSocketResponse | None:
        """Make ``ws`` the source; return the one it replaced, if any."""
        old = self.source
        self.source = ws
        self.source_since = time.monotonic()
        self.last_audio = self.source_since
        self._clear_pre_roll()
        self.source_ready.set()
        return old

    def detach(self, ws: web.WebSocketResponse) -> None:
        if self.source is not ws:
            return
        self.source = None
        self.source_ready.clear()
        self._clear_pre_roll()
        for queue in list(self.listeners):
            _offer(queue, None)

    def feed(self, chunk: bytes) -> None:
        if not chunk or len(chunk) > MAX_FRAME_BYTES:
            return
        # Whole samples only: half a sample shifts every sample after it
        # by one byte, which turns speech into noise for the rest of it.
        if len(chunk) % 2:
            chunk = chunk[:-1]
        self.last_audio = time.monotonic()
        self.pre_roll.append(chunk)
        self.pre_roll_bytes += len(chunk)
        while self.pre_roll_bytes > PRE_ROLL_BYTES and len(self.pre_roll) > 1:
            self.pre_roll_bytes -= len(self.pre_roll.popleft())
        for queue in list(self.listeners):
            _offer(queue, chunk)

    def _clear_pre_roll(self) -> None:
        self.pre_roll.clear()
        self.pre_roll_bytes = 0

    def source_alive(self) -> bool:
        if self.source is None or self.source.closed:
            return False
        now = time.monotonic()
        return (now - self.last_audio < SOURCE_IDLE_S
                and now - self.source_since < MAX_SOURCE_S)

    # -- the listeners ---------------------------------------------------

    def listen(self) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=LISTENER_QUEUE)
        for chunk in self.pre_roll:
            _offer(queue, chunk)
        self.listeners.add(queue)
        return queue

    def unlisten(self, queue: asyncio.Queue) -> None:
        self.listeners.discard(queue)


def _offer(queue: asyncio.Queue, item) -> None:
    """Put without blocking; a listener that cannot keep up loses the
    oldest audio rather than holding up the page or the other listeners."""
    try:
        queue.put_nowait(item)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            # Emptied between the two calls: there is room now.
            pass
        try:
            queue.put_nowait(item)
        except asyncio.QueueFull:
            # Still full after dropping one: this chunk is the one lost,
            # which is the same answer a step later.
            pass


HUB_KEY = web.AppKey("voice_hub", Hub) if hasattr(web, "AppKey") else "voice_hub"


def _hub(request: web.Request) -> Hub:
    return request.app[HUB_KEY]


def _enabled() -> bool:
    # The mic exists for the terminal; no terminal, no mic route.
    return os.environ.get("BRAIN_ENABLE_TERMINAL", "true").lower() != "false"


async def _tell(ws: web.WebSocketResponse, **message) -> None:
    if ws.closed:
        return
    try:
        await ws.send_str(json.dumps(message))
    except (ConnectionResetError, RuntimeError):
        # The page went while we were telling it something; there is
        # nobody left to tell, and its own close is handled where it lands.
        pass


async def h_mic(request: web.Request) -> web.StreamResponse:
    """The page's end: binary frames of 16 kHz mono S16LE in.

    Text frames out, so the page can say what is happening:
    ``{"listening": true|false}`` when Claude Code starts or stops
    reading, and ``{"replaced": true}`` when another page took over.
    """
    if not _enabled():
        return web.json_response({"error": "The terminal is switched off."},
                                 status=404)
    hub = _hub(request)
    ws = web.WebSocketResponse(heartbeat=25, max_msg_size=MAX_FRAME_BYTES * 2)
    await ws.prepare(request)
    old = hub.attach(ws)
    log.info("Microphone connected from the terminal page")
    if old is not None and not old.closed:
        await _tell(old, replaced=True, error=SOURCE_BUSY)
        await old.close()
    await _tell(ws, ready=True, listening=bool(hub.listeners))
    try:
        async for msg in ws:
            if msg.type == WSMsgType.BINARY:
                hub.feed(msg.data)
            elif msg.type == WSMsgType.ERROR:
                break
    finally:
        hub.detach(ws)
        log.info("Microphone disconnected")
    return ws


async def h_listen(request: web.Request) -> web.StreamResponse:
    """The arecord stand-in's end: raw PCM out, for as long as the page
    sends it. Loopback only — this is a live microphone."""
    if not ownership.from_loopback(request):
        return web.json_response({"error": ownership.LOOPBACK_ONLY},
                                 status=403)
    hub = _hub(request)
    if not hub.source_alive():
        try:
            await asyncio.wait_for(hub.source_ready.wait(), WAIT_FOR_SOURCE_S)
        except asyncio.TimeoutError:
            # No page came: answered just below, in words.
            pass
    if not hub.source_alive():
        log.info("Claude Code started recording with no microphone connected")
        return web.json_response({"error": NO_SOURCE}, status=409)

    response = web.StreamResponse(headers={
        "Content-Type": "application/octet-stream",
        "Cache-Control": "no-store",
    })
    await response.prepare(request)
    queue = hub.listen()
    source = hub.source
    if source is not None:
        await _tell(source, listening=True)
    try:
        while True:
            try:
                chunk = await asyncio.wait_for(queue.get(), SOURCE_IDLE_S)
            except asyncio.TimeoutError:
                if hub.source_alive():
                    continue
                break
            if chunk is None:
                break
            await response.write(chunk)
    except ConnectionResetError:
        # The CLI SIGTERMed arecord: that is how a recording ends.
        pass
    finally:
        hub.unlisten(queue)
        if source is not None and source is hub.source and not hub.listeners:
            await _tell(source, listening=False)
    return response


def settings_path() -> str:
    base = os.environ.get("CLAUDE_CONFIG_DIR") or "/data/home/.claude"
    return os.path.join(base, "settings.json")


def voice_setting(path: str | None = None) -> dict:
    """What the CLI's own user settings say about voice mode.

    The two keys the CLI writes itself from `/voice` (``voiceEnabled``
    and ``voice: {enabled, mode}``), read the way it reads them: the
    nested key wins. An unreadable file is ``known: False`` — "I could
    not tell" — and never "voice is off".
    """
    path = path or settings_path()
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"known": True, "enabled": False, "mode": "hold"}
    except (OSError, ValueError):
        return {"known": False, "enabled": False, "mode": "hold"}
    if not isinstance(data, dict):
        return {"known": False, "enabled": False, "mode": "hold"}
    voice = data.get("voice") if isinstance(data.get("voice"), dict) else {}
    enabled = voice.get("enabled")
    if enabled is None:
        enabled = data.get("voiceEnabled")
    mode = voice.get("mode") if voice.get("mode") in ("hold", "tap") else "hold"
    return {"known": True, "enabled": enabled is True, "mode": mode}


async def h_state(request: web.Request) -> web.Response:
    """Whether Claude Code's voice mode is on, and in which mode — the
    page needs tap mode, because a phone cannot hold a key down."""
    state = await asyncio.to_thread(voice_setting)
    state["ready"] = state["enabled"] and state["mode"] == "tap"
    return web.json_response(state)


def setup(app: web.Application) -> None:
    app[HUB_KEY] = Hub()
    app.router.add_get("/api/voice/mic", h_mic)
    app.router.add_get("/api/voice/listen", h_listen)
    app.router.add_get("/api/voice/state", h_state)
