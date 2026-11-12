#!/usr/bin/env python3
"""Finished, already drawn Minecraft maps, made from the world's own files.

A map in the game fills in only around a player holding it, so a set of
maps of the family's builds used to be a tour (the owner: "Is there a
better way to make these maps? Can you make them for me? Fully hands
off"). This draws each map here instead, from the region files the panel
already reads (`mcmap`), exactly as the game draws an explored one, and
writes it as the game's own map file (`<world>/data/map_<id>.dat`), locked,
so the server loads it the first time the map is held and never changes it.

What makes it match an explored map:

* **The grid.** A map of scale s covers 128·2^s blocks a side and the game
  snaps every map to one grid (`cell_centre`), so these sit where a map
  made in the game would, and neighbours tile edge to edge in item frames.
* **The colours.** Every block has one of the game's 62 map colours
  (`MAP_COLOURS`, `block_colour`), and each pixel takes one of four
  shades of it (packed `colour * 4 + shade`).
* **The drawing** (`render`): the vanilla map update, step for step. Each
  pixel is 2^s × 2^s columns. In each column the highest block with a map
  colour is found from the top; a fluid there counts its depth and is drawn
  as the fluid unless its top face is solid. The pixel's colour is the most
  common one (the first seen on a tie), its height the mean height, and the
  shade compares that height with the pixel north of it (a row north of
  the map is drawn first for the top row), with the game's checkerboard
  dither; water is shaded by depth instead. The Nether's ceiling draws the
  game's dirt-and-stone noise, as an explored Nether map shows.

What it cannot see: a chunk that has never been generated or saved is left
blank, as it is on a map nobody carried there. The world on disk is the
world as of the last save, so the caller saves first.

Map ids. The server hands out ids from its own counter, which may be ahead
of what is on disk, so these take ids from a band of their own far above
it (`ID_BAND`), recorded beside the panel's other world files, and never
an id the server has loaded: a map file is written whole, new, before the
map that names it exists.
"""
from __future__ import annotations

import gzip
import importlib.util
import os
import re
import struct
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


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

SIZE = 128                   # a map is 128 × 128 pixels at every scale
SCALE_MAX = 4
ID_BAND = 1_000_000          # the first id these maps take
DATA_VERSION_1_16 = 2566     # from here a map names its dimension as a string


class MapError(ValueError):
    """Why maps cannot be made, in words for the person who asked."""


# ---------------------------------------------------------------------------
# The game's map colours (MapColor), in id order
# ---------------------------------------------------------------------------
MAP_COLOURS: tuple[int, ...] = (
    0x000000, 0x7FB238, 0xF7E9A3, 0xC7C7C7, 0xFF0000, 0xA0A0FF, 0xA7A7A7, 0x007C00,
    0xFFFFFF, 0xA4A8B8, 0x976D4D, 0x707070, 0x4040FF, 0x8F7748, 0xFFFCF5, 0xD87F33,
    0xB24CD8, 0x6699D8, 0xE5E533, 0x7FCC19, 0xF27FA5, 0x4C4C4C, 0x999999, 0x4C7F99,
    0x7F3FB2, 0x334CB2, 0x664C33, 0x667F33, 0x993333, 0x191919, 0xFAEE4D, 0x5CDBD5,
    0x4A80FF, 0x00D93A, 0x815631, 0x700200, 0xD1B1A1, 0x9F5224, 0x95576C, 0x706C8A,
    0xBA8524, 0x677535, 0xA04D4E, 0x392923, 0x876B62, 0x575C5C, 0x7A4958, 0x4C3E5C,
    0x4C3223, 0x4C522A, 0x8E3C2E, 0x251610, 0xBD3031, 0x943F61, 0x5C191D, 0x167E86,
    0x3A8E8C, 0x562C3E, 0x14B485, 0x646464, 0xD8AF93, 0x7FA796,
)
# The four shades of a colour, by the low two bits of a packed pixel.
SHADES = (180, 220, 255, 135)
LOW, NORMAL, HIGH = 0, 1, 2

