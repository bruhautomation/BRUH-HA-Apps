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
import time
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

INCLUDE = ("default_config:\n"
           "automation: !include automations.yaml\n"
           "scene: !include scenes.yaml\n")

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
        os.environ["BRAIN_INTENTS_FILE"] = str(root / "intents.json")
        os.environ["BRAIN_INTENT_REQUESTS_DIR"] = str(root / "intent-requests")
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        for name in ("proposals", "automation_writer", "intents"):
            sys.modules.pop(name, None)

        self.proposals = importlib.import_module("proposals")
        self.writer = importlib.import_module("automation_writer")
        self.intents = importlib.import_module("intents")
        self.server = importlib.import_module("server")
        self.server.proposals = self.proposals
        self.server.automation_writer = self.writer
        self.server.intents = self.intents
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
        # `last_triggered` per entity, which is what an armed one-off is
        # watched by — the attribute, not the automation being off.
        self.triggered: dict[str, str] = {}
        # What `scene.reload` makes exist. A scene proposal claims four,
        # and the accept waits for every one of them.
        self.scenes_appear: list[str] = []

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
                attrs = {}
                if eid in self.triggered:
                    attrs["last_triggered"] = self.triggered[eid]
                return web.json_response({"entity_id": eid, "state": "on",
                                          "attributes": attrs})
            return web.json_response({"message": "not found"}, status=404)

        async def notify(request):
            body = await request.json()
            self.sent.append((request.match_info["service"],
                              body.get("title", ""), body.get("message", "")))
            return web.json_response([])

        async def history(request):
            # The replay's own fetch. An empty window is a real answer —
            # the recorder has nothing about this entity — and it is what
            # a fresh install gives.
            self.calls.append(request.path)
            return web.json_response([])

        core = web.Application()
        core.router.add_get("/history/period/{stamp}", history)
        async def scene_reload(request):
            self.calls.append(request.path)
            if self.reload_status != 200:
                return web.json_response({"message": "no"},
                                         status=self.reload_status)
            self.live |= set(self.scenes_appear)
            return web.json_response([])

        core.router.add_post("/services/scene/reload", scene_reload)
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
        for name in ("proposals", "automation_writer", "intents"):
            sys.modules.pop(name, None)

    def _restore_modules(self, proposals_mod, writer_mod):
        self.server.proposals = importlib.import_module("proposals")
        self.server.automation_writer = importlib.import_module(
            "automation_writer")
        self.server.intents = importlib.import_module("intents")

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


# The condition miner's proposal: the person's own automation, with one
# condition added, addressed by the id it already has.
EDIT_ID = "1699999999999"
EDIT_ENTITY = "automation.porch_light_at_dusk"


def edit_obj(entity_id: str = EDIT_ID) -> dict:
    import yaml
    config = yaml.safe_load(EXISTING)[0]
    config["condition"] = [{
        "condition": "not",
        "conditions": [{"condition": "time", "after": "21:00:00",
                        "before": "23:00:00",
                        "weekday": ["mon", "tue", "wed", "thu", "fri"]}],
    }]
    config["id"] = entity_id
    return {
        "kind": "condition",
        "title": "Stand Porch light at dusk down between 21:00 and 23:00",
        "why": "You have put it back 11 times on 8 separate weekdays.",
        "source": "condition",
        "config": config,
        "edits": entity_id,
        "automation": {"entity_id": EDIT_ENTITY,
                       "alias": "Porch light at dusk", "id": entity_id},
    }


