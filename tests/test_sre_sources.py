#!/usr/bin/env python3
"""The overnight check names what a log line came from, and who made a
failed call.

Two findings from real houses:

* #352 — "Something you set up still controls the switch… seven times,
  something the household set up tried to control it", with a fix to
  "remove it from whatever still controls it", while the row's look named
  the automation and the script. A log line about a call to an
  unavailable entity now carries which automations, scripts and scenes
  made those calls and how many each (`called_by`), and a cause citing
  one says so in its detail and fix in their names.
* #350 — "Errors keep appearing in the log", blaming the dashboard and
  Morph, while the only ERROR lines were the Wemo integration failing to
  reach a device the owner had set aside. A log line is now traced to its
  integration through the loggers each integration's manifest declares and
  to its device through the address it names; a cause's prose may not
  blame the dashboard unless a cited line came from the frontend; a fix
  left empty is written for the line's own source; and lines about a
  device the owner set aside on the offline check are held back.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import sre  # noqa: E402
from test_sre import NOW, PassCase, collected  # noqa: E402

VAGUE = ("something you set up", "something the household set up",
         "whatever still controls it")


def log_row(message, logger, level="WARNING", count=7):
    return {"name": logger, "message": [message], "level": level,
            "source": ["x.py", 1], "timestamp": NOW - 60, "count": count,
            "first_occurred": NOW - 20000}


MISSING = "Referenced entities switch.porch_heater are missing or not currently available"


def missing_house(log, **over):
    return collected(
        log=log, zha=[],
        entities=[{"entity_id": "switch.porch_heater", "device_id": "dev-ph",
                   "platform": "tplink"}],
        devices=[{"id": "dev-ph", "name": "Porch heater plug"}],
        states={
            "switch.porch_heater": {"state": "unavailable", "attributes": {
                "friendly_name": "Porch heater"}},
            "automation.morning_heat": {"state": "on", "attributes": {
                "id": "a1", "friendly_name": "Morning heat"}},
            "script.warm_porch": {"state": "off", "attributes": {
                "friendly_name": "Warm porch"}},
        },
        automations=[{"id": "a1", "alias": "Morning heat", "actions": [
            {"action": "switch.turn_on",
             "target": {"entity_id": "switch.porch_heater"}}]}],
        scripts={"warm_porch": {"alias": "Warm porch", "sequence": [
            {"action": "switch.turn_on",
             "target": {"entity_id": "switch.porch_heater"}}]}},
        **over)


VAGUE_CAUSE = {"title": "Something you set up still controls the switch",
               "detail": "Seven times, something the household set up tried "
                         "to control the Porch heater.",
               "fix": "Remove it from whatever still controls it."}


def cause_row(dig, **cause):
    recs = [r["id"] for r in dig["records"] if r["kind"] == "log"][:1]
    parsed = sre.parse_causes({"causes": [{"records": recs, **cause}]}, dig)
    return sre.rows(parsed["causes"], dig, {"anchors": {}}, NOW)[0]


class TestAFailedCallSaysWhoMadeIt(unittest.TestCase):
    def test_the_callers_found_in_the_config_with_their_runs(self):
        dig = sre.digest(missing_house(
            [log_row(MISSING, "homeassistant.helpers.service")],
            caller_runs={"automation.morning_heat": 5,
                         "script.warm_porch": 2}), NOW)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertEqual(rec["called_by"], [
            {"name": "Morning heat", "kind": "automation", "calls": 5},
            {"name": "Warm porch", "kind": "script", "calls": 2}])

    def test_the_caller_the_logger_names_carries_the_lines_count(self):
        dig = sre.digest(missing_house(
            [log_row(MISSING, "homeassistant.components.automation."
                              "morning_heat")]), NOW)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertEqual(rec["called_by"], [
            {"name": "Morning heat", "kind": "automation", "calls": 7}])

    def test_the_finding_names_them_and_says_nothing_vague(self):
        dig = sre.digest(missing_house(
            [log_row(MISSING, "homeassistant.helpers.service")],
            caller_runs={"automation.morning_heat": 5,
                         "script.warm_porch": 2}), NOW)
        row = cause_row(dig, **VAGUE_CAUSE)
        prose = " ".join((row["text"], row["detail"], row["fix"])).lower()
        for words in VAGUE:
            self.assertNotIn(words, prose)
        self.assertIn("Morning heat (automation, 5 calls)", row["detail"])
        self.assertIn("Warm porch (script, 2 calls)", row["detail"])
        self.assertIn("Morning heat", row["fix"])
        self.assertIn("Warm porch", row["fix"])
        self.assertIn("Porch heater", row["text"])


WEMO = log_row("Error communicating with 192.168.1.50: timed out",
               "pywemo.ouimeaux_device.api", level="ERROR", count=40)
FRONT = log_row("Uncaught TypeError in morph-panel card",
                "frontend.js.modern.202610230", count=3)


def wemo_house(**over):
    return collected(
        log=[WEMO, FRONT], zha=[],
        entities=[{"entity_id": "switch.patio_wemo", "device_id": "dev-wemo",
                   "platform": "wemo"}],
        devices=[{"id": "dev-wemo", "name": "Patio Wemo",
                  "configuration_url": "http://192.168.1.50:49153/setup.xml"}],
        states={"switch.patio_wemo": {"state": "unavailable", "attributes": {
            "friendly_name": "Patio Wemo"}}},
        manifests=[{"domain": "wemo", "name": "Belkin WeMo",
                    "loggers": ["pywemo"]}],
        **over)


BLAME = {"title": "Your Morph dashboard keeps throwing errors",
         "detail": "The dashboard's custom card fails to load in the "
                   "browser. Errors repeat through the night.",
         "fix": "Reload the dashboard in your browser."}


class TestALogLineIsTracedToItsSource(unittest.TestCase):
    def setUp(self):
        self.dig = sre.digest(wemo_house(), NOW)
        self.wemo = next(r for r in self.dig["records"]
                         if r["kind"] == "log" and r["level"] == "ERROR")

    def test_the_integration_comes_from_its_manifests_loggers(self):
        self.assertEqual(self.wemo["integration"], "wemo")

    def test_the_device_comes_from_the_address_the_line_names(self):
        self.assertEqual(self.wemo["devices"], ["dev-wemo"])

    def test_the_finding_names_the_source_not_the_dashboard(self):
        row = cause_row(self.dig, **BLAME)
        prose = " ".join((row["text"], row["detail"], row["fix"])).lower()
        for words in ("dashboard", "morph", "browser"):
            self.assertNotIn(words, prose)
        self.assertIn("Patio Wemo", row["text"])
        self.assertIn("Belkin WeMo", row["text"])
        self.assertIn("Patio Wemo", row["fix"])
        self.assertEqual(row["entity_id"], "switch.patio_wemo")

    def test_the_evidence_names_the_logger(self):
        row = cause_row(self.dig, **BLAME)
        self.assertIn("pywemo", row["evidence"][0]["value"])

    def test_a_cause_citing_a_frontend_line_may_say_dashboard(self):
        front = next(r["id"] for r in self.dig["records"]
                     if r["kind"] == "log" and r["level"] == "WARNING")
        parsed = sre.parse_causes({"causes": [{**BLAME, "records": [front]}]},
                                  self.dig)
        self.assertIn("dashboard", parsed["causes"][0]["title"].lower())


class TestASetAsideDeviceIsHeldBack(unittest.TestCase):
    def test_its_lines_leave_the_digest(self):
        dig = sre.digest(wemo_house(), NOW, set_aside={"switch.patio_wemo"})
        self.assertFalse(any(r["kind"] == "log" and r["level"] == "ERROR"
                             for r in dig["records"]))
        self.assertFalse(sre.worth_a_run(dig))


class TestThroughThePass(PassCase):
    def setUp(self):
        super().setUp()
        journal = self.server.journal
        self._journal = journal.JOURNAL_FILE
        journal.JOURNAL_FILE = str(Path(self.tmp.name) / "journal.jsonl")

    def tearDown(self):
        self.server.journal.JOURNAL_FILE = self._journal
        super().tearDown()

    def test_a_snoozed_offline_row_holds_its_devices_lines(self):
        fs = self.server.findings_store
        [row] = fs.add_many([{"text": "Patio Wemo has been unavailable for "
                                      "more than a day",
                              "severity": "serious",
                              "source": "check:dev.unavailable",
                              "entity_id": "switch.patio_wemo",
                              "status": "open"}])
        fs.snooze(row["ts"], NOW + 10 ** 9)
        self.collected = wemo_house()
        self.reply([{**BLAME, "records": [self.wemo_id()]}])
        self.run_pass()
        self.assertEqual(self.calls, [])
        self.assertEqual(self.rows(), [])

    def wemo_id(self):
        return next(r["id"] for r in sre.digest(wemo_house(), NOW)["records"]
                    if r["kind"] == "log" and r["level"] == "ERROR")


if __name__ == "__main__":
    unittest.main()
