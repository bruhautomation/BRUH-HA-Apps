#!/usr/bin/env python3
"""The atlas: what is where in the whole world, read from its region files.

A companion asked to "build a couch in this room" has to know the room:
where its floor is and which cells of it are free, where the door and the
windows are, what is already in it and what it is built of. Nothing on the
server says that, so this module works it out from the saved world, in the
background, and keeps it.

* **Chunk summaries** — per chunk: the region header timestamp it was read
  at, the surface height of every column, the "placed" blocks (planks,
  bricks, glass, doors, wool, concrete, … — not terrain) as per-column
  height runs with counts by block, the road blocks on the surface, and
  the block entities that say something (signs with their words, chests,
  beds, banners). A chunk is read again only when its timestamp moves.
  Kept per region in `.bruh-world/atlas/<world>/<dimension>/r.X.Z.json`.
* **Buildings** — connected clusters of placed columns (neighbouring
  columns whose height runs overlap), each with a box, a name and rooms.
* **Rooms** — enclosed air inside a building: a flood fill bounded by
  solid blocks (doors and glass are walls), capped at `ROOM_MAX` cells,
  that never reaches outside the building's box. Each has its floor height
  and area, the free floor cells (air with headroom), doors, windows,
  light, the furniture-like blocks in and around it, the floor, wall and
  ceiling palette and a guessed kind (bedroom: a bed; kitchen: a furnace
  or smoker; storage: chests; …).
* **Roads** — clusters of path, gravel, cobble and slab on the surface that
  run beside at least one building.
* **Labels** — `label` stores a name for a room, a building or a point
  (`labels.json`); a sign names the room it is in, or the building when it
  is in no room; a protected place or a build-log entry names a building
  inside it; otherwise "the build by spawn" or "the build at x, z".

Work is bounded: `step()` summarises chunks (nearest players first) until
its time budget is spent, and the rooms of a building are worked out once
per change of its chunks. Everything is per dimension and read through
`mcmap`, so every world layout and LZ4 chunks are read.
"""
from __future__ import annotations

import base64
import importlib.util
import math
import re
import struct
import sys
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Any, Callable


def _beside(name: str, filename: str):
    """A panel module beside this file, loaded by path (as the panel does)."""
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

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
RESCAN_S = 20            # seconds between looks at the region headers
FLUSH_S = 30             # seconds a summarised region may wait to be written
RESORT_S = 10            # seconds between re-ordering the queue by who is near
STEP_BUDGET = 0.06       # seconds of work in one background pass
ROOM_MAX = 40_000        # cells in one room's flood fill
ROOM_SCAN_MAX = 300_000  # cells in a building's box that rooms are looked for in
BUILDING_MIN = 20        # placed blocks that make a building
SEGMENT_GAP = 3          # blocks of gap that split a column's placed run
ROAD_MIN = 8             # surface cells that make a road
ROAD_NEAR = 4            # blocks from a building a road counts as reaching it
QUERY_RADIUS = 64
QUERY_RADIUS_MAX = 256
ENSURE_MAX = 64          # chunks a query summarises itself when the index is behind
FREE_MAX = 512           # free floor cells listed for one room
ROOMED_PER_QUERY = 4     # buildings a query maps the rooms of
LABEL_MAX = 500
NAME_MAX = 60

DIMENSIONS = ("minecraft:overworld", "minecraft:the_nether", "minecraft:the_end")

# What people place. Matched as words in the block's name; `_NOT_PLACED`
# wins (ores, infested stone, natural terracotta).
_PLACED = re.compile(
    r"planks|bricks?\b|brick_|glass|door|wool|carpet|concrete|glazed_terracotta|stairs|slab|"
    r"fence|_wall$|bookshelf|\bbed$|_bed$|torch|lantern|chest|barrel|furnace|smoker|"
    r"crafting_table|smooth_stone|polished_|cut_|chiseled_|quartz_block|quartz_pillar|"
    r"hay_block|trapdoor|pane|ladder|sign|banner|iron_bars|scaffolding|stripped_|"
    r"cobblestone|lectern|anvil|loom|smithing|cartography|fletching|stonecutter|grindstone|"
    r"enchanting|jukebox|note_block|bell$|flower_pot|candle|sea_lantern|glowstone|"
    r"redstone_lamp|shroomlight|froglight|copper_block|cut_copper|tiles|_block_of_|"
    r"^(white|orange|magenta|light_blue|yellow|lime|pink|gray|light_gray|cyan|purple|blue|"
    r"brown|green|red|black)_terracotta$")
_NOT_PLACED = re.compile(r"_ore$|infested|^(red_)?sandstone$|^terracotta$|budding")
ROAD_BLOCKS = re.compile(r"^(dirt_path|gravel|cobblestone|mossy_cobblestone|stone_bricks|"
                         r"[a-z_]*_slab|packed_mud|mud_bricks|bricks)$")
# Blocks a room's air may hold: furniture and decoration a person walks
# round, not walls. Anything else that is not air is a wall.
_OPEN = re.compile(r"carpet|_bed$|^bed$|torch|lantern|sign|banner|flower_pot|button|lever|"
                   r"pressure_plate|rail|candle|^potted_|sapling|_head$|skull|cobweb|"
                   r"tripwire|redstone_wire|^(short_)?grass$|fern|flower|tulip|poppy|"
                   r"dandelion|azure|orchid|allium|daisy|cornflower|lily_of|"
                   r"snow$|^light$|structure_void")
_FURNITURE = re.compile(r"chest|barrel|furnace|smoker|crafting_table|bookshelf|lectern|"
                        r"anvil|brewing_stand|cauldron|composter|loom|enchanting_table|"
                        r"jukebox|smithing_table|stonecutter|grindstone|cartography_table|"
                        r"fletching_table|_bed$|carpet|note_block|bell$|flower_pot|armor_stand|"
                        r"decorated_pot|chiseled_bookshelf|beehive|campfire")
_RAISED = re.compile(r"_slab$|_stairs$|_trapdoor$|fence$")
_LIGHT = re.compile(r"torch|lantern|glowstone|sea_lantern|shroomlight|candle|redstone_lamp|"
                    r"campfire|froglight|end_rod|jack_o_lantern|beacon|light$")
