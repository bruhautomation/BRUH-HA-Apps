#!/usr/bin/env python3
"""Printing a designed part: from the chat, from the dialog, in several colours.

The design's 3MF is one object with a part per body, and its
Metadata/model_settings.config names each part's filament — the shape Bambu
Studio's own importer reads (src/libslic3r/Format/bbs_3mf.cpp: an object in
model_settings.config keyed by the build item's object id, a <part> per
component object id, and "extruder" metadata applied to the volume). The
tests read the file the way that importer does, then drive the print path
with a fake printer and the slicer stubbed, because the real AppImage is not
on a test machine.
"""
import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import time
import unittest
import unittest.mock as mock
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402
from test_bambu_design import FakeBrain, write_profiles  # noqa: E402

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

(server, store, library, installer, designer, parts, brain_link, runner, profiles,
 painting) = bambu_env.load("server", "store", "library", "installer", "design.designer",
                            "design.parts", "design.brain_link", "design.runner",
                            "design.profiles", "design.painting")

CAD = Path(__file__).resolve().parent.parent / "bruh-bambu-studio" / "cad"
_spec = importlib.util.spec_from_file_location("bambu_mf3", CAD / "mf3.py")
mf3 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mf3)

CORE = "{http://schemas.microsoft.com/3dmanufacturing/core/2015/02}"
BOX = ([(0, 0, 0), (10, 0, 0), (10, 10, 0), (0, 10, 0), (0, 0, 10), (10, 0, 10),
        (10, 10, 10), (0, 10, 10)],
       [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4),
        (1, 2, 6), (1, 6, 5), (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)])


def write_design(path: Path, colors=None) -> dict:
    return mf3.write(str(path), "cube_logo", {"Cube": BOX, "Logo": BOX},
                     colors or {"Cube": "#111111", "Logo": "#FFFFFF"})


def read_like_bambu_studio(path: Path) -> dict:
    """What bbs_3mf.cpp makes of the file: {object name: {part name: extruder}}."""
    with zipfile.ZipFile(path) as archive:
        model = ET.fromstring(archive.read("3D/3dmodel.model"))
        config = ET.fromstring(archive.read("Metadata/model_settings.config"))
    objects = {o.get("id"): o for o in model.iter(f"{CORE}object")}
    built = [item.get("objectid") for item in model.iter(f"{CORE}item")]
    out = {}
    for obj in config.iter("object"):
        # The config's object is the build item's object, or the importer
        # attaches its metadata to nothing.
        assert obj.get("id") in built, (obj.get("id"), built)
        components = [c.get("objectid") for c in objects[obj.get("id")].iter(f"{CORE}component")]
        meta = {m.get("key"): m.get("value") for m in obj.findall("metadata")}
        parts_seen = {}
        for part in obj.findall("part"):
            assert part.get("id") in components, (part.get("id"), components)
            assert part.get("subtype") == "normal_part"
            pmeta = {m.get("key"): m.get("value") for m in part.findall("metadata")}
            # A mesh the part points at must hold the geometry.
            assert objects[part.get("id")].find(f"{CORE}mesh") is not None
            parts_seen[pmeta["name"]] = int(pmeta["extruder"])
        out[meta["name"]] = parts_seen
    return out


class TestTheDesignFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "cube_logo.3mf"

    def test_one_object_a_part_per_body_a_filament_per_colour(self):
        painted = write_design(self.path)
        self.assertEqual(painted, {"filaments": ["#111111", "#FFFFFF"],
                                   "extruders": {"Cube": 1, "Logo": 2}})
        self.assertEqual(read_like_bambu_studio(self.path), {"cube_logo": {"Cube": 1, "Logo": 2}})
        with zipfile.ZipFile(self.path) as archive:
            model = ET.fromstring(archive.read("3D/3dmodel.model"))
        # One build item: Bambu Studio arranges objects apart, and these
        # bodies have to stay where they were drawn.
        self.assertEqual(len(list(model.iter(f"{CORE}item"))), 1)

    def test_bodies_of_one_colour_share_a_filament(self):
        painted = write_design(self.path, {"Cube": "#ffffff", "Logo": "#FFFFFF"})
        self.assertEqual(painted["extruders"], {"Cube": 1, "Logo": 1})
        self.assertEqual(painting.bodies(self.path), ["Cube", "Logo"])

    def test_a_file_from_before_has_no_bodies_to_paint(self):
        with zipfile.ZipFile(self.path, "w") as archive:
            archive.writestr("3D/3dmodel.model", "<model/>")
        self.assertIsNone(painting.bodies(self.path))

    def test_the_trays_chosen_become_the_parts_filaments(self):
        write_design(self.path)
        order, filament = painting.plan({"Cube": 3, "Logo": 0})
        self.assertEqual((order, filament), ([3, 0], {"Cube": 1, "Logo": 2}))
        order, filament = painting.plan({"Cube": 2, "Logo": 2})
        self.assertEqual((order, filament), ([2], {"Cube": 1, "Logo": 1}))
        target = Path(self.tmp.name) / "out" / "cube_logo.3mf"
        painting.retarget(self.path, target, {"Cube": 2, "Logo": 1})
        self.assertEqual(read_like_bambu_studio(target), {"cube_logo": {"Cube": 2, "Logo": 1}})
        with zipfile.ZipFile(self.path) as a, zipfile.ZipFile(target) as b:
            self.assertEqual(a.read("3D/3dmodel.model"), b.read("3D/3dmodel.model"))


