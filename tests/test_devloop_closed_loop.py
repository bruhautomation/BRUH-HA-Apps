"""The development loop closes: a fix is judged on the house it came from.

Before this the loop was open at four seams. The cloud wrote "Fixed in
brAIn x.y.z" and the house read nothing off it, so a fault seen on an
OLDER release reopened the fix a day after any unrelated update, and a
house with auto-update off was read as a house where every fix held. A
request the owner typed had no fingerprint to stop, so nobody ever asked
them whether the fix did what they asked. A fault issue carried one
sentence and no evidence a fix could be aimed at. And the Resident's own
judgement — graded nightly by what the household answered — reached the
cloud through nothing.

Driven over the real queue, the real GitHub fake and the real store.
"""
from __future__ import annotations

import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import NAMES, TOKEN, DevloopCase, diagnostics, streams_mod, upstream  # noqa: E402

import devloop  # noqa: E402
import devloop.verify as verify  # noqa: E402

HOUR = 3600


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class _Case(DevloopCase):
    def close_fixed(self, number: int, at: float, version: str = "2.17.2",
                    comment: str | None = None):
        self.gh.judge(number, "devloop:fixed")
        self.gh.issues[number - 1]["closed_at"] = _iso(at)
        if comment is None:
            comment = (f"Fixed in brAIn {version} (https://github.test/pr/9). The "
                       "house will say \"Not seen since\" or \"Back again\" after it updates.")
        self.gh.comments.append((number, comment))

    def pass_(self, now: float, version: str = "2.17.0"):
        upstream.sweep(diagnostics(version=version), NAMES, now=now)
        upstream.send_due(now=now)

    def read_verdicts(self, now: float, version: str = "2.17.0"):
        self.pass_(now + upstream.VERDICT_INTERVAL_S + 1, version)


class TestTheFixVersionComesHome(_Case):
    def test_the_release_a_fix_shipped_in_is_read_off_the_closing_comment(self):
        self.switch_on()
        t = time.time() - 5 * 24 * HOUR
        self.pass_(t)
        self.close_fixed(1, t + HOUR, "2.17.2")
        self.read_verdicts(t + HOUR)
        row = next(e for e in upstream._load()["items"].values() if e.get("issue") == 1)
        self.assertEqual(row["fixed_in"], "2.17.2")
        self.assertEqual(row["verdict"], "fixed")

    def test_a_close_with_no_version_is_unknown_and_never_read_as_arrived(self):
        self.switch_on()
        t = time.time() - 5 * 24 * HOUR
        self.pass_(t)
        self.close_fixed(1, t + HOUR, comment="Closing this by hand.")
        self.read_verdicts(t + HOUR)
        row = next(e for e in upstream._load()["items"].values() if e.get("issue") == 1)
        self.assertNotIn("fixed_in", row)
        self.assertIsNone(upstream.running_at_least("2.17.9", ""))
        self.assertEqual(upstream.awaiting_update(), [])

    def test_version_arithmetic(self):
        self.assertTrue(upstream.running_at_least("3.1.0", "3.0.9"))
        self.assertTrue(upstream.running_at_least("3.0.9", "3.0.9"))
        self.assertFalse(upstream.running_at_least("3.0.10", "3.1.0"))
        self.assertFalse(upstream.running_at_least("3.0.9", "3.0.10"))  # not a string compare
        self.assertIsNone(upstream.running_at_least("dev", "3.0.9"))


