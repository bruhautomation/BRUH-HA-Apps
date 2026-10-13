"""A "Back again" is a sighting after the close, never a version re-stamp.

The house devloop re-stamps an entry's version on every sweep, so a closed
issue whose last sighting PREDATES its close was reopened with "Back again"
after every upgrade. Only a sighting later than the close reopens it.
"""
import os
import sys
import unittest
import unittest.mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "brain", "panel"))

from devloop import upstream  # noqa: E402

CLOSED_AT = "2026-10-13T05:35:00Z"
CLOSED_TS = 1791869700.0  # 2026-10-13T05:35:00Z


class TestBackAgainNeedsASightingAfterTheClose(unittest.TestCase):

    def _run(self, last_seen: float, state: str = "closed") -> tuple:
        comments = []
        issue = {"state": state, "closed_at": CLOSED_AT if state == "closed" else None}
        entry = {"issue": 7, "last_seen": last_seen, "version": "2.18.32",
                 "noted_version": "2.18.31", "stream": "faults"}
        with unittest.mock.patch.object(upstream.github, "get_issue",
                                        return_value=(issue, "")), \
             unittest.mock.patch.object(upstream.github, "comment",
                                        side_effect=lambda *a, **k: comments.append((a, k)) or (True, "")), \
             unittest.mock.patch.object(upstream, "stream_on", return_value=True):
            sent = upstream._follow_up("t", "o/r", entry, now=last_seen + 60)
        return sent, comments, entry

    def test_the_constant_is_the_close(self):
        self.assertTrue(upstream._seen_before_close(
            {"last_seen": CLOSED_TS}, {"closed_at": CLOSED_AT}))

    def test_a_sighting_before_the_close_is_a_restamp(self):
        sent, comments, entry = self._run(CLOSED_TS - 4 * 3600)
        self.assertFalse(sent)
        self.assertEqual(comments, [])
        self.assertEqual(entry["noted_version"], "2.18.32")
        self.assertFalse(entry["returned"])

    def test_a_sighting_after_the_close_reopens(self):
        sent, comments, _ = self._run(CLOSED_TS + 3600)
        self.assertTrue(sent)
        self.assertEqual(len(comments), 1)
        args, kwargs = comments[0]
        self.assertIn("Back again", args[3])
        self.assertTrue(kwargs.get("reopen"))

    def test_an_unreadable_close_keeps_the_old_answer(self):
        self.assertFalse(upstream._seen_before_close(
            {"last_seen": 1.0}, {"closed_at": "not a date"}))

    def test_an_open_issue_still_says_still_happening(self):
        sent, comments, _ = self._run(CLOSED_TS, state="open")
        self.assertTrue(sent)
        self.assertIn("Still happening", comments[0][0][3])


if __name__ == "__main__":
    unittest.main()
