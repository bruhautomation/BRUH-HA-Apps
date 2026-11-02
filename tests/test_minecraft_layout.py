"""Where a world's blocks are on disk, and why a box could not be read.

Two house reports: `look` and the undoable `edit` refused every area with
"Part of that area is not saved on disk yet…", even an 8x4x8 box at a
player's feet right after `save-all flush`, on a Paper 26.3 server.
Minecraft 26.1 moved each dimension's data to
`<world>/dimensions/<namespace>/<path>/` (Paper too), and the reader only
knew `<world>/region`, `DIM-1`, `DIM1` and Paper's `world_nether` /
`world_the_end` folders — so every chunk was "not on disk".

These build tiny worlds in both layouts (a region file written here), read
them in the overworld and the Nether, read a chunk compressed with LZ4
(lz4-java's "LZ4Block" stream, region compression type 4), and check that
a box that cannot be read says which of the three causes it was.
"""
from __future__ import annotations

import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from test_minecraft_world import mcmap, nbt_root, section  # noqa: E402

TS = 1_790_000_000


# ---------------------------------------------------------------------------
# A region file, written the way the server does
# ---------------------------------------------------------------------------
def lz4_block(data: bytes) -> bytes:
    """A raw LZ4 block (greedy, 4-byte hash matches) — enough to give the
    decoder literals, matches, long lengths and overlapping copies."""
    out = bytearray()
    n = len(data)
    table: dict[bytes, int] = {}
    anchor = i = 0

    def length_bytes(v: int) -> bytes:
        b = bytearray()
        while v >= 255:
            b.append(255)
            v -= 255
        b.append(v)
        return bytes(b)

    while i + 12 <= n:
        key = data[i:i + 4]
        cand = table.get(key)
        table[key] = i
        if cand is None or i - cand > 65535:
            i += 1
            continue
        m = 4
        while i + m < n - 5 and data[cand + m] == data[i + m]:
            m += 1
        lit = i - anchor
        token = (min(lit, 15) << 4) | min(m - 4, 15)
        out.append(token)
        if lit >= 15:
            out += length_bytes(lit - 15)
        out += data[anchor:i]
        out += struct.pack("<H", i - cand)
        if m - 4 >= 15:
            out += length_bytes(m - 4 - 15)
        i += m
        anchor = i
    lit = n - anchor
    out.append(min(lit, 15) << 4)
    if lit >= 15:
        out += length_bytes(lit - 15)
    out += data[anchor:]
    return bytes(out)


def lz4_stream(data: bytes, block: int = 1 << 16) -> bytes:
    """lz4-java's LZ4BlockOutputStream: blocks of `block` bytes, each with
    the magic, a token, both lengths and an xxHash32 checksum, then an
    empty block that ends the stream."""
    level = max(0, (block - 1).bit_length() - 10)
    out = bytearray()
    for start in range(0, len(data), block):
        part = data[start:start + block]
        packed = lz4_block(part)
        check = mcmap.xxh32(part, mcmap.LZ4_SEED) & 0x0FFFFFFF
        if len(packed) >= len(part):
            out += b"LZ4Block" + bytes([0x10 | level]) + struct.pack(
                "<iii", len(part), len(part), check) + part
        else:
            out += b"LZ4Block" + bytes([0x20 | level]) + struct.pack(
                "<iii", len(packed), len(part), check) + packed
    out += b"LZ4Block" + bytes([0x10 | level]) + struct.pack("<iii", 0, 0, 0)
    return bytes(out)


def region_file(chunks: dict, kind: int = 2, ts: int | dict = TS) -> bytes:
    """An .mca holding {(cx, cz): chunk NBT bytes}, with the location and
    timestamp tables, compressed as `kind` (2 zlib, 3 none, 4 LZ4, 99 a
    compressor nobody knows)."""
    header = bytearray(8192)
    body = b""
    sector = 2
    for (cx, cz), nbt in chunks.items():
        data = {2: zlib.compress, 3: bytes, 4: lz4_stream}.get(kind, bytes)(nbt)
        blob = struct.pack(">I", len(data) + 1) + bytes([kind]) + data
        blob += b"\x00" * (-len(blob) % 4096)
        i = 4 * ((cx & 31) + (cz & 31) * 32)
        header[i:i + 3] = sector.to_bytes(3, "big")
        header[i + 3] = len(blob) // 4096
        stamp = ts.get((cx, cz), TS) if isinstance(ts, dict) else ts
        header[4096 + i:4096 + i + 4] = stamp.to_bytes(4, "big")
        body += blob
        sector += len(blob) // 4096
    return bytes(header) + body


