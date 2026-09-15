"""Why did you do that — the selection, the budget, and the three answers.

The feature's whole risk is volume. A house produces tens of manual
actions a day and each question costs a real Claude run, so *most of
`curiosity.py` is the decision not to ask* — and that decision has to be
arithmetic, taken before anything is spawned, or the thing meant to stop
a million conversations is itself a model call per event.

So every floor here is asserted against the case it must NOT fire on
before it is asserted against the one it must find, the discipline
`tests/test_routines.py` and `tests/test_house_checks.py` apply for the
same reason: a feature that asks about a house with nothing puzzling in
it is one somebody turns off in the first week.

The two that took driving rather than reading are the settling and the
retry. A question asked once about a subject must never be asked again —
which is easy — *and* a run that could not tell must be askable again
once there is more to look at, which is the "a guard that refuses has to
change the next attempt" rule, and the two pull in opposite directions.
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "brain", "panel"))

import curiosity  # noqa: E402
import manual_ledger  # noqa: E402

UTC = dt.timezone.utc
# A Monday, so a "weekday" fixture can be written by counting forward.
MONDAY = dt.datetime(2026, 3, 2, 0, 0, tzinfo=UTC)


def when(day: int, hour: int, minute: int = 0) -> float:
    return (MONDAY + dt.timedelta(days=day, hours=hour,
                                  minutes=minute)).timestamp()


def action(day: int, hour: int, minute: int = 0, *,
           entity_id: str = "switch.sprinklers", state: str = "on",
           cause: str = "person", name: str = "Lawn sprinklers") -> dict:
    return {"ts": int(when(day, hour, minute)), "entity_id": entity_id,
            "state": state, "name": name, "cause": cause}


def evenings(n: int, hour: int = 19, minute: int = 4, jitter=None,
             **kw) -> list[dict]:
    """`n` consecutive daily presses at about the same time."""
    jitter = list(jitter or [0])
    return [action(d, hour, minute + jitter[d % len(jitter)], **kw)
            for d in range(n)]


class LedgerCase(unittest.TestCase):
    """A real store on disk, because both modules key on one."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.ledger = os.path.join(self.tmp.name, "manual.json")
        self.store = os.path.join(self.tmp.name, "curiosity.json")
        # `now` is the evening after the last fixture press, so
        # RECENT_DAYS and the off-pattern window both hold.
        self.now = when(14, 21)

    def record(self, actions):
        manual_ledger.record(actions, self.now, self.ledger)
        return manual_ledger.load(self.ledger)

    def candidates(self, actions):
        return manual_ledger.candidates(self.record(actions), UTC, self.now)


# ---------------------------------------------------------------------------
# The ledger: what is kept, and what is refused
# ---------------------------------------------------------------------------

