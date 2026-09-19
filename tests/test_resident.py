#!/usr/bin/env python3
"""Tests for the Resident — the attention loop's judgement, driven directly.

Nothing here spawns a model, because nothing in `resident.py` can: it
builds prompts and reads replies, and the server does the spawning. What
that buys is that every guard below is exercised against the failure it
exists to prevent rather than described, which is the only way a prompt's
rules have ever been held in this repo.

Four of them are reproduced before they are asserted, because each is a
rule that only means something if the thing it stops can be shown
happening:

  * a first look that says "ignore" about a leak. The model's word is
    taken as written when nothing is watching, and overridden when the
    guard is handed the batch — so the test can show the guard doing the
    work rather than a fixture that happens to be safe.
  * a reply that skipped a signal. The signal is `watch` carrying the
    sentence that says nothing came back, never absent.
  * a case whose evidence names an entity the run never read. Refused
    whole, and the same reply parses when there is nothing to check it
    against — "I could not look" is not "nothing is wrong".
  * a ledger that a restart resets. Driven across two instances over one
    file, and across a local day boundary.
"""

import datetime as dt
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import model_plan  # noqa: E402
import resident  # noqa: E402


def signal(**fields) -> dict:
    """One signal in the shape the signals module publishes."""
    return {"kind": "baseline", "subject": "sensor.hall_temperature",
            "salience": 0.4, "evidence": [], "seen_at": 1_760_000_000,
            "source": "baselines", "hot": False, "repeats": 1, **fields}


def reply(rows) -> dict:
    return {"verdicts": rows}


# ---------------------------------------------------------------------------
# The first look
# ---------------------------------------------------------------------------

class TestTheFirstLookReadsWhatItWasGiven(unittest.TestCase):
    def test_a_plain_reply_parses_to_one_verdict_each(self):
        out = resident.parse_first_look(
            reply([{"id": 1, "verdict": "ignore", "why": "a cupboard door"},
                   {"id": 2, "verdict": "investigate", "why": "it has moved"}]),
            2)
        self.assertEqual(out[1]["verdict"], "ignore")
        self.assertEqual(out[2]["verdict"], "investigate")
        self.assertFalse(out[1]["forced"])
        self.assertEqual(out[1]["why"], "a cupboard door")

    def test_a_reply_that_is_a_json_string_is_read(self):
        out = resident.parse_first_look(
            json.dumps(reply([{"id": 1, "verdict": "act", "why": "water"}])), 1)
        self.assertEqual(out[1]["verdict"], "act")

    def test_a_signal_the_reply_skipped_is_watched_and_says_so(self):
        """Silence surfaces — and here surfacing is the watch list, not a
        card. A signal nobody judged has to be kept, and the sentence that
        says nothing came back is what makes the keeping readable."""
        out = resident.parse_first_look(
            reply([{"id": 1, "verdict": "ignore", "why": "fine"}]), 3)
        for idx in (2, 3):
            self.assertEqual(out[idx]["verdict"], "watch")
            self.assertEqual(out[idx]["why"], resident.SKIPPED)
            self.assertTrue(out[idx]["forced"])

    def test_an_unreadable_reply_watches_the_whole_batch(self):
        for bad in ("not json at all", None, {"verdicts": "nope"}, 7):
            out = resident.parse_first_look(bad, 2)
            self.assertEqual({v["verdict"] for v in out.values()}, {"watch"})
            self.assertEqual(out[1]["why"], resident.UNREADABLE)

    def test_a_verdict_nobody_asked_for_is_dropped_not_coerced(self):
        """An invented verdict reads exactly like a real one; dropping it
        makes the signal a skipped one, which is watched."""
        out = resident.parse_first_look(
            reply([{"id": 1, "verdict": "probably fine", "why": "hmm"}]), 1)
        self.assertEqual(out[1]["verdict"], "watch")
        self.assertEqual(out[1]["why"], resident.SKIPPED)

    def test_an_id_outside_the_batch_is_ignored_and_the_first_wins(self):
        out = resident.parse_first_look(
            reply([{"id": 9, "verdict": "act", "why": "not in the batch"},
                   {"id": 1, "verdict": "ignore", "why": "first"},
                   {"id": 1, "verdict": "act", "why": "second"}]), 1)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[1]["why"], "first")


