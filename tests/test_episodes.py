#!/usr/bin/env python3
"""What HAPPENED, rather than every time a value changed.

The Activity tab was Home Assistant's own logbook with a cause column
added — one row per state change, newest first — which on a real house is
hundreds of rows an hour of a sensor reporting a number, and which was
reported as having "basically zero utility in its current form".

What is pinned here is the grouping that replaces it and the four ways it
can silently go wrong: a run split into rows, a burst listed one trip at a
time, a door filed under Motion, and a list that drops nine tenths of its
input without saying so.

Plus the two claims this makes about a house rather than about a row —
when it was empty, and which episode a person undid — both of which are
only safe because of what they refuse to say.
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
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import episodes  # noqa: E402

NOW = 1_700_000_000.0


def act(off: float, entity_id: str, state: str, cause: str = "unattributed",
        by_name: str = "") -> dict:
    return {"ts": NOW + off, "entity_id": entity_id,
            "name": entity_id.split(".", 1)[1].replace("_", " ").title(),
            "state": state, "cause": cause, "by_name": by_name}


def only(grouped: dict, entity_id: str) -> list[dict]:
    return [e for e in grouped["episodes"] if e["entity_id"] == entity_id]


class TestAReadingIsNotAnEvent(unittest.TestCase):
    """The single biggest thing that turns a logbook into a list of what
    happened — and the one that must not be silent."""

    def test_sensor_readings_are_dropped_and_counted(self):
        rows = [act(i, "sensor.lounge_temp", str(20 + i * 0.1))
                for i in range(200)]
        rows.append(act(5, "light.hall", "on"))
        g = episodes.group(rows, {}, NOW + 300)
        self.assertEqual(g["dropped"], 200)
        self.assertEqual([e["entity_id"] for e in g["episodes"]],
                         ["light.hall"])

    def test_a_stateless_press_is_noise_wearing_an_events_clothes(self):
        """A button's "state" in the logbook is a timestamp, so a row
        reading `Doorbell → 2026-09-15T20:14:03` says nothing. The press
        reaches this tab through whatever it changed."""
        g = episodes.group([act(0, "button.doorbell", "2026-09-15T20:14:03")],
                           {}, NOW)
        self.assertEqual(g["episodes"], [])
        self.assertEqual(g["dropped"], 1)

    def test_the_domains_that_are_readings_are_a_closed_list(self):
        for domain in ("sensor", "weather", "update", "event", "input_number"):
            self.assertTrue(episodes.is_reading(f"{domain}.x"), domain)
        for domain in ("light", "media_player", "person", "climate", "lock",
                       "binary_sensor", "cover", "camera"):
            self.assertFalse(episodes.is_reading(f"{domain}.x"), domain)


class TestWhatOneEpisodeIs(unittest.TestCase):
    def test_a_programme_is_one_row_and_the_off_is_what_ended_it(self):
        """The rule a first cut of this got wrong, demonstrated before it is
        asserted: a gap rule ALONE files the `off` three hours later as a
        fresh episode of *off*, which renders as "Lounge TV, off, 0 seconds"
        under a heading about what played."""
        rows = [act(0, "media_player.lounge", "playing"),
                act(600, "media_player.lounge", "paused"),
                act(900, "media_player.lounge", "playing"),
                act(10800, "media_player.lounge", "off")]
        gap = episodes._BY_ID["media"]["gap_s"]
        # The old recipe, run on the same fixture.
        naive, last = 1, rows[0]["ts"]
        for row in rows[1:]:
            if row["ts"] - last > gap:
                naive += 1
            last = row["ts"]
        self.assertEqual(naive, 2, "the gap-only rule, demonstrated")

        [ep] = only(episodes.group(rows, {}, NOW + 11000), "media_player.lounge")
        self.assertEqual(ep["count"], 4)
        self.assertEqual((ep["first"], ep["last"]), ("playing", "off"))
        self.assertFalse(ep["open"])
        self.assertAlmostEqual(ep["duration_s"], 10800, delta=1)

    def test_a_gap_still_ends_an_episode_that_had_already_stopped(self):
        """Two trips through a door, an hour apart, are two trips."""
        rows = [act(0, "binary_sensor.back", "on"),
                act(30, "binary_sensor.back", "off"),
                act(3600, "binary_sensor.back", "on"),
                act(3630, "binary_sensor.back", "off")]
        eps = only(episodes.group(rows, {"binary_sensor.back": "door"},
                                  NOW + 4000), "binary_sensor.back")
        self.assertEqual(len(eps), 2)
        for ep in eps:
            self.assertEqual(ep["count"], 2)
            self.assertAlmostEqual(ep["duration_s"], 30, delta=1)

    def test_a_burst_is_one_row_that_says_how_many(self):
        rows = [act(i * 60, "binary_sensor.hall", "on" if i % 2 == 0 else "off")
                for i in range(9)]
        [ep] = only(episodes.group(rows, {"binary_sensor.hall": "motion"},
                                   NOW + 1000), "binary_sensor.hall")
        self.assertEqual(ep["count"], 9)

    def test_an_unfinished_episode_says_how_long_it_has_covered(self):
        """One number with one meaning in both states it can be in — a
        light switched on at six with nothing since is not "0 s"."""
        [ep] = only(episodes.group([act(0, "light.kitchen", "on")], {},
                                   NOW + 7200), "light.kitchen")
        self.assertTrue(ep["open"])
        self.assertAlmostEqual(ep["duration_s"], 7200, delta=1)

    def test_the_cause_is_the_commonest_one_that_claims_it(self):
        """A run a person started and an automation continued is a
        person's; reading the FIRST would make an automation's tidy-up its
        author."""
        rows = [act(0, "light.hall", "on", "person", "Ben"),
                act(60, "light.hall", "on", "person", "Ben"),
                act(120, "light.hall", "off", "automation", "Away lights")]
        [ep] = only(episodes.group(rows, {}, NOW + 200), "light.hall")
        self.assertEqual(ep["cause"], "person")
        self.assertEqual(ep["by_name"], "Ben")

    def test_a_run_nothing_claims_says_so(self):
        [ep] = only(episodes.group([act(0, "light.hall", "on")], {}, NOW),
                    "light.hall")
        self.assertEqual(ep["cause"], "unattributed")

    def test_the_states_inside_are_newest_first_and_capped(self):
        rows = [act(i, "light.hall", "on" if i % 2 else "off")
                for i in range(40)]
        [ep] = only(episodes.group(rows, {}, NOW + 100), "light.hall")
        self.assertEqual(len(ep["states"]), episodes.MAX_STATES)
        self.assertGreater(ep["states"][0]["ts"], ep["states"][-1]["ts"])

    def test_grouping_does_not_mutate_what_it_is_handed(self):
        """The same list feeds `find_overrides` and the counts in the same
        request, and a grouping that edited in place would be marking rows
        those then read back."""
        rows = [act(0, "light.hall", "on")]
        before = json.dumps(rows, sort_keys=True)
        episodes.group(rows, {}, NOW)
        self.assertEqual(json.dumps(rows, sort_keys=True), before)


class TestWhichSectionAThingIsIn(unittest.TestCase):
    """The load-bearing one. A `binary_sensor` with no device class is a
    door, a motion sensor, a leak detector or a plug's own power flag, and
    naming one is a guess whose cost is the front door under Motion."""

    def test_the_device_class_is_what_separates_them(self):
        self.assertEqual(
            episodes.subject_for("binary_sensor.back", "door"), "openings")
        self.assertEqual(
            episodes.subject_for("binary_sensor.hall", "motion"), "motion")
        self.assertEqual(
            episodes.subject_for("binary_sensor.leak", "moisture"), "security")

    def test_an_unclassed_binary_sensor_is_not_guessed_into_a_section(self):
        self.assertEqual(episodes.subject_for("binary_sensor.front_door", ""),
                         "other",
                         "a name is not a device class, and the cost of "
                         "reading one as the other is the front door filed "
                         "under Motion")

    def test_an_unclassed_cover_is_still_a_thing_that_opens(self):
        """Which is what the DOMAIN means — the one place a missing class
        may fall through, because `cover` has already answered."""
        self.assertEqual(episodes.subject_for("cover.garage", ""), "openings")

    def test_the_domains_that_answer_on_their_own(self):
        for entity_id, want in (
            ("person.ben", "people"), ("device_tracker.phone", "people"),
            ("climate.hall", "climate"), ("media_player.lounge", "media"),
            ("lock.front", "security"), ("alarm_control_panel.house", "security"),
            ("camera.drive", "motion"), ("light.kitchen", "lights"),
            ("switch.kettle", "lights"), ("script.leaving", "other"),
        ):
            self.assertEqual(episodes.subject_for(entity_id, ""), want, entity_id)

    def test_every_subject_has_a_label_a_blurb_a_gap_and_what_it_reads(self):
        for spec in episodes.SUBJECTS:
            for key in ("id", "label", "blurb", "gap_s", "reads"):
                self.assertTrue(spec.get(key) is not None, f"{spec} {key}")
            self.assertIn(spec["reads"], ("span", "count", "moment"))
            self.assertGreater(spec["gap_s"], 0)

    def test_every_subject_a_row_can_land_in_has_a_section(self):
        """`group` reads the gap off the table by id, so a subject the
        matcher can answer with and the table does not hold is a KeyError
        on somebody's house rather than a missing row."""
        for domain in ("person", "climate", "media_player", "lock", "camera",
                       "cover", "valve", "binary_sensor", "light", "switch",
                       "scene", "script", "vacuum", "siren", "humidifier"):
            self.assertIn(episodes.subject_for(f"{domain}.x", ""),
                          episodes.SUBJECT_IDS, domain)


