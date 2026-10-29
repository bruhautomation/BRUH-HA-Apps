#!/usr/bin/env python3
"""The plate watch after a finish, the steadiest frame of a burst, and the
owner's brAIn preferences.

The owner, on the Printers tab: "parts show as finished even once they are
removed from the print bed. You should periodically look to see if a part is
removed and clear the UI if so after a part finished. Make that intelligent so
it only looks after a print finishes." And: "The part failure detection
sometimes takes pictures when the print bed is moving." And: "there needs to be
a way to select the model being used and a way to edit the prompt for make a
thing and printing so I can set default settings."

So: with failure detection OFF, the plate watch still runs — it never touches
the camera while a print runs, only once it has finished, until the plate is
seen (or said) clear; a plate somebody said is clear is kept as the empty
plate the next finish is compared with. A look is taken from a short burst of
frames and the sharpest one goes to brAIn. And Settings › brAIn chooses the
model a design turn and a print check run on, and adds standing instructions
to every design turn.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import types
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402
from test_bambu_failure_detection import FakeClient, Harness, noisy  # noqa: E402

(vision, judge, watcher, brain_link, designer, prefs, ftps) = bambu_env.load(
    "watch.vision", "watch.judge", "watch.watcher", "design.brain_link", "design.designer",
    "prefs", "bambu.ftps")


def smeared(grid: "vision.Grid") -> "vision.Grid":
    """The same plate, blurred sideways the way a moving bed smears it."""
    w, h, px = grid.w, grid.h, grid.px
    out = bytearray(px)
    for y in range(h):
        for x in range(w):
            row = [px[y * w + min(w - 1, max(0, x + d))] for d in range(-3, 4)]
            out[y * w + x] = sum(row) // len(row)
    return vision.Grid(bytes(out))


class TestSharpest(unittest.TestCase):
    def test_a_smeared_frame_has_less_edge(self):
        sharp = noisy(5)
        self.assertGreater(vision.sharpness(sharp), vision.sharpness(smeared(sharp)) * 1.5)

    def test_the_sharpest_of_a_burst_is_chosen(self):
        sharp = noisy(5)
        self.assertEqual(vision.sharpest([smeared(sharp), sharp, smeared(smeared(sharp))]), 1)


class PlateOnly(unittest.TestCase):
    """Detection off, the plate watch on (its default), on a fake clock."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = unittest.mock.patch.object(watcher, "SETTINGS_FILE", self.tmp / "settings.json")
        p.start()
        self.addCleanup(p.stop)
        self.client = FakeClient()
        self.panel = types.SimpleNamespace(clients={"p1": self.client}, uploaded={})
        self.w = watcher.Watcher(self.panel, data=self.tmp / "watch", start_threads=False)
        self.t = 1_000_000.0
        self.w.clock = lambda: self.t
        self.w.sleep = lambda _s: None
        self.grid = noisy(1)
        self.frames = 0

        def frame(_pid):
            self.frames += 1
            return b"\xff\xd8\xff" + str(self.frames).encode(), ""
        self.w.frame = frame
        self.w.decode = lambda _jpeg: self.grid
        self.brain = {"state": "off", "sentence": "brAIn is off."}
        self.w.brain_status = lambda: self.brain
        self.asked = []
        self.w.ask = lambda q, images, scheduled=True: (self.asked.append(q) or (None, "no"))
        self.pw = self.w.watch("p1")

    def step(self, n=1, every=60):
        for _ in range(n):
            self.t += every
            self.pw.step(self.t)
            for thread in threading.enumerate():
                if thread.name.startswith("watch-"):
                    thread.join(5)

    def print_and_finish(self):
        self.client.st.update(state="running", layer=10)
        self.step(5, every=30)
        self.assertEqual(self.pw.plate["state"], "printing")
        self.client.st.update(state="finish", layer=150)
        self.step()


