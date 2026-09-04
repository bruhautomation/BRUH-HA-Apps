"""Accepting a proposal, end to end: write, reload, verify, settle, undo.

Driven against the real panel app and a real aiohttp server standing in
for Core, because the whole claim is about the order those five things
happen in. A stub of `_apply_accepted` would only prove the stub.

Each test names the mutation it catches:

  the row is settled last     settle before applying -> a yes that could
                              not be honoured is recorded as a yes and the
                              proposal is gone
  a reload failure reverts    drop the revert -> automations.yaml keeps a
                              block Home Assistant never loaded
  verification is real        trust the reload's 200 -> "the file was
                              written" reported as "the automation exists"
  undo reverses all three     put back the row only -> the automation goes
                              on running while the card offers it again
  the settled entry           drop the applied fields -> nothing can say
                              which automation an accept became
  a decline is untouched      route a decline through the writer -> saying
                              no writes to /config
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

EXISTING = """\
# Mine. Do not reformat.
- id: '1699999999999'
  alias: Porch light at dusk
  trigger:
    - platform: sun
      event: sunset
  action:
    - service: light.turn_on
      target:
        entity_id: light.porch
  mode: single
"""

INCLUDE = "default_config:\nautomation: !include automations.yaml\n"

TITLE = "Turn the hall lamp on at 18:40 on weekdays"


def proposal_obj(entity: str = "light.hall") -> dict:
    return {
        "kind": "automation",
        "title": TITLE,
        "why": "You have done this yourself on 9 of the last 10 weekdays",
        "source": "routine",
        "config": {
            "trigger": [{"platform": "time", "at": "18:40:00"}],
            "action": [{"service": "light.turn_on",
                        "target": {"entity_id": entity}}],
            "mode": "single",
        },
    }


class AcceptCase(unittest.IsolatedAsyncioTestCase):
    """A real /config, a real journal, a real panel and a fake Core."""

    # What Core does with a reload and a state lookup, per test.
    reload_status = 200
    entity_appears = True

    async def asyncSetUp(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = root / "config"
        self.config.mkdir()
        (self.config / "configuration.yaml").write_text(INCLUDE)
        (self.config / "automations.yaml").write_text(EXISTING)

        self._env = dict(os.environ)
        self.addCleanup(self._restore_env)
        os.environ["BRAIN_EDIT_JOURNAL"] = str(root / "edits")
        os.environ["BRAIN_CONFIG_DIR"] = str(self.config)
        os.environ["BRAIN_PROPOSALS_FILE"] = str(root / "proposals.json")
        os.environ["BRAIN_PROPOSALS_SETTLED"] = str(root / "settled.json")
        os.environ["BRAIN_PROPOSALS_SHARED"] = str(
            root / "nope" / "brain" / "proposals_state.json")
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        for name in ("proposals", "automation_writer"):
            sys.modules.pop(name, None)

        self.proposals = importlib.import_module("proposals")
        self.writer = importlib.import_module("automation_writer")
        self.server = importlib.import_module("server")
        self.server.proposals = self.proposals
        self.server.automation_writer = self.writer
        self.addCleanup(self._restore_modules,
                        self.server.proposals, self.server.automation_writer)

        # Nothing here should reach a real memory inbox or a notifier.
        self.memory: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str, str]] = []
        self._old_submit = self.server._submit_memory
        self._old_notify = self.server._findings_notify_target

        async def submit(fact, source="insights"):
            self.memory.append((fact, source))

        self.server._submit_memory = submit
        self.server._findings_notify_target = lambda: ("mobile_app_phone",
                                                       "warning")
        self.addCleanup(self._restore_server_hooks)

        # Fake Core. `automation.reload` and `/states/<id>` are the two
        # calls the accept path makes, and the two it has to believe.
        self.calls: list[str] = []
        self.live: set[str] = set()

        async def reload(request):
            self.calls.append(request.path)
            if self.reload_status != 200:
                return web.json_response({"message": "no"},
                                         status=self.reload_status)
            if self.entity_appears:
                self.live.add(
                    "automation.turn_the_hall_lamp_on_at_18_40_on_weekdays")
            return web.json_response([])

        async def state(request):
            eid = request.match_info["entity_id"]
            self.calls.append(request.path)
            if eid in self.live:
                return web.json_response({"entity_id": eid, "state": "on"})
            return web.json_response({"message": "not found"}, status=404)

        async def notify(request):
            body = await request.json()
            self.sent.append((request.match_info["service"],
                              body.get("title", ""), body.get("message", "")))
            return web.json_response([])

        core = web.Application()
        core.router.add_post("/services/automation/reload", reload)
        core.router.add_get("/states/{entity_id}", state)
        core.router.add_post("/services/notify/{service}", notify)
        self.core = TestServer(core)
        await self.core.start_server()
        self.addAsyncCleanup(self.core.close)

        import ha_data
        self.ha_data = ha_data
        self._core_api = ha_data.CORE_API
        ha_data.CORE_API = str(self.core.make_url("")).rstrip("/")
        self.addCleanup(self._restore_core)
        # The verification ceiling is a ceiling on a failure; a test that
        # spent twelve seconds on it would be a test nobody runs.
        self._old_wait = (self.server.ACCEPT_VERIFY_S,
                          self.server.ACCEPT_POLL_S)
        self.server.ACCEPT_VERIFY_S = 0.5
        self.server.ACCEPT_POLL_S = 0.05
        self.addCleanup(self._restore_wait)

        # `QUEUE` is a module-level asyncio.Queue and each test here gets
        # its own loop, so it is rebound rather than left bound to the
        # first one — otherwise the panel's own worker raises into a
        # traceback attributed to nothing.
        self.server.QUEUE = asyncio.Queue()
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()
        self.addAsyncCleanup(self.client.close)

    # -- teardown helpers -------------------------------------------------
    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env)
        for name in ("proposals", "automation_writer"):
            sys.modules.pop(name, None)

    def _restore_modules(self, proposals_mod, writer_mod):
        self.server.proposals = importlib.import_module("proposals")
        self.server.automation_writer = importlib.import_module(
            "automation_writer")

    def _restore_server_hooks(self):
        self.server._submit_memory = self._old_submit
        self.server._findings_notify_target = self._old_notify

    def _restore_core(self):
        self.ha_data.CORE_API = self._core_api

    def _restore_wait(self):
        (self.server.ACCEPT_VERIFY_S,
         self.server.ACCEPT_POLL_S) = self._old_wait

    # -- fixtures ---------------------------------------------------------
    def offer(self, **kw) -> dict:
        row = self.proposals.add(proposal_obj(**kw))
        self.assertIsNotNone(row)
        return row

    async def accept(self, ts, **body):
        resp = await self.client.post(f"/api/proposal/{ts}/accept", json=body)
        return resp.status, await resp.json()

    def automations(self) -> str:
        return (self.config / "automations.yaml").read_text()

    def rows(self):
        import yaml
        return yaml.safe_load(self.automations())


class TestAcceptWritesThenReloadsThenVerifies(AcceptCase):

    async def test_the_happy_path_writes_reloads_verifies_and_settles(self):
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        self.assertEqual(out["automation"], f"brain_{row['ts']}")
        self.assertEqual(
            out["entity_id"],
            "automation.turn_the_hall_lamp_on_at_18_40_on_weekdays")
        self.assertIn("undo", out)
        # The file, then Core, then the store.
        self.assertEqual(len(self.rows()), 2)
        self.assertIn("/services/automation/reload", self.calls)
        self.assertTrue(any(c.startswith("/states/") for c in self.calls))
        self.assertEqual(self.proposals.listing(), [])
        self.assertEqual(out["proposal"]["status"], "accepted")

    async def test_the_settled_entry_says_what_the_accept_became(self):
        row = self.offer()
        await self.accept(row["ts"])
        settled = self.proposals.settled_keys()[row["key"]]
        self.assertEqual(settled["status"], "accepted")
        self.assertEqual(settled["automation_id"], f"brain_{row['ts']}")
        self.assertEqual(
            settled["entity_id"],
            "automation.turn_the_hall_lamp_on_at_18_40_on_weekdays")

    async def test_it_records_a_memory_line_and_says_the_house_changed(self):
        row = self.offer()
        _status, out = await self.accept(row["ts"])
        self.assertIn(TITLE, out["learned"])
        self.assertEqual([f for f, _s in self.memory], [out["learned"]])
        self.assertEqual(len(self.sent), 1)
        service, title, message = self.sent[0]
        self.assertEqual(service, "mobile_app_phone")
        self.assertIn("change you accepted", title)
        self.assertIn(TITLE, message)

    async def test_the_user_s_file_above_the_block_is_untouched(self):
        row = self.offer()
        await self.accept(row["ts"])
        self.assertTrue(self.automations().startswith(EXISTING))

    async def test_a_second_accept_of_the_same_row_is_a_409(self):
        row = self.offer()
        await self.accept(row["ts"])
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409)
        self.assertIn("already been answered", out["error"])
        self.assertEqual(len(self.rows()), 2)


class TestAFailedAcceptChangesNothing(AcceptCase):
    reload_status = 500

    async def test_a_reload_failure_reverts_and_leaves_the_row_open(self):
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409)
        self.assertIn("reload", out["error"])
        # The file is back exactly as it was...
        self.assertEqual(self.automations(), EXISTING)
        # ...and the proposal is where it was, not accepted.
        live = self.proposals.listing()
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["status"], "proposed")
        self.assertEqual(self.proposals.settled_keys(), {})
        self.assertEqual(self.memory, [])
        self.assertEqual(self.sent, [])


class TestAWrittenFileIsNotARunningAutomation(AcceptCase):
    """The distinction `playback_check` draws, in this add-on."""
    entity_appears = False

    async def test_an_automation_that_never_appears_is_reverted(self):
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409)
        self.assertIn("never appeared", out["error"])
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(len(self.proposals.listing()), 1)

    async def test_the_reload_returned_200_and_that_was_not_enough(self):
        row = self.offer()
        await self.accept(row["ts"])
        self.assertIn("/services/automation/reload", self.calls)


class TestARefusalNeverSettles(AcceptCase):

    async def test_a_protected_entity_is_a_409_with_the_row_still_open(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.hall"
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409)
        self.assertIn("light.hall", out["error"])
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(len(self.proposals.listing()), 1)
        self.assertEqual(self.calls, [])

    async def test_no_include_line_is_a_409_and_nothing_is_written(self):
        (self.config / "configuration.yaml").write_text("default_config:\n")
        row = self.offer()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409)
        self.assertIn("automation: !include automations.yaml", out["error"])
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(len(self.proposals.listing()), 1)


class TestDecliningTouchesNothing(AcceptCase):

    async def test_a_decline_writes_no_automation_and_calls_no_service(self):
        row = self.offer()
        resp = await self.client.post(f"/api/proposal/{row['ts']}/decline",
                                      json={"note": "my partner works nights"})
        self.assertEqual(resp.status, 200)
        out = await resp.json()
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(self.calls, [])
        self.assertNotIn("undo", out)
        self.assertIn("works nights", out["learned"])

    async def test_an_unknown_verb_is_a_404(self):
        row = self.offer()
        resp = await self.client.post(f"/api/proposal/{row['ts']}/maybe")
        self.assertEqual(resp.status, 404)


class TestUndoReversesAllThree(AcceptCase):

    async def test_it_puts_back_the_file_the_reload_and_the_row(self):
        row = self.offer()
        _status, out = await self.accept(row["ts"])
        self.assertEqual(len(self.rows()), 2)

        resp = await self.client.post(f"/api/undo/{out['undo']}")
        self.assertEqual(resp.status, 200)
        undone = await resp.json()
        self.assertTrue(undone["undone"], undone.get("error"))
        self.assertTrue(undone["reverted"])
        self.assertTrue(undone["reloaded"])
        # The file is exactly what it was before the accept.
        self.assertEqual(self.automations(), EXISTING)
        # Core was asked to reload again.
        self.assertEqual(
            self.calls.count("/services/automation/reload"), 2)
        # The proposal is back, proposed, under its original id.
        live = self.proposals.listing()
        self.assertEqual(len(live), 1)
        self.assertEqual(live[0]["ts"], row["ts"])
        self.assertEqual(live[0]["status"], "proposed")
        # And the settled key is gone, so it can be offered again.
        self.assertEqual(self.proposals.settled_keys(), {})

    async def test_an_undo_that_cannot_revert_says_so_rather_than_claiming(self):
        """A press that reports success while the automation is still
        running is worse than one that reports the failure — the whole
        point of the token is that the person believes it."""
        row = self.offer()
        _status, out = await self.accept(row["ts"])
        journal_dir = Path(os.environ["BRAIN_EDIT_JOURNAL"]) / "snapshots"
        for snap in journal_dir.iterdir():
            snap.unlink()

        resp = await self.client.post(f"/api/undo/{out['undo']}")
        undone = await resp.json()
        self.assertFalse(undone["undone"])
        self.assertFalse(undone["reverted"])
        self.assertIn("snapshot", undone["error"])
        # The automation really is still there, which is what the answer
        # says: the block was not removed.
        self.assertEqual(len(self.rows()), 2)

    async def test_a_reload_that_fails_on_the_way_back_is_not_a_success(self):
        row = self.offer()
        _status, out = await self.accept(row["ts"])
        self.reload_status = 500
        resp = await self.client.post(f"/api/undo/{out['undo']}")
        undone = await resp.json()
        self.assertTrue(undone["reverted"])
        self.assertFalse(undone["reloaded"])
        self.assertFalse(undone["undone"])
        self.assertIn("still running", undone["error"])

    async def test_the_token_is_spent_and_a_second_press_is_a_404(self):
        row = self.offer()
        _status, out = await self.accept(row["ts"])
        first = await self.client.post(f"/api/undo/{out['undo']}")
        self.assertEqual(first.status, 200)
        second = await self.client.post(f"/api/undo/{out['undo']}")
        self.assertEqual(second.status, 404)

    async def test_reopening_refuses_over_an_occupied_id(self):
        """A proposal restored on top of a live row would throw away
        whatever has happened since — `findings_store.restore`'s rule."""
        row = self.offer()
        # The row is on the list, so putting it back would overwrite it.
        self.assertIsNone(self.proposals.reopen(row))
        self.proposals.decide(row["ts"], "declined")
        self.assertIsNotNone(self.proposals.reopen(row))
        self.assertEqual(len(self.proposals.listing()), 1)
        # And once it is back, a second undo cannot duplicate it.
        self.assertIsNone(self.proposals.reopen(row))
        self.assertEqual(len(self.proposals.listing()), 1)

    async def test_the_memory_line_is_dropped_from_the_inbox(self):
        """Driven through the panel's own inbox rather than a stub, so
        the id the undo computes is the id the queue holds."""
        self.server._submit_memory = self._old_submit
        inbox = Path(self.tmp.name) / "inbox"
        old_dir = self.server.MEMORY_INBOX_DIR
        self.server.MEMORY_INBOX_DIR = inbox
        self.addCleanup(setattr, self.server, "MEMORY_INBOX_DIR", old_dir)

        row = self.offer()
        _status, out = await self.accept(row["ts"])
        queued = [i["text"] for i in self.server._inbox_items()]
        self.assertIn(out["learned"], queued)

        await self.client.post(f"/api/undo/{out['undo']}")
        left = [i["text"] for i in self.server._inbox_items()]
        self.assertNotIn(out["learned"], left)


