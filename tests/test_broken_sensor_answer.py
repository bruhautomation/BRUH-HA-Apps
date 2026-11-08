#!/usr/bin/env python3
"""A sensor the household called broken is not reasoned about (#701, #692).

"This sensor is broken, please ignore it" said on a card about a pressure
sensor, and then the impossible-readings check and the Resident's first
look both raised that sensor's readings again. ONE helper now says whether
such an answer covers an entity (`corrections.broken_answer`), and every
reader shares it: the device checks through `House.answered_off` (so
`dev.implausible` with them) and the first look before its batch is built
(`resident.set_aside_broken`: whatever the look
said of such a sensor, it is let go). It applies the never-ignore floors FIRST —
a leak, smoke or gas sensor, a lock, an alarm, the protected list and the
security checks are reasoned about whatever was said — writes a decision
trail entry for every row it drops, and reads only the broken wording that
already finishes a device (`gone_for_good`), never new words.
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import corrections  # noqa: E402
import resident  # noqa: E402
from checks import devices  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

BROKEN = "This sensor is broken, please ignore it"
FAULTY = {"sensor.pump_pressure": BROKEN,
          "binary_sensor.sink_leak": BROKEN,
          "lock.front_door": BROKEN,
          "sensor.loft_temperature": "It reads high in summer, that's fine"}
CLASSES = {"binary_sensor.sink_leak": "moisture"}


def covers(eid, check="dev.implausible"):
    notes = []
    said = corrections.broken_answer(
        eid, check, faulty=FAULTY, device_class=CLASSES.get(eid, ""),
        protected=(), note=notes.append)
    return said, notes


class TestTheOneHelper(unittest.TestCase):
    def test_a_pressure_sensor_is_dropped_with_a_trail_entry(self):
        said, notes = covers("sensor.pump_pressure")
        self.assertEqual(said, BROKEN)
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["subject"], "sensor.pump_pressure")
        self.assertEqual(notes[0]["reason"], BROKEN)

    def test_a_leak_sensor_is_never_dropped(self):
        self.assertEqual(covers("binary_sensor.sink_leak"), ("", []))

    def test_a_lock_is_never_dropped(self):
        self.assertEqual(covers("lock.front_door"), ("", []))

    def test_a_security_check_is_never_dropped(self):
        self.assertEqual(covers("sensor.pump_pressure", "sec.door_open"),
                         ("", []))

    def test_a_protected_entity_is_never_dropped(self):
        notes = []
        self.assertEqual(corrections.broken_answer(
            "sensor.pump_pressure", "dev.implausible", faulty=FAULTY,
            protected=("sensor.pump_pressure",), note=notes.append), "")
        self.assertEqual(notes, [])

    def test_only_the_broken_wording_counts(self):
        self.assertEqual(covers("sensor.loft_temperature"), ("", []))
        for words in ("Ignore this sensor. For a week.",
                      "Don't ignore this sensor",
                      "please ignore it"):
            self.assertEqual(corrections.broken_answer(
                "sensor.x", "dev.implausible", faulty={"sensor.x": words},
                protected=(), note=lambda row: None), "", words)


def impossible(snap, eid, value, klass, unit, name):
    snap["states"][eid] = {
        "state": str(value), "last_updated": "2026-01-01T00:00:00+00:00",
        "last_changed": "2026-01-01T00:00:00+00:00",
        "attributes": {"device_class": klass, "unit_of_measurement": unit,
                       "state_class": "measurement", "friendly_name": name}}
    snap["entities"].append({"entity_id": eid, "platform": "mqtt"})


class TestImpossibleReadings(unittest.TestCase):
    def test_a_sensor_called_broken_is_not_raised_and_the_trail_says_why(self):
        snap = house()
        impossible(snap, "sensor.pump_pressure", 200, "pressure", "hPa",
                   "Pump pressure")
        impossible(snap, "sensor.tank_pressure", 200, "pressure", "hPa",
                   "Tank pressure")
        before = [f["entity_id"] for f in devices.implausible(snap, NOW)]
        self.assertIn("sensor.pump_pressure", before)
        snap["faulty"] = {"sensor.pump_pressure": BROKEN}
        snap["_trail"] = []
        after = [f["entity_id"] for f in devices.implausible(snap, NOW)]
        self.assertEqual(after, ["sensor.tank_pressure"])
        trail = [t for t in snap["_trail"]
                 if t.get("subject") == "sensor.pump_pressure"]
        self.assertEqual(len(trail), 1, snap["_trail"])
        self.assertEqual(trail[0]["reason"], BROKEN)


def signal(subject, source="state", **flags):
    return {"subject": subject, "source": source, "kind": "state", **flags}


def watched(n):
    return {i: {"verdict": "investigate", "why": "worth a look"}
            for i in range(1, n + 1)}


class TestTheFirstLook(unittest.TestCase):
    def test_only_the_broken_pressure_sensor_is_let_go(self):
        notes = []
        batch = [signal("sensor.pump_pressure"),
                 signal("binary_sensor.sink_leak"),
                 signal("lock.front_door"),
                 signal("sensor.hall_temperature")]
        got = resident.set_aside_broken(
            batch, watched(4), FAULTY,
            device_class=lambda e: CLASSES.get(e, ""), protected=(),
            note=notes.append)
        self.assertEqual([got[i]["verdict"] for i in range(1, 5)],
                         ["ignore", "investigate", "investigate",
                          "investigate"])
        self.assertIn("broken", got[1]["why"])
        self.assertEqual([n["subject"] for n in notes],
                         ["sensor.pump_pressure"])

    def test_a_signal_on_a_never_ignore_floor_or_already_filed_keeps_it(self):
        batch = [signal("sensor.pump_pressure", hot=True),
                 signal("sensor.pump_pressure", source="check:safety.tripped"),
                 {**signal("sensor.pump_pressure"), "finding_ts": 12}]
        got = resident.set_aside_broken(batch, watched(3), FAULTY,
                                        protected=(), note=lambda row: None)
        self.assertEqual({v["verdict"] for v in got.values()},
                         {"investigate"})


if __name__ == "__main__":
    unittest.main()
