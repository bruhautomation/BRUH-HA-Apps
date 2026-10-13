"""What changed on the dashboard between two documents, in a person's words.

A leaf: `tell` reads it back after a Tell and `learning` reads it for an
undone one, and `learning` is imported by `tell` — so the arithmetic lives
here, importing nothing of Morph's, or the two would import each other.
"""
from __future__ import annotations

FLAG_WORDS = {"greeting": "the greeting", "story": "the story line", "ask": "the Ask box",
              "coming_up": "Coming up"}
MAX_SHOWS = 8


def _cards(dash: dict) -> dict:
    """Every card by id: (its words, the section it is in, the card)."""
    out = {}
    for fl in dash.get("floors") or []:
        for sec in fl.get("sections") or []:
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    words = (c.get("name") or c.get("entity") or c.get("text")
                             or ", ".join((c.get("entities") or [])[:2]) or c.get("type") or "a card")
                    out[c.get("id")] = (str(words)[:60], sec.get("title") or "", c)
    return out


def _sections(dash: dict) -> dict:
    return {s.get("id"): s for fl in dash.get("floors") or [] for s in fl.get("sections") or []}


def describe_change(old: dict, new: dict) -> list[str]:
    """What is different on the dashboard, in the words a person reads it
    in. Computed from the two documents, never from what brAIn said it did:
    a Tell that reports a change the file does not carry is the failure this
    exists to catch."""
    out: list[str] = []
    for flag, words in FLAG_WORDS.items():
        a, b = old.get(flag, True) is not False, new.get(flag, True) is not False
        if a != b:
            out.append(f"{words[0].upper() + words[1:]} is {'back' if b else 'hidden'}.")
    if (old.get("title") or "") != (new.get("title") or ""):
        out.append(f"The title is now “{new.get('title')}”.")
    if list(old.get("scenes") or []) != list(new.get("scenes") or []):
        out.append(f"The scenes line now has {len(new.get('scenes') or [])} scene(s).")
    if (old.get("theme") or "") != (new.get("theme") or ""):
        out.append(f"The theme is now {new.get('theme') or 'automatic'}.")
    os_, ns = _sections(old), _sections(new)
    for sid, sec in ns.items():
        if sid not in os_:
            out.append(f"New section “{sec.get('title')}”.")
        else:
            was = os_[sid]
            if was.get("title") != sec.get("title"):
                out.append(f"“{was.get('title')}” is now called “{sec.get('title')}”.")
            if bool(was.get("hidden")) != bool(sec.get("hidden")):
                out.append(f"“{sec.get('title')}” is {'hidden' if sec.get('hidden') else 'shown again'}.")
            if (was.get("width") or 2) != (sec.get("width") or 2):
                out.append(f"“{sec.get('title')}” is {'wider' if (sec.get('width') or 2) > (was.get('width') or 2) else 'narrower'}.")
    for sid, sec in os_.items():
        if sid not in ns:
            out.append(f"Removed the section “{sec.get('title')}”.")
    oc, nc = _cards(old), _cards(new)
    for cid, (words, sec, card) in nc.items():
        if cid not in oc:
            out.append(f"New card “{words}” in {sec}.")
        elif oc[cid][2] != card:
            out.append(f"Changed the card “{words}” in {sec}.")
    for cid, (words, sec, _) in oc.items():
        if cid not in nc:
            out.append(f"Removed the card “{words}” from {oc[cid][1]}.")
    if len(out) > MAX_SHOWS:
        out = out[:MAX_SHOWS - 1] + [f"…and {len(out) - MAX_SHOWS + 1} more changes."]
    return out
