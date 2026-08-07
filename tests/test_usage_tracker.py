"""The usage-limits tracker: where it looks for a credential, and what it
says when it cannot use one.

The bug these exist for: the tracker read only Claude Code's own
`.credentials.json`, so signing in through the panel — the add-on's primary
sign-in surface — left every usage sensor unavailable reporting
`no_oauth_token`, while the terminal, the listeners and the fixer were all
happily authenticated off the same login. "Not authenticated" was the one
thing it wasn't.
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
TRACKER = BASE_DIR / "brain" / "scripts" / "usage-limits-tracker.py"


def load_tracker(env):
    """Import the tracker with a given environment, since its paths are
    module-level constants resolved at import time."""
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
    try:
        spec = importlib.util.spec_from_file_location("usage_tracker", TRACKER)
        module = importlib.util.module_from_spec(spec)
        sys.modules["usage_tracker"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class TestCredentialDiscovery(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.secrets = os.path.join(self.tmp.name, "secrets")
        self.shared = os.path.join(self.tmp.name, "shared", "claude_auth.json")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(self.secrets)
        os.makedirs(os.path.dirname(self.shared))
        self.mod = load_tracker({
            "BRAIN_HOME": self.home,
            "BRAIN_SECRETS": self.secrets,
            "BRAIN_SHARED_AUTH": self.shared,
            "CLAUDE_CONFIG_DIR": None,
        })

    def _write(self, path, payload):
        with open(path, "w") as fh:
            json.dump(payload, fh)

    def test_the_cli_credential_is_preferred(self):
        self._write(os.path.join(self.home, ".claude", ".credentials.json"),
                    {"claudeAiOauth": {"accessToken": "sk-ant-oat01-cli"}})
        self._write(os.path.join(self.secrets, "claude_auth.json"),
                    {"type": "oauth_token", "value": "sk-ant-oat01-panel"})
        state = {}
        self.assertEqual(self.mod.find_oauth_token(state), "sk-ant-oat01-cli")
        self.assertEqual(state["auth"], "claude cli")

    def test_a_panel_login_is_found(self):
        """The case that was broken: no CLI credential file at all, because
        the person signed in through the panel."""
        self._write(os.path.join(self.secrets, "claude_auth.json"),
                    {"type": "oauth_token", "value": "sk-ant-oat01-panel"})
        state = {}
        self.assertEqual(self.mod.find_oauth_token(state), "sk-ant-oat01-panel")
        self.assertEqual(state["auth"], "panel")

    def test_a_shared_ha_login_is_found(self):
        self._write(self.shared,
                    {"type": "oauth_token", "value": "sk-ant-oat01-shared"})
        state = {}
        self.assertEqual(self.mod.find_oauth_token(state), "sk-ant-oat01-shared")
        self.assertEqual(state["auth"], "ha login")

    def test_the_token_is_returned_alone(self):
        """A label riding home beside a credential is a label nothing can
        tell apart from the credential — which is what CodeQL said about the
        first version of this, and it was right to."""
        self._write(self.shared,
                    {"type": "oauth_token", "value": "sk-ant-oat01-shared"})
        self.assertIsInstance(self.mod.find_oauth_token(), str)

    def test_an_api_key_says_so_rather_than_not_authenticated(self):
        """An API key bills per token and has no subscription window, so
        there is no utilization to report and never will be. Saying
        "no_oauth_token" sends people to redo a sign-in that worked."""
        self._write(os.path.join(self.secrets, "claude_auth.json"),
                    {"type": "api_key", "value": "sk-ant-api03-xyz"})
        self.assertIsNone(self.mod.find_oauth_token())
        self.assertEqual(self.mod.credential_problem(),
                         "api_key_has_no_usage_limits")

    def test_nothing_at_all_is_no_oauth_token(self):
        self.assertIsNone(self.mod.find_oauth_token())
        self.assertEqual(self.mod.credential_problem(), "no_oauth_token")

    def test_the_problem_is_a_status_not_a_credential(self):
        """credential_problem must never be able to leak a value: it reads
        `type` and nothing else, whatever the store holds."""
        self._write(os.path.join(self.secrets, "claude_auth.json"),
                    {"type": "api_key", "value": "sk-ant-api03-secret"})
        self.assertNotIn("secret", self.mod.credential_problem())
        self.assertIn(self.mod.credential_problem(),
                      ("no_oauth_token", "api_key_has_no_usage_limits"))

    def test_malformed_stores_are_skipped_not_fatal(self):
        with open(os.path.join(self.secrets, "claude_auth.json"), "w") as fh:
            fh.write("{not json")
        self._write(self.shared,
                    {"type": "oauth_token", "value": "sk-ant-oat01-shared"})
        state = {}
        self.assertEqual(self.mod.find_oauth_token(state), "sk-ant-oat01-shared")
        self.assertEqual(state["auth"], "ha login")

    def test_claude_config_dir_is_honoured(self):
        cfg = os.path.join(self.tmp.name, "cfg")
        os.makedirs(cfg)
        mod = load_tracker({
            "BRAIN_HOME": self.home,
            "BRAIN_SECRETS": self.secrets,
            "BRAIN_SHARED_AUTH": self.shared,
            "CLAUDE_CONFIG_DIR": cfg,
        })
        self._write(os.path.join(cfg, ".credentials.json"),
                    {"claudeAiOauth": {"accessToken": "sk-ant-oat01-cfg"}})
        self.assertEqual(mod.find_oauth_token(), "sk-ant-oat01-cfg")


class TestStaleCredentials(unittest.TestCase):
    """A dead credential must not speak for the live one behind it.

    The failure this exists for: the CLI's own .credentials.json holds an
    expired token, so the terminal defers to it and prompts for a login
    while a working panel credential sits unread — and run.sh restores that
    file from its backup whenever it goes missing, so it never clears.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.secrets = os.path.join(self.tmp.name, "secrets")
        self.shared = os.path.join(self.tmp.name, "shared", "claude_auth.json")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(self.secrets)
        os.makedirs(os.path.dirname(self.shared))
        self.mod = load_tracker({
            "BRAIN_HOME": self.home,
            "BRAIN_SECRETS": self.secrets,
            "BRAIN_SHARED_AUTH": self.shared,
            "CLAUDE_CONFIG_DIR": None,
        })
        self.cli = os.path.join(self.home, ".claude", ".credentials.json")

    def _write_cli(self, token, expires_in_s=None):
        oauth = {"accessToken": token}
        if expires_in_s is not None:
            oauth["expiresAt"] = int((time.time() + expires_in_s) * 1000)
        with open(self.cli, "w") as fh:
            json.dump({"claudeAiOauth": oauth}, fh)

    def _write_panel(self, token):
        with open(os.path.join(self.secrets, "claude_auth.json"), "w") as fh:
            json.dump({"type": "oauth_token", "value": token}, fh)

    def test_an_expired_cli_credential_is_skipped(self):
        self._write_cli("sk-ant-oat01-dead", expires_in_s=-3600)
        self._write_panel("sk-ant-oat01-panel")
        self.assertEqual(self.mod.find_oauth_token(), "sk-ant-oat01-panel")

    def test_a_live_cli_credential_still_wins(self):
        """A `claude /login` done in the terminal is the most recent thing
        the person did there — it must keep outranking an older paste."""
        self._write_cli("sk-ant-oat01-live", expires_in_s=3600)
        self._write_panel("sk-ant-oat01-panel")
        self.assertEqual(self.mod.find_oauth_token(), "sk-ant-oat01-live")

    def test_no_recorded_expiry_means_live_not_dead(self):
        self._write_cli("sk-ant-oat01-noexp")
        self._write_panel("sk-ant-oat01-panel")
        self.assertEqual(self.mod.find_oauth_token(), "sk-ant-oat01-noexp")

    def test_a_credential_about_to_expire_is_already_gone(self):
        """It must not die between being chosen and being used."""
        self._write_cli("sk-ant-oat01-dying", expires_in_s=5)
        self._write_panel("sk-ant-oat01-panel")
        self.assertEqual(self.mod.find_oauth_token(), "sk-ant-oat01-panel")

    def test_every_credential_is_offered_best_first(self):
        self._write_cli("sk-ant-oat01-live", expires_in_s=3600)
        self._write_panel("sk-ant-oat01-panel")
        with open(self.shared, "w") as fh:
            json.dump({"type": "oauth_token", "value": "sk-ant-oat01-shared"}, fh)
        self.assertEqual(list(self.mod.oauth_tokens()),
                         ["sk-ant-oat01-live", "sk-ant-oat01-panel",
                          "sk-ant-oat01-shared"])

    def test_a_refused_credential_falls_through_to_the_next_store(self):
        """401 ends that credential, not the search — a token the server
        rejects must not speak for a sign-in that would have worked."""
        self._write_cli("sk-ant-oat01-revoked", expires_in_s=3600)
        self._write_panel("sk-ant-oat01-panel")
        tried = []

        def fake_fetch(token):
            tried.append(token)
            if token == "sk-ant-oat01-revoked":
                return None, "http_401"
            return {"five_hour": {"utilization": 7}}, None

        self.mod.fetch_usage_limits = fake_fetch
        data, error = self.mod._fetch_with_any_credential({})
        self.assertEqual(tried,
                         ["sk-ant-oat01-revoked", "sk-ant-oat01-panel"])
        self.assertIsNone(error)
        self.assertEqual(data["five_hour"]["utilization"], 7)

    def test_all_refused_reports_the_refusal(self):
        self._write_cli("sk-ant-oat01-revoked", expires_in_s=3600)
        self._write_panel("sk-ant-oat01-also-revoked")
        self.mod.fetch_usage_limits = lambda token: (None, "http_401")
        data, error = self.mod._fetch_with_any_credential({})
        self.assertIsNone(data)
        self.assertEqual(error, "http_401")

    def test_a_network_error_does_not_burn_the_next_credential(self):
        """Anything other than a 401 is about the request, not the
        credential — retrying it on a second token proves nothing."""
        self._write_cli("sk-ant-oat01-live", expires_in_s=3600)
        self._write_panel("sk-ant-oat01-panel")
        tried = []

        def fake_fetch(token):
            tried.append(token)
            return None, "network_error"

        self.mod.fetch_usage_limits = fake_fetch
        _, error = self.mod._fetch_with_any_credential({})
        self.assertEqual(tried, ["sk-ant-oat01-live"])
        self.assertEqual(error, "network_error")

    def test_no_credentials_at_all_reports_the_problem(self):
        self.mod.fetch_usage_limits = lambda token: (None, "http_401")
        data, error = self.mod._fetch_with_any_credential({})
        self.assertIsNone(data)
        self.assertEqual(error, "no_oauth_token")


