#!/usr/bin/env python3
"""A bare model sliced for an A1 is sliced for the A1's 256 mm bed.

A house sliced an STL on its A1 through the slice service and got G-code
whose header said `printable_area = 0x0,200x0,200x200,0x200`: the part was
recentred at 100,100 and anything wider than about 200 mm was refused with
"nothing is fully on the plate" (exit -50). The panel handed the command
line Bambu Studio's system profiles exactly as they are on disk, and a
system profile is a few keys over a parent named in `inherits`; the
command line does not follow that chain, so the bed size, which the
family profile holds, never arrived and it sliced on its own default.

The profiles here are Bambu Studio's shape (resources/profiles/BBL, each
file a few keys over its `inherits`, the same shape test_bambu_design and
test_bambu_design_slice_params use), and the stand-in for Bambu Studio's
command line reads each settings file it is handed as it is — never its
parent — and lays the part out on the bed those keys describe, refusing a
part that does not fit the way the real one does.
"""
import json
import os
import sys
import tempfile
import unittest
import unittest.mock as mock
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from bambu_env import load  # noqa: E402

slicer, profiles, store, library, installer = load(
    "slicer", "design.profiles", "store", "library", "installer")

A1 = "Bambu Lab A1 0.4 nozzle"
A1_MINI = "Bambu Lab A1 mini 0.4 nozzle"
X1C = "Bambu Lab X1 Carbon 0.4 nozzle"
SQUARE_256 = ["0x0", "256x0", "256x256", "0x256"]
SQUARE_180 = ["0x0", "180x0", "180x180", "0x180"]


def write_profiles(root: Path, *, a1_family_area=True) -> Path:
    base = root / "resources" / "profiles" / "BBL"
    for kind in ("machine", "process", "filament"):
        (base / kind).mkdir(parents=True)

    def put(kind, name, **data):
        (base / kind / f"{name}.json").write_text(json.dumps({"name": name, **data}))

    put("machine", "fdm_machine_common", type="machine", **{"from": "system"},
        instantiation="false", printer_model="", nozzle_diameter=["0.4"])
    family = {"printable_area": SQUARE_256, "printable_height": "256"} if a1_family_area else {}
    put("machine", "fdm_bbl_3dp_001_common", type="machine", inherits="fdm_machine_common",
        **{"from": "system"}, instantiation="false", **family)
    put("machine", A1, type="machine", inherits="fdm_bbl_3dp_001_common",
        **{"from": "system"}, instantiation="true", printer_model="Bambu Lab A1",
        setting_id="GM014")
    put("machine", A1_MINI, type="machine", inherits="fdm_bbl_3dp_001_common",
        **{"from": "system"}, instantiation="true", printer_model="Bambu Lab A1 mini",
        printable_area=SQUARE_180, printable_height="180", setting_id="GM020")
    put("machine", X1C, type="machine", inherits="fdm_bbl_3dp_001_common",
        **{"from": "system"}, instantiation="true", printer_model="Bambu Lab X1 Carbon")
    put("process", "fdm_process_common", type="process", instantiation="false",
        layer_height="0.2", wall_loops="2", sparse_infill_density="15%")
    for suffix, machine in (("A1", A1), ("A1M", A1_MINI), ("X1C", X1C)):
        for label in ("Standard", "Strength"):
            put("process", f"0.20mm {label} @BBL {suffix}", type="process",
                inherits="fdm_process_common", instantiation="true",
                compatible_printers=[machine])
        put("filament", f"Bambu PLA Basic @BBL {suffix}", type="filament",
            instantiation="true", filament_type=["PLA"], compatible_printers=[machine])
    return root / "resources"


