#!/usr/bin/env python3
"""The spyglass: what a player points at, for a companion to look at.

Children do not type, so pointing is how they ask: anybody who looks
through a spyglass (any spyglass) has pointed at whatever is in its middle.
Nothing in the game says so over RCON, so a small data pack does
(`datapack/bruh_companion`, installed into the world's `datapacks/` and
enabled): it counts spyglass uses (`minecraft.used:minecraft.spyglass`),
numbers each player's uses (`bruh_spy_n`) and tags the player
`bruh_pointing` for three seconds. Bedrock players through Geyser use the
same spyglass.

The panel (`Pointer.step`, on the world thread) asks once a second while
anybody is on — ONE command while nobody points — and for a player who is
tagged with a use it has not seen: their position, facing and dimension,
then a save, then a ray from their eyes through the saved region files
(`ray_target`) to the first block that is not air or a fluid within
`REACH`, and the event `bruh_minecraft_point` with what was hit and the
atlas's building and room there. Nothing is said in chat, and the tag is
never removed over RCON (the pack drops it), because an RCON `tag` is
shown to operators.
"""
from __future__ import annotations

import importlib.util
import math
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable


def _beside(name: str, filename: str):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


mcmap = _beside("bruh_mc_map", "mcmap.py")
mcworld = _beside("bruh_mc_world", "mcworld.py")

PACK = "bruh_companion"
PACK_SOURCE = Path(__file__).resolve().parent / "datapack" / PACK
TAG = "bruh_pointing"
SEQ = "bruh_spy_n"
POLL_S = 1.0               # seconds between looks while anybody is on
IDLE_S = 60.0              # the loop's beat this module asks for while nobody is
INSTALL_S = 60.0           # seconds between checks that the pack is in the world
ENABLE_RETRY_S = 15.0      # ... while it is not yet seen enabled
REACH = 96                 # blocks a ray goes
EYE = 1.62                 # a standing player's eyes above their feet
FLUIDS = frozenset({"water", "lava", "bubble_column"})
_SEQ = re.compile(r" has (-?\d+) \[")


# ---------------------------------------------------------------------------
# The ray
# ---------------------------------------------------------------------------
def direction(yaw: float, pitch: float) -> tuple[float, float, float]:
    """Minecraft's look vector: yaw 0 faces +z, -90 faces +x; pitch -90 is up."""
    y, p = math.radians(yaw), math.radians(pitch)
    return (-math.sin(y) * math.cos(p), -math.sin(p), math.cos(y) * math.cos(p))


def ray_target(region: Path, eye: tuple[float, float, float], yaw: float, pitch: float,
               reach: int = REACH) -> dict[str, Any] | None:
    """The first block from `eye` along the look that is not air or a fluid,
    within `reach` blocks: {x, y, z, block (its full state)}; None when
    there is nothing, or the ray reaches a chunk that cannot be read."""
    d = direction(yaw, pitch)
    cell = [math.floor(c) for c in eye]
    step = [1 if v > 0 else -1 if v < 0 else 0 for v in d]
    t_max, t_delta = [], []
    for i in range(3):
        if d[i] == 0:
            t_max.append(math.inf)
            t_delta.append(math.inf)
        else:
            edge = cell[i] + (1 if step[i] > 0 else 0)
            t_max.append((edge - eye[i]) / d[i])
            t_delta.append(abs(1 / d[i]))
    chunks: dict[tuple[int, int], Any] = {}
    t = 0.0
    while t <= reach:
        i = min(range(3), key=lambda k: t_max[k])
        t = t_max[i]
        if t > reach:
            break
        cell[i] += step[i]
        t_max[i] += t_delta[i]
        x, y, z = cell
        if not -64 <= y <= 319:
            return None
        key = (x >> 4, z >> 4)
        if key not in chunks:
            root = mcmap.read_chunk(region, *key)
            chunks[key] = mcmap.Chunk(root) if root else None
        chunk = chunks[key]
        if chunk is None:
            return None
        name = chunk.block(x & 15, y, z & 15)
        if name in mcmap.AIR or name in FLUIDS:
            continue
        return {"x": x, "y": y, "z": z, "block": chunk.state(x & 15, y, z & 15)}
    return None


# ---------------------------------------------------------------------------
# The data pack
# ---------------------------------------------------------------------------
def install_pack(world: Path, source: Path = PACK_SOURCE) -> bool:
    """The pack in the world's `datapacks/`, as shipped. True when anything
    was written (the server then has to enable it). A world folder that does
    not exist yet (the server has not made it) gets nothing."""
    world = Path(world)
    if not world.is_dir():
        return False
    dest = world / "datapacks" / PACK
    changed = False
    for src in sorted(p for p in source.rglob("*") if p.is_file()):
        out = dest / src.relative_to(source)
        body = src.read_bytes()
        try:
            if out.read_bytes() == body:
                continue
        except OSError:
            # Not there yet: written below.
            pass
        out.parent.mkdir(parents=True, exist_ok=True)
        mcworld.atomic_write_text(out, body.decode("utf-8"))
        changed = True
    shipped = {p.relative_to(source) for p in source.rglob("*") if p.is_file()}
    for extra in sorted(p for p in dest.rglob("*") if p.is_file()):
        if extra.relative_to(dest) not in shipped:
            extra.unlink()
            changed = True
    for folder in sorted((p for p in dest.rglob("*") if p.is_dir()), reverse=True):
        if not any(folder.iterdir()):
            shutil.rmtree(folder, ignore_errors=True)
    return changed