class TestAuthEnvScript(unittest.TestCase):
    """brain-auth-env.sh — the half of this that fixes the terminal.

    It is sourced, and its whole output is what it exports. Deferring to a
    dead CLI credential exports nothing, so the CLI tries the dead token and
    prompts for a login while a working one sits unread below.
    """

    SCRIPT = BASE_DIR / "brain" / "scripts" / "brain-auth-env.sh"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.secrets = os.path.join(self.tmp.name, "secrets")
        self.shared = os.path.join(self.tmp.name, "shared", "claude_auth.json")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(self.secrets)
        os.makedirs(os.path.dirname(self.shared))

    def _write_cli(self, token, expires_in_s=None):
        oauth = {"accessToken": token}
        if expires_in_s is not None:
            oauth["expiresAt"] = int((time.time() + expires_in_s) * 1000)
        with open(os.path.join(self.home, ".claude", ".credentials.json"), "w") as fh:
            json.dump({"claudeAiOauth": oauth}, fh)

    def _write_panel(self, token):
        with open(os.path.join(self.secrets, "claude_auth.json"), "w") as fh:
            json.dump({"type": "oauth_token", "value": token}, fh)

    def _exported(self):
        """What a shell that sourced the script ends up holding."""
        env = dict(os.environ)
        env.update({"BRAIN_HOME": self.home, "BRAIN_SECRETS": self.secrets,
                    "BRAIN_SHARED_AUTH": self.shared})
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        env.pop("ANTHROPIC_API_KEY", None)
        out = subprocess.run(
            ["bash", "-c",
             f'. "{self.SCRIPT}"; echo "${{CLAUDE_CODE_OAUTH_TOKEN:-}}"'],
            capture_output=True, text=True, env=env, check=True)
        return out.stdout.strip()

    def test_a_live_cli_credential_is_left_to_authenticate_itself(self):
        self._write_cli("sk-ant-oat01-live", expires_in_s=3600)
        self._write_panel("sk-ant-oat01-panel")
        self.assertEqual(self._exported(), "",
                         "injecting over a live CLI token breaks its refresh")

    def test_an_expired_cli_credential_falls_through_to_the_panel(self):
        """The terminal symptom, exactly: chat works, terminal asks to log
        in, because a dead file outranked a working sign-in."""
        self._write_cli("sk-ant-oat01-dead", expires_in_s=-3600)
        self._write_panel("sk-ant-oat01-panel")
        self.assertEqual(self._exported(), "sk-ant-oat01-panel")

    def test_no_recorded_expiry_is_treated_as_live(self):
        self._write_cli("sk-ant-oat01-noexp")
        self._write_panel("sk-ant-oat01-panel")
        self.assertEqual(self._exported(), "")

    def test_nothing_anywhere_exports_nothing(self):
        """An unset variable is the right state for "not signed in" — an
        empty one makes the CLI fail instead of offering to log in."""
        self.assertEqual(self._exported(), "")


