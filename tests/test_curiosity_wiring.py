#!/usr/bin/env python3
"""Where an answer goes, and whether anything asks for one at all.

`tests/test_curiosity.py` drives the two modules that decide *what* is
worth asking. This drives the half in `server.py` that makes the feature
exist: the recorder in the checks pass, the three destinations an answer
has, and the two routes.

The claims worth testing here are the ones a module test cannot make.
A fact that was composed and a fact that reached the memory inbox are
different things, and only the second made the run worth its money — the
same reason `shadow_findings`' five "reaches nobody" claims are five
tests against the real stores rather than one about a set.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
# `import unittest.mock` rather than `from unittest import mock`: the
# repo's own convention (five other test files) and what clears CodeQL's
# py/import-and-import-from on the same module.
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))


class ServerCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.config = Path(base) / "config"
        self.config.mkdir()
        self.inbox = Path(base) / "memory" / "inbox"
        for key, value in {
            "BRAIN_CONFIG_DIR": str(self.config),
            "BRAIN_EDIT_JOURNAL": os.path.join(base, "edits"),
            "BRAIN_FINDINGS_FILE": os.path.join(base, "findings.json"),
            "BRAIN_FINDINGS_SETTLED": os.path.join(base, "settled.json"),
            "BRAIN_FINDINGS_STATE": os.path.join(base, "state.json"),
            "BRAIN_FINDINGS_INBOX": os.path.join(base, "finbox"),
            "BRAIN_JOURNAL_FILE": os.path.join(base, "journal.jsonl"),
            "BRAIN_MEMORY_DIR": os.path.join(base, "memory"),
            "BRAIN_MEMORY_INBOX": str(self.inbox),
            "BRAIN_HYPOTHESES_FILE": os.path.join(base, "hyp.jsonl"),
            "BRAIN_DIR": os.path.join(base, "insights"),
            "BRAIN_SETTINGS_FILE": os.path.join(base, "settings.json"),
            "BRAIN_KNOWLEDGE_FILE": os.path.join(base, "knowledge.json"),
            "BRAIN_DIAGNOSTICS_FILE": os.path.join(base, "diag.json"),
            "BRAIN_PROPOSALS_FILE": os.path.join(base, "proposals.json"),
            "BRAIN_MANUAL_LEDGER": os.path.join(base, "manual.json"),
            "BRAIN_CURIOSITY_STORE": os.path.join(base, "curiosity.json"),
            "BRAIN_ASK_WHY": "true",
        }.items():
            os.environ[key] = value
        import curiosity
        self.curiosity = importlib.reload(curiosity)
        import manual_ledger
        self.ledger = importlib.reload(manual_ledger)
        import hypotheses
        self.hypotheses = importlib.reload(hypotheses)
        import server
        self.server = importlib.reload(server)

    async def asyncTearDown(self):
        self.tmp.cleanup()

    def patch(self, target, name, value):
        """Replace an attribute and put it back afterwards.

        `server` imports its collaborators as modules, so
        `self.server.usage_store.budget_state = ...` mutates the **shared**
        module object — and `importlib.reload(server)` does not undo it,
        because it rebinds `server`'s names to the same already-mutated
        modules. Without this, these tests left `usage_store` and
        `settings_store` stubbed for the rest of the process and broke
        `test_insights_settings.py`, which passed alone and failed under
        the full suite: the same shared-table hazard `test_power_tools`
        documents about `sys.modules`.
        """
        patcher = unittest.mock.patch.object(target, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def inbox_facts(self) -> list[dict]:
        out = []
        for path in sorted(self.inbox.glob("*.jsonl")):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    out.append(json.loads(line))
        return out

    CANDIDATE = {
        "subject": "switch.sprinklers|on", "entity_id": "switch.sprinklers",
        "name": "Lawn sprinklers", "state": "on", "kind": "recurring",
        "at": "19:04", "days": 11, "span_days": 14, "events": 11,
        "when_days": "any day", "spread_min": 4.0, "cause": "person",
    }

    def answer(self, **kw) -> dict:
        base = {"confidence": "unknown", "because": "b", "fact": "",
                "ask": "", "evidence": []}
        base.update(kw)
        return self.curiosity.parse(base)


# ---------------------------------------------------------------------------
# The three destinations
# ---------------------------------------------------------------------------

class TestWhereAnAnswerGoes(ServerCase):

    async def test_an_explanation_reaches_the_memory_INBOX(self):
        """Not `memory.md`: one writer owns that document, which is what
        lets the terminal, voice, insights and study sessions all feed the
        same memory without a lock between them."""
        filed = self.server._file_curiosity(
            self.CANDIDATE,
            self.answer(confidence="explained",
                        fact="the lawn is in full sun until about six"))
        self.assertEqual(filed, "memory")
        facts = self.inbox_facts()
        self.assertEqual(len(facts), 1)
        self.assertIn("full sun", facts[0]["fact"])
        self.assertEqual(facts[0]["source"], "curiosity")

    async def test_the_panel_never_writes_the_memory_document_itself(self):
        self.server._file_curiosity(
            self.CANDIDATE,
            self.answer(confidence="explained", fact="a durable fact"))
        self.assertFalse((Path(os.environ["BRAIN_MEMORY_DIR"])
                          / "memory.md").exists())

    async def test_a_guess_reaches_the_HYPOTHESIS_queue(self):
        """Which is exactly what that queue is for: a claim brAIn believes
        and wants confirmed, appearing on the Findings tab as work waiting
        on a person and becoming a memory line when somebody ticks it."""
        filed = self.server._file_curiosity(
            self.CANDIDATE,
            self.answer(confidence="guess",
                        because="the garden faces west",
                        ask="Is it because of the afternoon sun?"))
        self.assertEqual(filed, "hypothesis")
        open_claims = self.hypotheses.list_all("open")
        self.assertEqual(len(open_claims), 1)
        # The reason travels in the claim: a question with no reasoning
        # under it is one nobody can answer well.
        self.assertIn("faces west", open_claims[0]["text"])
        self.assertIn("afternoon sun", open_claims[0]["text"])

    async def test_a_guess_rides_down_the_findings_payload(self):
        """The load-bearing claim. A hypothesis nothing renders is a
        question nobody will ever answer, and there is one list of things
        waiting on a person."""
        self.server._file_curiosity(
            self.CANDIDATE,
            self.answer(confidence="guess", because="b", ask="Is it?"))
        payload = self.server._findings_payload()
        self.assertEqual(len(payload["hypotheses"]), 1)
        # And it counts as work waiting, which is the only question a
        # badge on a work list answers.
        self.assertGreaterEqual(payload["open"], 1)

    async def test_an_unknown_files_nothing_anywhere(self):
        """A run that could not tell has learned nothing about the house,
        and "brAIn could not work out why" is a fact about brAIn."""
        filed = self.server._file_curiosity(
            self.CANDIDATE, self.answer(confidence="unknown"))
        self.assertEqual(filed, "")
        self.assertEqual(self.inbox_facts(), [])
        self.assertEqual(self.hypotheses.list_all("open"), [])

    async def test_a_refused_hypothesis_is_reported_and_not_an_error(self):
        """Three open questions is the whole design of that queue, and a
        fourth waiting behind them is what it exists to prevent."""
        for i in range(self.hypotheses.MAX_OPEN):
            self.assertTrue(self.hypotheses.propose(f"a standing claim {i}"))
        filed = self.server._file_curiosity(
            self.CANDIDATE,
            self.answer(confidence="guess", because="b", ask="Is it?"))
        self.assertEqual(filed, "hypothesis-refused")
        self.assertEqual(len(self.hypotheses.list_all("open")),
                         self.hypotheses.MAX_OPEN)


# ---------------------------------------------------------------------------
# The recorder, and the pass that asks
# ---------------------------------------------------------------------------

class TestTheCheckPassHook(ServerCase):

    def snapshot(self, available=True, actions=None):
        return {"actions": {"available": available,
                            "actions": actions or []}}

    async def test_the_recorder_files_what_a_pass_saw(self):
        rows = [{"ts": 1772000000 + d * 86400, "entity_id": "switch.pump",
                 "state": "on", "name": "Pump", "cause": "person"}
                for d in range(5)]
        self.assertEqual(
            self.server._record_manual(self.snapshot(actions=rows),
                                       1772500000), 5)

    async def test_a_logbook_that_could_not_be_read_files_nothing(self):
        """"I could not look" is not "nobody did anything" —
        `clear_resolved`'s rule, and here it is the difference between a
        quiet house and a logbook that 404'd."""
        rows = [{"ts": 1772000000, "entity_id": "switch.pump", "state": "on",
                 "name": "Pump", "cause": "person"}]
        self.assertEqual(
            self.server._record_manual(self.snapshot(False, rows),
                                       1772500000), 0)
        self.assertEqual(self.ledger.load()["rows"], [])

    async def test_the_recorder_never_fails_the_pass_that_saw_it(self):
        """Accounting must not fail the run it is accounting for — the
        same rule `journal.record` carries."""
        self.assertEqual(self.server._record_manual({"actions": None}, 0), 0)
        self.assertEqual(self.server._record_manual({}, 0), 0)

    async def test_the_option_off_means_no_run_is_ever_spawned(self):
        os.environ["BRAIN_ASK_WHY"] = "false"
        try:
            self.assertFalse(self.server._curiosity_enabled())
            self.assertEqual(await self.server._ask_why(1772500000), 0)
        finally:
            os.environ["BRAIN_ASK_WHY"] = "true"

    async def test_it_is_on_by_default(self):
        """It is the feature rather than an extra, and what bounds its
        cost is the one-a-day budget rather than the switch."""
        os.environ.pop("BRAIN_ASK_WHY", None)
        try:
            self.assertTrue(self.server._curiosity_enabled())
        finally:
            os.environ["BRAIN_ASK_WHY"] = "true"

    async def test_nothing_to_wonder_about_spawns_nothing(self):
        """A pass with an empty ledger costs one read of a JSON file, which
        is the whole reason this is not a million conversations."""
        calls = []
        self.patch(self.server.engine, "run_analyst",
                   lambda *a, **k: calls.append(a))
        # Gates open, so this really is "there is nothing to ask about"
        # rather than a gate answering for it.
        self.patch(self.server.engine, "get_auth",
                   lambda: {"type": "oauth_token"})
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": False})
        self.assertEqual(await self.server._ask_why(1772500000), 0)
        self.assertEqual(calls, [])

    async def test_a_pass_asks_at_most_once_and_settles_before_running(self):
        """Settled BEFORE the run: one that crashes having spent the money
        must not leave the identical question to be asked again in six
        hours for ever."""
        base = 1772000000
        rows = []
        for day in range(12):
            rows.append({"ts": base + day * 86400 + 19 * 3600,
                         "entity_id": "switch.sprinklers", "state": "on",
                         "name": "Lawn sprinklers", "cause": "person"})
        now = base + 13 * 86400
        self.server._record_manual({"actions": {"available": True,
                                                "actions": rows}}, now)
        seen = []

        def boom(*a, **k):
            seen.append(a)
            raise RuntimeError("the CLI fell over")

        self.patch(self.server.engine, "run_analyst", boom)
        self.patch(self.server, "_house_prompt_block",
                   lambda *a, **k: _async(""))
        # The three gates a scheduled run answers to, opened — see
        # TestTheScheduledRunAnswersToTheUsualGates for what they are and
        # why the pressed route skips one of them.
        self.patch(self.server.engine, "get_auth",
                   lambda: {"type": "oauth_token"})
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": False})
        asked = await self.server._ask_why(now)
        self.assertEqual(asked, self.curiosity.MAX_PER_PASS)
        self.assertEqual(len(seen), self.curiosity.MAX_PER_PASS)
        store = self.curiosity.load()
        self.assertEqual(len(store["asked"]), 1)
        entry = next(iter(store["asked"].values()))
        self.assertEqual(entry["status"], "failed")
        # And the same pass again asks nothing, because the subject is
        # settled whatever happened to the run.
        self.assertEqual(await self.server._ask_why(now), 0)


