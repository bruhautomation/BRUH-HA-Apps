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

    def test_the_poll_keeps_a_respectful_floor(self):
        """The poll is minutes, never seconds. With the CLI's own UA the
        endpoint serves minute-scale polling sustainably (it is what the
        statusline ecosystem does), but Claude Code itself only asks on
        demand — a timer is already more than the endpoint was built for,
        so the cadence stays at the gentle end of what is known to work,
        and far above anything that reads as hammering."""
        self.assertGreaterEqual(self.mod.POLL_INTERVAL, 180)

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


class TestUserAgent(unittest.TestCase):
    """The endpoint buckets rate limits by User-Agent, and only the UA the
    usage endpoint's own caller sends gets the bucket that answers a poll.

    Two wrong answers have shipped. `brain/1.0` — straight from the repo's
    naming rule — put every install in the stranger bucket: a 429 wall after
    a few hours that read, from the sensors, as a daily meter nobody could
    name. Its replacement, `claude-cli/<ver> (external, cli)`, is a real
    Claude Code UA and still the wrong one: that is what its *Messages-API*
    client sends, while the helper that fetches utilization sends
    `claude-code/<version>`. Same bucket, same wall, with the fix already
    shipped and the docstring claiming otherwise — which is why the shape
    is asserted against both mistakes below and not just described.
    """

    def _load(self, env=None):
        return load_tracker({"BRAIN_CLI_VERSION": None, **(env or {})})

    def test_a_pinned_version_is_used_verbatim(self):
        mod = self._load({"BRAIN_CLI_VERSION": "9.9.9"})
        self.assertEqual(mod.user_agent(), "claude-code/9.9.9")

    def test_an_unprobeable_cli_falls_back_to_a_real_version(self):
        """The fallback must be a version Claude Code actually shipped —
        a made-up one is a UA nobody else sends, which is the failure mode
        this whole class exists to prevent."""
        mod = self._load()
        mod.CLI_PROBE_COMMANDS = (os.path.join(tempfile.gettempdir(),
                                                "no-such-claude-binary"),)
        self.assertEqual(
            mod.user_agent(),
            f"claude-code/{mod.UA_FALLBACK_CLI_VERSION}",
        )

    def test_the_ua_is_the_one_the_usage_call_itself_sends(self):
        """Read off the CLI bundle at the usage call rather than at the
        first user-agent helper that turns up: the request is built as
        `{"Content-Type", "User-Agent": jH(), ...auth}` and `jH()` returns
        `claude-code/${VERSION}` — no suffix, no parenthetical."""
        mod = self._load({"BRAIN_CLI_VERSION": "1.2.3"})
        ua = mod.user_agent()
        self.assertRegex(ua, r"^claude-code/\d+\.\d+\.\d+$")
        self.assertNotIn("brain", ua.lower())

    def test_it_is_not_the_sdks_messages_api_ua(self):
        """The specific wrong answer that shipped and looked right.

        `claude-cli/<ver> (external, cli)` is what Claude Code's
        Messages-API client sends. It is a genuine Claude Code UA, which is
        exactly why sending it to the usage endpoint was not obviously a
        bug — and it lands in the same stranger bucket `brain/1.0` did."""
        mod = self._load({"BRAIN_CLI_VERSION": "1.2.3"})
        ua = mod.user_agent()
        self.assertNotIn("claude-cli", ua)
        self.assertNotIn("external", ua)

    def test_the_request_actually_carries_it(self):
        """The header on the wire is the fix; a correct constant nothing
        sends is the bug with better paperwork."""
        from unittest import mock

        mod = self._load({"BRAIN_CLI_VERSION": "9.9.9"})

        class _Resp:
            def read(self):
                return b'{"five_hour": {"utilization": 12}}'

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        with mock.patch("urllib.request.urlopen",
                        return_value=_Resp()) as opened:
            data, error = mod.fetch_usage_limits("sk-ant-oat01-token")
        self.assertIsNone(error)
        self.assertEqual(data, {"five_hour": {"utilization": 12}})
        request = opened.call_args[0][0]
        self.assertEqual(request.get_header("User-agent"), "claude-code/9.9.9")
        # The other two headers the CLI's own call sends, so a future edit
        # cannot quietly drop the beta flag the endpoint gates on.
        self.assertEqual(request.get_header("Anthropic-beta"),
                         "oauth-2025-04-20")
        self.assertTrue(
            request.get_header("Authorization").startswith("Bearer "))

    def test_the_probe_is_asked_once_per_process(self):
        """The probe spawns the CLI binary, and once is all the answer can
        change: run.sh updates the CLI before the tracker starts."""
        mod = self._load({"BRAIN_CLI_VERSION": "9.9.9"})
        first = mod.user_agent()
        mod.PINNED_CLI_VERSION = "8.8.8"
        self.assertEqual(mod.user_agent(), first)


