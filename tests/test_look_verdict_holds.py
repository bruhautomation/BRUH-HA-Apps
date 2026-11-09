#!/usr/bin/env python3
"""A finding whose look says it is not news is held, by a WORD (#790).

The look written under a finding said "this is cosmetic", "the household
has known about this for months", "this is already answered" or "this is
the same as the card about the hall sensor" — and the finding stayed on the
list. Two earlier fixes read those phrases out of the look's prose and held
real problems ("not log noise: the leak sensor has read wet for 20
minutes"; "…can wait, but this smoke alarm battery needs replacing
today"). So the verdict is a field the look gives (`resident.ALREADY`, with
`cosmetic` and `known` beside the older words), never a reading of its
sentence; a cross-reference is a field too (`same_as`, a case id from the
list the look was shown), and it merges the row into that card only when
the card is one the owner can see — otherwise it is dropped, and the
sentence naming "the list" is not shown.

And the floor under every one of those words (`corrections.not_news_floor`):
a leak or smoke sensor, a lock, a security check, a critical row and high
stakes are never held this way, whatever word the look gave.

Made-up examples: a porch light's icon, a utility-room radiator valve, a
garage plug, a shed motion sensor, a basement leak sensor, a hall smoke
alarm, the back-door lock and a `sec.` check.
"""

import sys
import time
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import corrections  # noqa: E402
import resident  # noqa: E402
from test_resident_loop import LoopCase, case_reply, reply  # noqa: E402


def open_ts(srv) -> set[int]:
    return {f["ts"] for f in srv.findings_store.list_all()
            if f["status"] == "open"}


class TestTheWords(unittest.TestCase):
    def test_cosmetic_and_known_are_words_the_look_may_give(self):
        self.assertIn("cosmetic", resident.ALREADY)
        self.assertIn("known", resident.ALREADY)
        item = resident.FIRST_LOOK_SCHEMA["properties"]["verdicts"]["items"]
        self.assertIn("same_as", item["properties"])
        self.assertNotIn("same_as", item["required"])
        self.assertIn('"cosmetic"', resident.FIRST_LOOK_SYSTEM)
        self.assertIn('"known"', resident.FIRST_LOOK_SYSTEM)
        self.assertIn('"same_as"', resident.FIRST_LOOK_SYSTEM)

    def test_the_sentence_alone_holds_nothing(self):
        # The two sentences the earlier attempts held, with no word: the
        # verdict the model gave stands.
        for why in ("This is not log noise: the leak sensor has read wet "
                    + "for 20 minutes.",
                    "It can wait, but this smoke alarm battery needs "
                    + "replacing today.",
                    "This is cosmetic and long-standing, already on the list."):
            out = resident.parse_first_look({"verdicts": [
                {"id": 1, "verdict": "investigate", "why": why}]}, 1,
                [{"kind": "check", "subject": "sensor.x",
                  "source": "check:dev.frozen"}])
            self.assertEqual(out[1]["verdict"], "investigate", why)
            self.assertNotIn("already", out[1])

    def test_same_as_is_kept_only_as_a_case_id(self):
        def said(ref):
            return resident.parse_first_look({"verdicts": [
                {"id": 1, "verdict": "ignore", "already": "duplicate",
                 "same_as": ref, "why": "Same Wi-Fi drop as the plug."}]}, 1,
                [{"kind": "check", "subject": "sensor.x"}])[1]
        self.assertEqual(said("f:1700000000")["same_as"], 1700000000)
        for bad in ("the hall card", "3", "f:", "p:12", ""):
            self.assertNotIn("same_as", said(bad), bad)

    def test_the_floor_names_each_class_it_keeps(self):
        floor = corrections.not_news_floor
        self.assertTrue(floor("binary_sensor.basement_leak", "check:dev.battery_low",
                              device_class="moisture", protected=()))
        self.assertTrue(floor("binary_sensor.hall_smoke", "check:dev.battery_low",
                              device_class="smoke", protected=()))
        self.assertTrue(floor("lock.back_door", "check:dev.unavailable",
                              protected=()))
        self.assertTrue(floor("binary_sensor.back_door", "check:sec.door_open",
                              protected=()))
        self.assertTrue(floor("sensor.freezer", "check:dev.frozen",
                              severity="critical", protected=()))
        self.assertTrue(floor("sensor.x", "resident", stakes="high",
                              protected=()))
        self.assertEqual(floor("light.porch", "check:dev.frozen",
                               severity="info", protected=()), "")

    def test_the_first_look_does_not_hold_a_lock_or_a_security_row(self):
        for sig in ({"kind": "check", "subject": "lock.back_door",
                     "source": "check:dev.unavailable"},
                    {"kind": "check", "subject": "binary_sensor.back_door",
                     "source": "check:sec.door_open"}):
            out = resident.parse_first_look({"verdicts": [
                {"id": 1, "verdict": "ignore", "already": "known",
                 "same_as": "f:12", "why": "Long-standing, they know."}]}, 1,
                [sig])
            self.assertNotEqual(out[1]["verdict"], "ignore", sig)
            self.assertNotIn("already", out[1])
            self.assertNotIn("same_as", out[1])


