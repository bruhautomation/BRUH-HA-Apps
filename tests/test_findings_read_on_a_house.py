#!/usr/bin/env python3
"""How brAIn's findings read on a real house: seven reports, each driven
at the class it belongs to, each with an example the report never named.

* (a) A "Is this fixed now" card cut the report's title at a character
  count and put the rest at the start of its detail ("…(Fix: Findings
  never" / "say who acts: …"). The card's text is the report's own title,
  shortened on a word with an ellipsis only when it was shortened, and
  fits the store's title cap so the store never splits it; the detail
  holds the whole report.
* (b) The same card explained how answers are routed ("Yes tells whoever
  fixed it…", "Nothing is written to memory…") and could carry developer
  text (constants, function calls, tool names). Its detail says what was
  meant to change and where to look, and nothing else.
* (c) An overnight finding about an unavailable device that automations
  still call was titled with their names. It is titled with the device
  and how many things use it; the detail names each once, with no "runs
  not counted"; the fix does not list them all again.
* (d) A log-derived finding said its count twice and pasted the log line,
  HTTP status and JSON. It says each count once and what the error means.
* (e) Quoted log text kept cloud account ids ("accountId: 123456"). The
  shared redactors take them, on the path that files the finding and on
  the paths that leave the house.
* (f) An overnight log finding named one blind and was filed on another
  cover of the same hub. It is filed on the entity the errors name, the
  hub when several are named, and on nothing rather than a guess.
"""
from __future__ import annotations

import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import capture  # noqa: E402
import checks  # noqa: E402
import findings_store  # noqa: E402
import house_words  # noqa: E402
import journal  # noqa: E402
import reports  # noqa: E402
import sre  # noqa: E402
from devloop import upstream, verify  # noqa: E402
from test_sre import NOW, collected  # noqa: E402

integrations = checks.integrations


# ---------------------------------------------------------------------------
# (a) and (b) — the fix question
# ---------------------------------------------------------------------------

LONG_TITLE = ("The morning brief and the weekly report never say which room "
              "a finding is about, so nobody in the house knows where to go "
              "or which of the sprayers to take out first when several "
              "trees are due on the same morning")
GARDEN = {"fp": "a" * 16, "verdict": "fixed", "stream": "look",
          "fixed_in": "0.4.2", "product": "GardenRX",
          "where": f"GardenRX · Fix: {LONG_TITLE}",
          "what": ("Spray reminders on the Today screen stop at the first "
                   "crop and leave the rest of the orchard out, so a tree "
                   "that is due is never mentioned until somebody opens "
                   "the crop list by hand and reads every row in turn.")}
CHAT = {"fp": "b" * 16, "verdict": "fixed", "stream": "unmet",
        "fixed_in": "4.0.3", "where": "Chat",
        "what": ("brAIn could not turn the porch light off at sunrise when "
                 "asked in the chat, because it said it had no way to run "
                 "something at a time of day and offered to write an "
                 "automation instead of doing what it was asked to do, "
                 "which is the thing the owner wanted in the first place.")}
DEVELOPER = {"fp": "c" * 16, "verdict": "fixed", "stream": "look",
             "fixed_in": "4.0.3", "where": "Fix: Cards on a phone",
             "what": ("A long card on a phone is cut off before its "
                      "buttons. The `renderCard()` helper caps it with "
                      "CARD_MAX_LINES 40 in app.js. The get_findings tool "
                      "returns the whole row.")}
_DEV_TEXT = re.compile(r"`|\(\)|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b|\b[a-z]+_[a-z0-9_]+\b"
                       r"|\.(?:py|js|css|sh)\b")
_PLUMBING = ("Yes tells", "No sends", "written to memory", "reopens it")


