"""The Respond box under a card on Today is Morph's reply line, in the panel.

The owner, under a "Protection mode off" finding whose right answer was
"BRUH Task Manager needs it off; remember that": *"These buttons don't
cover what needs to happen here … maybe the button is like Respond and I
just type one quick instruction or response to brAIn and it either does
that to fix it, write it to memory, or whatever."* So a card carries a
one-line box, and what is typed there goes through `_morph_reply` on the
interpreter's `panel` surface: the same endings, the same thread on the
row, the same undo token — handed back to the panel's own toast.

Each case is driven through the real routes, with only the model stubbed
(`RouteCase`'s `engine.run_claude`, `MorphCase`'s `engine.run_analyst`).
"""
from __future__ import annotations

import time
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain"
                       / "panel"))

import findings_store  # noqa: E402
import interpret  # noqa: E402
from test_morph_contracts_drain import MorphCase  # noqa: E402


class RespondCase(MorphCase):
    def setUp(self):
        super().setUp()
        self.server.RESPOND_RESULTS.clear()

    def respond(self, case_id: str, words: str) -> dict:
        """Post the reply, wait for the held task, read the result."""
        out: dict = {}

        async def body(client):
            res = await client.post(f"/api/case/{case_id}/respond",
                                    json={"text": words})
            out["status"] = res.status
            out["started"] = await res.json()
            await self.server._settle_morph(timeout=30)
            got = await client.get(f"/api/case/{case_id}/respond")
            out["result"] = await got.json()

        self.drive(body)
        return out

    def respond_then_undo(self, case_id: str, words: str) -> dict:
        out: dict = {}

        async def body(client):
            res = await client.post(f"/api/case/{case_id}/respond",
                                    json={"text": words})
            self.assertEqual(res.status, 200, await res.text())
            await self.server._settle_morph(timeout=30)
            out["result"] = await (await client.get(
                f"/api/case/{case_id}/respond")).json()
            out["rules_before_undo"] = self.rules()
            undo = await client.post(f"/api/undo/{out['result']['undo']}")
            out["undo_status"] = undo.status

        self.drive(body)
        return out


class TestRespondEndsAsTheWordsSay(RespondCase):
    def test_that_is_intentional_remember_it_is_wrong_with_the_note(self):
        row = self.check_row()
        note = ("It's off on purpose: BRUH Task Manager needs it for its "
                "process view. Remember that.")
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "wrong", "note": note},
            {"kind": "remember", "text": "remember that"}]}
        self.replies["correct"] = {"scope": "entity_check",
                                   "lifetime": "permanent"}
        out = self.respond_then_undo(f"f:{row['ts']}", note)
        result = out["result"]
        self.assertEqual(result["state"], "done", result)
        self.assertTrue(result["ended"])
        # Ended the way Wrong-with-a-note ends: settled as ignored, the
        # reason kept, and the rule that stops the check raising it.
        self.assertTrue(out["rules_before_undo"])
        self.assertIn("won't", result["say"])
        # The panel's toast got the token — Morph's Undo did not.
        self.assertTrue(result["undo"])
        self.assertEqual(self.server.MORPH_UNDO, {})
        # And the token puts every half back.
        self.assertEqual(out["undo_status"], 200)
        self.assertIsNotNone(findings_store.get(row["ts"]))
        self.assertEqual(self.rules(), [])
        # The interpreter was asked on the panel's own surface.
        self.assertIn("interpret", self.model_jobs())

    def test_the_wrong_is_settled_with_the_note_and_files_no_second_fact(self):
        row = self.check_row()
        note = "It's off on purpose for the Task Manager"
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "wrong", "note": note},
            {"kind": "remember", "text": note}]}
        self.replies["correct"] = {"scope": "entity_check",
                                   "lifetime": "permanent"}
        calls = []
        real = self.server._submit_memory

        async def spy(*a, **k):
            calls.append((a, k))
            return await real(*a, **k)

        self.server._submit_memory = spy
        try:
            self.respond(f"f:{row['ts']}", note)
        finally:
            self.server._submit_memory = real
        self.assertIsNone(findings_store.get(row["ts"]))
        [entry] = findings_store.settled_listing()
        self.assertEqual(entry["kind"], "ignored")
        self.assertIn("Task Manager", entry.get("note", ""))
        self.assertTrue(self.rules())
        # The reason reaches memory as the Wrong's correction; the
        # `remember` beside it is not filed a second time.
        self.assertEqual([k.get("source") for _a, k in calls], ["correction"])

    def test_fix_it_by_x_plans_with_the_change_and_does_not_apply(self):
        row = self.check_row("auto.dead_ref")
        self.replies["interpret"] = {"routes": [
            {"kind": "case_ending", "ending": "consent",
             "change": "turn the old schedule off"}]}
        out = self.respond(f"f:{row['ts']}",
                           "fix it by turning the old schedule off")
        self.assertEqual(out["status"], 200)
        # Planned (the live app may already have run the read-only plan
        # with the stubbed model), never applied: Apply is its own consent.
        self.assertIn(findings_store.get(row["ts"])["status"],
                      ("planning", "planned"))
        job = self.server.JOBS[f"{self.server.PLAN_JOB_PREFIX}{row['ts']}"]
        self.assertEqual(job.get("change"), "turn the old schedule off")
        self.assertNotIn(f"{self.server.FIX_JOB_PREFIX}{row['ts']}",
                         self.server.JOBS)
        self.assertIn("working out the change", out["result"]["say"])
        self.assertFalse(out["result"]["ended"])
        # Both turns are on the row, which is what the card paints.
        turns = findings_store.get(row["ts"])["thread"]
        self.assertEqual([t["who"] for t in turns], ["you", "brain"])

    def test_an_unclear_reply_leaves_the_row_and_asks_back(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [{"kind": "chat"}]}
        self.server.engine.run_analyst = (
            lambda *a, **k: {"ok": True, "error": "", "meta": {},
                             "text": "Do you want brAIn to stop raising "
                                     "this, or to change the setting?"})
        out = self.respond(f"f:{row['ts']}", "hmm the task manager thing")
        row_now = findings_store.get(row["ts"])
        self.assertIsNotNone(row_now)
        self.assertEqual(row_now["status"], row["status"])
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertTrue(out["result"]["say"].endswith("?"))
        self.assertEqual(out["result"]["undo"], "")

    def test_an_interpreter_that_cannot_run_leaves_the_row_with_a_sentence(self):
        self.server.engine.get_auth = lambda: None
        row = self.check_row()
        out = self.respond(f"f:{row['ts']}", "it's the one by the boiler")
        row_now = findings_store.get(row["ts"])
        self.assertIsNotNone(row_now)
        self.assertEqual(row_now["status"], row["status"])
        self.assertEqual(findings_store.settled_listing(), [])
        self.assertEqual(self.rules(), [])
        self.assertIn("could not read that", out["result"]["say"])
        self.assertEqual(self.model_jobs(), [])

    def test_the_case_payload_carries_the_thread_the_card_paints(self):
        row = self.check_row()
        self.replies["interpret"] = {"routes": [{"kind": "chat"}]}
        self.respond(f"f:{row['ts']}", "which one is that?")
        case = self.server.cases.get(f"f:{row['ts']}")
        self.assertEqual([t["who"] for t in case["thread"]],
                         ["you", "brain"])


