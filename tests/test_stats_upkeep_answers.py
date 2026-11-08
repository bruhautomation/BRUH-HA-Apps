#!/usr/bin/env python3
"""The statistics question's Yes and No, and when a pass runs (#576, the
second review).

  * A Yes to one "Clear the old long-term statistics of …?" card clears
    ONLY the statistics that card named — never one the owner said No to
    on an earlier card, never a second card's open at the same time, and
    nothing at all once the statistic is no longer flagged or has become
    protected.
  * A No is remembered: that statistic is never cleared and is not asked
    about again for a long time; the toast's Undo forgets the No.
  * A card that vanished unanswered is asked again.
  * A Core restart runs a pass (the integration sets up again and moves its
    loaded stamp), and a pass that found Core still starting is tried again
    after an hour, neither of them on every poll.
  * A `units_changed` whose data does not say whether the units convert is
    left alone with a reason, not relabelled.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import stats_upkeep  # noqa: E402

NOW = 1_800_000_000.0
HOURS = 3600
DAYS = 86400
NAMES = {"sensor.attic_temp": {"name": "Attic temperature"},
         "sensor.cellar_power": {"name": "Cellar power"},
         "sensor.porch_lux": {"name": "Porch light level"}}
YES = {"kind": "accepted", "label": "accepted"}
NO = {"kind": "ignored", "label": "wrong"}
DOES_NOT_APPLY = {"kind": "not_applicable"}


def live(eid, unit="W"):
    return {"entity_id": eid, "state": "1",
            "attributes": {"unit_of_measurement": unit}}


def flagged(eid, kind="state_class_removed"):
    return {eid: [{"type": kind, "data": {"statistic_id": eid}}]}


class FakeHouse(unittest.TestCase):
    """`server._run_statistics` and `_end_statistics` over a fake recorder
    and a fake findings store: the cards filed, the calls made."""

    def setUp(self):
        self.server = importlib.import_module("server")
        s, fs = self.server, self.server.findings_store
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = (stats_upkeep.STORE, s._stats_ws, s._stats_states,
                      fs.add_case, fs.list_all, fs.settle_and_clear,
                      fs.settled_listing, s._findings_payload, dict(s._NAMES))
        # The settled ledger: `{normalized text: kind}`. A card whose words
        # are in it is refused, as the real store refuses one.
        self.ledger: dict[str, str] = {}
        self.refuse_all = False
        stats_upkeep.STORE = Path(self.tmp.name) / "stats.json"
        s._NAMES.clear()
        s._NAMES.update(NAMES)
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        self.sent: list[dict] = []
        self.cards: list[dict] = []
        self.issues: dict = {}
        self.states: list[dict] = []

        async def ws(commands):
            out = []
            for cmd in commands:
                self.sent.append(cmd)
                kind = cmd["type"]
                if kind == "recorder/validate_statistics":
                    out.append({"ok": True, "result": dict(self.issues)})
                elif kind == "config/entity_registry/list":
                    out.append({"ok": True, "result": []})
                elif kind == "get_config":
                    out.append({"ok": True, "result": {"state": "RUNNING"}})
                else:
                    if kind == "recorder/clear_statistics":
                        for sid in cmd["statistic_ids"]:
                            self.issues.pop(sid, None)
                    out.append({"ok": True, "result": None})
            return out

        async def states():
            return list(self.states)

        def add_case(row, **kw):
            if self.refuse_all or fs.normalize(row["text"]) in self.ledger:
                return None
            card = {**row, "ts": 100 + len(self.cards), "status": "open"}
            self.cards.append(card)
            return card

        def settled_listing():
            return [{"key": k, "kind": v} for k, v in self.ledger.items()]

        def list_all(status=None):
            return [c for c in self.cards if c["status"] == "open"]

        def settle_and_clear(ts, kind, note=""):
            for c in self.cards:
                if c["ts"] == ts:
                    c["status"] = kind

        s._stats_ws, s._stats_states = ws, states
        fs.add_case, fs.list_all, fs.settle_and_clear = (
            add_case, list_all, settle_and_clear)
        fs.settled_listing = settled_listing
        s._findings_payload = lambda: {}

    def tearDown(self):
        s, fs = self.server, self.server.findings_store
        (stats_upkeep.STORE, s._stats_ws, s._stats_states, fs.add_case,
         fs.list_all, fs.settle_and_clear, fs.settled_listing,
         s._findings_payload, names) = self.saved
        s._NAMES.clear()
        s._NAMES.update(names)
        self.tmp.cleanup()

    def run_pass(self, now=NOW):
        asyncio.run(self.server._run_statistics("schedule", now=now))

    def answer(self, card, spec, now=NOW):
        asyncio.run(self.server._end_statistics(card, spec, "", now=now))

    def cleared(self):
        return [sid for c in self.sent if c["type"] == "recorder/clear_statistics"
                for sid in c["statistic_ids"]]

    def open_cards(self):
        return [c for c in self.cards if c["status"] == "open"]


class TestAYesClearsOnlyWhatItsCardNamed(FakeHouse):
    def test_no_to_one_card_then_yes_to_another_clears_only_the_second(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.run_pass(NOW)
        [first] = self.open_cards()
        self.assertIn("Attic temperature", first["text"])

        # A day later the cellar meter is flagged too: its own card.
        self.issues.update(flagged("sensor.cellar_power", "mean_type_changed"))
        self.states.append(live("sensor.cellar_power"))
        self.run_pass(NOW + DAYS)
        first, second = self.open_cards()
        self.assertIn("Cellar power", second["text"])
        self.assertNotIn("Attic temperature", second["text"])

        self.answer(first, NO)
        self.assertEqual(self.cleared(), [])
        self.answer(second, YES)
        self.assertEqual(self.cleared(), ["sensor.cellar_power"])
        self.assertEqual(self.open_cards(), [])
        # History says the cellar's statistics went on an answer.
        store = stats_upkeep.load()
        self.assertEqual([(c["statistic_id"], c["channel"], c["ok"])
                          for c in store["changes"]],
                         [("sensor.cellar_power", "answer", True)])

    def test_two_cards_open_at_once_each_clear_their_own(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C"), live("sensor.cellar_power")]
        self.run_pass(NOW)
        self.issues.update(flagged("sensor.cellar_power", "mean_type_changed"))
        self.run_pass(NOW + DAYS)
        first, second = self.open_cards()

        self.answer(first, YES)
        self.assertEqual(self.cleared(), ["sensor.attic_temp"])
        self.assertEqual(self.open_cards(), [second])
        self.answer(second, YES)
        self.assertEqual(self.cleared(), ["sensor.attic_temp",
                                          "sensor.cellar_power"])

    def test_a_yes_clears_nothing_once_the_statistic_is_not_flagged(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.run_pass(NOW)
        [card] = self.open_cards()
        # Core stopped flagging it (the owner fixed it in Core themselves).
        self.issues.clear()
        self.answer(card, YES)
        self.assertEqual(self.cleared(), [])
        self.assertEqual(self.open_cards(), [])

    def test_a_yes_clears_nothing_once_the_entity_is_protected(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.run_pass(NOW)
        [card] = self.open_cards()
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "sensor.attic_temp"
        try:
            self.answer(card, YES)
        finally:
            os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        self.assertEqual(self.cleared(), [])


class TestANoIsRemembered(FakeHouse):
    def test_a_statistic_said_no_to_is_not_asked_again_for_a_long_time(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.run_pass(NOW)
        [card] = self.open_cards()
        self.answer(card, NO)
        # Still flagged on every later pass: no new card, nothing cleared.
        for days in (1, 7, 60):
            self.run_pass(NOW + days * DAYS)
        self.assertEqual(self.open_cards(), [])
        self.assertEqual(self.cleared(), [])
        # Long after, it may be asked once more.
        self.run_pass(NOW + (stats_upkeep.DECLINED_S / DAYS + 1) * DAYS)
        self.assertEqual(len(self.open_cards()), 1)

    def test_doesnt_apply_clears_nothing_and_records_no_answer(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.run_pass(NOW)
        [card] = self.open_cards()
        self.answer(card, DOES_NOT_APPLY)
        self.assertEqual(self.cleared(), [])
        self.assertEqual(stats_upkeep.load()["declined"], {})

    def test_undo_of_a_no_puts_the_question_back(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.run_pass(NOW)
        [card] = self.open_cards()
        self.answer(card, NO)
        # The toast's Undo restores the card; the answer is forgotten with it.
        card["status"] = "open"
        self.server._stats_answer_undo({"kind": "finding", "finding": card})
        self.assertEqual(stats_upkeep.load()["declined"], {})
        self.answer(card, YES)
        self.assertEqual(self.cleared(), ["sensor.attic_temp"])

    def test_a_card_that_vanished_unanswered_is_asked_again(self):
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.run_pass(NOW)
        self.run_pass(NOW + DAYS)
        self.assertEqual(len(self.cards), 1)
        # Pruned, folded away: gone without an answer.
        self.cards.clear()
        self.run_pass(NOW + 2 * DAYS)
        self.assertEqual(len(self.open_cards()), 1)
        self.assertEqual(self.cleared(), [])


class TestTheStoreKeepsEachCardsOwnList(unittest.TestCase):
    def asks(self, *sids):
        return [{"statistic_id": s, "type": "state_class_removed", "why": ""}
                for s in sids]

    def test_answers_are_per_card(self):
        store = stats_upkeep.load(Path(tempfile.mkdtemp()) / "none.json")
        stats_upkeep.note_asked(store, self.asks("sensor.a"), "101", NOW)
        stats_upkeep.note_asked(store, self.asks("sensor.b", "sensor.c"),
                                "102", NOW)
        self.assertEqual(stats_upkeep.to_ask(store, self.asks("sensor.a",
                                                              "sensor.d"), NOW),
                         self.asks("sensor.d"))
        declined = stats_upkeep.answer(store, "101", outcome="declined", now=NOW)
        self.assertEqual([a["statistic_id"] for a in declined], ["sensor.a"])
        self.assertIn("sensor.a", store["declined"])
        # The No keeps a from being asked; b and c are still open on 102.
        self.assertEqual(stats_upkeep.to_ask(store, self.asks("sensor.a"), NOW),
                         [])
        taken = stats_upkeep.answer(store, "102", outcome="accepted", now=NOW)
        self.assertEqual(sorted(a["statistic_id"] for a in taken),
                         ["sensor.b", "sensor.c"])
        self.assertEqual(store["asked"], [])
        self.assertNotIn("sensor.b", store["declined"])
        # Undo of the No on 101 forgets it and puts a back on the card.
        stats_upkeep.forget_answer(store, "101")
        self.assertEqual(store["declined"], {})
        self.assertEqual([a["card"] for a in store["asked"]], ["101"])

    def test_open_questions_drops_a_card_that_is_gone(self):
        store = stats_upkeep.load(Path(tempfile.mkdtemp()) / "none.json")
        stats_upkeep.note_asked(store, self.asks("sensor.a"), "101", NOW)
        stats_upkeep.note_asked(store, self.asks("sensor.b"), "102", NOW)
        kept = stats_upkeep.open_questions(store, {"102"})
        self.assertEqual([a["statistic_id"] for a in kept], ["sensor.b"])
        # An unreadable list of cards is "could not tell": nothing dropped.
        self.assertEqual(len(stats_upkeep.open_questions(store, None)), 2)


class TestUnitsWhoseConversionCoreDidNotSay(unittest.TestCase):
    def issue(self, data):
        return stats_upkeep.issues_from({"sensor.meter": [
            {"type": "units_changed", "data": {"statistic_id": "sensor.meter",
                                               **data}}]})

    def test_missing_unit_class_keys_are_left_with_a_reason(self):
        out = stats_upkeep.plan(
            self.issue({"state_unit": "kWh", "metadata_unit": "Wh",
                        "supported_unit": "Wh"}),
            [live("sensor.meter", "kWh")], [], core_state="RUNNING")
        self.assertEqual(out["fix"], [])
        [left] = out["leave"]
        self.assertIn("did not say", left["why"])

    def test_one_class_key_alone_is_not_an_answer_either(self):
        out = stats_upkeep.plan(
            self.issue({"state_unit": "L", "metadata_unit": "gal",
                        "supported_unit": "gal", "state_unit_class": "volume"}),
            [live("sensor.meter", "L")], [], core_state="RUNNING")
        self.assertEqual(out["fix"], [])
        self.assertEqual(len(out["leave"]), 1)


class TestWhenAPassRuns(unittest.TestCase):
    def test_a_core_restart_is_a_pass_and_not_a_pass_per_poll(self):
        store = {"last_run": NOW - HOURS, "core_version": "2026.11.1",
                 "core_loaded_at": NOW - 2 * DAYS, "core_state": "RUNNING"}
        same = dict(core_version="2026.11.1", core_loaded_at=NOW - 2 * DAYS)
        self.assertFalse(stats_upkeep.due(store, NOW, **same))
        # Core came back up: the integration set up again just now.
        self.assertTrue(stats_upkeep.due(store, NOW, core_version="2026.11.1",
                                         core_loaded_at=NOW - 60))
        # A pass recorded that start; the next poll is quiet again.
        store["core_loaded_at"] = NOW - 60
        store["last_run"] = NOW
        self.assertFalse(stats_upkeep.due(store, NOW + 600,
                                          core_version="2026.11.1",
                                          core_loaded_at=NOW - 60))
        # And a store that never saw a stamp is not "it moved".
        self.assertFalse(stats_upkeep.due({"last_run": NOW}, NOW + 600,
                                          core_loaded_at=NOW))

    def test_a_pass_that_found_core_starting_is_tried_again_within_the_hour(self):
        store = {"last_run": NOW, "core_state": "NOT_RUNNING"}
        self.assertFalse(stats_upkeep.due(store, NOW + 600))
        self.assertTrue(stats_upkeep.due(store, NOW + stats_upkeep.RETRY_S + 1))
        # A pass Core did not answer about its state is a restart too.
        store["core_state"] = ""
        self.assertTrue(stats_upkeep.due(store, NOW + stats_upkeep.RETRY_S + 1))
        store["core_state"] = "RUNNING"
        self.assertFalse(stats_upkeep.due(store, NOW + stats_upkeep.RETRY_S + 1))


class TestTheMaintainerSeesCoreRestart(unittest.TestCase):
    def setUp(self):
        import settings_store
        self.server = importlib.import_module("server")
        self.settings_store = settings_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        s = self.server
        self.saved = (s.schedule_store.STORE, settings_store.SETTINGS_FILE,
                      s._maint_start, stats_upkeep.STORE, dict(s.STATS_STATE),
                      dict(s.MAINT_STATE["statistics"]), s.house_book.STORE,
                      s.INTEGRATION_LOADED_FILE)
        s.schedule_store.STORE = str(root / "schedule.json")
        settings_store.SETTINGS_FILE = str(root / "settings.json")
        stats_upkeep.STORE = root / "stats.json"
        s.house_book.STORE = root / "book.json"
        s.INTEGRATION_LOADED_FILE = root / "integration_loaded.json"
        s.STATS_STATE.update(booted=True, tried=0.0)
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "upgrade_advice_auto": False})
        self.started: list[str] = []
        s._maint_start = lambda name, factory: self.started.append(name) or True

    def tearDown(self):
        s = self.server
        (s.schedule_store.STORE, self.settings_store.SETTINGS_FILE,
         s._maint_start, stats_upkeep.STORE, state, maint,
         s.house_book.STORE, s.INTEGRATION_LOADED_FILE) = self.saved
        s.STATS_STATE.clear()
        s.STATS_STATE.update(state)
        s.MAINT_STATE["statistics"].update(maint)
        self.tmp.cleanup()

    def loaded(self, at):
        self.server.INTEGRATION_LOADED_FILE.write_text(json.dumps(
            {"version": "5.1.8", "fingerprint": "abc", "at": int(at)}))

    def tick(self, now):
        asyncio.run(self.server._maint_tick(now))

    def test_a_moved_loaded_stamp_starts_one_pass(self):
        # The last pass ran an hour ago and saw the stamp of two days ago.
        self.loaded(NOW - 2 * DAYS)
        stats_upkeep.save({"last_run": NOW - HOURS, "core_state": "RUNNING",
                           "core_loaded_at": int(NOW - 2 * DAYS)}, None, NOW)
        self.tick(NOW)
        self.assertEqual(self.started, [])
        self.loaded(NOW - 30)
        self.tick(NOW + self.server.MAINT_POLL_S)
        self.assertEqual(self.started, ["statistics"])
        # Nothing wrote the new stamp down (the pass is a fake), so this is
        # the retry wait holding it, not the poll.
        self.tick(NOW + 2 * self.server.MAINT_POLL_S)
        self.assertEqual(self.started, ["statistics"])


class TestACardNamesEverythingItsYesClears(FakeHouse):
    """Review round 3: the card named five and said "and N more", while its
    Yes cleared every statistic recorded under it. A card carries only the
    statistics its text names; the rest wait for a later card."""

    def flag(self, n):
        for i in range(n):
            sid = f"sensor.meter_{i}"
            self.issues.update(flagged(sid))
            self.states.append(live(sid))
            self.server._NAMES[sid] = {"name": f"Meter {i}"}

    def named_in(self, card):
        return sorted(f"sensor.meter_{i}" for i in range(8)
                      if f"Meter {i}" in card["text"])

    def test_eight_flagged_are_asked_five_then_the_rest(self):
        self.flag(8)
        self.run_pass(NOW)
        [card] = self.open_cards()
        first = self.named_in(card)
        self.assertEqual(len(first), stats_upkeep.MAX_NAMED)
        self.assertNotIn("more", card["text"])
        # The card's own record is exactly what its text names.
        self.assertEqual(sorted(a["statistic_id"]
                                for a in stats_upkeep.load()["asked"]), first)
        self.answer(card, YES)
        self.assertEqual(sorted(self.cleared()), first)
        # The rest are asked on a later card, and only then cleared.
        self.run_pass(NOW + DAYS)
        [second] = self.open_cards()
        rest = self.named_in(second)
        self.assertEqual(len(rest), 8 - stats_upkeep.MAX_NAMED)
        self.assertEqual(set(rest) & set(first), set())
        self.answer(second, YES)
        self.assertEqual(sorted(self.cleared()), sorted(first + rest))

    def test_long_names_make_a_shorter_card_never_a_clipped_one(self):
        asks = [{"statistic_id": f"sensor.m{i}", "type": "state_class_removed",
                 "why": "w"} for i in range(5)]
        names = {f"sensor.m{i}": {"name": f"A very long sensor name number {i} "
                                          "in the back of the garage"}
                 for i in range(5)}
        batch = stats_upkeep.batch(asks, names)
        self.assertLess(len(batch), 5)
        row = stats_upkeep.ask_row(batch, names)
        self.assertLessEqual(len(row["text"]), stats_upkeep.TEXT_BUDGET)
        for a in batch:
            self.assertIn(names[a["statistic_id"]]["name"], row["text"])


class TestARefusedCardIsNotANoUnlessItWasOne(FakeHouse):
    """Review round 3: a card the findings store refuses (its words were
    settled before) was written down as a 90-day No — but the settled
    ending may have been a Yes whose clear failed. Only a No is a No; a
    Yes, or an ending that cannot be told, is asked again later in other
    words, and not on every pass in between."""

    def words(self):
        plan = stats_upkeep.plan(stats_upkeep.issues_from(self.issues),
                                 self.states, [], core_state="RUNNING")
        return stats_upkeep.ask_row(plan["ask"], NAMES)["text"]

    def setUp(self):
        super().setUp()
        self.issues = flagged("sensor.attic_temp")
        self.states = [live("sensor.attic_temp", "°C")]
        self.key = self.server.findings_store.normalize(self.words())

    def test_words_settled_by_a_no_hold_as_a_no(self):
        self.ledger[self.key] = "ignored"
        self.run_pass(NOW)
        self.assertEqual(self.open_cards(), [])
        self.assertIn("sensor.attic_temp", stats_upkeep.load()["declined"])
        self.run_pass(NOW + 2 * DAYS)
        self.assertEqual(self.open_cards(), [])

    def test_words_settled_by_a_yes_are_asked_again_in_other_words(self):
        self.ledger[self.key] = "accepted"
        self.run_pass(NOW)
        self.assertEqual(self.open_cards(), [])
        self.assertEqual(stats_upkeep.load()["declined"], {})
        # A restart pass an hour later does not try the same card again.
        self.run_pass(NOW + HOURS)
        self.assertEqual(self.open_cards(), [])
        # A day later it is asked in other words, and that Yes clears it.
        self.run_pass(NOW + DAYS + HOURS)
        [card] = self.open_cards()
        self.assertNotEqual(self.server.findings_store.normalize(card["text"]),
                            self.key)
        self.assertIn("Attic temperature", card["text"])
        self.assertNotIn("sensor.", card["text"] + card["claim"])
        self.answer(card, YES)
        self.assertEqual(self.cleared(), ["sensor.attic_temp"])

    def test_a_refusal_nobody_can_explain_is_not_a_no_either(self):
        self.refuse_all = True
        self.run_pass(NOW)
        self.assertEqual(stats_upkeep.load()["declined"], {})
        self.refuse_all = False
        self.run_pass(NOW + DAYS + HOURS)
        self.assertEqual(len(self.open_cards()), 1)


if __name__ == "__main__":
    unittest.main()
