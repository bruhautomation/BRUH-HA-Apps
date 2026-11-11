"""Nothing credential-shaped leaves the house.

Reports, captures, the journal and the development loop's issues all leave
the box (a file somebody pastes, an issue in a repository). Every one of
them goes through a redactor first; this holds each redactor to the same
credential shapes.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import capture  # noqa: E402
import journal  # noqa: E402
import reports  # noqa: E402
from devloop import upstream  # noqa: E402

SECRETS = (
    "sk-ant-oat01-AbCdEfGhIjKlMnOpQrStUv",
    "Bearer abcdef0123456789abcdef",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6.eyJzdWIiOiIxMjM0NTY3ODkw.SflKxwRJSMeKKF2QT4fw",
    "accountId: 884213",
)
REDACTORS = (("capture", capture.redact), ("journal", journal.scrub),
             ("reports", reports.redact), ("upstream", upstream.scrub))


def leaked(secret: str, out: str) -> bool:
    # The label ("Bearer", "accountId:") may stay; the value may not.
    return secret.split()[-1] in out


class TestEveryRedactor(unittest.TestCase):
    def test_a_credential_in_prose_is_taken_out(self):
        for secret in SECRETS:
            for name, fn in REDACTORS:
                with self.subTest(secret=secret[:12], redactor=name):
                    out = fn(f"Login refused: {secret} by the cloud")
                    self.assertFalse(leaked(secret, out), out)
                    self.assertIn("[redacted]", out)

    def test_ordinary_words_are_left_alone(self):
        text = "the user is home and sensor.user_id_badge is on"
        for name, fn in REDACTORS:
            with self.subTest(redactor=name):
                self.assertEqual(fn(text), text)

    def test_a_token_field_in_json_is_blanked(self):
        raw = '{"access_token": "abcdefgh12345678", "value": "on"}'
        out = reports.redact(raw)
        self.assertNotIn("abcdefgh12345678", out)
        self.assertIn('"value": "on"', out)
        self.assertEqual(
            capture.redact({"refresh_token": "abcdefgh12345678", "value": "on"}),
            {"refresh_token": "[redacted]", "value": "on"})

    def test_a_github_token_never_reaches_an_issue(self):
        for token in ("ghp_" + "a1B2" * 9, "github_pat_" + "a1B2_" * 6):
            self.assertNotIn(token, upstream.scrub(f"push failed with {token}"))


if __name__ == "__main__":
    unittest.main()
