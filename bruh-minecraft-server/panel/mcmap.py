#!/usr/bin/env python3
"""A top-down picture of part of a Minecraft world, read from its files.

No plugin, no server command and no package: the world's own region files
(Anvil, `r.X.Z.mca`) are read here, the top block of every column inside
a box is looked up, and the result is painted one colour per block into a
PNG written by hand (zlib and struct are the whole encoder). It is what a
finished build in the companion's build log is shown as (`mcworld.BuildLog`), and
what `level.dat` is read with when the server cannot be asked the weather.

What it can read: Java Edition worlds from 1.16 on (the block-state
packing that never spans two longs), both the 1.18+ chunk layout
(`sections` / `block_states`) and the 1.16–1.17 one (`Level` / `Sections`
/ `Palette` / `BlockStates`), zlib, gzip and uncompressed chunks, and a
chunk stored beside its region in a `.mcc` file. A chunk written with
LZ4 (an opt-in server setting since 1.20.5) is skipped: there is no LZ4
in the standard library, so its columns come out empty rather than wrong.

A world on disk is the world as of the last save. The panel asks the
server for a `save-all` before it draws a build that has just finished.
"""
from __future__ import annotations

import gzip
import os
import struct
import zlib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# NBT
# ---------------------------------------------------------------------------
TAG_END, TAG_BYTE, TAG_SHORT, TAG_INT, TAG_LONG, TAG_FLOAT, TAG_DOUBLE = range(7)
TAG_BYTE_ARRAY, TAG_STRING, TAG_LIST, TAG_COMPOUND, TAG_INT_ARRAY, TAG_LONG_ARRAY = range(7, 13)


class NbtError(ValueError):
    """The bytes are not the NBT they were said to be."""


def _payload(buf: bytes, pos: int, tag: int) -> tuple[Any, int]:
    if tag == TAG_BYTE:
        return struct.unpack_from(">b", buf, pos)[0], pos + 1
    if tag == TAG_SHORT:
        return struct.unpack_from(">h", buf, pos)[0], pos + 2
    if tag == TAG_INT:
        return struct.unpack_from(">i", buf, pos)[0], pos + 4
    if tag == TAG_LONG:
        return struct.unpack_from(">q", buf, pos)[0], pos + 8
    if tag == TAG_FLOAT:
        return struct.unpack_from(">f", buf, pos)[0], pos + 4
    if tag == TAG_DOUBLE:
        return struct.unpack_from(">d", buf, pos)[0], pos + 8
    if tag == TAG_BYTE_ARRAY:
        n = struct.unpack_from(">i", buf, pos)[0]
        pos += 4
        return bytes(buf[pos:pos + n]), pos + n
    if tag == TAG_STRING:
        n = struct.unpack_from(">H", buf, pos)[0]
        pos += 2
        return bytes(buf[pos:pos + n]).decode("utf-8", "replace"), pos + n
    if tag == TAG_LIST:
        inner = buf[pos]
        n = struct.unpack_from(">i", buf, pos + 1)[0]
        pos += 5
        out = []
        for _ in range(max(0, n)):
            value, pos = _payload(buf, pos, inner)
            out.append(value)
        return out, pos
    if tag == TAG_COMPOUND:
        out: dict[str, Any] = {}
        while True:
            inner = buf[pos]
            pos += 1
            if inner == TAG_END:
                return out, pos
            n = struct.unpack_from(">H", buf, pos)[0]
            name = bytes(buf[pos + 2:pos + 2 + n]).decode("utf-8", "replace")
            out[name], pos = _payload(buf, pos + 2 + n, inner)
    if tag == TAG_INT_ARRAY:
        n = struct.unpack_from(">i", buf, pos)[0]
        return struct.unpack_from(f">{n}i", buf, pos + 4), pos + 4 + 4 * n
    if tag == TAG_LONG_ARRAY:
        # Unsigned, because these are bit fields: a block index is read
        # with shifts and a mask, and a negative long would sign-extend.
        n = struct.unpack_from(">i", buf, pos)[0]
        return struct.unpack_from(f">{n}Q", buf, pos + 4), pos + 4 + 8 * n
    raise NbtError(f"unknown NBT tag {tag}")


def read_nbt(data: bytes) -> dict[str, Any]:
    """The root compound of an uncompressed NBT document."""
    try:
        if not data or data[0] != TAG_COMPOUND:
            raise NbtError("an NBT document starts with a compound")
        n = struct.unpack_from(">H", data, 1)[0]
        value, _ = _payload(data, 3 + n, TAG_COMPOUND)
    except (struct.error, IndexError) as exc:
        raise NbtError(f"truncated NBT: {exc}") from exc
    return value


def read_nbt_file(path: Path) -> dict[str, Any]:
    """A gzipped (level.dat) or plain NBT file's root compound."""
    raw = Path(path).read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return read_nbt(raw)


