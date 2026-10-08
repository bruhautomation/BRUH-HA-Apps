#!/usr/bin/env python3
"""The morning brief does not send anybody to sign in over a rate limit.

When the usage endpoint answers 429 (or a credential is between
refreshes, or the account is an API key) the usage figures are missing
for a reason whose remedy is to do nothing — `usage_store.NEEDS_NOTHING`.
The brief read the health verdict, and its model read the same tracker
status through `get_health`, and neither was told that; what went out
was "sign in again" about a sign-in that was working. A real sign-in
problem must still be said.
"""

import sys
import unittest
from pathlib import Path
import unittest.mock as mock

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import brief  # noqa: E402
import health  # noqa: E402
import usage_store  # noqa: E402

NOW = 1_800_000_000.0


def limits_for(tracker: dict) -> dict:
    """What `usage_store.limits_problem` makes of a tracker file."""
    with mock.patch.object(usage_store, "_tracker_file", return_value=tracker):
        return usage_store.limits_problem()


def state(verdict: dict, limits: dict) -> dict:
    return brief.state_from([], verdict, {}, NOW - 86400, now=NOW,
                            usage={"source": "estimate", "limits": limits})


class TestARateLimitIsNotAReason(unittest.TestCase):

    def setUp(self):
        self.limits = limits_for({"error": "http_429",
                                  "detail": "Anthropic rate-limited the "
                                            "usage endpoint itself."})
        self.assertTrue(self.limits["needs_nothing"])

    def test_a_verdict_without_the_flag_is_not_a_reason(self):
        """A verdict read from a cache or an older mirror can carry the
        usage problem without the needs-nothing flag; the brief must not
        count it as worth a message."""
        stale = health.verdict(
            {"usage": {"limits": {"code": "http_429"}}}, {}, now=NOW)
        self.assertEqual(stale["state"], "degraded")
        self.assertEqual(brief.worth_saying(state(stale, self.limits)), [])

    def test_the_fresh_verdict_already_stands_down(self):
        fresh = health.verdict({"usage": {"limits": self.limits}}, {}, now=NOW)
        self.assertEqual(fresh["state"], "ok")
        self.assertEqual(brief.worth_saying(state(fresh, self.limits)), [])

    def test_the_prompt_tells_the_model_it_needs_nothing(self):
        st = state({}, self.limits)
        text = brief.frame(["New since the last brief: [warning] Hall door"], st)
        self.assertIn("needs nothing", text)
        self.assertIn("do not tell anybody to sign in", text)
        self.assertIn("sign in", brief.SYSTEM.lower())

    def test_every_needs_nothing_code_is_quiet(self):
        for code in usage_store.NEEDS_NOTHING:
            with self.subTest(code=code):
                limits = limits_for({"error": code})
                stale = health.verdict(
                    {"usage": {"limits": {"code": code}}}, {}, now=NOW)
                self.assertEqual(brief.worth_saying(state(stale, limits)), [])
                self.assertNotIn("Sign in again",
                                 brief.frame(["x"], state(stale, limits)))


class TestADayOfRateLimitsIsSaidButNeverAsASignIn(unittest.TestCase):
    """Past a day `http_429` stops needing nothing (`usage_store.STUCK_AFTER`)
    and becomes a reason, and the reason it is must still not be "sign in
    again": the account is fine and the endpoint is not answering."""

    def test_it_is_a_reason_and_the_prompt_rules_out_a_sign_in(self):
        import time as _time
        from datetime import datetime, timezone
        since = datetime.fromtimestamp(_time.time() - 30 * 3600,
                                       timezone.utc).isoformat()
        limits = limits_for({"error": "http_429", "error_since": since})
        self.assertFalse(limits["needs_nothing"])
        verdict = health.verdict({"usage": {"limits": limits}}, {}, now=NOW)
        self.assertEqual(verdict["state"], "degraded")
        st = state(verdict, limits)
        self.assertNotEqual(brief.worth_saying(st), [])
        text = brief.frame(["x"], st)
        self.assertIn("over a day", text)
        self.assertIn("signing in again will not help", text)
        self.assertNotIn("Sign in again", text)


class TestARealSignInProblemIsStillSaid(unittest.TestCase):

    def test_a_refused_sign_in_is_a_reason(self):
        verdict = health.verdict({"auth": {"state": "failed"}}, {}, now=NOW)
        reasons = brief.worth_saying(state(verdict, {}))
        self.assertTrue(reasons)
        self.assertIn("not signed in", reasons[0])

    def test_a_usage_scope_problem_keeps_its_remedy(self):
        limits = limits_for({"error": "oauth_token_lacks_usage_scope"})
        self.assertFalse(limits["needs_nothing"])
        verdict = health.verdict({"usage": {"limits": limits}}, {}, now=NOW)
        st = state(verdict, limits)
        self.assertTrue(brief.worth_saying(st))
        self.assertIn("Sign in again", brief.frame(["x"], st))


if __name__ == "__main__":
    unittest.main()
