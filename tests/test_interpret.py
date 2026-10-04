#!/usr/bin/env python3
"""One reader for what a person typed, and the old code when it cannot read.

`interpret.py` maps words and the surface they arrived on to routes out of
a closed vocabulary; `server` hands each route to code that already exists.
Driven through the real routes and the real request drain, with only
`engine.run_claude` / `engine.run_analyst` stubbed. Mutations each test
names:

  the fallback is gone       return a card when the reader is unavailable
                             -> "learn about…" stops reaching a study
  a surface is not narrowed  drop `ALLOWED` -> a case ending on the ask bar
  a reply only converses     skip `_reply_routes` -> "it's always like that
                             in winter" ends nothing
  the phone has no Undo      drop the `undo` action -> the button is dead
  "no record" is "decided"   drop the empty-trail sentence from the prompt
"""
from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))

import decision_trail  # noqa: E402
import findings_store  # noqa: E402
import interpret  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

NOW = 1_790_000_000.0


class TestParse(unittest.TestCase):
    def test_a_closed_vocabulary_narrowed_by_the_surface(self):
        data = {"routes": [{"kind": "case_ending", "ending": "wrong"},
                           {"kind": "card_question", "text": "how much"}]}
        got = interpret.parse(data, "ask_bar", "how much")
        self.assertEqual([r["kind"] for r in got], ["card_question"])
        self.assertIsNone(interpret.parse(
            {"routes": [{"kind": "case_ending", "ending": "wrong"}]},
            "ask_bar", "x"))
        reply = interpret.parse(data, "reply", "x")
        self.assertEqual([r["kind"] for r in reply], ["case_ending"])

    def test_an_ending_must_name_one_of_the_four(self):
        self.assertIsNone(interpret.parse(
            {"routes": [{"kind": "case_ending", "ending": "delete"}]},
            "reply", "x"))

    def test_one_message_ends_a_case_once(self):
        got = interpret.parse({"routes": [
            {"kind": "case_ending", "ending": "wrong", "note": "a"},
            {"kind": "defer", "hours": 24},
            {"kind": "remember", "text": "the freezer is off in winter"}]},
            "reply", "x")
        self.assertEqual([r["kind"] for r in got], ["case_ending", "remember"])

    def test_capped_and_cleaned(self):
        many = {"routes": [{"kind": "remember", "text": f"fact {i}"}
                           for i in range(9)]}
        self.assertEqual(len(interpret.parse(many, "ask_bar", "x")),
                         interpret.MAX_ROUTES)
        defer = interpret.parse({"routes": [{"kind": "defer", "hours": 9999}]},
                                "reply", "x")
        self.assertNotIn("hours", defer[0])
        self.assertIsNone(interpret.parse({"routes": [{"kind": "scenes"}]},
                                          "ask_bar", "x"))

    def test_anything_unreadable_is_no_answer(self):
        for data in (None, "text", {}, {"routes": "x"}, {"routes": [{}]},
                     {"routes": [{"kind": "launch"}]}):
            with self.subTest(data=data):
                self.assertIsNone(interpret.parse(data, "ask_bar", "x"))

    def test_the_gate(self):
        interpret.STATE.update(day="", runs=0)
        self.assertTrue(interpret.gate("ask_bar", has_auth=False, now=NOW))
        self.assertEqual(interpret.gate("ask_bar", has_auth=True,
                                        auto_enabled=False, budget_ok=False,
                                        now=NOW), "")
        self.assertTrue(interpret.gate("service", has_auth=True,
                                       budget_ok=False, now=NOW))
        self.assertTrue(interpret.gate("service", has_auth=True,
                                       auto_enabled=False, now=NOW))
        interpret.STATE.update(day=interpret._day(NOW),
                               runs=interpret.MAX_PER_DAY)
        self.assertIn("today", interpret.gate("ask_bar", has_auth=True,
                                              now=NOW))
        interpret.STATE.update(day="", runs=0)


