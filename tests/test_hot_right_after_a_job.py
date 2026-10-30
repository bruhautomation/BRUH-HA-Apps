#!/usr/bin/env python3
"""A heater is hot while the machine works and for a while after.

BRUH Bambu Studio's printer has a state sensor (idle, running, pause,
finish, ...) beside its nozzle and bed temperatures. The band that says what
a temperature usually is cannot know a print is on, so a nozzle at 220 C
mid-print, paused, or just finished and cooling was filed as unusual. While
the machine says it is working, `base.unusual` stands down; the moment it
says finished it is given the time a hot part needs to cool; a reading that
is still hot long after is the one worth a card.

The second example is not a printer: a coffee brewer with the same words.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import baselines  # noqa: E402
import corrections  # noqa: E402
from checks import baseline as band  # noqa: E402

NOW = dt.datetime(2026, 1, 5, 10, 0, tzinfo=dt.timezone.utc).timestamp()


def iso(seconds_ago):
    return dt.datetime.fromtimestamp(NOW - seconds_ago,
                                     tz=dt.timezone.utc).isoformat()


def machine(platform, name, status_key, word, changed_ago, *, hot=220.0,
            part="nozzle"):
    """A device with a state sensor and a hot-part temperature whose band
    was built mostly with the machine at rest."""
    dev = {"id": "dev_" + name, "name": name.replace("_", " ").title()}
    status = f"sensor.{name}_{status_key}"
    heat = f"sensor.{name}_{part}_temperature"
    snap = {"now": NOW, "states": {}, "entities": [], "devices": [dev],
            "areas": [], "_trail": [],
            "corrections": {"entity": {}, "area": {}, "check": {},
                            "never": {"checks": sorted(
                                corrections.NEVER_CHECKS)}},
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": {}}}
    snap["states"][status] = {
        "state": word, "last_changed": iso(changed_ago),
        "last_updated": iso(changed_ago),
        "attributes": {"friendly_name": f"{dev['name']} Status"}}
    snap["states"][heat] = {
        "state": str(hot), "last_changed": iso(30), "last_updated": iso(30),
        "attributes": {"device_class": "temperature",
                       "state_class": "measurement",
                       "unit_of_measurement": "°C",
                       "friendly_name": f"{dev['name']} {part.title()} temperature"}}
    for eid in (status, heat):
        snap["entities"].append({"entity_id": eid, "platform": platform,
                                 "device_id": dev["id"]})
    bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
    snap["baselines"]["entities"][heat] = {
        "unit": "°C", "samples": 672,
        "overall": {"median": 24.0, "spread": 1.0, "n": 672},
        "buckets": {bucket: {"median": 24.0, "spread": 1.0, "n": 4}}}
    return snap, heat


def raised(snap):
    return [r["entity_id"] for r in band.unusual(snap, NOW)]


class TestABambuPrinter(unittest.TestCase):
    def printer(self, word, ago):
        return machine("bruh_bambu", "garage_printer", "status", word, ago)

    def test_printing_and_paused_raise_nothing(self):
        for word in ("running", "pause", "prepare"):
            snap, _ = self.printer(word, 3600)
            self.assertEqual(raised(snap), [], word)

    def test_just_finished_and_still_cooling_raises_nothing(self):
        snap, _ = self.printer("finish", 10 * 60)
        self.assertEqual(raised(snap), [])

    def test_hot_long_after_it_finished_is_the_heater_checks(self):
        """A printer's heaters have a check of their own for this: the
        band never judges them, the idle case is `base.heater_idle`."""
        snap, heat = self.printer("finish", 3 * 3600)
        self.assertEqual(raised(snap), [])
        self.assertEqual([r["entity_id"] for r in band.heater_idle(snap, NOW)],
                         [heat])
        snap, heat = self.printer("idle", 2 * 3600)
        self.assertEqual([r["entity_id"] for r in band.heater_idle(snap, NOW)],
                         [heat])

    def test_just_finished_is_not_the_heater_checks_either(self):
        snap, _ = self.printer("finish", 10 * 60)
        self.assertEqual(band.heater_idle(snap, NOW), [])



class TestAnotherMachine(unittest.TestCase):
    def brewer(self, word, ago):
        return machine("brewer_ctl", "cafe_brewer", "brew_state", word, ago,
                       hot=480.0, part="boiler")

    def test_firing_raises_nothing(self):
        snap, _ = self.brewer("running", 7200)
        self.assertEqual(raised(snap), [])

    def test_just_finished_raises_nothing_and_long_after_does(self):
        snap, _ = self.brewer("finished", 600)
        self.assertEqual(raised(snap), [])
        snap, heat = self.brewer("finished", 4 * 3600)
        self.assertEqual(raised(snap), [heat])

    def test_a_reading_below_the_band_is_not_a_cooling_machine(self):
        snap, heat = self.brewer("finished", 600)
        snap["states"][heat]["state"] = "-30"
        self.assertEqual(raised(snap), [heat])


if __name__ == "__main__":
    unittest.main()
