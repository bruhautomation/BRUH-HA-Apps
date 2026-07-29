#!/usr/bin/env python3
"""Tests for the three smaller 1.7.0 panel changes.

- **Card tags are editable.** The interesting property isn't that an edit
  saves; it's that it is stored as a DIFF. Storing the final list would
  freeze a card's tags forever, so a later run that discovers a battery
  problem could never add "batteries" again.
- **The ask bar has two verbs.** "learn about X" runs a study session
  instead of drawing a card, and must never be enqueued as one.
- **Memory can be consolidated on demand**, using the same script and the
  same checks the daily daemon uses.
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

import card_tags  # noqa: E402
import engine  # noqa: E402
import feedback_store  # noqa: E402
import findings_store  # noqa: E402
import hypotheses  # noqa: E402
import knowledge_store  # noqa: E402
import onboarding  # noqa: E402
import prompt_store  # noqa: E402
import settings_store  # noqa: E402
import user_categories  # noqa: E402


class TestCardTags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = card_tags.TAGS_FILE
        card_tags.TAGS_FILE = Path(self.tmp.name) / "card_tags.json"
        self.card = {"id": "energy", "category": "energy",
                     "tags": ["energy", "anomaly", "dryer"]}

    def tearDown(self):
        card_tags.TAGS_FILE = self._old
        self.tmp.cleanup()

    def test_base_tags_include_the_category(self):
        """The category is a tag like any other on the filter bar, so it has
        to be removable like any other."""
        self.assertEqual(card_tags.base_tags(self.card),
                         ["energy", "anomaly", "dryer"])
        self.assertEqual(
            card_tags.base_tags({"id": "custom-1", "category": "custom",
                                 "tags": ["heating"]}),
            ["asked", "heating"])

    def test_tags_are_normalized(self):
        messy = {"id": "x", "category": "", "tags": ["#Batteries ", "LEFT-ON", 42,
                                                    "batteries", ""]}
        self.assertEqual(card_tags.base_tags(messy), ["batteries", "left-on"])

    def test_no_edits_means_no_file_entry(self):
        card_tags.set_tags("energy", self.card, ["energy", "anomaly", "dryer"])
        self.assertEqual(card_tags.effective_tags(self.card),
                         ["energy", "anomaly", "dryer"])
        self.assertNotIn("energy", json.loads(
            card_tags.TAGS_FILE.read_text())["cards"])

    def test_removing_a_tag_sticks_across_regeneration(self):
        card_tags.set_tags("energy", self.card, ["energy", "dryer"])
        # a later run writes the same tags again — the removal must hold
        regenerated = {"id": "energy", "category": "energy",
                       "tags": ["energy", "anomaly", "dryer"]}
        self.assertEqual(card_tags.effective_tags(regenerated),
                         ["energy", "dryer"])

    def test_a_new_tag_from_a_later_run_still_appears(self):
        """This is why the store keeps a diff rather than a list. Freezing
        the tags would mean a run that finds a battery problem can never say
        so again."""
        card_tags.set_tags("energy", self.card, ["energy", "dryer"])
        later = {"id": "energy", "category": "energy",
                 "tags": ["energy", "anomaly", "dryer", "batteries"]}
        self.assertEqual(card_tags.effective_tags(later),
                         ["energy", "dryer", "batteries"])

    def test_a_hand_added_tag_survives_a_run_that_never_mentions_it(self):
        card_tags.set_tags("energy", self.card,
                           ["energy", "anomaly", "dryer", "mine"])
        bare = {"id": "energy", "category": "energy", "tags": []}
        self.assertEqual(card_tags.effective_tags(bare), ["energy", "mine"])

    def test_the_category_tag_can_be_removed_too(self):
        card_tags.set_tags("energy", self.card, ["dryer"])
        self.assertEqual(card_tags.effective_tags(self.card), ["dryer"])

    def test_forget_clears_the_edit(self):
        """A deleted card's id must not hand its edits to a later card."""
        card_tags.set_tags("energy", self.card, ["dryer"])
        card_tags.forget("energy")
        self.assertEqual(card_tags.effective_tags(self.card),
                         ["energy", "anomaly", "dryer"])


class PanelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = (
            card_tags.TAGS_FILE, findings_store.FINDINGS_FILE,
            findings_store.INBOX_DIR, self.server.INSIGHTS_DIR,
            self.server.MEMORY_INBOX_DIR, self.server.SHARED_MEMORY_FILE,
            self.server.CONSOLIDATE_SCRIPT, prompt_store.OVERRIDES_FILE,
            feedback_store.FEEDBACK_FILE, user_categories.USER_CATS_FILE,
            knowledge_store.KNOWLEDGE_FILE, onboarding.STUDY_REQUESTS_DIR,
            engine.run_claude,
        )
        card_tags.TAGS_FILE = tmp / "card_tags.json"
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.INBOX_DIR = tmp / "findings-inbox"
        self.server.INSIGHTS_DIR = tmp
        self.server.MEMORY_INBOX_DIR = tmp / "memory-inbox"
        self.server.SHARED_MEMORY_FILE = tmp / "memory.md"
        prompt_store.OVERRIDES_FILE = os.path.join(self.tmp.name, "o", "ov.json")
        feedback_store.FEEDBACK_FILE = os.path.join(self.tmp.name, "fb.json")
        user_categories.USER_CATS_FILE = os.path.join(self.tmp.name, "uc.json")
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "k.json")
        hypotheses.HYPOTHESES_FILE = tmp / "hypotheses.jsonl"
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        onboarding.STATE_FILE = tmp / "onboarding.json"
        onboarding.STUDY_REQUESTS_DIR = tmp / "study_requests"
        settings_store.save({"onboarded": True})
        # never reach the real CLI: make_app() starts a worker, and this
        # container has `claude` on PATH
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": "OK", "error": "", "meta": {}}
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        (card_tags.TAGS_FILE, findings_store.FINDINGS_FILE,
         findings_store.INBOX_DIR, self.server.INSIGHTS_DIR,
         self.server.MEMORY_INBOX_DIR, self.server.SHARED_MEMORY_FILE,
         self.server.CONSOLIDATE_SCRIPT, prompt_store.OVERRIDES_FILE,
         feedback_store.FEEDBACK_FILE, user_categories.USER_CATS_FILE,
         knowledge_store.KNOWLEDGE_FILE, onboarding.STUDY_REQUESTS_DIR,
         engine.run_claude) = self._olds
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        return TestClient(TestServer(self.server.make_app()))

    def _save(self, card_id, category, tags):
        self.server.save_insight({
            "id": card_id, "category": category, "title": "T", "tags": tags,
            "generated_at": "2026-07-18T10:00:00", "html": "<p></p>",
        })


class TestTagRoute(PanelCase):
    def test_insights_are_served_with_effective_tags(self):
        self._save("energy", "energy", ["anomaly"])
        card_tags.set_tags("energy", {"id": "energy", "category": "energy",
                                      "tags": ["anomaly"]}, ["anomaly", "mine"])

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.get("/api/insights")).json()
                self.assertEqual(data["insights"][0]["tags"], ["anomaly", "mine"])
            finally:
                await client.close()

        asyncio.run(run())

    def test_put_tags_round_trips(self):
        self._save("energy", "energy", ["anomaly", "dryer"])

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.put("/api/card/energy/tags",
                                        json={"tags": ["dryer", "#Mine "]})
                self.assertEqual(resp.status, 200)
                self.assertEqual((await resp.json())["tags"], ["dryer", "mine"])

                data = await (await client.get("/api/insights")).json()
                self.assertEqual(data["insights"][0]["tags"], ["dryer", "mine"])
            finally:
                await client.close()

        asyncio.run(run())

    def test_bad_input_is_rejected(self):
        self._save("energy", "energy", ["anomaly"])

        async def run():
            client = self._client()
            await client.start_server()
            try:
                self.assertEqual(
                    (await client.put("/api/card/energy/tags",
                                      json={"tags": "dryer"})).status, 400)
                self.assertEqual(
                    (await client.put("/api/card/nope/tags",
                                      json={"tags": []})).status, 404)
            finally:
                await client.close()

        asyncio.run(run())


