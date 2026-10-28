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

Rows of this source are written by code, so `findings_store` leaves their
words alone (`PLAIN_EXEMPT`): the quoted line is the instruction's own.
"""
from __future__ import annotations

import re

import instructions
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


def as_question(obj: dict) -> dict | None:
    """The fields that make a row the question brAIn asks itself, or None
    when the row points at no line brAIn can find."""
    found = stale_line(obj)
    if found is None:
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
    """Yes: take the line out. Whether it was there to take."""
    edit = (row or {}).get("self_edit") or {}
    key, line = str(edit.get("key") or ""), str(edit.get("line") or "")
    if key not in instructions.CATALOG or not line:
        return False
    return instructions.drop_line(key, line)


__all__ = ["SOURCE", "SOURCE_TITLE", "as_question", "correct", "stale_line"]
