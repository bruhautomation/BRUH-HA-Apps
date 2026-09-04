#!/usr/bin/env python3
"""Turning a label into dots, once, for both consumers.

`render()` produces a 1-bit PIL image at the printer's own resolution, and
that same image is what the preview shows and what `raster_lines()` packs
into the bytes the printer gets. One rendering, two consumers: a preview
drawn by a second implementation is a preview of the second implementation,
and it would look right while the label came out blank.

Two details are load-bearing and both are about the head being one bit deep.

*Nothing is anti-aliased.* Text is drawn onto a greyscale canvas and
thresholded, images are converted with an explicit black point, and every
barcode bar is a whole number of dots wide. A thermal head has no grey: a
50% pixel is a black one, so an anti-aliased hairline becomes a solid line
and an anti-aliased bar becomes a bar one dot wider than the scanner
expects.

*Ink is 1 and paper is 0.* PIL's mode-"1" convention is the other way round
(255 is white), so the flip happens exactly once, in `raster_lines`, and
everything above it thinks in ink. Doing it per-element is how you get one
element rendered as its own negative.
"""
from __future__ import annotations

import io
import math
from dataclasses import dataclass, field
from pathlib import Path

from . import barcode, fonts
from .label import Element, Label

# Text is drawn on a 4x supersampled greyscale canvas and downsampled before
# thresholding. Not for smoothness — the threshold throws that away — but
# for *placement*: a 2mm-tall glyph is 23 dots, and rounding its stem to the
# nearest whole dot at 1x makes the difference between a readable 5 and a 6.
SUPERSAMPLE = 4

# Where the greyscale becomes ink. 128 is the middle, and the middle is
# right for text: DejaVu's stems at small sizes land either side of it
# cleanly, where a lower value fattens every glyph by a dot.
TEXT_THRESHOLD = 128


class RenderError(ValueError):
    """A label that cannot be drawn, with the reason a person can act on."""


@dataclass(frozen=True)
class Rendered:
    """The finished label, plus what it took to get there."""

    image: object            # PIL.Image, mode "1"
    across_dots: int
    feed_dots: int
    dpi: int
    notes: list[str]
    # The same messages, with the element each one is about. `notes` is what
    # everything already reads and stays exactly as it was — a sentence a
    # person can act on, whether or not there is an element behind it (the
    # head-width note and the continuous-length note are about the label).
    # `problems` is the half the designer can DRAW: it is what puts a red
    # outline on the barcode that will not fit rather than a line of prose
    # under a canvas with six boxes on it.
    problems: list = field(default_factory=list)

    def png(self, scale: int = 1, *, turn: int = 0) -> bytes:
        """A PNG of the label as it will print.

        Scaled with NEAREST, always. Any smoothing filter would show the
        preview a label the printer cannot make — soft edges on something
        that will come out hard — and the preview's whole job is to be
        believed.

        `turn` is for the designer and nothing else. `render` turns the design
        canvas by -rotate on its way to the sheet, so the sheet of a 90° label
        is the label as it comes off the roll: a 0.56" × 3.44" tube wrap is a
        tall strip with its words lying on their side. That is the right
        picture on the Quick tab and the wrong one under a drag overlay whose
        coordinates are the CANVAS's — the box you are holding and the ink it
        describes were in two different places, which is what made a
        wrap-around label undesignable. Turning the finished sheet back by
        +rotate recovers the canvas exactly, margins and clipping included,
        without a second render: same bitmap, held the way you drew it.
        """
        from PIL import Image  # noqa: PLC0415

        image = self.image.convert("L")
        if turn % 360:
            image = image.rotate(turn % 360, expand=True)
        if scale > 1:
            image = image.resize(
                (image.width * scale, image.height * scale),
                Image.Resampling.NEAREST)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue()


def mm_to_dots(mm: float, dpi: int) -> int:
    return int(round(mm / 25.4 * dpi))


def _new(width: int, height: int, colour: int = 255):
    from PIL import Image  # noqa: PLC0415
    return Image.new("L", (max(1, width), max(1, height)), colour)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------