_KINDS = (("bedroom", re.compile(r"_bed$|^bed$")),
          ("kitchen", re.compile(r"^(smoker|furnace|blast_furnace)$|cake|campfire")),
          ("library", re.compile(r"bookshelf|lectern|enchanting_table")),
          ("workshop", re.compile(r"crafting_table|anvil|smithing_table|stonecutter|grindstone|"
                                  r"loom|cartography_table|fletching_table")),
          ("storage", re.compile(r"^(chest|barrel|trapped_chest)$|shulker_box")))
_THINGS = {"sign": "sign", "hanging_sign": "sign", "chest": "chest", "trapped_chest": "chest",
           "barrel": "barrel", "bed": "bed", "banner": "banner", "lectern": "lectern",
           "furnace": "furnace", "smoker": "smoker", "blast_furnace": "furnace"}
_ID = re.compile(r"^(?P<kind>[bpr]):(?P<dim>[a-z0-9_./\-]+):(?P<nums>-?\d+(?::-?\d+){1,2})$")


class AtlasError(ValueError):
    """A request the atlas cannot answer as given; the message says why."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def short(name: str) -> str:
    return mcmap._short(str(name or ""))


def is_placed(name: str) -> bool:
    n = short(name)
    return bool(_PLACED.search(n)) and not _NOT_PLACED.search(n)


def is_open(name: str) -> bool:
    n = short(name)
    return n in mcmap.AIR or bool(_OPEN.search(n))


def dim_key(dimension: str | None) -> str:
    """`overworld` for minecraft:overworld, `ns/path` for anybody else's."""
    ns, path = mcmap._dimension_parts(dimension or "overworld")
    return path if ns == "minecraft" else f"{ns}/{path}"


def dim_id(key: str) -> str:
    ns, _, path = key.rpartition("/")
    return f"{ns or 'minecraft'}:{path}"


def parse_id(value: Any, kind: str) -> tuple[str, list[int]]:
    """(dimension id, numbers) from a building (`b:…`), room (`r:…`) or road id."""
    m = _ID.match(str(value or "").strip())
    if not m or m.group("kind") != kind:
        what = {"b": "building", "r": "room", "p": "road"}[kind]
        raise AtlasError(f"That is not a {what} id from the atlas.")
    return dim_id(m.group("dim")), [int(n) for n in m.group("nums").split(":")]


def _section_values(names: list[str], data: tuple, bits: int) -> list[int] | None:
    """Every palette index of a section, in block order; None when uniform."""
    if len(names) == 1 or not data:
        return None
    per = 64 // bits
    mask = (1 << bits) - 1
    shifts = [k * bits for k in range(per)]
    out: list[int] = []
    for word in data:
        out.extend((word >> s) & mask for s in shifts)
    return out[:4096]


def _component_text(value: Any) -> str:
    """The plain words of a text component (JSON or SNBT-decoded)."""
    if isinstance(value, str):
        t = value.strip()
        if t[:1] in ('{', '[', '"'):
            try:
                import json
                return _component_text(json.loads(t)) if t else ""
            except ValueError:
                return value
        return value
    if isinstance(value, list):
        return "".join(_component_text(v) for v in value)
    if isinstance(value, dict):
        return str(value.get("text") or "") + "".join(
            _component_text(v) for v in value.get("extra") or [])
    return ""


def sign_text(entity: dict[str, Any]) -> str:
    lines: list[str] = []
    for side in ("front_text", "back_text"):
        msgs = (entity.get(side) or {}).get("messages") if isinstance(entity.get(side), dict) else None
        lines += [_component_text(m) for m in msgs or []]
    lines += [_component_text(entity.get(f"Text{i}")) for i in range(1, 5) if entity.get(f"Text{i}")]
    return " ".join(" ".join(t.split()) for t in lines if t and t.strip())[:NAME_MAX * 2]


def _encode_heights(heights: list[int]) -> str:
    return base64.b64encode(struct.pack(f"<{len(heights)}h", *heights)).decode()


def _decode_heights(text: str) -> list[int]:
    raw = base64.b64decode(text or "")
    return list(struct.unpack(f"<{len(raw) // 2}h", raw))


# ---------------------------------------------------------------------------
# One chunk's summary
# ---------------------------------------------------------------------------
def summarise(root: dict[str, Any], ts: int, cx: int, cz: int) -> dict[str, Any]:
    """What the atlas keeps of chunk (cx, cz) (see the module's docstring)."""
    level = root.get("Level") if isinstance(root.get("Level"), dict) else root
    chunk = mcmap.Chunk(root)
    columns: dict[tuple[int, int], list[int]] = {}
    counts: Counter = Counter()
    for sy, (names, data, bits) in chunk.sections.items():
        placed = {i for i, n in enumerate(names) if is_placed(n)}
        if not placed:
            continue
        values = _section_values(names, data, bits)
        base = sy * 16
        if values is None:
            for idx in range(4096):
                columns.setdefault((idx & 15, (idx >> 4) & 15), []).append(base + (idx >> 8))
            counts[names[0]] += 4096
            continue
        for idx, v in enumerate(values):
            if v in placed:
                columns.setdefault((idx & 15, (idx >> 4) & 15), []).append(base + (idx >> 8))
                counts[names[v]] += 1
    cols = []
    for (lx, lz), ys in sorted(columns.items()):
        ys.sort()
        runs = [[ys[0], ys[0], 1]]
        for y in ys[1:]:
            if y - runs[-1][1] > SEGMENT_GAP:
                runs.append([y, y, 1])
            else:
                runs[-1][1] = y
                runs[-1][2] += 1
        cols.append([lx, lz, runs])
    heights, roads = [], []
    for lz in range(16):
        for lx in range(16):
            top = chunk.top(lx, lz, 319, -64)
            if top is None:
                heights.append(-32768)
                continue
            name, y = top
            heights.append(y)
            if ROAD_BLOCKS.match(name):
                roads.append([lx, lz, y, name])
    things = []
    for be in level.get("block_entities") or level.get("TileEntities") or []:
        if not isinstance(be, dict):
            continue
        kind = _THINGS.get(short(str(be.get("id") or "")))
        if not kind:
            continue
        try:
            thing = {"id": kind, "x": int(be["x"]), "y": int(be["y"]), "z": int(be["z"])}
        except (KeyError, TypeError, ValueError):
            continue
        if kind == "sign":
            thing["text"] = sign_text(be)
            if not thing["text"]:
                continue
        elif be.get("CustomName"):
            thing["text"] = _component_text(be["CustomName"])[:NAME_MAX]
        things.append(thing)
    return {"ts": int(ts), "cx": cx, "cz": cz, "cols": cols, "counts": dict(counts),
            "surface": _encode_heights(heights), "roads": roads, "things": things}


