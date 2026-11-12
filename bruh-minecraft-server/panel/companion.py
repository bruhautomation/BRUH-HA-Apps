#!/usr/bin/env python3
"""The companion's hands in the world: mechanics, never decisions.

BRUH Minecraft is a server first. A companion that plays in the world with
the family — greeting people, answering chat, asking a child a question,
building something small — is brAIn's (its Minecraft faculty, in the
`brain` integration), and decides everything: who is family, when to greet,
what to say, the bedtime rule, the budgets, the model, what to remember.
This module is what has to sit next to RCON for that to be safe and quick,
and it only ever does what it is asked through the integration's services:

* **Words** — `say`: a line in chat to named players under a speaker name
  and colour the caller supplies (`<Name> text`), optionally with a soft
  chime. Never to everyone at once unless asked, never as the server.
* **A body** — `appear`: an invulnerable, silent allay named as asked,
  beside a player for some seconds, with a chime, sparkles and a little
  wave (Bedrock players see allays through Geyser; display entities never
  reach them). Every entity carries the tag `bruh_companion`, the action's
  own tag and this process's epoch tag, so a sweep removes any left by an
  earlier run and an undo removes exactly one action's.
* **Choice pads** — `ask`: a question with two or three pictures. A 2×2
  carpet per option beside the child on flat, natural ground, each with a
  fence post, a picture block and maybe an item floating over it (an item
  entity nobody can pick up); standing on one for `PAD_HOLD` seconds is the answer,
  confirmed with a chime and sparkles, announced as the Home Assistant
  event `bruh_minecraft_answer`, and the pads are taken away again.
* **Blocks** — `build` and `place_blocks`, the one path that changes
  blocks: it refuses a footprint inside a protected place or on or next to
  a build in the build log, checks every cell is air over natural ground,
  places with `setblock … keep`, records what each cell was, and snapshots
  first when the change is large. An undo puts back only cells that still
  hold what was placed, so it never undoes a child's later change.
* **Progress and the spyglass** — `progress`: a line on a player's action
  bar; `give_spyglass`: one named spyglass, unless they have it (what a
  player points with: panel/spyglass.py).
* **A trusted edit** — `edit`: anything, anywhere, including `shapes`
  (panel/shapes.py), snapshotted first and undone by runs (`fill …
  replace <what was set>`); `undo_job` undoes every edit of a caller's job.
* **The account check** — `account_check`: whether the server checks the
  accounts behind the names in chat, which the chat events carry so a
  companion knows whether a name may be believed.

Hard limits live in `check_command`, the chokepoint every command passes:
only an allay (and a pad's icon, which cannot be picked up) is ever
summoned, only gentle sounds at a capped volume are played, only the
companion's own entities are killed or moved, words go to one named player,
an item given carries at most a name and what a player has is only ever
counted (`clear … 0`), and blocks change only through `place_blocks`/undo.
Nothing is sent while nobody is online.

The old engine's state (up to 1.17.7) is found and retired by
`companion_legacy`, the only module that knows its folder and tag.
"""
from __future__ import annotations

import importlib.util
import json
import math
import os
import re
import secrets
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable


def _beside(name: str, filename: str):
    """A module beside this file (the panel loads modules by path)."""
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


legacy = _beside("bruh_mc_companion_legacy", "companion_legacy.py")
shapes = _beside("bruh_mc_shapes", "shapes.py")

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
QUESTION_TIMEOUT = 180        # seconds a pad question waits for an answer
QUESTION_RETRY = 30           # seconds before trying a site again
QUESTION_ATTEMPTS = 4
PAD_HOLD = 2.0                # seconds on a pad that make an answer
RESULT_LINGER = 6             # seconds the answer is shown before the pads go
LARGE_CHANGE = 64             # blocks: a change this big is snapshotted first
FAST_INTERVAL = 0.5           # seconds between beats while something is live
MAX_ACTIONS = 300
MAX_QUESTIONS = 100
MAX_SAID = 60
APPEAR_MAX = 120              # seconds a body may stay
REPLY_LINES = 4               # chat lines one `say` may take
REPLY_LINE_CHARS = 160
BUILD_MAX = 64                # blocks in one build
BUILD_REACH = 48              # relative offsets, and how far from a player an absolute one may be
# A trusted edit (`edit`): what a grown-up who "can ask for anything" asks
# for through brAIn. Not a guard on size — a ceiling on one request so the
# snapshot that makes it undoable stays a file the panel can hold — and one
# `fills` box is one `fill` command, so at most FILL_MAX (Minecraft's limit).
EDIT_MAX = 131072
FILL_MAX = 32768
EDIT_REACH = 128              # relative offsets in a trusted edit
# An action whose cells are more than this many records keeps them beside
# the log (`actions/<id>.json`), so the log stays small to read and rewrite.
INLINE_CELLS = 400
# A chunk nobody is standing in answers "That position is not loaded": an
# edit (and its undo) force-loads the chunks it needs, asks again while
# they load, and lets go of the ones it loaded (#776).
_NOT_LOADED = re.compile(r"not loaded", re.I)
FORCE_MAX = 256               # chunks one edit may force-load
LOAD_TRIES = 20
LOAD_WAIT_S = 0.1
VANILLA_DIMS = {"nether": "the_nether", "end": "the_end", "overworld": "overworld"}
_JOB = re.compile(r"^[A-Za-z0-9_.:\-]{1,40}$")
LOOK_DEFAULT = (16, 8, 16)    # a look's box, x by y by z
LOOK_MAX = (32, 16, 32)
ACCOUNT_STALE = 60            # seconds the account check is trusted
NAME_MAX = 16

TAG = "bruh_companion"
# A job's boss bar: the companion's namespace and a job's key, nothing else.
BAR_ID = re.compile(r"^bruh_companion:[a-z0-9_\-]{1,24}$")
BAR_KEY = re.compile(r"^[a-z0-9_\-]{1,24}$")
DIR_NAME = "companion"
DEFAULT_NAME = "Companion"
DEFAULT_COLOUR = "light_purple"
COLOURS = frozenset({
    "black", "dark_blue", "dark_green", "dark_aqua", "dark_red", "dark_purple", "gold",
    "gray", "dark_gray", "blue", "green", "aqua", "red", "light_purple", "yellow", "white"})

SAFE_SUMMONS = frozenset({"minecraft:allay"})
GENTLE_SOUNDS = frozenset({
    "minecraft:block.note_block.chime", "minecraft:block.note_block.bell",
    "minecraft:block.note_block.pling", "minecraft:block.amethyst_block.chime",
    "minecraft:entity.allay.item_given", "minecraft:entity.experience_orb.pickup",
})
MAX_VOLUME = 0.8
GIFT_MAX = 16
# Ground the companion may build on: terrain, never something somebody placed.
NATURAL_GROUND = ("#minecraft:dirt", "#minecraft:sand", "#minecraft:base_stone_overworld",
                  "minecraft:gravel", "minecraft:snow_block")
# Blocks and items the companion never uses, whoever asks.
_FORBIDDEN = re.compile(
    r"tnt|lava|fire|magma|command|structure|jigsaw|spawner|portal|skull|head|cactus|"
    r"sculk|powder_snow|wither|dragon|barrier|bedrock|end_crystal|respawn_anchor|"
    r"spawn_egg|flint_and_steel|fire_charge|potion|arrow|trident|sword|axe|bow")
_BLOCK_ID = re.compile(r"^(minecraft:)?[a-z0-9_]{1,48}$")
# A block state for a trusted edit: any id, with its properties —
# `minecraft:red_bed[facing=east,part=head]`.
_BLOCK_STATE = re.compile(
    r"^([a-z0-9_.\-]{1,32}:)?[a-z0-9_/.]{1,64}(\[[a-z0-9_]{1,32}=[a-z0-9_]{1,32}"
    r"(,[a-z0-9_]{1,32}=[a-z0-9_]{1,32}){0,15}\])?$")
# A block whose neighbour is part of the same thing (a bed's other half, a
# door's other half, a tall plant): replacing one breaks the other, so an
# edit's snapshot takes these neighbours too and an undo puts them back.
_MULTI_PART = re.compile(r"[\[,](part|half)=")
_ACTION_ID = re.compile(r"^[0-9]{8}-[0-9a-f]{6}$")
# A power source with no block entity, whose power is in its state (#778):
# a lever, a button, a plate, dust, a torch, a repeater, an observer… A
# `setblock` updates only the six cells beside the one it sets, and a lever
# or a button powers the block it hangs on, which powers ITS neighbours —
# so a lever set off by an edit left the command block it drove running.
_POWER_SOURCE = re.compile(
    r"^minecraft:(lever|[a-z_]*_button|[a-z_]*_pressure_plate|redstone_wire|"
    r"redstone_(wall_)?torch|repeater|observer|tripwire_hook|target|redstone_block|"
    r"lightning_rod)(\[|$)")
_POWER_PROPS = re.compile(r"[\[,](powered|power|lit)=(\w+)")
# The moment's block a power change is passed through: an UNLIT torch gives
# no power, and putting one in and taking it away each update the neighbours
# of all six cells around it — the attached block's neighbours among them.
_NUDGE = "minecraft:redstone_torch[lit=false]"
_NUDGE_TOO = "minecraft:redstone_wall_torch[facing=north,lit=false]"


def _power(state: str) -> tuple[str, tuple] | None:
    """What a cell gives redstone: the source and its power, or None."""
    if not _POWER_SOURCE.match(state or ""):
        return None
    return state.split("[", 1)[0], tuple(sorted(_POWER_PROPS.findall(state)))


def power_changed(before: str, after: str) -> bool:
    """Whether setting `before` to `after` changes the power a source gives."""
    return _power(before) != _power(after)


_UNQUOTED = re.compile(r"^[0-9A-Za-z_\-.+]+$")
_PLAYER = re.compile(r"^[A-Za-z0-9_.*]{1,17}$")
_COLOUR_CODE = re.compile(r"§.")
# `give`/`clear` the chokepoint lets through: one named player, an item, at
# most its custom name as data, and a count.
_ITEM_COMMAND = re.compile(
    r"^(?:minecraft:)?(?:give|clear) (?P<who>\S+) (?P<item>[a-z0-9_:]+)"
    r"(?:\[(?:minecraft:)?custom_name=[^\[\]{}]*\]|\{display:\{Name:'[^{}]*'\}\})?"
    r"(?: (?P<count>\d+))?$")

PAD_COLOURS = (("minecraft:lime_carpet", "minecraft:lime_wool"),
               ("minecraft:red_carpet", "minecraft:red_wool"),
               ("minecraft:light_blue_carpet", "minecraft:light_blue_wool"))
# Where each option's pad goes across the player's view (two cells wide)
# and its post, for two and for three options.
PAD_LAYOUTS = {2: ((-3, -2, -3), (2, 3, 3)),
               3: ((-5, -4, -5), (-1, 0, -1), (3, 4, 4))}
ICON_TAG = "_o"               # an option's icon: the action's tag + _o<index>
SPYGLASS_NAME_MAX = 32
POST_BLOCK = "minecraft:oak_fence"
EVERYONE = ("", "everyone", "everybody", "all", "@a")


class GuardError(ValueError):
    """A command the companion is never allowed to send."""


class CompanionError(ValueError):
    """A request that cannot be done as given; the message says why."""


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _atomic_write_json(path: Path, data: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(data, indent=1))
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            # Already gone; the write's own error is the one that matters.
            pass
        raise


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def quote_name(name: str) -> str:
    """A player name as a command's entity argument takes it (`.Kaz` stays bare)."""
    if _UNQUOTED.match(name):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def parse_test(reply: str) -> bool | None:
    text = _COLOUR_CODE.sub("", str(reply or "")).strip().lower()
    if text.startswith("test passed"):
        return True
    if text.startswith("test failed"):
        return False
    return None


def unread_why(result: Any) -> str:
    """Why the world's blocks could not be read, from what the reader gave
    back instead of the states (mcmap's `Unread`: its `why`)."""
    why = getattr(result, "why", None)
    if why:
        return str(why)
    return "That part of the world could not be read from the saved files."


def bare(name: str) -> str:
    """A name as people mean it: no Bedrock prefix, no case."""
    return re.sub(r"^[.*]", "", str(name or "").strip()).lower()


# Blocks the game has renamed: a person or a model still says the old id.
RENAMED_BLOCKS = {"minecraft:chain": "minecraft:iron_chain"}


