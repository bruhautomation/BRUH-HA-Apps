"""Free looks at a camera frame, with no model and no network.

A frame is shrunk to a small grey grid (ffmpeg, which the image already
ships for the RTSP cameras) and everything here is arithmetic over that
grid. Three questions, each cheap enough to ask every few seconds:

* CAN IT SEE? A covered lens is a flat picture — no detail anywhere, at any
  brightness (a cap, a closed shutter, tape) — and a dark chamber is a black
  one. The two differ by the light: dark with the chamber light ON is a
  covered lens; dark with it off is only dark. Neither is a picture worth a
  verdict, so the watcher stands everything down while it lasts.
* DID SOMETHING JUST HAPPEN? The toolhead is never still, so frame against
  frame always differs. A per-pixel median of the last few frames takes the
  toolhead out and leaves the plate; a print grows that slowly, while a part
  knocked off or a nest of spaghetti changes it at once. A jump far outside
  this print's own spread of changes is a reason to look now.
* IS THE PLATE EMPTY? The plate as it was before the first layer is kept,
  and a finished plate that looks like it again — lighting taken out — has
  been cleared.

None of it decides that a print has failed. It decides when to look, and
when a look would be pointless.
"""
from __future__ import annotations

import hashlib
import shutil
import statistics
import subprocess
from collections import deque
from dataclasses import dataclass

W, H = 48, 36
DECODE_TIMEOUT = 10

# A lens that sees nothing: hardly any variation and hardly any edges.
FLAT_STD = 5.0
FLAT_DETAIL = 2.0
# A chamber too dark to judge (0–255).
DARK_MEAN = 22.0
# The plate is the lower part of every Bambu camera's picture; the top is
# the frame and the gantry.
PLATE_TOP = 0.3
# Two pictures of the same plate under different light still differ by a
# little everywhere; a pixel that moved this far moved for a reason.
PIXEL_CHANGED = 22
# The plate counts as looking like the empty plate below these.
CLEAR_DIFF = 7.0
CLEAR_FRACTION = 0.05
# A sudden change: this many times this print's own spread above its usual
# change, and never less than the absolute floor.
SPIKE_SPREADS = 6.0
SPIKE_FLOOR = 9.0
SPIKE_MIN_HISTORY = 6
MEDIAN_OF = 5
COMPARE_BACK = 6


@dataclass(frozen=True)
class Grid:
    """A frame as W×H grey levels, row by row."""
    px: bytes
    w: int = W
    h: int = H

    def __post_init__(self):
        if len(self.px) != self.w * self.h:
            raise ValueError(f"a {self.w}×{self.h} grid is {self.w * self.h} bytes, not {len(self.px)}")

    def rows(self, top: float = 0.0) -> range:
        return range(int(self.h * top), self.h)

    def signature(self) -> str:
        return hashlib.sha1(self.px).hexdigest()[:16]


