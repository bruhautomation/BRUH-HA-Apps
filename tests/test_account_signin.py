"""The panel can perform the sign-in that can read your usage.

The complaint this answers, in the words it arrived in: *"There is no
terminal... no place to run ha login. Like wtf is this recommending that I
do? the whole point is to login once and have that work everywhere."*

Every sign-in brAIn's UI offered ran `claude setup-token`, which asks
Anthropic for `user:inference` and nothing else — so the panel's own guided
sign-in minted a credential that can never read the usage figures, and the
only remedy it knew how to name was `claude /login` **in the Terminal tab**:
a shell command, in a tab `enable_terminal` removes and whose default face
is a chat with no shell in it.

Measured off the authorize URL each command prints, which is the only place
either states its scopes:

    claude setup-token  ->  scope=user:inference
    claude auth login   ->  scope=org:create_api_key user:profile
                                  user:inference user:sessions:claude_code
                                  user:mcp_servers user:file_upload

`user:profile` is what `/api/oauth/usage` requires. `auth login` is a plain
subcommand, not the TUI's `/login`, so it drives on a pty exactly as
`setup-token` does — which is what makes this a panel button rather than an
instruction to go and find a terminal.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))


class TestTheTwoSignIns(unittest.TestCase):
    """What each mode runs, and which one a person gets by default."""

    def setUp(self):
        import engine
        self.engine = engine

    def test_the_account_sign_in_runs_claude_auth_login(self):
        self.assertEqual(
            list(self.engine.FLOW_MODES["account"]["argv"]), ["auth", "login"])

    def test_the_shareable_token_still_runs_setup_token(self):
        """Not a replacement. A session credential refreshes itself and so
        cannot be copied into the file the other BRUH add-ons read; a
        long-lived token can, and that is what `ha login --share` is for."""
        self.assertEqual(
            list(self.engine.FLOW_MODES["token"]["argv"]), ["setup-token"])

    def test_the_default_is_the_one_that_can_read_usage(self):
        """The button somebody presses without thinking has to be the one
        that works. Defaulting to `setup-token` is what produced a panel
        that signed you in and then told you to go to a terminal."""
        self.assertEqual(self.engine.DEFAULT_FLOW_MODE, "account")

    def test_an_unknown_mode_falls_back_rather_than_running_it(self):
        flow = self.engine.SetupTokenFlow()
        flow.start("../../etc/passwd")
        try:
            self.assertEqual(flow.mode, self.engine.DEFAULT_FLOW_MODE)
        finally:
            flow.cancel()


class TestWhatTheFlowActuallyLaunches(unittest.TestCase):
    """A constant nobody passes down is a constant.

    `start()` is driven over a real pty against a stub that records its own
    argv, because the mode reaching `FLOW_MODES` and the mode reaching the
    process are different claims — and the second is the one that decides
    which scopes Anthropic is asked for.
    """

    def setUp(self):
        import engine
        self.engine = engine
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.argv_file = Path(self.tmp.name) / "argv.txt"
        stub = Path(self.tmp.name) / "claude"
        stub.write_text(
            "#!/bin/bash\n"
            f"printf '%s\\n' \"$*\" > {self.argv_file}\n"
            "printf 'Opening browser to sign in\\n'\n"
            "printf 'https://claude.com/cai/oauth/authorize"
            "?code=true&client_id=x&redirect_uri=y&state=z\\n'\n"
            "printf 'Paste code here if prompted > '\n"
            "read -r line\n"
            "sleep 5\n"
        )
        stub.chmod(0o755)
        old = self.engine._claude_argv
        self.engine._claude_argv = lambda: [str(stub)]
        self.addCleanup(lambda: setattr(self.engine, "_claude_argv", old))

    def _launched(self, mode) -> str:
        flow = self.engine.SetupTokenFlow()
        try:
            flow.start(mode)
            for _ in range(80):
                if self.argv_file.exists() and self.argv_file.read_text().strip():
                    break
                time.sleep(0.05)
        finally:
            flow.cancel()
        return self.argv_file.read_text().strip()

    def test_the_account_mode_really_runs_auth_login(self):
        self.assertEqual(self._launched("account"), "auth login")

    def test_the_token_mode_really_runs_setup_token(self):
        self.assertEqual(self._launched("token"), "setup-token")


class TestTheAccountSignInCompletes(unittest.TestCase):
    """`auth login` prints no token, so the credential FILE is the success.

    `setup-token` prints a token the flow scrapes and saves; `auth login`
    writes the CLI's own `.credentials.json` and prints nothing to capture.
    `_signed_in_here` — which already required that file to have CHANGED
    since the flow started, so a stale one cannot pass — is what carries it.
    """

    def test_a_pty_run_that_writes_the_credential_file_reaches_done(self):
        import engine
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        home = Path(tmp.name)
        (home / ".claude").mkdir(parents=True)
        cred = home / ".claude" / ".credentials.json"
        # A credential already there and already stale: the flow must not
        # read it as its own success.
        cred.write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "sk-ant-oat01-old", "refreshToken": "r",
            "expiresAt": 1}}))

        payload = json.dumps({"claudeAiOauth": {
            "accessToken": "sk-ant-oat01-new", "refreshToken": "r2",
            "expiresAt": int(time.time() * 1000) + 3600_000}})
        stub = home / "claude"
        stub.write_text(
            "#!/bin/bash\n"
            "printf 'Opening browser to sign in\\n'\n"
            "printf 'https://claude.com/cai/oauth/authorize"
            "?code=true&client_id=x&redirect_uri=y&state=z\\n'\n"
            "printf 'Paste code here if prompted > '\n"
            "read -r line\n"
            "sleep 0.3\n"
            f"cat > {cred} <<'JSON'\n{payload}\nJSON\n"
            "printf 'Login successful\\n'\n"
            "sleep 5\n"
        )
        stub.chmod(0o755)

        old_home, old_argv = engine.CLAUDE_HOME, engine._claude_argv
        engine.CLAUDE_HOME = str(home)
        engine._claude_argv = lambda: [str(stub)]
        flow = engine.SetupTokenFlow()
        try:
            flow.start("account")
            for _ in range(80):
                if flow.status()["phase"] == "awaiting_code":
                    break
                time.sleep(0.05)
            self.assertEqual(flow.status()["phase"], "awaiting_code",
                             flow.status())
            flow.submit_code("code-123")
            for _ in range(120):
                if flow.status()["phase"] in ("done", "error"):
                    break
                time.sleep(0.05)
            self.assertEqual(flow.status()["phase"], "done", flow.status())
        finally:
            flow.cancel()
            engine.CLAUDE_HOME, engine._claude_argv = old_home, old_argv


class TestNobodyIsSentToATerminalTheyMayNotHave(unittest.TestCase):
    """The regression test for the complaint itself.

    The remedy for an under-scoped token is now a button in the panel, so no
    surface may answer it by naming a shell command in a tab that
    `enable_terminal` can remove and whose default face has no shell. The
    scan is over the four places a person meets this verdict.
    """

    SURFACES = [
        BASE_DIR / "brain" / "panel" / "app.js",
        BASE_DIR / "brain" / "scripts" / "usage-limits-tracker.py",
        BASE_DIR / "brain" / "scripts" / "ha-selftest.sh",
        BASE_DIR / "brain" / "custom_components" / "brain" / "sensor.py",
    ]

    def test_no_scope_remedy_tells_you_to_open_a_terminal(self):
        # The sentence, not the word: these files legitimately DISCUSS the
        # terminal (it is one of the credential stores), and a grep for
        # "Terminal" alone would fail on prose that is simply true.
        bad = re.compile(
            r"(claude\s*/login|ha login)[^.\n]{0,80}Terminal tab"
            r"|Terminal tab[^.\n]{0,80}(claude\s*/login|ha login)",
            re.IGNORECASE)
        for path in self.SURFACES:
            with self.subTest(path.name):
                for n, line in enumerate(path.read_text().splitlines(), 1):
                    self.assertIsNone(
                        bad.search(line),
                        f"{path.name}:{n} sends somebody to a terminal for a "
                        f"sign-in the panel can now perform: {line.strip()}")

    def test_the_panel_names_the_button_that_fixes_it(self):
        app = (BASE_DIR / "brain" / "panel" / "app.js").read_text()
        note = app.split("oauth_token_lacks_usage_scope", 1)[1][:800]
        self.assertIn("Claude account", note)

    def test_both_sign_ins_are_reachable_from_the_panel(self):
        html = (BASE_DIR / "brain" / "panel" / "index.html").read_text()
        app = (BASE_DIR / "brain" / "panel" / "app.js").read_text()
        for el in ("setupStart", "setupStartToken"):
            self.assertIn(f'id="{el}"', html)
            self.assertIn(f'#{el}"', app)
        # And each button asks for its own mode: one handler that always sent
        # the default would be the shipped bug with a second button on it.
        self.assertIn('startSetup("account")', app)
        self.assertIn('startSetup("token")', app)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
