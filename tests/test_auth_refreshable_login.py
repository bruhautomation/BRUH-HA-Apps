"""An account sign-in whose access token has lapsed is still the account
sign-in, and the terminal must not hand the CLI a weaker one over it.

The access token in Claude Code's own `.credentials.json` lives for hours;
the file also carries the refresh token the CLI mints the next one from on
its next run. `brain-auth-env.sh` read a lapsed access token as no
credential at all, fell through to the panel's or `ha login`'s long-lived
token — one that can run Claude and nothing else — and exported it as
CLAUDE_CODE_OAUTH_TOKEN. The CLI then never opened its own file, never
refreshed it, and Remote Control refused for want of a full-scope login,
again and again.

`ha login --status` reported the same file as EXPIRED in red, which is
true of the access token and false of the sign-in.
"""
import json
import os
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
SCRIPTS = BASE_DIR / "brain" / "scripts"
AUTH_ENV = SCRIPTS / "brain-auth-env.sh"
SHARE_LOGIN = SCRIPTS / "ha-share-login.sh"


class _Stores(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.secrets = self.root / "secrets"
        self.shared_dir = self.root / "shared"
        for d in (self.home / ".claude", self.secrets, self.shared_dir):
            d.mkdir(parents=True)
        self.cli = self.home / ".claude" / ".credentials.json"

    def _put(self, path, body):
        """From the shell, so this process never holds a token-shaped
        string beside a file name (the reason the other auth tests do)."""
        proc = subprocess.run(
            ["bash", "-c", 'printf "%s" "$1" > "$2"', "_", body, str(path)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def _cli(self, access_in_s, refresh=True, refresh_in_s=None):
        oauth = {"accessToken": "sk-ant-" + "x" * 40,
                 "expiresAt": int((time.time() + access_in_s) * 1000)}
        if refresh:
            oauth["refreshToken"] = "sk-ant-ort01-" + "r" * 30
        if refresh_in_s is not None:
            oauth["refreshTokenExpiresAt"] = int(
                (time.time() + refresh_in_s) * 1000)
        self._put(self.cli, json.dumps({"claudeAiOauth": oauth}))

    def _panel(self):
        self._put(self.secrets / "claude_auth.json",
                  json.dumps({"type": "oauth_token",
                              "value": "sk-ant-oat01-" + "p" * 30,
                              "saved_at": 1752000000}))

    def _env(self):
        env = dict(os.environ)
        env.update({"BRAIN_HOME": str(self.home),
                    "BRAIN_SECRETS": str(self.secrets),
                    "BRAIN_SHARED_AUTH": str(self.shared_dir / "claude_auth.json"),
                    "BRAIN_AUTH_DIR": str(self.shared_dir)})
        env.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        env.pop("ANTHROPIC_API_KEY", None)
        return env


class TestTheTerminalDefersToARefreshableSignIn(_Stores):

    def _exported(self):
        out = subprocess.run(
            ["bash", "-c",
             f'. "{AUTH_ENV}"; echo "${{CLAUDE_CODE_OAUTH_TOKEN:-}}"'],
            capture_output=True, text=True, env=self._env(), timeout=30,
            check=True)
        return out.stdout.strip()

    def test_a_lapsed_access_token_beside_a_refresh_token_exports_nothing(self):
        """The report: the CLI's access token lapsed, a panel setup token
        sat below it, and the terminal ran on the setup token."""
        self._cli(-3600)
        self._panel()
        self.assertEqual(self._exported(), "",
                         "a lower store shadowed a sign-in that renews itself")

    def test_a_refresh_token_still_inside_its_own_life_counts(self):
        self._cli(-3600, refresh_in_s=86400)
        self._panel()
        self.assertEqual(self._exported(), "")

    def test_a_refresh_token_past_its_own_expiry_does_not(self):
        """The file records when the refresh token itself dies; past that
        nothing can renew the sign-in and the panel's token is the one that
        works."""
        self._cli(-3600, refresh_in_s=-60)
        self._panel()
        self.assertTrue(self._exported().startswith("sk-ant-oat01-"))

    def test_no_refresh_token_still_falls_through(self):
        self._cli(-3600, refresh=False)
        self._panel()
        self.assertTrue(self._exported().startswith("sk-ant-oat01-"))


class TestTheStatusSaysItRenewsItself(_Stores):

    def _status(self):
        out = subprocess.run(["bash", str(SHARE_LOGIN), "--status"],
                             capture_output=True, text=True, env=self._env(),
                             timeout=30)
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_a_refreshable_lapse_is_not_reported_as_expired(self):
        self._cli(-3600)
        said = self._status()
        self.assertNotIn("EXPIRED", said)
        self.assertIn("expired, refreshes itself on next use", said)

    def test_a_dead_one_is_still_expired(self):
        self._cli(-3600, refresh=False)
        self.assertIn("EXPIRED", self._status())

    def test_an_inference_only_token_alone_is_warned_about(self):
        """A panel or `ha login` token runs Claude and nothing else; when it
        is the only usable credential the usage figures and Remote Control
        cannot work, and the status has to say which sign-in fixes that."""
        self._panel()
        said = self._status()
        self.assertIn("can only run Claude", said)
        self.assertIn("Sign in to your Claude account", said)

    def test_no_warning_while_the_account_sign_in_is_usable(self):
        self._cli(-3600)
        self._panel()
        self.assertNotIn("can only run Claude", self._status())


if __name__ == "__main__":
    unittest.main()
