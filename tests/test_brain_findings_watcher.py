#!/usr/bin/env python3
"""The findings mirror, read from the Home Assistant side.

The add-on republishes /config/.brain/findings_state.json on every change
(tests/test_findings.py pins that half); this file pins the consumer — the
integration's ``FindingsWatcher`` — because its two jobs are subtle in
opposite directions.

The **event** half fires a ``brain_finding`` per NEW finding and for
nothing else: a watcher that replays the open list on every HA restart
turns "brAIn found something" automations into a 3am alarm test.

The **Repairs** half is the opposite claim and that is the whole point of
testing them together: an issue is STATE, so a restart has to put every
one of them back — Home Assistant drops non-persistent issues when it
boots, and a row still waiting on somebody must not lose its entry
because the add-on happened not to file anything new that minute.

``findings.py`` imports ``homeassistant.core``, the issue registry and its
own ``const``, so it comes in through stubs that skip the integration's
heavyweight ``__init__`` — and the table is put back exactly as it was
found, because several test modules install partial `homeassistant` stubs
and whichever runs first otherwise wins a shared ``sys.modules``.
"""

import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import findings_store  # noqa: E402  (the add-on's own writer)


class _IssueRegistry(types.ModuleType):
    """The slice of `homeassistant.helpers.issue_registry` findings.py uses.

    It records rather than asserts: what the tests below check is the
    sequence of creates and deletes a real registry would have been asked
    to perform, which is the only thing this module can honestly claim to
    know about Home Assistant.
    """

    def __init__(self):
        super().__init__("homeassistant.helpers.issue_registry")
        self.created: list[dict] = []
        self.deleted: list[str] = []

        class IssueSeverity:
            ERROR = "error"
            WARNING = "warning"
            CRITICAL = "critical"

        self.IssueSeverity = IssueSeverity

    def async_create_issue(self, hass, domain, issue_id, **kwargs):
        self.created.append({"domain": domain, "issue_id": issue_id, **kwargs})

    def async_delete_issue(self, hass, domain, issue_id):
        self.deleted.append(issue_id)

    def reset(self):
        self.created.clear()
        self.deleted.clear()

    # What exists right now, as far as the registry is concerned.
    def live(self) -> set[str]:
        out: set[str] = set()
        for row in self.created:
            out.add(row["issue_id"])
        for issue_id in self.deleted:
            out.discard(issue_id)
        return out


def _import_findings():
    """Import `brain_cc.findings` behind stubs, leaving sys.modules as found."""
    saved = dict(sys.modules)
    registry = _IssueRegistry()
    try:
        for name in ("homeassistant", "homeassistant.helpers"):
            sys.modules.setdefault(name, types.ModuleType(name))
        core = types.ModuleType("homeassistant.core")

        class _HomeAssistant:
            pass

        core.HomeAssistant = _HomeAssistant
        sys.modules["homeassistant.core"] = core
        sys.modules["homeassistant.helpers"].issue_registry = registry
        sys.modules["homeassistant.helpers.issue_registry"] = registry
        pkg = types.ModuleType("brain_cc")
        pkg.__path__ = [str(INTEGRATION_DIR)]
        sys.modules["brain_cc"] = pkg
        for stale in [m for m in sys.modules if m.startswith("brain_cc.")]:
            del sys.modules[stale]
        return importlib.import_module("brain_cc.findings"), registry
    finally:
        sys.modules.clear()
        sys.modules.update(saved)


findings, REGISTRY = _import_findings()


class _Bus:
    def __init__(self):
        self.fired: list[tuple[str, dict]] = []

    def async_fire(self, event: str, data: dict) -> None:
        self.fired.append((event, data))


class _Config:
    def __init__(self, base: str):
        self._base = base

    def path(self, *parts: str) -> str:
        return str(Path(self._base, *parts))


class _Hass:
    def __init__(self, base: str):
        self.config = _Config(base)
        self.bus = _Bus()
        self.data: dict = {}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class WatcherCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hass = _Hass(self.tmp.name)
        self.state_path = Path(self.tmp.name) / ".brain" / "findings_state.json"
        self.state_path.parent.mkdir(parents=True)
        REGISTRY.reset()

    def _write(self, rows, open_count=None):
        self.state_path.write_text(json.dumps({
            "ts": 1700000000,
            "open": len(rows) if open_count is None else open_count,
            "by_severity": {},
            "findings": rows,
        }), encoding="utf-8")

    def _poll(self, watcher):
        asyncio.run(watcher.async_poll())