class TestAFixQuestionIsTheReportsOwnTitle(unittest.TestCase):
    def stored(self, entry: dict) -> tuple[dict, dict]:
        row = verify.question_row(entry)
        return row, findings_store.coerce(row)

    def test_the_store_never_moves_part_of_the_title_into_the_detail(self):
        for entry in (GARDEN, CHAT):
            with self.subTest(entry["stream"]):
                row, kept = self.stored(entry)
                self.assertLessEqual(len(row["text"]), findings_store.MAX_TEXT)
                self.assertEqual(kept["text"], row["text"])
                self.assertEqual(kept["detail"], row["detail"])

    def test_the_title_is_shortened_on_a_word_and_says_so(self):
        row = verify.question_row(GARDEN)
        said = row["text"][len(verify.TEXT_PREFIX):]
        head = said.split("…")[0].rstrip()
        self.assertIn("…", said, said)
        self.assertTrue(LONG_TITLE.startswith(head), (head, said))
        self.assertTrue(LONG_TITLE[len(head):][:1] in (" ", ""), head)
        self.assertNotIn("Fix:", row["text"])
        self.assertIn("GardenRX 0.4.2", row["text"])

    def test_a_title_that_fits_carries_no_ellipsis(self):
        row = verify.question_row({**GARDEN,
                                   "where": "GardenRX · Fix: Spray reminders"})
        self.assertNotIn("…", row["text"])
        self.assertIn("Spray reminders", row["text"])

    def test_the_detail_holds_the_whole_report(self):
        for entry in (GARDEN, CHAT):
            with self.subTest(entry["stream"]):
                row = verify.question_row(entry)
                self.assertIn(entry["what"].rstrip("."), row["detail"])


class TestAFixQuestionSaysWhatChangedAndWhere(unittest.TestCase):
    def test_no_plumbing(self):
        for entry in (GARDEN, CHAT, DEVELOPER):
            row = verify.question_row(entry)
            for words in _PLUMBING:
                with self.subTest(entry["stream"], words=words):
                    self.assertNotIn(words, row["detail"])

    def test_no_developer_text(self):
        row = verify.question_row(DEVELOPER)
        self.assertIsNone(_DEV_TEXT.search(row["detail"]), row["detail"])
        self.assertIn("cut off before its buttons", row["detail"])

    def test_it_says_where_to_look(self):
        self.assertIn("Chat", verify.question_row(CHAT)["detail"])
        self.assertIn("GardenRX", verify.question_row(GARDEN)["detail"])


# ---------------------------------------------------------------------------
# (c) — a device automations still call
# ---------------------------------------------------------------------------

MISSING = ("Referenced entities light.hall_pendant are missing or not "
           "currently available")


def pendant_house():
    target = {"target": {"entity_id": "light.hall_pendant"}}
    states = {"light.hall_pendant": {"state": "unavailable", "attributes": {
        "friendly_name": "Hall pendant"}}}
    scenes = []
    for n, name in ((1, "Dinner"), (2, "Movie night")):
        states[f"scene.s{n}"] = {"state": "x", "attributes": {
            "id": f"s{n}", "friendly_name": name}}
        scenes.append({"id": f"s{n}", "name": name,
                       "entities": {"light.hall_pendant": {"state": "on"}}})
    states["automation.hall_dusk"] = {"state": "on", "attributes": {
        "id": "a1", "friendly_name": "Hall at dusk"}}
    states["script.hall_off"] = {"state": "off", "attributes": {
        "friendly_name": "Hall off"}}
    return collected(
        log=[{"name": "homeassistant.helpers.service", "message": [MISSING],
              "level": "WARNING", "source": ["x.py", 1],
              "timestamp": NOW - 60, "count": 9,
              "first_occurred": NOW - 20000}],
        zha=[],
        entities=[{"entity_id": "light.hall_pendant", "device_id": "dev-hp",
                   "platform": "hue"}],
        devices=[{"id": "dev-hp", "name": "Hall pendant"}],
        states=states,
        automations=[{"id": "a1", "alias": "Hall at dusk", "actions": [
            {"action": "light.turn_on", **target}]}],
        scripts={"hall_off": {"alias": "Hall off", "sequence": [
            {"action": "light.turn_off", **target}]}},
        scenes=scenes)


CALLERS = ("Hall at dusk", "Hall off", "Dinner", "Movie night")


