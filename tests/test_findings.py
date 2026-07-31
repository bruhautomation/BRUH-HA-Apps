#!/usr/bin/env python3
"""Tests for Findings — the work list and the one path that changes the house.

Three things worth pinning here, because getting any of them wrong is
expensive in a way a screenshot wouldn't show:

  * a problem is reported ONCE, across every status. Re-raising something the
    homeowner dismissed is exactly what the dismiss button buys off, so the
    dedup has to survive settling, not just be a within-run guard.
  * "Fix it" is the only tool-enabled Claude invocation in the panel, and it
    edits a real home. It must be reachable only by pressing the button, it
    must share the generation queue (one Claude at a time), and a run that
    dies has to leave the finding in a state you can see rather than stuck
    on "fixing" forever.
  * a fix reply that can't be parsed still means the house was touched, so it
    reports as a failure carrying the tail rather than raising.
"""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import card_tags  # noqa: E402
import engine  # noqa: E402
import feedback_store  # noqa: E402
import findings_store  # noqa: E402
import fixer  # noqa: E402
import hypotheses  # noqa: E402
import knowledge_store  # noqa: E402
import onboarding  # noqa: E402
import prompt_store  # noqa: E402
import settings_store  # noqa: E402
import user_categories  # noqa: E402


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR)
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "inbox"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR) = self._old
        self.tmp.cleanup()