# ---------------------------------------------------------------------------
# Region files
# ---------------------------------------------------------------------------
SECTOR = 4096


def read_chunk(region_dir: Path, cx: int, cz: int) -> dict[str, Any] | None:
    """Chunk (cx, cz)'s NBT from its region file, or None if not there."""
    path = Path(region_dir) / f"r.{cx >> 5}.{cz >> 5}.mca"
    try:
        with open(path, "rb") as f:
            header = f.read(SECTOR)
            i = 4 * ((cx & 31) + (cz & 31) * 32)
            if len(header) < i + 4:
                return None
            offset = int.from_bytes(header[i:i + 3], "big")
            if offset == 0:
                return None
            f.seek(offset * SECTOR)
            head = f.read(5)
            if len(head) < 5:
                return None
            length = int.from_bytes(head[:4], "big")
            kind = head[4]
            data = f.read(max(0, length - 1))
        if kind & 0x80:
            # Too big for the region: the chunk is its own file beside it.
            data = (Path(region_dir) / f"c.{cx}.{cz}.mcc").read_bytes()
            kind &= 0x7F
        if kind == 1:
            data = gzip.decompress(data)
        elif kind == 2:
            data = zlib.decompress(data)
        elif kind != 3:
            return None   # LZ4 (4) or a custom compressor: not readable here
        return read_nbt(data)
    except (OSError, zlib.error, EOFError, NbtError):
        return None


AIR = frozenset({"air", "cave_air", "void_air", "light", "structure_void", "barrier"})


class Chunk:
    """One chunk's blocks, looked up one at a time.

    Decoding a whole section is 4096 Python operations; a top-down picture
    needs a handful per column, so each lookup unpacks only its own index.
    """

    def __init__(self, root: dict[str, Any]):
        level = root.get("Level") if isinstance(root.get("Level"), dict) else root
        self.sections: dict[int, tuple[list[str], tuple, int]] = {}
        for sec in level.get("sections") or level.get("Sections") or []:
            if not isinstance(sec, dict) or "Y" not in sec:
                continue
            states = sec.get("block_states")
            if isinstance(states, dict):
                palette, data = states.get("palette") or [], states.get("data") or ()
            else:
                palette, data = sec.get("Palette") or [], sec.get("BlockStates") or ()
            names = [_short(p.get("Name", "")) if isinstance(p, dict) else "air" for p in palette]
            if not names or all(n in AIR for n in names):
                continue
            bits = max(4, (len(names) - 1).bit_length())
            self.sections[int(sec["Y"])] = (names, tuple(data), bits)
        self.top_section = max(self.sections) if self.sections else None
        self.bottom_section = min(self.sections) if self.sections else None

    def block(self, lx: int, y: int, lz: int) -> str:
        sec = self.sections.get(y >> 4)
        if sec is None:
            return "air"
        names, data, bits = sec
        if len(names) == 1 or not data:
            return names[0]
        idx = ((y & 15) * 16 + lz) * 16 + lx
        per = 64 // bits
        word = idx // per
        if word >= len(data):
            return "air"
        v = (data[word] >> ((idx % per) * bits)) & ((1 << bits) - 1)
        return names[v] if v < len(names) else "air"

    def top(self, lx: int, lz: int, y_top: int, y_bottom: int) -> tuple[str, int] | None:
        """The highest non-air block in the column between the two heights."""
        if self.top_section is None:
            return None
        y = min(y_top, self.top_section * 16 + 15)
        floor = max(y_bottom, self.bottom_section * 16)
        while y >= floor:
            if (y >> 4) not in self.sections:
                y = (y >> 4) * 16 - 1
                continue
            name = self.block(lx, y, lz)
            if name not in AIR:
                return name, y
            y -= 1
        return None


def _short(name: str) -> str:
    return name.split(":", 1)[1] if ":" in name else name


def region_dir(world_dir: Path, dimension: str) -> Path:
    """Where a dimension's region files are, in vanilla's or Paper's layout.

    Vanilla keeps the Nether and the End inside the world folder (DIM-1,
    DIM1); Paper/Spigot give each its own world folder beside it
    (`world_nether/DIM-1`, `world_the_end/DIM1`).
    """
    world_dir = Path(world_dir)
    dim = _short(dimension or "overworld")
    if dim in ("the_nether", "nether"):
        for cand in (world_dir.parent / f"{world_dir.name}_nether" / "DIM-1" / "region",
                     world_dir / "DIM-1" / "region"):
            if cand.is_dir():
                return cand
        return world_dir / "DIM-1" / "region"
    if dim in ("the_end", "end"):
        for cand in (world_dir.parent / f"{world_dir.name}_the_end" / "DIM1" / "region",
                     world_dir / "DIM1" / "region"):
            if cand.is_dir():
                return cand
        return world_dir / "DIM1" / "region"
    return world_dir / "region"