class TestNothingMayBeIgnored(unittest.TestCase):
    """The one thing a model's verdict cannot overrule."""

    def test_the_model_is_believed_when_nothing_is_watching(self):
        """The failure, reproduced: with no batch to read, `ignore` about a
        leak stands. The guard is what changes it, and the next test is
        what shows it doing so."""
        out = resident.parse_first_look(
            reply([{"id": 1, "verdict": "ignore", "why": "nothing here"}]), 1)
        self.assertEqual(out[1]["verdict"], "ignore")

    def test_a_leak_cannot_be_ignored(self):
        rows = [signal(kind="check:leak", subject="binary_sensor.utility_leak")]
        out = resident.parse_first_look(
            reply([{"id": 1, "verdict": "ignore", "why": "nothing here"}]),
            1, rows)
        self.assertEqual(out[1]["verdict"], resident.NEVER_IGNORE_FLOOR)
        self.assertTrue(out[1]["forced"])
        self.assertIn("leak", out[1]["why"])
        # The model's own sentence survives beside the guard's, because it
        # is the evidence that the guard was needed.
        self.assertIn("nothing here", out[1]["why"])

    def test_a_skipped_leak_is_investigated_rather_than_merely_watched(self):
        """The floor runs after the skipped rows are filled in, or a
        signal nothing answered about would take the softer verdict."""
        out = resident.parse_first_look(reply([]), 1, [signal(kind="leak")])
        self.assertEqual(out[1]["verdict"], "investigate")

    def test_a_hot_signal_earns_the_lower_floor(self):
        """`hot` is about WHEN, not about how much it matters, so what it
        buys is "do not forget this" and never a paid run."""
        out = resident.parse_first_look(
            reply([{"id": 1, "verdict": "ignore", "why": "routine"}]),
            1, [signal(hot=True)])
        self.assertEqual(out[1]["verdict"], "watch")

    def test_a_producers_own_flags_are_honoured(self):
        for flag, floor in resident.FLAG_FLOORS.items():
            out = resident.parse_first_look(
                reply([{"id": 1, "verdict": "ignore", "why": "routine"}]),
                1, [signal(**{flag: True})])
            self.assertEqual(out[1]["verdict"], floor, flag)

    def test_a_floor_raises_and_never_lowers(self):
        out = resident.parse_first_look(
            reply([{"id": 1, "verdict": "act", "why": "water on the floor"}]),
            1, [signal(hot=True, kind="leak")])
        self.assertEqual(out[1]["verdict"], "act")
        self.assertFalse(out[1]["forced"])

    def test_the_highest_floor_wins_whichever_was_checked_first(self):
        floor, why = resident.never_ignore(signal(hot=True, kind="check:smoke"))
        self.assertEqual(floor, resident.NEVER_IGNORE_FLOOR)
        self.assertIn("smoke", why)

    def test_the_subject_is_not_a_name_gate(self):
        """Pinned because it is a decision rather than an oversight: the
        gate reads the signal's KIND and the producer's flags, never
        somebody's entity naming scheme."""
        floor, _ = resident.never_ignore(
            signal(kind="baseline", subject="sensor.kitchen_leak_detector"))
        self.assertEqual(floor, "")

    def test_a_signal_that_is_not_a_dict_floors_nothing(self):
        self.assertEqual(resident.never_ignore("leak"), ("", ""))
        self.assertEqual(resident.never_ignore(None), ("", ""))


