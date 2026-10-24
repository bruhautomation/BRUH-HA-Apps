"""What a person said, and the context a card sent with it, made to fit.

A request to brAIn is bounded (a task file is not a place for a novel), and
the bound used to be a slice off the end: ``text[:2000]``. A custom card on a
house sent its context first and "What <who> said: <question>" last, so the
person's words were the part the slice took, and brAIn answered "your message
got cut off" to a message nobody had cut.

So the bound is sized for a context AND a message, and when something must
give it is never the person's words:

- ``context`` beside ``words`` (what a card should send): the words are kept
  whole and the context is cut to the room left, its cut said in words.
- ``words`` alone, too long: the END is kept, because the one shape a caller
  has used to pack a context in is context first and the person's words last.

Every cut is said in the text itself, so brAIn is never left to guess that
something is missing.
"""
from __future__ import annotations

MAX_TEXT = 16000
CONTEXT_CUT = " … (the rest of this context was cut to fit)"
START_CUT = "(the start of this message was cut to fit) … "


def fit(words: str, context: str = "", *, cap: int = MAX_TEXT) -> dict:
    """``{"words", "context", "words_cut", "context_cut"}``; the two kept
    parts together are at most ``cap`` characters."""
    words = str(words or "").strip()
    context = str(context or "").strip()
    out = {"words": words, "context": context, "words_cut": False, "context_cut": False}
    if len(words) > cap:
        # Only possible with nothing else to give: keep the end, which is
        # where the person's own words are when a caller packed them in.
        keep = max(0, cap - len(START_CUT))
        out["words"] = START_CUT + words[-keep:].lstrip() if keep else words[-cap:]
        out["words_cut"] = True
        out["context"] = ""
        out["context_cut"] = bool(context)
        return out
    room = cap - len(words)
    if len(context) > room:
        keep = max(0, room - len(CONTEXT_CUT))
        out["context"] = (context[:keep].rstrip() + CONTEXT_CUT) if keep else ""
        out["context_cut"] = True
    return out


__all__ = ["fit", "MAX_TEXT", "CONTEXT_CUT", "START_CUT"]