class TestTheSections(unittest.TestCase):
    def test_a_section_with_nothing_in_it_is_not_rendered(self):
        g = episodes.group([act(0, "light.hall", "on")], {}, NOW)
        ids = [s["id"] for s in episodes.sections(g)]
        self.assertEqual(ids, ["lights"])

    def test_the_order_is_the_tables_and_not_the_houses(self):
        rows = [act(0, "light.hall", "on"), act(1, "person.ben", "home"),
                act(2, "lock.front", "unlocked")]
        ids = [s["id"] for s in episodes.sections(episodes.group(rows, {}, NOW))]
        self.assertEqual(ids, ["security", "people", "lights"])

    def test_a_capped_section_says_what_it_is_not_showing(self):
        rows = [act(i * 10_000, f"light.lamp{i}", "on")
                for i in range(episodes.MAX_ROWS + 9)]
        [sec] = episodes.sections(episodes.group(rows, {}, NOW + 10_000_000))
        self.assertEqual(len(sec["episodes"]), episodes.MAX_ROWS)
        self.assertEqual(sec["total"], episodes.MAX_ROWS + 9)

    def test_a_section_counts_the_changes_under_it(self):
        rows = [act(0, "light.hall", "on"), act(60, "light.hall", "off"),
                act(120, "light.kitchen", "on")]
        [sec] = episodes.sections(episodes.group(rows, {}, NOW + 200))
        self.assertEqual(sec["changes"], 3)
        self.assertEqual(sec["total"], 2)