class TestTheFirstLookPrompt(unittest.TestCase):
    def test_signals_are_numbered_never_named_back(self):
        text = resident.first_look_prompt([signal(), signal(kind="check:dev")])
        self.assertIn("1. ", text)
        self.assertIn("2. ", text)

    def test_the_memory_and_the_open_cases_ride_in(self):
        text = resident.first_look_prompt(
            ["a signal"], "The garage fridge runs all night",
            ["The hall sensor has not reported since Tuesday"])
        self.assertIn("The garage fridge runs all night", text)
        self.assertIn("since Tuesday", text)

    def test_a_raw_signal_renders_without_the_signals_module(self):
        text = resident.first_look_prompt([signal(hot=True)])
        self.assertIn("sensor.hall_temperature", text)
        self.assertIn("urgent", text)

    def test_the_contract_states_the_rule_it_exists_for(self):
        system = resident.FIRST_LOOK_SYSTEM
        for word in ("water", "smoke", "freeze", "security", "protected"):
            self.assertIn(word, system)
        self.assertIn("health", system)
        for verdict in resident.VERDICTS:
            self.assertIn(f'"{verdict}"', system)

    def test_the_schema_admits_one_spelling_of_each_verdict(self):
        enum = (resident.FIRST_LOOK_SCHEMA["properties"]["verdicts"]["items"]
                ["properties"]["verdict"]["enum"])
        self.assertEqual(tuple(enum), resident.VERDICTS)


# ---------------------------------------------------------------------------
# The investigation
# ---------------------------------------------------------------------------

def case_reply(**fields) -> dict:
    out = {
        "claim": "The garage freezer has been drifting warmer for a fortnight",
        "detail": "It reads 6C warmer than a month ago and the trend is flat.",
        "kind": "problem",
        "confidence": 0.8,
        "stakes": "high",
        "fix": "Check the door seal on the garage freezer.",
        "evidence": [{"entity": "sensor.garage_freezer_temp",
                      "value": "-12.4", "when": "now"}],
        "actions": [{"label": "Tell me when it passes -10",
                     "shape": "notify", "consent": False, "detail": ""}],
        "memory_hint": "The garage freezer sits in an unheated garage.",
        "escalate": False,
    }
    out.update(fields)
    return out


