#!/usr/bin/env python3
"""Designing a part with brAIn: the conversation, the guard, the versions,
the profiles and the routes.

brAIn is faked at its task folder — the same files its automation listener
reads and writes — so what is under test is the protocol the add-on really
speaks. The CAD build is faked at `runner.build` except where a real
CadQuery is on the machine (BAMBU_TEST_CAD_PYTHON), because the image's CAD
stack is several hundred MB the suite's CI does not install.
"""
import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

(server, store, library, installer, guard, designer, parts, brain_link, runner,
 profiles) = bambu_env.load("server", "store", "library", "installer", "design.guard",
                            "design.designer", "design.parts", "design.brain_link",
                            "design.runner", "design.profiles")

CAD = Path(__file__).resolve().parent.parent / "bruh-bambu-studio" / "cad"
EXAMPLE = (CAD / "example_part.py").read_text()


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.brain = self.root / "brain"
        patches = [
            mock.patch.object(store, "PRINTERS", self.root / "printers.json"),
            mock.patch.object(store, "SECRETS", self.root / "secrets" / "printers.json"),
            mock.patch.object(library, "ROOT", self.root / "share"),
            mock.patch.object(installer, "MARKER", self.root / "bs" / "installed.json"),
            mock.patch.object(brain_link, "BRAIN_SHARED", self.brain),
            mock.patch.object(brain_link, "POLL_S", 0.05),
            mock.patch.object(designer, "CAD_DIR", CAD),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        library.ensure()


class FakeBrain:
    """brAIn's automation listener: claims a task by deleting it, answers
    with a result file. `answers` are the `data` objects, in order."""

    def __init__(self, folder: Path, answers, *, status="completed"):
        self.folder, self.answers, self.status = folder, list(answers), status
        self.tasks = []
        (folder / "tasks").mkdir(parents=True, exist_ok=True)
        (folder / "task_results").mkdir(exist_ok=True)
        self._stop = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        while not self._stop:
            for path in (self.folder / "tasks").glob("*.json"):
                task = json.loads(path.read_text())
                path.unlink()
                self.tasks.append(task)
                data = self.answers.pop(0) if self.answers else {"reply": "ok"}
                result = {"id": task["id"], "status": self.status,
                          "result": json.dumps(data), "data": data, "session_id": "sess-1"}
                (self.folder / "task_results" / f"{task['id']}.json").write_text(json.dumps(result))
            time.sleep(0.02)

    def stop(self):
        self._stop = True


def ok_build(script, outdir):
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "bodies").mkdir(exist_ok=True)
    (outdir / "bodies" / "Clip.stl").write_text("solid x\nendsolid x\n")
    (outdir / "cable_clip.3mf").write_bytes(b"PK")
    return {"ok": True, "size_mm": [26, 10, 10.9], "grams_pla": 1.3, "warnings": [],
            "files": {"3mf": "cable_clip.3mf", "stl": "x.stl", "step": "x.step",
                      "bodies": {"Clip": "bodies/Clip.stl"}}, "name": "cable_clip"}


def failed_build(script, outdir):
    return {"ok": False, "stage": "load", "error": "StdFail_NotDone: BRep_API: command not done",
            "traceback": ["design.py line 3: x.fillet(5)"]}


class TestGuard(unittest.TestCase):
    def test_the_example_passes(self):
        self.assertEqual(guard.check(EXAMPLE), [])

    def test_anything_reaching_past_geometry_is_refused_with_its_line(self):
        for bad in ("import os", "import subprocess", "from pathlib import Path",
                    "x = open('/data/secrets/printers.json').read()",
                    "eval('1')", "import cadquery as cq\ncq.__dict__",
                    "getattr(cq, 'os')", "from . import x"):
            with self.subTest(bad=bad):
                problems = guard.check(bad)
                self.assertTrue(problems)
                self.assertIn("Line", problems[0])

    def test_a_syntax_error_names_its_line(self):
        self.assertIn("Line 1", guard.check("def (")[0])


class TestSettings(unittest.TestCase):
    def test_sane_settings_are_kept_and_the_rest_dropped(self):
        got = designer.clean_settings({"material": "petg", "colour": "black",
                                       "layer_height": 0.2, "walls": 50, "infill_percent": 25,
                                       "supports": "maybe", "brim": "auto", "why": "flex"})
        self.assertEqual(got, {"material": "PETG", "colour": "black", "layer_height": 0.2,
                               "infill_percent": 25, "brim": "auto", "why": "flex"})
        self.assertIsNone(designer.clean_settings("nonsense"))