def why_refused(reply: str | None) -> str:
    """What a server's refusal of a block or a fill means for the one who
    asked: the reply, with the new name when the block was renamed, and
    a sentence when there was no reply at all."""
    if not reply:
        return "the server did not answer (it may be busy or restarting); nothing was changed"
    text = reply[:120]
    m = re.search(r"unknown block type '?([a-z0-9_:.\-]+)'?", reply, re.I)
    if m:
        old = m.group(1).lower()
        old = old if ":" in old else f"minecraft:{old}"
        if old in RENAMED_BLOCKS:
            text += f" - this server calls it {RENAMED_BLOCKS[old]}; use that id"
    return text


def block_state(value: Any) -> str:
    """A block state a trusted edit may place (any block, with its
    properties), with its namespace — or a refusal."""
    text = str(value or "").strip().lower().replace(" ", "_")
    if text in ("", "remove", "none"):
        text = "minecraft:air"
    if not _BLOCK_STATE.match(text):
        raise CompanionError("A block is an id like minecraft:oak_planks, with any "
                             "properties in brackets: minecraft:oak_door[facing=north,half=lower].")
    return text if ":" in text.split("[", 1)[0] else f"minecraft:{text}"


def block_id(value: Any, default: str | None = None) -> str:
    """A safe block or item id with its namespace, or a refusal."""
    text = str(value or "").strip().lower().replace(" ", "_")
    if not text:
        if default is None:
            raise CompanionError("Name a block or item, like minecraft:hay_block.")
        return default
    if not _BLOCK_ID.match(text) or _FORBIDDEN.search(text):
        raise CompanionError(f"The companion does not use {text!r}.")
    return text if ":" in text else f"minecraft:{text}"


def speaker_name(value: Any, default: str = DEFAULT_NAME) -> str:
    """A name the companion may go by in the game: letters, digits, spaces,
    apostrophes and dashes, at most NAME_MAX characters."""
    raw = " ".join(re.sub(r"[^\w '\-]", "", str(value or "")).split())[:NAME_MAX].strip()
    return raw or default


def colour(value: Any, default: str = DEFAULT_COLOUR) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    return text if text in COLOURS else default


def text_component(text: str, color: str = DEFAULT_COLOUR) -> str:
    """A text component; JSON that is also valid SNBT on 1.21.5+ servers."""
    return json.dumps({"text": str(text)[:200], "color": color}, ensure_ascii=False)


def modern_text(version: str | None) -> bool:
    """1.21.5 and later read a text component as SNBT, earlier as a JSON string."""
    nums = [int(n) for n in re.findall(r"\d+", str(version or ""))[:3]]
    if not nums:
        return True
    while len(nums) < 3:
        nums.append(0)
    if nums[0] != 1:
        return True          # 26.x and on: the new numbering, newest format
    return tuple(nums) >= (1, 21, 5)


def item_syntax(version: str | None) -> str:
    """How this server writes an item's data in a command: `snbt` (1.21.5
    and on: components, text as SNBT), `json` (1.20.5–1.21.4: components,
    text as a JSON string) or `nbt` (before 1.20.5: `{display:{Name:…}}`)."""
    nums = [int(n) for n in re.findall(r"\d+", str(version or ""))[:3]]
    if not nums or nums[0] != 1:
        return "snbt"
    while len(nums) < 3:
        nums.append(0)
    if tuple(nums) >= (1, 21, 5):
        return "snbt"
    return "json" if tuple(nums) >= (1, 20, 5) else "nbt"


def item_id(value: Any) -> str:
    """An item id shown as a pad's icon (never handed over, so any item)."""
    text = str(value or "").strip().lower().replace(" ", "_")
    if not _BLOCK_ID.match(text):
        raise CompanionError("An option's item is an id like minecraft:cake.")
    return text if ":" in text else f"minecraft:{text}"


def named_item(item: str, name: str, syntax: str) -> str:
    """`item` with a custom name, in the server's syntax."""
    if syntax == "nbt":
        js = json.dumps(name, ensure_ascii=False).replace("\\", "\\\\").replace("'", "\\'")
        return f"{item}{{display:{{Name:'{js}'}}}}"
    if syntax == "json":
        js = json.dumps(name, ensure_ascii=False).replace("\\", "\\\\").replace("'", "\\'")
        return f"{item}[custom_name='{js}']"
    snbt = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{item}[custom_name={snbt}]"


def split_reply(text: Any, width: int = REPLY_LINE_CHARS, lines: int = REPLY_LINES) -> list[str]:
    """Words as a few chat lines: plain text, wrapped, capped with "…"."""
    import textwrap
    plain = _COLOUR_CODE.sub("", str(text or ""))
    plain = re.sub(r"[\x00-\x1f§*_`#]", " ", plain)
    plain = " ".join(plain.split())
    if not plain:
        return []
    out = textwrap.wrap(plain, width, break_long_words=True, break_on_hyphens=False)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][:width - 1].rstrip() + "…"
    return out