def _line_ink(draw, line: str, font,
              exact: bool = False) -> tuple[float, float, float, float]:
    """One line's INK box, relative to the origin `draw.text` would be given.

    `textlength` is the advance width — where the *next* glyph would start —
    and it is neither the left nor the right edge of what gets drawn. A "W"
    hangs past its advance on both sides and a "j" starts left of its origin,
    so a box fitted to advances puts ink outside itself on both ends. This is
    the measurement everything here fits and places by.

    There are two answers and both are wanted. `textbbox` is FreeType's own
    box, which is cheap and a genuine *bound* — but it carries the last
    glyph's right side bearing, so on "Jam" at label sizes it reads about 4%
    wider than the ink and a block centred on it sits six dots left of
    centre. `exact=True` renders the mask and reads its real edges, which is
    what the placement uses: once per line, where the fit's bisection asks
    hundreds of times and has to stay cheap. Fitting to the bound and placing
    by the ink is the safe direction round — the drawn line is always inside
    the box the fitter reserved for it.
    """
    if not line:
        return (0.0, 0.0, 0.0, 0.0)
    if exact:
        measured = _mask_ink(draw, line, font)
        if measured is not None:
            return measured
    box = draw.textbbox((0, 0), line, font=font)
    return (float(box[0]), float(box[1]), float(box[2]), float(box[3]))


def _mask_ink(draw, line: str, font):
    """The real ink box, by rendering the glyphs and looking.

    `None` for a font that cannot be asked — `ImageFont.load_default()` on an
    image with no TrueType fonts at all — because the bound is still a right
    answer there and a renderer that raised would be a label that does not
    print over a rounding difference.
    """
    try:
        mask, offset = font.getmask2(line, draw.fontmode)
    except (AttributeError, TypeError, ValueError):  # pragma: no cover
        return None
    box = mask.getbbox()
    if box is None:
        return None
    return (float(offset[0] + box[0]), float(offset[1] + box[1]),
            float(offset[0] + box[2]), float(offset[1] + box[3]))


def _ink_width(draw, line: str, font) -> float:
    """How wide this line's ink is — not how far the cursor would move."""
    x0, _, x1, _ = _line_ink(draw, line, font)
    return max(0.0, x1 - x0)


def _ink_extent(draw, lines: list[str], font, spacing: float,
                exact: bool = False) -> tuple[int, int, float, float]:
    """The ink block: how big it is, and where it sits relative to the cursor.

    Line *pitch* is still `(ascent + descent) * spacing`, because that is what
    keeps two lines of different words the same distance apart — pitching by
    ink would make "no one" and "Wg Hj" different paragraphs. What changed is
    the block's outside: its top is the first line's ink top and its bottom
    the last line's ink bottom, not a line box that reserves room for
    ascenders and descenders no glyph here uses. DejaVu's line box is about
    1.29em against a cap height of 0.73em, so fitting to it left a word
    filling barely half the height it was given while sitting hard against the
    left and right edges.

    The two offsets are what makes the placement exact: `offset_y` is where
    the ink starts relative to the first line's draw origin, and `offset_x`
    the block's left overhang. Draw at (target - offset) and the ink lands
    where it was asked to.
    """
    if not lines:
        return 0, 0, 0.0, 0.0
    ascent, descent = font.getmetrics()
    pitch = (ascent + descent) * spacing
    width = 0.0
    left = top = bottom = None
    for index, line in enumerate(lines):
        x0, y0, x1, y1 = _line_ink(draw, line, font, exact=exact)
        if x1 <= x0 and y1 <= y0:
            # A blank line carries no ink and still owns its pitch, which is
            # the whole reason somebody typed it.
            continue
        offset = index * pitch
        width = max(width, x1 - x0)
        left = x0 if left is None else min(left, x0)
        top = offset + y0 if top is None else min(top, offset + y0)
        bottom = offset + y1 if bottom is None else max(bottom, offset + y1)
    if top is None:
        return 0, 0, 0.0, 0.0
    return (int(math.ceil(width)), int(math.ceil(bottom - top)),
            float(left), float(top))


# Breathing room inside every text box, on all four sides. A glyph whose stem
# touches the edge of its box reads as clipped even when every dot of it is
# there — and on a LabelWriter the box is often the label, where the printer's
# own registration wanders by a fraction of a millimetre either way. Two per
# cent of the box's shorter side, and never less than one dot: a proportion
# alone disappears on a 0.56" strip, and a fixed number of dots eats a small
# label while doing nothing for a big one.
TEXT_INSET_FRACTION = 0.02


def text_inset(width: int, height: int) -> int:
    """The inset, in dots, for a text box of this size."""
    return max(1, int(round(TEXT_INSET_FRACTION * min(width, height))))


