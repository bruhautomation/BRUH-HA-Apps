#!/usr/bin/env python3
"""Shapes a trusted edit can ask for, expanded to the cells they cover.

A tree, a rock or a tower described block by block is thousands of blocks a
caller has to work out and send; described as shapes it is a few lines:

* `line {from, to, radius, radius_end?}` — a trunk or branch: every cell
  within the radius of the segment (flat at both ends), the radius going
  from `radius` at `from` to `radius_end` at `to`;
* `ellipsoid {center, radii, hollow?}` — `radii` is [x, y, z];
* `blob {center, radius, density 0–1, seed}` — foliage, a boulder, a bush:
  a sphere whose edge is roughened by smooth noise and whose inside keeps
  `density` of its cells, the same cells for the same seed;
* `cylinder {base, height, radius, radius_top?, hollow?}` — upright, from
  `base` up;
* `box {from, to, hollow?}`.

Points are [x, y, z] (or {x, y, z}); with a `base` they are offsets from it
(at most `reach` blocks). Radii are blocks; a cell is in when its centre is
within the radius plus half a block, so radius 0 is a one-block line.
Nothing here knows about blocks or the server: `companion.edit` gives each
shape its block, takes the cells into its undo snapshot and writes them.
"""
from __future__ import annotations

import math
from typing import Any

MAX_RADIUS = 64
MAX_HEIGHT = 384
Y_MIN, Y_MAX = -64, 319
KINDS = ("line", "ellipsoid", "blob", "cylinder", "box")
Cell = tuple[int, int, int]


class ShapeError(ValueError):
    """A shape that cannot be made as given; the message says why."""


def _num(shape: dict[str, Any], key: str, lo: float, hi: float, default: Any = None) -> float:
    value = shape.get(key, default)
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ShapeError(f"A {shape.get('kind')}'s {key} is a number.") from None
    if not lo <= v <= hi:
        raise ShapeError(f"A {shape.get('kind')}'s {key} is from {lo:g} to {hi:g}.")
    return v


def _point(shape: dict[str, Any], key: str, base: list[int] | None, reach: int) -> list[int]:
    value = shape.get(key)
    if isinstance(value, dict):
        value = [value.get(k) for k in ("x", "y", "z")]
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        raise ShapeError(f"A {shape.get('kind')}'s {key} is [x, y, z].")
    try:
        p = [int(math.floor(float(v))) for v in value]
    except (TypeError, ValueError):
        raise ShapeError(f"A {shape.get('kind')}'s {key} is three numbers.") from None
    if base is not None:
        if any(abs(v) > reach for v in p):
            raise ShapeError(f"Offsets are at most {reach} blocks.")
        p = [v + base[i] for i, v in enumerate(p)]
    return p


def _flag(shape: dict[str, Any], key: str) -> bool:
    return shape.get(key) in (True, "true", 1, "1")


def _check(estimate: float, limit: int) -> None:
    if estimate > limit * 1.25:
        raise ShapeError(f"That shape is about {int(estimate)} blocks; one edit is at most "
                         f"{limit}, so split it.")


def _mix(*nums: int) -> int:
    """A well-mixed 64-bit hash of a few integers (splitmix64)."""
    h = 0x9E3779B97F4A7C15
    for n in nums:
        h = (h ^ (n & 0xFFFFFFFFFFFFFFFF)) * 0xBF58476D1CE4E5B9 & 0xFFFFFFFFFFFFFFFF
        h ^= h >> 31
        h = h * 0x94D049BB133111EB & 0xFFFFFFFFFFFFFFFF
        h ^= h >> 29
    return h


def _unit(*nums: int) -> float:
    return (_mix(*nums) >> 11) / float(1 << 53)