class TestWhatIsKept(LedgerCase):

    def test_a_person_pressing_something_is_kept(self):
        payload = self.record([action(0, 19)])
        self.assertEqual(len(payload["rows"]), 1)
        self.assertEqual(payload["rows"][0]["cause"], "person")

    def test_a_voice_command_is_kept(self):
        """`routines.py` is right to exclude voice — a time trigger built
        on a sentence is a trigger built on the wrong thing — and this is
        the opposite case: somebody who said what they wanted in words is
        the most informative manual action a house records."""
        payload = self.record([action(0, 19, cause="voice")])
        self.assertEqual(len(payload["rows"]), 1)

    def test_an_unattributed_change_is_not_kept(self):
        """A wall switch and a device's own integration reach Core
        identically. A question about a press nobody can prove happened is
        a question brAIn invented."""
        self.assertEqual(self.record([action(0, 19, cause="unattributed")])
                         ["rows"], [])

    def test_an_automation_is_a_timestamp_and_not_a_row(self):
        payload = self.record([action(0, 19, cause="automation")])
        self.assertEqual(payload["rows"], [])
        self.assertIn("switch.sprinklers|on", payload["automated"])

    def test_a_locks_domain_is_refused_outright(self):
        """Some questions a house should not ask. A refusal rather than a
        ranking, because a ranking is a thing that gets tuned."""
        for domain in manual_ledger.EXCLUDED:
            with self.subTest(domain=domain):
                self.assertEqual(
                    self.record([action(0, 2, entity_id=f"{domain}.front")])
                    ["rows"], [],
                    f"{domain} reached the ledger")

    def test_an_unavailable_state_is_not_a_decision(self):
        self.assertEqual(self.record([action(0, 19, state="unavailable")])
                         ["rows"], [])

    def test_the_same_press_from_two_overlapping_passes_lands_once(self):
        """Passes run every six hours over a day-long window, so the same
        press arrives four or five times."""
        rows = evenings(3)
        manual_ledger.record(rows, self.now, self.ledger)
        manual_ledger.record(rows, self.now, self.ledger)
        self.assertEqual(len(manual_ledger.load(self.ledger)["rows"]), 3)

    def test_rows_older_than_the_window_are_dropped(self):
        old = action(0, 19)
        old["ts"] = int(self.now - (manual_ledger.KEEP_DAYS + 5) * 86400)
        self.assertEqual(self.record([old])["rows"], [])


# ---------------------------------------------------------------------------
# The shape: would this fire on a house with nothing puzzling in it
# ---------------------------------------------------------------------------

class TestTheShapeIsEarned(LedgerCase):

    def test_the_sprinkler_case(self):
        """The one the request named: somebody runs this at about the same
        time most days, and nothing anywhere says why."""
        found = self.candidates(evenings(12))
        self.assertTrue(found)
        top = found[0]
        self.assertEqual(top["kind"], "recurring")
        self.assertEqual(top["entity_id"], "switch.sprinklers")
        self.assertEqual(top["at"], "19:04")
        self.assertGreaterEqual(top["days"], manual_ledger.MIN_DAYS)

    def test_one_press_is_not_a_shape(self):
        self.assertEqual(self.candidates([action(0, 19)]), [])

    def test_too_few_days_is_not_a_shape(self):
        self.assertEqual(
            self.candidates(evenings(manual_ledger.MIN_DAYS - 1)), [])

    def test_scattered_times_are_not_a_time(self):
        """A house that does this anywhere between breakfast and midnight
        has no time for it, and a median of that is a confident answer
        over data that holds none."""
        rows = [action(d, 6 + (d * 5) % 18) for d in range(12)]
        self.assertEqual(self.candidates(rows), [])

    def test_a_shape_that_stopped_is_not_asked_about(self):
        """Somebody who stopped in the spring goes on having a beautiful
        spring in a sixty-day ledger."""
        rows = evenings(12)
        for row in rows:
            row["ts"] -= int((manual_ledger.RECENT_DAYS + 5) * 86400)
        self.assertEqual(self.candidates(rows), [])

    def test_something_an_automation_already_does_is_not_a_mystery(self):
        """A person doing what a rule already does is a disagreement, and
        `auto.overridden` is the finding that reports it."""
        rows = evenings(12) + [action(13, 19, cause="automation")]
        self.assertEqual(self.candidates(rows), [])

    def test_turning_it_on_and_off_are_two_questions(self):
        """Two reasons, two answers. A key that collapsed them would ask a
        model about a set of events with no single reason behind it."""
        rows = evenings(12) + evenings(12, hour=21, state="off")
        subjects = {c["subject"] for c in self.candidates(rows)}
        self.assertEqual(subjects, {"switch.sprinklers|on",
                                    "switch.sprinklers|off"})

    def test_the_order_is_total(self):
        """An arbitrary pick among ties would ask about a different subject
        on every pass and settle none of them."""
        rows = (evenings(12, entity_id="light.hall", name="Hall")
                + evenings(12, entity_id="switch.pump", name="Pump")
                + evenings(12, entity_id="script.water", name="Water",
                           minute=6))
        first = [c["subject"] for c in self.candidates(rows)]
        second = [c["subject"] for c in manual_ledger.candidates(
            manual_ledger.load(self.ledger), UTC, self.now)]
        self.assertEqual(first, second)
        # And a script outranks a lamp, because with one question to spend
        # the lamp is the least likely to carry a reason worth keeping.
        self.assertLess(first.index("script.water|on"),
                        first.index("light.hall|on"))