class TestFreshnessGuard(unittest.TestCase):
    """A blip must not blank four working sensors, and a tracker that has
    stopped must not keep reporting last night's numbers as live."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mod = load_tracker({})
        self.mod.USAGE_FILE = os.path.join(self.tmp.name, "usage_limits.json")

    def _write(self, payload):
        with open(self.mod.USAGE_FILE, "w") as fh:
            json.dump(payload, fh)

    def _stamp(self, minutes_ago):
        return (datetime.now(timezone.utc)
                - timedelta(minutes=minutes_ago)).isoformat()

    def test_a_recent_reading_is_fresh(self):
        self._write({"updated_at": self._stamp(5),
                     "five_hour": {"utilization": 12}})
        self.assertTrue(self.mod._last_reading_is_fresh())

    def test_an_old_reading_is_not(self):
        self._write({"updated_at": self._stamp(60 * 5),
                     "five_hour": {"utilization": 12}})
        self.assertFalse(self.mod._last_reading_is_fresh())

    def test_an_error_file_is_not_a_reading(self):
        self._write({"updated_at": self._stamp(1), "error": "no_oauth_token"})
        self.assertFalse(self.mod._last_reading_is_fresh())

    def test_a_missing_or_broken_file_is_not_a_reading(self):
        self.assertFalse(self.mod._last_reading_is_fresh())
        with open(self.mod.USAGE_FILE, "w") as fh:
            fh.write("{nope")
        self.assertFalse(self.mod._last_reading_is_fresh())


class TestOneCredentialOneRequest(unittest.TestCase):
    """A credential reachable by four paths is still one credential.

    This is the regression that took the sensors down. run.sh exports
    CLAUDE_CONFIG_DIR as $BRAIN_HOME/.claude and symlinks
    $BRAIN_HOME/.config/claude onto /data/.config/claude, so all four
    CREDENTIAL_PATHS lead to one file — the first two are literally the same
    string. With a retry-on-401 loop above it that meant one sign-in sent
    the same rejected request four times in a row with no pause, every poll,
    which is what gets a token flagged on an endpoint that answers 429 with
    quota to spare.

    Every other test in this file sets ``CLAUDE_CONFIG_DIR: None``, and that
    variable *being set* is what creates the duplicate — so the suite could
    not see the bug it was covering. This class sets the environment the way
    run.sh actually does.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = os.path.join(self.tmp.name, "home")
        self.secrets = os.path.join(self.tmp.name, "secrets")
        self.shared = os.path.join(self.tmp.name, "shared", "claude_auth.json")
        os.makedirs(os.path.join(self.home, ".claude"))
        os.makedirs(os.path.join(self.home, ".config"))
        os.makedirs(self.secrets)
        os.makedirs(os.path.dirname(self.shared))
        # What run.sh does: CLAUDE_CONFIG_DIR is $BRAIN_HOME/.claude, and
        # $BRAIN_HOME/.config/claude is a symlink to the shared config dir.
        os.symlink(os.path.join(self.home, ".claude"),
                   os.path.join(self.home, ".config", "claude"))
        self.mod = load_tracker({
            "BRAIN_HOME": self.home,
            "BRAIN_SECRETS": self.secrets,
            "BRAIN_SHARED_AUTH": self.shared,
            "CLAUDE_CONFIG_DIR": os.path.join(self.home, ".claude"),
        })
        self.cli = os.path.join(self.home, ".claude", ".credentials.json")

    def _write_cli(self, token):
        with open(self.cli, "w") as fh:
            json.dump({"claudeAiOauth": {"accessToken": token}}, fh)

    def test_the_paths_really_do_collide(self):
        """Guards the premise: if this stops being true the test below is
        passing for the wrong reason."""
        self.assertGreater(len(self.mod.CREDENTIAL_PATHS),
                           len({os.path.realpath(p)
                                for p in self.mod.CREDENTIAL_PATHS}))

    def test_one_sign_in_is_offered_once(self):
        self._write_cli("sk-ant-oat01-cli")
        self.assertEqual(list(self.mod.oauth_tokens()), ["sk-ant-oat01-cli"])

    def test_a_refused_credential_is_not_retried_against_itself(self):
        """The burst: four identical 401s per poll, no delay between them."""
        self._write_cli("sk-ant-oat01-revoked")
        tried = []

        def fake_fetch(token):
            tried.append(token)
            return None, "http_401"

        self.mod.fetch_usage_limits = fake_fetch
        _, error = self.mod._fetch_with_any_credential({})
        self.assertEqual(tried, ["sk-ant-oat01-revoked"])
        self.assertEqual(error, "http_401")

    def test_the_same_token_in_two_stores_is_one_credential(self):
        """The three stores can hold one token that arrived by three routes,
        so collapsing paths is not enough on its own."""
        self._write_cli("sk-ant-oat01-same")
        with open(os.path.join(self.secrets, "claude_auth.json"), "w") as fh:
            json.dump({"type": "oauth_token", "value": "sk-ant-oat01-same"}, fh)
        with open(self.shared, "w") as fh:
            json.dump({"type": "oauth_token", "value": "sk-ant-oat01-same"}, fh)
        self.assertEqual(list(self.mod.oauth_tokens()), ["sk-ant-oat01-same"])

    def test_distinct_credentials_are_all_still_offered(self):
        """Dedup must not cost the fall-through the retry loop exists for."""
        self._write_cli("sk-ant-oat01-cli")
        with open(os.path.join(self.secrets, "claude_auth.json"), "w") as fh:
            json.dump({"type": "oauth_token", "value": "sk-ant-oat01-panel"}, fh)
        with open(self.shared, "w") as fh:
            json.dump({"type": "oauth_token", "value": "sk-ant-oat01-shared"}, fh)
        self.assertEqual(list(self.mod.oauth_tokens()),
                         ["sk-ant-oat01-cli", "sk-ant-oat01-panel",
                          "sk-ant-oat01-shared"])


