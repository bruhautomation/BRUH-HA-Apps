#!/usr/bin/env python3
"""What is going on in the Minecraft world: its senses, and the build log.

The owner (#573): *"I don't care about TPS or latency. I want to know what's
going on in the world … I want to know what [the companion] is building
as part of the sentience engine."* This module is that layer, and the API
a companion playing in the world (brAIn's, through Home Assistant) reads it
through.

* **WorldCollector** asks the server over RCON — no plugin — who is on and,
  for each of them, where (position, dimension), in what game mode and
  with how much health and food; the time of day, the day count and the
  weather. It does that every few seconds ONLY while somebody is online,
  and once a minute otherwise (four short commands). While anybody is on it
  keeps ONE RCON connection open, because every new connection writes two
  "Thread RCON Client" lines into the server log.
* It also tails the server's log (`logs/latest.log`) for joins, leaves,
  deaths, advancements, chat and the server starting and stopping, keeps
  the last `FEED_SIZE` of them as the world feed, each player's last-seen
  time, and writes a **journal** per day (`.bruh-world/journal/<day>.jsonl`
  in the world folder): what happened, who was on and for how long.
* **BuildLog** is the companion's build jobs (`.bruh-world/builds.json`): title, which
  part of the engine, status queued/building/done/failed, progress, the
  build's box, start and finish, a picture and notes. The panel's
  `/api/builds` routes are its only writer; nothing about it needs RCON.

Everything a person or Home Assistant reads is in one snapshot
(`WorldCollector.snapshot()`), written to `world.json` beside `stats.json`
and mirrored to `/config/.bruh_minecraft` by the HA bridge.

The commands are namespaced (`minecraft:time`, `minecraft:data`) because
EssentialsX overrides the bare ones and logs every RCON use of a command it
handles. None of them is broadcast to operators in chat: `data get`, `time
query`, `list` and `execute if` all answer the caller only.
"""
from __future__ import annotations

import json
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
BUSY_INTERVAL = 5          # seconds between polls while somebody is online
IDLE_INTERVAL = 60         # ... and while nobody is
LOG_INTERVAL = 2           # seconds between looks at the log (a stat, mostly)
FEED_SIZE = 50
MAX_PLAYERS_DETAILED = 12  # players asked about in detail each poll
JOURNAL_DAY_CAP = 3000     # lines in one day's journal; chat is dropped first
CHAT_CAP = 200             # characters of one chat line kept
MAX_JOBS = 200
NEAR_RADIUS = 96           # blocks: within this a place is "near"
WEATHER_RETRY = 3600       # seconds before asking a server that refused again
JOIN_GRACE = 30            # seconds a join seen by `list` waits for its log line
LOG_SILENT = 300           # seconds of a silent log, with players on, that mean it is not read

DATA_DIR_NAME = ".bruh-world"

# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
_COLOUR = re.compile(r"\u00a7.")


def plain(text: str) -> str:
    """A reply without Minecraft's § colour codes."""
    return _COLOUR.sub("", str(text or ""))


