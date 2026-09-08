#!/usr/bin/env python3
"""Problem reports: a failure becomes ONE readable, redacted text file.

Every producer is driven rather than described — a journal row through the
real listener, the health verdict through `note_health`, a notification
failure through the real `save_queue`, the routes through the real panel
app, and `brain-report.sh` against a real HTTP stub and a closed port.
Each test names the mutation it catches:

  one file per failure        drop the dedup -> forty files about one dead
                              credential, and the folder stops being opened
  redaction is whole-file     redact a section at a time -> the add-on log,
                              the one section that DOES carry tokens, is
                              the one that is missed
  the cap spares the newest   prune newest-first -> the report about the
                              failure that just happened is the one deleted
  the barrier                 basename-only -> a name off the wire reads
                              /data/reports-index.json, or worse
  a listener cannot fail a run  let it raise -> the journal, which promised
                              never to, takes the run down with it
  the shell agrees            two redactions -> a secret one keeps and the
                              other drops, depending on who wrote the file
"""
from __future__ import annotations

import importlib
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
INTEGRATION = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(PANEL_DIR))

import journal  # noqa: E402
import reports  # noqa: E402

LOG_SECRET = "sk-ant-oat01-AAAABBBBCCCCDDDDEEEEFFFF"
LOG_TEXT = ("[12:00:01] INFO panel started\n"
            f"[12:00:02] DEBUG auth token {LOG_SECRET} loaded\n"
            "[12:00:03] WARNING something failed\n")
DIAG = {
    "versions": {"addon": "1.48.0", "claude_cli": "2.1.0",
                 # A JSON field rule case, planted where the abridged
                 # section will carry it verbatim.
                 "token": "verysecretvalue123456"},
    "health": {"state": "ok", "reason": "everything brAIn runs is running",
               "fix": "", "problems": []},
    "journal": {"runs": 3, "by_outcome": {"ok": 2, "timeout": 1},
                "by_source": {"insight": {"ok": 2, "timeout": 1}}},
    "checks": {"finished_at": 1_700_000_000, "created": 1, "cleared": 0,
               "ran": ["a", "b"], "skipped": {}, "errors": {}},
    "auth": {"state": "ok", "checked_at": 1_700_000_000, "error": ""},
    "daemons": {"ttyd": {"running": True}},
}
# The strings both redactions have to handle, one list so neither side can
# quietly stop covering one (the pattern `tests/test_capture.py` uses).
SECRETS = [
    ("sk-ant-oat01-AAAABBBBCCCCDDDDEEEEFFFF", "an OAuth token"),
    ("Bearer abcdefghijklmnop.qrstuv-wxyz", "an Authorization header"),
    ("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0"
     + ".dBjftJeZ4CVPmB92K27uhbUJU1p1r_wW1gFWFOEjXk", "a JWT"),
    ('"token": "abcdefghijklmnop"', "a token field"),
    ('"access_token": "abcdefghijklmnop"', "an access_token field"),
    ('"refresh_token":"abcdefghijklmnop"', "a refresh_token field, no space"),
    ('"api_key": "abcdefghijklmnop"', "an api_key field"),
    ('"value": "sk-ant-oat01-something-long"', "the panel store's value field"),
]


class ReportsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / "share").mkdir()
        (self.base / "data").mkdir()
        self._old = (reports.REPORTS_DIR, reports.INDEX_FILE, reports.HEALTH_LAST_FILE,
                     reports.fetch_addon_log, journal.JOURNAL_FILE,
                     list(journal._LISTENERS), os.environ.get("ADDON_VERSION"))
        reports.REPORTS_DIR = self.base / "share" / "brain" / "reports"
        reports.INDEX_FILE = self.base / "data" / "reports-index.json"
        reports.HEALTH_LAST_FILE = self.base / "data" / "health-last.json"
        reports.fetch_addon_log = lambda *a, **k: LOG_TEXT
        journal.JOURNAL_FILE = str(self.base / "data" / "journal.jsonl")
        journal._LISTENERS.clear()
        os.environ["ADDON_VERSION"] = "1.48.0-test"

    def tearDown(self):
        (reports.REPORTS_DIR, reports.INDEX_FILE, reports.HEALTH_LAST_FILE,
         reports.fetch_addon_log, journal.JOURNAL_FILE, listeners, ver) = self._old
        journal._LISTENERS[:] = listeners
        if ver is None:
            os.environ.pop("ADDON_VERSION", None)
        else:
            os.environ["ADDON_VERSION"] = ver
        self.tmp.cleanup()

    def files(self) -> list[Path]:
        if not reports.REPORTS_DIR.is_dir():
            return []
        return sorted(reports.REPORTS_DIR.glob("*.txt"))

    def index(self) -> dict:
        try:
            return json.loads(reports.INDEX_FILE.read_text())
        except OSError:
            return {}


