"""Who brAIn is in this house: a name, a persona, and how it has grown.

A household's chosen personality used to live in Morph's own code — a copy
of a frontend module under `/config/morph/frontend/personality.js` holding
`PERSONA` and `GROWTH` — and it was shown only in Morph's Settings. Not
everybody who uses brAIn uses Morph, and everybody who uses Morph uses
brAIn, so the personality is brAIn's: one JSON file in brAIn's own config,
read by the chat, the terminal, the generated `/config/CLAUDE.md` and the
voice prompt, and served at `GET /api/personality` for Morph to read.

    /config/.brain/personality.json
    {"name": "…", "persona": "…",
     "growth": [{"date": "YYYY-MM-DD", "at": 1700000000, "text": "…"}],
     "updated_at": 1700000000}

Four rules. **Reading never raises**: an absent, unreadable or malformed
file is "no personality set", which changes nothing anywhere. **Everything
is capped** (the name, the persona, each growth entry and the number of
them), because what is here is handed to every chat turn. **The store never
creates its own directory** (`facts_store.writable`'s rule): run.sh makes
`/config/.brain`, so a missing parent is a dev checkout or a test. And
**Morph's copy is read once and never written**: `migrate_from_morph` runs
at panel startup only while brAIn has no file of its own.

This module is also a small CLI, because two readers cannot import the
panel the ordinary way: `ha-context-gen.sh` runs `personality.py section`
and `brain_voice_context.py` appends the panel directory to its path.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
import sys
import time

log = logging.getLogger("brain.personality")

STORE = os.environ.get("BRAIN_PERSONALITY_FILE", "/config/.brain/personality.json")
# brAIn's switches (features.py): Personality is one of them. Read here
# directly, not through features.py, because this module is also a CLI and a
# voice-side import that cannot pull the panel in.
FEATURES_FILE = os.environ.get("BRAIN_FEATURES_FILE", "/config/.brain/features.json")
MORPH_FILE = os.environ.get(
    "BRAIN_MORPH_PERSONALITY_FILE", "/config/morph/frontend/personality.js")

NAME_MAX = 60
VOICE_MAX = 80
# One ceiling for the persona everywhere it is stored, shown or typed.
PERSONA_MAX = 32000
GROWTH_TEXT_MAX = 500
GROWTH_MAX = 200
# What a file may be before it is not read at all: a persona and two hundred
# entries are well under this, and a file past it is not one we wrote.
READ_MAX_BYTES = 256 * 1024
MORPH_READ_MAX_BYTES = 512 * 1024

# What a prompt carries: the persona whole (it is already capped by PERSONA_MAX,
# and the household chose it; a clip here showed up as a cut-off persona), and
# the newest few growth entries. Morph's websocket.py holds its own PERSONA_MAX
# (it cannot import this module); tests/test_personality_long.py keeps them equal.
PROMPT_PERSONA_CHARS = PERSONA_MAX
PROMPT_GROWTH_ENTRIES = 3
PROMPT_GROWTH_CHARS = 200

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SPACE = re.compile(r"[ \t]+")


def _clip(text, limit: int) -> str:
    try:
        import textclip  # noqa: PLC0415 — panel-local; absent in some readers
        return textclip.clip(text, limit)
    except ImportError:  # pragma: no cover - the panel dir is always beside us
        s = "" if text is None else str(text)
        return s if len(s) <= limit else s[: max(0, limit - 1)].rstrip() + "…"


def _one_line(value, limit: int) -> str:
    text = _SPACE.sub(" ", str(value or "").replace("\r", " ").replace("\n", " ")).strip()
    return _clip(text, limit)


def _block(value, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return _clip(text, limit)


# The keys a growth entry may carry its date and its words under. A file
# somebody wrote by hand names them however they like, and an entry read
# under none of these is an entry lost.
GROWTH_DATE_KEYS = ("date", "when", "day", "on", "at")
GROWTH_TEXT_KEYS = ("text", "note", "change", "entry", "what", "growth",
                    "summary", "learned")


def _date_of(entry: dict) -> str:
    for key in GROWTH_DATE_KEYS:
        raw = entry.get(key)
        if isinstance(raw, str):
            raw = raw.strip()[:10]
            if _DATE_RE.match(raw):
                return raw
    at = next((entry.get(k) for k in ("at", "when")
               if isinstance(entry.get(k), (int, float))), None)
    if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0:
        if at > 1e12:  # milliseconds, as a JavaScript Date.now() writes
            at = at / 1000
        try:
            return _dt.date.fromtimestamp(at).isoformat()
        except (OverflowError, OSError, ValueError):
            return ""
    return ""


def clean_growth(rows) -> list[dict]:
    """Growth entries as stored: dated, capped, oldest first."""
    out: list[dict] = []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, str):
            row = {"text": row}
        if not isinstance(row, dict):
            continue
        text = _block(next((row[k] for k in GROWTH_TEXT_KEYS
                            if isinstance(row.get(k), str) and row[k].strip()),
                           ""), GROWTH_TEXT_MAX)
        if not text:
            continue
        entry = {"date": _date_of(row), "text": text}
        at = row.get("at")
        if isinstance(at, (int, float)) and not isinstance(at, bool) and at > 0:
            entry["at"] = int(at / 1000 if at > 1e12 else at)
        out.append(entry)
    out.sort(key=lambda e: (e.get("date") or "", e.get("at") or 0))
    return out[-GROWTH_MAX:]


def normalise(data) -> dict:
    """Any parsed shape as the stored one, every field capped."""
    data = data if isinstance(data, dict) else {}
    out = {
        "name": _one_line(data.get("name"), NAME_MAX),
        # The voice brAIn speaks with: one line, the household's answer
        # (`identity`), set in ⚙ › Personality or by a growth note that says
        # the voice changed. Absent is "" — "not recorded", never a guess.
        "voice": _one_line(data.get("voice"), VOICE_MAX),
        "persona": _block(data.get("persona"), PERSONA_MAX),
        "growth": clean_growth(data.get("growth")),
    }
    stamp = data.get("updated_at")
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and stamp > 0:
        out["updated_at"] = int(stamp)
    return out


def load(path: str | None = None) -> dict:
    """The personality, or the empty one. Never raises."""
    target = path or STORE
    try:
        with open(target, "rb") as fh:
            raw = fh.read(READ_MAX_BYTES + 1)
        if len(raw) > READ_MAX_BYTES:
            log.warning("%s is larger than brAIn writes; not read", target)
            return normalise({})
        return normalise(json.loads(raw.decode("utf-8")))
    except (OSError, ValueError):
        return normalise({})


DEFAULT_NAME = "brAIn"


def enabled(features_file: str | None = None) -> bool:
    """Whether Personality is switched on (⚙ › Features). A house whose
    switches were never written keeps what it had, which is on: only an
    explicit off turns it off. Never raises."""
    try:
        with open(features_file or FEATURES_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return True
    return not (isinstance(data, dict) and data.get("personality") is False)


def assistant_name(data: dict | None = None, path: str | None = None) -> str:
    """What brAIn's own fixed words call the assistant, to a person.

    The household's chosen name when one is set and Personality is
    switched on, else "brAIn". One helper
    for every sentence brAIn builds about itself in words somebody reads —
    the who-acts line on a card, a Repairs dialog, a notification's title —
    so a house that named its assistant does not meet two of them. Never
    raises: an unreadable file is no name."""
    if not enabled():
        return DEFAULT_NAME
    try:
        name = (data if isinstance(data, dict) else load(path)).get("name")
    except Exception:  # noqa: BLE001 — a name is a nicety, never a failure
        name = ""
    name = " ".join(str(name or "").split())
    return name or DEFAULT_NAME


_WORD = re.compile(r"\bbrAIn\b")


def speak(text, name: str | None = None) -> str:
    """Prose about to reach a person, with brAIn called by its name.

    With Personality on and a name set, the product's name ("brAIn", in
    exactly that spelling) is the household's name for it: on a card, in a
    notification, in Repairs. `brain` in lower case is a command or a path
    and is never touched. Off, or with no name, the text is unchanged."""
    s = "" if text is None else str(text)
    name = assistant_name() if name is None else name
    if not s or name == DEFAULT_NAME or "brAIn" not in s:
        return s
    return _WORD.sub(name, s)


def is_set(data: dict | None) -> bool:
    data = data or {}
    return bool(data.get("name") or data.get("persona"))


def exists(path: str | None = None) -> bool:
    try:
        return os.path.isfile(path or STORE)
    except OSError:
        return False


def writable(path: str | None = None) -> bool:
    """Never creates its own directory (`facts_store.writable`'s rule)."""
    try:
        return os.path.isdir(os.path.dirname(path or STORE) or ".")
    except OSError:
        return False


def _write(data: dict, path: str) -> None:
    import atomic_write  # noqa: PLC0415 — panel-local
    # The `claude` user's sessions read this file through the terminal's
    # CLAUDE.md as well as the panel, so it is world-readable.
    atomic_write.write_json(path, data, mode=0o644, indent=1, ensure_ascii=False)


def save_refusal(name, persona, path: str | None = None) -> str:
    """Why `save` would refuse these, as the sentence a person reads, or
    "" when it would not. The routes answer with this rather than with an
    exception's text."""
    if not isinstance(name, str) or not isinstance(persona, str):
        return "send {name, persona} as text"
    if len(name.strip()) > NAME_MAX:
        return f"a name is at most {NAME_MAX} characters"
    if len(persona.strip()) > PERSONA_MAX:
        return f"a personality is at most {PERSONA_MAX} characters"
    if not writable(path or STORE):
        return "brAIn's config folder is not there to save into"
    return ""


def growth_refusal(text, path: str | None = None) -> str:
    """Why `add_growth` would refuse this, or ""."""
    if not _block(text, GROWTH_TEXT_MAX):
        return "say what changed"
    if not writable(path or STORE):
        return "brAIn's config folder is not there to save into"
    return ""


def save(name, persona, path: str | None = None, voice=None) -> dict:
    """Replace the name and the persona; the growth log is kept, and so is
    the voice unless ``voice`` is given.

    Raises ValueError when there is nowhere to write, or the text is past
    the cap (a person typed it, so it is refused rather than shortened).
    """
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or STORE
    if not isinstance(name, str) or not isinstance(persona, str):
        raise ValueError("send {name, persona} as text")
    if len(name.strip()) > NAME_MAX:
        raise ValueError(f"a name is at most {NAME_MAX} characters")
    if len(persona.strip()) > PERSONA_MAX:
        raise ValueError(f"a personality is at most {PERSONA_MAX} characters")
    if not writable(target):
        raise ValueError("brAIn's config folder is not there to save into")
    with atomic_write.locked(target):
        data = load(target)
        data["name"] = _one_line(name, NAME_MAX)
        data["persona"] = _block(persona, PERSONA_MAX)
        if isinstance(voice, str):
            data["voice"] = _one_line(voice, VOICE_MAX)
        data["updated_at"] = int(time.time())
        _write(data, target)
    return data


def add_growth(text, when: float | None = None, path: str | None = None) -> dict:
    """Append one dated growth entry. Raises ValueError on nothing to say,
    or nowhere to write."""
    import atomic_write  # noqa: PLC0415 — panel-local

    target = path or STORE
    words = _block(text, GROWTH_TEXT_MAX)
    if not words:
        raise ValueError("say what changed")
    if not writable(target):
        raise ValueError("brAIn's config folder is not there to save into")
    at = int(when if when is not None else time.time())
    entry = {"date": _dt.date.fromtimestamp(at).isoformat(), "at": at, "text": words}
    with atomic_write.locked(target):
        data = load(target)
        data["growth"] = (data.get("growth") or []) + [entry]
        said = voice_named(words)
        if said:
            # The note that the voice changed IS the new answer: every
            # surface quotes the store (`identity`), never the note.
            data["voice"] = said
        data["growth"] = data["growth"][-GROWTH_MAX:]
        data["updated_at"] = at
        _write(data, target)
    return entry


# A growth note saying which voice brAIn now speaks with: "the spoken voice
# changed from A to B", "my voice is now B", "switched the voice to B".
_VOICE_NOTE = re.compile(
    r"\bvoice\b[^.\n]*?\b(?:to|is now|now)\s+(?:the\s+)?[“\"']?"
    r"([^.,;”\"'\n]{2,%d}?)[”\"']?\s*(?:voice\b|for\b|on\b|in\b|[.,;]|$)"
    % VOICE_MAX, re.I)


def voice_named(text) -> str:
    """The voice a growth note says brAIn now speaks with, or ""."""
    m = _VOICE_NOTE.search(str(text or ""))
    return _one_line(m.group(1), VOICE_MAX) if m else ""


def identity(data: dict | None = None, path: str | None = None) -> dict:
    """THE answer to who brAIn is here: `{name, voice}`, read off the store
    (the name through `assistant_name`, so the Personality switch holds).
    Findings and cards quote this and never a model's memory of it."""
    try:
        data = data if isinstance(data, dict) else load(path)
    except Exception:  # noqa: BLE001 — an unreadable store is no answer
        data = {}
    return {"name": assistant_name(data), "voice": str(data.get("voice") or "")}


def identity_line(data: dict | None = None, path: str | None = None) -> str:
    """The line a prompt carries about brAIn's own name and voice."""
    who = identity(data, path)
    voice = (f"brAIn's spoken voice is {who['voice']}." if who["voice"] else
             "Which voice brAIn speaks with is not recorded: say nothing "
             "about it.")
    return ("BRAIN'S OWN VOICE (the one stored answer; quote it, never from "
            f"memory, and never ask the household to change brAIn's files): "
            f"{voice}")


def payload(path: str | None = None) -> dict:
    """What `GET /api/personality` answers: the file, newest growth first."""
    data = load(path)
    return {
        "set": is_set(data),
        "name": data["name"],
        "persona": data["persona"],
        "voice": data.get("voice") or "",
        "growth": list(reversed(data["growth"])),
        "updated_at": data.get("updated_at") or 0,
        "path": path or STORE,
        "limits": {"name": NAME_MAX, "persona": PERSONA_MAX,
                   "growth": GROWTH_TEXT_MAX, "voice": VOICE_MAX},
    }


def summary(data: dict | None) -> str:
    """The ⚙ list row's second line: the current answer, in a few words."""
    data = data or {}
    if not is_set(data):
        return "None set"
    name = data.get("name") or ""
    first = _one_line(data.get("persona"), 60)
    if name and first:
        return f"{name} · {first}"
    return name or first


def prompt_block(data: dict | None = None) -> str:
    """The lines a prompt carries, or "" when no personality is set or
    Personality is switched off."""
    if not enabled():
        return ""
    data = load() if data is None else data
    if not is_set(data):
        return ""
    parts = []
    if data.get("name"):
        parts.append(f"Your name is {data['name']}.")
    persona = _clip(data.get("persona") or "", PROMPT_PERSONA_CHARS)
    if persona:
        parts.append(f"Your personality: {persona}")
    text = " ".join(parts)
    growth = (data.get("growth") or [])[-PROMPT_GROWTH_ENTRIES:]
    if growth:
        lines = [f"- {g.get('date') or 'undated'}: {_one_line(g['text'], PROMPT_GROWTH_CHARS)}"
                 for g in growth]
        text += "\nHow you have grown, most recent last:\n" + "\n".join(lines)
    return text


# ---- the one-time read of Morph's copy ---------------------------------------
#
# Morph's file is a JavaScript module, so it is parsed as one: a tolerant
# reader of the object-literal subset such a file is written in (strings in
# any of the three quotes, unquoted keys, trailing commas, comments,
# numbers, true/false/null, arrays and objects). A template literal with a
# `${…}` in it, a function or anything else is a refusal, never a guess.

class _Unreadable(ValueError):
    pass


class _Literal:
    def __init__(self, src: str, pos: int):
        self.s = src
        self.i = pos

    def _skip(self) -> None:
        s = self.s
        while self.i < len(s):
            c = s[self.i]
            if c.isspace():
                self.i += 1
            elif s.startswith("//", self.i):
                end = s.find("\n", self.i)
                self.i = len(s) if end < 0 else end + 1
            elif s.startswith("/*", self.i):
                end = s.find("*/", self.i + 2)
                if end < 0:
                    raise _Unreadable("an unclosed comment")
                self.i = end + 2
            else:
                break

    def value(self):
        self._skip()
        if self.i >= len(self.s):
            raise _Unreadable("the file ends mid-value")
        c = self.s[self.i]
        if c in "'\"`":
            return self._string(c)
        if c == "[":
            return self._array()
        if c == "{":
            return self._object()
        m = re.match(r"-?\d+(\.\d+)?([eE][-+]?\d+)?", self.s[self.i:])
        if m:
            self.i += m.end()
            num = float(m.group(0))
            return int(num) if num.is_integer() and "." not in m.group(0) else num
        for word, val in (("true", True), ("false", False), ("null", None)):
            if self.s.startswith(word, self.i):
                self.i += len(word)
                return val
        raise _Unreadable(f"something that is not a value at character {self.i}")

    def _string(self, quote: str) -> str:
        s = self.s
        self.i += 1
        out = []
        escapes = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f",
                   "v": "\v", "0": "\0"}
        while self.i < len(s):
            c = s[self.i]
            if c == quote:
                self.i += 1
                return "".join(out)
            if c == "\\":
                nxt = s[self.i + 1:self.i + 2]
                if nxt == "u":
                    hexa = s[self.i + 2:self.i + 6]
                    try:
                        out.append(chr(int(hexa, 16)))
                    except ValueError:
                        raise _Unreadable("a bad \\u escape") from None
                    self.i += 6
                    continue
                if nxt == "\n":
                    self.i += 2
                    continue
                out.append(escapes.get(nxt, nxt))
                self.i += 2
                continue
            if quote == "`" and s.startswith("${", self.i):
                raise _Unreadable("a template literal with a substitution")
            if c == "\n" and quote != "`":
                raise _Unreadable("a string that runs over a line")
            out.append(c)
            self.i += 1
        raise _Unreadable("an unclosed string")

    def _array(self) -> list:
        self.i += 1
        out = []
        while True:
            self._skip()
            if self.s[self.i:self.i + 1] == "]":
                self.i += 1
                return out
            out.append(self.value())
            self._skip()
            c = self.s[self.i:self.i + 1]
            if c == ",":
                self.i += 1
            elif c != "]":
                raise _Unreadable("an array that does not close")

    def _object(self) -> dict:
        self.i += 1
        out = {}
        while True:
            self._skip()
            c = self.s[self.i:self.i + 1]
            if c == "}":
                self.i += 1
                return out
            if c in ("'", '"'):
                key = self._string(c)
            else:
                m = re.match(r"[A-Za-z_$][\w$]*", self.s[self.i:])
                if not m:
                    raise _Unreadable(f"a key that is not a name at character {self.i}")
                key = m.group(0)
                self.i += m.end()
            self._skip()
            if self.s[self.i:self.i + 1] != ":":
                raise _Unreadable(f"no ':' after the key {key!r}")
            self.i += 1
            out[key] = self.value()
            self._skip()
            c = self.s[self.i:self.i + 1]
            if c == ",":
                self.i += 1
            elif c != "}":
                raise _Unreadable("an object that does not close")


