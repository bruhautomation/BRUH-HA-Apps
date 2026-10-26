"""After an update, brAIn settles the "is this fixed?" questions it can.

An update fills Today with "Is this fixed now?" questions, and the owner
asked for the ones brAIn can answer itself to be closed without them. Three
outcomes, each driven through the real panel:

  * a report whose fingerprint the house watches, not seen since the fixed
    release was installed and looked for again since, is answered Yes
    through the same ending the owner's press takes — and the comment the
    send pass posts says brAIn checked, never that the owner confirmed;
  * a question about a fix that is no longer the fix (reopened, re-fixed in
    a newer release, gone from the queue) is withdrawn with nothing posted;
  * a request with no fingerprint, a fault seen again after the install, or
    a stream that has not looked since, is left for the person.

And the second half of the protocol: a checks pass re-runs a while after
an update, once, so findings left by the restart are cleared.
"""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_dispatch import DispatchCase  # noqa: E402

TOKEN = "github_pat_" + "Z9y8X7w6V5u4T3s2R1q0" * 2
DAY = 86400


class VerifyCase(DispatchCase):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.point("devloop", DATA_DIR=root / "devloop",
                   TOKEN_FILE=root / "secrets" / "devloop_github_token")
        dl = self.server.devloop
        dl.save_settings({"enabled": True, "repo": "me/reports", "review": False})
        dl.save_token(TOKEN)
        self.now = time.time()
        self.installed = self.now - 3 * 3600

    def seed(self, fp: str, **entry) -> None:
        dl = self.server.devloop
        data = dl.upstream._load()
        base = {"fp": fp, "stream": "faults", "state": "sent", "issue": 11,
                "where": "Checks", "what": "the porch check stops every evening",
                "verdict": "fixed", "fixed_in": "4.1.0",
                "closed_at": self.now - 2 * DAY, "version": "4.0.9",
                "first_seen": self.now - 9 * DAY,
                "last_seen": self.now - DAY, "seen": 6}
        base.update(entry)
        data["items"][fp] = base
        data["version"] = "4.1.0"
        data.setdefault("installed", {})["brAIn"] = {
            "4.0.9": self.now - 30 * DAY, "4.1.0": self.installed}
        data.setdefault("last_run", {})["faults"] = self.now - 600
        dl.upstream._save(data)

    def ask(self, fp: str) -> dict:
        """File the question the way the verify pass does."""
        dl, fs = self.server.devloop, self.server.findings_store
        entry = dl.upstream._load()["items"][fp]
        row = fs.add_case(dl.verify.question_row(entry), when=self.now - 3600)
        state = dl.verify.load()
        dl.verify.record_asked(state, fp, int(row["ts"]), str(entry["fixed_in"]),
                               self.now - 3600, text=str(row["text"]))
        dl.verify.save(state)
        return row

    def settle(self) -> dict:
        return asyncio.run(self.server._devloop_verify_settle(self.now))

    def live(self, row) -> bool:
        return self.server.findings_store.get(row["ts"]) is not None

    def owner(self, fp: str) -> dict:
        return self.server.devloop.upstream._load()["items"][fp].get("owner") or {}


class TestWhatBrainCanProve(VerifyCase):
    def test_a_fault_gone_since_the_install_is_answered_as_brains(self):
        fp = "aa11bb22cc33dd44"
        self.seed(fp)
        row = self.ask(fp)
        done = self.settle()
        self.assertEqual(done["answered"], 1)
        self.assertFalse(self.live(row), "the question is closed")
        owner = self.owner(fp)
        self.assertEqual(owner.get("verdict"), "held")
        self.assertEqual(owner.get("by"), "brain")
        self.assertIn("brAIn checked", owner.get("note", ""))
        state = self.server.devloop.verify.load()[fp]
        self.assertEqual((state["answer"], state["by"]), ("held", "brain"))

        # The comment the send pass posts says who answered.
        up = self.server.devloop.upstream
        posted = []
        with mock.patch.object(up.github, "comment",
                               lambda tok, repo, n, text, reopen=False:
                               posted.append((text, reopen)) or (True, "")):
            items = up._load()["items"]
            self.assertEqual(up._post_owner_answers(
                TOKEN, "me/reports", items, up.Aliases.load(), "4.1.0"), 1)
        [(text, reopen)] = posted
        self.assertTrue(text.startswith("brAIn checked on brAIn 4.1.0"), text)
        self.assertNotIn("owner confirms", text.lower())
        self.assertIn("Not answered by the owner", text)
        self.assertFalse(reopen)

    def test_the_owners_own_yes_still_says_the_owner_confirms(self):
        fp = "ab12ab12ab12ab12"
        self.seed(fp)
        self.server.devloop.upstream.owner_answer(fp, True, "")
        up = self.server.devloop.upstream
        posted = []
        with mock.patch.object(up.github, "comment",
                               lambda tok, repo, n, text, reopen=False:
                               posted.append(text) or (True, "")):
            up._post_owner_answers(TOKEN, "me/reports", up._load()["items"],
                                   up.Aliases.load(), "4.1.0")
        self.assertEqual(posted, ["The owner confirms this is fixed on brAIn 4.1.0."])

    def test_a_fault_seen_after_the_install_is_left_for_the_person(self):
        fp = "ee55ff66aa77bb88"
        self.seed(fp, last_seen=self.installed + 600)
        row = self.ask(fp)
        self.assertEqual(self.settle(), {"answered": 0, "withdrawn": 0})
        self.assertTrue(self.live(row))
        self.assertEqual(self.owner(fp), {})

    def test_nothing_looked_since_the_install_proves_nothing(self):
        fp = "1234abcd5678ef90"
        self.seed(fp)
        data = self.server.devloop.upstream._load()
        data["last_run"]["faults"] = self.installed - 60
        self.server.devloop.upstream._save(data)
        row = self.ask(fp)
        self.settle()
        self.assertTrue(self.live(row))

    def test_a_stream_switched_off_proves_nothing(self):
        fp = "0f0f0f0f0f0f0f0f"
        self.seed(fp)
        dl = self.server.devloop
        settings = dl.load_settings()
        settings["streams"]["faults"] = False
        dl.save_settings(settings)
        row = self.ask(fp)
        self.settle()
        self.assertTrue(self.live(row))

    def test_a_request_with_no_fingerprint_is_left_for_the_person(self):
        fp = "9a9a9a9a9a9a9a9a"
        self.seed(fp, stream="look", where="Looks",
                  what="the brief never mentions the boiler")
        row = self.ask(fp)
        self.settle()
        self.assertTrue(self.live(row))
        self.assertEqual(self.owner(fp), {})

    def test_an_unknown_install_time_proves_nothing(self):
        fp = "c0ffeec0ffeec0ff"
        self.seed(fp)
        data = self.server.devloop.upstream._load()
        data["installed"] = {}
        self.server.devloop.upstream._save(data)
        row = self.ask(fp)
        self.settle()
        self.assertTrue(self.live(row))