class TestTheJournalRecordsIt(AcceptCase):

    async def test_an_accept_is_one_line_with_the_applied_outcome(self):
        import journal
        old = journal.JOURNAL_FILE
        journal.JOURNAL_FILE = str(Path(self.tmp.name) / "journal.jsonl")
        self.addCleanup(setattr, journal, "JOURNAL_FILE", old)

        row = self.offer()
        await self.accept(row["ts"])
        lines = [json.loads(x) for x in
                 Path(journal.JOURNAL_FILE).read_text().splitlines() if x]
        applied = [x for x in lines if x["source"] == "proposal"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["outcome"], "applied")
        self.assertTrue(applied[0]["ok"])
        self.assertIn("applied", journal.OUTCOMES)


class TestTheChecksPassEvaluatesTrials(AcceptCase):

    async def test_a_trialling_row_gets_a_report_without_ending_the_trial(self):
        import routines
        import trials
        row = self.offer()
        started = self.proposals.start_trial(row["ts"])
        self.assertEqual(started["status"], "trialling")

        old_load = routines.load
        routines.load = lambda *a, **k: {"rows": [], "automated": {}}
        self.addCleanup(setattr, routines, "load", old_load)

        graded = await self.server._evaluate_trials(
            started["trial_started_at"] + 3 * 86400)
        self.assertEqual(graded, 1)
        back = self.proposals.get(row["ts"])
        self.assertEqual(back["status"], "trialling")
        result = back["trial_result"]
        self.assertEqual(result["days"], 3)
        self.assertEqual(result["would_fire"], 3)
        self.assertEqual(result["disagreed"], 3)
        self.assertEqual(sum(result[v] for v in trials.VERDICTS),
                         result["would_fire"])

    async def test_a_person_doing_the_same_thing_reads_as_agreement(self):
        """The presses are built from the firings the replay itself
        reports, so the fixture cannot disagree with the thing it is
        grading — and the neighbouring case, the same presses to `off`,
        comes out as a contradiction."""
        import routines
        row = self.offer()
        started = self.proposals.start_trial(row["ts"])
        base = started["trial_started_at"]
        end = base + 4 * 86400

        empty = {"rows": [], "automated": {}}
        old_load = routines.load
        routines.load = lambda *a, **k: empty
        self.addCleanup(setattr, routines, "load", old_load)
        await self.server._evaluate_trials(end)
        fired = [f["ts"] for f
                 in self.proposals.get(row["ts"])["trial_result"]["firings"]]
        self.assertGreaterEqual(len(fired), 3)

        def ledger(state):
            return {"rows": [{"ts": t + 120, "entity_id": "light.hall",
                              "state": state, "name": "Hall lamp"}
                             for t in fired], "automated": {}}

        routines.load = lambda *a, **k: ledger("on")
        await self.server._evaluate_trials(end)
        agreed = self.proposals.get(row["ts"])["trial_result"]
        self.assertEqual(agreed["agreed"], len(fired))
        self.assertEqual(agreed["contradicted"], 0)

        routines.load = lambda *a, **k: ledger("off")
        await self.server._evaluate_trials(end)
        against = self.proposals.get(row["ts"])["trial_result"]
        self.assertEqual(against["contradicted"], len(fired))
        self.assertEqual(against["agreed"], 0)

    async def test_the_diagnostics_say_how_many_carry_a_result(self):
        row = self.offer()
        self.proposals.start_trial(row["ts"])
        diag = self.server._proposals_diagnostics()
        self.assertEqual(diag["trialling"], 1)
        self.assertEqual(diag["trial_results"], 0)

        self.proposals.record_trial(row["ts"], {"would_fire": 1})
        diag = self.server._proposals_diagnostics()
        self.assertEqual(diag["trial_results"], 1)

    async def test_nothing_trialling_costs_no_session_and_no_fetch(self):
        self.offer()
        self.assertEqual(await self.server._evaluate_trials(1_800_000_000), 0)


if __name__ == "__main__":
    unittest.main()
