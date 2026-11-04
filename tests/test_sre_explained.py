#!/usr/bin/env python3
"""An explained error stays explained (#578, #612).

The overnight check filed an automation as failing at one step, the owner
answered Wrong with why (the automation is built that way on purpose), and
the next night's card came back under new words. The answer is now kept on
the automation and the error's own identity, so the same error on that
automation is not handed to the run again, while a different error on the
same automation still is.

And a media player that leaves the network whenever it is switched off is
not an integration failing: before a log cause about it is filed, its own
history is read, and unavailable straight after an off that has cleared on
the next power-on before is held. A player that dropped while playing, or
that has never come back, is still filed.

Made-up entities throughout: a hallway night-light automation, a garden
pump script, a lounge TV and a kitchen speaker.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import sre  # noqa: E402
from test_sre import NOW, collected  # noqa: E402

H = 3600.0
AUTO = "homeassistant.components.automation.hall_night_light"


def iso(ago):
    return dt.datetime.fromtimestamp(NOW - ago, dt.timezone.utc).isoformat()


def log_row(message, logger, *, count=12, last_ago=600, first_ago=20 * H):
    return {"name": logger, "message": [message], "level": "ERROR",
            "source": ["helpers/script.py", 500], "timestamp": NOW - last_ago,
            "first_occurred": NOW - first_ago, "count": count}


STEP_ERR = ("Hall night light: Error executing script. Error for call_service "
            "at pos 2: Failed to send request: device did not respond "
            "(context 01HZX4K9Q2ABCDEF)")
STEP_ERR_TOMORROW = ("Hall night light: Error executing script. Error for "
                     "call_service at pos 2: Failed to send request: device "
                     "did not respond (context 01J0000ZZZ99FFEE)")
OTHER_ERR = ("Hall night light: Error executing script. Error for call_service "
             "at pos 4: Unable to find service light.turn_of")


def house(*messages):
    return collected(log=[log_row(m, AUTO) for m in messages],
                     zha=[], automations=[])


def records(dig, kind="log"):
    return [r for r in dig["records"] if r["kind"] == kind
            and r.get("logger") == AUTO]


def file_card(dig, state):
    recs = [r["id"] for r in records(dig)]
    parsed = sre.parse_causes({"causes": [{
        "title": "Hall night light keeps failing to reach the hall lamp",
        "records": recs, "detail": "It errors at its second step.",
        "fix": "", "severity": "warning"}]}, dig)
    return sre.rows(parsed["causes"], dig, state, NOW)


def wrong(row, note):
    return {"key": findings_store.normalize(row["text"]), "text": row["text"],
            "kind": "ignored", "source": sre.SOURCE, "note": note,
            "entity_id": row.get("entity_id") or ""}


REASON = ("It is meant to switch the bulb off and leave the lamp powered, so "
          "the bulb keeps routing for the mesh")


class TestAnExplainedAutomationErrorStaysExplained(unittest.TestCase):
    def setUp(self):
        self.state = {"anchors": {}}
        dig = sre.digest(house(STEP_ERR), NOW)
        self.assertTrue(records(dig), "the automation's error is a record")
        self.rows = file_card(dig, self.state)
        self.assertEqual(len(self.rows), 1)

    def test_the_same_error_tomorrow_is_not_handed_to_the_run(self):
        keys = sre.explained(self.state, [wrong(self.rows[0], REASON)], NOW)
        self.assertTrue(keys)
        dig = sre.digest(house(STEP_ERR_TOMORROW), NOW + 86400,
                         explained_keys=keys)
        self.assertEqual(records(dig), [])
        self.assertEqual(dig["explained"], 1)

    def test_a_different_error_on_the_same_automation_still_raises(self):
        keys = sre.explained(self.state, [wrong(self.rows[0], REASON)], NOW)
        dig = sre.digest(house(STEP_ERR_TOMORROW, OTHER_ERR), NOW + 86400,
                         explained_keys=keys)
        kept = records(dig)
        self.assertEqual(len(kept), 1)
        self.assertIn("pos 4", kept[0]["message"])

    def test_the_explanation_outlives_the_cards_anchor(self):
        keys = sre.explained(self.state, [wrong(self.rows[0], REASON)], NOW)
        # The anchors age out of the state; the explanation does not.
        later = {"anchors": {}, "explained": self.state["explained"]}
        self.assertEqual(sre.explained(later, [], NOW + 30 * 86400), keys)

    def test_wrong_without_a_reason_explains_nothing(self):
        self.assertEqual(sre.explained(self.state,
                                       [wrong(self.rows[0], "")], NOW), set())

    def test_another_producers_answer_explains_nothing(self):
        entry = {**wrong(self.rows[0], REASON), "source": "check:dev.unavailable"}
        self.assertEqual(sre.explained(self.state, [entry], NOW), set())

    def test_a_script_error_is_keyed_the_same_way(self):
        logger = "homeassistant.components.script.garden_pump_cycle"
        rec = {"kind": "log", "logger": logger,
               "message": "Garden pump cycle: Error at pos 1: valve did not open"}
        again = {**rec, "message": "Garden pump cycle: Error at pos 1: valve "
                                   "did not open"}
        other = {**rec, "message": "Garden pump cycle: Error at pos 3: timeout"}
        self.assertEqual(sre.explain_key(rec), sre.explain_key(again))
        self.assertNotEqual(sre.explain_key(rec), sre.explain_key(other))
        self.assertEqual(sre.explain_key({"kind": "log", "logger":
                                          "homeassistant.components.hue",
                                          "message": "x"}), "")


class TestASwitchedOffRouterExplanationIsTheAutomationsOwn(unittest.TestCase):
    """The mesh cross-reference — an automation switching off a router —
    is an explanation keyed on that automation and what it switches off."""

    def test_the_router_record_is_held_and_a_new_target_is_not(self):
        base = collected()
        dig = sre.digest(base, NOW)
        autos = [r for r in dig["records"] if r["kind"] == "automation"]
        self.assertTrue(autos)
        key = sre.explain_key(autos[0])
        dig = sre.digest(base, NOW, explained_keys={key})
        self.assertFalse([r for r in dig["records"] if r["kind"] == "automation"])
        moved = {**autos[0], "switches_off": ["switch.another_plug"]}
        self.assertNotEqual(sre.explain_key(moved), key)


def series(*steps):
    """[(hours ago, state)] oldest first -> raw history rows."""
    return [[iso(ago * H), word] for ago, word in steps]


TV_SLEEPS = series((100, "on"), (90, "off"), (89, "unavailable"),
                   (60, "playing"), (50, "off"), (49.5, "unavailable"),
                   (30, "on"), (10, "off"), (9.8, "unavailable"))
CAST = "homeassistant.components.cast.media_player"


def cast_house(history, tv_state="unavailable", tv_since=9.8 * H):
    h = collected(
        log=[log_row("Failed to connect to service ServiceInfo(type='mdns', "
                     "data='Lounge TV'), retrying in 5.0 seconds", CAST,
                     count=200, last_ago=300, first_ago=9 * H)],
        zha=[], automations=[],
        entities=[{"entity_id": "media_player.lounge_tv", "device_id": "d-tv",
                   "platform": "cast"},
                  {"entity_id": "media_player.kitchen_speaker",
                   "device_id": "d-sp", "platform": "cast"}],
        devices=[{"id": "d-tv", "name": "Lounge TV"},
                 {"id": "d-sp", "name": "Kitchen speaker"}],
        states={"media_player.lounge_tv": {
                    "state": tv_state, "last_changed": iso(tv_since),
                    "attributes": {"friendly_name": "Lounge TV"}},
                "media_player.kitchen_speaker": {
                    "state": "idle", "last_changed": iso(20 * H),
                    "attributes": {"friendly_name": "Kitchen speaker"}}})
    h["history"] = {"media_player.lounge_tv": history}
    return h


def judge(h):
    dig = sre.digest(h, NOW)
    recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
    parsed = sre.parse_causes({"causes": [{
        "title": "Google Cast cannot reach the Lounge TV", "records": recs,
        "detail": "It has been unreachable for hours.", "fix": ""}]}, dig)
    return sre.hold_transient(parsed["causes"], dig, NOW)


class TestATvThatSleepsWhenOffIsNotAFailure(unittest.TestCase):
    def test_unavailable_after_off_that_came_back_before_is_held(self):
        self.assertTrue(sre.sleeps_when_off(TV_SLEEPS, NOW))
        kept, held = judge(cast_house(TV_SLEEPS))
        self.assertEqual(kept, [])
        self.assertEqual(len(held), 1)
        self.assertIn("switched off", held[0]["reason"])
        self.assertIn("Lounge TV", held[0]["reason"])

    def test_unavailable_while_playing_is_still_filed(self):
        dropped = series((100, "on"), (90, "off"), (89, "unavailable"),
                         (60, "on"), (12, "playing"), (9.8, "unavailable"))
        self.assertFalse(sre.sleeps_when_off(dropped, NOW))
        kept, held = judge(cast_house(dropped))
        self.assertEqual(len(kept), 1)

    def test_a_first_ever_drop_after_off_is_still_filed(self):
        first = series((100, "playing"), (10, "off"), (9.8, "unavailable"))
        self.assertFalse(sre.sleeps_when_off(first, NOW))
        kept, _held = judge(cast_house(first))
        self.assertEqual(len(kept), 1)

    def test_a_tv_gone_for_days_is_still_filed(self):
        gone = series((160, "on"), (150, "off"), (149, "unavailable"),
                      (130, "on"), (100, "off"), (99, "unavailable"))
        self.assertFalse(sre.sleeps_when_off(gone, NOW))
        kept, _held = judge(cast_house(gone, tv_since=99 * H))
        self.assertEqual(len(kept), 1)

    def test_no_history_holds_nothing(self):
        kept, _held = judge(cast_house([]))
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()
