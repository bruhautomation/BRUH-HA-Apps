"""A signal orders a batch and decides nothing, and these are the lines
that keep it that way.

The Resident's whole argument is that rules stop judging. That is a claim
about a module nobody can look at from outside, so it has to be a claim a
test makes: the salience arithmetic is pinned by ORDER rather than by the
numbers it happens to produce (a weight somebody retunes must not fail a
test, and a leak sliding under a battery must), and `hot` — the one thing
a signal can cause on its own — is asserted as a CLOSED set, case by case,
including the cases that must not be in it.

The near-miss worth naming: a `critical` finding is not hot. Severity is
how bad a thing is and hot is how soon somebody has to think about it, and
a battery three weeks from flat is `critical` because a rule said so. If
severity could make a signal hot, the first look would run on the timer
brAIn already has, plus every check row, which is the architecture this
replaces wearing a new word.
"""
from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import signals  # noqa: E402

UTC = dt.timezone.utc


def at(hour: int, minute: int = 0) -> float:
    """An epoch at a known UTC hour, so the night window is testable."""
    return dt.datetime(2026, 9, 15, hour, minute, tzinfo=UTC).timestamp()


NOON = at(12)
THREE_AM = at(3)


def state_change(entity_id: str, to: str, *, was: str = "off",
                 **attrs) -> dict:
    """One `state_changed` event's data, in Core's own shape."""
    return {
        "entity_id": entity_id,
        "old_state": {"entity_id": entity_id, "state": was, "attributes": {}},
        "new_state": {"entity_id": entity_id, "state": to,
                      "attributes": dict(attrs)},
        "context": {"id": "01ABC", "user_id": None, "parent_id": None},
    }


# ---------------------------------------------------------------------------
# The shape
# ---------------------------------------------------------------------------

class TestOneShapeAndNoOther(unittest.TestCase):

    def test_a_signal_has_exactly_the_documented_keys(self):
        sig = signals.make("state", "light.hall", now=NOON)
        self.assertEqual(sorted(sig), sorted(signals.SIGNAL_KEYS))

    def test_repeats_is_always_there_and_always_at_least_one(self):
        """A reader that branches on a key being present is a second
        answer to "how many times"."""
        sig = signals.make("state", "light.hall", now=NOON)
        self.assertEqual(sig["repeats"], 1)
        self.assertEqual(signals.make("state", "x", now=NOON,
                                      repeats=0)["repeats"], 1)

    def test_a_kind_nobody_wrote_a_weight_for_is_refused(self):
        with self.assertRaises(ValueError):
            signals.make("hunch", "light.hall", now=NOON)

    def test_evidence_and_text_are_capped(self):
        sig = signals.make(
            "state", "x" * 500, now=NOON, text="y" * 500,
            evidence=[signals.evidence_row("e" * 400, "v" * 400, NOON)
                      for _ in range(50)])
        self.assertLessEqual(len(sig["subject"]), signals.MAX_SUBJECT)
        self.assertLessEqual(len(sig["text"]), signals.MAX_TEXT)
        self.assertLessEqual(len(sig["evidence"]), signals.MAX_EVIDENCE)
        self.assertLessEqual(len(sig["evidence"][0]["value"]), 80)

    def test_a_float_renders_short_rather_than_as_a_binary_artefact(self):
        row = signals.evidence_row("sensor.t", 21.3 * 3, NOON)
        self.assertEqual(row["value"], "63.9")

    def test_salience_is_clamped_to_the_range_it_claims(self):
        huge = signals.score("reply", severity="critical", urgency="now",
                             protected=True, safety=True, known=True,
                             odd_hour=True, age_s=0.0, repeats=99)
        self.assertLessEqual(huge, 1.0)
        self.assertGreaterEqual(signals.score("time"), 0.0)


# ---------------------------------------------------------------------------
# Every adapter, on something a house really produces
# ---------------------------------------------------------------------------

