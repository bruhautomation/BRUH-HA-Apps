#!/usr/bin/env python3
"""Release on the scorecard (self-learning plan 1.5).

Every new ending carries the brAIn release it was given under, so "worse
since 4.x.y" is a query over the settled ledger rather than prose: the
devloop's canary asks `scorecard_by_release()` whether a producer's
right-share dropped under a new release. An ending written before the field
existed — or moved in from somewhere it was not answered under — is
`unknown`, and is never counted as the release running now.

Driven through the real writers over temporary stores.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
import unittest.mock as mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store  # noqa: E402

SOURCE = "check:dev.frozen"
OTHER = "check:battery.low"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "findings-settled.json"
        findings_store.STATE_FILE = root / "findings-state.json"
        self.n = 0

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()

    def end(self, kind: str, release: str, source: str = SOURCE) -> dict:
        self.n += 1
        with mock.patch.dict(os.environ, {"ADDON_VERSION": release}):
            rows = findings_store.add_many([{
                "text": f"Sensor number {self.n} has read the same value for a week",
                "severity": "warning", "source": source}])
            return findings_store.settle_and_clear(rows[0]["ts"], kind)

    def ledger(self) -> list[dict]:
        return json.loads(findings_store.SETTLED_FILE.read_text())["settled"]


class TestEveryEndingSaysItsRelease(Case):
    def test_the_ledger_row_and_the_ending_carry_it(self):
        ended = self.end("ignored", "4.2.0")
        self.assertEqual(ended["release"], "4.2.0")
        self.assertEqual(self.ledger()[-1]["release"], "4.2.0")

    def test_no_version_writes_none(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("ADDON_VERSION", None)
            rows = findings_store.add_many([{"text": "A thing that is wrong somewhere",
                                             "severity": "warning", "source": SOURCE}])
            ended = findings_store.settle_and_clear(rows[0]["ts"], "fixed")
        self.assertNotIn("release", ended)
        self.assertNotIn("release", self.ledger()[-1])

    def test_a_remembered_answer_carries_it(self):
        with mock.patch.dict(os.environ, {"ADDON_VERSION": "4.3.1"}):
            findings_store.remember_answer("k", "Water the plants", "fixed",
                                           source=SOURCE)
        self.assertEqual(self.ledger()[-1]["release"], "4.3.1")

    def test_a_migrated_old_answer_is_unknown_not_now(self):
        findings_store.FINDINGS_FILE.write_text(json.dumps({"findings": [{
            "ts": 5, "text": "An old dismissal from long ago", "status": "ignored",
            "severity": "warning", "source": SOURCE, "settled_at": 4}]}))
        with mock.patch.dict(os.environ, {"ADDON_VERSION": "4.4.0"}):
            findings_store.migrate_settled()
        self.assertNotIn("release", self.ledger()[-1])

    def test_an_imported_ledger_keeps_its_own_or_none(self):
        with mock.patch.dict(os.environ, {"ADDON_VERSION": "4.4.0"}):
            findings_store.merge_settled([
                {"key": "a", "text": "a", "kind": "fixed", "release": "3.9.0"},
                {"key": "b", "text": "b", "kind": "fixed"}])
        rows = {r["key"]: r for r in self.ledger()}
        self.assertEqual(rows["a"]["release"], "3.9.0")
        self.assertNotIn("release", rows["b"])


class TestTheQueries(Case):
    def setUp(self):
        super().setUp()
        # Rows from before the field existed.
        findings_store.SETTLED_FILE.write_text(json.dumps({"settled": [
            {"key": "old1", "text": "old one", "kind": "fixed", "ts": 1, "source": SOURCE},
            {"key": "old2", "text": "old two", "kind": "ignored", "ts": 2, "source": SOURCE},
            {"key": "old3", "text": "old three", "kind": "not_applicable", "ts": 3,
             "source": SOURCE}]}))
        self.end("fixed", "4.1.0")
        self.end("accepted", "4.1.0")
        self.end("ignored", "4.2.0")
        self.end("ignored", "4.2.0")
        self.end("fixed", "4.2.0")
        self.end("fixed", "4.2.0", source=OTHER)
        self.end("not_applicable", "4.2.0")

    def test_by_release_is_the_canary_s_shape(self):
        out = findings_store.scorecard_by_release()
        self.assertEqual(out["4.1.0"], {SOURCE: {"right": 2, "wrong": 0, "total": 2}})
        self.assertEqual(out["4.2.0"], {
            SOURCE: {"right": 1, "wrong": 2, "total": 3},
            OTHER: {"right": 1, "wrong": 0, "total": 1}})
        self.assertEqual(out[findings_store.UNKNOWN_RELEASE],
                         {SOURCE: {"right": 1, "wrong": 1, "total": 2}})

    def test_old_rows_are_never_the_current_release(self):
        with mock.patch.dict(os.environ, {"ADDON_VERSION": "4.2.0"}):
            [row] = [r for r in findings_store.scorecard(release="4.2.0")
                     if r["source"] == SOURCE]
            self.assertEqual((row["confirmed"], row["wrong"], row["total"]), (1, 2, 3))
            self.assertEqual(row["release"], "4.2.0")
            [old] = findings_store.scorecard(release=findings_store.UNKNOWN_RELEASE)
            self.assertEqual((old["confirmed"], old["wrong"]), (1, 1))

    def test_every_release_is_the_old_scorecard(self):
        rows = {r["source"]: r for r in findings_store.scorecard()}
        self.assertEqual((rows[SOURCE]["confirmed"], rows[SOURCE]["wrong"]), (4, 3))
        self.assertIsNone(rows[SOURCE]["release"])
        self.assertEqual(findings_store.scorecard(release="9.9.9"), [])


if __name__ == "__main__":
    unittest.main()
