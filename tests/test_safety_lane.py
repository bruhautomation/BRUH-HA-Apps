#!/usr/bin/env python3
"""The safety lane, and the Resident fixes that ride with it.

A tripped leak, smoke, CO or gas detector used to reach a phone only if a
Haiku look ran (a credential, `auto_enabled`, the budget and the day cap all
passing), parsed, and answered exactly `act` — and the never-ignore floor
that was supposed to stop it answering anything else matched words in the
signal's KIND, which for a bus signal is `state`. The case it filed then sat
under `resident`, which had no urgency entry, so in the default quiet hours
it was held until morning; and its text was fixed, so the second leak on the
same sensor was a duplicate of the first for ever.

Every test here drives the real code: `_note_safety` inside a running loop,
the real `_announce_findings` during quiet hours with every model gate
closed, the real stores. The only fakes are the two things that would leave
the process — the notification and the CLI — and both record what reached
them.
"""

import asyncio
import json
import os
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_resident_loop import LoopCase, case_reply, reply  # noqa: E402

LEAK = "binary_sensor.kitchen_leak"


def leak_state(state: str = "on") -> dict:
    return {"state": state, "attributes": {"device_class": "moisture",
                                           "friendly_name": "Kitchen leak"}}


class SafetyCase(LoopCase):
    def setUp(self):
        super().setUp()
        srv = self.server
        self.sent: list[dict] = []
        self.core_calls: list[tuple] = []
        self._saved = (srv._announce_findings, srv._send_notification,
                       srv._quiet_hours)
        # The REAL announcer — the one the old safety path never reached
        # past quiet hours — with only the delivery itself recorded.
        srv._announce_findings = self._old["server"][3]

        async def send(rows, held=False, message=None):
            self.sent.append({"rows": list(rows), "held": held})
            return True

        srv._send_notification = send
        hour = time.localtime().tm_hour
        # A quiet window that contains NOW, whatever hour the suite runs at.
        srv._quiet_hours = lambda: (hour, (hour + 2) % 24)
        for mod in self.copies("notify_router"):
            self._restore.append((mod, "ESCALATION_FILE",
                                  mod.ESCALATION_FILE))
            mod.ESCALATION_FILE = os.path.join(self.tmp.name, "esc.json")
            self._restore.append((mod, "QUEUE_FILE", mod.QUEUE_FILE))
            mod.QUEUE_FILE = os.path.join(self.tmp.name, "queue.json")

    def tearDown(self):
        srv = self.server
        (srv._announce_findings, srv._send_notification,
         srv._quiet_hours) = self._saved
        super().tearDown()

    def close_every_gate(self):
        import engine
        import settings_store
        engine.get_auth = lambda: None
        settings_store.save({"onboarded": True, "auto_enabled": False})

    def bus_event(self, new: str, old: str | None):
        """What the bus hands `_note_safety`, run inside a real loop and
        waited out — the lane is a task scheduled off the socket pump."""
        srv = self.server

        async def go():
            srv._note_safety("state_changed", {
                "entity_id": LEAK,
                "old_state": leak_state(old) if old is not None else None,
                "new_state": leak_state(new)})
            await asyncio.gather(*list(srv._SAFETY_TASKS))
        asyncio.run(go())

    def lane_rows(self):
        return [f for f in self.server.findings_store.list_all()
                if f["source"] == self.server.SAFETY_SOURCE]


class TestATripReachesAPhone(SafetyCase):

    def test_with_every_gate_closed_and_inside_quiet_hours(self):
        self.close_every_gate()
        self.bus_event("on", "off")
        [row] = self.lane_rows()
        self.assertEqual(row["severity"], "critical")
        self.assertEqual(row["stakes"], "high")
        self.assertIn("Water leak", row["text"])
        self.assertIn("Kitchen leak", row["text"])
        # Sent, not held: `safety` is a `now` producer and critical+high is
        # the escalate tier, which quiet hours do not hold.
        self.assertEqual([[r["ts"] for r in m["rows"]] for m in self.sent],
                         [[row["ts"]]])
        self.assertFalse(self.sent[0]["held"])
        esc = self.server.notify_router.load_escalations()
        self.assertIn(row["ts"], esc, "no reminder ladder started")
        # And no model was asked anything.
        self.assertEqual(self.look_calls, [])
        self.assertEqual(self.analyst_calls, [])

    def test_a_sensor_that_was_already_on_is_not_a_new_trip(self):
        self.bus_event("on", "on")
        self.assertEqual(self.lane_rows(), [])

    def test_a_house_with_no_notify_target_gets_home_assistants_own(self):
        import ha_data
        self.server._findings_notify_target = lambda: ("", "critical")
        saved = ha_data.call_core_service

        async def call(domain, service, data=None, timeout=30):
            self.core_calls.append((domain, service, data))
            return []

        ha_data.call_core_service = call
        try:
            self.bus_event("on", "off")
        finally:
            ha_data.call_core_service = saved
        [row] = self.lane_rows()
        [(domain, service, data)] = self.core_calls
        self.assertEqual((domain, service),
                         ("persistent_notification", "create"))
        self.assertIn(str(row["ts"]), data["notification_id"])
        self.assertEqual(self.sent, [])