class TestTheAdapters(unittest.TestCase):

    def test_a_check_row_becomes_a_check_signal_named_by_its_catalog(self):
        sig = signals.from_finding({
            "text": "Kitchen temperature has not moved in 9 days",
            "detail": "last change 3 Sep",
            "severity": "warning", "entity_id": "sensor.kitchen_temp",
            "source": "check:dev.frozen",
            "source_title": "Device check", "ts": NOON - 600}, NOON)
        self.assertEqual(sig["kind"], "check")
        self.assertEqual(sig["subject"], "sensor.kitchen_temp")
        self.assertEqual(sig["source"], "check:dev.frozen")
        # The check's own title, not its group's — `Device check` three
        # times over is three things nobody can tell apart.
        self.assertIn("Sensors frozen on one value", sig["text"])
        self.assertEqual(sig["evidence"][0]["entity"], "sensor.kitchen_temp")

    def test_a_row_with_no_text_is_not_a_signal(self):
        self.assertIsNone(signals.from_finding({"severity": "critical"}, NOON))
        self.assertIsNone(signals.from_finding(None, NOON))

    def test_a_producer_that_is_not_a_check_keeps_its_own_title(self):
        sig = signals.from_finding({
            "text": "The hall light fights the motion rule",
            "severity": "serious", "entity_id": "light.hall",
            "source": "analyst", "source_title": "Automations"}, NOON)
        self.assertTrue(sig["text"].startswith("Automations:"))

    def test_urgency_comes_from_the_producer_table_not_the_words(self):
        """`notify_router.urgency_of` is keyed on `source` for a reason,
        and reading it here rather than restating it is what stops the two
        disagreeing about the same producer."""
        soon = signals.from_finding({"text": "Leak under the sink",
                                     "severity": "warning",
                                     "source": "check:dev.unavailable"}, NOON)
        later = signals.from_finding({"text": "Leak under the sink",
                                      "severity": "warning",
                                      "source": "check:reg.no_area"}, NOON)
        self.assertGreater(soon["salience"], later["salience"])

    def test_a_state_change_on_something_that_matters(self):
        ctx = signals.RegistryContext(known={"light.hall"})
        sig = signals.from_state_change(
            state_change("light.hall", "on", friendly_name="Hall"),
            ctx, NOON)
        self.assertEqual(sig["kind"], "state")
        self.assertEqual(sig["subject"], "light.hall")
        self.assertIn("Hall", sig["text"])

    def test_most_state_changes_are_not_signals_at_all(self):
        """The filter IS the feature: a house publishes tens of thousands
        of readings a day and a listener that made a row of each would
        hand the first look a batch of sensors reporting numbers."""
        ctx = signals.RegistryContext(known={"light.hall"})
        self.assertIsNone(signals.from_state_change(
            state_change("sensor.power", "412", was="408"), ctx, NOON))

    def test_a_change_that_changed_nothing_is_not_a_signal(self):
        ctx = signals.RegistryContext(known={"light.hall"})
        self.assertIsNone(signals.from_state_change(
            state_change("light.hall", "on", was="on"), ctx, NOON))

    def test_an_entity_being_removed_is_not_a_state_change(self):
        ctx = signals.RegistryContext(known={"light.hall"})
        self.assertIsNone(signals.from_state_change(
            {"entity_id": "light.hall", "old_state": {"state": "on"},
             "new_state": None}, ctx, NOON))

    def test_a_closure_is_a_closure_by_the_one_rule_that_decides_it(self):
        ctx = signals.RegistryContext()
        sig = signals.from_state_change(
            state_change("binary_sensor.back_door", "on",
                         device_class="door"), ctx, NOON)
        self.assertIsNotNone(sig)
        self.assertEqual(sig["kind"], "state")

    def test_a_trace_error_on_an_automation_of_ours(self):
        sig = signals.from_trace({
            "item_id": "brain_playbook_smoke",
            "timestamp": "2026-09-15T12:00:00+00:00",
            "error": "Service notify.mobile_app_x not found"}, NOON)
        self.assertEqual(sig["kind"], "trace_error")
        self.assertEqual(sig["subject"], "brain_playbook_smoke")
        self.assertIn("not found", sig["text"])

    def test_a_trace_that_did_not_error_is_not_a_signal(self):
        self.assertIsNone(signals.from_trace(
            {"item_id": "brain_x", "timestamp": "2026-09-15T12:00:00Z"}, NOON))

    def test_a_trace_stamp_that_will_not_parse_reads_as_now(self):
        """Zero would make a fresh trace look weeks old, which is the
        recency weight reading a parse failure as a fact about the house."""
        sig = signals.from_trace({"item_id": "brain_x", "error": "boom",
                                  "timestamp": "not a date"}, NOON)
        self.assertEqual(sig["evidence"][0]["when"], NOON)

    def test_an_override_keeps_find_overrides_own_shape(self):
        sig = signals.from_override({
            "ts": NOON - 120, "entity_id": "light.porch", "name": "Porch",
            "from_state": "on", "to_state": "off",
            "by": "automation.dusk", "by_name": "Dusk lights",
            "person": "Ben", "after_s": 40.0}, NOON)
        self.assertEqual(sig["kind"], "override")
        self.assertEqual(sig["subject"], "light.porch")
        self.assertIn("Dusk lights", sig["text"])
        self.assertEqual(len(sig["evidence"]), 2)

    def test_presence_reads_person_and_phone_alike(self):
        for eid in ("person.ben", "device_tracker.bens_phone"):
            sig = signals.from_presence(
                state_change(eid, "home", was="not_home"), NOON)
            self.assertEqual(sig["kind"], "presence", eid)

    def test_presence_refuses_anything_that_is_not_a_person(self):
        self.assertIsNone(signals.from_presence(
            state_change("light.hall", "on"), NOON))

    def test_a_reply_is_the_highest_base_weight_in_the_table(self):
        """Somebody is waiting, which is a different claim from anything a
        rule noticed — and it orders first rather than deciding anything."""
        self.assertEqual(max(signals.KIND_BASE, key=signals.KIND_BASE.get),
                         "reply")
        sig = signals.from_reply({"action": "BRAIN_WRONG", "ts": 1700,
                                  "note": "that cupboard is never opened",
                                  "via": "notification"}, NOON)
        self.assertEqual(sig["kind"], "reply")
        self.assertIn("never opened", sig["text"])
        self.assertEqual(sig["source"], "reply:notification")

    def test_an_empty_reply_is_not_a_signal(self):
        self.assertIsNone(signals.from_reply({"via": "notification"}, NOON))

    def test_a_scheduled_moment_always_produces_one(self):
        """The one adapter that cannot return None: a moment happened
        whether or not anything else did, and that is the point of it."""
        sig = signals.from_time("evening", NOON)
        self.assertEqual(sig["kind"], "time")
        self.assertEqual(sig["subject"], "evening")
        self.assertEqual(sig["evidence"], [])

    def test_the_three_measurement_stores_share_one_shape(self):
        base = signals.from_baseline(
            {"entity_id": "sensor.freezer", "value": -12.0,
             "deviation": 6.4, "source": "hour", "ts": NOON - 30}, NOON)
        therm = signals.from_thermal(
            {"entity_id": "climate.lounge", "text": "falling past its k",
             "value": 1.8, "ts": NOON - 30}, NOON)
        app = signals.from_appliance(
            {"entity_id": "sensor.washer_power",
             "text": "cycle finished 20 minutes ago", "ts": NOON - 30}, NOON)
        self.assertEqual([base["kind"], therm["kind"], app["kind"]],
                         ["baseline", "thermal", "appliance"])
        self.assertIn("sensor.freezer.deviation",
                      [e["entity"] for e in base["evidence"]])
        # The weights are the judgement `notify_router` already makes about
        # the same producers: a window open now, a dishwasher whenever.
        self.assertGreater(therm["salience"], app["salience"])

    def test_a_measurement_row_with_nothing_in_it_is_not_a_signal(self):
        self.assertIsNone(signals.from_baseline({}, NOON))
        self.assertIsNone(signals.from_thermal(None, NOON))