# ---------------------------------------------------------------------------
# A failed run, through the journal
# ---------------------------------------------------------------------------

class TestAFailedRunFilesOneFile(ReportsCase):
    def setUp(self):
        super().setUp()
        # What `server.on_startup` registers, with the diagnostics a test
        # can hold still.
        journal.on_record(lambda row: reports.file_run_failure(row, diagnostics=DIAG))

    def test_a_timeout_row_files_exactly_one_redacted_file(self):
        journal.record("insight", "timeout",
                       error=f"took too long, token was {LOG_SECRET}",
                       duration_s=480, model="sonnet", now=1_700_000_000)
        files = self.files()
        self.assertEqual(len(files), 1, files)
        name = files[0].name
        self.assertRegex(name, r"^\d{4}-\d{2}-\d{2}-\d{4}-run\.txt$")
        text = files[0].read_text()
        head = text.splitlines()[0]
        self.assertIn("brAIn 1.48.0-test", head)
        self.assertIn("insight run ended timeout", head)
        for section in ("What happened:", "Where to look:", "--- run ---",
                        "--- health ---", "--- add-on log, last 80 lines ---",
                        "--- diagnostics (abridged) ---"):
            if section == "--- health ---":
                self.assertNotIn(section, text)      # a run has no health block
            else:
                self.assertIn(section, text, section)
        # The timeout sentence names the option for THIS source.
        self.assertIn("generation_timeout_minutes", text)
        self.assertIn("outcome=timeout", text)
        self.assertIn("duration_s=480", text)
        # The log made it in ...
        self.assertIn("panel started", text)
        # ... and the redaction ran over the whole file: the log line, the
        # error text and the diagnostics field alike.
        self.assertNotIn(LOG_SECRET, text)
        self.assertNotIn("verysecretvalue123456", text)
        self.assertIn('"token": "[redacted]"', text)
        self.assertIn("[redacted]", text)

    def test_every_failure_outcome_files_and_no_success_does(self):
        for i, outcome in enumerate(sorted(reports.FAILURE_OUTCOMES)):
            journal.record("card", outcome, error=f"failure {i}", now=1_700_000_000 + i * 60)
        self.assertEqual(len(self.files()), len(reports.FAILURE_OUTCOMES))
        before = len(self.files())
        for i, outcome in enumerate(("ok", "fallback", "applied", "healed",
                                     "heal_skipped", "denied")):
            journal.record("card", outcome, error="not a failure",
                           extra={"landed": True}, now=1_700_100_000 + i * 60)
        self.assertEqual(len(self.files()), before)

    def test_the_checks_pass_and_the_nightly_builder_are_covered(self):
        """server.run_checks and _baseline_loop journal `checks`/`baselines`
        `error` rows; the listener is what makes those a report."""
        journal.record("checks", "error", error="KeyError: 'states'", now=1_700_000_000)
        journal.record("baselines", "error", error="statistics timed out",
                       now=1_700_000_060)
        names = [p.name for p in self.files()]
        self.assertEqual(len(names), 2, names)
        texts = "\n".join(p.read_text() for p in self.files())
        self.assertIn("checks run ended error", texts)
        self.assertIn("baselines run ended", texts)

    def test_a_repeat_inside_a_day_is_a_line_not_a_file(self):
        row = dict(error="claude exited 1: boom", now=1_700_000_000)
        journal.record("card", "crash", **row)
        row["now"] += 3600
        journal.record("card", "crash", **row)
        files = self.files()
        self.assertEqual(len(files), 1, files)
        text = files[0].read_text()
        self.assertEqual(text.count("seen again at"), 1)
        self.assertRegex(text, r"seen again at \d\d:\d\d\n$")
        listing = reports.list_reports()
        self.assertEqual(listing[0]["count"], 2)

    def test_a_repeat_after_the_window_is_a_new_file(self):
        journal.record("card", "crash", error="claude exited 1: boom", now=1_700_000_000)
        journal.record("card", "crash", error="claude exited 1: boom",
                       now=1_700_000_000 + reports.DEDUP_HOURS * 3600 + 60)
        self.assertEqual(len(self.files()), 2)

    def test_a_different_error_is_a_different_problem(self):
        journal.record("card", "crash", error="claude exited 1: boom", now=1_700_000_000)
        journal.record("card", "crash", error="claude exited 2: other", now=1_700_000_060)
        self.assertEqual(len(self.files()), 2)

    def test_the_31st_prunes_the_oldest_and_never_the_one_just_written(self):
        for i in range(reports.MAX_REPORTS + 1):
            journal.record("card", "error", error=f"distinct failure {i}",
                           now=1_700_000_000 + i * 60)
        files = self.files()
        self.assertEqual(len(files), reports.MAX_REPORTS)
        texts = [p.read_text() for p in files]
        self.assertFalse(any("distinct failure 0\n" in t or "distinct failure 0 " in t
                             for t in texts), "the oldest survived the prune")
        self.assertTrue(any(f"distinct failure {reports.MAX_REPORTS}" in t for t in texts),
                        "the newest was pruned")
        # The index forgets the pruned one, so a repeat of it is a new file
        # rather than an append to nothing.
        self.assertEqual(len(self.index()), reports.MAX_REPORTS)

    def test_file_incident_never_raises(self):
        # Patched on the module object `reports` holds, not on whatever
        # `import atomic_write` answers now: three add-ons ship a module of
        # that name and other test files swap them in `sys.modules`.
        aw = reports.atomic_write
        old = aw.write_text
        aw.write_text = lambda *a, **k: (_ for _ in ()).throw(OSError("disk full"))
        try:
            self.assertIsNone(reports.file_incident("run", "h", "w", "l", diagnostics=DIAG))
        finally:
            aw.write_text = old
        reports.fetch_addon_log = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no"))
        self.assertIsNone(reports.file_incident("run", "h", "w", "l", diagnostics=DIAG))
        # The diagnostics callable failing is a section, not a lost report.
        reports.fetch_addon_log = lambda *a, **k: LOG_TEXT

        def bad():
            raise RuntimeError("diag broke")

        name = reports.file_incident("run", "h", "w", "l", diagnostics=bad)
        self.assertIsNotNone(name)
        self.assertIn("diagnostics unavailable", (reports.REPORTS_DIR / name).read_text())

    def test_nothing_is_written_where_share_does_not_exist(self):
        reports.REPORTS_DIR = self.base / "nope" / "brain" / "reports"
        journal.record("card", "crash", error="claude exited 1", now=1_700_000_000)
        self.assertFalse((self.base / "nope").exists())