class TestAcceptingAnEditRatherThanAnAddition(AcceptCase):
    """A `condition` proposal changes an entry that is already there.

    The mutation each test catches:

      route it through `apply`   -> a second automation is appended under
                                 a `brain_` id and the person's own one
                                 goes on doing what they keep undoing
      verify the slugged name    -> the accept waits for an entity Home
                                 Assistant never registered under that
                                 name and reverts a change that worked
      undo puts back the row     -> the condition stays in their file
    """

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # It is already running: an edit is about an automation the house
        # has, so the verification is that it is STILL there.
        self.live.add(EDIT_ENTITY)

    def offer_edit(self, **kw) -> dict:
        row = self.proposals.add(edit_obj(**kw))
        self.assertIsNotNone(row)
        return row

    async def test_it_splices_the_entry_rather_than_appending_one(self):
        row = self.offer_edit()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        rows = self.rows()
        self.assertEqual(len(rows), 1, "an edit appended a second automation")
        self.assertEqual(rows[0]["id"], EDIT_ID)
        self.assertEqual(rows[0]["condition"][0]["condition"], "not")
        # Their file, above the entry, byte for byte.
        self.assertTrue(self.automations().startswith(
            "# Mine. Do not reformat.\n"))

    async def test_it_verifies_the_entity_home_assistant_registered(self):
        row = self.offer_edit()
        _status, out = await self.accept(row["ts"])
        self.assertEqual(out["entity_id"], EDIT_ENTITY)
        self.assertIn(f"/states/{EDIT_ENTITY}", self.calls)

    async def test_the_toast_names_the_automation_that_changed(self):
        row = self.offer_edit()
        _status, out = await self.accept(row["ts"])
        self.assertEqual(out["proposal"]["edits"], EDIT_ID)
        self.assertEqual(out["automation"], EDIT_ID)

    async def test_undo_puts_the_file_back_byte_for_byte(self):
        row = self.offer_edit()
        _status, out = await self.accept(row["ts"])
        resp = await self.client.post(f"/api/undo/{out['undo']}")
        self.assertEqual(resp.status, 200)
        undone = await resp.json()
        self.assertTrue(undone["undone"], undone)
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(len(self.proposals.listing()), 1)

    async def test_an_id_that_is_not_in_the_file_is_refused_and_kept(self):
        row = self.offer_edit(entity_id="not_in_the_file")
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertIn("not_in_the_file", out["error"])
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(len(self.proposals.listing()), 1)

    async def test_a_missing_include_line_is_refused(self):
        (self.config / "configuration.yaml").write_text("default_config:\n")
        row = self.offer_edit()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertIn("!include automations.yaml", out["error"])
        self.assertEqual(self.automations(), EXISTING)

    async def test_a_protected_target_is_refused_at_the_writer_too(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.porch"
        row = self.offer_edit()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertIn("protected", out["error"])
        self.assertEqual(self.automations(), EXISTING)

    async def test_a_reload_failure_puts_the_entry_back(self):
        self.reload_status = 500
        row = self.offer_edit()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(len(self.proposals.listing()), 1)


# ---------------------------------------------------------------------------
# One-off intents, end to end: a sentence in, a card out, a press to remove it
# ---------------------------------------------------------------------------

SENTENCE = "when the guests leave, turn the porch light off"
CLAUDE_JSON = json.dumps({
    "once": True,
    "plain": "Turn the porch light off ten minutes after the front door shuts.",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.front_door",
                 "to": "off", "for": {"minutes": 10}}],
    "action": [{"service": "light.turn_off",
                "target": {"entity_id": "light.porch"}}],
})