async def _async(value):
    return value


# ---------------------------------------------------------------------------
# The routes, because a feature reachable only from a checks pass is one
# nobody can try
# ---------------------------------------------------------------------------

class TestTheRoutes(ServerCase):

    def routes(self) -> set[str]:
        app = self.server.make_app()
        return {r.resource.canonical for r in app.router.routes()
                if r.resource is not None}

    async def test_both_routes_are_registered(self):
        """A route with no caller is a button nobody can press; a handler
        with no route is worse."""
        have = self.routes()
        self.assertIn("/api/curiosity", have)
        self.assertIn("/api/curiosity/ask", have)

    async def test_the_panel_calls_them(self):
        """The other half of the same rule. `h_baselines_run` existed for
        releases with no caller anywhere, which is why this is asserted
        rather than assumed."""
        app_js = (PANEL / "app.js").read_text(encoding="utf-8")
        self.assertIn("api/curiosity/ask", app_js)
        self.assertIn('api("api/curiosity")', app_js)
        self.assertIn("diagCurious",
                      (PANEL / "index.html").read_text(encoding="utf-8"))

    async def test_asking_with_nothing_to_ask_about_is_refused(self):
        class R:
            pass
        resp = await self.server.h_curiosity_ask(R())
        self.assertEqual(resp.status, 409)
        self.assertIn("account for", json.loads(resp.text)["error"])

    async def test_the_diagnostics_section_survives_an_empty_house(self):
        """Six sections and a sentence about the seventh is a screen
        somebody can read; a 500 is not."""
        payload = self.server._curiosity_diagnostics()
        self.assertNotIn("error", payload)
        self.assertIn("budget", payload)
        self.assertIn("evidence", payload)
        self.assertEqual(payload["curious_total"], 0)

    async def test_the_run_claims_its_own_session_source(self):
        """A rail offering somebody "Somebody in this home did something by
        hand…" as something they typed is the person's own chats buried
        under machine ones again."""
        import run_sources
        self.assertIn("curiosity", run_sources.SOURCES)
        self.assertIn("curiosity", run_sources.ENGINE_SOURCES)
        shell = (BASE_DIR / "brain" / "scripts"
                 / "brain-run-source.sh").read_text(encoding="utf-8")
        self.assertIn("curiosity", shell)


