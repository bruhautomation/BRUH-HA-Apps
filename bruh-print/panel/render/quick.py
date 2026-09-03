#!/usr/bin/env python3
"""One word in, one label out.

This is the feature the whole add-on is for. "Give me a word and fit it to a
label" is not a designer with defaults filled in — it is a different job,
because a designer asks you where things go and this asks you nothing. The
only question it answers is *how big*, and the answer is "as big as fits".

Getting that answer right takes two ideas that a naive largest-font-that-fits
does not have.

**Layout is chosen, not assumed.** "Spare keys" on a 2.25 × 1.25 label is
biggest on two lines; "9912" is biggest on one; "Christmas decorations loft" is
biggest on three. So every plausible line-break of the words is *rendered*
and the one whose glyphs come out largest wins. Trying only one arrangement
is what makes an auto-fit label look like it did not try, and people go
back to the designer.

**A cap, because filling the label is not always the goal.** A single "9"
fitted to a 2.25" label is a nine the height of your thumb, which reads as
a mistake rather than as emphasis. `max_mm` bounds it, and it defaults to
the label's own height — so short text gets big and stops being silly.
"""
from __future__ import annotations

from dataclasses import dataclass

from . import fonts, image as ri
from .label import Element, Label

# Above this many words, every line-break combination is more arrangements
# than a label has room for anyway, so the search falls back to the wrapper's
# own greedy answer at each line count. Eight words is already a paragraph on
# a 2.25" label.
_MAX_WORDS_FOR_SEARCH = 8


@dataclass(frozen=True)
class Fit:
    """What the fitter decided, so the panel can show its working."""

    lines: list[str]
    size_mm: float
    label: Label

    def as_dict(self) -> dict:
        return {"lines": self.lines, "size_mm": round(self.size_mm, 2)}


def _arrangements(words: list[str]) -> list[list[str]]:
    """Every way of breaking these words across lines, order preserved.

    A break is a subset of the gaps between words, so n words give 2^(n-1)
    arrangements — 128 at the seven-word ceiling, each costing one bisection
    over a cached font. That is milliseconds, and it is what makes the
    result look chosen rather than defaulted.
    """
    if len(words) <= 1:
        return [words]
    out: list[list[str]] = []
    gaps = len(words) - 1
    for mask in range(1 << gaps):
        lines: list[str] = []
        current = [words[0]]
        for index in range(gaps):
            if mask & (1 << index):
                lines.append(" ".join(current))
                current = [words[index + 1]]
            else:
                current.append(words[index + 1])
        lines.append(" ".join(current))
        out.append(lines)
    return out


def _measure(draw, lines: list[str], font_key: str, box_px: tuple[int, int],
             spacing: float) -> tuple[int, list[str]]:
    """The largest whole-pixel font at which these exact lines fit."""
    width_px, height_px = box_px
    low, high = 1, max(2, height_px)
    best = 0
    while low <= high:
        mid = (low + high) // 2
        font = fonts.load(font_key, mid)
        used_w, used_h = ri._text_extent(draw, lines, font, spacing)
        if used_w <= width_px and used_h <= height_px:
            best = mid
            low = mid + 1
        else:
            high = mid - 1
    return best, lines


def fit(text: str, stock, *, font: str = "sans-bold", dpi: int = 300,
        rotate: int = 0, spacing: float = 1.05,
        max_mm: float | None = None, uppercase: bool = False) -> Fit:
    """The biggest legible arrangement of `text` on `stock`.

    Returns a real `Label` — the same document type the designer produces —
    so a quick print can be opened in the designer and adjusted, and so
    there is exactly one thing that gets rendered. A quick-print path that
    rendered its own way would be a second renderer to keep in step with the
    first.
    """
    from PIL import ImageDraw  # noqa: PLC0415

    words = [w for w in str(text or "").split() if w]
    if uppercase:
        words = [w.upper() for w in words]
    if not words:
        raise ValueError("There is nothing to print — type a word first.")

    across_mm, feed_mm = stock.drawable_mm
    canvas_w_mm, canvas_h_mm = ((feed_mm, across_mm) if rotate in (90, 270)
                                else (across_mm, feed_mm))
    width_px = ri.mm_to_dots(canvas_w_mm, dpi)
    height_px = ri.mm_to_dots(canvas_h_mm, dpi)
    # The same breathing room the renderer will take off this box when it
    # draws the label. Measuring against the full canvas and rendering
    # against the inset one is two answers to "how big does this go", and
    # the one on screen would be the smaller of them.
    inset = ri.text_inset(width_px, height_px)
    width_px = max(1, width_px - 2 * inset)
    height_px = max(1, height_px - 2 * inset)

    plate = ri._new(8, 8)
    draw = ImageDraw.Draw(plate)

    if len(words) <= _MAX_WORDS_FOR_SEARCH:
        candidates = _arrangements(words)
    else:
        # Greedy per line-count: the exhaustive search is exponential and a
        # 20-word label is not a label anybody is squinting at anyway.
        candidates = []
        for count in range(1, min(len(words), 6) + 1):
            per = -(-len(words) // count)
            candidates.append([" ".join(words[i:i + per])
                               for i in range(0, len(words), per)])

    best_size, best_lines = 0, words[:1]
    for lines in candidates:
        size, used = _measure(draw, lines, font, (width_px, height_px), spacing)
        # Strictly greater, so the FIRST arrangement wins a tie — and
        # `_arrangements` yields the fewest-lines version first. Two layouts
        # at the same glyph size is a tie a person breaks by preferring the
        # one that is not needlessly stacked.
        if size > best_size:
            best_size, best_lines = size, used

    size_mm = best_size / dpi * 25.4
    ceiling = max_mm if max_mm is not None else canvas_h_mm
    if ceiling and size_mm > ceiling:
        size_mm = ceiling

    label = Label(
        stock=getattr(stock, "id", ""),
        rotate=rotate,
        name=" ".join(words)[:60],
        elements=[Element.from_dict({
            "type": "text",
            "x_mm": 0.0,
            "y_mm": 0.0,
            "w_mm": canvas_w_mm,
            "h_mm": canvas_h_mm,
            "props": {
                "text": "\n".join(best_lines),
                "font": font,
                # 0 means "fit the box", which is what we just computed —
                # but the CAP is a real size, so a capped label has to say
                # so rather than re-fitting to the box and undoing it.
                "size_mm": 0 if size_mm >= (best_size / dpi * 25.4) else size_mm,
                "align": "center",
                "valign": "middle",
                "wrap": False,
                "line_spacing": spacing,
            },
        })],
    )
    return Fit(lines=best_lines, size_mm=size_mm, label=label)
