#!/usr/bin/env python3
"""`ha-selftest.sh`, driven a block at a time.

Two of its blocks are lifted out of the real script and run in a shell,
the way test_memory_learning drives ``consolidator_lock_check``: the
`--json` report block (recording, printing, the emitter), and the verdict
it prints on the Claude CLI's own credential. A grep for a line is not a
test of what the line does — and the credential verdict in particular is
a sentence that has to be TRUE of the state it is printed for, which is
not a property any grep can check.
"""

import json
import os
import re
import subprocess
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "brain" / "scripts" / "ha-selftest.sh"


def report_block() -> str:
    src = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^JSON_MODE=0\n.*?^PYEMIT\n\}\n", src, re.M | re.S)
    assert match, "ha-selftest.sh no longer defines the JSON report block"
    return match.group(0)


def run(args: str, body: str) -> subprocess.CompletedProcess:
    script = (
        "set -u\n"
        + report_block()
        + "\n" + body
        + '\nif [ "$JSON_MODE" = "1" ]; then emit_json; rm -f "$RECORDS"; exit 0; fi\n'
        + 'rm -f "$RECORDS"\n'
    )
    return subprocess.run(["bash", "-c", script, "doctor"] + args.split(),
                          capture_output=True, text=True, timeout=30)


BODY = '''
hdr "Environment & Home Assistant API"
pass "token present"
info "a detail, with \\"quotes\\" and a | pipe"
hdr "Background listeners"
warn "study watcher not running"
fail "Panel not answering (:8099/api/health)"
'''


