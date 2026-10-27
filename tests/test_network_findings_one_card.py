#!/usr/bin/env python3
"""Network and log findings: one device one card, cleared when it is back,
and numbers that agree (#440, #441, #443, #434, #444).

* #440 — one Wi-Fi switch was three open rows (a check's on its switch, a
  card's on its UniFi tracker, a third inside a four-device card), and the
  UniFi integration losing its controller was two. A row about a device
  dropping is folded on the DEVICE (the registry's, and for a UniFi
  client's tracker the device it is a client of, through the MAC), and a
  row about an integration as a whole on the integration.
* #441 — a "not reachable" card from the overnight check and an "offline
  since Thursday" card stayed open after the devices had reported for a
  day. A row from a producer that does not re-check its own rows is taken
  off once every entity it names has reported for a settle period, and a
  row whose own detail says the trouble stopped is not kept.
* #443 — a look's reason said 49 drops beside a detail the check had since
  refreshed to 36: such a reason is not shown.
* #434 — a log finding was filed on an unrelated entity by a name match:
  only the integration's own things, or the automation the logger names.
* #444 — a log finding said nothing of the error: it states what it means,
  how often and when, or it is held back; its fix follows from the error.

Driven over the real store, the real checks and the real overnight parse.
"""
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import findings_store  # noqa: E402
import sre  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402
import test_network_checks as tnc  # noqa: E402

add_ap, add_client = tnc.add_ap, tnc.add_client
from test_sre import collected  # noqa: E402
from test_subject_fold import FoldCase  # noqa: E402

network = checks.network
integrations = checks.integrations