class TestExplainContract(unittest.TestCase):
    def test_no_record_is_said_in_words(self):
        empty = interpret.explain_prompt("why didn't you tell me",
                                         subject="Garage door",
                                         trail={"readable": True, "rows": []})
        self.assertIn("NO decision", empty)
        unreadable = interpret.explain_prompt(
            "why", trail={"readable": False, "rows": []})
        self.assertIn("could not be read", unreadable)
        rows = interpret.explain_prompt("why", trail={"readable": True, "rows": [
            {"ts": NOW, "kind": "quiet_hold", "meaning": "held for quiet hours",
             "reason": "held 22:00–07:00", "check": "evening.left_open"}]})
        self.assertIn("held for quiet hours", rows)

    def test_parse_explain(self):
        self.assertIsNone(interpret.parse_explain({"kind": "why", "answer": "x"}))
        self.assertIsNone(interpret.parse_explain({"kind": "why_happened",
                                                   "answer": " "}))
        got = interpret.parse_explain({"kind": "why_not_told",
                                       "answer": "It was held",
                                       "cited": ["22:10 quiet_hold", 3],
                                       "offer": "Ring me even at night"})
        self.assertEqual(got["cited"], ["22:10 quiet_hold"])


class AskCase(RouteCase):
    def setUp(self):
        super().setUp()
        s = self.server
        self._ask_olds = (s.engine.run_analyst, s.intents.request,
                          s.onboarding.request_study, s.finding_requests.collect,
                          s.EXPLAINS.copy())
        self.analyst = []

        def analyst(prompt, system, model="", timeout=480, max_turns=40,
                    source="", *, job="", effort="", schema=None):
            self.analyst.append((job, prompt))
            if job in self.replies:
                return {"ok": True, "data": self.replies[job], "text": "",
                        "error": "", "meta": {}}
            return {"ok": True, "text": "Here is what I found.", "error": "",
                    "meta": {}}

        s.engine.run_analyst = analyst
        self.intent_calls = []
        s.intents.request = lambda text, via="panel": (
            self.intent_calls.append((text, via)) or text[:40])
        self.studies = []
        s.onboarding.request_study = lambda topic="", *a, **k: (
            self.studies.append(topic) or topic)

    def tearDown(self):
        s = self.server
        (s.engine.run_analyst, s.intents.request, s.onboarding.request_study,
         s.finding_requests.collect, explains) = self._ask_olds
        s.EXPLAINS.clear()
        s.EXPLAINS.update(explains)
        super().tearDown()

    def ask(self, question):
        async def body(client):
            res = await client.post("/api/generate", json={"question": question})
            self.assertEqual(res.status, 200, await res.text())
            out = await res.json()
            await asyncio.gather(*list(self.server._EXPLAIN_TASKS))
            return out
        return self.drive(body)


class TestTheAskBar(AskCase):
    def test_without_a_credential_the_patterns_answer(self):
        self.server.engine.get_auth = lambda: None
        self.assertIn("learning", self.ask("learn about the boiler"))
        self.assertEqual(self.studies, ["the boiler"])
        out = self.ask("when the guests leave, turn the porch light off")
        self.assertIn("intent", out)
        self.assertEqual(self.jobs, [])

    def test_a_failed_read_is_the_old_bar(self):
        self.replies.pop("interpret", None)     # "OK" is not a route list
        out = self.ask("learn about the boiler")
        self.assertIn("learning", out)
        self.assertNotIn("routes", out)
        self.assertEqual(self.model_jobs(), ["interpret"])
        self.assertTrue(self.server.interpret.STATE["fallbacks"])

    def test_two_things_in_one_sentence(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "remember", "text": "the garage freezer is off in winter"},
            {"kind": "card_question", "text": "how much did the freezer use"}]}
        out = self.ask("the garage freezer is off in winter — how much did it "
                       "use?")
        self.assertEqual(out["routes"], ["remember", "card_question"])
        self.assertEqual(out["remembered"],
                         ["the garage freezer is off in winter"])
        self.assertEqual(len(out["queued"]), 1)
        self.assertIn("the garage freezer is off in winter",
                      self.queued_memory())

    def test_a_rule_goes_to_the_intent_drop(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "standing_rule",
             "text": "turn the hall light on when the door opens after dark"}]}
        out = self.ask("hall light on with the door after dark")
        self.assertIn("intent", out)
        self.assertEqual(self.intent_calls[0][1], "panel")

    def test_why_is_answered_with_the_trail(self):
        decision_trail.note("quiet_hold", self.ENTITY,
                            "held for quiet hours (22:00–07:00)",
                            check="evening.left_open", now=NOW)
        self.replies["interpret"] = {"routes": [
            {"kind": "explain", "text": "why didn't you tell me",
             "subject": "Cupboard door"}]}
        self.replies["explain"] = {"kind": "why_not_told",
                                   "answer": "It was held for quiet hours.",
                                   "cited": ["quiet_hold 22:10"],
                                   "offer": "Tell me about doors even at night"}
        out = self.ask("why didn't you tell me about the cupboard door")
        got = self.server.EXPLAINS[out["explain"]]
        self.assertEqual(got["state"], "done")
        self.assertEqual(got["kind"], "why_not_told")
        self.assertEqual(got["subject"], self.ENTITY)
        job, prompt = self.analyst[-1]
        self.assertEqual(job, "explain")
        self.assertIn("held for quiet hours", prompt)

        async def fetch(client):
            res = await client.get(f"/api/explain/{out['explain']}")
            return res.status, await res.json()

        status, body = self.drive(fetch)
        self.assertEqual(status, 200)
        self.assertEqual(body["offer"], "Tell me about doors even at night")

    def test_why_with_no_record_says_so_to_the_run(self):
        self.replies["interpret"] = {"routes": [
            {"kind": "explain", "text": "why didn't you tell me",
             "subject": "Cupboard door"}]}
        self.ask("why didn't you tell me about the cupboard door")
        self.assertIn("NO decision", self.analyst[-1][1])