# ---------------------------------------------------------------------------
# Salience: pinned by order, never by the number
# ---------------------------------------------------------------------------

class TestWhatOutranksWhat(unittest.TestCase):

    def leak(self, now=NOON):
        return signals.from_state_change(
            state_change("binary_sensor.under_sink", "on",
                         device_class="moisture", friendly_name="Under sink"),
            signals.RegistryContext(), now)

    def battery(self, now=NOON):
        return signals.from_finding({
            "text": "Front door sensor battery at 5%", "severity": "critical",
            "entity_id": "sensor.front_door_battery",
            "source": "check:dev.battery_low", "ts": now}, now)

    def test_a_leak_beats_a_battery(self):
        """The ordering this whole table exists to get right. A battery is
        `critical` because a rule said so and it is three weeks out; a leak
        detector reading wet is now."""
        self.assertGreater(self.leak()["salience"],
                           self.battery()["salience"])

    def test_and_the_leak_is_first_in_the_batch_whatever_it_scored(self):
        got = signals.batch([self.battery(), self.leak()])
        self.assertEqual(got["batch"][0]["subject"], "binary_sensor.under_sink")

    def test_a_protected_entity_beats_an_ordinary_one(self):
        ctx = signals.RegistryContext(protected=["lock.front_door"],
                                      known={"light.hall"})
        lock = signals.from_state_change(
            state_change("lock.front_door", "unlocked", was="locked"),
            ctx, NOON)
        light = signals.from_state_change(
            state_change("light.hall", "on"), ctx, NOON)
        self.assertGreater(lock["salience"], light["salience"])

    def test_the_same_thing_five_times_outranks_the_same_thing_once(self):
        once = signals.score("state", age_s=0.0, repeats=1)
        many = signals.score("state", age_s=0.0, repeats=5)
        self.assertGreater(many, once)

    def test_and_a_count_can_only_ever_move_it_a_little(self):
        """A repeat is evidence, not a verdict — `REPEAT_CAP` is what
        stops a chatty sensor climbing over a leak by sheer volume."""
        chatty = signals.score("state", repeats=500, age_s=0.0)
        self.assertLess(chatty, signals.score("state", severity="critical",
                                              urgency="now", safety=True,
                                              age_s=0.0))

    def test_older_scores_lower_and_never_negative(self):
        fresh = signals.score("check", age_s=0.0)
        old = signals.score("check", age_s=86400.0)
        self.assertGreater(fresh, old)
        self.assertGreaterEqual(old, 0.0)

    def test_rank_is_a_total_order_so_two_passes_agree(self):
        rows = [signals.make("state", f"light.{i}", now=NOON,
                             salience=0.4) for i in range(6)]
        self.assertEqual([s["subject"] for s in signals.rank(rows)],
                         [s["subject"] for s in signals.rank(list(reversed(rows)))])


