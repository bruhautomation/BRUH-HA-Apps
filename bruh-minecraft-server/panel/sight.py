#!/usr/bin/env python3
"""The live world, from the BRUH Sight plugin running inside the server.

Before it, the panel knew the world two slow ways: RCON (`data get entity`,
six commands a player every five seconds) and the region files on disk,
which the server writes minutes after a block changes. So the companion
could not see what had just been built, a chunk not yet saved read as
nothing at all (#606, #607, #620), and "this" meant nothing without the
spyglass. The plugin (`sight/`, copied into `plugins/` by run.sh on Paper
and Purpur) answers from the running server on loopback, with a token in
its own folder:

* `state()` — every online player: position, facing, dimension, health,
  food, game mode, the block and entity under the crosshair (`looking_at`,
  `looking_at_entity`), what they hold and carry, what is around them, the
  blocks they just placed or broke, the biome and the light.
* `blocks(dimension, box)` — every block state in a box as it is NOW.

Everything here fails soft: without the plugin (vanilla, Fabric, Forge,
Folia, a server still starting) every call answers None and the callers
read RCON and the saved world as before. A failure backs off for
`BACKOFF_S` so a missing plugin costs one file stat a beat, not a timeout.
"""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ENDPOINT = Path("plugins") / "BruhSight" / "endpoint.json"
BACKOFF_S = 5.0          # after a failed call, how long to read the old way
STATE_FRESH_S = 0.4      # one state answers every caller within this long
STATE_TIMEOUT_S = 2.0
BLOCKS_TIMEOUT_S = 15.0
BOX_MAX = 262_144        # the plugin's own cap on one read

# What a live player carries beyond what RCON could say, passed through to
# the world snapshot (and so to brAIn) under the same names.
LIVE_KEYS = ("looking_at", "looking_at_entity", "holding", "offhand", "armor", "inventory",
             "nearby", "recent_blocks", "standing_on", "biome", "light", "doing", "level",
             "uuid")


