#!/usr/bin/env python3
"""Three things a house's own reports called faults that were not.

Each is a refusal doing its job, or nothing having changed, read as a
failure somewhere downstream:

  * The periodic sign-in check met the account's usage limit and recorded
    the sign-in as **failed**, so health said "Claude is not signed in" and
    told somebody to sign in again over a credential the refusal itself
    proved was working.
  * A curiosity run the account refused for a usage limit was counted as
    "an asking that ended without an answer" — a run that spent its money
    and filed nothing, when nothing ran and nothing was spent.
  * An answer from Home Assistant naming a finding already gone (an app
    still holding last week's list) was a fault row, where it is an
    ordinary race that is dropped and logged.

Driven, not grepped: the real `_check_auth_bg`, the real `_ask_why` and the
real `reports.faults`.
"""
from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
PANEL = HERE.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(HERE))

import brain_status  # noqa: E402
import health  # noqa: E402
import reports  # noqa: E402
from test_curiosity_wiring import ServerCase, _async  # noqa: E402

SESSION_LIMIT = "You've hit your session limit · resets 2pm (America/New_York)"
# Wordings the house's reports never carried, so the fix is the class and
# not the one sentence.
OTHER_LIMITS = (
    "Claude AI usage limit reached|1760900000",
    "API Error: 429 {\"type\":\"error\",\"error\":{\"type\":\"rate_limit_error\"}}",
)


def _wheres(rows: list[dict]) -> list[str]:
    return [f"{r['where']}: {r['what']}" for r in rows]


# ---------------------------------------------------------------------------
# 1. A usage limit is not a sign-out
# ---------------------------------------------------------------------------