(NONE, GRASS, SAND, WOOL, FIRE, ICE, METAL, PLANT, SNOW, CLAY, DIRT, STONE, WATER, WOOD,
 QUARTZ, ORANGE, MAGENTA, LIGHT_BLUE, YELLOW, LIGHT_GREEN, PINK, GRAY, LIGHT_GRAY, CYAN,
 PURPLE, BLUE, BROWN, GREEN, RED, BLACK, GOLD, DIAMOND, LAPIS, EMERALD, PODZOL, NETHER,
 T_WHITE, T_ORANGE, T_MAGENTA, T_LIGHT_BLUE, T_YELLOW, T_LIGHT_GREEN, T_PINK, T_GRAY,
 T_LIGHT_GRAY, T_CYAN, T_PURPLE, T_BLUE, T_BROWN, T_GREEN, T_RED, T_BLACK, CRIMSON_NYLIUM,
 CRIMSON_STEM, CRIMSON_HYPHAE, WARPED_NYLIUM, WARPED_STEM, WARPED_HYPHAE, WARPED_WART,
 DEEPSLATE, RAW_IRON, GLOW_LICHEN) = range(62)

DYES = ("white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray",
        "light_gray", "cyan", "purple", "blue", "brown", "green", "red", "black")
DYE_COLOUR = dict(zip(DYES, (SNOW, ORANGE, MAGENTA, LIGHT_BLUE, YELLOW, LIGHT_GREEN, PINK,
                             GRAY, LIGHT_GRAY, CYAN, PURPLE, BLUE, BROWN, GREEN, RED, BLACK)))
TERRACOTTA = dict(zip(DYES, range(T_WHITE, T_BLACK + 1)))

# A wood's planks (and a log's end) and its bark.
WOODS = {
    "oak": (WOOD, PODZOL), "spruce": (PODZOL, BROWN), "birch": (SAND, QUARTZ),
    "jungle": (DIRT, PODZOL), "acacia": (ORANGE, STONE), "dark_oak": (BROWN, BROWN),
    "mangrove": (RED, PODZOL), "cherry": (T_WHITE, T_GRAY), "pale_oak": (QUARTZ, STONE),
    "bamboo": (YELLOW, PLANT), "crimson": (CRIMSON_STEM, CRIMSON_STEM),
    "warped": (WARPED_STEM, WARPED_STEM),
}
WOOD_BARK = {"acacia": GRAY, "cherry": T_GRAY, "crimson": CRIMSON_HYPHAE,
             "warped": WARPED_HYPHAE}
WOOD_PARTS = ("planks", "stairs", "slab", "fence", "fence_gate", "door", "trapdoor",
              "pressure_plate", "sign", "wall_sign", "hanging_sign", "wall_hanging_sign",
              "mosaic", "mosaic_stairs", "mosaic_slab")
_WOOD_RE = re.compile(r"^(stripped_)?(" + "|".join(sorted(WOODS, key=len, reverse=True))
                      + r")_(log|stem|wood|hyphae|block|" + "|".join(WOOD_PARTS) + r")$")
_DYED_RE = re.compile(r"^(" + "|".join(sorted(DYES, key=len, reverse=True)) + r")_(.+)$")
DYED_BLOCKS = ("wool", "carpet", "concrete", "concrete_powder", "stained_glass",
               "stained_glass_pane", "glazed_terracotta", "shulker_box", "candle", "banner",
               "wall_banner", "bed")
_COPPER_RE = re.compile(r"^(waxed_)?(exposed_|weathered_|oxidized_)?(cut_copper|copper|"
                        r"chiseled_copper|copper_grate|copper_bulb|copper_door|copper_trapdoor|"
                        r"cut_copper_stairs|cut_copper_slab|copper_block)$")
COPPER_AGE = {"": ORANGE, "exposed_": T_LIGHT_GRAY, "weathered_": WARPED_STEM,
              "oxidized_": WARPED_NYLIUM}
_CORAL_RE = re.compile(r"^(dead_)?(tube|brain|bubble|fire|horn)_coral(_block|_fan|_wall_fan)?$")
CORALS = {"tube": BLUE, "brain": PINK, "bubble": PURPLE, "fire": RED, "horn": YELLOW}

# Blocks named outright. A family's stairs, slabs and walls are found from
# these by `block_colour` (`stone_brick_wall` → `stone_bricks`).
EXACT: dict[str, int] = {}


def _put(colour_id: int, names: str) -> None:
    for name in names.split():
        EXACT[name] = colour_id