class FakeClient:
    def __init__(self, trays=None, state="idle"):
        self.host, self.code, self.connected, self.last_error = "10.0.0.2", "abcd1234", True, ""
        self._summary = {"online": True, "state": state, "printing": state == "running",
                         "ams": trays or []}

    def summary(self):
        return json.loads(json.dumps(self._summary))

    def tick(self):
        pass

    def stop(self):
        pass


TRAYS = [{"slot": 0, "type": "PLA", "colour": "#FFFFFF", "remaining": 80},
         {"slot": 1, "type": "PLA", "colour": "#101010", "remaining": 40},
         {"slot": 2, "type": "PETG", "colour": "#1E9FE0", "remaining": None}]


class PrintTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        res = write_profiles(self.root)
        profiles._index.cache_clear()
        patches = [
            mock.patch.object(store, "PRINTERS", self.root / "printers.json"),
            mock.patch.object(store, "SECRETS", self.root / "secrets" / "printers.json"),
            mock.patch.object(library, "ROOT", self.root / "share"),
            mock.patch.object(installer, "MARKER", self.root / "bs" / "installed.json"),
            mock.patch.object(installer, "resources", return_value=res),
            mock.patch.object(brain_link, "BRAIN_SHARED", self.root / "brain"),
            mock.patch.object(brain_link, "POLL_S", 0.05),
            mock.patch.object(designer, "CAD_DIR", CAD),
            mock.patch.object(designer, "PRINTING", None),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        library.ensure()
        store.save({"name": "X1C", "host": "10.0.0.2", "serial": "AAAA11112222",
                    "model": "X1C"}, "abcd1234")
        self.panel = server.Panel(start_clients=False)
        self.client = FakeClient(TRAYS)
        self.panel.clients["aaaa11112222"] = self.client
        self.sent = []
        run = mock.patch.object(server, "_print_job", side_effect=self._print_job)
        run.start()
        self.addCleanup(run.stop)

    def _print_job(self, panel, job, row, client, body, env, prepared, after, notify=None):
        job.update(state="done", phase="started")
        after(job)
        self.sent.append({"body": body, "prepared": prepared})

    def wait_sent(self, count=1):
        """The print runs on a thread of its own, as in the panel."""
        deadline = time.time() + 5
        while len(self.sent) < count and time.time() < deadline:
            time.sleep(0.02)
        self.assertEqual(len(self.sent), count)

    def part(self, colors=None, *, multi=True):
        part = parts.create("Cube with a logo")
        vdir = parts.version_dir(part["id"], 1)
        vdir.mkdir(parents=True)
        if multi:
            write_design(vdir / "cube_logo.3mf", colors)
        else:
            with zipfile.ZipFile(vdir / "cube_logo.3mf", "w") as archive:
                archive.writestr("3D/3dmodel.model", "<model/>")
        part["versions"] = [{"n": 1, "ok": True, "files": {"3mf": "cube_logo.3mf"},
                             "colors": colors or {"Cube": "#111111", "Logo": "#FFFFFF"}}]
        part["current"] = 1
        part["print_settings"] = {"material": "PLA", "layer_height": 0.28}
        parts.save(part)
        return part


class TestStartingAPrint(PrintTest):
    def test_each_body_prints_from_its_own_tray(self):
        part = self.part()
        _job, prepared, sentence = server.start_design_print(
            self.panel, part["id"], slots={"Cube": 1, "Logo": 0})
        self.wait_sent()
        body = self.sent[0]["body"]
        self.assertEqual((body["use_ams"], body["ams_mapping"]), (True, [1, 0]))
        sliced = library.path_of(body["file"])
        self.assertNotEqual(sliced.name, "")
        self.assertEqual(read_like_bambu_studio(sliced), {"cube_logo": {"Cube": 1, "Logo": 2}})
        # One filament profile per tray, in that order, in the tray's colour.
        files = prepared["paths"]["filaments"]
        self.assertEqual(len(files), 2)
        colours = [json.loads(Path(f).read_text())["filament_colour"] for f in files]
        self.assertEqual(colours, [["#101010"], ["#FFFFFF"]])
        self.assertIn("Cube from AMS 2", sentence)
        self.assertIn("Logo from AMS 1", sentence)
        record = parts.load(part["id"])
        self.assertEqual(record["prints"][0]["slots"], {"Cube": 1, "Logo": 0})
        self.assertIn("Started version 1 on X1C", record["messages"][-1]["text"])

    def test_a_body_nobody_named_takes_the_tray_its_colour_fits(self):
        part = self.part()
        server.start_design_print(self.panel, part["id"], slots={"Logo": 0})
        self.wait_sent()
        self.assertEqual(self.sent[0]["body"]["ams_mapping"], [1, 0])

    def test_one_slot_for_everything_is_one_filament(self):
        part = self.part()
        server.start_design_print(self.panel, part["id"], slots=1)
        self.wait_sent()
        body = self.sent[0]["body"]
        self.assertEqual(body["ams_mapping"], [1])
        self.assertEqual(read_like_bambu_studio(library.path_of(body["file"])),
                         {"cube_logo": {"Cube": 1, "Logo": 1}})

    def test_an_older_version_prints_in_one_filament(self):
        part = self.part(multi=False)
        server.start_design_print(self.panel, part["id"], slots="external")
        self.wait_sent()
        body = self.sent[0]["body"]
        self.assertEqual((body["use_ams"], body["ams_mapping"]), (False, [0]))

    def test_an_older_version_takes_the_tray_brain_named(self):
        part = self.part(multi=False)
        server.start_design_print(self.panel, part["id"], slots={"Clip": 2})
        self.wait_sent()
        self.assertEqual(self.sent[0]["body"]["ams_mapping"], [2])

    def test_what_cannot_print_is_refused_and_says_why(self):
        part = self.part()
        cases = [
            ({"Cube": "external", "Logo": 0}, "external spool holds one filament"),
            ({"Cube": 7, "Logo": 0}, "AMS tray 8 has no filament"),
        ]
        for slots, words in cases:
            with self.subTest(slots=slots), self.assertRaises(server.PrintRefused) as caught:
                server.start_design_print(self.panel, part["id"], slots=slots)
            self.assertIn(words, str(caught.exception))
        self.client._summary.update(printing=True)
        with self.assertRaises(server.PrintRefused) as caught:
            server.start_design_print(self.panel, part["id"], slots={"Cube": 1, "Logo": 0})
        self.assertIn("already printing", str(caught.exception))
        self.assertEqual(self.sent, [])


class TestTheRoutes(PrintTest):
    def setUp(self):
        super().setUp()
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.http = TestClient(TestServer(server.build_app(self.panel, ticker=False)), loop=self.loop)
        self.loop.run_until_complete(self.http.start_server())
        self.addCleanup(lambda: self.loop.run_until_complete(self.http.close()))

    def call(self, method, path, **kw):
        async def go():
            resp = await self.http.request(method, path, **kw)
            return resp.status, await resp.json()
        return self.loop.run_until_complete(go())

    def test_the_plan_offers_a_tray_per_body(self):
        part = self.part()
        status, body = self.call("GET", f"/api/design/parts/{part['id']}/plan")
        self.assertEqual(status, 200, body)
        self.assertEqual([(b["name"], b["recommended_slot"]) for b in body["bodies"]],
                         [("Cube", 1), ("Logo", 0)])

    def test_the_dialog_sends_a_tray_per_body(self):
        part = self.part()
        status, body = self.call("POST", f"/api/design/parts/{part['id']}/print",
                                 json={"slots": {"Cube": 1, "Logo": 0}, "wait": 5})
        self.assertEqual(status, 200, body)
        self.wait_sent()
        self.assertEqual(self.sent[0]["body"]["ams_mapping"], [1, 0])
        status, body = self.call("POST", f"/api/design/parts/{part['id']}/print",
                                 json={"slots": {"Cube": "external", "Logo": 0}})
        self.assertEqual(status, 409)

    def test_open_in_bambu_studio_opens_that_versions_file(self):
        part = self.part()
        with mock.patch.object(self.panel.studio, "restart") as restart:
            status, body = self.call("POST", f"/api/design/parts/{part['id']}/studio",
                                     json={"version": 1})
        self.assertEqual(status, 200, body)
        # A copy carrying the printer's project settings, so Bambu Studio does
        # not open it as geometry only (test_bambu_slice_rules).
        opened = Path(restart.call_args[0][0])
        self.assertEqual(opened.name, "cube_logo.studio.3mf", body.get("note"))
        import zipfile
        with zipfile.ZipFile(opened) as z:
            self.assertIn("Metadata/project_settings.config", z.namelist())
        empty = parts.create("Nothing yet")
        status, _ = self.call("POST", f"/api/design/parts/{empty['id']}/studio", json={})
        self.assertEqual(status, 400)


class TestBrainPrintsFromTheChat(PrintTest):
    def turn(self, answers, words="Print it"):
        fake = FakeBrain(self.root / "brain", answers)
        self.addCleanup(fake.stop)
        part = self.part()
        printing = server.DesignPrinting(self.panel)
        with mock.patch.object(designer, "PRINTING", printing):
            designer.start_turn(part["id"], words)
            deadline = time.time() + 10
            while time.time() < deadline and parts.load(part["id"])["state"] not in ("idle", "failed"):
                time.sleep(0.05)
        return parts.load(part["id"]), fake

    def test_brain_sees_the_printers_and_starts_the_print_it_chose(self):
        part, fake = self.turn([{"reply": "Printing on the X1C: cube black, logo white.",
                                 "print": {"go": True, "printer": "aaaa11112222",
                                           "slots": [{"body": "Cube", "slot": 1},
                                                     {"body": "Logo", "slot": 0}]}}])
        prompt = fake.tasks[0]["prompt"]
        self.assertIn("PRINTERS (live)", prompt)
        self.assertIn('"slot": 1, "material": "PLA", "colour": "#101010"', prompt)
        self.assertIn("never tell the person to press a button", prompt)
        self.assertIn("print", fake.tasks[0]["schema"]["properties"])
        self.wait_sent()
        self.assertEqual(self.sent[0]["body"]["ams_mapping"], [1, 0])
        said = [m["text"] for m in part["messages"] if m["role"] == "system"]
        self.assertTrue(any(t.startswith("Slicing and sending version 1 on X1C") for t in said), said)
        self.assertEqual(part["state"], "idle")

    def test_a_reply_without_go_prints_nothing(self):
        part, fake = self.turn([{"reply": "Which colour for the logo?",
                                 "print": {"go": False, "printer": "aaaa11112222"}}])
        self.assertEqual(len(fake.tasks), 1)
        self.assertEqual(part["messages"][-1]["text"], "Which colour for the logo?")
        self.assertEqual(self.sent, [])

    def test_a_print_that_cannot_start_is_said_in_the_conversation(self):
        self.client._summary.update(printing=True)
        part, _fake = self.turn([{"reply": "Printing.", "print": {"go": True}}])
        self.assertEqual(self.sent, [])
        self.assertIn("The print did not start: X1C is already printing.",
                      part["messages"][-1]["text"])

    def test_only_a_print_request_brain_meant_is_kept(self):
        self.assertIsNone(designer.clean_print({"go": "yes"}))
        self.assertIsNone(designer.clean_print(None))
        self.assertEqual(designer.clean_print({"go": True, "slots": [
            {"body": "Cube", "slot": -1}, {"body": "Logo", "slot": 99},
            {"body": "Lid", "slot": True}, {"slot": 2}]}),
            {"timelapse": False, "slots": {"Cube": "external"}})


class TestThePrintButton(unittest.TestCase):
    def test_three_ways_to_print(self):
        panel = CAD.parent / "panel"
        html = (panel / "index.html").read_text()
        for button in ("pcAuto", "pcManual", "pcStudio"):
            self.assertIn(f'id="{button}"', html)
        js = (panel / "design.js").read_text()
        self.assertIn('$("#partPrint").addEventListener("click", openPrintChoice)', js)
        self.assertIn("/studio`", js)


if __name__ == "__main__":
    unittest.main()