# Bambu Studio's command line, as far as a bed goes: each settings file is
# read as it is (no `inherits`), a machine that says nothing of its bed gets
# the 200 mm default, the part is centred on the bed, and a part wider than
# the bed is "nothing is fully on the plate" (-50, the shell's 206).
STAND_IN = r'''#!/usr/bin/env python3
import json, os, sys, zipfile
argv = sys.argv[1:]
opts = {argv[i]: argv[i + 1] for i in range(len(argv) - 1) if argv[i].startswith("--")}
machine = {}
for path in (opts.get("--load-settings") or "").split(";"):
    data = json.load(open(path)) if path else {}
    if data.get("type") == "machine" or "printer_model" in data:
        machine = data
json.dump(machine, open(os.environ["RECORD"], "w"))
area = machine.get("printable_area") or ["0x0", "200x0", "200x200", "0x200"]
xs = [float(p.split("x")[0]) for p in area]
ys = [float(p.split("x")[1]) for p in area]
bed_x, bed_y = max(xs) - min(xs), max(ys) - min(ys)
pts = [tuple(map(float, l.split()[1:4])) for l in open(argv[-1]) if l.strip().startswith("vertex")]
size_x = max(p[0] for p in pts) - min(p[0] for p in pts)
size_y = max(p[1] for p in pts) - min(p[1] for p in pts)
if size_x > bed_x or size_y > bed_y:
    print("[error] Nothing to be sliced, Either the print is empty or no object is fully inside the plate")
    print("run found error, return -50, exit...")
    sys.exit(206)
cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
out = os.path.join(opts["--outputdir"], opts["--export-3mf"])
with zipfile.ZipFile(out, "w") as z:
    z.writestr("Metadata/plate_1.gcode",
               "; printable_area = %s\n; part_x = %.1f-%.1f\n" % (
                   ",".join(area), cx - size_x / 2, cx + size_x / 2))
'''


def box_stl(path: Path, x: float, y: float, z: float, at=(0.0, 0.0)) -> Path:
    ox, oy = at
    corners = [(ox + a * x, oy + b * y, c * z) for a in (0, 1) for b in (0, 1) for c in (0, 1)]
    lines = ["solid box"]
    for i in range(0, 8, 3):
        lines += ["facet normal 0 0 0", "outer loop"]
        for v in (corners[i % 8], corners[(i + 1) % 8], corners[(i + 2) % 8]):
            lines.append("vertex %g %g %g" % v)
        lines += ["endloop", "endfacet"]
    lines.append("endsolid box")
    path.write_text("\n".join(lines) + "\n")
    return path