class TestTheOddPress(LedgerCase):

    def test_a_press_well_outside_its_own_shape_is_news(self):
        rows = evenings(12) + [action(14, 2, 30)]
        found = [c for c in self.candidates(rows)
                 if c["kind"] == "off_pattern"]
        self.assertTrue(found)
        self.assertEqual(found[0]["usually_at"], "19:04")
        self.assertGreater(found[0]["away_min"],
                           manual_ledger.OFF_PATTERN_FLOOR_MIN)

    def test_a_press_at_the_usual_time_is_not(self):
        rows = evenings(12) + [action(14, 19, 6)]
        self.assertEqual([c for c in self.candidates(rows)
                          if c["kind"] == "off_pattern"], [])

    def test_a_first_ever_press_is_not_the_oddest_thing_in_the_house(self):
        """Asked only of a subject that ALREADY has a shape, or every new
        device installed is the strangest event on record."""
        self.assertEqual([c for c in self.candidates([action(14, 3)])
                          if c["kind"] == "off_pattern"], [])

    def test_a_subject_with_too_little_shape_says_nothing(self):
        rows = evenings(manual_ledger.OFF_PATTERN_MIN_DAYS - 1) \
            + [action(14, 3)]
        self.assertEqual([c for c in self.candidates(rows)
                          if c["kind"] == "off_pattern"], [])

    def test_the_distance_is_measured_the_short_way_round(self):
        """A press at 00:10 against a usual 23:50 is twenty minutes away,
        not twenty-three hours and forty — which would make every late
        evening the oddest press ever recorded."""
        rows = evenings(12, hour=23, minute=50) + [action(14, 0, 10)]
        self.assertEqual([c for c in self.candidates(rows)
                          if c["kind"] == "off_pattern"], [])

    def test_an_old_odd_press_is_not_news(self):
        rows = evenings(12) + [action(2, 3)]
        self.assertEqual([c for c in self.candidates(rows)
                          if c["kind"] == "off_pattern"], [])

    def test_the_odd_press_is_not_in_its_own_baseline(self):
        """A press included in the shape it is judged against drags the
        centre toward itself, which is how the oddest thing in the house
        comes out ordinary."""
        rows = evenings(12) + [action(14, 2, 30)]
        payload = self.record(rows)
        odd = manual_ledger.off_pattern(payload, UTC, self.now)[0]
        self.assertEqual(odd["usually_at"], "19:04")


# ---------------------------------------------------------------------------
# The decision: the part that costs money if it is wrong
# ---------------------------------------------------------------------------