# -- whether a name in chat is who it says it is ------------------------------
def _properties(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            out[key.strip()] = value.strip()
    return out


def _yaml_block(text: str, key: str) -> str:
    """The indented lines under `key:` in a simple YAML file ('' if none)."""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = re.match(rf"^(\s*){re.escape(key)}:\s*(#.*)?$", line)
        if not m:
            continue
        indent, block = len(m.group(1)), []
        for nxt in lines[i + 1:]:
            if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent:
                break
            block.append(nxt)
        return "\n".join(block)
    return ""


def _yaml_true(block: str, key: str) -> bool:
    return bool(re.search(rf"^\s*{re.escape(key)}:\s*true\b", block, re.M | re.I))


def account_check(server_dir: Path) -> dict[str, Any]:
    """Whether the server checks the accounts behind the names in chat.

    Java names are real when `online-mode` is on (a missing setting is the
    server's default, on) or a Velocity proxy in front checks them
    (`config/paper-global.yml` → `proxies.velocity` enabled with online-mode).
    Bedrock names (Geyser's dotted ones) are real when Floodgate is installed
    and Geyser's `auth-type` is not `offline`: Floodgate signs them in with
    their Xbox account. A name the server does not check is anyone's to type,
    which the chat events say (`verified`), so a companion can refuse a
    grown-up's commands under it.
    """
    sd = Path(server_dir)
    online = _properties(sd / "server.properties").get("online-mode", "true").lower() != "false"
    velocity = False
    try:
        paper = (sd / "config" / "paper-global.yml").read_text(encoding="utf-8", errors="replace")
        block = _yaml_block(paper, "velocity")
        velocity = _yaml_true(block, "enabled") and _yaml_true(block, "online-mode")
    except OSError:
        velocity = False
    floodgate = (sd / "plugins" / "floodgate").is_dir() or any(
        p.is_file() for d in ("plugins", "mods") for p in (sd / d).glob("floodgate*.jar")
    ) if sd.is_dir() else False
    auth = None
    for cfg in (sd / "plugins" / "Geyser-Spigot" / "config.yml",
                sd / "config" / "Geyser-Fabric" / "config.yml",
                sd / "config" / "geyser" / "config.yml"):
        try:
            m = re.search(r"^\s*auth-type:\s*['\"]?([a-z]+)", cfg.read_text(
                encoding="utf-8", errors="replace"), re.M)
        except OSError:
            continue
        if m:
            auth = m.group(1).lower()
            break
    java = online or velocity
    bedrock = floodgate and auth != "offline"
    return {
        "java": java, "bedrock": bedrock, "online_mode": online, "velocity": velocity,
        "floodgate": floodgate, "geyser_auth": auth,
        "why_java": "" if java else "this server does not check Java accounts (online-mode "
                                    "is off in server.properties)",
        "why_bedrock": "" if bedrock else (
            "Bedrock players are not signed in (Geyser's auth-type is offline)"
            if auth == "offline" else "Bedrock players are not signed in through Floodgate"),
    }


def bedrock_name(player: str) -> bool:
    """A Geyser/Floodgate player: the prefix is part of the name."""
    return str(player or "").startswith((".", "*"))


def trusted(accounts: dict[str, Any], player: str) -> tuple[bool, str]:
    """(may this name be believed, why not)."""
    if bedrock_name(player):
        return bool(accounts.get("bedrock")), str(accounts.get("why_bedrock") or "")
    return bool(accounts.get("java")), str(accounts.get("why_java") or "")


# ---------------------------------------------------------------------------
# The chokepoint
# ---------------------------------------------------------------------------
def _final(cmd: str) -> tuple[str, list[str]]:
    """The command an `execute … run` chain ends in, as (verb, words)."""
    chained = cmd.startswith(("execute ", "minecraft:execute ")) and " run " in cmd
    tail = cmd.rsplit(" run ", 1)[-1] if chained else cmd
    words = tail.split()
    verb = words[0].split(":", 1)[-1] if words else ""
    return verb, words


def _own_selector(selector: str) -> bool:
    """`@e[tag=bruh_companion…]` or the old engine's tag (a sweep)."""
    m = re.match(r"^@e\[tag=([a-z0-9_]+)(?:[,\]])", selector)
    if not m:
        return False
    tag = m.group(1)
    return tag == TAG or tag.startswith(TAG + "_") or legacy.is_legacy_tag(tag)


def check_command(cmd: str, placing: bool = False) -> None:
    """Raise GuardError unless `cmd` is something the companion may ever send."""
    if "\n" in cmd or "\r" in cmd:
        raise GuardError("one line only")
    verb, words = _final(cmd)
    if cmd.startswith(("execute", "minecraft:execute")) and " run " not in cmd:
        if " if " not in f" {cmd} " and " unless " not in f" {cmd} ":
            raise GuardError("an execute that runs nothing is a test")
        return
    if verb == "summon":
        icon = len(words) > 1 and words[1] == "minecraft:item" and "PickupDelay:32767" in cmd
        if len(words) < 2 or (words[1] not in SAFE_SUMMONS and not icon):
            raise GuardError(f"the companion never summons {words[1] if len(words) > 1 else 'nothing'}")
        if f'"{TAG}"' not in cmd:
            raise GuardError(f"every entity the companion summons carries the {TAG} tag")
        return
    if verb == "playsound":
        if len(words) < 2 or words[1] not in GENTLE_SOUNDS:
            raise GuardError(f"not a gentle sound: {words[1] if len(words) > 1 else ''}")
        try:
            volume = float(words[7]) if len(words) > 7 else 1.0
        except ValueError:
            raise GuardError("an unreadable volume") from None
        if volume > MAX_VOLUME:
            raise GuardError(f"too loud ({volume})")
        if len(words) < 4 or words[3].startswith("@"):
            raise GuardError("a sound is for one named player")
        return
    if verb == "particle":
        return
    if verb == "kill":
        if len(words) < 2 or not _own_selector(words[1]):
            raise GuardError("the companion only removes its own entities")
        return
    if verb in ("tp", "teleport"):
        if len(words) < 2 or words[1] != "@s" or f"as @e[tag={TAG}" not in cmd:
            raise GuardError("the companion only moves its own entities")
        return
    if verb == "bossbar":
        # A job's boss bar, and only the companion's own (`bruh_companion:…`):
        # what an iPad player on Geyser sees of a job going on.
        if len(words) < 3 or words[1] not in ("add", "set", "remove") \
                or not BAR_ID.fullmatch(words[2]):
            raise GuardError("the companion only changes its own boss bars")
        if words[1] == "set" and len(words) > 4 and words[3] == "players" \
                and words[4].startswith("@"):
            raise GuardError("a boss bar is for one named player")
        return
    if verb in ("title", "tellraw"):
        if len(words) < 2 or words[1].startswith("@"):
            raise GuardError("words go to one named player")
        return
    if verb in ("give", "clear"):
        tail = cmd.rsplit(" run ", 1)[-1] if " run " in cmd else cmd
        m = _ITEM_COMMAND.match(tail)
        if not m or m.group("who").startswith("@"):
            raise GuardError("an item is for one named player, with no data but a name")
        try:
            block_id(m.group("item"))
        except CompanionError as exc:
            raise GuardError(str(exc)) from None
        count = int(m.group("count") or 1)
        if verb == "clear" and (m.group("count") is None or count != 0):
            raise GuardError("the companion only counts what a player has (clear … 0)")
        if count > GIFT_MAX:
            raise GuardError("too many")
        return
    if verb in ("setblock", "forceload"):
        if not placing:
            raise GuardError("blocks change only through place_blocks or an undo")
        if verb == "setblock":
            try:
                block_id(words[4] if len(words) > 4 else "", None)
            except CompanionError as exc:
                raise GuardError(str(exc)) from None
        return
    raise GuardError(f"the companion does not use '{verb}'")


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------
class Zones:
    """Named places (`places.json`, which the collector also reads for
    "near X" and the place events), with a `protect` flag: nothing is ever
    built inside a protected one. A companion sets them (`set_zone`); the
    rule is held here, next to the blocks."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def list(self) -> list[dict[str, Any]]:
        data = _read_json(self.path, [])
        if isinstance(data, dict):
            data = data.get("places") or []
        return [p for p in data if isinstance(p, dict) and p.get("name")]

    def save(self, zone: Any) -> dict[str, Any]:
        if not isinstance(zone, dict):
            raise CompanionError("A place is an object.")
        name = str(zone.get("name") or "").strip()[:60]
        if not name:
            raise CompanionError("A place needs a name.")
        try:
            x, z = float(zone["x"]), float(zone["z"])
            radius = max(1, min(512, int(float(zone.get("radius") or 16))))
        except (KeyError, TypeError, ValueError):
            raise CompanionError("A place needs x and z (and a radius up to 512).") from None
        dim = str(zone.get("dimension") or "minecraft:overworld")
        if not re.fullmatch(r"[a-z0-9_.\-]+:[a-z0-9_./\-]+", dim):
            raise CompanionError("dimension is an id like minecraft:overworld.")
        kind = str(zone.get("kind") or "family")
        kind = kind if kind in ("family", "companion") else "family"
        clean = {"name": name, "x": x, "z": z, "radius": radius, "dimension": dim,
                 "protect": bool(zone.get("protect", kind != "companion")), "kind": kind}
        places = [p for p in self.list() if p.get("name") != name]
        places.append(clean)
        _atomic_write_json(self.path, places)
        return clean

    def delete(self, name: str) -> bool:
        places = self.list()
        kept = [p for p in places if p.get("name") != name]
        if len(kept) == len(places):
            return False
        _atomic_write_json(self.path, kept)
        return True

    def protected_at(self, x: float, z: float, dim: str) -> str | None:
        for p in self.list():
            if not p.get("protect"):
                continue
            if (p.get("dimension") or "minecraft:overworld") != dim:
                continue
            try:
                dx, dz = x - float(p["x"]), z - float(p["z"])
                r = float(p.get("radius") or 16)
            except (KeyError, TypeError, ValueError):
                continue
            if dx * dx + dz * dz <= r * r:
                return str(p["name"])
        return None


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
def _new_id(now: float) -> str:
    return time.strftime("%Y%m%d", time.localtime(now)) + "-" + secrets.token_hex(3)


class ActionLog:
    """Everything the companion did in the world, newest first, with what it
    changed (`cells`: each block's before and after; `tag`: its entities),
    so an undo can put it back (`.bruh-world/companion/actions.json`)."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        data = _read_json(self.path, {})
        acts = data.get("actions") if isinstance(data, dict) else []
        acts = [a for a in (acts or []) if isinstance(a, dict) and a.get("id")]
        acts.sort(key=lambda a: a.get("t") or 0, reverse=True)
        return acts[:max(0, limit)]

    def get(self, action_id: str) -> dict[str, Any] | None:
        """One action, with its cells (read from beside the log when kept there)."""
        act = next((a for a in self.list(MAX_ACTIONS) if a.get("id") == action_id), None)
        if act is not None and act.get("cells_file"):
            data = _read_json(self._cells_path(action_id), {})
            act = dict(act, cells=data.get("cells") if isinstance(data, dict) else [])
            act.pop("cells_file", None)
        return act

    def _cells_path(self, action_id: str) -> Path:
        return self.path.parent / "actions" / f"{action_id}.json"

    def start(self, kind: str, player: str | None, text: str, **extra) -> dict[str, Any]:
        now = self.clock()
        act = {"id": _new_id(now), "t": int(now), "kind": kind, "player": player,
               "text": text, "status": "active", "cells": [], "tag": "", "ended_at": None,
               **extra}
        act["tag"] = f"{TAG}_" + act["id"].split("-")[1]
        self.put(act)
        return act

    def put(self, act: dict[str, Any]) -> None:
        cells = act.get("cells") or []
        if len(cells) > INLINE_CELLS:
            _atomic_write_json(self._cells_path(act["id"]), {"cells": cells})
            act = dict(act, cells=[], cells_file=True,
                       placed_left=any(c.get("placed") for c in cells))
        with self._lock:
            acts = [a for a in self.list(MAX_ACTIONS) if a.get("id") != act["id"]]
            acts.append(act)
            acts.sort(key=lambda a: a.get("t") or 0, reverse=True)
            _atomic_write_json(self.path, {"actions": acts[:MAX_ACTIONS]})
            for gone in acts[MAX_ACTIONS:]:
                if gone.get("cells_file"):
                    try:
                        self._cells_path(gone["id"]).unlink()
                    except OSError:
                        # Already gone: nothing is left to undo of it either way.
                        pass


class SaidLog:
    """What the companion said in chat, newest first
    (`.bruh-world/companion/said.json`), for the panel's card."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def list(self, limit: int = 30) -> list[dict[str, Any]]:
        data = _read_json(self.path, {})
        rows = data.get("said") if isinstance(data, dict) else []
        rows = [r for r in (rows or []) if isinstance(r, dict) and r.get("id")]
        rows.sort(key=lambda r: r.get("t") or 0, reverse=True)
        return rows[:max(0, limit)]

    def add(self, **row) -> dict[str, Any]:
        now = self.clock()
        row = {"id": _new_id(now), "t": int(now), **row}
        with self._lock:
            rows = [row] + self.list(MAX_SAID)
            try:
                _atomic_write_json(self.path, {"said": rows[:MAX_SAID]})
            except OSError:
                # The card loses a line; the game does not.
                pass
        return row


def _runs(cells: dict[tuple[int, int, int], Any]) -> list[tuple[int, int, int, int, Any]]:
    """Cells as runs along +x of one value: (x1, x2, y, z, value)."""
    out: list[list[Any]] = []
    for (x, y, z) in sorted(cells, key=lambda c: (c[1], c[2], c[0])):
        v = cells[(x, y, z)]
        last = out[-1] if out else None
        if last and last[2] == y and last[3] == z and last[1] == x - 1 and last[4] == v \
                and x - last[0] < FILL_MAX:
            last[1] = x
        else:
            out.append([x, x, y, z, v])
    return [tuple(r) for r in out]


def _without(cells: list[dict[str, Any]], gone: set[tuple[int, int, int]]) -> list[dict[str, Any]]:
    """An edit's run records with the cells in `gone` taken out of them."""
    out: list[dict[str, Any]] = []
    for c in cells:
        run: list[int] = []
        for x in range(c["x"], c["x"] + int(c.get("n") or 1)):
            if (x, c["y"], c["z"]) in gone:
                if run:
                    out.append(dict(c, x=run[0], n=len(run)))
                run = []
            else:
                run.append(x)
        if run:
            out.append(dict(c, x=run[0], n=len(run)))
    return out


def undoable(act: dict[str, Any]) -> bool:
    if act.get("status") in ("undone", "failed"):
        return False
    if act.get("cells_file"):
        return act.get("status") == "active" or bool(act.get("placed_left"))
    return act.get("status") == "active" or any(c.get("placed") for c in act.get("cells") or [])


class Questions:
    """Questions waiting for, being shown to, and answered by a player."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def list(self, status: str | None = None) -> list[dict[str, Any]]:
        data = _read_json(self.path, {})
        qs = data.get("questions") if isinstance(data, dict) else []
        qs = [q for q in (qs or []) if isinstance(q, dict) and q.get("id")]
        qs.sort(key=lambda q: q.get("created_at") or 0, reverse=True)
        return [q for q in qs if not status or q.get("status") == status]

    def get(self, qid: str) -> dict[str, Any] | None:
        return next((q for q in self.list() if q.get("id") == qid), None)

    def put(self, q: dict[str, Any]) -> None:
        with self._lock:
            qs = [x for x in self.list() if x.get("id") != q["id"]]
            qs.append(q)
            qs.sort(key=lambda x: x.get("created_at") or 0, reverse=True)
            _atomic_write_json(self.path, {"questions": qs[:MAX_QUESTIONS]})


def clean_options(options: Any) -> list[dict[str, Any]]:
    """Two or three choices, each a label, a picture block, maybe an item
    shown above its pad, and maybe a gift."""
    if options in (None, "", []):
        options = [{"label": "yes"}, {"label": "no"}]
    if not isinstance(options, list) or len(options) not in PAD_LAYOUTS:
        raise CompanionError("A pad question has two or three options.")
    out = []
    for i, o in enumerate(options):
        if isinstance(o, str):
            o = {"label": o}
        if not isinstance(o, dict):
            raise CompanionError("Each option is a label, or {label, picture, item, gift}.")
        label = str(o.get("label") or "").strip()[:40]
        if not label:
            raise CompanionError("Each option needs a label.")
        carpet, picture = PAD_COLOURS[i]
        opt = {"label": label, "picture": block_id(o.get("picture"), picture), "pad": carpet}
        if o.get("item"):
            opt["item"] = item_id(o["item"])
        if o.get("gift"):
            opt["gift"] = block_id(o["gift"])
            try:
                opt["gift_count"] = max(1, min(GIFT_MAX, int(o.get("gift_count") or 1)))
            except (TypeError, ValueError):
                opt["gift_count"] = 1
        out.append(opt)
    return out


# ---------------------------------------------------------------------------
# The hands
# ---------------------------------------------------------------------------
class Companion:
    """Body, words, pads and blocks, beat by beat beside the collector.

    `step()` runs after every collector beat on the world thread; the API
    (`say`, `appear`, `ask`, `build`, `undo`) is called from request
    threads, so state is under one lock and the RCON session has its own.

    Who the companion is in the game (`identity`: the name and colour a
    companion goes by, and whether one is running) is what brAIn last told
    it (`set_identity`), kept per world in `.bruh-world/companion/
    companion.json`. Every call may also name its own speaker.
    """

    def __init__(self, collector, *,
                 emit: Callable[[str, dict], Any] | None = None,
                 snapshot: Callable[[], str | None] | None = None,
                 modern: Callable[[], bool] = lambda: True,
                 item_syntax: Callable[[], str] = lambda: "snbt",
                 accounts: Callable[[], dict] | None = None,
                 reader: Callable[[str, tuple], Any] | None = None,
                 reading: Callable[[], Any] | None = None,
                 clock: Callable[[], float] = time.time):
        self.col = collector
        # The world's blocks as saved (the panel's: `save-all flush`, then
        # mcmap's region reader): `reader(dimension, (x1, y1, z1, x2, y2, z2))`
        # → {(x, y, z): block state}, or why not (mcmap.Unread, or None).
        self.reader = reader
        # Called once before a look or an edit reads the world, so the
        # panel's read from disk saves first instead of trusting a save
        # from a moment ago — which an edit just made stale (#776).
        self.reading = reading or (lambda: None)
        self.pause = time.sleep
        self.clock = clock
        self.emit_fn = emit or (lambda kind, data: None)
        self.snapshot_fn = snapshot
        self.modern = modern
        self.item_syntax = item_syntax
        self.accounts_fn = accounts or (lambda: account_check(self.col.server_dir))
        data_dir = Path(collector.data_dir)
        self.root = data_dir / DIR_NAME
        self.data_dir = data_dir
        if not (self.root / "actions.json").exists():
            try:
                legacy.carry_mechanics(data_dir, self.root)
            except OSError:
                # The old logs only matter to an undo of an old action.
                pass
        self.zones = Zones(data_dir / "places.json")
        self.actions = ActionLog(self.root / "actions.json", clock)
        self.questions = Questions(self.root / "questions.json", clock)
        self.said = SaidLog(self.root / "said.json", clock)
        self.identity_path = self.root / "companion.json"
        self.epoch = f"{TAG}_e" + secrets.token_hex(3)
        self._lock = threading.RLock()
        self.live: dict[str, dict[str, Any]] = {}     # action id -> its live state
        self.asking: dict[str, Any] | None = None     # the open pad question
        self.swept = False
        self.state = "idle"
        self.last_note = ""
        self._accounts: tuple[float, dict[str, Any]] | None = None

    # -- who the companion is ------------------------------------------------
    def identity(self) -> dict[str, Any]:
        data = _read_json(self.identity_path, {})
        data = data if isinstance(data, dict) else {}
        return {"name": speaker_name(data.get("name")), "colour": colour(data.get("colour")),
                "active": bool(data.get("active", False)), "by": str(data.get("by") or "")[:40],
                "model": str(data.get("model") or "")[:60], "at": data.get("at")}

    def set_identity(self, name: Any = None, colour_: Any = None, active: Any = None,
                     by: Any = None, model: Any = None) -> dict[str, Any]:
        with self._lock:
            cur = self.identity()
            if name is not None:
                cur["name"] = speaker_name(name)
            if colour_ is not None:
                cur["colour"] = colour(colour_)
            if active is not None:
                cur["active"] = bool(active)
            if by is not None:
                cur["by"] = str(by)[:40]
            if model is not None:
                cur["model"] = str(model)[:60]
            cur["at"] = int(self.clock())
            _atomic_write_json(self.identity_path, cur)
            if not cur["active"] and (self.live or self.asking) and self.col.sessions:
                self._wind_down("The companion was switched off.")
            return cur

    def _speaker(self, name: Any, colour_: Any) -> tuple[str, str]:
        ident = self.identity()
        return (speaker_name(name, ident["name"]) if name else ident["name"],
                colour(colour_, ident["colour"]) if colour_ else ident["colour"])

    def accounts(self) -> dict[str, Any]:
        now = self.clock()
        if self._accounts is None or now - self._accounts[0] > ACCOUNT_STALE:
            try:
                value = dict(self.accounts_fn() or {})
            except Exception:  # noqa: BLE001 — unreadable: believe no name
                value = {"java": False, "bedrock": False,
                         "why_java": "the server's settings could not be read",
                         "why_bedrock": "the server's settings could not be read"}
            self._accounts = (now, value)
        return self._accounts[1]

    def verified(self, player: str | None) -> tuple[bool, str]:
        """Whether a chat line under this name can be believed, for the events."""
        if not player:
            return False, "the line's name is not anybody playing"
        return trusted(self.accounts(), player)

    # -- commands ------------------------------------------------------------
    def _cmd(self, cmd: str, placing: bool = False) -> str:
        check_command(cmd, placing=placing)
        return self.col.session.command(cmd)

    def _try(self, cmd: str, placing: bool = False) -> str | None:
        try:
            return self._cmd(cmd, placing)
        except GuardError:
            raise
        except Exception:  # noqa: BLE001 — a server that went away mid-beat
            return None

    def _test(self, cmd: str) -> bool | None:
        reply = self._try(cmd)
        return None if reply is None else parse_test(reply)

    def _online(self, player: str) -> str | None:
        """The online player a name means (case and Bedrock prefix ignored)."""
        want = bare(player)
        return next((p for p in sorted(self.col.sessions) if bare(p) == want), None)

    def _tell(self, player: str, text: str, name: str, colour_: str) -> None:
        line = " ".join(str(text).split())[:REPLY_LINE_CHARS * 2]
        comp = json.dumps(["", {"text": f"<{name}> ", "color": colour_},
                           {"text": line, "color": "white"}], ensure_ascii=False)
        self._try(f"minecraft:tellraw {quote_name(player)} {comp}")

    def _name_nbt(self, name: str, colour_: str) -> str:
        comp = text_component(name, colour_)
        return f"CustomName:{comp}" if self.modern() else f"CustomName:'{comp}'"

    def _body_nbt(self, tag: str, name: str, colour_: str) -> str:
        return ("{NoAI:1b,NoGravity:1b,Invulnerable:1b,Silent:1b,PersistenceRequired:1b,"
                f"CustomNameVisible:1b,{self._name_nbt(name, colour_)},"
                f'Tags:["{TAG}","{self.epoch}","{tag}"]}}')

    def _chime(self, player: str, pitches=(1.0, 1.26, 1.5), volume: float = 0.6) -> None:
        who = quote_name(player)
        for p in pitches:
            self._try(f"minecraft:execute at {who} run minecraft:playsound "
                      f"minecraft:block.note_block.chime master {who} ~ ~ ~ {volume} {p}")

    def _sparkle_at_tag(self, tag: str, count: int = 14, kind: str = "minecraft:happy_villager") -> None:
        self._try(f"minecraft:execute at @e[tag={tag},limit=1] run minecraft:particle "
                  f"{kind} ~ ~0.6 ~ 0.4 0.4 0.4 0 {count}")

    def _remove_tag(self, tag: str, poof: bool = True) -> None:
        if poof:
            self._sparkle_at_tag(tag, 10, "minecraft:poof")
        self._try(f"minecraft:kill @e[tag={tag}]")

    def interval(self, default: float) -> float:
        return FAST_INTERVAL if (self.asking or self.live) else default

    # -- one beat ------------------------------------------------------------
    def step(self) -> None:
        with self._lock:
            self._step()

    def _step(self) -> None:
        now = self.clock()
        online = list(self.col.sessions)
        if not online:
            if self.live or self.asking:
                self._wind_down("Everyone left.")
            self.swept = False
            self.state = "idle"
            return
        if not self.swept:
            # Anything an earlier run of this panel (or the old engine) left.
            self._try(f"minecraft:kill @e[tag={TAG},tag=!{self.epoch}]")
            for selector in legacy.kill_selectors():
                self._try(f"minecraft:kill {selector}")
            self.swept = True
        self._run_live(now)
        self._run_questions(online, now)
        self.state = "asking" if self.asking else "acting" if self.live else "idle"

    # -- words ---------------------------------------------------------------
    def say(self, to: Any, text: Any, name: Any = None, colour_: Any = None,
            chime: bool = False, by: str = "") -> dict[str, Any]:
        """Words in chat as `<name> text`, to named players (a name, a list of
        names, or "everyone" for every player on). Raises CompanionError
        when nothing could be said."""
        with self._lock:
            text = " ".join(str(text or "").split())[:REPLY_LINE_CHARS * REPLY_LINES]
            if not text:
                raise CompanionError("Nothing to say.")
            if not self.col.sessions:
                raise CompanionError("Nobody is in the game, so there is nobody to say it to.")
            name, col = self._speaker(name, colour_)
            players, missing = self._players(to)
            if not players:
                raise CompanionError(f"{', '.join(missing) or 'Nobody'} is not in the game right now.")
            lines = split_reply(text)
            for p in players:
                for line in lines:
                    self._tell(p, line, name, col)
                if chime:
                    self._chime(p, pitches=(1.26, 1.5), volume=0.5)
            self.said.add(to=players, text=text, name=name, by=str(by or "")[:40])
            return {"sent": players, "missing": missing, "lines": lines, "name": name}

    def _players(self, to: Any) -> tuple[list[str], list[str]]:
        """The online players a name, a list of names or "everyone" means,
        and the names that are not on."""
        targets = to if isinstance(to, list) else [to]
        players: list[str] = []
        missing: list[str] = []
        for t in targets:
            t = str(t or "").strip()
            if t.lower() in EVERYONE:
                players.extend(sorted(self.col.sessions))
                continue
            found = self._online(t)
            if found:
                players.append(found)
            else:
                missing.append(t)
        return list(dict.fromkeys(players)), missing

    def progress(self, to: Any, text: Any, percent: Any = None, colour_: Any = None
                 ) -> dict[str, Any]:
        """A long job's progress on named players' action bar (above the
        hotbar): seen, never in chat, gone after a few seconds."""
        with self._lock:
            line = " ".join(str(text or "").split())[:REPLY_LINE_CHARS]
            if not line:
                raise CompanionError("What is the progress? (text is empty)")
            if percent not in (None, ""):
                try:
                    pct = max(0, min(100, int(round(float(percent)))))
                except (TypeError, ValueError):
                    raise CompanionError("percent is a number from 0 to 100.") from None
                line = f"{line} — {pct}%"
            players, missing = self._players(to)
            if not players:
                raise CompanionError(f"{', '.join(missing) or 'Nobody'} is not in the game "
                                     "right now.")
            _, col = self._speaker(None, colour_)
            comp = text_component(line, col)
            for p in players:
                self._try(f"minecraft:title {quote_name(p)} actionbar {comp}")
            return {"sent": players, "missing": missing, "text": line}

    def bar(self, player: Any, key: Any, text: Any = None, percent: Any = None,
            end: bool = False) -> dict[str, Any]:
        """A long job's boss bar at the top of one player's screen: its
        title, the last step and how far along it is. Java and Bedrock (via
        Geyser) both draw boss bars, so a player on a tablet sees a job going
        on. `end` takes it away. Its own namespace only (`check_command`)."""
        with self._lock:
            key = str(key or "").strip().lower()
            if not BAR_KEY.fullmatch(key):
                raise CompanionError("key is a job's id: letters, digits, _ and -.")
            bar_id = f"{TAG}:{key}"
            if end:
                self._try(f"minecraft:bossbar remove {bar_id}")
                return {"bar": bar_id, "removed": True}
            line = " ".join(str(text or "").split())[:REPLY_LINE_CHARS]
            if not line:
                raise CompanionError("What does the bar say? (text is empty)")
            pct = None
            if percent not in (None, ""):
                try:
                    pct = max(0, min(100, int(round(float(percent)))))
                except (TypeError, ValueError):
                    raise CompanionError("percent is a number from 0 to 100.") from None
            found = self._online(str(player or ""))
            if not found:
                raise CompanionError(f"{player} is not in the game right now.")
            _, col = self._speaker(None, None)
            comp = text_component(line, col)
            # `add` answers an error when the bar is already there: that is
            # the bar this updates.
            self._try(f"minecraft:bossbar add {bar_id} {comp}")
            self._try(f"minecraft:bossbar set {bar_id} name {comp}")
            self._try(f"minecraft:bossbar set {bar_id} color purple")
            self._try(f"minecraft:bossbar set {bar_id} max 100")
            if pct is not None:
                self._try(f"minecraft:bossbar set {bar_id} value {pct}")
            self._try(f"minecraft:bossbar set {bar_id} players {quote_name(found)}")
            return {"bar": bar_id, "player": found, "text": line, "percent": pct}

    def give_spyglass(self, player: Any, name: Any) -> dict[str, Any]:
        """One spyglass named `name` for a player, unless they already have
        a spyglass by that name (counted with `clear … 0`, which takes
        nothing). The spyglass is how anybody points at something for the
        companion (the bruh_companion data pack)."""
        with self._lock:
            found = self._online(str(player or ""))
            if not found:
                raise CompanionError(f"{player} is not in the game right now.")
            label = " ".join(re.sub(r"[^\w '\-.!?]", "", str(name or "")).split())
            label = label[:SPYGLASS_NAME_MAX].strip()
            if not label:
                raise CompanionError("Give the spyglass a name.")
            item = named_item("minecraft:spyglass", label, self.item_syntax())
            who = quote_name(found)
            reply = self._try(f"minecraft:clear {who} {item} 0")
            text = _COLOUR_CODE.sub("", reply or "")
            m = re.search(r"Found (\d+) matching item", text, re.I)
            if m and int(m.group(1)) > 0:
                return {"player": found, "name": label, "given": False, "had": int(m.group(1))}
            if not m and not re.search(r"No items were found", text, re.I):
                raise CompanionError("The server would not say what they have: "
                                     f"{(reply or 'no answer')[:120]}")
            reply = self._try(f"minecraft:give {who} {item} 1")
            if reply is None or not re.search(r"^Gave ", _COLOUR_CODE.sub("", reply).strip()):
                raise CompanionError(f"The server would not give it: {(reply or 'no answer')[:120]}")
            return {"player": found, "name": label, "given": True, "had": 0}

    # -- a body ----------------------------------------------------------------
    def appear(self, player: Any, seconds: Any = 25, kind: str = "greet", name: Any = None,
               colour_: Any = None, chime: str = "full", text: str = "",
               by: str = "") -> dict[str, Any]:
        """The companion's body beside `player` for a while (a greeting, a
        visit). Raises CompanionError when they are not on."""
        with self._lock:
            found = self._online(str(player or ""))
            if not found:
                raise CompanionError(f"{player} is not in the game right now.")
            try:
                lifetime = max(3, min(APPEAR_MAX, int(seconds)))
            except (TypeError, ValueError):
                raise CompanionError("seconds is a number from 3 to 120.") from None
            kind = kind if kind in ("greet", "visit") else "visit"
            name, col = self._speaker(name, colour_)
            pitches = {"full": (1.0, 1.26, 1.5), "short": (1.26, 1.5)}.get(chime, ())
            now = self.clock()
            act = self.actions.start(kind, found, str(text or f"{name} came over to {found}.")[:200],
                                     by=str(by or "")[:40], name=name)
            tag = act["tag"]
            p = quote_name(found)
            reply = self._try(f"minecraft:execute at {p} rotated ~ 0 run minecraft:summon "
                              f"minecraft:allay ^ ^1.2 ^2 {self._body_nbt(tag, name, col)}")
            if reply is None or not re.search(r"summoned", reply, re.I):
                act.update(status="failed", ended_at=int(now),
                           note=(reply or "The server did not answer.")[:200])
                self.actions.put(act)
                raise CompanionError(f"The server would not summon the companion: "
                                     f"{(reply or 'no answer')[:120]}")
            if pitches:
                self._chime(found, pitches=pitches)
            self._sparkle_at_tag(tag)
            self._try(f"minecraft:execute as @e[tag={tag},limit=1] at @s run minecraft:tp @s "
                      f"~ ~ ~ facing entity {p} eyes")
            self.live[act["id"]] = {"kind": kind, "player": found, "tag": tag,
                                    "beats": 0, "ends_at": now + lifetime}
            self.col.record({"kind": "companion", "player": found, "action": act["id"],
                             "text": act["text"]})
            return dict(act, undoable=undoable(act))

    def _run_live(self, now: float) -> None:
        for aid, live in list(self.live.items()):
            tag = live["tag"]
            live["beats"] += 1
            if now >= live["ends_at"] or live["player"] not in self.col.sessions:
                self._end_live(aid, "done")
                continue
            if live["beats"] in (1, 3):            # the wave: up …
                self._try(f"minecraft:execute as @e[tag={tag},limit=1] at @s run "
                          "minecraft:tp @s ~ ~0.5 ~ ~30 ~")
            elif live["beats"] in (2, 4):          # … and down, sparkling
                self._try(f"minecraft:execute as @e[tag={tag},limit=1] at @s run "
                          "minecraft:tp @s ~ ~-0.5 ~ ~-30 ~")
                self._sparkle_at_tag(tag, 8)

    def _end_live(self, aid: str, status: str) -> None:
        live = self.live.pop(aid, None)
        if live:
            self._remove_tag(live["tag"])
        act = self.actions.get(aid)
        if act and act.get("status") == "active":
            act.update(status=status, ended_at=int(self.clock()))
            self.actions.put(act)

    def _wind_down(self, why: str) -> None:
        """Take every live thing out of the world (the transition to quiet)."""
        for aid in list(self.live):
            self._end_live(aid, "done")
        if self.asking:
            self._close_question(requeue=True, note=why)
        self.last_note = why
        if not self.col.sessions:
            # Nobody to watch: give the connection back, as the collector does.
            self.col.session.close()

    def _pos(self, player: str) -> tuple[list[float], str] | None:
        info = self.col.players.get(player) or {}
        pos = info.get("pos")
        if not pos:
            return None
        return list(pos), info.get("dimension") or "minecraft:overworld"

    # -- blocks ----------------------------------------------------------------
    def build(self, blocks: Any, player: Any = None, dimension: Any = None,
              title: Any = "", by: str = "", name: Any = None) -> dict[str, Any]:
        """A small build: `blocks` [{x, y, z, block}], relative to `player`'s
        feet when one is named, else absolute (and then within BUILD_REACH of
        somebody playing). Through `place_blocks`: empty cells only, natural
        ground under the bottom layer, never in a protected place or on or
        next to a build, logged and undoable."""
        with self._lock:
            if not self.col.sessions:
                raise CompanionError("Nobody is in the game.")
            if not isinstance(blocks, list) or not blocks:
                raise CompanionError("blocks is a list of {x, y, z, block}.")
            if len(blocks) > BUILD_MAX:
                raise CompanionError(f"At most {BUILD_MAX} blocks in one build.")
            speaker, _ = self._speaker(name, None)
            base = None
            beside = None
            if player:
                beside = self._online(str(player))
                if not beside:
                    raise CompanionError(f"{player} is not in the game right now.")
                here = self._pos(beside)
                if not here:
                    raise CompanionError(f"Where {beside} is is not known yet.")
                pos, dim = here
                base = [math.floor(c) for c in pos]
            cells, seen = [], set()
            for b in blocks:
                if not isinstance(b, dict):
                    raise CompanionError("Each block is {x, y, z, block}.")
                try:
                    x, y, z = (int(b[k]) for k in ("x", "y", "z"))
                except (KeyError, TypeError, ValueError):
                    raise CompanionError("Each block needs whole-number x, y and z.") from None
                if base is not None:
                    if max(abs(x), abs(y), abs(z)) > BUILD_REACH:
                        raise CompanionError(f"Offsets are at most {BUILD_REACH} blocks.")
                    x, y, z = x + base[0], y + base[1], z + base[2]
                if not -64 <= y <= 319:
                    raise CompanionError("That is outside the world's height.")
                if (x, y, z) in seen:
                    raise CompanionError("Two blocks in the same place.")
                seen.add((x, y, z))
                cells.append({"x": x, "y": y, "z": z, "block": block_id(b.get("block"))})
            if base is None:
                dim = self._work_dim(dimension, near=(cells[0]["x"], cells[0]["z"]))
            here_all = [self._pos(p) for p in self.col.sessions]
            here_all = [f for f in here_all if f and f[1] == dim]
            if base is None and not all(
                    any(math.hypot(c["x"] - f[0][0], c["z"] - f[0][2]) <= BUILD_REACH
                        for f in here_all) for c in cells):
                raise CompanionError("The companion builds only near somebody playing.")
            for p in self.col.sessions:
                at = self._pos(p)
                if not at or at[1] != dim:
                    continue
                fx, fy, fz = (math.floor(v) for v in at[0])
                if (fx, fy, fz) in seen or (fx, fy + 1, fz) in seen:
                    raise CompanionError("Somebody is standing there.")
            low = min(c["y"] for c in cells)
            for c in cells:
                if c["y"] == low:
                    c["ground"] = True
            title = " ".join(str(title or "").split())[:60] or f"{len(cells)} blocks"
            who = str(by or "")[:40]
            text = f"{speaker} built {title}" + (f" beside {beside}" if beside else "") + \
                (f" (asked by {who})" if who else "")
            act = self.actions.start("build", beside, text, by=who, name=speaker)
            why = self.place_blocks(act, cells, dim)
            now = self.clock()
            if why:
                act.update(status="failed", ended_at=int(now), note=why[:200])
                self.actions.put(act)
                raise CompanionError(why)
            act.update(status="done", ended_at=int(now))
            self.actions.put(act)
            self.col.record({"kind": "companion", "player": beside,
                             "action": act["id"], "text": text[:240]})
            return dict(act, undoable=undoable(act))

    def footprint_refusal(self, cells: list[dict[str, Any]], dim: str) -> str:
        """Why these cells are somebody else's, or ''."""
        for c in cells:
            zone = self.zones.protected_at(c["x"] + 0.5, c["z"] + 0.5, dim)
            if zone:
                return f"That is inside {zone}, which is protected."
        for job in self.col.builds.list(limit=200):
            b = job.get("bounds")
            if not b or (b.get("dimension") or "minecraft:overworld") != dim:
                continue
            x1, x2 = sorted((b["x1"], b["x2"]))
            z1, z2 = sorted((b["z1"], b["z2"]))
            for c in cells:
                if x1 - 1 <= c["x"] <= x2 + 1 and z1 - 1 <= c["z"] <= z2 + 1:
                    return f"That is on {job.get('title') or 'a build'}."
        return ""

    def _natural(self, x: int, y: int, z: int, dim: str) -> bool:
        for ground in NATURAL_GROUND:
            ok = self._test(f"minecraft:execute in {dim} if block {x} {y} {z} {ground}")
            if ok is None:
                return False
            if ok:
                return True
        return False

    def _air(self, x: int, y: int, z: int, dim: str) -> bool:
        return bool(self._test(f"minecraft:execute in {dim} if block {x} {y} {z} minecraft:air"))

    def place_blocks(self, act: dict[str, Any], cells: list[dict[str, Any]], dim: str) -> str:
        """Put `cells` ({x,y,z,block}) into the world for `act`; '' or why not.

        Every cell must be air; the ground under any cell marked `ground`
        must be natural. Placed with `keep`, recorded in the action before
        and after each one, and taken back out if any of them fails.
        """
        why = self.footprint_refusal(cells, dim)
        if why:
            return why
        for c in cells:
            if not self._air(c["x"], c["y"], c["z"], dim):
                return "Something is already there."
            if c.get("ground") and not self._natural(c["x"], c["y"] - 1, c["z"], dim):
                return "The ground there is not natural ground."
        if len(cells) >= LARGE_CHANGE:
            note = self.snapshot_fn() if self.snapshot_fn else "no snapshot available"
            if note:
                return f"A change this large needs a snapshot first, and it failed: {note}"
        placed = []
        for c in cells:
            reply = self._try(f"minecraft:execute in {dim} run minecraft:setblock "
                              f"{c['x']} {c['y']} {c['z']} {c['block']} keep", placing=True)
            if reply is None or not re.search(r"changed the block", reply, re.I):
                act["cells"] = placed
                self._restore(act)
                return f"The server would not place {c['block']}: {(reply or 'no answer')[:120]}"
            placed.append({"x": c["x"], "y": c["y"], "z": c["z"], "dim": dim,
                           "before": "minecraft:air", "after": c["block"], "placed": True})
            act["cells"] = placed
        self.actions.put(act)
        return ""

    # -- a trusted edit: anything, anywhere, undoable -----------------------------
    def _raw(self, cmd: str) -> str | None:
        """A command for a trusted edit or its undo. Not the companion's own
        act, so not `check_command`'s: one line, and the server's answer."""
        if "\n" in cmd or "\r" in cmd:
            raise GuardError("one line only")
        for _ in range(2):
            # The session reconnects on the next command, so one dropped
            # connection costs a second ask (a fill or a setblock is the same
            # when said twice), not an edit that fails with no answer.
            try:
                return self.col.session.command(cmd)
            except Exception:  # noqa: BLE001 — a server that went away
                continue
        return None

    def _raw_loaded(self, cmd: str, dim: str, xs: tuple[int, int], zs: tuple[int, int],
                    forced: dict[tuple[str, int, int], bool]) -> str | None:
        """`_raw(cmd)`, and when the server says the place is not loaded:
        force-load its chunks (`forced` records each, and whether this
        edit loaded it), then ask again while they load."""
        reply = self._raw(cmd)
        if reply is None or not _NOT_LOADED.search(reply):
            return reply
        for cx in range(min(xs) >> 4, (max(xs) >> 4) + 1):
            for cz in range(min(zs) >> 4, (max(zs) >> 4) + 1):
                key = (dim, cx, cz)
                if key in forced:
                    continue
                if len(forced) >= FORCE_MAX:
                    return reply
                at = f"{cx * 16} {cz * 16}"
                said = self._raw(f"minecraft:execute in {dim} run minecraft:forceload query {at}")
                # A chunk somebody already keeps loaded is theirs to let go.
                mine = not (said and re.search(r"\bis marked\b", said, re.I))
                if mine:
                    self._raw(f"minecraft:execute in {dim} run minecraft:forceload add {at}")
                forced[key] = mine
        for _ in range(LOAD_TRIES):
            reply = self._raw(cmd)
            if reply is None or not _NOT_LOADED.search(reply):
                return reply
            self.pause(LOAD_WAIT_S)
        return reply

    def _release(self, forced: dict[tuple[str, int, int], bool]) -> None:
        for (dim, cx, cz), mine in forced.items():
            if mine:
                self._raw(f"minecraft:execute in {dim} run minecraft:forceload remove "
                          f"{cx * 16} {cz * 16}")
        forced.clear()

    def _work_dim(self, dimension: Any, job: str | None = None,
                  near: tuple[int, int] | None = None) -> str:
        """The dimension of a look, a build or an edit given by coordinates
        (#782): the one named; else its job's (where that job's earlier
        edits were made); else where the people playing are — the one
        nearest `near` when they are in several; else the Overworld."""
        dim = str(dimension or "").strip().lower()
        if dim and ":" not in dim:
            dim = "minecraft:" + VANILLA_DIMS.get(dim, dim)
        if not dim and job:
            for act in self.actions.list(MAX_ACTIONS):
                if act.get("job") == job:
                    cells = act.get("cells") or [{}]
                    dim = str(act.get("dimension") or cells[0].get("dim") or "")
                    if dim:
                        break
        if not dim:
            here = [h for h in (self._pos(p) for p in sorted(self.col.sessions)) if h]
            if here and near is not None:
                here.sort(key=lambda h: math.hypot(h[0][0] - near[0], h[0][2] - near[1]))
            dim = here[0][1] if here else "minecraft:overworld"
        if not re.fullmatch(r"[a-z0-9_.\-]+:[a-z0-9_./\-]+", dim):
            raise CompanionError("dimension is an id like minecraft:overworld.")
        return dim

    def _box_of(self, player: Any, x: Any, y: Any, z: Any, size: Any,
                dimension: Any) -> tuple[str, tuple[int, ...], str | None, list[int] | None]:
        sx, sy, sz = LOOK_DEFAULT
        if isinstance(size, (list, tuple)) and len(size) == 3:
            try:
                sx, sy, sz = (max(1, int(v)) for v in size)
            except (TypeError, ValueError):
                raise CompanionError("size is [x, y, z] in blocks.") from None
        sx, sy, sz = min(sx, LOOK_MAX[0]), min(sy, LOOK_MAX[1]), min(sz, LOOK_MAX[2])
        who, feet = None, None
        if player:
            who = self._online(str(player))
            if not who:
                raise CompanionError("That player is not in the game right now.")
            here = self._pos(who)
            if not here:
                raise CompanionError("Where that player is is not known yet.")
            pos, dim = here
            feet = [math.floor(c) for c in pos]
            cx, cy, cz = feet
            y1 = cy - 2
        else:
            try:
                cx, cy, cz = int(x), int(y), int(z)
            except (TypeError, ValueError):
                raise CompanionError("Give a player, or x, y and z.") from None
            dim = self._work_dim(dimension, near=(cx, cz))
            y1 = cy - sy // 2
        x1, z1 = cx - sx // 2, cz - sz // 2
        return dim, (x1, y1, z1, x1 + sx - 1, y1 + sy - 1, z1 + sz - 1), who, feet

    def look(self, player: Any = None, x: Any = None, y: Any = None, z: Any = None,
             size: Any = None, dimension: Any = None) -> dict[str, Any]:
        """What is in a box around a player (or a point): every block that is
        not air, by block state, as runs along x — walls, doors, beds,
        furniture — so a room can be understood before it is changed. Read
        from the world as saved, after a save; at most 32 × 16 × 32."""
        dim, box, who, feet = self._box_of(player, x, y, z, size, dimension)
        if self.reader is None:
            raise CompanionError("The world's blocks cannot be read here.")
        self.reading()
        states = self.reader(dim, box)
        if not isinstance(states, dict):
            raise CompanionError(f"{unread_why(states)} So it was not looked at.")
        blocks: dict[str, list[list[int]]] = {}
        for (bx, by, bz), st in states.items():
            if st.split("[", 1)[0] in ("minecraft:air", "minecraft:cave_air", "minecraft:void_air"):
                continue
            blocks.setdefault(st, []).append([bx, by, bz])
        runs: dict[str, list[list[int]]] = {}
        for st, cells in sorted(blocks.items()):
            out: list[list[int]] = []
            for bx, by, bz in sorted(cells, key=lambda c: (c[1], c[2], c[0])):
                last = out[-1] if out else None
                if last and last[1] == by and last[2] == bz and last[0] + last[3] == bx:
                    last[3] += 1
                else:
                    out.append([bx, by, bz, 1])
            runs[st] = out
        return {"dimension": dim, "box": dict(zip(("x1", "y1", "z1", "x2", "y2", "z2"), box)),
                "player": who, "feet": feet, "blocks": runs,
                "note": "Runs are [x, y, z, length] along +x; everything else in the box is air."}

    def _edit_targets(self, blocks: Any, fills: Any, base: list[int] | None,
                      shape_list: Any = None) -> tuple[dict[tuple[int, int, int], str], list[tuple]]:
        """{cell: new state} for every cell the edit sets, and the fill boxes
        (applied first, as one `fill` each). Fills first, then shapes in
        order, then single blocks: a later one wins a cell."""
        def at(item: dict, keys: tuple[str, ...]) -> list[int]:
            try:
                vals = [int(item[k]) for k in keys]
            except (KeyError, TypeError, ValueError):
                raise CompanionError("Coordinates are whole numbers.") from None
            if base is not None:
                if any(abs(v) > EDIT_REACH for v in vals):
                    raise CompanionError(f"Offsets are at most {EDIT_REACH} blocks.")
                vals = [v + base[i % 3] for i, v in enumerate(vals)]
            for i in range(1, len(vals), 3):
                if not -64 <= vals[i] <= 319:
                    raise CompanionError("That is outside the world's height.")
            return vals

        too_many = f"At most {EDIT_MAX} blocks in one edit; split it in two."
        targets: dict[tuple[int, int, int], str] = {}
        boxes: list[tuple] = []
        for f in (fills or []) if isinstance(fills, list) else []:
            if not isinstance(f, dict):
                raise CompanionError("Each fill is {x1, y1, z1, x2, y2, z2, block}.")
            x1, y1, z1, x2, y2, z2 = at(f, ("x1", "y1", "z1", "x2", "y2", "z2"))
            x1, x2 = sorted((x1, x2))
            y1, y2 = sorted((y1, y2))
            z1, z2 = sorted((z1, z2))
            st = block_state(f.get("block"))
            size = (x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1)
            if size > FILL_MAX:
                raise CompanionError(f"One fill is at most {FILL_MAX} blocks; use a box shape "
                                     "or split it.")
            if size + len(targets) > EDIT_MAX:
                raise CompanionError(too_many)
            boxes.append((x1, y1, z1, x2, y2, z2, st))
            for bx in range(x1, x2 + 1):
                for by in range(y1, y2 + 1):
                    for bz in range(z1, z2 + 1):
                        targets[(bx, by, bz)] = st
        for sh in (shape_list or []) if isinstance(shape_list, list) else []:
            st = block_state(sh.get("block") if isinstance(sh, dict) else None)
            try:
                cells = shapes.expand(sh, base=base, reach=EDIT_REACH,
                                      limit=EDIT_MAX - len(targets))
            except shapes.ShapeError as exc:
                raise CompanionError(str(exc)) from None
            for c in cells:
                targets[c] = st
            if len(targets) > EDIT_MAX:
                raise CompanionError(too_many)
        for b in (blocks or []) if isinstance(blocks, list) else []:
            if not isinstance(b, dict):
                raise CompanionError("Each block is {x, y, z, block}.")
            bx, by, bz = at(b, ("x", "y", "z"))
            remove = str(b.get("mode") or "").lower() == "remove"
            targets[(bx, by, bz)] = block_state("air" if remove else b.get("block"))
            if len(targets) > EDIT_MAX:
                raise CompanionError(too_many)
        if not targets:
            raise CompanionError("Give blocks ({x, y, z, block}), fills "
                                 "({x1, y1, z1, x2, y2, z2, block}) or shapes ({kind, block, …}).")
        return targets, boxes

    def _snapshot_states(self, dim: str, cells: list[tuple[int, int, int]]) -> Any:
        """The saved states of these cells (and their neighbours), read per
        chunk column; the reader's reason (`unread_why`) when any part
        cannot be read."""
        groups: dict[tuple[int, int], list[tuple[int, int, int]]] = {}
        for c in cells:
            groups.setdefault((c[0] >> 4, c[2] >> 4), []).append(c)
        out: dict[tuple[int, int, int], str] = {}
        for group in groups.values():
            xs = [c[0] for c in group]
            ys = [c[1] for c in group]
            zs = [c[2] for c in group]
            box = (min(xs) - 1, max(min(ys) - 1, -64), min(zs) - 1,
                   max(xs) + 1, min(max(ys) + 1, 319), max(zs) + 1)
            got = self.reader(dim, box) if self.reader else None
            if not isinstance(got, dict):
                return got
            out.update(got)
        return out

    def edit(self, blocks: Any = None, fills: Any = None, player: Any = None,
             dimension: Any = None, title: Any = "", by: str = "",
             name: Any = None, shapes: Any = None, job: Any = None) -> dict[str, Any]:
        """A trusted edit: what a grown-up who can ask for anything asked for
        through brAIn. Any block, anywhere — over existing blocks, inside or
        next to a build, in a protected place — placed, replaced or removed
        (`mode: "remove"`, or block air), boxes filled, and shapes (a
        tapering line, an ellipsoid, a blob, a cylinder, a box; panel/
        shapes.py). None of `place_blocks`' rules: those hold the
        companion's OWN acts. `job` is the caller's id for the work this is
        part of, recorded so `undo_job` can take all of it back.

        What makes it safe is the undo. Before anything changes, the world is
        saved and every cell's block state is read (with the other half of a
        bed or a door beside one), and the action records each before and
        after (as runs along x); an edit whose before cannot be read is not
        made. A large one is backed up first; a backup that fails is said,
        never a refusal. Cells are written as `fill` runs along x."""
        job = None if job in (None, "") else str(job).strip()
        if job is not None and not _JOB.match(job):
            raise CompanionError("A job id is letters, digits, dots, dashes and underscores, "
                                 "at most 40.")
        with self._lock:
            speaker, _ = self._speaker(name, None)
            base = None
            beside = None
            if player:
                beside = self._online(str(player))
                if not beside:
                    raise CompanionError("That player is not in the game right now.")
                here = self._pos(beside)
                if not here:
                    raise CompanionError("Where that player is is not known yet.")
                pos, dim = here
                base = [math.floor(c) for c in pos]
            targets, boxes = self._edit_targets(blocks, fills, base, shapes)
            if base is None:
                first = min(targets)
                dim = self._work_dim(dimension, job, near=(first[0], first[2]))
            self.reading()
            before = self._snapshot_states(dim, list(targets))
            if not isinstance(before, dict):
                raise CompanionError(f"{unread_why(before)} So the change could not be made "
                                     "undoable and was not made.")
            changed = {c: st for c, st in targets.items()
                       if before.get(c, "minecraft:air") != st}
            neighbours: list[tuple[int, int, int]] = []
            for (cx, cy, cz) in changed:
                for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1)):
                    n = (cx + d[0], cy + d[1], cz + d[2])
                    if n in changed or n in neighbours:
                        continue
                    if _MULTI_PART.search(before.get(n, "")):
                        neighbours.append(n)
            backup_note = ""
            if len(changed) >= LARGE_CHANGE:
                note = self.snapshot_fn() if self.snapshot_fn else "no backup is available"
                if note:
                    backup_note = "No world backup was made first (it failed); Undo still covers it."
            title = " ".join(str(title or "").split())[:60] or f"{len(changed)} blocks"
            who = str(by or "")[:40]
            text = f"{speaker} changed {title}" + (f" beside {beside}" if beside else "") + \
                (f" (asked by {who})" if who else "")
            act = self.actions.start("edit", beside, text, by=who, name=speaker, trusted=True,
                                     job=job, dimension=dim)
            # Runs of one before and one after along x; a bed's or door's
            # half is a cell of its own, because its undo checks its partner.
            pairs = {c: (before.get(c, "minecraft:air"), st, c if _MULTI_PART.search(st) else None)
                     for c, st in changed.items()}
            cells = [{"x": x1, "y": y, "z": z, "n": x2 - x1 + 1, "dim": dim, "before": b,
                      "after": st, "placed": True}
                     for x1, x2, y, z, (b, st, _) in _runs(pairs)]
            cells += [{"x": n[0], "y": n[1], "z": n[2], "n": 1, "dim": dim, "before": before[n],
                       "after": None, "placed": True} for n in neighbours]
            # Recorded before anything is set: a server that goes away half
            # way leaves an action Undo can still put back.
            act["cells"] = cells
            self.actions.put(act)
            failed = ""
            # Cells the server says already hold what was asked ("Could not
            # set the block", "No blocks were filled"): no failure, and out
            # of the undo, which would otherwise "put back" what they never
            # were. Only a read from a moment before the edit can say so.
            already: set[tuple[int, int, int]] = set()
            forced: dict[tuple[str, int, int], bool] = {}
            try:
                for x1, y1, z1, x2, y2, z2, st in boxes:
                    reply = self._raw_loaded(f"minecraft:execute in {dim} run minecraft:fill "
                                             f"{x1} {y1} {z1} {x2} {y2} {z2} {st} replace",
                                             dim, (x1, x2), (z1, z2), forced)
                    if reply is not None and re.search(r"no blocks were filled", reply, re.I):
                        already |= {c for c in changed
                                    if x1 <= c[0] <= x2 and y1 <= c[1] <= y2 and z1 <= c[2] <= z2}
                    elif reply is None or not re.search(r"filled", reply, re.I):
                        failed = f"The server would not fill a box: {why_refused(reply)}"
                        break
                singles = dict(changed)
                for box in boxes:
                    for c in list(singles):
                        if (box[0] <= c[0] <= box[3] and box[1] <= c[1] <= box[4]
                                and box[2] <= c[2] <= box[5] and singles[c] == box[6]):
                            singles.pop(c)
                if not failed:
                    for x1, x2, y, z, st in _runs(singles):
                        if x1 == x2:
                            cmd = (f"minecraft:execute in {dim} run minecraft:setblock "
                                   f"{x1} {y} {z} {st} replace")
                            done, same = r"changed the block", r"could not set the block"
                        else:
                            cmd = (f"minecraft:execute in {dim} run minecraft:fill "
                                   f"{x1} {y} {z} {x2} {y} {z} {st} replace")
                            done, same = r"filled", r"no blocks were filled"
                        reply = self._raw_loaded(cmd, dim, (x1, x2), (z, z), forced)
                        if reply is not None and re.search(same, reply, re.I):
                            already |= {(x, y, z) for x in range(x1, x2 + 1)}
                        elif reply is None or not re.search(done, reply, re.I):
                            failed = ("The server would not place a block: "
                                      f"{why_refused(reply)}")
                            break
                if not failed:
                    failed = self._nudge({c: (before.get(c, "minecraft:air"), st)
                                          for c, st in changed.items() if c not in already},
                                         dim, forced)
                if failed:
                    self._restore(act)
            finally:
                self._release(forced)
            if already:
                cells = _without(cells, already)
                act["cells"] = cells
                changed = {c: st for c, st in changed.items() if c not in already}
            now = self.clock()
            if failed:
                act.update(status="failed", ended_at=int(now), note=failed[:200])
                self.actions.put(act)
                raise CompanionError(failed)
            act.update(status="done", ended_at=int(now), note=backup_note)
            self.actions.put(act)
            self.col.record({"kind": "companion", "player": beside,
                             "action": act["id"], "text": text[:240]})
            xs = [k[0] for k in targets] or [0]
            ys = [k[1] for k in targets] or [0]
            zs = [k[2] for k in targets] or [0]
            # Where the work happened, for the companion's body to hover by.
            focus = {"x": (min(xs) + max(xs)) // 2, "y": max(ys), "z": (min(zs) + max(zs)) // 2,
                     "dimension": dim}
            return dict(act, cells=sum(c["n"] for c in cells), changed=len(changed),
                        undoable=undoable(act), backup_note=backup_note, dimension=dim,
                        focus=focus)

    def _nudge(self, cells: dict[tuple[int, int, int], tuple[str, str]], dim: str,
               forced: dict[tuple[str, int, int], bool]) -> str:
        """After an edit or its undo: every cell whose power changed (#778),
        `{cell: (before, after)}`, is set for a moment to an unlit redstone
        torch and then to what it now holds, so what the power drives —
        through the block a lever hangs on too — is updated as a flip in the
        game would. Every other cell is left alone. '' when done, else what
        went wrong (the cell holds the torch only if the server stopped
        answering between the two)."""
        for (x, y, z), (was, now) in sorted(cells.items()):
            if not power_changed(was, now):
                continue
            via = _NUDGE_TOO if now == _NUDGE else _NUDGE
            where = f"minecraft:execute in {dim} run minecraft:setblock {x} {y} {z}"
            reply = self._raw_loaded(f"{where} {via} replace", dim, (x, x), (z, z), forced)
            if reply is None or not re.search(r"changed the block", reply, re.I):
                continue          # nothing changed: the cell still holds what was asked
            for _ in range(2):
                back = self._raw_loaded(f"{where} {now} replace", dim, (x, x), (z, z), forced)
                if back is not None and re.search(r"changed the block", back, re.I):
                    break
            else:
                return (f"The server stopped answering while updating the redstone at "
                        f"{x} {y} {z}: {why_refused(back)}")
        return ""

    def _restore(self, act: dict[str, Any]) -> dict[str, int]:
        """Put back each cell that still holds what was placed."""
        if act.get("trusted"):
            return self._restore_edit(act)
        restored = changed = 0
        loaded: set[tuple[str, int, int]] = set()
        offline = not self.col.sessions
        for c in act.get("cells") or []:
            if not c.get("placed"):
                continue
            dim = c.get("dim") or "minecraft:overworld"
            chunk = (dim, c["x"] >> 4, c["z"] >> 4)
            if offline and chunk not in loaded:
                self._try(f"minecraft:execute in {dim} run minecraft:forceload add "
                          f"{c['x']} {c['z']}", placing=True)
                loaded.add(chunk)
            still = self._test(f"minecraft:execute in {dim} if block {c['x']} {c['y']} {c['z']} "
                               f"{c['after']}")
            if still:
                self._try(f"minecraft:execute in {dim} run minecraft:setblock "
                          f"{c['x']} {c['y']} {c['z']} {c['before']}", placing=True)
                restored += 1
            elif still is False:
                changed += 1
            else:
                continue          # the server did not answer: try again on the next undo
            c["placed"] = False
        for dim, cx, cz in loaded:
            self._try(f"minecraft:execute in {dim} run minecraft:forceload remove "
                      f"{cx * 16} {cz * 16}", placing=True)
        return {"restored": restored, "changed": changed}

    def _restore_edit(self, act: dict[str, Any]) -> dict[str, int]:
        """A trusted edit's undo: every cell that still holds what the edit
        set goes back to its saved state — a run at a time, with `fill …
        replace <what was set>`, which leaves a cell somebody changed since
        alone — then the neighbours it broke (the other half of a bed or
        door) are put back where they are missing."""
        forced: dict[tuple[str, int, int], bool] = {}
        try:
            cells = act.get("cells") or []
            out = self._restore_runs(cells, forced)
            self._nudge_restored(cells, forced)
            return out
        finally:
            self._release(forced)

    def _nudge_restored(self, cells: list[dict[str, Any]],
                        forced: dict[tuple[str, int, int], bool]) -> None:
        """An undo's power changes (#778): each cell of a run whose power
        the edit changed, and which now holds what it held before, has the
        redstone it drives updated as `_nudge` does for an edit."""
        by_dim: dict[str, dict[tuple[int, int, int], tuple[str, str]]] = {}
        for c in cells:
            after, before = c.get("after"), c.get("before")
            if c.get("placed") or after is None or not before or \
                    not power_changed(after, before):
                continue
            dim = c.get("dim") or "minecraft:overworld"
            for x in range(c["x"], c["x"] + int(c.get("n") or 1)):
                said = self._raw_loaded(f"minecraft:execute in {dim} if block {x} {c['y']} "
                                        f"{c['z']} {before}", dim, (x, x), (c["z"], c["z"]),
                                        forced)
                if said is not None and parse_test(said):
                    by_dim.setdefault(dim, {})[(x, c["y"], c["z"])] = (after, before)
        for dim, todo in by_dim.items():
            self._nudge(todo, dim, forced)

    def _restore_runs(self, cells: list[dict[str, Any]],
                      forced: dict[tuple[str, int, int], bool]) -> dict[str, int]:
        restored = changed = 0
        for c in sorted(cells, key=lambda c: c.get("after") is None):
            if not c.get("placed"):
                continue
            dim = c.get("dim") or "minecraft:overworld"
            n = int(c.get("n") or 1)
            where = f"{c['x']} {c['y']} {c['z']}"

            def raw(cmd: str, c: dict = c, n: int = n, dim: str = dim) -> str | None:
                # Nobody near the edit any more: its chunks are loaded for the undo.
                return self._raw_loaded(cmd, dim, (c["x"], c["x"] + n - 1), (c["z"], c["z"]),
                                        forced)

            if c.get("after") is None:
                same = raw(f"minecraft:execute in {dim} if block {where} {c['before']}")
                if same is not None and parse_test(same) is False:
                    raw(f"minecraft:execute in {dim} run minecraft:setblock {where} "
                        f"{c['before']} replace")
                c["placed"] = False
                continue
            if n == 1 and _MULTI_PART.search(c["after"]):
                still = raw(f"minecraft:execute in {dim} if block {where} {c['after']}")
                verdict = None if still is None else parse_test(still)
                if verdict is False:
                    # Half of a bed or door this edit set, which fell when its
                    # other half was put back a moment ago: gone, not changed.
                    gone = raw(f"minecraft:execute in {dim} if block {where} minecraft:air")
                    verdict = True if gone is not None and parse_test(gone) else verdict
                if verdict:
                    raw(f"minecraft:execute in {dim} run minecraft:setblock {where} "
                        f"{c['before']} replace")
                    restored += 1
                elif verdict is False:
                    changed += 1
                else:
                    continue      # the server did not answer: try again on the next undo
                c["placed"] = False
                continue
            reply = raw(f"minecraft:execute in {dim} run minecraft:fill {where} "
                        f"{c['x'] + n - 1} {c['y']} {c['z']} {c['before']} replace "
                        f"{c['after']}")
            if reply is None:
                continue          # the server did not answer: try again on the next undo
            m = re.search(r"filled (\d+)", reply, re.I)
            if m:
                done = min(n, int(m.group(1)))
            elif re.search(r"no blocks were filled", reply, re.I):
                done = 0
            else:
                continue          # a refusal we cannot read: leave it for another undo
            restored += done
            changed += n - done
            c["placed"] = False
        return {"restored": restored, "changed": changed}

    def undo_job(self, job: Any) -> dict[str, Any]:
        """Undo every edit recorded for a job, newest first."""
        job = str(job or "").strip()
        if not _JOB.match(job):
            raise CompanionError("That is not a job id.")
        with self._lock:
            undone, restored, changed = [], 0, 0
            for act in self.actions.list(MAX_ACTIONS):
                if act.get("job") == job and undoable(act):
                    out = self.undo(act["id"])
                    undone.append(act["id"])
                    restored += out.get("restored", 0)
                    changed += out.get("changed", 0)
            return {"job": job, "undone": undone, "restored": restored, "changed": changed}

    # -- choice pads -----------------------------------------------------------
    def ask(self, player: Any, text: Any, options: Any = None, by: str = "",
            person: Any = None, name: Any = None) -> dict[str, Any]:
        """Queue a question for a player; it is put to them when they are on.
        `person` is how the caller calls them (for the card), `name` the
        speaker the pads' companion goes by."""
        with self._lock:
            player = str(player or "").strip()
            if not _PLAYER.match(player):
                raise CompanionError(f"{player!r} is not a Minecraft name.")
            player = self._online(player) or player
            text = str(text or "").replace("\n", " ").strip()[:200]
            if not text:
                raise CompanionError("What is the question? (It is kept for the record; the "
                                     "player sees the pictures.)")
            now = self.clock()
            speaker, col = self._speaker(name, None)
            q = {"id": _new_id(now), "player": player,
                 "person": " ".join(str(person or player).split())[:40], "text": text,
                 "options": clean_options(options), "by": str(by or "")[:40],
                 "name": speaker, "colour": col,
                 "status": "queued", "created_at": int(now), "asked_at": None,
                 "answered_at": None, "answer": None, "attempts": 0, "next_try": 0,
                 "action": None, "note": ""}
            self.questions.put(q)
            return q

    def _run_questions(self, online: list[str], now: float) -> None:
        if self.asking:
            self._watch_pads(now)
            return
        for q in sorted(self.questions.list("queued"), key=lambda q: q.get("created_at") or 0):
            if q["player"] not in online or now < (q.get("next_try") or 0):
                continue
            self._pose(q, now)
            return

    def _site(self, player: str, n: int = 2) -> tuple[list[dict[str, Any]] | None, dict[str, Any], str]:
        here = self._pos(player)
        if not here:
            return None, {}, "Where they are is not known yet."
        pos, dim = here
        px, py, pz = (math.floor(c) for c in pos)
        gy = py - 1
        why = "There is no flat, clear, natural ground beside them."
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            perp = (dz, dx)

            def at(a, b, y):
                return {"x": px + a * dx + b * perp[0], "y": y, "z": pz + a * dz + b * perp[1]}
            layout: dict[str, Any] = {"dim": dim, "y": gy + 1, "pads": []}
            cells = []
            for i, (b1, b2, bp) in enumerate(PAD_LAYOUTS[n]):
                pad = [at(a, b, gy + 1) for a in (2, 3) for b in (b1, b2)]
                post = at(4, bp, gy + 1)
                pic = at(4, bp, gy + 2)
                layout["pads"].append({"cells": pad, "post": post, "picture": pic,
                                       "min_x": min(c["x"] for c in pad),
                                       "min_z": min(c["z"] for c in pad)})
                cells += [dict(c, ground=True, role=("pad", i)) for c in pad]
                cells += [dict(post, ground=True, role=("post", i)),
                          dict(pic, role=("picture", i))]
            refusal = self.footprint_refusal(cells, dim)
            if refusal:
                why = refusal
                continue
            if all(self._air(c["x"], c["y"], c["z"], dim) and
                   (not c.get("ground") or self._natural(c["x"], c["y"] - 1, c["z"], dim))
                   for c in cells):
                return cells, layout, ""
        return None, {}, why

    def _pose(self, q: dict[str, Any], now: float) -> None:
        player = q["player"]
        opts = q["options"]
        cells, layout, why = self._site(player, len(opts))
        q["attempts"] = int(q.get("attempts") or 0) + 1
        if cells is None:
            q["note"] = why
            q["next_try"] = int(now + QUESTION_RETRY)
            if q["attempts"] >= QUESTION_ATTEMPTS:
                q["status"] = "expired"
            self.questions.put(q)
            return
        name = speaker_name(q.get("name"), self.identity()["name"])
        act = self.actions.start(
            "pads", player, f"{name} asked {q.get('person') or player}: {q['text']} "
                            f"({' or '.join(o['label'] for o in opts)})",
            question=q["id"], by=q.get("by") or "", name=name)
        for c in cells:
            kind, i = c["role"]
            c["block"] = (opts[i]["pad"] if kind == "pad" else POST_BLOCK if kind == "post"
                          else opts[i]["picture"])
        why = self.place_blocks(act, [{k: c[k] for k in ("x", "y", "z", "block", "ground")
                                       if k in c} for c in cells], layout["dim"])
        if why:
            act.update(status="failed", ended_at=int(now), note=why[:200])
            self.actions.put(act)
            q.update(note=why, next_try=int(now + QUESTION_RETRY))
            if q["attempts"] >= QUESTION_ATTEMPTS:
                q["status"] = "expired"
            self.questions.put(q)
            return
        mid = layout["pads"]
        cx = (mid[0]["min_x"] + mid[-1]["min_x"]) / 2 + 1
        cz = (mid[0]["min_z"] + mid[-1]["min_z"]) / 2 + 1
        self._try(f"minecraft:execute in {layout['dim']} positioned {cx} {layout['y'] + 1.5} {cz} "
                  f"run minecraft:summon minecraft:allay ~ ~ ~ "
                  f"{self._body_nbt(act['tag'], name, colour(q.get('colour')))}")
        for i, opt in enumerate(opts):
            if opt.get("item"):
                pic = layout["pads"][i]["picture"]
                self._icon(layout["dim"], pic, opt["item"], f"{act['tag']}{ICON_TAG}{i}",
                           act["tag"])
        self._chime(player, pitches=(1.0, 1.5))
        q.update(status="open", asked_at=int(now), action=act["id"], note="")
        self.questions.put(q)
        self.asking = {"qid": q["id"], "player": player, "action": act["id"],
                       "layout": layout, "on": {}, "since": now, "beats": 0,
                       "answered": None, "remove_at": None}
        self.col.record({"kind": "companion", "player": player, "action": act["id"],
                         "text": f"{name} put {len(opts)} choice pads beside "
                                 f"{q.get('person') or player}"})

    def _icon(self, dim: str, pic: dict[str, int], item: str, tag: str, act_tag: str) -> None:
        """An option's item, floating still above its picture block: an item
        entity nobody can pick up and that never despawns (Bedrock players
        see item entities through Geyser)."""
        count = "Count:1b" if self.item_syntax() == "nbt" else "count:1"
        self._try(f"minecraft:execute in {dim} run minecraft:summon minecraft:item "
                  f"{pic['x'] + 0.5} {pic['y'] + 1.15} {pic['z'] + 0.5} "
                  f'{{Item:{{id:"{item}",{count}}},PickupDelay:32767,Age:-32768,NoGravity:1b,'
                  f'Invulnerable:1b,Motion:[0.0d,0.0d,0.0d],'
                  f'Tags:["{TAG}","{self.epoch}","{act_tag}","{tag}"]}}')

    def _watch_pads(self, now: float) -> None:
        a = self.asking
        lay = a["layout"]
        dim, y = lay["dim"], lay["y"]
        if a["player"] not in self.col.sessions:
            self._close_question(requeue=True, note=f"{a['player']} left before answering.")
            return
        if a["answered"] is not None:
            if now >= a["remove_at"]:
                self._close_question(requeue=False)
            return
        if now - a["since"] > QUESTION_TIMEOUT:
            self._close_question(requeue=False, note="Nobody stood on a pad.", status="expired")
            return
        a["beats"] += 1
        p = quote_name(a["player"])
        if a["beats"] % 4 == 1:
            for pad in lay["pads"]:
                self._try(f"minecraft:execute in {dim} run minecraft:particle minecraft:happy_villager "
                          f"{pad['min_x'] + 1} {y + 0.3} {pad['min_z'] + 1} 0.6 0.1 0.6 0 4")
        for i, pad in enumerate(lay["pads"]):
            on = self._test(f"minecraft:execute in {dim} if entity @a[name={p},x={pad['min_x']},"
                            f"y={y},z={pad['min_z']},dx=1,dy=0,dz=1]")
            if on:
                since = a["on"].setdefault(i, now)
                if now - since >= PAD_HOLD:
                    self._answer(i, now)
                    return
            else:
                a["on"].pop(i, None)

    def _answer(self, i: int, now: float) -> None:
        a = self.asking
        q = self.questions.get(a["qid"])
        if q is None:
            self._close_question(requeue=False)
            return
        chosen = q["options"][i]
        others = [o for j, o in enumerate(q["options"]) if j != i]
        lay = a["layout"]
        pad = lay["pads"][i]
        gone = [p for j, p in enumerate(lay["pads"]) if j != i]
        dim = lay["dim"]
        player = a["player"]
        self._chime(player, pitches=(1.0, 1.26, 1.5, 2.0), volume=0.7)
        self._try(f"minecraft:execute in {dim} run minecraft:particle minecraft:happy_villager "
                  f"{pad['min_x'] + 1} {lay['y'] + 1} {pad['min_z'] + 1} 1 1 1 0 40")
        # The result in the world: the other pictures (and their items) go,
        # the chosen one stays.
        act = self.actions.get(a["action"])
        if act:
            pics = {(p["picture"]["x"], p["picture"]["y"], p["picture"]["z"]) for p in gone}
            for c in act["cells"]:
                if (c["x"], c["y"], c["z"]) in pics and c.get("placed"):
                    self._restore({"cells": [c]})
            self.actions.put(act)
            for j in range(len(lay["pads"])):
                if j != i and q["options"][j].get("item"):
                    self._try(f"minecraft:kill @e[tag={act['tag']}{ICON_TAG}{j}]")
        if chosen.get("gift"):
            self._try(f"minecraft:give {quote_name(player)} {chosen['gift']} "
                      f"{chosen.get('gift_count', 1)}")
        if a.get("action"):
            self._sparkle_at_tag(f"{TAG}_" + a["action"].split("-")[1], 20)
        q.update(status="answered", answer=chosen["label"], answered_at=int(now))
        self.questions.put(q)
        a.update(answered=i, remove_at=now + RESULT_LINGER)
        self.col.record({"kind": "companion", "player": player, "action": a["action"],
                         "text": f"{q.get('person') or player} chose {chosen['label']}"})
        try:
            self.emit_fn("bruh_minecraft_answer", {
                "player": player, "question_id": q["id"], "question": q["text"],
                "answer": chosen["label"], "index": i, "other": others[0].get("label"),
                "others": [o.get("label") for o in others],
                "options": [o.get("label") for o in q["options"]], "by": q.get("by") or "",
                "time": int(now), "world": self.col.level_name()})
        except Exception:  # noqa: BLE001 — Home Assistant away is not the game's problem
            pass

    def _close_question(self, requeue: bool, note: str = "", status: str | None = None) -> None:
        a, self.asking = self.asking, None
        if not a:
            return
        act = self.actions.get(a["action"])
        if act:
            self._restore(act)
            self._remove_tag(act["tag"])
            if act.get("status") == "active":
                act.update(status="done", ended_at=int(self.clock()))
            self.actions.put(act)
        q = self.questions.get(a["qid"])
        if q and q.get("status") == "open":
            if status:
                q["status"] = status
            elif requeue and q.get("attempts", 0) < QUESTION_ATTEMPTS:
                q["status"] = "queued"
            else:
                q["status"] = "expired"
            q["note"] = note
            q["next_try"] = int(self.clock() + QUESTION_RETRY)
            self.questions.put(q)

    # -- undo -------------------------------------------------------------------
    def undo(self, action_id: str) -> dict[str, Any]:
        if not _ACTION_ID.match(str(action_id or "")):
            raise CompanionError("That is not an action id.")
        with self._lock:
            act = self.actions.get(action_id)
            if act is None:
                raise KeyError(action_id)
            if not undoable(act):
                return {"action": act, "restored": 0, "changed": 0,
                        "note": "Nothing of it is left in the world."}
            if self.asking and self.asking.get("action") == action_id:
                q = self.questions.get(self.asking["qid"])
                self.asking = None
                if q and q.get("status") == "open":
                    q.update(status="cancelled", note="Undone.")
                    self.questions.put(q)
            self.live.pop(action_id, None)
            result = self._restore(act)
            self._remove_tag(act["tag"], poof=False)
            act.update(status="undone", ended_at=int(self.clock()),
                       undo_note=(f"{result['changed']} block(s) had changed since and were left."
                                  if result["changed"] else ""))
            self.actions.put(act)
            self.col.record({"kind": "companion", "player": None, "action": action_id,
                             "text": f"Undone: {act.get('text', '')}"[:240]})
            return {"action": act, **result}

    def undo_last(self) -> dict[str, Any] | None:
        """Undo the newest action that still has something in the world."""
        with self._lock:
            for act in self.actions.list(MAX_ACTIONS):
                if undoable(act):
                    return self.undo(act["id"])
            return None

    # -- the old engine's state -------------------------------------------------
    def legacy_state(self) -> dict[str, Any] | None:
        return legacy.read_state(self.data_dir)

    def retire_legacy(self) -> bool:
        with self._lock:
            return legacy.retire(self.data_dir, self.root)

    # -- reading ---------------------------------------------------------------
    def brief(self) -> dict[str, Any]:
        """The small view for world.json and Home Assistant."""
        last = self.actions.list(1)
        open_q = self.asking and self.questions.get(self.asking["qid"])
        ident = self.identity()
        return {"active": ident["active"], "name": ident["name"], "colour": ident["colour"],
                "state": self.state,
                "queued_questions": len(self.questions.list("queued")),
                "open_question": ({k: open_q.get(k) for k in ("id", "person", "text")}
                                  if open_q else None),
                "last_action": ({k: last[0].get(k) for k in ("id", "t", "kind", "player",
                                                             "text", "status")}
                                if last else None)}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {**self.brief(), "identity": self.identity(), "note": self.last_note,
                    "online": sorted(self.col.sessions),
                    "zones": self.zones.list(),
                    "questions": self.questions.list()[:20],
                    "actions": [dict(a, undoable=undoable(a)) for a in self.actions.list(30)],
                    "said": self.said.list(20),
                    "accounts": {k: v for k, v in self.accounts().items()
                                 if k in ("java", "bedrock", "online_mode", "floodgate",
                                          "geyser_auth", "why_java", "why_bedrock")}}


__all__ = ["Companion", "Zones", "ActionLog", "SaidLog", "Questions", "GuardError",
           "CompanionError", "check_command", "clean_options", "block_id", "modern_text",
           "item_syntax", "item_id", "named_item", "unread_why", "shapes",
           "bare", "undoable", "split_reply", "account_check", "trusted", "speaker_name",
           "colour", "TAG"]
