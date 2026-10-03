#!/usr/bin/env python3
"""Four places the acting half of brAIn did the wrong thing quietly.

  healing    a fault fixed every night is a fault hidden every night: an
             add-on that stops each evening was started at 3am for ever and
             the morning brief called each one a fresh success
  authoring  every standing rule was forced to `single`, which drops every
             re-trigger while a rule waits — "off five minutes after the
             motion stops" went off on somebody still in the room
  scenes     the schedule's room was read off the scene id by splitting on
             `_`, so `living_room` was looked for as `living` and the
             commonest rooms were offered nothing, silently
  counters   one variable counted the signals handed to the Resident and
             then the proposals filed, so the summary reported the second
             under both names and the hand-off was never seen

Each over the real module or the real server function. Mutations:

  no history        drop the chronic gate in `plan` -> a third heal in a
                    fortnight is attempted again
  count in text     put the count in the finding's text -> every night's
                    re-report is a new finding
  single forever    force `mode: single` -> the restart rule is refused or
                    written wrong
  split on _        take the third piece of the id -> no schedule for a
                    two-word room
  one variable      reuse `offered` -> `offered` equals `proposed`
"""
from __future__ import annotations

import asyncio
import datetime as dt
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import healing  # noqa: E402
from test_authoring import ANSWER, AuthoringCase  # noqa: E402
from test_healing import NOW, PerformCase, finding, house  # noqa: E402
from test_shadow_findings import ShadowCase  # noqa: E402

DAY = 86400.0


# ---------------------------------------------------------------------------
# Healing
# ---------------------------------------------------------------------------

class TestAChronicFaultStopsBeingHealed(unittest.TestCase):

    def plan(self, history):
        return healing.plan([finding()], house(), [], set(),
                            healing.MAX_PER_NIGHT, NOW, history)

    def test_the_window_counts_heals_of_the_target_not_the_row(self):
        attempt = self.plan({})["attempts"][0]
        key = healing.target_key(attempt)
        self.assertEqual(key, "addon.start:core_mosquitto")
        history: dict = {}
        for days_ago in (20, 9, 3):
            healing.record_heal(history, attempt, NOW - days_ago * DAY)
        # The one twenty days ago has fallen out of the window.
        self.assertEqual(len(healing.heals_in_window(history, key, NOW)), 2)
        self.assertEqual(len(self.plan(history)["attempts"]), 1)

    def test_the_third_heal_in_a_fortnight_is_not_attempted(self):
        attempt = self.plan({})["attempts"][0]
        history: dict = {}
        for days_ago in (9, 5, 1):
            healing.record_heal(history, attempt, NOW - days_ago * DAY)
        out = self.plan(history)
        self.assertEqual(out["attempts"], [])
        self.assertEqual(len(out["chronic"]), 1)
        self.assertIn("stopped", out["skips"][0]["reason"])

    def test_the_findings_text_is_stable_and_the_count_is_in_the_detail(self):
        attempt = self.plan({})["attempts"][0]
        three = [int(NOW - d * DAY) for d in (9, 5, 1)]
        four = [int(NOW - d * DAY) for d in (12, 9, 5, 1)]
        a = healing.chronic_finding(attempt, three, dt.timezone.utc)
        b = healing.chronic_finding(attempt, four, dt.timezone.utc)
        self.assertEqual(a["text"], b["text"])
        self.assertIn("keeps stopping", a["text"])
        self.assertIn("3 times", a["detail"])
        self.assertIn("4 times", b["detail"])
        self.assertIs(a["fixable"], False)

    def test_the_brief_says_it_was_not_the_first_time(self):
        state = {"night": "x", "attempts": [{
            "ts": 1, "ok": True, "remedy": "addon.start",
            "target": "core_mosquitto", "sentence": "started Mosquitto",
            "at": NOW, "times": 3}]}
        lines = healing.brief_lines(state, set(), dt.timezone.utc)
        self.assertEqual(len(lines), 1)
        self.assertIn("third time", lines[0])

    def test_the_history_is_capped(self):
        history: dict = {}
        for i in range(healing.MAX_HISTORY_TARGETS + 10):
            healing.record_heal(history, {"remedy": "addon.start",
                                          "target": f"addon_{i}"}, NOW + i)
        self.assertEqual(len(history), healing.MAX_HISTORY_TARGETS)
        self.assertNotIn("addon.start:addon_0", history)