def _iso(ts: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# #440 — one device, one card
# ---------------------------------------------------------------------------

class TestATrackerIsItsDevicesDevice(unittest.TestCase):
    def test_a_tracker_on_its_own_unifi_device_joins_the_device_by_mac(self):
        snap = house()
        add_ap(snap)
        switch, tracker = add_client(snap, 4, down_for=0)
        # UniFi registered a device of its own for the client, carrying the
        # same MAC; the tracker sits on it.
        mac = snap["states"][tracker]["attributes"]["mac"]
        snap["devices"].append({"id": "dev-unifi-client", "name": "Plug 4",
                                "connections": [["mac", mac]]})
        for row in snap["entities"]:
            if row["entity_id"] == tracker:
                row["device_id"] = "dev-unifi-client"
        keys = network.device_keys(snap)
        self.assertEqual(keys[tracker], keys[switch])
        self.assertEqual(keys[switch], "dev-plug4")


NAMES = {
    "switch.attic_plug": {"name": "Attic plug", "device": "dev-attic"},
    "device_tracker.attic_plug": {"name": "Attic plug", "device": "dev-attic"},
    "switch.shed_plug": {"name": "Shed plug", "device": "dev-shed"},
    "device_tracker.shed_plug": {"name": "Shed plug", "device": "dev-shed"},
    "switch.porch_plug": {"name": "Porch plug", "device": "dev-porch"},
    "light.study_lamp": {"name": "Study lamp", "device": "dev-study"},
}


class DeviceCase(FoldCase):
    def setUp(self):
        super().setUp()
        self._names = findings_store.DISPLAY_NAMES
        findings_store.DISPLAY_NAMES = lambda: NAMES

    def tearDown(self):
        findings_store.DISPLAY_NAMES = self._names
        super().tearDown()


def flapping(eid="switch.attic_plug", count=36):
    return {"text": "Attic plug keeps dropping off the network",
            "detail": f"It went unavailable {count} separate times in the "
                      "last 7 days.",
            "source": "check:net.wifi_flapping", "entity_id": eid,
            "severity": "warning", "fixable": False,
            "evidence": [{"entity": eid, "value": f"{count} drops",
                          "when": ""}]}


def live():
    return [f for f in findings_store.list_all()
            if f["status"] in findings_store.CROSS_FOLD_STATUSES]


class TestOneDeviceOneCard(DeviceCase):
    def test_a_card_about_the_tracker_folds_into_the_checks_row(self):
        findings_store.add_many([flapping()])
        findings_store.add_many([{
            "text": "The attic plug's Wi-Fi tracker keeps going offline",
            "claim": "The attic plug's Wi-Fi tracker keeps going offline",
            "detail": "UniFi saw it drop 45 separate times this week.",
            "source": "network_card", "kind": "problem",
            "entity_id": "device_tracker.attic_plug", "severity": "warning",
            "evidence": [{"entity": "device_tracker.attic_plug",
                          "value": "45 separate times", "when": ""}]}])
        rows = live()
        self.assertEqual(len(rows), 1, rows)
        [row] = rows
        self.assertEqual(row["source"], "check:net.wifi_flapping")
        named = {e["entity"] for e in row.get("evidence") or []}
        self.assertIn("device_tracker.attic_plug", named)
        # One count on the card: the other producer's 45 is not carried.
        self.assertNotIn("45", " ".join(e["value"] for e in row["evidence"]))

    def test_a_second_device_example_folds_into_a_card_naming_several(self):
        findings_store.add_many([{
            "text": "Two Wi-Fi plugs are connected but not reachable",
            "claim": "Two Wi-Fi plugs are connected but not reachable",
            "detail": "Both share one access point.", "kind": "problem",
            "source": "sre", "entity_id": "", "severity": "warning",
            "evidence": [{"entity": "switch.shed_plug", "value": "unavailable",
                          "when": ""},
                         {"entity": "switch.porch_plug",
                          "value": "unavailable", "when": ""}]}])
        findings_store.add_many([{
            "text": "Shed plug tracker unavailable",
            "claim": "Shed plug tracker unavailable",
            "source": "network_card", "kind": "problem",
            "entity_id": "device_tracker.shed_plug", "severity": "warning"}])
        rows = live()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["source"], "sre")

    def test_a_row_about_another_device_stays_its_own(self):
        findings_store.add_many([flapping()])
        findings_store.add_many([{
            "text": "Study lamp keeps dropping off Wi-Fi",
            "claim": "Study lamp keeps dropping off Wi-Fi",
            "source": "network_card", "kind": "problem",
            "entity_id": "light.study_lamp", "severity": "warning"}])
        self.assertEqual(len(live()), 2)

    def test_a_row_that_is_not_about_a_drop_is_not_folded(self):
        findings_store.add_many([flapping()])
        findings_store.add_many([{
            "text": "Attic plug draws more power than usual",
            "claim": "Attic plug draws more power than usual",
            "source": "network_card", "kind": "problem",
            "entity_id": "switch.attic_plug", "severity": "info"}])
        self.assertEqual(len(live()), 2)

    def test_an_integration_wide_drop_is_one_card(self):
        snap_row = {"text": "UniFi's device trackers keep dropping all at once",
                    "detail": "Every UniFi tracker went unavailable together.",
                    "source": "check:net.unifi_dropped", "entity_id": "",
                    "severity": "warning", "fixable": False,
                    "integration": "unifi"}
        findings_store.add_many([snap_row])
        findings_store.add_many([{
            "text": "Home Assistant lost the UniFi controller overnight",
            "claim": "Home Assistant lost the UniFi controller overnight",
            "detail": "The UniFi integration logged a lost connection.",
            "source": "sre", "kind": "problem", "entity_id": "",
            "integration": "unifi", "severity": "warning"}])
        rows = live()
        self.assertEqual(len(rows), 1, rows)
        self.assertEqual(rows[0]["source"], "check:net.unifi_dropped")

    def test_the_unifi_check_says_its_row_is_about_the_integration(self):
        snap = tnc.TestFlapping().wifi_house(tnc.flaps(0))
        for n in (1, 2, 3):
            tracker = [(6.5 * 86400, "home")]
            for k in range(4):
                t = 3 * 86400 - k * 7200
                tracker += [(t, "unavailable"), (t - 120, "home")]
            snap["wifi_history"]["entities"][
                f"device_tracker.plug_{n}_client"] = tnc.series(
                f"device_tracker.plug_{n}_client", tracker)
        [row] = network.unifi_dropped(snap, NOW)
        self.assertEqual(row["integration"], "unifi")