class TestAnUnavailableDeviceStillCalled(unittest.TestCase):
    def row(self):
        dig = sre.digest(pendant_house(), NOW)
        recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
        parsed = sre.parse_causes({"causes": [{
            "title": "Hall at dusk, Hall off, Dinner and Movie night still "
                     "control Hall pendant", "records": recs[:1],
            "detail": "They keep trying.", "fix": "Fix them."}]}, dig)
        return sre.rows(parsed["causes"], dig, {"anchors": {}}, NOW)[0]

    def test_the_title_is_the_device_and_a_count(self):
        row = self.row()
        self.assertTrue(row["text"].startswith(
            "Hall pendant is offline and 4 "), row["text"])
        self.assertIn("still use it", row["text"])
        for name in CALLERS:
            self.assertNotIn(name, row["text"].replace("Hall pendant", ""))

    def test_the_detail_names_each_once_with_no_bookkeeping(self):
        row = self.row()
        for name in CALLERS:
            self.assertEqual(len(re.findall(rf"\b{re.escape(name)}\b",
                                            row["detail"])), 1,
                             (name, row["detail"]))
        self.assertNotIn("not counted", row["detail"])

    def test_the_fix_does_not_list_them_again(self):
        row = self.row()
        self.assertLess(sum(name in row["fix"] for name in CALLERS), 2,
                        row["fix"])
        self.assertIn("Hall pendant", row["fix"])


# ---------------------------------------------------------------------------
# (d) — a log finding says what the error means, once
# ---------------------------------------------------------------------------

RAW = re.compile(r"[“”\"{}]|\b[1-5]\d\d\b|url=|message=")


def overkiz_house(log, **over):
    return collected(
        log=log, zha=[], automations=[],
        entities=[
            {"entity_id": "cover.bedroom_blind", "device_id": "dev-b1",
             "platform": "overkiz"},
            {"entity_id": "cover.kitchen_blind", "device_id": "dev-b2",
             "platform": "overkiz"},
            {"entity_id": "sensor.tahoma_box", "device_id": "dev-hub",
             "platform": "overkiz"}],
        devices=[{"id": "dev-b1", "name": "io motor 1",
                  "via_device_id": "dev-hub"},
                 {"id": "dev-b2", "name": "io motor 2",
                  "via_device_id": "dev-hub"},
                 {"id": "dev-hub", "name": "TaHoma box"}],
        states={"cover.bedroom_blind": {"state": "open", "attributes": {
                    "friendly_name": "Bedroom blind"}},
                "cover.kitchen_blind": {"state": "open", "attributes": {
                    "friendly_name": "Kitchen blind"}},
                "sensor.tahoma_box": {"state": "ok", "attributes": {
                    "friendly_name": "TaHoma box"}}},
        manifests=[{"domain": "overkiz", "name": "Overkiz"}],
        **over)


def log_row(message, count=12, logger="homeassistant.components.overkiz"):
    return {"name": logger, "message": [message], "level": "ERROR",
            "source": ["x.py", 1], "timestamp": NOW - 3600, "count": count,
            "first_occurred": NOW - 40000}


def one_cause(house, **cause):
    dig = sre.digest(house, NOW)
    recs = [r["id"] for r in dig["records"] if r["kind"] == "log"]
    parsed = sre.parse_causes({"causes": [{"title": "Errors in the log",
                                           "records": recs[:1], **cause}]},
                              dig)
    return sre.rows(parsed["causes"], dig, {"anchors": {}}, NOW)


SERVER = ("Error fetching Kitchen blind data: 503, message='Service "
          "Unavailable', url=URL('https://ha101-1.overkiz.com/enduser')")


class TestALogFindingSaysWhatTheErrorMeans(unittest.TestCase):
    def test_the_overnight_check(self):
        [row] = one_cause(overkiz_house([log_row(SERVER)]),
                          detail="Kitchen blind failed 12 times overnight.",
                          fix="Check the Overkiz cloud for Kitchen blind.")
        self.assertIsNone(RAW.search(row["detail"]), row["detail"])
        self.assertEqual(len(re.findall(r"\b12\b", row["detail"])), 1,
                         row["detail"])
        self.assertIn(house_words.log_meaning(SERVER), row["detail"])

    def test_a_models_detail_quoting_the_line_loses_that_sentence(self):
        [row] = one_cause(
            overkiz_house([log_row('Kitchen blind answered {"code": 500}')]),
            detail=('The log says “Kitchen blind answered {"code": 500}”. '
                    "The blind is not answering its hub."))
        self.assertIsNone(RAW.search(row["detail"]), row["detail"])
        self.assertIn("not answering its hub", row["detail"])

    def test_the_flood_check(self):
        from test_house_checks import NOW as CNOW, house
        snap = house()
        message = "Error requesting data: 401, message='Unauthorized'"
        snap["core_log"] = {"hours": 24, "lines": 300, "groups": [{
            "logger": "homeassistant.components.tado", "domain": "tado",
            "count": 1200, "last": CNOW, "ips": [], "message": message}]}
        [row] = integrations.log_flood(snap, CNOW)
        self.assertIsNone(RAW.search(row["detail"]), row["detail"])
        self.assertEqual(len(re.findall(r"\b1200\b", row["detail"])), 1)
        self.assertIn(house_words.log_meaning(message), row["detail"])

    def test_meanings_are_plain_words(self):
        for message in (SERVER, "Timed out reaching the hub",
                        "Error requesting data: 401", '{"error": "x"}',
                        "Something odd happened"):
            with self.subTest(message):
                said = house_words.log_meaning(message)
                self.assertTrue(said)
                self.assertIsNone(RAW.search(said), said)


