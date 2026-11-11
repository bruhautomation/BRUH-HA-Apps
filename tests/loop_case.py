"""The Resident-loop fixture the camera tests share (was in test_resident_loop.py)."""

import asyncio
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

# Imported for the names; every one of them is REBOUND in `setUpClass` to
# the copy the panel itself holds — see the note there. `cases` is not
# imported: nothing here reads it by name, and the copy the feed uses is
# reached as `cls.server.cases` where `point()` needs it.
import findings_store  # noqa: E402
import resident  # noqa: E402
import signals  # noqa: E402
import triage  # noqa: E402


def reply(verdicts: list[dict], run_id: str = "look-1") -> dict:
    """What a first look answers with, in the CLI's envelope."""
    return {"ok": True, "error": "", "text": json.dumps({"verdicts": verdicts}),
            "meta": {"session_id": run_id}}


def case_reply(**over) -> dict:
    body = {
        "claim": "The garage freezer has drifted six degrees in a month",
        "detail": "Its own statistics walk upward and no other freezer does.",
        "kind": "problem", "confidence": 0.8, "stakes": "high",
        "fix": "Check the door seal.",
        "evidence": [{"entity": "sensor.garage_freezer", "value": "-12.4",
                      "when": "15 Sep 08:10"}],
        "actions": [], "escalate": False, **over}
    return {"ok": True, "error": "", "text": json.dumps(body),
            "meta": {"session_id": "inv-1"}}