# ---------------------------------------------------------------------------
# Listing, reading, deleting — and the barrier
# ---------------------------------------------------------------------------

class TestListReadDelete(ReportsCase):
    def test_list_is_newest_first_with_the_headline_off_the_file(self):
        reports.file_incident("run", "first problem", "w", "l", diagnostics=DIAG,
                              now=1_700_000_000)
        reports.file_incident("health", "second problem", "w", "l", diagnostics=DIAG,
                              now=1_700_000_600)
        rows = reports.list_reports()
        self.assertEqual([r["headline"] for r in rows], ["second problem", "first problem"])
        self.assertEqual([r["kind"] for r in rows], ["health", "run"])
        for r in rows:
            self.assertEqual(set(r), {"name", "ts", "kind", "headline", "count", "bytes"})
            self.assertGreater(r["bytes"], 100)
            self.assertEqual(r["count"], 1)

    def test_read_and_delete(self):
        name = reports.file_incident("run", "h", "w", "l", diagnostics=DIAG,
                                     now=1_700_000_000)
        self.assertIn("What happened:", reports.read_report(name))
        self.assertTrue(reports.delete_report(name))
        self.assertIsNone(reports.read_report(name))
        self.assertFalse(reports.delete_report(name))
        self.assertEqual(self.index(), {})

    def test_the_barrier(self):
        reports.REPORTS_DIR.mkdir(parents=True)
        outside = self.base / "share" / "brain" / "x.txt"
        outside.write_text("not yours")
        (reports.REPORTS_DIR / "sub").mkdir()
        (reports.REPORTS_DIR / "sub" / "b.txt").write_text("nested")
        (reports.REPORTS_DIR / "x.json").write_text("{}")
        (reports.REPORTS_DIR / ".hidden.txt").write_text("hidden")
        for bad in ("../x.txt", "sub/b.txt", "x.json", ".hidden.txt", "", "a\\b.txt",
                    "/etc/passwd", "..", "sub/../x.json"):
            with self.subTest(bad):
                self.assertIsNone(reports._safe_path(bad))
                self.assertIsNone(reports.read_report(bad))
                self.assertFalse(reports.delete_report(bad))
        self.assertTrue(outside.exists())
        self.assertTrue((reports.REPORTS_DIR / "x.json").exists())

    def test_combined_separates_and_skips_the_missing(self):
        a = reports.file_incident("run", "A", "w", "l", diagnostics=DIAG, now=1_700_000_000)
        b = reports.file_incident("run", "B", "w", "l", diagnostics=DIAG, now=1_700_000_060)
        text = reports.combined([a, "../x.txt", b, "gone.txt"])
        self.assertEqual(text.count("===="), 4)
        self.assertLess(text.index(f"==== {a} ===="), text.index(f"==== {b} ===="))