class TestConversation(Isolated):
    def turn(self, answers, words="A clip for a 6 mm cable", build=ok_build, status="completed"):
        fake = FakeBrain(self.brain, answers, status=status)
        self.addCleanup(fake.stop)
        part = parts.create("New part")
        with mock.patch.object(runner, "build", side_effect=build):
            designer.start_turn(part["id"], words)
            deadline = time.time() + 10
            while time.time() < deadline and parts.load(part["id"])["state"] != "idle" and \
                    parts.load(part["id"])["state"] != "failed":
                time.sleep(0.05)
        return parts.load(part["id"]), fake

    def test_a_turn_builds_a_version_and_keeps_the_session(self):
        part, fake = self.turn([{"reply": "Here it is.", "name": "Cable clip",
                                 "design_py": EXAMPLE, "change_summary": "First draft",
                                 "print_settings": {"material": "PETG", "colour": "black"},
                                 "questions": ["How thick is the wall?"]}])
        self.assertEqual(part["state"], "idle")
        self.assertEqual(part["name"], "Cable clip")
        self.assertEqual(part["current"], 1)
        self.assertEqual(part["session_id"], "sess-1")
        self.assertEqual(part["print_settings"], {"material": "PETG", "colour": "black"})
        self.assertEqual([m["role"] for m in part["messages"]], ["user", "brain"])
        self.assertEqual(part["messages"][1]["version"], 1)
        self.assertEqual(part["messages"][1]["questions"], ["How thick is the wall?"])
        self.assertTrue((parts.version_dir(part["id"], 1) / "design.py").read_text().startswith('"""Example'))
        task = fake.tasks[0]
        self.assertEqual((task["kind"], task["tools"], task["source"]),
                         ("conversation", "read_only", "bruh_bambu"))
        self.assertIn("A clip for a 6 mm cable", task["prompt"])
        self.assertIn("design_py", json.dumps(task["schema"]))

    def test_a_failed_build_goes_back_to_brain_before_anybody_sees_it(self):
        builds = iter([failed_build, ok_build])
        part, fake = self.turn(
            [{"reply": "Draft.", "design_py": EXAMPLE}, {"reply": "Fixed.", "design_py": EXAMPLE}],
            build=lambda s, o: next(builds)(s, o))
        # The attempt that failed is not a version: the fix is version 1.
        self.assertEqual(part["current"], 1)
        self.assertEqual([v["n"] for v in part["versions"]], [1])
        self.assertEqual(len(fake.tasks), 2)
        self.assertIn("DID NOT BUILD", fake.tasks[1]["prompt"])
        self.assertIn("design.py line 3", fake.tasks[1]["prompt"])
        self.assertEqual(fake.tasks[1]["session_id"], "sess-1")

    def test_a_design_that_never_builds_says_so_and_stops(self):
        part, fake = self.turn([{"reply": "x", "design_py": EXAMPLE}] * 5, build=failed_build)
        self.assertEqual(len(fake.tasks), 1 + designer.FIX_ATTEMPTS)
        self.assertIsNone(part["current"])
        self.assertIn("did not build", part["messages"][-1]["text"])

    def test_a_refused_script_never_runs(self):
        runs = []
        part, _ = self.turn([{"reply": "x", "design_py": "import os\nPARTS = {}"}] * 5,
                            build=lambda s, o: runs.append(s) or ok_build(s, o))
        self.assertEqual(runs, [])
        self.assertIsNone(part["current"])

    def test_a_reply_with_no_script_changes_no_version(self):
        part, _ = self.turn([{"reply": "What does it clip onto?"}])
        self.assertEqual(part["versions"], [])
        self.assertEqual(part["messages"][-1]["text"], "What does it clip onto?")

    def test_nothing_listening_is_said_by_name(self):
        (self.brain / "tasks").mkdir(parents=True)
        part = parts.create("New part")
        with mock.patch.object(brain_link, "CLAIM_GRACE_S", 0.2):
            designer.start_turn(part["id"], "A hook")
            deadline = time.time() + 5
            while time.time() < deadline and parts.load(part["id"])["state"] != "failed":
                time.sleep(0.05)
        part = parts.load(part["id"])
        self.assertEqual(part["state"], "failed")
        self.assertIn("Automation integration", part["error"])
        self.assertEqual(list((self.brain / "tasks").glob("*.json")), [])

    def test_a_restart_mid_turn_does_not_leave_it_thinking(self):
        part = parts.create("x")
        part["state"] = "thinking"
        parts.save(part)
        designer.recover()
        self.assertEqual(parts.load(part["id"])["state"], "idle")


class TestBrainStatus(Isolated):
    def test_three_answers(self):
        self.assertEqual(brain_link.status()["state"], "missing")
        self.brain.mkdir()
        self.assertEqual(brain_link.status()["state"], "off")
        (self.brain / "tasks").mkdir()
        self.assertEqual(brain_link.status()["state"], "ok")