# ---------------------------------------------------------------------------
# #441 — cleared when the device is back
# ---------------------------------------------------------------------------

FOUR = ("switch.attic_plug", "switch.shed_plug", "switch.porch_plug",
        "light.study_lamp")


class TestBackForASettlePeriod(DeviceCase):
    def four_card(self, **over):
        [row] = findings_store.add_many([{
            "text": "Four Wi-Fi devices are connected but not reachable",
            "claim": "Four Wi-Fi devices are connected but not reachable",
            "detail": "All four are unavailable.", "kind": "problem",
            "source": "sre", "entity_id": FOUR[0], "severity": "warning",
            "about": list(FOUR),
            "evidence": [{"entity": "log:abc123", "value": "Error x3",
                          "when": ""}], **over}])
        return row

    def states(self, since, state="on", **odd):
        out = {e: {"state": state, "last_changed": _iso(since)} for e in FOUR}
        out.update(odd)
        return out

    def test_every_named_entity_back_for_the_settle_period_clears_it(self):
        row = self.four_card()
        now = row["ts"] + findings_store.RETURN_SETTLE_S + 600
        gone = findings_store.clear_returned(
            self.states(row["ts"] + 300), now)
        self.assertEqual([g["ts"] for g in gone], [row["ts"]])
        self.assertFalse(findings_store.is_known(row["text"]))

    def test_one_still_unavailable_keeps_it(self):
        row = self.four_card()
        now = row["ts"] + 6 * 3600
        odd = {FOUR[2]: {"state": "unavailable",
                         "last_changed": _iso(row["ts"])}}
        self.assertEqual(findings_store.clear_returned(
            self.states(row["ts"] - 60, **odd), now), [])

    def test_inside_the_settle_period_it_stays(self):
        row = self.four_card()
        now = row["ts"] + findings_store.RETURN_SETTLE_S - 60
        self.assertEqual(findings_store.clear_returned(
            self.states(row["ts"] - 3600), now), [])

    def test_a_house_checks_row_is_left_to_its_check(self):
        [row] = findings_store.add_many([{
            "text": "Attic plug has been unavailable for a day",
            "source": "check:dev.unavailable", "entity_id": FOUR[0],
            "severity": "warning"}])
        now = row["ts"] + 6 * 3600
        self.assertEqual(findings_store.clear_returned(
            self.states(row["ts"] - 3600), now), [])

    def test_a_row_its_detail_says_is_over_does_not_keep_its_title(self):
        [row] = findings_store.add_many([{
            "text": "The hall thermostat has been offline since Thursday",
            "claim": "The hall thermostat has been offline since Thursday",
            "detail": "It went offline on Thursday.", "kind": "problem",
            "source": "climate_card", "entity_id": "climate.hall",
            "severity": "serious"}])
        # A later run's words about it: it has reported since Saturday.
        stored = findings_store._load()
        for f in stored:
            if f["ts"] == row["ts"]:
                f["detail"] = ("It went offline on Thursday evening and has "
                               "reported since Saturday at 22:33.")
        findings_store._write(stored)
        gone = findings_store.clear_returned({}, row["ts"] + 60)
        self.assertEqual([g["ts"] for g in gone], [row["ts"]])

    def test_a_new_row_saying_it_came_back_is_not_filed(self):
        created = findings_store.add_many([{
            "text": "The cellar freezer plug is unavailable",
            "claim": "The cellar freezer plug is unavailable",
            "detail": "It dropped at 02:00 and came back at 02:20.",
            "source": "freezer_card", "kind": "problem",
            "entity_id": "switch.cellar_freezer", "severity": "warning"}])
        self.assertEqual(created, [])

    def test_not_reported_since_is_not_a_recovery(self):
        self.assertFalse(findings_store.says_recovered(
            "It has not reported since Thursday at 23:29."))
        self.assertFalse(findings_store.says_recovered(
            "It came back at noon, then went offline again at 15:00."))
        self.assertTrue(findings_store.says_recovered(
            "It went offline on Thursday and has reported since Saturday."))