# ---------------------------------------------------------------------------
# Health transitions
# ---------------------------------------------------------------------------

class TestHealthTransitions(ReportsCase):
    def verdict(self, state, reason="the automation listener is not running"):
        return {"state": state, "reason": reason, "fix": "Turn enable_automations on."}

    def test_ok_to_degraded_files_one_and_says_both_states(self):
        self.assertIsNone(reports.note_health(self.verdict("ok"), DIAG, now=1_700_000_000))
        self.assertEqual(self.files(), [])
        name = reports.note_health(self.verdict("degraded"), DIAG, now=1_700_000_600)
        self.assertIsNotNone(name)
        self.assertEqual(len(self.files()), 1)
        text = (reports.REPORTS_DIR / name).read_text()
        self.assertIn("--- health ---", text)
        self.assertIn("ok → degraded: the automation listener is not running", text)
        self.assertIn("Turn enable_automations on.", text)
        self.assertTrue(name.endswith("-health.txt"))

    def test_degraded_to_degraded_files_nothing(self):
        reports.note_health(self.verdict("degraded"), DIAG, now=1_700_000_000)
        self.assertEqual(len(self.files()), 1)
        for i in range(1, 4):
            self.assertIsNone(reports.note_health(self.verdict("degraded"), DIAG,
                                                  now=1_700_000_000 + i * 3600))
        self.assertEqual(len(self.files()), 1)
        self.assertNotIn("seen again", self.files()[0].read_text())

    def test_back_to_ok_files_nothing_and_updates_the_record(self):
        reports.note_health(self.verdict("degraded"), DIAG, now=1_700_000_000)
        self.assertIsNone(reports.note_health(self.verdict("ok"), DIAG, now=1_700_003_600))
        self.assertEqual(len(self.files()), 1)
        self.assertEqual(json.loads(reports.HEALTH_LAST_FILE.read_text())["state"], "ok")
        # And a fresh fall is news again — the same reason inside a day
        # is a line on the file it already has, not silence.
        self.assertEqual(reports.note_health(self.verdict("degraded"), DIAG,
                                             now=1_700_007_200), self.files()[0].name)
        self.assertIn("seen again", self.files()[0].read_text())

    def test_a_worsening_is_filed_too(self):
        reports.note_health(self.verdict("degraded"), DIAG, now=1_700_000_000)
        name = reports.note_health(self.verdict("failed", "the credential was refused"),
                                   DIAG, now=1_700_000_600)
        self.assertIsNotNone(name)
        self.assertIn("degraded → failed", (reports.REPORTS_DIR / name).read_text())

    def test_no_data_directory_means_no_tracking_and_no_report(self):
        reports.HEALTH_LAST_FILE = self.base / "nodata" / "health-last.json"
        self.assertFalse(reports.tracks_health())
        self.assertIsNone(reports.note_health(self.verdict("failed"), DIAG))
        self.assertEqual(self.files(), [])


# ---------------------------------------------------------------------------
# Notification failures
# ---------------------------------------------------------------------------

class TestNotifyFailures(ReportsCase):
    def test_a_failed_send_files_one(self):
        name = reports.notify_failure("mobile_app_phone", "Service notify.mobile_app_phone "
                                      "not found", context="2 finding(s)", diagnostics=DIAG,
                                      now=1_700_000_000)
        self.assertTrue(name.endswith("-notify.txt"))
        text = (reports.REPORTS_DIR / name).read_text()
        self.assertIn("notification via mobile_app_phone failed", text)
        self.assertIn("findings_notify_service", text)
        self.assertIn("source=mobile_app_phone", text)

    def test_the_hold_queue_failing_to_write_files_one(self):
        """Through the real `save_queue`, with the write made to fail."""
        import atomic_write
        import notify_router

        old = atomic_write.write_json

        def boom(*a, **k):
            raise OSError("read-only file system")

        atomic_write.write_json = boom
        try:
            notify_router.save_queue([{"ts": 1, "text": "x"}],
                                     path=str(self.base / "data" / "queue.json"))
        finally:
            atomic_write.write_json = old
        for t in threading.enumerate():
            if t.name == "brain-reports-queue":
                t.join(timeout=10)
        files = self.files()
        self.assertEqual(len(files), 1, files)
        text = files[0].read_text()
        self.assertIn("hold queue could not be written", text)
        self.assertIn("read-only file system", text)


