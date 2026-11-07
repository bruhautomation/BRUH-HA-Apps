#!/usr/bin/env python3
"""Finding and card words that say only what brAIn measured (#583, #700,
#725, #726, #735, #737) — the second attempt, built from what a reviewer
found the first one did wrong.

Every negative list below is a sentence the first attempt broke: a real
problem held, a correct step dropped, or a claim nobody measured printed.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import card_claims  # noqa: E402
import categories  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import resident  # noqa: E402
import sre  # noqa: E402
from checks import integrations  # noqa: E402
from checks.network import _FIXES  # noqa: E402
from test_cases import StoresCase  # noqa: E402,F401  (setUp/tearDown)

ZIGBEE_MAINS_FIX = _FIXES["zigbee_mains"]

# What the first attempt printed that nobody measured, and the stock phrase.
UNMEASURED = (
    "something it was doing failed",
    "without saying what went wrong",
    "only that it keeps happening",
    "brAIn raises these only past",
    "Usually it logs",
    "Until it stops",
)


# ---------------------------------------------------------------------------
# #725 — a log error says what is known, and nothing else
# ---------------------------------------------------------------------------

class TestALogErrorSaysOnlyWhatIsKnown(unittest.TestCase):
    def _flood(self, message, count=1200, logger="homeassistant.components.tado"):
        from test_house_checks import NOW, house
        snap = house()
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": logger, "domain": logger.split(".")[-1]
            if logger.startswith("homeassistant") else "",
            "count": count, "last": NOW, "first": NOW - 10 * 3600,
            "ips": [], "message": message}]}
        return integrations.log_flood(snap, NOW)

    def test_an_unread_error_in_the_flood_check_says_who_how_often_and_when(self):
        [row] = self._flood("Update of thermostat went sideways")
        for phrase in UNMEASURED:
            self.assertNotIn(phrase.lower(), row["detail"].lower())
        self.assertIn("1200 times in the last 24 hours.", row["detail"])

    def test_a_library_logger_is_not_promised_to_update(self):
        [row] = self._flood("Connection pool is full, discarding connection",
                            logger="urllib3.connectionpool")
        for phrase in UNMEASURED:
            self.assertNotIn(phrase.lower(), row["detail"].lower())

    def test_an_unread_error_overnight_says_once_and_when(self):
        said = sre._log_said([{"message": "Update of thermostat went sideways",
                               "count": 1, "last_hours_ago": 3,
                               "integration_name": "Tado"}], {})
        self.assertEqual(said, "The Tado integration logged an error once, "
                               "most recently about 3 hours ago.")
        for phrase in UNMEASURED:
            self.assertNotIn(phrase.lower(), said.lower())

    def test_a_read_error_still_says_what_it_means(self):
        message = "Error requesting data: 401, message='Unauthorized'"
        [row] = self._flood(message)
        self.assertIn(house_words.known_log_meaning(message), row["detail"])
        said = sre._log_said([{"message": "Timed out talking to the hub",
                               "count": 4, "last_hours_ago": 0.5,
                               "integration_name": "Hue"}], {})
        self.assertIn("did not answer in time", said)

    def test_known_meaning_is_empty_for_an_unread_line(self):
        self.assertEqual(house_words.known_log_meaning("Something odd"), "")
        self.assertTrue(house_words.known_log_meaning("HTTP 503 from cloud"))


# ---------------------------------------------------------------------------
# #737 — a device title from what was measured; steps agree with the detail
# ---------------------------------------------------------------------------

def zigbee(**over):
    rec = {"id": "zha:00:11", "kind": "zigbee", "name": "Hall sensor",
           "type": "EndDevice", "available": True, "lqi": 200,
           "last_seen_hours": 0.2}
    rec.update(over)
    return rec


class TestADeviceTitleIsWhatWasMeasured(unittest.TestCase):
    def test_titles(self):
        cases = [
            (zigbee(available=False, last_seen_hours=30),
             "Hall sensor has been offline on the Zigbee network for 30 hours"),
            (zigbee(available=False, last_seen_hours=None),
             "Hall sensor is offline on the Zigbee network"),
            (zigbee(last_seen_hours=72),
             "Hall sensor has not been heard on the Zigbee network for 3 days"),
            (zigbee(lqi=40),
             "Hall sensor has a weak Zigbee link (link quality 40)"),
            ({"id": "zw:1", "kind": "zwave", "name": "Pump", "status": "dead",
              "stats": {}}, "The Z-Wave device Pump is marked dead by Z-Wave"),
            ({"id": "zw:1", "kind": "zwave", "name": "Pump", "status": "alive",
              "stats": {"commandsDroppedTX": 3}},
             "The Z-Wave device Pump has dropped 3 Z-Wave commands"),
        ]
        for rec, want in cases:
            with self.subTest(want):
                title = sre._plain_title(rec, {})
                self.assertEqual(title, want)
                self.assertNotRegex(title, r"struggl|having trouble")

    def test_a_stock_verb_on_one_mesh_device_is_replaced(self):
        got = sre._measured_title("Hall sensor is struggling",
                                  [zigbee(lqi=35)], {})
        self.assertEqual(got, "Hall sensor has a weak Zigbee link "
                              "(link quality 35)")

    def test_a_title_is_kept_when_it_is_not_one_mesh_device(self):
        log = {"id": "log:1", "kind": "log", "message": "x"}
        for recs in ([log], [zigbee(), zigbee(id="zha:2")], [zigbee(), log]):
            self.assertEqual(sre._measured_title("Hall is struggling", recs, {}),
                             "Hall is struggling")
        self.assertEqual(sre._measured_title(
            "Hall sensor dropped off overnight", [zigbee(lqi=30)], {}),
            "Hall sensor dropped off overnight")


class TestAStepAgreesWithTheDetail(unittest.TestCase):
    def test_a_flat_present_fine_drops_only_that_step(self):
        cases = [
            ("Its signal is fine. It has been offline for 6 hours.",
             "Move it closer to a router. Check its battery.",
             "Check its battery."),
            ("The battery reads full. Link quality is 25.",
             "Replace its battery. Add a router between it and the hub.",
             "Add a router between it and the hub."),
            ("The signal looked fine.",
             "Move it closer to the coordinator. Re-pair it from its "
             + "device page.", "Re-pair it from its device page."),
        ]
        for detail, fix, want in cases:
            with self.subTest(detail):
                self.assertEqual(sre._steps_agree(detail, fix), want)

    def test_the_reviewers_sentences_keep_every_step(self):
        fix = "Replace its battery. Move it closer to a router."
        for detail in (
                "The battery was fine yesterday, but it is at 4% now.",
                "The battery was good for two years but is now at 3%.",
                "The battery is fine for now but dropping 5% a week.",
                "Its link quality was strong last week but has fallen to 30.",
                "The battery is no good.",
                "The battery is not fine.",
                "Its signal is fine, but it dropped off twice today."):
            with self.subTest(detail):
                self.assertEqual(sre._steps_agree(detail, fix), fix)

    def test_a_step_is_never_left_empty(self):
        fix = "Replace its battery."
        self.assertEqual(sre._steps_agree("The battery is fine.", fix), fix)


# ---------------------------------------------------------------------------
# #583 — the rule's usual-cause aside goes when a look found the cause
# ---------------------------------------------------------------------------

RECORDER_FIX = ("Settings > System > Logs, filtered to recorder: a database "
                "error, a full disk or a restart that interrupted a write is "
                "the usual cause. Settings > System > Repairs may also list a "
                "recorder issue.")


class TestTheUsualCauseAside(unittest.TestCase):
    def test_the_aside_goes_and_the_step_stays(self):
        self.assertEqual(findings_store.without_usual_cause(ZIGBEE_MAINS_FIX),
                         "Zigbee, plugged in: check it still has power.")
        self.assertEqual(findings_store.without_usual_cause(RECORDER_FIX),
                         "Settings > System > Logs, filtered to recorder. "
                         "Settings > System > Repairs may also list a "
                         "recorder issue.")

    def test_the_reviewers_steps_are_untouched(self):
        for fix in (
                "Exclude the entities that write most often from the recorder.",
                "Dry the area and check the pipe under the sink; a loose "
                + "fitting is the most common cause.",
                "(A socket turned off is the usual cause.)"):
            with self.subTest(fix):
                self.assertEqual(findings_store.without_usual_cause(fix), fix)


class TestRefineDropsTheAsideOnlyWhenTheLookFoundTheCause(StoresCase):
    def _row(self):
        [row] = findings_store.add_many([{
            "text": "Landing plug has been unavailable for more than a day",
            "detail": "Unavailable since Tuesday.", "severity": "warning",
            "source": "check:net.zigbee_offline",
            "entity_id": "switch.landing_plug", "fix": ZIGBEE_MAINS_FIX,
            "status": "triaging"}])
        return row

    def test_a_cause_found_strips_the_aside(self):
        row = self._row()
        findings_store.refine(row["ts"], {
            "claim": "The landing plug lost power on Tuesday",
            "kind": "problem",
            "detail": "The hall switch that feeds it went off at 18:02.",
            "evidence": [{"entity": "switch.hall", "reading": "off",
                          "when": "Tue 18:02"}]}, run_id="inv-1")
        stored = findings_store.get(row["ts"])
        self.assertEqual(stored["fix"],
                         "Zigbee, plugged in: check it still has power.")
        self.assertEqual(stored["status"], "open")

    def test_a_look_with_nothing_found_keeps_the_rule_step(self):
        row = self._row()
        findings_store.refine(row["ts"], {
            "claim": "The landing plug is unavailable", "kind": "problem",
            "detail": "Nothing in its history says why."}, run_id="inv-1")
        self.assertEqual(findings_store.get(row["ts"])["fix"], ZIGBEE_MAINS_FIX)


# ---------------------------------------------------------------------------
# #726 — an all-fine card over nothing is not news; steps are never trimmed
# ---------------------------------------------------------------------------

class TestAnAllFineCardOverNothing(unittest.TestCase):
    def test_absence_only_is_nothing_happened(self):
        for obj in (
                {"title": "All quiet",
                 "summary": "The doors stayed shut overnight. Nothing ran."},
                {"title": "Garage: nothing unusual",
                 "summary": "The garage door stayed shut all day."}):
            with self.subTest(obj["title"]):
                self.assertEqual(card_claims.blind_lead(obj),
                                 "nothing happened")

    def test_a_comparison_or_a_problem_is_news(self):
        for obj in (
                {"title": "All quiet", "summary": "Heating ran 3 h, less than "
                                                  "the usual 5 h."},
                {"title": "All quiet", "summary": "No doors opened.",
                 "highlights": [{"label": "Door", "value": "0",
                                 "delta": "-4 vs avg"}]},
                {"title": "All quiet", "summary": "No doors opened.",
                 "findings": [{"text": "Back door lock is jammed"}]},
                {"title": "Dryer vent: nothing new since Sat 17 Oct",
                 "summary": "Nothing new since Sat 17 Oct: no run since."},
                {"title": "Kitchen leak sensor: wet",
                 "summary": "It may be worth checking the pipe under it."}):
            with self.subTest(obj):
                self.assertEqual(card_claims.blind_lead(obj), "")

    def test_the_contract_asks_for_the_shape_and_keeps_the_chart_rules(self):
        c = categories._CARD_CONTRACT
        self.assertLess(len(c), 9100)
        for phrase in ("The title holds the conclusion",
                       "one usual-vs-now comparison", "never the ending",
                       "Leave a left margin", "Hover tooltips on every mark",
                       "bars from zero"):
            self.assertIn(phrase, c)


# ---------------------------------------------------------------------------
# #735 — the first look's "why" never says an elevated row can wait
# ---------------------------------------------------------------------------

REVIEWER_REASONS = (
    "This is not log noise: the leak sensor under the sink has read wet "
    + "for 20 minutes",
    "The Wi-Fi drop cleared up on its own, but the back door has been "
    + "unlocked for 6 hours",
    "Replacing the hub can wait, but this smoke alarm battery needs "
    + "replacing today",
    "It can wait an hour, but past -10 the food is at risk",
)


class TestAReasonIsNeverReadAsAHold(StoresCase):
    def test_an_elevated_row_with_a_wait_in_its_reason_stays_open(self):
        for why in REVIEWER_REASONS:
            with self.subTest(why):
                [row] = findings_store.add_many([{
                    "text": "Under-sink leak sensor reads wet " + why[:12],
                    "detail": "Wet since 14:02.", "severity": "serious",
                    "source": "check:safety.leak",
                    "entity_id": "binary_sensor.sink_leak",
                    "status": "triaging"}])
                findings_store.record_triage(
                    {row["ts"]: ("elevated", why)}, run_id="look-1")
                findings_store.refine(row["ts"], {
                    "claim": "The sink leak sensor is wet",
                    "kind": "problem"}, run_id="inv-1")
                stored = findings_store.get(row["ts"])
                self.assertEqual(stored["status"], "open")
                self.assertEqual(stored["severity"], "serious")


class TestTheFirstLookWording(unittest.TestCase):
    def test_can_wait_belongs_to_watch(self):
        text = resident.FIRST_LOOK_SYSTEM
        self.assertNotIn("why it can wait", text)
        self.assertIn('until somebody next looks is "watch"', text)
        self.assertIn("never that it\n  can wait", text)


if __name__ == "__main__":
    unittest.main()