class TestThePlateWatchWithDetectionOff(PlateOnly):
    def test_it_is_on_by_default_and_the_printer_gets_a_thread_for_it(self):
        settings = self.w.settings_for("p1")
        self.assertFalse(settings["enabled"])
        self.assertTrue(settings["plate"])
        self.assertTrue(self.w.wanted("p1"))
        self.w.update_settings("p1", {"plate": False})
        self.assertFalse(self.w.wanted("p1"))

    def test_it_never_looks_while_a_print_runs(self):
        self.client.st.update(state="running", layer=10)
        self.step(20, every=30)
        self.assertEqual(self.frames, 0)

    def test_a_finished_print_is_on_the_plate_until_it_looks_like_the_empty_plate(self):
        empty = self.grid
        self.pw._store_empty(empty, b"\xff\xd8\xffempty")
        self.grid = noisy(42)  # the finished part on the plate
        self.print_and_finish()
        self.step(3)
        self.assertEqual(self.pw.plate["state"], "occupied")
        self.assertEqual(self.w.summary("p1", "finish")["plate"]["state"], "occupied")
        self.grid = empty  # the part is taken off
        self.step(3)
        self.assertEqual(self.pw.plate["state"], "clear")
        self.assertEqual(self.w.summary("p1", "finish")["status"], "off")
        self.assertEqual(self.w.summary("p1", "finish")["plate"]["state"], "clear")
        looked = self.frames
        self.step(10)
        self.assertEqual(self.frames, looked, "a clear plate is not watched any more")

    def test_it_stops_after_the_watch_window(self):
        self.grid = noisy(42)
        self.print_and_finish()
        self.step(1, every=watcher.PLATE_WATCH_S + 60)
        looked = self.frames
        self.step(5)
        self.assertEqual(self.frames, looked)

    def test_a_plate_said_clear_is_learnt_as_the_empty_plate(self):
        self.grid = noisy(42)
        self.print_and_finish()
        self.grid = noisy(7)  # the plate as it is once the part is off
        self.assertIn("clear", self.pw.act("plate_clear"))
        for thread in threading.enumerate():
            if thread.name.startswith("watch-empty"):
                thread.join(5)
        self.assertEqual(self.pw.empty_ref, self.grid)
        # The next print, the same plate afterwards: clear without anybody saying so.
        self.grid = noisy(43)
        self.print_and_finish()
        self.step(2)
        self.assertEqual(self.pw.plate["state"], "occupied")
        self.grid = noisy(7)
        self.step(3)
        self.assertEqual(self.pw.plate["state"], "clear")

    def test_a_printer_already_finished_when_the_watch_starts_is_watched(self):
        self.client.st.update(state="finish", layer=150)
        self.step()
        self.assertEqual(self.pw.plate["state"], "occupied")

    def test_with_no_empty_plate_known_brain_is_asked_once_the_plate_changes(self):
        self.brain = {"state": "ok", "sentence": "ok"}
        self.w.ask = lambda q, images, scheduled=True: (self.asked.append(q) or (judge.parse({
            "verdict": "ok", "confidence": 0.9, "problem": "none", "summary": "The plate is empty.",
            "plate": "empty"}), ""))
        self.grid = noisy(42)
        self.print_and_finish()
        self.step(2)
        self.assertEqual(self.asked, [])
        self.grid = noisy(7)  # somebody took the part off
        self.step(2)
        self.assertEqual(len(self.asked), 1)
        self.assertIn("Has the finished print been taken off", self.asked[0])
        self.assertEqual(self.pw.plate["state"], "clear")
        self.assertEqual(self.pw.empty_ref, self.grid)