class TestOneOffIntents(AcceptCase):
    """Claude is stubbed; the request file, the checks and the presses are not.

    The mutation each test catches:

      route the sentence to a card  -> "when the guests leave…" answered as a
                                    question about the house
      arm before verifying          -> a card saying the house is holding
                                    something Core never loaded
      remove without verifying      -> a row taken off a list while the
                                    automation is still running
      no undo                       -> the one press that deletes from
                                    /config with no way back
    """

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.answers = [CLAUDE_JSON]
        self.prompts: list[str] = []
        self._old_analyst = self.server.engine.run_analyst

        def analyst(prompt, system, *a, **kw):
            self.prompts.append(prompt)
            text = self.answers.pop(0) if self.answers else ""
            return {"ok": bool(text), "text": text, "error": "", "meta": {}}

        self.server.engine.run_analyst = analyst
        self.addCleanup(setattr, self.server.engine, "run_analyst",
                        self._old_analyst)

        # The map the prompt carries. Reading it is `ha_data`'s and is not
        # what this is about.
        import ha_data
        self._old_orient = ha_data.collect_orientation

        async def orient(question=None):
            return {"areas": {"Porch": 3}, "domains": {"light": 4},
                    "meta": {"now": "2026-09-05T01:00:00"}}

        ha_data.collect_orientation = orient
        self.addCleanup(setattr, ha_data, "collect_orientation",
                        self._old_orient)

    async def ask(self, question=SENTENCE):
        resp = await self.client.post("/api/generate",
                                      json={"question": question})
        return resp.status, await resp.json()

    async def test_the_ask_bar_routes_a_sentence_and_never_makes_a_card(self):
        status, out = await self.ask()
        self.assertEqual(status, 200, out)
        self.assertEqual(out["queued"], [])
        self.assertEqual(out["intent"], SENTENCE)
        self.assertEqual(self.intents.pending(), 1)

    async def test_a_scene_sentence_survives_whatever_whitespace_it_arrives_in(self):
        """`h_generate` collapses the question before any pattern sees it,
        which is what lets `SCENE_RE` use literal spaces — and what stops
        a room's name arriving as two lines. Driven through the real
        route, because a copy of the collapse in the test would only ever
        agree with itself."""
        seen = []

        async def design(area):
            seen.append(area)
            return {"scenes": area, "lights": 4}

        self.server._design_scenes = design
        self.addCleanup(setattr, self.server, "_design_scenes",
                        self.server._design_scenes)
        status, out = await self.ask("design  my   evening \n for the "
                                     "living  room")
        self.assertEqual(status, 200, out)
        self.assertEqual(seen, ["living room"])
        self.assertEqual(out["queued"], [])

    async def test_an_ordinary_question_is_still_a_card(self):
        status, out = await self.ask("what is using the most power?")
        self.assertEqual(status, 200, out)
        self.assertTrue(out["queued"])
        self.assertEqual(self.intents.pending(), 0)

    async def test_the_drain_turns_the_sentence_into_a_proposal(self):
        await self.ask()
        self.assertEqual(await self.server._apply_intent_requests(), 1)
        rows = self.proposals.listing()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["kind"], "intent")
        self.assertEqual(row["config"]["mode"], "single")
        self.assertEqual(row["config"]["action"][-1]["service"],
                         "automation.turn_off")
        self.assertIn(SENTENCE, self.prompts[0])
        self.assertIn("Porch", self.prompts[0])

    async def test_a_refused_sentence_is_a_row_on_the_tab_not_a_log_line(self):
        self.answers = [json.dumps({"once": False,
                                    "plain": "every evening at sunset"})]
        await self.ask()
        await self.server._apply_intent_requests()
        self.assertEqual(self.proposals.listing(), [])
        rows = self.intents.listing()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "refused")
        self.assertIn("standing rule", rows[0]["refused"])

    async def test_a_claude_run_that_says_nothing_is_reported_the_same_way(self):
        self.answers = []
        await self.ask()
        await self.server._apply_intent_requests()
        rows = self.intents.listing()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "refused")

    async def accepted(self) -> dict:
        await self.ask()
        await self.server._apply_intent_requests()
        row = self.proposals.listing()[0]
        # Whatever alias the sentence became, Core has to have it.
        self.live.add(f"automation.{self.writer.slugify(row['title'])}")
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        return out

    async def test_accepting_writes_it_and_arms_it(self):
        out = await self.accepted()
        self.assertEqual(len(self.rows()), 2)
        armed = self.intents.listing()
        self.assertEqual(len(armed), 1)
        self.assertEqual(armed[0]["status"], "armed")
        self.assertEqual(armed[0]["entity_id"], out["entity_id"])
        self.assertEqual(armed[0]["sentence"], SENTENCE)
        # It left the proposals list, like every other answered proposal.
        self.assertEqual(self.proposals.listing(), [])

    async def test_an_accept_home_assistant_refuses_arms_nothing(self):
        self.entity_appears = False
        self.reload_status = 500
        await self.ask()
        await self.server._apply_intent_requests()
        row = self.proposals.listing()[0]
        status, _out = await self.accept(row["ts"])
        self.assertEqual(status, 409)
        self.assertEqual(self.intents.listing(), [])
        self.assertEqual(self.automations(), EXISTING)

    async def test_the_checks_pass_moves_it_to_fired_when_it_has(self):
        out = await self.accepted()
        # Nothing has happened yet: no `last_triggered`, no move.
        self.assertEqual(await self.server._poll_intents(time.time()), 0)
        self.assertEqual(self.intents.listing()[0]["status"], "armed")

        self.triggered[out["entity_id"]] = "2099-01-01T09:30:00+00:00"
        self.assertEqual(await self.server._poll_intents(time.time()), 1)
        row = self.intents.listing()[0]
        self.assertEqual(row["status"], "fired")
        self.assertGreater(row["fired_at"], 0)

    async def test_an_entity_core_will_not_answer_for_is_left_alone(self):
        """"I could not look" and "it has not happened" are different
        answers, and only the second belongs on a card."""
        await self.accepted()
        self.live.clear()
        self.assertEqual(await self.server._poll_intents(time.time()), 0)
        self.assertEqual(self.intents.listing()[0]["status"], "armed")

    async def test_remove_splices_it_out_verifies_and_offers_undo(self):
        out = await self.accepted()
        row = self.intents.listing()[0]
        self.live.discard(out["entity_id"])   # the reload takes it away
        resp = await self.client.post(f"/api/intent/{row['ts']}/remove",
                                      json={})
        self.assertEqual(resp.status, 200)
        removed = await resp.json()
        self.assertTrue(removed["removed"])
        self.assertIn("undo", removed)
        self.assertEqual(self.automations(), EXISTING)
        self.assertEqual(self.intents.listing(), [])

    async def test_undoing_a_remove_puts_back_the_file_and_the_row(self):
        out = await self.accepted()
        after_accept = self.automations()
        row = self.intents.listing()[0]
        self.live.discard(out["entity_id"])
        removed = await (await self.client.post(
            f"/api/intent/{row['ts']}/remove", json={})).json()
        undone = await (await self.client.post(
            f"/api/undo/{removed['undo']}")).json()
        self.assertTrue(undone["undone"], undone)
        self.assertEqual(self.automations(), after_accept)
        self.assertEqual(len(self.intents.listing()), 1)

    async def test_an_automation_core_still_has_after_the_reload_is_kept(self):
        """The mirror of the accept path's verification: "the file was
        written" is not "the automation is gone"."""
        await self.accepted()
        row = self.intents.listing()[0]
        # `self.live` still holds it, so the reload did not take it away.
        resp = await self.client.post(f"/api/intent/{row['ts']}/remove",
                                      json={})
        self.assertEqual(resp.status, 409)
        out = await resp.json()
        self.assertIn("still in Home Assistant", out["error"])
        self.assertEqual(len(self.intents.listing()), 1)
        self.assertIn("brain_intent_", self.automations())

    async def test_a_refused_row_is_dismissed_without_touching_the_file(self):
        self.answers = [json.dumps({"once": False, "plain": "every evening"})]
        await self.ask()
        await self.server._apply_intent_requests()
        row = self.intents.listing()[0]
        resp = await self.client.post(f"/api/intent/{row['ts']}/remove",
                                      json={})
        self.assertEqual(resp.status, 200)
        self.assertEqual(self.intents.listing(), [])
        self.assertEqual(self.automations(), EXISTING)

    async def test_a_row_that_is_gone_is_a_404_and_not_a_crash(self):
        resp = await self.client.post("/api/intent/12345/remove", json={})
        self.assertEqual(resp.status, 404)

    async def test_the_cap_refuses_with_a_sentence_rather_than_silence(self):
        for i in range(self.intents.MAX_ARMED):
            self.intents.arm({"ts": 1000 + i, "title": f"one {i}",
                              "sentence": f"when thing {i} happens"},
                             {"automation_id": f"a{i}",
                              "entity_id": f"automation.a{i}"})
        await self.ask()
        await self.server._apply_intent_requests()
        refused = [r for r in self.intents.listing()
                   if r.get("status") == "refused"]
        self.assertEqual(len(refused), 1)
        self.assertIn("one-offs waiting", refused[0]["refused"])

    async def test_the_payload_carries_the_intents_and_the_badge_does_not(self):
        await self.accepted()
        payload = self.server._proposals_payload()
        self.assertEqual(len(payload["intents"]), 1)
        self.assertEqual(payload["counts"]["open"], 0)
        self.assertIn("intent_ttl_days", payload)

    async def test_the_diagnostics_count_them_apart_from_proposals(self):
        await self.accepted()
        diag = self.server._proposals_diagnostics()["intents"]
        self.assertEqual(diag["armed"], 1)
        self.assertEqual(diag["fired"], 0)
        self.assertEqual(diag["overdue"], 0)


