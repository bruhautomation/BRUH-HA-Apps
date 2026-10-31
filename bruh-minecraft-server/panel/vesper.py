#!/usr/bin/env python3
"""Vesper in the game: the sentience engine (#572), first milestones.

The owner: *"I really want you to play Minecraft with us … Really think
about how you can get feedback from us without a console command or typing
words (my kids are 4 and 5)."* This module is the part of that which runs
beside the world's senses (mcworld.WorldCollector) in the panel process,
with no server plugin: everything Vesper does is an RCON command, and
everything it notices is the collector's log tail and position polls.

Layers, cheapest first:

* **Who is who** — `Roster` (`.bruh-world/vesper/family.json`): in-game
  names, Bedrock's dotted ones included, mapped to people, and each
  person's role. A *child* gets Vesper in the world; a *reader* (a
  parent) gets words; anybody not on the roster is a *guest* Vesper leaves
  alone.
* **Attention** — collector events and positions become scored *moments*
  (join, idle, death, achievement, a favourite place, a parent saying
  "Vesper" in chat, an answer). Each kind has a cooldown per player, each
  player a cap per session, the day a budget, and the default is quiet: a
  moment worth more than `EVENT_THRESHOLD` is announced to Home Assistant
  as a `bruh_minecraft_moment` event (brAIn's hook to decide on it), and
  only the rules below act on their own.
* **Body** — on a child's join Vesper appears: a named, invulnerable,
  silent allay (Bedrock players see allays through Geyser; display
  entities never reach them), a three-note chime, sparkles, a hop that
  is its wave, and then it goes. Every entity carries the tag `vesper`, the
  action's own tag and this process's epoch tag, so a sweep removes any
  left by an earlier run and an undo removes exactly one action's.
* **Choice pads** — a question with two pictures. Two 2×2 carpets
  (green and red by default) beside the child on flat, natural ground,
  each with a fence post and a picture block behind it; standing on one
  for `PAD_HOLD` seconds is the answer. It is confirmed with a chime and
  sparkles, written to the person's memory, shown (the other picture goes,
  an optional gift is given), and the pads are taken away again.
* **Hands** — `place_blocks`, the one path that changes blocks: it refuses
  a footprint inside a protected zone or any build in the build log,
  checks every cell is air over natural ground first, places with
  `setblock … keep`, records what each cell was, and snapshots first when
  the change is large. An undo puts back only cells that still hold what
  Vesper put there, so it never undoes a child's later change.

Hard rules live in `check_command`, the chokepoint every command passes:
only an allay is ever summoned, only gentle sounds at a capped volume are
played, only Vesper's own entities are killed or moved, words go to one
named player, and blocks change only through `place_blocks`/undo. Words to
a player never name another child (`tell`). At bedtime (a Home Assistant
entity the owner names) Vesper says goodnight and stops. Nothing at all is
sent while nobody is online.
"""
from __future__ import annotations

import json
import math
import os
import re
import secrets
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# Tuning
# ---------------------------------------------------------------------------
GREET_COOLDOWN = 20 * 60      # seconds before the same child is greeted again
MOMENT_COOLDOWN = 10 * 60     # per (kind, player)
SESSION_CAP = 4               # proactive acts per player per session
DAILY_ACTIONS = 120           # world-changing acts a day (option overrides)
DAILY_EVENTS = 40             # moments sent to Home Assistant (each may wake brAIn)
EVENT_THRESHOLD = 0.5         # a moment scoring this or more is announced
IDLE_AFTER = 60               # seconds standing still before "idle"
IDLE_RADIUS = 1.5             # blocks of movement that still count as still
FAVOURITE_VISITS = 3          # visits before a place is a favourite
QUESTION_TIMEOUT = 180        # seconds a pad question waits for an answer
QUESTION_RETRY = 30           # seconds before trying a site again
QUESTION_ATTEMPTS = 4
PAD_HOLD = 2.0                # seconds on a pad that make an answer
GREETING_LIFETIME = 25        # seconds Vesper stays after a greeting
RESULT_LINGER = 6             # seconds the answer is shown before the pads go
LARGE_CHANGE = 64             # blocks: a change this big is snapshotted first
FAST_INTERVAL = 0.5           # seconds between beats while something is live
MAX_ACTIONS = 300
MAX_QUESTIONS = 100
MAX_ANSWERS = 50
MOMENTS_KEPT = 40
BEDTIME_STALE = 30

ROLES = ("child", "reader", "guest")
DIR_NAME = "vesper"