class TestWhyRoute(AskCase):
    def test_rows_and_the_sentence_for_none(self):
        decision_trail.note("cap", self.ENTITY, "12 at once",
                            check="dev.frozen", now=NOW)

        async def body(client):
            a = await (await client.get(f"/api/why?entity={self.ENTITY}")).json()
            b = await (await client.get("/api/why?entity=sensor.none")).json()
            return a, b

        found, none = self.drive(body)
        self.assertEqual(found["rows"][0]["kind"], "cap")
        self.assertEqual(found["name"], "Cupboard door")
        self.assertEqual(none["rows"], [])
        self.assertIn("no record", none["says"])


class PhoneCase(AskCase):
    def setUp(self):
        super().setUp()
        import ha_data
        self.ha_data = ha_data
        self._send = ha_data.send_notification
        self.sent = []

        async def send(service, title, body, data=None):
            self.sent.append({"service": service, "title": title, "body": body,
                              "data": data or {}})

        ha_data.send_notification = send
        self.server._findings_notify_target = lambda: (
            "notify.mobile_app_phone", "warning")

    def tearDown(self):
        self.ha_data.send_notification = self._send
        self.server.PHONE_UNDO.clear()
        super().tearDown()


class TestAReplyCanEndTheCase(PhoneCase):
    def test_a_correction_typed_on_a_phone(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "wrong",
             "note": "it's always like that until October"}]}
        self.replies["correct"] = {"scope": "entity_check", "lifetime": "month",
                                   "until_month": 10}

        async def body(_client):
            return await self.server._reply_to_finding(
                row, "it's always like that until October")

        ok, why = self.drive(body)
        self.assertTrue(ok, why)
        self.assertIsNone(findings_store.get(row["ts"]))
        rules = self.rules()
        self.assertEqual(len(rules), 1)
        self.assertTrue(rules[0]["expires"])
        sent = self.sent[-1]
        self.assertIn("until", sent["body"])
        self.assertIn("I'll stop flagging it", sent["body"])
        buttons = sent["data"]["actions"]
        self.assertEqual([b["title"] for b in buttons], ["Undo"])
        self.assertEqual(buttons[0]["action"], f"brain.undo.{row['ts']}")
        # Nothing conversed: the Resident was not asked.
        self.assertEqual([j for j, _ in self.analyst], [])

        self.server.finding_requests.collect = lambda: [
            {"ts": row["ts"], "action": "undo", "note": "", "hours": None,
             "via": "notification"}]

        async def undo(_client):
            return await self.server._apply_finding_requests()

        results = self.drive(undo)
        self.assertTrue(results[0]["ok"], results)
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertEqual(self.rules(), [])

    def test_a_question_is_still_a_conversation(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [{"kind": "chat"}]}

        async def body(_client):
            return await self.server._reply_to_finding(row, "is it the battery?")

        ok, _ = self.drive(body)
        self.assertTrue(ok)
        self.assertEqual([j for j, _ in self.analyst], ["investigate"])
        self.assertIsNotNone(findings_store.get(row["ts"]))

    def test_unread_is_the_conversation_it_always_was(self):
        self.server.engine.get_auth = lambda: None
        row = self.check_row()

        async def body(_client):
            return await self.server._reply_to_finding(row, "it's like that")

        self.drive(body)
        self.assertEqual(self.jobs, [])
        self.assertEqual([j for j, _ in self.analyst], ["investigate"])
        self.assertIsNotNone(findings_store.get(row["ts"]))

    def test_the_undo_action_is_one_word_on_both_sides(self):
        # The integration's half cannot be imported without Home Assistant,
        # and a wire format is the one thing two processes must agree on,
        # so its tuple is read off the file itself.
        import ast
        tree = ast.parse((BASE_DIR / "brain" / "custom_components" / "brain"
                          / "requests.py").read_text())
        ha_actions = next(
            ast.literal_eval(node.value) for node in tree.body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "ACTIONS" for t in node.targets))
        self.assertIn("undo", ha_actions)
        self.assertEqual(tuple(ha_actions),
                         tuple(self.server.finding_requests.ACTIONS))


