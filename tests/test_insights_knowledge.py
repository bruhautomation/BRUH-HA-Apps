#!/usr/bin/env python3
"""Tests for the brAIn knowledge layer (the "depth" release).

Covers:
- knowledge_store: fact dedup, question lifecycle, prompt block rendering
- build_prompt: knowledge + previous-run injection
- ha_data: device-context expansion (phone sensors joined via the device
  registry) and its budget shrinking
- server: question re-ask filtering, findings landing in the store, the
  /api/knowledge endpoints
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
import engine  # noqa: E402
import hypotheses  # noqa: E402
import onboarding  # noqa: E402
import feedback_store  # noqa: E402
import card_tags  # noqa: E402
import findings_store  # noqa: E402
import knowledge_store  # noqa: E402
import prompt_store  # noqa: E402
import settings_store  # noqa: E402
import user_categories  # noqa: E402


class KnowledgeStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = knowledge_store.KNOWLEDGE_FILE
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "knowledge.json")
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "hypotheses.jsonl"
        # These exercise a home that has finished onboarding. A fresh
        # install deliberately has NO cards, so without this every
        # category-facing test would see an empty dashboard.
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        onboarding.STATE_FILE = Path(self.tmp.name) / "onboarding.json"
        settings_store.save({"onboarded": True})

    def tearDown(self):
        knowledge_store.KNOWLEDGE_FILE = self._old
        self.tmp.cleanup()


class TestKnowledgeFacts(KnowledgeStoreCase):
    def test_add_and_dedup(self):
        entry, created = knowledge_store.add_fact("The hall sensor drops at 2 AM.")
        self.assertTrue(created)
        self.assertTrue(entry["ts"])
        # same fact, different case/punctuation/whitespace → not re-stored
        dup, created2 = knowledge_store.add_fact("the Hall  sensor drops at 2 AM")
        self.assertFalse(created2)
        self.assertEqual(dup["ts"], entry["ts"])
        self.assertEqual(len(knowledge_store.list_facts()), 1)

    def test_blank_rejected(self):
        entry, created = knowledge_store.add_fact("   ")
        self.assertIsNone(entry)
        self.assertFalse(created)

    def test_remove(self):
        entry, _ = knowledge_store.add_fact("A fact", source="user", category="energy")
        listed = knowledge_store.list_facts()
        self.assertEqual(listed[0]["source"], "user")
        self.assertEqual(listed[0]["category"], "energy")
        self.assertTrue(knowledge_store.remove_fact(entry["ts"]))
        self.assertFalse(knowledge_store.remove_fact(entry["ts"]))
        self.assertEqual(knowledge_store.list_facts(), [])

    def test_cap_keeps_newest(self):
        old_max = knowledge_store.MAX_FACTS
        knowledge_store.MAX_FACTS = 5
        try:
            for i in range(8):
                knowledge_store.add_fact(f"fact number {i}")
        finally:
            knowledge_store.MAX_FACTS = old_max
        texts = [f["text"] for f in knowledge_store.list_facts()]
        self.assertEqual(texts, [f"fact number {i}" for i in range(3, 8)])

    def test_corrupt_file_tolerated(self):
        with open(knowledge_store.KNOWLEDGE_FILE, "w") as f:
            f.write("not json")
        self.assertEqual(knowledge_store.list_facts(), [])
        _, created = knowledge_store.add_fact("works anyway")
        self.assertTrue(created)


class TestKnowledgeQuestions(KnowledgeStoreCase):
    def test_record_and_reask_bumps_count(self):
        q = knowledge_store.record_question("Is the fridge meant to run overnight?", "energy")
        self.assertEqual(q["status"], "open")
        self.assertEqual(q["asked_count"], 1)
        again = knowledge_store.record_question("Is the fridge meant to run overnight?")
        self.assertEqual(again["ts"], q["ts"])
        self.assertEqual(again["asked_count"], 2)
        self.assertEqual(len(knowledge_store.list_questions()), 1)

    def test_is_known_question_any_status(self):
        self.assertFalse(knowledge_store.is_known_question("Is X on?"))
        knowledge_store.record_question("Is X on?")
        self.assertTrue(knowledge_store.is_known_question("is x ON??"))
        # answered and dismissed stay known
        knowledge_store.answer_question("Is X on?", "Yes")
        self.assertTrue(knowledge_store.is_known_question("Is X on?"))

    def test_answer_lifecycle(self):
        q = knowledge_store.record_question("Is the fridge ok?")
        answered = knowledge_store.answer_question("is the fridge ok", "Yes, by design")
        self.assertEqual(answered["ts"], q["ts"])
        self.assertEqual(answered["status"], "answered")
        self.assertEqual(answered["answer"], "Yes, by design")
        # re-recording an answered question never reopens it
        again = knowledge_store.record_question("Is the fridge ok?")
        self.assertEqual(again["status"], "answered")
        self.assertEqual(knowledge_store.list_questions("open"), [])

    def test_answer_unrecorded_question_creates_answered(self):
        entry = knowledge_store.answer_question("Never asked?", "Answer anyway")
        self.assertEqual(entry["status"], "answered")
        self.assertEqual(len(knowledge_store.list_questions("answered")), 1)

    def test_dismiss_and_remove(self):
        q = knowledge_store.record_question("Annoying question?")
        self.assertTrue(knowledge_store.dismiss_question(q["ts"]))
        self.assertEqual(knowledge_store.list_questions("dismissed")[0]["ts"], q["ts"])
        self.assertTrue(knowledge_store.is_known_question("Annoying question?"))
        self.assertTrue(knowledge_store.remove_question(q["ts"]))
        self.assertFalse(knowledge_store.remove_question(q["ts"]))
        self.assertFalse(knowledge_store.is_known_question("Annoying question?"))


class TestPromptBlock(KnowledgeStoreCase):
    def test_empty_store_renders_nothing(self):
        self.assertEqual(knowledge_store.prompt_block(), "")

    def test_only_rejected_lines_of_inquiry_are_rendered(self):
        """Facts live in the memory document and are injected from there;
        the ask-history is enforced in code. Neither belongs in the prompt."""
        knowledge_store.add_fact("The office lamp is called the beacon")
        knowledge_store.record_question("Is the fridge ok?")
        knowledge_store.answer_question("Is the fridge ok?", "Yes, by design")
        knowledge_store.record_question("Should the porch light stay on?")
        dead = knowledge_store.record_question("Is the attic fan broken?")
        knowledge_store.dismiss_question(dead["ts"])

        block = knowledge_store.prompt_block()
        self.assertIn("REJECTED", block)
        self.assertIn("attic fan", block)
        for leaked in ("KNOWN FACTS", "the beacon", "ANSWERED QUESTIONS",
                       "Yes, by design", "QUESTIONS ALREADY ASKED", "porch light"):
            self.assertNotIn(leaked, block)

    def test_empty_when_nothing_was_rejected(self):
        knowledge_store.add_fact("The office lamp is called the beacon")
        knowledge_store.record_question("Should the porch light stay on?")
        self.assertEqual(knowledge_store.prompt_block(), "")

    def test_budget_capped(self):
        for i in range(60):
            q = knowledge_store.record_question(f"question {i} " + "x" * 400)
            knowledge_store.dismiss_question(q["ts"])
        block = knowledge_store.prompt_block()
        self.assertLessEqual(len(block), knowledge_store.PROMPT_MAX_CHARS)


class TestPromptInjection(unittest.TestCase):
    def test_knowledge_injected(self):
        prompt = categories.build_prompt(
            categories.CATEGORIES[0], {"entities": []},
            knowledge="KNOWN FACTS about this home:\n- The beacon is the office lamp")
        self.assertIn("KNOWN FACTS", prompt)
        self.assertIn("The beacon is the office lamp", prompt)

    def test_previous_run_injected(self):
        prompt = categories.build_prompt(
            categories.CATEGORIES[0], {"entities": []},
            previous={
                "generated_at": "2026-07-20T08:00:00",
                "title": "Quiet morning",
                "summary": "All quiet.",
                "highlights": [{"label": "Lights on", "value": "3"}],
                "learned": ["Old discovery"],
            })
        self.assertIn("YOUR PREVIOUS ANALYSIS", prompt)
        self.assertIn("Quiet morning", prompt)
        self.assertIn("Lights on: 3", prompt)
        self.assertIn("Old discovery", prompt)

    def test_no_blocks_when_absent(self):
        prompt = categories.build_prompt(categories.CATEGORIES[0], {"entities": []})
        self.assertNotIn("KNOWN FACTS", prompt)
        self.assertNotIn("YOUR PREVIOUS ANALYSIS", prompt)

    def test_system_prompt_depth_rules(self):
        sp = categories.SYSTEM_PROMPT
        self.assertIn("device_context", sp)
        self.assertIn("REASON LIKE A DETECTIVE", sp)
        self.assertIn("never re-ask", sp.lower())

    def test_presence_category_uses_device_context(self):
        presence = categories.get_category("presence")
        self.assertTrue(presence.get("device_context"))
        overview = categories.get_category("overview")
        self.assertTrue(overview.get("device_context"))

    def test_bundle_section_documented(self):
        prompt = categories.build_prompt(categories.CATEGORIES[0], {"entities": []})
        self.assertIn("device_context", prompt)


class TestDeviceContext(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ha_data = importlib.import_module("ha_data")

    def _fixture(self):
        states = [
            {"entity_id": "device_tracker.bens_phone", "state": "not_home",
             "attributes": {"friendly_name": "Ben's Phone", "source_type": "gps"}},
            {"entity_id": "sensor.bens_phone_ssid", "state": "OfficeNet",
             "attributes": {"friendly_name": "Ben's Phone SSID"}},
            {"entity_id": "sensor.bens_phone_geocoded_location", "state": "5th & Main",
             "attributes": {"friendly_name": "Ben's Phone Geocoded Location"}},
            {"entity_id": "sensor.bens_phone_battery", "state": "81",
             "attributes": {"friendly_name": "Ben's Phone Battery",
                            "unit_of_measurement": "%"}},
            {"entity_id": "sensor.bens_phone_activity", "state": "unavailable",
             "attributes": {}},
            {"entity_id": "sensor.unrelated_temp", "state": "21.5",
             "attributes": {"unit_of_measurement": "°C"}},
            {"entity_id": "sensor.bens_phone_hidden", "state": "x", "attributes": {}},
        ]
        registries = {
            "entity_area": {},
            "entity_device": {
                "device_tracker.bens_phone": "dev-phone",
                "sensor.bens_phone_ssid": "dev-phone",
                "sensor.bens_phone_geocoded_location": "dev-phone",
                "sensor.bens_phone_battery": "dev-phone",
                "sensor.bens_phone_activity": "dev-phone",
                "sensor.bens_phone_hidden": "dev-phone",
                "sensor.unrelated_temp": "dev-thermo",
            },
            "device_names": {"dev-phone": "Ben's iPhone"},
            "hidden": {"sensor.bens_phone_hidden"},
            "areas": [],
        }
        return states, registries

    def test_siblings_of_trackers_included(self):
        states, registries = self._fixture()
        out = self.ha_data.related_device_entities(
            states, registries, {"device_tracker.bens_phone"})
        ids = [e["e"] for e in out]
        self.assertIn("sensor.bens_phone_ssid", ids)
        self.assertIn("sensor.bens_phone_geocoded_location", ids)
        self.assertIn("sensor.bens_phone_battery", ids)
        # excluded: unavailable, hidden, unrelated devices, already-present
        self.assertNotIn("sensor.bens_phone_activity", ids)
        self.assertNotIn("sensor.bens_phone_hidden", ids)
        self.assertNotIn("sensor.unrelated_temp", ids)
        self.assertNotIn("device_tracker.bens_phone", ids)
        # tagged with the owning device's name
        self.assertTrue(all(e.get("d") == "Ben's iPhone" for e in out))

    def test_no_trackers_no_context(self):
        states, registries = self._fixture()
        states = [s for s in states if not s["entity_id"].startswith("device_tracker.")]
        out = self.ha_data.related_device_entities(states, registries, set())
        self.assertEqual(out, [])

    def test_tracker_without_device_ignored(self):
        states, registries = self._fixture()
        registries["entity_device"].pop("device_tracker.bens_phone")
        out = self.ha_data.related_device_entities(
            states, registries, {"device_tracker.bens_phone"})
        self.assertEqual(out, [])

    def test_per_device_cap(self):
        states, registries = self._fixture()
        for i in range(60):
            eid = f"sensor.bens_phone_extra_{i}"
            states.append({"entity_id": eid, "state": str(i), "attributes": {}})
            registries["entity_device"][eid] = "dev-phone"
        out = self.ha_data.related_device_entities(
            states, registries, {"device_tracker.bens_phone"})
        self.assertLessEqual(len(out), self.ha_data.MAX_CONTEXT_PER_DEVICE)

    def test_device_tracker_extra_attrs(self):
        slim = self.ha_data.slim_state(
            {"entity_id": "device_tracker.bens_phone", "state": "home",
             "attributes": {"source_type": "gps", "battery_level": 81}}, None)
        self.assertEqual(slim["x"]["source_type"], "gps")
        self.assertEqual(slim["x"]["battery_level"], 81)

    def test_shrink_trims_device_context(self):
        bundle = {
            "entities": [],
            "device_context": [
                {"e": f"sensor.ctx_{i}", "s": "v" * 2000} for i in range(120)
            ],
        }
        out = self.ha_data._shrink_to_budget(bundle)
        self.assertLess(
            len(json.dumps(out, separators=(",", ":"))),
            self.ha_data.MAX_BUNDLE_CHARS + 5000)
        self.assertGreaterEqual(len(out["device_context"]), 20)


class InsightsServerCase(unittest.TestCase):
    """Isolated server fixture mirroring test_insights_addon's."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        cls.ha_data = importlib.import_module("ha_data")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._olds = (
            self.server.INSIGHTS_DIR, prompt_store.OVERRIDES_FILE,
            self.server.MEMORY_INBOX_DIR, feedback_store.FEEDBACK_FILE,
            user_categories.USER_CATS_FILE, self.server.CARD_TOKEN_FILE,
            knowledge_store.KNOWLEDGE_FILE, self.server.SHARED_MEMORY_FILE,
            self.server.MEMORY_MARKER_FILE,
        )
        self.server.INSIGHTS_DIR = Path(self.tmp.name)
        prompt_store.OVERRIDES_FILE = os.path.join(self.tmp.name, "o", "overrides.json")
        self.server.MEMORY_INBOX_DIR = Path(self.tmp.name) / "memory-inbox"
        feedback_store.FEEDBACK_FILE = os.path.join(self.tmp.name, "feedback.json")
        user_categories.USER_CATS_FILE = os.path.join(self.tmp.name, "user_cats.json")
        self.server.CARD_TOKEN_FILE = Path(self.tmp.name) / "secrets" / "card_token"
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "knowledge.json")
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "hypotheses.jsonl"
        # These exercise a home that has finished onboarding. A fresh
        # install deliberately has NO cards, so without this every
        # category-facing test would see an empty dashboard.
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        onboarding.STATE_FILE = Path(self.tmp.name) / "onboarding.json"
        settings_store.save({"onboarded": True})
        self.server.SHARED_MEMORY_FILE = Path(self.tmp.name) / "memory.md"
        self.server.MEMORY_MARKER_FILE = Path(self.tmp.name) / ".last_consolidated"
        self._old_www = self.server.WWW_CARD_DIR
        self._old_findings = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR)
        self._old_tags = card_tags.TAGS_FILE
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "findings-inbox"
        card_tags.TAGS_FILE = Path(self.tmp.name) / "card_tags.json"
        self.server.WWW_CARD_DIR = Path(self.tmp.name) / "www" / "bruh_insights"
        self.server.MEMORY_STATE.update(merging=False, error="")
        self.server.MEMORY_LAST_TASK = None
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        (self.server.INSIGHTS_DIR, prompt_store.OVERRIDES_FILE,
         self.server.MEMORY_INBOX_DIR, feedback_store.FEEDBACK_FILE,
         user_categories.USER_CATS_FILE, self.server.CARD_TOKEN_FILE,
         knowledge_store.KNOWLEDGE_FILE, self.server.SHARED_MEMORY_FILE,
         self.server.MEMORY_MARKER_FILE) = self._olds
        self.server.WWW_CARD_DIR = self._old_www
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR) = self._old_findings
        card_tags.TAGS_FILE = self._old_tags
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        return TestClient(TestServer(self.server.make_app()))


