#!/usr/bin/env python3
"""Speak first: which room, which speaker, and what may be said aloud.

`household.py` is pure over one states read and the area map the checks
pass already recorded; `server._speak_first` is where it meets
`_announce_findings`. Every refusal is shown refusing — off by default, an
empty house, an unoccupied room, quiet hours, an escalating row, a row that
names a person, a protected speaker, a Core with no announce service — and
the one path that speaks is driven through the real announcer with only
Home Assistant faked, recording the service call it was asked to make.
"""

import asyncio
import datetime as dt
import os
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import household  # noqa: E402
from test_dispatch import DispatchCase  # noqa: E402

NOW = 1_760_000_000.0
AREAS = {"assist_satellite.kitchen": "Kitchen",
         "assist_satellite.bedroom": "Bedroom",
         "binary_sensor.kitchen_motion": "Kitchen",
         "binary_sensor.bedroom_occupancy": "Bedroom"}


def iso(ts):
    return dt.datetime.fromtimestamp(ts, dt.timezone.utc).isoformat()


def states(*, home=True, kitchen_motion=("off", NOW - 60),
           bedroom=("off", NOW - 3600), sat_state="idle"):
    return [
        {"entity_id": "person.sam", "state": "home" if home else "not_home",
         "attributes": {"friendly_name": "Sam"}},
        {"entity_id": "assist_satellite.kitchen", "state": sat_state,
         "attributes": {"friendly_name": "Kitchen voice"}},
        {"entity_id": "assist_satellite.bedroom", "state": "idle",
         "attributes": {"friendly_name": "Bedroom voice"}},
        {"entity_id": "binary_sensor.kitchen_motion", "state": kitchen_motion[0],
         "last_changed": iso(kitchen_motion[1]),
         "attributes": {"device_class": "motion"}},
        {"entity_id": "binary_sensor.bedroom_occupancy", "state": bedroom[0],
         "last_changed": iso(bedroom[1]),
         "attributes": {"device_class": "occupancy"}},
    ]


WINDOW = {"ts": 5, "text": "Bedroom window looks open on a cold night",
          "severity": "serious", "source": "check:climate.window",
          "entity_id": "sensor.bedroom_temperature"}


class TestWhereSomebodyIs(unittest.TestCase):

    def test_the_freshest_room_with_a_speaker(self):
        r = household.roster(states(), AREAS)
        occ = household.occupied_areas(states(), AREAS, NOW)
        self.assertEqual(occ, ["Kitchen"])
        self.assertEqual(household.pick_satellite(r, occ)["entity_id"],
                         "assist_satellite.kitchen")

    def test_a_sensor_that_is_on_counts_however_long_ago_it_changed(self):
        s = states(kitchen_motion=("off", NOW - 3600),
                   bedroom=("on", NOW - 5 * 3600))
        self.assertEqual(household.occupied_areas(s, AREAS, NOW), ["Bedroom"])

    def test_an_empty_house_is_told_nothing(self):
        s = states(home=False)
        r = household.roster(s, AREAS)
        self.assertIsNone(household.pick_satellite(
            r, household.occupied_areas(s, AREAS, NOW)))

    def test_a_room_left_long_ago_is_not_occupied(self):
        s = states(kitchen_motion=("off", NOW - 3600))
        self.assertEqual(household.occupied_areas(s, AREAS, NOW), [])

    def test_an_unavailable_satellite_is_not_a_speaker(self):
        s = states(sat_state="unavailable")
        r = household.roster(s, AREAS)
        self.assertIsNone(household.pick_satellite(
            r, household.occupied_areas(s, AREAS, NOW)))


class TestWhatMayBeSaid(unittest.TestCase):

    def test_only_an_urgent_serious_check_in_the_notify_tier(self):
        self.assertTrue(household.speakable(WINDOW, "notify", "now"))
        self.assertFalse(household.speakable(WINDOW, "escalate", "now"))
        self.assertFalse(household.speakable(WINDOW, "notify", "today"))
        self.assertFalse(household.speakable({**WINDOW, "severity": "warning"},
                                             "notify", "now"))
        # A Resident claim is a model's sentence, not a check's.
        self.assertFalse(household.speakable({**WINDOW, "source": "resident"},
                                             "notify", "now"))

    def test_the_words_are_the_checks_and_never_a_persons(self):
        r = household.roster(states(), AREAS)
        said = household.spoken_text(WINDOW, r)
        self.assertIn("Bedroom window looks open", said)
        self.assertIn("on your phone", said)
        self.assertIsNone(household.spoken_text(
            {**WINDOW, "text": "Sam left the back door open"}, r))