# ---------------------------------------------------------------------------
# #443 — a look's numbers against the detail's
# ---------------------------------------------------------------------------

class TestALooksCountMatchesItsDetail(FoldCase):
    def look_reason(self, ts):
        [row] = [f for f in findings_store.listing()["findings"]
                 if f["ts"] == ts]
        return (row.get("triage") or {}).get("reason") or ""

    def test_a_refreshed_count_hides_the_reason_that_quoted_the_old_one(self):
        [row] = findings_store.add_many([{**flapping(count=49),
                                          "status": "triaging"}])
        findings_store.record_triage({row["ts"]: (
            "elevated", "It dropped 49 times this week with UniFi holding it.")})
        self.assertIn("49", self.look_reason(row["ts"]))
        findings_store.refresh_details([flapping(count=36)])
        self.assertEqual(self.look_reason(row["ts"]), "")

    def test_a_second_kind_of_count_too(self):
        [row] = findings_store.add_many([{
            "text": "The kitchen sensor misses readings",
            "detail": "170 readings were missing yesterday.",
            "source": "check:dev.gaps", "entity_id": "sensor.kitchen",
            "severity": "info", "status": "triaging"}])
        findings_store.record_triage({row["ts"]: (
            "elevated", "Real: 170 readings missing is more than usual.")})
        findings_store.refresh_details([{
            "text": "The kitchen sensor misses readings",
            "detail": "159 readings were missing yesterday.",
            "source": "check:dev.gaps", "entity_id": "sensor.kitchen",
            "severity": "info"}])
        self.assertEqual(self.look_reason(row["ts"]), "")

    def test_a_reason_that_agrees_is_shown(self):
        [row] = findings_store.add_many([{**flapping(count=36),
                                          "status": "triaging"}])
        findings_store.record_triage({row["ts"]: (
            "elevated", "It dropped 36 times; the signal is weak.")})
        self.assertIn("36", self.look_reason(row["ts"]))


# ---------------------------------------------------------------------------
# #434 / #444 — a log finding's subject and what it says
# ---------------------------------------------------------------------------

def log_row(message, logger, level="ERROR", count=40):
    return {"name": logger, "message": [message], "level": level,
            "source": ["x.py", 1], "timestamp": NOW - 7200, "count": count,
            "first_occurred": NOW - 20000}


LIFX = "homeassistant.components.lifx"


def lifx_house(log, **over):
    return collected(
        log=log, zha=[], automations=[],
        entities=[
            {"entity_id": "binary_sensor.back_porch_motion",
             "device_id": "dev-motion", "platform": "zha"},
            {"entity_id": "light.study_bulb", "device_id": "dev-bulb",
             "platform": "lifx"},
            {"entity_id": "automation.aaa_morning",
             "platform": "automation"},
            {"entity_id": "automation.printer_alert",
             "platform": "automation"},
        ],
        devices=[{"id": "dev-motion", "name": "Back Porch Motion"},
                 {"id": "dev-bulb", "name": "Study Bulb"}],
        states={"automation.aaa_morning": {"state": "on", "attributes": {
                    "friendly_name": "Morning lights"}},
                "automation.printer_alert": {"state": "on", "attributes": {
                    "friendly_name": "Printer alert"}}},
        **over)


def one_cause(h, **cause):
    dig = sre.digest(h, NOW)
    recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
    parsed = sre.parse_causes({"causes": [{"title": "Errors in the log",
                                           "records": recs[:1], **cause}]},
                              dig)
    rows = sre.rows(parsed["causes"], dig, {"anchors": {}}, NOW)
    return parsed, rows