def _noise(x: float, y: float, z: float, seed: int) -> float:
    """Smooth value noise in [0, 1]: lattice values, trilinear with smoothstep."""
    x0, y0, z0 = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = x - x0, y - y0, z - z0
    sx, sy, sz = (f * f * (3 - 2 * f) for f in (fx, fy, fz))
    total = 0.0
    for dx in (0, 1):
        wx = sx if dx else 1 - sx
        for dy in (0, 1):
            wy = sy if dy else 1 - sy
            for dz in (0, 1):
                wz = sz if dz else 1 - sz
                total += wx * wy * wz * _unit(seed, x0 + dx, y0 + dy, z0 + dz)
    return total


def line(a: list[int], b: list[int], r0: float, r1: float, limit: int) -> set[Cell]:
    length = math.dist(a, b)
    _check(math.pi * max(r0, r1, 0.5) ** 2 * (length + 1), limit)
    d = [b[i] - a[i] for i in range(3)]
    ll = length * length
    out: set[Cell] = set()
    checked: set[Cell] = set()
    steps = max(1, math.ceil(length / 0.5))
    for s in range(steps + 1):
        t = s / steps
        p = [a[i] + d[i] * t for i in range(3)]
        centre = tuple(math.floor(v + 0.5) for v in p)
        out.add(centre)
        r = r0 + (r1 - r0) * t
        reach = math.ceil(r + 1)
        for x in range(centre[0] - reach, centre[0] + reach + 1):
            for y in range(centre[1] - reach, centre[1] + reach + 1):
                for z in range(centre[2] - reach, centre[2] + reach + 1):
                    c = (x, y, z)
                    if c in checked:
                        continue
                    checked.add(c)
                    v = (x - a[0], y - a[1], z - a[2])
                    u = (v[0] * d[0] + v[1] * d[1] + v[2] * d[2]) / ll if ll else 0.0
                    if not -1e-9 <= u <= 1 + 1e-9:
                        continue
                    q = (v[0] - d[0] * u, v[1] - d[1] * u, v[2] - d[2] * u)
                    rr = r0 + (r1 - r0) * u + 0.5
                    if q[0] * q[0] + q[1] * q[1] + q[2] * q[2] <= rr * rr:
                        out.add(c)
    return out


def ellipsoid(c: list[int], radii: list[float], hollow: bool, limit: int) -> set[Cell]:
    rx, ry, rz = (r + 0.5 for r in radii)
    _check((4 / 3) * math.pi * rx * ry * rz * (0.5 if hollow else 1), limit)
    ix, iy, iz = (max(r - 0.5, 0.0) for r in radii)
    out: set[Cell] = set()
    for dx in range(-math.floor(rx), math.floor(rx) + 1):
        for dy in range(-math.floor(ry), math.floor(ry) + 1):
            rem = 1 - (dx / rx) ** 2 - (dy / ry) ** 2
            if rem < 0:
                continue
            zr = rz * math.sqrt(rem)
            for dz in range(-math.floor(zr), math.floor(zr) + 1):
                if hollow and ix and iy and iz and \
                        (dx / ix) ** 2 + (dy / iy) ** 2 + (dz / iz) ** 2 < 1:
                    continue
                out.add((c[0] + dx, c[1] + dy, c[2] + dz))
    return out


def blob(c: list[int], radius: float, density: float, seed: int, limit: int) -> set[Cell]:
    R = radius + 0.5
    _check((4 / 3) * math.pi * R ** 3 * density, limit)
    scale = max(2.0, radius / 3)
    out: set[Cell] = set()
    n = math.floor(R)
    for dx in range(-n, n + 1):
        for dy in range(-n, n + 1):
            for dz in range(-n, n + 1):
                d2 = dx * dx + dy * dy + dz * dz
                if d2 > R * R:
                    continue
                edge = R * (0.7 + 0.3 * _noise(dx / scale, dy / scale, dz / scale, seed))
                if d2 > edge * edge:
                    continue
                if density < 1 and _unit(seed, 7, dx, dy, dz) >= density:
                    continue
                out.add((c[0] + dx, c[1] + dy, c[2] + dz))
    return out


