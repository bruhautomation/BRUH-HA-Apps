"""brAIn's own upkeep, done by brAIn: a stale line in its instructions.

A finding told the owner to "edit line 27 of chat_identity.md" and call a
tool to record it — brAIn's housekeeping, asked of the household in words
only its developer reads. A model-written row whose words point at a line
of one of brAIn's instruction overrides (⚙ › Instructions, `instructions.
CATALOG`) that brAIn can find — by its number, or by a quoted piece of it —
is filed as ONE yes/no question instead: "brAIn's instructions for <what>
still say “…”. Shall brAIn take that line out?" Yes takes it out
(`correct`, through `instructions.drop_line`, so the override is saved and
put in force the way ⚙ saves it); No leaves it. A line brAIn cannot find
is not a question: the row stays a finding, its developer words scrubbed
(`house_words.self_said`).

A voice the household settles is the other half (#769): the instruction
overrides and the persona are words a person wrote, so a line in them that
still names the voice it replaced is not rewritten unattended. In the step
that stores the voice, brAIn files one question per file quoting the line
(`voice_questions`), and Yes replaces the old name with the new one
(`correct`); a model's row about the conflict is read as that question
too (`as_question`). The growth note that settles a voice can come from a
conversation, which is why it is a press and not a write.

Rows of this source are written by code, so `findings_store` leaves their
words alone (`PLAIN_EXEMPT`): the quoted line is the instruction's own.
"""
from __future__ import annotations

import re

import instructions
import personality
import textclip

SOURCE = "self_care"
SOURCE_TITLE = "brAIn's own upkeep"
QUOTE_MAX = 160

_LINE_NO = re.compile(r"\bline\s+(\d{1,4})\b", re.I)
_QUOTED = re.compile(r"[“\"']([^”\"']{6,200})[”\"']")


def _keys_named(text: str) -> list[str]:
    out = []
    for key in instructions.CATALOG:
        if re.search(r"(?<![\w])" + re.escape(key) + r"(?:\.md)?(?![\w])",
                     text):
            out.append(key)
    return out


def stale_line(obj: dict) -> tuple[str, str] | None:
    """`(key, line)`: the instruction line a row's words point at and brAIn
    can read, or None."""
    if not isinstance(obj, dict):
        return None
    words = " ".join(str(obj.get(k) or "") for k in
                     ("text", "claim", "detail", "fix"))
    for key in _keys_named(words):
        lines = instructions.override_lines(key)
        if not lines:
            continue
        for m in _LINE_NO.finditer(words):
            n = int(m.group(1))
            if 1 <= n <= len(lines) and lines[n - 1].strip():
                return key, lines[n - 1].strip()
        for m in _QUOTED.finditer(words):
            piece = m.group(1).strip().lower()
            for line in lines:
                if piece and piece in line.lower():
                    return key, line.strip()
    return None


# The persona, beside the instruction overrides: the other file of brAIn's
# own that says who it is.
PERSONA_KEY = "personality"
PERSONA_WHAT = "who brAIn is (⚙ › Personality)"
def _what(key: str) -> str:
    return PERSONA_WHAT if key == PERSONA_KEY else instructions.CATALOG[key][0]


def _replaced(voice: str, old: str = "") -> list[str]:
    """The voices brAIn no longer speaks with: the one just replaced and
    every one the store remembers replacing. Only these are ever read as a
    voice in a line — a capitalised word beside "voice" ("the Assistant
    voice pipeline", "Voice: Dutch accent") is the household's words."""
    known = ([old] if old else []) + list(personality.load().get("replaced")
                                          or [])
    return [k for k in dict.fromkeys(str(k).strip() for k in known)
            if k and k.lower() != voice.lower()]


def _voices_named(line: str, known) -> list[str]:
    """The replaced voices a line about a voice names."""
    if not re.search(r"\bvoice\b", line, re.I):
        return []
    return [k for k in known if re.search(
        r"(?<![\w])" + re.escape(k) + r"(?![\w])", line, re.I)]


