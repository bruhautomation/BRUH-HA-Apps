#!/usr/bin/env python3
"""Before the Resident says how long a door has been open, it reads the
history that would say so (#580).

A case said a garage door had been open 70 minutes; it had opened and
closed eight minutes apart. A stated duration is now read against the
door's last open and close: a door that has closed since is not filed as
open, and one still open is filed with the duration its history says.
Only the door the claim is about is read — a motion sensor beside it in
the evidence, or a second door that never opened, refuses nothing — and
a door open since before the window stands as the case said it.

Made-up entities: a garage door, a side gate, a patio door with a hall
motion sensor beside it.
"""

import asyncio
import datetime as dt
import json
import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import resident  # noqa: E402
from test_resident_loop import LoopCase  # noqa: E402

NOW = 1_800_000_000.0
H = 3600.0
GARAGE = "cover.garage_door"
GATE = "binary_sensor.side_gate"
MOTION = "binary_sensor.hall_motion"
PATIO = "binary_sensor.patio_door"
FRONT = "binary_sensor.front_door"
CLASSES = {MOTION: "motion", PATIO: "door", FRONT: "door", GATE: "gate"}


def iso(ago_h):
    return dt.datetime.fromtimestamp(NOW - ago_h * H, dt.timezone.utc).isoformat()


def series(*steps):
    return [[iso(ago), word] for ago, word in steps]


def case(claim, *evidence, entity=""):
    return {"claim": claim, "text": claim, "entity_id": entity, "detail": "",
            "evidence": [{"entity": e, "value": v} for e, v in evidence]}


class TestAStatedOpenDurationIsReadAgainstTheHistory(unittest.TestCase):
    GARAGE_CASE = case("The garage door has been open for 70 minutes",
                       (GARAGE, "open"), entity=GARAGE)

    def test_a_door_that_opened_and_closed_is_not_filed_as_open(self):
        history = {GARAGE: series((3, "closed"), (70 / 60, "open"),
                                  (62 / 60, "closed"))}
        verdict, _c, why = resident.open_duration(self.GARAGE_CASE, history, NOW)
        self.assertEqual(verdict, "refuse")
        self.assertIn("8 minutes later", why)

    def test_a_door_still_open_gets_the_history_s_duration(self):
        history = {GARAGE: series((3, "closed"), (25 / 60, "open"))}
        verdict, fixed, why = resident.open_duration(self.GARAGE_CASE,
                                                     history, NOW)
        self.assertEqual(verdict, "correct")
        self.assertIn("open for 25 minutes", fixed["claim"])
        self.assertNotIn("70", fixed["claim"])
        self.assertIn("25 minutes", why)

    def test_a_duration_the_history_agrees_with_is_left_alone(self):
        history = {GARAGE: series((3, "closed"), (72 / 60, "open"))}
        verdict, c, _why = resident.open_duration(self.GARAGE_CASE, history, NOW)
        self.assertEqual(verdict, "ok")
        self.assertIs(c, self.GARAGE_CASE)

    def test_a_gate_sensor_in_hours(self):
        gate = case("The side gate was left open 2 hours", (GATE, "on"))
        history = {GATE: series((5, "off"), (0.25, "on"), (0.1, "off"))}
        verdict, _c, why = resident.open_duration(gate, history, NOW)
        self.assertEqual(verdict, "refuse")
        self.assertIn(GATE, why)

    def test_unread_history_and_other_claims_pass(self):
        self.assertEqual(resident.open_duration(self.GARAGE_CASE, None, NOW)[0],
                         "ok")
        other = case("The garage light was on for 70 minutes", entity="light.garage")
        self.assertIsNone(resident.stated_open(other))


class TestOnlyTheDoorTheClaimIsAboutIsRead(unittest.TestCase):
    PATIO_CASE = case("The heating is running while the patio door has been "
                      + "open for 40 minutes", (MOTION, "off"), (PATIO, "on"),
                      entity="climate.lounge")

    def test_a_motion_sensor_is_not_a_door(self):
        minutes, ents = resident.stated_open(self.PATIO_CASE, CLASSES.get)
        self.assertEqual((minutes, ents), (40.0, [PATIO]))
        # A sensor nobody classed is kept: the history says what it is.
        self.assertIn(GATE, resident.stated_open(
            case("The side gate was left open 2 hours", (GATE, "on")),
            lambda _e: "")[1])

    def test_a_motion_sensor_ahead_of_the_door_refuses_nothing(self):
        history = {MOTION: series((2, "off"), (0.5, "on"), (0.4, "off")),
                   PATIO: series((3, "off"), (40 / 60, "on"))}
        verdict, _c, why = resident.open_duration(self.PATIO_CASE, history,
                                                  NOW, CLASSES.get)
        self.assertEqual((verdict, why), ("ok", ""))
        # Even with no class to read, the door that agrees is the door.
        self.assertEqual(resident.open_duration(self.PATIO_CASE, history,
                                                NOW)[0], "ok")

    def test_a_second_door_that_never_opened_is_not_the_door(self):
        c = case("The patio door has been open for 40 minutes",
                 (FRONT, "off"), (PATIO, "on"), entity=PATIO)
        history = {FRONT: series((3, "off")),
                   PATIO: series((3, "off"), (40 / 60, "on"))}
        self.assertEqual(resident.open_duration(c, history, NOW,
                                                CLASSES.get)[0], "ok")
        # …and one still open for its own time corrects the case.
        history[PATIO] = series((3, "off"), (20 / 60, "on"))
        verdict, fixed, _why = resident.open_duration(c, history, NOW,
                                                      CLASSES.get)
        self.assertEqual(verdict, "correct")
        self.assertIn("20 minutes", fixed["claim"])

    def test_every_door_closed_still_refuses(self):
        c = case("The patio door has been open for 40 minutes",
                 (FRONT, "off"), (PATIO, "off"), entity=PATIO)
        history = {FRONT: series((3, "off")),
                   PATIO: series((3, "off"), (1, "on"), (0.5, "off"))}
        verdict, _c, why = resident.open_duration(c, history, NOW, CLASSES.get)
        self.assertEqual(verdict, "refuse")
        self.assertIn(PATIO, why)

    def test_a_door_open_since_before_the_window_is_not_corrected(self):
        # Open at the window's first row: when it opened is before what
        # was read, so "open for 2 hours" is left as the case said it.
        c = case("The patio door has been open for 2 hours", (PATIO, "on"),
                 entity=PATIO)
        history = {PATIO: series((5, "on"))}
        self.assertEqual(resident.open_duration(c, history, NOW,
                                                CLASSES.get)[0], "ok")
        shut = {PATIO: series((5, "on"), (0.5, "off"))}
        verdict, _c, why = resident.open_duration(c, shut, NOW, CLASSES.get)
        self.assertEqual(verdict, "refuse")
        self.assertIn("before", why)
        self.assertIn("not open now", why)