class TestTheRepairsBox(PhoneCase):
    def test_remind_me_tomorrow_is_a_defer_not_a_rule(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [{"kind": "defer", "hours": 24}]}
        self.server.finding_requests.collect = lambda: [
            {"ts": row["ts"], "action": "wrong", "note": "remind me tomorrow",
             "hours": None, "via": "repairs"}]

        async def body(_client):
            return await self.server._apply_finding_requests()

        results = self.drive(body)
        self.assertTrue(results[0]["ok"])
        kept = findings_store.get(row["ts"])
        self.assertIsNotNone(kept)
        self.assertTrue(kept.get("snoozed_until"))
        self.assertEqual(self.rules(), [])

    def test_unread_it_is_the_wrong_it_always_was(self):
        self.server.engine.get_auth = lambda: None
        row = self.check_row()
        self.server.finding_requests.collect = lambda: [
            {"ts": row["ts"], "action": "wrong", "note": "remind me tomorrow",
             "hours": None, "via": "repairs"}]

        async def body(_client):
            return await self.server._apply_finding_requests()

        self.drive(body)
        self.assertIsNone(findings_store.get(row["ts"]))
        self.assertEqual(len(self.rules()), 1)


class TestTheService(AskCase):
    def test_a_fact_sent_by_an_automation_is_kept_not_armed(self):
        settings = self.server.settings_store
        settings.save({"onboarded": True, "auto_enabled": True})
        self.replies["interpret"] = {"routes": [
            {"kind": "remember", "text": "the pool pump runs at night"}]}

        async def body(_client):
            return await self.server._service_routes(
                {"sentence": "the pool pump runs at night", "via": "service"},
                NOW)

        self.assertEqual(self.drive(body), 1)
        self.assertIn("the pool pump runs at night", self.queued_memory())
        self.assertEqual([j for j, _ in self.analyst], [])

    def test_paused_it_is_the_intent_path(self):
        self.server.settings_store.save({"onboarded": True,
                                         "auto_enabled": False})

        async def body(_client):
            return await self.server._service_routes(
                {"sentence": "x", "via": "service"}, NOW)

        self.assertIsNone(self.drive(body))
        self.assertEqual(self.model_jobs(), [])


class TestTheTool(unittest.TestCase):
    def setUp(self):
        import ha_mcp_server
        self.mcp = ha_mcp_server
        self._get = ha_mcp_server._panel_get
        self.asked = []

        def fake(path, timeout=60):
            self.asked.append(path)
            return {"subject": "sensor.a", "readable": True, "name": "A",
                    "says": "", "rows": [
                        {"ts": NOW, "kind": "mute", "meaning": "muted",
                         "reason": "you asked", "check": "dev.frozen"}]}

        ha_mcp_server._panel_get = fake

    def tearDown(self):
        self.mcp._panel_get = self._get

    def test_reads_the_panel_and_refuses_what_is_not_an_id(self):
        got = self.mcp.explain_decision(entity_id="sensor.a")
        self.assertEqual(got["decisions"][0]["kind"], "mute")
        self.assertIn("entity=sensor.a", self.asked[-1])
        self.assertIn("error", self.mcp.explain_decision(entity_id="x&y=1"))
        self.mcp.explain_decision(check_id="dev.frozen")
        self.assertIn("check=dev.frozen", self.asked[-1])

    def test_it_is_a_read_the_analyst_may_make_and_voice_may_not(self):
        import engine
        self.assertIn("mcp__home-assistant__explain_decision",
                      engine.ANALYST_TOOLS)
        self.assertNotIn("mcp__home-assistant__explain_decision",
                         engine.ANALYST_DENIED)
        self.assertIn("explain_decision", self.mcp.VOICE_REFUSED_TOOLS)


if __name__ == "__main__":
    unittest.main()