class TestALogLineIsFiledOnItsOwnIntegrationsThing(unittest.TestCase):
    def test_another_integrations_device_named_in_the_line_is_not_it(self):
        h = lifx_house([log_row("Timed out reaching Back Porch Motion area "
                                "bulb", LIFX)])
        [row] = one_cause(h)[1]
        self.assertNotEqual(row["entity_id"], "binary_sensor.back_porch_motion")
        self.assertIn(row["entity_id"], ("", "light.study_bulb"))

    def test_its_own_device_named_in_the_line_is(self):
        h = lifx_house([log_row("Timed out reaching Study Bulb", LIFX)])
        [row] = one_cause(h)[1]
        self.assertEqual(row["entity_id"], "light.study_bulb")

    def test_an_automations_line_is_filed_on_that_automation(self):
        h = lifx_house([log_row(
            "Printer alert: Error executing script. Referenced entities "
            "sensor.printer_ink are missing or not currently available",
            "homeassistant.components.automation.printer_alert")])
        [row] = one_cause(h)[1]
        self.assertEqual(row["entity_id"], "automation.printer_alert")

    def test_a_rule_integration_never_stands_for_itself(self):
        h = lifx_house([log_row("Something broke while loading",
                                "homeassistant.components.automation")])
        [row] = one_cause(h)[1]
        self.assertEqual(row["entity_id"], "")

    def test_the_flood_check_does_not_match_another_integrations_name(self):
        snap = house()
        snap["entities"] += [
            {"entity_id": "binary_sensor.back_porch_motion",
             "device_id": "dev-motion", "platform": "zha"},
            {"entity_id": "light.study_bulb", "device_id": "dev-bulb",
             "platform": "lifx"}]
        snap["devices"] += [{"id": "dev-motion", "name": "Back Porch Motion"},
                            {"id": "dev-bulb", "name": "Study Bulb"}]
        for eid in ("binary_sensor.back_porch_motion", "light.study_bulb"):
            snap["states"][eid] = {"state": "on", "attributes": {},
                                   "last_changed": _iso(NOW - 600)}
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": LIFX, "domain": "lifx", "count": 300, "last": NOW,
            "ips": [], "message": "Timed out reaching Back Porch Motion bulb"}]}
        [row] = integrations.log_flood(snap, NOW)
        self.assertEqual(row["entity_id"], "")
        self.assertEqual(row["integration"], "lifx")
        self.assertNotIn("Back Porch Motion", row["detail"].split("”")[-1])
        snap["core_log"]["groups"][0]["message"] = "Timed out reaching Study Bulb"
        [row] = integrations.log_flood(snap, NOW)
        self.assertEqual(row["entity_id"], "light.study_bulb")


VACUUM = "homeassistant.components.robovac"


def vacuum_house(log):
    return collected(
        log=log, zha=[], automations=[],
        entities=[{"entity_id": "vacuum.downstairs", "device_id": "dev-vac",
                   "platform": "robovac"}],
        devices=[{"id": "dev-vac", "name": "Downstairs cleaner"}],
        manifests=[{"domain": "robovac", "name": "RoboVac"}])


class TestALogFindingSaysWhatFailed(unittest.TestCase):
    def test_the_meaning_the_count_and_when_are_in_the_detail(self):
        h = vacuum_house([log_row("Failed to update map data: cloud rate "
                                  "limited", VACUUM, count=40)])
        parsed, [row] = one_cause(
            h, detail="", fix="Restart the vacuum on its dock.")
        # What the error means, never the line pasted in.
        self.assertNotIn("Failed to update map data", row["detail"])
        self.assertIn("asked too often", row["detail"])
        self.assertIn("40 times", row["detail"])
        self.assertIn("most recently", row["detail"])
        self.assertNotIn("dock", row["fix"].lower())
        self.assertEqual(parsed["unfollowed"], 1)

    def test_a_fix_about_the_error_is_kept(self):
        h = vacuum_house([log_row("Failed to update map data: cloud rate "
                                  "limited", VACUUM)])
        _, [row] = one_cause(
            h, fix="Wait for the cloud rate limit to lift, then update the "
                   "map again.")
        self.assertIn("rate limit", row["fix"])

    def test_a_line_with_nothing_in_it_is_held_back(self):
        h = vacuum_house([log_row("", VACUUM)])
        parsed, rows = one_cause(h)
        self.assertEqual(rows, [])
        self.assertEqual(parsed["unstated"], 1)


if __name__ == "__main__":
    unittest.main()