SAFE_SUMMONS = frozenset({"minecraft:allay"})
GENTLE_SOUNDS = frozenset({
    "minecraft:block.note_block.chime", "minecraft:block.note_block.bell",
    "minecraft:block.note_block.pling", "minecraft:block.amethyst_block.chime",
    "minecraft:entity.allay.item_given", "minecraft:entity.experience_orb.pickup",
})
MAX_VOLUME = 0.8
GIFT_MAX = 16
# Ground Vesper may build on: terrain, never something somebody placed.
NATURAL_GROUND = ("#minecraft:dirt", "#minecraft:sand", "#minecraft:base_stone_overworld",
                  "minecraft:gravel", "minecraft:snow_block")
# Blocks and items Vesper never uses, whoever asks.
_FORBIDDEN = re.compile(
    r"tnt|lava|fire|magma|command|structure|jigsaw|spawner|portal|skull|head|cactus|"
    r"sculk|powder_snow|wither|dragon|barrier|bedrock|end_crystal|respawn_anchor|"
    r"spawn_egg|flint_and_steel|fire_charge|potion|arrow|trident|sword|axe|bow")
_BLOCK_ID = re.compile(r"^(minecraft:)?[a-z0-9_]{1,48}$")
_ACTION_ID = re.compile(r"^[0-9]{8}-[0-9a-f]{6}$")
_UNQUOTED = re.compile(r"^[0-9A-Za-z_\-.+]+$")
_COLOUR = re.compile(r"§.")

PAD_COLOURS = (("minecraft:lime_carpet", "minecraft:lime_wool", "yes"),
               ("minecraft:red_carpet", "minecraft:red_wool", "no"))
POST_BLOCK = "minecraft:oak_fence"


class GuardError(ValueError):
    """A command Vesper is never allowed to send."""


class VesperError(ValueError):
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
    text = _COLOUR.sub("", str(reply or "")).strip().lower()
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
            raise VesperError("Name a block or item, like minecraft:hay_block.")
        return default
    if not _BLOCK_ID.match(text) or _FORBIDDEN.search(text):
        raise VesperError(f"Vesper does not use {text!r}.")
    return text if ":" in text else f"minecraft:{text}"


def text_component(text: str, color: str = "light_purple") -> str:
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