class TestFindingsStore(StoreCase):
    def test_add_and_shape(self):
        entry, created = findings_store.add(
            "Back Door battery is dead",
            detail="0% since Jul 12", fix="Replace the CR2032",
            severity="serious", fixable=False,
            entity_id="sensor.back_door_battery", source="health",
            source_title="Device Health")
        self.assertTrue(created)
        self.assertEqual(entry["status"], "open")
        self.assertEqual(entry["severity"], "serious")
        self.assertFalse(entry["fixable"])
        self.assertEqual(entry["entity_id"], "sensor.back_door_battery")
        self.assertEqual(findings_store.open_count(), 1)

    def test_a_bogus_severity_falls_back_rather_than_raising(self):
        entry, _ = findings_store.add("X", severity="catastrophic")
        self.assertEqual(entry["severity"], "warning")

    def test_blank_text_is_not_a_finding(self):
        entry, created = findings_store.add("   ")
        self.assertIsNone(entry)
        self.assertFalse(created)

    def test_dedup_survives_settling(self):
        """The point of Dismiss is that it sticks. A finding that comes back
        after being ignored — in the same words or a rewording — makes the
        button worthless."""
        findings_store.add("Back Door battery is dead")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "ignored")

        for wording in ("Back Door battery is dead",
                        "back door battery is dead!",
                        "  Back  Door   battery is dead  "):
            entry, created = findings_store.add(wording)
            self.assertFalse(created, f"{wording!r} came back as a new finding")
            self.assertEqual(entry["status"], "ignored")
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_ids_are_unique_within_one_second(self):
        """ts doubles as the id the panel acts on, and one insight run can
        report three findings inside the same second."""
        for text in ("A problem", "B problem", "C problem"):
            findings_store.add(text)
        ids = [f["ts"] for f in findings_store.list_all()]
        self.assertEqual(len(set(ids)), 3)

    def test_lifecycle_and_live_filter(self):
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]
        self.assertEqual(len(findings_store.list_all("live")), 1)
        findings_store.set_status(ts, "fixing")
        self.assertEqual(len(findings_store.list_all("live")), 1)
        entry = findings_store.set_status(ts, "fixed", result="Reloaded it",
                                          changed=["automation.x — trigger fixed"])
        self.assertEqual(entry["result"], "Reloaded it")
        self.assertEqual(entry["changed"], ["automation.x — trigger fixed"])
        self.assertTrue(entry["settled_at"])
        self.assertEqual(findings_store.list_all("live"), [])
        self.assertEqual(findings_store.open_count(), 0)

    def test_a_failed_fix_still_needs_you(self):
        """failed and needs_you both stay on the badge — a fix that didn't
        work is not a problem that went away."""
        findings_store.add("A")
        findings_store.add("B")
        a, b = findings_store.list_all()[1], findings_store.list_all()[0]
        findings_store.set_status(a["ts"], "failed")
        findings_store.set_status(b["ts"], "needs_you")
        self.assertEqual(findings_store.open_count(), 2)

    def test_unknown_status_is_a_programming_error(self):
        findings_store.add("A")
        ts = findings_store.list_all()[0]["ts"]
        with self.assertRaises(ValueError):
            findings_store.set_status(ts, "sorted")

    def test_set_status_on_a_ghost_returns_none(self):
        self.assertIsNone(findings_store.set_status(999, "fixed"))

    def test_remove_lets_it_be_reported_again(self):
        """Unlike ignoring, forgetting is not a judgement — the finding can
        legitimately come back."""
        findings_store.add("A")
        ts = findings_store.list_all()[0]["ts"]
        self.assertTrue(findings_store.remove(ts))
        self.assertFalse(findings_store.is_known("A"))
        _, created = findings_store.add("A")
        self.assertTrue(created)

    def test_pruning_drops_settled_before_open(self):
        """An open finding is live work. Dropping it silently to make room is
        how a real problem disappears without ever being fixed."""
        for i in range(findings_store.MAX_FINDINGS):
            findings_store.add(f"Old settled problem {i}")
        for f in findings_store.list_all():
            findings_store.set_status(f["ts"], "fixed")
        findings_store.add("A brand new open problem")
        texts = [f["text"] for f in findings_store.list_all()]
        self.assertIn("A brand new open problem", texts)
        self.assertLessEqual(len(texts), findings_store.MAX_FINDINGS)

    def test_prompt_block_names_both_lists(self):
        findings_store.add("Still open")
        findings_store.add("Waved off")
        waved = next(f for f in findings_store.list_all() if f["text"] == "Waved off")
        findings_store.set_status(waved["ts"], "ignored")
        block = findings_store.prompt_block()
        self.assertIn("ALREADY ON THE FINDINGS LIST", block)
        self.assertIn("Still open", block)
        self.assertIn("DISMISSED", block)
        self.assertIn("Waved off", block)

    def test_prompt_block_is_empty_when_nothing_is_known(self):
        self.assertEqual(findings_store.prompt_block(), "")

    def test_a_fix_orphaned_by_a_restart_is_recoverable(self):
        """"fixing" is claimed on disk but owned by an in-memory job. A
        restart mid-fix orphans it: the row still says fixing, the job that
        would settle it is gone, and the tab offers no buttons in that
        status — so the finding becomes permanently unreachable."""
        findings_store.add("Automation can't fire")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "fixing")

        self.assertEqual(findings_store.reconcile_running("brAIn restarted"), 1)
        entry = findings_store.get(ts)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("restarted", entry["result"])
        # back on the badge, and Try again is offered
        self.assertEqual(findings_store.open_count(), 1)
        # nothing else is touched, and a second pass is a no-op
        self.assertEqual(findings_store.reconcile_running("again"), 0)

    def test_a_running_fix_is_not_counted_as_a_decision(self):
        """The badge is "things waiting on you". A fix already in flight is
        waiting on Claude, not on the homeowner."""
        findings_store.add("A")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "fixing")
        self.assertEqual(findings_store.open_count(), 0)
        self.assertEqual(len(findings_store.list_all("live")), 1)

    def test_add_many_writes_once_and_dedupes_within_the_batch(self):
        """A study session filing five findings must not rewrite the store
        five times — that is five SD-card erase cycles for one batch."""
        writes = []
        real_write = findings_store._write
        findings_store._write = lambda items: (writes.append(len(items)),
                                               real_write(items))[1]
        try:
            created = findings_store.add_many([
                {"text": "One"}, {"text": "Two"},
                {"text": "one"},        # same as the first, normalized
                {"text": "   "},        # nothing there
                "not a dict",
            ])
        finally:
            findings_store._write = real_write
        self.assertEqual([f["text"] for f in created], ["One", "Two"])
        self.assertEqual(len(writes), 1, "add_many rewrote the store per item")

    def test_coerce_is_the_one_reader_of_the_wire_shape(self):
        """Both producers — a model reply and an inbox line — hand over the
        same loose shape, so both go through one coercion."""
        entry = findings_store.coerce({"finding": "  Stuck sensor  ",
                                       "severity": "SERIOUS", "fixable": False})
        self.assertEqual(entry["text"], "Stuck sensor")
        self.assertEqual(entry["severity"], "serious")
        self.assertFalse(entry["fixable"])
        # absent means fixable; only an explicit false means hands required
        self.assertTrue(findings_store.coerce({"text": "x"})["fixable"])
        self.assertIsNone(findings_store.coerce({"text": "  "}))
        self.assertIsNone(findings_store.coerce("nope"))