def _assigned(src: str, name: str):
    """The literal assigned to `name` (`const NAME = …` or `NAME: …`), or a
    `_Unreadable` sentinel-free None when the file never assigns it."""
    m = re.search(rf"(?:\b(?:const|let|var)\s+{name}\s*=|\b{name}\s*:)", src)
    if not m:
        return None
    return _Literal(src, m.end()).value()


_PERSONA_TEXT_KEYS = ("persona", "personality", "text", "prompt", "description",
                      "voice", "style", "about")


def _render(value, indent: int = 0) -> list[str]:
    """A parsed object as readable lines, nothing dropped: a string as
    ``key: value``, a list as ``- item`` lines under its key, a nested
    object as its own ``key: value`` lines indented under its key."""
    pad = " " * indent
    out: list[str] = []
    if isinstance(value, dict):
        for key, item in value.items():
            if item is None or item == "" or item == [] or item == {}:
                continue
            if isinstance(item, (dict, list)):
                out.append(f"{pad}{key}:")
                out += _render(item, indent + 2)
            else:
                out.append(f"{pad}{key}: {_scalar(item)}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                inner = _render(item, indent + 2)
                if inner:
                    out.append(f"{pad}- {inner[0].strip()}")
                    out += inner[1:]
            elif item is not None and item != "":
                out.append(f"{pad}- {_scalar(item)}")
    elif value is not None and value != "":
        out.append(f"{pad}{_scalar(value)}")
    return out


def _scalar(value) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value).strip()