# ---------------------------------------------------------------------------
# The journal's listeners
# ---------------------------------------------------------------------------

class TestJournalListeners(ReportsCase):
    def test_a_raising_listener_never_reaches_the_caller_and_the_next_still_runs(self):
        seen = []

        def bad(row):
            raise RuntimeError("listener broke")

        journal.on_record(bad)
        journal.on_record(seen.append)
        row = journal.record("card", "timeout", error="x", now=1_700_000_000)
        self.assertEqual(row["outcome"], "timeout")
        self.assertEqual(seen, [row])
        self.assertEqual(len(journal.tail(5)), 1)
        journal.off_record(bad)
        journal.record("card", "ok", now=1_700_000_001)
        self.assertEqual(len(seen), 2)
        journal.off_record(seen.append)  # bound methods compare equal: removed
        journal.record("card", "ok", now=1_700_000_002)
        self.assertEqual(len(seen), 2)

    def test_registering_twice_calls_once(self):
        seen = []
        journal.on_record(seen.append)
        journal.on_record(seen.append)
        journal.record("card", "ok", now=1_700_000_000)
        self.assertEqual(len(seen), 1)


# ---------------------------------------------------------------------------
# Both redactions, one fixture
# ---------------------------------------------------------------------------

class TestTheShellAndThePythonAgree(unittest.TestCase):
    SHELL = SCRIPTS / "brain-report.sh"

    def shell_redact(self, text: str) -> str:
        src = self.SHELL.read_text(encoding="utf-8")
        start = src.index("redact() {")
        end = src.index("\n}\n", start) + 3
        block = src[start:end]
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "sample.txt"
            proc = subprocess.run(
                ["bash", "-c",
                 block + '\nprintf "%s" "$1" > "$2"\nredact "$2"\ncat "$2"\n',
                 "_", text, str(target)],
                capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_same_output_over_every_secret(self):
        for secret, what in SECRETS:
            text = f"the log said: {secret} — and then it stopped"
            with self.subTest(what):
                mine = reports.redact(text)
                theirs = self.shell_redact(text)
                self.assertNotIn(secret, mine, f"python kept {what}")
                self.assertEqual(mine, theirs, what)
                self.assertIn("[redacted]", mine)

    def test_a_short_value_and_a_plain_state_are_left_alone(self):
        for text in ('"value": "on"', '"token": "short"', "light.kitchen is on"):
            with self.subTest(text):
                self.assertEqual(reports.redact(text), text)
                self.assertEqual(self.shell_redact(text), text)


# ---------------------------------------------------------------------------
# The routes, through the real panel app
# ---------------------------------------------------------------------------

class TestRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = self.tmp.name
        self.config = Path(base) / "config"
        self.config.mkdir()
        (Path(base) / "share").mkdir()
        (Path(base) / "data").mkdir()
        self._env = dict(os.environ)
        for key, value in {
            "BRAIN_CONFIG_DIR": str(self.config),
            "BRAIN_INTENTS_FILE": os.path.join(base, "intents.json"),
            "BRAIN_INTENT_REQUESTS_DIR": os.path.join(base, "intent-requests"),
            "BRAIN_EDIT_JOURNAL": os.path.join(base, "edits"),
            "BRAIN_FINDINGS_FILE": os.path.join(base, "findings.json"),
            "BRAIN_FINDINGS_SETTLED": os.path.join(base, "settled.json"),
            "BRAIN_FINDINGS_STATE": os.path.join(base, "state.json"),
            "BRAIN_FINDINGS_INBOX": os.path.join(base, "finbox"),
            "BRAIN_JOURNAL_FILE": os.path.join(base, "journal.jsonl"),
            "BRAIN_MEMORY_DIR": os.path.join(base, "memory"),
            "BRAIN_MEMORY_INBOX": os.path.join(base, "memory", "inbox"),
            "BRAIN_DIR": os.path.join(base, "insights"),
            "BRAIN_SETTINGS_FILE": os.path.join(base, "settings.json"),
            "BRAIN_KNOWLEDGE_FILE": os.path.join(base, "knowledge.json"),
            "BRAIN_DIAGNOSTICS_FILE": os.path.join(base, "diag.json"),
            "BRAIN_PROPOSALS_FILE": os.path.join(base, "proposals.json"),
            "BRAIN_REPORTS_DIR": os.path.join(base, "share", "brain", "reports"),
            "BRAIN_REPORTS_INDEX": os.path.join(base, "data", "reports-index.json"),
            "BRAIN_HEALTH_LAST": os.path.join(base, "data", "health-last.json"),
            "ADDON_VERSION": "1.48.0-test",
        }.items():
            os.environ[key] = value
        self.reports = importlib.reload(reports)
        self.reports.fetch_addon_log = lambda *a, **k: LOG_TEXT
        import server
        self.server = importlib.reload(server)
        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        journal._LISTENERS.clear()
        os.environ.clear()
        os.environ.update(self._env)
        importlib.reload(reports)
        self.tmp.cleanup()

    def drain(self):
        self.server._REPORT_EXECUTOR.submit(lambda: None).result(timeout=30)

    async def test_the_whole_surface(self):
        resp = await self.client.get("/api/reports")
        self.assertEqual(resp.status, 200)
        data = await resp.json()
        self.assertEqual(data["reports"], [])
        self.assertTrue(data["available"])
        self.assertEqual(data["max"], reports.MAX_REPORTS)

        # A manual report: the full diagnostics appended, never deduped.
        resp = await self.client.post("/api/reports/run", json={})
        self.assertEqual(resp.status, 200, await resp.text())
        first = (await resp.json())["name"]
        self.assertTrue(first.endswith("-manual.txt"))
        resp = await self.client.post("/api/reports/run", json={})
        second = (await resp.json())["name"]
        self.assertNotEqual(first, second)

        resp = await self.client.get(f"/api/reports/{first}")
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.content_type.startswith("text/plain"))
        text = await resp.text()
        self.assertIn("--- diagnostics (full) ---", text)
        self.assertIn('"versions"', text)
        self.assertIn("panel started", text)
        self.assertNotIn(LOG_SECRET, text)

        # A failed run through the listener the startup hook registered.
        journal.record("card", "crash", error="claude exited 1: boom")
        self.drain()
        resp = await self.client.get("/api/reports")
        rows = (await resp.json())["reports"]
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["kind"], "run")

        # Copy: several as one text, the missing skipped.
        resp = await self.client.post("/api/reports/copy",
                                      json={"names": [first, second, "nope.txt"]})
        self.assertEqual(resp.status, 200)
        combined = await resp.text()
        self.assertIn(f"==== {first} ====", combined)
        self.assertIn(f"==== {second} ====", combined)
        self.assertNotIn("nope.txt", combined)
        resp = await self.client.post("/api/reports/copy", json={"names": "x"})
        self.assertEqual(resp.status, 400)

        # The barrier answers 404, never a file from elsewhere.
        for bad in ("..%2Fx.txt", "x.json", "reports-index.json"):
            resp = await self.client.get(f"/api/reports/{bad}")
            self.assertEqual(resp.status, 404, bad)
            resp = await self.client.delete(f"/api/reports/{bad}")
            self.assertEqual(resp.status, 404, bad)

        resp = await self.client.delete(f"/api/reports/{first}")
        self.assertEqual(resp.status, 200)
        resp = await self.client.get(f"/api/reports/{first}")
        self.assertEqual(resp.status, 404)

    async def test_no_share_is_a_503_that_says_so(self):
        self.reports.REPORTS_DIR = Path(self.tmp.name) / "nowhere" / "brain" / "reports"
        resp = await self.client.post("/api/reports/run", json={})
        self.assertEqual(resp.status, 503)
        self.assertIn("/share", (await resp.json())["error"])
        resp = await self.client.get("/api/reports")
        self.assertFalse((await resp.json())["available"])

    async def test_publish_diagnostics_notes_the_verdict(self):
        """The mirror's writer is where the comparison lives."""
        import health

        old = health.verdict
        health.verdict = lambda *a, **k: {"state": "degraded", "reason": "test reason",
                                          "fix": "flip the switch", "problems": [],
                                          "checked_at": 0, "stale_after_h": 3}
        try:
            await asyncio_to_thread(self.server.publish_diagnostics)
        finally:
            health.verdict = old
        rows = self.reports.list_reports()
        self.assertEqual([r["kind"] for r in rows], ["health"])
        self.assertIn("ok → degraded: test reason",
                      self.reports.read_report(rows[0]["name"]))
        self.assertEqual(json.loads(Path(os.environ["BRAIN_HEALTH_LAST"]).read_text())["state"],
                         "degraded")


