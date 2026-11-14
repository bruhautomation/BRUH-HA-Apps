#!/usr/bin/env python3
"""BRUH Browser never buys without an approval it can check.

Three gates, each driven for real. The PANEL refuses `purchase: true` over
HTTP unless it carries a finished, recent, unused cart errand of its own and
the total that cart reported (`tasks.check_approval`, reached through the
real routes with the real token check), and only then stands the guard
down. The HOOK (`purchase_hook.py`) is run as Claude Code runs it — a
process, the payload on stdin — and refuses an order-placing call for an
errand without approval, including a click on an element a page-read
labelled "Place order", and lets it through for an approved one. brAIn's
ACTION GATE asks a person about every `browser_purchase`, with YOLO on,
and refuses it where nobody can be asked. The panel's own Buy this is the
same approval check, pressed only from the sidebar, and a declined cart, or
one built in another computer's Chrome, is never bought.
"""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

BASE = Path(__file__).resolve().parent.parent
PANEL = BASE / "bruh-browser" / "panel"


def _load_panel():
    """The panel's modules, with its folder on the path only while they load:
    `server` is also brAIn's module name, and panel_case imports it by name."""
    sys.path.insert(0, str(PANEL))
    try:
        import tasks as errands_module
        spec = importlib.util.spec_from_file_location("bruh_browser_server",
                                                      PANEL / "server.py")
        server_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(server_module)
    finally:
        sys.path.remove(str(PANEL))
    return errands_module, server_module


tasks, server = _load_panel()

HOOK = PANEL / "purchase_hook.py"
GATE = BASE / "brain" / "scripts" / "brain-action-gate.py"
CART = {"store": "Shop", "items": [{"name": "Oat milk", "quantity": 2, "price": 1.5}],
        "fees": [], "total": 3.0, "currency": "GBP"}


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


def errands_with_a_cart(tmp: str, clock: Clock, cart=CART) -> tuple[tasks.Errands, str]:
    seen = []

    def run(task, progress, stop):
        seen.append(task)
        return {"state": "done", "answer": "cart ready", "cart": cart}

    errs = tasks.Errands(Path(tmp) / "tasks.json", run, lambda: {"tolerance_percent": 0},
                         now=clock)
    errs.seen = seen
    task, why = errs.create("buy oat milk")
    assert task, why
    errs.run_one()
    return errs, task["id"]


