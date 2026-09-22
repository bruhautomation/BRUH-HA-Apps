#!/usr/bin/env python3
"""Ideas — proposed cards, and the rules that keep the page worth opening.

The store is driven through its real writers into a real file. What is
asserted is the four claims the page rests on:

  * an answered idea is never offered again, whichever way it was
    answered — a dismissed idea coming back next week is how a page stops
    being read, and an accepted one coming back is brAIn offering to
    build what it already built.
  * a card this home already has is not an idea, however it came to have
    one. The fingerprint set is seeded from the live categories, because
    a card made through the ask bar or by hand never told this module
    anything.
  * accepting creates the category BEFORE it marks the row, so an idea
    cannot vanish into a card that was never made.
  * a pass that proposed nothing is an answer and not a failure, and
    `last_error` is what tells them apart.
"""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import ideas  # noqa: E402
import user_categories  # noqa: E402


def proposal(title, **over):
    return {"title": title, "icon": "🌡", "focus": f"Analyse {title}.",
            "why": "Because this house has three of them.",
            "question": f"How is {title} doing?", **over}


class IdeasCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (ideas.STORE, user_categories.USER_CATS_FILE)
        ideas.STORE = str(root / "ideas.json")
        user_categories.USER_CATS_FILE = str(root / "user_categories.json")

    def tearDown(self):
        ideas.STORE, user_categories.USER_CATS_FILE = self._old
        self.tmp.cleanup()


class TestFilingAnIdea(IdeasCase):
    def test_a_proposal_becomes_an_open_idea(self):
        out = ideas.add_many([proposal("Freezer drift")], run_id="sess-a")
        self.assertEqual(len(out["filed"]), 1)
        [row] = ideas.open_ideas()
        self.assertEqual(row["title"], "Freezer drift")
        self.assertEqual(row["run_id"], "sess-a")
        self.assertEqual(row["status"], "open")
        self.assertTrue(row["why"])
        self.assertTrue(row["question"])

    def test_an_idea_with_no_focus_is_not_an_idea(self):
        """A title with no focus is a card that cannot be generated."""
        out = ideas.add_many([proposal("Nameless", focus="")])
        self.assertEqual(out["filed"], [])
        self.assertEqual(ideas.open_ideas(), [])

    def test_two_ids_from_one_batch_never_collide(self):
        """One pass files eight in a loop, well inside a millisecond."""
        out = ideas.add_many([proposal(f"Idea {i}") for i in range(8)])
        ids = [e["id"] for e in out["filed"]]
        self.assertEqual(len(ids), 8)
        self.assertEqual(len(set(ids)), 8)

    def test_the_cap_refuses_rather_than_making_room(self):
        """The room would be made by dropping an idea nobody has read."""
        for i in range(ideas.MAX_OPEN):
            ideas.add_many([proposal(f"Filler {i}")])
        self.assertEqual(len(ideas.open_ideas()), ideas.MAX_OPEN)
        out = ideas.add_many([proposal("One too many")])
        self.assertEqual(out["filed"], [])
        self.assertEqual(out["full"], 1)
        self.assertEqual(len(ideas.open_ideas()), ideas.MAX_OPEN)
        self.assertNotIn("One too many",
                         [e["title"] for e in ideas.open_ideas()])

    def test_one_batch_cannot_propose_the_same_card_twice(self):
        out = ideas.add_many([proposal("Freezer drift"),
                              proposal("freezer  DRIFT")])
        self.assertEqual(len(out["filed"]), 1)
        self.assertEqual(out["duplicate"], 1)


class TestAnAnsweredIdeaIsNeverOfferedAgain(IdeasCase):
    def test_a_dismissed_idea_does_not_come_back(self):
        ideas.add_many([proposal("Freezer drift")])
        [row] = ideas.open_ideas()
        self.assertTrue(ideas.dismiss(row["id"]))
        self.assertEqual(ideas.open_ideas(), [])
        out = ideas.add_many([proposal("Freezer drift")])
        self.assertEqual(out["filed"], [])
        self.assertEqual(out["answered"], 1)

    def test_nor_does_a_reworded_one(self):
        """The fingerprint is the title, normalised — a second pass
        writes its own wording of the same idea."""
        ideas.add_many([proposal("Freezer drift")])
        ideas.dismiss(ideas.open_ideas()[0]["id"])
        out = ideas.add_many([proposal("  freezer   DRIFT!  ")])
        self.assertEqual(out["answered"], 1)

    def test_an_accepted_idea_is_not_proposed_again_either(self):
        ideas.add_many([proposal("Freezer drift")])
        created = ideas.accept(ideas.open_ideas()[0]["id"])
        self.assertIsNotNone(created)
        out = ideas.add_many([proposal("Freezer drift")])
        self.assertEqual(out["filed"], [])

    def test_answering_twice_is_refused_rather_than_doubled(self):
        ideas.add_many([proposal("Freezer drift")])
        row_id = ideas.open_ideas()[0]["id"]
        self.assertTrue(ideas.dismiss(row_id))
        self.assertFalse(ideas.dismiss(row_id))
        self.assertIsNone(ideas.accept(row_id))


