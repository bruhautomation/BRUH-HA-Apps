#!/usr/bin/env python3
"""A claim that a device is unplugged is read against the house again (#789).

"Hall plug is unplugged, and 2 scenes still set it" was marked Wrong ("I
don't think this is true anymore"): the plug was no longer in Home
Assistant at all, and only the scenes still named it. Nothing read the
entity's state AND its registry entry before the card was filed or shown:

* filed (the overnight check): a line saying calls went to an entity the
  house no longer has says so, and names what still calls it as the only
  thing left to change — never "bring it back online";
* shown: a stored row saying a device is offline or unplugged, whose
  entities are now in neither the states nor the registry, says the entity
  is gone and the scenes are what is left; one that is still there and
  still down is shown as it was;
* kept: a Wrong on such a card holds while the entity stays gone, as it
  holds while a plug stays unplugged.

The second examples are ones the report never named: an automation and a
script (not scenes) still aimed at a removed heater, and an insight card's
"Kitchen speaker is offline" about a speaker that was removed.
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import sre  # noqa: E402
from test_sre import NOW  # noqa: E402
from test_sre_sources import MISSING, cause_row, log_row, missing_house  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402

HALL = ("Referenced entities switch.hall_plug are missing or not currently "
        "available")


def scenes_house():
    """Two scenes still set a hall plug the house no longer has."""
    h = missing_house([log_row(HALL, "homeassistant.helpers.service")])
    h["scenes"] = [
        {"id": "s1", "name": "Evening", "entities": {
            "switch.hall_plug": {"state": "on"}}},
        {"id": "s2", "name": "Movie night", "entities": {
            "switch.hall_plug": {"state": "off"}}},
    ]
    h["states"]["scene.evening"] = {"state": "2026-11-01T10:00:00+00:00",
                                    "attributes": {"id": "s1",
                                                   "friendly_name": "Evening"}}
    h["states"]["scene.movie_night"] = {
        "state": "2026-11-01T10:00:00+00:00",
        "attributes": {"id": "s2", "friendly_name": "Movie night"}}
    return h


def heater_gone_house():
    """The porch heater is out of the registry and the states; an
    automation and a script still switch it on."""
    h = missing_house([log_row(MISSING, "homeassistant.helpers.service")])
    h["entities"] = [e for e in h["entities"]
                     if e.get("entity_id") != "switch.porch_heater"]
    h["states"].pop("switch.porch_heater")
    return h


GONE_CAUSE = {"title": "Hall plug is unplugged and 2 scenes still set it",
              "detail": "Scenes keep trying to switch it.",
              "fix": "Plug the hall plug back in."}


class TestFiledAgainstTheHouseAsItIs(unittest.TestCase):
    def assert_gone_wording(self, row, callers):
        said = " ".join((row["text"], row["detail"], row["fix"])).lower()
        self.assertIn("no longer exists", row["text"].lower())
        for word in ("unplugged", "offline", "back online", "plug the"):
            self.assertNotIn(word, said, said)
        for name in callers:
            self.assertIn(name, row["detail"] + row["fix"])

    def test_scenes_aimed_at_a_plug_that_is_gone(self):
        dig = sre.digest(scenes_house(), NOW)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertEqual(rec.get("gone"), ["switch.hall_plug"])
        self.assertEqual([c["name"] for c in rec["called_by"]],
                         ["Evening", "Movie night"])
        row = cause_row(dig, **GONE_CAUSE)
        self.assert_gone_wording(row, ["Evening", "Movie night"])
        self.assertIn("switch.hall_plug", row.get("about") or [])

    def test_an_automation_and_a_script_aimed_at_a_removed_heater(self):
        dig = sre.digest(heater_gone_house(), NOW)
        row = cause_row(dig, title="Porch heater is offline",
                        detail="It keeps failing.",
                        fix="Bring it back online.")
        self.assert_gone_wording(row, ["Morning heat", "Warm porch"])

    def test_a_plug_still_there_and_down_keeps_its_wording(self):
        dig = sre.digest(missing_house(
            [log_row(MISSING, "homeassistant.helpers.service")]), NOW)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertNotIn("gone", rec)
        row = cause_row(dig, title="Porch heater is offline", detail="x",
                        fix="Bring it back.")
        self.assertIn("offline", row["text"])


class TestAWrongHoldsWhileItStaysGone(unittest.TestCase):
    def test_answered_about_a_plug_that_is_now_gone(self):
        states = {"switch.shed_lamp": {"state": "on"}}
        ignored = [{"source": sre.SOURCE, "entity_id": "switch.hall_plug"}]
        self.assertEqual(sre.answered_down([], ignored, states, NOW),
                         {"switch.hall_plug"})
        # nothing read is still nothing guessed
        self.assertEqual(sre.answered_down([], ignored, {}, NOW), set())


def unplugged_row(eid="switch.hall_plug", source="sre"):
    return {"text": "Hall plug is unplugged and 2 scenes still set it",
            "claim": "Hall plug is unplugged and 2 scenes still set it",
            "detail": "Two scenes still turn it on.",
            "fix": "Plug the hall plug back in.",
            "source": source, "kind": "problem", "severity": "warning",
            "entity_id": eid, "about": [eid]}


class ShownCase(FoldCase):
    def setUp(self):
        super().setUp()
        self._live = dict(findings_store.LIVE_STATES)
        self._reg = set(findings_store.LIVE_REGISTRY)
        findings_store.LIVE_STATES.clear()
        findings_store.LIVE_REGISTRY.clear()

    def tearDown(self):
        findings_store.LIVE_STATES.clear()
        findings_store.LIVE_STATES.update(self._live)
        findings_store.LIVE_REGISTRY.clear()
        findings_store.LIVE_REGISTRY.update(self._reg)
        super().tearDown()

    def shown(self, text):
        return next(f for f in findings_store.listing()["findings"]
                    if f["text"] == text)

    def house_without(self, *gone):
        states = {"light.porch": {"state": "on", "last_changed": 1},
                  "switch.shed_lamp": {"state": "off", "last_changed": 1}}
        findings_store.seed_states(states)
        findings_store.seed_registry(
            [{"entity_id": e} for e in states if e not in gone])


class TestShownAgainstTheHouseAsItIs(ShownCase):
    def test_a_plug_that_is_gone_says_so_and_the_scenes_are_left(self):
        [row] = findings_store.add_many([unplugged_row()])
        self.house_without("switch.hall_plug")
        shown = self.shown(row["text"])
        self.assertIn("no longer exists", shown["claim"])
        self.assertNotIn("unplugged", shown["claim"])
        self.assertIn("scenes", shown["fix"])
        self.assertNotIn("Plug the hall plug back in", shown["fix"])

    def test_a_removed_speaker_on_an_insight_card(self):
        [row] = findings_store.add_many([{
            "text": "Kitchen speaker is offline",
            "claim": "Kitchen speaker is offline",
            "detail": "It has not answered since Tuesday.",
            "fix": "Power-cycle the speaker.",
            "source": "card-music", "kind": "problem", "severity": "warning",
            "entity_id": "media_player.kitchen",
            "about": ["media_player.kitchen"]}])
        self.house_without("media_player.kitchen")
        shown = self.shown(row["text"])
        self.assertIn("no longer exists", shown["claim"])

    def test_one_still_in_the_registry_and_down_is_shown_as_it_was(self):
        [row] = findings_store.add_many([unplugged_row()])
        self.house_without()
        findings_store.seed_registry([{"entity_id": "switch.hall_plug"}])
        findings_store.note_state("switch.hall_plug", {
            "state": "unavailable", "last_changed": row["ts"] + 10})
        shown = self.shown(row["text"])
        self.assertEqual(shown["claim"], row["claim"])

    def test_no_registry_read_proves_nothing(self):
        [row] = findings_store.add_many([unplugged_row()])
        findings_store.seed_states({"light.porch": {"state": "on"}})
        shown = self.shown(row["text"])
        self.assertEqual(shown["claim"], row["claim"])

    def test_a_house_check_row_is_left_to_its_check(self):
        [row] = findings_store.add_many([unplugged_row(
            source="check:dev.unavailable")])
        self.house_without("switch.hall_plug")
        self.assertEqual(self.shown(row["text"])["claim"], row["claim"])


if __name__ == "__main__":
    unittest.main()