def _day(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


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


def check_command(cmd: str, placing: bool = False) -> None:
    """Raise GuardError unless `cmd` is something Vesper may ever send."""
    if "\n" in cmd or "\r" in cmd:
        raise GuardError("one line only")
    verb, words = _final(cmd)
    if cmd.startswith(("execute", "minecraft:execute")) and " run " not in cmd:
        if " if " not in f" {cmd} " and " unless " not in f" {cmd} ":
            raise GuardError("an execute that runs nothing is a test")
        return
    if verb == "summon":
        if len(words) < 2 or words[1] not in SAFE_SUMMONS:
            raise GuardError(f"Vesper never summons {words[1] if len(words) > 1 else 'nothing'}")
        if '"vesper"' not in cmd:
            raise GuardError("every entity Vesper summons carries the vesper tag")
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
        if len(words) < 2 or "tag=vesper" not in words[1]:
            raise GuardError("Vesper only removes its own entities")
        return
    if verb in ("tp", "teleport"):
        if len(words) < 2 or words[1] != "@s" or "as @e[tag=vesper" not in cmd:
            raise GuardError("Vesper only moves its own entities")
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
        except VesperError as exc:
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
            except VesperError as exc:
                raise GuardError(str(exc)) from None
        return
    raise GuardError(f"Vesper does not use '{verb}'")


# ---------------------------------------------------------------------------
# Who is who
# ---------------------------------------------------------------------------
class Roster:
    """The family: people, their roles, and the names they play under."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def people(self) -> list[dict[str, Any]]:
        data = _read_json(self.path, {})
        people = data.get("people") if isinstance(data, dict) else data
        return [p for p in (people or []) if isinstance(p, dict) and p.get("person")]

    @staticmethod
    def clean(people: Any) -> list[dict[str, Any]]:
        if not isinstance(people, list):
            raise VesperError("people is a list of {person, role, players}.")
        out, seen = [], set()
        for p in people[:20]:
            if not isinstance(p, dict):
                raise VesperError("Each person is an object.")
            person = str(p.get("person") or "").strip()[:40]
            if not person:
                raise VesperError("Each person needs a name.")
            role = str(p.get("role") or "child").strip().lower()
            if role not in ("child", "reader"):
                raise VesperError("role is child (Vesper plays with them) or reader (a parent).")
            players = p.get("players") or []
            if isinstance(players, str):
                players = [players]
            names = []
            for n in players[:6]:
                n = str(n).strip()
                if not re.fullmatch(r"[A-Za-z0-9_.*]{1,17}", n):
                    raise VesperError(f"{n!r} is not a Minecraft name.")
                if bare(n) in seen:
                    raise VesperError(f"{n} is listed twice.")
                seen.add(bare(n))
                names.append(n)
            if not names:
                raise VesperError(f"{person} needs at least one in-game name.")
            out.append({"person": person, "role": role, "players": names})
        return out

    def save(self, people: Any) -> list[dict[str, Any]]:
        cleaned = self.clean(people)
        _atomic_write_json(self.path, {"people": cleaned})
        return cleaned

    def who(self, player: str) -> dict[str, Any]:
        want = bare(player)
        for p in self.people():
            for n in p.get("players") or []:
                if n == player or bare(n) == want:
                    return {"person": p["person"], "role": p.get("role") or "child",
                            "player": player}
        return {"person": player, "role": "guest", "player": player}

    def children(self) -> list[dict[str, Any]]:
        return [p for p in self.people() if p.get("role", "child") == "child"]


# ---------------------------------------------------------------------------
# Zones
# ---------------------------------------------------------------------------
class Zones:
    """Named places (`places.json`, which the collector also reads for
    "near X"), with a `protect` flag: Vesper never builds inside one."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def list(self) -> list[dict[str, Any]]:
        data = _read_json(self.path, [])
        if isinstance(data, dict):
            data = data.get("places") or []
        return [p for p in data if isinstance(p, dict) and p.get("name")]

    def save(self, zone: Any) -> dict[str, Any]:
        if not isinstance(zone, dict):
            raise VesperError("A zone is an object.")
        name = str(zone.get("name") or "").strip()[:60]
        if not name:
            raise VesperError("A zone needs a name.")
        try:
            x, z = float(zone["x"]), float(zone["z"])
            radius = max(1, min(512, int(float(zone.get("radius") or 16))))
        except (KeyError, TypeError, ValueError):
            raise VesperError("A zone needs x and z (and a radius up to 512).") from None
        dim = str(zone.get("dimension") or "minecraft:overworld")
        if not re.fullmatch(r"[a-z0-9_.\-]+:[a-z0-9_./\-]+", dim):
            raise VesperError("dimension is an id like minecraft:overworld.")
        kind = str(zone.get("kind") or "family")
        clean = {"name": name, "x": x, "z": z, "radius": radius, "dimension": dim,
                 "protect": bool(zone.get("protect", kind != "vesper")),
                 "kind": kind if kind in ("family", "vesper") else "family"}
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
# Memory, per person
# ---------------------------------------------------------------------------
class Memory:
    """What Vesper knows about each person, across sessions
    (`.bruh-world/vesper/people.json`): sessions and time, the places they
    keep going back to, what they chose and liked, which moments happened.
    Read by the parent through the panel, Home Assistant and brAIn; never
    said to another player in the game."""

    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def all(self) -> dict[str, Any]:
        data = _read_json(self.path, {})
        return data if isinstance(data, dict) else {}

    def get(self, person: str) -> dict[str, Any] | None:
        return self.all().get(person)

    def _edit(self, who: dict[str, Any], fn: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._lock:
            data = self.all()
            rec = data.get(who["person"]) or {
                "person": who["person"], "role": who.get("role"), "players": [],
                "sessions": 0, "seconds": 0, "first_seen": int(self.clock()),
                "places": {}, "likes": {}, "dislikes": {}, "answers": [], "moments": {}}
            rec["role"] = who.get("role") or rec.get("role")
            if who.get("player") and who["player"] not in rec["players"]:
                rec["players"] = (rec.get("players") or []) + [who["player"]]
            fn(rec)
            rec["last_seen"] = int(self.clock())
            data[who["person"]] = rec
            try:
                _atomic_write_json(self.path, data)
            except OSError:
                # Memory is a record of play, not the play itself; a full disk loses a line.
                pass
            return rec

    def joined(self, who):
        return self._edit(who, lambda r: r.__setitem__("sessions", r.get("sessions", 0) + 1))

    def left(self, who, seconds: int | None):
        return self._edit(who, lambda r: r.__setitem__("seconds",
                                                        r.get("seconds", 0) + int(seconds or 0)))

    def visited(self, who, place: str):
        def fn(r):
            places = r.setdefault("places", {})
            places[place] = places.get(place, 0) + 1
        return self._edit(who, fn)

    def moment(self, who, kind: str):
        def fn(r):
            m = r.setdefault("moments", {})
            m[kind] = m.get(kind, 0) + 1
        return self._edit(who, fn)

    def answered(self, who, question: dict[str, Any], chosen: dict[str, Any], other: dict[str, Any]):
        def fn(r):
            likes, dislikes = r.setdefault("likes", {}), r.setdefault("dislikes", {})
            label = chosen.get("label") or "?"
            likes[label] = likes.get(label, 0) + 1
            if other.get("label") and other.get("label") not in ("no", "yes"):
                dislikes[other["label"]] = dislikes.get(other["label"], 0) + 1
            answers = r.setdefault("answers", [])
            answers.append({"t": int(self.clock()), "question": question.get("text"),
                            "options": [o.get("label") for o in question.get("options") or []],
                            "answer": label, "id": question.get("id")})
            del answers[:-MAX_ANSWERS]
        return self._edit(who, fn)

    @staticmethod
    def favourites(rec: dict[str, Any] | None, top: int = 3) -> list[str]:
        places = (rec or {}).get("places") or {}
        ranked = sorted(places.items(), key=lambda kv: kv[1], reverse=True)
        return [name for name, n in ranked[:top] if n >= FAVOURITE_VISITS]


# ---------------------------------------------------------------------------
# The action log
# ---------------------------------------------------------------------------
class ActionLog:
    """Everything Vesper did in the world, newest first, with what it
    changed (`cells`: each block's before and after; `tag`: its entities),
    so an undo can put it back (`.bruh-world/vesper/actions.json`)."""

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

    def start(self, kind: str, who: dict[str, Any], text: str, **extra) -> dict[str, Any]:
        now = self.clock()
        act = {"id": time.strftime("%Y%m%d", time.localtime(now)) + "-" + secrets.token_hex(3),
               "t": int(now), "kind": kind, "player": who.get("player"),
               "person": who.get("person"), "text": text, "status": "active",
               "cells": [], "tag": "", "ended_at": None, **extra}
        act["tag"] = "vesper_" + act["id"].split("-")[1]
        self.put(act)
        return act

    def put(self, act: dict[str, Any]) -> None:
        with self._lock:
            acts = [a for a in self.list(MAX_ACTIONS) if a.get("id") != act["id"]]
            acts.append(act)
            acts.sort(key=lambda a: a.get("t") or 0, reverse=True)
            _atomic_write_json(self.path, {"actions": acts[:MAX_ACTIONS]})


def undoable(act: dict[str, Any]) -> bool:
    if act.get("status") in ("undone", "failed"):
        return False
    return act.get("status") == "active" or any(c.get("placed") for c in act.get("cells") or [])


# ---------------------------------------------------------------------------
# The budget
# ---------------------------------------------------------------------------
class Budget:
    """Per-day counts of world-changing acts and of moments sent out."""

    def __init__(self, path: Path, limits: Callable[[], dict[str, int]],
                 clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.limits = limits
        self.clock = clock

    def today(self) -> dict[str, Any]:
        data = _read_json(self.path, {})
        day = _day(self.clock())
        if not isinstance(data, dict) or data.get("day") != day:
            data = {"day": day, "actions": 0, "events": 0}
        return data

    def left(self, kind: str) -> int:
        return max(0, int(self.limits().get(kind, 0)) - int(self.today().get(kind, 0)))

    def spend(self, kind: str) -> bool:
        if self.left(kind) <= 0:
            return False
        data = self.today()
        data[kind] = int(data.get(kind, 0)) + 1
        try:
            _atomic_write_json(self.path, data)
        except OSError:
            # Counted in memory for this beat only; a full disk is not a reason to act more.
            return True
        return True

    def view(self) -> dict[str, Any]:
        data, lim = self.today(), self.limits()
        return {"day": data["day"], "actions": data["actions"], "actions_limit": lim["actions"],
                "events": data["events"], "events_limit": lim["events"]}


# ---------------------------------------------------------------------------
# Questions
# ---------------------------------------------------------------------------
class Questions:
    """Questions waiting for, being shown to, and answered by a child."""

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
        raise VesperError("A pad question has exactly two options.")
    out = []
    for i, o in enumerate(options):
        if isinstance(o, str):
            o = {"label": o}
        if not isinstance(o, dict):
            raise VesperError("Each option is a label, or {label, picture, gift}.")
        label = str(o.get("label") or "").strip()[:40]
        if not label:
            raise VesperError("Each option needs a label.")
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
# The engine
# ---------------------------------------------------------------------------
class Engine:
    """Attention, rules, body and pads, beat by beat beside the collector.

    `step()` runs after every collector beat on the world thread; the API
    (`ask`, `undo`, `set_paused`) is called from request threads, so state
    is under one lock and the RCON session has its own.
    """

    def __init__(self, collector, *, enabled: Callable[[], bool],
                 bedtime: Callable[[], bool | None] = lambda: False,
                 emit: Callable[[str, dict], Any] | None = None,
                 snapshot: Callable[[], str | None] | None = None,
                 modern: Callable[[], bool] = lambda: True,
                 limits: Callable[[], dict[str, int]] | None = None,
                 state_path: Path | None = None,
                 clock: Callable[[], float] = time.time):
        self.col = collector
        self.clock = clock
        self.enabled_opt = enabled
        self.bedtime_fn = bedtime
        self.emit_fn = emit or (lambda kind, data: None)
        self.snapshot_fn = snapshot
        self.modern = modern
        root = Path(collector.data_dir) / DIR_NAME
        self.root = root
        self.roster = Roster(root / "family.json")
        self.zones = Zones(Path(collector.data_dir) / "places.json")
        self.memory = Memory(root / "people.json", clock)
        self.actions = ActionLog(root / "actions.json", clock)
        self.questions = Questions(root / "questions.json", clock)
        self.budget = Budget(root / "budget.json", limits or (
            lambda: {"actions": DAILY_ACTIONS, "events": DAILY_EVENTS}), clock)
        self.state_path = Path(state_path) if state_path else root / "engine.json"
        self.epoch = "vesper_e" + secrets.token_hex(3)
        self._lock = threading.RLock()
        self._events: deque[dict[str, Any]] = deque(maxlen=200)
        self.moments: deque[dict[str, Any]] = deque(maxlen=MOMENTS_KEPT)
        self.cooldowns: dict[tuple[str, str], float] = {}
        self.session_acts: dict[str, int] = {}
        self.pending_greet: dict[str, float] = {}
        self.still: dict[str, tuple[list[float], float, bool]] = {}
        self.near: dict[str, str | None] = {}
        self.live: dict[str, dict[str, Any]] = {}     # action id -> its live state
        self.asking: dict[str, Any] | None = None     # the open pad question
        self.was_online = False
        self.swept = False
        self.bedtime_said = False
        self.state = "off"
        self.last_note = ""
        collector.on_event = self.observe

    # -- settings ------------------------------------------------------------
    def paused(self) -> bool:
        return bool(_read_json(self.state_path, {}).get("paused"))

    def set_paused(self, paused: bool) -> dict[str, Any]:
        _atomic_write_json(self.state_path, {"paused": bool(paused), "at": int(self.clock())})
        return self.status()

    def enabled(self) -> bool:
        return bool(self.enabled_opt()) and not self.paused()

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

    def tell(self, player: str, text: str) -> bool:
        """Words to one player, never naming another child."""
        me = self.roster.who(player)
        lower = text.lower()
        for p in self.roster.children():
            if p["person"] == me["person"]:
                continue
            names = [p["person"]] + [bare(n) for n in p.get("players") or []]
            if any(n and re.search(rf"(?<![a-z0-9]){re.escape(n.lower())}(?![a-z0-9])", lower)
                   for n in names):
                self.last_note = "Vesper kept one child's news from another."
                return False
        self._try(f"minecraft:tellraw {quote_name(player)} "
                  + text_component("[Vesper] " + text))
        return True

    def _name_nbt(self) -> str:
        comp = text_component("Vesper")
        return f"CustomName:{comp}" if self.modern() else f"CustomName:'{comp}'"

    def _body_nbt(self, tag: str) -> str:
        return ("{NoAI:1b,NoGravity:1b,Invulnerable:1b,Silent:1b,PersistenceRequired:1b,"
                f"CustomNameVisible:1b,{self._name_nbt()},"
                f'Tags:["vesper","{self.epoch}","{tag}"]}}')

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

    # -- the collector's events ----------------------------------------------
    def observe(self, event: dict[str, Any]) -> None:
        if event.get("kind") in ("join", "leave", "death", "advancement", "chat"):
            self._events.append(dict(event))

    def interval(self, default: float) -> float:
        return FAST_INTERVAL if (self.asking or self.live) else default

    # -- one beat ------------------------------------------------------------
    def step(self) -> None:
        with self._lock:
            self._step()

    def _step(self) -> None:
        now = self.clock()
        online = list(self.col.sessions)
        events = list(self._events)
        self._events.clear()
        for ev in events:
            self._learn(ev, now)
        if not online:
            if self.was_online:
                self._wind_down("Everyone left.")
            self.was_online = False
            self.swept = False
            self.state = "off" if not self.enabled() else "idle"
            return
        self.was_online = True
        if not self.enabled():
            if self.live or self.asking:
                self._wind_down("Vesper was switched off.")
            self.state = "paused" if self.enabled_opt() else "off"
            return
        if not self.swept:
            # Anything an earlier run of this panel left behind.
            self._try(f"minecraft:kill @e[tag=vesper,tag=!{self.epoch}]")
            self.swept = True
        bed = self.bedtime_fn()
        if bed:
            if not self.bedtime_said:
                self._goodnight(online)
                self.bedtime_said = True
            self.state = "bedtime"
            return
        self.bedtime_said = False
        if bed is None:
            # Configured but unreadable: nothing new until it can be read.
            self.state = "waiting"
            self._run_live(now)
            return
        for ev in events:
            self._attend(ev, now)
        self._watch_positions(online, now)
        for player, since in list(self.pending_greet.items()):
            if player not in self.col.sessions or now - since > 30:
                self.pending_greet.pop(player, None)
            elif self._pos(player):
                self.pending_greet.pop(player, None)
                self.greet(player)
        self._run_live(now)
        self._run_questions(online, now)
        self.state = "asking" if self.asking else "acting" if self.live else "idle"

    # -- learning (no RCON) ------------------------------------------------
    def _learn(self, ev: dict[str, Any], now: float) -> None:
        player = ev.get("player")
        if not player:
            return
        who = self.roster.who(player)
        if who["role"] == "guest":
            return
        kind = ev.get("kind")
        if kind == "join":
            self.memory.joined(who)
        elif kind == "leave":
            self.memory.left(who, ev.get("seconds"))

    # -- attention ---------------------------------------------------------
    def _attend(self, ev: dict[str, Any], now: float) -> None:
        player = ev.get("player")
        if not player:
            return
        who = self.roster.who(player)
        kind = ev.get("kind")
        child = who["role"] == "child"
        if kind == "join":
            self.session_acts[player] = 0
            self.still.pop(player, None)
            self.near.pop(player, None)
            self.moment("join", player, 0.9 if child else 0.3 if who["role"] == "reader" else 0.0)
            if child:
                self.pending_greet[player] = now
        elif kind == "leave":
            self._player_left(player)
            self.session_acts.pop(player, None)
            self.still.pop(player, None)
        elif kind == "death":
            self.moment("death", player, 0.6 if child else 0.3)
        elif kind == "advancement":
            self.moment("achievement", player, 0.5 if child else 0.2, what=ev.get("what"))
        elif kind == "chat" and who["role"] == "reader":
            said = str(ev.get("text") or "").split(": ", 1)[-1]
            if re.search(r"\bvesper\b", said, re.I):
                m = self.moment("asked", player, 0.8, said=said[:200])
                if m and m.get("sent"):
                    self.tell(player, "I heard you.")

    def moment(self, kind: str, player: str, score: float, **detail) -> dict[str, Any] | None:
        """Note a moment; announce it when it is worth it and allowed."""
        now = self.clock()
        who = self.roster.who(player)
        key = (kind, player)
        if kind not in ("join", "answered") and now - self.cooldowns.get(key, -1e12) < MOMENT_COOLDOWN:
            return None
        self.cooldowns[key] = now
        m = {"t": int(now), "kind": kind, "player": player, "person": who["person"],
             "role": who["role"], "score": round(score, 2), **detail, "sent": False}
        if who["role"] != "guest":
            self.memory.moment(who, kind)
        if score >= EVENT_THRESHOLD and self.budget.spend("events"):
            payload = {k: v for k, v in m.items() if k != "sent"}
            payload["world"] = self.col.level_name()
            try:
                self.emit_fn("bruh_minecraft_moment", payload)
                m["sent"] = True
            except Exception:  # noqa: BLE001 — Home Assistant away is not the game's problem
                m["sent"] = False
        self.moments.appendleft(m)
        return m

    def _pos(self, player: str) -> tuple[list[float], str] | None:
        info = self.col.players.get(player) or {}
        pos = info.get("pos")
        if not pos:
            return None
        return list(pos), info.get("dimension") or "minecraft:overworld"

    def _watch_positions(self, online: list[str], now: float) -> None:
        for player in online:
            who = self.roster.who(player)
            if who["role"] == "guest":
                continue
            info = self.col.players.get(player) or {}
            pos = info.get("pos")
            if pos:
                was = self.still.get(player)
                if was is None or math.dist(was[0], pos) > IDLE_RADIUS:
                    self.still[player] = (list(pos), now, False)
                elif not was[2] and now - was[1] >= IDLE_AFTER:
                    self.still[player] = (was[0], was[1], True)
                    self.moment("idle", player, 0.5 if who["role"] == "child" else 0.1)
            place = info.get("near")
            if place != self.near.get(player, "\0"):
                prev = self.near.get(player, "\0")
                self.near[player] = place
                if place and prev != "\0":
                    rec = self.memory.get(who["person"])
                    favourite = place in Memory.favourites(rec)
                    self.memory.visited(who, place)
                    if favourite:
                        self.moment("favourite_place", player,
                                    0.6 if who["role"] == "child" else 0.2, place=place)
                elif place:
                    self.memory.visited(who, place)

    # -- may Vesper act? -----------------------------------------------------
    def can_act(self, player: str) -> str:
        """'' when Vesper may do something proactive for `player` now, else why not."""
        if not self.enabled():
            return "Vesper is switched off."
        bed = self.bedtime_fn()
        if bed:
            return "It is bedtime."
        if bed is None:
            return "Vesper cannot see the bedtime switch."
        if player not in self.col.sessions:
            return f"{player} is not online."
        if self.session_acts.get(player, 0) >= SESSION_CAP:
            return f"Vesper has done enough for {player} this session."
        if self.budget.left("actions") <= 0:
            return "Vesper's budget for today is spent."
        return ""

    def _spend(self, player: str) -> None:
        self.session_acts[player] = self.session_acts.get(player, 0) + 1
        self.budget.spend("actions")

    # -- M2: the greeting ------------------------------------------------------
    def greet(self, player: str) -> dict[str, Any] | None:
        now = self.clock()
        if now - self.cooldowns.get(("greet", player), -1e12) < GREET_COOLDOWN:
            return None
        if self.can_act(player) or self.asking:
            return None
        who = self.roster.who(player)
        self.cooldowns[("greet", player)] = now
        act = self.actions.start("greet", who, f"Vesper came to say hello to {who['person']}.")
        tag = act["tag"]
        p = quote_name(player)
        reply = self._try(f"minecraft:execute at {p} rotated ~ 0 run minecraft:summon "
                          f"minecraft:allay ^ ^1.2 ^2 {self._body_nbt(tag)}")
        if reply is None or not re.search(r"summoned", reply, re.I):
            act.update(status="failed", ended_at=int(now),
                       note=(reply or "The server did not answer.")[:200])
            self.actions.put(act)
            return act
        self._spend(player)
        self._chime(player)
        self._sparkle_at_tag(tag)
        self._try(f"minecraft:execute as @e[tag={tag},limit=1] at @s run minecraft:tp @s "
                  f"~ ~ ~ facing entity {p} eyes")
        self.live[act["id"]] = {"kind": "greet", "player": player, "tag": tag,
                                "beats": 0, "ends_at": now + GREETING_LIFETIME}
        self.col.record({"kind": "vesper", "player": player, "action": act["id"],
                         "text": act["text"]})
        return act

    def _run_live(self, now: float) -> None:
        for aid, live in list(self.live.items()):
            if live["kind"] != "greet":
                continue
            tag = live["tag"]
            live["beats"] += 1
            if now >= live["ends_at"]:
                self._end_greeting(aid, "done")
                continue
            if live["beats"] in (1, 3):            # the wave: up …
                self._try(f"minecraft:execute as @e[tag={tag},limit=1] at @s run "
                          "minecraft:tp @s ~ ~0.5 ~ ~30 ~")
            elif live["beats"] in (2, 4):          # … and down, sparkling
                self._try(f"minecraft:execute as @e[tag={tag},limit=1] at @s run "
                          "minecraft:tp @s ~ ~-0.5 ~ ~-30 ~")
                self._sparkle_at_tag(tag, 8)

    def _end_greeting(self, aid: str, status: str) -> None:
        live = self.live.pop(aid, None)
        if live:
            self._remove_tag(live["tag"])
        act = self.actions.get(aid)
        if act and act.get("status") == "active":
            act.update(status=status, ended_at=int(self.clock()))
            self.actions.put(act)

    def _goodnight(self, online: list[str]) -> None:
        self._wind_down("Bedtime.")
        for player in online:
            if self.roster.who(player)["role"] != "child":
                continue
            p = quote_name(player)
            self._try(f"minecraft:title {p} title {text_component('Goodnight!')}")
            self._chime(player, pitches=(1.5, 1.26, 1.0), volume=0.4)
        self.col.record({"kind": "vesper", "player": None,
                         "text": "Vesper said goodnight and stopped for bedtime."})

    def _player_left(self, player: str) -> None:
        for aid, live in list(self.live.items()):
            if live.get("player") == player:
                self._end_greeting(aid, "done")
        if self.asking and self.asking.get("player") == player:
            self._close_question(requeue=True, note=f"{player} left before answering.")
        self.pending_greet.pop(player, None)

    def _wind_down(self, why: str) -> None:
        """Take every live thing out of the world (the transition to quiet)."""
        for aid in list(self.live):
            self._end_greeting(aid, "done")
        if self.asking:
            self._close_question(requeue=True, note=why)
        self.pending_greet.clear()
        self.last_note = why
        if not self.col.sessions:
            # Nobody to watch: give the connection back, as the collector does.
            self.col.session.close()

    # -- hands -----------------------------------------------------------------
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
        """Put back each cell that still holds what Vesper placed."""
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

    # -- M3: choice pads -----------------------------------------------------
    def ask(self, player: str, text: str, options: Any = None, by: str = "brAIn") -> dict[str, Any]:
        """Queue a question for a child; it is put to them when they are on."""
        with self._lock:
            if not self.enabled_opt():
                raise VesperError("Vesper's engine is off (the add-on's vesper_engine option).")
            player = str(player or "").strip()
            who = self.roster.who(player)
            if who["role"] == "guest":
                # A person's name rather than a player's: find their name online.
                match = [p for p in self.roster.people() if p["person"].lower() == player.lower()]
                if match:
                    names = match[0]["players"]
                    on = [n for n in self.col.sessions if bare(n) in {bare(x) for x in names}]
                    player = on[0] if on else names[0]
                    who = self.roster.who(player)
            if who["role"] == "guest" and not re.fullmatch(r"[A-Za-z0-9_.*]{1,17}", player):
                raise VesperError(f"{player!r} is not a player Vesper knows.")
            text = str(text or "").replace("\n", " ").strip()[:200]
            if not text:
                raise VesperError("What is the question? (It is kept for the parent; the "
                                  "child sees the pictures.)")
            now = self.clock()
            q = {"id": time.strftime("%Y%m%d", time.localtime(now)) + "-" + secrets.token_hex(3),
                 "player": player, "person": who["person"], "text": text,
                 "options": clean_options(options), "by": str(by or "brAIn")[:40],
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
            if self.can_act(q["player"]):
                continue
            self._pose(q, now)
            return

    def _site(self, player: str) -> tuple[list[dict[str, Any]] | None, dict[str, Any], str]:
        here = self._pos(player)
        if not here:
            return None, {}, "Vesper does not know where they are yet."
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
        who = self.roster.who(player)
        opts = q["options"]
        act = self.actions.start(
            "pads", who, f"Vesper asked {who['person']}: {q['text']} "
                         f"({opts[0]['label']} or {opts[1]['label']})", question=q["id"])
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
        self._spend(player)
        mid = layout["pads"]
        cx = (mid[0]["min_x"] + mid[1]["min_x"]) / 2 + 1
        cz = (mid[0]["min_z"] + mid[1]["min_z"]) / 2 + 1
        self._try(f"minecraft:execute in {layout['dim']} positioned {cx} {layout['y'] + 1.5} {cz} "
                  f"run minecraft:summon minecraft:allay ~ ~ ~ {self._body_nbt(act['tag'])}")
        self._chime(player, pitches=(1.0, 1.5))
        q.update(status="open", asked_at=int(now), action=act["id"], note="")
        self.questions.put(q)
        self.asking = {"qid": q["id"], "player": player, "action": act["id"],
                       "layout": layout, "on": {}, "since": now, "beats": 0,
                       "answered": None, "remove_at": None}
        self.col.record({"kind": "vesper", "player": player, "action": act["id"],
                         "text": f"Vesper put two choice pads beside {who['person']}"})

    def _watch_pads(self, now: float) -> None:
        a = self.asking
        lay = a["layout"]
        dim, y = lay["dim"], lay["y"]
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
            self._sparkle_at_tag("vesper_" + a["action"].split("-")[1], 20)
        who = self.roster.who(player)
        self.memory.answered(who, q, chosen, other)
        q.update(status="answered", answer=chosen["label"], answered_at=int(now))
        self.questions.put(q)
        a.update(answered=i, remove_at=now + RESULT_LINGER)
        self.col.record({"kind": "vesper", "player": player, "action": a["action"],
                         "text": f"{who['person']} chose {chosen['label']}"})
        self.moment("answered", player, 0.9, question=q["text"], answer=chosen["label"],
                    question_id=q["id"])

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
            raise VesperError("That is not an action id.")
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
                    q.update(status="cancelled", note="Undone by a parent.")
                    self.questions.put(q)
            self.live.pop(action_id, None)
            result = self._restore(act)
            self._remove_tag(act["tag"], poof=False)
            act.update(status="undone", ended_at=int(self.clock()),
                       undo_note=(f"{result['changed']} block(s) had changed since and were left."
                                  if result["changed"] else ""))
            self.actions.put(act)
            self.col.record({"kind": "vesper", "player": None, "action": action_id,
                             "text": f"A parent undid: {act.get('text', '')}"[:240]})
            return {"action": act, **result}

    # -- reading ---------------------------------------------------------------
    def brief(self) -> dict[str, Any]:
        """The small view for world.json and Home Assistant."""
        last = self.actions.list(1)
        open_q = self.asking and self.questions.get(self.asking["qid"])
        return {"enabled": bool(self.enabled_opt()), "paused": self.paused(),
                "state": self.state, "budget": self.budget.view(),
                "queued_questions": len(self.questions.list("queued")),
                "open_question": ({k: open_q.get(k) for k in ("id", "person", "text")}
                                  if open_q else None),
                "last_action": ({k: last[0].get(k) for k in ("id", "t", "kind", "person",
                                                             "text", "status")}
                                if last else None)}

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {**self.brief(), "note": self.last_note,
                    "family": self.roster.people(),
                    "zones": self.zones.list(),
                    "moments": list(self.moments)[:20],
                    "questions": self.questions.list()[:20],
                    "actions": [dict(a, undoable=undoable(a)) for a in self.actions.list(30)],
                    "memory": self.memory.all()}


__all__ = ["Engine", "Roster", "Zones", "Memory", "ActionLog", "Budget", "Questions",
           "GuardError", "VesperError", "check_command", "clean_options", "block_id",
           "modern_text", "bare", "undoable"]