class TestAUsageLimitIsNotASignOut(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self._old = dict(self.server.AUTH_CHECK)
        self._real = self.server.engine.validate_auth
        self.addCleanup(self._restore)

    def _restore(self):
        self.server.engine.validate_auth = self._real
        self.server.AUTH_CHECK.clear()
        self.server.AUTH_CHECK.update(self._old)

    def check(self, answer: dict, before: str = "ok") -> dict:
        self.server.engine.validate_auth = lambda *a, **k: dict(answer)
        self.server.AUTH_CHECK.update(state=before, error="", checked_at=0,
                                      running=True)
        asyncio.run(self.server._check_auth_bg())
        return dict(self.server.AUTH_CHECK)

    def assert_signed_in(self, verdict: dict):
        self.assertEqual(verdict["state"], "ok", verdict)
        self.assertFalse(verdict["running"])
        self.assertGreater(verdict["checked_at"], 0)
        auth = {"state": verdict["state"], "error": verdict.get("error")}
        said = [p["what"] for p in health.problems(
            {"auth": auth, "daemons": {}}, {})]
        self.assertNotIn("Claude is not signed in", said)
        rows = _wheres(reports.faults({"auth": auth}))
        self.assertFalse([r for r in rows if "sign-in" in r], rows)
        status = brain_status.derive(signed_in=True,
                                     auth_state=verdict["state"])
        self.assertNotEqual(status["state"], "signed_out")

    def test_the_session_limit_the_house_saw_is_not_a_failed_sign_in(self):
        verdict = self.check({"ok": False, "error": SESSION_LIMIT})
        self.assert_signed_in(verdict)
        self.assertIn("session limit", verdict["limited"])

    def test_other_wordings_of_the_limit_are_not_either(self):
        for wording in OTHER_LIMITS:
            with self.subTest(wording=wording):
                self.assert_signed_in(
                    self.check({"ok": False, "error": wording}))

    def test_a_limit_after_a_failed_check_proves_the_credential_works(self):
        verdict = self.check({"ok": False, "error": SESSION_LIMIT},
                             before="failed")
        self.assert_signed_in(verdict)

    def test_a_real_sign_in_failure_still_fails(self):
        """The control: without it the tests above pass on a check that
        can never say failed."""
        verdict = self.check({"ok": False,
                              "error": "Invalid API key · Please run /login"})
        self.assertEqual(verdict["state"], "failed")
        self.assertEqual(verdict["limited"], "")
        said = [p["what"] for p in health.problems(
            {"auth": {"state": "failed", "error": verdict["error"]},
             "daemons": {}}, {})]
        self.assertIn("Claude is not signed in", said)


# ---------------------------------------------------------------------------
# 2. A run the account refused is not an asking that ended without an answer
# ---------------------------------------------------------------------------

class TestARefusedAskingIsNotAFailedOne(ServerCase):

    async def arm(self, answer: dict) -> float:
        base = 1772000000
        rows = [{"ts": base + d * 86400 + 19 * 3600,
                 "entity_id": "switch.sprinklers", "state": "on",
                 "name": "Lawn sprinklers", "cause": "person"}
                for d in range(12)]
        now = base + 13 * 86400
        self.server._record_manual({"actions": {"available": True,
                                                "actions": rows}}, now)
        self.calls = []

        def run_analyst(*a, **k):
            self.calls.append(a)
            return dict(answer)

        self.patch(self.server.engine, "run_analyst", run_analyst)
        self.patch(self.server, "_house_prompt_block",
                   lambda *a, **k: _async(""))
        self.patch(self.server.engine, "get_auth",
                   lambda: {"type": "oauth_token"})
        self.patch(self.server.settings_store, "load",
                   lambda: {"auto_enabled": True})
        self.patch(self.server.usage_store, "budget_state",
                   lambda s: {"blocked": False})
        return now

    def curiosity_rows(self) -> list[str]:
        diag = {"curiosity": {"counts": self.curiosity.counts()}}
        return [r for r in _wheres(reports.faults(diag))
                if r.startswith("Why you did something")]

    async def test_a_rate_limited_run_counts_as_no_failure(self):
        now = await self.arm({"ok": False, "error": SESSION_LIMIT})
        self.assertEqual(await self.server._ask_why(now), 1)
        self.assertEqual(self.curiosity.counts()["failed"], 0)
        self.assertEqual(self.curiosity_rows(), [])
        # Nothing was learned and nothing was spent, so the subject is
        # askable again and today's question is still unspent.
        self.assertEqual(await self.server._ask_why(now), 1)
        self.assertEqual(len(self.calls), 2)

    async def test_a_refused_re_ask_puts_the_earlier_answer_back(self):
        now = await self.arm({"ok": False, "error": SESSION_LIMIT})
        candidate = dict(self.CANDIDATE)
        self.curiosity.mark_asked(candidate, now - 86400 * 9)
        self.curiosity.record_answer(candidate["subject"],
                                     self.answer(), "", "", now - 86400 * 9)
        self.curiosity.mark_asked(candidate, now)
        self.curiosity.record_answer(candidate["subject"], None, "",
                                     SESSION_LIMIT, now)
        entry = self.curiosity.load()["asked"][candidate["subject"]]
        self.assertEqual(entry["status"], "unknown")
        self.assertNotIn("prior", entry)

    async def test_a_genuinely_failed_run_still_counts(self):
        now = await self.arm({"ok": False, "error": "claude exited 1"})
        self.assertEqual(await self.server._ask_why(now), 1)
        self.assertEqual(self.curiosity.counts()["failed"], 1)
        self.assertEqual(len(self.curiosity_rows()), 1)
        self.assertNotIn("prior", next(iter(
            self.curiosity.load()["asked"].values())))

    async def test_a_refusal_stored_before_the_fix_is_not_counted(self):
        """The house's own store already holds one such `failed` entry."""
        now = 1772000000
        self.curiosity.mark_asked(dict(self.CANDIDATE), now)
        payload = self.curiosity.load()
        entry = payload["asked"][self.CANDIDATE["subject"]]
        entry.update(status="failed", error=SESSION_LIMIT)
        entry.pop("prior", None)
        self.curiosity.save(payload)
        self.assertEqual(self.curiosity.counts()["failed"], 0)
        self.assertEqual(self.curiosity_rows(), [])
        self.assertEqual(self.curiosity.spent(self.curiosity.load(),
                                              now)["day"], 0)


# ---------------------------------------------------------------------------
# 3. An answer naming a finding already gone is a race, not a fault
# ---------------------------------------------------------------------------

class TestAnUnappliedAnswerIsNotAFault(unittest.TestCase):

    def test_missed_requests_file_no_fault_row(self):
        diag = {"finding_requests": {"pending": 0, "applied": 2,
                                     "missed": 7}}
        rows = _wheres(reports.faults(diag))
        self.assertFalse([r for r in rows
                          if "Home Assistant" in r and "applied" in r], rows)


# ---------------------------------------------------------------------------
# 4. A clock re-stamped with the same state is not cut history
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
