"""A noise verdict silences a report for 90 days, not for ever (plan 0.5).

A declined, not-brAIn or duplicate verdict on a report from a stream that
writes its own sentences used to stand that fingerprint (and a Claude
stream's title) down for good, so one wrong decline silenced the house
permanently. Now it lasts `stand_down_days`; a recurrence after that is a
NEW issue that names the old one and says it was declined before. A
stand-down recorded before the change starts its days when first read.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import NAMES, DevloopCase, diagnostics, upstream  # noqa: E402

import atomic_write  # noqa: E402
import devloop  # noqa: E402
from devloop import blocks  # noqa: E402

DAY = 86400
GAP = {"where": "Gap: The brief ignores the boiler", "what": "The boiler is never in the brief",
       "detail": "", "body": "**Done when:** the brief names the boiler."}


class _Case(DevloopCase):
    def file(self, now: float):
        upstream.ingest("gaps", [dict(GAP)], diagnostics(), NAMES, now=now)
        upstream.send_due(now=now)

    def decline(self, number: int, at: float):
        self.gh.judge(number, "devloop:declined")
        self.gh.issues[number - 1]["closed_at"] = time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(at))


class TestTheDaysAreCounted(_Case):
    def test_the_setting_is_the_houses_own_and_defaults_to_ninety(self):
        self.assertEqual(devloop.load_settings()["stand_down_days"], 90)
        self.assertEqual(devloop.load_settings()["canary_window_hours"], 24)
        devloop.save_settings({"stand_down_days": 30, "house_login": "brain-house"})
        self.assertEqual(devloop.load_settings()["stand_down_days"], 30)
        self.assertEqual(devloop.load_settings()["house_login"], "brain-house")
        with self.assertRaises(ValueError):
            devloop.save_settings({"stand_down_days": 0})
        with self.assertRaises(ValueError):
            devloop.save_settings({"house_login": "not a login"})

    def test_inside_its_days_the_report_stays_silent(self):
        self.switch_on()
        t = time.time() - 30 * DAY
        self.file(t)
        self.decline(1, t + 60)
        self.file(t + 2 * 3600)          # the verdict is read back
        self.file(t + 20 * DAY)
        self.assertEqual(len(self.gh.issues), 1)
        self.assertEqual(upstream._load()["items"][next(iter(upstream._load()["items"]))]
                         ["state"], "sent")

    def test_the_first_date_is_kept_when_the_verdict_is_read_again(self):
        self.switch_on()
        t = time.time() - 30 * DAY
        self.file(t)
        self.decline(1, t + 60)
        self.file(t + 2 * 3600)
        first = {k: r["at"] for k, r in upstream._vload()["stood_down"].items()}
        self.file(t + 2 * 3600 + upstream.VERDICT_INTERVAL_S + 60)
        again = {k: r["at"] for k, r in upstream._vload()["stood_down"].items()}
        self.assertTrue(first)
        self.assertEqual(first, again, "restamped every hour, 90 days would never end")

    def test_after_its_days_a_recurrence_is_a_new_issue_naming_the_old(self):
        self.switch_on()
        t = time.time() - 120 * DAY
        self.file(t)
        self.decline(1, t + 60)
        self.file(t + 2 * 3600)
        self.file(t + 95 * DAY)
        self.assertEqual(len(self.gh.issues), 2, "filed again, as a new issue")
        new = self.gh.issues[1]
        self.assertIn("**Filed again:** #1 was closed as declined", new["body"])
        self.assertEqual(self.gh.issues[0]["state"], "closed", "the old one untouched")
        self.assertEqual([c for c in self.gh.comments if c[0] == 1], [])
        obj = blocks.parse_block("devloop", new["body"])
        self.assertEqual(obj["stream"], "gaps")
        self.assertIn(obj["fp"], upstream._vload()["refiled"])
        # It is a report again: its new verdict decides from here.
        self.decline(2, t + 95 * DAY + 60)
        self.file(t + 95 * DAY + 2 * 3600)
        self.file(t + 100 * DAY)
        self.assertEqual(len(self.gh.issues), 2)

    def test_a_shorter_setting_ends_it_sooner(self):
        self.switch_on()
        devloop.save_settings({"stand_down_days": 10})
        t = time.time() - 30 * DAY
        self.file(t)
        self.decline(1, t + 60)
        self.file(t + 2 * 3600)
        self.file(t + 11 * DAY)
        self.assertEqual(len(self.gh.issues), 2)


class TestOldStandDownsAreMigrated(_Case):
    def test_an_undated_stand_down_starts_its_days_when_first_read(self):
        fp = upstream.fingerprint(GAP["where"], GAP["what"])
        atomic_write.write_json(upstream._verdict_file(), {"stood_down": {
            fp: {"fp": fp, "stream": "gaps", "verdict": "declined", "issue": 4}}})
        before = time.time()
        row = upstream._vload()["stood_down"][fp]
        self.assertGreaterEqual(row["at"], before)
        live = upstream.live_stood(upstream._vload()["stood_down"], time.time() + 89 * DAY)
        self.assertIn(fp, live)
        self.assertEqual(upstream.live_stood(upstream._vload()["stood_down"],
                                             time.time() + 91 * DAY), {})

    def test_a_dated_one_keeps_its_date(self):
        old = time.time() - 100 * DAY
        atomic_write.write_json(upstream._verdict_file(), {"stood_down": {
            "x": {"fp": "x", "stream": "gaps", "verdict": "declined", "at": old}}})
        self.assertEqual(upstream._vload()["stood_down"]["x"]["at"], old)
        self.assertEqual(upstream.live_stood(upstream._vload()["stood_down"], time.time()), {})


if __name__ == "__main__":
    unittest.main()


class TestTheDefaultsStayDefaults(DevloopCase):
    def test_a_first_save_does_not_change_the_defaults(self):
        before = devloop.DEFAULTS["streams"]["corpus"]
        devloop.save_settings({"streams": {"corpus": not before}})
        self.assertEqual(devloop.DEFAULTS["streams"]["corpus"], before,
                         "the first save wrote through to DEFAULTS")