class TestTheServerSpeaksFirst(DispatchCase):

    def setUp(self):
        super().setUp()
        import engine
        import ha_data
        import settings_store
        engine.get_auth = lambda: None          # phone: the deterministic path
        settings_store.save({"speak_first": True})
        srv = self.server
        srv._NAMES.update({k: {"name": k, "area": v} for k, v in AREAS.items()})
        srv.SPEAK_STATE.update(last_at=0.0, spoken=0, last_reason="",
                               last_error="")
        srv.SPEAK_STATE["said"].clear()
        self.calls: list[tuple] = []
        self.house_states = states(kitchen_motion=("on", time.time()))
        self.services = [{"domain": "assist_satellite",
                          "services": {"announce": {}, "start_conversation": {}}}]
        self._ha_saved = (ha_data.call_core_service, ha_data._rest_get)

        async def call(domain, service, data=None, timeout=30):
            self.calls.append((domain, service, data))
            return []

        async def rest_get(session, path, *a, **k):
            return self.house_states if path == "/states" else self.services

        ha_data.call_core_service = call
        ha_data._rest_get = rest_get
        self.ha_data = ha_data

    def tearDown(self):
        self.ha_data.call_core_service, self.ha_data._rest_get = self._ha_saved
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        super().tearDown()

    def announce_window(self, **over):
        [row] = self.file({"text": "Bedroom window looks open on a cold night",
                           "severity": "serious",
                           "source": "check:climate.window", **over})
        self.announce([row])
        return row

    def test_it_says_it_in_the_room_and_still_sends_the_phone(self):
        self.announce_window()
        [(domain, service, data)] = self.calls
        self.assertEqual((domain, service), ("assist_satellite", "announce"))
        self.assertEqual(data["entity_id"], "assist_satellite.kitchen")
        self.assertIn("Bedroom window looks open", data["message"])
        self.assertEqual(len(self.sent), 1, "the phone still carries the buttons")

    def test_off_by_default(self):
        import settings_store
        settings_store.save({"speak_first": False})
        self.announce_window()
        self.assertEqual(self.calls, [])

    def test_never_in_the_quiet_hours(self):
        utc = dt.datetime.now(dt.timezone.utc).hour
        self.server._quiet_hours = lambda: (utc, (utc + 2) % 24)
        self.announce_window()
        self.assertEqual(self.calls, [])
        self.assertIn("quiet", self.server.SPEAK_STATE["last_reason"])

    def test_nobody_in_a_room_with_a_speaker(self):
        self.house_states = states(kitchen_motion=("off", time.time() - 7200))
        self.announce_window()
        self.assertEqual(self.calls, [])

    def test_a_core_without_announce(self):
        self.services = [{"domain": "light", "services": {"turn_on": {}}}]
        self.announce_window()
        self.assertEqual(self.calls, [])

    def test_a_protected_speaker_is_not_used(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "assist_satellite.*"
        self.announce_window()
        self.assertEqual(self.calls, [])

    def test_once_per_finding_and_spaced(self):
        self.announce_window()
        self.announce_window(text="Hall window looks open on a cold night")
        self.assertEqual(len(self.calls), 1, "a second one inside the spacing")

    def test_an_escalating_row_is_the_phones(self):
        [leak] = self.file({"text": "Kitchen leak sensor tripped",
                            "severity": "critical", "source": "safety"})
        self.announce([leak])
        self.assertEqual(self.calls, [])

    def test_a_failure_to_speak_is_a_line_and_the_phone_goes_anyway(self):
        async def boom(*a, **k):
            raise RuntimeError("Core said no")
        self.ha_data.call_core_service = boom
        self.announce_window()
        self.assertEqual(len(self.sent), 1)
        self.assertIn("Core said no", self.server.SPEAK_STATE["last_error"])

    def test_it_is_in_the_diagnostics(self):
        self.announce_window()
        diag = self.server._notify_diagnostics()
        self.assertEqual(diag["speak_first"]["spoken"], 1)
        self.assertTrue(diag["speak_first"]["enabled"])


if __name__ == "__main__":
    asyncio.set_event_loop_policy(None)
    unittest.main()
