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
* **Choice pads** — `ask`: a question with two pictures. Two 2×2 carpets
  beside the child on flat, natural ground, each with a fence post and a
  picture block; standing on one for `PAD_HOLD` seconds is the answer,
  confirmed with a chime and sparkles, announced as the Home Assistant
  event `bruh_minecraft_answer`, and the pads are taken away again.
* **Blocks** — `build` and `place_blocks`, the one path that changes
  blocks: it refuses a footprint inside a protected place or on or next to
  a build in the build log, checks every cell is air over natural ground,
  places with `setblock … keep`, records what each cell was, and snapshots
  first when the change is large. An undo puts back only cells that still
  hold what was placed, so it never undoes a child's later change.
* **The account check** — `account_check`: whether the server checks the
  accounts behind the names in chat, which the chat events carry so a
  companion knows whether a name may be believed.

Hard limits live in `check_command`, the chokepoint every command passes:
only an allay is ever summoned, only gentle sounds at a capped volume are
played, only the companion's own entities are killed or moved, words go to
one named player, and blocks change only through `place_blocks`/undo.
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


def _load_legacy():
    """companion_legacy, beside this file (the panel loads modules by path)."""
    name = "bruh_mc_companion_legacy"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent / "companion_legacy.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


legacy = _load_legacy()

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
ACCOUNT_STALE = 60            # seconds the account check is trusted
NAME_MAX = 16

TAG = "bruh_companion"
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
_ACTION_ID = re.compile(r"^[0-9]{8}-[0-9a-f]{6}$")
_UNQUOTED = re.compile(r"^[0-9A-Za-z_\-.+]+$")
_PLAYER = re.compile(r"^[A-Za-z0-9_.*]{1,17}$")
_COLOUR_CODE = re.compile(r"§.")

PAD_COLOURS = (("minecraft:lime_carpet", "minecraft:lime_wool", "yes"),
               ("minecraft:red_carpet", "minecraft:red_wool", "no"))
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


def bare(name: str) -> str:
    """A name as people mean it: no Bedrock prefix, no case."""
    return re.sub(r"^[.*]", "", str(name or "").strip()).lower()


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
        if len(words) < 2 or words[1] not in SAFE_SUMMONS:
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
    if verb in ("title", "tellraw"):
        if len(words) < 2 or words[1].startswith("@"):
            raise GuardError("words go to one named player")
        return
    if verb == "give":
        if len(words) < 3 or words[1].startswith("@"):
            raise GuardError("a gift is for one named player")
        try:
            block_id(words[2])
        except CompanionError as exc:
            raise GuardError(str(exc)) from None
        try:
            count = int(words[3]) if len(words) > 3 else 1
        except ValueError:
            raise GuardError("an unreadable count") from None
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
        return next((a for a in self.list(MAX_ACTIONS) if a.get("id") == action_id), None)

    def start(self, kind: str, player: str | None, text: str, **extra) -> dict[str, Any]:
        now = self.clock()
        act = {"id": _new_id(now), "t": int(now), "kind": kind, "player": player,
               "text": text, "status": "active", "cells": [], "tag": "", "ended_at": None,
               **extra}
        act["tag"] = f"{TAG}_" + act["id"].split("-")[1]
        self.put(act)
        return act

    def put(self, act: dict[str, Any]) -> None:
        with self._lock:
            acts = [a for a in self.list(MAX_ACTIONS) if a.get("id") != act["id"]]
            acts.append(act)
            acts.sort(key=lambda a: a.get("t") or 0, reverse=True)
            _atomic_write_json(self.path, {"actions": acts[:MAX_ACTIONS]})


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