class TestGenerateLearns(InsightsServerCase):
    def setUp(self):
        super().setUp()
        self.reply = {
            "title": "Energy story",
            "summary": "Stuff happened.",
            "highlights": [{"label": "Total", "value": "12 kWh"}],
            "hypotheses": ["The garage fridge is meant to run 24/7 — right?"],
            "learned": ["Hall sensor drops offline at 2 AM"],
            "tags": ["energy"],
            "html": "<!DOCTYPE html><html><body>ok</body></html>",
        }
        self.prompts = []
        self._old_collect = self.ha_data.collect_bundle
        self._old_run = engine.run_claude
        self._old_service = self.ha_data.call_service

        async def fake_collect(category, days, question=None):
            return {"entities": []}

        def fake_run(prompt, *a, **k):
            self.prompts.append(prompt)
            return {"ok": True, "text": json.dumps(self.reply), "error": "",
                    "meta": {"duration_ms": 5}}

        async def ok_service(service, data):
            pass

        self.ha_data.collect_bundle = fake_collect
        engine.run_claude = fake_run
        self.ha_data.call_service = ok_service

    def tearDown(self):
        self.ha_data.collect_bundle = self._old_collect
        engine.run_claude = self._old_run
        self.ha_data.call_service = self._old_service
        super().tearDown()

    def _stored(self, insight_id="energy"):
        with open(Path(self.tmp.name) / f"{insight_id}.json") as f:
            return json.load(f)

    def test_learned_discoveries_land_in_knowledge_store(self):
        asyncio.run(self.server._generate("energy"))
        facts = knowledge_store.list_facts()
        self.assertEqual([f["text"] for f in facts],
                         ["Hall sensor drops offline at 2 AM"])
        self.assertEqual(facts[0]["source"], "insights")
        self.assertEqual(facts[0]["category"], "energy")

    def test_hypotheses_queued_and_repeats_dropped(self):
        asyncio.run(self.server._generate("energy"))
        self.assertEqual([h["text"] for h in hypotheses.list_all("open")],
                         ["The garage fridge is meant to run 24/7 — right?"])
        # The queue is the only copy. A card used to carry one too, and
        # answering on one surface left the other showing an open question.
        self.assertNotIn("questions", self._stored())

        # Proposed again next run → dropped in code, not merely discouraged
        # by the prompt. A model that ignores the budget must not be able to
        # grow the queue anyway.
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(len(hypotheses.list_all("open")), 1)

    def test_queue_is_capped_regardless_of_what_the_model_returns(self):
        for i in range(hypotheses.MAX_OPEN + 3):
            hypotheses.propose(f"claim number {i}")
        self.assertEqual(len(hypotheses.list_all("open")), hypotheses.MAX_OPEN)
        self.assertEqual(hypotheses.budget(), 0)
        # with no budget nothing new is accepted, even though the stub offers one
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(len(hypotheses.list_all("open")), hypotheses.MAX_OPEN)

    def test_ledger_is_not_injected_but_dead_ends_are(self):
        knowledge_store.add_fact("The beacon is the office lamp")
        knowledge_store.record_question("Old question?")
        dead = knowledge_store.record_question("Is the attic fan broken?")
        knowledge_store.dismiss_question(dead["ts"])
        asyncio.run(self.server._generate("energy"))
        for leaked in ("KNOWN FACTS", "The beacon is the office lamp",
                       "QUESTIONS ALREADY ASKED", "Old question?"):
            self.assertNotIn(leaked, self.prompts[0])
        self.assertIn("attic fan", self.prompts[0])

    def test_previous_run_injected_on_second_generation(self):
        asyncio.run(self.server._generate("energy"))
        self.assertNotIn("YOUR PREVIOUS ANALYSIS", self.prompts[0])
        asyncio.run(self.server._generate("energy"))
        self.assertIn("YOUR PREVIOUS ANALYSIS", self.prompts[1])
        self.assertIn("Energy story", self.prompts[1])
        self.assertIn("Total: 12 kWh", self.prompts[1])

    def test_question_mode_gets_knowledge_but_no_previous(self):
        knowledge_store.add_fact("The beacon is the office lamp")
        self.server._set_job("custom-9", state="queued", question="Why cold?")
        asyncio.run(self.server._generate("custom-9"))
        self.assertNotIn("KNOWN FACTS", self.prompts[0])
        self.assertNotIn("YOUR PREVIOUS ANALYSIS", self.prompts[0])

    def test_duplicate_discovery_not_relearned(self):
        knowledge_store.add_fact("Hall sensor drops offline at 2 AM")
        inbox_before = list(self.server.MEMORY_INBOX_DIR.glob("*")) \
            if self.server.MEMORY_INBOX_DIR.exists() else []

        async def broken_service(service, data):
            raise RuntimeError("not installed")

        self.ha_data.call_service = broken_service
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(len(knowledge_store.list_facts()), 1)
        # nothing new → nothing handed to the memory inbox either
        inbox_after = list(self.server.MEMORY_INBOX_DIR.glob("*")) \
            if self.server.MEMORY_INBOX_DIR.exists() else []
        self.assertEqual(inbox_before, inbox_after)