class TestAskBarLearns(PanelCase):
    """One bar, two verbs. A study session is a different thing from a
    question — minutes not seconds, tools not a snapshot, memory not a card —
    but a second input for it meant nobody ever ran one."""

    def _queued_topics(self):
        return sorted(
            json.loads(p.read_text())["topic"]
            for p in onboarding.STUDY_REQUESTS_DIR.glob("*.json"))

    def test_learn_phrasings_queue_a_study_session(self):
        cases = {
            "learn about my energy use": "my energy use",
            "Study the boiler": "the boiler",
            "go learn more about presence": "presence",
            "please research the heating?": "the heating",
            "figure out why the hall sensor drops": "why the hall sensor drops",
            "learn": "",
        }

        async def run():
            client = self._client()
            await client.start_server()
            try:
                for phrase, topic in cases.items():
                    resp = await client.post("/api/generate",
                                             json={"question": phrase})
                    body = await resp.json()
                    self.assertEqual(body["queued"], [],
                                     f"{phrase!r} was drawn as a card")
                    self.assertEqual(body["learning"], topic, f"for {phrase!r}")
            finally:
                await client.close()

        asyncio.run(run())
        self.assertEqual(len(list(onboarding.STUDY_REQUESTS_DIR.glob("*.json"))),
                         len(cases))
        self.assertIn("my energy use", self._queued_topics())

    def test_an_ordinary_question_is_still_a_card(self):
        """The trigger is a leading verb, not the word appearing anywhere —
        "what did the house learn" is a question, not a study session."""
        async def run():
            client = self._client()
            await client.start_server()
            try:
                for phrase in ("Which rooms are coldest at night?",
                               "What has the house learned about me?",
                               "Did the study of my energy use finish?"):
                    body = await (await client.post(
                        "/api/generate", json={"question": phrase})).json()
                    self.assertNotIn("learning", body, f"{phrase!r} ran a study")
                    self.assertEqual(len(body["queued"]), 1)
            finally:
                await client.close()

        asyncio.run(run())
        self.assertEqual(list(onboarding.STUDY_REQUESTS_DIR.glob("*.json")), [])


class TestManualConsolidation(PanelCase):
    def _queue(self, n):
        self.server.MEMORY_INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (self.server.MEMORY_INBOX_DIR / "1-panel.jsonl").write_text(
            "".join(json.dumps({"ts": 1, "source": "panel", "fact": f"Fact {i}"})
                    + "\n" for i in range(n)), encoding="utf-8")

    def test_pending_count_reaches_the_panel(self):
        """The button says how much is waiting, so pressing it is an informed
        choice rather than a hopeful one."""
        self._queue(3)

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.get("/api/knowledge")).json()
                self.assertEqual(data["inbox_pending"], 3)
            finally:
                await client.close()

        asyncio.run(run())

    def test_consolidating_runs_the_same_script_the_daemon_does(self):
        script = Path(self.tmp.name) / "fake-consolidate.sh"
        marker = Path(self.tmp.name) / "ran"
        script.write_text(
            f'#!/bin/bash\necho "$1" > {marker}\n'
            f'rm -f {self.server.MEMORY_INBOX_DIR}/*.jsonl\n', encoding="utf-8")
        script.chmod(0o755)
        self.server.CONSOLIDATE_SCRIPT = str(script)
        self._queue(2)
        self.server.SHARED_MEMORY_FILE.write_text("# Home Memory\n", encoding="utf-8")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/memory/consolidate")
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                self.assertEqual(body["consolidated"], 2)
                self.assertEqual(body["inbox_pending"], 0)
                self.assertIn("Home Memory", body["shared_memory"])
            finally:
                await client.close()

        asyncio.run(run())
        # --once, not the daemon loop: the panel must never start a second one
        self.assertEqual(marker.read_text().strip(), "--once")

    def test_a_failed_pass_says_so_and_leaves_the_queue_alone(self):
        """The consolidator leaves the inbox pending on any failure. The
        panel has to report that rather than claiming it filed."""
        script = Path(self.tmp.name) / "broken.sh"
        script.write_text("#!/bin/bash\necho 'inbox left pending' >&2\nexit 1\n",
                          encoding="utf-8")
        script.chmod(0o755)
        self.server.CONSOLIDATE_SCRIPT = str(script)
        self._queue(2)

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/memory/consolidate")
                self.assertEqual(resp.status, 502)
                self.assertIn("pending", await resp.text())
                # and the flag is cleared, or the tab claims it's still merging
                self.assertFalse(self.server.MEMORY_STATE["merging"])
            finally:
                await client.close()

        asyncio.run(run())
        self.assertEqual(self.server._inbox_pending(), 2)

    def test_a_missing_script_is_reported_not_crashed(self):
        self.server.CONSOLIDATE_SCRIPT = "/nope/does-not-exist.sh"

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/memory/consolidate")
                self.assertEqual(resp.status, 502)
                self.assertIn("isn't installed", await resp.text())
            finally:
                await client.close()

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