class TestOneCasePerTrip(SafetyCase):

    def trip(self, when: float, state: str = "on"):
        return asyncio.run(self.server._safety_trip(
            LEAK, "moisture", leak_state(state), when))

    def test_a_second_trip_after_the_first_was_dismissed_is_a_new_case(self):
        """The old case text was fixed, so once one case on a sensor had
        been dismissed every later trip deduped against the settled ledger
        and nothing was ever said about it again."""
        first = self.trip(time.time() - 7200)
        self.assertIsNotNone(first)
        self.server.findings_store.settle_and_clear(first["ts"], "ignored")
        second = self.trip(time.time())
        self.assertIsNotNone(second, "the second leak was swallowed")
        self.assertNotEqual(first["text"], second["text"])
        self.assertEqual(len(self.sent), 2)

    def test_a_chattering_detector_is_one_case(self):
        now = time.time()
        self.assertIsNotNone(self.trip(now))
        self.assertIsNone(self.trip(now + 60))
        self.assertEqual(len(self.lane_rows()), 1)
        self.assertEqual(self.server.SAFETY_STATE["repeats"], 1)

    def test_a_sensor_reporting_clear_annotates_the_card_and_stops_the_ladder(self):
        self.bus_event("on", "off")
        [row] = self.lane_rows()
        self.assertIn(row["ts"], self.server.notify_router.load_escalations())
        self.bus_event("off", "on")
        [after] = self.lane_rows()
        # The card stays — a leak that dried still came from somewhere —
        # and says so; the reminders stop.
        self.assertIn("reported off", after["detail"])
        self.assertNotIn(row["ts"],
                         self.server.notify_router.load_escalations())

    def test_a_look_that_says_act_after_the_lane_files_nothing_twice(self):
        self.bus_event("on", "off")
        sig = self.server.signals.from_state_change(
            {"entity_id": LEAK, "old_state": leak_state("off"),
             "new_state": leak_state("on")},
            self.server.signals.EMPTY_CONTEXT, time.time())
        self.assertTrue(sig["safety"], "a tripped detector carries no flag")
        self.server._resident_offer(sig)
        self.looks.append(reply([{"id": 1, "verdict": "act",
                                  "why": "water"}]))
        self.investigations.append(case_reply(
            claim="Water under the kitchen sink", evidence=[]))
        self.tick()
        rows = self.lane_rows()
        self.assertEqual(len(rows), 1)
        # The look's `act` became context ON the lane's card.
        self.assertEqual(rows[0]["claim"], "Water under the kitchen sink")


class TestTheFloorsAreReachable(unittest.TestCase):

    def setUp(self):
        import importlib
        self.server = importlib.import_module("server")
        self.resident = self.server.resident
        self.signals = self.server.signals
        self.router = self.server.notify_router

    def test_a_safety_flag_floors_a_look_at_act(self):
        sig = self.signals.make("state", LEAK, now=time.time(), hot=True,
                                safety=True, text="Kitchen leak → on")
        out = self.resident.parse_first_look(
            {"verdicts": [{"id": 1, "verdict": "ignore", "why": "fine"}]},
            1, [sig])
        self.assertEqual(out[1]["verdict"], "act")
        self.assertTrue(out[1]["forced"])

    def test_the_producer_is_read_as_well_as_the_kind(self):
        sig = self.signals.make("check", "sensor.loft", now=time.time(),
                                source="check:climate.freeze", text="pipes")
        floor, _ = self.resident.never_ignore(sig)
        self.assertIn(floor, ("investigate", "act"))

    def test_a_protected_entity_floors_at_investigate(self):
        sig = self.signals.make("state", "lock.front", now=time.time(),
                                protected=True)
        self.assertEqual(self.resident.never_ignore(sig)[0], "investigate")

    def test_critical_with_high_stakes_escalates_and_safety_is_now(self):
        self.assertEqual(self.router.urgency_of({"source": "safety"}), "now")
        self.assertEqual(self.router.tier_of(
            {"severity": "critical", "source": "resident", "stakes": "high"},
            "critical"), "escalate")
        # An investigation's own stakes top out at `serious`: they cannot
        # reach the escalate tier however sure the run was.
        self.assertEqual(self.router.tier_of(
            {"severity": "serious", "source": "resident", "stakes": "high"},
            "warning"), "notify")

    def test_the_bus_ceiling_never_drops_a_tripped_detector(self):
        import eventbus
        bus = eventbus.EventBus(lambda s: None)
        now = 1000.0
        for _ in range(eventbus.HARD_CEILING_PER_S + 5):
            bus._admits("state_changed", {"entity_id": "sensor.power"}, now)
        self.assertFalse(bus._admits(
            "state_changed", {"entity_id": "sensor.power"}, now))
        self.assertTrue(bus._admits(
            "state_changed", {"entity_id": LEAK, "new_state": leak_state()},
            now))


