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


class TestLikedCarriesCountsOnly(unittest.TestCase):
    """The Liked stream reads stores full of names and typed words, and
    files counts and brAIn's own names for its rules and kinds."""

    def test_no_name_no_typed_word_and_no_entity_leaves(self):
        from devloop import streams
        private = ("Marguerite", "person.marguerite", "sensor.nursery_door",
                   "the nursery door was left open", "because the baby sleeps",
                   "Welcome home, Marguerite", "Lock the nursery at night")
        signals = {
            "settled": [
                {"source": "check:battery_low", "kind": "fixed", "release": "9.9.9",
                 "text": "the nursery door was left open",
                 "note": "because the baby sleeps", "source_title": "Marguerite's rule"},
                {"source": "check:battery_low", "kind": "accepted"},
                # A producer keyed on an entity is counted under its family.
                {"source": "baseline:sensor.nursery_door", "kind": "fixed"},
                {"source": "baseline:sensor.nursery_door", "kind": "fixed"},
                # A source that is a sentence is not printed at all.
                {"source": "Marguerite", "kind": "fixed"},
                {"source": "Marguerite", "kind": "fixed"},
            ],
            "presence": {
                "people": {"person.marguerite": {"name": "Marguerite",
                                                  "retired": {"morning": 1}}},
                "touches": [{"id": "a1", "person": "person.marguerite",
                             "name": "Marguerite", "kind": "arrival",
                             "text": "Welcome home, Marguerite",
                             "reason": "because the baby sleeps",
                             "reaction": "thanks"}]},
            "proposals": [{"kind": "automation", "status": "accepted",
                           "title": "Lock the nursery at night",
                           "note": "because the baby sleeps"}],
            "fixes": [{"status": "held", "text": "the nursery door was left open"}],
            "morph": {"items": [{"status": "done", "title": "Marguerite"}],
                      "keeps": {"card:c1": {"entity": "sensor.nursery_door",
                                            "why": "because the baby sleeps"}}},
            "discussions": 2,
        }
        rows = streams.liked(signals, "9.9.9")
        self.assertEqual(len(rows), 1)
        sent = " ".join(str(rows[0].get(k) or "")
                        for k in ("where", "what", "detail", "body"))
        for secret in private:
            self.assertNotIn(secret.lower(), sent.lower())
        # And what it is for did arrive: the rule, the family, the counts.
        self.assertIn("| `check:battery_low` | 1 | 1 | 0 | 1 |", sent)
        self.assertIn("| `baseline` | 2 | 0 | 0 | 0 |", sent)
        self.assertIn("| `arrival` | 1 | 1 | 0 | 0 | 0 |", sent)

    def test_a_house_with_nothing_counted_files_nothing(self):
        from devloop import streams
        self.assertEqual(streams.liked({"settled": [], "presence": {}}, "9.9.9"), [])


if __name__ == "__main__":
    unittest.main()