class TestSixFindingsNoneReachTheList(LoopCase):
    """Six findings replayed through the real loop and store."""

    def setUp(self):
        super().setUp()
        import decision_trail
        old = decision_trail.TRAIL_FILE
        decision_trail.TRAIL_FILE = str(Path(self.tmp.name) / "trail.jsonl")
        self.addCleanup(setattr, decision_trail, "TRAIL_FILE", old)
        names = self.server._NAMES
        saved = dict(names)
        self.addCleanup(lambda: (names.clear(), names.update(saved)))
        names.update({
            "binary_sensor.basement_leak": {"name": "Basement leak",
                                            "class": "moisture"},
            "binary_sensor.hall_smoke": {"name": "Hall smoke",
                                         "class": "smoke"},
            "sensor.garage_plug_rssi": {"name": "Garage plug signal",
                                        "class": "signal_strength"},
            "sensor.kitchen_fridge_temp": {"name": "Kitchen fridge",
                                           "class": "temperature"}})

    def row(self, eid, text, source="check:dev.frozen", **fields):
        return self.file_check_row(text=text, entity_id=eid, source=source,
                                   **fields)

    def visible(self, eid, text):
        row = self.row(eid, text)
        self.server.findings_store.record_triage(
            {row["ts"]: ("elevated", "Worth a look.")}, "look-0")
        return row

    def look(self, verdicts, now=None):
        self.looks.append(reply(verdicts))
        return self.tick(now if now is not None else time.time())

    def test_six_not_news_rows_are_held_or_merged(self):
        srv = self.server
        host = self.visible("switch.garage_plug",
                            "The garage plug drops off Wi-Fi every night")
        clock = [time.time()]

        def one(eid, text, answer, case=None):
            # One row, one look: the batch's order is the loop's own.
            row = self.row(eid, text)
            if case is not None:
                self.investigations.append(case)
            out = self.look([{"id": 1, **answer}], clock[0])
            self.assertTrue(out["looked"], out)
            clock[0] += srv.RESIDENT_LOOK_S + 1
            return row

        rows = [
            one("light.porch", "The porch light shows the wrong icon",
                {"verdict": "watch", "already": "cosmetic",
                 "why": "Only the icon is wrong; the light works."}),
            one("climate.utility", "The utility radiator valve is slow",
                {"verdict": "investigate", "already": "known",
                 "why": "The household has lived with this valve for a year."}),
            one("sensor.shed_motion_battery",
                "The shed motion sensor reads 31% battery",
                {"verdict": "watch", "already": "answered",
                 "why": "Memory says the battery is replaced every autumn."}),
            one("sensor.garage_plug_rssi",
                "The garage plug's signal reads -82 dBm",
                {"verdict": "ignore", "already": "duplicate",
                 "same_as": f"f:{host['ts']}",
                 "why": "Same Wi-Fi trouble as the garage plug card."}),
            # Two whose look sends them to an investigation that gives the
            # word (`answered`, the one word a case gives).
            one("sensor.loft_temp", "The loft sensor is named 'Temp 2'",
                {"verdict": "investigate", "why": "Worth a look."},
                case_reply(claim="The loft sensor is named Temp 2",
                           stakes="low", already="answered",
                           detail="The owner said the name is fine.", fix="")),
            one("sensor.pond_pump_power",
                "The pond pump draws no power at night",
                {"verdict": "investigate", "why": "Worth a look."},
                case_reply(claim="The pond pump is off at night",
                           stakes="low", already="answered",
                           detail="Its automation switches it off at 22:00 "
                                  "on purpose.", fix="")),
        ]
        shown = open_ts(srv)
        open_texts = [f["text"] for f in srv.findings_store.list_all()
                      if f["status"] == "open"]
        for row in rows:
            self.assertNotIn(row["text"], open_texts)
        # The duplicate is merged into the card it named, which the owner
        # can see: its device is listed under that card.
        # (A row's id is minted past what is live, so the merged row's id
        # can be the next row's: it is looked for by its words.)
        live = {f["ts"]: f for f in srv.findings_store.list_all()}
        self.assertNotIn(rows[3]["text"], [f["text"] for f in live.values()])
        self.assertIn(host["ts"], shown)
        self.assertIn("sensor.garage_plug_rssi",
                      [e["entity"] for e in live[host["ts"]]["evidence"]])

    def test_a_reference_to_nothing_visible_is_dropped(self):
        srv = self.server
        row = self.row("light.porch", "The porch light shows the wrong icon")
        self.look([{"id": 1, "verdict": "ignore", "already": "duplicate",
                    "same_as": "f:42",
                    "why": "Same as the open card about the porch. "
                           "It is already on your list."}])
        fresh = srv.findings_store.get(row["ts"])
        self.assertEqual(fresh["status"], "held")
        self.assertNotIn("cause", fresh)
        said = srv.findings_store.shown_look(fresh["triage"], fresh)["reason"]
        self.assertNotIn("list", said)
        self.assertNotIn("open card", said)

    def test_a_leak_smoke_lock_and_security_row_are_never_held_this_way(self):
        srv = self.server
        rows = [
            self.row("binary_sensor.basement_leak",
                     "The basement leak sensor reads 9% battery",
                     source="check:dev.battery_low"),
            self.row("binary_sensor.hall_smoke",
                     "The hall smoke alarm reads 12% battery",
                     source="check:dev.battery_low"),
            self.row("lock.back_door", "The back door lock has been offline",
                     source="check:dev.unavailable"),
            self.row("binary_sensor.back_door",
                     "The back door has been open since 02:10",
                     source="check:sec.door_open"),
            self.row("sensor.chest_freezer",
                     "The chest freezer reads -4 °C", severity="critical"),
        ]
        self.look([{"id": i, "verdict": "ignore", "already": word,
                    "why": "This can wait; it is long-standing."}
                   for i, word in enumerate(
                       ("known", "cosmetic", "known", "answered",
                        "known"), 1)])
        for row in rows:
            self.assertNotEqual(srv.findings_store.get(row["ts"])["status"],
                                "held", row["text"])

    def test_cosmetic_or_known_never_holds_food_water_or_an_unknown_sensor(
            self):
        # The review's gaps: a fridge temperature, a water row no class
        # names, and a sensor of no known kind. Each looked at on its own.
        srv = self.server
        clock = time.time()
        for eid, text, word in (
                ("sensor.kitchen_fridge_temp",
                 "The kitchen fridge reads 9 °C", "known"),
                ("sensor.chest_freezer_temperature",
                 "The chest freezer reads -9 °C", "cosmetic"),
                ("switch.garden_water_valve",
                 "The garden water valve has been on for 6 hours", "known"),
                ("sensor.boiler_pressure_raw",
                 "The boiler pressure reads 0.4", "known")):
            row = self.row(eid, text)
            self.look([{"id": 1, "verdict": "ignore", "already": word,
                        "why": "Long-standing; the household knows."}],
                      clock)
            clock += srv.RESIDENT_LOOK_S + 1
            self.assertNotEqual(srv.findings_store.get(row["ts"])["status"],
                                "held", text)

    def test_the_store_reapplies_the_strict_floor_for_the_new_words(self):
        srv = self.server
        row = self.row("sensor.chest_freezer", "The chest freezer reads -9 °C")
        srv.findings_store.record_triage(
            {row["ts"]: ("held", "They know.", True, 0, "known")}, "look-x")
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")
        other = self.row("light.porch", "The porch light shows the wrong icon")
        srv.findings_store.record_triage(
            {other["ts"]: ("held", "Only the icon.", True, 0, "cosmetic")},
            "look-y")
        self.assertEqual(srv.findings_store.get(other["ts"])["status"], "held")

    def test_the_store_keeps_its_floor_whoever_calls_it(self):
        srv = self.server
        row = self.row("sensor.chest_freezer", "The chest freezer reads -4 °C",
                       severity="critical")
        srv.findings_store.record_triage(
            {row["ts"]: ("held", "Long-standing; they know.", True)}, "look-x")
        self.assertEqual(srv.findings_store.get(row["ts"])["status"], "open")

    def test_an_investigation_word_on_a_lock_is_not_read(self):
        srv = self.server
        row = self.row("lock.back_door", "The back door lock jams",
                       source="check:dev.unavailable")
        self.investigations.append(case_reply(
            claim="The back door lock jams", stakes="medium",
            already="answered", detail="The owner knows it sticks.",
            fix="Oil the latch.",
            evidence=[{"entity": "lock.back_door", "value": "jammed",
                       "when": "today"}]))
        self.look([{"id": 1, "verdict": "investigate", "why": "Look."}])
        self.assertNotEqual(srv.findings_store.get(row["ts"])["status"],
                            "held")


if __name__ == "__main__":
    unittest.main()