# ---------------------------------------------------------------------------
# Colours
# ---------------------------------------------------------------------------
DYES = {
    "white": (233, 236, 236), "orange": (240, 118, 19), "magenta": (189, 68, 179),
    "light_blue": (58, 175, 217), "yellow": (248, 197, 39), "lime": (112, 185, 25),
    "pink": (237, 141, 172), "gray": (62, 68, 71), "light_gray": (142, 142, 134),
    "cyan": (21, 137, 145), "purple": (121, 42, 172), "blue": (53, 57, 157),
    "brown": (114, 71, 40), "green": (84, 109, 27), "red": (160, 39, 34),
    "black": (20, 21, 25),
}
# The first keyword a block's name contains decides its colour; the order
# matters (`grass_block` before `grass`, `redstone` before `stone`).
KEYWORDS: tuple[tuple[str, tuple[int, int, int]], ...] = (
    ("water", (52, 92, 196)), ("lava", (226, 96, 20)), ("ice", (150, 190, 240)),
    ("snow", (240, 246, 250)), ("grass_block", (98, 152, 58)), ("moss", (89, 110, 45)),
    ("leaves", (60, 120, 40)), ("short_grass", (98, 152, 58)), ("tall_grass", (98, 152, 58)),
    ("fern", (88, 140, 52)), ("vine", (70, 120, 40)), ("lily_pad", (40, 120, 40)),
    ("sandstone", (216, 203, 155)), ("red_sand", (190, 102, 33)), ("sand", (219, 207, 163)),
    ("gravel", (136, 126, 126)), ("clay", (160, 166, 179)), ("mud", (60, 57, 60)),
    ("dirt", (134, 96, 67)), ("farmland", (110, 75, 50)), ("path", (148, 122, 65)),
    ("podzol", (91, 63, 24)), ("mycelium", (111, 99, 105)),
    ("deepslate", (80, 80, 82)), ("blackstone", (42, 36, 41)), ("redstone", (170, 20, 10)),
    ("netherrack", (110, 50, 50)), ("nether_brick", (44, 22, 26)), ("soul", (81, 62, 50)),
    ("basalt", (80, 80, 86)), ("end_stone", (219, 222, 158)), ("purpur", (169, 125, 169)),
    ("obsidian", (20, 18, 30)), ("bedrock", (60, 60, 60)), ("prismarine", (99, 156, 151)),
    ("quartz", (235, 229, 222)), ("copper", (192, 107, 79)), ("gold", (246, 208, 61)),
    ("iron", (220, 220, 220)), ("diamond", (98, 237, 228)), ("emerald", (42, 203, 88)),
    ("lapis", (31, 67, 140)), ("amethyst", (133, 97, 191)), ("glowstone", (250, 213, 140)),
    ("lantern", (250, 200, 110)), ("torch", (250, 200, 110)), ("glass", (200, 230, 240)),
    ("brick", (150, 97, 83)), ("terracotta", (152, 94, 67)), ("mangrove", (117, 54, 48)),
    ("cherry", (226, 178, 172)), ("bamboo", (193, 173, 80)), ("crimson", (101, 48, 70)),
    ("warped", (43, 104, 99)), ("dark_oak", (66, 43, 20)), ("spruce", (115, 85, 49)),
    ("birch", (192, 175, 121)), ("jungle", (160, 115, 80)), ("acacia", (168, 90, 50)),
    ("oak", (162, 130, 78)), ("log", (109, 85, 50)), ("wood", (109, 85, 50)),
    ("planks", (162, 130, 78)), ("bookshelf", (117, 94, 59)), ("hay", (166, 136, 38)),
    ("pumpkin", (198, 118, 24)), ("melon", (111, 145, 30)), ("cactus", (85, 127, 43)),
    ("flower", (200, 80, 120)), ("poppy", (200, 40, 40)), ("dandelion", (240, 220, 40)),
    ("tulip", (220, 100, 60)), ("rail", (120, 110, 100)), ("chest", (163, 116, 46)),
    ("andesite", (136, 136, 136)), ("diorite", (188, 188, 188)), ("granite", (149, 103, 85)),
    ("tuff", (108, 109, 102)), ("calcite", (223, 224, 220)), ("cobblestone", (122, 122, 122)),
    ("stone", (125, 125, 125)), ("ore", (130, 130, 130)),
)
UNKNOWN = (128, 128, 128)
EMPTY = (0, 0, 0, 0)


