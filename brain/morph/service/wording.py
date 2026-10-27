"""What a person said, and the context a card sent with it, made to fit.

A request to brAIn is bounded (a task file is not a place for a novel), and
the bound used to be a slice off the end: ``text[:2000]``. A custom card on a
house sent its context first and "What <who> said: <question>" last, so the
person's words were the part the slice took, and brAIn answered "your message
got cut off" to a message nobody had cut. The next answer was worse in the
other direction: words alone over the bound kept their END behind "(the start
of this message was cut to fit)", so a long request reached brAIn — and
brAIn's chat — missing its opening, cut mid-word (#428).

So the person's words are never cut, at any length. What gives is the context
sent beside them, and only the context:

- the context is cut to the room left, on a line break where there is one
  and otherwise between words, and the cut is said in the text;
- with no room left at all the context is left out, and that is said too.

``clip`` is the same rule for any other text Morph writes into a request (a
suggestion's change, an answer's request): a word boundary and an ellipsis,
never half a word.
"""
from __future__ import annotations

MAX_TEXT = 16000
CONTEXT_CUT = " … (the rest of this context was cut to fit)"
CONTEXT_LEFT_OUT = "(the context sent with this message was left out to fit)"


def _cut_at_boundary(text: str, keep: int) -> str:
    """``text`` cut to at most ``keep`` characters, ending at the last line
    break in the second half of what is kept, else the last space; a run of
    one long word is cut where it must."""
    if len(text) <= keep:
        return text
    head = text[:keep]
    for sep in ("\n", " "):
        at = head.rfind(sep)
        if at >= keep // 2:
            return head[:at].rstrip()
    return head.rstrip()


def clip(text: str, limit: int) -> str:
    """``text`` within ``limit`` characters, cut between words and marked
    with an ellipsis when it had to be cut."""
    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    return _cut_at_boundary(text, max(0, limit - 1)) + "…"


def fit(words: str, context: str = "", *, cap: int = MAX_TEXT) -> dict:
    """``{"words", "context", "words_cut", "context_cut"}``. The words are
    always whole; the context takes what room ``cap`` leaves beside them."""
    words = str(words or "").strip()
    context = str(context or "").strip()
    out = {"words": words, "context": context, "words_cut": False, "context_cut": False}
    room = cap - len(words)
    if len(context) <= room:
        return out
    out["context_cut"] = True
    keep = room - len(CONTEXT_CUT)
    if keep < 80:
        out["context"] = CONTEXT_LEFT_OUT
        return out
    out["context"] = _cut_at_boundary(context, keep) + CONTEXT_CUT
    return out


__all__ = ["fit", "clip", "MAX_TEXT", "CONTEXT_CUT", "CONTEXT_LEFT_OUT"]