class Sight:
    """A client for the plugin; one per panel."""

    def __init__(self, server_dir: Path | Callable[[], Path], *,
                 clock: Callable[[], float] = time.monotonic,
                 opener: Callable[..., Any] | None = None):
        self._server_dir = server_dir
        self.clock = clock
        self.opener = opener or urllib.request.urlopen
        self.down_until = -1e12
        self.last_error: str | None = None
        self._state: tuple[float, dict[str, Any]] | None = None
        self.calls = 0

    # -- plumbing ------------------------------------------------------------
    def server_dir(self) -> Path:
        d = self._server_dir
        return Path(d() if callable(d) else d)

    def endpoint(self) -> dict[str, Any] | None:
        """{host, port, token} from the plugin's own file, or None."""
        try:
            data = json.loads((self.server_dir() / ENDPOINT).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or not isinstance(data.get("port"), int) \
                or not isinstance(data.get("token"), str) or not data["token"]:
            return None
        host = data.get("host") if data.get("host") in ("127.0.0.1", "::1", "localhost") \
            else "127.0.0.1"
        return {"host": host, "port": data["port"], "token": data["token"]}

    def _fail(self, why: str) -> None:
        self.last_error = why[:200]
        self.down_until = self.clock() + BACKOFF_S

    def _call(self, path: str, payload: dict[str, Any] | None, timeout: float) -> Any:
        if self.clock() < self.down_until:
            return None
        ep = self.endpoint()
        if ep is None:
            self._fail("BRUH Sight is not running (no endpoint file)")
            return None
        data = None if payload is None else json.dumps(payload).encode()
        req = urllib.request.Request(
            f"http://{ep['host']}:{ep['port']}{path}", data=data,
            method="GET" if payload is None else "POST",
            headers={"X-Bruh-Token": ep["token"], "Content-Type": "application/json"})
        self.calls += 1
        try:
            with self.opener(req, timeout=timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # A 400 is our question, not the plugin being down: say it, no backoff.
            if exc.code == 400:
                try:
                    return {"error": json.loads(exc.read().decode("utf-8")).get("error")}
                except (ValueError, OSError, AttributeError):
                    return {"error": "bad request"}
            self._fail(f"BRUH Sight answered {exc.code}")
            return None
        except (OSError, ValueError) as exc:
            self._fail(f"BRUH Sight did not answer ({exc})")
            return None
        self.last_error = None
        return body

    @property
    def available(self) -> bool:
        """Whether the last word from the plugin was an answer."""
        return self.last_error is None and self.endpoint() is not None

    # -- the world -------------------------------------------------------------
    def state(self) -> dict[str, Any] | None:
        now = self.clock()
        if self._state is not None and now - self._state[0] < STATE_FRESH_S:
            return self._state[1]
        got = self._call("/v1/state", None, STATE_TIMEOUT_S)
        if not isinstance(got, dict) or not isinstance(got.get("players"), list):
            return None
        self._state = (now, got)
        return got

    def players(self) -> dict[str, dict[str, Any]] | None:
        """{name: live player} for everybody online, or None without the plugin."""
        st = self.state()
        if st is None:
            return None
        return {p["name"]: p for p in st["players"]
                if isinstance(p, dict) and isinstance(p.get("name"), str) and not p.get("error")}

    def player(self, name: str) -> dict[str, Any] | None:
        live = self.players()
        return None if live is None else live.get(name)

    def blocks(self, dimension: str, box: tuple) -> dict[tuple[int, int, int], str] | dict | None:
        """Every cell's block state in the box, air included, as it is now:
        `{(x, y, z): state}`; `{"unread": {code, why, chunk?}}` when part of
        it was never generated; `{"error": why}` for a question the plugin
        refused; None when the plugin cannot be asked (read the disk)."""
        x1, y1, z1, x2, y2, z2 = (int(v) for v in box)
        x1, x2 = sorted((x1, x2))
        y1, y2 = sorted((y1, y2))
        z1, z2 = sorted((z1, z2))
        if (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1) > BOX_MAX:
            return None
        got = self._call("/v1/blocks", {"dimension": dimension, "x1": x1, "y1": y1, "z1": z1,
                                        "x2": x2, "y2": y2, "z2": z2}, BLOCKS_TIMEOUT_S)
        if not isinstance(got, dict):
            return None
        if "unread" in got or "error" in got:
            return got
        return decode_blocks(got)

    # -- the companion's thoughts (the plugin's bubble and journal) ---------------
    def thought(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """One step of the companion's thinking for one player: the bubble
        only they see (over the allay when it is near) and the journal's
        stream. None when the plugin cannot be asked."""
        got = self._call("/v1/thought", payload, STATE_TIMEOUT_S)
        return got if isinstance(got, dict) else None

    def focus(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Where the companion is working ({x, y, z, dimension} with the
        line's `key` and/or the `player`): its body hovers there while the
        work goes on."""
        got = self._call("/v1/focus", payload, STATE_TIMEOUT_S)
        return got if isinstance(got, dict) else None

    def give_journal(self, player: str, name: str) -> dict[str, Any] | None:
        got = self._call("/v1/journal", {"player": player, "name": name}, STATE_TIMEOUT_S)
        return got if isinstance(got, dict) else None


def decode_blocks(got: dict[str, Any]) -> dict[tuple[int, int, int], str] | None:
    """The plugin's palette-and-indices answer as {(x, y, z): state}: cells
    run x, then z, then y fastest."""
    try:
        x1, y1, z1, x2, y2, z2 = (int(v) for v in got["box"])
        palette = [str(p) for p in got["palette"]]
        cells = got["cells"]
    except (KeyError, TypeError, ValueError):
        return None
    if len(cells) != (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1):
        return None
    out: dict[tuple[int, int, int], str] = {}
    i = 0
    for x in range(x1, x2 + 1):
        for z in range(z1, z2 + 1):
            for y in range(y1, y2 + 1):
                v = cells[i]
                i += 1
                out[(x, y, z)] = palette[v] if 0 <= v < len(palette) else "minecraft:air"
    return out


def live_info(p: dict[str, Any]) -> dict[str, Any]:
    """A live player in the collector's own shape (what `_poll_player`
    makes from RCON), with the extras under `live`."""
    info: dict[str, Any] = {"name": p.get("name")}
    pos = p.get("pos")
    if isinstance(pos, list) and len(pos) == 3:
        info["pos"] = [round(float(c), 1) for c in pos]
    for key in ("yaw", "pitch", "health"):
        if isinstance(p.get(key), (int, float)):
            info[key] = round(float(p[key]), 1)
    if isinstance(p.get("food"), (int, float)):
        info["food"] = int(p["food"])
    for key in ("dimension", "gamemode"):
        if isinstance(p.get(key), str):
            info[key] = p[key]
    info["live"] = {k: p[k] for k in LIVE_KEYS if p.get(k) not in (None, [], {})}
    return info


__all__ = ["Sight", "decode_blocks", "live_info", "LIVE_KEYS", "ENDPOINT"]