class TestTheBudget(LedgerCase):

    def setUp(self):
        super().setUp()
        self.found = self.candidates(
            evenings(12, entity_id="switch.pump", name="Pump")
            + evenings(12, entity_id="script.water", name="Water", minute=7)
            + evenings(12, entity_id="fan.study", name="Study fan", minute=9))
        self.assertGreaterEqual(len(self.found), 3)

    def ask(self, candidate):
        curiosity.mark_asked(candidate, self.now, self.store)

    def ready(self, now=None):
        return curiosity.ready(self.found,
                               curiosity.load(self.store),
                               now or self.now, UTC, self.store)

    def test_a_pass_asks_at_most_once(self):
        """The checks pass runs every few hours; without this the daily cap
        is a burst rather than a budget."""
        self.assertEqual(len(self.ready()), curiosity.MAX_PER_PASS)

    def test_nothing_to_ask_about_costs_nothing(self):
        self.assertEqual(
            curiosity.ready([], curiosity.load(self.store), self.now, UTC,
                            self.store), [])

    def test_the_daily_cap_holds(self):
        for _ in range(curiosity.MAX_PER_DAY):
            self.ask(self.ready()[0])
        self.assertEqual(self.ready(), [])
        self.assertIn("today",
                      curiosity.budget_reason(curiosity.load(self.store),
                                              self.now, UTC))

    def test_the_day_is_the_LOCAL_day(self):
        """A budget of one a day whose day turns at midnight UTC gives two
        questions in one evening to half the world.

        Asked at 21:00 UTC and counted at 02:00 UTC the next morning. In
        UTC those are two days, so the budget has freed up; in Tokyo they
        are 06:00 and 11:00 of one morning, so it has not.
        """
        tokyo = dt.timezone(dt.timedelta(hours=9))
        curiosity.mark_asked(self.found[0], when(14, 21), self.store)
        store = curiosity.load(self.store)
        later = when(15, 2)
        self.assertEqual(curiosity.spent(store, later, UTC)["day"], 0)
        self.assertEqual(curiosity.spent(store, later, tokyo)["day"], 1)

    def test_the_weekly_cap_holds_over_several_days(self):
        # Spent on previous days, so it is the week's limit being reported
        # and not today's — which fires first, and rightly.
        for day in range(1, curiosity.MAX_PER_WEEK + 1):
            curiosity.mark_asked(self.found[day - 1],
                                 self.now - day * 86400, self.store)
        store = curiosity.load(self.store)
        self.assertEqual(curiosity.spent(store, self.now, UTC)["week_left"], 0)
        self.assertIn("this week", curiosity.budget_reason(store, self.now,
                                                            UTC))

    def test_the_budget_frees_up_again(self):
        """A cap, not a switch."""
        self.ask(self.ready()[0])
        self.assertEqual(self.ready(), [])
        self.assertTrue(self.ready(self.now + 2 * 86400))

    def test_a_held_candidate_says_it_is_held_and_not_skipped(self):
        """*"Not now"* and *"never again"* are different silences, and both
        are read by somebody wondering why nothing is happening."""
        self.ask(self.ready()[0])
        ranked = curiosity.worth_asking(self.found,
                                        curiosity.load(self.store),
                                        self.now, UTC, self.store)
        holds = [r for r in ranked if r.get("hold")]
        self.assertTrue(holds)
        self.assertFalse(any(r.get("why") for r in ranked))

    def test_the_askable_ones_sort_first(self):
        """The front of the list is what will happen; the tail is why
        nothing else will."""
        self.ask(self.found[1])
        ranked = curiosity.worth_asking(self.found,
                                        curiosity.load(self.store),
                                        self.now + 2 * 86400, UTC, self.store)
        self.assertTrue(ranked[0].get("why"))
        self.assertTrue(ranked[-1].get("skip"))