def _wrap(draw, text: str, font, max_px: int) -> list[str]:
    """Greedy wrap on spaces, then on characters when a single word is wider.

    Breaking mid-word is the right answer here even though it is the wrong
    answer in prose: label text is one long identifier at least as often as
    it is a sentence, and a 24-character name on a 0.56" label that
    refuses to break is a line that runs off the edge and silently loses its
    tail.
    """
    lines: list[str] = []
    for paragraph in text.split("\n"):
        if not paragraph:
            lines.append("")
            continue
        current = ""
        for word in paragraph.split(" "):
            trial = f"{current} {word}".strip()
            if not current or _ink_width(draw, trial, font) <= max_px:
                current = trial
                continue
            lines.append(current)
            current = word
            while _ink_width(draw, current, font) > max_px and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and _ink_width(
                        draw, current[:cut], font) > max_px:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
        lines.append(current)
    return lines


def _text_extent(draw, lines: list[str], font, spacing: float) -> tuple[int, int]:
    """How big this block of lines actually is, in ink.

    Kept as a name because it is the one measurement three callers share —
    `fit_text`, the fixed-size check in `_draw_text`, and `quick._measure`.
    One measurement, three consumers: a fitter measuring line boxes while the
    drawer places ink is how a label comes out visibly smaller than its box
    and touching the edge at the same time.
    """
    width, height, _, _ = _ink_extent(draw, lines, font, spacing)
    return width, height


def fit_text(draw, text: str, font_key: str, box_px: tuple[int, int],
             *, wrap: bool, spacing: float,
             max_px: int | None = None) -> tuple[object, list[str], int]:
    """The largest size that fits, found by bisection rather than by stepping.

    Stepping down from a guess is what a first cut does and it is
    quadratically slow on the case that matters — a two-character word on a
    long label wants a size in the hundreds of pixels, so stepping finds it
    in hundreds of font loads. Bisection finds it in about eight, and the
    font cache makes each of those free the second time a template renders.

    The returned size is never 0: a box too small for even one pixel of text
    still gets the smallest font, so an over-full template shows something
    unreadable rather than showing nothing, which is the failure people
    cannot diagnose.
    """
    width_px, height_px = box_px
    ceiling = max_px if max_px is not None else max(4, height_px * 2)
    low, high = 1, max(1, int(ceiling))
    best_size, best_lines = 1, [text]

    while low <= high:
        mid = (low + high) // 2
        font = fonts.load(font_key, mid)
        lines = (_wrap(draw, text, font, width_px) if wrap
                 else text.split("\n"))
        used_w, used_h = _text_extent(draw, lines, font, spacing)
        if used_w <= width_px and used_h <= height_px:
            best_size, best_lines = mid, lines
            low = mid + 1
        else:
            high = mid - 1

    return fonts.load(font_key, best_size), best_lines, best_size


def _draw_text(canvas, element: Element, box: tuple[int, int, int, int],
               dpi: int, notes: list[str]) -> None:
    from PIL import Image, ImageDraw  # noqa: PLC0415

    text = str(element.props.get("text", "") or "")
    if not text.strip():
        return

    x0, y0, width, height = box
    rotate = int(element.props.get("rotate", 0) or 0)
    if rotate in (90, 270):
        width, height = height, width

    scale = SUPERSAMPLE
    plate = _new(width * scale, height * scale, 255)
    draw = ImageDraw.Draw(plate)

    # The inset is taken off the box before anything is fitted into it, so
    # the size that comes back already accounts for the breathing room —
    # fitting to the full box and then nudging the result inwards would push
    # the ink back out of the other side.
    inset = text_inset(width, height) * scale
    box_w = max(1, width * scale - 2 * inset)
    box_h = max(1, height * scale - 2 * inset)

    spacing = float(element.props.get("line_spacing", 1.1) or 1.1)
    wrap = bool(element.props.get("wrap", True))
    font_key = str(element.props.get("font", "sans-bold"))
    size_mm = float(element.props.get("size_mm", 0) or 0)

    if size_mm > 0:
        size_px = max(1, mm_to_dots(size_mm, dpi) * scale)
        font = fonts.load(font_key, size_px)
        lines = (_wrap(draw, text, font, box_w) if wrap
                 else text.split("\n"))
        used_w, used_h = _text_extent(draw, lines, font, spacing)
        if used_w > box_w or used_h > box_h:
            # A fixed size that does not fit is reported, never silently
            # shrunk. The person set a height on purpose — probably to match
            # another element — and quietly changing it is how two labels
            # that should look identical do not.
            notes.append(
                f"“{text.splitlines()[0][:24]}” is set to {size_mm:g}mm and "
                f"does not fit its box; it is clipped.")
    else:
        font, lines, _ = fit_text(
            draw, text, font_key, (box_w, box_h),
            wrap=wrap, spacing=spacing)

    ascent, descent = font.getmetrics()
    line_height = (ascent + descent) * spacing
    _, block_height, _, block_top = _ink_extent(draw, lines, font, spacing,
                                                exact=True)

    valign = element.props.get("valign", "middle")
    if valign == "top":
        top = float(inset)
    elif valign == "bottom":
        top = inset + box_h - block_height
    else:
        top = inset + (box_h - block_height) / 2
    # `block_top` is where the ink starts relative to the first line's own
    # draw origin, so subtracting it is what puts the INK at `top` rather
    # than putting the line box there and leaving the ink somewhere inside
    # it. This is the whole difference between a word that looks centred and
    # one that sits high in its box.
    cursor = top - block_top

    align = element.props.get("align", "center")
    for line in lines:
        left, _, right, _ = _line_ink(draw, line, font, exact=True)
        line_width = right - left
        if align == "left":
            x = float(inset)
        elif align == "right":
            x = inset + box_w - line_width
        else:
            x = inset + (box_w - line_width) / 2
        # Minus the line's own left bearing, for the same reason: a "j" or an
        # italic "W" starts left of where it is drawn from.
        draw.text((x - left, cursor), line, font=font, fill=0)
        cursor += line_height

    plate = plate.resize((max(1, width), max(1, height)),
                         Image.Resampling.LANCZOS)
    plate = plate.point(lambda v: 0 if v < TEXT_THRESHOLD else 255)

    if element.props.get("invert"):
        plate = plate.point(lambda v: 255 - v)
    if rotate:
        plate = plate.rotate(rotate, expand=True)

    canvas.paste(plate, (x0, y0), mask=plate.point(lambda v: 255 - v))