if __name__ == "__main__":
    unittest.main()


class TestTheScheduledRunAnswersToTheUsualGates(ServerCase):
    """A curiosity run on the checks pass is a scheduled Claude run, so it
    answers to the three gates every scheduled Claude run answers to —
    `_offer_milestones`' rule. The pressed route deliberately does not,
    because "automatic insights pause; asking by hand always runs" is one
    promise with two halves, and a feature that kept spending after the
    pause would break the half people actually notice.
    """

    async def arm(self):
        """A house with a real shape in it, so only the gates can stop it."""
        base = 1772000000
        rows = [{"ts": base + d * 86400 + 19 * 3600,
                 "entity_id": "switch.sprinklers", "state": "on",
                 "name": "Lawn sprinklers", "cause": "person"}
                for d in range(12)]
        now = base + 13 * 86400
        self.server._record_manual({"actions": {"available": True,
                                                "actions": rows}}, now)
        self.calls = []
        self.patch(self.server.engine, "run_analyst",
                   lambda *a, **k: self.calls.append(a))
        self.patch(self.server, "_house_prompt_block",
                   lambda *a, **k: _async(""))
        self.patch(self.server.engine, "get_auth",
                   lambda: {"type": "oauth_token"})
        return now

    async def test_it_runs_when_every_gate_is_open(self):
        """The control. Without this the three tests below would pass on a
        feature that never runs at all."""
        now = await self.arm()
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": False})
        self.assertEqual(await self.server._ask_why(now), 1)

    async def test_no_credential_spends_nothing(self):
        now = await self.arm()
        self.patch(self.server.engine, "get_auth", lambda: None)
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": False})
        self.assertEqual(await self.server._ask_why(now), 0)
        self.assertEqual(self.calls, [])

    async def test_automatic_generation_switched_off_spends_nothing(self):
        now = await self.arm()
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": False})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": False})
        self.assertEqual(await self.server._ask_why(now), 0)

    async def test_a_reached_usage_budget_spends_nothing(self):
        """The state whose whole promise is that the rest of the account is
        yours."""
        now = await self.arm()
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": True})
        self.assertEqual(await self.server._ask_why(now), 0)
        self.assertEqual(self.calls, [])

    async def test_nothing_was_settled_by_a_pass_that_could_not_run(self):
        """A subject is settled by an asking, and a gate is not one — so a
        paused house asks on the pass after it is unpaused, rather than
        having silently spent its questions while it was paused."""
        now = await self.arm()
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": True})
        await self.server._ask_why(now)
        self.assertEqual(self.curiosity.load()["asked"], {})