class TestWhenTheHouseWasEmpty(unittest.TestCase):
    """The one overlay worth having for free — and it is only safe because
    of what it refuses to say."""

    def span(self, rows, now=NOW + 100_000):
        return episodes.away_spans(episodes.group(rows, {}, now), now)

    def test_a_departure_and_an_arrival_bound_a_span(self):
        rows = [act(0, "person.ben", "not_home"), act(30_000, "person.ben", "home")]
        [span] = self.span(rows)
        self.assertEqual(span["start"], NOW)
        self.assertEqual(span["end"], NOW + 30_000)

    def test_a_person_never_seen_is_not_a_person_who_was_out(self):
        """The logbook carries CHANGES, so the state before the first one is
        unknown — and reading that silence as "away" would report an empty
        house on every window in which nobody moved."""
        self.assertEqual(self.span([act(0, "light.hall", "on")]), [])

    def test_the_house_is_not_empty_while_anybody_seen_is_in(self):
        rows = [act(0, "person.ben", "not_home"),
                act(10, "person.amy", "home"),
                act(30_000, "person.ben", "home")]
        self.assertEqual(self.span(rows), [])

    def test_a_span_still_running_says_so(self):
        rows = [act(0, "person.ben", "home"), act(600, "person.ben", "not_home"),
                act(900, "light.hall", "on")]
        [span] = self.span(rows)
        self.assertTrue(span.get("ongoing"))

    def test_a_phone_is_not_a_person(self):
        """A `device_tracker` on a charger in the hall is not somebody being
        in, so the claim is made off `person.*` and nothing else."""
        rows = [act(0, "device_tracker.phone", "not_home"),
                act(30_000, "device_tracker.phone", "home")]
        self.assertEqual(self.span(rows), [])

    def test_within_answers_about_an_instant(self):
        spans = [{"start": 10.0, "end": 20.0}]
        self.assertTrue(episodes.within(spans, 15.0))
        self.assertFalse(episodes.within(spans, 25.0))
        self.assertFalse(episodes.within([], 15.0))


