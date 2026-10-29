#!/usr/bin/env python3
"""BRUH Bambu Studio's print failure detection, driven with a fake printer.

The camera, the printer and brAIn are fakes at the Watcher's doors (`frame`,
`decode`, `summary_of`, `ask`, `command`), so the real state machine runs a
whole print: the plan read out of G-code, the free looks at every frame, the
looks brAIn is asked for, and what a verdict does to the printer.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import threading
import types
import unittest
import unittest.mock
import zipfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

(server, brain_link, vision, plan, judge, watcher) = bambu_env.load(
    "server", "design.brain_link", "watch.vision", "watch.plan", "watch.judge", "watch.watcher")

REPO = Path(__file__).resolve().parent.parent
LISTENER = REPO / "brain" / "integrations" / "automation-listener.sh"


def noisy(seed: int, base: int = 120, spread: int = 40) -> "vision.Grid":
    r = random.Random(seed)
    return vision.Grid(bytes(max(0, min(255, base + r.randint(-spread, spread)))
                             for _ in range(vision.W * vision.H)))


def flat(level: int) -> "vision.Grid":
    return vision.Grid(bytes([level]) * (vision.W * vision.H))


def gcode(layers: int = 150, base: int = 40, narrow_at: int = 11, top: int = 6,
          bridge_at: int = 30, tool_at: int = 40, minutes: int = 120) -> list[str]:
    """A Bambu-shaped G-code: a wide base, then a thin column, a bridge, a colour change."""
    lines = ["M83", "; FEATURE: Custom", "G1 X5 Y5", "G1 X200 Y5 E20"]  # the purge line
    for n in range(1, layers + 1):
        lines += ["; CHANGE_LAYER", f"; Z_HEIGHT: {0.2 * n:.2f}", "; LAYER_HEIGHT: 0.2",
                  f"M73 P{n * 100 // layers} R{max(0, minutes - n * minutes // layers)}"]
        if n == 1:
            lines.append("T0")
        if n == tool_at:
            lines.append("T1")
        size = base if n < narrow_at else top
        lines.append("; FEATURE: Bridge" if n == bridge_at else "; FEATURE: Outer wall")
        lines += ["G1 X100 Y100", f"G1 X{100 + size} Y100 E1", f"G1 X{100 + size} Y{100 + size} E1",
                  f"G1 X100 Y{100 + size} E1", "G1 X100 Y100 E1"]
        for k in range(0, size, 2):
            lines += [f"G1 X100 Y{100 + k}", f"G1 X{100 + size} Y{100 + k} E1"]
        lines += ["; FEATURE: Prime tower", "G1 X10 Y200", "G1 X40 Y230 E3"]
    return lines


class TestVision(unittest.TestCase):
    def test_a_covered_lens_is_flat_at_any_brightness(self):
        self.assertEqual(vision.view(flat(140), True), "covered")
        self.assertEqual(vision.view(flat(140), False), "covered")

    def test_dark_is_covered_only_when_the_light_is_on(self):
        self.assertEqual(vision.view(noisy(1, base=8, spread=6), False), "dark")
        self.assertEqual(vision.view(noisy(1, base=8, spread=6), True), "covered")
        self.assertEqual(vision.view(noisy(1, base=8, spread=6), None), "dark")

    def test_a_real_picture_is_seen(self):
        self.assertEqual(vision.view(noisy(2), True), "ok")

    def test_the_light_changing_is_not_the_plate_changing(self):
        a = noisy(3, base=110)
        brighter = vision.Grid(bytes(min(255, p + 30) for p in a.px))
        self.assertTrue(vision.looks_like(brighter, a))
        self.assertFalse(vision.looks_like(noisy(4, base=110), a))

    def test_a_sudden_change_is_a_spike_and_slow_growth_is_not(self):
        tracker = vision.ChangeTracker()
        base = noisy(5)
        spikes = []
        for i in range(30):
            # The same plate with a different toolhead spot each frame.
            px = bytearray(base.px)
            spot = (i * 37) % (vision.W * vision.H - 20)
            px[spot:spot + 20] = bytes(20)
            spikes.append(tracker.add(vision.Grid(bytes(px)))["spike"])
        self.assertFalse(any(spikes))
        moved = noisy(99)
        for _ in range(4):
            out = tracker.add(moved)
        self.assertTrue(out["spike"] or tracker.add(moved)["spike"])

    def test_a_feed_that_stopped_is_counted(self):
        tracker = vision.ChangeTracker()
        g = noisy(6)
        counts = [tracker.add(g)["frozen"] for _ in range(4)]
        self.assertEqual(counts, [0, 1, 2, 3])

    def test_a_real_jpeg_decodes_through_ffmpeg(self):
        if not watcher.vision.shutil.which("ffmpeg"):
            self.skipTest("ffmpeg is not installed here")
        out = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                              "testsrc=size=320x240", "-frames:v", "1", "-f", "image2pipe",
                              "-c:v", "mjpeg", "pipe:1"], capture_output=True, check=True)
        grid = vision.decode(out.stdout)
        self.assertIsNotNone(grid)
        self.assertEqual(len(grid.px), vision.W * vision.H)
        self.assertIsNone(vision.decode(b"not a jpeg"))


class TestPlan(unittest.TestCase):
    def setUp(self):
        self.facts = plan.analyse(gcode())

    def test_the_layers_and_their_footprint_are_read(self):
        self.assertEqual(len(self.facts["layers"]), 150)
        self.assertEqual(self.facts["total_min"], 120)
        self.assertAlmostEqual(self.facts["height"], 30.0)
        # 40 mm square on a 2 mm grid; the purge line and prime tower are not the part.
        self.assertLess(self.facts["base_cells"], 500)
        self.assertGreater(self.facts["base_cells"], 380)
        self.assertTrue(self.facts["layers"][39]["tool_change"])
        self.assertIn("bridge", self.facts["layers"][29]["features"])

    def test_the_risky_moments_are_where_this_print_fails(self):
        points = plan.from_gcode(self.facts, "medium")["checkpoints"]
        kinds = {p["kind"]: p["layer"] for p in points}
        self.assertEqual(kinds["first_layer"], 2)
        self.assertIn("early", kinds)
        self.assertEqual(kinds["narrowing"], 13)
        self.assertEqual(kinds["bridge"], 32)
        self.assertEqual(kinds["colour"], 41)
        self.assertEqual(kinds["last"], 150)
        self.assertIn("narrows sharply at layer 11", next(p for p in points if p["kind"] == "narrowing")["reason"])

    def test_a_budget_and_a_gap_keep_it_from_looking_all_the_time(self):
        for sensitivity, budget in plan.BUDGETS.items():
            points = plan.from_gcode(self.facts, sensitivity)["checkpoints"]
            self.assertLessEqual(len(points), budget, sensitivity)
            layers = [p["layer"] for p in points]
            self.assertEqual(layers, sorted(layers))
            self.assertTrue(all(b - a >= plan.MIN_GAP_LAYERS for a, b in zip(layers, layers[1:])))
        self.assertEqual(plan.from_gcode(self.facts, "low")["checkpoints"][0]["kind"], "first_layer")

    def test_a_long_quiet_stretch_gets_one_routine_look(self):
        points = plan.from_gcode(self.facts, "medium")["checkpoints"]
        self.assertTrue(any(p["kind"] == "fill" and 41 < p["layer"] < 150 for p in points))

    def test_a_tall_part_on_a_small_base_is_a_moment(self):
        facts = plan.analyse(gcode(layers=200, base=8, narrow_at=999, bridge_at=999, tool_at=999))
        kinds = [p["kind"] for p in plan.candidates(facts)]
        self.assertIn("tall", kinds)

    def test_a_print_whose_file_cannot_be_read_is_spread_by_layer(self):
        est = plan.estimated(200, "medium")
        self.assertEqual(est["source"], "estimate")
        layers = [p["layer"] for p in est["checkpoints"]]
        self.assertEqual(layers[0], 2)
        self.assertEqual(layers[-1], 200)
        self.assertLessEqual(len(layers), plan.BUDGETS["medium"])
        self.assertEqual(plan.estimated(None)["checkpoints"][0]["layer"], 2)

    def test_the_plate_is_read_out_of_a_sliced_3mf(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as z:
            z.writestr("Metadata/plate_2.gcode", "\n".join(gcode(layers=20)))
        facts = plan.read_plate(io.BytesIO(data.getvalue()), 2)
        self.assertEqual(len(facts["layers"]), 20)
        self.assertIsNone(plan.read_plate(io.BytesIO(b"not a zip"), 1))


class TestJudge(unittest.TestCase):
    def answer(self, **kw):
        base = {"verdict": "failure", "confidence": 0.9, "problem": "spaghetti",
                "summary": "Spaghetti.", "plate": "has_print"}
        return judge.parse({**base, **kw})

    def test_an_answer_outside_the_vocabulary_is_no_answer(self):
        self.assertIsNone(judge.parse({"verdict": "maybe", "confidence": 1, "problem": "none",
                                       "summary": "", "plate": "unknown"}))
        self.assertIsNone(judge.parse({"verdict": "ok", "confidence": "high", "problem": "none",
                                       "summary": "", "plate": "unknown"}))
        self.assertIsNone(judge.parse({"verdict": "ok", "confidence": 2, "problem": "none",
                                       "summary": "", "plate": "unknown"}))
        self.assertIsNone(judge.parse("text"))
        self.assertEqual(judge.parse({"verdict": "ok", "confidence": 0.9, "problem": "blob",
                                      "summary": "", "plate": "unknown"})["problem"], "none")

    def test_a_sure_failure_pauses_and_less_only_warns(self):
        self.assertEqual(judge.decide(self.answer()), "failure")
        self.assertEqual(judge.decide(self.answer(confidence=0.6)), "warning")
        self.assertEqual(judge.decide(self.answer(confidence=0.3)), "watch")
        self.assertEqual(judge.decide(self.answer(confidence=0.8), sensitivity="low"), "warning")
        self.assertEqual(judge.decide(self.answer(confidence=0.7), sensitivity="high"), "failure")

    def test_warn_mode_never_pauses_and_some_problems_never_do(self):
        self.assertEqual(judge.decide(self.answer(), mode="warn"), "warning")
        self.assertEqual(judge.decide(self.answer(problem="stringing")), "warning")

    def test_what_the_owner_said_is_kept(self):
        self.assertEqual(judge.decide(self.answer(), ignored=["spaghetti"]), "ignored")
        self.assertEqual(judge.decide(self.answer(), no_pause=["spaghetti"]), "warning")
        self.assertEqual(judge.decide(self.answer(verdict="cannot_see")), "blind")
        self.assertEqual(judge.decide(self.answer(verdict="ok", problem="none")), "ok")

    def test_the_prompt_carries_what_the_code_knows(self):
        text = judge.prompt({"file": "Gear", "layer": 13, "total_layers": 150, "progress": 9,
                             "why": "The print narrows sharply.", "expected": True, "earlier": True,
                             "z_mm": 2.6, "ignored": "stringing"})
        for needle in ("Gear", "Layer 13 of 150", "narrows sharply", "Picture 2", "Picture 3",
                       "2.6 mm", "ignore: stringing", "toolhead"):
            self.assertIn(needle, text)


class FakeClient:
    def __init__(self):
        self.st = {"online": True, "state": "idle", "layer": 0, "total_layers": 150, "file": "Gear",
                   "gcode_file": "Metadata/plate_1.gcode", "hms": [], "chamber_light": True,
                   "progress": 0, "stage": None}
        self.sent = []

    def summary(self):
        return dict(self.st)

    def send(self, payload):
        self.sent.append(payload)
        return {"acknowledged": True}


class Harness(unittest.TestCase):
    """A Watcher whose doors are fakes, stepped on a fake clock."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for name, value in (("SETTINGS_FILE", self.tmp / "settings.json"),
                            ("SHARED", self.tmp / "shared")):
            p = unittest.mock.patch.object(watcher, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = FakeClient()
        self.panel = types.SimpleNamespace(clients={"p1": self.client}, uploaded={})
        self.w = watcher.Watcher(self.panel, data=self.tmp / "watch", start_threads=False)
        self.t = 1_000_000.0
        self.w.clock = lambda: self.t
        self.w.sleep = lambda _s: None  # a look's burst of frames, without the waits
        self.grid = noisy(1)
        self.w.frame = lambda pid: (b"\xff\xd8\xff-frame", "")
        self.frames = 0

        def decode(_jpeg):
            # A camera's frames are never byte-for-byte the same (sensor
            # noise), or the watcher would rightly call the feed frozen.
            self.frames += 1
            r = random.Random(self.frames)
            return vision.Grid(bytes(max(0, min(255, p + r.randint(-2, 2))) for p in self.grid.px))
        self.w.decode = decode
        self.w.row = lambda pid: {"id": "p1", "name": "X1C", "model": "X1C"}
        self.brain = {"state": "ok", "sentence": "ok"}
        self.w.brain_status = lambda: self.brain
        self.w.read_print = lambda pid, s: (plan.analyse(gcode()), b"\x89PNG\r\n\x1a\nexpected", "")
        self.answers: list = []
        self.asked: list = []

        def ask(question, images, scheduled=True):
            self.asked.append((question, len(images), scheduled))
            data = self.answers.pop(0) if self.answers else {
                "verdict": "ok", "confidence": 0.9, "problem": "none", "summary": "Fine.",
                "plate": "has_print"}
            return judge.parse(data), ""
        self.w.ask = ask
        self.w.update_settings("p1", {"enabled": True})
        self.pw = self.w.watch("p1")

    def step(self, n=1, every=11):
        for _ in range(n):
            self.t += every
            self.pw.step(self.t)
            self.pw.finish_look_due(self.t)
            for thread in threading.enumerate():
                if thread.name.startswith("watch-"):
                    thread.join(5)

    def start_print(self):
        self.step()
        self.client.st.update(state="prepare", layer=0)
        self.step(3)
        self.client.st.update(state="running", layer=1)
        self.step()

    def run_to(self, layer, steps=2, every=60):
        self.client.st.update(layer=layer)
        self.step(steps, every)


class TestTheWatcher(Harness):
    def test_it_looks_at_the_checkpoints_and_nowhere_else(self):
        self.start_print()
        self.assertEqual(self.pw.record["plan"]["source"], "gcode")
        self.assertEqual(self.asked, [])
        points = [p["layer"] for p in self.pw.record["plan"]["checkpoints"]]
        for layer in range(2, 151):
            self.run_to(layer, steps=1, every=90)
        looked = [c["layer"] for c in self.pw.record["checks"]]
        self.assertEqual(looked, points)
        self.assertLessEqual(len(self.asked), plan.BUDGETS["medium"])
        self.assertTrue(all(scheduled for _q, _n, scheduled in self.asked))

    def test_brain_gets_the_frame_the_picture_and_the_last_frame(self):
        self.start_print()
        self.run_to(2)
        self.assertEqual(self.asked[0][1], 2)  # the frame and the plate's picture
        self.run_to(8, every=300)
        question, images, _ = self.asked[1]
        self.assertEqual(images, 3)
        self.assertIn("previous look", question)

    def test_a_failure_pauses_the_printer(self):
        self.start_print()
        self.answers = [{"verdict": "failure", "confidence": 0.92, "problem": "spaghetti",
                         "summary": "Spaghetti behind the part.", "plate": "has_print"}]
        self.run_to(2)
        alert = self.pw.record["alert"]
        self.assertEqual(alert["level"], "failure")
        self.assertTrue(alert["paused"])
        self.assertIn({"print": {"command": "pause", "param": ""}}, self.client.sent)
        self.assertEqual(self.w.summary("p1", "running")["status"], "failure")

    def test_warn_mode_tells_and_does_not_pause(self):
        self.w.update_settings("p1", {"mode": "warn"})
        self.start_print()
        self.answers = [{"verdict": "failure", "confidence": 0.95, "problem": "detached",
                         "summary": "The part came loose.", "plate": "has_print"}]
        self.run_to(2)
        self.assertEqual(self.pw.record["alert"]["level"], "warning")
        self.assertNotIn({"print": {"command": "pause", "param": ""}}, self.client.sent)

    def test_a_doubt_is_looked_at_again_and_cleared(self):
        self.start_print()
        self.answers = [{"verdict": "warning", "confidence": 0.7, "problem": "warping",
                         "summary": "A corner may be lifting.", "plate": "has_print"}]
        self.run_to(2)
        self.assertTrue(self.pw.record["alert"]["open"])
        self.t += watcher.FOLLOW_UP_S
        self.run_to(3)
        self.assertEqual([c["trigger"] for c in self.pw.record["checks"]], ["checkpoint", "follow_up"])
        self.assertFalse(self.pw.record["alert"]["open"])
        self.assertEqual(self.pw.record["alert"]["answer"], "cleared")

    def test_ignore_keeps_quiet_about_that_problem_and_resume_stops_pausing_for_it(self):
        self.start_print()
        self.answers = [{"verdict": "warning", "confidence": 0.7, "problem": "stringing",
                         "summary": "Stringing.", "plate": "has_print"}]
        self.run_to(2)
        alert_id = self.pw.record["alert"]["id"]
        with self.assertRaises(ValueError):
            self.pw.act("ignore", "someone-else")
        self.assertIn("Ignoring stringing", self.pw.act("ignore", alert_id))
        self.answers = [{"verdict": "warning", "confidence": 0.9, "problem": "stringing",
                         "summary": "More stringing.", "plate": "has_print"}]
        self.t += watcher.FOLLOW_UP_S
        self.run_to(3)
        self.assertEqual(self.pw.record["checks"][-1]["decision"], "ignored")
        self.assertFalse(self.pw.record["alert"]["open"])
        self.answers = [{"verdict": "failure", "confidence": 0.95, "problem": "spaghetti",
                         "summary": "Spaghetti.", "plate": "has_print"}]
        self.run_to(8, every=300)
        self.client.st.update(state="pause")
        self.pw.act("resume")
        self.assertEqual(self.client.sent[-1], {"print": {"command": "resume", "param": ""}})
        self.assertEqual(self.pw.record["no_pause"], ["spaghetti"])

    def test_a_covered_lens_stands_everything_down(self):
        self.start_print()
        self.grid = flat(130)
        self.run_to(2, steps=3)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.w.summary("p1", "running")["status"], "covered")
        with self.assertRaises(ValueError):
            self.pw.act("check")
        self.grid = noisy(1)
        self.run_to(3)
        self.assertEqual(len(self.asked), 1)

    def test_a_dark_chamber_gets_its_light_once(self):
        self.start_print()
        self.client.st.update(chamber_light=False)
        self.grid = noisy(1, base=6, spread=4)
        self.step(4)
        lights = [p for p in self.client.sent if "system" in p]
        self.assertEqual(len(lights), 1)
        self.assertEqual(lights[0]["system"]["led_mode"], "on")
        self.assertEqual(self.w.summary("p1", "running")["status"], "dark")

    def test_the_printers_own_camera_asks_for_a_look_now(self):
        self.start_print()
        self.run_to(2)
        self.client.st.update(hms=["0C00_0300_0003_000B"], layer=5)
        self.step(1, every=100)
        self.assertEqual(self.pw.record["checks"][-1]["trigger"], "printer_camera")

    def test_without_brain_the_printers_own_camera_still_warns(self):
        self.brain = {"state": "off", "sentence": "brAIn is off."}
        self.start_print()
        self.client.st.update(hms=["0C00_0300_0003_000B"])
        self.step()
        self.assertEqual(self.pw.record["alert"]["level"], "warning")
        self.assertEqual(self.asked, [])
        self.assertEqual(self.w.summary("p1", "running")["status"], "warning")

    def test_triggers_cannot_spend_past_the_budget(self):
        self.start_print()
        budget = plan.BUDGETS["medium"] + plan.TRIGGER_EXTRA
        for i in range(40):
            self.pw.triggers.append({"kind": "change", "why": "x", "at": self.t, "urgent": True})
            self.run_to(3 + (i % 2), steps=1, every=watcher.URGENT_LOOK_GAP_S + 1)
        self.assertLessEqual(self.pw.record["looks"], budget)

    def test_the_plate_is_clear_when_it_looks_empty_again(self):
        self.start_print()
        empty = self.grid
        self.run_to(2)
        self.grid = noisy(42)
        self.client.st.update(state="finish", layer=150)
        self.step(3, every=60)
        self.assertEqual(self.pw.plate["state"], "occupied")
        self.grid = empty
        self.step(3, every=60)
        self.assertEqual(self.pw.plate["state"], "clear")
        self.assertEqual(self.w.summary("p1", "finish")["plate"]["state"], "clear")

    def test_a_manual_look_and_marking_the_plate(self):
        self.start_print()
        self.assertIn("looking", self.pw.act("check"))
        for thread in threading.enumerate():
            if thread.name.startswith("watch-"):
                thread.join(5)
        self.assertEqual(self.pw.record["checks"][-1]["trigger"], "manual")
        self.assertFalse(self.asked[-1][2])
        self.assertEqual(self.pw.record["looks"], 0)
        self.assertIn("clear", self.pw.act("plate_clear"))

    def test_a_frozen_feed_stands_looks_down(self):
        self.start_print()
        self.w.decode = lambda jpeg: self.grid
        self.step(watcher.FROZEN_AFTER + 2)
        self.run_to(2)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.w.summary("p1", "running")["status"], "frozen")

    def test_off_does_nothing(self):
        self.w.update_settings("p1", {"enabled": False})
        self.start_print()
        self.run_to(2)
        self.assertEqual(self.asked, [])
        self.assertEqual(self.w.summary("p1", "running")["status"], "off")

    def test_a_brain_that_does_not_answer_gives_the_look_back(self):
        self.start_print()
        self.w.ask = lambda q, i, scheduled=True: (None, "brAIn did not pick the request up.")
        self.run_to(2)
        self.assertEqual(self.pw.record["looks"], 0)
        self.assertEqual(self.pw.record["plan"]["checkpoints"][0]["state"], "skipped")
        self.assertIn("did not pick", self.pw.record["errors"][-1]["error"])

    def test_images_served_are_only_its_own(self):
        self.start_print()
        self.run_to(2)
        rid = self.pw.record["id"]
        self.assertIsNotNone(self.pw.image(f"{rid}/1.jpg"))
        for bad in ("../settings.json", f"{rid}/../../x.jpg", "/etc/passwd", f"{rid}/1.png"):
            self.assertIsNone(self.pw.image(bad), bad)

    def test_settings_are_checked(self):
        with self.assertRaises(ValueError):
            self.w.update_settings("p1", {"mode": "explode"})
        with self.assertRaises(ValueError):
            self.w.update_settings(None, {"notify": "light.kitchen"})
        self.assertEqual(self.w.update_settings(None, {"notify": "notify.mobile_app_x"}),
                         {"notify": "notify.mobile_app_x"})