def colour(name: str) -> tuple[int, int, int]:
    """A block's colour on the map: its dye if it has one, else a keyword's."""
    name = _short(name)
    for dye in sorted(DYES, key=len, reverse=True):
        if name.startswith(dye + "_"):
            return DYES[dye]
    for word, rgb in KEYWORDS:
        if word in name:
            return rgb
    return UNKNOWN


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
MAX_SIDE = 256          # blocks; a bigger box is drawn around its middle
TARGET_PX = 512         # the picture's longer side, roughly


def _clip(lo: int, hi: int) -> tuple[int, int]:
    lo, hi = min(lo, hi), max(lo, hi)
    if hi - lo + 1 > MAX_SIDE:
        mid = (lo + hi) // 2
        lo, hi = mid - MAX_SIDE // 2, mid - MAX_SIDE // 2 + MAX_SIDE - 1
    return lo, hi


def top_blocks(region: Path, x1: int, z1: int, x2: int, z2: int,
               y_top: int = 319, y_bottom: int = -64) -> list[list[tuple[str, int] | None]]:
    """The top block of every column in the box, as rows (north to south)."""
    x1, x2 = _clip(x1, x2)
    z1, z2 = _clip(z1, z2)
    chunks: dict[tuple[int, int], Chunk | None] = {}
    rows = []
    for z in range(z1, z2 + 1):
        row = []
        for x in range(x1, x2 + 1):
            key = (x >> 4, z >> 4)
            if key not in chunks:
                root = read_chunk(region, *key)
                chunks[key] = Chunk(root) if root else None
            chunk = chunks[key]
            row.append(chunk.top(x & 15, z & 15, y_top, y_bottom) if chunk else None)
        rows.append(row)
    return rows


def paint(rows: list[list[tuple[str, int] | None]]) -> tuple[int, int, list[bytes]]:
    """RGBA pixel rows for a grid of top blocks, shaded like an in-game map.

    A block higher than the one north of it is lighter and a lower one
    darker, which is how a Minecraft map shows height without contour lines.
    """
    h = len(rows)
    w = len(rows[0]) if h else 0
    scale = max(1, min(8, TARGET_PX // max(1, w, h)))
    out = []
    for zi, row in enumerate(rows):
        line = bytearray()
        for xi, cell in enumerate(row):
            if cell is None:
                px = EMPTY
            else:
                name, y = cell
                r, g, b = colour(name)
                north = rows[zi - 1][xi] if zi else None
                if north is not None and "water" not in name:
                    f = 1.12 if y > north[1] else 0.86 if y < north[1] else 1.0
                    r, g, b = (min(255, int(c * f)) for c in (r, g, b))
                px = (r, g, b, 255)
            line.extend(bytes(px) * scale)
        out.extend([bytes(line)] * scale)
    return w * scale, h * scale, out


def write_png(path: Path, width: int, height: int, rows: list[bytes]) -> None:
    """An RGBA PNG, written to a temporary file and moved into place."""
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (struct.pack(">I", len(body)) + kind + body
                + struct.pack(">I", zlib.crc32(kind + body) & 0xFFFFFFFF))

    raw = b"".join(b"\x00" + r for r in rows)
    png = (b"\x89PNG\r\n\x1a\n"
           + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(raw, 9))
           + chunk(b"IEND", b""))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(png)
    os.replace(tmp, path)


def render_bounds(world_dir: Path, bounds: dict[str, Any], out: Path) -> dict[str, Any]:
    """Draw a build's box from above into `out`.

    `bounds` is the build log's: x1, z1, x2, z2, optional y1/y2 (the top
    block is looked for between them) and dimension. Answers what was
    drawn, or `{"error": ...}` in words when there was nothing to draw.
    """
    try:
        x1, z1, x2, z2 = (int(bounds[k]) for k in ("x1", "z1", "x2", "z2"))
    except (KeyError, TypeError, ValueError):
        return {"error": "A picture needs the build's corners (x1, z1, x2, z2)."}
    ys = [int(bounds[k]) for k in ("y1", "y2") if isinstance(bounds.get(k), (int, float))]
    y_top, y_bottom = (max(ys), min(ys)) if len(ys) == 2 else (319, -64)
    region = region_dir(world_dir, str(bounds.get("dimension") or "overworld"))
    if not region.is_dir():
        return {"error": f"The world has no region files at {region}."}
    rows = top_blocks(region, x1, z1, x2, z2, y_top, y_bottom)
    filled = sum(1 for row in rows for c in row if c is not None)
    if not filled:
        return {"error": "Nothing is saved in that box yet (the chunks are not on disk)."}
    w, h, pixels = paint(rows)
    write_png(out, w, h, pixels)
    return {"path": str(out), "width": w, "height": h, "columns": filled}


__all__ = ["read_nbt", "read_nbt_file", "read_chunk", "Chunk", "region_dir", "colour",
           "top_blocks", "paint", "write_png", "render_bounds", "NbtError"]