class TestFindingsInbox(StoreCase):
    """Study sessions run on the CLI side and must be able to file what they
    found without the panel being up — same hand-off as the memory inbox."""

    def _write(self, name, *objs):
        findings_store.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (findings_store.INBOX_DIR / name).write_text(
            "".join(json.dumps(o) + "\n" for o in objs), encoding="utf-8")

    def test_sweep_folds_in_and_consumes(self):
        self._write("1-study-devices.jsonl",
                    {"text": "Hall motion offline nightly", "severity": "warning",
                     "fix": "Re-pair it", "fixable": False,
                     "source": "study:devices", "source_title": "Study: devices"})
        self.assertEqual(findings_store.sweep_inbox(), 1)
        entry = findings_store.list_all()[0]
        self.assertEqual(entry["text"], "Hall motion offline nightly")
        self.assertEqual(entry["source"], "study:devices")
        self.assertFalse(entry["fixable"])
        # consumed, so a second sweep is a no-op rather than a duplicate
        self.assertEqual(findings_store.sweep_inbox(), 0)
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_a_torn_line_does_not_wedge_the_tab(self):
        """A study session killed mid-write leaves half a line behind. That
        must cost its own line and nothing else."""
        findings_store.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (findings_store.INBOX_DIR / "1.jsonl").write_text(
            json.dumps({"text": "Good one"}) + "\n{\"text\": \"tor",
            encoding="utf-8")
        self.assertEqual(findings_store.sweep_inbox(), 1)
        self.assertEqual([f["text"] for f in findings_store.list_all()], ["Good one"])

    def test_missing_inbox_is_fine(self):
        self.assertEqual(findings_store.sweep_inbox(), 0)