class TestTheCaseReply(unittest.TestCase):
    def test_a_full_reply_becomes_a_row_the_store_can_file(self):
        case = resident.parse_case(case_reply())
        self.assertEqual(case["claim"], case["text"])
        self.assertEqual(case["kind"], "problem")
        self.assertEqual(case["stakes"], "high")
        self.assertEqual(case["severity"],
                         resident.SEVERITY_BY_STAKES["high"])
        self.assertEqual(case["fix_by"], "resident")
        self.assertEqual(case["evidence"][0]["entity"],
                         "sensor.garage_freezer_temp")

    def test_high_stakes_is_not_the_notifiers_escalation_tier(self):
        """`critical` pushes through quiet hours and repeats on a ladder.
        That is a decision about a phone at 3am, not one a run's own sense
        of its own importance may reach."""
        self.assertNotIn("critical", resident.SEVERITY_BY_STAKES.values())

    def test_no_claim_is_no_case(self):
        for bad in (case_reply(claim=""), case_reply(claim="   "), {},
                    "not json", None, []):
            self.assertIsNone(resident.parse_case(bad))

    def test_evidence_naming_an_entity_the_run_never_read_is_refused(self):
        """Reproduced first: the same reply parses with nothing to check
        it against, because "I could not look" may not throw away a real
        investigation. Handed what the run actually touched, an invented
        reading refuses the WHOLE case — the claim was reasoned from it,
        so trimming the row leaves the conclusion it produced."""
        reply_with_invention = case_reply(evidence=[
            {"entity": "sensor.garage_freezer_temp", "value": "-12.4",
             "when": "now"},
            {"entity": "sensor.that_does_not_exist", "value": "9",
             "when": "yesterday"}])
        self.assertIsNotNone(resident.parse_case(reply_with_invention))
        self.assertIsNone(resident.parse_case(
            reply_with_invention,
            read_entities={"sensor.garage_freezer_temp"}))

    def test_evidence_the_run_did_read_survives_the_check(self):
        case = resident.parse_case(
            case_reply(), read_entities={"sensor.garage_freezer_temp",
                                         "sensor.hall_temperature"})
        self.assertEqual(len(case["evidence"]), 1)

    def test_an_evidence_row_with_no_entity_is_not_evidence(self):
        case = resident.parse_case(case_reply(
            evidence=[{"entity": "", "value": "9", "when": "now"}]))
        self.assertEqual(case["evidence"], [])

    def test_escalate_is_read_only_where_the_plan_says_it_may_be(self):
        unsure_and_serious = case_reply(confidence=0.3, stakes="high",
                                        escalate=True)
        self.assertTrue(resident.parse_case(unsure_and_serious)["escalate"])
        for ignored in (case_reply(confidence=0.9, stakes="high",
                                   escalate=True),
                        case_reply(confidence=0.3, stakes="low",
                                   escalate=True),
                        case_reply(confidence=0.3, stakes="medium",
                                   escalate=True)):
            self.assertFalse(resident.parse_case(ignored)["escalate"])

    def test_an_action_whose_consent_could_not_be_read_asks_anyway(self):
        case = resident.parse_case(case_reply(actions=[
            {"label": "Write it", "shape": "write_automation"}]))
        self.assertTrue(case["actions"][0]["consent"])

    def test_an_unreadable_confidence_is_no_confidence(self):
        case = resident.parse_case(case_reply(confidence="very"))
        self.assertEqual(case["confidence"], 0.0)

    def test_a_kind_this_cannot_decide_it_found_is_refused(self):
        """A change is something brAIn DID and a chore is what a person
        agreed to; neither is a thing an investigation discovers."""
        for kind in ("change", "chore", "nonsense"):
            self.assertEqual(resident.parse_case(case_reply(kind=kind))["kind"],
                             "problem")

    def test_the_contract_forbids_the_two_things_it_must(self):
        system = resident.INVESTIGATE_SYSTEM
        self.assertIn("NEVER invent", system)
        self.assertIn("health", system)
        self.assertIn("whereabouts", system)

    def test_the_prompt_carries_the_signal_and_what_is_already_asked(self):
        text = resident.investigate_prompt(
            signal(subject="sensor.garage_freezer_temp"),
            "It is an unheated garage", "25 baselines measured",
            ["The hall sensor is unavailable"])
        self.assertIn("sensor.garage_freezer_temp", text)
        self.assertIn("unheated garage", text)
        self.assertIn("25 baselines measured", text)
        self.assertIn("hall sensor is unavailable", text)


# ---------------------------------------------------------------------------
# The watch list
# ---------------------------------------------------------------------------

class WatchCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = resident.WATCH_FILE
        resident.WATCH_FILE = Path(self.tmp.name) / "resident-watch.json"

    def tearDown(self):
        resident.WATCH_FILE = self._old
        self.tmp.cleanup()