def cylinder(base: list[int], height: int, r0: float, r1: float, hollow: bool,
             limit: int) -> set[Cell]:
    _check(math.pi * (max(r0, r1) + 0.5) ** 2 * height, limit)
    out: set[Cell] = set()
    for dy in range(height):
        r = r0 + (r1 - r0) * (dy / (height - 1) if height > 1 else 0)
        R = r + 0.5
        inner = (r - 0.5) ** 2 if hollow and r >= 1 else -1
        for dx in range(-math.floor(R), math.floor(R) + 1):
            zr = math.sqrt(max(0.0, R * R - dx * dx))
            for dz in range(-math.floor(zr), math.floor(zr) + 1):
                if dx * dx + dz * dz <= inner:
                    continue
                out.add((base[0] + dx, base[1] + dy, base[2] + dz))
    return out


def box(a: list[int], b: list[int], hollow: bool, limit: int) -> set[Cell]:
    (x1, x2), (y1, y2), (z1, z2) = (sorted((a[i], b[i])) for i in range(3))
    _check((x2 - x1 + 1) * (y2 - y1 + 1) * (z2 - z1 + 1), limit)
    out: set[Cell] = set()
    for x in range(x1, x2 + 1):
        for y in range(y1, y2 + 1):
            for z in range(z1, z2 + 1):
                if hollow and x1 < x < x2 and y1 < y < y2 and z1 < z < z2:
                    continue
                out.add((x, y, z))
    return out


def expand(shape: Any, base: list[int] | None = None, reach: int = 128,
           limit: int = 131072) -> set[Cell]:
    """The cells one shape covers (inside the world's height), or ShapeError."""
    if not isinstance(shape, dict):
        raise ShapeError("Each shape is {kind, block, …}.")
    kind = str(shape.get("kind") or "").strip().lower()
    if kind not in KINDS:
        raise ShapeError(f"A shape is one of {', '.join(KINDS)}.")
    hollow = _flag(shape, "hollow")
    if kind == "line":
        r0 = _num(shape, "radius", 0, MAX_RADIUS, 0)
        r1 = _num(shape, "radius_end", 0, MAX_RADIUS, r0)
        cells = line(_point(shape, "from", base, reach), _point(shape, "to", base, reach),
                     r0, r1, limit)
    elif kind == "ellipsoid":
        radii = shape.get("radii")
        if isinstance(radii, (int, float)):
            radii = [radii] * 3
        if not isinstance(radii, (list, tuple)) or len(radii) != 3:
            raise ShapeError("An ellipsoid's radii are [x, y, z].")
        rs = [_num({"kind": kind, "radii": r}, "radii", 0, MAX_RADIUS) for r in radii]
        cells = ellipsoid(_point(shape, "center", base, reach), rs, hollow, limit)
    elif kind == "blob":
        try:
            seed = int(shape.get("seed") or 0)
        except (TypeError, ValueError):
            raise ShapeError("A blob's seed is a whole number.") from None
        cells = blob(_point(shape, "center", base, reach),
                     _num(shape, "radius", 0, MAX_RADIUS), _num(shape, "density", 0, 1, 1),
                     seed, limit)
    elif kind == "cylinder":
        r0 = _num(shape, "radius", 0, MAX_RADIUS, 0)
        cells = cylinder(_point(shape, "base", base, reach),
                         int(_num(shape, "height", 1, MAX_HEIGHT)), r0,
                         _num(shape, "radius_top", 0, MAX_RADIUS, r0), hollow, limit)
    else:
        cells = box(_point(shape, "from", base, reach), _point(shape, "to", base, reach),
                    hollow, limit)
    return {c for c in cells if Y_MIN <= c[1] <= Y_MAX}


__all__ = ["expand", "ShapeError", "KINDS", "line", "ellipsoid", "blob", "cylinder", "box"]
