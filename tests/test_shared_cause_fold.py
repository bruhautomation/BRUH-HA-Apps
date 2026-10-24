#!/usr/bin/env python3
"""One cause is one row, with every device it reaches listed under it.

Seen on a house: four Wi-Fi devices that were connected but not reachable
were one finding — and two of those devices each had their own finding as
well; a sensor that went offline and "the automation failed, the device did
not respond" were the same fault shown twice. The folds keyed on one
entity (the subject fold, the cross-producer fold, `_check_host_key`) could
not see either, because a shared cause names several entities and an
automation's row is filed under the automation.

So two more folds, over the live list, with the existing refusals:

  * a row that diagnoses a shared cause (the Resident's case or the
    overnight check's row) whose evidence names two or more devices takes
    in the live rows about each of them — they leave the list and the
    shared row lists the device;
  * a model-written row about an automation or a script whose evidence
    names exactly one device folds into that device's own live row: the
    device being offline is the cause, the automation failing the symptom.

Never a safety, security or correction row; never a row brAIn fixed;
never a row somebody has replied under or put back; never into a row that
is less visible than the one folded.

Driven over the real store.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "brain" / "panel"))

import findings_store  # noqa: E402
import triage  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402

DEVICES = ("sensor.hall_plug_power", "climate.landing",
           "sensor.loft_plug_power", "switch.garage_heater")


def offline(eid: str, **over) -> dict:
    return {"text": f"{eid} has been unavailable for six hours",
            "entity_id": eid, "source": "check:dev.unavailable",
            "source_title": "Devices offline", "severity": "warning",
            "detail": "unavailable since 03:10", **over}


def wifi_case(**over) -> dict:
    return {"text": "Four Wi-Fi devices are connected but not reachable",
            "claim": "Four Wi-Fi devices are connected but not reachable",
            "detail": "They share one access point.", "kind": "problem",
            "severity": "serious", "entity_id": "",
            "evidence": [{"entity": e, "value": "unavailable", "when": "03:10"}
                         for e in DEVICES], **over}


def open_rows() -> list[dict]:
    return [f for f in findings_store.list_all()
            if f["status"] in ("open", "needs_you", "triaging")]


def named(row: dict) -> set[str]:
    out = {row.get("entity_id") or ""}
    out |= {e.get("entity") or "" for e in row.get("evidence") or []}
    out.discard("")
    return out


def show(rows: list[dict]) -> None:
    findings_store.record_triage({r["ts"]: ("elevated", "real") for r in rows})


class TestASharedCauseTakesInItsDevices(FoldCase):

    def test_rows_about_its_devices_fold_into_the_shared_cause(self):
        rows = findings_store.add_many(triage.gate(
            [offline(DEVICES[0]), offline(DEVICES[1])]))
        show(rows)
        case = findings_store.add_case(wifi_case(), run_id="look-1")
        self.assertIsNotNone(case)
        live = open_rows()
        self.assertEqual([r["ts"] for r in live], [case["ts"]])
        self.assertEqual(named(live[0]), set(DEVICES))

    def test_a_device_reported_again_lands_on_the_shared_row(self):
        case = findings_store.add_case(wifi_case(), run_id="look-1")
        again = findings_store.add_many(triage.gate([offline(DEVICES[2])]))
        self.assertEqual(again, [])
        self.assertEqual([r["ts"] for r in open_rows()], [case["ts"]])

    def test_no_device_is_named_as_a_problem_twice(self):
        show(findings_store.add_many(triage.gate(
            [offline(e) for e in DEVICES[:3]])))
        findings_store.add_case(wifi_case(), run_id="look-1")
        seen: dict[str, int] = {}
        for row in open_rows():
            for eid in named(row):
                seen[eid] = seen.get(eid, 0) + 1
        self.assertTrue(all(n == 1 for n in seen.values()), seen)

    def test_the_shared_row_says_how_bad_the_worst_of_them_was(self):
        show(findings_store.add_many(triage.gate(
            [offline(DEVICES[0], severity="critical")])))
        case = findings_store.add_case(wifi_case(), run_id="look-1")
        self.assertEqual(findings_store.get(case["ts"])["severity"],
                         "critical")


class TestAnAutomationThatFailedBecauseADeviceIsOffline(FoldCase):

    def test_the_automation_row_folds_into_the_device_row(self):
        [device] = findings_store.add_many(triage.gate(
            [offline("light.porch")]))
        show([device])
        findings_store.add_case({
            "text": "The porch automation failed: the light did not respond",
            "claim": "The porch automation failed: the light did not respond",
            "kind": "problem", "severity": "warning",
            "entity_id": "automation.porch_lights",
            "evidence": [{"entity": "light.porch", "value": "unavailable",
                          "when": "19:02"}]}, run_id="look-2")
        live = open_rows()
        self.assertEqual([r["ts"] for r in live], [device["ts"]])
        self.assertIn("automation.porch_lights", named(live[0]))

    def test_a_check_about_an_automation_is_its_own_claim(self):
        # `auto.trigger_unavailable` is deliberately separate from the
        # device row (CLAUDE.md): it answers why the automation stopped.
        show(findings_store.add_many(triage.gate([offline("light.porch")])))
        show(findings_store.add_many(triage.gate([{
            "text": "Porch lights can never fire: its trigger is unavailable",
            "entity_id": "automation.porch_lights",
            "source": "check:auto.trigger_unavailable",
            "evidence": [{"entity": "light.porch", "value": "unavailable"}],
            "severity": "warning"}])))
        self.assertEqual(len(open_rows()), 2)


class TestWhatIsNeverFolded(FoldCase):

    def test_a_safety_row_stands(self):
        rows = findings_store.add_many(triage.gate([{
            "text": "Leak detected under the sink", "source": "safety",
            "entity_id": DEVICES[0], "severity": "critical"}]))
        show(rows)
        findings_store.add_case(wifi_case(), run_id="look-1")
        self.assertEqual(len(open_rows()), 2)

    def test_a_row_somebody_replied_under_stands(self):
        rows = findings_store.add_many(triage.gate([offline(DEVICES[0])]))
        show(rows)
        findings_store.append_thread(rows[0]["ts"], "you", "it is unplugged")
        findings_store.add_case(wifi_case(), run_id="look-1")
        self.assertEqual(len(open_rows()), 2)

    def test_a_fixed_row_stands(self):
        rows = findings_store.add_many(triage.gate([offline(DEVICES[0])]))
        findings_store.set_status(rows[0]["ts"], "fixed")
        findings_store.add_case(wifi_case(), run_id="look-1")
        self.assertIsNotNone(findings_store.get(rows[0]["ts"]))

    def test_a_held_shared_row_does_not_hide_an_open_one(self):
        rows = findings_store.add_many(triage.gate([offline(DEVICES[0])]))
        show(rows)
        [held] = findings_store.add_many(triage.gate([{
            **wifi_case(), "source": "sre"}]))
        findings_store.record_triage({held["ts"]: ("held", "passed")})
        findings_store.add_many(triage.gate([offline(DEVICES[1])]))
        self.assertIsNotNone(findings_store.get(rows[0]["ts"]))
        self.assertEqual(findings_store.get(rows[0]["ts"])["status"], "open")


if __name__ == "__main__":
    unittest.main()