class TestALookUsesTheSteadiestFrame(Harness):
    def test_brain_is_shown_the_sharp_frame_not_the_smeared_one(self):
        sharp = noisy(9)
        frames = {b"\xff\xd8\xff-smear1": smeared(sharp), b"\xff\xd8\xff-sharp": sharp,
                  b"\xff\xd8\xff-smear2": smeared(smeared(sharp))}
        order = iter([b"\xff\xd8\xff-sharp", b"\xff\xd8\xff-smear2", b"\xff\xd8\xff-smear1"] * 10)
        shown = []

        def ask(question, images, scheduled=True):
            shown.append(images[0])
            return judge.parse({"verdict": "ok", "confidence": 0.9, "problem": "none",
                                "summary": "Fine.", "plate": "has_print"}), ""
        self.start_print()
        self.w.ask = ask
        self.w.frame = lambda pid: (next(order), "")
        self.w.decode = lambda jpeg: frames.get(jpeg, noisy(1))
        self.pw.last_frame = b"\xff\xd8\xff-smear1"
        self.pw._launch({"kind": "manual", "why": "test", "at": self.t}, self.client.summary())
        for thread in threading.enumerate():
            if thread.name.startswith("watch-"):
                thread.join(5)
        self.assertEqual(shown, [b"\xff\xd8\xff-sharp"])

    def test_the_question_says_a_moving_bed_is_not_a_failure(self):
        text = judge.prompt({"file": "Gear"})
        self.assertIn("A1's bed slides", text)
        self.assertIn("neither is a problem with the print", text)


class TestPreferences(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        p = unittest.mock.patch.object(prefs, "FILE", self.tmp / "preferences.json")
        p.start()
        self.addCleanup(p.stop)

    def test_defaults_and_a_saved_change(self):
        self.assertEqual(prefs.load()["design_model"], "default")
        saved = prefs.update({"design_model": "Opus", "design_notes": "  Walls 2 mm.  "})
        self.assertEqual(saved["design_model"], "opus")
        self.assertEqual(prefs.load()["design_notes"], "Walls 2 mm.")

    def test_only_a_known_model_is_kept(self):
        # brAIn's listener puts the model on a command line.
        for bad in ("opus --dangerously", "gpt-4", "sonnet; rm -rf /"):
            with self.assertRaises(ValueError):
                prefs.update({"look_model": bad})
        with self.assertRaises(ValueError):
            prefs.update({"design_notes": "x" * (prefs.NOTES_MAX + 1)})
        with self.assertRaises(ValueError):
            prefs.update({"colour": "red"})
        (self.tmp / "preferences.json").write_text(json.dumps({"design_model": "rm -rf"}))
        self.assertEqual(prefs.load()["design_model"], "default")

    def test_the_model_reaches_the_task_only_when_one_is_chosen(self):
        shared = self.tmp / "brain"
        (shared / "tasks").mkdir(parents=True)
        with unittest.mock.patch.object(brain_link, "BRAIN_SHARED", shared):
            plain = brain_link.submit("hi", schema={})
            chosen = brain_link.submit("hi", schema={}, model="haiku")
            default = brain_link.submit("hi", schema={}, model="default")
        read = lambda tid: json.loads((shared / "tasks" / f"{tid}.json").read_text())  # noqa: E731
        self.assertNotIn("model", read(plain))
        self.assertEqual(read(chosen)["model"], "haiku")
        self.assertNotIn("model", read(default))

    def test_a_design_turn_carries_the_standing_instructions(self):
        prefs.update({"design_notes": "Round every outside edge 1 mm.",
                      "print_notes": "Textured PEI plate, 3 walls."})
        lines = "\n".join(designer.owner_notes())
        self.assertIn("Round every outside edge 1 mm.", lines)
        self.assertIn("Textured PEI plate, 3 walls.", lines)
        self.assertIn("unless the person asks otherwise", lines)
        prefs.update({"design_notes": "", "print_notes": ""})
        self.assertEqual(designer.owner_notes(), [])


class TestPrinterFileDates(unittest.TestCase):
    NOW = 1761739200.0  # 2025-10-29 12:00 UTC

    def test_this_years_rows_and_older_ones(self):
        self.assertEqual(ftps.listing_time("Oct 20 10:02", self.NOW), 1760954520.0)
        self.assertEqual(ftps.listing_time("Mar  3  2024", self.NOW), 1709424000.0)

    def test_a_date_that_would_be_in_the_future_was_last_year(self):
        self.assertEqual(ftps.listing_time("Dec 24 09:00", self.NOW), 1735030800.0)

    def test_nonsense_is_none(self):
        for text in (None, "", "yesterday", "Foo 1 10:00", "Oct x 10:00"):
            self.assertIsNone(ftps.listing_time(text, self.NOW))


if __name__ == "__main__":
    unittest.main()
