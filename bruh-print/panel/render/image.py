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
from dataclasses import dataclass
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

    def png(self, scale: int = 1) -> bytes:
        """A PNG of the label as it will print.

        Scaled with NEAREST, always. Any smoothing filter would show the
        preview a label the printer cannot make — soft edges on something
        that will come out hard — and the preview's whole job is to be
        believed.
        """
        from PIL import Image  # noqa: PLC0415

        image = self.image.convert("L")
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
            if not current or draw.textlength(trial, font=font) <= max_px:
                current = trial
                continue
            lines.append(current)
            current = word
            while draw.textlength(current, font=font) > max_px and len(current) > 1:
                cut = len(current) - 1
                while cut > 1 and draw.textlength(
                        current[:cut], font=font) > max_px:
                    cut -= 1
                lines.append(current[:cut])
                current = current[cut:]
        lines.append(current)
    return lines


def _text_extent(draw, lines: list[str], font, spacing: float) -> tuple[int, int]:
    if not lines:
        return 0, 0
    widest = max((draw.textlength(line, font=font) for line in lines),
                 default=0)
    ascent, descent = font.getmetrics()
    line_height = (ascent + descent) * spacing
    return int(math.ceil(widest)), int(math.ceil(line_height * len(lines)))


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

    spacing = float(element.props.get("line_spacing", 1.1) or 1.1)
    wrap = bool(element.props.get("wrap", True))
    font_key = str(element.props.get("font", "sans-bold"))
    size_mm = float(element.props.get("size_mm", 0) or 0)

    if size_mm > 0:
        size_px = max(1, mm_to_dots(size_mm, dpi) * scale)
        font = fonts.load(font_key, size_px)
        lines = (_wrap(draw, text, font, width * scale) if wrap
                 else text.split("\n"))
        used_w, used_h = _text_extent(draw, lines, font, spacing)
        if used_w > width * scale or used_h > height * scale:
            # A fixed size that does not fit is reported, never silently
            # shrunk. The person set a height on purpose — probably to match
            # another element — and quietly changing it is how two labels
            # that should look identical do not.
            notes.append(
                f"“{text.splitlines()[0][:24]}” is set to {size_mm:g}mm and "
                f"does not fit its box; it is clipped.")
    else:
        font, lines, _ = fit_text(
            draw, text, font_key, (width * scale, height * scale),
            wrap=wrap, spacing=spacing)

    ascent, descent = font.getmetrics()
    line_height = (ascent + descent) * spacing
    block_height = line_height * len(lines)

    valign = element.props.get("valign", "middle")
    if valign == "top":
        cursor = 0.0
    elif valign == "bottom":
        cursor = height * scale - block_height
    else:
        cursor = (height * scale - block_height) / 2

    align = element.props.get("align", "center")
    for line in lines:
        line_width = draw.textlength(line, font=font)
        if align == "left":
            x = 0.0
        elif align == "right":
            x = width * scale - line_width
        else:
            x = (width * scale - line_width) / 2
        draw.text((x, cursor), line, font=font, fill=0)
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
        text_w = sub_draw.textlength(line, font=font)
        sub_draw.text(((width - text_w) / 2, 0), line, font=font, fill=0)
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

    for element in label.elements:
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
    )


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
