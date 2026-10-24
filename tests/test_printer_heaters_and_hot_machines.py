#!/usr/bin/env python3
"""A printer's heaters are judged by whether the printer is printing, and a
computer's temperatures are not judged against a room.

A house marked `base.unusual` Wrong four times of four, twice saying a 3D
printer's nozzle and bed are hot while it prints and room temperature when
it is idle — "only unusual if hot while the printer is idle". The band
compared every heater reading with an hour-of-the-week median whatever the
printer was doing, and BRUH Bambu Studio's own sensors were not on the
printer list at all. And `dev.implausible` was marked Wrong for a computer's
processor temperature that read like a processor.

Three claims, driven through the real checks:

* while the printer's own status says it is working, neither check says
  anything about its heaters;
* a heater still hot well after the printer went idle is filed, by a check
  of its own (`base.heater_idle`), so an answer given about the band — even
  one that covered the whole sensor — does not silence it;
* a computer's chip or drive temperature raises nothing from either check,
  including from an impossible-value record an older nightly pass left.
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
from checks import devices  # noqa: E402
from checks import get_check  # noqa: E402

NOW = dt.datetime(2026, 1, 5, 10, 0, tzinfo=dt.timezone.utc).timestamp()
PRINTER = {"id": "dev_printer", "name": "Workshop printer",
           "manufacturer": "Bambu Lab", "model": "P1S"}
COMPUTER = {"id": "dev_server", "name": "Home server", "manufacturer": "",
            "model": ""}


def iso(seconds_ago: float) -> str:
    return dt.datetime.fromtimestamp(NOW - seconds_ago,
                                     tz=dt.timezone.utc).isoformat()


def snapshot():
    return {"now": NOW, "states": {}, "entities": [], "devices": [],
            "areas": [], "_trail": [],
            "corrections": {"entity": {}, "area": {}, "check": {},
                            "never": {"checks": sorted(
                                corrections.NEVER_CHECKS)}},
            "baselines": {"built_at": int(NOW - 3600), "tz": "UTC",
                          "days": 28, "entities": {}}}


def reading(snap, eid, name, value, *, unit="°C", platform="", device=None,
            median=25.0, spread=0.5, extra=None):
    snap["states"][eid] = {
        "state": str(value), "last_changed": iso(600),
        "last_updated": iso(60),
        "attributes": {"device_class": "temperature", "state_class":
                       "measurement", "unit_of_measurement": unit,
                       "friendly_name": name}}
    row = {"entity_id": eid, "name": name, "platform": platform}
    if device:
        if device not in snap["devices"]:
            snap["devices"].append(device)
        row["device_id"] = device["id"]
    snap["entities"].append(row)
    bucket = str(baselines.hour_of_week(NOW, dt.timezone.utc))
    entry = {"unit": unit, "samples": 672,
             "overall": {"median": median, "spread": spread, "n": 672},
             "buckets": {bucket: {"median": median, "spread": spread,
                                  "n": 4}}}
    entry.update(extra or {})
    snap["baselines"]["entities"][eid] = entry


def status(snap, eid, name, word, *, since=7200, platform="", device=PRINTER,
           options=None):
    attrs = {"friendly_name": name}
    if options:
        attrs["options"] = options
    snap["states"][eid] = {"state": word, "attributes": attrs,
                           "last_changed": iso(since),
                           "last_updated": iso(since)}
    if device not in snap["devices"]:
        snap["devices"].append(device)
    snap["entities"].append({"entity_id": eid, "name": name,
                             "platform": platform,
                             "device_id": device["id"]})


def bruh_bambu_printer(snap, word, *, nozzle=220, bed=60, since=7200):
    """BRUH Bambu Studio's own five sensors' worth: a status and the two
    heaters, on one printer device, platform `bruh_bambu`."""
    status(snap, "sensor.workshop_status", "Workshop printer Status", word,
           since=since, platform="bruh_bambu")
    reading(snap, "sensor.workshop_nozzle", "Workshop printer Nozzle",
            nozzle, platform="bruh_bambu", device=PRINTER)
    reading(snap, "sensor.workshop_bed", "Workshop printer Bed", bed,
            platform="bruh_bambu", device=PRINTER)


def unusual_ids(snap):
    return [r["entity_id"] for r in band.unusual(snap, NOW)]


def idle_rows(snap):
    return band.heater_idle(snap, NOW)


class TestWhilePrintingTheHeatersAreNotNews(unittest.TestCase):
    def test_bruh_bambu_heaters_while_running(self):
        snap = snapshot()
        bruh_bambu_printer(snap, "running")
        self.assertEqual(unusual_ids(snap), [])
        self.assertEqual(idle_rows(snap), [])

    def test_a_printer_preheating_is_working(self):
        """The Bambu integration's stage reads `heatbed_preheating` before a
        print starts: not idle, and its options say it runs jobs."""
        snap = snapshot()
        status(snap, "sensor.p1s_current_stage", "P1S Current stage",
               "heatbed_preheating", platform="bambu_lab",
               options=["idle", "printing", "heatbed_preheating"])
        reading(snap, "sensor.p1s_bed_temperature", "P1S Bed temperature",
                90, platform="bambu_lab", device=PRINTER)
        self.assertEqual(unusual_ids(snap), [])
        self.assertEqual(idle_rows(snap), [])

    def test_the_stand_down_is_said_as_the_printer_printing(self):
        snap = snapshot()
        bruh_bambu_printer(snap, "running")
        band.unusual(snap, NOW)
        kinds = {(w["kind"], w["subject"]) for w in snap["_trail"]}
        self.assertNotIn(("cap", "sensor.workshop_nozzle"), kinds)


class TestHotWhileIdleIsFiled(unittest.TestCase):
    def test_a_nozzle_hot_two_hours_after_the_printer_went_idle(self):
        snap = snapshot()
        bruh_bambu_printer(snap, "idle", nozzle=200, bed=24)
        rows = idle_rows(snap)
        self.assertEqual([r["entity_id"] for r in rows],
                         ["sensor.workshop_nozzle"])
        self.assertIn("idle", rows[0]["text"])
        self.assertNotIn("sensor.", rows[0]["detail"])
        # The band says nothing about it: the heater rule is the one rule.
        self.assertEqual(unusual_ids(snap), [])

    def test_a_finished_print_in_fahrenheit(self):
        snap = snapshot()
        status(snap, "sensor.p1s_print_status", "P1S Print status",
               "finish", since=3 * 3600, platform="bambu_lab")
        reading(snap, "sensor.p1s_bed_temperature", "P1S Bed temperature",
                150, unit="°F", platform="bambu_lab", device=PRINTER)
        self.assertEqual([r["entity_id"] for r in idle_rows(snap)],
                         ["sensor.p1s_bed_temperature"])

    def test_cooling_down_just_after_a_print_is_not_filed(self):
        snap = snapshot()
        bruh_bambu_printer(snap, "finish", nozzle=150, since=300)
        self.assertEqual(idle_rows(snap), [])

    def test_idle_and_cool_is_not_filed(self):
        snap = snapshot()
        bruh_bambu_printer(snap, "idle", nozzle=26, bed=25)
        self.assertEqual(idle_rows(snap), [])

    def test_no_status_to_read_files_nothing(self):
        snap = snapshot()
        reading(snap, "sensor.p1s_nozzle", "P1S Nozzle temperature", 210,
                platform="bambu_lab", device=PRINTER)
        self.assertEqual(idle_rows(snap), [])

    def test_a_wrong_given_about_the_band_does_not_silence_it(self):
        """The owner's answer was about the heater while printing. Stored
        as a rule on `base.unusual` — even one covering the whole sensor —
        it must not stand down the one case they said they want."""
        snap = snapshot()
        bruh_bambu_printer(snap, "idle", nozzle=200, bed=24)
        snap["corrections"]["entity"]["sensor.workshop_nozzle"] = {
            "base.unusual": {"text": "Normal while printing"},
            "*": {"text": "That is normal for this sensor"}}
        self.assertEqual([r["entity_id"] for r in idle_rows(snap)],
                         ["sensor.workshop_nozzle"])

    def test_a_wrong_given_about_the_idle_case_does(self):
        snap = snapshot()
        bruh_bambu_printer(snap, "idle", nozzle=200, bed=24)
        snap["corrections"]["entity"]["sensor.workshop_nozzle"] = {
            "base.heater_idle": {"text": "It keeps warm on purpose"}}
        self.assertEqual(idle_rows(snap), [])

    def test_the_check_is_catalogued_and_urgent(self):
        import urgency
        self.assertTrue(get_check("base.heater_idle"))
        self.assertEqual(
            urgency.urgency_of({"source": "check:base.heater_idle"}), "now")


class TestAComputersTemperaturesAreNotARoom(unittest.TestCase):
    def test_a_system_monitor_processor_at_212f(self):
        snap = snapshot()
        reading(snap, "sensor.system_monitor_processor_temperature",
                "System Monitor Processor temperature", 212, unit="°F",
                platform="systemmonitor", device=COMPUTER, median=140.0,
                spread=3.0)
        self.assertEqual(
            [r["entity_id"] for r in devices.implausible(snap, NOW)], [])
        self.assertEqual(unusual_ids(snap), [])

    def test_a_drive_temperature_on_an_unknown_integration(self):
        """A second example the report did not name: a drive's temperature
        from an integration nobody listed, known only by its name."""
        snap = snapshot()
        reading(snap, "sensor.pool_hdd_1_temperature",
                "Pool HDD 1 temperature", 150, unit="°F",
                platform="scrutiny", median=100.0, spread=2.0)
        self.assertEqual(
            [r["entity_id"] for r in devices.implausible(snap, NOW)], [])
        self.assertEqual(unusual_ids(snap), [])

    def test_an_old_impossible_record_is_read_again(self):
        """A record an older pass left — it took 90 °C as impossible on a
        sensor it now knows is a chip's — is not a reason to file now."""
        snap = snapshot()
        reading(snap, "sensor.server_cpu_temperature", "Server CPU temperature",
                70, platform="systemmonitor", device=COMPUTER, median=60.0,
                extra={"impossible": {"count": 3, "lowest": 85.0,
                                      "highest": 95.0,
                                      "last": int(NOW - 3600)}})
        self.assertEqual(
            [r["entity_id"] for r in devices.implausible(snap, NOW)], [])

    def test_a_real_impossible_record_still_files(self):
        snap = snapshot()
        reading(snap, "sensor.hall_temperature", "Hall temperature", 20,
                extra={"impossible": {"count": 3, "lowest": -95.0,
                                      "highest": -90.0,
                                      "last": int(NOW - 3600)}})
        self.assertEqual(
            [r["entity_id"] for r in devices.implausible(snap, NOW)],
            ["sensor.hall_temperature"])


if __name__ == "__main__":
    unittest.main()