class TestAskedOnce(LedgerCase):

    def setUp(self):
        super().setUp()
        self.found = self.candidates(evenings(12))
        self.subject = self.found[0]["subject"]

    def settle(self, status, events=None, answer=None):
        candidate = dict(self.found[0])
        if events is not None:
            candidate["events"] = events
        curiosity.mark_asked(candidate, self.now, self.store)
        if status != "asked":
            curiosity.record_answer(self.subject, answer, "", "", self.now,
                                    self.store)

    def may(self, events=None):
        candidate = dict(self.found[0])
        if events is not None:
            candidate["events"] = events
        return curiosity.may_ask(curiosity.load(self.store), candidate)[0]

    def test_a_new_subject_may_be_asked(self):
        self.assertTrue(self.may())

    def test_an_explained_subject_is_never_asked_again(self):
        self.settle("explained", answer={
            "confidence": "explained", "because": "b",
            "fact": "the lawn is in sun until six", "ask": "",
            "evidence": []})
        self.assertFalse(self.may())
        self.assertFalse(self.may(events=9999))

    def test_a_guessed_subject_is_never_asked_again(self):
        """The question is on the Findings tab; asking a model again would
        buy a second wording of a question already waiting on somebody."""
        self.settle("guessed", answer={
            "confidence": "guess", "because": "b", "fact": "",
            "ask": "is it the sun?", "evidence": []})
        self.assertFalse(self.may())

    def test_a_crashed_run_still_settles_the_subject(self):
        """Written BEFORE the run, so a crash that spent the money cannot
        leave the identical question to be asked every six hours."""
        curiosity.mark_asked(self.found[0], self.now, self.store)
        self.assertFalse(self.may())

    def test_an_unknown_reopens_on_MORE_EVIDENCE(self):
        """A guard that refuses has to change the next attempt. What
        changes is the evidence, never the clock."""
        events = self.found[0]["events"]
        self.settle("unknown", events=events, answer={
            "confidence": "unknown", "because": "nothing explains it",
            "fact": "", "ask": "", "evidence": []})
        self.assertFalse(self.may(events=events))
        self.assertFalse(
            self.may(events=events + curiosity.RETRY_EVENTS - 1))
        self.assertTrue(self.may(events=events + curiosity.RETRY_EVENTS))

    def test_a_retry_is_never_bought_by_the_clock_alone(self):
        """Asking again over the same rows buys the same answer, on
        somebody else's money."""
        events = self.found[0]["events"]
        self.settle("unknown", events=events, answer={
            "confidence": "unknown", "because": "b", "fact": "", "ask": "",
            "evidence": []})
        store = curiosity.load(self.store)
        candidate = dict(self.found[0], events=events)
        self.assertFalse(curiosity.may_ask(store, candidate)[0])
        # A year later, with nothing new to look at.
        self.assertFalse(curiosity.may_ask(store, candidate)[0])

    def test_the_skip_says_which_silence_it_is(self):
        self.settle("unknown", answer={
            "confidence": "unknown", "because": "b", "fact": "", "ask": "",
            "evidence": []})
        _ok, reason = curiosity.may_ask(curiosity.load(self.store),
                                        self.found[0])
        self.assertIn("unknown", reason)
        self.assertIn(str(curiosity.RETRY_EVENTS), reason)

    def test_the_index_is_capped_oldest_first(self):
        """A subject dropped can be asked again, which is the right way
        round; dropping the newest would forget what was just asked."""
        payload = {"asked": {
            f"switch.s{i}|on": {"subject": f"switch.s{i}|on",
                                "asked_at": i, "status": "explained"}
            for i in range(curiosity.MAX_ASKED + 20)}}
        curiosity.save(payload, self.store)
        kept = curiosity.load(self.store)["asked"]
        self.assertEqual(len(kept), curiosity.MAX_ASKED)
        self.assertIn(f"switch.s{curiosity.MAX_ASKED + 19}|on", kept)
        self.assertNotIn("switch.s0|on", kept)


# ---------------------------------------------------------------------------
# What comes back
# ---------------------------------------------------------------------------