class TestEndToEnd(ServerCase):
    """One asking, from a ledger of presses to a fact in the memory inbox.

    The module tests prove the arithmetic and the destinations separately.
    This is the only test that proves they are joined up — the prompt is
    built, a reply comes back in the contract's shape, and the thing brAIn
    learned reaches the place every future prompt reads.
    """

    async def arm(self, reply: dict):
        # Anchored to the REAL clock, because `h_curiosity_ask` reads it
        # rather than taking a `now` — and with a fixed fixture date this
        # test passed through `_ask_why` and answered 409 on the route,
        # the rows being seven months old and correctly refused as a shape
        # that has stopped happening.
        now = time.time()
        rows = [{"ts": int(now - (12 - d) * 86400),
                 "entity_id": "switch.sprinklers", "state": "on",
                 "name": "Lawn sprinklers", "cause": "person"}
                for d in range(12)]
        self.server._record_manual({"actions": {"available": True,
                                                "actions": rows}}, now)
        self.prompts = []

        def analyst(prompt, system, *a, **k):
            self.prompts.append((prompt, system))
            return {"ok": True, "text": json.dumps(reply)}

        self.patch(self.server.engine, "run_analyst", analyst)
        self.patch(self.server, "_house_prompt_block",
                   lambda *a, **k: _async("The garden faces west."))
        self.patch(self.server, "_read_shared_memory",
                   lambda: "The front lawn is grass.")
        self.patch(self.server.engine, "get_auth",
                   lambda: {"type": "oauth_token"})
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": False})
        return now

    async def test_a_reason_worked_out_reaches_memory(self):
        now = await self.arm({
            "confidence": "explained",
            "because": "the garden is in full sun until about six",
            "fact": "the lawn sprinklers are run by hand on summer evenings, "
                    "once the sun is off the west-facing garden",
            "ask": "",
            "evidence": ["sun elevation at 19:00", "no rain in the week"]})
        self.assertEqual(await self.server._ask_why(now), 1)

        # The prompt was built from the real shape, and carries the two
        # blocks handed in rather than fetched.
        prompt, system = self.prompts[0]
        self.assertIn("switch.sprinklers", prompt)
        self.assertIn("Lawn sprinklers", prompt)
        self.assertIn("faces west", prompt)
        self.assertIn("front lawn is grass", prompt)
        self.assertEqual(system, self.curiosity.SYSTEM)

        # The fact reached the one place every future prompt reads.
        facts = self.inbox_facts()
        self.assertEqual(len(facts), 1)
        self.assertIn("west-facing garden", facts[0]["fact"])
        self.assertEqual(facts[0]["source"], "curiosity")

        # And the store records what was learned and where it went.
        entry = self.curiosity.load()["asked"]["switch.sprinklers|on"]
        self.assertEqual(entry["status"], "explained")
        self.assertEqual(entry["filed"], "memory")
        self.assertEqual(self.curiosity.recent(self.curiosity.load())[0]
                         ["filed"], "memory")

        # The subject is done, so a second pass spends nothing.
        self.assertEqual(await self.server._ask_why(now), 0)
        self.assertEqual(len(self.prompts), 1)

    async def test_a_guess_reaches_the_person(self):
        now = await self.arm({
            "confidence": "guess",
            "because": "the garden faces west, so the sun is likely on it "
                       "until early evening",
            "fact": "",
            "ask": "Is seven o'clock about the sun, or about the water rate?",
            "evidence": ["the garden's orientation"]})
        self.assertEqual(await self.server._ask_why(now), 1)
        payload = self.server._findings_payload()
        self.assertEqual(len(payload["hypotheses"]), 1)
        self.assertIn("water rate", payload["hypotheses"][0]["text"])
        self.assertEqual(self.inbox_facts(), [])

    async def test_a_reply_that_is_not_the_contract_files_nothing(self):
        """The one thing this must never do is let a malformed answer
        through as a fact: it would go into a home's memory as a sentence
        nothing ever questions again."""
        now = await self.arm({"confidence": "definitely", "because": "sun",
                              "fact": "a made-up fact"})
        self.assertEqual(await self.server._ask_why(now), 1)
        self.assertEqual(self.inbox_facts(), [])
        self.assertEqual(self.hypotheses.list_all("open"), [])
        entry = self.curiosity.load()["asked"]["switch.sprinklers|on"]
        self.assertEqual(entry["status"], "failed")
        self.assertIn("shape", entry["error"])

    async def test_an_explanation_with_no_fact_learns_nothing_and_says_so(self):
        """Demoted rather than believed — otherwise the subject is settled
        for ever having learned nothing, which is worse than not asking."""
        now = await self.arm({"confidence": "explained",
                              "because": "it seems obvious enough",
                              "fact": "", "ask": "", "evidence": []})
        await self.server._ask_why(now)
        self.assertEqual(self.inbox_facts(), [])
        entry = self.curiosity.load()["asked"]["switch.sprinklers|on"]
        self.assertEqual(entry["status"], "unknown")
        self.assertIn("durable fact", entry["downgraded"])

    async def test_the_pressed_route_runs_and_files_too(self):
        """The button is the whole difference between a feature and a
        schedule, so it gets the same end-to-end claim."""
        await self.arm({
            "confidence": "explained", "because": "the sun",
            "fact": "the sprinklers follow the sun off the garden",
            "ask": "", "evidence": ["sun elevation"]})

        class R:
            pass
        resp = await self.server.h_curiosity_ask(R())
        self.assertEqual(resp.status, 200)
        body = json.loads(resp.text)
        self.assertEqual(body["asked"], 1)
        self.assertIn("Lawn sprinklers", body["why"])
        # Started, not awaited — the outcome is read back off the route.
        for _ in range(50):
            if not self.server.CURIOSITY_STATE["starting"]:
                break
            await asyncio.sleep(0.01)
        self.assertFalse(self.server.CURIOSITY_STATE["starting"])
        self.assertEqual(len(self.inbox_facts()), 1)


