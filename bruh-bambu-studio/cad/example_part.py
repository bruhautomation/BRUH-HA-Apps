"""Example design: a cable clip for a 6 mm cable, screwed to a wall.

Parameters first, then geometry, then the module-level names the build reads.
"""
import cadquery as cq

# Parameters (mm)
CABLE_D = 6.0
CLEARANCE = 0.4
WALL = 2.0
WIDTH = 10.0
BASE_L = 26.0
BASE_T = 3.0
SCREW_D = 3.4

bore = CABLE_D + CLEARANCE
ring_r = bore / 2 + WALL
base = cq.Workplane("XY").box(BASE_L, WIDTH, BASE_T, centered=(True, True, False))
ring = (cq.Workplane("XZ").center(0, BASE_T + bore / 2).circle(ring_r)
        .extrude(WIDTH / 2, both=True))
body = base.union(ring)
body = body.cut(cq.Workplane("XZ").center(0, BASE_T + bore / 2).circle(bore / 2)
                .extrude(WIDTH, both=True))
# An entry slot so the cable snaps in from above.
body = body.cut(cq.Workplane("XY").workplane(offset=BASE_T + bore / 2)
                .box(bore * 0.7, WIDTH + 1, bore, centered=(True, True, False)))
for x in (-BASE_L / 2 + 4, BASE_L / 2 - 4):
    body = body.cut(cq.Workplane("XY").center(x, 0).circle(SCREW_D / 2).extrude(BASE_T))

NAME = "cable_clip"
TITLE = "Cable clip, 6 mm"
PARTS = {"Clip": body}
DIMS = {"cable bore": f"Ø{bore:.1f}", "screw holes": f"2 × Ø{SCREW_D}"}
NOTES = ["Print flat on the base, no supports.", "PETG for a clip that flexes without cracking."]
MATERIAL = "PETG"