class TestTheInvestigationReadsWhatItRead(LoopCase):

    def write_transcript(self, session_id: str, traffic: list[dict]):
        import conversations
        import engine
        root = Path(self.tmp.name) / "claude"
        for mod in self.copies("conversations"):
            self._restore.append((mod, "CONFIG_DIR", mod.CONFIG_DIR))
            mod.CONFIG_DIR = str(root)
        project = root / "projects" / conversations._escape(engine.CLAUDE_HOME)
        project.mkdir(parents=True)
        with (project / f"{session_id}.jsonl").open("w") as fh:
            fh.write(json.dumps({"cwd": engine.CLAUDE_HOME}) + "\n")
            for entry in traffic:
                fh.write(json.dumps(entry) + "\n")

    def test_tool_results_count_and_the_final_answer_does_not(self):
        self.write_transcript("inv-1", [
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "name": "get_history",
                 "input": {"entity_id": "sensor.garage_freezer"}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": [
                    {"type": "text", "text": "sensor.outdoor_temp: 4.1"}]}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "I also saw sensor.invented_one"}]}},
        ])
        read = self.server._entities_read({"meta": {"session_id": "inv-1"}})
        self.assertIn("sensor.garage_freezer", read)
        self.assertIn("sensor.outdoor_temp", read)
        self.assertNotIn("sensor.invented_one", read)

    def test_an_unreadable_transcript_checks_nothing(self):
        self.assertIsNone(self.server._entities_read(
            {"meta": {"session_id": "no-such-run"}}))
        self.assertIsNone(self.server._entities_read({"meta": {}}))

    def test_a_case_citing_a_neighbour_it_read_is_filed(self):
        """With the guard reading the final prose, a case citing anything
        past the signal's own entity was refused whole on a schema-capable
        CLI — logged as 'made no claim' — however real the reading was."""
        self.write_transcript("inv-1", [
            {"type": "user", "message": {"content": [
                {"type": "tool_result",
                 "content": "sensor.outdoor_temp reads 4.1"}]}}])
        now = time.time()
        self.server._resident_offer(self.server.signals.make(
            "baseline", "sensor.garage_freezer", now=now,
            source="baseline:hour", text="far above its usual", salience=0.9))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "look"}]))
        self.investigations.append(case_reply(evidence=[
            {"entity": "sensor.outdoor_temp", "value": "4.1", "when": "now"}]))
        self.tick(now)
        filed = [f for f in self.server.findings_store.list_all()
                 if f["source"] == "resident"]
        self.assertEqual(len(filed), 1)

    def test_a_case_citing_what_it_never_read_is_refused_and_counted(self):
        self.write_transcript("inv-1", [
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "content": "nothing useful"}]}}])
        now = time.time()
        self.server._resident_offer(self.server.signals.make(
            "baseline", "sensor.garage_freezer", now=now,
            source="baseline:hour", text="far above its usual", salience=0.9))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "look"}]))
        self.investigations.append(case_reply(evidence=[
            {"entity": "sensor.made_up", "value": "4.1", "when": "now"}]))
        self.tick(now)
        self.assertEqual([f for f in self.server.findings_store.list_all()
                          if f["source"] == "resident"], [])
        self.assertEqual(self.server.RESIDENT_STATE.get("refused"), 1)


class TestAStrongerLookMayWithdraw(LoopCase):

    def test_an_empty_claim_from_the_escalation_files_nothing(self):
        import settings_store
        settings_store.save({"onboarded": True, "auto_enabled": True,
                             "thinking": "generous"})
        now = time.time()
        self.server._resident_offer(self.server.signals.make(
            "baseline", "sensor.garage_freezer", now=now,
            source="baseline:hour", text="far above its usual", salience=0.9))
        self.looks.append(reply([{"id": 1, "verdict": "investigate",
                                  "why": "look"}]))
        self.investigations.append(case_reply(confidence=0.3, escalate=True))
        self.investigations.append(case_reply(claim="", evidence=[]))
        self.tick(now)
        self.assertEqual(len(self.analyst_calls), 2)
        # The second run was handed the first one's case to judge.
        self.assertIn("A FIRST INVESTIGATION CONCLUDED THIS",
                      self.analyst_calls[1]["prompt"])
        self.assertEqual([f for f in self.server.findings_store.list_all()
                          if f["source"] == "resident"], [])


