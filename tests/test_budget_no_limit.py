"""The usage budget's "No limit" choice: run until Anthropic rate-limits.

The ⚙ slider caps automatic insights at 5-100% of each 5-hour session.
When Anthropic's usage endpoint is unavailable the figure is brAIn's own
estimate, and a cap against an estimate can stop automatic work while the
account still has headroom. "No limit" is a separate boolean
(`budget_no_limit`) rather than a new percentage, so no value an older
install ever stored can mean it by accident, and `budget_percent` keeps
meaning exactly what it did.

While it is on, `budget_state` never blocks on brAIn's estimate; the only
things that stop automatic work are the account's own figure saying the
session is spent and the rate-limit pause (`RATE_LIMIT_STATE`), which the
Resident's gate reads in this mode and says when it lifts.
"""
from __future__ import annotations

import datetime
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

PANEL_DIR = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain_status  # noqa: E402
import settings_store  # noqa: E402
import usage_store  # noqa: E402


class Stores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = self.tmp.name
        old = (settings_store.SETTINGS_FILE, usage_store.USAGE_FILE,
               usage_store.LIMITS_FILE)

        def restore():
            (settings_store.SETTINGS_FILE, usage_store.USAGE_FILE,
             usage_store.LIMITS_FILE) = old
        self.addCleanup(restore)
        settings_store.SETTINGS_FILE = os.path.join(base, "settings.json")
        usage_store.USAGE_FILE = os.path.join(base, "usage.json")
        usage_store.LIMITS_FILE = os.path.join(base, "usage_limits.json")

    def spend_the_estimate(self, now: float) -> None:
        # Far past a Pro session's estimated allowance: the estimate reads 100%.
        usage_store.record_run(usage_store.PLAN_SESSION_TOKENS["pro"] * 2,
                               "energy", now=now - 60)

    def account(self, utilization: float) -> datetime.datetime:
        now_dt = datetime.datetime.now(datetime.timezone.utc)
        resets = now_dt + datetime.timedelta(hours=2)
        Path(usage_store.LIMITS_FILE).write_text(json.dumps(
            {"updated_at": now_dt.isoformat(),
             "five_hour": {"utilization": utilization,
                           "resets_at": resets.isoformat()}}))
        return resets


class TestTheSettingIsItsOwnKey(Stores):
    def test_off_by_default(self):
        self.assertIs(settings_store.load()["budget_no_limit"], False)
        self.assertEqual(settings_store.load()["budget_percent"], 25)

    def test_it_saves_as_a_boolean_and_nothing_else(self):
        self.assertIs(settings_store.save({"budget_no_limit": True})["budget_no_limit"], True)
        self.assertIs(settings_store.load()["budget_no_limit"], True)
        for bad in (1, "yes", None, 101):
            with self.assertRaises(ValueError):
                settings_store.save({"budget_no_limit": bad})

    def test_no_percentage_can_mean_it(self):
        """The slider's range is unchanged: 101 or 0 is refused, never read
        as "no limit"."""
        for bad in (0, 4, 101, 105, 1000):
            with self.assertRaises(ValueError):
                settings_store.save({"budget_percent": bad})
        self.assertIs(settings_store.load()["budget_no_limit"], False)

    def test_a_garbage_stored_value_reads_as_off(self):
        Path(settings_store.SETTINGS_FILE).write_text(json.dumps(
            {"budget_no_limit": "true", "budget_percent": 40}))
        st = settings_store.load()
        self.assertIs(st["budget_no_limit"], False)
        self.assertEqual(st["budget_percent"], 40)

    def test_choosing_a_percentage_keeps_the_old_one_for_later(self):
        settings_store.save({"budget_percent": 60})
        settings_store.save({"budget_no_limit": True})
        st = settings_store.load()
        self.assertEqual(st["budget_percent"], 60)
        self.assertTrue(st["budget_no_limit"])


class TestBudgetState(Stores):
    def test_a_percentage_still_stops_at_the_estimate(self):
        now = time.time()
        self.spend_the_estimate(now)
        st = usage_store.budget_state({"plan": "pro", "budget_percent": 25}, now=now)
        self.assertEqual(st["source"], "estimate")
        self.assertTrue(st["blocked"])
        self.assertIs(st["no_limit"], False)

    def test_one_hundred_percent_stops_at_an_estimated_hundred(self):
        now = time.time()
        self.spend_the_estimate(now)
        st = usage_store.budget_state({"plan": "pro", "budget_percent": 100}, now=now)
        self.assertTrue(st["blocked"])

    def test_no_limit_runs_past_an_estimated_hundred(self):
        now = time.time()
        self.spend_the_estimate(now)
        st = usage_store.budget_state(
            {"plan": "pro", "budget_percent": 25, "budget_no_limit": True}, now=now)
        self.assertEqual(st["used_percent"], 100.0)
        self.assertFalse(st["blocked"])
        self.assertIs(st["no_limit"], True)

    def test_no_limit_still_stops_when_the_account_says_the_session_is_spent(self):
        resets = self.account(100)
        st = usage_store.budget_state(
            {"plan": "pro", "budget_percent": 25, "budget_no_limit": True})
        self.assertEqual(st["source"], "account")
        self.assertTrue(st["blocked"])
        self.assertEqual(st["resets_at"], int(resets.timestamp()))

    def test_no_limit_runs_on_while_the_account_has_headroom(self):
        self.account(97)
        st = usage_store.budget_state(
            {"plan": "pro", "budget_percent": 25, "budget_no_limit": True})
        self.assertFalse(st["blocked"])

    def test_only_a_literal_true_switches_it_on(self):
        now = time.time()
        self.spend_the_estimate(now)
        st = usage_store.budget_state(
            {"plan": "pro", "budget_percent": 25, "budget_no_limit": "true"}, now=now)
        self.assertTrue(st["blocked"])
        self.assertIs(st["no_limit"], False)