class TestTheWatchList(WatchCase):
    def test_watching_records_the_repeat_count_it_started_from(self):
        entry = resident.watch(signal(repeats=4), "one reading is not a trend",
                               now=1000.0)
        self.assertEqual(entry["repeats"], 4)
        self.assertEqual(resident.watched()["sensor.hall_temperature"]["why"],
                         "one reading is not a trend")

    def test_a_subject_nothing_is_watching_goes_straight_in(self):
        self.assertTrue(resident.rejudge_due(signal(), now=1000.0))

    def test_a_watched_subject_waits_for_evidence_and_not_for_the_clock(self):
        resident.watch(signal(repeats=4), "if it happens again", now=1000.0)
        # A year later, with nothing further seen: still held. The clock
        # buys the identical answer over the identical data.
        self.assertFalse(resident.rejudge_due(
            signal(repeats=4), now=1000.0 + resident.WATCH_TTL_S - 1))
        # One more occurrence is not enough either.
        self.assertFalse(resident.rejudge_due(signal(repeats=5), now=2000.0))
        self.assertTrue(resident.rejudge_due(
            signal(repeats=4 + resident.WATCH_RETRY_REPEATS), now=2000.0))

    def test_a_watch_that_has_aged_out_lets_the_next_signal_through(self):
        resident.watch(signal(repeats=4), "if it happens again", now=1000.0)
        self.assertTrue(resident.rejudge_due(
            signal(repeats=4), now=1000.0 + resident.WATCH_TTL_S + 1))

    def test_a_watch_cannot_hold_a_leak_back(self):
        resident.watch(signal(kind="leak", repeats=1), "quiet", now=1000.0)
        self.assertTrue(resident.rejudge_due(signal(kind="leak", repeats=1),
                                             now=1001.0))

    def test_expire_drops_what_has_aged_out_and_says_how_many(self):
        resident.watch(signal(subject="a"), "", now=1000.0)
        resident.watch(signal(subject="b"), "", now=1000.0)
        resident.watch(signal(subject="c"),
                       "", now=1000.0 + resident.WATCH_TTL_S)
        gone = resident.expire(now=1000.0 + resident.WATCH_TTL_S + 1)
        self.assertEqual(gone, 2)
        self.assertEqual(set(resident.watched()), {"c"})

    def test_a_signal_with_no_subject_is_not_watched(self):
        self.assertEqual(resident.watch(signal(subject="")), {})
        self.assertEqual(resident.watched(), {})

    def test_a_file_that_cannot_be_read_watches_nothing(self):
        resident.WATCH_FILE.write_text("{ torn", encoding="utf-8")
        self.assertEqual(resident.watched(), {})
        self.assertTrue(resident.rejudge_due(signal(), now=1000.0))


# ---------------------------------------------------------------------------
# The budget ledger
# ---------------------------------------------------------------------------

DAY = 86400
# 2026-09-19T12:00:00Z and the same clock a day later, so the day key
# really does turn between them under the ledger's own timezone.
NOON = dt.datetime(2026, 9, 19, 12, tzinfo=dt.timezone.utc).timestamp()


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "resident-ledger.json"

    def tearDown(self):
        self.tmp.cleanup()

    def ledger(self) -> resident.Ledger:
        return resident.Ledger(self.path)