# ---------------------------------------------------------------------------
# `hot` is a closed set
# ---------------------------------------------------------------------------

class TestTheHotSetIsExactlyTheClosedSet(unittest.TestCase):
    """Four cases in, and the near-misses out. Hot is the one thing a
    signal may cause on its own — the first look runs NOW — so it is
    pinned case by case rather than described."""

    def test_one_a_leak_smoke_co_or_gas_sensor_going_on(self):
        for klass in sorted(signals.HOT_SAFETY_CLASSES):
            sig = signals.from_state_change(
                state_change(f"binary_sensor.{klass}", "on",
                             device_class=klass),
                signals.RegistryContext(), NOON)
            self.assertTrue(sig["hot"], klass)

    def test_but_never_one_going_off_again(self):
        """A leak detector going dry is good news, and good news at 3am is
        a phone nobody thanks you for."""
        sig = signals.from_state_change(
            state_change("binary_sensor.under_sink", "off", was="on",
                         device_class="moisture"),
            signals.RegistryContext(), THREE_AM)
        self.assertFalse(sig["hot"])

    def test_two_a_protected_entity_moving(self):
        ctx = signals.RegistryContext(protected=["lock.front_door"])
        sig = signals.from_state_change(
            state_change("lock.front_door", "unlocked", was="locked"),
            ctx, NOON)
        self.assertTrue(sig["hot"])

    def test_three_a_person_level_event_at_an_odd_hour(self):
        night = signals.from_presence(
            state_change("person.ben", "home", was="not_home"), THREE_AM)
        day = signals.from_presence(
            state_change("person.ben", "home", was="not_home"), NOON)
        self.assertTrue(night["hot"])
        self.assertFalse(day["hot"])

    def test_four_a_trace_error_on_an_automation_brain_wrote(self):
        ours = signals.from_trace({"item_id": "brain_intent_1", "error": "x"},
                                  NOON)
        theirs = signals.from_trace({"item_id": "1699999999999", "error": "x"},
                                    NOON)
        self.assertTrue(ours["hot"])
        self.assertFalse(theirs["hot"])

    def test_a_critical_finding_is_never_hot(self):
        """The near-miss worth naming. If severity could make a signal hot
        the first look would run on every check row, which is the
        architecture this replaces wearing a new word."""
        for severity in ("info", "warning", "serious", "critical"):
            sig = signals.from_finding(
                {"text": "something", "severity": severity,
                 "source": "check:dev.unavailable"}, NOON)
            self.assertFalse(sig["hot"], severity)

    def test_an_ordinary_entity_at_three_in_the_morning_is_not_hot(self):
        ctx = signals.RegistryContext(known={"light.hall"})
        sig = signals.from_state_change(
            state_change("light.hall", "on"), ctx, THREE_AM)
        self.assertFalse(sig["hot"])

    def test_an_appliance_a_baseline_and_a_moment_are_never_hot(self):
        self.assertFalse(signals.from_appliance(
            {"entity_id": "sensor.washer", "text": "done"}, THREE_AM)["hot"])
        self.assertFalse(signals.from_baseline(
            {"entity_id": "sensor.freezer", "deviation": 9}, THREE_AM)["hot"])
        self.assertFalse(signals.from_time("evening", THREE_AM)["hot"])


