""""Is this fixed now?" waits for the fix to be running, and asks once per
release and area (#535).

Seen on a house: the add-on had deployed a new release whose fixes lived in
its Home Assistant integration, Home Assistant had not restarted and was
still running the integration from three releases before — and Today held
five "Is this fixed now?" cards about the new release, several about the
same part of brAIn. The owner could not answer any of them: the code that
would fix them was not running yet.

Two rules, both in `devloop/verify.py`, both driven here over invented
reports:

* the release a fix is checked against is the one RUNNING — brAIn's is the
  older of the add-on's and the integration Home Assistant has loaded, and
  "could not tell" while a restart is owed with no loaded version known;
* the fixes one release made to one area are ONE question that lists them.
"""
from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from devloop import verify  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_dispatch import DispatchCase  # noqa: E402


def report(i: int, fixed_in: str, where: str, what: str) -> dict:
    return {"fp": f"{i:016x}", "stream": "look", "verdict": "fixed",
            "fixed_in": fixed_in, "closed_at": 1000 + i, "where": where,
            "what": what}


# Nine reports the owner filed, fixed across two releases and two places.
REPORTS = [
    report(1, "3.1.4", "Fix: the porch card shows yesterday's weather",
           "the porch card shows yesterday's weather"),
    report(2, "3.1.4", "Fix: the brief skips the garage",
           "the brief skips the garage"),
    report(3, "3.1.4", "Chat", "the chat forgets the last question"),
    report(4, "3.1.4", "Chat", "the chat repeats its answer twice"),
    report(5, "3.1.5", "Fix: the heating card counts minutes as hours",
           "the heating card counts minutes as hours"),
    report(6, "3.1.5", "Fix: the heating card counts minutes as hours",
           "the heating card counts minutes as hours"),
    report(7, "3.1.5", "Fix: the energy tile has no unit",
           "the energy tile has no unit"),
    report(8, "3.1.5", "Chat", "the chat's send button is hidden on a phone"),
    report(9, "3.1.5", "Chat", "the chat scrolls back to the top"),
]


def replay(running: str, integration: dict | None = None) -> list[dict]:
    """Every pass the server would make until nothing is due: the rows."""
    items = {r["fp"]: dict(r) for r in REPORTS}
    live = verify.live_version(running, integration)
    state: dict = {}
    rows: list[dict] = []
    ts = 100
    for _ in range(20):
        groups = verify.due_groups(items, live, state, set())
        if not groups:
            break
        for group in groups:
            ts += 1
            row = verify.group_row(group)
            rows.append(row)
            for entry in group:
                verify.record_asked(state, entry["fp"], ts, entry["fixed_in"],
                                    0, text=row["text"])
    return rows


class TestWaitForTheRunningRelease(unittest.TestCase):
    def test_none_while_home_assistant_runs_the_older_integration(self):
        rows = replay("3.1.5", {"loaded": "3.1.2", "required": "3.1.5",
                                "restart_pending": True})
        self.assertEqual(rows, [])

    def test_none_while_a_restart_is_owed_and_nothing_says_what_runs(self):
        rows = replay("3.1.5", {"loaded": None, "required": "3.1.5",
                                "restart_pending": True})
        self.assertEqual(rows, [])

    def test_only_the_release_actually_loaded_is_asked_about(self):
        rows = replay("3.1.5", {"loaded": "3.1.4", "required": "3.1.5",
                                "restart_pending": True})
        self.assertEqual(len(rows), 2)
        self.assertTrue(all("3.1.4" in r["text"] for r in rows))

    def test_live_version(self):
        self.assertEqual(verify.live_version("3.1.5", None), "3.1.5")
        self.assertEqual(verify.live_version(
            "3.1.5", {"loaded": "3.1.5", "restart_pending": False}), "3.1.5")
        self.assertEqual(verify.live_version(
            "3.1.5", {"loaded": "3.1.3", "restart_pending": True}), "3.1.3")
        self.assertEqual(verify.live_version(
            "3.1.5", {"loaded": None, "restart_pending": True}), "")


