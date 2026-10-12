"""Shortening prose for a screen without cutting a word in half.

Every store caps what a model or a check wrote, because a reply can be any
length and a card cannot. The cap used to be a bare slice, which cut where
the count ran out — "…would change the answer to t", "…none of these ent"
— with no ellipsis, so a shortened sentence read as a broken one. `clip` is
the one implementation: it keeps the whole text when it fits, and otherwise
ends at the last sentence boundary, then the last space, that leaves most
of the budget, and says it shortened with "…".

A leaf on purpose: the stores, the review and the house book all read it,
and a module they all import may import none of them.
"""

from __future__ import annotations

ELLIPSIS = "…"

# How much of the budget a boundary has to keep before it is preferred over
# a plain word break. A sentence end at character 20 of 300 would throw
# away nearly everything to look tidy; a word break never costs more than
# one word.
_SENTENCE_SHARE = 0.6
_WORD_SHARE = 0.5
_SENTENCE_ENDS = (". ", "! ", "? ", "; ", ".\n", "!\n", "?\n")
_TRAILING = " \t\n,;:-–—(/"


def clip(text, limit: int) -> str:
    """`text` as a string of at most `limit` characters, cut on a boundary.

    Never longer than `limit`, the ellipsis included, so a caller's cap
    means what it meant before. A text that fits comes back unchanged
    (stripped only of what the caller already stripped).
    """
    s = "" if text is None else str(text)
    if limit <= 0:
        return ""
    if len(s) <= limit:
        return s
    if limit <= len(ELLIPSIS):
        return s[:limit]
    room = limit - len(ELLIPSIS)
    head = s[:room]
    # A sentence (or clause) that ends inside the budget is the best cut.
    best = -1
    for end in _SENTENCE_ENDS:
        best = max(best, head.rfind(end))
    if best >= int(room * _SENTENCE_SHARE):
        return head[:best + 1].rstrip() + ELLIPSIS
    # Otherwise the last whole word. A character after the cut that is
    # whitespace means `head` already ends on a whole word.
    if s[room:room + 1].isspace():
        cut = room
    else:
        cut = max(head.rfind(" "), head.rfind("\n"), head.rfind("\t"))
    if cut >= int(room * _WORD_SHARE):
        head = head[:cut]
    # A single long token (an entity id, a URL) has no word to keep whole:
    # cutting it is the only honest answer, and the ellipsis says so.
    return head.rstrip(_TRAILING) + ELLIPSIS


# Below this budget a display copy is one line — a button's label, a chip's
# summary, an option's description — and a second line saying how much was
# hidden would be longer than what it describes. Above it the copy is a
# block (a tool's input, a tool's result, a message), and the line under it
# is what tells a reader the cut is the screen's and not the model's.
NOTE_FROM = 400
# How much of the budget a line break has to keep before it is preferred
# over a plain word break. A block of JSON cut mid-line reads as broken.
_LINE_SHARE = 0.5


def shown(text, limit: int) -> str:
    """``text`` shortened for the SCREEN, saying so.

    The chat and the conversation replay draw a copy of what the CLI
    already has — a tool's input, a tool's result, a message — and nothing
    shortened here is ever sent back to Claude. "… (truncated)" cut
    mid-word said none of that, and read as Claude cutting off its own
    context. So a block is cut on a line break, else on a word, and the
    line under it says how much is shown and that Claude has the full text;
    a short one-line budget is ``clip``'s plain ellipsis. Text that fits
    comes back unchanged.
    """
    s = "" if text is None else str(text)
    if limit <= 0 or len(s) <= limit:
        return s if limit > 0 else ""
    if limit < NOTE_FROM:
        return clip(s, limit)
    head = s[:limit]
    nl = head.rfind("\n")
    if s[limit:limit + 1] == "\n":
        cut = limit
    elif nl >= int(limit * _LINE_SHARE):
        cut = nl
    elif s[limit:limit + 1].isspace():
        cut = limit
    else:
        sp = max(head.rfind(" "), head.rfind("\t"))
        cut = sp if sp >= int(limit * _WORD_SHARE) else limit
    head = head[:cut].rstrip()
    return (f"{head}\n{ELLIPSIS} display truncated: {len(head):,} of "
            f"{len(s):,} characters shown here — Claude has the full text.")


__all__ = ["ELLIPSIS", "NOTE_FROM", "clip", "shown"]