class TestParts(Isolated):
    def test_a_file_cannot_leave_its_version(self):
        part = parts.create("Bracket")
        vdir = parts.version_dir(part["id"], 1)
        vdir.mkdir()
        (vdir / "a.stl").write_text("x")
        self.assertEqual(parts.file_in(part["id"], 1, "a.stl").name, "a.stl")
        for bad in ("../part.json", "../../../printers.json", ""):
            with self.subTest(bad=bad), self.assertRaises(LookupError):
                parts.file_in(part["id"], 1, bad)
        with self.assertRaises(ValueError):
            parts.folder("../x")


def write_profiles(root: Path):
    base = root / "resources" / "profiles" / "BBL"
    for kind in ("machine", "process", "filament"):
        (base / kind).mkdir(parents=True)

    def put(kind, name, **data):
        (base / kind / f"{name}.json").write_text(json.dumps({"name": name, **data}))

    put("machine", "fdm_machine_common", instantiation="false", printer_model="")
    put("machine", "Bambu Lab X1 Carbon 0.4 nozzle", inherits="fdm_machine_common",
        instantiation="true")
    put("process", "fdm_process_common", instantiation="false", layer_height="0.2",
        wall_loops="2", sparse_infill_density="15%")
    for lh in ("0.12", "0.20", "0.28"):
        label = {"0.12": "Fine", "0.20": "Standard", "0.28": "Extra Draft"}[lh]
        put("process", f"{lh}mm {label} @BBL X1C", inherits="fdm_process_common",
            layer_height=lh, instantiation="true",
            compatible_printers=["Bambu Lab X1 Carbon 0.4 nozzle"])
    put("process", "0.20mm Standard @BBL A1M", inherits="fdm_process_common",
        instantiation="true", compatible_printers=["Bambu Lab A1 mini 0.4 nozzle"])
    for name, kind in (("Bambu PLA Basic @BBL X1C", "PLA"), ("Generic PETG @BBL X1C", "PETG"),
                       ("Bambu PETG Basic @BBL X1C", "PETG")):
        put("filament", name, instantiation="true", filament_type=[kind],
            compatible_printers=["Bambu Lab X1 Carbon 0.4 nozzle"])
    return root / "resources"


class TestProfiles(Isolated):
    def setUp(self):
        super().setUp()
        res = write_profiles(self.root)
        profiles._index.cache_clear()
        p = mock.patch.object(installer, "resources", return_value=res)
        p.start()
        self.addCleanup(p.stop)

    def test_the_right_profiles_for_a_printer_and_a_part(self):
        machine = profiles.machine_for("X1C")
        self.assertEqual(machine, "Bambu Lab X1 Carbon 0.4 nozzle")
        self.assertEqual(profiles.process_for(machine, 0.28), "0.28mm Extra Draft @BBL X1C")
        self.assertEqual(profiles.process_for(machine, None), "0.20mm Standard @BBL X1C")
        self.assertEqual(profiles.filament_for(machine, "petg"), "Bambu PETG Basic @BBL X1C")
        with self.assertRaises(LookupError):
            profiles.filament_for(machine, "TPU")
        with self.assertRaises(LookupError):
            profiles.machine_for("")

    def test_settings_are_written_over_a_flattened_profile(self):
        prepared = profiles.prepare("X1C", {"material": "PETG", "layer_height": 0.2,
                                            "walls": 4, "infill_percent": 30,
                                            "supports": "tree", "brim": "auto"},
                                    self.root / "slicing")
        process = json.loads(Path(prepared["paths"]["process"]).read_text())
        self.assertEqual(process["inherits"], "0.20mm Standard @BBL X1C")
        self.assertEqual(process["wall_loops"], "4")
        self.assertEqual(process["sparse_infill_density"], "30%")
        self.assertEqual((process["enable_support"], process["support_type"]), ("1", "tree(auto)"))
        self.assertEqual(process["brim_type"], "auto_brim")
        self.assertEqual(prepared["filament"], "Bambu PETG Basic @BBL X1C")


    def test_the_cli_reads_the_process_as_compatible_with_the_printer(self):
        """The check Bambu Studio's CLI makes before it slices
        (BambuStudio.cpp: a User profile's system name is its `inherits`, and
        the process must list the machine's). It exited -17 when it failed."""
        prepared = profiles.prepare("X1C", {"material": "PLA"}, self.root / "slicing")
        paths = prepared["paths"]

        def system_name(path):
            data = json.loads(Path(path).read_text())
            self.assertIn(data["from"], ("system", "User", "user"))
            return data["name"] if data["from"] == "system" else data.get("inherits", "")

        machine = system_name(paths["machine"])
        self.assertEqual(machine, "Bambu Lab X1 Carbon 0.4 nozzle")
        process = json.loads(Path(paths["process"]).read_text())
        self.assertIn(machine, process["compatible_printers"])
        self.assertEqual(system_name(paths["filament"]), prepared["filament_names"][0])