class TestOneQuestionPerReleaseAndArea(unittest.TestCase):
    def test_nine_reports_are_four_questions_after_the_restart(self):
        rows = replay("3.1.5", {"loaded": "3.1.5", "restart_pending": False})
        self.assertEqual(len(rows), 4)
        self.assertEqual(len({r["text"] for r in rows}), 4)

    def test_a_merged_question_lists_what_changed(self):
        rows = replay("3.1.5", {"loaded": "3.1.5", "restart_pending": False})
        chat = next(r for r in rows if "3.1.5" in r["text"]
                    and "Chat" in r["claim"])
        self.assertIn("send button", chat["detail"])
        self.assertIn("scrolls back", chat["detail"])
        # The same change reported twice is listed once.
        heating = next(r for r in rows if "3.1.5" in r["text"]
                       and "Chat" not in r["claim"])
        self.assertEqual(heating["detail"].count("minutes as hours"), 1)
        self.assertIn("no unit", heating["detail"])
        for r in rows:
            self.assertEqual(r["kind"], "question")
            self.assertLessEqual(len(r["text"]), verify.TEXT_CHARS)

    def test_one_report_is_the_question_it_always_was(self):
        [entry] = [r for r in REPORTS if r["fp"] == f"{1:016x}"]
        self.assertEqual(verify.group_row([entry]), verify.question_row(entry))

    def test_every_report_in_a_question_is_found_by_its_row(self):
        items = {r["fp"]: dict(r) for r in REPORTS}
        [group] = verify.due_groups(items, "3.1.4", {}, set())
        state: dict = {}
        row = verify.group_row(group)
        for entry in group:
            verify.record_asked(state, entry["fp"], 55, "3.1.4", 0,
                                text=row["text"])
        self.assertEqual(sorted(verify.fps_for_finding(
            state, {"ts": 55, "text": row["text"]})),
            sorted(e["fp"] for e in group))


class TestThePanelWaitsForTheRestart(DispatchCase):
    """The real `_devloop_verify_pass`: no question while Home Assistant
    still runs an older integration; one per area once it restarts."""

    def setUp(self):
        super().setUp()
        srv = self.srv = self.server
        root = self.root = Path(self.tmp.name)
        self.point("devloop", DATA_DIR=root / "devloop",
                   TOKEN_FILE=root / "secrets" / "token")
        for attr, name in (("INTEGRATION_LOADED_FILE", "loaded.json"),
                           ("RESTART_MARKER_FILE", "restart_required")):
            old = getattr(srv, attr)
            setattr(srv, attr, root / name)
            self.addCleanup(setattr, srv, attr, old)
        srv.devloop.save_settings({"enabled": True, "repo": "me/reports",
                                   "review": False})
        items = {r["fp"]: {**r, "state": "sent", "issue": i + 1,
                           "closed_at": time.time() - 3600 + i}
                 for i, r in enumerate(REPORTS)}
        srv.devloop.upstream._save({"version": "3.1.5", "items": items})

    def restart_owed(self, loaded: str) -> None:
        (self.root / "loaded.json").write_text(
            json.dumps({"version": loaded}), encoding="utf-8")
        (self.root / "restart_required").write_text(
            json.dumps({"required_version": "3.1.5"}), encoding="utf-8")

    def questions(self) -> list[dict]:
        return [f for f in self.srv.findings_store.list_all()
                if f.get("source") == self.srv.devloop.verify.SOURCE]

    def drain(self) -> int:
        total = 0
        for _ in range(10):
            n = asyncio.run(self.srv._devloop_verify_pass())
            if not n:
                break
            total += n
        return total

    def test_nothing_is_asked_before_the_restart_and_four_after(self):
        self.restart_owed("3.1.2")
        self.assertEqual(self.drain(), 0)
        self.assertEqual(self.questions(), [])
        self.restart_owed("3.1.5")
        (self.root / "restart_required").unlink()
        self.assertEqual(self.drain(), 4)
        self.assertEqual(len(self.questions()), 4)

    def test_one_yes_answers_every_report_the_question_covers(self):
        (self.root / "loaded.json").write_text(
            json.dumps({"version": "3.1.5"}), encoding="utf-8")
        self.assertEqual(asyncio.run(self.srv._devloop_verify_pass()), 1)
        [q] = self.questions()
        asyncio.run(self.srv._end_devloop_verify(
            q, {"label": "accepted"}, "all good"))
        items = self.srv.devloop.upstream._load()["items"]
        state = self.srv.devloop.verify.load()
        covered = [fp for fp, rec in state.items() if rec.get("ts") == q["ts"]]
        self.assertEqual(len(covered), 2)
        for fp in covered:
            self.assertTrue(items[fp].get("owner"), fp)
            self.assertEqual(state[fp]["answer"], "held")


if __name__ == "__main__":
    unittest.main()