class TestTheAnswer(unittest.TestCase):

    def test_an_explanation_with_a_fact(self):
        answer = curiosity.parse({
            "confidence": "explained",
            "because": "the garden is in full sun until about six",
            "fact": "the lawn sprinklers are run by hand on summer evenings",
            "ask": "", "evidence": ["sun elevation at 19:00"]})
        self.assertEqual(answer["confidence"], "explained")
        self.assertEqual(answer["evidence"], ["sun elevation at 19:00"])

    def test_a_guess_with_a_question(self):
        answer = curiosity.parse({
            "confidence": "guess", "because": "probably the sun",
            "fact": "", "ask": "Is it because of the afternoon sun?",
            "evidence": []})
        self.assertEqual(answer["confidence"], "guess")

    def test_an_explanation_with_no_fact_is_demoted(self):
        """It would file nothing anywhere, so calling it explained settles
        the subject for ever having learned nothing — the one outcome
        worse than not asking."""
        answer = curiosity.parse({
            "confidence": "explained", "because": "it is clear enough",
            "fact": "", "ask": "", "evidence": []})
        self.assertEqual(answer["confidence"], "unknown")
        self.assertIn("durable fact", answer["downgraded"])

    def test_a_guess_with_no_question_is_demoted(self):
        answer = curiosity.parse({
            "confidence": "guess", "because": "maybe the sun", "fact": "",
            "ask": "", "evidence": []})
        self.assertEqual(answer["confidence"], "unknown")

    def test_an_unknown_files_nothing(self):
        answer = curiosity.parse({
            "confidence": "unknown", "because": "nothing accounts for it",
            "fact": "", "ask": "", "evidence": []})
        self.assertEqual(answer["confidence"], "unknown")
        self.assertEqual(curiosity.status_for(answer), "unknown")

    def test_a_malformed_reply_is_refused_and_not_passed_through(self):
        """The one thing this must never do is let a malformed answer
        through as an explanation: that writes a sentence into a home's
        memory that nothing will ever question again."""
        for reply in (None, {}, "explained", [],
                      {"confidence": "explained"},
                      {"confidence": "very sure", "because": "b"},
                      {"because": "b", "fact": "f"},
                      {"confidence": "explained", "because": "   ",
                       "fact": "f"}):
            with self.subTest(reply=reply):
                self.assertIsNone(curiosity.parse(reply))

    def test_every_field_is_bounded(self):
        answer = curiosity.parse({
            "confidence": "explained", "because": "b" * 9000,
            "fact": "f" * 9000, "ask": "a" * 9000,
            "evidence": ["e" * 9000] * 50})
        self.assertLessEqual(len(answer["because"]), curiosity.MAX_BECAUSE)
        self.assertLessEqual(len(answer["fact"]), curiosity.MAX_FACT)
        self.assertLessEqual(len(answer["evidence"]),
                             curiosity.MAX_EVIDENCE)
        self.assertLessEqual(len(answer["evidence"][0]),
                             curiosity.MAX_EVIDENCE_CHARS)

    def test_a_failed_run_is_a_status_and_not_a_crash(self):
        self.assertEqual(curiosity.status_for(None), "failed")


class TestThePrompt(LedgerCase):

    def setUp(self):
        super().setUp()
        self.found = self.candidates(evenings(12))

    def test_it_says_what_was_done_and_the_shape_of_it(self):
        text = curiosity.frame(self.found[0])
        self.assertIn("switch.sprinklers", text)
        self.assertIn("19:04", text)
        self.assertIn("Lawn sprinklers", text)

    def test_the_odd_press_asks_a_different_question(self):
        """*Why does this happen at all* and *what was different about this
        one* are two questions, and asking the first about an odd press
        wastes the run."""
        rows = evenings(12) + [action(14, 2, 30)]
        odd = [c for c in self.candidates(rows)
               if c["kind"] == "off_pattern"][0]
        text = curiosity.frame(odd)
        self.assertIn("what was different", text)
        self.assertIn("19:04", text)

    def test_the_memory_is_handed_in_and_told_not_to_be_repeated(self):
        """Without it a run rediscovers what the document already says and
        spends a question asking somebody to confirm what they told brAIn
        once."""
        text = curiosity.frame(self.found[0],
                               memory="The sprinklers water the front lawn.")
        self.assertIn("front lawn", text)
        self.assertIn("do not repeat", text.lower())

    def test_the_contract_and_the_refusal_are_in_the_system_prompt(self):
        for needle in ('"confidence"', '"fact"', '"ask"', "explained",
                       "guess", "unknown", "NEVER invent"):
            self.assertIn(needle, curiosity.SYSTEM)

    def test_it_is_told_not_to_reason_about_people(self):
        """The other half of `manual_ledger.EXCLUDED`'s judgement. A domain
        refusal cannot stop a run reasoning its way to "somebody was
        unwell", and that is not a sentence this should compose."""
        low = curiosity.SYSTEM.lower()
        for needle in ("health", "whereabouts", "sleep", "household"):
            self.assertIn(needle, low)
        self.assertIn("no exception to it", low)

    def test_the_reason_it_was_asked_is_stated(self):
        """A question brAIn asked for a reason it cannot state is one
        nobody can judge — and the same sentence is rendered on the
        diagnostics screen, so the two cannot disagree."""
        why = curiosity.describe(self.found[0])
        self.assertIn("19:04", why)
        self.assertIn("Lawn sprinklers", why)