class TestTheLedger(LedgerCase):
    def test_the_cheap_tier_never_stops_on_the_ledger(self):
        led = self.ledger()
        for _ in range(500):
            led.record(resident.JOB_FIRST_LOOK, 3000, now=NOON)
        self.assertEqual(led.allows("haiku", "light", False, now=NOON),
                         (True, ""))

    def test_the_account_being_out_stops_everything_including_the_cheap_tier(self):
        led = self.ledger()
        for tier in model_plan.TIERS:
            ok, why = led.allows(tier, "normal", True, now=NOON)
            self.assertFalse(ok, tier)
            self.assertIn("usage window", why)
        # Not even a press, because a press cannot conjure a window.
        self.assertFalse(led.allows("sonnet", "normal", True, pressed=True,
                                    now=NOON)[0])

    def test_investigations_queue_past_the_days_allowance(self):
        for thinking, cap in resident.SONNET_PER_DAY.items():
            with self.subTest(thinking=thinking):
                tmp = tempfile.TemporaryDirectory()
                led = resident.Ledger(Path(tmp.name) / "l.json")
                for _ in range(cap):
                    self.assertTrue(
                        led.allows("sonnet", thinking, False, now=NOON)[0])
                    led.record(resident.JOB_INVESTIGATE, 20_000, now=NOON)
                ok, why = led.allows("sonnet", thinking, False, now=NOON)
                self.assertFalse(ok)
                self.assertIn(thinking, why)
                self.assertIn(str(cap), why)
                tmp.cleanup()

    def test_the_top_tier_has_its_own_allowance_and_light_is_none(self):
        led = self.ledger()
        self.assertFalse(led.allows("opus", "light", False, now=NOON)[0])
        self.assertTrue(led.allows("opus", "normal", False, now=NOON)[0])
        for _ in range(resident.OPUS_PER_DAY["normal"]):
            led.record(resident.JOB_APPLY, 40_000, now=NOON)
        self.assertFalse(led.allows("opus", "normal", False, now=NOON)[0])

    def test_the_press_tier_never_runs_unattended(self):
        led = self.ledger()
        ok, why = led.allows("fable", "generous", False, now=NOON)
        self.assertFalse(ok)
        self.assertIn("press", why)
        self.assertTrue(led.allows("fable", "generous", False, pressed=True,
                                   now=NOON)[0])

    def test_a_press_runs_although_the_allowance_is_spent(self):
        led = self.ledger()
        for _ in range(resident.SONNET_PER_DAY["normal"]):
            led.record(resident.JOB_INVESTIGATE, 0, now=NOON)
        self.assertFalse(led.allows("sonnet", "normal", False, now=NOON)[0])
        self.assertTrue(led.allows("sonnet", "normal", False, pressed=True,
                                   now=NOON)[0])

    def test_an_unknown_thinking_setting_reads_as_the_default(self):
        led = self.ledger()
        for _ in range(resident.SONNET_PER_DAY[model_plan.DEFAULT_THINKING]):
            led.record(resident.JOB_INVESTIGATE, 0, now=NOON)
        self.assertFalse(led.allows("sonnet", "lavish", False, now=NOON)[0])

    def test_a_tier_that_does_not_exist_is_refused_rather_than_guessed(self):
        ok, why = self.ledger().allows("genius", "normal", False, now=NOON)
        self.assertFalse(ok)
        self.assertIn("genius", why)

    def test_a_day_boundary_gives_the_allowance_back(self):
        led = self.ledger()
        for _ in range(resident.SONNET_PER_DAY["normal"]):
            led.record(resident.JOB_INVESTIGATE, 0, now=NOON)
        self.assertFalse(led.allows("sonnet", "normal", False, now=NOON)[0])
        self.assertTrue(led.allows("sonnet", "normal", False,
                                   now=NOON + DAY)[0])
        self.assertEqual(led.summary(NOON + DAY)["investigated"], 0)

    def test_a_restart_does_not_reset_a_day(self):
        """`schedule_store`'s rule: a restart is the first thing anybody
        does after changing an option, so an in-memory count turns "twice
        a day" into "twice per restart"."""
        first = self.ledger()
        for _ in range(resident.SONNET_PER_DAY["normal"]):
            first.record(resident.JOB_INVESTIGATE, 1000, now=NOON)
        after_restart = self.ledger()
        self.assertFalse(
            after_restart.allows("sonnet", "normal", False, now=NOON)[0])
        self.assertEqual(after_restart.summary(NOON)["investigated"],
                         resident.SONNET_PER_DAY["normal"])

    def test_a_ledger_that_cannot_be_read_reads_as_nothing_spent(self):
        self.path.write_text("{ torn", encoding="utf-8")
        led = self.ledger()
        self.assertEqual(led.spent("sonnet", NOON), 0)
        self.assertTrue(led.allows("sonnet", "normal", False, now=NOON)[0])

    def test_recording_never_raises_however_it_fails(self):
        led = resident.Ledger(Path(self.tmp.name) / "nope" / "x" / "l.json")
        os.chmod(self.tmp.name, 0o500)
        try:
            led.record(resident.JOB_FIRST_LOOK, 10, now=NOON)
        finally:
            os.chmod(self.tmp.name, 0o700)

    def test_the_summary_is_the_line_the_feed_shows(self):
        led = self.ledger()
        for _ in range(3):
            led.record(resident.JOB_FIRST_LOOK, 2500, now=NOON)
        led.record(resident.JOB_INVESTIGATE, 18_000, now=NOON)
        led.record(resident.JOB_PLAN, 12_000, now=NOON)
        out = led.summary(NOON)
        self.assertEqual(out["looked"], 3)
        self.assertEqual(out["investigated"], 1)
        # A plan is a read-only run that says what it WOULD change, so the
        # foot's "changed nothing" stays true.
        self.assertEqual(out["acted"], 0)
        self.assertEqual(out["tokens"]["haiku"], 7500)
        self.assertEqual(out["day"], "2026-09-19")
        led.record(resident.JOB_APPLY, 40_000, now=NOON)
        self.assertEqual(led.summary(NOON)["acted"], 1)

    def test_the_file_never_grows_past_a_week(self):
        led = self.ledger()
        for day in range(20):
            led.record(resident.JOB_FIRST_LOOK, 1, now=NOON + day * DAY)
        kept = json.loads(self.path.read_text())["days"]
        self.assertEqual(len(kept), resident.LEDGER_DAYS)

    def test_the_day_is_the_local_one(self):
        """A budget whose day turns at midnight UTC gives half the world
        two evenings' worth in one — `curiosity.spent`'s reason."""
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo("Pacific/Auckland")
        except Exception:  # noqa: BLE001 — no tz database in this image
            tz = None
        if tz is None:
            self.skipTest("no timezone database")
        # Two instants two hours apart that straddle a local midnight and
        # sit inside one UTC day — the whole of the failure, reproduced.
        evening = dt.datetime(2026, 9, 19, 11,
                              tzinfo=dt.timezone.utc).timestamp()
        after = dt.datetime(2026, 9, 19, 13,
                            tzinfo=dt.timezone.utc).timestamp()
        in_utc = resident.Ledger(self.path)
        self.assertEqual(in_utc.summary(evening)["day"],
                         in_utc.summary(after)["day"])
        local = resident.Ledger(self.path, tz=tz)
        self.assertNotEqual(local.summary(evening)["day"],
                            local.summary(after)["day"])


