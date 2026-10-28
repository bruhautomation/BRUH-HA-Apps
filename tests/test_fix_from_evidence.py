#!/usr/bin/env python3
"""A finding's "what to do" names what brAIn read, or says nothing.

A real house's log-error findings carried canned fixes that did not fit
the evidence: a Music Assistant connection error, with one device failing,
was told "Restart the router or DNS server"; an integration error got
"check that integration's settings, or report it to its author"; a plug
finding said "check that it is switched on" though brAIn reads that plug;
and "Stop the pump now" stood on one reading of -3.6 psi.

The per-category sentences are gone. Now:

* the overnight check's fallback fix is made of what it read (the device's
  state now, how many of its integration's other entities answer), or is
  empty (`sre._evidence_fix`);
* a fix sentence telling the owner to check what brAIn can read itself
  (switched on, powered, reachable, its state, a log) goes
  (`house_words.without_self_checks`), and so does one blaming the network
  (router, DNS, internet) when the integration's other devices answer;
* the dehumidifier check says the plug state and draw it read;
* urgent wording stands only when two readings agree
  (`house_words.calm`), on every model-written row.

The examples are not the house's: a media player integration with one
player failing, a garage freezer read once at -40 °F.
"""

import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import checks  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import sre  # noqa: E402
from test_dehumidifier_stopped import NOW as DNOW, snap as dehum_snap  # noqa: E402
from test_sre import NOW, collected  # noqa: E402

ROKU = "homeassistant.components.roku"


def roku_house(message, players_ok=2):
    ents, states, devices = [], {}, []
    names = ["Kitchen Roku", "Den Roku", "Bedroom Roku", "Office Roku"]
    for i, name in enumerate(names[:players_ok + 1]):
        eid = "media_player." + name.lower().replace(" ", "_")
        ents.append({"entity_id": eid, "device_id": f"dev-{i}",
                     "platform": "roku"})
        devices.append({"id": f"dev-{i}", "name": name})
        states[eid] = {"state": "unavailable" if i == 0 else "idle",
                       "attributes": {"friendly_name": name}}
    log = [{"name": ROKU, "message": [message], "level": "ERROR",
            "source": ["components/roku/coordinator.py", 70],
            "timestamp": NOW - 300, "count": 37}]
    return collected(log=log, entities=ents, devices=devices, states=states)


def cause(h, **fields):
    dig = sre.digest(h, NOW)
    recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
    parsed = sre.parse_causes({"causes": [{
        "title": "The Kitchen Roku keeps failing to connect",
        "records": recs, **fields}]}, dig)
    return parsed["causes"][0]


class TestTheOvernightFix(unittest.TestCase):
    def test_one_failing_device_is_not_the_network(self):
        got = cause(roku_house("Cannot connect to Kitchen Roku"),
                    fix="Restart your router or DNS server, then reload "
                        "the integration.")
        self.assertNotRegex(got["fix"], r"(?i)router|dns")
        self.assertIn("Kitchen Roku", got["fix"])
        self.assertIn("unavailable", got["fix"])
        self.assertRegex(got["fix"], r"other 2\b")

    def test_no_canned_sentence_when_the_run_wrote_none(self):
        got = cause(roku_house("Cannot connect to Kitchen Roku"), fix="")
        for canned in ("author", "Check that", "check that",
                       "Settings > Devices", "powered on and reachable",
                       "put right what"):
            self.assertNotIn(canned, got["fix"])
        self.assertIn("Kitchen Roku", got["fix"])

    def test_a_check_brain_can_make_itself_is_not_asked(self):
        got = cause(roku_house("Cannot connect to Kitchen Roku"),
                    fix="Check that the Kitchen Roku is switched on. "
                        "Re-add the Kitchen Roku if its address changed.")
        self.assertNotIn("switched on", got["fix"])
        self.assertIn("Re-add the Kitchen Roku", got["fix"])

    def test_the_canned_helpers_are_gone(self):
        for name in ("_not_your_template_fix", "_error_fix", "_source_fix",
                     "_record_fix"):
            self.assertFalse(hasattr(sre, name), name)


class TestThePlug(unittest.TestCase):
    def test_the_dehumidifier_fix_says_what_brain_read(self):
        [row] = checks.chores.dehumidifier(dehum_snap(), DNOW)
        self.assertNotRegex(row["fix"], r"(?i)check (?:that )?it is switched on")
        self.assertIn("Basement plug", row["fix"])
        self.assertIn("reads on", row["fix"])
        self.assertRegex(row["fix"], r"\b2 W\b")


class TestTheFloodCheck(unittest.TestCase):
    def test_it_never_sends_the_owner_to_the_log(self):
        from test_house_checks import NOW as CNOW, house
        snap = house()
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": "homeassistant.components.tado", "domain": "tado",
            "count": 900, "last": CNOW, "ips": [],
            "message": "Error requesting data: timed out"}]}
        [row] = checks.integrations.log_flood(snap, CNOW)
        self.assertNotIn("System > Logs", row["fix"])
        self.assertNotRegex(row["fix"], r"(?i)\bread what the error")


class TestUrgency(unittest.TestCase):
    def test_one_reading_is_not_urgent(self):
        fix = "Move the food out of the garage freezer immediately."
        calm = house_words.calm(fix, readings_agree=False)
        self.assertNotRegex(calm, r"(?i)immediately|now\b|right away")
        self.assertEqual(house_words.calm(fix, readings_agree=True), fix)

    def test_a_model_row_on_one_reading_loses_its_urgency(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        olds = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR,
                findings_store.SETTLED_FILE)
        findings_store.FINDINGS_FILE = Path(tmp.name) / "f.json"
        findings_store.INBOX_DIR = Path(tmp.name) / "in"
        findings_store.SETTLED_FILE = Path(tmp.name) / "s.json"
        self.addCleanup(lambda: (setattr(findings_store, "FINDINGS_FILE", olds[0]),
                                 setattr(findings_store, "INBOX_DIR", olds[1]),
                                 setattr(findings_store, "SETTLED_FILE", olds[2])))
        once = [{"entity": "sensor.garage_freezer", "value": "-40 °F",
                 "when": "06:10"}]
        twice = once + [{"entity": "sensor.garage_freezer", "value": "-39 °F",
                         "when": "06:15"}]
        [a] = findings_store.add_many([{
            "text": "Garage freezer read -40 °F", "source": "resident",
            "fix": "Unplug the garage freezer right away.",
            "entity_id": "sensor.garage_freezer", "evidence": once}])
        [b] = findings_store.add_many([{
            "text": "Chest freezer read -40 °F", "source": "resident",
            "fix": "Unplug the chest freezer right away.",
            "entity_id": "sensor.chest_freezer", "evidence": twice}])
        self.assertNotIn("right away", a["fix"])
        self.assertIn("right away", b["fix"])


if __name__ == "__main__":
    unittest.main()