_put(NONE, "air cave_air void_air light barrier structure_void glass glass_pane torch "
     "wall_torch soul_torch soul_wall_torch redstone_torch redstone_wall_torch redstone_wire "
     "rail powered_rail detector_rail activator_rail lever tripwire tripwire_hook repeater "
     "comparator ladder iron_bars chain iron_chain flower_pot cake end_rod nether_portal "
     "skeleton_skull skeleton_wall_skull wither_skeleton_skull zombie_head player_head "
     "creeper_head dragon_head piglin_head redstone_lamp moving_piston piston_head "
     "candle_cake string")
_put(GRASS, "grass_block slime_block")
_put(SAND, "sand sandstone chiseled_sandstone cut_sandstone smooth_sandstone suspicious_sand "
     "end_stone end_stone_bricks glowstone bone_block scaffolding candle birch_planks")
_put(WOOL, "cobweb mushroom_stem")
_put(FIRE, "lava fire soul_fire tnt redstone_block")
_put(ICE, "ice packed_ice blue_ice frosted_ice")
_put(METAL, "iron_block iron_door iron_trapdoor anvil chipped_anvil damaged_anvil lantern "
     "soul_lantern brewing_stand heavy_weighted_pressure_plate grindstone lodestone "
     "heavy_core")
_put(PLANT, "short_grass grass tall_grass fern large_fern dandelion poppy blue_orchid allium "
     "azure_bluet red_tulip orange_tulip white_tulip pink_tulip oxeye_daisy cornflower "
     "lily_of_the_valley wither_rose sunflower lilac rose_bush peony torchflower "
     "pitcher_plant pitcher_crop torchflower_crop pink_petals wildflowers leaf_litter "
     "oak_sapling spruce_sapling birch_sapling jungle_sapling acacia_sapling "
     "dark_oak_sapling cherry_sapling pale_oak_sapling mangrove_propagule azalea "
     "flowering_azalea wheat carrots potatoes beetroots sweet_berry_bush sugar_cane bamboo "
     "bamboo_sapling vine cave_vines cave_vines_plant cactus lily_pad melon_stem "
     "pumpkin_stem attached_melon_stem attached_pumpkin_stem cocoa big_dripleaf "
     "big_dripleaf_stem small_dripleaf spore_blossom oak_leaves spruce_leaves birch_leaves "
     "jungle_leaves acacia_leaves dark_oak_leaves mangrove_leaves azalea_leaves "
     "flowering_azalea_leaves pale_oak_leaves bush firefly_bush short_dry_grass "
     "tall_dry_grass")
_put(SNOW, "snow snow_block powder_snow")
_put(CLAY, "clay infested_stone infested_cobblestone infested_stone_bricks "
     "infested_mossy_stone_bricks infested_cracked_stone_bricks "
     "infested_chiseled_stone_bricks infested_deepslate")
_put(DIRT, "dirt coarse_dirt rooted_dirt farmland dirt_path packed_mud granite "
     "polished_granite brown_mushroom_block jukebox hanging_roots")
_put(STONE, "stone cobblestone mossy_cobblestone stone_bricks mossy_stone_bricks "
     "cracked_stone_bricks chiseled_stone_bricks smooth_stone andesite polished_andesite "
     "gravel suspicious_gravel bedrock furnace dispenser dropper observer piston "
     "sticky_piston stonecutter cauldron water_cauldron lava_cauldron powder_snow_cauldron "
     "hopper coal_ore iron_ore gold_ore diamond_ore emerald_ore lapis_ore redstone_ore "
     "copper_ore smoker blast_furnace spawner trial_spawner vault crafter "
     "stone_pressure_plate polished_blackstone_pressure_plate")
_put(WATER, "water bubble_column kelp kelp_plant seagrass tall_seagrass frogspawn")
_put(WOOD, "bookshelf chiseled_bookshelf crafting_table chest trapped_chest barrel lectern "
     "composter beehive note_block loom cartography_table fletching_table smithing_table "
     "daylight_detector dead_bush white_banner white_wall_banner")
_put(QUARTZ, "quartz_block chiseled_quartz_block quartz_pillar quartz_bricks smooth_quartz "
     "diorite polished_diorite sea_lantern target")
_put(ORANGE, "red_sand red_sandstone chiseled_red_sandstone cut_red_sandstone "
     "smooth_red_sandstone terracotta pumpkin carved_pumpkin jack_o_lantern honey_block "
     "honeycomb_block raw_copper_block lightning_rod")