class TestTheInvestigationReadsTheHistory(LoopCase):
    """The real `_resident_investigate`, with the history it reads stubbed
    and the registry's device classes in `_NAMES`."""

    def setUp(self):
        super().setUp()
        srv = self.server
        self._trail = srv.decision_trail.TRAIL_FILE
        srv.decision_trail.TRAIL_FILE = str(Path(self.tmp.name)
                                            / "decisions.jsonl")
        # `refused` is a counter `LoopCase` does not reset, and a test down
        # the same worker asserts its own count from zero.
        self.addCleanup(srv.RESIDENT_STATE.__setitem__, "refused",
                        srv.RESIDENT_STATE.get("refused", 0))
        self._names = dict(srv._NAMES)
        srv._NAMES.clear()
        srv._NAMES.update({MOTION: {"name": "Hall motion", "class": "motion"},
                           PATIO: {"name": "Patio door", "class": "door"}})
        self.history: dict = {}
        self.addCleanup(setattr, srv, "_recent_history", srv._recent_history)

        async def fake(ids, hours, now=None):
            return {e: self.history[e] for e in ids if e in self.history}
        srv._recent_history = fake

    def tearDown(self):
        srv = self.server
        srv.decision_trail.TRAIL_FILE = self._trail
        srv._NAMES.clear()
        srv._NAMES.update(self._names)
        super().tearDown()

    def investigate(self, claim, evidence, subject):
        now = time.time()
        self.investigations.append({
            "ok": True, "error": "", "meta": {"session_id": "inv-h"},
            "text": json.dumps({
                "claim": claim, "detail": "Seen in its history today.",
                "kind": "problem", "confidence": 0.8, "stakes": "medium",
                "fix": "Look at it when you are next home.",
                "evidence": evidence, "actions": [], "escalate": False})})
        signal = {"kind": "state", "subject": subject, "salience": 0.6,
                  "text": claim, "evidence": []}
        asyncio.run(self.server._resident_investigate(signal, now, "normal"))
        return [r for r in self.server.findings_store._load()
                if r.get("source") == "resident"]

    def rel(self, *steps):
        now = time.time()
        return [[dt.datetime.fromtimestamp(now - ago * H, dt.timezone.utc)
                 .isoformat(), word] for ago, word in steps]

    def test_a_door_that_closed_is_not_filed_as_open_for_an_hour(self):
        self.history = {GARAGE: self.rel((3, "closed"), (70 / 60, "open"),
                                         (62 / 60, "closed"))}
        rows = self.investigate("The garage door has been open for 70 minutes",
                                [{"entity": GARAGE, "value": "open",
                                  "when": "14:02"}], GARAGE)
        self.assertEqual(rows, [])
        trail = Path(self.server.decision_trail.TRAIL_FILE).read_text()
        self.assertIn(GARAGE, trail)

    def test_a_door_still_open_is_filed_with_the_right_duration(self):
        self.history = {GARAGE: self.rel((3, "closed"), (25 / 60, "open"))}
        rows = self.investigate("The garage door has been open for 70 minutes",
                                [{"entity": GARAGE, "value": "open",
                                  "when": "14:02"}], GARAGE)
        self.assertEqual(len(rows), 1)
        said = rows[0].get("claim") or rows[0].get("text")
        self.assertIn("25 minutes", said)
        self.assertNotIn("70 minutes", said)

    def test_a_motion_sensor_in_the_evidence_does_not_refuse_the_door(self):
        self.history = {MOTION: self.rel((2, "off"), (0.5, "on"), (0.4, "off")),
                        PATIO: self.rel((3, "off"), (40 / 60, "on"))}
        rows = self.investigate(
            "The heating is running while the patio door has been open for "
            + "40 minutes",
            [{"entity": MOTION, "value": "off", "when": "14:02"},
             {"entity": PATIO, "value": "on", "when": "13:30"}],
            "climate.lounge")
        self.assertEqual(len(rows), 1)
        self.assertIn("40 minutes", rows[0].get("claim") or "")