class TestTheStatusLine(unittest.TestCase):
    def test_a_spent_account_in_no_limit_mode_says_claude_limit(self):
        now = time.time()
        out = brain_status.derive(
            signed_in=True, now=now,
            budget={"blocked": True, "no_limit": True, "resets_at": now + 3600})
        self.assertEqual(out["state"], "paused")
        self.assertIn("Claude limit reached", out["sentence"])
        self.assertIn("back at", out["sentence"])
        self.assertNotIn("budget", out["sentence"])

    def test_a_percentage_still_says_budget(self):
        now = time.time()
        out = brain_status.derive(
            signed_in=True, now=now,
            budget={"blocked": True, "resets_at": now + 3600})
        self.assertIn("usage budget reached", out["sentence"])


class TestTheResidentGate(Stores):
    """In no-limit mode the rate-limit pause is what governs the looks too."""

    def setUp(self):
        super().setUp()
        os.environ["BRAIN_INSIGHTS_DIR"] = os.path.join(self.tmp.name, "insights")
        os.environ["BRAIN_INSIGHTS_SECRETS"] = os.path.join(self.tmp.name, "secrets")
        os.environ["BRAIN_INSIGHTS_SETTINGS_FILE"] = settings_store.SETTINGS_FILE
        os.environ["BRAIN_INSIGHTS_USAGE_FILE"] = usage_store.USAGE_FILE
        import server
        self.server = importlib.reload(server)
        patcher = mock.patch.object(self.server.engine, "get_auth",
                                    return_value={"type": "oauth_token", "value": "x"})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.server.RATE_LIMIT_STATE.update,
                        dict(self.server.RATE_LIMIT_STATE))

    def gate(self, **settings):
        base = {"auto_enabled": True, "plan": "pro", "budget_percent": 25}
        return self.server._resident_gate({**base, **settings})

    def test_no_limit_looks_on_past_an_estimated_hundred(self):
        self.spend_the_estimate(time.time())
        self.assertEqual(self.gate(budget_no_limit=True), "")
        self.assertIn("budget", self.gate())

    def test_no_limit_holds_while_anthropic_has_rate_limited(self):
        until = time.time() + 1800
        self.server.RATE_LIMIT_STATE.update(until=until, streak=1, tier="sonnet")
        reason = self.gate(budget_no_limit=True)
        self.assertIn("rate-limit", reason)
        self.assertIn(time.strftime("%H:%M", time.localtime(until)), reason)

    def test_a_percentage_install_is_gated_exactly_as_before(self):
        self.server.RATE_LIMIT_STATE.update(until=time.time() + 1800, streak=1)
        self.assertEqual(self.gate(), "")

    def test_the_usage_the_panel_shows_says_when_the_pause_lifts(self):
        until = time.time() + 1800
        self.server.RATE_LIMIT_STATE.update(until=until, streak=1)
        usage = self.server._usage_for_panel({"plan": "pro", "budget_percent": 25,
                                              "budget_no_limit": True})
        self.assertEqual(usage["rate_limited_until"], int(until))
        self.server.RATE_LIMIT_STATE.update(until=0.0, streak=0)
        usage = self.server._usage_for_panel({"plan": "pro", "budget_percent": 25})
        self.assertIsNone(usage["rate_limited_until"])


try:
    from test_task_failures import ListenerCase
except Exception:  # noqa: BLE001 — the listener half needs bash
    ListenerCase = None

if ListenerCase is not None:
    class TestTheAutomationListener(ListenerCase):
        """A scheduled insight job reads the same budget."""

        def spend(self):
            now = time.time()
            (self.tmp / "usage.json").write_text(json.dumps(
                {"runs": [{"ts": now - 60, "tokens": 10_000_000, "id": "energy"}]}))

        def test_a_percentage_skips_at_the_estimate(self):
            self.spend()
            result = self.run_task({"scheduled": True},
                                   settings={"budget_percent": 25})
            self.assertEqual(result["error"], "budget")
            self.assertFalse(self.claude_ran())

        def test_no_limit_runs_past_the_estimate(self):
            self.spend()
            result = self.run_task({"scheduled": True},
                                   settings={"budget_percent": 25,
                                             "budget_no_limit": True})
            self.assertEqual(result["status"], "completed")
            self.assertTrue(self.claude_ran())


if __name__ == "__main__":
    unittest.main()
