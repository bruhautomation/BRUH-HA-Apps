#!/usr/bin/env python3
"""Capture — the prompt, the reply, and the ending that grades them.

The feature exists because BRight's `detect_hits` returned zero results
for its entire life with a green suite behind it: the only fixture was
synthetic. brAIn's analyst prompts have the same exposure, and a captured
run with a person's ending on it is the one thing that can measure a
prompt change on a house nobody wrote a fixture for.

So the tests here are about the four claims the feature makes:

  * nothing is recorded unless somebody switched it on;
  * what IS recorded has had anything credential-shaped taken out of it
    on the way in, by the same rules `brain-report.sh` applies — driven
    against the real shell function on the same fixture strings, because
    two implementations of "what a credential looks like" is one too many
    and the one nobody runs is the one that drifts;
  * an ending given on the Findings tab lands on the capture of the run
    that raised it, through `_end_finding`, which is the one door;
  * a run id off the wire is not a filename.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import capture  # noqa: E402
import findings_store  # noqa: E402
import journal  # noqa: E402


# The strings both redactions have to handle. Kept in one list precisely
# so neither side can quietly stop covering one.
SECRETS = [
    ("sk-ant-oat01-AAAABBBBCCCCDDDDEEEEFFFF", "an OAuth token"),
    ("Bearer abcdefghijklmnop.qrstuv-wxyz", "an Authorization header"),
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
     + ".dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk", "a JWT"),
]


class CaptureCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self._old = (capture.CAPTURE_DIR, capture.EXPORT_DIR)
        capture.CAPTURE_DIR = self.base / "data" / "capture"
        capture.EXPORT_DIR = self.base / "share" / "brain" / "corpus"
        (self.base / "share").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        capture.CAPTURE_DIR, capture.EXPORT_DIR = self._old
        self.tmp.cleanup()

    def a_run(self, run_id="11111111-2222-3333-4444-555555555555", **over):
        fields = dict(source="card", category="automations", model="a-model",
                      gather_mode="search", prompt_chars=1449,
                      bundle={"domains": {"light": 12}},
                      reply={"findings": [{"text": "A dead reference"}]},
                      tokens={"total": 31000})
        fields.update(over)
        return capture.record(run_id, **fields)


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

class TestRedaction(CaptureCase):
    """The Python and the shell, against the same strings."""

    SHELL = BASE_DIR / "brain" / "scripts" / "brain-report.sh"

    def shell_redact(self, text: str) -> str:
        """Run `brain-report.sh`'s own `redact()` over one file.

        Lifted out of the real script rather than reimplemented — a copy
        of a regex in a test proves the copy works.
        """
        src = self.SHELL.read_text(encoding="utf-8")
        start = src.index("redact() {")
        end = src.index("\n}\n", start) + 3
        block = src[start:end]
        target = self.base / "sample.txt"
        target.write_text(text, encoding="utf-8")
        proc = subprocess.run(
            ["bash", "-c", block + f'\nredact "{target}"\n'],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return target.read_text(encoding="utf-8")

    def test_both_implementations_remove_the_same_secrets(self):
        for secret, what in SECRETS:
            text = f"the log said: {secret} — and then it stopped"
            with self.subTest(what):
                mine = capture.redact(text)
                theirs = self.shell_redact(text)
                self.assertNotIn(secret, mine, f"python kept {what}")
                self.assertNotIn(secret, theirs, f"the shell kept {what}")
                self.assertIn("[redacted]", mine)
                self.assertIn("[redacted]", theirs)

    def test_journal_scrub_agrees_with_capture_redact(self):
        """A third copy already existed. It has to cover the same set."""
        for secret, what in SECRETS:
            with self.subTest(what):
                self.assertNotIn(secret, journal.scrub(f"x {secret} y"))

    def test_a_secret_shaped_key_is_blanked_whatever_its_value_looks_like(self):
        """The shell does this one textually over the serialised JSON; here
        the object is still an object, so it is done structurally."""
        got = capture.redact({"access_token": "totally-ordinary-looking",
                              "nested": [{"api_key": "0123456789abcdef"}]})
        self.assertEqual(got["access_token"], "[redacted]")
        self.assertEqual(got["nested"][0]["api_key"], "[redacted]")

    def test_a_short_value_under_a_secret_shaped_key_survives(self):
        """`"value": "on"` is a setting, not a credential, and blanking it
        would make the entry unreadable for nothing. The shell's own rule
        is the same number."""
        self.assertEqual(capture.redact({"value": "on"})["value"], "on")

    def test_the_house_is_left_alone(self):
        house = {"e": "light.kitchen", "s": "on", "n": "Kitchen ceiling"}
        self.assertEqual(capture.redact(house), house)

    def test_redaction_happens_on_the_way_in(self):
        """Not at export. A redaction applied on the way OUT is one that
        never ran for the file somebody found by another route."""
        secret = SECRETS[0][0]
        self.a_run(bundle={"note": f"token {secret}"})
        raw = (capture.CAPTURE_DIR /
               "11111111-2222-3333-4444-555555555555.json").read_text()
        self.assertNotIn(secret, raw)
        self.assertIn("[redacted]", raw)

    def test_a_correction_is_redacted_too(self):
        """The note is the one field in the entry a person typed."""
        self.a_run()
        capture.add_label("11111111-2222-3333-4444-555555555555",
                          finding_key="k", verb="wrong",
                          note=f"my key is {SECRETS[0][0]} by the way")
        entry = capture.read("11111111-2222-3333-4444-555555555555")
        self.assertNotIn(SECRETS[0][0], json.dumps(entry))


# ---------------------------------------------------------------------------
# Writing, capping, reading
# ---------------------------------------------------------------------------

class TestWhatIsWritten(CaptureCase):
    def test_a_capture_carries_the_prompt_the_reply_and_no_labels_yet(self):
        path = self.a_run()
        entry = json.loads(Path(path).read_text(encoding="utf-8"))
        self.assertEqual(entry["schema"], capture.SCHEMA)
        self.assertEqual(entry["kind"], "analyst")
        self.assertEqual(entry["gather_mode"], "search")
        self.assertEqual(entry["bundle"], {"domains": {"light": 12}})
        self.assertEqual(entry["labels"], [])
        self.assertEqual(entry["tokens"]["total"], 31000)

    def test_the_cap_takes_the_oldest_first(self):
        now = time.time()
        for i in range(10):
            path = self.a_run(f"run-{i:04d}")
            # mtime is what `prune` orders by: a run id is a uuid and
            # sorts by nothing.
            os.utime(path, (now + i, now + i))
        self.assertEqual(capture.prune(keep=4), 6)
        left = sorted(p.stem for p in capture.CAPTURE_DIR.glob("*.json"))
        self.assertEqual(left, ["run-0006", "run-0007", "run-0008",
                                "run-0009"])

    def test_recording_enforces_the_cap_without_being_asked(self):
        """The prune is inside `record`, not on a timer: an uncapped
        directory on an SD card is a different bug report."""
        old = capture.CAPTURE_MAX_FILES
        capture.CAPTURE_MAX_FILES = 3
        try:
            for i in range(8):
                self.a_run(f"run-{i:04d}")
        finally:
            capture.CAPTURE_MAX_FILES = old
        self.assertEqual(len(list(capture.CAPTURE_DIR.glob("*.json"))), 3)

    def test_a_listing_row_says_how_many_endings_have_labelled_it(self):
        self.a_run("run-a")
        self.a_run("run-b")
        capture.add_label("run-b", finding_key="k1", verb="done")
        rows = {r["run_id"]: r for r in capture.listing()}
        self.assertEqual(rows["run-a"]["labels"], 0)
        self.assertEqual(rows["run-b"]["labels"], 1)
        self.assertEqual(rows["run-b"]["findings"], 1)

    def test_stats_are_numbers_and_never_the_captures(self):
        self.a_run("run-a")
        capture.add_label("run-a", finding_key="k", verb="wrong")
        stats = capture.stats(True)
        self.assertEqual(stats, {"enabled": True, "files": 1, "labelled": 1,
                                 "bytes": stats["bytes"],
                                 "max_files": capture.CAPTURE_MAX_FILES})
        self.assertNotIn("bundle", json.dumps(stats))

    def test_one_finding_is_labelled_once_however_many_times_it_is_ended(self):
        """A request applied twice is harmless by design (see
        `finding_requests`), so the label has to be idempotent too or the
        same ending is counted as two."""
        self.a_run("run-a")
        capture.add_label("run-a", finding_key="k", verb="done")
        capture.add_label("run-a", finding_key="k", verb="wrong")
        labels = capture.read("run-a")["labels"]
        self.assertEqual(len(labels), 1)
        self.assertEqual(labels[0]["verb"], "wrong")

    def test_labelling_a_run_that_was_never_captured_is_not_an_error(self):
        self.assertFalse(capture.add_label("run-nope", finding_key="k",
                                           verb="done"))

    def test_a_run_id_the_cli_did_not_give_is_no_run_id(self):
        self.assertEqual(capture.run_id_from({}), "")
        self.assertEqual(capture.run_id_from({"session_id": "../etc/x"}), "")
        self.assertEqual(capture.run_id_from({"session_id": "abc-123"}),
                         "abc-123")


# ---------------------------------------------------------------------------
# The barrier
# ---------------------------------------------------------------------------

class TestARunIdIsNotAPath(CaptureCase):
    BAD = ("../escape", "a/b", "/etc/passwd", "..", ".", "", "x" * 200,
           "run\x00id", "./x")

    def test_nothing_that_is_not_a_run_id_becomes_a_filename(self):
        for bad in self.BAD:
            with self.subTest(bad):
                self.assertIsNone(capture.path_for(bad))
                self.assertFalse(capture.safe_id(bad))

    def test_a_traversal_id_writes_reads_exports_and_deletes_nothing(self):
        outside = self.base / "escape.json"
        for bad in self.BAD:
            with self.subTest(bad):
                self.assertIsNone(self.a_run(bad))
                self.assertIsNone(capture.read(bad))
                self.assertFalse(capture.delete(bad))
                _path, error = capture.export(bad)
                self.assertTrue(error)
        self.assertFalse(outside.exists())
        self.assertFalse(any(self.base.glob("*.json")))

    def test_export_copies_and_does_not_move(self):
        self.a_run("run-a")
        path, error = capture.export("run-a")
        self.assertEqual(error, "")
        self.assertTrue(Path(path).is_file())
        # Exporting is not deleting: somebody who exported the wrong entry
        # must still be able to delete it from the list they exported from.
        self.assertIsNotNone(capture.read("run-a"))
        self.assertEqual(json.loads(Path(path).read_text())["run_id"], "run-a")

    def test_export_says_so_when_there_is_no_share_volume(self):
        capture.EXPORT_DIR = self.base / "nope" / "brain" / "corpus"
        self.a_run("run-a")
        path, error = capture.export("run-a")
        self.assertEqual(path, "")
        self.assertIn("does not exist", error)


# ---------------------------------------------------------------------------
# The ending is the label — driven through the real door
# ---------------------------------------------------------------------------

class TestTheEndingIsTheLabel(CaptureCase):
    """`server._end_finding` is the one door every ending comes through.

    The tab's buttons, a tick in the To-do app and a button on a
    notification all reach it, so hooking the label here is what makes
    the claim true of the ANSWER rather than of the surface it was given
    on — the same reasoning that put `_end_finding` there in the first
    place.
    """

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        self._old_store = (findings_store.FINDINGS_FILE,
                           findings_store.SETTLED_FILE,
                           findings_store.STATE_FILE,
                           self.server.MEMORY_INBOX_DIR)
        findings_store.FINDINGS_FILE = self.base / "findings.json"
        findings_store.SETTLED_FILE = self.base / "settled.json"
        findings_store.STATE_FILE = self.base / "cfg" / ".brain" / "state.json"
        self.server.MEMORY_INBOX_DIR = self.base / "memory-inbox"

    def tearDown(self):
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE,
         self.server.MEMORY_INBOX_DIR) = self._old_store
        super().tearDown()

    RUN = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"

    def a_finding(self, text="The hall sensor has not reported since Tuesday"):
        created = findings_store.add_many([{
            "text": text, "detail": "last seen 3 Sep", "fix": "Re-pair it",
            "severity": "serious", "source": "automations",
            "source_title": "Automations", "run_id": self.RUN}])
        return created[0]

    def end(self, row, verb, note=""):
        return asyncio.run(self.server._end_finding(
            findings_store.get(row["ts"]),
            self.server.FINDING_VERBS[verb], note))

    def test_the_row_remembers_which_run_raised_it(self):
        row = self.a_finding()
        self.assertEqual(findings_store.get(row["ts"])["run_id"], self.RUN)

    def test_each_ending_lands_on_the_capture_with_its_own_word(self):
        for verb, word in (("done", "done"), ("wrong", "wrong"),
                           ("ack", "got_it")):
            with self.subTest(verb):
                self.a_run(self.RUN)
                row = self.a_finding(f"Something is broken ({verb})")
                self.end(row, verb)
                labels = capture.read(self.RUN)["labels"]
                self.assertEqual(len(labels), 1, labels)
                self.assertEqual(labels[0]["verb"], word)
                self.assertEqual(
                    labels[0]["finding_key"],
                    findings_store.normalize(f"Something is broken ({verb})"))
                capture.delete(self.RUN)

    def test_a_correction_carries_its_reason_onto_the_capture(self):
        self.a_run(self.RUN)
        row = self.a_finding()
        self.end(row, "wrong", "that cupboard is never opened")
        label = capture.read(self.RUN)["labels"][0]
        self.assertEqual(label["verb"], "wrong")
        self.assertIn("never opened", label["note"])

    def test_a_check_finding_labels_nothing_because_no_run_raised_it(self):
        """A house check costs no Claude turn, so there is no prompt to
        grade — and an id invented for one would file a label against a
        capture nothing in the add-on can point at."""
        self.a_run(self.RUN)
        created = findings_store.add_many([{
            "text": "A battery is running down", "source": "check:forecast.battery",
            "source_title": "Forecast"}])
        self.end(created[0], "done")
        self.assertEqual(capture.read(self.RUN)["labels"], [])

    def test_the_ending_still_happens_when_there_is_no_capture(self):
        """Capture is off on nearly every install. An ending must not
        notice."""
        row = self.a_finding()
        payload, fact = self.end(row, "done")
        self.assertEqual(findings_store.list_all(), [])
        self.assertTrue(findings_store.is_known(row["text"]))
        self.assertIn("Fixed by the homeowner", fact)
        self.assertEqual(payload["open"], 0)


class TestTheSwitchIsOffByDefault(unittest.TestCase):
    def test_capture_defaults_to_false(self):
        """The design page's own "not building" list says *any capture
        that is on by default*. A house's entity names are a floor plan."""
        import settings_store
        self.assertIs(settings_store.DEFAULTS["capture"], False)
        self.assertIs(settings_store.load().get("capture"), False)

    def test_the_setting_refuses_anything_that_is_not_a_boolean(self):
        import settings_store
        with self.assertRaises(ValueError):
            settings_store.save({"capture": "yes"})

    def test_the_capture_directory_is_excluded_from_backups(self):
        """HA backups are unencrypted unless somebody opted in, then get
        copied to cloud storage. A backup is the one route out nobody
        presses."""
        text = (BASE_DIR / "brain" / "config.yaml").read_text(encoding="utf-8")
        block = text.split("backup_exclude:", 1)[1].split("\nstage:", 1)[0]
        self.assertIn("capture/**", block)


if __name__ == "__main__":
    unittest.main()