class TestWhichHoursAreOdd(unittest.TestCase):

    def test_with_no_measurement_the_fallback_night_is_used_and_wraps(self):
        self.assertTrue(signals.is_odd_hour(at(23, 30)))
        self.assertTrue(signals.is_odd_hour(at(2)))
        self.assertFalse(signals.is_odd_hour(at(9)))
        self.assertEqual(signals.night_window(),
                         (signals.NIGHT_START_H, signals.NIGHT_END_H))

    def test_a_measured_rhythm_is_preferred_to_somebody_elses_evening(self):
        # A household that settles at 21:40 and is up at 05:10. 2026-09-15
        # is a Tuesday, so the weekday shape is the one read.
        payload = {"weekday": {"settles": {"minute": 21 * 60 + 40},
                               "wakes": {"minute": 5 * 60 + 10}}}
        self.assertEqual(signals.night_window(
            payload, dt.datetime(2026, 9, 15, 22, tzinfo=UTC)), (21, 5))
        self.assertTrue(signals.is_odd_hour(at(22), payload))
        self.assertFalse(signals.is_odd_hour(at(22)))

    def test_a_payload_with_no_moment_falls_back_rather_than_reading_a_clock(self):
        """A measured night is measured per KIND of day, so reading one
        needs to know which day it is — and taking that off the wall clock
        is the one reach this module does not make."""
        payload = {"weekday": {"settles": {"minute": 21 * 60 + 40},
                               "wakes": {"minute": 5 * 60 + 10}}}
        self.assertEqual(signals.night_window(payload),
                         (signals.NIGHT_START_H, signals.NIGHT_END_H))

    def test_a_half_measured_rhythm_falls_back_rather_than_guessing(self):
        payload = {"weekday": {"settles": {"minute": 1300}}}
        self.assertEqual(signals.night_window(
            payload, dt.datetime(2026, 9, 15, 22, tzinfo=UTC)),
            (signals.NIGHT_START_H, signals.NIGHT_END_H))


# ---------------------------------------------------------------------------
# A batch
# ---------------------------------------------------------------------------