# ---------------------------------------------------------------------------
# The atlas
# ---------------------------------------------------------------------------
class Atlas:
    """The index and what is worked out from it; safe to call from the
    world thread (`step`) and request threads at once."""

    def __init__(self, world_dir: Callable[[], Path], data_dir: Path, *,
                 players: Callable[[], list[dict[str, Any]]] = lambda: [],
                 places: Callable[[], list[dict[str, Any]]] = lambda: [],
                 clock: Callable[[], float] = time.time):
        self.world_dir = world_dir
        self.base = Path(data_dir) / "atlas"
        self.players = players
        self.places = places
        self.clock = clock
        self._lock = threading.RLock()
        self._world: str | None = None
        self.regions: dict[tuple[str, int, int], dict[str, Any]] = {}
        self.index: dict[str, dict[str, Any]] = {}
        self.queue: deque = deque()
        self.queued: set[tuple[str, int, int]] = set()
        self.waiting: Counter = Counter()        # queued chunks per region
        self.dirty: set[tuple[str, int, int]] = set()
        self.last_scan = -1e12
        self.last_flush = 0.0
        self.last_sort = -1e12
        self._rooms: dict[str, tuple[tuple, list[dict[str, Any]]]] = {}
        self._labels: list[dict[str, Any]] | None = None
        self.read_chunks = 0

    # -- where things are kept ------------------------------------------------
    def _root(self) -> Path:
        world = Path(self.world_dir())
        if world.name != self._world:
            # Another world: nothing of the last one's applies.
            self._world = world.name
            self.regions, self.index, self._rooms, self._labels = {}, {}, {}, None
            self.queue.clear()
            self.queued.clear()
            self.waiting.clear()
            self.dirty.clear()
            self.last_scan = -1e12
        return self.base / re.sub(r"[^A-Za-z0-9._ -]", "_", world.name)

    def _dim_dir(self, key: str) -> Path:
        return self._root() / key.replace("/", "__")

    def _region(self, key: str, rx: int, rz: int) -> dict[str, Any]:
        rk = (key, rx, rz)
        reg = self.regions.get(rk)
        if reg is None:
            data = mcworld._read_json(self._dim_dir(key) / f"r.{rx}.{rz}.json", {})
            chunks = data.get("chunks") if isinstance(data, dict) else None
            reg = {"chunks": {tuple(int(n) for n in k.split(",")): v
                              for k, v in (chunks or {}).items() if isinstance(v, dict)}}
            self.regions[rk] = reg
        return reg

    def _index(self, key: str) -> dict[str, Any]:
        idx = self.index.get(key)
        if idx is None:
            data = mcworld._read_json(self._dim_dir(key) / "index.json", {})
            idx = data if isinstance(data, dict) else {}
            idx.setdefault("regions", {})
            self.index[key] = idx
        return idx

    def dimensions(self) -> list[str]:
        """Every dimension this world has region files for."""
        world = Path(self.world_dir())
        dims = [d for d in DIMENSIONS if mcmap.region_dir(world, d).is_dir()]
        base = world / "dimensions"
        if base.is_dir():
            for region in sorted(base.glob("*/*/region")):
                d = f"{region.parent.parent.name}:{region.parent.name}"
                if d not in dims:
                    dims.append(d)
        return dims

    # -- indexing ---------------------------------------------------------------
    def pending(self) -> int:
        with self._lock:
            return len(self.queue)

    def summary(self, dimension: str, cx: int, cz: int) -> dict[str, Any] | None:
        with self._lock:
            self._root()
            return self._region(dim_key(dimension), cx >> 5, cz >> 5)["chunks"].get((cx, cz))

    def _scan(self) -> None:
        """Queue every chunk whose header timestamp is not the one it was read at."""
        self.last_scan = self.clock()
        world = Path(self.world_dir())
        for dimension in self.dimensions():
            key = dim_key(dimension)
            idx = self._index(key)
            region_dir = mcmap.region_dir(world, dimension)
            seen = set()
            for path in sorted(region_dir.glob("r.*.*.mca")):
                name = path.stem
                seen.add(name)
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                rec = idx["regions"].setdefault(name, {"mtime": None})
                if rec.get("mtime") == mtime:
                    continue
                stamps = mcmap.chunk_timestamps(path)
                rx, rz = (int(n) for n in name.split(".")[1:3])
                reg = self._region(key, rx, rz)
                for (cx, cz), ts in stamps.items():
                    have = reg["chunks"].get((cx, cz))
                    if have is None or have.get("ts") != ts:
                        self._enqueue(key, cx, cz, ts)
                gone = [c for c in reg["chunks"] if c not in stamps]
                for c in gone:
                    reg["chunks"].pop(c, None)
                if gone:
                    self.dirty.add((key, rx, rz))
                rec["pending_mtime"] = mtime
                self._finish_regions()
            for name in [n for n in idx["regions"] if n not in seen]:
                idx["regions"].pop(name, None)
        self.last_sort = -1e12

    def _enqueue(self, key: str, cx: int, cz: int, ts: int) -> None:
        if (key, cx, cz) not in self.queued:
            self.queued.add((key, cx, cz))
            self.waiting[(key, cx >> 5, cz >> 5)] += 1
            self.queue.append((key, cx, cz, ts))

    def _take(self, item: tuple) -> None:
        key, cx, cz, ts = item
        self.queued.discard((key, cx, cz))
        self.waiting[(key, cx >> 5, cz >> 5)] -= 1
        self._summarise(key, cx, cz, ts)

    def _sort(self) -> None:
        """Nearest an online player first (spawn's corner of the world otherwise)."""
        self.last_sort = self.clock()
        spots: dict[str, list[tuple[float, float]]] = {}
        for p in self.players() or []:
            pos = p.get("pos")
            if pos:
                spots.setdefault(dim_key(p.get("dimension")), []).append((pos[0], pos[2]))

        def dist(item) -> float:
            key, cx, cz, _ = item
            pts = spots.get(key) or [(0.0, 0.0)]
            return min((cx * 16 + 8 - x) ** 2 + (cz * 16 + 8 - z) ** 2 for x, z in pts)
        self.queue = deque(sorted(self.queue, key=dist))

    def _summarise(self, key: str, cx: int, cz: int, ts: int) -> None:
        world = Path(self.world_dir())
        region = mcmap.region_dir(world, dim_id(key))
        root, status = mcmap.load_chunk(region, cx, cz)
        reg = self._region(key, cx >> 5, cz >> 5)
        if root is not None and not mcmap.has_sections(root):
            # A layout this reader does not know is not an empty chunk (#620).
            root, status = None, "unreadable:layout this panel does not know"
        if root is None:
            reg["chunks"][(cx, cz)] = {"ts": int(ts), "cx": cx, "cz": cz, "error": status}
        else:
            reg["chunks"][(cx, cz)] = summarise(root, ts, cx, cz)
        self.read_chunks += 1
        self.dirty.add((key, cx >> 5, cz >> 5))

    def _finish_regions(self) -> None:
        """A region whose queued chunks are all read is up to date at its mtime."""
        for key, idx in self.index.items():
            for name, rec in idx["regions"].items():
                if rec.get("pending_mtime") is None:
                    continue
                rx, rz = (int(n) for n in name.split(".")[1:3])
                if self.waiting[(key, rx, rz)] <= 0:
                    rec["mtime"] = rec.pop("pending_mtime")
                    self.dirty.add((key, rx, rz))

    def _flush(self) -> None:
        self.last_flush = self.clock()
        keys = set()
        for key, rx, rz in sorted(self.dirty):
            reg = self.regions.get((key, rx, rz))
            if reg is None:
                continue
            body = {"chunks": {f"{cx},{cz}": v for (cx, cz), v in reg["chunks"].items()}}
            try:
                mcworld.atomic_write_json(self._dim_dir(key) / f"r.{rx}.{rz}.json", body)
            except OSError:
                # The summaries stay in memory; the next flush tries again.
                return
            keys.add(key)
        for key in keys:
            try:
                mcworld.atomic_write_json(self._dim_dir(key) / "index.json", self._index(key))
            except OSError:
                return
        self.dirty.clear()

    def step(self, budget: float = STEP_BUDGET) -> int:
        """One bounded pass: rescan when due, then summarise chunks until the
        budget is spent (always at least one). Answers how many were read."""
        with self._lock:
            self._root()
            now = self.clock()
            if now - self.last_scan >= RESCAN_S:
                self._scan()
            if self.queue and now - self.last_sort >= RESORT_S:
                self._sort()
            deadline = time.perf_counter() + max(0.0, budget)
            done = 0
            while self.queue:
                self._take(self.queue.popleft())
                done += 1
                if time.perf_counter() >= deadline:
                    break
            if done:
                self._finish_regions()
            if self.dirty and (not self.queue or now - self.last_flush >= FLUSH_S):
                self._flush()
            if not self.queue:
                self._warm_rooms(deadline)
            return done

    def _ensure(self, key: str, cx1: int, cz1: int, cx2: int, cz2: int) -> None:
        """A query's area summarised now, when the index has not got there."""
        if self.last_scan < 0:
            self._scan()
        want = [(cx, cz) for cx in range(cx1, cx2 + 1) for cz in range(cz1, cz2 + 1)
                if (key, cx, cz) in self.queued]
        for cx, cz in want[:ENSURE_MAX]:
            item = next((q for q in self.queue if q[:3] == (key, cx, cz)), None)
            if item is None:
                continue
            self.queue.remove(item)
            self._take(item)
        if want:
            self._finish_regions()

    def _warm_rooms(self, deadline: float) -> None:
        """The rooms of the building each online player is in, ahead of being asked."""
        for p in self.players() or []:
            if time.perf_counter() >= deadline:
                return
            pos = p.get("pos")
            if not pos:
                continue
            key = dim_key(p.get("dimension"))
            b = self._building_at(key, math.floor(pos[0]), math.floor(pos[1]),
                                  math.floor(pos[2]))
            if b is not None:
                self._rooms_of(key, b)

    # -- buildings ----------------------------------------------------------------
    def _chunks_in(self, key: str, cx1: int, cz1: int, cx2: int, cz2: int):
        for cx in range(cx1, cx2 + 1):
            for cz in range(cz1, cz2 + 1):
                s = self._region(key, cx >> 5, cz >> 5)["chunks"].get((cx, cz))
                if s and not s.get("error"):
                    yield s

    def _buildings(self, key: str, cx1: int, cz1: int, cx2: int, cz2: int) -> list[dict[str, Any]]:
        """The buildings in a range of chunks (one more chunk all round is
        read, so a building on the edge is whole)."""
        nodes: list[tuple[int, int, int, int, int]] = []
        stamps = []
        for s in self._chunks_in(key, cx1 - 1, cz1 - 1, cx2 + 1, cz2 + 1):
            stamps.append((s["cx"], s["cz"], s["ts"]))
            bx, bz = s["cx"] * 16, s["cz"] * 16
            for lx, lz, runs in s.get("cols") or []:
                for y1, y2, n in runs:
                    nodes.append((bx + lx, bz + lz, y1, y2, n))
        at: dict[tuple[int, int], list[int]] = {}
        for i, (x, z, *_rest) in enumerate(nodes):
            at.setdefault((x, z), []).append(i)
        parent = list(range(len(nodes)))

        def find(i: int) -> int:
            while parent[i] != i:
                parent[i] = parent[parent[i]]
                i = parent[i]
            return i

        for i, (x, z, y1, y2, _n) in enumerate(nodes):
            for dx in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for j in at.get((x + dx, z + dz), ()):
                        if j > i and nodes[j][2] <= y2 + 2 and y1 <= nodes[j][3] + 2:
                            a, b = find(i), find(j)
                            if a != b:
                                parent[b] = a
        groups: dict[int, list[int]] = {}
        for i in range(len(nodes)):
            groups.setdefault(find(i), []).append(i)
        out = []
        for members in groups.values():
            count = sum(nodes[i][4] for i in members)
            if count < BUILDING_MIN:
                continue
            xs = [nodes[i][0] for i in members]
            zs = [nodes[i][1] for i in members]
            box = {"x1": min(xs), "y1": min(nodes[i][2] for i in members), "z1": min(zs),
                   "x2": max(xs), "y2": max(nodes[i][3] for i in members), "z2": max(zs)}
            if box["x2"] >> 4 < cx1 or box["x1"] >> 4 > cx2 or box["z2"] >> 4 < cz1 \
                    or box["z1"] >> 4 > cz2:
                continue
            out.append({"id": f"b:{key}:{box['x1']}:{box['z1']}", "dimension": dim_id(key),
                        "box": box, "blocks": count,
                        "columns": {(nodes[i][0], nodes[i][1]) for i in members}})
        out.sort(key=lambda b: (b["box"]["x1"], b["box"]["z1"]))
        return out

    def _building_at(self, key: str, x: int, y: int, z: int) -> dict[str, Any] | None:
        for b in self._buildings(key, x >> 4, z >> 4, x >> 4, z >> 4):
            box = b["box"]
            if box["x1"] <= x <= box["x2"] and box["z1"] <= z <= box["z2"] \
                    and box["y1"] - 2 <= y <= box["y2"] + 2:
                return b
        return None

    # -- rooms ----------------------------------------------------------------------
    def _rooms_of(self, key: str, b: dict[str, Any]) -> list[dict[str, Any]]:
        """The rooms of one building, worked out once per change of its chunks."""
        box = b["box"]
        stamps = tuple((s["cx"], s["cz"], s["ts"]) for s in self._chunks_in(
            key, (box["x1"] - 1) >> 4, (box["z1"] - 1) >> 4, (box["x2"] + 1) >> 4,
            (box["z2"] + 1) >> 4))
        cached = self._rooms.get(b["id"])
        if cached and cached[0] == stamps:
            return cached[1]
        rooms = find_rooms(mcmap.region_dir(Path(self.world_dir()), dim_id(key)), key, b)
        self._rooms[b["id"]] = (stamps, rooms)
        return rooms

    # -- labels ---------------------------------------------------------------------
    def _labels_path(self) -> Path:
        return self._root() / "labels.json"

    def labels(self) -> list[dict[str, Any]]:
        if self._labels is None:
            data = mcworld._read_json(self._labels_path(), {})
            rows = data.get("labels") if isinstance(data, dict) else None
            self._labels = [r for r in rows or [] if isinstance(r, dict) and r.get("name")]
        return self._labels

    def _save_labels(self) -> None:
        mcworld.atomic_write_json(self._labels_path(), {"labels": self.labels()[-LABEL_MAX:]})

    def _things_in(self, key: str, box: dict[str, int]) -> list[dict[str, Any]]:
        out = []
        for s in self._chunks_in(key, box["x1"] >> 4, box["z1"] >> 4, box["x2"] >> 4,
                                 box["z2"] >> 4):
            out += [t for t in s.get("things") or []
                    if box["x1"] <= t["x"] <= box["x2"] and box["z1"] <= t["z"] <= box["z2"]
                    and box["y1"] - 1 <= t["y"] <= box["y2"] + 1]
        return out

    def _named(self, key: str, b: dict[str, Any], rooms: list[dict[str, Any]] | None
               ) -> dict[str, Any]:
        """A building (and its rooms) with names: a label, a sign, a place, or where it is."""
        dim = dim_id(key)
        box = b["box"]
        labels = [lab for lab in self.labels() if lab.get("dimension") == dim]
        signs = [t for t in self._things_in(key, box) if t["id"] == "sign"]
        named_rooms = []
        in_rooms = set()
        for r in rooms or []:
            cells = r["_cells"]
            name, source = None, None
            for lab in reversed(labels):
                if lab.get("target") == "room" and (lab["x"], lab["y"], lab["z"]) in cells:
                    name, source = lab["name"], "label"
                    break
            for t in signs:
                if (t["x"], t["y"], t["z"]) in cells or any(
                        (t["x"] + d[0], t["y"] + d[1], t["z"] + d[2]) in cells
                        for d in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1))):
                    in_rooms.add((t["x"], t["y"], t["z"]))
                    if name is None:
                        name, source = t["text"], "sign"
            if name is None:
                name = f"the {r['kind']}" if r["kind"] != "room" else "a room"
                source = "kind"
            named_rooms.append({**{k: v for k, v in r.items() if not k.startswith("_")},
                                "name": name[:NAME_MAX], "named_by": source})
        name, source = None, None
        for lab in reversed(labels):
            if lab.get("target") == "building" and box["x1"] <= lab["x"] <= box["x2"] \
                    and box["z1"] <= lab["z"] <= box["z2"]:
                name, source = lab["name"], "label"
                break
        if name is None:
            for t in signs:
                if (t["x"], t["y"], t["z"]) not in in_rooms:
                    name, source = t["text"], "sign"
                    break
        cx, cz = (box["x1"] + box["x2"]) / 2, (box["z1"] + box["z2"]) / 2
        if name is None:
            for p in self.places() or []:
                try:
                    px, pz, rad = float(p["x"]), float(p["z"]), float(p.get("radius") or 32)
                except (KeyError, TypeError, ValueError):
                    continue
                if (p.get("dimension") or "minecraft:overworld") != dim:
                    continue
                if (px - cx) ** 2 + (pz - cz) ** 2 <= rad ** 2:
                    name = "the build by spawn" if p.get("name") == "spawn" else str(p["name"])
                    source = "place"
                    break
        if name is None:
            name, source = f"the build at {round(cx)}, {round(cz)}", "where"
        for r in named_rooms:
            r["building"] = b["id"]
        return {"id": b["id"], "dimension": dim, "name": name[:NAME_MAX], "named_by": source,
                "box": dict(box), "blocks": b["blocks"],
                "rooms": named_rooms if rooms is not None else None}

    # -- reading ---------------------------------------------------------------------
    def _player(self, name: Any) -> dict[str, Any]:
        want = re.sub(r"^[.*]", "", str(name or "").strip()).lower()
        for p in self.players() or []:
            if re.sub(r"^[.*]", "", str(p.get("name") or "")).lower() == want and p.get("pos"):
                return p
        raise AtlasError(f"{name} is not in the game, or where they are is not known yet.")

    def _where(self, player: Any, x: Any, y: Any, z: Any, dimension: Any,
               need_y: bool = False) -> tuple[str, float, float | None, float]:
        if player:
            p = self._player(player)
            pos = p["pos"]
            return dim_key(p.get("dimension")), pos[0], pos[1], pos[2]
        try:
            fx, fz = float(x), float(z)
            fy = float(y) if y is not None else None
        except (TypeError, ValueError):
            raise AtlasError("Give a player, or x and z (and y).") from None
        if need_y and fy is None:
            raise AtlasError("Give a player, or x, y and z.")
        return dim_key(str(dimension or "minecraft:overworld")), fx, fy, fz

    def _here(self, key: str, x: float, y: float | None, z: float, compute: bool
              ) -> dict[str, Any]:
        bx, bz = math.floor(x), math.floor(z)
        by = math.floor(y) if y is not None else None
        b = None
        for cand in self._buildings(key, bx >> 4, bz >> 4, bx >> 4, bz >> 4):
            box = cand["box"]
            if box["x1"] <= bx <= box["x2"] and box["z1"] <= bz <= box["z2"] and (
                    by is None or box["y1"] - 2 <= by <= box["y2"] + 2):
                b = cand
                break
        if b is None:
            return {"building": None, "room": None, "_cells": None}
        if compute:
            rooms = self._rooms_of(key, b)
        else:
            cached = self._rooms.get(b["id"])
            rooms = cached[1] if cached else None
        named = self._named(key, b, rooms)
        room, cells = None, None
        if by is not None:
            for r, raw in zip(named["rooms"] or [], rooms or []):
                if (bx, by, bz) in raw["_cells"] or (bx, by + 1, bz) in raw["_cells"]:
                    room, cells = r, raw["_cells"]
                    break
        return {"building": named, "room": room, "_cells": cells}

    def here(self, dimension: str | None, x: float, y: float, z: float) -> dict[str, Any]:
        """The building and room a point is in, from what is already worked
        out (cheap: for the world snapshot). Ids and names only."""
        with self._lock:
            self._root()
            got = self._here(dim_key(dimension), x, y, z, compute=False)
        b, r = got["building"], got["room"]
        return {"building": {"id": b["id"], "name": b["name"]} if b else None,
                "room": {"id": r["id"], "name": r["name"], "kind": r["kind"]} if r else None}

    def query(self, player: Any = None, x: Any = None, z: Any = None, y: Any = None,
              dimension: Any = None, radius: Any = None, query: Any = None) -> dict[str, Any]:
        """The buildings and roads near a player or a point, the building and
        room it is in (`here`), and a search of names and signs (`query`)."""
        with self._lock:
            self._root()
            if query and not player and x is None and z is None:
                return self._search_world(dim_key(str(dimension or "minecraft:overworld")),
                                          str(query))
            key, fx, fy, fz = self._where(player, x, y, z, dimension)
            try:
                rad = max(8, min(QUERY_RADIUS_MAX, int(radius or QUERY_RADIUS)))
            except (TypeError, ValueError):
                raise AtlasError("radius is a number of blocks.") from None
            cx1, cz1 = math.floor(fx - rad) >> 4, math.floor(fz - rad) >> 4
            cx2, cz2 = math.floor(fx + rad) >> 4, math.floor(fz + rad) >> 4
            self._ensure(key, cx1 - 1, cz1 - 1, cx2 + 1, cz2 + 1)
            found = []
            for b in self._buildings(key, cx1, cz1, cx2, cz2):
                box = b["box"]
                dx = max(box["x1"] - fx, 0, fx - box["x2"])
                dz = max(box["z1"] - fz, 0, fz - box["z2"])
                d = math.hypot(dx, dz)
                if d <= rad:
                    found.append((d, b))
            found.sort(key=lambda t: t[0])
            buildings = []
            for i, (d, b) in enumerate(found):
                rooms = self._rooms_of(key, b) if i < ROOMED_PER_QUERY else (
                    self._rooms.get(b["id"], (None, None))[1])
                named = self._named(key, b, rooms)
                if named["rooms"] is not None:
                    named["rooms"] = [{k: r[k] for k in ("id", "name", "kind", "floor_y",
                                                         "floor_area", "free_count")}
                                      for r in named["rooms"]]
                buildings.append({**named, "distance": round(d)})
            roads = self._roads(key, cx1, cz1, cx2, cz2, [b for _, b in found])
            here = self._here(key, fx, fy, fz, compute=True)
            if here["building"]:
                here["building"] = {k: here["building"][k] for k in ("id", "name", "box")}
            if here["room"]:
                here["room"] = {k: here["room"][k] for k in ("id", "name", "kind", "floor_y",
                                                               "free_count")}
            out = {"dimension": dim_id(key), "center": {"x": round(fx), "z": round(fz)},
                   "radius": rad, "here": here, "buildings": buildings, "roads": roads,
                   "indexed": {"pending": len(self.queue)}}
            if query:
                out["query"] = str(query)[:NAME_MAX]
                out["matches"] = self._search(key, str(query), buildings, cx1, cz1, cx2, cz2)
            return out

    def _search_world(self, key: str, text: str) -> dict[str, Any]:
        """A name search with no place to look: the named places and signs of
        the whole dimension, from what is already indexed."""
        words = [w for w in re.findall(r"[\w']+", text.lower()) if w]
        dim = dim_id(key)
        out: list[dict[str, Any]] = []
        if self.last_scan < 0:
            self._scan()

        def hit(name: Any) -> bool:
            low = str(name or "").lower()
            return bool(words) and all(w in low for w in words)
        for lab in self.labels():
            if lab.get("dimension") == dim and hit(lab["name"]):
                out.append({"kind": "place" if lab.get("target") == "point" else lab["target"],
                            "name": lab["name"], "x": lab["x"], "y": lab["y"], "z": lab["z"]})
        for rx, rz in sorted(tuple(int(n) for n in name[2:].split("."))
                             for name in self._index(key)["regions"]):
            for s in self._region(key, rx, rz)["chunks"].values():
                if s.get("error"):
                    continue
                for t in s.get("things") or []:
                    if t["id"] == "sign" and hit(t.get("text")):
                        out.append({"kind": "sign", "name": t["text"], "x": t["x"],
                                    "y": t["y"], "z": t["z"]})
        return {"dimension": dim, "query": text[:NAME_MAX], "matches": out[:40],
                "indexed": {"pending": len(self.queue)}}

    def _search(self, key: str, text: str, buildings: list[dict[str, Any]],
                cx1: int, cz1: int, cx2: int, cz2: int) -> list[dict[str, Any]]:
        words = [w for w in re.findall(r"[\w']+", text.lower()) if w]
        if not words:
            return []

        def hit(name: str) -> bool:
            low = str(name or "").lower()
            return all(w in low for w in words)
        out: list[dict[str, Any]] = []
        seen = set()

        def add(row: dict[str, Any]) -> None:
            k = (row["kind"], row.get("id") or row["name"])
            if k not in seen:
                seen.add(k)
                out.append(row)
        for b in buildings:
            if hit(b["name"]):
                add({"kind": "building", "id": b["id"], "name": b["name"]})
            for r in b.get("rooms") or []:
                if hit(r["name"]):
                    add({"kind": "room", "id": r["id"], "name": r["name"], "building": b["id"]})
        dim = dim_id(key)
        for lab in self.labels():
            if lab.get("dimension") == dim and hit(lab["name"]) and lab.get("target") == "point":
                add({"kind": "place", "name": lab["name"], "x": lab["x"], "y": lab["y"],
                     "z": lab["z"]})
        for s in self._chunks_in(key, cx1, cz1, cx2, cz2):
            for t in s.get("things") or []:
                if t["id"] == "sign" and hit(t.get("text")):
                    add({"kind": "sign", "name": t["text"], "x": t["x"], "y": t["y"],
                         "z": t["z"]})
        return out[:40]

    def _roads(self, key: str, cx1: int, cz1: int, cx2: int, cz2: int,
               buildings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        cells: dict[tuple[int, int], tuple[int, str]] = {}
        inside = set()
        for b in buildings:
            inside |= b["columns"]
        for s in self._chunks_in(key, cx1, cz1, cx2, cz2):
            for lx, lz, y, name in s.get("roads") or []:
                c = (s["cx"] * 16 + lx, s["cz"] * 16 + lz)
                if c not in inside:
                    cells[c] = (y, name)
        seen: set[tuple[int, int]] = set()
        out = []
        for start in sorted(cells):
            if start in seen:
                continue
            group, todo = [], [start]
            seen.add(start)
            while todo:
                c = todo.pop()
                group.append(c)
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        n = (c[0] + dx, c[1] + dz)
                        if n in cells and n not in seen and abs(cells[n][0] - cells[c][0]) <= 1:
                            seen.add(n)
                            todo.append(n)
            if len(group) < ROAD_MIN:
                continue
            connects = []
            for b in buildings:
                box = b["box"]
                if any(box["x1"] - ROAD_NEAR <= x <= box["x2"] + ROAD_NEAR
                       and box["z1"] - ROAD_NEAR <= z <= box["z2"] + ROAD_NEAR for x, z in group):
                    connects.append(b["id"])
            if not connects:
                continue
            xs, zs = [c[0] for c in group], [c[1] for c in group]
            material = Counter(cells[c][1] for c in group).most_common(1)[0][0]
            out.append({"id": f"p:{key}:{min(xs)}:{min(zs)}", "cells": len(group),
                        "box": {"x1": min(xs), "z1": min(zs), "x2": max(xs), "z2": max(zs)},
                        "material": material, "connects": connects})
        return out

    def room(self, player: Any = None, room: Any = None, x: Any = None, y: Any = None,
             z: Any = None, dimension: Any = None) -> dict[str, Any]:
        """One room in full: where a player stands, a room id, or a point."""
        with self._lock:
            self._root()
            if room:
                dim, nums = parse_id(room, "r")
                if len(nums) != 3:
                    raise AtlasError("That is not a room id from the atlas.")
                key, (fx, fy, fz) = dim_key(dim), nums
            else:
                key, fx, fy, fz = self._where(player, x, y, z, dimension, need_y=True)
            bx, bz = math.floor(fx), math.floor(fz)
            self._ensure(key, (bx >> 4) - 1, (bz >> 4) - 1, (bx >> 4) + 1, (bz >> 4) + 1)
            got = self._here(key, fx, fy, fz, compute=True)
            if got["room"] is None:
                where = "That point" if not player else f"{player}"
                raise AtlasError(f"{where} is not in a room the atlas knows: no enclosed space "
                                 "inside a building there"
                                 + (f" (it is in {got['building']['name']})."
                                    if got["building"] else "."))
            b = got["building"]
            return {"room": got["room"], "building": {"id": b["id"], "name": b["name"],
                                                      "box": b["box"]},
                    "dimension": dim_id(key)}

    def label(self, name: Any, by: Any = "", room: Any = None, building: Any = None,
              x: Any = None, y: Any = None, z: Any = None, dimension: Any = None
              ) -> dict[str, Any]:
        """Name a room, a building or a point; a newer name for the same
        thing replaces the older."""
        text = " ".join(str(name or "").split())[:NAME_MAX]
        if not text:
            raise AtlasError("What is it called?")
        with self._lock:
            self._root()
            if room:
                dim, nums = parse_id(room, "r")
                if len(nums) != 3:
                    raise AtlasError("That is not a room id from the atlas.")
                key, (px, py, pz) = dim_key(dim), nums
                got = self._here(key, px, py, pz, compute=True)
                if got["room"] is None:
                    raise AtlasError("That room is not there any more.")
                target, tid = "room", got["room"]["id"]
            elif building:
                dim, nums = parse_id(building, "b")
                key = dim_key(dim)
                bx, bz = nums[0], nums[1]
                b = next((c for c in self._buildings(key, bx >> 4, bz >> 4, bx >> 4, bz >> 4)
                          if c["id"] == building), None)
                if b is None:
                    raise AtlasError("That building is not there any more.")
                box = b["box"]
                px, py, pz = (box["x1"] + box["x2"]) // 2, box["y1"], (box["z1"] + box["z2"]) // 2
                target, tid = "building", b["id"]
            else:
                key, fx, fy, fz = self._where(None, x, y, z, dimension, need_y=True)
                px, py, pz = math.floor(fx), math.floor(fy), math.floor(fz)
                got = self._here(key, px, py, pz, compute=True)
                if got["room"] is not None:
                    target, tid = "room", got["room"]["id"]
                    if (px, py, pz) not in got["_cells"]:
                        py += 1          # the feet's cell is the floor's; the room is above
                elif got["building"] is not None:
                    target, tid = "building", got["building"]["id"]
                else:
                    target, tid = "point", None
            dim = dim_id(key)
            rows = self.labels()
            if tid:
                rows[:] = [r for r in rows if r.get("of") != tid]
            else:
                rows[:] = [r for r in rows if not (
                    r.get("target") == "point" and r.get("dimension") == dim
                    and abs(r["x"] - px) <= 1 and abs(r["y"] - py) <= 1 and abs(r["z"] - pz) <= 1)]
            rec = {"name": text, "by": " ".join(str(by or "").split())[:40], "target": target,
                   "of": tid, "dimension": dim, "x": px, "y": py, "z": pz,
                   "t": int(self.clock())}
            rows.append(rec)
            self._save_labels()
            return {"label": rec}


# ---------------------------------------------------------------------------
# Rooms: enclosed air inside a building
# ---------------------------------------------------------------------------
class _Blocks:
    """Block names (and states) looked up through a small chunk cache."""

    def __init__(self, region: Path):
        self.region = region
        self.chunks: dict[tuple[int, int], Any] = {}

    def chunk(self, x: int, z: int):
        key = (x >> 4, z >> 4)
        if key not in self.chunks:
            root = mcmap.read_chunk(self.region, *key)
            self.chunks[key] = mcmap.Chunk(root) if root else None
        return self.chunks[key]

    def name(self, x: int, y: int, z: int) -> str:
        c = self.chunk(x, z)
        return c.block(x & 15, y, z & 15) if c is not None else "air"


def _kind(furniture: Counter) -> str:
    for kind, pattern in _KINDS:
        n = sum(v for k, v in furniture.items() if pattern.search(k))
        if n and (kind != "storage" or n >= 2):
            return kind
    return "room"


def find_rooms(region: Path, key: str, b: dict[str, Any]) -> list[dict[str, Any]]:
    """Every enclosed air volume in a building's box (one block of margin):
    a flood fill over open cells that never reaches the margin. Rooms
    larger than ROOM_MAX are open space, not rooms."""
    box = b["box"]
    x1, x2 = box["x1"] - 1, box["x2"] + 1
    z1, z2 = box["z1"] - 1, box["z2"] + 1
    y1, y2 = max(-64, box["y1"] - 1), min(319, box["y2"] + 1)
    if (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1) > ROOM_SCAN_MAX:
        return []
    blocks = _Blocks(region)
    names: dict[tuple[int, int, int], str] = {}

    def name(c: tuple[int, int, int]) -> str:
        n = names.get(c)
        if n is None:
            n = names[c] = blocks.name(*c)
        return n

    visited: set[tuple[int, int, int]] = set()
    rooms = []
    sides = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))
    for y in range(y1 + 1, y2):
        for x in range(x1 + 1, x2):
            for z in range(z1 + 1, z2):
                seed = (x, y, z)
                if seed in visited or not is_open(name(seed)):
                    continue
                cells, todo, leaked = [], [seed], False
                visited.add(seed)
                while todo:
                    c = todo.pop()
                    cells.append(c)
                    for d in sides:
                        n = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
                        if n in visited:
                            continue
                        if not (x1 < n[0] < x2 and y1 < n[1] < y2 and z1 < n[2] < z2):
                            if is_open(name(n)):
                                leaked = True
                            continue
                        if is_open(name(n)):
                            visited.add(n)
                            todo.append(n)
                if leaked or len(cells) > ROOM_MAX:
                    continue
                room = _describe(key, cells, name)
                if room is not None:
                    rooms.append(room)
    return rooms