# ---------------------------------------------------------------------------
# (e) — account ids in quoted log text
# ---------------------------------------------------------------------------

IDS = [("accountId: 123456", "accountId: [redacted]"),
       ("customerId=CU-77812", "customerId=[redacted]"),
       ('"user_id": "9f8e7d6c"', '"user_id": "[redacted]"'),
       ("account_id = 55501", "account_id = [redacted]")]


def shell_redact(text: str) -> str:
    src = (BASE_DIR / "brain" / "scripts" / "brain-report.sh").read_text(
        encoding="utf-8")
    start = src.index("redact() {")
    block = src[start:src.index("\n}\n", start) + 3]
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "sample.txt"
        proc = subprocess.run(
            ["bash", "-c", block + '\nprintf "%s" "$1" > "$2"\nredact "$2"\n'
             'cat "$2"\n', "_", text, str(target)],
            capture_output=True, text=True, timeout=30)
    return proc.stdout


class TestAccountIdsAreRedacted(unittest.TestCase):
    def test_every_redactor(self):
        for raw, want in IDS:
            text = f"Login refused for {raw} by the cloud"
            expected = f"Login refused for {want} by the cloud"
            for name, fn in (("capture", capture.redact),
                             ("journal", journal.scrub),
                             ("reports", reports.redact),
                             ("upstream", upstream.scrub),
                             ("shell", shell_redact)):
                with self.subTest(raw, redactor=name):
                    self.assertEqual(fn(text), expected)

    def test_a_house_word_is_left_alone(self):
        for text in ("user is home", "the account is fine",
                     "sensor.user_id_badge is on"):
            self.assertEqual(reports.redact(text), text)

    def test_the_overnight_finding_and_the_flood_summary(self):
        message = "Cloud refused Kitchen blind: accountId: 884213, retrying"
        dig = sre.digest(overkiz_house([log_row(message)]), NOW)
        [rec] = [r for r in dig["records"] if r["kind"] == "log"]
        self.assertNotIn("884213", rec["message"])
        line = ("2026-10-27 10:00:00.000 ERROR (MainThread) "
                "[homeassistant.components.tado] " + message)
        import datetime as dt
        summary = integrations.summarise_log(
            "\n".join([line] * 3),
            dt.datetime(2026, 10, 27, 11, 0, tzinfo=dt.timezone.utc)
            .timestamp(), dt.timezone.utc)
        self.assertNotIn("884213", summary["groups"][0]["message"])


# ---------------------------------------------------------------------------
# (f) — which entity a log finding is filed on
# ---------------------------------------------------------------------------

class TestALogFindingIsFiledOnWhatItNames(unittest.TestCase):
    def test_the_blind_the_errors_name(self):
        [row] = one_cause(overkiz_house([log_row(
            "Kitchen blind did not respond to the command")]))
        self.assertEqual(row["entity_id"], "cover.kitchen_blind")

    def test_several_on_one_hub_is_the_hub(self):
        [row] = one_cause(overkiz_house([log_row(
            "Kitchen blind and Bedroom blind did not respond")]))
        self.assertEqual(row["entity_id"], "sensor.tahoma_box")

    def test_nothing_named_is_no_entity_not_a_sibling(self):
        [row] = one_cause(overkiz_house([log_row(
            "Server disconnected while polling events")]))
        self.assertEqual(row["entity_id"], "")
        self.assertEqual(row.get("integration"), "overkiz")


if __name__ == "__main__":
    unittest.main()