def chunk_nbt(sections, block_entities=None) -> bytes:
    fields = {"DataVersion": ("int", 4700), "sections": ("list", ("compound", sections))}
    if block_entities is not None:
        fields["block_entities"] = ("list", ("compound", block_entities))
    return nbt_root(fields)


def write_region(region: Path, chunks: dict, kind: int = 2, ts=TS) -> None:
    region.mkdir(parents=True, exist_ok=True)
    by_file: dict = {}
    for (cx, cz), nbt in chunks.items():
        by_file.setdefault((cx >> 5, cz >> 5), {})[(cx, cz)] = nbt
    for (rx, rz), part in by_file.items():
        (region / f"r.{rx}.{rz}.mca").write_bytes(region_file(part, kind, ts))


def a_floor(y_section: int = 4, block: str = "minecraft:oak_planks"):
    """One chunk: a floor of `block` at local y 0 of the section."""
    return chunk_nbt([section(y_section, ["minecraft:air", block],
                              {(x, 0, z): 1 for x in range(16) for z in range(16)})])


class TestTheWorldLayouts(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.server = Path(tmp.name)
        self.world = self.server / "world"

    def test_26_1_keeps_every_dimension_under_dimensions(self):
        new_ow = self.world / "dimensions" / "minecraft" / "overworld" / "region"
        new_nether = self.world / "dimensions" / "minecraft" / "the_nether" / "region"
        write_region(new_ow, {(0, 0): a_floor()})
        write_region(new_nether, {(0, 0): a_floor(4, "minecraft:nether_bricks")})
        self.assertEqual(mcmap.region_dir(self.world, "minecraft:overworld"), new_ow)
        self.assertEqual(mcmap.region_dir(self.world, "minecraft:the_nether"), new_nether)
        # An 8x4x8 box at a player's feet: the exact read the reports refused.
        got = mcmap.box_states(new_ow, 0, 63, 0, 7, 66, 7)
        self.assertIsInstance(got, dict)
        self.assertEqual(got[(3, 64, 3)], "minecraft:oak_planks")
        nether = mcmap.box_states(mcmap.region_dir(self.world, "the_nether"), 0, 64, 0, 3, 64, 3)
        self.assertEqual(nether[(1, 64, 1)], "minecraft:nether_bricks")

    def test_the_old_layouts_still_read_and_the_one_that_exists_wins(self):
        write_region(self.world / "region", {(0, 0): a_floor()})
        write_region(self.server / "world_nether" / "DIM-1" / "region", {(0, 0): a_floor()})
        self.assertEqual(mcmap.region_dir(self.world, "minecraft:overworld"),
                         self.world / "region")
        self.assertEqual(mcmap.region_dir(self.world, "minecraft:the_nether"),
                         self.server / "world_nether" / "DIM-1" / "region")
        # Vanilla before 26.1: the End inside the world folder.
        write_region(self.world / "DIM1" / "region", {(0, 0): a_floor()})
        self.assertEqual(mcmap.region_dir(self.world, "minecraft:the_end"),
                         self.world / "DIM1" / "region")
        # A world upgraded to 26.1 writes the new folders: those are its blocks now.
        write_region(self.world / "dimensions" / "minecraft" / "overworld" / "region",
                     {(0, 0): a_floor()})
        self.assertEqual(mcmap.region_dir(self.world, "overworld"),
                         self.world / "dimensions" / "minecraft" / "overworld" / "region")

    def test_a_data_pack_dimension_is_found_too(self):
        custom = self.world / "dimensions" / "bruh" / "sky_islands" / "region"
        write_region(custom, {(0, 0): a_floor()})
        self.assertEqual(mcmap.region_dir(self.world, "bruh:sky_islands"), custom)

    def test_render_bounds_reads_the_26_1_layout(self):
        write_region(self.world / "dimensions" / "minecraft" / "overworld" / "region",
                     {(0, 0): a_floor()})
        out = mcmap.render_bounds(self.world, {"x1": 0, "z1": 0, "x2": 7, "z2": 7},
                                  self.server / "pic.png")
        self.assertNotIn("error", out)
        self.assertEqual(out["columns"], 64)


class TestLz4Chunks(unittest.TestCase):
    def test_xxhash32_known_values(self):
        self.assertEqual(mcmap.xxh32(b"", 0), 0x02CC5D05)
        self.assertEqual(mcmap.xxh32(b"abc", 0), 0x32D153FF)

    def test_an_overlapping_match(self):
        # Three literals, then a match 3 back for 9: "abc" four times.
        self.assertEqual(mcmap.lz4_block_decode(b"\x35abc\x03\x00"), b"abc" * 4)
        with self.assertRaises(mcmap.Lz4Error):
            mcmap.lz4_block_decode(b"\x35abc\x09\x00")     # reaches before the start

    def test_the_lz4block_stream_round_trips_with_checksums(self):
        data = (b"minecraft:oak_planks" * 5000) + bytes(range(256)) * 300
        self.assertEqual(mcmap.lz4_stream_decode(lz4_stream(data)), data)
        bad = bytearray(lz4_stream(data))
        bad[17] ^= 0x01            # the first block's checksum
        with self.assertRaises(mcmap.Lz4Error):
            mcmap.lz4_stream_decode(bytes(bad))

    def test_a_region_chunk_written_with_lz4_is_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            region = Path(tmp) / "region"
            write_region(region, {(0, 0): a_floor()}, kind=4)
            got = mcmap.box_states(region, 0, 64, 0, 7, 64, 7)
            self.assertIsInstance(got, dict)
            self.assertEqual(got[(5, 64, 5)], "minecraft:oak_planks")


class TestWhyABoxCouldNotBeRead(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def test_no_region_folder(self):
        got = mcmap.box_states(self.root / "nowhere", 0, 64, 0, 3, 64, 3)
        self.assertIsInstance(got, mcmap.Unread)
        self.assertEqual(got.code, "no_region")
        self.assertIn("no saved region files", got.why)

    def test_a_chunk_never_generated(self):
        region = self.root / "region"
        write_region(region, {(0, 0): a_floor()})
        got = mcmap.box_states(region, 10, 64, 0, 20, 64, 3)     # reaches chunk (1, 0)
        self.assertEqual(got.code, "not_generated")
        self.assertEqual(got.chunk, (1, 0))
        self.assertIn("never been generated", got.why)

    def test_a_compression_nobody_knows_and_damaged_data(self):
        region = self.root / "region"
        write_region(region, {(0, 0): a_floor()}, kind=99)
        got = mcmap.box_states(region, 0, 64, 0, 3, 64, 3)
        self.assertEqual(got.code, "unreadable")
        self.assertIn("99", got.why)
        raw = bytearray(region_file({(0, 0): a_floor()}, kind=2))
        raw[8192 + 10:8192 + 40] = b"\xff" * 30
        (region / "r.0.0.mca").write_bytes(bytes(raw))
        got = mcmap.box_states(region, 0, 64, 0, 3, 64, 3)
        self.assertEqual(got.code, "unreadable")
        self.assertIn("damaged", got.why)


class TestTheCompanionSaysWhich(unittest.TestCase):
    """The refusal a person hears names the cause, not one catch-all."""

    def test_look_and_edit_carry_the_readers_reason(self):
        from test_minecraft_companion_edit import EditingHandsBase  # noqa: E402

        class Case(EditingHandsBase):
            def runTest(self):
                pass

        case = Case()
        case.setUp()
        try:
            case.join("Ben13765")
            unread = mcmap.Unread("not_generated", "Chunk 3, 4 has never been generated.",
                                  (3, 4))
            case.hands.reader = lambda dim, box: unread
            with self.assertRaisesRegex(Exception, "never been generated"):
                case.hands.look(player="Ben13765", size=[8, 4, 8])
            with self.assertRaisesRegex(Exception, "never been generated"):
                case.hands.edit(blocks=[{"x": 1, "y": 64, "z": 1, "block": "dirt"}])
        finally:
            case.doCleanups()


if __name__ == "__main__":
    unittest.main()