class TestFailureRecord(unittest.TestCase):
    """A failed poll that leaves a fresh reading alone must still leave the
    *reason* beside it. The bug these exist for: a 429's backoff waits are
    longer than the two-hour staleness window on purpose, so during a wall
    the reading always ages out and four sensors go unavailable — and the
    why was only written on the poll *after* that, hours later. In between,
    the diagnostic sensor said `stale` and nothing else, which is exactly
    "keeps going unavailable for reasons I do not understand"."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mod = load_tracker({})
        self.mod.USAGE_FILE = os.path.join(self.tmp.name, "usage_limits.json")

    def _write(self, payload):
        with open(self.mod.USAGE_FILE, "w") as fh:
            json.dump(payload, fh)

    def _read(self):
        with open(self.mod.USAGE_FILE) as fh:
            return json.load(fh)

    def _fresh_reading(self):
        return {"updated_at": datetime.now(timezone.utc).isoformat(),
                "five_hour": {"utilization": 12},
                "seven_day": {"utilization": 34}}

    def test_the_reason_rides_beside_untouched_numbers(self):
        reading = self._fresh_reading()
        self._write(reading)
        self.mod._record_failure("http_429", 3600, strikes=1)
        data = self._read()
        self.assertEqual(data["five_hour"], reading["five_hour"])
        self.assertEqual(data["updated_at"], reading["updated_at"])
        self.assertEqual(data["last_error"], "http_429")
        self.assertEqual(data["rate_limit_strikes"], 1)
        self.assertIn("next_attempt_at", data)
        self.assertIn("not your", data["last_error_detail"].lower())

    def test_a_recorded_failure_does_not_blank_the_reading(self):
        """The annotation must not look like an error status to any reader
        of this file — the sensors and the panel both key on `error`."""
        self._write(self._fresh_reading())
        self.mod._record_failure("http_429", 3600, strikes=1)
        self.assertTrue(self.mod._last_reading_is_fresh())
        self.assertNotIn("error", self._read())

    def test_a_successful_poll_clears_the_record(self):
        self._write(self._fresh_reading())
        self.mod._record_failure("http_429", 3600, strikes=2)
        self.mod.write_usage({"five_hour": {"utilization": 15}})
        data = self._read()
        self.assertNotIn("last_error", data)
        self.assertNotIn("next_attempt_at", data)
        self.assertNotIn("rate_limit_strikes", data)

    def test_a_failure_with_no_gloss_carries_no_stale_one(self):
        self._write(self._fresh_reading())
        self.mod._record_failure("http_429", 3600, strikes=1)
        self.mod._record_failure("network_error", 1800)
        data = self._read()
        self.assertEqual(data["last_error"], "network_error")
        self.assertNotIn("last_error_detail", data)
        self.assertNotIn("rate_limit_strikes", data)


class TestBackoffSurvivesRestart(unittest.TestCase):
    """Backoff lived only in memory, so restarting the add-on — the first
    thing anyone does when sensors go unavailable — polled immediately and
    restarted the ladder from its first rung: retrying straight back into
    the daily meter that caused the outage being investigated."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.mod = load_tracker({})
        self.mod.USAGE_FILE = os.path.join(self.tmp.name, "usage_limits.json")

    def _write(self, payload):
        with open(self.mod.USAGE_FILE, "w") as fh:
            json.dump(payload, fh)

    def _in(self, seconds):
        return (datetime.now(timezone.utc)
                + timedelta(seconds=seconds)).isoformat()

    def test_a_promised_quiet_is_honoured_across_a_restart(self):
        self._write({"updated_at": self._in(-600),
                     "five_hour": {"utilization": 12},
                     "last_error": "http_429",
                     "next_attempt_at": self._in(3000),
                     "rate_limit_strikes": 2})
        wait, strikes = self.mod._resume_backoff()
        self.assertGreater(wait, 2900)
        self.assertEqual(strikes, 2)

    def test_an_expired_backoff_owes_nothing(self):
        self._write({"last_error": "http_429",
                     "next_attempt_at": self._in(-5)})
        self.assertEqual(self.mod._resume_backoff(), (0.0, 0))

    def test_only_a_rate_limit_is_resumed(self):
        self._write({"last_error": "network_error",
                     "next_attempt_at": self._in(3000)})
        self.assertEqual(self.mod._resume_backoff(), (0.0, 0))

    def test_an_error_status_file_resumes_too(self):
        """Once the reading has aged out the file is the error-status shape
        (`error`, not `last_error`) — a restart mid-wall usually finds it."""
        self._write({"error": "http_429",
                     "next_attempt_at": self._in(3000)})
        wait, strikes = self.mod._resume_backoff()
        self.assertGreater(wait, 2900)
        self.assertEqual(strikes, 1)

    def test_an_absurd_promise_is_capped(self):
        self._write({"last_error": "http_429",
                     "next_attempt_at": self._in(10 ** 8)})
        wait, _ = self.mod._resume_backoff()
        self.assertEqual(wait, self.mod.RETRY_AFTER_MAX_S)

    def test_a_missing_or_broken_file_owes_nothing(self):
        self.assertEqual(self.mod._resume_backoff(), (0.0, 0))
        with open(self.mod.USAGE_FILE, "w") as fh:
            fh.write("{nope")
        self.assertEqual(self.mod._resume_backoff(), (0.0, 0))


if __name__ == "__main__":
    unittest.main()