class TestDedupe(unittest.TestCase):

    def burst(self, n: int, *, start: float = NOON, step: float = 10.0):
        return [signals.make("state", "binary_sensor.back_door",
                             now=start + i * step, salience=0.3,
                             text=f"open {i}",
                             evidence=[signals.evidence_row(
                                 "binary_sensor.back_door", f"open {i}",
                                 start + i * step)])
                for i in range(n)]

    def test_the_same_thing_four_times_is_one_signal_with_a_count(self):
        got = signals.dedupe(self.burst(4))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["repeats"], 4)

    def test_and_the_freshest_evidence_is_the_one_kept(self):
        """The newest reading is the one still true; the older ones are
        what make it worth reading."""
        got = signals.dedupe(self.burst(4))
        self.assertEqual(got[0]["text"], "open 3")
        self.assertEqual(got[0]["evidence"][0]["value"], "open 3")
        self.assertEqual(got[0]["seen_at"], NOON + 30.0)

    def test_a_count_lifts_the_score_or_it_says_nothing(self):
        once = signals.dedupe(self.burst(1))[0]
        many = signals.dedupe(self.burst(4))[0]
        self.assertGreater(many["salience"], once["salience"])

    def test_two_bursts_an_hour_apart_are_two_signals(self):
        rows = self.burst(3) + self.burst(3, start=NOON + 3600)
        got = signals.dedupe(rows)
        self.assertEqual([s["repeats"] for s in got], [3, 3])

    def test_different_subjects_never_fold_together(self):
        rows = [signals.make("state", "light.a", now=NOON),
                signals.make("state", "light.b", now=NOON)]
        self.assertEqual(len(signals.dedupe(rows)), 2)

    def test_the_same_subject_under_two_kinds_is_two_signals(self):
        rows = [signals.make("state", "sensor.x", now=NOON),
                signals.make("baseline", "sensor.x", now=NOON)]
        self.assertEqual(len(signals.dedupe(rows)), 2)

    def test_hot_survives_any_member_of_the_run(self):
        """A leak that tripped, cleared and tripped again is still a leak
        that tripped — reading only the newest lets the clear cancel it."""
        rows = self.burst(3)
        rows[0]["hot"] = True
        self.assertTrue(signals.dedupe(rows)[0]["hot"])

    def test_first_appearance_is_the_order_because_rank_is_what_sorts(self):
        rows = [signals.make("state", "light.b", now=NOON),
                signals.make("state", "light.a", now=NOON + 1)]
        self.assertEqual([s["subject"] for s in signals.dedupe(rows)],
                         ["light.b", "light.a"])

    def test_something_that_is_not_a_signal_is_dropped_not_folded(self):
        got = signals.dedupe([{"kind": "hunch", "subject": "x"}, None,
                              signals.make("state", "light.a", now=NOON)])
        self.assertEqual([s["subject"] for s in got], ["light.a"])


class TestBatch(unittest.TestCase):

    def rows(self, n: int):
        return [signals.make("state", f"light.{i}", now=NOON,
                             salience=0.1 + i / 1000.0) for i in range(n)]

    def test_the_cap_is_taken_and_the_surplus_is_reported_not_dropped(self):
        got = signals.batch(self.rows(30), cap=10)
        self.assertEqual(len(got["batch"]), 10)
        self.assertEqual(got["waiting"], 20)

    def test_the_highest_salience_is_what_is_taken(self):
        got = signals.batch(self.rows(30), cap=3)
        self.assertEqual([s["subject"] for s in got["batch"]],
                         ["light.29", "light.28", "light.27"])

    def test_a_hot_signal_is_never_left_waiting(self):
        """Hot is what made the look run now rather than on its timer, so
        a batch that pushed it past the cap would be the cap answering the
        question the look was called to answer."""
        rows = self.rows(40)
        rows[0]["hot"] = True          # the lowest-scoring row there is
        got = signals.batch(rows, cap=5)
        self.assertEqual(got["batch"][0]["subject"], "light.0")
        self.assertEqual(got["hot"], 1)
        self.assertEqual(got["waiting"], 35)

    def test_an_empty_batch_says_so_rather_than_failing(self):
        self.assertEqual(signals.batch([]),
                         {"batch": [], "waiting": 0, "hot": 0})