class TestAFixTheHouseHasNotInstalled(_Case):
    """Seeing a fault on a release OLDER than the fix says nothing about
    the fix: no reopen, no comment, and the wait said where the cloud
    reads it."""

    def test_is_not_reopened_by_an_unrelated_update(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.pass_(t)
        closed = t + 2 * HOUR
        self.close_fixed(1, closed, "2.18.0")
        self.read_verdicts(closed)
        # The house updates to 2.17.1 — not the fix — and keeps seeing it
        # for two days.
        for h in range(3, 50, 3):
            self.pass_(closed + h * HOUR, version="2.17.1")
        self.assertEqual(self.gh.issues[0]["state"], "closed")
        self.assertEqual([c for c in self.gh.comments if c[1].startswith("Back again")], [])

    def test_the_wait_is_counted_and_said_on_the_scorecard(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.pass_(t)
        self.close_fixed(1, t + HOUR, "2.18.0")
        self.read_verdicts(t + HOUR)
        waiting = upstream.awaiting_update()
        self.assertEqual([(w["issue"], w["fixed_in"]) for w in waiting], [(1, "2.18.0")])
        st = upstream.status()
        self.assertEqual((st["awaiting_update"], st["awaiting_version"]), (1, "2.18.0"))
        body = streams_mod.scorecard([], diagnostics(), "2.17.0", waiting)[0]["body"]
        self.assertIn("#1 needs brAIn 2.18.0", body)
        self.assertIn("not one that held", body)
        self.assertIn("Awaiting an update: nothing",
                      streams_mod.scorecard([], diagnostics(), "2.17.0", [])[0]["body"])

    def test_once_installed_and_gone_the_house_says_held(self):
        self.switch_on()
        t = time.time() - 10 * 24 * HOUR
        self.pass_(t)
        closed = t + HOUR
        self.close_fixed(1, closed, "2.17.2")
        self.read_verdicts(closed)
        self.rows = []
        later = closed + upstream.CLEAR_AFTER_S + 2 * HOUR
        self.pass_(later, version="2.17.2")
        held = [c for c in self.gh.comments if c[0] == 1 and c[1].startswith("Held:")]
        self.assertEqual(len(held), 1)
        self.assertIn("on brAIn 2.17.2 (fixed in 2.17.2)", held[0][1])
        self.assertEqual(upstream.awaiting_update(), [])

    def test_the_cloud_s_last_answer_is_dated(self):
        self.switch_on()
        t = time.time() - 5 * 24 * HOUR
        self.assertEqual(upstream.status()["cloud_last_seen"], 0)
        self.pass_(t)
        self.close_fixed(1, t + HOUR)
        self.read_verdicts(t + HOUR)
        self.assertGreater(upstream.status()["cloud_last_seen"], 0)


class TestTheOwnerIsAskedWhetherTheirFixHeld(_Case):
    """A `look` report has no fingerprint to stop, so once the house runs
    the release the fix shipped in, ONE question is due; its answer is a
    comment in the words the cloud reads, and No reopens the report."""

    def _file_look(self, t: float) -> int:
        rows = streams_mod.verbatim_rows("the brief never mentions the boiler")
        upstream.ingest("look", rows, diagnostics(), NAMES, now=t)
        upstream.send_due(now=t)
        return len(self.gh.issues)

    def test_due_only_once_the_fix_is_installed_and_once_per_fix(self):
        self.switch_on()
        t = time.time() - 5 * 24 * HOUR
        n = self._file_look(t)
        self.close_fixed(n, t + HOUR, "2.17.2")
        self.read_verdicts(t + HOUR)  # still on 2.17.0
        data = upstream._load()
        self.assertEqual(verify.due(data["items"], data["version"], {}, set()), [])
        self.pass_(t + 3 * HOUR, version="2.17.2")
        data = upstream._load()
        [entry] = verify.due(data["items"], data["version"], {}, set())
        self.assertEqual(entry["issue"], n)
        state = verify.record_asked({}, entry["fp"], 1234, "2.17.2", t)
        self.assertEqual(verify.due(data["items"], data["version"], state, set()), [])
        # A fault stream's report is never asked about: its fingerprint answers.
        fault = next(e for e in data["items"].values() if e.get("stream") == "faults")
        fault.update(verdict="fixed", fixed_in="2.17.2")
        self.assertEqual([e["fp"] for e in verify.due(data["items"], "2.17.2", {}, set())],
                         [entry["fp"]])

    def test_the_question_names_the_release_and_the_request(self):
        row = verify.question_row({"fp": "a" * 16, "fixed_in": "2.17.2",
                                   "what": "the brief never mentions the boiler"})
        self.assertEqual(row["kind"], "question")
        self.assertEqual(row["source"], verify.SOURCE)
        self.assertIn("brAIn 2.17.2 was meant to fix this", row["claim"])
        self.assertIn("boiler", row["claim"])
        self.assertTrue(row["text"].startswith(verify.TEXT_PREFIX + "a" * 16))
        self.assertEqual(verify.fp_for_finding({}, {"text": row["text"]}), "a" * 16)

    def test_yes_confirms_on_the_issue_and_no_reopens_it_with_the_words(self):
        self.switch_on()
        t = time.time() - 5 * 24 * HOUR
        n = self._file_look(t)
        self.close_fixed(n, t + HOUR, "2.17.2")
        self.read_verdicts(t + HOUR, version="2.17.2")
        fp = next(e["fp"] for e in upstream._load()["items"].values() if e.get("issue") == n)
        self.assertTrue(upstream.owner_answer(fp, True, "", now=t + 4 * HOUR))
        self.pass_(t + 4 * HOUR, version="2.17.2")
        self.assertIn((n, "The owner confirms this is fixed on brAIn 2.17.2."),
                      self.gh.comments)
        self.assertEqual(self.gh.issues[n - 1]["state"], "closed")
        # Then No, with words naming the house: aliased on the way out.
        self.assertTrue(upstream.owner_answer(
            fp, False, "Still nothing about the boiler in Master Bedroom", now=t + 5 * HOUR))
        self.pass_(t + 5 * HOUR, version="2.17.2")
        said = [c for c in self.gh.comments if c[0] == n and c[1].startswith("Not fixed on brAIn 2.17.2")]
        self.assertEqual(len(said), 1)
        self.assertIn("boiler", said[0][1])
        self.assertNotIn("Master Bedroom", said[0][1])
        self.assertEqual(self.gh.issues[n - 1]["state"], "open")

    def test_an_unposted_answer_can_be_forgotten_and_a_posted_one_stands(self):
        self.switch_on()
        t = time.time() - 5 * 24 * HOUR
        n = self._file_look(t)
        fp = next(e["fp"] for e in upstream._load()["items"].values() if e.get("issue") == n)
        self.assertTrue(upstream.owner_answer(fp, True))
        self.assertTrue(upstream.forget_owner_answer(fp))
        self.pass_(t + HOUR)
        self.assertEqual([c for c in self.gh.comments if c[0] == n], [])
        self.assertTrue(upstream.owner_answer(fp, True))
        self.pass_(t + 2 * HOUR)
        self.assertFalse(upstream.forget_owner_answer(fp))
        state = verify.record_answer({fp: {"ts": 1, "at": 1, "fixed_in": "x"}}, fp, True, t)
        self.assertEqual(state[fp]["answer"], "held")
        self.assertEqual(verify.forget_answer(state, fp)[fp]["answer"], "")


class TestAFaultIssueCarriesItsEvidence(DevloopCase):
    def test_the_journal_rows_and_the_log_s_trouble_lines_ride_the_issue(self):
        diag = diagnostics()
        diag["journal"]["failures"] = [
            {"ts": int(time.time()) - 60, "source": "card", "outcome": "timeout",
             "error": "Kitchen card timed out after 480s", "extra": {"title": "Energy"}},
            {"ts": int(time.time()) - 30, "source": "card", "outcome": "crash",
             "error": "claude exited 1"},
        ]
        self.rows = [{"where": "Run (card)", "what": "Energy: ended timeout (2 times)",
                      "detail": "x"}]
        log_text = "\n".join([
            "INFO brain.panel: all quiet",
            f"ERROR brain.panel: Kitchen card timed out; token {TOKEN}",
            "Traceback (most recent call last):",
            '  File "server.py", line 12, in h_x',
            "TypeError: 'NoneType' object is not subscriptable",
        ])
        [row] = streams_mod.faults(diag, log_text)
        self.assertIn("Recent occurrences", row["body"])
        self.assertIn("card · timeout · Energy: Kitchen card timed out after 480s", row["body"])
        self.assertNotIn("claude exited 1", row["body"])  # a different outcome
        self.assertIn("TypeError", row["body"])
        self.assertNotIn("all quiet", row["body"])
        # The stream is pure and redaction is `compose`'s, once over the
        # whole issue: the credential's absence is asserted on what is SENT.

    def test_what_is_sent_is_aliased_and_carries_no_credential(self):
        self.switch_on()
        self._faults_rows = self.rows
        diag = diagnostics()
        diag["journal"]["failures"] = [
            {"ts": int(time.time()), "source": "card", "outcome": "timeout",
             "error": f"light.bedroom_lamp in Master Bedroom; {TOKEN}"}]
        upstream.reports.faults = lambda d: [
            {"where": "Run (card)", "what": "ended timeout", "detail": ""}]
        rows = streams_mod.faults(diag, f"ERROR light.bedroom_lamp failed {TOKEN}")
        upstream.ingest("faults", rows, diag, NAMES)
        upstream.send_due()
        body = self.gh.issues[0]["body"]
        self.assertIn("Recent occurrences", body)
        self.assertIn("Add-on log", body)
        for real in ("Master Bedroom", "light.bedroom_lamp", TOKEN):
            self.assertNotIn(real, body)


class TestTheOutcomesStream(DevloopCase):
    """The Resident's judgement, graded by the household, as one issue per
    lopsided scope — keyed, so it stays one issue and clears when a
    confirmed case ends the pattern."""

    REPORT = {"calibration_line": "Of the looks rated sure, 40% were confirmed.",
              "by_stage": {"look": {"rows": 10, "agreed": 3, "disagreed": 5}}}
    CANDS = [{"scope": "entity", "subject": "sensor.lounge_temp", "direction": "quieter",
              "counts": "4 of 5 it raised were marked not a problem",
              "whys": ["the lounge reads 0.5 above the band"],
              "notes": ["it's next to the Lounge radiator, that's normal"]},
             {"scope": "check", "subject": "check:dev.frozen", "direction": "louder",
              "counts": "3 of 4 it passed over turned out to matter",
              "whys": [], "notes": []}]

    def test_rows_are_keyed_on_the_scope_and_carry_the_evidence(self):
        rows = streams_mod.outcomes(self.REPORT, self.CANDS, "2.17.0")
        self.assertEqual([r["key"] for r in rows],
                         ["outcomes|entity|sensor.lounge_temp", "outcomes|check|check:dev.frozen"])
        self.assertEqual(rows[0]["what"], "too loud about sensor.lounge_temp")
        self.assertEqual(rows[1]["what"], "too quiet about check:dev.frozen")
        self.assertIn("radiator", rows[0]["body"])
        self.assertIn("Calibration", rows[0]["body"])
        self.assertEqual(rows[0]["impact"], {"wrong": 4, "confirmed": 1, "endings": 5})

    def test_what_leaves_is_aliased_and_the_stream_is_a_switch(self):
        self.assertIn("outcomes", devloop.STREAMS)
        self.assertFalse(devloop.DEFAULTS["streams"]["outcomes"])
        self.assertTrue(devloop.STREAMS["outcomes"]["clears"])
        self.switch_on()
        devloop.save_settings({"streams": {"outcomes": True}})
        rows = streams_mod.outcomes(self.REPORT, self.CANDS, "2.17.0")
        upstream.ingest("outcomes", rows, diagnostics(), NAMES)
        upstream.send_due()
        sent = json.dumps(self.gh.issues)
        self.assertNotIn("sensor.lounge_temp", sent)
        self.assertNotIn("Lounge", sent)
        self.assertIn("check:dev.frozen", sent)
        self.assertIn("devloop:outcomes", sent)

    def test_a_scope_no_longer_lopsided_is_told_not_seen_since(self):
        self.switch_on()
        devloop.save_settings({"streams": {"outcomes": True}})
        t = time.time() - 5 * 24 * HOUR
        rows = streams_mod.outcomes(self.REPORT, self.CANDS, "2.17.0")
        upstream.ingest("outcomes", rows, diagnostics(), NAMES, now=t)
        upstream.send_due(now=t)
        later = t + upstream.CLEAR_AFTER_S + HOUR
        upstream.ingest("outcomes", [], diagnostics(), NAMES, now=later)
        upstream.send_due(now=later)
        self.assertEqual(sum(1 for c in self.gh.comments
                             if c[1].startswith("Not seen since")), 2)


if __name__ == "__main__":
    unittest.main()