class TestTheFaultSweep(ServerCase):
    """`reports.faults` is deliberately exhaustive — every surface the
    payload can say something went wrong on, read in one pass — and just as
    deliberately silent about refusals doing their job. Both halves are
    asserted, because a section that listed the quiet states is one people
    learn to skim, which is the failure that sweep was written against.
    """

    def faults(self, curiosity_section):
        import reports
        return reports.faults({"curiosity": curiosity_section})

    def rows(self, section):
        return [r for r in self.faults(section)
                if "Why you did something" in str(r.get("what", ""))
                or "Why you did something" in str(r)]

    async def test_a_section_that_could_not_be_read_is_a_fault(self):
        self.assertTrue(self.rows({"error": "no such file"}))

    async def test_a_run_that_spent_its_money_and_filed_nothing_is_a_fault(self):
        rows = self.rows({"enabled": True, "counts": {"failed": 2}})
        self.assertTrue(rows)
        self.assertIn("2", str(rows[0]))

    async def test_the_quiet_states_are_not_faults(self):
        """Off, still watching, nothing left to ask, and today's question
        already spent are four refusals doing their job."""
        for section in (
            {"enabled": False, "counts": {}},
            {"enabled": True, "counts": {"failed": 0},
             "evidence": {"state": "collecting"}},
            {"enabled": True, "counts": {"explained": 3, "unknown": 1},
             "curious_total": 0},
            {"enabled": True, "counts": {"guessed": 2},
             "holding": "brAIn has already asked 1 question today"},
        ):
            with self.subTest(section=section):
                self.assertEqual(self.rows(section), [], section)

    async def test_a_missing_section_says_nothing(self):
        import reports
        self.assertEqual(
            [r for r in reports.faults({}) if "Why you" in str(r)], [])