# ---------------------------------------------------------------------------
# The poll
# ---------------------------------------------------------------------------
class Pointer:
    """One look a second for a spyglass use, beside the collector."""

    def __init__(self, col, *, world_dir: Callable[[], Path],
                 emit: Callable[[dict[str, Any]], Any],
                 save: Callable[[], Any] = lambda: None,
                 here: Callable[[str, float, float, float], dict[str, Any]] | None = None,
                 clock: Callable[[], float] = time.time):
        self.col = col
        self.world_dir = world_dir
        self.emit = emit
        self.save = save
        self.here = here
        self.clock = clock
        self.last_poll = -1e12
        self.last_install = -1e12
        self.enabled_for: str | None = None      # the world the pack was seen enabled in
        self.seen: dict[str, int] = {}           # player -> the use last acted on
        self.points = 0

    def interval(self) -> float:
        return POLL_S if self.col.sessions else IDLE_S

    def _ask(self, cmd: str) -> str | None:
        try:
            return self.col.session.command(cmd)
        except Exception:  # noqa: BLE001 — a server that went away: the next beat asks again
            return None

    def _ensure_pack(self, now: float) -> None:
        """The pack's files in the active world (from the panel's start, so a
        server starting after it loads the pack itself), and, once the
        server answers, enabled."""
        if now - self.last_install < (INSTALL_S if self.enabled_for else ENABLE_RETRY_S):
            return
        self.last_install = now
        world = Path(self.world_dir())
        try:
            if install_pack(world):
                self.enabled_for = None
        except OSError:
            # A world folder the panel cannot write: no spyglass, the rest works.
            return
        if self.enabled_for == world.name or not self.col.reachable:
            return
        listed = self._ask("minecraft:datapack list enabled")
        if listed is None:
            return
        if f"file/{PACK}" not in listed:
            reply = self._ask(f'minecraft:datapack enable "file/{PACK}"') or ""
            if re.search(r"unknown data pack", reply, re.I):
                # Written while the server ran: it has to look at the folder again.
                self._ask("minecraft:reload")
                self._ask(f'minecraft:datapack enable "file/{PACK}"')
        self.enabled_for = world.name

    def step(self) -> None:
        now = self.clock()
        self._ensure_pack(now)
        if not self.col.sessions:
            self.seen.clear()
            return
        if now - self.last_poll < POLL_S * 0.9:
            return
        self.last_poll = now
        test = mcworld.parse_test
        if test(self._ask(f"minecraft:execute if entity @a[tag={TAG}]") or "") is not True:
            return
        for player in sorted(self.col.sessions):
            who = mcworld.quote_name(player)
            if test(self._ask(f"minecraft:execute if entity @a[name={who},tag={TAG}]")
                    or "") is not True:
                continue
            m = _SEQ.search(mcworld.plain(
                self._ask(f"minecraft:scoreboard players get {who} {SEQ}") or ""))
            seq = int(m.group(1)) if m else None
            if seq is None or self.seen.get(player) == seq:
                continue
            self.seen[player] = seq
            self._point(player)

    def _data(self, who: str, path: str) -> str | None:
        return mcworld.data_value(self._ask(f"minecraft:data get entity {who} {path}") or "")

    def _point(self, player: str) -> None:
        who = mcworld.quote_name(player)
        pos = mcworld.snbt_pos(self._data(who, "Pos"))
        facing = mcworld.snbt_floats(self._data(who, "Rotation"))
        dim = mcworld.snbt_string(self._data(who, "Dimension")) or "minecraft:overworld"
        if not pos or not facing or len(facing) != 2:
            return
        self.save()
        region = mcmap.region_dir(Path(self.world_dir()), dim)
        eye = (pos[0], pos[1] + EYE, pos[2])
        target = ray_target(region, eye, facing[0], facing[1])
        place: dict[str, Any] = {"building": None, "room": None}
        if target is not None and self.here is not None:
            try:
                place = self.here(dim, target["x"], target["y"], target["z"]) or place
            except Exception:  # noqa: BLE001 — a point is still a point without the atlas
                place = {"building": None, "room": None}
        shown = next((nick for nick, p in (getattr(self.col, "nicknames", {}) or {}).items()
                      if p == player), player)
        self.points += 1
        self.emit({"t": int(self.clock()), "kind": "point", "player": player, "shown": shown,
                   "dimension": dim, "target": target, "eye": [round(c, 2) for c in eye],
                   "yaw": facing[0], "pitch": facing[1],
                   "building": place.get("building"), "room": place.get("room")})


__all__ = ["Pointer", "ray_target", "install_pack", "direction", "PACK", "TAG", "REACH"]