# ---------------------------------------------------------------------------
# Four scenes: a different file, the same five steps
# ---------------------------------------------------------------------------

SCENE_NAMES = ["Morning — Lounge", "Day — Lounge", "Evening — Lounge",
               "Night — Lounge"]
SCENE_ENTITIES = ["scene.morning_lounge", "scene.day_lounge",
                  "scene.evening_lounge", "scene.night_lounge"]


def scene_obj() -> dict:
    return {
        "kind": "scene",
        "source": "scene",
        "title": "Four scenes for the Lounge",
        "why": "Composed from the 2 lights the Lounge has.",
        "config": [
            {"id": f"brain_scene_lounge_{mood}", "name": name,
             "entities": {"light.lounge": {"state": "on", "brightness": 200},
                          "light.lamp": {"state": "off"}}}
            for mood, name in zip(("morning", "day", "evening", "night"),
                                  SCENE_NAMES)],
        "scene": {"area": "Lounge", "lights": [], "skipped": [],
                  "preview": [], "moods": ["morning", "day", "evening",
                                           "night"]},
    }


class TestAcceptingFourScenes(AcceptCase):
    """The mutation each test catches:

      write to automations.yaml   -> four scenes appended to the wrong file,
                                  under a schema Core refuses to load
      reload `automation`         -> the file is right and Core never reads it
      verify the first only       -> three scenes out of four, and a schedule
                                  that turns on nothing on the fourth
    """

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.scenes = self.config / "scenes.yaml"
        self.scenes.write_text("# My scenes.\n")
        self.scenes_appear = list(SCENE_ENTITIES)

    def offer_scenes(self) -> dict:
        row = self.proposals.add(scene_obj())
        self.assertIsNotNone(row)
        return row

    def scene_rows(self):
        import yaml
        return yaml.safe_load(self.scenes.read_text())

    async def test_it_writes_all_four_to_scenes_yaml_and_leaves_the_rest(self):
        row = self.offer_scenes()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 200, out)
        rows = self.scene_rows()
        self.assertEqual(len(rows), 4)
        self.assertEqual([r["name"] for r in rows], SCENE_NAMES)
        self.assertEqual(rows[0]["entities"]["light.lounge"]["brightness"], 200)
        # Their file, above the block, byte for byte — and automations.yaml
        # is untouched, because this yes was never about it.
        self.assertTrue(self.scenes.read_text().startswith("# My scenes.\n"))
        self.assertEqual(self.automations(), EXISTING)

    async def test_it_reloads_scenes_rather_than_automations(self):
        row = self.offer_scenes()
        await self.accept(row["ts"])
        self.assertIn("/services/scene/reload", self.calls)
        self.assertNotIn("/services/automation/reload", self.calls)

    async def test_it_waits_for_every_scene_not_just_the_first(self):
        """Three out of four is a mood missing from a schedule nobody has
        written yet."""
        self.scenes_appear = SCENE_ENTITIES[:3]
        row = self.offer_scenes()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertIn("scene.night_lounge", out["error"])
        # And it put the file back, so nothing half-written survives.
        self.assertEqual(self.scenes.read_text(), "# My scenes.\n")

    async def test_a_missing_scene_include_line_is_refused(self):
        (self.config / "configuration.yaml").write_text(
            "default_config:\nautomation: !include automations.yaml\n")
        row = self.offer_scenes()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertIn("scene: !include scenes.yaml", out["error"])
        self.assertEqual(self.scenes.read_text(), "# My scenes.\n")

    async def test_a_protected_light_in_a_scene_is_refused_at_the_writer(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.lounge"
        row = self.offer_scenes()
        status, out = await self.accept(row["ts"])
        self.assertEqual(status, 409, out)
        self.assertIn("protected", out["error"])
        self.assertEqual(self.scenes.read_text(), "# My scenes.\n")

    async def test_a_second_set_under_the_same_names_is_refused(self):
        """Two scenes with one name is a house where nobody can tell which
        is which — and the store cannot catch it, because a re-composed
        set is a different config and so a different key."""
        row = self.offer_scenes()
        await self.accept(row["ts"])
        second = scene_obj()
        for entry in second["config"]:
            entry["entities"]["light.lounge"]["brightness"] = 120
        again = self.proposals.add(second)
        self.assertIsNotNone(again)
        status, out = await self.accept(again["ts"])
        self.assertEqual(status, 409, out)
        self.assertEqual(len(self.scene_rows()), 4)

    async def test_undo_puts_scenes_yaml_back_and_reloads_scenes(self):
        row = self.offer_scenes()
        _status, out = await self.accept(row["ts"])
        self.calls.clear()
        undone = await (await self.client.post(
            f"/api/undo/{out['undo']}")).json()
        self.assertTrue(undone["undone"], undone)
        self.assertEqual(self.scenes.read_text(), "# My scenes.\n")
        self.assertIn("/services/scene/reload", self.calls)


class TestWhatComesOffTheWire(unittest.TestCase):
    """The ask bar's two patterns and the log line, against a caller who is
    not being kind.

    Each test names the mutation it catches:

      adjacent whitespace runs   -> two pieces of SCENE_RE that can both
                                 consume the same run of spaces backtrack
                                 polynomially, and 500 spaces is a
                                 question somebody can send
      collapse the question      -> drop it and every literal space in
                                 the pattern stops matching a real
                                 sentence, and a room name arrives as two
                                 lines
      the log barrier            -> a newline in a room name writes a
                                 second line that looks like brAIn's own,
                                 which is how a log stops being evidence
    """

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def match(self, text):
        # Exactly what `h_generate` feeds it.
        return self.server.SCENE_RE.match(" ".join(str(text).split()))

    def timed(self, pattern, text) -> float:
        start = time.perf_counter()
        pattern.match(text)
        return time.perf_counter() - start

    def test_the_sentences_it_is_for_still_match(self):
        for text, area in (
                ("design my evening for the living room", "living room"),
                ("scenes for the kitchen", "kitchen"),
                ("Design scenes for the hall.", "hall"),
                ("make scenes for the office", "office"),
                ("design  some   lighting scenes\nfor my bedroom", "bedroom")):
            got = self.match(text)
            self.assertIsNotNone(got, text)
            self.assertEqual(got.group("area"), area, text)

    def test_the_sentences_it_is_not_for_do_not(self):
        for text in ("what is using the most power?",
                     "what is the best temperature for the bedroom?",
                     "when the guests leave, turn the porch light off",
                     "learn about the boiler"):
            self.assertIsNone(self.match(text), text)

    def test_no_piece_of_the_scene_pattern_can_eat_a_run_of_spaces(self):
        """The actual fix, and the one a future edit can undo.

        A polynomial backtrack needs two adjacent pieces that can both
        consume the same run of whitespace. `h_generate` collapses the
        question first, so every space in this pattern is a single
        literal one and there is nothing to fight over — which is a
        property of the source, and so is what is asserted. A wall-clock
        test cannot stand in for it: at the route's own 500-character cap
        Python's engine does not reach the blow-up the shape allows, so a
        timing bound would pass over the broken pattern too (it was
        measured doing exactly that) and prove nothing.
        """
        self.assertNotIn("\\s", self.server.SCENE_RE.pattern)

    def test_neither_pattern_takes_long_over_a_line_of_spaces(self):
        """A ceiling rather than a reproduction — see the test above for
        why. It is here because the route accepts 500 characters from
        anybody, and something has to fail if that ever stops being
        cheap."""
        for pattern, name in ((self.server.SCENE_RE, "SCENE_RE"),
                              (self.server.INTENT_RE, "INTENT_RE")):
            for text in (" " * 500,
                         "design " + " " * 490 + "scenes for the x",
                         "scenes " + " " * 480 + "for the x",
                         "tell me" + " " * 490 + "when"):
                self.assertLess(self.timed(pattern, text), 0.05,
                                f"{name} is slow on {len(text)} chars")

    def test_the_intent_pattern_has_no_ambiguous_whitespace_either(self):
        """It had the same shape: `^\\s*` beside `(?:please\\s+)?` is two
        adjacent pieces that can both eat one run of spaces. Both are
        literal now, for the same reason and behind the same collapse."""
        self.assertNotIn("\\s", self.server.INTENT_RE.pattern)

    def test_the_intent_sentences_still_match(self):
        for text in ("when the guests leave, turn the porch light off",
                     "Once the door has been shut ten minutes, lock it",
                     "tell me when the dryer finishes",
                     "the next time it rains, shut the skylight",
                     "please remind me when the bins go out"):
            self.assertIsNotNone(
                self.server.INTENT_RE.match(" ".join(text.split())), text)
        for text in ("what happens when the freezer warms up?",
                     "design scenes for the kitchen"):
            self.assertIsNone(
                self.server.INTENT_RE.match(" ".join(text.split())), text)

    def test_the_area_never_reaches_a_log_line_with_a_newline_in_it(self):
        safe = self.server.log_safe("Living\nroom\r\nWARNING brAIn: all clear")
        self.assertNotIn("\n", safe)
        self.assertNotIn("\r", safe)
        self.assertIn("Living room", safe)

    def test_it_drops_the_control_characters_a_terminal_would_act_on(self):
        self.assertEqual(self.server.log_safe("a\x1b[31mb\x00c"), "a[31mbc")

    def test_it_is_capped_because_a_log_line_is_a_sentence(self):
        self.assertEqual(len(self.server.log_safe("x" * 500)), 60)

    def test_it_answers_for_anything_at_all(self):
        for value in (None, 0, 12345, {"a": 1}):
            self.assertIsInstance(self.server.log_safe(value), str)


if __name__ == "__main__":
    unittest.main()


class TestTheScheduleGetsItsReplay(AcceptCase):
    """The schedule is an ordinary automation and the changelog says it gets
    a replay — but `_offer_scene_schedule` filed it without one for a
    release, so the card had no "would have fired N times" line while the
    routine miner's did. The mutation: drop the `_replay_config` call and
    the proposal lands with no `replay` key.
    """

    async def test_the_schedule_proposal_carries_a_replay(self):
        server, scenes_mod = self.server, self.server.scenes
        added, replayed = [], []

        async def fake_replay(session, config, start, end, tz):
            replayed.append(config)
            return {"days": 30, "would_run": 28, "triggered": 28}

        def fake_schedule(snap, area, wake, settle):
            return {"kind": "schedule", "source": "scene", "key": "sched-1",
                    "title": f"Walk the {area} through its scenes",
                    "why": "…", "status": "proposed",
                    "config": {"id": "brain_scene_schedule_lounge",
                               "trigger": [{"platform": "time",
                                            "at": "07:00:00"}],
                               "action": []}}

        old = (server._replay_config, scenes_mod.schedule,
               server.proposals.add, server.rhythm.load)
        server._replay_config = fake_replay
        scenes_mod.schedule = fake_schedule
        server.proposals.add = lambda obj: added.append(obj) or obj
        server.rhythm.load = lambda: {}
        try:
            snapshot = {"scenes": [{"id": f"brain_scene_lounge_{m}",
                                    "name": m.title()}
                                   for m in ("morning", "day", "evening",
                                             "night")],
                        "states": {}, "registries": {}}
            offered = await server._offer_scene_schedule(snapshot, 1_800_000_000)
        finally:
            (server._replay_config, scenes_mod.schedule,
             server.proposals.add, server.rhythm.load) = old
        self.assertEqual(offered, 1)
        self.assertEqual(len(replayed), 1)
        self.assertEqual(added[0]["replay"]["would_run"], 28)