class TestTrays(unittest.TestCase):
    TRAYS = [{"slot": 0, "type": "PLA", "colour": "#FFFFFF"},
             {"slot": 1, "type": "PETG", "colour": "#111111"},
             {"slot": 2, "type": "PETG", "colour": "#1E9FE0"}]

    def test_the_material_first_then_the_colour(self):
        self.assertEqual(server.recommend_tray(self.TRAYS, "PETG", "black"), 1)
        self.assertEqual(server.recommend_tray(self.TRAYS, "PETG", "blue"), 2)
        self.assertEqual(server.recommend_tray(self.TRAYS, "PLA", "black"), 0)
        self.assertIsNone(server.recommend_tray(self.TRAYS, "TPU", "black"))


class TestRoutes(Isolated):
    def setUp(self):
        super().setUp()
        self.panel = server.Panel(start_clients=False)
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.http = TestClient(TestServer(server.build_app(self.panel, ticker=False)), loop=self.loop)
        self.loop.run_until_complete(self.http.start_server())
        self.addCleanup(lambda: self.loop.run_until_complete(self.http.close()))

    def call(self, method, path, **kw):
        async def go():
            resp = await self.http.request(method, path, **kw)
            return resp.status, await resp.read()
        return self.loop.run_until_complete(go())

    def test_without_brain_parts_are_browsable_and_a_message_says_why_not(self):
        status, body = self.call("GET", "/api/design/status")
        self.assertEqual(json.loads(body)["brain"]["state"], "missing")
        status, body = self.call("POST", "/api/design/parts", json={"name": "Hook"})
        part = json.loads(body)["part"]
        status, body = self.call("POST", f"/api/design/parts/{part['id']}/message",
                                 json={"text": "a hook"})
        self.assertEqual(status, 409)
        self.assertIn("not installed", json.loads(body)["error"])

    def test_files_are_served_only_from_inside_a_version(self):
        part = parts.create("Hook")
        vdir = parts.version_dir(part["id"], 1)
        (vdir / "bodies").mkdir(parents=True)
        (vdir / "bodies" / "Hook.stl").write_text("solid")
        status, body = self.call("GET", f"/api/design/parts/{part['id']}/file?v=1&path=bodies/Hook.stl")
        self.assertEqual((status, body), (200, b"solid"))
        status, _ = self.call("GET", f"/api/design/parts/{part['id']}/file?v=1&path=../part.json")
        self.assertEqual(status, 404)

    def test_a_thumbnail_must_be_a_png(self):
        part = parts.create("Hook")
        status, _ = self.call("POST", f"/api/design/parts/{part['id']}/thumb", data=b"<svg/>")
        self.assertEqual(status, 400)
        status, _ = self.call("POST", f"/api/design/parts/{part['id']}/thumb",
                              data=b"\x89PNG\r\n\x1a\n" + b"0" * 10)
        self.assertEqual(status, 200)

    def test_only_a_version_that_built_can_be_current(self):
        part = parts.create("Hook")
        part["versions"] = [{"n": 1, "ok": False}, {"n": 2, "ok": True}]
        parts.save(part)
        status, _ = self.call("POST", f"/api/design/parts/{part['id']}", json={"current": 1})
        self.assertEqual(status, 400)
        status, body = self.call("POST", f"/api/design/parts/{part['id']}", json={"current": 2})
        self.assertEqual(json.loads(body)["part"]["current"], 2)


@unittest.skipUnless(os.environ.get("BAMBU_TEST_CAD_PYTHON"),
                     "set BAMBU_TEST_CAD_PYTHON to a Python with CadQuery to build for real")
class TestRealBuild(Isolated):
    def test_the_example_builds_every_file(self):
        with mock.patch.object(runner, "CAD_PYTHON", os.environ["BAMBU_TEST_CAD_PYTHON"]), \
                mock.patch.object(runner, "CAD_DIR", CAD):
            out = self.root / "v1"
            out.mkdir()
            (out / "design.py").write_text(EXAMPLE)
            report = runner.build(out / "design.py", out)
        self.assertTrue(report["ok"], report)
        for name in ("cable_clip.3mf", "cable_clip.step", "cable_clip.stl", "bodies/Clip.stl"):
            self.assertTrue((out / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