class TestFixParsing(unittest.TestCase):
    def test_parses_a_clean_reply(self):
        parsed = fixer.parse_result(json.dumps({
            "ok": True, "needs_you": False, "summary": "Corrected the trigger.",
            "changed": ["automation.morning_lights — trigger entity corrected"],
            "verified": "Re-read the automation; it now references the live entity.",
            "also_found": ["The porch light has no area"],
        }))
        self.assertTrue(parsed["ok"])
        self.assertEqual(len(parsed["changed"]), 1)
        self.assertIn("Corrected the trigger.", fixer.result_text(parsed))
        self.assertIn("Verified:", fixer.result_text(parsed))

    def test_tolerates_a_code_fence(self):
        parsed = fixer.parse_result(
            '```json\n{"ok": true, "summary": "Done", "changed": []}\n```')
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["summary"], "Done")

    def test_needs_you_can_never_read_as_fixed(self):
        """A model that ticks both is claiming it fixed something only hands
        can fix. The finding must not settle as done."""
        parsed = fixer.parse_result(json.dumps({
            "ok": True, "needs_you": True, "summary": "Replace the battery."}))
        self.assertFalse(parsed["ok"])
        self.assertTrue(parsed["needs_you"])

    def test_an_unreadable_reply_is_a_failure_that_says_so(self):
        """The run may already have edited the house. Raising here would lose
        that; silence would be worse."""
        parsed = fixer.parse_result("I had a go at it and things happened.")
        self.assertFalse(parsed["ok"])
        self.assertIn("unreadable", parsed["summary"])
        self.assertIn("things happened", parsed["summary"])

    def test_prompt_carries_the_finding_and_the_memory(self):
        prompt = fixer.build_prompt(
            {"text": "Back Door battery is dead", "detail": "0% since Jul 12",
             "fix": "Replace the CR2032", "entity_id": "sensor.back_door_battery",
             "fixable": False, "source_title": "Device Health"},
            memory="## Device notes\n- The garage fridge runs 24/7 on purpose")
        self.assertIn("Back Door battery is dead", prompt)
        self.assertIn("sensor.back_door_battery", prompt)
        self.assertIn("starting hypothesis", prompt,
                      "the proposed fix must not read as an instruction")
        self.assertIn("garage fridge", prompt)
        self.assertIn("needing a human", prompt)

    def test_the_system_prompt_states_the_hard_rules(self):
        """These are the rules that keep an agentic run off the rails in
        somebody's actual house. Losing one silently is the failure mode."""
        for rule in ("NEVER delete", "NEVER restart", "secrets.yaml",
                     "smallest change", "one problem"):
            self.assertIn(rule.lower(), fixer.FIX_SYSTEM.lower(),
                          f"the fix contract dropped: {rule}")


