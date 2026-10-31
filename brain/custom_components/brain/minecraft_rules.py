"""brAIn's Minecraft faculty: the rules, with no Home Assistant in them.

BRUH Minecraft reports what happens in the game as plain events and carries
out what it is asked (its DOCS, "The companion contract"). Everything that
DECIDES is brAIn's, and the decisions that are rules rather than judgement
live here so the three places that need them read one copy:

* the integration's listener (`minecraft.py`), which hears the events and
  greets, answers and remembers;
* the MCP server (`ha_mcp_server.minecraft_world`), which a turn acts
  through — and which must hold the same privacy and bedtime rules;
* the panel (`panel/minecraft_companion.py`), which owns ⚙ › Minecraft and
  is the one writer of the settings.

It imports nothing outside the standard library and no sibling module, so
the MCP server and the panel load it by path from `../custom_components/
brain/` (true in the repository and in the image, where both sit in /opt).

The files, all under `/config/.brain/minecraft/`:

* `settings.json` — ⚙ › Minecraft (the panel writes it): on/off, the family
  list and roles, bedtime, the budgets (0 = unlimited), the models.
* `handover.json` — what BRUH Minecraft's own engine knew up to 1.17.7,
  fetched once by the listener; read as the settings until the panel has
  saved its own.
* `state.json` — the listener's: today's counts, paused, bedtime said.
* `people.json` — what the companion remembers about each person.
* `talks.json` — what was said to it and what it answered.
* `approvals.json` — the panel's: house changes a trusted grown-up asked
  for in the game that waited for a person's approval, and how each ended.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import time
from typing import Any

SUBDIR = "minecraft"
SETTINGS = "settings.json"
HANDOVER = "handover.json"
STATE = "state.json"
PEOPLE = "people.json"
TALKS = "talks.json"
APPROVALS = "approvals.json"

ROLES = ("child", "reader")
DEFAULT_NAME = "brAIn"
NAME_MAX = 16
DEFAULT_COLOUR = "light_purple"
# Minecraft's sixteen chat colours: what BRUH Minecraft's services take.
COLOURS = ("black", "dark_blue", "dark_green", "dark_aqua", "dark_red", "dark_purple", "gold",
           "gray", "dark_gray", "blue", "green", "aqua", "red", "light_purple", "yellow",
           "white")
EFFORTS = ("low", "medium", "high", "xhigh", "max")
# Budgets: how many of each a day (`per_session`: proactive acts for one
# player in one sitting). 0 is unlimited — the default, the owner's call
# ("get rid of the limits") — and every one stays settable.
BUDGETS = ("daily_turns", "daily_actions", "per_session")
BUDGET_MAX = 100000

GREET_COOLDOWN = 20 * 60          # a child greeted again after this
GREET_ADULT_COOLDOWN = 60 * 60
GREETING_SECONDS = 25
ADULT_GREETING_SECONDS = 8
VISIT_SECONDS = 15
TALK_SPACING = 5                  # seconds between one person's requests
COMMAND_SPACING = 2
TALK_TIMEOUT = 90
BRAIN_RETRY = 300
REPLY_LINES = 4
REPLY_LINE_CHARS = 160
PROMPT_CHARS = 6000
FAVOURITE_VISITS = 3
MAX_ANSWERS = 50
MAX_ASKED = 12
MAX_NOTES = 12
MAX_TALKS = 60
MAX_PEOPLE = 20
BUILD_WORDS = re.compile(
    r"\b(build|built|make|place|put|bridge|house|tower|wall|castle|farm|fence|garden|"
    r"door|roof|stairs?|path|pool|hut|shelter|statue)\b", re.I)

CANNED = {
    "greet": "Hello! Good to see you.",
    "thinking": "Hmm…",
    "down": "I can't think that one through right now. Try again in a bit.",
    "budget": "I've talked a lot today — let's pick this up tomorrow.",
    "timeout": "That's taking me too long. Ask me again in a moment?",
    "busy": "Still thinking about your last one.",
    "spacing": "One at a time — give me a moment.",
    "paused": "I'm paused. Say “{name} start” when you want me back.",
    "untrusted": ("I can't take commands here: {why}, so anybody could use your name. "
                  "Ask me in brAIn instead."),
    "empty": "Yes? Say “{name} help” to see what I can do.",
    "error": "Something went wrong on my side. Try again?",
    "goodnight": "Goodnight! See you tomorrow.",
    "kept": "I'd better not say that one here.",
    # What a grown-up without "Can ask for anything" hears for a request
    # outside the game: there is nothing to approve, so it says who can
    # change that and where — never "approve it in brAIn".
    "outside": ("I can't do that from the game. A parent can turn on 'Can ask for anything' "
                "for you in brAIn › ⚙ › Minecraft."),
}
# A grown-up the family trusts ("Can ask for anything", ⚙ › Minecraft) asks
# for a house change while "Let brAIn act without asking" is off: the change
# waits as a question in brAIn › Today (and on the phone, where brAIn's
# notifications have a phone), and the game hears where it went, then how
# it ended. The panel files it and says the ending; the words are here so
# the prompt, the gate and the panel say the same sentence.
APPROVAL_LINES = {
    "sent_phone": "I've sent that to your phone and to brAIn › Today to approve.",
    "sent_today": "I've put that in brAIn › Today for you to approve.",
    "done": "Done: {what}.",
    "failed": "That was approved, but it didn't work: {what}.",
    "denied": "That wasn't approved in brAIn: {what}.",
    "expired": "Nobody approved that in brAIn in time, so I didn't do it: {what}.",
}
APPROVAL_TTL = 60 * 60            # an approval nobody answered expires after this
HELP_LINES = (
    "{n} stop · {n} start — pause me and bring me back",
    "{n} undo — take back the last thing I did",
    "{n} status — what I'm doing and who is here",
    "{n} come here · {n} help — or just ask me anything",
)
TALK_SCHEMA = {
    "type": "object",
    "properties": {
        "reply": {"type": "string", "maxLength": 700},
        "learned": {"type": "array", "items": {"type": "string", "maxLength": 200},
                    "maxItems": 2},
    },
    "required": ["reply"],
}
_BUILTINS = {"stop": "stop", "pause": "stop", "stop it": "stop", "be quiet": "stop",
             "start": "start", "resume": "start", "unpause": "start", "go": "start",
             "undo": "undo", "undo that": "undo", "status": "status",
             "help": "help", "commands": "help", "come here": "come", "come": "come",
             "here": "come"}
_COLOUR_CODE = re.compile(r"§.")


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------
def folder(shared_dir: str) -> str:
    return os.path.join(shared_dir, SUBDIR)


def read_json(path: str, default: Any) -> Any:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return default
    return data if isinstance(data, type(default)) else default


def _umask() -> int:
    current = os.umask(0o022)
    os.umask(current)
    return current


def write_json(path: str, data: Any) -> None:
    """tmp + rename in the same folder, with a unique scratch name: two
    writers never share one, and a reader never sees half a file. The mode
    is the panel's `atomic_write` rule: an existing file keeps the mode it
    had, a new one gets what the process umask allows (what a plain write
    would have made), never a mode chosen here."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        mode = os.stat(path).st_mode & 0o777
    except OSError:
        mode = 0o666 & ~_umask()
    fd, tmp = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            # Already gone; the write's own error is the one that matters.
            pass
        raise