class TestWhatAnUpdateMadeMoot(VerifyCase):
    def test_a_reopened_report_withdraws_its_question_and_posts_nothing(self):
        fp = "1a2b3c4d5e6f7a8b"
        self.seed(fp, stream="look", verdict="open", closed_at=0)
        row = self.ask(fp)
        done = self.settle()
        self.assertEqual(done["withdrawn"], 1)
        self.assertFalse(self.live(row))
        self.assertEqual(self.owner(fp), {})
        self.assertEqual(self.server.devloop.verify.load()[fp]["answer"], "moot")

    def test_a_report_fixed_again_withdraws_the_older_question(self):
        fp = "8b7a6f5e4d3c2b1a"
        self.seed(fp, stream="unmet", fixed_in="4.0.5")
        row = self.ask(fp)
        data = self.server.devloop.upstream._load()
        data["items"][fp]["fixed_in"] = "4.1.0"
        self.server.devloop.upstream._save(data)
        self.settle()
        self.assertFalse(self.live(row))
        # ... and the newer fix is asked about on its own.
        self.assertEqual(asyncio.run(self.server._devloop_verify_pass(self.now)), 1)


class TestTheInstallIsRecorded(VerifyCase):
    def test_a_sweep_notes_when_a_release_was_first_seen(self):
        up = self.server.devloop.upstream
        diag = {"versions": {"addon": "5.0.1"}, "faults": []}
        up.ingest("faults", [], diag, {}, 1000.0)
        up.ingest("faults", [], diag, {}, 2000.0)
        self.assertEqual(up._load()["installed"]["brAIn"]["5.0.1"], 1000.0)
        self.assertEqual(up.installed_at(up._load(), "brAIn", "5.0.0"), 1000.0)
        self.assertIsNone(up.installed_at(up._load(), "brAIn", "5.0.2"))

    def test_another_addons_release_is_noted_under_its_own_name(self):
        up = self.server.devloop.upstream
        up.ingest("siblings", [], {"versions": {"addon": "5.0.1"}}, {}, 1500.0,
                  products={"GardenRX": "0.4.2"})
        self.assertEqual(up.installed_at(up._load(), "GardenRX", "0.4.0"), 1500.0)


class TestChecksRerunAfterAnUpdate(VerifyCase):
    def setUp(self):
        super().setUp()
        root = Path(self.tmp.name)
        self.sched = str(root / "schedule.json")
        patcher = mock.patch.object(self.server.schedule_store, "STORE", self.sched)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.calls = []

        async def fake_run(reason="schedule"):
            self.calls.append(reason)
            return {}
        p = mock.patch.object(self.server, "run_checks", fake_run)
        p.start()
        self.addCleanup(p.stop)
        self.server.UPDATE_STATE.update(started_at=self.now, done=False)
        self.addCleanup(self.server.UPDATE_STATE.update, done=True)

    def recheck(self, at):
        return asyncio.run(self.server._update_recheck(at))

    def test_an_update_reruns_the_checks_once_after_it_settles(self):
        self.server.schedule_store.set_text(self.server.UPDATE_VERSION_KEY, "0.0.1")
        self.assertFalse(self.recheck(self.now + 60), "too soon after the restart")
        self.assertEqual(self.calls, [])
        self.assertTrue(self.recheck(self.now + self.server.UPDATE_RECHECK_S + 1))
        self.assertEqual(self.calls, ["update"])
        self.assertFalse(self.recheck(self.now + 2 * self.server.UPDATE_RECHECK_S))
        self.assertEqual(self.calls, ["update"])
        self.assertEqual(self.server.schedule_store.get_text(
            self.server.UPDATE_VERSION_KEY), self.server.ADDON_VERSION)

    def test_the_same_release_reruns_nothing(self):
        self.server.schedule_store.set_text(self.server.UPDATE_VERSION_KEY,
                                            self.server.ADDON_VERSION)
        self.assertFalse(self.recheck(self.now + 10 * self.server.UPDATE_RECHECK_S))
        self.assertEqual(self.calls, [])

    def test_a_schedule_of_zero_is_respected(self):
        self.server.schedule_store.set_text(self.server.UPDATE_VERSION_KEY, "0.0.1")
        with mock.patch.object(self.server, "eff_checks_interval_hours", lambda: 0):
            self.assertFalse(self.recheck(self.now + 10 * self.server.UPDATE_RECHECK_S))
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
