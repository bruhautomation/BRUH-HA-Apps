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
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
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
        token, source = self.mod.find_oauth_token()
        self.assertEqual(token, "sk-ant-oat01-cli")
        self.assertEqual(source, "claude cli")

    def test_a_panel_login_is_found(self):
        """The case that was broken: no CLI credential file at all, because
        the person signed in through the panel."""
        self._write(os.path.join(self.secrets, "claude_auth.json"),
                    {"type": "oauth_token", "value": "sk-ant-oat01-panel"})
        token, source = self.mod.find_oauth_token()
        self.assertEqual(token, "sk-ant-oat01-panel")
        self.assertEqual(source, "panel")

    def test_a_shared_ha_login_is_found(self):
        self._write(self.shared,
                    {"type": "oauth_token", "value": "sk-ant-oat01-shared"})
        token, source = self.mod.find_oauth_token()
        self.assertEqual(token, "sk-ant-oat01-shared")
        self.assertEqual(source, "ha login")

    def test_an_api_key_says_so_rather_than_not_authenticated(self):
        """An API key bills per token and has no subscription window, so
        there is no utilization to report and never will be. Saying
        "no_oauth_token" sends people to redo a sign-in that worked."""
        self._write(os.path.join(self.secrets, "claude_auth.json"),
                    {"type": "api_key", "value": "sk-ant-api03-xyz"})
        token, reason = self.mod.find_oauth_token()
        self.assertIsNone(token)
        self.assertEqual(reason, "api_key_has_no_usage_limits")

    def test_nothing_at_all_is_no_oauth_token(self):
        token, reason = self.mod.find_oauth_token()
        self.assertIsNone(token)
        self.assertEqual(reason, "no_oauth_token")

    def test_malformed_stores_are_skipped_not_fatal(self):
        with open(os.path.join(self.secrets, "claude_auth.json"), "w") as fh:
            fh.write("{not json")
        self._write(self.shared,
                    {"type": "oauth_token", "value": "sk-ant-oat01-shared"})
        token, source = self.mod.find_oauth_token()
        self.assertEqual(token, "sk-ant-oat01-shared")
        self.assertEqual(source, "ha login")

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
        self.assertEqual(mod.find_oauth_token()[0], "sk-ant-oat01-cfg")


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


if __name__ == "__main__":
    unittest.main()