_put(MAGENTA, "purpur_block purpur_pillar")
_put(YELLOW, "hay_block sponge wet_sponge bee_nest")
_put(LIGHT_GREEN, "melon")
_put(LIGHT_GRAY, "structure_block jigsaw pale_moss_block pale_moss_carpet "
     "pale_hanging_moss")
_put(CYAN, "prismarine warped_fungus warped_roots nether_sprouts twisting_vines "
     "twisting_vines_plant sculk_sensor calibrated_sculk_sensor")
_put(PURPLE, "mycelium amethyst_block budding_amethyst amethyst_cluster large_amethyst_bud "
     "medium_amethyst_bud small_amethyst_bud chorus_plant chorus_flower shulker_box "
     "repeating_command_block")
_put(BROWN, "soul_sand soul_soil dark_oak_planks command_block brown_mushroom")
_put(GREEN, "moss_block moss_carpet dried_kelp_block sea_pickle end_portal_frame "
     "chain_command_block")
_put(RED, "bricks nether_wart_block shroomlight red_mushroom_block red_mushroom "
     "enchanting_table nether_wart")
_put(BLACK, "obsidian crying_obsidian basalt polished_basalt smooth_basalt blackstone "
     "polished_blackstone polished_blackstone_bricks cracked_polished_blackstone_bricks "
     "chiseled_polished_blackstone gilded_blackstone netherite_block coal_block "
     "ancient_debris respawn_anchor dragon_egg end_portal end_gateway sculk "
     "sculk_catalyst sculk_shrieker sculk_vein")
_put(GOLD, "gold_block raw_gold_block bell light_weighted_pressure_plate")
_put(DIAMOND, "diamond_block prismarine_bricks dark_prismarine beacon conduit")
_put(LAPIS, "lapis_block")
_put(EMERALD, "emerald_block")
_put(PODZOL, "podzol campfire soul_campfire mangrove_roots muddy_mangrove_roots")
_put(NETHER, "netherrack nether_bricks cracked_nether_bricks chiseled_nether_bricks "
     "red_nether_bricks magma_block nether_gold_ore nether_quartz_ore crimson_fungus "
     "crimson_roots weeping_vines weeping_vines_plant")
_put(T_WHITE, "calcite")
_put(T_GRAY, "tuff polished_tuff tuff_bricks chiseled_tuff chiseled_tuff_bricks")
_put(T_LIGHT_GRAY, "mud_bricks")
_put(T_CYAN, "mud")
_put(T_BROWN, "dripstone_block pointed_dripstone")
_put(T_RED, "decorated_pot")
_put(CRIMSON_NYLIUM, "crimson_nylium")
_put(WARPED_NYLIUM, "warped_nylium")
_put(WARPED_WART, "warped_wart_block")
_put(DEEPSLATE, "deepslate cobbled_deepslate polished_deepslate deepslate_bricks "
     "cracked_deepslate_bricks deepslate_tiles cracked_deepslate_tiles chiseled_deepslate "
     "reinforced_deepslate deepslate_coal_ore deepslate_iron_ore deepslate_gold_ore "
     "deepslate_diamond_ore deepslate_emerald_ore deepslate_lapis_ore "
     "deepslate_redstone_ore deepslate_copper_ore")
_put(RAW_IRON, "raw_iron_block")
_put(GLOW_LICHEN, "glow_lichen")
_put(GRAY, "tinted_glass")

# What a family's stairs, slabs and walls are cut from, when the name alone
# does not say (`brick_stairs` is from `bricks`, `quartz_slab` from
# `quartz_block`).
_CUT = re.compile(r"_(stairs|slab|wall|fence|fence_gate|pressure_plate|button)$")
_CUT_FROM = {"brick": "bricks", "stone_brick": "stone_bricks", "mossy_stone_brick":
             "mossy_stone_bricks", "nether_brick": "nether_bricks", "red_nether_brick":
             "red_nether_bricks", "end_stone_brick": "end_stone_bricks", "quartz":
             "quartz_block", "purpur": "purpur_block", "prismarine_brick": "prismarine_bricks",
             "mud_brick": "mud_bricks", "deepslate_brick": "deepslate_bricks",
             "deepslate_tile": "deepslate_tiles", "polished_blackstone_brick":
             "polished_blackstone_bricks", "tuff_brick": "tuff_bricks", "resin_brick":
             "resin_bricks"}
