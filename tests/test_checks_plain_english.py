#!/usr/bin/env python3
"""A check's fixed sentences read naturally in either English.

A US house's cards read "a draught under a door or through a letterbox…
a loft hatch" (`climate.heat_loss`), "a guest, a heatwave, a new
appliance" (`base.unusual`) and "Take it off, then tick it off"
(`chore.job_done`) beside prose that was otherwise plain. Each is a
British idiom, and the heat-loss one is also a stock list of fixtures
that pretends to know the house: the room was measured, its letterbox
was not. The fix is neutral plain English, not locale machinery.

The sweep is `test_finding_text_plain`'s: every catalogued check is
wrapped, the check test modules that plant each defect are run (plus
the thermal and chore ones, which plant the rows these sentences are
on), and every row's ``text``, ``detail`` and ``fix`` is read for the
idioms. The checks the report named are asserted to have produced rows,
because a sweep that never reached them proves nothing about them.
"""

import io
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
PANEL_DIR = TESTS_DIR.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(TESTS_DIR))

from test_finding_text_plain import SWEEP_MODULES, _Capture  # noqa: E402

from checks import thermal  # noqa: E402
from checks._util import House  # noqa: E402

MODULES = SWEEP_MODULES + (
    "test_thermal.TestUnderheated", "test_thermal.TestHeatLoss",
    "test_thermal.TestWindow", "test_thermal.TestFreeze",
    "test_thermal.TestPreheat",
    "test_appliances", "test_plain_device_words",
    "test_access_steward",
)

# Whole words, case-folded. Each is British usage, or a phrase only one
# side of the Atlantic says, that a plain sentence can do without.
IDIOMS = re.compile(
    r"\b(draughts?|draughty|letterbox(es)?|loft|tick (it|them) off|"
    r"heatwave|bled system|flat battery|mains (power|node)|recognise|colour|"
    r"cooker|hob|fortnight|holiday)\b", re.I)


# Two phrases an existing test pins word for word:
# `test_appliances.TestTheChore.test_the_fix_says_brAIn_cannot_see_you_
# emptied_it` asserts "tick it off" in `chore.waiting`'s fix, and
# `test_battery_beside_mains...test_a_real_flat_battery_still_files`
# asserts "mains" in `dev.battery_low`'s. Rewording either changes what
# that test asserts, which is a person's decision, so each is held here BY
# NAME rather than loosened in the pattern: the day the test moves, the
# entry goes and the sweep covers it.
HELD_BY_A_TEST = {("chore.waiting", "fix", "tick it off"),
                  ("dev.battery_low", "fix", "mains power")}


class TestNoBritishIdiomInWhatAPersonReads(unittest.TestCase):
    def test_every_row_reads_in_plain_english(self):
        with _Capture() as cap:
            suite = unittest.defaultTestLoader.loadTestsFromNames(MODULES)
            result = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(),
                        [str(t) for t, _ in result.failures + result.errors])
        seen = {cid for cid, _r, _s in cap.rows}
        for wanted in ("climate.heat_loss", "climate.underheated",
                       "base.unusual", "chore.job_done", "chore.waiting"):
            self.assertIn(wanted, seen,
                          "the sweep never produced a row for " + wanted)
        bad = []
        for cid, row, _snap in cap.rows:
            for field in ("text", "detail", "fix"):
                prose = str(row.get(field) or "")
                for m in IDIOMS.finditer(prose):
                    if (cid, field, m.group(0).lower()) in HELD_BY_A_TEST:
                        continue
                    bad.append(f"{cid} {field}: {m.group(0)!r} in {prose!r}")
        self.assertEqual(bad, [])


class TestTheHeatLossFixIsAboutTheRoomItMeasured(unittest.TestCase):
    """The advice names the room, and names a door or window only when
    the house has one there to name."""

    def snap(self, extra_states=None, extra_entities=None):
        rooms = {}
        states, entities = {}, []
        for i, (room, tau) in enumerate((("Office", 3.0), ("Kitchen", 9.0),
                                         ("Hall", 9.5), ("Den", 10.0),
                                         ("Bedroom", 9.0))):
            eid = f"sensor.t{i}"
            rooms[eid] = {"k": 1.0 / tau, "tau_h": tau, "area": room}
            states[eid] = {"state": "20", "attributes": {
                "friendly_name": f"{room} temperature",
                "device_class": "temperature",
                "unit_of_measurement": "°C"}}
            entities.append({"entity_id": eid, "area_id": room.lower()})
            # Every room is heated: `climate.heat_loss` compares only the
            # rooms a thermostat or heater serves.
            cid = f"climate.{room.lower()}"
            states[cid] = {"state": "heat", "attributes": {
                "friendly_name": f"{room} thermostat"}}
            entities.append({"entity_id": cid, "area_id": room.lower()})
        states.update(extra_states or {})
        entities += extra_entities or []
        return {"states": states, "entities": entities, "devices": [],
                "areas": [{"area_id": r.lower(), "name": r}
                          for r in ("Office", "Kitchen", "Hall", "Den",
                                    "Bedroom")],
                "thermal": {"built_at": 1, "rooms": rooms,
                            "outdoor": "sensor.outside"}}

    def rows(self, snap):
        out = thermal.heat_loss(snap, 2_000_000_000.0)
        self.assertEqual([r["entity_id"] for r in out], ["sensor.t0"])
        return out[0]

    def test_it_names_the_room(self):
        row = self.rows(self.snap())
        self.assertIn("Office", row["fix"])
        self.assertNotRegex(row["fix"], IDIOMS)

    def test_a_window_the_house_has_is_named(self):
        snap = self.snap(
            {"binary_sensor.office_window": {"state": "off", "attributes": {
                "friendly_name": "Office window",
                "device_class": "window"}}},
            [{"entity_id": "binary_sensor.office_window",
              "area_id": "office"}])
        row = self.rows(snap)
        self.assertIn("Office window", row["fix"])

    def test_no_fixture_is_listed_that_the_data_does_not_show(self):
        row = self.rows(self.snap())
        for invented in ("letterbox", "flue", "loft", "glass"):
            self.assertNotIn(invented, row["fix"].lower())
        # And a window in another room is not this room's.
        snap = self.snap(
            {"binary_sensor.den_window": {"state": "off", "attributes": {
                "friendly_name": "Den window", "device_class": "window"}}},
            [{"entity_id": "binary_sensor.den_window", "area_id": "den"}])
        self.assertNotIn("Den window", self.rows(snap)["fix"])
        self.assertTrue(House(snap).area_of("binary_sensor.den_window"))


if __name__ == "__main__":
    unittest.main()