class TestBrainGetsPictures(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "tasks").mkdir()
        (self.tmp / "task_results").mkdir()
        p = unittest.mock.patch.object(brain_link, "BRAIN_SHARED", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def test_a_look_carries_its_pictures_and_is_not_a_conversation(self):
        task_id = brain_link.submit("look", schema={}, kind="look", scheduled=True,
                                    images=[b"\xff\xd8\xffjpg", b"\x89PNG\r\n\x1a\npng", b"nope"])
        task = json.loads((self.tmp / "tasks" / f"{task_id}.json").read_text())
        self.assertNotIn("kind", task)
        self.assertTrue(task["scheduled"])
        self.assertEqual(task["tools"], "read_only")
        self.assertEqual([Path(p).suffix for p in task["images"]], [".jpg", ".png"])
        (self.tmp / "tasks" / f"{task_id}.json").unlink()
        (self.tmp / "task_results" / f"{task_id}.json").write_text(json.dumps({"status": "completed"}))
        brain_link.wait(task_id, 5)
        self.assertEqual(list((self.tmp / "task_images").iterdir()), [])

    def test_a_design_turn_is_still_a_conversation(self):
        task_id = brain_link.submit("make a hook", schema={})
        task = json.loads((self.tmp / "tasks" / f"{task_id}.json").read_text())
        self.assertEqual(task["kind"], "conversation")
        self.assertNotIn("images", task)


class TestTheListenerHandsPicturesOver(unittest.TestCase):
    """brAIn's automation listener: a task's pictures become image blocks."""

    def run_fn(self, images, folder: Path) -> dict | None:
        source = LISTENER.read_text()
        fn = re.search(r"^task_images_message\(\) \{.*?^\}$", source, re.S | re.M).group(0)
        prompt = folder.parent / "prompt.txt"
        prompt.write_text("Is it failing?")
        out = subprocess.run(["bash", "-c", fn + '\ntask_images_message "$1" "$2"', "x",
                              json.dumps(images), str(prompt)],
                             env={**os.environ, "TASK_IMAGE_DIR": str(folder)},
                             capture_output=True, text=True, timeout=30)
        return json.loads(out.stdout) if out.stdout.strip() else None

    def test_only_real_pictures_in_its_folder_are_read_and_then_deleted(self):
        root = Path(tempfile.mkdtemp())
        folder = root / "task_images"
        folder.mkdir()
        (folder / "a-0.jpg").write_bytes(b"\xff\xd8\xff\xe0frame")
        (folder / "a-1.jpg").write_bytes(b"#!/bin/sh not a picture")
        secret = root / "secrets.yaml"
        secret.write_bytes(b"\xff\xd8\xff pretend")
        message = self.run_fn([str(folder / "a-0.jpg"), str(folder / "a-1.jpg"), str(secret),
                               str(folder / ".." / "secrets.yaml")], folder)
        blocks = message["message"]["content"]
        self.assertEqual([b["type"] for b in blocks], ["image", "text"])
        self.assertEqual(blocks[0]["source"]["media_type"], "image/jpeg")
        self.assertEqual(blocks[1]["text"], "Is it failing?")
        self.assertEqual(list(folder.iterdir()), [])
        self.assertTrue(secret.exists())

    def test_no_usable_picture_runs_as_text(self):
        folder = Path(tempfile.mkdtemp()) / "task_images"
        folder.mkdir()
        self.assertIsNone(self.run_fn(["/etc/passwd"], folder))

    def test_every_attempt_feeds_the_same_input(self):
        source = LISTENER.read_text()
        self.assertNotIn("printf '%s' \"$prompt\" | timeout", source)
        self.assertEqual(source.count("task_feed | timeout"), 3)
        self.assertEqual(source.count('task_envelope_from_stream "$output_file"'), 3)
        self.assertIn("--input-format stream-json --output-format stream-json --verbose", source)


class TestRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from aiohttp.test_utils import TestClient, TestServer
        self.tmp = Path(tempfile.mkdtemp())
        p = unittest.mock.patch.object(watcher, "SETTINGS_FILE", self.tmp / "s.json")
        p.start()
        self.addCleanup(p.stop)
        self.panel = server.Panel(start_clients=False)
        self.panel.watch = watcher.Watcher(self.panel, data=self.tmp / "w", start_threads=False)
        self.row = {"id": "p1", "name": "A1", "host": "127.0.0.1", "serial": "S", "model": "A1"}
        self.panel.clients["p1"] = FakeClient()
        for target, attr, value in ((server.store, "resolve", lambda rows, wanted: self.row),
                                    (server.store, "load", lambda: [self.row])):
            p = unittest.mock.patch.object(target, attr, value)
            p.start()
            self.addCleanup(p.stop)
        self.client = TestClient(TestServer(server.build_app(self.panel, ticker=False)))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    async def test_detection_is_switched_on_and_shows_in_the_state(self):
        r = await self.client.post("/api/watch/settings", json={"printer": "p1", "enabled": True,
                                                                  "sensitivity": "high"})
        self.assertEqual(r.status, 200)
        state = await (await self.client.get("/api/state")).json()
        fd = state["printers"][0]["failure_detection"]
        self.assertTrue(fd["enabled"])
        self.assertEqual(fd["sensitivity"], "high")
        self.assertEqual(fd["status"], "idle")

    async def test_answers_without_an_alert_are_refused(self):
        await self.client.post("/api/watch/settings", json={"printer": "p1", "enabled": True})
        r = await self.client.post("/api/watch/action", json={"printer": "p1", "action": "ignore"})
        self.assertEqual(r.status, 409)
        r = await self.client.post("/api/watch/action", json={"printer": "p1", "action": "explode"})
        self.assertEqual(r.status, 400)
        r = await self.client.get("/api/watch/image", params={"printer": "p1", "name": "../s.json"})
        self.assertEqual(r.status, 404)

    async def test_a_look_is_refused_while_detection_is_off(self):
        r = await self.client.post("/api/watch/action", json={"printer": "p1", "action": "check"})
        self.assertEqual(r.status, 409)
        self.assertIn("off", (await r.json())["error"])


class TestDownloadsHaveNames(unittest.TestCase):
    def test_the_part_name_version_and_kind(self):
        self.assertEqual(server.download_name("Wall hook", 3, ".3MF"), "Wall hook v3.3mf")
        self.assertEqual(server.download_name('a/b:c*"', 1, ".step"), "a b c v1.step")
        self.assertEqual(server.download_name("...", 2, ".stl"), "part v2.stl")

    def test_any_name_survives_the_header(self):
        header = server.content_disposition("Crochet hook — café v2.3mf")
        self.assertTrue(header.startswith("attachment; filename=\""))
        self.assertIn("filename*=UTF-8''Crochet%20hook%20%E2%80%94%20caf%C3%A9%20v2.3mf", header)
        self.assertNotIn("\n", header)


class TestHomeAssistantAlerts(unittest.TestCase):
    def setUp(self):
        from test_addon_service_responses import INTEGRATIONS, _stubs
        stubs = _stubs()
        saved = {k: sys.modules.get(k) for k in stubs}
        sys.modules.update(stubs)
        pkg = "_watch_alerts_bruh_bambu"
        try:
            folder = INTEGRATIONS["bruh_bambu"]
            spec = importlib.util.spec_from_file_location(
                pkg, folder / "__init__.py", submodule_search_locations=[str(folder)])
            module = importlib.util.module_from_spec(spec)
            sys.modules[pkg] = module
            spec.loader.exec_module(module)
            self.alerts = sys.modules[f"{pkg}.alerts"]
        finally:
            for k, v in saved.items():
                if v is None:
                    sys.modules.pop(k, None)
                else:
                    sys.modules[k] = v

    def test_a_button_names_its_alert(self):
        self.assertEqual(self.alerts.parse_action("BRUH_BAMBU_WATCH:ignore:p1:abc-1"),
                         ("ignore", "p1", "abc-1"))
        self.assertIsNone(self.alerts.parse_action("BRUH_BAMBU_WATCH:explode:p1:abc"))
        self.assertIsNone(self.alerts.parse_action("SOMEONE_ELSE:ignore:p1:abc"))

    def test_the_words_say_what_happened(self):
        title, message, kind = self.alerts.message_for("X1C", {"level": "failure", "paused": True,
                                                               "summary": "Spaghetti."})
        self.assertEqual((title, kind), ("X1C: print paused", "failure"))
        self.assertIn("Resume it if this is a false alarm", message)
        _t, message, kind = self.alerts.message_for("X1C", {"level": "failure", "paused": False,
                                                            "summary": "Spaghetti.",
                                                            "pause_error": "Developer Mode."})
        self.assertEqual(kind, "failure_unpaused")
        self.assertIn("Developer Mode", message)
        self.assertEqual(self.alerts.message_for("X1C", {"level": "warning"})[2], "warning")


if __name__ == "__main__":
    unittest.main()