class TestACardThisHomeHasIsNotAnIdea(IdeasCase):
    def test_an_existing_category_blocks_the_proposal(self):
        """However the card came to exist — this module watched none of
        them being made, so the set is read live."""
        user_categories.create({"title": "Freezer drift", "icon": "🌡",
                                "focus": "Watch the freezers."})
        out = ideas.add_many([proposal("Freezer drift")])
        self.assertEqual(out["filed"], [])
        self.assertEqual(out["duplicate"], 1)

    def test_known_keys_spans_both_sources(self):
        user_categories.create({"title": "Energy split", "icon": "⚡",
                                "focus": "Split the meters."})
        ideas.add_many([proposal("Freezer drift")])
        ideas.dismiss(ideas.open_ideas()[0]["id"])
        keys = ideas.known_keys()
        self.assertIn("energy split", keys)
        self.assertIn("freezer drift", keys)


class TestAccepting(IdeasCase):
    def test_accepting_creates_the_card_and_marks_the_row(self):
        ideas.add_many([proposal("Freezer drift")])
        row = ideas.open_ideas()[0]
        created = ideas.accept(row["id"])
        self.assertIsNotNone(created)
        titles = [c["title"] for c in user_categories.load()]
        self.assertIn("Freezer drift", titles)
        again = ideas.get(row["id"])
        self.assertEqual(again["status"], "accepted")
        self.assertEqual(again["category_id"], created["id"])
        self.assertEqual(ideas.open_ideas(), [])

    def test_the_focus_is_what_reaches_the_card(self):
        """The focus is the card's standing prompt. An idea whose focus
        did not travel is a card that analyses nothing."""
        ideas.add_many([proposal("Freezer drift",
                                 focus="Compare each freezer's own month.")])
        created = ideas.accept(ideas.open_ideas()[0]["id"])
        self.assertEqual(created["focus"],
                         "Compare each freezer's own month.")

    def test_a_card_that_could_not_be_created_leaves_the_idea_open(self):
        """The one outcome with no way back is an idea that vanished into
        a card nobody made, so the row is marked only after the create."""
        ideas.add_many([proposal("Freezer drift")])
        row = ideas.open_ideas()[0]
        real = user_categories.create

        def boom(fields):
            raise ValueError("no room")

        user_categories.create = boom
        try:
            self.assertIsNone(ideas.accept(row["id"]))
        finally:
            user_categories.create = real
        self.assertEqual(ideas.get(row["id"])["status"], "open")
        self.assertEqual(len(ideas.open_ideas()), 1)


class TestNothingNewIsAnAnswer(IdeasCase):
    def test_a_quiet_pass_is_not_an_error(self):
        ideas.record_run(0)
        state = ideas.state()
        self.assertEqual(state["last_error"], "")
        self.assertEqual(state["last_count"], 0)
        self.assertEqual(state["runs"], 1)
        self.assertTrue(state["last_run"])

    def test_a_failed_pass_says_so(self):
        ideas.record_run(0, error="the reply did not parse")
        self.assertIn("did not parse", ideas.state()["last_error"])

    def test_the_stamp_is_written_even_when_the_pass_failed(self):
        """Otherwise the weekly schedule re-runs it on every tick."""
        self.assertTrue(ideas.due())
        ideas.record_run(0, error="it broke")
        self.assertFalse(ideas.due())


class TestTheWeeklyTopUp(IdeasCase):
    def test_a_house_that_has_never_looked_is_due(self):
        self.assertTrue(ideas.due())

    def test_and_is_not_due_again_until_the_week_is_up(self):
        ideas.record_run(3, now=1000.0)
        self.assertFalse(ideas.due(now=1000.0 + 6 * 86400))
        self.assertTrue(ideas.due(now=1000.0 + 8 * 86400))