def _describe(key: str, cells: list[tuple[int, int, int]],
              name: Callable[[tuple[int, int, int]], str]) -> dict[str, Any] | None:
    cellset = set(cells)
    floor = [c for c in cells if (c[0], c[1] - 1, c[2]) not in cellset]
    columns = {(c[0], c[2]) for c in cells}
    if len(columns) < 2 or not any((c[0], c[1] + 1, c[2]) in cellset for c in floor):
        return None            # a gap in a wall, not a room
    floor_y = Counter(c[1] for c in floor).most_common(1)[0][0]
    level = [c for c in floor if c[1] == floor_y]
    free = sorted([list(c) for c in level
                   if short(name(c)) in mcmap.AIR and (c[0], c[1] + 1, c[2]) in cellset
                   and short(name((c[0], c[1] + 1, c[2]))) in mcmap.AIR],
                  key=lambda c: (c[1], c[2], c[0]))
    doors, windows, lights = set(), set(), set()
    furniture: Counter = Counter()
    things: list[dict[str, Any]] = []
    walls: Counter = Counter()
    floors: Counter = Counter()
    ceilings: Counter = Counter()
    seen_out: set[tuple[int, int, int]] = set()
    for c in cells:
        n = short(name(c))
        if n not in mcmap.AIR:
            if _LIGHT.search(n):
                lights.add(c)
            if _FURNITURE.search(n):
                furniture[n] += 1
                things.append({"block": n, "x": c[0], "y": c[1], "z": c[2]})
        for d in ((1, 0, 0), (-1, 0, 0), (0, 0, 1), (0, 0, -1), (0, 1, 0), (0, -1, 0)):
            o = (c[0] + d[0], c[1] + d[1], c[2] + d[2])
            if o in cellset or o in seen_out:
                continue
            seen_out.add(o)
            on = short(name(o))
            if "door" in on and "trapdoor" not in on:
                lower = (o[0], o[1] - 1, o[2])
                doors.add(lower if "door" in short(name(lower)) else o)
                continue
            if "glass" in on:
                windows.add(o)
                continue
            if _LIGHT.search(on):
                lights.add(o)
            if _FURNITURE.search(on) or (_RAISED.search(on) and o[1] >= floor_y
                                         and d[1] == 0):
                furniture[on] += 1
                things.append({"block": on, "x": o[0], "y": o[1], "z": o[2]})
                continue
            if d[1] == -1:
                floors[on] += 1
            elif d[1] == 1:
                ceilings[on] += 1
            else:
                walls[on] += 1
    seed = min(cells, key=lambda c: (c[1], c[0], c[2]))
    xs, ys, zs = [c[0] for c in cells], [c[1] for c in cells], [c[2] for c in cells]
    return {
        "id": f"r:{key}:{seed[0]}:{seed[1]}:{seed[2]}",
        "kind": _kind(furniture), "floor_y": floor_y, "floor_area": len(level),
        "cells": len(cells), "height": max(ys) - min(ys) + 1,
        "box": {"x1": min(xs), "y1": min(ys), "z1": min(zs),
                "x2": max(xs), "y2": max(ys), "z2": max(zs)},
        "free_count": len(free), "free_floor": free[:FREE_MAX],
        "doors": sorted([list(d) for d in doors]),
        "windows": sorted([list(w) for w in windows])[:40],
        "light": {"sources": len(lights), "windows": len(windows)},
        "furniture": dict(furniture), "things": things[:60],
        "palette": {"floor": [n for n, _ in floors.most_common(3)],
                    "walls": [n for n, _ in walls.most_common(3)],
                    "ceiling": [n for n, _ in ceilings.most_common(3)]},
        "_cells": cellset,
    }


__all__ = ["Atlas", "AtlasError", "summarise", "find_rooms", "is_placed", "is_open",
           "dim_key", "dim_id", "parse_id", "sign_text"]