class TestPromptRows(unittest.TestCase):

    def test_every_row_fits_inside_the_cap(self):
        rows = signals.prompt_rows([signals.make(
            "check", "sensor." + "x" * 200, now=NOON, text="y" * 400,
            evidence=[signals.evidence_row("e" * 100, "v" * 100, NOON)])],
            NOON)
        self.assertEqual(len(rows), 1)
        self.assertLessEqual(len(rows[0]), signals.ROW_CHARS)

    def test_a_row_carries_the_kind_the_subject_and_the_score(self):
        sig = signals.make("check", "sensor.k", now=NOON, salience=0.42,
                           text="frozen for 9 days")
        row = signals.prompt_rows([sig], NOON)[0]
        self.assertIn("[check]", row)
        self.assertIn("sensor.k", row)
        self.assertIn("s=0.42", row)
        self.assertIn("frozen for 9 days", row)

    def test_hot_and_a_repeat_count_are_said_in_the_row(self):
        sig = signals.make("state", "binary_sensor.leak", now=NOON,
                           hot=True, repeats=3, text="wet")
        row = signals.prompt_rows([sig], NOON)[0]
        self.assertIn("HOT", row)
        self.assertIn("x3", row)

    def test_no_row_is_json_and_no_row_carries_a_whole_state(self):
        """The first look is the cheap tier and runs every few minutes; a
        row that pasted an entity's attributes would put the day's budget
        into the one place it buys nothing."""
        sig = signals.from_state_change(
            state_change("lock.front", "unlocked", was="locked",
                         friendly_name="Front door", device_class="lock",
                         code_format="number", changed_by="Ben"),
            signals.RegistryContext(protected=["lock.front"]), NOON)
        row = signals.prompt_rows([sig], NOON)[0]
        self.assertNotIn("{", row)
        self.assertNotIn("code_format", row)

    def test_without_a_now_no_age_is_invented(self):
        """`now` is an argument everywhere in this module, and a renderer
        that reached for the wall clock when it was not given one would be
        the one place a batch could not be replayed."""
        sig = signals.make("check", "sensor.k", now=NOON, text="x")
        self.assertIn(" 0s ", signals.prompt_rows([sig], NOON)[0])
        self.assertNotIn(" 0s ", signals.prompt_rows([sig])[0])

    def test_ages_read_in_the_fewest_characters_that_say_it(self):
        sig = signals.make("check", "sensor.k", now=NOON, text="x")
        for offset, want in ((30, "30s"), (600, "10m"),
                             (7200, "2h"), (3 * 86400, "3d")):
            self.assertIn(want, signals.prompt_rows([sig], NOON + offset)[0])

    def test_a_caller_that_numbers_them_itself_can_ask_for_bare_rows(self):
        """A signal is named back by its POSITION and never by its
        subject, so a prompt builder laying the rows out in its own list
        is doing the right thing — and two numbers on one row is the shape
        where a reply saying "3" means two different signals depending on
        which one it counted."""
        rows = [signals.make("check", f"s.{i}", now=NOON) for i in range(3)]
        bare = signals.prompt_rows(rows, numbered=False)
        self.assertTrue(all(r.startswith("[check]") for r in bare), bare)
        self.assertTrue(signals.prompt_rows(rows)[0].startswith("1. "))

    def test_rows_are_numbered_from_one_so_a_reply_can_name_one(self):
        rows = signals.prompt_rows(
            [signals.make("check", f"s.{i}", now=NOON) for i in range(3)])
        self.assertTrue(rows[0].startswith("1."))
        self.assertTrue(rows[2].startswith("3."))


class TestNothingHereDecidesAnything(unittest.TestCase):
    """The architectural claim, as far as a test can make it."""

    def test_no_signal_carries_a_verdict_a_fix_or_advice(self):
        sig = signals.from_finding({
            "text": "Kitchen sensor frozen", "severity": "critical",
            "fix": "replace the battery and reload the integration",
            "entity_id": "sensor.k", "source": "check:dev.frozen"}, NOON)
        self.assertEqual(sorted(sig), sorted(signals.SIGNAL_KEYS))
        self.assertNotIn("fix", sig)
        self.assertNotIn("replace the battery", sig["text"])

    def test_the_module_reads_no_store_and_asks_no_model(self):
        import ast
        source = (PANEL / "signals.py").read_text(encoding="utf-8")
        names = {n.names[0].name.split(".")[0]
                 for n in ast.walk(ast.parse(source))
                 if isinstance(n, ast.Import)}
        names |= {n.module.split(".")[0]
                  for n in ast.walk(ast.parse(source))
                  if isinstance(n, ast.ImportFrom) and n.module}
        for banned in ("engine", "server", "subprocess", "aiohttp",
                       "findings_store", "atomic_write"):
            self.assertNotIn(banned, names, banned)


if __name__ == "__main__":
    unittest.main()