class TestTheContract(IdeasCase):
    def test_a_reply_that_is_not_json_raises(self):
        """The caller has to tell a failed run from a quiet one."""
        with self.assertRaises(ValueError):
            ideas.parse("I could not think of anything, sorry!")

    def test_a_reply_wrapped_in_a_fence_still_parses(self):
        out = ideas.parse('```json\n{"ideas": [], "nothing_new": true, '
                          '"note": "well covered"}\n```')
        self.assertTrue(out["nothing_new"])
        self.assertEqual(out["note"], "well covered")

    def test_an_empty_list_reads_as_nothing_new_whatever_the_flag_says(self):
        out = ideas.parse('{"ideas": [], "nothing_new": false}')
        self.assertTrue(out["nothing_new"])

    def test_an_idea_missing_its_focus_is_dropped_not_kept_blank(self):
        out = ideas.parse(json.dumps({
            "ideas": [{"title": "Fine", "focus": "Do a thing."},
                      {"title": "Broken"}]}))
        self.assertEqual([i["title"] for i in out["ideas"]], ["Fine"])

    def test_the_cap_is_written_into_the_prompt_once(self):
        text = ideas.system_prompt(5)
        self.assertIn("at most 5", text)
        self.assertNotIn("%(cap)d", text)

    def test_the_prompt_names_the_cards_this_home_already_has(self):
        """Without it the run proposes them again, every week."""
        text = ideas.build_prompt("", None, ["Energy split", "Freezer drift"])
        self.assertIn("Energy split", text)
        self.assertIn("Freezer drift", text)

    def test_and_says_so_plainly_when_there_are_none(self):
        text = ideas.build_prompt("", None, [])
        self.assertIn("none yet", text)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# The routes
# ---------------------------------------------------------------------------

class TestTheRoutes(IdeasCase):
    """Driven against the real app, because a handler that answers
    correctly while nothing routes to it is a page that cannot load."""

    def setUp(self):
        super().setUp()
        import server  # noqa: PLC0415 — needs aiohttp, which the store does not
        self.server = server
        self.app = server.make_app()
        # A pass in flight is module state and outlives one test.
        server.IDEAS_STATE.update(
            {"running": False, "starting": False, "started_at": 0.0})

    def _client(self):
        from aiohttp.test_utils import TestClient, TestServer  # noqa: PLC0415
        return TestClient(TestServer(self.app))

    def _run(self, fn):
        async def go():
            client = self._client()
            await client.start_server()
            try:
                return await fn(client)
            finally:
                await client.close()
        return asyncio.new_event_loop().run_until_complete(go())

    def test_the_page_can_be_fetched(self):
        ideas.add_many([proposal("Freezer drift")])

        async def go(client):
            res = await client.get("/api/ideas")
            self.assertEqual(res.status, 200)
            return await res.json()

        body = self._run(go)
        self.assertEqual(len(body["ideas"]), 1)
        self.assertFalse(body["running"])
        self.assertIn("last_run", body)

    def test_accepting_over_a_route_makes_the_card(self):
        ideas.add_many([proposal("Freezer drift")])
        row = ideas.open_ideas()[0]

        async def go(client):
            res = await client.post(f"/api/idea/{row['id']}/accept")
            self.assertEqual(res.status, 200)
            return await res.json()

        body = self._run(go)
        self.assertEqual(body["created"]["title"], "Freezer drift")
        self.assertEqual(body["ideas"], [])
        self.assertIn("Freezer drift",
                      [c["title"] for c in user_categories.load()])

    def test_dismissing_over_a_route_takes_it_off(self):
        ideas.add_many([proposal("Freezer drift")])
        row = ideas.open_ideas()[0]

        async def go(client):
            res = await client.post(f"/api/idea/{row['id']}/dismiss")
            self.assertEqual(res.status, 200)
            return await res.json()

        self.assertEqual(self._run(go)["ideas"], [])

    def test_answering_a_row_that_is_gone_is_a_409_and_not_a_500(self):
        async def go(client):
            res = await client.post("/api/idea/123456/dismiss")
            return res.status

        self.assertEqual(self._run(go), 409)

    def test_a_second_press_while_one_is_running_is_refused(self):
        """`_start_ideas` flips its flag synchronously, so two presses in
        one tick cannot both pass the guard — `start_auth_check`'s rule.

        Driven inside a loop with both presses in ONE tick, because the
        claim it is about is the one `create_task` has not run yet: a
        guard reading a flag its own task sets would pass twice.
        """
        seen = []

        async def go():
            seen.append(self.server._start_ideas())
            seen.append(self.server._start_ideas())

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(go())
        finally:
            for task in asyncio.all_tasks(loop):
                task.cancel()
            loop.close()
            self.server.IDEAS_STATE.update(
                {"running": False, "starting": False})
        self.assertEqual(seen, [True, False])

    def test_asking_without_a_credential_says_so(self):
        real = self.server.engine.get_auth
        self.server.engine.get_auth = lambda: None

        async def go(client):
            res = await client.post("/api/ideas/run")
            return res.status

        try:
            self.assertEqual(self._run(go), 400)
        finally:
            self.server.engine.get_auth = real
