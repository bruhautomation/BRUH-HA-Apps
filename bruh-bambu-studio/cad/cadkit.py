"""cadkit: the helpers a design script builds on.

Adapted from the create-a-thing skill. Conventions:

* Units are millimetres. Every part is modelled IN PRINT ORIENTATION: +Z up,
  the bed at Z = 0.
* A design is a dict {body name: cq.Workplane or cq.Shape}. Several bodies
  in one dict are one print-in-place job and stay aligned in the 3MF/STEP.

Entry points
  revolve(pts)                     closed (r, z) profile -> solid about Z
  thread_spec(name)                a verified thread from THREADS
  thread_ridge(spec, length, ...)  helical male ridge to union onto a core
  thread_groove(spec, length, ...) helical tool to CUT from a bore
  knurl_cut(r, z0, h, n, flute_r)  flute cutters for a grip
  validate(parts)                  validity / bed / interference / gaps / overhang
  export_all(parts, name, outdir)  STEP + per-body STL + a 3MF of one object, a part per body
"""
from __future__ import annotations

import json
import math
import os

import cadquery as cq
import numpy as np

import mf3

# Nominal thread data (d = major diameter, P = pitch, h = working depth,
# angle = included flank angle). Values here were checked against a
# standards table; anything not here must be looked up, not guessed —
# a wrong pitch looks perfect on screen and binds after two turns.
THREADS = {
    # DIN 40430 PG (80°).
    "PG7": dict(d=12.5, P=1.270, h=0.61, angle=80),
    "PG9": dict(d=15.2, P=1.411, h=0.67, angle=80),
    "PG11": dict(d=18.6, P=1.411, h=0.67, angle=80),
    "PG13.5": dict(d=20.4, P=1.411, h=0.67, angle=80),
    "PG16": dict(d=22.5, P=1.411, h=0.67, angle=80),
    "PG21": dict(d=28.3, P=1.588, h=0.76, angle=80),
    # ISO metric coarse (60°); h = 0.6134 P.
    **{f"M{d}": dict(d=d, P=p, h=round(0.6134 * p, 3), angle=60) for d, p in [
        (3, 0.5), (4, 0.7), (5, 0.8), (6, 1.0), (8, 1.25), (10, 1.5), (12, 1.75),
        (16, 2.0), (20, 2.5), (24, 3.0), (30, 3.5)]},
}


def thread_spec(name: str) -> dict:
    if name not in THREADS:
        raise KeyError(f"{name} is not in THREADS. Look it up, verify it, and add it.")
    return dict(THREADS[name], name=name)


def revolve(pts, angle=360):
    """Revolve a closed (r, z) polyline about the Z axis."""
    return cq.Workplane("XZ").polyline(pts).close().revolve(angle, (0, 0, 0), (0, 1, 0))


def _ridge_profile(r_in, r_out, P, h, angle, crest=None):
    half = math.radians(angle / 2)
    run = h * math.tan(half)
    crest = crest if crest is not None else max(0.08, 0.1 * P)
    root_w = min(crest + 2 * run, 0.80 * P)
    r_root = r_out - h
    # The flanks run on below the root into the core, so no flat is exposed.
    wi = root_w / 2 + (r_root - r_in) * math.tan(half)
    return [(r_in, -wi), (r_out, -crest / 2), (r_out, crest / 2), (r_in, wi)]


def thread_ridge(spec, length, z0=0.0, fit=0.3, lead_in=True, left_hand=False):
    """Male thread ridge. Union it onto a core cylinder of the returned radius.
    fit is the diametral undersize for FDM (0.2–0.4). Returns (ridge, r_core)."""
    P, h = spec["P"], spec["h"]
    r_maj = spec["d"] / 2 - fit / 2
    r_core = r_maj - h
    r_in = r_core - 0.15
    prof = cq.Workplane("XZ").polyline(_ridge_profile(r_in, r_maj, P, h, spec["angle"])).close()
    helix = cq.Wire.makeHelix(P, length + 2 * P, r_in, center=cq.Vector(0, 0, z0 - P),
                              lefthand=left_hand)
    ridge = prof.sweep(cq.Workplane().add(helix), isFrenet=True)
    ramp = (1.0 + h) if lead_in else 0.0
    trim = revolve([(0, z0), (r_core - 0.3, z0), (r_maj + 1, z0 + ramp + 0.2),
                    (r_maj + 1, z0 + length), (0, z0 + length)])
    return ridge.intersect(trim), r_core


def thread_groove(spec, length, z0=0.0, fit=0.3, left_hand=False):
    """Female thread cutting tool. Bore the hole to the returned radius, then
    .cut() the tool. Returns (tool, r_bore)."""
    P, h = spec["P"], spec["h"]
    r_maj = spec["d"] / 2 + fit / 2
    r_bore = r_maj - h
    prof = cq.Workplane("XZ").polyline(
        _ridge_profile(r_bore - 0.15, r_maj, P, h, spec["angle"])).close()
    helix = cq.Wire.makeHelix(P, length + 2 * P, r_bore - 0.15,
                              center=cq.Vector(0, 0, z0 - P), lefthand=left_hand)
    tool = prof.sweep(cq.Workplane().add(helix), isFrenet=True)
    trim = cq.Workplane("XY").workplane(offset=z0).circle(r_maj + 1).extrude(length)
    return tool.intersect(trim), r_bore