class TestTheRouteRefuses(RespondCase):
    def test_an_empty_reply_and_a_missing_case(self):
        row = self.check_row()

        async def body(client):
            empty = await client.post(f"/api/case/f:{row['ts']}/respond",
                                      json={"text": "   "})
            self.assertEqual(empty.status, 400)
            gone = await client.post("/api/case/f:1/respond",
                                     json={"text": "hello"})
            self.assertEqual(gone.status, 404)
            none = await client.get(f"/api/case/f:{row['ts']}/respond")
            self.assertEqual((await none.json())["state"], "none")

        self.drive(body)
        self.assertEqual(self.model_jobs(), [])

    def test_a_second_reply_while_the_first_runs_is_refused(self):
        row = self.check_row()
        self.server.RESPOND_RESULTS[f"f:{row['ts']}"] = {
            "state": "running", "at": time.time()}

        async def body(client):
            res = await client.post(f"/api/case/f:{row['ts']}/respond",
                                    json={"text": "yes"})
            self.assertEqual(res.status, 409)

        self.drive(body)


class TestThePanelSurfaceIsMorphsWithoutTheTell(unittest.TestCase):
    def test_the_vocabulary(self):
        self.assertIn("panel", interpret.SURFACES)
        self.assertIn("panel", interpret.PRESSED)
        data = {"routes": [{"kind": "dashboard", "text": "x"},
                           {"kind": "case_ending", "ending": "consent",
                            "change": " do  it "}]}
        [route] = interpret.parse(data, "panel", "yes")
        self.assertEqual((route["ending"], route["change"]),
                         ("consent", "do it"))
        kinds = interpret.schema_for("panel")["properties"]["routes"][
            "items"]["properties"]["kind"]["enum"]
        self.assertNotIn("dashboard", kinds)
        self.assertNotIn("code", kinds)
        self.assertIn("Respond box", interpret.prompt("hi", "panel"))
        self.assertIn("intentional", interpret.SYSTEM)

    def test_the_panel_reply_prompt_is_not_the_dashboard_one(self):
        s = sys.modules.get("server")
        if s is None:
            import server as s
        self.assertIn("brAIn's panel", s.PANEL_REPLY_SYSTEM)
        self.assertNotIn("Morph", s.PANEL_REPLY_SYSTEM)


if __name__ == "__main__":
    unittest.main()