_put(ORANGE, "resin_bricks resin_block resin_clump creaking_heart")

# Blocks whose map colour depends on their state, so the state is read.
_BY_STATE = re.compile(r"_(log|stem|bed)$|^bamboo_block$|^stripped_bamboo_block$")
_FLUID_NAMES = frozenset({"water", "lava", "bubble_column", "kelp", "kelp_plant", "seagrass",
                          "tall_seagrass"})


def block_colour(name: str, props: dict[str, str] | None = None) -> int:
    """The map colour id of a block (a name without its namespace)."""
    hit = EXACT.get(name)
    if hit is not None:
        return hit
    m = _WOOD_RE.match(name)
    if m:
        stripped, wood, part = m.group(1), m.group(2), m.group(3)
        planks, bark = WOODS[wood]
        if part in ("log", "stem", "block"):
            if stripped:
                return planks
            axis = (props or {}).get("axis", "y")
            return planks if axis == "y" else bark
        if part in ("wood", "hyphae"):
            # Bark all round is the planks' colour but for a few woods;
            # stripped, it is the planks' (hyphae keep theirs).
            if stripped and part == "wood":
                return planks
            return WOOD_BARK.get(wood, planks)
        return planks
    m = _DYED_RE.match(name)
    if m and m.group(1) in DYE_COLOUR:
        dye, rest = m.group(1), m.group(2)
        if rest == "terracotta":
            return TERRACOTTA[dye]
        if rest == "bed":
            # The foot is the dye; the pillow end is white wool.
            return DYE_COLOUR[dye] if (props or {}).get("part", "foot") == "foot" else WOOL
        if rest in ("banner", "wall_banner"):
            return WOOD
        if rest in DYED_BLOCKS:
            return DYE_COLOUR[dye]
    m = _COPPER_RE.match(name)
    if m:
        return COPPER_AGE[m.group(2) or ""]
    m = _CORAL_RE.match(name)
    if m:
        return GRAY if m.group(1) else CORALS[m.group(2)]
    if name.endswith("_button"):
        return NONE
    if name.endswith(("_leaves", "_sapling", "_tulip")):
        return PINK if name == "cherry_leaves" else PLANT
    if name.endswith(("_head", "_wall_head", "_skull", "_wall_skull", "_torch", "_rail")):
        return NONE
    if name.endswith("_candle_cake"):
        return NONE
    m = _CUT.search(name)
    if m:
        base = name[:m.start()]
        for cand in (_CUT_FROM.get(base), base, base + "s", base + "_block"):
            if cand and cand in EXACT:
                return EXACT[cand]
    if name.startswith("infested_"):
        return CLAY
    if name.startswith("potted_"):
        return NONE
    if name.endswith("_ore"):
        return DEEPSLATE if name.startswith("deepslate_") else STONE
    # Anything newer than this list: stone, the commonest colour of a
    # built thing, rather than a hole in the map.
    return STONE


def _props(state: str) -> dict[str, str]:
    """`minecraft:oak_log[axis=x]` → {"axis": "x"}."""
    if "[" not in state:
        return {}
    inner = state[state.index("[") + 1:state.rindex("]")]
    return dict(p.split("=", 1) for p in inner.split(",") if "=" in p)


def _sturdy_top(name: str, props: dict[str, str]) -> bool:
    """Whether a waterlogged block's top face is whole (the game draws the
    block then, else the water)."""
    if name.endswith("_slab"):
        return props.get("type") in ("top", "double")
    if name.endswith("_stairs"):
        return props.get("half") == "top"
    return name.endswith("_grate") or name == "mangrove_roots"