def atomic_write_text(path: Path, text: str) -> None:
    """Write `text` to `path` through a temporary file in the same folder."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            # The temporary file is already gone; the write's own error is what matters.
            pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write_text(path, json.dumps(data, indent=1, sort_keys=False))


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Reading the server's replies
# ---------------------------------------------------------------------------
_LIST_RE = re.compile(
    r"There are (?P<online>\d+) of a max(?: of)? (?P<max>\d+) players online:? ?(?P<players>.*)")
_TIME_RE = re.compile(r"The time is (-?\d+)")
_DATA_RE = re.compile(r"has the following entity data: (.*)$", re.S)
GAMEMODES = {0: "survival", 1: "creative", 2: "adventure", 3: "spectator"}
# What a name may hold unquoted in a command's entity argument (Brigadier's
# unquoted-string characters). A Floodgate prefix of `.` is one of them; a
# `*` prefix, which some Floodgate configs use, is not, so that name is
# quoted.
_UNQUOTED = re.compile(r"^[0-9A-Za-z_\-.+]+$")


def parse_list(reply: str) -> dict[str, Any] | None:
    m = _LIST_RE.search(plain(reply))
    if not m:
        return None
    return {"online": int(m.group("online")), "max": int(m.group("max")),
            "players": [p.strip() for p in m.group("players").split(",") if p.strip()]}


_TIME_ANY_RE = re.compile(
    # "The time is 6000", "The time of minecraft:overworld is 6000 ticks",
    # "Time: 6,000", "Daytime is 6000", "It is day 12": the number that
    # follows "is", "time", "day" or a colon, with thousands separators.
    r"(?:\bis|\btime|\bday|:)\D{0,40}?(-?\d[\d,_ ]{0,15}\d|-?\d)\b", re.I)
_BARE_NUMBER_RE = re.compile(r"^\s*(-?\d[\d,_]*)\s*(?:ticks?)?\s*\.?\s*$", re.I)


def parse_time(reply: str) -> int | None:
    """The number in a `time query` answer, or None.

    Vanilla answers "The time is 6000"; Paper 26.x's world clocks and some
    forks say it differently ("The time of minecraft:overworld is 6000
    ticks", "Time: 6,000", a bare "6000"). Anything that is not one of
    those — an error, a usage line — is None rather than a guess.
    """
    text = plain(reply).strip()
    if not text or re.search(r"unknown|incorrect|expected|<--\[here\]|usage", text, re.I):
        return None
    m = _TIME_RE.search(text)
    if m:
        return int(m.group(1))
    m = _BARE_NUMBER_RE.match(text) or _TIME_ANY_RE.search(text)
    if not m:
        return None
    digits = re.sub(r"[,_ ]", "", m.group(1))
    try:
        return int(digits)
    except ValueError:
        return None


def parse_test(reply: str) -> bool | None:
    """`execute if …`'s answer: True passed, False failed, None not understood."""
    text = plain(reply).strip().lower()
    if text.startswith("test passed"):
        return True
    if text.startswith("test failed"):
        return False
    return None


def quote_name(name: str) -> str:
    """A player name as a command's entity argument takes it."""
    if _UNQUOTED.match(name):
        return name
    return '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'


def data_value(reply: str) -> str | None:
    """The SNBT after `… has the following entity data:`, or None."""
    m = _DATA_RE.search(plain(reply))
    return m.group(1).strip() if m else None


def snbt_number(text: str | None) -> float | None:
    if text is None:
        return None
    m = re.match(r"^\s*(-?\d+(?:\.\d+)?(?:[eE]-?\d+)?)[bBsSlLfFdD]?\s*$", text)
    return float(m.group(1)) if m else None


def snbt_pos(text: str | None) -> list[float] | None:
    if not text:
        return None
    nums = re.findall(r"-?\d+(?:\.\d+)?(?:[eE]-?\d+)?", text)
    if len(nums) != 3:
        return None
    return [float(n) for n in nums]


def snbt_string(text: str | None) -> str | None:
    if not text:
        return None
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    return t


def short_dimension(dim: str | None) -> str:
    d = (dim or "").split(":", 1)[-1]
    return {"overworld": "Overworld", "the_nether": "Nether",
            "the_end": "End"}.get(d, d.replace("_", " ").title() or "Overworld")


def phase_of(daytime: int) -> str:
    """sunrise, day, sunset or night, as the sky in game has it."""
    t = daytime % 24000
    if t < 12000:
        return "day"
    if t < 13800:
        return "sunset"
    if t < 22200:
        return "night"
    return "sunrise"


def clock_of(daytime: int) -> tuple[int, int]:
    """The in-game clock (hour, minute): tick 0 is 06:00."""
    t = daytime % 24000
    hour = (t // 1000 + 6) % 24
    minute = (t % 1000) * 60 // 1000
    return hour, minute


# ---------------------------------------------------------------------------
# The log
# ---------------------------------------------------------------------------
# `logs/latest.log`: "[12:34:56] [Server thread/INFO]: Steve joined the game"
# the console (stdout): "[12:34:56 INFO]: Steve joined the game"
_LINE_RE = re.compile(
    r"^\[(?P<clock>\d\d:\d\d:\d\d)(?:\] \[(?P<thread>[^\]]*)/| )(?P<level>[A-Z]+)\]: (?P<msg>.*)$")
_NAME = r"[A-Za-z0-9_.*\-]{1,32}"
_JOIN_RE = re.compile(rf"^(?P<name>{_NAME}) joined the game$")
_LEAVE_RE = re.compile(rf"^(?P<name>{_NAME}) left the game$")
_ADV_RE = re.compile(
    rf"^(?P<name>{_NAME}) has (?P<how>made the advancement|completed the challenge|reached the goal) \[(?P<what>.+)\]$")
_CHAT_RE = re.compile(r"^(?:\[Not Secure\] )?<(?P<name>[^>]{1,40})> (?P<text>.*)$")
# The shapes a server script or chat plugin gives a chat line once it
# rewrites the format (Skript's `chat format`, EssentialsX Chat, a nickname
# plugin): "[Not Secure] Dad: hi", "[Member] Dad » hi", "Dad > hi". These
# are only read as chat when the line says it is (`[Not Secure]`, Paper's
# chat thread) or the name is somebody the collector knows is playing — a
# plugin's "Loading: 12 worlds" is not somebody called Loading talking.
_NOT_SECURE = "[Not Secure] "
_SPOKEN_RE = re.compile(
    r"^(?P<name>(?:\[[^\]]{1,24}\] ?)*[^\s:<>»\[\]][^:<>»]{0,39}?)\s?(?::|»|>|›|\|)\s(?P<text>.+)$")
_RANK_RE = re.compile(r"^(?:\[[^\]]{0,24}\]\s*)+|^[~*@]+")
# Paper logs messages the server itself broadcast (a script's own join line,
# an announcement) as "System chat: …"; the vanilla join and leave lines
# can arrive that way too.
_SYSTEM_RE = re.compile(r"^(?:\[[^\]]*\] )?System chat: (?P<text>.*)$")


def shown_name(name: str) -> str:
    """A name as a chat line shows it, without a rank in brackets, colour
    codes or a nickname marker: "[Admin] ~Dad" is "Dad"."""
    text = plain(str(name or "")).strip()
    for _ in range(4):
        cut = _RANK_RE.sub("", text).strip()
        if cut == text:
            break
        text = cut
    return text[:40]
_DONE_RE = re.compile(r"^Done \([\d.,]+s\)! For help")
_DEATH_RE = re.compile(
    rf"^(?P<name>{_NAME}) (?P<how>"
    r"was (?:slain|shot|killed|blown up|fireballed|pummeled|impaled|squashed|squished|"
    r"pricked|poked|stung|struck by lightning|frozen|obliterated|skewered|"
    r"doomed to fall|burnt to a crisp|roasted|knocked|sniped|stabbed)"
    r"|fell |drowned|burned to death|blew up|hit the ground too hard|tried to swim in lava|"
    r"starved to death|suffocated|died|withered away|froze to death|experienced kinetic energy|"
    r"went up in flames|went off with a bang|walked into|discovered the floor was lava|"
    r"didn't want to live|left the confines of this world|was killed)")


def _bare(name: str) -> str:
    return re.sub(r"^[.*]", "", str(name or "").strip()).lower()


def parse_log_line(line: str, known: set[str] | frozenset[str] = frozenset()) -> dict[str, Any] | None:
    """One world event from a server log line, or None.

    `kind` is join, leave, death, advancement, chat, save or server. A
    death is anything that reads like a death message for a player name;
    when the names of the players known to be on are given, the line has to
    be about one of them, because a plugin's line can start with a word.

    A chat line's `player` is the name the line shows, which a script may
    have made a nickname ("Dad"); the collector maps it back to who is
    playing (`WorldCollector.speaker`). A rewritten format is still chat
    (`_SPOKEN_RE`) when the line is marked `[Not Secure]`, came from
    Paper's chat thread, or names somebody `known`.
    """
    m = _LINE_RE.match(line.rstrip("\r\n"))
    if not m or m.group("level") != "INFO":
        return None
    msg = plain(m.group("msg")).strip()
    thread = str(m.group("thread") or "")
    if (s := _SYSTEM_RE.match(msg)):
        inner = s["text"].strip()
        if _JOIN_RE.match(inner) or _LEAVE_RE.match(inner):
            msg = inner
        else:
            return None
    marked = msg.startswith(_NOT_SECURE)
    if marked:
        msg = msg[len(_NOT_SECURE):].strip()
    if (j := _JOIN_RE.match(msg)) and not marked:
        return {"kind": "join", "player": j["name"], "text": f"{j['name']} joined"}
    if (j := _LEAVE_RE.match(msg)):
        return {"kind": "leave", "player": j["name"], "text": f"{j['name']} left"}
    if (j := _ADV_RE.match(msg)):
        verb = {"made the advancement": "made the advancement",
                "completed the challenge": "completed the challenge",
                "reached the goal": "reached the goal"}[j["how"]]
        return {"kind": "advancement", "player": j["name"], "what": j["what"],
                "text": f"{j['name']} {verb} {j['what']}"}
    if (j := _CHAT_RE.match(msg)):
        name = shown_name(j["name"]) or j["name"]
        said = j["text"].strip()[:CHAT_CAP]
        return {"kind": "chat", "player": name, "said": said, "text": f"{name}: {said}"}
    if (j := _SPOKEN_RE.match(msg)):
        name = shown_name(j["name"])
        chat_thread = "chat" in thread.lower()
        if name and (marked or chat_thread or _bare(name) in {_bare(k) for k in known}):
            said = j["text"].strip()[:CHAT_CAP]
            return {"kind": "chat", "player": name, "said": said, "text": f"{name}: {said}"}
    if marked:
        return None
    if msg == "Saved the game":
        return {"kind": "save", "player": None, "text": "The world was saved"}
    if _DONE_RE.match(msg):
        return {"kind": "server", "player": None, "text": "The server started"}
    if msg.startswith("Stopping server") or msg == "Stopping the server":
        return {"kind": "server", "player": None, "text": "The server is stopping"}
    if (j := _DEATH_RE.match(msg)):
        if known and j["name"] not in known:
            return None
        return {"kind": "death", "player": j["name"], "text": msg[:240]}
    return None


class LogTail:
    """New lines of a log file, across the server replacing it on restart."""

    def __init__(self, paths: list[Path]):
        self.paths = [Path(p) for p in paths]
        self.path: Path | None = None
        self.inode: int | None = None
        self.pos = 0
        self.buffer = b""
        self._pick(at_end=True)

    def _pick(self, at_end: bool) -> None:
        for p in self.paths:
            try:
                st = p.stat()
            except OSError:
                continue
            self.path, self.inode = p, st.st_ino
            self.pos = st.st_size if at_end else 0
            self.buffer = b""
            return
        self.path = None

    def read(self, limit: int = 1 << 20) -> list[str]:
        if self.path is None:
            self._pick(at_end=False)
            if self.path is None:
                return []
        try:
            st = self.path.stat()
        except OSError:
            self.path = None
            return []
        if st.st_ino != self.inode or st.st_size < self.pos:
            # A new log (the server restarted): its lines are all new.
            self.inode, self.pos, self.buffer = st.st_ino, 0, b""
        if st.st_size == self.pos:
            return []
        try:
            with open(self.path, "rb") as f:
                f.seek(self.pos)
                chunk = f.read(min(limit, st.st_size - self.pos))
        except OSError:
            return []
        self.pos += len(chunk)
        data = self.buffer + chunk
        *lines, self.buffer = data.split(b"\n")
        return [ln.decode("utf-8", "replace") for ln in lines]


# ---------------------------------------------------------------------------
# The journal
# ---------------------------------------------------------------------------
class Journal:
    """One JSON-lines file per local day: what happened in the world.

    Each event is one line (`t`, `kind`, `player`, `text`, and `seconds`
    on a leave). A day's file is rewritten whole through a temporary file
    on every event, so a reader never sees half a line; a day is capped at
    `JOURNAL_DAY_CAP` lines, and chat is what stops being kept first.
    """

    def __init__(self, root: Path, clock: Callable[[], float] = time.time):
        self.root = Path(root)
        self.clock = clock
        self._day: str | None = None
        self._lines: list[str] = []
        self._lock = threading.Lock()

    @staticmethod
    def day_of(t: float) -> str:
        return time.strftime("%Y-%m-%d", time.localtime(t))

    def path(self, day: str) -> Path:
        return self.root / f"{day}.jsonl"

    def add(self, event: dict[str, Any]) -> None:
        day = self.day_of(event.get("t") or self.clock())
        with self._lock:
            if day != self._day:
                self._day = day
                try:
                    self._lines = self.path(day).read_text(encoding="utf-8").splitlines()
                except OSError:
                    self._lines = []
            if len(self._lines) >= JOURNAL_DAY_CAP:
                return
            if event.get("kind") == "chat" and len(self._lines) >= JOURNAL_DAY_CAP * 2 // 3:
                return
            self._lines.append(json.dumps(event, separators=(",", ":")))
            atomic_write_text(self.path(day), "\n".join(self._lines) + "\n")

    def days(self, limit: int = 60) -> list[str]:
        try:
            names = sorted((p.stem for p in self.root.glob("*.jsonl")), reverse=True)
        except OSError:
            return []
        return [n for n in names if re.fullmatch(r"\d{4}-\d\d-\d\d", n)][:limit]

    def events(self, day: str) -> list[dict[str, Any]]:
        if not re.fullmatch(r"\d{4}-\d\d-\d\d", day or ""):
            return []
        out = []
        try:
            text = self.path(day).read_text(encoding="utf-8")
        except OSError:
            return []
        for line in text.splitlines():
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            if isinstance(ev, dict):
                out.append(ev)
        return out

    def summary(self, day: str, open_sessions: dict[str, float] | None = None,
                person_of: Callable[[str], str] | None = None) -> dict[str, Any]:
        """Who was on that day and for how long, and what happened.

        With `person_of` (an in-game name to a person), `people` sums each
        person's names: time on, deaths, advancements, chat lines and what
        the companion did with them.
        """
        events = self.events(day)
        seconds: dict[str, int] = {}
        counts: dict[str, int] = {}
        per: dict[str, dict[str, int]] = {}
        for ev in events:
            counts[ev.get("kind", "?")] = counts.get(ev.get("kind", "?"), 0) + 1
            who = ev.get("player")
            if ev.get("kind") == "leave" and who and isinstance(ev.get("seconds"), (int, float)):
                seconds[who] = seconds.get(who, 0) + int(ev["seconds"])
            elif who and ev.get("kind") in ("join", "death", "advancement", "chat"):
                seconds.setdefault(who, 0)
            if who and ev.get("kind") in ("join", "death", "advancement", "chat", "companion"):
                per.setdefault(who, {}).setdefault(ev["kind"], 0)
                per[who][ev["kind"]] += 1
        if open_sessions and day == self.day_of(self.clock()):
            now = self.clock()
            start_of_day = time.mktime(time.strptime(day, "%Y-%m-%d"))
            for who, since in open_sessions.items():
                seconds[who] = seconds.get(who, 0) + int(now - max(since, start_of_day))
        out = {"day": day, "players": seconds, "counts": counts,
               "events": len(events),
               "first": events[0].get("t") if events else None,
               "last": events[-1].get("t") if events else None}
        if person_of is not None:
            people: dict[str, dict[str, Any]] = {}
            for who in set(seconds) | set(per):
                rec = people.setdefault(person_of(who), {
                    "players": [], "seconds": 0, "joins": 0, "deaths": 0,
                    "advancements": 0, "chat": 0, "companion": 0})
                rec["players"].append(who)
                rec["seconds"] += seconds.get(who, 0)
                kinds = per.get(who, {})
                rec["joins"] += kinds.get("join", 0)
                rec["deaths"] += kinds.get("death", 0)
                rec["advancements"] += kinds.get("advancement", 0)
                rec["chat"] += kinds.get("chat", 0)
                rec["companion"] += kinds.get("companion", 0)
            out["people"] = people
        return out


# ---------------------------------------------------------------------------
# The build log
# ---------------------------------------------------------------------------
STATUSES = ("queued", "building", "done", "failed")
_TEXT_FIELDS = {"title": 120, "part": 60, "notes": 2000, "by": 40, "image": 300,
                "image_note": 200}
_BOUND_KEYS = ("x1", "y1", "z1", "x2", "y2", "z2")


class BuildError(ValueError):
    """A job that cannot be saved as given; the message says why."""


def clean_bounds(value: Any) -> dict[str, Any] | None:
    """A build's box: two corners, y optional, and a dimension."""
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        raise BuildError("bounds is an object with x1, z1, x2, z2 (y1, y2 and dimension optional).")
    out: dict[str, Any] = {}
    for k in _BOUND_KEYS:
        v = value.get(k)
        if v is None or v == "":
            continue
        try:
            n = int(round(float(v)))
        except (TypeError, ValueError):
            raise BuildError(f"bounds.{k} is not a number.") from None
        if abs(n) > 30_000_000:
            raise BuildError(f"bounds.{k} is outside the world.")
        out[k] = n
    for k in ("x1", "z1", "x2", "z2"):
        if k not in out:
            raise BuildError("bounds needs x1, z1, x2 and z2.")
    dim = str(value.get("dimension") or "minecraft:overworld").strip()
    if not re.fullmatch(r"[a-z0-9_.\-]+(:[a-z0-9_./\-]+)?", dim):
        raise BuildError("bounds.dimension is a dimension id like minecraft:overworld.")
    out["dimension"] = dim if ":" in dim else f"minecraft:{dim}"
    return out


class BuildLog:
    """The companion's build jobs for one world, newest first.

    The file is the record (`builds.json`), written whole through a
    temporary file; the panel is its one writer. Status moves set the
    times: `building` stamps `started_at` (once), `done`/`failed` stamp
    `finished_at` and, on done, `progress` 100.
    """

    def __init__(self, path: Path, clock: Callable[[], float] = time.time):
        self.path = Path(path)
        self.clock = clock
        self._lock = threading.Lock()

    def _load(self) -> list[dict[str, Any]]:
        data = _read_json(self.path, {})
        jobs = data.get("jobs") if isinstance(data, dict) else data
        return [j for j in (jobs or []) if isinstance(j, dict) and j.get("id")]

    def _save(self, jobs: list[dict[str, Any]]) -> None:
        jobs = sorted(jobs, key=lambda j: j.get("created_at") or 0, reverse=True)[:MAX_JOBS]
        atomic_write_json(self.path, {"jobs": jobs})

    def list(self, status: str | None = None, limit: int = MAX_JOBS) -> list[dict[str, Any]]:
        jobs = sorted(self._load(), key=lambda j: j.get("created_at") or 0, reverse=True)
        if status:
            jobs = [j for j in jobs if j.get("status") == status]
        return jobs[:max(0, limit)]

    def get(self, job_id: str) -> dict[str, Any] | None:
        return next((j for j in self._load() if j.get("id") == job_id), None)

    def current(self) -> dict[str, Any] | None:
        """The job being built now (the most recently started), if any."""
        building = [j for j in self._load() if j.get("status") == "building"]
        if not building:
            return None
        return max(building, key=lambda j: j.get("started_at") or j.get("created_at") or 0)

    def _apply(self, job: dict[str, Any], data: dict[str, Any], now: float) -> None:
        for key, cap in _TEXT_FIELDS.items():
            if key in data:
                v = data[key]
                job[key] = "" if v is None else str(v).replace("\r", " ").strip()[:cap]
        if "bounds" in data:
            job["bounds"] = clean_bounds(data["bounds"])
        if "progress" in data:
            v = data["progress"]
            if v is None or v == "":
                job["progress"] = None
            else:
                try:
                    job["progress"] = max(0, min(100, int(round(float(v)))))
                except (TypeError, ValueError):
                    raise BuildError("progress is a number from 0 to 100.") from None
        for key in ("started_at", "finished_at"):
            if key in data:
                v = data[key]
                try:
                    job[key] = None if v in (None, "") else int(float(v))
                except (TypeError, ValueError):
                    raise BuildError(f"{key} is a Unix time in seconds.") from None
        if "status" in data:
            status = str(data["status"] or "").strip().lower()
            if status not in STATUSES:
                raise BuildError(f"status is one of {', '.join(STATUSES)}.")
            was = job.get("status")
            job["status"] = status
            if status == "building" and not job.get("started_at"):
                job["started_at"] = int(now)
            if status in ("done", "failed") and was not in ("done", "failed"):
                job.setdefault("started_at", None)
                if not data.get("finished_at"):
                    job["finished_at"] = int(now)
                if status == "done":
                    job["progress"] = 100
            if status in ("queued", "building"):
                job["finished_at"] = None if "finished_at" not in data else job.get("finished_at")
        job["updated_at"] = int(now)

    def create(self, data: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(data, dict):
            raise BuildError("A job is an object.")
        if not str(data.get("title") or "").strip():
            raise BuildError("A job needs a title (what is being built).")
        now = self.clock()
        job: dict[str, Any] = {
            "id": time.strftime("%Y%m%d", time.localtime(now)) + "-" + secrets.token_hex(3),
            "title": "", "part": "", "status": "queued", "progress": None,
            "bounds": None, "created_at": int(now), "started_at": None,
            "finished_at": None, "image": "", "image_note": "", "notes": "", "by": "brAIn",
        }
        self._apply(job, {"status": "queued", **data}, now)
        with self._lock:
            jobs = self._load()
            jobs.append(job)
            self._save(jobs)
        return job

    def update(self, job_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(data, dict):
            raise BuildError("A change is an object.")
        if "title" in data and not str(data.get("title") or "").strip():
            raise BuildError("A job's title cannot be empty.")
        with self._lock:
            jobs = self._load()
            job = next((j for j in jobs if j.get("id") == job_id), None)
            if job is None:
                return None
            self._apply(job, {k: v for k, v in data.items()
                              if k not in ("id", "created_at", "updated_at")}, self.clock())
            self._save(jobs)
            return job

    def delete(self, job_id: str) -> bool:
        with self._lock:
            jobs = self._load()
            kept = [j for j in jobs if j.get("id") != job_id]
            if len(kept) == len(jobs):
                return False
            self._save(kept)
            return True


def job_brief(job: dict[str, Any] | None) -> dict[str, Any] | None:
    """A job as small as Home Assistant's attributes want it."""
    if not job:
        return None
    return {k: job.get(k) for k in ("id", "title", "part", "status", "progress",
                                    "started_at", "finished_at", "image")}


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------
def nearest_place(pos: list[float] | None, dimension: str,
                  places: list[dict[str, Any]], radius: int = NEAR_RADIUS) -> str | None:
    """The name of the closest place within `radius` blocks, same dimension."""
    if not pos:
        return None
    best, best_d = None, float(radius) ** 2
    for p in places:
        if (p.get("dimension") or "minecraft:overworld") != (dimension or "minecraft:overworld"):
            continue
        try:
            dx, dz = pos[0] - float(p["x"]), pos[2] - float(p["z"])
        except (KeyError, TypeError, ValueError):
            continue
        r = float(p.get("radius") or radius)
        d = dx * dx + dz * dz
        if d <= min(best_d, r * r):
            best, best_d = p.get("name"), d
    return best


# ---------------------------------------------------------------------------
# RCON
# ---------------------------------------------------------------------------
class RconSession:
    """One RCON connection, opened on first use and kept until closed."""

    def __init__(self, factory: Callable[[], Any]):
        self.factory = factory
        self.conn = None
        # The world thread and the companion's API calls (an undo from the panel)
        # share the one connection; a request and its reply are one turn.
        self._lock = threading.RLock()

    def command(self, cmd: str) -> str:
        with self._lock:
            if self.conn is None:
                conn = self.factory()
                conn.connect()
                self.conn = conn
            try:
                return self.conn.command(cmd)
            except Exception:
                self.close()
                raise

    def close(self) -> None:
        with self._lock:
            conn, self.conn = self.conn, None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 — closing a broken socket
                pass


# ---------------------------------------------------------------------------
# The collector
# ---------------------------------------------------------------------------
class WorldCollector:
    """The world's senses: RCON polls, the log, the feed, the journal.

    `step()` is one beat (call it every `LOG_INTERVAL` seconds from a
    thread): it reads new log lines, and polls the server when it is time
    to — at once after a join, every `BUSY_INTERVAL` while somebody is on,
    every `IDLE_INTERVAL` otherwise.
    """

    def __init__(self, *, rcon_factory: Callable[[], Any], server_dir: Path,
                 out_path: Path, log_paths: list[Path] | None = None,
                 backup_dir: Path | None = None, level_name: Callable[[], str] | None = None,
                 read_nbt: Callable[[Path], dict] | None = None,
                 clock: Callable[[], float] = time.time):
        self.server_dir = Path(server_dir)
        self.data_dir = self.server_dir / DATA_DIR_NAME
        self.out_path = Path(out_path)
        self.backup_dir = Path(backup_dir) if backup_dir else None
        self.level_name = level_name or (lambda: "world")
        # mcmap.read_nbt_file, handed in: the panel loads its modules by path.
        self.read_nbt = read_nbt
        self._spawn_cache: dict[str, Any] | None = None
        self.clock = clock
        self.session = RconSession(rcon_factory)
        self.tail = LogTail(log_paths or [self.server_dir / "logs" / "latest.log"])
        self.journal = Journal(self.data_dir / "journal", clock)
        self.builds = BuildLog(self.data_dir / "builds.json", clock)
        self.feed: deque[dict[str, Any]] = deque(maxlen=FEED_SIZE)
        self.players: dict[str, dict[str, Any]] = {}
        self.sessions: dict[str, float] = {}
        self.missing: dict[str, int] = {}
        self.reachable = False
        self.max_players = 0
        self.world_time: dict[str, Any] | None = None
        self.weather: dict[str, Any] | None = None
        self.weather_rcon_refused_at = 0.0
        self.last_save: float | None = None
        self.last_backup: float | None = None
        self._backup_checked = 0.0
        self.next_poll = 0.0
        self.polled_at: float | None = None
        self._lock = threading.Lock()
        # The panel listens to every recorded event (and to a player entering
        # a named place, which is not written to the feed) and adds its own
        # small view to the snapshot; both stay None without it.
        self.on_event: Callable[[dict[str, Any]], None] | None = None
        self.extra: Callable[[], dict[str, Any]] | None = None
        # Who a chat line's nickname is (bare nickname -> player), learned
        # when a name could be tied to the one person it could be.
        self.nicknames: dict[str, str] = {}
        # Players `list` showed before the log said they joined: the feed
        # records them at once, and the log's own line (if it comes) is not
        # recorded twice. One still here after JOIN_GRACE means the log's
        # join lines are not being read — a script rewrote them, or the log
        # is somewhere the collector cannot see.
        self.joined_via_list: set[str] = set()
        self.unheard_joins: dict[str, float] = {}
        self.heard_at: float | None = None
        self.heard_player_at: float | None = None
        self.line_at: float | None = None
        self.near_of: dict[str, str | None] = {}
        state = _read_json(self.data_dir / "state.json", {})
        self.last_seen: dict[str, float] = {
            str(k): float(v) for k, v in (state.get("last_seen") or {}).items()
            if isinstance(v, (int, float))} if isinstance(state, dict) else {}
        self._seed_feed()

    # -- feed and journal ---------------------------------------------------
    def _seed_feed(self) -> None:
        now = self.clock()
        events: list[dict[str, Any]] = []
        for day in (Journal.day_of(now - 86400), Journal.day_of(now)):
            events.extend(e for e in self.journal.events(day) if e.get("kind") != "save")
        for ev in events[-FEED_SIZE:]:
            self.feed.appendleft(ev)

    def _save_state(self) -> None:
        recent = dict(sorted(self.last_seen.items(), key=lambda kv: kv[1], reverse=True)[:50])
        try:
            atomic_write_json(self.data_dir / "state.json", {"last_seen": recent})
        except OSError:
            # last_seen is a convenience; the journal holds the record, so a full disk costs only this.
            pass

    def record(self, event: dict[str, Any]) -> dict[str, Any]:
        """Add one event to the feed and today's journal."""
        event = {"t": int(event.get("t") or self.clock()), **{k: v for k, v in event.items() if k != "t"}}
        with self._lock:
            if event.get("kind") != "save":
                self.feed.appendleft(event)
        try:
            self.journal.add(event)
        except OSError:
            # The feed still has it; a journal that cannot be written loses a line, not the world.
            pass
        if self.on_event is not None:
            self.on_event(event)
        return event

    def _open(self, name: str, now: float) -> None:
        self.sessions.setdefault(name, now)
        self.missing.pop(name, None)
        self.last_seen[name] = now

    def _close(self, name: str, now: float) -> int | None:
        since = self.sessions.pop(name, None)
        self.players.pop(name, None)
        self.missing.pop(name, None)
        self.joined_via_list.discard(name)
        self.near_of.pop(name, None)
        self.last_seen[name] = now
        return int(now - since) if since else None

    # -- the log --------------------------------------------------------------
    def speaker(self, shown: str) -> str | None:
        """The player a chat line's name means, or None.

        A server script can show a nickname instead of the account name
        ("Dad" for DadMC). Who is playing is known from `list`, so: the
        player whose name it is (case and a Bedrock prefix ignored), a
        nickname this collector already tied to a player, a player whose
        name starts with it or contains it when only one does, and, with
        exactly one person on, that person. Anything else is None and the
        line keeps the name it showed — a companion matches it against the
        names it knows (BRUH Minecraft keeps no roster).
        """
        name = shown_name(shown)
        if not name:
            return None
        online = list(self.sessions)
        want = _bare(name)
        for p in online:
            if _bare(p) == want:
                return p
        tied = self.nicknames.get(want)
        if tied in online:
            return tied
        close = [p for p in online if want and (_bare(p).startswith(want) or want in _bare(p))]
        if len(close) == 1:
            return close[0]
        if len(online) == 1:
            return online[0]
        return None

    def _heard(self, now: float, kind: str) -> None:
        self.heard_at = now
        if kind in ("join", "chat", "leave", "death", "advancement"):
            self.heard_player_at = now

    def handle_line(self, line: str) -> dict[str, Any] | None:
        self.line_at = self.clock()
        known = (set(self.sessions) | set(self.players) | set(self.last_seen)
                 | set(self.nicknames))
        ev = parse_log_line(line, known)
        if ev is None:
            return None
        now = self.clock()
        self._heard(now, ev["kind"])
        if ev["kind"] == "chat":
            shown = ev["player"]
            who = self.speaker(shown)
            if who is not None:
                if _bare(who) != _bare(shown):
                    self.nicknames[_bare(shown)] = who
                    ev["shown"] = shown
                ev["player"] = who
            else:
                ev["player"], ev["shown"], ev["unmatched"] = None, shown, True
        if ev["kind"] == "join":
            self.unheard_joins.pop(ev["player"], None)
        if ev["kind"] == "join" and ev["player"] in self.joined_via_list:
            # `list` saw them first and the feed already says so.
            self.joined_via_list.discard(ev["player"])
            self._open(ev["player"], now)
            return None
        if ev["kind"] == "join":
            self._open(ev["player"], now)
            self.next_poll = 0.0       # ask where they are at once
            self._save_state()
        elif ev["kind"] == "leave":
            secs = self._close(ev["player"], now)
            if secs is not None:
                ev["seconds"] = secs
                ev["text"] = f"{ev['player']} left after {duration_words(secs)}"
            self._save_state()
        elif ev["kind"] == "save":
            self.last_save = now
        elif ev["kind"] == "server" and "stopping" in ev["text"]:
            for name in list(self.sessions):
                self._close(name, now)
            self.reachable = False
        return self.record(ev)

    def read_log(self) -> list[dict[str, Any]]:
        return [ev for line in self.tail.read() if (ev := self.handle_line(line))]

    # -- polling ----------------------------------------------------------------
    def poll(self) -> None:
        """Ask the server what it can say, over one connection."""
        now = self.clock()
        try:
            listed = parse_list(self.session.command("minecraft:list"))
        except Exception:  # noqa: BLE001 — a server that is down is a state
            listed = None
        if listed is None:
            self.session.close()
            self.reachable = False
            for name in list(self.sessions):
                self._close(name, now)
            self.players = {}
            self.polled_at = now
            return
        self.reachable = True
        self.max_players = listed["max"]
        online = listed["players"]
        # The first look after the panel starts finds people who joined
        # before it was watching: they are opened quietly, as always.
        first = self.polled_at is None
        for name in online:
            if name not in self.sessions:
                self._open(name, now)
                if first:
                    continue
                # On the list with no join line read: say so in the feed now
                # rather than never (a script's own join message is not the
                # vanilla line), and remember the log owes us that line.
                self.joined_via_list.add(name)
                self.unheard_joins[name] = now
                self.record({"kind": "join", "player": name, "text": f"{name} joined",
                             "via": "list"})
        # Gone from the list twice running and no leave line read: the log
        # missed it (a crash, a log we could not read). Close it quietly.
        for name in list(self.sessions):
            if name in online:
                self.missing.pop(name, None)
                continue
            self.missing[name] = self.missing.get(name, 0) + 1
            if self.missing[name] >= 2:
                secs = self._close(name, now)
                self.record({"kind": "leave", "player": name, "seconds": secs,
                             "text": f"{name} left" + (f" after {duration_words(secs)}" if secs else "")})
        self._poll_time(now)
        self._poll_weather(now)
        places = self.places()
        players = {}
        for name in online[:MAX_PLAYERS_DETAILED]:
            info = self._poll_player(name)
            info["since"] = int(self.sessions.get(name, now))
            info["near"] = nearest_place(info.get("pos"), info.get("dimension") or "", places)
            self._entered(name, info, now)
            players[name] = info
            self.last_seen[name] = now
        for name in online[MAX_PLAYERS_DETAILED:]:
            players[name] = {"name": name, "since": int(self.sessions.get(name, now))}
        self.players = players
        self.polled_at = now
        if not online:
            # Nobody to watch: give the connection back until somebody joins.
            self.session.close()

    def _entered(self, name: str, info: dict[str, Any], now: float) -> None:
        """A player walking into a named place: told to whoever listens
        (`on_event`), never written to the feed, which would fill with it."""
        place = info.get("near")
        was = self.near_of.get(name, "\0")
        self.near_of[name] = place
        if place and was != "\0" and place != was and self.on_event is not None:
            self.on_event({"t": int(now), "kind": "place", "player": name, "place": place,
                           "dimension": info.get("dimension") or "minecraft:overworld",
                           "text": f"{name} is at {place}"})

    def listening(self) -> dict[str, Any]:
        """Whether the server's log is being heard, for the panel's headline,
        the feed sensor and anything that reports on the world.

        Two things say it is not: somebody `list` shows came on and no join
        line for them was read within JOIN_GRACE (a script rewrote the join
        message, or the log is not the one being read), or the log has said
        nothing at all for LOG_SILENT while the server answers RCON (whose
        own polls write lines, so a silent log is one that is not read).
        """
        now = self.clock()
        if not self.reachable or not self.sessions:
            return {"ok": True, "why": ""}
        missed = sorted(n for n, at in self.unheard_joins.items()
                        if n in self.sessions and now - at >= JOIN_GRACE)
        if self.line_at is None or now - self.line_at >= LOG_SILENT:
            return {"ok": False, "code": "log_silent", "since": int(self.line_at or 0) or None,
                    "why": ("The panel cannot read the server's log, so chat, joins and "
                            "deaths are missing from the feed while players are on.")}
        if missed:
            return {"ok": False, "code": "joins_unheard", "players": missed[:6],
                    "why": (f"{', '.join(missed[:3])} came on without the usual join line in "
                            "the server's log. A plugin or script probably changed the join "
                            "or chat messages, so the feed may miss chat. Chat is still read "
                            "in the common rewritten shapes (\"Name: text\").")}
        return {"ok": True, "why": ""}

    def _query_time(self, what: str) -> int | None:
        """`time query <what>`, asked the ways a server may want it: the
        namespaced command first (EssentialsX overrides the bare one), then
        the bare one for a server whose dispatcher refuses the namespace
        over RCON. The first answer that reads as a number wins."""
        for cmd in (f"minecraft:time query {what}", f"time query {what}"):
            try:
                value = parse_time(self.session.command(cmd))
            except Exception:  # noqa: BLE001 — a server that went away
                return None
            if value is not None:
                return value
        return None

    def _time_from_save(self) -> tuple[int | None, int | None]:
        """(daytime, day) as of the last save, from level.dat's DayTime."""
        if self.read_nbt is None:
            return None, None
        level = self.server_dir / (self.level_name() or "world") / "level.dat"
        try:
            data = self.read_nbt(level).get("Data", {})
            ticks = int(data.get("DayTime"))
        except Exception:  # noqa: BLE001 — no save, or a format we cannot read
            return None, None
        return ticks % 24000, ticks // 24000

    def _poll_time(self, now: float) -> None:
        daytime = self._query_time("daytime")
        day = self._query_time("day")
        source = "server"
        if daytime is None:
            saved_time, saved_day = self._time_from_save()
            if saved_time is None:
                return
            daytime, source = saved_time, "save"
            day = day if day is not None else saved_day
        elif day is None:
            day = self._time_from_save()[1]
        hour, minute = clock_of(daytime)
        self.world_time = {"daytime": daytime, "day": day, "hour": hour,
                           "clock": f"{hour:02d}:{minute:02d}", "phase": phase_of(daytime),
                           "as_of": int(now), "source": source}

    def _poll_weather(self, now: float) -> None:
        state = None
        if now - self.weather_rcon_refused_at > WEATHER_RETRY:
            state = self._weather_from_server()
            if state is None:
                # Inline predicates are 1.20.5+; an older server says no.
                self.weather_rcon_refused_at = now
            else:
                self.weather = {"state": state, "source": "server", "as_of": int(now)}
                return
        self.weather = self._weather_from_save() or self.weather

    def _weather_from_server(self) -> str | None:
        """clear, rain or thunder as the server says it now; None when it cannot say."""
        try:
            thunder = parse_test(self.session.command(
                'minecraft:execute if predicate {condition:"minecraft:weather_check",thundering:true}'))
            rain = parse_test(self.session.command(
                'minecraft:execute if predicate {condition:"minecraft:weather_check",raining:true}'))
        except Exception:  # noqa: BLE001
            return None
        if thunder is None or rain is None:
            return None
        return "thunder" if thunder else "rain" if rain else "clear"

    def _weather_from_save(self) -> dict[str, Any] | None:
        """The weather as of the last save, from level.dat."""
        level = self.server_dir / (self.level_name() or "world") / "level.dat"
        if self.read_nbt is None:
            return None
        try:
            data = self.read_nbt(level).get("Data", {})
            mtime = level.stat().st_mtime
        except Exception:  # noqa: BLE001
            return None
        state = "thunder" if data.get("thundering") else "rain" if data.get("raining") else "clear"
        return {"state": state, "source": "save", "as_of": int(mtime)}

    def _poll_player(self, name: str) -> dict[str, Any]:
        who = quote_name(name)
        info: dict[str, Any] = {"name": name}

        def ask(path: str) -> str | None:
            try:
                return data_value(self.session.command(f"minecraft:data get entity {who} {path}"))
            except Exception:  # noqa: BLE001
                return None

        pos = snbt_pos(ask("Pos"))
        if pos:
            info["pos"] = [round(c, 1) for c in pos]
        dim = snbt_string(ask("Dimension"))
        if dim:
            info["dimension"] = dim
        health = snbt_number(ask("Health"))
        if health is not None:
            info["health"] = round(health, 1)
        food = snbt_number(ask("foodLevel"))
        if food is not None:
            info["food"] = int(food)
        mode = snbt_number(ask("playerGameType"))
        if mode is not None:
            info["gamemode"] = GAMEMODES.get(int(mode), str(int(mode)))
        return info

    def places(self) -> list[dict[str, Any]]:
        """Named places: the hand-kept list, finished builds, and spawn."""
        out: list[dict[str, Any]] = []
        kept = _read_json(self.data_dir / "places.json", [])
        if isinstance(kept, dict):
            kept = kept.get("places") or []
        out.extend(p for p in kept if isinstance(p, dict) and p.get("name"))
        for job in self.builds.list(limit=40):
            b = job.get("bounds")
            if b and job.get("status") in ("done", "building"):
                out.append({"name": job.get("title"), "dimension": b.get("dimension"),
                            "x": (b["x1"] + b["x2"]) / 2, "z": (b["z1"] + b["z2"]) / 2,
                            "radius": max(32, abs(b["x2"] - b["x1"]), abs(b["z2"] - b["z1"]))})
        spawn = self._spawn()
        if spawn:
            out.append(spawn)
        return out

    def _spawn(self) -> dict[str, Any] | None:
        if self._spawn_cache is not None:
            return self._spawn_cache or None
        if self.read_nbt is None:
            return None
        level = self.server_dir / (self.level_name() or "world") / "level.dat"
        try:
            data = self.read_nbt(level).get("Data", {})
            spawn = data.get("spawn") if isinstance(data.get("spawn"), dict) else None
            if spawn and isinstance(spawn.get("pos"), (list, tuple)):
                x, _, z = spawn["pos"][:3]
            else:
                x, z = data["SpawnX"], data["SpawnZ"]
            self._spawn_cache = {"name": "spawn", "dimension": "minecraft:overworld",
                                 "x": x, "z": z, "radius": 64}
        except Exception:  # noqa: BLE001
            self._spawn_cache = {}
        return self._spawn_cache or None

    # -- saves and backups ----------------------------------------------------
    def _check_saves(self, now: float) -> None:
        level = self.server_dir / (self.level_name() or "world") / "level.dat"
        try:
            m = level.stat().st_mtime
            if not self.last_save or m > self.last_save:
                self.last_save = m
        except OSError:
            # No level.dat yet (a world not generated): no save to report.
            pass
        if self.backup_dir is None or now - self._backup_checked < 60:
            return
        self._backup_checked = now
        newest = self.last_backup or 0.0
        reflog = self.backup_dir / "git" / ".git" / "logs" / "HEAD"
        try:
            last = reflog.read_text(encoding="utf-8", errors="replace").rstrip("\n").splitlines()[-1]
            m = re.search(r"> (\d{9,11}) [+-]\d{4}\t", last)
            if m:
                newest = max(newest, float(m.group(1)))
        except (OSError, IndexError):
            # No git backups, or an empty reflog: the archives below may still say.
            pass
        try:
            for p in (self.backup_dir / "archives").glob("*.tar.gz"):
                newest = max(newest, p.stat().st_mtime)
        except OSError:
            # No archives folder: git above was the only place backups could be.
            pass
        self.last_backup = newest or None

    # -- one beat ------------------------------------------------------------
    def step(self) -> bool:
        """Read the log; poll if it is time. True when the snapshot moved."""
        now = self.clock()
        moved = bool(self.read_log())
        if now >= self.next_poll:
            self.poll()
            self._check_saves(now)
            self.next_poll = now + (BUSY_INTERVAL if self.players or self.sessions else IDLE_INTERVAL)
            moved = True
        if moved:
            self.write()
        return moved

    def build_changed(self, job: dict[str, Any], was: str | None) -> None:
        """A job's status moved: say so in the feed."""
        status = job.get("status")
        if status == was:
            self.write()
            return
        by = job.get("by") or "brAIn"
        title = job.get("title") or "a build"
        text = {"building": f"{by} started building {title}",
                "done": f"{by} finished building {title}",
                "failed": f"{by} could not finish {title}",
                "queued": f"{by} plans to build {title}"}.get(status)
        if text:
            self.record({"kind": "build", "player": by, "job": job.get("id"), "text": text})
        self.write()

    def snapshot(self) -> dict[str, Any]:
        now = self.clock()
        players = []
        for name, p in sorted(self.players.items()):
            pos = p.get("pos")
            players.append({
                "name": name, "dimension": p.get("dimension"),
                "x": round(pos[0]) if pos else None, "y": round(pos[1]) if pos else None,
                "z": round(pos[2]) if pos else None, "near": p.get("near"),
                "gamemode": p.get("gamemode"), "health": p.get("health"),
                "food": p.get("food"), "since": p.get("since")})
        recent = [job_brief(j) for j in self.builds.list(limit=10)
                  if j.get("status") in ("done", "failed")][:5]
        with self._lock:
            feed = list(self.feed)
        last_seen = dict(sorted(self.last_seen.items(), key=lambda kv: kv[1], reverse=True)[:20])
        return {
            "updated_at": int(now),
            "polled_at": int(self.polled_at) if self.polled_at else None,
            "reachable": self.reachable,
            "world": self.level_name(),
            "online": len(players) if self.reachable else 0,
            "max": self.max_players,
            "players": players if self.reachable else [],
            "time": self.world_time if self.reachable else None,
            "weather": self.weather,
            "last_seen": {k: int(v) for k, v in last_seen.items()},
            "feed": feed,
            "listening": self.listening(),
            "last_save": int(self.last_save) if self.last_save else None,
            "last_backup": int(self.last_backup) if self.last_backup else None,
            "builds": {"current": job_brief(self.builds.current()), "recent": recent,
                       "queued": len(self.builds.list(status="queued"))},
            **(self._extra()),
        }

    def _extra(self) -> dict[str, Any]:
        if self.extra is None:
            return {}
        try:
            return self.extra()
        except Exception:  # noqa: BLE001 — the world view never fails for the companion's part
            return {}

    def write(self) -> dict[str, Any]:
        snap = self.snapshot()
        try:
            atomic_write_json(self.out_path, snap)
        except OSError:
            # The next beat writes again; the panel's /api/world answers from memory meanwhile.
            pass
        return snap

    def close(self) -> None:
        self.session.close()


def duration_words(seconds: int | None) -> str:
    if not seconds or seconds < 60:
        return "under a minute"
    m = seconds // 60
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    return f"{h} h {m} min" if m else f"{h} h"


__all__ = ["WorldCollector", "BuildLog", "BuildError", "Journal", "LogTail", "RconSession",
           "parse_log_line", "parse_list", "parse_time", "parse_test", "quote_name",
           "data_value", "snbt_pos", "snbt_number", "snbt_string", "phase_of", "clock_of",
           "nearest_place", "job_brief", "clean_bounds", "duration_words", "short_dimension"]
