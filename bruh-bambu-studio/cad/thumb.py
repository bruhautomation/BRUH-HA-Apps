"""A picture of a model file: thumb.py <model> <out.png> [size].

Run by the panel in the CAD virtualenv (/opt/cad), which has trimesh to read
STL, OBJ, AMF and 3MF and CadQuery to read STEP. The model is drawn from the
front-right corner, flat-shaded, back to front (the painter's algorithm) —
no OpenGL, so it works on a server with no screen at all. A 3MF that Bambu
Studio saved carries its own picture, and the panel uses that instead.
"""
from __future__ import annotations

import sys

import numpy as np
from PIL import Image, ImageDraw

MAX_FACES = 300_000
BASE = (63, 167, 230)


def load(path: str):
    import trimesh
    lower = path.lower()
    if lower.endswith((".step", ".stp")):
        import cadquery as cq
        shape = cq.importers.importStep(path)
        tmp = path + ".thumb.stl"
        cq.exporters.export(shape, tmp)
        path = tmp
    mesh = trimesh.load(path, force="mesh")
    return np.asarray(mesh.vertices, dtype=float), np.asarray(mesh.faces, dtype=int)


def render(vertices, faces, size: int = 256) -> Image.Image:
    if len(faces) > MAX_FACES:
        # Keep the biggest faces: they are what the outline is made of.
        tri = vertices[faces]
        area = np.linalg.norm(np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0]), axis=1)
        faces = faces[np.argsort(area)[-MAX_FACES:]]
    yaw, pitch = np.radians(-40), np.radians(30)
    rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, np.cos(pitch), -np.sin(pitch)], [0, np.sin(pitch), np.cos(pitch)]])
    # Model space is +Z up; the picture's y is down and its depth is +y.
    v = vertices @ rz.T
    v = v[:, [0, 2, 1]] * np.array([1, -1, 1])
    v = v @ rx.T
    lo, hi = v.min(axis=0), v.max(axis=0)
    span = max(hi[0] - lo[0], hi[1] - lo[1]) or 1.0
    scale = (size * 0.86) / span
    xy = (v[:, :2] - (lo[:2] + hi[:2]) / 2) * scale + size / 2
    tri = v[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    length = np.linalg.norm(normals, axis=1)
    keep = length > 0
    normals[keep] /= length[keep, None]
    light = np.array([-0.4, -0.7, -0.6])
    light /= np.linalg.norm(light)
    shade = np.clip(np.abs(normals @ light), 0, 1) * 0.65 + 0.35
    depth = tri[:, :, 2].mean(axis=1)
    order = np.argsort(-depth)
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    pts = xy[faces]
    for i in order:
        if not keep[i]:
            continue
        s = shade[i]
        colour = (int(BASE[0] * s), int(BASE[1] * s), int(BASE[2] * s), 255)
        draw.polygon([tuple(p) for p in pts[i]], fill=colour)
    return image


def main() -> int:
    if len(sys.argv) < 3:
        print("usage: thumb.py MODEL OUT.png [SIZE]", file=sys.stderr)
        return 2
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 256
    vertices, faces = load(sys.argv[1])
    if not len(faces):
        print("The file has no triangles.", file=sys.stderr)
        return 1
    render(vertices, faces, size).save(sys.argv[2], "PNG")
    return 0


if __name__ == "__main__":
    sys.exit(main())