def voice_conflicts(voice: str, old: str = "") -> list[tuple[str, str, str]]:
    """``(key, line, new)``: every line of brAIn's instruction overrides and
    its persona that names a voice other than ``voice``, with that name
    replaced by ``voice``. [] when no voice is stored."""
    voice = str(voice or "").strip()
    known = _replaced(voice, old) if voice else []
    if not known:
        return []
    files = [(key, instructions.override_lines(key))
             for key in instructions.CATALOG]
    files.append((PERSONA_KEY, str(personality.load().get("persona")
                                   or "").split("\n")))
    out = []
    for key, lines in files:
        for line in lines:
            names = _voices_named(line, known)
            if not names:
                continue
            new = line
            for name in names:
                new = re.sub(r"(?<![\w])" + re.escape(name) + r"(?![\w])",
                             voice, new, flags=re.I)
            out.append((key, line.strip(), new.strip()))
    return out


def _voice_question(voice: str, conflicts) -> dict:
    keys = list(dict.fromkeys(k for k, _l, _n in conflicts))
    what = " and ".join(f"“{_what(k)}”" for k in keys)
    # Every line the Yes changes is quoted: a press is agreement to what
    # it can see.
    quoted = " and “".join(textclip.clip(line, QUOTE_MAX)
                           for _k, line, _n in conflicts)
    claim = (f"brAIn's voice is now {voice}, but its instructions for {what} "
             f"still say “{quoted}”. Shall brAIn change "
             f"{'that line' if len(conflicts) == 1 else 'those lines'} "
             f"to say {voice}?")
    return {
        "text": f"Change brAIn's {what} instructions to say the {voice} "
                "voice?",
        "claim": claim,
        "detail": "",
        "fix": "",
        "kind": "question",
        "severity": "info",
        "fixable": False,
        "source": SOURCE,
        "source_title": SOURCE_TITLE,
        "entity_id": "",
        "self_edit": {"edits": [{"key": k, "line": line, "new": new}
                                for k, line, new in conflicts]},
    }


def voice_questions(voice: str, old: str = "") -> list[dict]:
    """One question per file that still names a voice other than the one
    just settled, each a one-press edit."""
    by_key: dict[str, list] = {}
    for found in voice_conflicts(voice, old):
        by_key.setdefault(found[0], []).append(found)
    return [_voice_question(voice, found) for found in by_key.values()]


def as_question(obj: dict) -> dict | None:
    """The fields that make a row the question brAIn asks itself, or None
    when the row points at no line brAIn can find. A row about brAIn's
    voice while a file still names another one is the voice question."""
    if not isinstance(obj, dict) or obj.get("self_edit"):
        return None
    found = stale_line(obj)
    if found is None:
        words = " ".join(str(obj.get(k) or "") for k in
                         ("text", "claim", "detail", "fix"))
        voice = personality.identity().get("voice") or ""
        if voice and re.search(r"\bvoice\b", words, re.I):
            conflicts = voice_conflicts(voice)
            if conflicts:
                return _voice_question(voice, conflicts)
        return None
    key, line = found
    what = instructions.CATALOG[key][0]
    quoted = textclip.clip(line, QUOTE_MAX)
    claim = (f"brAIn's instructions for “{what}” still say “{quoted}”, "
             "which is out of date. Shall brAIn take that line out?")
    return {
        "text": f"Take an out-of-date line out of brAIn's “{what}” instructions?",
        "claim": claim,
        "detail": "",
        "fix": "",
        "kind": "question",
        "severity": "info",
        "fixable": False,
        "source": SOURCE,
        "source_title": SOURCE_TITLE,
        "entity_id": "",
        "self_edit": {"key": key, "line": line},
    }


def correct(row: dict) -> bool:
    """Yes: take the line out, or make the edits the question named.
    Whether anything was there to change."""
    edit = (row or {}).get("self_edit") or {}
    edits = edit.get("edits") if isinstance(edit.get("edits"), list) else [
        {"key": edit.get("key"), "line": edit.get("line"), "new": None}]
    by_key: dict[str, list] = {}
    for e in edits:
        if not isinstance(e, dict) or not str(e.get("line") or ""):
            continue
        key = str(e.get("key") or "")
        if key != PERSONA_KEY and key not in instructions.CATALOG:
            continue
        new = e.get("new")
        by_key.setdefault(key, []).append(
            (str(e["line"]), None if new is None else str(new)))
    done = False
    for key, pairs in by_key.items():
        if key == PERSONA_KEY:
            done = personality.edit_persona_lines(
                [(line, new) for line, new in pairs if new is not None]) or done
        else:
            done = instructions.edit_lines(key, pairs) or done
    return done


__all__ = ["PERSONA_KEY", "SOURCE", "SOURCE_TITLE", "as_question", "correct",
           "stale_line", "voice_conflicts", "voice_questions"]