def knurl_cut(r, z0, h, n=18, flute_r=1.1):
    """n vertical flute cylinders on radius r, to .cut() from a grip."""
    out = None
    for i in range(n):
        a = 2 * math.pi * i / n
        c = (cq.Workplane("XY").workplane(offset=z0)
             .center(r * math.cos(a), r * math.sin(a)).circle(flute_r).extrude(h))
        out = c if out is None else out.union(c)
    return out


def solid(x):
    return x.val() if isinstance(x, cq.Workplane) else x


def mesh_of(shape, tol=0.05, ang=0.3):
    vs, fs = solid(shape).tessellate(tol, ang)
    return np.array([(v.x, v.y, v.z) for v in vs]), np.array(fs, dtype=np.int64)


def validate(parts: dict, gap_min=0.25):
    """The checks that catch the failures that actually ruin prints.

    Returns {bodies, pairs, warnings, blocking}. Blocking problems are an
    invalid solid and two bodies that overlap; everything else is a warning
    to fix or to carry into the print instructions.
    """
    rep = {"bodies": {}, "pairs": [], "warnings": [], "blocking": []}
    solids = {k: solid(v) for k, v in parts.items()}
    if not solids:
        rep["blocking"].append("PARTS is empty.")
        return rep
    zmin_all = min(s.BoundingBox().zmin for s in solids.values())
    if abs(zmin_all) > 1e-3:
        rep["warnings"].append(
            f"The lowest point is Z={zmin_all:.3f}, not 0. Model in print orientation on the bed.")
    for name, s in solids.items():
        bb = s.BoundingBox()
        valid = bool(s.isValid())
        v, f = mesh_of(s)
        tri = v[f]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        area = np.linalg.norm(n, axis=1) / 2
        nz = n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-12)
        zc = tri[:, :, 2].mean(axis=1)
        on_bed = zc < zmin_all + 0.05
        over = (nz < -math.cos(math.radians(25))) & ~on_bed
        overhang = float(area[over].sum())
        bed = float(area[on_bed & (nz < -0.99)].sum())
        rep["bodies"][name] = {
            "valid": valid, "volume_mm3": round(s.Volume(), 1),
            "bbox": [round(x, 2) for x in (bb.xmin, bb.ymin, bb.zmin, bb.xmax, bb.ymax, bb.zmax)],
            "size_mm": [round(bb.xlen, 2), round(bb.ylen, 2), round(bb.zlen, 2)],
            "bed_contact_mm2": round(bed, 1), "overhang_mm2": round(overhang, 1)}
        if not valid:
            rep["blocking"].append(f"{name} is not a valid solid.")
        if overhang > 5:
            rep["warnings"].append(
                f"{name}: {overhang:.0f} mm² of near-flat overhang. Chamfer it to 45° or plan supports.")
        if bed == 0 and bb.zmin < zmin_all + 0.05:
            rep["warnings"].append(f"{name} touches the bed with no flat face. Give it a flat.")
        if bb.zlen > 3 * max(min(bb.xlen, bb.ylen), 1) and bed < 50:
            rep["warnings"].append(f"{name} is tall on a small footprint and may tip. Use a brim.")
    names = list(solids)
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = solids[names[i]], solids[names[j]]
            pair = {"a": names[i], "b": names[j]}
            try:
                common = a.intersect(b).Volume()
            except Exception:  # noqa: BLE001 - an OCC boolean that fails is reported, not fatal
                common = None
            pair["overlap_mm3"] = round(common, 3) if common is not None else None
            if common and common > 1e-3:
                rep["blocking"].append(
                    f"{names[i]} and {names[j]} overlap by {common:.2f} mm³; they would print fused.")
            try:
                gap = a.distance(b)
                pair["gap_mm"] = round(gap, 3)
                if 1e-6 < gap < gap_min:
                    rep["warnings"].append(
                        f"{names[i]}–{names[j]} gap is {gap:.2f} mm, under {gap_min} mm; "
                        f"they may fuse when printed.")
            except Exception:  # noqa: BLE001 - distance is informative only
                pair["gap_mm"] = None
            rep["pairs"].append(pair)
    return rep


def export_all(parts: dict, name: str, outdir: str, colors: dict | None = None) -> dict:
    """STEP assembly, one STL per body, one combined STL and a 3MF whose
    parts each name their filament (by colour: see mf3)."""
    import trimesh

    os.makedirs(os.path.join(outdir, "bodies"), exist_ok=True)
    assembly = cq.Assembly(name=name)
    meshes = {}
    for body, shape in parts.items():
        s = solid(shape)
        assembly.add(s, name=body)
        path = os.path.join(outdir, "bodies", f"{body}.stl")
        cq.exporters.export(s, path, tolerance=0.02, angularTolerance=0.15)
        meshes[body] = trimesh.load(path, force="mesh")
    step = os.path.join(outdir, f"{name}.step")
    assembly.save(step)
    combined = trimesh.util.concatenate(list(meshes.values()))
    combined.export(os.path.join(outdir, f"{name}.stl"))
    # One object with a part per body, each part naming its filament (mf3).
    painted = mf3.write(os.path.join(outdir, f"{name}.3mf"), name,
                        {b: (m.vertices.tolist(), m.faces.tolist()) for b, m in meshes.items()},
                        colors)
    files = {"step": f"{name}.step", "stl": f"{name}.stl", "3mf": f"{name}.3mf",
             "bodies": {b: f"bodies/{b}.stl" for b in meshes}, **painted}
    with open(os.path.join(outdir, "files.json"), "w") as handle:
        json.dump(files, handle)
    return files
