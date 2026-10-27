#!/usr/bin/env python3
"""Timed actions: "water the garden for 90 minutes" without an automation.

A sentence is read into steps by one cheap tool-less run, every step is
checked in code, and the panel runs each through `typed_fix.execute` — the
chokepoint every panel service call takes. Driven through the real store,
the real loop, the real routes and the real request drain, with only
Core (`_typed_hooks`, `_fetch_states_once`) and the model stubbed.

Mutations each test names:

  the chokepoint is skipped     call `hooks.call` directly -> no ledger
                                row under `timed`, the protected list not
                                asked at run time
  a lock opens on a timer       drop `SECURITY_REDUCING` from `check_step`
  a garage opens on a timer     drop the cover-class check
  hours late after a restart    `decide` answers "run" for any late step
  the valve is left open        Stop cancels the ending with the rest
  a failure rings twice         drop `notified`
  the card stays with the
  switch on                     drop the accept in `_one_intent`
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))

import finding_requests  # noqa: E402
import interpret  # noqa: E402
import timed_actions  # noqa: E402
from test_interpret import AskCase  # noqa: E402

NOW = 1_790_000_000.0


def state(eid, name, **attrs):
    return {"entity_id": eid, "state": "off",
            "attributes": {"friendly_name": name, **attrs}}


HOUSE = {
    "valve.garden": state("valve.garden", "Garden valve"),
    "light.porch": state("light.porch", "Porch light"),
    "lock.front_door": state("lock.front_door", "Front door"),
    "alarm_control_panel.home": state("alarm_control_panel.home", "Alarm"),
    "cover.garage": state("cover.garage", "Garage door",
                          device_class="garage"),
    "cover.blind": state("cover.blind", "Lounge blind", device_class="blind"),
    "script.party": state("script.party", "Party"),
    "input_boolean.brain_tripwire": state("input_boolean.brain_tripwire",
                                          "Spare switch"),
}

WATER = {"timed": True, "title": "Water the garden for 90 minutes",
         "steps": [
             {"after_minutes": 0, "domain": "valve", "service": "open_valve",
              "entities": ["valve.garden"]},
             {"after_minutes": 90, "domain": "valve",
              "service": "close_valve", "entities": ["valve.garden"],
              "ends": True}]}


def one(domain, service, eid, after=0):
    return {"timed": True, "title": "x", "steps": [
        {"after_minutes": after, "domain": domain, "service": service,
         "entities": [eid]}]}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._store = timed_actions.STORE
        timed_actions.STORE = Path(self.tmp.name) / "timed.json"

    def tearDown(self):
        timed_actions.STORE = self._store
        self.tmp.cleanup()

    def add_water(self, now=NOW):
        task = timed_actions.build(WATER, "water the garden for 90 minutes",
                                   HOUSE, protected=[], now=now)
        return timed_actions.add(task)


class TestTheSentenceIsCheckedInCode(StoreCase):
    def build(self, answer, protected=(), tokens=()):
        return timed_actions.build(answer, "s", HOUSE,
                                   protected=list(protected),
                                   honeytokens=tokens, now=NOW)

    def test_watering_is_two_steps_and_the_last_puts_it_back(self):
        task = self.build(WATER)
        self.assertEqual([s["service"] for s in task["steps"]],
                         ["open_valve", "close_valve"])
        self.assertEqual(task["steps"][1]["at"] - task["steps"][0]["at"],
                         90 * 60)
        self.assertEqual([s["ends"] for s in task["steps"]], [False, True])
        self.assertEqual(task["steps"][0]["names"],
                         {"valve.garden": "Garden valve"})

    def test_not_timed_or_unreadable_is_handed_back(self):
        for answer in (None, "text", {"timed": False, "steps": []},
                       {"timed": True, "steps": []},
                       {"timed": True, "steps": [{"domain": "light"}]}):
            with self.subTest(answer=answer):
                self.assertIsNone(self.build(answer))

    def test_what_brain_will_not_do_on_a_timer_is_refused(self):
        cases = {
            "unlock": one("lock", "unlock", "lock.front_door"),
            "open a lock": one("lock", "open", "lock.front_door"),
            "disarm": one("alarm_control_panel", "alarm_disarm",
                          "alarm_control_panel.home"),
            "open the garage": one("cover", "open_cover", "cover.garage"),
            "a script": one("script", "turn_on", "script.party"),
            "a device it cannot see": one("light", "turn_on",
                                          "light.nowhere"),
            "another domain's service": one("light", "turn_on",
                                            "valve.garden"),
            "past a day": one("light", "turn_on", "light.porch",
                              after=24 * 60 + 1),
        }
        for why, answer in cases.items():
            with self.subTest(why=why):
                with self.assertRaises(timed_actions.Refused):
                    self.build(answer)

    def test_too_many_steps_is_refused(self):
        steps = [{"after_minutes": i, "domain": "light", "service": "toggle",
                  "entities": ["light.porch"]}
                 for i in range(timed_actions.MAX_STEPS + 1)]
        with self.assertRaises(timed_actions.Refused):
            self.build({"timed": True, "steps": steps})

    def test_closing_the_garage_and_opening_a_blind_are_fine(self):
        self.assertIsNotNone(self.build(one("cover", "close_cover",
                                            "cover.garage")))
        self.assertIsNotNone(self.build(one("cover", "open_cover",
                                            "cover.blind")))

    def test_protected_is_named_and_the_tripwire_is_not(self):
        with self.assertRaises(timed_actions.Refused) as got:
            self.build(one("light", "turn_on", "light.porch"),
                       protected=["light.porch"])
        self.assertIn("Porch light", str(got.exception))
        self.assertNotIn("light.porch", str(got.exception))
        with self.assertRaises(timed_actions.Refused) as got:
            self.build(one("input_boolean", "turn_on",
                           "input_boolean.brain_tripwire"),
                       tokens={"input_boolean.brain_tripwire"})
        self.assertNotIn("tripwire", str(got.exception))
        self.assertNotIn("brain_tripwire", str(got.exception))

    def test_the_store_is_capped(self):
        for _ in range(timed_actions.MAX_LIVE):
            self.assertIsNotNone(self.add_water())
        self.assertIsNone(self.add_water())
        ids = [r["id"] for r in timed_actions.load()]
        self.assertEqual(len(ids), len(set(ids)), "an id was handed out twice")


class TestNeverHoursLate(StoreCase):
    def test_a_little_late_runs_and_a_long_way_late_is_missed(self):
        row = self.add_water()
        self.assertEqual(timed_actions.decide(row, 0, NOW + 60), "run")
        # The ending is still ahead, so the watering can still happen.
        self.assertEqual(timed_actions.decide(row, 0, NOW + 3600), "run")
        light = timed_actions.add(timed_actions.build(
            one("light", "turn_on", "light.porch", after=60), "s", HOUSE,
            protected=[], now=NOW))
        self.assertEqual(timed_actions.decide(light, 0, NOW + 3600 + 30),
                         "run")
        self.assertEqual(timed_actions.decide(light, 0, NOW + 6 * 3600),
                         "missed")

    def test_the_ending_runs_late_only_after_something_ran(self):
        row = self.add_water()
        self.assertEqual(timed_actions.decide(row, 1, NOW + 9 * 3600), "skip")
        row = timed_actions.mark_step(row["id"], 0, "done", now=NOW)
        self.assertEqual(timed_actions.decide(row, 1, NOW + 9 * 3600), "run")

    def test_the_store_survives_a_restart(self):
        row = self.add_water()
        timed_actions.mark_step(row["id"], 0, "done", now=NOW)
        # A fresh read of the file is all a restarted panel has.
        again = timed_actions.get(row["id"])
        self.assertEqual(again["status"], "running")
        self.assertEqual(timed_actions.due(NOW + 91 * 60), [(row["id"], 1)])


class FakeCore:
    def __init__(self, house=None, fail=()):
        self.house = dict(house or HOUSE)
        self.calls: list[tuple[str, str, dict]] = []
        self.ledger: list[dict] = []
        self.fail = set(fail)

    def hooks(self):
        import typed_fix

        async def call(domain, service, data):
            if (domain, service) in self.fail:
                raise RuntimeError("Home Assistant said no")
            self.calls.append((domain, service, data))
            return []

        async def st(eid):
            return self.house.get(eid)

        async def nope(*a, **k):
            raise AssertionError("not a call a timed action makes")

        return typed_fix.Hooks(apply_edit=nope, revert_edit=nope, call=call,
                               state=st, ws=nope, ledger=self.ledger.append)


class ServerCase(StoreCase):
    @classmethod
    def setUpClass(cls):
        import importlib
        cls.server = importlib.import_module("server")

    def setUp(self):
        super().setUp()
        s = self.server
        self.core = FakeCore()
        self.sent: list[tuple] = []
        self._olds = (s._typed_hooks, s._send_notification,
                      s.security.honeytoken_ids,
                      s.morph_bridge.MORPH_DIR, s._fetch_states_once,
                      dict(s.TIMED_STATE), os.environ.get(
                          "BRAIN_PROTECTED_ENTITIES"))
        s._typed_hooks = self.core.hooks
        s.security.honeytoken_ids = set
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)

        async def send(rows, held=False, message=None, buttons=None, **k):
            self.sent.append((rows, message))
            return True

        s._send_notification = send

        async def states():
            return list(self.core.house.values())

        s._fetch_states_once = states
        # A shared volume, so the Morph mirror is written and can be read.
        root = Path(self.tmp.name)
        (root / "config" / ".brain").mkdir(parents=True)
        s.morph_bridge.MORPH_DIR = root / "config" / ".brain" / "morph"
        s.TIMED_STATE["published"] = ""

    def tearDown(self):
        s = self.server
        (s._typed_hooks, s._send_notification, s.security.honeytoken_ids,
         s.morph_bridge.MORPH_DIR, s._fetch_states_once, timed_state,
         protected) = self._olds
        s.TIMED_STATE.clear()
        s.TIMED_STATE.update(timed_state)
        if protected is None:
            os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        else:
            os.environ["BRAIN_PROTECTED_ENTITIES"] = protected
        super().tearDown()

    def tick(self, now):
        return asyncio.run(self.server._timed_tick(now))


class TestTheLoop(ServerCase):
    def test_each_step_goes_through_the_chokepoint_at_its_time(self):
        row = self.add_water()
        self.assertEqual(self.tick(NOW + 1), 1)
        self.assertEqual(self.core.calls,
                         [("valve", "open_valve",
                           {"entity_id": ["valve.garden"]})])
        self.assertEqual(self.core.ledger[0]["channel"], "timed")
        self.assertEqual(self.core.ledger[0]["intervention"],
                         f"timed-{row['id']}")
        self.assertEqual(self.tick(NOW + 60), 0, "a step ran twice")
        self.assertEqual(self.tick(NOW + 90 * 60 + 2), 1)
        self.assertEqual(self.core.calls[-1][1], "close_valve")
        self.assertEqual(timed_actions.get(row["id"])["status"], "done")

    def test_the_protected_list_is_asked_again_when_the_step_runs(self):
        row = self.add_water()
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "valve.garden"
        self.tick(NOW + 1)
        self.assertEqual(self.core.calls, [])
        self.assertEqual(timed_actions.get(row["id"])["steps"][0]["status"],
                         "failed")

    def test_a_cover_that_became_a_garage_is_not_opened(self):
        timed_actions.add(timed_actions.build(
            one("cover", "open_cover", "cover.blind"), "s", HOUSE,
            protected=[], now=NOW))
        self.core.house["cover.blind"] = state("cover.blind", "Shed door",
                                               device_class="garage")
        self.tick(NOW + 1)
        self.assertEqual(self.core.calls, [])

    def test_a_failure_is_recorded_and_said_once(self):
        self.core.fail = {("valve", "open_valve")}
        row = self.add_water()
        self.tick(NOW + 1)
        after = timed_actions.get(row["id"])
        self.assertEqual(after["steps"][0]["status"], "failed")
        self.assertIn("said no", after["error"])
        self.assertEqual(len(self.sent), 1)
        # Nothing ran, so the ending has nothing to put back.
        self.tick(NOW + 91 * 60)
        self.assertEqual(timed_actions.get(row["id"])["status"], "failed")
        self.assertEqual(len(self.sent), 1, "a failure was said twice")

    def test_after_a_restart_a_passed_moment_is_missed_not_late(self):
        light = timed_actions.add(timed_actions.build(
            one("light", "turn_on", "light.porch", after=60), "s", HOUSE,
            protected=[], now=NOW))
        self.tick(NOW + 7 * 3600)
        self.assertEqual(self.core.calls, [])
        self.assertEqual(timed_actions.get(light["id"])["status"], "missed")

    def test_morph_reads_the_list_with_its_stop_request(self):
        row = self.add_water()
        self.tick(NOW + 1)
        doc = json.loads((self.server.morph_bridge.MORPH_DIR
                          / "timed.json").read_text())
        [task] = doc["tasks"]
        self.assertEqual(task["stop"], {"kind": "timed", "action": "stop",
                                        "id": row["id"]})
        self.assertEqual(task["steps"][0]["does"], "Open Garden valve")
        self.assertIsNotNone(finding_requests.parse(task["stop"]))


class TestStop(ServerCase):
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

    def test_stop_runs_the_ending_and_cancels_the_rest(self):
        # The panel's own loop runs beside the routes, on the real clock.
        base = time.time()
        row = self.add_water(now=base)
        self.tick(base + 1)

        async def body(client):
            listed = await (await client.get("/api/timed")).json()
            res = await client.post(f"/api/timed/{row['id']}/stop")
            again = await client.post(f"/api/timed/{row['id']}/stop")
            gone = await client.post("/api/timed/12345/stop")
            return listed, res.status, await res.json(), again.status, \
                gone.status

        listed, status, out, again, gone = self.drive(body)
        self.assertEqual(listed["tasks"][0]["id"], row["id"])
        self.assertIn("left_s", listed["tasks"][0])
        self.assertEqual(status, 200, out)
        self.assertEqual(self.core.calls[-1][1], "close_valve")
        self.assertIn("close Garden valve", out["say"])
        self.assertEqual(timed_actions.get(row["id"])["status"], "stopped")
        self.assertEqual((again, gone), (409, 404))

    def test_stopping_before_anything_ran_calls_nothing(self):
        row = timed_actions.add(timed_actions.build(
            WATER, "s", HOUSE, protected=[], now=NOW + 600))
        payload, status = asyncio.run(self.server._stop_timed(row["id"]))
        self.assertEqual(status, 200)
        self.assertEqual(self.core.calls, [])
        self.assertEqual({s["status"] for s in
                          timed_actions.get(row["id"])["steps"]}, {"stopped"})

    def test_morph_stop_rides_the_request_drain(self):
        row = self.add_water()
        self.tick(NOW + 1)
        s = self.server
        old = s.finding_requests.collect
        s.finding_requests.collect = lambda: [finding_requests.parse(
            {"kind": "timed", "action": "stop", "id": row["id"],
             "via": "morph"})]
        try:
            out = asyncio.run(s._apply_finding_requests())
        finally:
            s.finding_requests.collect = old
        self.assertTrue(out[0]["ok"], out)
        self.assertEqual(timed_actions.get(row["id"])["status"], "stopped")
        self.assertEqual(self.core.calls[-1][1], "close_valve")

    def test_only_a_stop_with_an_id_is_a_request(self):
        for bad in ({"kind": "timed", "action": "start", "id": 1},
                    {"kind": "timed", "action": "stop", "id": "1"},
                    {"kind": "timed", "action": "stop", "id": True},
                    {"kind": "timed", "action": "stop"}):
            with self.subTest(bad=bad):
                self.assertIsNone(finding_requests.parse(bad))


class TestTheAskBarAndMorphAsk(AskCase):
    def setUp(self):
        super().setUp()
        s = self.server
        self.tmpdir = tempfile.TemporaryDirectory()
        self.core = FakeCore()
        self._timed_olds = (timed_actions.STORE, s._typed_hooks,
                            s._fetch_states_once, s.security.honeytoken_ids,
                            s.morph_bridge.MORPH_DIR)
        timed_actions.STORE = Path(self.tmpdir.name) / "timed.json"
        s.morph_bridge.MORPH_DIR = Path(self.tmpdir.name) / "a" / "b" / "c"
        s._typed_hooks = self.core.hooks
        s.security.honeytoken_ids = set

        async def states():
            return list(self.core.house.values())

        s._fetch_states_once = states

    def tearDown(self):
        s = self.server
        (timed_actions.STORE, s._typed_hooks, s._fetch_states_once,
         s.security.honeytoken_ids, s.morph_bridge.MORPH_DIR) = \
            self._timed_olds
        self.tmpdir.cleanup()
        super().tearDown()

    def ask_and_settle(self, question):
        async def body(client):
            res = await client.post("/api/generate",
                                    json={"question": question})
            self.assertEqual(res.status, 200, await res.text())
            out = await res.json()
            await asyncio.gather(*list(self.server._TIMED_TASKS))
            return out
        return self.drive(body)

    def test_a_timed_sentence_is_listed_not_drafted(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "timed", "text": "water the garden for 90 minutes"}]}
        self.replies["timed"] = WATER
        out = self.ask_and_settle("water the garden for 90 minutes")
        self.assertIn("task", out.get("timed") or {}, out)
        self.assertEqual(self.intent_calls, [], "an automation was drafted")
        [row] = timed_actions.load()
        self.assertEqual(row["via"], "panel")
        # The first step is due now and ran on the press.
        self.assertEqual(self.core.calls[0][1], "open_valve")
        self.assertIn("timed", self.model_jobs())

    def test_a_one_off_that_is_not_timed_is_drafted_as_before(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "one_off",
             "text": "when the guests leave, turn the porch light off"}]}
        self.replies["timed"] = {"timed": False, "steps": []}
        out = self.ask_and_settle("when the guests leave, turn the porch "
                                  "light off")
        self.assertIn("intent", out)
        self.assertEqual(len(self.intent_calls), 1)
        self.assertEqual(timed_actions.load(), [])

    def test_an_unlock_is_said_and_not_drafted_instead(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "timed", "text": "unlock the front door in an hour"}]}
        self.replies["timed"] = one("lock", "unlock", "lock.front_door", 60)
        out = self.ask_and_settle("unlock the front door in an hour")
        self.assertIn("refused", out["timed"])
        self.assertEqual(self.intent_calls, [])
        self.assertEqual(timed_actions.load(), [])

    def test_morph_ask_takes_it_on_too(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "timed", "text": "in an hour turn on the porch light"}]}
        self.replies["timed"] = one("light", "turn_on", "light.porch", 60)

        async def run():
            got = await self.server._answer_morph_ask(
                {"id": "a1", "text": "in an hour turn on the porch light"})
            await asyncio.gather(*list(self.server._TIMED_TASKS))
            return got

        got = asyncio.run(run())
        self.assertEqual(got["do"], "done", got)
        self.assertIn("timed actions", got["say"])
        [row] = timed_actions.load()
        self.assertEqual(row["via"], "morph")
        self.assertEqual(self.intent_calls, [])

    def test_the_vocabulary_and_the_surfaces(self):
        self.assertIn("timed", interpret.KINDS)
        for surface in ("ask_bar", "morph", "reply", "panel"):
            self.assertIn("timed", interpret.ALLOWED[surface])
        self.assertNotIn("timed", interpret.ALLOWED["repairs"])
        self.assertNotIn("timed", interpret.ALLOWED["service"])


class TestATypedRuleWithTheSwitchOn(unittest.IsolatedAsyncioTestCase):
    """`_one_intent`'s last step: the ordinary accept, only when typed."""

    async def asyncSetUp(self):
        import importlib
        self.server = importlib.import_module("server")
        s = self.server
        # The run is journaled; keep that off the real /data.
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_journal = s.journal.JOURNAL_FILE
        s.journal.JOURNAL_FILE = os.path.join(tmp.name, "journal.jsonl")
        self.addCleanup(setattr, s.journal, "JOURNAL_FILE", old_journal)
        self.accepts: list[int] = []
        self.switch = False
        olds = {k: getattr(s, k) for k in (
            "_claude", "_replay_config", "_grade_against_you",
            "_decide_proposal", "eff_skip_permissions")}
        olds_mods = (s.proposals.add, s.authoring.build, s.intents.parse_answer,
                     s.ha_data_orientation if hasattr(
                         s, "ha_data_orientation") else None)
        self.addCleanup(lambda: [setattr(s, k, v) for k, v in olds.items()])
        self.addCleanup(lambda: (setattr(s.proposals, "add", olds_mods[0]),
                                 setattr(s.authoring, "build", olds_mods[1]),
                                 setattr(s.intents, "parse_answer",
                                         olds_mods[2])))

        async def claude(*a, **k):
            return {"ok": True, "data": {"once": False}, "text": ""}

        async def nothing(*a, **k):
            return {}

        s._claude = claude
        s._replay_config = nothing
        s._grade_against_you = nothing
        s.intents.parse_answer = lambda text, data: {"once": False}
        s.authoring.build = lambda sentence, answer, ts, protected: {
            "kind": "automation", "title": "Hall light", "config": {},
            "spoken": {"sentence": sentence}}
        s.proposals.add = lambda obj: {**obj, "ts": 7, "status": "proposed"}

        async def decide(ts, verb, note=""):
            self.accepts.append(ts)
            return {"proposal": {"ts": ts, "status": "accepted"},
                    "undo": "tok"}, 200

        s._decide_proposal = decide
        s.eff_skip_permissions = lambda: self.switch
        import ha_data
        old_orient = ha_data.collect_orientation

        async def orient(question=None):
            return {"areas": {}, "domains": {}, "meta": {}}

        ha_data.collect_orientation = orient
        self.addCleanup(setattr, ha_data, "collect_orientation", old_orient)

    async def one(self, via="panel", typed=True):
        req = {"sentence": "turn the hall light on when the door opens",
               "via": via, "ts": 1}
        if typed:
            req["typed"] = True
        return await self.server._one_intent(req, NOW)

    async def test_switch_on_accepts_at_once(self):
        self.switch = True
        row = await self.one()
        self.assertEqual(self.accepts, [7])
        self.assertTrue(row["accepted_at_once"])
        self.assertEqual(row["undo"], "tok")

    async def test_switch_off_keeps_the_card(self):
        row = await self.one()
        self.assertEqual(self.accepts, [])
        self.assertEqual(row["status"], "proposed")

    async def test_only_what_a_person_typed_is_accepted(self):
        self.switch = True
        # brain.intent from an automation is nobody typing; a phone reply
        # is a person typing and is accepted (test_scenes_act_and_naming).
        await self.one(via="service")
        await self.one(typed=False)
        self.assertEqual(self.accepts, [])

    def test_only_a_literal_true_rides_the_request(self):
        intents = self.server.intents
        self.assertIs(intents.parse_request(
            {"ts": 1, "sentence": "s", "typed": True})["typed"], True)
        self.assertNotIn("typed", intents.parse_request(
            {"ts": 1, "sentence": "s", "typed": "yes"}) or {})


if __name__ == "__main__":
    unittest.main()
