"""After an update, the "is this fixed?" questions an update made moot go.

An update fills Today with "Is this fixed now?" questions, and the owner
asked for the ones that no longer mean anything to be closed without them.
Two outcomes, each driven through the real panel:

  * a question about a fix that is no longer the fix (reopened, re-fixed in
    a newer release, gone from the queue) is withdrawn with nothing posted;
  * a question about a fix that still stands is left for the person, and
    brAIn never answers it for them.

The questions are only ever about the owner's own requests (`look`) and
what the chat could not do (`unmet`): neither has a fingerprint to stop,
so nothing brAIn measures can prove one. A fault proves itself on its own
issue (upstream's "Held"), and no question is ever asked about one. The
settle pass once answered Yes "for brAIn" on a fault question the ask pass
never files; that branch is gone, and these tests hold that no question is
asked about a fault and none is answered for the owner.

And the second half of the protocol: a checks pass re-runs a while after
an update, once, so findings left by the restart are cleared.
"""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path
import unittest.mock as mock

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

    def seed(self, fp: str, **entry) -> None:
        dl = self.server.devloop
        data = dl.upstream._load()
        # The shape the ask pass asks about: the owner's own request.
        base = {"fp": fp, "stream": "look", "state": "sent", "issue": 11,
                "where": "Fix: Porch check", "what": "the porch check stops every evening",
                "verdict": "fixed", "fixed_in": "4.1.0",
                "closed_at": self.now - 2 * DAY, "version": "4.0.9",
                "first_seen": self.now - 9 * DAY,
                "last_seen": self.now - DAY, "seen": 6}
        base.update(entry)
        data["items"][fp] = base
        data["version"] = "4.1.0"
        data.setdefault("last_run", {})[base["stream"]] = self.now - 600
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


class TestBrainNeverAnswersForTheOwner(VerifyCase):
    def test_no_question_is_ever_asked_about_a_fault(self):
        # A fault's fix is said on its own issue ("Held"); the settle pass
        # once answered fault questions "for brAIn", and none is ever asked.
        fp = "aa11bb22cc33dd44"
        self.seed(fp, stream="faults", where="Checks")
        self.assertEqual(asyncio.run(self.server._devloop_verify_pass(self.now)), 0)
        self.assertEqual(self.server.devloop.verify.load(), {})

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

    def test_a_request_not_seen_since_the_install_is_still_the_owners(self):
        # Nobody asking again is not evidence that a request was met.
        fp = "ee55ff66aa77bb88"
        self.seed(fp)
        row = self.ask(fp)
        self.assertEqual(self.settle(), {"withdrawn": 0})
        self.assertTrue(self.live(row))
        self.assertEqual(self.owner(fp), {})
        self.assertEqual(self.server.devloop.verify.load()[fp]["answer"], "")

    def test_nothing_is_posted_until_the_owner_answers(self):
        fp = "1234abcd5678ef90"
        self.seed(fp)
        self.ask(fp)
        self.settle()
        up = self.server.devloop.upstream
        posted = []
        with mock.patch.object(up.github, "comment",
                               lambda tok, repo, n, text, reopen=False:
                               posted.append(text) or (True, "")):
            self.assertEqual(up._post_owner_answers(
                TOKEN, "me/reports", up._load()["items"], up.Aliases.load(), "4.1.0"), 0)
        self.assertEqual(posted, [])

    def test_an_unmet_request_is_left_for_the_person(self):
        fp = "0f0f0f0f0f0f0f0f"
        self.seed(fp, stream="unmet", where="Chat",
                  what="brAIn could not turn the oven off")
        row = self.ask(fp)
        self.settle()
        self.assertTrue(self.live(row))
        self.assertEqual(self.owner(fp), {})

    def test_a_request_with_no_fingerprint_is_left_for_the_person(self):
        fp = "9a9a9a9a9a9a9a9a"
        self.seed(fp, stream="look", where="Looks",
                  what="the brief never mentions the boiler")
        row = self.ask(fp)
        self.settle()
        self.assertTrue(self.live(row))
        self.assertEqual(self.owner(fp), {})

    def test_a_report_gone_from_the_queue_withdraws_its_question(self):
        fp = "c0ffeec0ffeec0ff"
        self.seed(fp)
        row = self.ask(fp)
        data = self.server.devloop.upstream._load()
        del data["items"][fp]
        self.server.devloop.upstream._save(data)
        self.assertEqual(self.settle(), {"withdrawn": 1})
        self.assertFalse(self.live(row))
        self.assertEqual(self.server.devloop.verify.load()[fp]["answer"], "moot")


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


class TestTheReleaseIsRecorded(VerifyCase):
    def test_a_sweep_records_the_release_the_house_runs(self):
        up = self.server.devloop.upstream
        diag = {"versions": {"addon": "5.0.1"}, "faults": []}
        up.ingest("faults", [], diag, {}, 1000.0)
        self.assertEqual(up._load()["version"], "5.0.1")
        self.assertEqual(up.running_for({"fixed_in": "5.0.0"}, up._load()["version"],
                                        up._load().get("products")), "5.0.1")

    def test_another_addons_release_is_recorded_under_its_own_name(self):
        up = self.server.devloop.upstream
        up.ingest("siblings", [], {"versions": {"addon": "5.0.1"}}, {}, 1500.0,
                  products={"GardenRX": "0.4.2"})
        data = up._load()
        self.assertEqual(data["products"]["GardenRX"], "0.4.2")
        self.assertEqual(up.running_for({"product": "GardenRX"}, data["version"],
                                        data["products"]), "0.4.2")


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