class TestJsonMode(unittest.TestCase):
    def test_json_mode_prints_one_object_and_nothing_else(self):
        proc = run("--json", BODY)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)  # the whole of stdout parses
        self.assertFalse(data["ok"])
        self.assertEqual((data["passed"], data["failed"], data["warnings"]), (1, 1, 1))
        kinds = [c["kind"] for c in data["checks"]]
        self.assertEqual(kinds, ["pass", "info", "warn", "fail"])
        self.assertEqual(data["checks"][0]["section"], "Environment & Home Assistant API")
        self.assertEqual(data["checks"][3]["section"], "Background listeners")
        self.assertIn('"quotes"', data["checks"][1]["text"])
        self.assertIn("|", data["checks"][1]["text"])

    def test_text_mode_is_unchanged(self):
        proc = run("", BODY)
        self.assertIn("✓ token present", proc.stdout)
        self.assertIn("✗ Panel not answering", proc.stdout)
        self.assertIn("! study watcher", proc.stdout)
        self.assertNotIn("{", proc.stdout)

    def test_the_real_script_routes_the_flag_and_the_dispatcher_offers_it(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if [ "$JSON_MODE" = "1" ]; then\n    emit_json', src)
        dispatcher = (REPO / "brain" / "scripts" / "brain.sh").read_text(encoding="utf-8")
        self.assertIn("brain doctor [--json]", dispatcher)
        self.assertIn("check)      delegate brain-check.sh", dispatcher)
        self.assertIn("report)     delegate brain-report.sh", dispatcher)


class TestReportScript(unittest.TestCase):
    """`brain report` redacts every file, whether or not it thinks it needs to."""

    def test_redaction_covers_the_credential_shapes(self):
        src = (REPO / "brain" / "scripts" / "brain-report.sh").read_text(encoding="utf-8")
        match = re.search(r"^redact\(\) \{\n.*?^\}\n", src, re.M | re.S)
        assert match, "brain-report.sh no longer defines redact()"
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "sample.json")
            path.write_text(
                'token sk-ant-oat01-ABCDEFGHIJKLMNOPQRSTUVWXYZ here\n'
                'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123\n'
                '{"access_token": "0123456789abcdef", "value": "sk-ant-api03-zzzzzzzzzzzz"}\n'
                'jwt eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV\n'
                'sensor.kitchen_temperature is fine\n')
            proc = subprocess.run(
                ["bash", "-c", match.group(0) + f'\nredact "{path}"\n'],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = path.read_text()
        self.assertNotIn("sk-ant-", out)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123", out)
        self.assertNotIn("0123456789abcdef", out)
        self.assertNotIn("eyJhbGci", out)
        self.assertIn("sensor.kitchen_temperature", out)
        self.assertGreaterEqual(out.count("[redacted]"), 5)


class TestTheCliCredentialVerdict(unittest.TestCase):
    """The three sentences a lapsed access token can deserve.

    `ha-selftest.sh` had one, and it was the worst of the three: *"the
    terminal prefers this one, so it will keep asking you to log in"*, plus
    a Fix that deleted the credential and its backup. The `accessToken` is
    short-lived by design and the file carries the `refreshToken` the CLI
    mints the next one from by itself — so on an install whose only
    credential is that file, a lapsed token is not a fault, and the advice
    threw a working sign-in away to cure it. The warning is true of exactly
    one of the three states, and this drives all three.

    Lifted out of the script and run, the way the report block above is: a
    grep for a line is not a test of what the line does.
    """

    @classmethod
    def setUpClass(cls):
        src = SCRIPT.read_text(encoding="utf-8")
        match = re.search(
            r'^cli_cred=.*?^fi\n(?=if \[ -f "\$USAGE_FILE" \])', src, re.M | re.S)
        assert match, "ha-selftest.sh no longer defines the CLI credential verdict"
        cls.block = match.group(0)

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "home" / ".claude").mkdir(parents=True)
        (self.root / "secrets").mkdir()
        (self.root / "shared").mkdir()
        self.cli = self.root / "home" / ".claude" / ".credentials.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _put(self, path, body):
        """Write the fixture from the shell, so nothing in this process
        stores a credential-shaped string (the reason the backup-restore
        tests do the same)."""
        proc = subprocess.run(
            ["bash", "-c", 'printf "%s" "$1" > "$2"', "_", body, str(path)],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def _credential(self, offset_s, refresh=True):
        oauth = {"accessToken": "sk-ant-" + "x" * 40,
                 "expiresAt": int((time.time() + offset_s) * 1000)}
        if refresh is not True:
            if refresh is not False:
                oauth["refreshToken"] = refresh
        else:
            oauth["refreshToken"] = "sk-ant-ort01-" + "r" * 30
        self._put(self.cli, json.dumps({"claudeAiOauth": oauth}))

    def _other_store(self, which="panel"):
        name = "secrets" if which == "panel" else "shared"
        self._put(self.root / name / "claude_auth.json",
                  json.dumps({"type": "oauth_token",
                              "value": "sk-ant-oat01-" + "p" * 30,
                              "saved_at": 1752000000}))

    def _run(self):
        """Run the real block with the counters and printers stubbed."""
        script = (
            "set -u\n"
            'warn() { echo "WARN|$1"; }\n'
            'info() { echo "INFO|$1"; }\n'
            'pass() { echo "PASS|$1"; }\n'
            + self.block
        )
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True, timeout=30,
            env={**os.environ,
                 "HOME": str(self.root / "home"),
                 "CLAUDE_CONFIG_DIR": str(self.root / "home" / ".claude"),
                 "BRAIN_SECRETS": str(self.root / "secrets"),
                 "BRAIN_SHARED_AUTH": str(self.root / "shared" / "claude_auth.json")})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        lines = [ln for ln in proc.stdout.splitlines() if "|" in ln]
        return [tuple(ln.split("|", 1)) for ln in lines]

    @staticmethod
    def _kinds(lines):
        return [kind for kind, _ in lines]

    # -- the three states an expiry in the past can be ---------------------

    def test_a_lapsed_token_with_another_store_behind_it_warns(self):
        """The shadowing case, and the only one the warning was ever true
        of. `brain-auth-env.sh` is strict here on purpose: it falls through
        and exports the panel credential, so the terminal runs on that one
        and the CLI never gets the run that would refresh its own."""
        self._credential(-3600)
        self._other_store("panel")
        lines = self._run()
        self.assertIn("WARN", self._kinds(lines))
        warned = " ".join(t for k, t in lines if k == "WARN")
        self.assertIn("EXPIRED", warned)
        self.assertIn("panel sign-in", warned)
        # And it must not be the old sentence, which was about a login
        # nobody had to redo.
        self.assertNotIn("keep asking you to log in", warned)

    def test_the_shared_store_shadows_it_too_and_is_named(self):
        self._credential(-3600)
        self._other_store("shared")
        warned = " ".join(t for k, t in self._run() if k == "WARN")
        self.assertIn("ha login", warned)

    def test_a_lapsed_token_that_can_renew_itself_is_only_an_info(self):
        """The bug. Nothing is wrong here: the next `claude` run mints a new
        access token off the refresh token in the same file, and the old
        line sent somebody to delete it."""
        self._credential(-3600)
        lines = self._run()
        self.assertNotIn("WARN", self._kinds(lines))
        said = " ".join(t for _, t in lines)
        self.assertIn("refresh token", said)
        self.assertIn("next run", said)

    def test_a_lapsed_token_with_nothing_to_renew_it_still_warns(self):
        """The revoked session. There is no other store to carry the
        terminal and nothing in the file can renew it, so this is the one
        state where somebody really does have to sign in again."""
        self._credential(-3600, refresh=False)
        lines = self._run()
        warned = " ".join(t for k, t in lines if k == "WARN")
        self.assertIn("no refresh token", warned)
        said = " ".join(t for _, t in lines)
        self.assertIn("ha login", said)

    def test_a_refresh_token_that_is_not_one_does_not_soften_the_verdict(self):
        """Same predicate as `engine._cli_credentials_present` and run.sh's
        restore: a usable string, never the key being there. jq's `//` fills
        in a null but not an empty string or a number."""
        for junk in (None, "", 0, 12345, [], {}):
            with self.subTest(refreshToken=repr(junk)):
                self.tearDown()
                self.setUp()
                self._credential(-3600, refresh=junk)
                warned = " ".join(t for k, t in self._run() if k == "WARN")
                self.assertIn("no refresh token", warned)

    # -- and the states that were already right ----------------------------

    def test_a_live_credential_is_an_info_naming_the_date(self):
        self._credential(9000)
        self._other_store("panel")
        lines = self._run()
        self.assertNotIn("WARN", self._kinds(lines))
        self.assertIn("valid until", " ".join(t for _, t in lines))

    def test_a_credential_recording_no_expiry_says_exactly_that(self):
        self._put(self.cli, json.dumps({"claudeAiOauth": {
            "accessToken": "sk-ant-" + "x" * 40}}))
        lines = self._run()
        self.assertNotIn("WARN", self._kinds(lines))
        self.assertIn("records no expiry", " ".join(t for _, t in lines))

    def test_no_cli_credential_at_all_says_nothing_here(self):
        """The panel-only install. This block is about one file, and the
        roll-call above it has already reported the stores."""
        self._other_store("panel")
        self.assertEqual(self._run(), [])

    def test_the_fix_line_no_longer_tells_anybody_to_delete_the_backup(self):
        """`run.sh` discards a dead backup by itself now and keeps a
        refreshable one, so `rm -f … /data/.brain_auth_backup/…` is advice
        that either does nothing or throws away a working sign-in."""
        self.assertNotIn(".brain_auth_backup", self.block)
        self.assertNotIn("keep asking you to log in", self.block)


if __name__ == "__main__":
    unittest.main()