class TestRateLimitBackoff(unittest.TestCase):
    """Retrying a 429 is what sustains it, so a 429 buys real quiet."""

    def setUp(self):
        self.mod = load_tracker({})

    def test_each_strike_lengthens_the_wait(self):
        waits = [self.mod._rate_limit_delay(n, None) for n in (1, 2, 3)]
        self.assertEqual(waits, sorted(waits))
        self.assertEqual(len(set(waits)), 3)

    def test_the_wait_stops_growing_at_the_cap(self):
        capped = self.mod._rate_limit_delay(len(self.mod.RATE_LIMIT_BACKOFF_S),
                                            None)
        self.assertEqual(self.mod._rate_limit_delay(99, None), capped)

    def test_a_polling_interval_is_never_the_answer_to_a_429(self):
        self.assertGreater(self.mod._rate_limit_delay(1, None),
                           self.mod.POLL_INTERVAL)

    def test_every_backoff_actually_backs_off(self):
        """The invariant that broke when the poll interval was lengthened
        and these were left alone: a step shorter than POLL_INTERVAL means
        a failing tracker asks *more* often than a working one, which is
        the opposite of a backoff and exactly what a daily cap punishes."""
        for step in self.mod.RATE_LIMIT_BACKOFF_S:
            self.assertGreater(step, self.mod.POLL_INTERVAL)
        self.assertGreater(self.mod.FAILURE_BACKOFF_S, self.mod.POLL_INTERVAL)

    def test_the_daily_request_budget_stays_small(self):
        """The endpoint meters per day, so the number that matters is
        requests per day, not the interval it is spelled with. Nine hours
        of working sensors cost ~270 requests at the old two-minute poll;
        whatever replaces this must stay far under that."""
        per_day = 86400 / self.mod.POLL_INTERVAL
        self.assertLessEqual(per_day, 60)

    def test_retry_after_zero_does_not_mean_retry_now(self):
        """The endpoint sends `Retry-After: 0` while still refusing
        (anthropics/claude-code#30930). Obeying it is how a tracker retries
        straight back into the limit it was just told about."""
        self.assertEqual(self.mod._rate_limit_delay(1, 0),
                         self.mod._rate_limit_delay(1, None))

    def test_the_server_may_lengthen_the_wait(self):
        floor = self.mod._rate_limit_delay(1, None)
        self.assertEqual(self.mod._rate_limit_delay(1, floor + 600),
                         floor + 600)

    def test_an_absurd_retry_after_is_capped(self):
        self.assertEqual(self.mod._rate_limit_delay(1, 10 ** 9),
                         self.mod.RETRY_AFTER_MAX_S)

    def test_retry_after_reads_seconds_and_dates(self):
        self.assertEqual(self.mod._parse_retry_after({"Retry-After": "120"}), 120)
        self.assertIsNone(self.mod._parse_retry_after({}))
        self.assertIsNone(self.mod._parse_retry_after(None))
        self.assertIsNone(self.mod._parse_retry_after({"Retry-After": "soon"}))
        when = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=10))
        seconds = self.mod._parse_retry_after({"Retry-After": when})
        self.assertIsNotNone(seconds)
        self.assertGreater(seconds, 500)

    def test_a_rate_limit_does_not_blank_a_working_reading(self):
        """A 429 says nothing about the sign-in, so it must not overwrite
        good numbers the way a settled auth fact does."""
        self.assertNotIn("http_429", self.mod.AUTH_PROBLEMS)

    def test_the_status_arrives_with_an_explanation(self):
        detail = self.mod.ERROR_DETAIL.get("http_429", "")
        self.assertIn("not your", detail.lower())


if __name__ == "__main__":
    unittest.main()