def day_of(t: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(t))


# ---------------------------------------------------------------------------
# Names
# ---------------------------------------------------------------------------
def bare(name: Any) -> str:
    """A name as people mean it: no Bedrock prefix, no case."""
    return re.sub(r"^[.*]", "", str(name or "").strip()).lower()


def game_name(value: Any, default: str = DEFAULT_NAME) -> str:
    """A name the companion can go by in the game (BRUH Minecraft takes up
    to 16 letters, digits, spaces, apostrophes and dashes)."""
    raw = " ".join(re.sub(r"[^\w '\-]", "", str(value or "")).split())[:NAME_MAX].strip()
    return raw or default


def persona_name(shared_dir: str) -> str:
    """The house's name for its assistant (⚙ › Personality), when
    Personality is on and a name is set; else "brAIn". The companion goes by
    it in the game, and it is the chat's wake word."""
    features = read_json(os.path.join(shared_dir, "features.json"), {})
    if features.get("personality") is False:
        return DEFAULT_NAME
    data = read_json(os.path.join(shared_dir, "personality.json"), {})
    return game_name(data.get("name"))


def wake_words(name: str) -> tuple[str, ...]:
    """What starts a chat line meant for the companion: its name, and
    "brain" too, which is always the product's name."""
    return tuple(dict.fromkeys(n for n in (str(name or "").strip(), "brain") if n))