class TestThePanelRefusesAPurchaseWithoutAnApproval(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.errs, self.cart_id = errands_with_a_cart(self.tmp.name, self.clock)

    def refused(self, approval):
        task, why = self.errs.create("", purchase=True, approval=approval)
        self.assertIsNone(task)
        self.assertTrue(why)
        return why

    def test_a_cart_errand_runs_with_the_guard_up(self):
        cart_task = self.errs.seen[0]
        self.assertFalse(cart_task["purchase_approved"])
        self.assertIn("Purchase approved: no", cart_task["message"])

    def test_no_approval_a_stranger_a_wrong_total_or_a_stale_cart_is_refused(self):
        self.refused(None)
        self.refused({"cart_task": "feedfeedfeed", "total": 3.0})
        self.assertIn("not the cart's total", self.refused({"cart_task": self.cart_id, "total": 2.0}))
        self.clock.t += tasks.APPROVAL_WINDOW_S + 1
        self.assertIn("minutes ago", self.refused({"cart_task": self.cart_id, "total": 3.0}))

    def test_a_purchase_cannot_be_the_approval_and_a_cart_buys_once(self):
        task, why = self.errs.create("ignored words", purchase=True,
                                     approval={"cart_task": self.cart_id, "total": 3.0})
        self.assertTrue(task, why)
        self.assertTrue(task["purchase_approved"])
        message = self.errs.tasks[task["id"]]["message"]
        self.assertIn("Purchase approved: YES", message)
        self.assertNotIn("ignored words", message)
        self.assertIn("already approved", self.refused({"cart_task": self.cart_id, "total": 3.0}))
        self.errs.run_one()
        self.refused({"cart_task": task["id"], "total": 3.0})

    def test_an_unfinished_cart_or_one_without_a_total_is_refused(self):
        errs, cart_id = errands_with_a_cart(self.tmp.name + "/b", self.clock,
                                            cart={**CART, "total": None})
        task, why = errs.create("", purchase=True, approval={"cart_task": cart_id, "total": 3.0})
        self.assertIsNone(task)
        self.assertIn("nothing to approve", why)

    def test_over_http_the_token_and_the_approval_are_both_asked(self):
        from aiohttp.test_utils import TestClient, TestServer

        token_file = Path(self.tmp.name) / "api_token"
        token_file.write_text("t" * 40)

        async def drive():
            app = server.build_app(chrome=object(), errs=self.errs, ticker=False)
            async with TestClient(TestServer(app)) as client:
                plain = await client.post("/api/tasks", json={"purchase": True})
                good = {"Authorization": "Bearer " + "t" * 40}
                bare = await client.post("/api/tasks", json={"purchase": True}, headers=good)
                wrong = await client.post("/api/tasks", headers=good, json={
                    "purchase": True, "approval": {"cart_task": self.cart_id, "total": 9}})
                right = await client.post("/api/tasks", headers=good, json={
                    "purchase": True, "approval": {"cart_task": self.cart_id, "total": 3.0}})
                return (plain.status, bare.status, (await bare.json())["error"],
                        wrong.status, right.status, (await right.json())["task"])

        with patch.object(server, "INGRESS_PEERS", frozenset()), \
                patch.object(server, "TOKEN_FILE", token_file):
            server._TOKEN.update(mtime=None, value=None)
            plain, bare, why, wrong, right, task = asyncio.run(drive())
        self.assertEqual(plain, 403)
        self.assertEqual(bare, 409)
        self.assertIn("approval", why)
        self.assertEqual(wrong, 409)
        self.assertEqual(right, 201)
        self.assertTrue(task["purchase_approved"])


class TestBuyThisOnThePanelIsTheSameApproval(unittest.TestCase):
    """The page's Buy this goes through `check_approval` like brAIn's
    purchase, only a person on the page can press it (never a token caller),
    and a cart the household declined, or one built in another computer's
    Chrome, is never bought."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.clock = Clock()
        self.errs, self.cart_id = errands_with_a_cart(self.tmp.name, self.clock)
        self.token_file = Path(self.tmp.name) / "api_token"
        self.token_file.write_text("t" * 40)

    def drive(self, calls, ingress: bool):
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            app = server.build_app(chrome=object(), errs=self.errs, ticker=False)
            out = []
            async with TestClient(TestServer(app)) as client:
                for path, body in calls:
                    headers = {} if ingress else {"Authorization": "Bearer " + "t" * 40}
                    res = await client.post(path, json=body, headers=headers)
                    out.append((res.status, await res.json()))
            return out

        peers = frozenset({"127.0.0.1", "::1"}) if ingress else frozenset()
        with patch.object(server, "INGRESS_PEERS", peers), \
                patch.object(server, "TOKEN_FILE", self.token_file):
            server._TOKEN.update(mtime=None, value=None)
            return asyncio.run(go())

    def test_a_token_caller_cannot_buy_decline_or_say_it_is_done(self):
        base = f"/api/tasks/{self.cart_id}"
        answers = self.drive([(base + "/buy", {"total": 3.0}), (base + "/decline", {}),
                              (base + "/continue", {}),
                              (base + "/answer", {"carry_on": True}),
                              ("/api/browsers/own", {"browser": "x"})], ingress=False)
        self.assertEqual([status for status, _ in answers], [403] * 5)
        self.assertFalse(any(t.get("purchase") for t in self.errs.tasks.values()))
        self.assertFalse(self.errs.tasks[self.cart_id].get("declined"))

    def test_buy_this_needs_the_cart_total_and_buys_once(self):
        base = f"/api/tasks/{self.cart_id}/buy"
        (wrong, why), (bare, _), (right, made), (again, why2) = self.drive(
            [(base, {"total": 2.0}), (base, {}), (base, {"total": 3.0}),
             (base, {"total": 3.0})], ingress=True)
        self.assertEqual((wrong, bare, right, again), (409, 409, 201, 409))
        self.assertIn("not the cart's total", why["error"])
        self.assertTrue(made["task"]["purchase_approved"])
        self.assertEqual(made["task"]["source"], "panel")
        self.assertIn("already approved", why2["error"])

    def test_buy_this_is_refused_on_a_stale_cart(self):
        self.clock.t += tasks.APPROVAL_WINDOW_S + 1
        (status, why), = self.drive([(f"/api/tasks/{self.cart_id}/buy", {"total": 3.0})],
                                    ingress=True)
        self.assertEqual(status, 409)
        self.assertIn("minutes ago", why["error"])

    def test_a_declined_cart_is_never_bought_from_the_page_or_by_brain(self):
        base = f"/api/tasks/{self.cart_id}"
        (declined, _), (buy, why) = self.drive(
            [(base + "/decline", {}), (base + "/buy", {"total": 3.0})], ingress=True)
        self.assertEqual((declined, buy), (200, 409))
        self.assertIn("declined", why["error"])
        (status, _), = self.drive([("/api/tasks", {
            "purchase": True, "approval": {"cart_task": self.cart_id, "total": 3.0}})],
            ingress=False)
        self.assertEqual(status, 409)
        self.assertFalse(any(t.get("purchase") for t in self.errs.tasks.values()))

    def test_a_cart_bought_cannot_then_be_declined(self):
        base = f"/api/tasks/{self.cart_id}"
        (bought, _), (declined, _) = self.drive(
            [(base + "/buy", {"total": 3.0}), (base + "/decline", {})], ingress=True)
        self.assertEqual((bought, declined), (201, 409))

    def test_a_cart_from_another_computers_chrome_is_never_bought(self):
        self.errs.tasks[self.cart_id]["browser_own"] = False
        task, why = self.errs.create("", purchase=True,
                                     approval={"cart_task": self.cart_id, "total": 3.0})
        self.assertIsNone(task)
        self.assertIn("another computer", why)


def run_hook(mode: str, payload, approved: bool, state: Path) -> dict | None:
    env = {**os.environ, "BROWSER_PURCHASE_APPROVED": "1" if approved else "0",
           "BROWSER_TASK_STATE": str(state)}
    text = payload if isinstance(payload, str) else json.dumps(payload)
    done = subprocess.run([sys.executable, str(HOOK), mode], input=text, env=env,
                          capture_output=True, text=True, timeout=20)
    assert done.returncode == 0, done.stderr
    out = done.stdout.strip()
    return json.loads(out)["hookSpecificOutput"] if out else None


class TestTheHookStopsAnOrderForAnUnapprovedErrand(unittest.TestCase):
    P = "mcp__claude-in-chrome__"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / "task.json"

    def call(self, tool, tool_input, approved=False):
        return run_hook("pre", {"tool_name": self.P + tool, "tool_input": tool_input},
                        approved, self.state)

    def test_an_order_button_is_refused_and_building_a_cart_is_not(self):
        for tool, args in (("find", {"query": "Place your order button"}),
                           ("computer", {"action": "type", "text": "BUY NOW"}),
                           ("browser_batch", {"actions": [{"find": "pay £42.10"}]})):
            answer = self.call(tool, args)
            self.assertEqual((answer or {}).get("permissionDecision"), "deny", (tool, args))
            self.assertIn("spending guard", answer["permissionDecisionReason"])
        for tool, args in (("navigate", {"url": "https://shop.example/checkout"}),
                           ("find", {"query": "oat milk 1L"}),
                           ("computer", {"action": "left_click", "coordinate": [10, 20]})):
            self.assertIsNone(self.call(tool, args), (tool, args))

    def test_a_click_on_an_element_the_page_called_place_order_is_refused(self):
        run_hook("post", {"tool_name": self.P + "read_page", "tool_input": {},
                          "tool_response": 'link "Basket" [ref_3]\nbutton "Place order" [ref_42]'},
                 False, self.state)
        answer = self.call("computer", {"action": "left_click", "ref": "ref_42"})
        self.assertEqual((answer or {}).get("permissionDecision"), "deny")
        self.assertIsNone(self.call("computer", {"action": "left_click", "ref": "ref_3"}))

    def test_an_approved_errand_may_place_the_order(self):
        self.assertIsNone(self.call("find", {"query": "Place your order button"}, approved=True))

    def test_a_payload_it_cannot_read_is_refused(self):
        answer = run_hook("pre", "not json", False, self.state)
        self.assertEqual((answer or {}).get("permissionDecision"), "deny")


class TestBrainAlwaysAsksBeforeBuying(unittest.TestCase):
    def run_gate(self, channel: str, yolo: bool) -> dict | None:
        spec = importlib.util.spec_from_file_location("gate_for_browser", GATE)
        hook = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook)
        with tempfile.TemporaryDirectory() as tmp:
            flag = Path(tmp) / "yolo"
            flag.write_text("on" if yolo else "off")
            payload = json.dumps({"tool_name": hook.MCP_PREFIX + "browser_purchase",
                                  "tool_input": {"cart_task": "a", "total": 3.0, "items": []}})
            out = io.StringIO()
            env = {"BRAIN_CHANNEL": channel, "BRAIN_PANEL_URL": "http://127.0.0.1:9"}
            with patch.dict(os.environ, env), patch.object(hook, "YOLO_FILE", str(flag)), \
                    patch("sys.stdout", out):
                hook.main(io.StringIO(payload))
        text = out.getvalue().strip()
        return json.loads(text)["hookSpecificOutput"] if text else None

    def test_the_chat_is_asked_even_with_yolo_on(self):
        for yolo in (False, True):
            self.assertEqual(self.run_gate("chat", yolo)["permissionDecision"], "ask")

    def test_an_unattended_run_is_refused(self):
        self.assertEqual(self.run_gate("automation", True)["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