# ---------------------------------------------------------------------------
# Barcode
# ---------------------------------------------------------------------------
def _draw_barcode(canvas, element: Element, box: tuple[int, int, int, int],
                  dpi: int, notes: list[str]) -> None:
    from PIL import ImageDraw  # noqa: PLC0415

    data = str(element.props.get("data", "") or "")
    if not data:
        return

    x0, y0, width, height = box
    rotate = int(element.props.get("rotate", 0) or 0)
    if rotate in (90, 270):
        width, height = height, width

    modules = barcode.code128_modules(
        data, quiet_modules=int(element.props.get("quiet", 10)))

    # The module width is a whole number of dots or the barcode does not
    # scan. Fractional module widths are the classic small-label barcode
    # failure: the renderer rounds each bar independently, so a run of five
    # 1.4-dot bars comes out 1,1,2,1,2 and the scanner reads the wrong
    # widths. One integer, applied to every module, or the symbol is
    # narrower than its box and centred in it.
    module_px = max(1, width // max(1, len(modules)))
    symbol_px = module_px * len(modules)
    if symbol_px > width:
        notes.append(
            f"The barcode “{data[:20]}” needs {len(modules)} modules and the "
            f"box is only {width} dots wide — it cannot be printed at one "
            f"dot per module. Make the box wider, or shorten the data.")
        return

    hri = bool(element.props.get("hri", True))
    hri_px = (mm_to_dots(float(element.props.get("hri_mm", 2.5)), dpi)
              if hri else 0)
    bars_px = max(1, height - hri_px - (2 if hri else 0))

    plate = _new(width, height, 255)
    draw = ImageDraw.Draw(plate)
    offset = (width - symbol_px) // 2
    for index, ink in enumerate(modules):
        if not ink:
            continue
        left = offset + index * module_px
        draw.rectangle([left, 0, left + module_px - 1, bars_px - 1], fill=0)

    if hri and hri_px > 0:
        font_key = str(element.props.get("hri_font", "mono"))
        sub = _new(width, hri_px, 255)
        sub_draw = ImageDraw.Draw(sub)
        font, lines, _ = fit_text(
            sub_draw, data, font_key, (width, hri_px),
            wrap=False, spacing=1.0)
        line = lines[0] if lines else data
        left, _, right, _ = _line_ink(sub_draw, line, font, exact=True)
        _, _, _, top = _ink_extent(sub_draw, [line], font, 1.0, exact=True)
        sub_draw.text(((width - (right - left)) / 2 - left, -top),
                      line, font=font, fill=0)
        sub = sub.point(lambda v: 0 if v < TEXT_THRESHOLD else 255)
        plate.paste(sub, (0, height - hri_px))

    if rotate:
        plate = plate.rotate(rotate, expand=True)
    canvas.paste(plate, (x0, y0), mask=plate.point(lambda v: 255 - v))


# ---------------------------------------------------------------------------
# QR
# ---------------------------------------------------------------------------
def _draw_qr(canvas, element: Element, box: tuple[int, int, int, int],
             dpi: int, notes: list[str]) -> None:
    from PIL import ImageDraw  # noqa: PLC0415

    data = str(element.props.get("data", "") or "")
    if not data:
        return

    x0, y0, width, height = box
    matrix = barcode.qr_matrix(
        data,
        error_correction=str(element.props.get("ec", "M")),
        border=int(element.props.get("border", 2)),
    )
    count = len(matrix)
    # Square, and a whole number of dots per module, for the same reason the
    # barcode is: a QR whose modules are 3.5 dots wide is a QR with a
    # rounding error in every row.
    module_px = max(1, min(width, height) // count)
    side = module_px * count
    if side > min(width, height):
        notes.append(
            f"The QR code needs {count}×{count} modules and its box is only "
            f"{min(width, height)} dots — make it bigger or shorten the data.")
        return

    plate = _new(side, side, 255)
    draw = ImageDraw.Draw(plate)
    for row, cells in enumerate(matrix):
        for column, ink in enumerate(cells):
            if not ink:
                continue
            draw.rectangle(
                [column * module_px, row * module_px,
                 (column + 1) * module_px - 1, (row + 1) * module_px - 1],
                fill=0)

    canvas.paste(plate,
                 (x0 + (width - side) // 2, y0 + (height - side) // 2),
                 mask=plate.point(lambda v: 255 - v))


# ---------------------------------------------------------------------------
# Shapes and images
# ---------------------------------------------------------------------------
def _draw_box(canvas, element: Element, box: tuple[int, int, int, int],
              dpi: int, notes: list[str]) -> None:
    from PIL import ImageDraw  # noqa: PLC0415

    x0, y0, width, height = box
    draw = ImageDraw.Draw(canvas)
    stroke = max(0, mm_to_dots(float(element.props.get("stroke_mm", 0.4)), dpi))
    radius = max(0, mm_to_dots(float(element.props.get("radius_mm", 0)), dpi))
    rect = [x0, y0, x0 + width - 1, y0 + height - 1]
    if element.props.get("fill"):
        if radius:
            draw.rounded_rectangle(rect, radius=radius, fill=0)
        else:
            draw.rectangle(rect, fill=0)
        return
    if stroke <= 0:
        return
    if radius:
        draw.rounded_rectangle(rect, radius=radius, outline=0, width=stroke)
    else:
        draw.rectangle(rect, outline=0, width=stroke)


def _draw_line(canvas, element: Element, box: tuple[int, int, int, int],
               dpi: int, notes: list[str]) -> None:
    from PIL import ImageDraw  # noqa: PLC0415

    x0, y0, width, height = box
    draw = ImageDraw.Draw(canvas)
    stroke = max(1, mm_to_dots(float(element.props.get("stroke_mm", 0.4)), dpi))
    if width >= height:
        middle = y0 + height // 2
        draw.rectangle([x0, middle - stroke // 2,
                        x0 + width - 1, middle - stroke // 2 + stroke - 1],
                       fill=0)
    else:
        middle = x0 + width // 2
        draw.rectangle([middle - stroke // 2, y0,
                        middle - stroke // 2 + stroke - 1, y0 + height - 1],
                       fill=0)


def _draw_image(canvas, element: Element, box: tuple[int, int, int, int],
                dpi: int, notes: list[str], assets: Path | None) -> None:
    from PIL import Image  # noqa: PLC0415

    name = str(element.props.get("asset", "") or "")
    if not name or assets is None:
        return
    # The asset name is a filename in the asset folder and nothing else.
    # Resolving it and checking the parent is what stops "../../config/
    # secrets.yaml" being a valid image reference in a label somebody
    # imported — a label file is data from outside, even when the outside is
    # the person's own laptop.
    candidate = (assets / Path(name).name).resolve()
    if candidate.parent != assets.resolve() or not candidate.is_file():
        notes.append(f"The image “{name}” is not in this label's uploads.")
        return

    x0, y0, width, height = box
    try:
        source = Image.open(candidate)
        source.load()
    except (OSError, ValueError) as exc:
        notes.append(f"“{name}” could not be read as an image ({exc}).")
        return

    source = source.convert("L")
    fit = element.props.get("fit", "contain")
    if fit == "stretch":
        source = source.resize((max(1, width), max(1, height)),
                               Image.Resampling.LANCZOS)
    else:
        ratio = (max if fit == "cover" else min)(
            width / source.width, height / source.height)
        source = source.resize(
            (max(1, int(source.width * ratio)),
             max(1, int(source.height * ratio))),
            Image.Resampling.LANCZOS)

    if element.props.get("invert"):
        source = source.point(lambda v: 255 - v)

    if element.props.get("dither"):
        source = source.convert("1", dither=Image.Dither.FLOYDSTEINBERG)
        source = source.convert("L")
    else:
        threshold = int(element.props.get("threshold", 128))
        source = source.point(lambda v: 0 if v < threshold else 255)

    left = x0 + max(0, (width - source.width) // 2)
    top = y0 + max(0, (height - source.height) // 2)
    crop = source.crop((0, 0, min(source.width, width),
                        min(source.height, height)))
    canvas.paste(crop, (left, top), mask=crop.point(lambda v: 255 - v))


_DRAWERS = {
    "text": _draw_text,
    "barcode": _draw_barcode,
    "qr": _draw_qr,
    "box": _draw_box,
    "line": _draw_line,
}


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------
def render(label: Label, stock, *, dpi: int = 300, max_across_dots: int = 672,
           assets: Path | None = None) -> Rendered:
    """Draw a label at the printer's resolution.

    `max_across_dots` is the print head's real width and the canvas is
    clipped to it, not scaled down to it. A 2.25" label on a 2.24" head is
    three dot columns the printer physically cannot reach: scaling would
    shrink every element by half a percent to hide that, which makes a
    barcode's module width fractional — see the note in `_draw_barcode` for
    why that is the one thing that must not happen. Clipping loses three
    columns of margin instead, and says so.
    """

    notes: list[str] = []
    across_dots, feed_dots = stock.dots(dpi)

    if across_dots > max_across_dots:
        notes.append(
            f"This stock is {stock.across_in}\" across and the print head "
            f"reaches {max_across_dots / dpi:.2f}\" — the outer "
            f"{across_dots - max_across_dots} dot columns are the printer's "
            f"margin.")
        across_dots = max_across_dots

    if feed_dots <= 1:
        # Continuous stock: the label is as long as its artwork, with the
        # drawn content plus the margin deciding where it ends.
        extent = max((e.y_mm + e.h_mm for e in label.elements), default=25.0)
        feed_dots = max(mm_to_dots(extent + 2 * stock.margin_mm, dpi), 32)
        notes.append(
            f"Continuous stock: length taken from the artwork "
            f"({feed_dots / dpi:.2f}\").")

    margin_dots = mm_to_dots(stock.margin_mm, dpi)
    draw_w = max(1, across_dots - 2 * margin_dots)
    draw_h = max(1, feed_dots - 2 * margin_dots)

    canvas_w, canvas_h = ((draw_h, draw_w) if label.rotate in (90, 270)
                          else (draw_w, draw_h))
    canvas = _new(canvas_w, canvas_h, 255)

    problems: list[dict] = []
    for index, element in enumerate(label.elements):
        # Which notes this element is responsible for, taken by watching the
        # list rather than by threading an index through six drawers: a new
        # element type gets its problems drawn on the canvas by existing, and
        # cannot forget to report one.
        before = len(notes)
        x0 = mm_to_dots(element.x_mm, dpi)
        y0 = mm_to_dots(element.y_mm, dpi)
        width = mm_to_dots(element.w_mm, dpi)
        height = mm_to_dots(element.h_mm, dpi)
        # Clamped rather than refused: a box dragged half off a 0.56" label
        # is a finger on a phone, and printing the part that fits is more
        # useful than printing nothing.
        x0 = max(0, min(x0, canvas_w - 1))
        y0 = max(0, min(y0, canvas_h - 1))
        width = max(1, min(width, canvas_w - x0))
        height = max(1, min(height, canvas_h - y0))
        box = (x0, y0, width, height)
        try:
            if element.type == "image":
                _draw_image(canvas, element, box, dpi, notes, assets)
            else:
                _DRAWERS[element.type](canvas, element, box, dpi, notes)
        except barcode.BarcodeError as exc:
            notes.append(str(exc))
        except (OSError, ValueError) as exc:
            notes.append(f"{element.type} could not be drawn: {exc}")
        problems.extend({"index": index, "message": note}
                        for note in notes[before:])

    if label.rotate:
        canvas = canvas.rotate(-label.rotate, expand=True)
    if label.invert:
        canvas = canvas.point(lambda v: 255 - v)

    sheet = _new(across_dots, feed_dots, 255)
    sheet.paste(canvas, (margin_dots, margin_dots))
    return Rendered(
        image=sheet.point(lambda v: 0 if v < 128 else 255).convert("1"),
        across_dots=across_dots,
        feed_dots=feed_dots,
        dpi=dpi,
        notes=notes,
        problems=problems,
    )


# What a font sample says. Short enough to render at a readable size on a
# phone-width row, and it carries the four shapes people actually judge a
# label font by: capitals, lower case with an ascender and a descender, and
# digits — which is what a lot number is made of.
SAMPLE_TEXT = "Aa Bb Cc 0123"
SAMPLE_MAX_CHARS = 40


def sample_png(text: str, font_key: str, *, size_px: int = 28,
               pad: int = 3) -> bytes:
    """This font, drawn by the renderer that draws labels.

    A picker that previewed with a CSS font-family would be showing the
    browser's idea of "Monospace" beside a label printed in DejaVu Sans Mono
    — which is the failure a font preview exists to prevent, arriving in a
    new place. So this goes through `_draw_text`: same threshold, same
    supersample, same ink measurement. What comes back is what prints.

    Black ink on a transparent ground, so one image serves a light and a dark
    panel (the stylesheet inverts it, and inverting leaves alpha alone).
    """
    from PIL import Image  # noqa: PLC0415

    words = str(text or SAMPLE_TEXT)[:SAMPLE_MAX_CHARS] or SAMPLE_TEXT
    # Room for the widest plausible sample at this size, then cropped to the
    # ink — a fixed canvas would either clip a wide font or pad a narrow one
    # into a row of ragged whitespace.
    width = max(size_px * 4, int(size_px * 0.9 * len(words)))
    height = size_px * 3
    canvas = _new(width, height, 255)
    element = Element.from_dict({"type": "text", "props": {
        "text": words,
        "font": font_key,
        "size_mm": size_px / 300 * 25.4,
        "align": "left",
        "valign": "middle",
        "wrap": False,
        "line_spacing": 1.0,
    }})
    _draw_text(canvas, element, (0, 0, width, height), 300, [])

    ink = canvas.point(lambda v: 255 - v)
    box = ink.getbbox()
    if box is None:  # pragma: no cover - a font that drew nothing at all
        box = (0, 0, width, height)
    crop = (max(0, box[0] - pad), max(0, box[1] - pad),
            min(width, box[2] + pad), min(height, box[3] + pad))
    alpha = ink.crop(crop)
    out = Image.merge("LA", (_new(alpha.width, alpha.height, 0), alpha))
    buffer = io.BytesIO()
    out.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def raster_lines(rendered: Rendered, bytes_per_line: int) -> list[bytes]:
    """The image as packed raster rows, ink-is-1.

    PIL packs mode "1" MSB-first with 255 (white) as a set bit, which is the
    inverse of what the head wants — so the whole plane is inverted once,
    here, and every layer above this one gets to think in ink. `tobytes()`
    already pads each row to a byte boundary, which is why the row stride is
    computed rather than assumed equal to `bytes_per_line`.
    """
    image = rendered.image
    stride = (image.width + 7) // 8
    raw = image.tobytes()
    inverted = bytes(255 - b for b in raw)
    return [inverted[row * stride:(row + 1) * stride][:bytes_per_line]
            for row in range(image.height)]


# ---------------------------------------------------------------------------
# Where the printing starts
# ---------------------------------------------------------------------------
#
# **The manual DOES document a feed-direction print-position command, and it
# is deliberately not what this uses.** `<esc> f 1 n` Skip "n" Lines: *"use
# this command to force the LabelWriter printer to advance the number of
# lines corresponding to the variable n (0 to 255 lines). This command is put
# into the data buffer along with the print data so that it will take effect
# at the appropriate point in the data stream."* That is unambiguous, it is
# in the printer's own steps, and it is the right mechanism for exactly half
# of this problem. It cannot express the other half, and the other half is
# the one this feature exists for.
#
# A skip only ever moves paper FORWARD. The measured fault is a printer that
# begins laying ink 4.7mm AFTER the leading edge, so the correction has to
# move the artwork toward that edge — a negative skip, which is not a thing.
# Using `ESC f` for a positive offset and a raster shift for a negative one
# would give one control two behaviours at the sheet's edge as well: a skip
# pushes the tail of the raster past the die cut and into the gap, where the
# printer explicitly does not check ("the printer does not check for
# inter-label gap when printing. It is the responsibility of the host
# computer to avoid overrunning the label area"), while a raster shift keeps
# the sheet exactly one label long, so ink pushed off it is ink this add-on
# can SEE it is about to lose and say so. A control whose two directions
# report differently is a control nobody can read. And a skip is charged
# against the `ESC L` search budget on top of the print lines, which is the
# arithmetic that took three releases to get right once already.
#
# The across axis has the same shape of answer and the same conclusion.
# `ESC B n` (dot tab) is the documented mechanism and it is in whole BYTES of
# eight dots — 0.68mm a step, against a misregistration measured in tenths of
# a millimetre — it is likewise one-directional, and this add-on already
# sends `ESC B 0` in every preamble for an unrelated and more important
# reason (to clear whatever another driver left in the printer). Making the
# same byte carry a per-roll correction would mean the preamble could no
# longer state a known starting point, which is the whole reason it is sent.
#
# So: one mechanism, both axes, both directions, in the raster. The shift is
# in whole dots and it is rounded exactly ONCE, by `mm_to_dots` at the print
# resolution, which is the only place millimetres become dots in this file.

# Nothing here is applied to the label a person is DESIGNING. The offset is a
# correction to where the printer puts the sheet, not a change to the label,
# and a design canvas that drew it would be showing somebody their printer's
# registration as if it were their own layout.


def _ink_box(image):
    """The bounding box of the ink, or None for a blank sheet.

    `getbbox` finds the non-zero pixels, and in mode "1" the set bit is
    white — the paper. So the plane is inverted first, which is the same
    flip `raster_lines` makes for the same reason and in the same direction:
    everything above the wire thinks in ink.
    """
    return image.convert("L").point(lambda v: 255 - v).getbbox()


def offset_raster(rendered: Rendered, *, across_mm: float = 0.0,
                  feed_mm: float = 0.0) -> tuple[Rendered, str | None]:
    """The rendered sheet, moved to where this roll needs it printed.

    Returns the sheet to send and, when the shift pushes real INK off the
    label, one sentence saying so. Not when the shift is merely non-zero: a
    correction of a few millimetres normally slides blank margin off one
    edge and blank margin on at the other, which costs nothing, and a note on
    every print is a note nobody reads by the second roll. So the test is
    whether ink was lost, measured on the ink.

    `across_mm` is positive toward the right-hand edge as the label comes out
    of the printer, `feed_mm` positive away from the edge that comes out
    first. The sheet keeps its exact size: what moves off one edge is gone,
    and what moves on at the other is paper.
    """
    dpi = rendered.dpi
    across_dots = mm_to_dots(across_mm, dpi)
    feed_dots = mm_to_dots(feed_mm, dpi)
    if not across_dots and not feed_dots:
        return rendered, None

    image = rendered.image
    width, height = image.width, image.height
    box = _ink_box(image)

    sheet = _new(width, height, 255)
    # A negative paste origin is a crop, which is exactly the semantics
    # wanted here: the sheet is one label and stays one label.
    sheet.paste(image.convert("L"), (across_dots, feed_dots))
    moved = Rendered(
        image=sheet.point(lambda v: 0 if v < 128 else 255).convert("1"),
        across_dots=rendered.across_dots,
        feed_dots=rendered.feed_dots,
        dpi=dpi,
        # The SAME list objects, not copies. Everything that renders a label
        # reads `rendered.notes` after the print has gone out, so a note
        # added to either object has to be visible from both — the
        # alternative is threading a second notes list through five handlers
        # so that one of them can forget it.
        notes=rendered.notes,
        problems=rendered.problems,
    )
    if box is None:
        return moved, None

    x0, y0, x1, y1 = box
    lost = {
        "the leading edge": max(0, -(y0 + feed_dots)),
        "the trailing edge": max(0, (y1 + feed_dots) - height),
        "the left edge": max(0, -(x0 + across_dots)),
        "the right edge": max(0, (x1 + across_dots) - width),
    }
    clipped = [(name, dots) for name, dots in lost.items() if dots > 0]
    if not clipped:
        return moved, None

    where = " and ".join(f"{dots / dpi * 25.4:.1f}mm past {name}"
                         for name, dots in clipped)
    return moved, (
        f"This roll’s print offset moves the printing "
        f"{_offset_words(across_mm, feed_mm)}, so the artwork now runs "
        f"{where} — that much of it did not print. Change the offset on "
        f"the Printer tab, under “Where the printing starts”, or "
        f"move the artwork in from that edge.")


def _offset_words(across_mm: float, feed_mm: float) -> str:
    """The offset as a direction and a distance, never as a signed number.

    Nobody knows which way "+" goes on a label printer, which is the whole
    reason this reads as words: a note saying "offset -6.4mm" is a note that
    sends somebody to work out the convention before they can act on it.
    """
    parts = []
    if feed_mm:
        parts.append(f"{abs(feed_mm):.1f}mm "
                     + ("further along the roll" if feed_mm > 0
                        else "back toward the edge that comes out first"))
    if across_mm:
        parts.append(f"{abs(across_mm):.1f}mm "
                     + ("to the right" if across_mm > 0 else "to the left"))
    return " and ".join(parts) or "not at all"