class BedTest(unittest.TestCase):
    family_area = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        res = write_profiles(self.root, a1_family_area=self.family_area)
        profiles._index.cache_clear()
        self.addCleanup(profiles._index.cache_clear)
        self.app = self.root / "AppRun"
        self.app.write_text(STAND_IN.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        self.app.chmod(0o755)
        self.record = self.root / "machine-handed.json"
        for patch in (
                mock.patch.object(store, "PRINTERS", self.root / "printers.json"),
                mock.patch.object(store, "SECRETS", self.root / "secrets" / "printers.json"),
                mock.patch.object(library, "ROOT", self.root / "share"),
                mock.patch.object(installer, "resources", return_value=res),
                mock.patch.object(installer, "apprun", return_value=self.app),
                mock.patch.object(slicer, "MAKE_ROOM", None),
                mock.patch.object(slicer, "SLICE_HOME", self.root / "slicer-home"),
                mock.patch.dict(os.environ, {"RECORD": str(self.record)})):
            patch.start()
            self.addCleanup(patch.stop)
        library.ensure()
        # Names a person might give: one says "mini" and is an A1, one says
        # "A1" and is an A1 mini.
        store.save({"name": "Loft A1 mini shelf 0.4 nozzle", "host": "10.0.0.7",
                    "serial": "CCCC11112222", "model": "A1"}, "abcd1234")
        store.save({"name": "Desk A1", "host": "10.0.0.8",
                    "serial": "DDDD11112222", "model": "A1 mini"}, "abcd1234")
        self.part = box_stl(library.ROOT / "rack mount.stl", 241, 104, 117)

    def slice(self, machine, process, filaments=None, source="rack mount.stl"):
        job = slicer.start(source, machine=machine, process=process,
                           filaments=filaments, arrange=True, env=dict(os.environ))
        done = slicer.wait(job["id"], 30)
        handed = json.loads(self.record.read_text()) if self.record.exists() else {}
        return done, handed

    def gcode(self, done) -> str:
        with zipfile.ZipFile(library.path_of(done["output"])) as z:
            return z.read("Metadata/plate_1.gcode").decode()


class TestTheA1SlicesOnItsOwnBed(BedTest):
    def test_a_printer_named_by_the_house_is_sliced_for_its_model(self):
        done, handed = self.slice("Loft A1 mini shelf 0.4 nozzle", "0.20mm Standard @BBL A1",
                                  ["Bambu PLA Basic @BBL A1"])
        self.assertEqual(done["state"], "done", done.get("error"))
        self.assertEqual(handed["printable_area"], SQUARE_256)
        self.assertEqual(handed["printable_height"], "256")
        self.assertIn("printable_area = 0x0,256x0,256x256,0x256", self.gcode(done))

    def test_the_a1_profile_by_its_own_name_carries_its_family_bed(self):
        for process in ("0.20mm Standard @BBL A1", "0.20mm Strength @BBL A1"):
            with self.subTest(process=process):
                done, handed = self.slice(A1, process)
                self.assertEqual(done["state"], "done", done.get("error"))
                self.assertEqual(handed["printable_area"], SQUARE_256)
                self.assertEqual((handed["inherits"], handed["from"]), (A1, "User"))
                self.assertIn("256x256", self.gcode(done))

    def test_a_small_part_is_centred_on_the_256_mm_bed(self):
        box_stl(library.ROOT / "cube.stl", 20, 20, 20, at=(118, 118))
        done, _handed = self.slice("CCCC11112222", "0.20mm Standard @BBL A1", source="cube.stl")
        self.assertEqual(done["state"], "done", done.get("error"))
        self.assertIn("part_x = 118.0-138.0", self.gcode(done))

    def test_an_a1_mini_still_gets_180_mm_whatever_it_is_called(self):
        box_stl(library.ROOT / "cube.stl", 20, 20, 20)
        for machine in ("Desk A1", A1_MINI):
            with self.subTest(machine=machine):
                done, handed = self.slice(machine, "0.20mm Standard @BBL A1M", source="cube.stl")
                self.assertEqual(done["state"], "done", done.get("error"))
                self.assertEqual(handed["printable_area"], SQUARE_180)
        done, _handed = self.slice("Desk A1", "0.20mm Standard @BBL A1M")
        self.assertEqual(done["state"], "failed")
        self.assertIn("nothing is fully on the plate", done["error"])

    def test_a_printer_with_no_model_is_refused_by_its_name(self):
        store.save({"name": "Garage printer", "host": "10.0.0.9",
                    "serial": "EEEE11112222", "model": ""}, "abcd1234")
        with self.assertRaises(LookupError) as caught:
            slicer.start("rack mount.stl", machine="Garage printer",
                         process="0.20mm Standard @BBL A1")
        self.assertIn("Garage printer", str(caught.exception))
        self.assertIn("model", str(caught.exception))

    def test_a_name_that_is_neither_offers_the_printers(self):
        with self.assertRaises(LookupError) as caught:
            slicer.start("rack mount.stl", machine="Workshop A1",
                         process="0.20mm Standard @BBL A1")
        self.assertIn("Desk A1", str(caught.exception))

    def test_a_designed_part_is_prepared_with_the_same_beds(self):
        a1 = profiles.prepare("A1", {"material": "PLA"}, self.root / "p1")
        mini = profiles.prepare("A1 mini", {"material": "PLA"}, self.root / "p2")
        self.assertEqual(json.loads(Path(a1["paths"]["machine"]).read_text())
                         ["printable_area"], SQUARE_256)
        self.assertEqual(json.loads(Path(mini["paths"]["machine"]).read_text())
                         ["printable_area"], SQUARE_180)


class TestAProfileWithNoBedIsRefused(BedTest):
    family_area = False

    def test_the_slice_is_refused_in_words_naming_the_printer(self):
        with self.assertRaises(LookupError) as caught:
            slicer.start("rack mount.stl", machine="Loft A1 mini shelf 0.4 nozzle",
                         process="0.20mm Standard @BBL A1")
        said = str(caught.exception)
        self.assertIn("Loft A1 mini shelf 0.4 nozzle", said)
        self.assertIn("bed", said)
        self.assertFalse(self.record.exists(), "Bambu Studio ran on a default bed")

    def test_a_designed_part_is_refused_too(self):
        with self.assertRaises(LookupError):
            profiles.prepare("A1", {"material": "PLA"}, self.root / "p1")
        with self.assertRaises(LookupError):
            profiles.project_settings("A1", {"material": "PLA"})


if __name__ == "__main__":
    unittest.main()