class TestTheRowAPersonUndid(unittest.TestCase):
    def test_the_mark_lands_on_the_episode_that_contains_it(self):
        rows = [act(0, "light.kitchen", "on", "automation", "Evening lights"),
                act(60, "light.kitchen", "off", "person", "Ben"),
                act(20_000, "light.hall", "on")]
        g = episodes.group(rows, {}, NOW + 30_000)
        n = episodes.mark_overrides(g, [{
            "ts": NOW + 60, "entity_id": "light.kitchen",
            "by_name": "Evening lights"}])
        self.assertEqual(n, 1)
        [kitchen] = only(g, "light.kitchen")
        self.assertEqual(kitchen["undid"], "Evening lights")
        self.assertNotIn("undid", only(g, "light.hall")[0])

    def test_an_override_outside_every_episode_marks_nothing(self):
        g = episodes.group([act(0, "light.kitchen", "on")], {}, NOW)
        self.assertEqual(episodes.mark_overrides(g, [{
            "ts": NOW + 99_999, "entity_id": "light.kitchen"}]), 0)


class TestTheParagraph(unittest.TestCase):
    """The one part that spends, and the gathering that happens before it."""

    def payload(self):
        rows = [act(0, "media_player.lounge", "playing"),
                act(10_800, "media_player.lounge", "off"),
                act(0, "person.ben", "not_home"),
                act(9_000, "person.ben", "home")]
        g = episodes.group(rows, {}, NOW + 11_000)
        return {"start": NOW, "end": NOW + 11_000,
                "sections": episodes.sections(g),
                "away": episodes.away_spans(g), "dropped": 1842}

    def test_the_prompt_is_built_from_what_is_on_the_screen(self):
        """A model handed the four hundred underlying rows would write
        about the ones the tab deliberately does not show."""
        text = episodes.summary_prompt(self.payload(), "Europe/London")
        self.assertIn("MEDIA", text)
        self.assertIn("Lounge", text)
        self.assertIn("Europe/London", text)
        self.assertIn("1842", text)
        self.assertIn("NOBODY HOME", text)

    def test_the_prompt_is_capped_before_anything_is_spawned(self):
        rows = [act(i * 10_000, f"light.lamp{i}", "on") for i in range(200)]
        g = episodes.group(rows, {}, NOW + 3_000_000)
        text = episodes.summary_prompt({
            "start": NOW, "end": NOW + 3_000_000,
            "sections": episodes.sections(g), "away": [], "dropped": 0})
        self.assertLessEqual(text.count("\n- "), episodes.SUMMARY_MAX_ROWS)

    def test_the_contract_forbids_writing_about_the_person(self):
        for phrase in ("never about the person", "about the house"):
            self.assertIn(phrase, episodes.SUMMARY_SYSTEM)
        self.assertIn(str(episodes.SUMMARY_MAX_WORDS), episodes.SUMMARY_SYSTEM)

    def test_nothing_in_this_module_asks_a_model(self):
        """`curiosity.py`'s rule: a model call made to decide whether to
        make a model call is the one design that cannot pay, and this runs
        on every visit to the tab."""
        src = (PANEL_DIR / "episodes.py").read_text()
        for forbidden in ("run_analyst", "run_claude", "subprocess",
                          "import engine", "aiohttp"):
            self.assertNotIn(forbidden, src, forbidden)