def parse_morph(src: str) -> dict:
    """PERSONA and GROWTH out of Morph's module, as the stored shape.

    Raises ValueError (naming what it could not read) when the file is not
    something this reader understands, or holds no personality at all.
    """
    persona_raw = _assigned(src, "PERSONA")
    growth_raw = _assigned(src, "GROWTH")
    name = ""
    persona = ""
    if isinstance(persona_raw, str):
        persona = persona_raw
    elif isinstance(persona_raw, dict):
        name = persona_raw.get("name") if isinstance(persona_raw.get("name"), str) else ""
        # The one text the object leads with, as itself; every other part
        # after it, rendered whole. Keeping only the top-level strings is
        # what reduced a house's persona to two lines: its traits, its
        # voice rules and its nested description were lists and objects.
        lead = next((k for k in _PERSONA_TEXT_KEYS
                     if isinstance(persona_raw.get(k), str)
                     and persona_raw[k].strip()), "")
        lines = [persona_raw[lead].strip()] if lead else []
        rest = {k: v for k, v in persona_raw.items() if k not in ("name", lead)}
        lines += _render(rest)
        persona = "\n".join(lines)
    elif persona_raw is not None:
        raise ValueError("PERSONA is neither text nor an object")
    if not name:
        named = _assigned(src, "NAME")
        if isinstance(named, str):
            name = named
    data = normalise({"name": name, "persona": persona, "growth": growth_raw})
    if not is_set(data) and not data["growth"]:
        raise ValueError("it holds no PERSONA and no GROWTH")
    return data