def addressed(said: Any, names: Any) -> str | None:
    """The rest of a chat line spoken to the companion, or None if it is not.

    The name, "name," "@name", "hey name" at the start of the line; "names"
    is not the name, and a line that only mentions it later is not addressed.
    """
    text = " ".join(str(said or "").split())
    low = text.lower()
    wanted = sorted({str(n).strip().lower() for n in names if str(n or "").strip()},
                    key=len, reverse=True)
    for n in wanted:
        for pre in (f"hey {n}", f"hi {n}", f"ok {n}", f"@{n}", n):
            if not low.startswith(pre):
                continue
            rest = text[len(pre):]
            if rest and (rest[0].isalnum() or rest[0] == "_"):
                continue
            return rest.lstrip(" ,:;!.?-").strip()
    return None


def builtin(command: Any, name: str = "") -> str | None:
    """stop, start, undo, status, come or help — or None for a turn."""
    key = re.sub(r"[^a-z ]", "", str(command or "").lower())
    drop = {"please", "now", bare(name), "brain"}
    key = " ".join(w for w in key.split() if w not in drop)
    return _BUILTINS.get(key)


def split_reply(text: Any, width: int = REPLY_LINE_CHARS, lines: int = REPLY_LINES) -> list[str]:
    """A reply as a few chat lines: plain text, wrapped, capped with "…"."""
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


def untrusted(text: Any, cap: int = 300) -> dict[str, Any]:
    """Words from the game, in the shape brAIn reads as data, never as an
    instruction (the MCP server's own `{"untrusted": true, "text": …}`)."""
    return {"untrusted": True, "text": " ".join(str(text or "").split())[:cap]}


def bedtime_rule(text: Any) -> tuple[str, str] | None:
    """`input_boolean.bedtime` (bedtime while on) or `binary_sensor.door=off`."""
    text = str(text or "").strip()
    if not text:
        return None
    entity, _, state = text.partition("=")
    entity, state = entity.strip(), (state.strip() or "on")
    if not re.fullmatch(r"[a-z_]+\.[a-z0-9_]+", entity) or len(state) > 40:
        return None
    return entity, state


def is_bedtime(rule: tuple[str, str] | None, state: str | None) -> bool | None:
    """True at bedtime, False otherwise, None when the switch cannot be read."""
    if rule is None:
        return False
    if state in (None, "unknown", "unavailable"):
        return None
    return state == rule[1]


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
class RulesError(ValueError):
    """A setting that cannot be kept as given; the message says why."""


def clean_people(people: Any) -> list[dict[str, Any]]:
    """The family list: each person, their role, their in-game names, the
    nicknames a server script may show for them in chat, and — for a
    grown-up only — whether they "can ask for anything" (`trusted`)."""
    if not isinstance(people, list):
        raise RulesError("The family is a list of people.")
    out, seen = [], set()
    for p in people[:MAX_PEOPLE]:
        if not isinstance(p, dict):
            raise RulesError("Each person is an object.")
        person = " ".join(str(p.get("person") or "").split())[:40]
        if not person:
            raise RulesError("Each person needs a name.")
        role = str(p.get("role") or "child").strip().lower()
        if role not in ROLES:
            raise RulesError("A role is child or reader (a grown-up).")
        names = []
        players = p.get("players") or []
        if isinstance(players, str):
            players = [n for n in re.split(r"[,\s]+", players) if n]
        for n in players[:6]:
            n = str(n).strip()
            if not re.fullmatch(r"[A-Za-z0-9_.*]{1,17}", n):
                raise RulesError(f"{n!r} is not a Minecraft name.")
            if bare(n) in seen:
                raise RulesError(f"{n} is listed twice.")
            seen.add(bare(n))
            names.append(n)
        if not names:
            raise RulesError(f"{person} needs at least one in-game name.")
        nicks = p.get("nicknames") or []
        if isinstance(nicks, str):
            nicks = [n for n in nicks.split(",") if n.strip()]
        nicknames = [" ".join(str(n).split())[:40] for n in nicks[:6] if str(n).strip()]
        # "Can ask for anything": a grown-up's alone. A child's row with the
        # flag set (a hand-edited file, an old save) is read as off, so the
        # one place every reader takes the family from cannot hand a child
        # the house.
        trusted = role == "reader" and p.get("trusted") is True
        out.append({"person": person, "role": role, "players": names, "nicknames": nicknames,
                    "trusted": trusted})
    return out


