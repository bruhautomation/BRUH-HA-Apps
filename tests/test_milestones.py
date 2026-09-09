#!/usr/bin/env python3
"""The card brAIn writes the day it first knows something.

Seven measurements, each of which takes weeks, and each of which becomes
news exactly once. What has to hold is not that a card gets written —
that is a Claude run and nothing here calls one — but that the *table*
fires when it should, never on a house where nothing has landed, never
twice, and never onto the Insights tab.

Every case drives the real `due()` over the real predicates. A fixture
that satisfied a milestone by asserting the predicate's own arithmetic
back at it would only ever agree with itself, so each store's fixture is
the shape that store really writes.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import categories  # noqa: E402
import house  # noqa: E402
import milestones  # noqa: E402

NOW = 1_800_000_000.0


# ---------------------------------------------------------------------------
# Fixtures: one house per milestone, in the shape its store really writes
# ---------------------------------------------------------------------------

def progress(state, **fields):
    """A store's own answer, through `house.progress` rather than a dict.

    The shape is written down in one place and this is that place's
    consumer; hand-rolling the seven keys here would be a second copy of
    the contract `house.py`'s docstring publishes.
    """
    base = {"unit": "days", "need": 1, "have": 1, "now": NOW}
    base.update(fields)
    return house.progress(state=state, **base)


def clean_snapshot():
    """A house eight days old: every measurement still waiting."""
    return {"generated_at": int(NOW), "stores": {
        name: progress(house.NOT_STARTED, have=0,
                       reason="no pass has run yet",
                       summary="Nothing measured yet.")
        for name in house.STORES}}


def with_store(name, prog, payload=None):
    """The clean house with one measurement answered."""
    snap = clean_snapshot()
    snap["stores"][name] = prog
    return snap, {name: payload or {}}


def rhythm_house(wake="07:10", settle="22:40"):
    return with_store("rhythm", progress(
        house.READY, unit="days", need=14, have=20,
        summary=f"Weekdays wake about {wake}, spread 18 min.",
        detail={"weekday_days": 20, "weekend_days": 8,
                "weekday": {"wakes": {"at": wake, "minute": 430,
                                      "spread_min": 18.0, "days": 20},
                            "settles": {"at": settle, "minute": 1360,
                                        "spread_min": 22.0, "days": 20}},
                "weekend": {"wakes": {"at": "09:05", "minute": 545,
                                      "spread_min": 30.0, "days": 8},
                            "settles": None}}))


def baselines_house(with_buckets=30):
    payload = {"built_at": int(NOW), "entities": {
        f"sensor.room_{i}": {"buckets": {"12": {"median": 20.0}},
                             "unit": "°C"}
        for i in range(with_buckets)}}
    return with_store("baselines", progress(
        house.READY, unit="entities", need=1, have=with_buckets,
        summary=f"{with_buckets} sensors measured.",
        detail={"measured": with_buckets, "with_buckets": with_buckets,
                "flat": 2, "trends": 1}), payload)


def thermal_house(rooms=2):
    payload = {"built_at": int(NOW), "outdoor": "sensor.outside",
               "coldest": -2.5,
               "rooms": {f"sensor.room_{i}": {
                   "k": 0.11, "tau_h": 9.0 + i, "gain": 1.4,
                   "area": f"Room {i}"} for i in range(rooms)}}
    return with_store("thermal", progress(
        house.READY, unit="rooms", need=1, have=rooms,
        summary=f"{rooms} rooms measured against sensor.outside.",
        detail={"outdoor": "sensor.outside", "rooms": rooms,
                "coldest": -2.5}), payload)


def appliances_house(profiled=1, chores=1):
    payload = {"built_at": int(NOW), "entities": {
        f"sensor.machine_{i}": {"name": f"Machine {i}", "idle_w": 1.2,
                                "threshold_w": 18.0, "settle_min": 21.0}
        for i in range(profiled)}}
    return with_store("appliances", progress(
        house.READY, unit="machines", need=1, have=profiled,
        summary=f"{profiled} machines measured.",
        detail={"profiled": profiled, "chore_capable": chores}), payload)


def closures_house(watched=3, hours=30):
    payload = {"built_at": int(NOW), "entities": {
        f"binary_sensor.door_{i}": {
            "name": f"Door {i}", "overall": 0.08,
            "buckets": {str(h): {"open": 0.05} for h in range(hours)}}
        for i in range(watched)}}
    return with_store("closures", progress(
        house.READY, unit="hours", need=24, have=hours,
        summary=f"{watched} closures watched.",
        detail={"entities": watched}), payload)


def energy_house(comparable=True):
    week = {"available": True, "energy": {
        "this": 84.2, "last": 91.0, "days": 7, "days_before": 7,
        "change_pct": -7.5, "comparable": comparable, "unit": "kWh"}}
    return with_store("energy", progress(
        house.READY, unit="days", need=7, have=7,
        summary="84.2 kWh over 7 days.", detail=week))


def habits_house(propose=2):
    return with_store("habits", progress(
        house.READY, unit="days", need=6, have=9,
        summary="41 presses over 9 days.",
        detail={"presses": 41, "would_propose": propose, "overrides": 4}))


HOUSES = {
    "rhythm": rhythm_house,
    "baselines": baselines_house,
    "thermal": thermal_house,
    "appliances": appliances_house,
    "closures": closures_house,
    "energy": energy_house,
    "habits": habits_house,
}


class MilestoneCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (milestones.CARDS_DIR, milestones.SETTLED_FILE)
        milestones.CARDS_DIR = root / "knowledge-cards"
        milestones.SETTLED_FILE = milestones.CARDS_DIR / "_settled.json"

    def tearDown(self):
        milestones.CARDS_DIR, milestones.SETTLED_FILE = self._old
        self.tmp.cleanup()

    def fire(self, name):
        snap, payloads = HOUSES[name]()
        return milestones.due(snap, payloads, NOW)


# ---------------------------------------------------------------------------

class TestEachOneFiresOnce(MilestoneCase):
    def test_every_milestone_in_the_table_has_a_house_that_fires_it(self):
        """The table and this file agree about what the seven are.

        Asserted as a set rather than per case, because a new milestone
        with no fixture would otherwise be a test nobody wrote and
        nothing would say so.
        """
        self.assertEqual(set(milestones.MILESTONE_IDS), set(HOUSES))

    def test_each_fires_on_its_own_house(self):
        for name in milestones.MILESTONE_IDS:
            with self.subTest(name):
                due = self.fire(name)
                self.assertEqual([d["id"] for d in due], [name])
                self.assertIn(name, due[0]["made_because"])

    def test_nothing_fires_on_a_house_where_nothing_has_landed(self):
        """The clean fixture is the whole point: a card about a
        measurement that has not been made is a card about nothing."""
        self.assertEqual(milestones.due(clean_snapshot(), {}, NOW), [])

    def test_a_stale_measurement_is_not_news(self):
        """`stale` is an answer from three weeks ago, and a milestone is
        about something becoming true today."""
        snap, payloads = rhythm_house()
        snap["stores"]["rhythm"]["state"] = house.STALE
        self.assertEqual(milestones.due(snap, payloads, NOW), [])


class TestTheExtraBarACardNeeds(MilestoneCase):
    """The floors that are the CARD's rather than the measurement's."""

    def test_one_baseline_is_not_a_picture_of_a_house(self):
        snap, payloads = baselines_house(with_buckets=3)
        self.assertEqual(milestones.due(snap, payloads, NOW), [])
        snap, payloads = baselines_house(
            with_buckets=milestones.BASELINE_ENTITIES)
        self.assertEqual([d["id"] for d in milestones.due(snap, payloads, NOW)],
                         ["baselines"])

    def test_one_fitted_room_cannot_be_compared_with_anything(self):
        snap, payloads = thermal_house(rooms=1)
        self.assertEqual(milestones.due(snap, payloads, NOW), [])

    def test_a_closure_watched_for_less_than_a_day_does_not_count(self):
        snap, payloads = closures_house(watched=5, hours=6)
        self.assertEqual(milestones.due(snap, payloads, NOW), [])
        snap, payloads = closures_house(watched=2, hours=40)
        self.assertEqual(milestones.due(snap, payloads, NOW), [])

    def test_a_week_that_cannot_be_compared_is_not_a_comparison(self):
        snap, payloads = energy_house(comparable=False)
        self.assertEqual(milestones.due(snap, payloads, NOW), [])

    def test_a_ledger_with_nothing_worth_proposing_is_not_a_habit(self):
        snap, payloads = habits_house(propose=0)
        self.assertEqual(milestones.due(snap, payloads, NOW), [])


class TestTheStoresNumbersReachThePrompt(MilestoneCase):
    def test_the_wake_and_settle_times_are_in_the_rhythm_prompt(self):
        prompt = self.fire("rhythm")[0]["prompt"]
        self.assertIn("07:10", prompt)
        self.assertIn("22:40", prompt)
        self.assertIn("09:05", prompt)

    def test_the_measured_counts_are_in_the_baselines_prompt(self):
        prompt = self.fire("baselines")[0]["prompt"]
        self.assertIn("30 sensors read", prompt)
        self.assertIn("sensor.room_0", prompt)

    def test_each_rooms_time_constant_is_in_the_thermal_prompt(self):
        prompt = self.fire("thermal")[0]["prompt"]
        self.assertIn("Room 0", prompt)
        self.assertIn("9.0 h", prompt)
        self.assertIn("sensor.outside", prompt)

    def test_the_measured_watts_are_in_the_appliance_prompt(self):
        prompt = self.fire("appliances")[0]["prompt"]
        self.assertIn("18.0 W", prompt)
        self.assertIn("21 minutes", prompt)

    def test_both_weeks_are_in_the_energy_prompt(self):
        prompt = self.fire("energy")[0]["prompt"]
        self.assertIn("84.2 kWh", prompt)
        self.assertIn("91.0 kWh", prompt)

    def test_the_prompt_says_these_are_brains_own_numbers(self):
        """The whole reason for the block: a card that re-derives what
        was already measured is a card that disagrees with the tab
        beside it."""
        for name in milestones.MILESTONE_IDS:
            with self.subTest(name):
                prompt = self.fire(name)[0]["prompt"]
                self.assertIn("OWN numbers", prompt)
                self.assertIn("Do not re-derive", prompt)


class TestOnceAndOnlyOnce(MilestoneCase):
    def _save(self, name, due):
        return milestones.save_card(
            name, {"title": "T", "summary": "S", "html": "<p>x</p>"},
            due["mark"], due["made_because"], NOW)

    def test_the_settled_key_blocks_a_refire(self):
        due = self.fire("rhythm")[0]
        self._save("rhythm", due)
        self.assertTrue(milestones.is_settled("rhythm"))
        self.assertEqual(self.fire("rhythm"), [])

    def test_deleting_the_card_does_not_re_arm_it(self):
        """The settled key is beside the cards, not inside one: a card
        somebody removed is not a measurement that became true again."""
        due = self.fire("rhythm")[0]
        self._save("rhythm", due)
        milestones.card_path("rhythm").unlink()
        self.assertIsNone(milestones.get_card("rhythm"))
        self.assertEqual(self.fire("rhythm"), [])

    def test_a_failed_card_leaves_the_milestone_armed(self):
        """`save_card` is what settles, which is to say success is —
        a card that never got written is news nobody has had."""
        self.fire("rhythm")
        self.assertFalse(milestones.is_settled("rhythm"))
        self.assertEqual(len(self.fire("rhythm")), 1)

    def test_an_unchanged_measurement_says_nothing_again(self):
        due = self.fire("rhythm")[0]
        self._save("rhythm", due)
        snap, payloads = rhythm_house()
        snap["stores"]["rhythm"]["detail"]["weekday"]["wakes"]["minute"] = 445
        self.assertEqual(milestones.due(snap, payloads, NOW), [])

    def test_a_wake_time_that_really_moved_says_so_again(self):
        due = self.fire("rhythm")[0]
        self._save("rhythm", due)
        snap, payloads = rhythm_house(wake="09:30")
        snap["stores"]["rhythm"]["detail"]["weekday"]["wakes"]["minute"] = 570
        again = milestones.due(snap, payloads, NOW)
        self.assertEqual([d["id"] for d in again], ["rhythm"])
        self.assertIn("changed materially", again[0]["made_because"])

    def test_a_settle_time_either_side_of_midnight_is_not_a_days_drift(self):
        """23:50 is twenty minutes from 00:10, and a straight subtraction
        reports it as twenty-three hours and forty."""
        self.assertFalse(milestones._rhythm_moved(
            {"settle": 1430.0}, {"settle": 10.0}))
        self.assertTrue(milestones._rhythm_moved(
            {"settle": 1430.0}, {"settle": 120.0}))

    def test_a_week_of_electricity_never_re_fires(self):
        """Every week is a new week; what became true once is that a
        comparison is possible at all, and that is the weekly report's
        job from then on."""
        due = self.fire("energy")[0]
        self._save("energy", due)
        snap, payloads = energy_house()
        snap["stores"]["energy"]["detail"]["energy"]["this"] = 12.0
        self.assertEqual(milestones.due(snap, payloads, NOW), [])

    def test_refresh_re_arms_exactly_one(self):
        for name in ("rhythm", "habits"):
            self._save(name, self.fire(name)[0])
        self.assertTrue(milestones.unsettle("rhythm"))
        self.assertFalse(milestones.is_settled("rhythm"))
        self.assertTrue(milestones.is_settled("habits"))
        self.assertFalse(milestones.unsettle("rhythm"))


class TestTheCards(MilestoneCase):
    def test_a_card_carries_why_it_was_made(self):
        due = self.fire("thermal")[0]
        card = milestones.save_card(
            "thermal", {"title": "How the rooms hold heat", "summary": "S",
                        "html": "<p>x</p>"},
            due["mark"], due["made_because"], NOW)
        self.assertEqual(card["kind"], "milestone")
        self.assertIn("thermal", card["made_because"])
        stored = milestones.get_card("thermal")
        self.assertEqual(stored["title"], "How the rooms hold heat")
        self.assertEqual([c["id"] for c in milestones.list_cards()], ["thermal"])

    def test_an_oversized_visualization_is_refused(self):
        due = self.fire("thermal")[0]
        with self.assertRaises(ValueError):
            milestones.save_card(
                "thermal", {"title": "T", "html": "x" * (200_001)},
                due["mark"], due["made_because"], NOW)
        # And nothing was settled by the attempt.
        self.assertFalse(milestones.is_settled("thermal"))

    def test_an_unreadable_settled_index_reads_as_nothing_settled(self):
        milestones.CARDS_DIR.mkdir(parents=True, exist_ok=True)
        milestones.SETTLED_FILE.write_text("not json")
        self.assertEqual(milestones.settled(), {})


class TestAMilestoneIsNotACategory(MilestoneCase):
    def test_a_milestone_is_never_offered_as_a_category(self):
        """They share a shape and nothing else. A milestone that became a
        category would get a schedule, a refresh interval and a place on
        a dashboard nobody chose it for.

        `energy` names both a measurement and a shipped card, which is
        the one overlap and deliberately not a collision: two tables, two
        stores, two routes, two job ids. What must hold is that neither
        table answers for the other.
        """
        overlap = {c["id"] for c in categories.CATEGORIES} & set(
            milestones.MILESTONE_IDS)
        self.assertEqual(overlap, {"energy"})
        for name in milestones.MILESTONE_IDS:
            with self.subTest(name):
                entry = milestones.get(name)
                self.assertIsNotNone(entry)
                shipped = categories.get_category(name)
                if shipped is not None:
                    # Same word, different thing — and the two tables say
                    # so, rather than one being reachable through the
                    # other.
                    self.assertNotEqual(entry["title"], shipped["title"])
                    self.assertNotIn("focus", entry)

    def test_a_milestone_card_never_appears_among_the_insights(self):
        server = importlib.import_module("server")
        tmp = tempfile.TemporaryDirectory()
        old_dir = server.INSIGHTS_DIR
        try:
            server.INSIGHTS_DIR = Path(tmp.name)
            due = self.fire("habits")[0]
            milestones.save_card(
                "habits", {"title": "T", "summary": "S", "html": "<p>x</p>"},
                due["mark"], due["made_because"], NOW)
            self.assertEqual(server.load_insights(), [])
            # And it landed where it was meant to.
            self.assertTrue(milestones.card_path("habits").exists())
            self.assertFalse(
                (Path(tmp.name) / "habits.json").exists())
        finally:
            server.INSIGHTS_DIR = old_dir
            tmp.cleanup()


class TestTheRoutes(MilestoneCase):
    """The three doors, driven over a real router.

    A payload nothing has fetched over aiohttp is a payload the panel
    cannot build against — `test_house`'s rule, one tab over.
    """

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self._olds = {}
        for mod, attr, value in (
                (self.server, "INSIGHTS_DIR", Path(self.tmp.name) / "insights"),):
            self._olds[(mod, attr)] = getattr(mod, attr)
            setattr(mod, attr, value)
        os.makedirs(self.server.INSIGHTS_DIR, exist_ok=True)

    def tearDown(self):
        for (mod, attr), value in self._olds.items():
            setattr(mod, attr, value)
        super().tearDown()

    def run_client(self, body):
        async def go():
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()
        return asyncio.run(go())

    def test_the_list_says_what_is_still_being_waited_for(self):
        due = self.fire("rhythm")[0]
        milestones.save_card(
            "rhythm", {"title": "Up at seven", "summary": "S",
                       "html": "<p>x</p>"},
            due["mark"], due["made_because"], NOW)

        async def body(client):
            resp = await client.get("/api/knowledge/cards")
            self.assertEqual(resp.status, 200)
            return await resp.json()

        payload = self.run_client(body)
        self.assertEqual([c["id"] for c in payload["cards"]], ["rhythm"])
        pending = {p["id"] for p in payload["pending"]}
        self.assertNotIn("rhythm", pending)
        self.assertIn("energy", pending)

    def test_one_card_by_id_and_a_404_for_anything_else(self):
        due = self.fire("energy")[0]
        milestones.save_card(
            "energy", {"title": "A week to compare", "summary": "S",
                       "html": "<p>x</p>"},
            due["mark"], due["made_because"], NOW)

        async def body(client):
            ok = await client.get("/api/knowledge/card/energy")
            missing = await client.get("/api/knowledge/card/nonsense")
            never = await client.get("/api/knowledge/card/thermal")
            return (ok.status, await ok.json(), missing.status, never.status)

        status, card, missing, never = self.run_client(body)
        self.assertEqual(status, 200)
        self.assertEqual(card["title"], "A week to compare")
        self.assertEqual(missing, 404)
        # A real milestone with no card yet is also a 404: the id exists
        # and the card does not, and inventing an empty one would be a
        # card about a measurement nobody has made.
        self.assertEqual(never, 404)

    def test_refresh_refuses_when_the_measurement_has_no_answer(self):
        """A 409 rather than a card written from numbers that have gone."""
        calls = []
        old_snapshot = self.server._house_snapshot
        old_payloads = self.server._milestone_payloads
        old_auth = self.server.engine.get_auth
        try:
            async def snapshot(now=None):
                calls.append("snapshot")
                return clean_snapshot()

            self.server._house_snapshot = snapshot
            self.server._milestone_payloads = lambda: {}
            self.server.engine.get_auth = lambda: {"type": "oauth"}

            async def body(client):
                resp = await client.post("/api/knowledge/card/rhythm/refresh")
                return resp.status, await resp.json()

            status, payload = self.run_client(body)
        finally:
            self.server._house_snapshot = old_snapshot
            self.server._milestone_payloads = old_payloads
            self.server.engine.get_auth = old_auth
        self.assertEqual(status, 409)
        self.assertIn("does not have an answer", payload["error"])
        self.assertEqual(calls, ["snapshot"])

    def test_refresh_re_arms_and_queues(self):
        snap, payloads = rhythm_house()
        due = milestones.due(snap, payloads, NOW)[0]
        milestones.save_card(
            "rhythm", {"title": "T", "summary": "S", "html": "<p>x</p>"},
            due["mark"], due["made_because"], NOW)
        old_snapshot = self.server._house_snapshot
        old_payloads = self.server._milestone_payloads
        old_auth = self.server.engine.get_auth
        try:
            async def snapshot(now=None):
                return snap

            self.server._house_snapshot = snapshot
            self.server._milestone_payloads = lambda: payloads
            self.server.engine.get_auth = lambda: {"type": "oauth"}
            self.server.JOBS.clear()

            async def body(client):
                resp = await client.post("/api/knowledge/card/rhythm/refresh")
                return resp.status, await resp.json()

            status, payload = self.run_client(body)
        finally:
            self.server._house_snapshot = old_snapshot
            self.server._milestone_payloads = old_payloads
            self.server.engine.get_auth = old_auth
        self.assertEqual(status, 200)
        self.assertTrue(payload["queued"])
        self.assertFalse(milestones.is_settled("rhythm"))
        job = self.server.JOBS["milestone-rhythm"]
        self.assertEqual(job["kind"], "milestone")
        self.assertEqual(job["because"], "you asked for it again")
        self.assertIn("07:10", job["prompt"])
        self.server.JOBS.clear()


class TestTheStoreOnDisk(MilestoneCase):
    def test_a_card_is_json_on_disk_under_its_own_id(self):
        due = self.fire("closures")[0]
        milestones.save_card(
            "closures", {"title": "Doors", "summary": "S", "html": "<p>x</p>"},
            due["mark"], due["made_because"], NOW)
        raw = json.loads(milestones.card_path("closures").read_text())
        self.assertEqual(raw["id"], "closures")
        self.assertEqual(raw["store"], "closures")
        self.assertEqual(raw["made_at"], int(NOW))


if __name__ == "__main__":
    unittest.main()