def decode(jpeg: bytes) -> Grid | None:
    """A JPEG as a grey grid, or None when it cannot be read."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not jpeg:
        return None
    try:
        done = subprocess.run(
            [ffmpeg, "-nostdin", "-loglevel", "error", "-f", "image2pipe", "-i", "pipe:0",
             "-vf", f"scale={W}:{H}:flags=area,format=gray", "-frames:v", "1",
             "-f", "rawvideo", "pipe:1"],
            input=jpeg, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=DECODE_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or len(done.stdout) != W * H:
        return None
    return Grid(done.stdout)


def stats(grid: Grid) -> dict:
    """Mean brightness, its spread, and how much edge there is (detail)."""
    px = grid.px
    mean = sum(px) / len(px)
    std = (sum((p - mean) ** 2 for p in px) / len(px)) ** 0.5
    edges, count = 0, 0
    w = grid.w
    for y in range(grid.h):
        row = y * w
        for x in range(w - 1):
            edges += abs(px[row + x] - px[row + x + 1])
            count += 1
    for y in range(grid.h - 1):
        row = y * w
        for x in range(w):
            edges += abs(px[row + x] - px[row + w + x])
            count += 1
    return {"mean": round(mean, 1), "std": round(std, 1),
            "detail": round(edges / count, 2) if count else 0.0}


def sharpness(grid: Grid, top: float = PLATE_TOP) -> float:
    """How much edge there is over the plate: a frame taken while the bed or
    the toolhead was moving is smeared, and a smear has less edge."""
    px, w = grid.px, grid.w
    total, count = 0, 0
    for y in grid.rows(top):
        row = y * w
        for x in range(w - 1):
            total += abs(px[row + x] - px[row + x + 1])
            count += 1
        if y + 1 < grid.h:
            for x in range(w):
                total += abs(px[row + x] - px[row + w + x])
                count += 1
    return total / count if count else 0.0


def sharpest(grids: list[Grid]) -> int:
    """The index of the steadiest of a burst of frames (the most edge)."""
    if not grids:
        raise ValueError("no grids")
    return max(range(len(grids)), key=lambda i: sharpness(grids[i]))


def view(grid: Grid, light_on: bool | None) -> str:
    """"ok", "covered" or "dark" — whether a look at this frame means anything."""
    s = stats(grid)
    if s["std"] < FLAT_STD and s["detail"] < FLAT_DETAIL and s["mean"] >= DARK_MEAN:
        return "covered"
    if s["mean"] < DARK_MEAN:
        return "covered" if light_on else "dark"
    return "ok"


def difference(a: Grid, b: Grid, top: float = PLATE_TOP) -> dict:
    """How far apart two frames of the plate are, with the light taken out.

    Each frame's own mean over the plate is subtracted first, so the chamber
    light going brighter is not the plate changing. `mean` is the average
    per-pixel distance (0–255) and `changed` the share of pixels that moved
    more than PIXEL_CHANGED.
    """
    if (a.w, a.h) != (b.w, b.h):
        raise ValueError("two grids of different sizes")
    rows = a.rows(top)
    idx = [y * a.w + x for y in rows for x in range(a.w)]
    if not idx:
        return {"mean": 0.0, "changed": 0.0}
    ma = sum(a.px[i] for i in idx) / len(idx)
    mb = sum(b.px[i] for i in idx) / len(idx)
    total, changed = 0.0, 0
    for i in idx:
        d = abs((a.px[i] - ma) - (b.px[i] - mb))
        total += d
        if d > PIXEL_CHANGED:
            changed += 1
    return {"mean": round(total / len(idx), 2), "changed": round(changed / len(idx), 4)}


def looks_like(current: Grid, reference: Grid) -> bool:
    """Whether the plate now looks like the reference (the empty plate)."""
    d = difference(current, reference)
    return d["mean"] < CLEAR_DIFF and d["changed"] < CLEAR_FRACTION


def median_grid(grids: list[Grid]) -> Grid:
    """Per-pixel median: what stayed put while the toolhead moved."""
    if not grids:
        raise ValueError("no grids")
    first = grids[0]
    columns = zip(*(g.px for g in grids))
    return Grid(bytes(int(statistics.median(c)) for c in columns), first.w, first.h)


class ChangeTracker:
    """Notices a sudden change to the plate while a print runs."""

    def __init__(self):
        self.recent: deque[Grid] = deque(maxlen=MEDIAN_OF)
        self.medians: deque[Grid] = deque(maxlen=COMPARE_BACK + 1)
        self.changes: deque[float] = deque(maxlen=60)
        self.last_signature = ""
        self.same_count = 0

    def reset(self) -> None:
        self.__init__()

    def add(self, grid: Grid) -> dict:
        """Take one frame; {"spike": bool, "change": float, "frozen": int}.

        `frozen` counts frames identical to the one before — a camera whose
        feed has stopped moving hands the same bytes back.
        """
        sig = grid.signature()
        self.same_count = self.same_count + 1 if sig == self.last_signature else 0
        self.last_signature = sig
        self.recent.append(grid)
        out = {"spike": False, "change": 0.0, "frozen": self.same_count}
        if len(self.recent) < self.recent.maxlen:
            return out
        self.medians.append(median_grid(list(self.recent)))
        if len(self.medians) <= COMPARE_BACK:
            return out
        change = difference(self.medians[-1], self.medians[0])["mean"]
        out["change"] = change
        if len(self.changes) >= SPIKE_MIN_HISTORY:
            usual = statistics.median(self.changes)
            spread = statistics.median(abs(c - usual) for c in self.changes) or 0.5
            out["spike"] = change > max(SPIKE_FLOOR, usual + SPIKE_SPREADS * spread)
        self.changes.append(change)
        return out
