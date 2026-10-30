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

import re

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


# A sentence's own end, which `shorten` cuts after and never marks: a whole
# sentence is not a cut one. "; " is not among them — inside a list it is
# where an item ends, and `_listed` says how many more there were.
_FULL_STOPS = (". ", "! ", "? ", ".\n", "!\n", "?\n")
# "…" straight after a sentence's end ("…malformed-event errors.…") says
# a whole sentence was cut, which it was not.
_STOP_ELLIPSIS = re.compile(r"([.!?][\"'”’)]?)\s*…(?=\s|$)")
# A list needs this many items before "and N more" reads as one.
_LIST_MIN = 3


def _listed(s: str, begin: int, limit: int) -> str:
    """``s`` up to the sentence starting at ``begin``, with that sentence's
    list kept to whole items and the rest counted ("A; B; and 6 more."),
    within ``limit`` — or "" when that sentence is no list or no item fits.
    A list is three or more items split by "; ", or by ", " after a colon."""
    rest = s[begin:]
    body_at = begin + len(rest) - len(rest.lstrip())
    body = s[body_at:]
    ends = [i for i in (body.find(e) for e in _FULL_STOPS) if i >= 0]
    if ends:
        body = body[:min(ends) + 1]
    body = body.rstrip(" .!?\n")
    lead, sep, items = "", "; ", body.split("; ")
    if len(items) < _LIST_MIN and ": " in body:
        intro, tail = body.split(": ", 1)
        lead, sep, items = intro + ": ", ", ", tail.split(", ")
    if len(items) < _LIST_MIN:
        return ""
    for keep in range(len(items) - 1, 0, -1):
        more = len(items) - keep
        out = (s[:body_at] + lead + sep.join(items[:keep]).rstrip(" ,;:")
               + f"{sep}and {more} more.")
        if len(out) <= limit:
            return out
    return ""


def shorten(text, limit: int) -> str:
    """``text`` within ``limit`` characters for a card, cut by WHOLE
    sentence or WHOLE list item, never mid-clause where it can be helped.

    A finding's detail, what-to-do and a look's conclusion ended "…from its
    device page.…", "…last 29 Oct;…" and "…will be settled by your…" (#560):
    `clip` keeps most of the budget, and a card would rather lose a sentence
    than end in half of one. So the cut is the last whole sentence that
    fits (unmarked: it is a whole sentence), or — when the sentence being
    cut is a list — its whole items and how many more ("and 6 more."),
    whichever keeps more. Only text with neither (one sentence longer than
    the budget) falls back to `clip`'s word and "…". A "…" left after a
    full stop by an older cut is taken off. Text that fits is unchanged.
    """
    s = "" if text is None else str(text)
    if limit <= 0:
        return ""
    if "…" in s:
        s = _STOP_ELLIPSIS.sub(r"\1", s)
    if len(s) <= limit:
        return s
    head = s[:limit + 1]
    stop = max(head.rfind(e) for e in _FULL_STOPS)
    whole = s[:stop + 1].rstrip() if stop >= 0 else ""
    listed = _listed(s, stop + 1 if stop >= 0 else 0, limit)
    best = max(whole, listed, key=len)
    return best if best else clip(s, limit)


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


__all__ = ["ELLIPSIS", "NOTE_FROM", "clip", "shorten", "shown"]