class TestReadState(WatcherCase):
    def test_missing_file_is_none(self):
        self.state_path.unlink(missing_ok=True)
        self.assertIsNone(findings.read_findings_state(self.hass))

    def test_garbage_is_none_not_a_crash(self):
        self.state_path.write_text("{not json", encoding="utf-8")
        self.assertIsNone(findings.read_findings_state(self.hass))

    def test_rows_without_text_are_dropped(self):
        self._write([{"ts": 1, "text": "Real"}, {"ts": 2}, "junk"])
        state = findings.read_findings_state(self.hass)
        self.assertEqual([f["text"] for f in state["findings"]], ["Real"])


class TestFindingsWatcher(WatcherCase):
    def test_prime_adopts_without_announcing(self):
        """An HA restart must not replay the open list onto the bus."""
        self._write([{"ts": 1, "text": "Old problem", "severity": "serious"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])

    def test_new_finding_fires_once(self):
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()

        self._write([
            {"ts": 2, "text": "Hall battery dead", "severity": "critical",
             "entity_id": "sensor.hall_battery", "fixable": False,
             "source_title": "Device Health"},
            {"ts": 1, "text": "Old", "severity": "warning"},
        ])
        self._poll(watcher)
        # One moment, two names: `brain_finding` for every automation
        # written against it, `brain_case` for the catalogue.
        self.assertEqual([e for e, _d in self.hass.bus.fired],
                         ["brain_case", "brain_finding"])
        event, data = self.hass.bus.fired[1]
        self.assertEqual(event, "brain_finding")
        self.assertEqual(data["finding"], "Hall battery dead")
        self.assertEqual(data["severity"], "critical")
        self.assertEqual(data["entity_id"], "sensor.hall_battery")
        self.assertFalse(data["fixable"])
        # the logbook line reads as a sentence
        self.assertIn("Hall battery dead", data["message"])
        _event, case = self.hass.bus.fired[0]
        self.assertEqual(case["case_id"], "f:2")
        self.assertEqual(case["kind"], "problem")
        self.assertEqual(case["claim"], "Hall battery dead")
        self.assertEqual(case["status"], "open")
        self.assertIn("Hall battery dead", case["message"])

        # same content again: nothing new, nothing fired
        self._poll(watcher)
        self.assertEqual(len(self.hass.bus.fired), 2)

    def test_a_case_leaving_the_feed_fires_case_ended_and_nothing_else(self):
        self._write([{"ts": 1, "text": "Old", "severity": "warning",
                      "kind": "problem", "claim": "The hall sensor is dead"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)            # the first poll takes the roster
        self._write([])
        self._poll(watcher)
        self.assertEqual([e for e, _d in self.hass.bus.fired],
                         ["brain_case_ended"])
        _event, data = self.hass.bus.fired[0]
        self.assertEqual(data["case_id"], "f:1")
        self.assertEqual(data["claim"], "The hall sensor is dead")
        self.assertIn("closed", data["message"])
        # ...and never `brain_finding`, which is for a case OPENING.
        self.assertNotIn("brain_finding", [e for e, _d in self.hass.bus.fired])

    def test_a_row_that_becomes_fixed_fires_change(self):
        self._write([{"ts": 1, "text": "Porch light stuck on",
                      "severity": "warning", "status": "open"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        self._write([{"ts": 1, "text": "Porch light stuck on",
                      "severity": "warning", "status": "fixed"}])
        self._poll(watcher)
        self.assertEqual([e for e, _d in self.hass.bus.fired], ["brain_change"])
        _event, data = self.hass.bus.fired[0]
        self.assertEqual(data["status"], "fixed")
        self.assertIn("changed the house", data["message"])
        # A second poll over the same fixed row is not a second change.
        self._poll(watcher)
        self.assertEqual(len(self.hass.bus.fired), 1)

    def test_a_restart_does_not_replay_endings_either(self):
        """The roster is taken on the first poll after a prime, so a row
        that left while Home Assistant was down is not announced as
        having closed now."""
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._write([])
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])

    def test_a_settled_finding_leaves_the_watermark_quietly(self):
        """Ids leave the mirror when settled; the watcher forgets them
        without firing `brain_finding` — the add-on's settled ledger is
        what stops the same problem re-entering the list under the same
        text. What it does fire is `brain_case_ended`, once."""
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        self._write([])
        self._poll(watcher)
        self.assertEqual([e for e, _d in self.hass.bus.fired],
                         ["brain_case_ended"])
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        self._poll(watcher)
        # Back again under the same id is a case opening, not a replay.
        self.assertEqual([e for e, _d in self.hass.bus.fired][1:],
                         ["brain_case", "brain_finding"])

    def test_unreadable_state_changes_nothing(self):
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self.state_path.write_text("{torn", encoding="utf-8")
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])
        # ...and the watermark survives, so recovery doesn't replay history
        self._write([{"ts": 1, "text": "Old", "severity": "warning"}])
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])


