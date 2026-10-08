"""A print that finished, read from the printer's own status.

`chore.waiting` reads a power sensor's shape, and a 3D printer whose
integration publishes a job status but no power sensor was invisible to
it: brAIn could not say "the print has finished and is waiting to be
taken off", which is exactly what somebody asked it. `chore.job_done`
reads the status the device's own integration publishes — a TRANSITION
from a running word to a finished word, never a finished word alone,
because a status that has said `finish` since Tuesday (or since a
restart) is not a job that ended.

Every case here is about not being noisier than the check it sits
beside: silent on the clean house, silent a couple of minutes after the
finish (somebody is standing there), silent on yesterday's job, silent
on a status that never ran, silent on anything that is not a chore, and
the power path exactly as it was.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
from checks import chores  # noqa: E402

NOW = 1_756_800_000.0
EID = "sensor.workshop_printer_print_status"


def iso(seconds_ago: float) -> str:
    return dt.datetime.fromtimestamp(
        NOW - seconds_ago, tz=dt.timezone.utc).isoformat()


def rows(spec: list[tuple[str, float]], eid: str = EID) -> list[dict]:
    """`[(state, minutes_ago), ...]` as minimal history rows, oldest first."""
    out = []
    for i, (state, ago) in enumerate(spec):
        row = {"state": state, "last_changed": iso(ago * 60)}
        if i == 0:
            row["entity_id"] = eid
        out.append(row)
    return out


def printer_house(history=None, *, state="finish", changed_min=40.0,
                  name="Workshop 3D printer Print status",
                  available=True, extra_states=None) -> dict:
    """A house with a printer that publishes a status and no power sensor."""
    if history is None:
        history = rows([("idle", 300), ("printing", 200),
                        ("finish", changed_min)])
    states = {EID: {"state": state, "last_changed": iso(changed_min * 60),
                    "attributes": {"friendly_name": name,
                                   "device_class": "enum"}}}
    states.update(extra_states or {})
    snap = {
        "now": NOW,
        "available": {"states": True, "registry": True,
                      "job_status": available},
        "errors": {},
        "states": states,
        "entities": [{"entity_id": e, "disabled_by": None} for e in states],
        "devices": [], "areas": [],
        "job_status": {EID: history} if available else {},
    }
    return snap


class TestTheFinishedPrint(unittest.TestCase):
    def test_a_print_that_finished_forty_minutes_ago_is_one_chore(self):
        got = chores.job_done(printer_house(), NOW)
        self.assertEqual(len(got), 1, got)
        row = got[0]
        self.assertEqual(row["entity_id"], EID)
        self.assertIn("printer", row["text"].lower())
        self.assertIn("finished", row["text"].lower())
        self.assertFalse(row["fixable"])
        self.assertEqual(row["severity"], "info")
        self.assertIn("40 minutes ago", row["detail"])

    def test_it_reaches_the_findings_through_run_all(self):
        result = checks.run_all(printer_house(), NOW, only=["chore.job_done"])
        self.assertEqual(result["ran"], ["chore.job_done"])
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(result["findings"][0]["source"],
                         "check:chore.job_done")

    def test_the_text_is_stable_and_the_minutes_live_in_detail(self):
        one = chores.job_done(printer_house(changed_min=40.0), NOW)[0]
        two = chores.job_done(printer_house(changed_min=150.0), NOW)[0]
        self.assertEqual(one["text"], two["text"])
        self.assertNotEqual(one["detail"], two["detail"])

    def test_the_fix_says_brAIn_cannot_see_it_taken_off(self):
        row = chores.job_done(printer_house(), NOW)[0]
        self.assertIn("cannot see", row["fix"])

    def test_a_restart_in_between_does_not_hide_the_finish(self):
        # finish -> unavailable (a restart) -> finish: the live last
        # change is two minutes old, the job ended forty minutes ago.
        hist = rows([("printing", 200), ("finish", 40), ("unavailable", 3),
                     ("finish", 2)])
        got = chores.job_done(printer_house(hist, changed_min=2.0), NOW)
        self.assertEqual(len(got), 1)
        self.assertIn("40 minutes ago", got[0]["detail"])

    def test_a_washer_status_is_a_chore_too(self):
        eid = "sensor.washer_operation_state"
        hist = rows([("Run", 120), ("Finished", 45)], eid=eid)
        snap = printer_house(extra_states={eid: {
            "state": "Finished", "last_changed": iso(45 * 60),
            "attributes": {"friendly_name": "Washer Operation state"}}})
        del snap["states"][EID]
        snap["entities"] = [{"entity_id": eid, "disabled_by": None}]
        snap["job_status"] = {eid: hist}
        got = chores.job_done(snap, NOW)
        self.assertEqual(len(got), 1)
        self.assertIn("washing machine", got[0]["text"].lower())


class TestTheSilences(unittest.TestCase):
    def test_the_clean_fixture_stays_silent_and_the_check_runs(self):
        from test_house_checks import house
        result = checks.run_all(house(), NOW)
        self.assertIn("chore.job_done", result["ran"])
        self.assertEqual(result["findings"], [])

    def test_somebody_standing_at_the_printer_hears_nothing(self):
        got = chores.job_done(printer_house(changed_min=2.0), NOW)
        self.assertEqual(got, [])

    def test_yesterday_s_print_is_not_a_chore(self):
        ago = (chores.STALE_HOURS + 2) * 60
        hist = rows([("printing", ago + 300), ("finish", ago)])
        got = chores.job_done(printer_house(hist, changed_min=ago), NOW)
        self.assertEqual(got, [])

    def test_a_status_that_never_ran_is_not_a_finish(self):
        # Said `finish` since before the window, or since a restart.
        for hist in (rows([("finish", 900)]),
                     rows([("finish", 900), ("unavailable", 41),
                           ("finish", 40)]),
                     rows([("idle", 300), ("finish", 40)]),
                     rows([("failed", 100), ("finish", 40)])):
            self.assertEqual(chores.job_done(printer_house(hist), NOW), [],
                             hist)

    def test_a_job_that_failed_or_is_still_running_is_not_a_finish(self):
        for state in ("failed", "printing", "idle", "pause"):
            got = chores.job_done(printer_house(state=state), NOW)
            self.assertEqual(got, [], state)

    def test_something_that_is_not_a_chore_says_nothing(self):
        # The guess, in the cheap direction: a label printer, a paper
        # printer, an update, a backup, an oven — all "finish" things
        # nobody has to go and take something off.
        for name in ("Label printer status", "Office printer",
                     "Oven program", "Backup status", "Firmware update",
                     "Robot vacuum status"):
            got = chores.job_done(printer_house(name=name), NOW)
            self.assertEqual(got, [], name)

    def test_a_number_or_a_switch_is_not_a_status(self):
        for eid in ("switch.printer_finish", "binary_sensor.printer_done"):
            snap = printer_house()
            snap["states"] = {eid: snap["states"][EID]}
            snap["entities"] = [{"entity_id": eid, "disabled_by": None}]
            snap["job_status"] = {eid: snap["job_status"][EID]}
            self.assertEqual(chores.job_done(snap, NOW), [], eid)

    def test_a_disabled_entity_is_not_a_chore(self):
        snap = printer_house()
        snap["entities"][0]["disabled_by"] = "user"
        self.assertEqual(chores.job_done(snap, NOW), [])

    def test_history_that_could_not_be_read_is_not_a_quiet_house(self):
        # A candidate with no history behind it: the check is SKIPPED, so
        # it clears nothing it filed last pass.
        result = checks.run_all(printer_house(available=False), NOW,
                                only=["chore.job_done"])
        self.assertEqual(result["ran"], [])
        self.assertIn("chore.job_done", result["skipped"])
        self.assertEqual(result["errors"], {})

    def test_past_the_cap_it_says_nothing_at_all(self):
        snap = printer_house()
        snap["states"], snap["entities"], snap["job_status"] = {}, [], {}
        for i in range(chores.MAX_ROWS + 1):
            eid = f"sensor.printer{i}_print_status"
            snap["states"][eid] = {
                "state": "finish", "last_changed": iso(40 * 60),
                "attributes": {"friendly_name": f"3D printer {i} Print status"}}
            snap["entities"].append({"entity_id": eid, "disabled_by": None})
            snap["job_status"][eid] = rows([("printing", 200),
                                            ("finish", 40)], eid=eid)
        self.assertEqual(chores.job_done(snap, NOW), [])

    def test_a_correction_stands_it_down(self):
        snap = printer_house()
        snap["corrections"] = {"entity": {EID: {"chore.job_done": {
            "text": "we leave prints on the bed"}}}}
        self.assertEqual(chores.job_done(snap, NOW), [])

    def test_a_chore_is_never_urgent(self):
        import notify_router
        self.assertEqual(
            notify_router.urgency_of({"source": "check:chore.job_done"}),
            "whenever")


class TestThePowerPathIsUnchanged(unittest.TestCase):
    def test_a_printer_is_not_a_power_chore(self):
        # The printer kind is the status check's, and only its: a plug
        # called "3D printer" draws like anything else with a heater.
        self.assertEqual(chores.kind_of("3D printer plug power"), "")
        self.assertEqual(chores.kind_of("Washing machine plug"), "washer")

    def test_chore_waiting_needs_what_it_always_needed(self):
        check = checks.get_check("chore.waiting")
        self.assertEqual(tuple(check["needs"]),
                         ("states", "registry", "appliances"))


class TestCandidates(unittest.TestCase):
    def test_only_a_finished_status_on_a_chore_inside_the_window(self):
        snap = printer_house()
        self.assertEqual(chores.job_candidates(snap["states"], NOW), [EID])
        old = printer_house(changed_min=(chores.STALE_HOURS + 1) * 60)
        self.assertEqual(chores.job_candidates(old["states"], NOW), [])
        busy = printer_house(state="printing")
        self.assertEqual(chores.job_candidates(busy["states"], NOW), [])

    def test_the_fetch_is_bounded(self):
        states = {}
        for i in range(chores.JOB_FETCH_MAX + 5):
            states[f"sensor.p{i}_print_status"] = {
                "state": "finish", "last_changed": iso(40 * 60 + i),
                "attributes": {"friendly_name": f"3D printer {i}"}}
        self.assertEqual(len(chores.job_candidates(states, NOW)),
                         chores.JOB_FETCH_MAX)


class TestTheCollector(unittest.TestCase):
    def test_it_asks_only_for_the_candidates_and_keys_the_answer(self):
        from checks import snapshot
        import ha_data
        seen = {}

        async def fake_get(session, path, timeout=30, params=None):
            seen["params"] = params
            return [rows([("printing", 200), ("finish", 40)])]

        with mock.patch.object(ha_data, "_rest_get", fake_get):
            got = asyncio.run(snapshot._job_history(
                None, printer_house()["states"], NOW))
        self.assertEqual(list(got), [EID])
        self.assertIn(EID, seen["params"]["filter_entity_id"])
        self.assertIn("end_time", seen["params"])

    def test_nothing_to_ask_asks_nothing(self):
        from checks import snapshot
        import ha_data

        async def boom(*a, **k):
            raise AssertionError("should not fetch")

        with mock.patch.object(ha_data, "_rest_get", boom):
            got = asyncio.run(snapshot._job_history(None, {}, NOW))
        self.assertEqual(got, {})

    def test_a_refusal_is_none(self):
        from checks import snapshot
        import ha_data

        async def refuse(*a, **k):
            return {"message": "no"}

        with mock.patch.object(ha_data, "_rest_get", refuse):
            got = asyncio.run(snapshot._job_history(
                None, printer_house()["states"], NOW))
        self.assertIsNone(got)


class TestTickingItOffSticks(unittest.TestCase):
    """The status says `finish` until the next job, whatever was taken off
    the bed — so a re-run cannot tell a done chore from an undone one,
    and must not put it back on the list saying it came back."""

    def setUp(self):
        import findings_store
        import todo_store
        self.fs, self.ts = findings_store, todo_store
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE, todo_store.TODO_FILE,
                     todo_store.STATE_FILE)
        findings_store.FINDINGS_FILE = root / "findings.json"
        findings_store.SETTLED_FILE = root / "settled.json"
        findings_store.STATE_FILE = root / "nowhere" / ".brain" / "s.json"
        todo_store.TODO_FILE = root / "todo.json"
        todo_store.STATE_FILE = root / "nowhere" / ".brain" / "t.json"

    def tearDown(self):
        (self.fs.FINDINGS_FILE, self.fs.SETTLED_FILE, self.fs.STATE_FILE,
         self.ts.TODO_FILE, self.ts.STATE_FILE) = self._old
        self.tmp.cleanup()

    def test_a_done_print_chore_is_not_reopened(self):
        source = "check:chore.job_done"
        text = chores.job_done(printer_house(), NOW)[0]["text"]
        key = self.fs.normalize(text)
        item = self.ts.add(text, origin="finding", source=source,
                           source_title="Chore", finding_key=key)
        self.ts.complete(item["id"], now=time.time() - 3 * 3600)
        self.fs.clear_resolved({source}, {key})
        self.assertEqual(self.ts.get(item["id"])["status"], "done")


if __name__ == "__main__":
    unittest.main()