def undoable(act: dict[str, Any]) -> bool:
    if act.get("status") in ("undone", "failed"):
        return False
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
    """Two choices, each a label, a picture block and maybe a gift."""
    if options in (None, "", []):
        options = [{"label": "yes"}, {"label": "no"}]
    if not isinstance(options, list) or len(options) != 2:
        raise CompanionError("A pad question has exactly two options.")
    out = []
    for i, o in enumerate(options):
        if isinstance(o, str):
            o = {"label": o}
        if not isinstance(o, dict):
            raise CompanionError("Each option is a label, or {label, picture, gift}.")
        label = str(o.get("label") or "").strip()[:40]
        if not label:
            raise CompanionError("Each option needs a label.")
        carpet, picture, _ = PAD_COLOURS[i]
        opt = {"label": label, "picture": block_id(o.get("picture"), picture), "pad": carpet}
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
                 accounts: Callable[[], dict] | None = None,
                 clock: Callable[[], float] = time.time):
        self.col = collector
        self.clock = clock
        self.emit_fn = emit or (lambda kind, data: None)
        self.snapshot_fn = snapshot
        self.modern = modern
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
            players = list(dict.fromkeys(players))
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
            else:
                dim = str(dimension or "minecraft:overworld")
                if not re.fullmatch(r"[a-z0-9_.\-]+:[a-z0-9_./\-]+", dim):
                    raise CompanionError("dimension is an id like minecraft:overworld.")
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

    def _restore(self, act: dict[str, Any]) -> dict[str, int]:
        """Put back each cell that still holds what was placed."""
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

    def _site(self, player: str) -> tuple[list[dict[str, Any]] | None, dict[str, Any], str]:
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
            for i, side in enumerate((-1, 1)):
                pad = [at(a, side * b, gy + 1) for a in (2, 3) for b in (2, 3)]
                post = at(4, side * 3, gy + 1)
                pic = at(4, side * 3, gy + 2)
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
        cells, layout, why = self._site(player)
        q["attempts"] = int(q.get("attempts") or 0) + 1
        if cells is None:
            q["note"] = why
            q["next_try"] = int(now + QUESTION_RETRY)
            if q["attempts"] >= QUESTION_ATTEMPTS:
                q["status"] = "expired"
            self.questions.put(q)
            return
        opts = q["options"]
        name = speaker_name(q.get("name"), self.identity()["name"])
        act = self.actions.start(
            "pads", player, f"{name} asked {q.get('person') or player}: {q['text']} "
                            f"({opts[0]['label']} or {opts[1]['label']})",
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
        cx = (mid[0]["min_x"] + mid[1]["min_x"]) / 2 + 1
        cz = (mid[0]["min_z"] + mid[1]["min_z"]) / 2 + 1
        self._try(f"minecraft:execute in {layout['dim']} positioned {cx} {layout['y'] + 1.5} {cz} "
                  f"run minecraft:summon minecraft:allay ~ ~ ~ "
                  f"{self._body_nbt(act['tag'], name, colour(q.get('colour')))}")
        self._chime(player, pitches=(1.0, 1.5))
        q.update(status="open", asked_at=int(now), action=act["id"], note="")
        self.questions.put(q)
        self.asking = {"qid": q["id"], "player": player, "action": act["id"],
                       "layout": layout, "on": {}, "since": now, "beats": 0,
                       "answered": None, "remove_at": None}
        self.col.record({"kind": "companion", "player": player, "action": act["id"],
                         "text": f"{name} put two choice pads beside {q.get('person') or player}"})

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
        chosen, other = q["options"][i], q["options"][1 - i]
        lay = a["layout"]
        pad, gone = lay["pads"][i], lay["pads"][1 - i]
        dim = lay["dim"]
        player = a["player"]
        self._chime(player, pitches=(1.0, 1.26, 1.5, 2.0), volume=0.7)
        self._try(f"minecraft:execute in {dim} run minecraft:particle minecraft:happy_villager "
                  f"{pad['min_x'] + 1} {lay['y'] + 1} {pad['min_z'] + 1} 1 1 1 0 40")
        # The result in the world: the other picture goes, the chosen one stays.
        act = self.actions.get(a["action"])
        if act:
            pic = gone["picture"]
            for c in act["cells"]:
                if (c["x"], c["y"], c["z"]) == (pic["x"], pic["y"], pic["z"]) and c.get("placed"):
                    self._restore({"cells": [c]})
            self.actions.put(act)
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
                "answer": chosen["label"], "other": other.get("label"),
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
           "bare", "undoable", "split_reply", "account_check", "trusted", "speaker_name",
           "colour", "TAG"]