# ---------------------------------------------------------------------------
# Conventions
# ---------------------------------------------------------------------------

class TestTheJobsAreTheModelPlans(unittest.TestCase):
    def test_every_job_this_module_names_is_in_the_table(self):
        """A job the table does not know falls through to its `sonnet`
        default, which would spend the middle tier on a look."""
        for job in resident.JOBS:
            self.assertIn(job, model_plan.JOBS, job)

    def test_the_tiers_are_read_off_the_plan_and_not_restated(self):
        self.assertEqual(resident.tier_for(resident.JOB_FIRST_LOOK), "haiku")
        self.assertEqual(resident.tier_for(resident.JOB_INVESTIGATE), "sonnet")
        self.assertEqual(resident.tier_for(resident.JOB_APPLY), "opus")

    def test_no_model_identifier_is_written_down_anywhere(self):
        """Tiers are named through `model_plan` and nothing else. A dated
        model id in a prompt or a comment is the release where a table
        somebody can read stops being the answer."""
        for name in ("resident.py", "cases.py"):
            text = (PANEL_DIR / name).read_text(encoding="utf-8")
            self.assertNotIn("claude-", text, name)
            self.assertNotIn("--model", text, name)

    def test_nothing_here_spawns_a_model(self):
        """The server does the spawning. A module that reached for
        `engine` could not be driven without a CLI, a credential and a
        house, which is every guard above untested."""
        text = (PANEL_DIR / "resident.py").read_text(encoding="utf-8")
        self.assertNotIn("import engine", text)
        self.assertNotIn("run_analyst", text)
        self.assertNotIn("import server", text)


if __name__ == "__main__":
    unittest.main()