class TestTheRecord(LedgerCase):

    def setUp(self):
        super().setUp()
        self.found = self.candidates(evenings(12))
        self.subject = self.found[0]["subject"]

    def test_what_was_filed_is_recorded_beside_what_was_said(self):
        """A fact that was composed and a fact that reached the inbox are
        different claims, and the second is what made the run worth its
        money."""
        curiosity.mark_asked(self.found[0], self.now, self.store)
        curiosity.record_answer(self.subject, curiosity.parse({
            "confidence": "explained", "because": "sun",
            "fact": "the lawn is in sun until six", "ask": "",
            "evidence": []}), "memory", "", self.now, self.store)
        entry = curiosity.load(self.store)["asked"][self.subject]
        self.assertEqual(entry["status"], "explained")
        self.assertEqual(entry["filed"], "memory")
        self.assertEqual(curiosity.counts(curiosity.load(self.store))
                         ["explained"], 1)

    def test_the_log_says_what_brain_worked_out(self):
        """A settled entry says a subject is done; this says what was
        learned and when, which is what the screen renders."""
        curiosity.mark_asked(self.found[0], self.now, self.store)
        curiosity.record_answer(self.subject, curiosity.parse({
            "confidence": "guess", "because": "probably the sun",
            "fact": "", "ask": "is it?", "evidence": []}),
            "hypothesis", "", self.now, self.store)
        rows = curiosity.recent(curiosity.load(self.store))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["filed"], "hypothesis")
        self.assertIn("sun", rows[0]["because"])

    def test_an_answer_for_a_subject_nobody_asked_about_is_refused(self):
        self.assertIsNone(curiosity.record_answer(
            "switch.nothing|on", None, "", "", self.now, self.store))

    def test_an_unreadable_store_reads_as_nothing_asked(self):
        with open(self.store, "w") as fh:
            fh.write("{ this is not json")
        payload = curiosity.load(self.store)
        self.assertEqual(payload["asked"], {})
        self.assertEqual(curiosity.budget_reason(payload, self.now, UTC), "")

    def test_a_repeat_asking_is_counted(self):
        """A subject that keeps coming back unexplained is worth being able
        to count."""
        curiosity.mark_asked(self.found[0], self.now, self.store)
        curiosity.mark_asked(self.found[0], self.now + 86400, self.store)
        self.assertEqual(
            curiosity.load(self.store)["asked"][self.subject]["asks"], 2)


class TestTheSilenceSaysWhy(LedgerCase):
    """A floor's cost is silence, and silence is indistinguishable from
    broken — `house.py`'s rule, and it bites hardest on a feature that
    asks one question a day and is therefore quiet nearly all the time."""

    def test_a_fresh_install_says_what_it_is_waiting_for(self):
        progress = manual_ledger.progress({"rows": []}, self.now)
        self.assertEqual(progress["state"], "collecting")
        self.assertEqual(progress["have"], 0)
        self.assertTrue(progress["note"])

    def test_a_partly_watched_house_says_how_far_along_it_is(self):
        payload = self.record(evenings(2))
        progress = manual_ledger.progress(payload, self.now)
        self.assertEqual(progress["state"], "collecting")
        self.assertIsNotNone(progress["ready_at"])

    def test_a_watched_house_is_ready(self):
        payload = self.record(evenings(12))
        self.assertEqual(manual_ledger.progress(payload, self.now)["state"],
                         "ready")


if __name__ == "__main__":
    unittest.main()