class TestResidentCasesCanBeAnswered(LoopCase):

    def file(self, **over):
        row = {"claim": "Is the garage freezer meant to be off overnight?",
               "kind": "question", "stakes": "medium",
               "memory_hint": "The garage freezer is switched off overnight.",
               **over}
        return self.server.findings_store.add_case({"text": row["claim"],
                                                    **row})

    def test_yes_on_a_resident_question_confirms_the_finding(self):
        row = self.file()
        cases = self.server.cases
        seen = []
        hooks = cases.Hooks(
            end_finding=lambda key, word, note: seen.append(
                ("end", key, word)),
            hypothesis=lambda key, word, note: seen.append(("hyp", key)),
            proposal=lambda key, word, note: seen.append(("prop", key)),
            finding_todo=lambda key: seen.append(("todo", key)))
        cases.end(f"f:{row['ts']}", "do", hooks=hooks)
        cases.end(f"f:{row['ts']}", "wrong", hooks=hooks)
        self.assertEqual(seen, [("end", row["ts"], "confirm"),
                                ("end", row["ts"], "wrong")])

    def test_do_on_a_resident_opportunity_goes_to_the_list(self):
        row = self.file(kind="opportunity", claim="The porch light could "
                        "follow sunset instead of 18:00")
        cases = self.server.cases
        seen = []
        hooks = cases.Hooks(
            finding_todo=lambda key: seen.append(("todo", key)),
            proposal=lambda key, word, note: seen.append(("prop", key)))
        cases.end(f"f:{row['ts']}", "do", hooks=hooks)
        self.assertEqual(seen, [("todo", row["ts"])])
        case = cases.get(f"f:{row['ts']}")
        self.assertNotEqual(cases.situation(case), "opportunity",
                            "Make the change offered over nothing to write")

    def test_confirm_files_the_cases_own_memory_hint(self):
        row = self.file()
        facts = []

        async def submit(fact, source="homeowner"):
            facts.append((fact, source))

        saved = self.server._submit_memory
        self.server._submit_memory = submit
        try:
            asyncio.run(self.server._end_finding(
                row, self.server.FINDING_VERBS["confirm"], ""))
        finally:
            self.server._submit_memory = saved
        hint = "The garage freezer is switched off overnight."
        self.assertEqual(facts, [(hint, "homeowner")])

    def test_the_resident_and_the_safety_lane_cannot_be_muted(self):
        from aiohttp import web
        row = self.file()
        case = self.server.cases.get(f"f:{row['ts']}")
        self.assertNotIn("mute", [o["verb"] for o in
                                  self.server.cases.overflow(case)])
        for source in ("resident", "safety"):
            with self.assertRaises(web.HTTPConflict):
                self.server._refuse_unmutable(source)
        self.server._refuse_unmutable("check:dev.frozen")


class TestCasesHaveALifecycle(LoopCase):

    def test_a_held_row_whose_severity_rose_is_looked_at_again(self):
        store = self.server.findings_store
        row = self.file_check_row()
        store.record_triage({row["ts"]: ("held", "fine at 30%")})
        self.assertEqual(store.get(row["ts"])["status"], "held")
        store.refresh_details([{**row, "severity": "serious",
                                "detail": "4% left"}])
        self.assertEqual(store.get(row["ts"])["status"], "triaging")
        # A severity that did not rise leaves the verdict standing.
        store.record_triage({row["ts"]: ("held", "still fine")})
        store.refresh_details([{**row, "severity": "serious",
                                "detail": "3% left"}])
        self.assertEqual(store.get(row["ts"])["status"], "held")

    def test_an_unanswered_resident_case_expires_by_its_stakes(self):
        store = self.server.findings_store
        now = time.time()
        def case(claim, **over):
            return {"text": claim, "claim": claim, **over}

        low = store.add_case(case("A minor thing", stakes="low"))
        high = store.add_case(case("A big thing", stakes="high"))
        lane = store.add_case(case("Water leak", stakes="high",
                                   source="safety"))
        # Eight days on for the first two, sixty for the lane's.
        gone = store.expire_cases(now + 8 * 86400)
        self.assertEqual([g["ts"] for g in gone], [low["ts"]])
        gone = store.expire_cases(now + 60 * 86400)
        self.assertEqual([g["ts"] for g in gone], [high["ts"]])
        self.assertIsNotNone(store.get(lane["ts"]),
                             "a safety case expired without anybody looking")


if __name__ == "__main__":
    unittest.main()