class ServerCase(unittest.TestCase):
    """The panel with every store pointed at a temp dir."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = Path(self.tmp.name)
        self._olds = (
            findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
            card_tags.TAGS_FILE, self.server.INSIGHTS_DIR,
            self.server.MEMORY_INBOX_DIR, self.server.SHARED_MEMORY_FILE,
            prompt_store.OVERRIDES_FILE, feedback_store.FEEDBACK_FILE,
            user_categories.USER_CATS_FILE, knowledge_store.KNOWLEDGE_FILE,
            engine.AUTH_FILE, engine.SHARED_AUTH_FILE, engine.CLAUDE_HOME,
        )
        findings_store.FINDINGS_FILE = tmp / "findings.json"
        findings_store.INBOX_DIR = tmp / "findings-inbox"
        card_tags.TAGS_FILE = tmp / "card_tags.json"
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
        # A credential has to exist: pressing Fix without one is rejected.
        engine.CLAUDE_HOME = os.path.join(self.tmp.name, "home")
        engine.SHARED_AUTH_FILE = os.path.join(self.tmp.name, "shared.json")
        # SECRETS_DIR too, not just AUTH_FILE: save_auth() mkdirs it, and the
        # default is /data — writable for root, denied for everyone else, so
        # skipping it passes locally and fails in CI.
        engine.SECRETS_DIR = os.path.join(self.tmp.name, "secrets")
        engine.AUTH_FILE = os.path.join(self.tmp.name, "auth.json")
        self.server.CARD_TOKEN_FILE = tmp / "secrets" / "card_token"
        self.server.WWW_CARD_DIR = tmp / "www" / "brain"
        engine.save_auth("sk-ant-oat01-" + "x" * 30)
        # NOTHING in these tests may reach the real Claude CLI. make_app()
        # starts a worker and an auth check on startup, and this container
        # happens to have `claude` on PATH — without these stubs the suite
        # spawns real agentic runs and hangs.
        self._old_engine = (engine.run_claude, engine.run_agent)
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": "OK", "error": "", "meta": {}}
        engine.run_agent = lambda *a, **k: {
            "ok": True, "text": json.dumps({"ok": True, "summary": "stub"}),
            "error": "", "meta": {}}
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        (engine.run_claude, engine.run_agent) = self._old_engine
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         card_tags.TAGS_FILE, self.server.INSIGHTS_DIR,
         self.server.MEMORY_INBOX_DIR, self.server.SHARED_MEMORY_FILE,
         prompt_store.OVERRIDES_FILE, feedback_store.FEEDBACK_FILE,
         user_categories.USER_CATS_FILE, knowledge_store.KNOWLEDGE_FILE,
         engine.AUTH_FILE, engine.SHARED_AUTH_FILE, engine.CLAUDE_HOME) = self._olds
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        return TestClient(TestServer(self.server.make_app()))


class TestFindingRoutes(ServerCase):
    def test_the_list_sweeps_the_inbox(self):
        findings_store.INBOX_DIR.mkdir(parents=True, exist_ok=True)
        (findings_store.INBOX_DIR / "1.jsonl").write_text(
            json.dumps({"text": "Found while studying"}) + "\n", encoding="utf-8")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.get("/api/findings")).json()
                self.assertEqual([f["text"] for f in data["findings"]],
                                 ["Found while studying"])
                self.assertEqual(data["open"], 1)
            finally:
                await client.close()

        asyncio.run(run())

    def test_ignore_done_and_reopen(self):
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/ignore")).json()
                self.assertEqual(data["findings"][0]["status"], "ignored")
                self.assertEqual(data["open"], 0)

                await client.post(f"/api/finding/{ts}/reopen")
                self.assertEqual(findings_store.get(ts)["status"], "open")

                data = await (await client.post(f"/api/finding/{ts}/done")).json()
                self.assertEqual(data["findings"][0]["status"], "fixed")
                # resolving it yourself is durable knowledge about the home
                queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
                self.assertTrue(queued)
                self.assertIn("Sensor stuck", queued[0].read_text())
            finally:
                await client.close()

        asyncio.run(run())

    def test_delete_removes_it(self):
        findings_store.add("Sensor stuck")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.delete(f"/api/finding/{ts}")).json()
                self.assertEqual(data["findings"], [])
                self.assertEqual((await client.delete(f"/api/finding/{ts}")).status, 404)
                self.assertEqual((await client.post("/api/finding/nope/fix")).status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_fix_queues_a_job_and_never_runs_on_its_own(self):
        """Nothing may change the house except a press of this button — so
        the route is the only thing that enqueues a fix, and a second press
        while one is in flight is refused rather than queued behind it."""
        findings_store.add("Automation can't fire")
        ts = findings_store.list_all()[0]["ts"]
        old_run_fix = self.server._run_fix

        async def run():
            gate = asyncio.Event()
            started = asyncio.Event()

            async def held(job_id):
                started.set()
                await gate.wait()

            self.server._run_fix = held
            client = self._client()
            await client.start_server()
            try:
                data = await (await client.post(f"/api/finding/{ts}/fix")).json()
                self.assertEqual(data["findings"][0]["status"], "fixing")
                job = self.server.JOBS[f"{self.server.FIX_JOB_PREFIX}{ts}"]
                self.assertEqual(job["kind"], "fix")
                self.assertEqual(job["finding_ts"], ts)
                await asyncio.wait_for(started.wait(), 5)

                # a second press while it's in flight is refused, not queued
                self.assertEqual(
                    (await client.post(f"/api/finding/{ts}/fix")).status, 409)
            finally:
                gate.set()
                await client.close()
                self.server._run_fix = old_run_fix

        asyncio.run(run())

    def test_fix_without_a_credential_is_refused(self):
        engine.clear_auth()
        findings_store.add("Automation can't fire")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                self.assertEqual(
                    (await client.post(f"/api/finding/{ts}/fix")).status, 400)
                self.assertEqual(findings_store.get(ts)["status"], "open")
            finally:
                await client.close()

        asyncio.run(run())


class TestSnooze(StoreCase):
    """"Remind me later" and "not a problem" are different answers.

    The second is permanent and is fed back into every future analysis so
    the same non-problem is never raised again. Using it for the first would
    quietly throw away a real problem you meant to come back to — so snooze
    must not touch the status at all.
    """

    def test_snoozing_leaves_the_finding_exactly_as_open_as_it_was(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        shaped = findings_store.snooze(ts, int(time.time()) + 3600)
        self.assertEqual(shaped["status"], "open")
        self.assertEqual(findings_store.get(ts)["status"], "open")
        self.assertTrue(findings_store.is_snoozed(shaped))

    def test_a_snoozed_finding_stops_asking(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        self.assertEqual(findings_store.open_count(), 1)
        findings_store.snooze(ts, int(time.time()) + 3600)
        self.assertEqual(findings_store.open_count(), 0)
        self.assertEqual(findings_store.listing()["open"], 0)
        self.assertEqual(findings_store.listing()["snoozed"], 1)
        self.assertEqual(findings_store.list_all("live"), [])

    def test_a_snoozed_finding_is_findable_rather_than_vanished(self):
        """The point of "later" is that it comes back, and something you
        cannot find has not come back."""
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.snooze(ts, int(time.time()) + 3600)
        self.assertEqual([f["text"] for f in findings_store.list_all("snoozed")],
                         ["Battery low"])
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_it_comes_back_on_its_own(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.snooze(ts, int(time.time()) - 1)   # already due
        self.assertEqual(findings_store.open_count(), 1)
        self.assertEqual(len(findings_store.list_all("live")), 1)
        self.assertEqual(findings_store.list_all("snoozed"), [])

    def test_it_can_be_brought_back_by_hand(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]
        findings_store.snooze(ts, int(time.time()) + 3600)
        findings_store.snooze(ts, 0)
        self.assertEqual(findings_store.open_count(), 1)

    def test_snoozing_an_unknown_finding_is_not_an_error(self):
        self.assertIsNone(findings_store.snooze(1, int(time.time()) + 60))


class TestSnoozeAndDiscussRoutes(ServerCase):
    def test_the_snooze_route_takes_a_duration_and_gives_it_back(self):
        findings_store.add("Battery low")
        ts = findings_store.list_all()[0]["ts"]

        async def run():
            client = self._client()
            await client.start_server()
            try:
                before = int(time.time())
                data = await (await client.post(
                    f"/api/finding/{ts}/snooze", json={"for": "week"})).json()
                self.assertEqual(data["open"], 0)
                self.assertEqual(data["snoozed"], 1)
                until = findings_store.get(ts)["snoozed_until"]
                self.assertGreaterEqual(until, before + 7 * 86400 - 5)
                # Still open. Snoozing is not a decision.
                self.assertEqual(findings_store.get(ts)["status"], "open")

                data = await (await client.post(
                    f"/api/finding/{ts}/snooze", json={"for": "now"})).json()
                self.assertEqual(data["open"], 1)

                resp = await client.post(
                    f"/api/finding/{ts}/snooze", json={"for": "forever"})
                self.assertEqual(resp.status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_discussing_a_finding_hands_it_to_the_chat_read_only(self):
        """The discussion is for understanding it. "Explain this to me" and
        "go change my house" are different consents, and Fix it is the one
        that gives the second."""
        findings_store.add("Porch light never comes on",
                           detail="The trigger cannot fire",
                           fix="Invert the condition", entity_id="light.porch")
        ts = findings_store.list_all()[0]["ts"]
        sent = []

        async def run():
            import chat_session
            client = self._client()
            await client.start_server()

            async def fake_send(text):
                sent.append(text)
                return {"ok": True}

            session = chat_session.session()
            original, session.send = session.send, fake_send
            try:
                data = await (await client.post(
                    f"/api/finding/{ts}/discuss")).json()
                self.assertTrue(data["ok"])
                self.assertEqual(data["finding"]["ts"], ts)
            finally:
                session.send = original
                await client.close()

        asyncio.run(run())
        self.assertEqual(len(sent), 1)
        prompt = sent[0]
        self.assertIn("Porch light never comes on", prompt)
        self.assertIn("The trigger cannot fire", prompt)
        self.assertIn("Invert the condition", prompt)
        self.assertIn("light.porch", prompt)
        self.assertIn("Do not change anything", prompt)

    def test_discussing_a_finding_that_does_not_exist_is_a_404(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/finding/1/discuss")
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())


class TestFixRun(ServerCase):
    def setUp(self):
        super().setUp()
        self._old_agent = engine.run_agent
        findings_store.add("Automation can't fire", fix="Correct the trigger")
        self.ts = findings_store.list_all()[0]["ts"]
        self.job = f"{self.server.FIX_JOB_PREFIX}{self.ts}"

    def tearDown(self):
        engine.run_agent = self._old_agent
        super().tearDown()

    def _reply(self, obj):
        engine.run_agent = lambda *a, **k: {
            "ok": True, "text": json.dumps(obj), "error": "", "meta": {}}

    def _run(self):
        self.server._set_job(self.job, state="queued", kind="fix", finding_ts=self.ts)
        asyncio.run(self.server._run_fix(self.job))

    def test_a_successful_fix_settles_and_is_remembered(self):
        self._reply({"ok": True, "summary": "Trigger corrected.",
                     "changed": ["automation.morning_lights — trigger corrected"],
                     "verified": "Reloaded automations; it fires again."})
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "fixed")
        self.assertIn("Trigger corrected.", entry["result"])
        self.assertEqual(entry["changed"],
                         ["automation.morning_lights — trigger corrected"])
        self.assertEqual(self.server.JOBS[self.job]["state"], "done")
        # a later analysis must not rediscover a problem brAIn resolved
        queued = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
        self.assertTrue(queued, "the fix was not written into memory")
        self.assertIn("Automation can't fire", queued[0].read_text())

    def test_needs_you_does_not_read_as_fixed(self):
        self._reply({"ok": False, "needs_you": True,
                     "summary": "The CR2032 has to be replaced by hand."})
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "needs_you")
        self.assertEqual(findings_store.open_count(), 1)

    def test_side_findings_become_findings_not_edits(self):
        """Anything it notices on the way in is a new work item, never an
        edit it wasn't asked to make."""
        self._reply({"ok": True, "summary": "Done.", "changed": ["x — y"],
                     "also_found": ["The porch light has no area"]})
        self._run()
        texts = [f["text"] for f in findings_store.list_all()]
        self.assertIn("The porch light has no area", texts)

    def test_a_failed_run_leaves_a_visible_state_not_a_stuck_one(self):
        """A finding wedged on 'fixing' forever is unreachable from the UI —
        no button is offered in that state."""
        engine.run_agent = lambda *a, **k: {
            "ok": False, "text": "", "error": "claude timed out", "meta": {}}
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("claude timed out", entry["result"])
        self.assertEqual(self.server.JOBS[self.job]["state"], "error")

    def test_an_unparseable_reply_fails_loudly(self):
        self._reply_raw = None
        engine.run_agent = lambda *a, **k: {
            "ok": True, "text": "I did some stuff", "error": "", "meta": {}}
        self._run()
        entry = findings_store.get(self.ts)
        self.assertEqual(entry["status"], "failed")
        self.assertIn("unreadable", entry["result"])

    def test_a_deleted_finding_does_not_crash_the_worker(self):
        findings_store.remove(self.ts)
        self._run()
        self.assertEqual(self.server.JOBS[self.job]["state"], "error")

    def test_the_worker_dispatches_on_kind(self):
        """One queue serves cards and fixes; picking the wrong handler would
        try to generate an insight called 'fix-1234'."""
        self._reply({"ok": True, "summary": "Done.", "changed": []})
        seen = []
        old_generate = self.server._generate

        async def spy(job_id):
            seen.append(job_id)

        self.server._generate = spy
        try:
            async def run():
                self.server._enqueue(self.job, kind="fix", finding_ts=self.ts)
                worker = asyncio.ensure_future(self.server._worker())
                await self.server.QUEUE.join()
                worker.cancel()

            asyncio.run(run())
        finally:
            self.server._generate = old_generate
        self.assertEqual(seen, [], "a fix was handed to the insight generator")
        self.assertEqual(findings_store.get(self.ts)["status"], "fixed")


if __name__ == "__main__":
    unittest.main()
