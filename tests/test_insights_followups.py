#!/usr/bin/env python3
"""Five places an insight path read or wrote the wrong thing.

  weekly    "still open" counted `held` and `triaging` rows — the ones
            triage chose NOT to show — so the report described rows the
            homeowner had never been shown
  milestone the card was saved without the design system the contract
            tells the model to rely on, so on the dark panel it was a white
            box; and its `learned` sentences were requested and dropped
  ideas     the next pass was never shown what had been dismissed, so a
            rewording came back a week later; a dismissal's reason is the
            part that rules out a whole kind of card
  onboarding "something has been learned" was 200 characters of the
            document, and the seeded template is 311 of headings — so the
            Recommend step opened on a memory with nothing in it, and
            what the study sessions DID find (still in the inbox) never
            reached the prompt that was meant to be grounded in it

Each driven over the real module and, where the defect was in the server,
the real server function with only the model and Core replaced.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import categories  # noqa: E402
import findings_store  # noqa: E402
import ideas  # noqa: E402
import knowledge_store  # noqa: E402
import milestones  # noqa: E402
import onboarding  # noqa: E402
import triage  # noqa: E402
import user_categories  # noqa: E402
from test_milestones import NOW, MilestoneCase  # noqa: E402

STYLE_MARK = 'data-brain="card-styles"'


class TestTheWeekCountsWhatWasShown(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.server = importlib.import_module("server")
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE, self.server._weekly_energy)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"

        async def no_energy(now):
            return {}

        self.server._weekly_energy = no_energy

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, self.server._weekly_energy) = self._old
        self.tmp.cleanup()

    def test_held_and_unjudged_rows_are_not_still_open(self):
        rows = [{"text": f"row {i}", "severity": "warning",
                 "source": "check:dev.frozen", "source_title": "Frozen"}
                for i in range(3)]
        filed = findings_store.add_many(triage.gate(rows))
        findings_store.record_triage(
            {filed[0]["ts"]: ("elevated", "real"),
             filed[1]["ts"]: ("held", "a cupboard contact")})
        # filed[2] is still `triaging`: nothing has judged it.
        state = asyncio.run(self.server._weekly_state(time.time()))
        self.assertEqual(state["findings"]["open_now"], 1, state["findings"])
        self.assertEqual(state["findings"]["still_open"], 1)


class TestAMilestoneCardCarriesTheDesignSystem(MilestoneCase):

    def test_the_saved_html_has_the_sheet_once(self):
        due = self.fire("thermal")[0]
        milestones.save_card(
            "thermal", {"title": "How the rooms hold heat", "summary": "S",
                        "html": "<html><head></head><body>"
                                "<svg stroke='var(--accent)'></svg>"
                                "</body></html>"},
            due["mark"], due["made_because"], NOW)
        html = milestones.get_card("thermal")["html"]
        self.assertEqual(html.count(STYLE_MARK), 1)
        self.assertLess(html.index(STYLE_MARK), html.index("<svg"))
        # Re-saved, still once.
        self.assertEqual(categories.inject_styles(html).count(STYLE_MARK), 1)


class TestAMilestoneFilesWhatItLearned(MilestoneCase):

    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.server = importlib.import_module("server")
        self.inbox = root / "memory-inbox"
        self._olds = (knowledge_store.KNOWLEDGE_FILE,
                      self.server.MEMORY_INBOX_DIR,
                      self.server.engine.run_analyst,
                      self.server._record_usage)
        knowledge_store.KNOWLEDGE_FILE = str(root / "knowledge.json")
        self.server.MEMORY_INBOX_DIR = self.inbox
        self.server._record_usage = lambda *a, **k: {}
        self.server.JOBS.clear()

    def tearDown(self):
        (knowledge_store.KNOWLEDGE_FILE, self.server.MEMORY_INBOX_DIR,
         self.server.engine.run_analyst,
         self.server._record_usage) = self._olds
        self.server.JOBS.clear()
        super().tearDown()

    def run_job(self, card: dict):
        due = self.fire("thermal")[0]
        self.server.engine.run_analyst = lambda *a, **k: {
            "ok": True, "text": "", "data": card,
            "meta": {"session_id": "run-mile"}}
        self.server.JOBS["m"] = {"milestone": "thermal", "prompt": "p",
                                 "mark": due["mark"],
                                 "because": due["made_because"]}
        asyncio.run(self.server._run_milestone("m"))
        return self.server.JOBS["m"]

    def queued(self) -> list[dict]:
        out = []
        for path in sorted(self.inbox.glob("*.jsonl")):
            out += [json.loads(line) for line in path.read_text().splitlines()
                    if line.strip()]
        return out

    def test_learned_reaches_the_inbox_once(self):
        card = {"title": "How the rooms hold heat", "summary": "S",
                "html": "<p>x</p>",
                "learned": ["The loft loses heat twice as fast as the lounge"],
                "findings": [{"text": "never a finding from a milestone"}]}
        job = self.run_job(card)
        self.assertEqual(job["state"], "done", job)
        facts = [q["fact"] for q in self.queued()]
        self.assertEqual(facts,
                         ["The loft loses heat twice as fast as the lounge"])
        # The ledger knows it, so the next card does not announce it again.
        _row, created = knowledge_store.add_fact(
            "The loft loses heat twice as fast as the lounge", "insights",
            "climate")
        self.assertFalse(created)


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

    @staticmethod
    def proposal(title):
        return {"title": title, "icon": "🌡", "focus": f"Analyse {title}.",
                "why": "Because.", "question": f"How is {title}?"}


class TestTheNextPassIsToldWhatWasAnswered(IdeasCase):

    def test_a_dismissal_and_its_reason_reach_the_prompt(self):
        ideas.add_many([self.proposal("Heat pump vs everything else"),
                        self.proposal("Freezer drift")])
        heat = [r for r in ideas.open_ideas()
                if r["title"].startswith("Heat pump")][0]
        self.assertTrue(ideas.dismiss(
            heat["id"], reason="we do not care   about the heat pump split"))
        answered, open_titles = ideas.prompt_context()
        self.assertEqual(answered, [{
            "title": "Heat pump vs everything else", "how": "dismissed",
            "reason": "we do not care about the heat pump split"}])
        self.assertEqual(open_titles, ["Freezer drift"])
        prompt = ideas.build_prompt("", {}, [], answered=answered,
                                    open_ideas=open_titles)
        self.assertIn("IDEAS ALREADY SUGGESTED", prompt)
        self.assertIn("Heat pump vs everything else (dismissed: we do not "
                      "care about the heat pump split)", prompt)
        self.assertIn("Freezer drift (already suggested", prompt)

    def test_a_reason_is_optional_and_capped(self):
        ideas.add_many([self.proposal("Freezer drift")])
        idea = ideas.open_ideas()[0]
        self.assertTrue(ideas.dismiss(idea["id"], reason="x" * 999))
        answered, _ = ideas.prompt_context()
        self.assertEqual(len(answered[0]["reason"]), ideas.MAX_REASON)

    def test_the_route_takes_the_reason(self):
        server = importlib.import_module("server")
        ideas.add_many([self.proposal("Freezer drift")])
        idea = ideas.open_ideas()[0]

        async def go():
            from aiohttp.test_utils import TestClient, TestServer
            client = TestClient(TestServer(server.make_app()))
            await client.start_server()
            try:
                res = await client.post(f"/api/idea/{idea['id']}/dismiss",
                                        json={"reason": "no freezer here"})
                self.assertEqual(res.status, 200, await res.text())
            finally:
                await client.close()

        asyncio.run(go())
        self.assertEqual(ideas.prompt_context()[0][0]["reason"],
                         "no freezer here")


def seeded_template() -> str:
    """The document run.sh writes on a fresh install, read out of run.sh —
    a copy here would be the one template the test agreed with."""
    text = (BASE_DIR / "brain" / "run.sh").read_text(encoding="utf-8")
    body = text.split("<< 'MEMORYMD'\n", 1)[1]
    return body.split("\nMEMORYMD", 1)[0] + "\n"


TEMPLATE = seeded_template()


class TestOnboardingWaitsForSomethingLearned(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (onboarding.MEMORY_FILE, onboarding.CURRICULUM_FILE,
                     onboarding.INBOX_DIR)
        onboarding.MEMORY_FILE = root / "memory.md"
        onboarding.CURRICULUM_FILE = root / "curriculum.json"
        onboarding.INBOX_DIR = root / "inbox"
        onboarding.INBOX_DIR.mkdir()
        onboarding.MEMORY_FILE.write_text(TEMPLATE)
        self.assertGreater(len(TEMPLATE), 200)

    def tearDown(self):
        (onboarding.MEMORY_FILE, onboarding.CURRICULUM_FILE,
         onboarding.INBOX_DIR) = self._old
        self.tmp.cleanup()

    def study_all(self, ts: float):
        onboarding.CURRICULUM_FILE.write_text(json.dumps(
            {t: {"ts": int(ts)} for t in onboarding.FIRST_TOPICS}))

    def test_the_seeded_template_is_not_something_learned(self):
        now = time.time()
        self.study_all(now)
        progress = onboarding.learning_progress(now)
        self.assertTrue(progress["complete"])
        self.assertEqual(progress["memory_lines"], 0)
        self.assertFalse(progress["memory_ready"])

    def test_a_fact_still_in_the_inbox_is(self):
        now = time.time()
        self.study_all(now)
        (onboarding.INBOX_DIR / "1-study.jsonl").write_text(
            json.dumps({"fact": "The heating is a heat pump",
                        "source": "study"}) + "\n"
            + json.dumps({"fact": "FORGET: something", "source": "x"}) + "\n")
        progress = onboarding.learning_progress(now)
        self.assertEqual(progress["pending_facts"], 1)
        self.assertTrue(progress["memory_ready"])

    def test_five_sessions_that_found_nothing_open_the_step_eventually(self):
        then = time.time() - onboarding.READY_AFTER_S - 5
        self.study_all(then)
        self.assertTrue(onboarding.learning_progress()["memory_ready"])

    def test_what_the_studies_found_reaches_the_recommend_prompt(self):
        blocks = "\n".join(onboarding._shared_blocks(
            TEMPLATE, pending=["The heating is a heat pump"]))
        self.assertIn("nothing filed into memory yet", blocks)
        self.assertIn("NOT YET FILED INTO MEMORY", blocks)
        self.assertIn("- The heating is a heat pump", blocks)
        self.assertNotIn("## Devices", blocks)


if __name__ == "__main__":
    unittest.main()