class TestKnowledgeEndpoints(InsightsServerCase):
    def setUp(self):
        super().setUp()
        self._old_service = self.ha_data.call_service
        # taught facts trigger a background memory merge — pin auth off so
        # the merge deterministically takes the plain-append path
        self._old_auth = engine.get_auth
        engine.get_auth = lambda: None

        async def ok_service(service, data):
            pass

        self.ha_data.call_service = ok_service

    def tearDown(self):
        self.ha_data.call_service = self._old_service
        engine.get_auth = self._old_auth
        super().tearDown()

    def test_knowledge_roundtrip(self):
        self.server.SHARED_MEMORY_FILE.write_text("# Home Memory\n- a note\n")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                # teach a fact — it is QUEUED for the consolidator, and never
                # lands in the facts ledger (no duplicate row under Add)
                resp = await client.post("/api/knowledge/fact",
                                         json={"text": "Garage fridge runs 24/7"})
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                self.assertTrue(body["added"])
                self.assertTrue(body["queued"])
                self.assertEqual(knowledge_store.list_facts(), [])
                # the document is only written once the consolidator runs
                self.server.SHARED_MEMORY_FILE.write_text(
                    "# Home Memory\n- a note\n- Garage fridge runs 24/7\n")
                # duplicate (already in the document) → added: false
                resp = await client.post("/api/knowledge/fact",
                                         json={"text": "garage fridge runs 24/7!"})
                self.assertFalse((await resp.json())["added"])
                # blank → 400
                resp = await client.post("/api/knowledge/fact", json={"text": " "})
                self.assertEqual(resp.status, 400)

                knowledge_store.record_question("Is the porch light intentional?")

                resp = await client.get("/api/knowledge")
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                # The taught fact is in the QUEUE — which is now what the tab
                # lists, so the list and the count are the same read.
                self.assertEqual([f["text"] for f in data["inbox"]],
                                 ["Garage fridge runs 24/7"])
                self.assertEqual(data["inbox_pending"], 1)
                self.assertEqual(data["questions"][0]["status"], "open")
                self.assertIn("a note", data["shared_memory"])

                # answer the open question via the knowledge panel
                q_ts = data["questions"][0]["ts"]
                resp = await client.post(f"/api/knowledge/question/{q_ts}/answer",
                                         json={"answer": "Yes, security"})
                self.assertEqual(resp.status, 200)
                data = (await (await client.get("/api/knowledge")).json())
                self.assertEqual(data["questions"][0]["status"], "answered")
                self.assertEqual(data["questions"][0]["answer"], "Yes, security")
                # the answer became a fact — as a statement, not a Q/A pair —
                # and it is waiting in the queue like everything else
                self.assertTrue(
                    any("Yes, security" in f["text"] for f in data["inbox"]))
                self.assertTrue(
                    any("Yes, security" in f["text"]
                        for f in knowledge_store.list_facts()))
                self.assertFalse(
                    any(f["text"].startswith("Q:") for f in data["inbox"]))

                # ✕ drops it from the queue, and the reply carries the fresh
                # list and count together so the row cannot vanish while the
                # label above it still counts it.
                item = next(f for f in data["inbox"] if "Yes, security" in f["text"])
                resp = await client.delete(f"/api/memory/inbox/{item['id']}")
                self.assertEqual(resp.status, 200)
                after = await resp.json()
                self.assertEqual(len(after["inbox"]), after["inbox_pending"])
                self.assertFalse(
                    any("Yes, security" in f["text"] for f in after["inbox"]))
                resp = await client.delete(f"/api/memory/inbox/{item['id']}")
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())

    def test_dismiss_and_delete_question(self):
        q = knowledge_store.record_question("Meh question?")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/knowledge/question/{q['ts']}/dismiss")
                self.assertEqual(resp.status, 200)
                self.assertEqual(
                    knowledge_store.list_questions("dismissed")[0]["ts"], q["ts"])
                resp = await client.delete(f"/api/knowledge/question/{q['ts']}")
                self.assertEqual(resp.status, 200)
                self.assertEqual(knowledge_store.list_questions(), [])
                resp = await client.post("/api/knowledge/question/999/dismiss")
                self.assertEqual(resp.status, 404)
                resp = await client.post("/api/knowledge/question/abc/dismiss")
                self.assertEqual(resp.status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_dismissing_retires_question_from_cards(self):
        self.server.save_insight({
            "id": "energy", "category": "energy", "title": "T",
            "generated_at": "2026-07-20T10:00:00", "html": "<p>x</p>",
            "questions": ["Is the porch light intentional?"]})
        q = knowledge_store.record_question("Is the porch light intentional?")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/knowledge/question/{q['ts']}/dismiss")
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        stored = json.loads((Path(self.tmp.name) / "energy.json").read_text())
        self.assertEqual(stored["questions"], [])

    def test_confirming_a_guess_settles_it_and_answers_with_the_list(self):
        """Guesses are answered on the Findings tab now, so the reply is the
        Findings payload — the tab that asked has what it needs to redraw
        without a second round trip."""
        claim = "The garage fridge is meant to run 24/7"
        entry = hypotheses.propose(claim, "energy")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/hypothesis/{entry['ts']}/confirm")
                self.assertEqual(resp.status, 200)
                return await resp.json()
            finally:
                await client.close()

        payload = asyncio.run(run())
        self.assertEqual(payload["hypotheses"], [])
        self.assertIn("findings", payload)
        self.assertEqual([h["status"] for h in hypotheses.list_all()], ["confirmed"])
        # The claim is the durable part: it queues for the memory document.
        facts = [json.loads(line)["fact"]
                 for f in self.server.MEMORY_INBOX_DIR.glob("*.jsonl")
                 for line in f.read_text().splitlines() if line.strip()]
        self.assertIn(claim, facts)

    def test_rejecting_a_guess_without_a_reason_is_still_a_dead_end(self):
        claim = "The attic fan is broken"
        entry = hypotheses.propose(claim, "energy")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/hypothesis/{entry['ts']}/reject")
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        self.assertEqual([h["status"] for h in hypotheses.list_all()], ["rejected"])
        self.assertIn(claim, knowledge_store.prompt_block())
        # No reason, nothing to remember about the house.
        self.assertEqual(list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")), [])

    def test_a_reason_for_no_reaches_both_the_prompt_and_memory(self):
        """"No" retires one claim. "No, that's the beer fridge and it cycles
        all night" retires every guess built on the same misreading — so the
        reason goes to the analyst AND to the consolidator, which decides
        what durable truth is in it."""
        claim = "The garage fridge is faulty"
        entry = hypotheses.propose(claim, "energy")
        why = "That's the beer fridge — it's meant to cycle all night."

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(
                    f"/api/hypothesis/{entry['ts']}/reject", json={"note": why})
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        self.assertIn(why, "\n".join(hypotheses.dead_ends()))
        lines = [json.loads(line)
                 for f in self.server.MEMORY_INBOX_DIR.glob("*.jsonl")
                 for line in f.read_text().splitlines() if line.strip()]
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["source"], "correction")
        self.assertIn(why, lines[0]["fact"])
        # The rejected claim rides along as context. What the consolidator is
        # being corrected ABOUT is half of what makes the correction legible.
        self.assertIn(claim, lines[0]["fact"])


class TestMemoryFile(InsightsServerCase):
    """The memory document behind the panel's Memory section.

    The panel does not write this file. One writer owns it — the
    consolidator — so everything here queues into the inbox instead, and
    these tests assert the queueing rather than a merge.
    """

    def setUp(self):
        super().setUp()
        self._old_service = self.ha_data.call_service
        self._old_auth = engine.get_auth
        self._old_run = engine.run_claude

        async def ok_service(service, data):
            pass

        self.ha_data.call_service = ok_service
        # The app starts a generation scheduler on startup. Without an auth
        # stub it finds the real CLI on PATH and blocks the whole test.
        engine.get_auth = lambda: None
        engine.run_claude = lambda *a, **k: {
            "ok": False, "text": "", "error": "stubbed", "meta": {}}
        self.inbox = Path(self.tmp.name) / "inbox"
        self.server.MEMORY_INBOX_DIR = self.inbox

    def tearDown(self):
        self.ha_data.call_service = self._old_service
        engine.get_auth = self._old_auth
        engine.run_claude = self._old_run
        super().tearDown()

    def _queued_facts(self):
        facts = []
        for f in sorted(self.inbox.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    facts.append(json.loads(line))
        return facts

    def test_put_and_read_roundtrip(self):
        """A manual edit is the one write the panel still performs — it is
        the user typing, not the analyst learning."""
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.put("/api/memory", json={
                    "text": "# Home Memory\n\n## Preferences\n- Lights warm at night\n"})
                self.assertEqual(resp.status, 200)
                data = await (await client.get("/api/knowledge")).json()
                self.assertIn("Lights warm at night", data["shared_memory"])
                # invalid bodies rejected
                resp = await client.put("/api/memory", json={"text": 42})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/memory", json={
                    "text": "x" * (self.server.MAX_MEMORY_CHARS + 1)})
                self.assertEqual(resp.status, 400)
            finally:
                await client.close()

        asyncio.run(run())
        self.assertIn("Lights warm at night",
                      self.server.SHARED_MEMORY_FILE.read_text())

    def test_taught_fact_is_queued_not_written(self):
        self.server.SHARED_MEMORY_FILE.write_text(
            "# Home Memory\n\n## Device notes\n- Old note\n")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/knowledge/fact", json={
                    "text": "Garage fridge runs 24/7 by design"})
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                self.assertTrue(body["added"])
                self.assertTrue(body["queued"])
            finally:
                await client.close()

        asyncio.run(run())

        queued = self._queued_facts()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["fact"], "Garage fridge runs 24/7 by design")

        # The document is untouched until the consolidator runs.
        self.assertEqual(self.server.SHARED_MEMORY_FILE.read_text(),
                         "# Home Memory\n\n## Device notes\n- Old note\n")

    def test_duplicate_fact_is_not_queued_twice(self):
        self.server.SHARED_MEMORY_FILE.write_text(
            "# Home Memory\n\n## Device notes\n- Garage fridge runs 24/7 by design\n")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/knowledge/fact", json={
                    "text": "Garage fridge runs 24/7 by design"})
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                self.assertFalse(body["added"])
                self.assertFalse(body["queued"])
            finally:
                await client.close()

        asyncio.run(run())
        self.assertEqual(self._queued_facts(), [])

    def test_a_fact_the_document_already_holds_is_edited_out_of_it(self):
        """The panel's ✕ used to delete a ledger entry and queue
        `FORGET: ...` for the consolidator. It acts on the filing QUEUE now,
        where the fact has not reached the document and there is nothing to
        strike from it — and a line the document does hold is edited out in
        the markdown editor beside the queue, which rewrites the file
        through the same single writer.

        `FORGET:` itself is unchanged and still understood: `brain memory
        forget` writes one from the terminal.
        """
        self.assertFalse(hasattr(self.server, "_queue_memory_removal"))
        consolidator = (BASE_DIR / "brain" / "scripts" / "brain-memory-consolidate.sh").read_text()
        self.assertIn('Lines beginning "FORGET: "', consolidator)
        cli = (BASE_DIR / "brain" / "scripts" / "brain-memory.sh").read_text()
        self.assertIn('append_inbox_fact "FORGET: $1"', cli)

    def test_answered_question_is_remembered_as_a_statement(self):
        """Not as "Q: ... -> A: ...", which is what made memory unreadable."""
        async def run():
            await self.server._submit_answer(
                "Is the garage fridge meant to run overnight?", "Yes, always")

        asyncio.run(run())
        queued = self._queued_facts()
        self.assertEqual(len(queued), 1)
        self.assertNotIn("Q:", queued[0]["fact"])
        self.assertNotIn("→", queued[0]["fact"])
        self.assertIn("Yes, always", queued[0]["fact"])

    def test_inbox_failure_never_breaks_the_request(self):
        """A memory hand-off that cannot write must not fail an insight run."""
        self.server.MEMORY_INBOX_DIR = Path("/proc/nonexistent/inbox")

        async def run():
            await self.server._submit_memory("something worth knowing")

        asyncio.run(run())  # must not raise



if __name__ == "__main__":
    unittest.main()