class MirrorCase(WatcherCase):
    """Driven against the mirror the ADD-ON really writes.

    A fixture of the row shape written by hand would be a second answer to
    "what is in that file", tested against itself — which is the failure
    this repo keeps finding. So `findings_store._publish_state` writes it,
    from the store, exactly as the panel does on every change.
    """

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                     findings_store.SETTLED_FILE, findings_store.STATE_FILE)
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.INBOX_DIR = base / "inbox"
        findings_store.SETTLED_FILE = base / "settled.json"
        # The same path the integration reads, so nothing here agrees with
        # itself about where the mirror is.
        findings_store.STATE_FILE = Path(findings.findings_state_path(self.hass))
        self.addCleanup(self._restore)

    def _restore(self):
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old

    def file(self, text, *, severity="warning", status="open", **fields):
        entry, _created = findings_store.add(
            text, severity=severity, source="check:dev.unavailable",
            source_title="Devices", **fields)
        if status != "open":
            findings_store.set_status(entry["ts"], status)
        return entry


class TestFindingsBecomeRepairs(MirrorCase):
    def test_a_real_mirror_row_raises_one_issue(self):
        entry = self.file("The hall sensor has not reported since Tuesday",
                          severity="serious", detail="last seen 3 Sep",
                          fix="Re-pair it")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)

        self.assertEqual(len(REGISTRY.created), 1)
        row = REGISTRY.created[0]
        self.assertEqual(row["issue_id"], f"finding_{entry['ts']}")
        self.assertEqual(row["domain"], "brain")
        self.assertTrue(row["is_fixable"])
        self.assertEqual(row["translation_key"], "finding")
        self.assertEqual(row["severity"], "error")  # serious -> ERROR
        placeholders = row["translation_placeholders"]
        self.assertEqual(placeholders["text"], entry["text"])
        self.assertEqual(placeholders["detail"], "last seen 3 Sep")
        self.assertEqual(placeholders["fix"], "Re-pair it")
        self.assertEqual(placeholders["source_title"], "Devices")
        self.assertEqual(row["data"]["ts"], entry["ts"])

    def test_the_issue_is_raised_even_though_the_event_was_not(self):
        """An issue is state and an event is news.

        `prime` adopts the open list so a restart does not replay it onto
        the bus — and the Repairs entry for that same row still has to
        exist, because Home Assistant threw away the non-persistent issues
        when it booted.
        """
        self.file("Front door battery is low")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        self.assertEqual(self.hass.bus.fired, [])
        self.assertEqual(len(REGISTRY.created), 1)

    def test_a_restart_re_creates_what_is_still_waiting(self):
        entry = self.file("Front door battery is low")
        first = findings.FindingsWatcher(self.hass)
        first.prime()
        self._poll(first)
        REGISTRY.reset()

        # A restart: a brand new watcher over the same house, and nothing
        # about the mirror has changed.
        second = findings.FindingsWatcher(self.hass)
        second.prime()
        self._poll(second)
        self.assertEqual([r["issue_id"] for r in REGISTRY.created],
                         [f"finding_{entry['ts']}"])

    def test_an_unchanged_row_is_not_re_raised_every_minute(self):
        self.file("Front door battery is low")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        REGISTRY.reset()
        self._poll(watcher)
        self._poll(watcher)
        self.assertEqual(REGISTRY.created, [])
        self.assertEqual(REGISTRY.deleted, [])

    def test_a_refreshed_detail_re_raises_it(self):
        """A check writes a stable text and a moving number in `detail`.

        A dialog quoting last week's figure is a reading nothing can
        correct, so the issue follows the sentence rather than the id.
        """
        entry = self.file("Front door battery is low", detail="9 days left")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        REGISTRY.reset()

        findings_store.refresh_details([{
            "text": "Front door battery is low", "detail": "3 days left",
            "source": "check:dev.unavailable"}])
        self._poll(watcher)
        self.assertEqual(len(REGISTRY.created), 1)
        self.assertEqual(
            REGISTRY.created[0]["translation_placeholders"]["detail"],
            "3 days left")
        self.assertEqual(REGISTRY.created[0]["issue_id"],
                         f"finding_{entry['ts']}")

    def test_an_answered_finding_takes_its_issue_with_it(self):
        entry = self.file("Front door battery is low")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        REGISTRY.reset()

        findings_store.settle_and_clear(entry["ts"], "fixed")
        self._poll(watcher)
        self.assertEqual(REGISTRY.deleted, [f"finding_{entry['ts']}"])
        self.assertNotIn(f"finding_{entry['ts']}", REGISTRY.live())

    def test_info_raises_nothing_at_all(self):
        """Repairs is the list of things that need a person.

        An `info` finding is still on the tab, still counted, still an
        event — and a Repairs row nobody has to act on is how the page
        that holds the row that matters stops being read.
        """
        self.file("Nine automations have no description", severity="info")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        self.assertEqual(REGISTRY.created, [])
        # ...and it did reach the mirror, so this is a decision rather
        # than the row simply not being there.
        state = findings.read_findings_state(self.hass)
        self.assertEqual(len(state["findings"]), 1)

    def test_work_in_flight_is_not_a_decision(self):
        """`fixing` and `fixed` are on the mirror and raise no issue.

        The first is brAIn running a repair right now; the second is news
        to read, whose one honest answer ("Got it") is not a verb a
        request can carry.
        """
        running = self.file("A", status="fixing")
        done = self.file("B", status="fixed")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        raised = {r["issue_id"] for r in REGISTRY.created}
        self.assertNotIn(f"finding_{running['ts']}", raised)
        self.assertNotIn(f"finding_{done['ts']}", raised)
        self.assertEqual(raised, set())

    def test_needs_you_and_failed_are_decisions(self):
        asked = self.file("A", status="needs_you")
        failed = self.file("B", status="failed")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        self.assertEqual({r["issue_id"] for r in REGISTRY.created},
                         {f"finding_{asked['ts']}", f"finding_{failed['ts']}"})

    def test_the_cap_holds_and_takes_the_oldest(self):
        """A noisy house must not fill somebody's Repairs page.

        Oldest first: the row that has waited longest is the one at risk
        of never being looked at, and taking the newest would churn the
        set on every pass.
        """
        rows = [self.file(f"Problem {n:02d}")
                for n in range(findings.MAX_REPAIR_ISSUES + 6)]
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        raised = [r["issue_id"] for r in REGISTRY.created]
        self.assertEqual(len(raised), findings.MAX_REPAIR_ISSUES)
        oldest = sorted(r["ts"] for r in rows)[:findings.MAX_REPAIR_ISSUES]
        self.assertEqual(set(raised), {f"finding_{ts}" for ts in oldest})

    def test_an_answer_holds_the_issue_down_until_the_addon_applies_it(self):
        """The press writes a request; the row stays until it is drained.

        Without the memory the very next poll would put the entry back,
        which reads as a dialog that reappears the moment it is closed.
        """
        entry = self.file("Front door battery is low")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        REGISTRY.reset()

        findings.mark_answered(self.hass, entry["ts"])
        self._poll(watcher)
        self.assertEqual(REGISTRY.deleted, [f"finding_{entry['ts']}"])
        REGISTRY.reset()
        self._poll(watcher)                      # still on the mirror
        self.assertEqual(REGISTRY.created, [])

        # The add-on drains the request: the row goes, and the id is
        # forgotten rather than suppressing the same problem for ever.
        findings_store.settle_and_clear(entry["ts"], "fixed")
        self._poll(watcher)
        self.assertEqual(
            self.hass.data["brain"][findings.ANSWERED_KEY], set())

    def test_an_unreadable_registry_does_not_stop_the_events(self):
        """A Repairs page that could not be updated is not a reason to
        stop announcing findings — they are two claims, and only one of
        them broke."""
        self.file("Old")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        REGISTRY.reset()

        boom = self.file("Hall sensor silent", severity="critical")
        original = REGISTRY.async_create_issue

        def explode(*args, **kwargs):
            raise RuntimeError("registry is busy")

        REGISTRY.async_create_issue = explode
        try:
            self._poll(watcher)
        finally:
            REGISTRY.async_create_issue = original
        self.assertEqual([d["finding"] for e, d in self.hass.bus.fired
                          if e == "brain_finding"],
                         [boom["text"]])

    def test_unloading_takes_the_issues_with_it(self):
        entry = self.file("Front door battery is low")
        watcher = findings.FindingsWatcher(self.hass)
        watcher.prime()
        self._poll(watcher)
        REGISTRY.reset()
        watcher.clear_issues()
        self.assertEqual(REGISTRY.deleted, [f"finding_{entry['ts']}"])


if __name__ == "__main__":
    unittest.main()