async def asyncio_to_thread(fn):
    import asyncio
    return await asyncio.to_thread(fn)


# ---------------------------------------------------------------------------
# brain-report.sh, against a stub panel and against a closed port
# ---------------------------------------------------------------------------

class _StubPanel(BaseHTTPRequestHandler):
    NAME = "2026-09-08-1200-manual.txt"
    TEXT = ("2026-09-08 12:00 · brAIn 1.48.0 · report requested\n\nWhat happened:\n"
            "Somebody asked.\n\n--- run ---\n(none)\nlight.kitchen was on\n")

    def log_message(self, *a):  # quiet
        pass

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/api/reports/run":
            body = json.dumps({"name": self.NAME}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def do_GET(self):
        if self.path == f"/api/reports/{self.NAME}":
            body = self.TEXT.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


class TestBrainReportScript(unittest.TestCase):
    SCRIPT = SCRIPTS / "brain-report.sh"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        self.out = self.base / "reports"

    def tearDown(self):
        self.tmp.cleanup()

    def run_script(self, port: int, *args: str, mirror: str = "") -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "SUPERVISOR_TOKEN"}
        env.update({
            "BRAIN_PANEL_URL": f"http://127.0.0.1:{port}",
            "BRAIN_REPORTS_DIR": str(self.out),
            "BRAIN_SCRIPTS_DIR": str(self.base),        # no ha-selftest.sh here
            "BRAIN_DIAGNOSTICS_FILE": mirror or str(self.base / "no-mirror.json"),
            "ADDON_VERSION": "1.48.0-test",
        })
        return subprocess.run(["bash", str(self.SCRIPT), *args], env=env,
                              capture_output=True, text=True, timeout=120)

    def test_against_a_panel_it_writes_one_txt_and_prints_its_path(self):
        srv = HTTPServer(("127.0.0.1", 0), _StubPanel)
        thread = threading.Thread(target=srv.serve_forever, daemon=True)
        thread.start()
        try:
            proc = self.run_script(srv.server_address[1])
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        files = sorted(self.out.glob("*"))
        self.assertEqual([p.name for p in files], [_StubPanel.NAME])
        self.assertIn(str(files[0]), proc.stdout)
        self.assertIn("light.kitchen", files[0].read_text())

    def test_no_names_hashes_the_entity_ids(self):
        srv = HTTPServer(("127.0.0.1", 0), _StubPanel)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            proc = self.run_script(srv.server_address[1], "--no-names")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        text = (self.out / _StubPanel.NAME).read_text()
        self.assertNotIn("light.kitchen", text)
        self.assertRegex(text, r"light\.[0-9a-f]{8} was on")

    def test_against_a_closed_port_it_writes_the_fallback(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        mirror = self.base / "diag.json"
        mirror.write_text(json.dumps({"versions": {"addon": "1.48.0"},
                                      "auth": {"error": f"401 for {LOG_SECRET}"},
                                      "note": "light.kitchen"}))
        proc = self.run_script(port, mirror=str(mirror))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        files = sorted(self.out.glob("*"))
        self.assertEqual(len(files), 1, files)
        self.assertRegex(files[0].name, r"^\d{4}-\d{2}-\d{2}-\d{4}-manual\.txt$")
        self.assertIn(str(files[0]), proc.stdout)
        text = files[0].read_text()
        self.assertIn("panel not answering", text)
        for section in ("What happened:", "Where to look:", "--- doctor ---",
                        "--- versions ---", "--- add-on log, last 80 lines ---",
                        "--- diagnostics"):
            self.assertIn(section, text, section)
        self.assertIn("ha-selftest.sh not installed", text)
        self.assertIn('"addon": "1.48.0"', text)        # the mirror was read
        self.assertNotIn(LOG_SECRET, text)              # and redacted
        self.assertIn("[redacted]", text)
        self.assertIn("light.kitchen", text)            # names stay without --no-names

    def test_no_python3_dash_c_and_no_pipe_into_a_heredoc(self):
        src = self.SCRIPT.read_text()
        self.assertNotIn("python3 -c", src)
        for line in src.splitlines():
            self.assertFalse("|" in line and "python3 - " in line, line)
        self.assertNotIn("tar ", src)


# ---------------------------------------------------------------------------
# The Repairs entry, on the integration side
# ---------------------------------------------------------------------------

SENSOR_DRIVER = r'''
import asyncio, json, os, sys, types
INTEGRATION = sys.argv[1]
mirror_dir = sys.argv[2]

def mod(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m

class _Enum(str):
    pass

calls = []
ir = mod("homeassistant.helpers.issue_registry")
class IssueSeverity:
    WARNING = "warning"
    ERROR = "error"
ir.IssueSeverity = IssueSeverity
ir.async_create_issue = lambda hass, domain, issue_id, **kw: calls.append(("create", domain, issue_id, kw))
ir.async_delete_issue = lambda hass, domain, issue_id: calls.append(("delete", domain, issue_id))

mod("homeassistant")
mod("homeassistant.components")
class SensorEntity:
    pass
mod("homeassistant.components.sensor", SensorDeviceClass=types.SimpleNamespace(TIMESTAMP="ts"),
    SensorEntity=SensorEntity, SensorStateClass=types.SimpleNamespace(MEASUREMENT="m"))
mod("homeassistant.config_entries", ConfigEntry=object)
mod("homeassistant.const", EntityCategory=types.SimpleNamespace(DIAGNOSTIC="diagnostic"))
mod("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
mod("homeassistant.helpers")
mod("homeassistant.helpers.device_registry", DeviceInfo=lambda **kw: kw)
mod("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
mod("homeassistant.helpers.dispatcher", async_dispatcher_connect=lambda *a, **k: None)

pkg = types.ModuleType("brain")
pkg.__path__ = [INTEGRATION]
sys.modules["brain"] = pkg
import importlib
sensor = importlib.import_module("brain.sensor")

class Hass:
    class config:
        @staticmethod
        def path(*parts):
            return os.path.join(mirror_dir, *parts)
    async def async_add_executor_job(self, fn, *args):
        return fn(*args)

entry = types.SimpleNamespace(entry_id="e1")
s = sensor.BrainHealthSensor(entry)
s.hass = Hass()
mirror = os.path.join(mirror_dir, sensor.SHARED_DIR, sensor.DIAGNOSTICS_FILENAME)
os.makedirs(os.path.dirname(mirror), exist_ok=True)

def publish(state, reason):
    with open(mirror, "w") as fh:
        json.dump({"health": {"state": state, "reason": reason, "fix": "f",
                              "problems": [], "stale_after_h": 3}}, fh)

out = []
# 1. no mirror yet
if os.path.exists(mirror):
    os.remove(mirror)
asyncio.run(s.async_update()); out.append((s._attr_native_value, list(calls))); calls.clear()
# 2. degraded
publish("degraded", "the automation listener is not running")
asyncio.run(s.async_update()); out.append((s._attr_native_value, list(calls))); calls.clear()
# 3. back to ok
publish("ok", "everything brAIn runs is running")
asyncio.run(s.async_update()); out.append((s._attr_native_value, list(calls))); calls.clear()
print(json.dumps(out))
'''


class TestTheRepairsEntry(unittest.TestCase):
    """Driven in a subprocess behind stubs, so the partial `homeassistant`
    stubs other test modules install cannot collide with these."""

    def test_the_issue_follows_the_verdict(self):
        with tempfile.TemporaryDirectory() as d:
            proc = subprocess.run(
                [sys.executable, "-c", SENSOR_DRIVER, str(INTEGRATION), d],
                capture_output=True, text=True, timeout=60)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        first, degraded, ok = json.loads(proc.stdout)
        # No mirror: failed, and no repair — a stopped add-on is a decision.
        self.assertEqual(first[0], "failed")
        self.assertEqual(first[1], [])
        # Degraded: one WARNING issue, not fixable, carrying the reason.
        self.assertEqual(degraded[0], "degraded")
        self.assertEqual(len(degraded[1]), 1)
        kind, domain, issue_id, kw = degraded[1][0]
        self.assertEqual((kind, domain, issue_id), ("create", "brain", "health_degraded"))
        self.assertFalse(kw["is_fixable"])
        self.assertEqual(kw["severity"], "warning")
        self.assertEqual(kw["translation_key"], "health_degraded")
        self.assertEqual(kw["translation_placeholders"],
                         {"reason": "the automation listener is not running."})
        # Back to ok: deleted.
        self.assertEqual(ok[0], "ok")
        self.assertEqual(ok[1], [["delete", "brain", "health_degraded"]])

    def test_the_strings_carry_the_issue_in_both_files(self):
        for f in (INTEGRATION / "strings.json", INTEGRATION / "translations" / "en.json"):
            with f.open(encoding="utf-8") as fh:
                issues = json.load(fh)["issues"]
            self.assertIn("health_degraded", issues, f.name)
            self.assertIn("{reason}", issues["health_degraded"]["description"])
            self.assertNotIn("fix_flow", issues["health_degraded"])


if __name__ == "__main__":
    unittest.main()
