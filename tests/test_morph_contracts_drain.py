#!/usr/bin/env python3
"""Morph's answers on a case, through the real request drain (contract C).

brAIn 3.0 makes a finding a conversation (morph-vision §14): Morph drops a
request on the queue every other surface writes to, the panel reads a reply
with the interpreter on the `morph` surface, and the words decide the ending
— through the same `_end_finding`, `_move_finding_to_todo`, plan and
dismiss code the panel's own buttons run. These drive the real
`_apply_finding_requests` over request files, with only the Claude runs
stubbed (`RouteCase`'s `run_claude`, and `run_analyst` here).

Mutations each test names:

  consent applies           make "yes" call `_start_apply` -> the plan test
                            sees `fixing`, not `planning`
  a refusal teaches nothing drop the note from `_morph_wrong` -> no rule
  the thread is lost        skip `_morph_turn` -> no turns on the row
  a guess is guessed        drop `_plain_morph_routes`' exact match -> a
                            sentence nobody could read ends the case
  Morph's suggestion files  skip `note_ended` -> `ended_morph` is empty
  into memory               let `_end_finding` past `_end_morph_case` ->
                            a memory line about a dashboard layout
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(BASE_DIR / "tests"))

import findings_store  # noqa: E402
import todo_store  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402


class MorphCase(RouteCase):
    ENTITY = "binary_sensor.cupboard"

    def setUp(self):
        super().setUp()
        s = self.server
        root = Path(self.tmp.name)
        (root / "config" / ".brain").mkdir(parents=True)
        (root / "data").mkdir()
        self._morph_olds = (
            s.finding_requests.REQUEST_DIR, s.morph_bridge.MORPH_DIR,
            s.morph_bridge.ENDED_FILE, s.morph_bridge.THREADS_FILE,
            s.cases.SNOOZE_FILE, s.hypotheses.HYPOTHESES_FILE,
            s.proposals.STORE, s.deliveries.DELIVERIES_FILE,
            s.engine.run_analyst, s.intents.request, s.journal.JOURNAL_FILE)
        s.journal.JOURNAL_FILE = str(root / "data" / "journal.jsonl")
        s.finding_requests.REQUEST_DIR = root / "requests"
        s.finding_requests.REQUEST_DIR.mkdir()
        s.morph_bridge.MORPH_DIR = root / "config" / ".brain" / "morph"
        s.morph_bridge.ENDED_FILE = root / "data" / "morph-ended.json"
        s.morph_bridge.THREADS_FILE = root / "data" / "morph-threads.json"
        s.cases.SNOOZE_FILE = root / "data" / "cases-snooze.json"
        s.hypotheses.HYPOTHESES_FILE = root / "data" / "hypotheses.json"
        s.proposals.STORE = root / "data" / "proposals.json"
        s.deliveries.DELIVERIES_FILE = root / "data" / "deliveries.jsonl"
        self.analyst = []

        def analyst(prompt, system, model="", timeout=480, max_turns=40,
                    source="", **kw):
            self.analyst.append((kw.get("job"), prompt, system))
            return {"ok": True, "text": "The one by the stairs; it reads 61%.",
                    "error": "", "meta": {}}

        s.engine.run_analyst = analyst
        self.intents = []
        s.intents.request = lambda text, via="panel", **k: (
            self.intents.append((text, via)) or text[:40])
        s.MORPH_UNDO.clear()
        self.seq = 0

    def tearDown(self):
        s = self.server
        (s.finding_requests.REQUEST_DIR, s.morph_bridge.MORPH_DIR,
         s.morph_bridge.ENDED_FILE, s.morph_bridge.THREADS_FILE,
         s.cases.SNOOZE_FILE, s.hypotheses.HYPOTHESES_FILE,
         s.proposals.STORE, s.deliveries.DELIVERIES_FILE,
         s.engine.run_analyst, s.intents.request,
         s.journal.JOURNAL_FILE) = self._morph_olds
        s.MORPH_UNDO.clear()
        super().tearDown()

    def request(self, body: dict) -> None:
        self.seq += 1
        path = self.server.finding_requests.REQUEST_DIR / f"{self.seq:04d}.json"
        path.write_text(json.dumps(body), encoding="utf-8")

    def drain(self) -> list[dict]:
        async def go():
            out = await self.server._apply_finding_requests()
            await self.server._settle_morph(timeout=30)
            return out
        return asyncio.run(go())

    def reply(self, case_id: str, words: str) -> list[dict]:
        self.request({"kind": "morph", "case": case_id, "action": "reply",
                      "text": words, "via": "morph"})
        return self.drain()

    def thread(self, ts: int) -> list[dict]:
        row = findings_store.get(ts)
        if row is not None and row.get("thread"):
            return row["thread"]
        return self.server.morph_bridge.threads().get(f"f:{ts}", [])


class TestAReplyIsReadThenDone(MorphCase):
    def test_yes_on_a_fixable_problem_plans_with_the_instruction(self):
        row = self.check_row("auto.dead_ref")
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "consent",
             "change": "call it Sump Pump Current"}]}
        got = self.reply(f"f:{row['ts']}", "yes, but call it Sump Pump Current")
        self.assertTrue(got[0]["ok"], got)
        # Planned, never applied: Apply is its own consent.
        self.assertEqual(findings_store.get(row["ts"])["status"], "planning")
        job = self.server.JOBS[f"{self.server.PLAN_JOB_PREFIX}{row['ts']}"]
        self.assertEqual(job.get("change"), "call it Sump Pump Current")
        turns = self.thread(row["ts"])
        self.assertEqual([t["who"] for t in turns], ["you", "brain"])
        self.assertIn("call it Sump Pump", turns[0]["text"])
        self.assertIn("working out the change", turns[1]["text"])
        # The interpreter was asked on Morph's own surface and schema.
        self.assertIn("interpret", self.model_jobs())

    def test_no_with_a_reason_is_wrong_and_teaches(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "wrong",
             "note": "it's mains powered"}]}
        self.replies["correct"] = {"scope": "entity_check",
                                   "lifetime": "permanent"}
        self.reply(f"f:{row['ts']}", "no, it's mains powered")
        self.assertIsNone(findings_store.get(row["ts"]))
        self.assertEqual([e["kind"] for e in findings_store.settled_listing()],
                         ["ignored"])
        self.assertTrue(self.rules())
        # The row is gone, so what brAIn said is kept beside it and
        # published as `said` for Morph to show as the card sinks.
        turns = self.thread(row["ts"])
        self.assertEqual(turns[0]["text"], "no, it's mains powered")
        self.assertEqual(turns[-1]["who"], "brain")
        payload = self.server._morph_cases_payload()
        self.assertEqual([s["case"] for s in payload["said"]],
                         [f"f:{row['ts']}"])
        # And Morph's Undo puts every half back.
        self.request({"kind": "morph", "case": f"f:{row['ts']}",
                      "action": "undo"})
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertEqual(self.rules(), [])

    def test_a_question_back_is_answered_and_ends_nothing(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [{"kind": "chat"}]}
        self.reply(f"f:{row['ts']}", "which sensor is that?")
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertEqual([j for j, _p, _s in self.analyst], ["explain"])
        _job, prompt, system = self.analyst[0]
        self.assertIn("<<<REPLY\nwhich sensor is that?\nREPLY>>>", prompt)
        self.assertIs(system, self.server.MORPH_REPLY_SYSTEM)
        turns = self.thread(row["ts"])
        self.assertEqual(turns[-1]["text"], "The one by the stairs; it reads 61%.")

    def test_a_dashboard_half_rides_on_brains_turn_for_morph(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [
            {"kind": "dashboard", "text": "add it to the kitchen card"}]}
        self.reply(f"f:{row['ts']}", "add it to the kitchen card")
        turn = self.thread(row["ts"])[-1]
        self.assertEqual(turn["tell"], {"kind": "dashboard",
                                        "text": "add it to the kitchen card"})

    def test_unread_one_word_answers_still_work_and_nothing_else_is_guessed(self):
        self.server.engine.get_auth = lambda: None
        row = self.check_row()
        self.reply(f"f:{row['ts']}", "it's the one by the boiler I think")
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertIn("could not read that", self.thread(row["ts"])[-1]["text"])
        self.reply(f"f:{row['ts']}", "Later.")
        self.assertGreater(findings_store.get(row["ts"])["snoozed_until"],
                           time.time())

    def test_a_bare_no_writes_no_reason(self):
        self.server.engine.get_auth = lambda: None
        row = self.check_row()
        self.reply(f"f:{row['ts']}", "no")
        [entry] = findings_store.settled_listing()
        self.assertEqual(entry["kind"], "ignored")
        self.assertEqual(entry.get("note", ""), "")


class TestThePresses(MorphCase):
    def test_todo_uses_the_cards_own_sentence(self):
        entry, _ = findings_store.add(
            "Cupboard door battery is low", severity="warning",
            fix="Replace its battery.", entity_id=self.ENTITY,
            source="check:dev.battery_low", source_title="Low batteries",
            todo_text="Replace the battery in the cupboard door sensor.")
        self.request({"kind": "morph", "case": f"f:{entry['ts']}",
                      "action": "todo"})
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        [item] = todo_store.listing()["items"]
        self.assertEqual(item["text"],
                         "Replace the battery in the cupboard door sensor.")
        self.assertEqual(item["claim"], "Cupboard door battery is low")
        self.assertEqual(item["from_case"], f"f:{entry['ts']}")

    def test_dismiss_then_undo(self):
        row = self.check_row()
        self.request({"kind": "morph", "case": f"f:{row['ts']}",
                      "action": "dismiss"})
        self.drain()
        self.assertIsNone(findings_store.get(row["ts"]))
        self.assertEqual(findings_store.settled_listing(), [])
        self.request({"kind": "morph", "case": f"f:{row['ts']}",
                      "action": "undo"})
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        self.assertIsNotNone(findings_store.get(row["ts"]))

    def test_a_snooze_with_its_hours(self):
        row = self.check_row()
        self.request({"kind": "morph", "case": f"f:{row['ts']}",
                      "action": "snooze", "hours": 48})
        self.drain()
        until = findings_store.get(row["ts"])["snoozed_until"]
        self.assertAlmostEqual(until, time.time() + 48 * 3600, delta=120)

    def test_a_to_do_item_slides_aside_for_a_week(self):
        item = todo_store.add("Empty the dehumidifier")
        self.request({"kind": "todo", "action": "snooze", "id": item["id"],
                      "days": 7, "via": "morph"})
        got = self.drain()
        self.assertTrue(got[0]["ok"], got)
        until = self.server.cases.snoozes()[f"t:{item['id']}"]
        self.assertAlmostEqual(until, time.time() + 7 * 86400, delta=120)
        rows = self.server._morph_cases_payload()["todo"]
        self.assertEqual(rows[0]["snoozed_until"], until)

    def test_apply_needs_a_plan(self):
        row = self.check_row("auto.dead_ref")
        self.request({"kind": "morph", "case": f"f:{row['ts']}",
                      "action": "apply"})
        got = self.drain()
        self.assertFalse(got[0]["ok"])
        self.assertIn("no plan", got[0]["why"])


class TestMorphsOwnSuggestions(MorphCase):
    def file(self, key="sug-abc", claim="Move Kitchen above Dining."):
        self.request({"kind": "morph_case", "action": "file", "key": key,
                      "case_kind": "opportunity", "claim": claim,
                      "detail": "You open it first every morning.",
                      "ask": "Should I move it?", "via": "morph"})
        return self.drain()

    def test_filed_with_its_key_and_on_the_list(self):
        got = self.file()
        self.assertTrue(got[0]["ok"], got)
        row = findings_store.get(int(got[0]["case"].split(":")[1]))
        self.assertEqual(row["source"], "morph")
        self.assertEqual(row["morph_key"], "sug-abc")
        self.assertEqual(row["status"], "open")
        case = [c for c in self.server._morph_cases_payload()["cases"]
                if c["id"] == got[0]["case"]]
        self.assertEqual(case[0]["morph_key"], "sug-abc")
        # Filing the same key twice is one card.
        self.assertFalse(self.file()[0]["ok"])

    def test_yes_is_accepted_for_morph_and_files_no_memory(self):
        got = self.file()
        case = got[0]["case"]
        self.server.engine.get_auth = lambda: None
        self.reply(case, "yes")
        self.assertIsNone(findings_store.get(int(case.split(":")[1])))
        ended = self.server.morph_bridge.ended()
        self.assertEqual([(e["key"], e["how"]) for e in ended],
                         [("sug-abc", "accepted")])
        self.assertEqual(self.queued_memory(), [])
        self.assertEqual(self.server._morph_cases_payload()["ended_morph"],
                         ended)

    def test_dismissed_and_withdrawn(self):
        got = self.file()
        self.request({"kind": "morph", "case": got[0]["case"],
                      "action": "dismiss"})
        self.drain()
        self.assertEqual([e["how"] for e in self.server.morph_bridge.ended()],
                         ["dismissed"])
        again = self.file(key="sug-two", claim="Fold the garage at night.")
        self.request({"kind": "morph_case", "action": "withdraw",
                      "key": "sug-two"})
        out = self.drain()
        self.assertTrue(out[0]["ok"], out)
        self.assertIsNone(findings_store.get(int(again[0]["case"].split(":")[1])))
        # A withdrawal is Morph's own and says nothing to Morph.
        self.assertEqual(len(self.server.morph_bridge.ended()), 1)

    def test_a_muted_producer_files_nothing(self):
        import settings_store
        settings_store.save({"onboarded": True, "muted_sources": ["morph"]})
        got = self.file()
        self.assertFalse(got[0]["ok"])
        self.assertIn("muted", got[0]["why"])


class TestTheAskLine(MorphCase):
    def ask(self, text):
        return asyncio.run(self.server._answer_morph_ask(
            {"id": "a-abcdef12", "text": text, "ts": int(time.time()),
             "user_id": "u"}))

    def test_remember_is_done_brain_side(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "remember", "text": "the garage fridge is the beer fridge"}]}
        out = self.ask("remember that the garage fridge is the beer fridge")
        self.assertEqual(out["do"], "done")
        self.assertEqual(out["routes"], ["remember"])
        self.assertEqual(out["say"], "Remembered.")
        self.assertIn("the garage fridge is the beer fridge",
                      self.queued_memory())

    def test_a_layout_change_is_morphs_tell(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "dashboard",
             "text": "move the kitchen above the dining room"}]}
        out = self.ask("move the kitchen above the dining room")
        self.assertEqual(out["do"], "tell_dashboard")
        self.assertEqual(out["tell_text"], "move the kitchen above the dining room")

    def test_a_question_is_a_conversation_and_a_rule_is_drafted(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "chat", "text": "why is it warm upstairs?"}]}
        self.assertEqual(self.ask("why is it warm upstairs?")["do"],
                         "conversation")
        self.replies["interpret"] = {"routes": [
            {"kind": "standing_rule",
             "text": "turn the porch light off when everyone is asleep"}]}
        out = self.ask("turn the porch light off when everyone is asleep")
        self.assertEqual(out["do"], "done")
        self.assertEqual(self.intents[-1][1], "morph")

    def test_no_answer_is_fallback(self):
        self.server.engine.get_auth = lambda: None
        self.assertEqual(self.ask("anything")["do"], "fallback")

    def test_the_answer_is_written_and_an_old_ask_dropped(self):
        bridge = self.server.morph_bridge
        asks = bridge.MORPH_DIR / "asks"
        asks.mkdir(parents=True)
        (asks / "a-1.json").write_text(json.dumps(
            {"id": "a-00001111", "text": "hi", "ts": int(time.time())}))
        (asks / "a-2.json").write_text(json.dumps(
            {"id": "a-00002222", "text": "old", "ts": int(time.time()) - 300}))
        taken = bridge.take_asks()
        self.assertEqual([a["id"] for a in taken], ["a-00001111"])
        self.assertEqual(list(asks.glob("*.json")), [])
        self.server.engine.get_auth = lambda: None
        asyncio.run(self.server._morph_ask(taken[0]))
        answer = json.loads((bridge.MORPH_DIR / "answers" / "a-00001111.json")
                            .read_text())
        self.assertEqual(answer["do"], "fallback")
        self.assertEqual(answer["id"], "a-00001111")


if __name__ == "__main__":
    unittest.main()


class TestACaseIsSentWithItsRoom(MorphCase):
    """The audit: ten of twelve cases reached Morph with no area, so most
    fell to the house-wide fold. A case whose subject has no room takes the
    room most of its evidence is in."""

    def test_the_evidence_names_the_room(self):
        ctx = self.server._FACTS_CTX
        old = ctx.get("entity_areas")
        ctx["entity_areas"] = {"sensor.garage_freezer": "garage",
                               "sensor.garage_door": "garage",
                               "sensor.outdoor": "outside"}
        try:
            got = self.server._morph_case_area({
                "entity_id": "",
                "evidence": [{"entity": "sensor.outdoor"},
                             {"entity": "sensor.garage_freezer"},
                             "sensor.garage_door"]})
            self.assertEqual(got, "garage")
            self.assertEqual(self.server._morph_case_area(
                {"entity_id": "sensor.outdoor",
                 "evidence": ["sensor.garage_door"]}), "outside",
                "the subject's own room wins over its evidence")
            self.assertEqual(self.server._morph_case_area({}), "")
        finally:
            if old is None:
                ctx.pop("entity_areas", None)
            else:
                ctx["entity_areas"] = old