def rgb(packed: int) -> tuple[int, int, int]:
    """The colour a packed map byte (0–255, or the signed byte) is shown as."""
    packed &= 0xFF
    base = MAP_COLOURS[packed >> 2] if (packed >> 2) < len(MAP_COLOURS) else 0
    m = SHADES[packed & 3]
    return ((base >> 16 & 0xFF) * m // 255, (base >> 8 & 0xFF) * m // 255, (base & 0xFF) * m // 255)


# ---------------------------------------------------------------------------
# The grid
# ---------------------------------------------------------------------------
def span(scale: int) -> int:
    """Blocks a side one map of this scale covers."""
    return SIZE << scale


def cell_of(x: int, z: int, scale: int) -> tuple[int, int]:
    """The grid cell (column, row) a block is in, for maps of this scale."""
    s = span(scale)
    return (x + 64) // s, (z + 64) // s


def cell_centre(col: int, row: int, scale: int) -> tuple[int, int]:
    """The centre the game gives a map of this cell (MapItemSavedData)."""
    s = span(scale)
    return col * s + s // 2 - 64, row * s + s // 2 - 64


def cell_box(col: int, row: int, scale: int) -> tuple[int, int, int, int]:
    """(x1, z1, x2, z2) of the blocks the cell's map shows, inclusive."""
    s = span(scale)
    x1, z1 = col * s - 64, row * s - 64
    return x1, z1, x1 + s - 1, z1 + s - 1


def cells_for(boxes: Iterable[tuple[int, int, int, int]], scale: int) -> list[tuple[int, int]]:
    """Every grid cell any of the boxes (x1, z1, x2, z2) touches, north to
    south then west to east."""
    out: set[tuple[int, int]] = set()
    for x1, z1, x2, z2 in boxes:
        c1, r1 = cell_of(min(x1, x2), min(z1, z2), scale)
        c2, r2 = cell_of(max(x1, x2), max(z1, z2), scale)
        for c in range(c1, c2 + 1):
            for r in range(r1, r2 + 1):
                out.add((c, r))
    return sorted(out, key=lambda cr: (cr[1], cr[0]))


def sheets(cells: list[tuple[int, int]]) -> list[list[tuple[int, int]]]:
    """The cells in groups that touch (side or corner): one wall of item
    frames each."""
    left = set(cells)
    groups = []
    while left:
        start = min(left, key=lambda cr: (cr[1], cr[0]))
        left.discard(start)
        group, todo = [start], [start]
        while todo:
            c, r = todo.pop()
            for dc in (-1, 0, 1):
                for dr in (-1, 0, 1):
                    n = (c + dc, r + dr)
                    if n in left:
                        left.discard(n)
                        group.append(n)
                        todo.append(n)
        groups.append(sorted(group, key=lambda cr: (cr[1], cr[0])))
    return sorted(groups, key=lambda g: (g[0][1], g[0][0]))


def frame_label(cell: tuple[int, int], group: list[tuple[int, int]]) -> str:
    """Where a map hangs in its wall: a row letter (A is north) and a column
    number (1 is west), as on a chart, so `A1 A2 / B1 B2` is the wall."""
    top = min(r for _, r in group)
    left = min(c for c, _ in group)
    row = cell[1] - top
    letters = ""
    n = row
    while True:
        letters = chr(ord("A") + n % 26) + letters
        n = n // 26 - 1
        if n < 0:
            break
    return f"{letters}{cell[0] - left + 1}"


# ---------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------
def _i32(v: int) -> int:
    v &= 0xFFFFFFFF
    return v - (1 << 32) if v & 0x80000000 else v


def nether_noise(x: int, z: int) -> int:
    """The colour an explored map of a dimension with a ceiling shows for
    the pixel whose first column is (x, z): the game's own noise."""
    n = _i32(x + _i32(z * 231871))
    n = _i32(_i32(_i32(n * n) * 31287121) + _i32(n * 11))
    return DIRT if (n >> 20) & 1 == 0 else STONE


class _Columns:
    """Columns of one chunk at a time, read from the region files."""

    def __init__(self, region: Path, min_y: int):
        self.region = region
        self.min_y = min_y
        self.key: tuple[int, int] | None = None
        self.chunk = None

    def load(self, cx: int, cz: int):
        if self.key != (cx, cz):
            root, status = mcmap.load_chunk(self.region, cx, cz)
            self.chunk = mcmap.Chunk(root) if root is not None and mcmap.has_sections(root) \
                else None
            self.key = (cx, cz)
        return self.chunk

    def column(self, chunk, lx: int, lz: int) -> tuple[int, int, int]:
        """(map colour, height, fluid depth) of one column, as the game's
        map update finds them."""
        if chunk.top_section is None:
            return NONE, self.min_y, 0
        y = chunk.top_section * 16 + 15
        floor = max(self.min_y, chunk.bottom_section * 16)
        while y >= floor:
            if (y >> 4) not in chunk.sections:
                y = (y >> 4) * 16 - 1
                continue
            name = chunk.block(lx, y, lz)
            state = chunk.state(lx, y, lz)
            colour = EXACT.get(name)
            if colour is None or _BY_STATE.search(name):
                colour = block_colour(name, _props(state))
            if colour == NONE:
                y -= 1
                continue
            if name not in _FLUID_NAMES and "waterlogged=true" not in state:
                return colour, y, 0
            # A fluid: count down through it, as the game does.
            depth, t = 0, y - 1
            while True:
                below = chunk.block(lx, t, lz)
                below_fluid = below in _FLUID_NAMES or \
                    "waterlogged=true" in chunk.state(lx, t, lz)
                t -= 1
                depth += 1
                if not (t > self.min_y and below_fluid):
                    break
            if name == "lava":
                return FIRE, y, depth
            if name in _FLUID_NAMES or not _sturdy_top(name, _props(state)):
                return WATER, y, depth
            return colour, y, depth
        return NONE, self.min_y, 0


def render(region: Path, centre_x: int, centre_z: int, scale: int, *, ceiling: bool = False,
           min_y: int = -64) -> tuple[bytearray, int]:
    """The 128 × 128 packed colours of the map centred here (row by row,
    north first, as a map file keeps them) and how many pixels were drawn."""
    i = 1 << scale
    base_x, base_z = centre_x // i - 64, centre_z // i - 64
    cols = _Columns(Path(region), min_y)
    # Per pixel (including the row north of the map, -1): (colour, height,
    # depth), or None where the chunk is not on disk.
    pixels: dict[tuple[int, int], tuple[int, float, int] | None] = {}
    per = max(1, 16 // i)                    # pixels a side in one chunk
    cx0, cz0 = (base_x * i) >> 4, ((base_z - 1) * i) >> 4
    cx1, cz1 = ((base_x + SIZE) * i - 1) >> 4, ((base_z + SIZE) * i - 1) >> 4
    for cx in range(cx0, cx1 + 1):
        for cz in range(cz0, cz1 + 1):
            # The pixels whose first column is in this chunk.
            k0 = max(0, -(-(cx * 16) // i) - base_x)
            l0 = max(-1, -(-(cz * 16) // i) - base_z)
            k_end = min(SIZE, k0 + per)
            l_end = min(SIZE, l0 + per)
            chunk = None if ceiling else cols.load(cx, cz)
            for k in range(k0, k_end):
                q = (base_x + k) * i
                if q >> 4 != cx:
                    continue
                for ll in range(l0, l_end):
                    r = (base_z + ll) * i
                    if r >> 4 != cz:
                        continue
                    if ceiling:
                        loaded = cols.load(cx, cz)
                        if loaded is None:
                            pixels[(k, ll)] = None
                            continue
                        pixels[(k, ll)] = (nether_noise(q, r), 100.0, 0)
                        continue
                    if chunk is None:
                        pixels[(k, ll)] = None
                        continue
                    seen: Counter = Counter()
                    height, depth = 0.0, 0
                    for n in range(i):
                        for o in range(i):
                            colour, y, d = cols.column(chunk, (q + n) & 15, (r + o) & 15)
                            depth += d
                            height += y / (i * i)
                            seen[colour] += 1
                    # The most common colour; on a tie the first one seen
                    # (Counter keeps the order it met them in).
                    top = max(seen.values())
                    colour = next(c for c, v in seen.items() if v == top)
                    pixels[(k, ll)] = (colour, height, depth // (i * i))
    out = bytearray(SIZE * SIZE)
    drawn = 0
    for k in range(SIZE):
        prev = 0.0
        for ll in range(-1, SIZE):
            px = pixels.get((k, ll))
            if px is None:
                continue
            colour, height, depth = px
            odd = (k + ll) & 1
            if colour == WATER:
                g = depth * 0.1 + odd * 0.2
                shade = HIGH if g < 0.5 else LOW if g > 0.9 else NORMAL
            else:
                g = (height - prev) * 4.0 / (i + 4) + (odd - 0.5) * 0.4
                shade = HIGH if g > 0.6 else LOW if g < -0.6 else NORMAL
            prev = height
            if ll >= 0:
                out[ll * SIZE + k] = (colour * 4 + shade) if colour else 0
                drawn += 1
    return out, drawn


# ---------------------------------------------------------------------------
# The map file
# ---------------------------------------------------------------------------
def _nbt_string(s: str) -> bytes:
    raw = s.encode("utf-8")
    return struct.pack(">H", len(raw)) + raw


def _nbt_payload(tag: int, value: Any) -> bytes:
    if tag == mcmap.TAG_BYTE:
        return struct.pack(">b", value)
    if tag == mcmap.TAG_INT:
        return struct.pack(">i", value)
    if tag == mcmap.TAG_STRING:
        return _nbt_string(value)
    if tag == mcmap.TAG_BYTE_ARRAY:
        return struct.pack(">i", len(value)) + bytes(value)
    if tag == mcmap.TAG_LIST:
        kind, items = value
        return struct.pack(">bi", kind, len(items)) + b"".join(
            _nbt_payload(kind, v) for v in items)
    if tag == mcmap.TAG_COMPOUND:
        body = b""
        for key, (t, v) in value.items():
            body += struct.pack(">b", t) + _nbt_string(key) + _nbt_payload(t, v)
        return body + b"\x00"
    raise ValueError(f"no writer for NBT tag {tag}")


def map_file_bytes(colours: bytes, centre_x: int, centre_z: int, scale: int, dimension: str,
                   data_version: int) -> bytes:
    """A locked map's saved data, gzipped, as the game writes `map_<id>.dat`."""
    if data_version >= DATA_VERSION_1_16:
        dim = (mcmap.TAG_STRING, dimension)
    else:
        dim = (mcmap.TAG_BYTE, {"minecraft:the_nether": -1, "minecraft:the_end": 1}
               .get(dimension, 0))
    data = {
        "scale": (mcmap.TAG_BYTE, scale), "dimension": dim,
        "trackingPosition": (mcmap.TAG_BYTE, 1), "unlimitedTracking": (mcmap.TAG_BYTE, 0),
        "locked": (mcmap.TAG_BYTE, 1),
        "xCenter": (mcmap.TAG_INT, centre_x), "zCenter": (mcmap.TAG_INT, centre_z),
        "banners": (mcmap.TAG_LIST, (mcmap.TAG_END, [])),
        "frames": (mcmap.TAG_LIST, (mcmap.TAG_END, [])),
        "colors": (mcmap.TAG_BYTE_ARRAY, bytes(colours)),
    }
    root = {"data": (mcmap.TAG_COMPOUND, data), "DataVersion": (mcmap.TAG_INT, data_version)}
    raw = struct.pack(">b", mcmap.TAG_COMPOUND) + _nbt_string("") \
        + _nbt_payload(mcmap.TAG_COMPOUND, root)
    return gzip.compress(raw, mtime=0)


def write_new(path: Path, data: bytes) -> None:
    """A file that must not exist yet, written whole before it has its name."""
    path = Path(path)
    if path.exists():
        raise MapError(f"{path.name} is already there; no map was overwritten.")
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, 0o644)
        os.link(tmp, path)               # fails rather than replace one that appeared
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass


def maps_dir(world: Path) -> Path:
    """Where this world keeps its maps: beside `idcounts.dat` (the game's
    map counter), in `<world>/data` before 26.1 and whatever layout keeps
    them there. A world whose maps are elsewhere is refused, never guessed."""
    world = Path(world)
    plain = world / "data"
    if (plain / "idcounts.dat").exists() or not (world / "dimensions").is_dir():
        return plain
    for found in sorted(world.rglob("idcounts.dat")):
        if any(found.parent.glob("map_*.dat")):
            return found.parent
    raise MapError("This server version keeps its maps somewhere this add-on does not know "
                   "yet, so it cannot make maps for it.")


def next_ids(folder: Path, count: int, last: int = 0) -> list[int]:
    """`count` map ids nobody has: above the band's start, the last one this
    add-on gave, and every map file already in the folder."""
    top = max(ID_BAND - 1, int(last or 0))
    for f in Path(folder).glob("map_*.dat"):
        m = re.fullmatch(r"map_(\d+)\.dat", f.name)
        if m:
            top = max(top, int(m.group(1)))
    return list(range(top + 1, top + 1 + count))


__all__ = ["MAP_COLOURS", "block_colour", "rgb", "render", "cell_of", "cell_centre",
           "cell_box", "cells_for", "sheets", "frame_label", "map_file_bytes", "write_new",
           "maps_dir", "next_ids", "MapError", "span", "nether_noise"]
