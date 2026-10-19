"""Write a design as a 3MF Bambu Studio reads as ONE object with a part per body.

trimesh writes each body as an object of its own, and Bambu Studio arranges
objects independently: a print-in-place part comes apart on the plate, and
there is no place to say which filament each body prints in. So the model
here is one object made of components (one per body), and
Metadata/model_settings.config gives each part its filament — the file
Bambu Studio itself writes, read by its importer for any 3MF. A body's
filament is the 1-based index of its colour among the distinct colours, in
body order; the panel rewrites those numbers when it knows which AMS tray
each body prints from.

Pure Python over vertex and face lists, so it is testable without the CAD
tools.
"""
from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import quoteattr

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
 <Default Extension="config" ContentType="text/xml"/>
</Types>
"""
RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel0" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>
"""


def extruders(names: list[str], colors: dict | None) -> tuple[list[str], dict]:
    """(distinct colours in body order, {body: 1-based filament})."""
    colors = colors or {}
    order: list[str] = []
    out = {}
    for name in names:
        colour = str(colors.get(name) or "").upper()
        if colour not in order:
            order.append(colour)
        out[name] = order.index(colour) + 1
    return order, out


def _mesh_xml(vertices, faces) -> str:
    rows = ["<mesh><vertices>"]
    rows += [f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in vertices]
    rows.append("</vertices><triangles>")
    rows += [f'<triangle v1="{int(a)}" v2="{int(b)}" v3="{int(c)}"/>' for a, b, c in faces]
    rows.append("</triangles></mesh>")
    return "\n".join(rows)


def model_settings(object_id: int, title: str, parts: list[tuple[int, str]],
                   filament: dict) -> str:
    """Metadata/model_settings.config: the object, and each part's filament."""
    first = filament.get(parts[0][1], 1) if parts else 1
    rows = ['<?xml version="1.0" encoding="UTF-8"?>', "<config>",
            f'  <object id="{object_id}">',
            f'    <metadata key="name" value={quoteattr(title)}/>',
            f'    <metadata key="extruder" value="{first}"/>']
    for part_id, name in parts:
        rows += [f'    <part id="{part_id}" subtype="normal_part">',
                 f'      <metadata key="name" value={quoteattr(name)}/>',
                 f'      <metadata key="extruder" value="{filament.get(name, 1)}"/>',
                 "    </part>"]
    rows += ["  </object>", "</config>", ""]
    return "\n".join(rows)


def write(path: str, title: str, bodies: dict, colors: dict | None = None) -> dict:
    """bodies = {name: (vertices, faces)}. Returns {"filaments", "extruders"}."""
    names = list(bodies)
    order, filament = extruders(names, colors)
    model = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<model unit="millimeter" xml:lang="en-US" '
             + 'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">',
             f'<metadata name="Title">{_escape(title)}</metadata>',
             "<resources>"]
    parts = []
    for i, name in enumerate(names, start=1):
        vertices, faces = bodies[name]
        model.append(f'<object id="{i}" type="model" name={quoteattr(name)}>')
        model.append(_mesh_xml(vertices, faces))
        model.append("</object>")
        parts.append((i, name))
    holder = len(names) + 1
    model.append(f'<object id="{holder}" type="model" name={quoteattr(title)}><components>')
    model += [f'<component objectid="{i}"/>' for i, _ in parts]
    model += ["</components></object>", "</resources>",
              f'<build><item objectid="{holder}"/></build>', "</model>", ""]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES)
        archive.writestr("_rels/.rels", RELS)
        archive.writestr("3D/3dmodel.model", "\n".join(model))
        archive.writestr("Metadata/model_settings.config",
                         model_settings(holder, title, parts, filament))
    with open(path, "wb") as handle:
        handle.write(buffer.getvalue())
    return {"filaments": order, "extruders": filament}


def _escape(text: str) -> str:
    return quoteattr(str(text))[1:-1]