class TestTheTab(unittest.TestCase):
    """The route, over a real client, with the logbook stubbed."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        import engine
        import settings_store
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._olds = (settings_store.SETTINGS_FILE, engine.run_claude,
                      engine.run_analyst, engine.get_auth,
                      self.server._activity, self.server._device_classes,
                      self.server.INSIGHTS_DIR, self.server.CARD_TOKEN_FILE,
                      self.server.WWW_CARD_DIR)
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        settings_store.save({"onboarded": True, "auto_enabled": True})
        self.server.INSIGHTS_DIR = base
        self.server.CARD_TOKEN_FILE = base / "secrets" / "card_token"
        self.server.WWW_CARD_DIR = base / "www"
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": "OK", "error": "", "meta": {}}
        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.rows = [
            act(0, "media_player.lounge", "playing"),
            act(10_800, "media_player.lounge", "off"),
            act(100, "binary_sensor.back", "on"),
            act(130, "binary_sensor.back", "off"),
        ] + [act(i, "sensor.temp", str(i)) for i in range(120)]

        async def activity(start, end, entity_id=""):
            return {"available": True, "error": "", "start": NOW,
                    "end": NOW + 11_000, "actions": list(self.rows),
                    "capped": False, "overrides": [], "conflicts": [],
                    "moves": {},
                    "counts": {c: 0 for c in __import__("actions").CAUSES}}

        async def classes():
            return {"binary_sensor.back": "door"}

        self.server._activity = activity
        self.server._device_classes = classes
        self.runs = []

        def run_analyst(prompt, system, *a, **k):
            self.runs.append(prompt)
            return {"ok": True, "error": "",
                    "text": "A quiet evening. The television ran for three "
                            "hours and the back door was opened once.",
                    "meta": {"session_id": "sess-1"}}
        engine.run_analyst = run_analyst
        self.server._ACTIVITY_SUMMARIES.clear()

    def tearDown(self):
        import engine
        import settings_store
        (settings_store.SETTINGS_FILE, engine.run_claude, engine.run_analyst,
         engine.get_auth, self.server._activity, self.server._device_classes,
         self.server.INSIGHTS_DIR, self.server.CARD_TOKEN_FILE,
         self.server.WWW_CARD_DIR) = self._olds
        self.server._ACTIVITY_SUMMARIES.clear()
        self.tmp.cleanup()

    def drive(self, body):
        async def run():
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(self.server.make_app()))
            await client.start_server()
            try:
                return await body(client)
            finally:
                await client.close()
        return asyncio.run(run())

    def test_the_tab_answers_with_what_happened_and_not_with_rows(self):
        async def body(client):
            res = await client.get("/api/activity")
            self.assertEqual(res.status, 200)
            return await res.json()

        data = self.drive(body)
        self.assertNotIn("actions", data)
        ids = [s["id"] for s in data["sections"]]
        self.assertEqual(ids, ["openings", "media"])
        self.assertEqual(data["dropped"], 120)
        self.assertEqual(data["episodes"], 2)
        [media] = [s for s in data["sections"] if s["id"] == "media"]
        self.assertEqual(media["episodes"][0]["count"], 2)
        self.assertEqual(media["reads"], "span")

    def test_a_logbook_that_could_not_be_read_says_so_and_shows_nothing(self):
        async def boom(start, end, entity_id=""):
            raise RuntimeError("no logbook")
        self.server._activity = boom

        async def body(client):
            return await (await client.get("/api/activity")).json()

        data = self.drive(body)
        self.assertFalse(data["available"])
        self.assertEqual(data["sections"], [])

    def test_the_paragraph_is_a_press_and_a_second_press_is_free(self):
        async def body(client):
            first = await client.post("/api/activity/summary")
            self.assertEqual(first.status, 200)
            one = await first.json()
            two = await (await client.post("/api/activity/summary")).json()
            return one, two

        one, two = self.drive(body)
        self.assertIn("three hours", one["summary"])
        self.assertFalse(one["cached"])
        self.assertTrue(two["cached"])
        self.assertEqual(len(self.runs), 1, "a second press must not spend")

    def test_asking_costs_nothing_when_nothing_happened(self):
        self.rows = [act(i, "sensor.temp", str(i)) for i in range(5)]

        async def body(client):
            return await client.post("/api/activity/summary")

        self.assertEqual(self.drive(body).status, 409)
        self.assertEqual(self.runs, [])

    def test_a_reply_too_short_to_be_an_answer_is_not_one(self):
        import engine
        engine.run_analyst = lambda *a, **k: {
            "ok": True, "error": "", "text": "Quiet.", "meta": {}}

        async def body(client):
            return await client.post("/api/activity/summary")

        self.assertEqual(self.drive(body).status, 502)

    def test_nothing_is_asked_without_a_credential(self):
        import engine
        engine.get_auth = lambda: None

        async def body(client):
            return await client.post("/api/activity/summary")

        self.assertEqual(self.drive(body).status, 409)
        self.assertEqual(self.runs, [])

    def test_a_triage_run_is_never_started_by_looking_at_the_tab(self):
        """Everything on this tab but the paragraph is arithmetic over one
        fetch, so opening it is free however often somebody does."""
        async def body(client):
            await client.get("/api/activity")
            await client.get("/api/activity")
            return True

        self.drive(body)
        self.assertEqual(self.runs, [])


class TestOneVocabulary(unittest.TestCase):
    """The words live here; the panel spells them, and a spelling that
    drifts is a section nobody can read."""

    @classmethod
    def setUpClass(cls):
        cls.js = (PANEL_DIR / "app.js").read_text()
        cls.css = (PANEL_DIR / "style.css").read_text()

    def test_the_panel_branches_on_every_reading_the_server_can_send(self):
        for reads in {s["reads"] for s in episodes.SUBJECTS}:
            self.assertIn(f'reads === "{reads}"', self.js + 'reads === "span"',
                          reads)

    def test_the_panel_renders_the_sections_the_server_sends(self):
        self.assertIn("function actSection(sec)", self.js)
        self.assertIn("sec.blurb", self.js)
        self.assertIn("sec.reads", self.js)

    def test_the_old_flat_list_is_gone_from_the_panel_and_the_stylesheet(self):
        """Hour headings over a flat stream of state changes were the tab,
        and leaving the renderer in place is how it comes back."""
        for gone in ("acthour", "actOverrides", "renderActOverrides"):
            self.assertNotIn(gone, self.js, gone)
            self.assertNotIn(gone, self.css, gone)

    def test_what_was_left_out_is_said_out_loud(self):
        self.assertIn("data.dropped", self.js)
        self.assertIn("actfoot", self.js)


if __name__ == "__main__":
    unittest.main()