class TestTheServerFilesTheChronicFinding(PerformCase):

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.root = tempfile.TemporaryDirectory()
        self.addCleanup(self.root.cleanup)
        root = Path(self.root.name)
        self._store = healing.STORE
        healing.STORE = root / "healing.json"
        self.addCleanup(lambda: setattr(healing, "STORE", self._store))
        os.environ["BRAIN_JOURNAL_FILE"] = str(root / "journal.jsonl")
        self.addCleanup(lambda: os.environ.pop("BRAIN_JOURNAL_FILE", None))
        self._findings = (findings_store.FINDINGS_FILE,
                          findings_store.SETTLED_FILE,
                          findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"
        self.addCleanup(self._restore_findings)

        self.server = importlib.import_module("server")
        import journal
        journal.JOURNAL_FILE = os.environ["BRAIN_JOURNAL_FILE"]
        self.rows = [finding()]

        async def collect(now=None):
            return house()

        self._old = (self.server.checks.snapshot.collect,
                     self.server.findings_store.list_all,
                     self.server.automation_writer.protected_patterns)
        self.server.checks.snapshot.collect = collect
        self.server.findings_store.list_all = \
            lambda status=None: list(self.rows)
        self.server.automation_writer.protected_patterns = \
            lambda *a, **k: []
        self.addCleanup(self._restore)
        self.server.HEAL_STATE["last"] = None

    def _restore(self):
        (self.server.checks.snapshot.collect,
         self.server.findings_store.list_all,
         self.server.automation_writer.protected_patterns) = self._old

    def _restore_findings(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._findings

    def seed(self, *days_ago: float):
        import time
        now = time.time()
        healing.STORE.write_text(json.dumps({
            "night": "", "attempts": [], "skips": [],
            "history": {"addon.start:core_mosquitto":
                        [int(now - d * DAY) for d in days_ago]}}))

    async def test_a_heal_records_how_many_this_is(self):
        self.seed(6, 2)
        state = await self.server.run_healing("test")
        self.assertEqual(len(state["attempts"]), 1, state)
        self.assertEqual(state["attempts"][0]["times"], 3)
        stored = healing.load()["history"]["addon.start:core_mosquitto"]
        self.assertEqual(len(stored), 3)

    async def test_a_chronic_target_is_filed_and_not_called(self):
        self.seed(9, 5, 1)
        state = await self.server.run_healing("test")
        self.assertEqual(self.calls, [])
        self.assertEqual(state["attempts"], [])
        rows = json.loads(findings_store.FINDINGS_FILE.read_text())
        rows = rows if isinstance(rows, list) else rows.get("findings", [])
        filed = [r for r in rows if r.get("source") == healing.CHRONIC_SOURCE]
        self.assertEqual(len(filed), 1, rows)
        self.assertIn("keeps stopping", filed[0]["text"])
        # Through the gate every producer files through.
        self.assertEqual(filed[0]["status"], "triaging")


# ---------------------------------------------------------------------------
# Authoring
# ---------------------------------------------------------------------------

class TestARuleMayRestart(AuthoringCase):

    def test_restart_is_written_as_asked(self):
        out = self.build({**ANSWER, "mode": "restart"})
        self.assertNotIn("refused", out)
        self.assertEqual(out["config"]["mode"], "restart")

    def test_single_is_the_default(self):
        self.assertEqual(self.build()["config"]["mode"], "single")

    def test_a_mode_that_runs_two_copies_is_refused(self):
        for mode in ("parallel", "queued", "PARALLEL", "anything"):
            with self.subTest(mode=mode):
                out = self.build({**ANSWER, "mode": mode})
                self.assertIn("refused", out)
                self.assertNotIn("config", out)

    def test_a_one_off_ignores_the_mode(self):
        intents = importlib.import_module("intents")
        out = intents.build("when the door opens turn the porch light on",
                            {**ANSWER, "once": True, "mode": "restart"},
                            1_700_000_000_000)
        self.assertEqual(out["config"]["mode"], "single")
        self.assertEqual(out["config"]["action"][-1]["target"]["entity_id"],
                         intents.SELF_TARGET)


# ---------------------------------------------------------------------------
# The scene schedule
# ---------------------------------------------------------------------------

class TestATwoWordRoomGetsItsSchedule(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.server = importlib.import_module("server")
        scenes = self.server.scenes
        self.added: list[dict] = []

        async def replay(session, config, start, end, tz):
            return {"days": 30, "would_run": 28, "triggered": 28}

        self._old = (self.server._replay_config, self.server.proposals.add,
                     self.server.proposals.knows, self.server.rhythm.load)
        self.server._replay_config = replay
        self.server.proposals.add = \
            lambda obj: self.added.append(obj) or obj
        self.server.proposals.knows = lambda obj: False
        self.server.rhythm.load = lambda: {}
        self.addCleanup(self._restore)
        self.snapshot = {
            "areas": [{"area_id": "living_room", "name": "Living Room"},
                      {"area_id": "hall", "name": "Hall"}],
            "states": {},
            "scenes": [{"id": f"{scenes.ID_PREFIX}living_room_{m}",
                        "name": scenes.scene_name("Living Room", m)}
                       for m in scenes.MOODS],
        }

    def _restore(self):
        (self.server._replay_config, self.server.proposals.add,
         self.server.proposals.knows, self.server.rhythm.load) = self._old

    async def test_the_room_slug_keeps_its_underscores(self):
        self.assertEqual(self.server._scene_room_slugs(self.snapshot["scenes"]),
                         {"living_room"})

    async def test_the_schedule_is_offered_under_the_rooms_own_name(self):
        offered = await self.server._offer_scene_schedule(
            self.snapshot, 1_800_000_000)
        self.assertEqual(offered, 1)
        self.assertEqual(self.added[0]["schedule"]["area"], "Living Room")
        targets = {b["sequence"][0]["target"]["entity_id"]
                   for b in self.added[0]["config"]["action"][0]["choose"]}
        self.assertEqual(len(targets), 4)

    async def test_three_of_four_moods_is_not_a_schedule(self):
        self.snapshot["scenes"] = self.snapshot["scenes"][:3]
        self.assertEqual(await self.server._offer_scene_schedule(
            self.snapshot, 1_800_000_000), 0)


# ---------------------------------------------------------------------------
# The pass's two counters
# ---------------------------------------------------------------------------

class TestThePassCountsTwoThings(ShadowCase):

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        import checks
        import test_house_checks as fixture
        self.checks = checks
        snap = fixture.house()

        async def collect(_started=None):
            return snap

        def returning(n):
            async def produce(*a, **kw):
                return n
            return produce

        async def nothing(*a, **kw):
            return 0

        self._patched = {}
        for name, value in (
                ("_record_overrides", lambda *a: None),
                ("_record_rhythm", lambda *a: None),
                ("_record_routines", lambda *a: None),
                ("_announce_findings", nothing),
                ("_offer_findings", lambda *a, **k: 4),
                ("_resident_offer_many", lambda *a, **k: 0),
                ("_measurement_signals", lambda *a, **k: 1),
                ("_resident_offer", lambda *a, **k: None),
                ("_offer_routines", returning(2)),
                ("_offer_playbooks", returning(1)),
                ("_offer_conditions", nothing),
                ("_offer_scene_schedule", nothing),
                ("_evaluate_trials", nothing),
                ("_poll_intents", nothing),
                ("publish_diagnostics", lambda: None)):
            self._patched[name] = getattr(self.server, name)
            setattr(self.server, name, value)
        self._collect = checks.snapshot.collect
        checks.snapshot.collect = collect

    def tearDown(self):
        for name, value in self._patched.items():
            setattr(self.server, name, value)
        self.checks.snapshot.collect = self._collect
        self.server.CHECKS_STATE["last"] = None
        super().tearDown()

    def test_offered_is_the_hand_off_and_proposed_is_the_proposals(self):
        summary = asyncio.run(self.server.run_checks("test"))
        self.assertIsNone(summary.get("error"), summary)
        self.assertEqual(summary["offered"], 5)
        self.assertEqual(summary["proposed"], 3)


if __name__ == "__main__":
    unittest.main()