def _model(value: Any) -> str:
    text = str(value or "").strip()
    return text[:100] if re.fullmatch(r"[A-Za-z0-9._:\[\]\-]{0,100}", text) else ""


def _effort(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in EFFORTS else ""


def _budget(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return max(0, min(BUDGET_MAX, n))


def clean_settings(raw: Any, strict: bool = False) -> dict[str, Any]:
    """Settings as the listener reads them. `strict` raises on a family list
    that cannot be kept (the panel's save); otherwise a bad one reads as
    nobody, which plays with no one rather than with the wrong people."""
    raw = raw if isinstance(raw, dict) else {}
    try:
        people = clean_people(raw.get("people") or [])
    except RulesError:
        if strict:
            raise
        people = []
    bedtime = str(raw.get("bedtime_entity") or "").strip()[:160]
    if bedtime and bedtime_rule(bedtime) is None:
        if strict:
            raise RulesError("The bedtime switch is an entity like input_boolean.kids_bedtime, "
                             "or an entity and a state like binary_sensor.boys_door=off.")
        bedtime = ""
    budgets = raw.get("budgets") if isinstance(raw.get("budgets"), dict) else {}
    models = raw.get("models") if isinstance(raw.get("models"), dict) else {}
    out = {
        "enabled": raw.get("enabled") is True,
        "people": people,
        "bedtime_entity": bedtime,
        "budgets": {k: _budget(budgets.get(k)) for k in BUDGETS},
        "chat_model": _model(raw.get("chat_model")),
        "chat_effort": _effort(raw.get("chat_effort")),
        "build_model": _model(raw.get("build_model")),
        "build_effort": _effort(raw.get("build_effort")),
        "greet": raw.get("greet") is not False,
        "colour": (str(raw.get("colour")) if str(raw.get("colour") or "") in COLOURS
                   else DEFAULT_COLOUR),
        # What the panel resolved "Default" to (model_plan), so the listener
        # needs no copy of the plan: {"chat": {model, effort}, "build": {...}}.
        "models": {k: {"model": _model((models.get(k) or {}).get("model")),
                       "effort": _effort((models.get(k) or {}).get("effort"))}
                   for k in ("chat", "build")},
        "saved_at": raw.get("saved_at"),
    }
    return out


def from_handover(handover: Any) -> dict[str, Any]:
    """What BRUH Minecraft's own engine (up to 1.17.7) knew, as settings:
    its family list, switch and bedtime. Its fixed limits are not carried:
    the owner's budgets start unlimited."""
    h = handover if isinstance(handover, dict) else {}
    old = h.get("settings") if isinstance(h.get("settings"), dict) else {}
    family = h.get("family") if isinstance(h.get("family"), list) else []
    raw = {"enabled": old.get("enabled") is True, "people": family,
           "bedtime_entity": old.get("bedtime_entity") or ""}
    return clean_settings(raw)


def effective_settings(shared_dir: str) -> dict[str, Any]:
    """settings.json, or — until the panel has saved one — the handover."""
    base = folder(shared_dir)
    raw = read_json(os.path.join(base, SETTINGS), {})
    if raw.get("saved_at") or "people" in raw:
        return clean_settings(raw)
    handover = read_json(os.path.join(base, HANDOVER), {})
    if handover:
        merged = from_handover(handover)
        merged.update({k: v for k, v in clean_settings(raw).items()
                       if k in ("models", "chat_model", "chat_effort", "build_model",
                                "build_effort", "budgets", "colour", "greet")})
        return merged
    return clean_settings(raw)


def left(limit: int, used: int) -> float:
    """What is left of a budget: infinity when the limit is 0 (unlimited)."""
    return float("inf") if not limit else max(0, int(limit) - int(used))


# ---------------------------------------------------------------------------
# Who is who
# ---------------------------------------------------------------------------
class Roster:
    def __init__(self, people: list[dict[str, Any]]):
        self.people = list(people or [])

    def who(self, player: Any, shown: Any = None) -> dict[str, Any]:
        """The person a player is. A chat line may show a nickname a server
        script set (#588) instead of the account name, so `shown` is matched
        too: against each person's in-game names, the nicknames listed for
        them, and their own name."""
        for name in (player, shown):
            want = bare(name)
            if not want:
                continue
            for p in self.people:
                keys = ([bare(n) for n in p.get("players") or []]
                        + [bare(n) for n in p.get("nicknames") or []] + [bare(p["person"])])
                if want in keys:
                    role = p.get("role") or "child"
                    return {"person": p["person"], "role": role,
                            "player": player or (p.get("players") or [None])[0],
                            "trusted": role == "reader" and p.get("trusted") is True}
        return {"person": str(player or shown or "?"), "role": "guest", "player": player,
                "trusted": False}

    def player_name(self, target: Any) -> str | None:
        """A person's (or a player's) Minecraft name: the first one listed,
        or the name itself when it is a player's."""
        t = bare(target)
        for p in self.people:
            names = p.get("players") or []
            if bare(p["person"]) == t and names:
                return names[0]
            for n in names:
                if bare(n) == t:
                    return n
        return None

    def children(self) -> list[dict[str, Any]]:
        return [p for p in self.people if p.get("role", "child") == "child"]

    def players_of(self, target: Any, online: list[str]) -> list[str]:
        """The online players a person's or a player's name means."""
        t = bare(target)
        for p in self.people:
            if bare(p["person"]) == t or t in {bare(n) for n in p.get("players") or []}:
                names = {bare(n) for n in p.get("players") or []}
                return [o for o in online if bare(o) in names]
        return [o for o in online if bare(o) == t]

    def names_another_child(self, player: str, text: Any) -> bool:
        """True when `text`, said to `player` (a child), names another child.
        A grown-up may hear about anybody in the family."""
        me = self.who(player)
        if me["role"] != "child":
            return False
        lower = str(text or "").lower()
        for p in self.children():
            if p["person"] == me["person"]:
                continue
            names = ([p["person"]] + [bare(n) for n in p.get("players") or []]
                     + list(p.get("nicknames") or []))
            if any(n and re.search(rf"(?<![a-z0-9]){re.escape(str(n).lower())}(?![a-z0-9])", lower)
                   for n in names):
                return True
        return False


# ---------------------------------------------------------------------------
# Memory, per person
# ---------------------------------------------------------------------------
def _record(mem: dict, who: dict, now: float) -> dict:
    rec = mem.get(who["person"]) or {
        "person": who["person"], "role": who.get("role"), "players": [],
        "sessions": 0, "seconds": 0, "first_seen": int(now),
        "places": {}, "likes": {}, "dislikes": {}, "answers": [], "moments": {}}
    rec["role"] = who.get("role") or rec.get("role")
    if who.get("player") and who["player"] not in rec.setdefault("players", []):
        rec["players"].append(who["player"])
    rec["last_seen"] = int(now)
    mem[who["person"]] = rec
    return rec


def remember(mem: dict, who: dict, kind: str, now: float, **data) -> dict:
    """One thing to remember about a person, onto `mem` (people.json's dict)."""
    rec = _record(mem, who, now)
    if kind == "join":
        rec["sessions"] = int(rec.get("sessions") or 0) + 1
    elif kind == "leave":
        rec["seconds"] = int(rec.get("seconds") or 0) + int(data.get("seconds") or 0)
    elif kind == "place" and data.get("place"):
        places = rec.setdefault("places", {})
        places[data["place"]] = places.get(data["place"], 0) + 1
    elif kind in ("death", "advancement"):
        m = rec.setdefault("moments", {})
        m[kind] = m.get(kind, 0) + 1
    elif kind == "answer":
        label = str(data.get("answer") or "?")[:40]
        likes = rec.setdefault("likes", {})
        likes[label] = likes.get(label, 0) + 1
        other = str(data.get("other") or "")[:40]
        if other and other not in ("yes", "no"):
            dislikes = rec.setdefault("dislikes", {})
            dislikes[other] = dislikes.get(other, 0) + 1
        answers = rec.setdefault("answers", [])
        answers.append({"t": int(now), "question": str(data.get("question") or "")[:200],
                        "answer": label})
        del answers[:-MAX_ANSWERS]
    elif kind == "asked":
        asked = rec.setdefault("asked", [])
        asked.append({"t": int(now), "text": " ".join(str(data.get("text") or "").split())[:120]})
        del asked[:-MAX_ASKED]
    elif kind == "noted":
        notes = [" ".join(str(n).split())[:140] for n in (data.get("notes") or [])
                 if isinstance(n, str) and n.strip()][:3]
        kept = rec.setdefault("notes", [])
        kept.extend({"t": int(now), "text": n} for n in notes)
        del kept[:-MAX_NOTES]
    return rec


def favourites(rec: dict | None, top: int = 3) -> list[str]:
    places = (rec or {}).get("places") or {}
    ranked = sorted(places.items(), key=lambda kv: kv[1], reverse=True)
    return [name for name, n in ranked[:top] if n >= FAVOURITE_VISITS]


def from_legacy_memory(memory: Any) -> dict:
    """The old engine's people.json, kept as it was (same record shape)."""
    if not isinstance(memory, dict):
        return {}
    return {str(k)[:40]: v for k, v in memory.items() if isinstance(v, dict)}


def learned_facts(memory: dict[str, Any], name: str = DEFAULT_NAME,
                  limit: int = 40) -> list[dict[str, Any]]:
    """What the companion learned about each person, as short fixed-word
    lines for brAIn's facts store (one per person and key). A child's pad
    answer is a label, a grown-up's request is quoted as theirs, and nothing
    is a sentence a model wrote freely except brAIn's own notes, written
    from a turn told to treat the chat as data."""
    out: list[dict[str, Any]] = []
    for person, rec in sorted((memory or {}).items()):
        if not isinstance(rec, dict) or rec.get("role") == "guest":
            continue
        who = str(person)[:40]
        likes = sorted((rec.get("likes") or {}).items(), key=lambda kv: kv[1], reverse=True)[:3]
        if likes:
            out.append({"person": who, "key": "likes", "text": (
                f"In Minecraft, when {name} asked, {who} chose "
                + ", ".join(f"{k} ({n} time{'s' if n != 1 else ''})" for k, n in likes) + ".")})
        answers = rec.get("answers") or []
        if answers:
            a = answers[-1]
            out.append({"person": who, "key": "last_answer", "text": (
                f"In Minecraft, {who} last answered {name}'s question "
                f"“{str(a.get('question') or '')[:100]}” with {str(a.get('answer'))[:40]}.")})
        fav = favourites(rec)
        if fav:
            out.append({"person": who, "key": "places",
                        "text": f"In Minecraft, {who} keeps going back to {', '.join(fav)}."})
        asked = rec.get("asked") or []
        if asked:
            said = "; ".join(f"“{str(x.get('text') or '')[:80]}”" for x in asked[-3:])
            out.append({"person": who, "key": "asked",
                        "text": f"In Minecraft, {who} recently asked {name}: {said}."})
        notes = rec.get("notes") or []
        if notes:
            out.append({"person": who, "key": "notes", "text": (
                f"In Minecraft, {name} noticed about {who}: "
                + " ".join(str(n.get("text") or "") for n in notes[-2:])[:280])})
        sessions, secs = int(rec.get("sessions") or 0), int(rec.get("seconds") or 0)
        if sessions:
            hours = round(secs / 3600, 1)
            out.append({"person": who, "key": "play", "text": (
                f"In Minecraft, {who} has played {sessions} session{'s' if sessions != 1 else ''}"
                + (f", about {hours:g} hours in all." if hours >= 0.1 else "."))})
    return out[:limit]


__all__ = ["bare", "Roster", "RulesError", "addressed", "builtin", "split_reply", "untrusted",
           "bedtime_rule", "is_bedtime", "clean_settings", "clean_people", "effective_settings",
           "from_handover", "from_legacy_memory", "left", "persona_name", "game_name",
           "wake_words", "remember", "favourites", "learned_facts", "read_json", "write_json"]
