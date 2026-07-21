#!/usr/bin/env python3
"""Tests for the BRUH Insights knowledge layer (the "depth" release).

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
PANEL_DIR = BASE_DIR / "bruh-insights" / "panel"

sys.path.insert(0, str(PANEL_DIR))

import categories  # noqa: E402
import claude_client  # noqa: E402
import feedback_store  # noqa: E402
import knowledge_store  # noqa: E402
import prompt_store  # noqa: E402
import user_categories  # noqa: E402


class KnowledgeStoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = knowledge_store.KNOWLEDGE_FILE
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "knowledge.json")

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

    def test_sections_present(self):
        knowledge_store.add_fact("The office lamp is called the beacon")
        q = knowledge_store.record_question("Is the fridge ok?")
        knowledge_store.answer_question("Is the fridge ok?", "Yes, by design")
        knowledge_store.record_question("Should the porch light stay on?")
        block = knowledge_store.prompt_block()
        self.assertIn("KNOWN FACTS", block)
        self.assertIn("the beacon", block)
        self.assertIn("ANSWERED QUESTIONS", block)
        self.assertIn("Yes, by design", block)
        self.assertIn("QUESTIONS ALREADY ASKED", block)
        self.assertIn("porch light", block)
        del q

    def test_budget_capped(self):
        for i in range(60):
            knowledge_store.add_fact(f"fact {i} " + "x" * 400)
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
                "findings": ["Old finding"],
            })
        self.assertIn("YOUR PREVIOUS ANALYSIS", prompt)
        self.assertIn("Quiet morning", prompt)
        self.assertIn("Lights on: 3", prompt)
        self.assertIn("Old finding", prompt)

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
        )
        self.server.INSIGHTS_DIR = Path(self.tmp.name)
        prompt_store.OVERRIDES_FILE = os.path.join(self.tmp.name, "o", "overrides.json")
        self.server.MEMORY_INBOX_DIR = Path(self.tmp.name) / "memory-inbox"
        feedback_store.FEEDBACK_FILE = os.path.join(self.tmp.name, "feedback.json")
        user_categories.USER_CATS_FILE = os.path.join(self.tmp.name, "user_cats.json")
        self.server.CARD_TOKEN_FILE = Path(self.tmp.name) / "secrets" / "card_token"
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "knowledge.json")
        self.server.SHARED_MEMORY_FILE = Path(self.tmp.name) / "memory.md"
        self._old_www = self.server.WWW_CARD_DIR
        self.server.WWW_CARD_DIR = Path(self.tmp.name) / "www" / "bruh_insights"
        self.server.MEMORY_STATE.update(merging=False, error="")
        self.server.MEMORY_LAST_TASK = None
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        (self.server.INSIGHTS_DIR, prompt_store.OVERRIDES_FILE,
         self.server.MEMORY_INBOX_DIR, feedback_store.FEEDBACK_FILE,
         user_categories.USER_CATS_FILE, self.server.CARD_TOKEN_FILE,
         knowledge_store.KNOWLEDGE_FILE, self.server.SHARED_MEMORY_FILE) = self._olds
        self.server.WWW_CARD_DIR = self._old_www
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
            "questions": ["Is the garage fridge meant to run overnight?"],
            "findings": ["Hall sensor drops offline at 2 AM"],
            "tags": ["energy"],
            "html": "<!DOCTYPE html><html><body>ok</body></html>",
        }
        self.prompts = []
        self._old_collect = self.ha_data.collect_bundle
        self._old_run = claude_client.run_claude
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
        claude_client.run_claude = fake_run
        self.ha_data.call_service = ok_service

    def tearDown(self):
        self.ha_data.collect_bundle = self._old_collect
        claude_client.run_claude = self._old_run
        self.ha_data.call_service = self._old_service
        super().tearDown()

    def _stored(self, insight_id="energy"):
        with open(Path(self.tmp.name) / f"{insight_id}.json") as f:
            return json.load(f)

    def test_findings_land_in_knowledge_store(self):
        asyncio.run(self.server._generate("energy"))
        facts = knowledge_store.list_facts()
        self.assertEqual([f["text"] for f in facts],
                         ["Hall sensor drops offline at 2 AM"])
        self.assertEqual(facts[0]["source"], "insights")
        self.assertEqual(facts[0]["category"], "energy")

    def test_questions_recorded_and_repeats_dropped(self):
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(self._stored()["questions"],
                         ["Is the garage fridge meant to run overnight?"])
        self.assertEqual(len(knowledge_store.list_questions("open")), 1)
        # the model asks the same question next run → filtered out
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(self._stored()["questions"], [])
        # still just one recorded question, asked twice
        qs = knowledge_store.list_questions()
        self.assertEqual(len(qs), 1)
        self.assertEqual(qs[0]["asked_count"], 2)

    def test_known_facts_and_asked_questions_injected(self):
        knowledge_store.add_fact("The beacon is the office lamp")
        knowledge_store.record_question("Old question?")
        asyncio.run(self.server._generate("energy"))
        self.assertIn("KNOWN FACTS", self.prompts[0])
        self.assertIn("The beacon is the office lamp", self.prompts[0])
        self.assertIn("QUESTIONS ALREADY ASKED", self.prompts[0])
        self.assertIn("Old question?", self.prompts[0])

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
        self.assertIn("KNOWN FACTS", self.prompts[0])
        self.assertNotIn("YOUR PREVIOUS ANALYSIS", self.prompts[0])

    def test_duplicate_finding_not_relearned(self):
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
        self._old_auth = claude_client.get_auth
        claude_client.get_auth = lambda: None

        async def ok_service(service, data):
            pass

        self.ha_data.call_service = ok_service

    def tearDown(self):
        self.ha_data.call_service = self._old_service
        claude_client.get_auth = self._old_auth
        super().tearDown()

    def test_knowledge_roundtrip(self):
        self.server.SHARED_MEMORY_FILE.write_text("# Home Memory\n- a note\n")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                # teach a fact — it goes into the memory DOCUMENT, not the
                # facts ledger (no duplicate row under the Add button)
                resp = await client.post("/api/knowledge/fact",
                                         json={"text": "Garage fridge runs 24/7"})
                self.assertEqual(resp.status, 200)
                self.assertTrue((await resp.json())["added"])
                await self.server.MEMORY_LAST_TASK
                self.assertIn("Garage fridge runs 24/7",
                              self.server.SHARED_MEMORY_FILE.read_text())
                self.assertEqual(knowledge_store.list_facts(), [])
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
                self.assertEqual(data["facts"], [])
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
                # the Q→A became a fact
                self.assertTrue(any("Yes, security" in f["text"] for f in data["facts"]))

                # delete the fact — also kicks off a memory-file scrub
                ts = data["facts"][0]["ts"]
                resp = await client.delete(f"/api/knowledge/fact/{ts}")
                self.assertEqual(resp.status, 200)
                self.assertTrue((await resp.json())["removing"])
                await self.server.MEMORY_LAST_TASK
                resp = await client.delete(f"/api/knowledge/fact/{ts}")
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

    def test_card_question_dismissed_as_not_relevant(self):
        self.server.save_insight({
            "id": "energy", "category": "energy", "title": "T",
            "generated_at": "2026-07-20T10:00:00", "html": "<p>x</p>",
            "questions": ["Is the attic fan broken?"]})

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/questions/dismiss", json={
                    "insight_id": "energy", "question": "Is the attic fan broken?"})
                self.assertEqual(resp.status, 200)
                # unknown question → 404
                resp = await client.post("/api/questions/dismiss", json={
                    "insight_id": "energy", "question": "Never asked?"})
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())
        dismissed = knowledge_store.list_questions("dismissed")
        self.assertEqual([q["text"] for q in dismissed], ["Is the attic fan broken?"])
        stored = json.loads((Path(self.tmp.name) / "energy.json").read_text())
        self.assertEqual(stored["questions"], [])
        # the wrong-track signal reaches the prompt
        block = knowledge_store.prompt_block()
        self.assertIn("NOT RELEVANT", block)
        self.assertIn("Is the attic fan broken?", block)

    def test_card_answer_records_in_store(self):
        self.server.save_insight({
            "id": "energy", "category": "energy", "title": "T",
            "generated_at": "2026-07-20T10:00:00", "html": "<p>x</p>",
            "questions": ["Is X ok?"]})

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/questions/answer", json={
                    "insight_id": "energy", "question": "Is X ok?", "answer": "Yes"})
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        answered = knowledge_store.list_questions("answered")
        self.assertEqual(len(answered), 1)
        self.assertEqual(answered[0]["answer"], "Yes")
        self.assertTrue(knowledge_store.is_known_question("Is X ok?"))
        self.assertTrue(any("Yes" in f["text"] for f in knowledge_store.list_facts()))


class TestMemoryFile(InsightsServerCase):
    """The editable home memory file behind the panel's Memory section."""

    def setUp(self):
        super().setUp()
        self._old_auth = claude_client.get_auth
        self._old_run = claude_client.run_claude
        self._old_service = self.ha_data.call_service

        async def ok_service(service, data):
            pass

        self.ha_data.call_service = ok_service

    def tearDown(self):
        claude_client.get_auth = self._old_auth
        claude_client.run_claude = self._old_run
        self.ha_data.call_service = self._old_service
        super().tearDown()

    def test_put_and_read_roundtrip(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.put("/api/memory", json={
                    "text": "# Home Memory\n\n## Preferences\n- Lights warm at night\n"})
                self.assertEqual(resp.status, 200)
                data = await (await client.get("/api/knowledge")).json()
                self.assertIn("Lights warm at night", data["shared_memory"])
                self.assertFalse(data["memory_state"]["merging"])
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

    def test_teach_fact_merges_via_claude(self):
        self.server.SHARED_MEMORY_FILE.write_text(
            "# Home Memory\n\n## Device notes\n- Old note\n")
        prompts = []
        claude_client.get_auth = lambda: {"type": "api_key", "value": "k"}

        def fake_run(prompt, system, *a, **k):
            prompts.append((prompt, system))
            return {"ok": True, "text":
                    "# Home Memory\n\n## Device notes\n- Old note\n"
                    "- Garage fridge runs 24/7 by design\n",
                    "error": "", "meta": {}}

        claude_client.run_claude = fake_run

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/knowledge/fact", json={
                    "text": "Garage fridge runs 24/7 by design"})
                self.assertEqual(resp.status, 200)
                body = await resp.json()
                self.assertTrue(body["added"])
                self.assertTrue(body["merging"])
                await self.server.MEMORY_LAST_TASK
            finally:
                await client.close()

        asyncio.run(run())
        merged = self.server.SHARED_MEMORY_FILE.read_text()
        self.assertIn("Garage fridge runs 24/7 by design", merged)
        self.assertIn("Old note", merged)
        # the merge prompt carried the current doc and the new fact (skip the
        # startup auth-check call, which also goes through run_claude)
        merge_calls = [p for p in prompts if "NEW FACTS" in p[0]]
        self.assertEqual(len(merge_calls), 1)
        self.assertIn("Old note", merge_calls[0][0])
        self.assertIn("Garage fridge runs 24/7", merge_calls[0][0])
        self.assertIn("ONLY the complete updated markdown", merge_calls[0][1])
        self.assertFalse(self.server.MEMORY_STATE["merging"])

    def test_merge_strips_code_fences(self):
        claude_client.get_auth = lambda: {"type": "api_key", "value": "k"}
        claude_client.run_claude = lambda *a, **k: {
            "ok": True,
            "text": "```markdown\n# Home Memory\n\n## Preferences\n- A fact\n```",
            "error": "", "meta": {}}

        async def run():
            client = self._client()
            await client.start_server()
            try:
                await client.post("/api/knowledge/fact", json={"text": "A fact"})
                await self.server.MEMORY_LAST_TASK
            finally:
                await client.close()

        asyncio.run(run())
        text = self.server.SHARED_MEMORY_FILE.read_text()
        self.assertNotIn("```", text)
        self.assertIn("- A fact", text)

    def test_no_auth_falls_back_to_append(self):
        claude_client.get_auth = lambda: None

        async def run():
            client = self._client()
            await client.start_server()
            try:
                await client.post("/api/knowledge/fact", json={
                    "text": "The beacon is the office lamp"})
                await self.server.MEMORY_LAST_TASK
            finally:
                await client.close()

        asyncio.run(run())
        text = self.server.SHARED_MEMORY_FILE.read_text()
        self.assertIn("## Recently added", text)
        self.assertIn("- The beacon is the office lamp", text)
        # started from the shared template since no file existed
        self.assertIn("# Home Memory", text)

    def test_bogus_merge_output_falls_back(self):
        self.server.SHARED_MEMORY_FILE.write_text("# Home Memory\n\n- Keep me\n")
        claude_client.get_auth = lambda: {"type": "api_key", "value": "k"}
        claude_client.run_claude = lambda *a, **k: {
            "ok": True, "text": "Sorry, I can't do that.", "error": "", "meta": {}}

        async def run():
            client = self._client()
            await client.start_server()
            try:
                await client.post("/api/knowledge/fact", json={"text": "New fact"})
                await self.server.MEMORY_LAST_TASK
            finally:
                await client.close()

        asyncio.run(run())
        text = self.server.SHARED_MEMORY_FILE.read_text()
        self.assertIn("Keep me", text)
        self.assertIn("## Recently added", text)
        self.assertIn("- New fact", text)
        self.assertNotIn("Sorry", text)

    def test_fact_delete_scrubs_memory_without_claude(self):
        """Fallback path: the matching bullet is stripped deterministically."""
        claude_client.get_auth = lambda: None
        entry, _ = knowledge_store.add_fact("Hall sensor drops offline at 2 AM")
        self.server.SHARED_MEMORY_FILE.write_text(
            "# Home Memory\n\n## Device notes\n"
            "- Hall sensor drops offline at 2 AM\n- Keep me\n")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.delete(f"/api/knowledge/fact/{entry['ts']}")
                self.assertEqual(resp.status, 200)
                self.assertTrue((await resp.json())["removing"])
                await self.server.MEMORY_LAST_TASK
            finally:
                await client.close()

        asyncio.run(run())
        text = self.server.SHARED_MEMORY_FILE.read_text()
        self.assertNotIn("Hall sensor drops offline", text)
        self.assertIn("- Keep me", text)
        self.assertEqual(knowledge_store.list_facts(), [])

    def test_fact_delete_scrubs_memory_via_claude(self):
        """Claude path: reworded statements are removed by the model."""
        entry, _ = knowledge_store.add_fact("The garage fridge runs 24/7")
        self.server.SHARED_MEMORY_FILE.write_text(
            "# Home Memory\n\n## Device notes\n"
            "- Garage refrigerator is expected to run around the clock\n"
            "- Keep me\n")
        prompts = []
        claude_client.get_auth = lambda: {"type": "api_key", "value": "k"}

        def fake_run(prompt, system, *a, **k):
            prompts.append((prompt, system))
            return {"ok": True, "text":
                    "# Home Memory\n\n## Device notes\n- Keep me\n",
                    "error": "", "meta": {}}

        claude_client.run_claude = fake_run

        async def run():
            client = self._client()
            await client.start_server()
            try:
                await client.delete(f"/api/knowledge/fact/{entry['ts']}")
                await self.server.MEMORY_LAST_TASK
            finally:
                await client.close()

        asyncio.run(run())
        text = self.server.SHARED_MEMORY_FILE.read_text()
        self.assertNotIn("around the clock", text)
        self.assertIn("- Keep me", text)
        removal_calls = [p for p in prompts if "DELETED" in p[0]]
        self.assertEqual(len(removal_calls), 1)
        self.assertIn("The garage fridge runs 24/7", removal_calls[0][0])
        self.assertIn("even if reworded", removal_calls[0][1])

    def test_fact_delete_without_memory_file_skips_scrub(self):
        entry, _ = knowledge_store.add_fact("Orphan fact")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.delete(f"/api/knowledge/fact/{entry['ts']}")
                self.assertEqual(resp.status, 200)
                self.assertFalse((await resp.json())["removing"])
                self.assertIsNone(self.server.MEMORY_LAST_TASK)
            finally:
                await client.close()

        asyncio.run(run())

    def test_duplicate_fact_does_not_merge(self):
        knowledge_store.add_fact("Already known")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/knowledge/fact",
                                         json={"text": "Already known"})
                body = await resp.json()
                self.assertFalse(body["added"])
                self.assertFalse(body["merging"])
                self.assertIsNone(self.server.MEMORY_LAST_TASK)
            finally:
                await client.close()

        asyncio.run(run())
        self.assertFalse(self.server.SHARED_MEMORY_FILE.exists())


if __name__ == "__main__":
    unittest.main()