def migrate_from_morph(src_path: str | None = None, path: str | None = None) -> str:
    """Read Morph's copy into brAIn's file, once. Returns what happened, in
    a sentence for the log. Never raises and never writes to /config/morph."""
    src_path = src_path or MORPH_FILE
    target = path or STORE
    if exists(target):
        return ""
    if not os.path.isfile(src_path):
        return ""
    if not writable(target):
        return "brAIn has no config folder yet; Morph's personality was not read"
    try:
        with open(src_path, "rb") as fh:
            raw = fh.read(MORPH_READ_MAX_BYTES + 1)
        if len(raw) > MORPH_READ_MAX_BYTES:
            raise ValueError("it is larger than a personality file")
        data = parse_morph(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as exc:
        return f"could not read the personality out of {src_path} ({exc}); nothing was moved"
    data["updated_at"] = int(time.time())
    try:
        import atomic_write  # noqa: PLC0415 — panel-local
        with atomic_write.locked(target):
            if exists(target):
                return ""
            _write(data, target)
    except OSError as exc:
        return f"could not save the personality read from Morph ({exc})"
    return (f"moved the personality out of {src_path} into {target} "
            f"({len(data['growth'])} growth entries); Morph's file is left as it was")


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]


def repair_from_morph(src_path: str | None = None, path: str | None = None) -> str:
    """Replace a stored personality that is exactly an earlier, poorer
    import of Morph's file with a full read of it. Returns what happened,
    in a sentence for the log, or "". Never raises.

    Only when nothing in the stored file is missing from a fresh read —
    the same name (or none), every persona line, every growth entry — and
    the fresh read holds more. Anything the fresh read does not contain is
    somebody's edit, and an edit is never replaced."""
    src_path = src_path or MORPH_FILE
    target = path or STORE
    if not exists(target) or not os.path.isfile(src_path):
        return ""
    try:
        with open(src_path, "rb") as fh:
            raw = fh.read(MORPH_READ_MAX_BYTES + 1)
        if len(raw) > MORPH_READ_MAX_BYTES:
            return ""
        fresh = parse_morph(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError):
        return ""
    stored = load(target)
    if stored["name"] and stored["name"] != fresh["name"]:
        return ""
    fresh_lines = set(_lines(fresh["persona"]))
    if not set(_lines(stored["persona"])) <= fresh_lines:
        return ""
    have = {(g.get("date") or "", g["text"]) for g in fresh["growth"]}
    have_text = {g["text"] for g in fresh["growth"]}
    for g in stored["growth"]:
        if (g.get("date") or "", g["text"]) not in have and g["text"] not in have_text:
            return ""
    if (len(fresh_lines) <= len(set(_lines(stored["persona"])))
            and len(fresh["growth"]) <= len(stored["growth"])):
        return ""
    data = {**fresh, "name": stored["name"] or fresh["name"],
            "updated_at": int(time.time())}
    try:
        import atomic_write  # noqa: PLC0415 — panel-local
        with atomic_write.locked(target):
            if load(target) != stored:
                return ""
            _write(data, target)
    except OSError as exc:
        return f"could not repair the personality read from Morph ({exc})"
    return (f"repaired the personality imported from {src_path}: it now holds "
            f"{len(fresh_lines)} persona lines and {len(data['growth'])} growth "
            "entries; Morph's file is left as it was")


def section(path: str | None = None) -> str:
    """The `/config/CLAUDE.md` section, or "" when none is set."""
    block = prompt_block(load(path))
    if not block:
        return ""
    return ("## Personality\n\nThe household gave brAIn this personality "
            "(⚙ › Personality). Speak as it in the terminal and the chat.\n\n"
            + block + "\n")


def _cli(argv: list[str]) -> int:
    verb = argv[1] if len(argv) > 1 else ""
    path = argv[2] if len(argv) > 2 else None
    if verb == "section":
        sys.stdout.write(section(path))
        return 0
    if verb == "block":
        sys.stdout.write(prompt_block(load(path)))
        return 0
    sys.stderr.write("usage: personality.py section|block [file]\n")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv))