class LoopCase(unittest.TestCase):
    """`_resident_tick` driven over real stores, with the CLI stubbed."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        # The panel's OWN module objects, not whatever `sys.modules` holds
        # by the time this file is collected. Several test modules pop a
        # store out of `sys.modules` and re-import it against their own
        # temporary directory, so by the time this one runs there can be
        # THREE live copies of `proposals`: the one this file imported, the
        # one `server` holds, and the one `cases` holds — and they are not
        # the same object, which was measured rather than assumed. Writing
        # through one and reading through another is a test that passes
        # alone and fails under the suite, which is exactly what happened.
        # CLAUDE.md's `atomic_write` rule, one import graph over: patch the
        # copy the code under test actually reads, and here that means all
        # of them.
        global findings_store, hypotheses, proposals, todo_store
        global resident, signals, triage
        findings_store = cls.server.findings_store
        hypotheses = cls.server.hypotheses
        proposals = cls.server.proposals
        todo_store = cls.server.todo_store
        resident = cls.server.resident
        signals = cls.server.signals
        triage = cls.server.triage

    @classmethod
    def copies(cls, name: str) -> list:
        """Every live module object under this name that the panel reads."""
        out, seen = [], set()
        for holder in (cls.server, cls.server.cases, sys.modules):
            mod = (sys.modules.get(name) if holder is sys.modules
                   else getattr(holder, name, None))
            if mod is not None and id(mod) not in seen:
                seen.add(id(mod))
                out.append(mod)
        return out

    def point(self, name: str, **paths) -> None:
        """Point every copy of `name` at this test's own directory, and put
        each one back afterwards."""
        for mod in self.copies(name):
            for attr, value in paths.items():
                self._restore.append((mod, attr, getattr(mod, attr)))
                setattr(mod, attr, value)

    def setUp(self):
        import engine
        import settings_store
        import undo_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        srv = self.server
        self._restore: list[tuple] = []
        self._old = {
            "settings": settings_store.SETTINGS_FILE,
            "engine": (engine.run_claude, engine.run_analyst, engine.get_auth),
            "server": (srv.LEDGER, srv._house_prompt_block,
                       srv._read_shared_memory, srv._announce_findings,
                       srv._record_usage, srv.MEMORY_INBOX_DIR,
                       srv.EVENT_BUS, srv._findings_notify_target),
        }
        (root / "inbox").mkdir(parents=True, exist_ok=True)
        # Pointed under a "config" that does not exist, so the mirrors are
        # skipped exactly as they are on a dev checkout.
        self.point("findings_store",
                   FINDINGS_FILE=root / "findings.json",
                   INBOX_DIR=root / "inbox",
                   SETTLED_FILE=root / "findings-settled.json",
                   STATE_FILE=root / "config" / ".brain" / "state.json")
        self.point("hypotheses", HYPOTHESES_FILE=root / "hypotheses.jsonl")
        self.point("proposals",
                   STORE=root / "proposals.json",
                   SETTLED_FILE=root / "proposals-settled.json",
                   SHARED=root / "config" / ".brain" / "proposals.json")
        self.point("todo_store",
                   TODO_FILE=root / "todo.json",
                   STATE_FILE=root / "config" / ".brain" / "todo.json")
        self.point("cases", SNOOZE_FILE=root / "cases-snooze.json")
        self.point("resident", WATCH_FILE=root / "resident-watch.json")
        # Answering a question records it in the facts ledger; left at its
        # default this wrote /data/knowledge.json, which passed for as long
        # as an earlier test file in the same process had pointed it at
        # tmp and never put it back. Under xdist that file is on another
        # worker and CI's runner cannot create /data.
        self.point("knowledge_store", KNOWLEDGE_FILE=str(root / "knowledge.json"))
        # Every look and investigation writes a verdict row, and the next
        # look reads the graded log back as worked examples — so the log is
        # this test's own, or one test's verdicts become the next one's
        # prompt.
        self.point("outcomes",
                   VERDICTS_FILE=root / "resident-verdicts.jsonl",
                   STATE_FILE=root / "resident-outcomes.json")
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        settings_store.save({"onboarded": True, "auto_enabled": True})
        srv.LEDGER = resident.Ledger(root / "resident-ledger.json")
        srv.MEMORY_INBOX_DIR = root / "memory-inbox"
        srv.EVENT_BUS = None
        undo_store.clear() if hasattr(undo_store, "clear") else None

        engine.get_auth = lambda: {"type": "oauth", "value": "x"}
        self.looks: list[dict] = []
        self.investigations: list[dict] = []
        self.look_calls: list[dict] = []
        self.analyst_calls: list[dict] = []

        def run_claude(prompt, system, *a, **k):
            self.look_calls.append({"prompt": prompt, "system": system,
                                    "args": a, **k})
            return self.looks.pop(0) if self.looks else {
                "ok": False, "error": "no reply", "meta": {}}

        def run_analyst(prompt, system, *a, **k):
            self.analyst_calls.append({"prompt": prompt, "system": system,
                                       "args": a, **k})
            return self.investigations.pop(0) if self.investigations else {
                "ok": False, "error": "no reply", "meta": {}}

        engine.run_claude = run_claude
        engine.run_analyst = run_analyst
        srv._read_shared_memory = lambda: ""
        srv._record_usage = lambda result, name: {"total": 1234}
        self.announced: list[dict] = []

        async def house(now=None):
            return ""

        async def announce(rows):
            self.announced.extend(rows or [])

        srv._house_prompt_block = house
        srv._announce_findings = announce
        srv.RESIDENT_PENDING.clear()
        srv.RESIDENT_INFLIGHT.clear()
        srv.RESIDENT_PARKED.clear()
        srv.RESIDENT_QUEUE = asyncio.Queue()
        srv.SAFETY_SUBJECTS.clear()
        srv.SAFETY_TRIPS.clear()
        # A notify target, so a safety case is announced (stubbed above)
        # rather than falling back to a persistent notification over a
        # Supervisor this test has none of.
        srv._findings_notify_target = lambda: ("mobile_app_test", "critical")
        srv._KNOWN_ENTITIES.update({"at": 0.0, "ids": frozenset()})
        srv._SIGNAL_CTX.update({"at": 0.0, "ctx": signals.EMPTY_CONTEXT})
        for key, value in (("running", False), ("last_look_at", 0.0),
                           ("last_sweep_at", 0.0),
                           ("queue_len", 0), ("waiting", 0),
                           ("hot_pending", 0), ("dropped", 0),
                           ("duplicates", 0), ("last_error", ""),
                           ("investigations_waiting", 0),
                           ("last_investigation_at", 0.0)):
            srv.RESIDENT_STATE[key] = value
        srv.TRIAGE_STATE.update({"running": False, "day": "", "runs": 0})

    def tearDown(self):
        import engine
        import settings_store
        srv = self.server
        for mod, attr, value in reversed(self._restore):
            setattr(mod, attr, value)
        settings_store.SETTINGS_FILE = self._old["settings"]
        (engine.run_claude, engine.run_analyst,
         engine.get_auth) = self._old["engine"]
        (srv.LEDGER, srv._house_prompt_block, srv._read_shared_memory,
         srv._announce_findings, srv._record_usage, srv.MEMORY_INBOX_DIR,
         srv.EVENT_BUS, srv._findings_notify_target) = self._old["server"]
        srv.RESIDENT_PENDING.clear()
        srv.RESIDENT_INFLIGHT.clear()
        srv.RESIDENT_PARKED.clear()
        srv.SAFETY_TRIPS.clear()
        srv.TRIAGE_STATE.update({"running": False, "day": "", "runs": 0})
        self.tmp.cleanup()

    # -- helpers ---------------------------------------------------------
    def file_check_row(self, **fields) -> dict:
        """One finding, filed the way every producer files: waiting."""
        [row] = findings_store.add_many(triage.gate([{
            "text": "The pantry contact has not changed in nine days",
            "detail": "last change 3 Sep", "severity": "warning",
            "entity_id": "binary_sensor.pantry",
            "source": "check:dev.frozen", "source_title": "Sensors frozen",
            **fields}]))
        return row

    def tick(self, now: float | None = None) -> dict:
        return asyncio.run(self.server._resident_tick(
            now if now is not None else time.time()))

    def statuses(self) -> dict[int, str]:
        return {f["ts"]: f["status"] for f in findings_store.list_all()}
