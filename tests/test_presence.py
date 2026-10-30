#!/usr/bin/env python3
"""The presence loop: how the assistant grows, and how it keeps in touch.

`presence.py` is the arithmetic and the store; the server half (the bus,
the nightly run, delivery) is driven in `test_presence_server.py`. Every
rule here is one the household was promised in words, so each test is
named after the promise:

* nothing runs unless BOTH Personality and the Learning loop are on;
* a hard budget — one touch per person a day, a few a week, a gap between
  any two in the house, none in quiet hours or outside the day, none to
  somebody away, none in the first minutes after an arrival except the
  arrival greeting itself;
* reactions steer it: a swipe or an ignore costs, "Not now" stops today at
  once, "Less like this" retires that kind for that person, and a run of
  touches nobody wanted pauses that person for a week;
* the nightly answer is read strictly, and anything about a sensitive
  attribute, a judgement of a person, an entity id or the assistant's own
  voice is refused rather than softened;
* growth notes the assistant writes itself are bounded, deduplicated,
  marked as its own, removable — and never touch the persona.

The people are invented (Wren, Ilo) and so is the assistant's name.
"""

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import personality  # noqa: E402
import presence  # noqa: E402

UTC = dt.timezone.utc


def at(day: int, hour: int, minute: int = 0) -> float:
    """An epoch on 2026-10-<day> at a UTC hour (the house is on UTC here)."""
    return dt.datetime(2026, 10, day, hour, minute, tzinfo=UTC).timestamp()


NOW = at(28, 9, 30)          # a Wednesday morning
WREN = "person.wren"
ILO = "person.ilo"
PEOPLE = {WREN: "Wren", ILO: "Ilo"}


def idea(kind="morning", text="Morning, Wren. The bins go out tonight.",
         reason="Wren asked about the bins on Monday."):
    return {"person": WREN, "kind": kind, "text": text, "reason": reason}


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.store = root / "presence.json"
        self.features = root / "features.json"
        self.pers = root / "personality.json"
        self._saved = (presence.STORE, presence.FEATURES_FILE,
                       personality.STORE, personality.FEATURES_FILE)
        presence.STORE = self.store
        presence.FEATURES_FILE = str(self.features)
        personality.STORE = str(self.pers)
        personality.FEATURES_FILE = str(self.features)
        self.addCleanup(self._restore)

    def _restore(self):
        (presence.STORE, presence.FEATURES_FILE,
         personality.STORE, personality.FEATURES_FILE) = self._saved

    def switches(self, **values):
        self.features.write_text(json.dumps(values), encoding="utf-8")

    def state_with(self, *ideas_, now=NOW):
        state = presence.load()
        presence.add_ideas(state, list(ideas_), PEOPLE, now)
        return state


class TestOffUnlessBothSwitchesAreOn(StoreCase):

    def test_both_on_is_on(self):
        self.switches(personality=True, learning_loop=True)
        self.assertEqual(presence.active(), (True, ""))

    def test_personality_off_is_off_and_says_so(self):
        self.switches(personality=False, learning_loop=True)
        on, why = presence.active()
        self.assertFalse(on)
        self.assertIn("Personality", why)

    def test_learning_loop_off_is_off_and_says_so(self):
        self.switches(personality=True, learning_loop=False)
        on, why = presence.active()
        self.assertFalse(on)
        self.assertIn("Learning loop", why)

    def test_a_house_that_never_chose_a_personality_is_off(self):
        # No switches written and no personality set: Features' own
        # default for Personality is off, so this is off too.
        on, _why = presence.active()
        self.assertFalse(on)

    def test_a_house_that_named_its_assistant_and_never_opened_features_is_on(self):
        personality.save("Sable", "Warm and brief.", str(self.pers))
        self.assertEqual(presence.active(), (True, ""))


class TestTheBudget(StoreCase):

    def touch(self, state, person=WREN, kind="morning", when=NOW,
              reaction=""):
        t = presence.record_touch(state, person, PEOPLE[person],
                                  {"kind": kind, "text": "Hello.",
                                   "reason": "Because."}, "phone", when)
        if reaction:
            presence.react(state, t["id"], reaction, when + 60, tz=UTC)
        return t

    def may(self, state, person=WREN, kind="morning", now=NOW, **kw):
        kw.setdefault("tz", UTC)
        kw.setdefault("home", True)
        return presence.may_touch(state, person, kind, now, **kw)

    def test_a_quiet_morning_is_allowed(self):
        self.assertEqual(self.may(presence.load()), "")

    def test_one_touch_per_person_per_day(self):
        state = presence.load()
        self.touch(state, when=at(28, 8, 15), reaction="thanks")
        self.assertIn("today", self.may(state, kind="evening",
                                        now=at(28, 18)))
        # The other person still may be greeted.
        self.assertEqual(self.may(state, person=ILO, now=at(28, 18)), "")
        # And tomorrow is a new day.
        self.assertEqual(self.may(state, now=at(29, 9, 30)), "")

    def test_a_few_per_week(self):
        state = presence.load()
        for i, day in enumerate((23, 24, 25)):
            self.touch(state, when=at(day, 9 + i), reaction="thanks")
        self.assertIn("week", self.may(state, now=at(26, 9, 30)))
        # A week after the first, there is room again.
        self.assertEqual(self.may(state, now=at(30, 12)), "")

    def test_the_house_caps_and_gap(self):
        state = presence.load()
        self.touch(state, person=ILO, when=at(28, 9), reaction="thanks")
        # Too soon after the last touch anybody in the house had.
        self.assertIn("minutes", self.may(state, now=at(28, 9, 45)))
        self.assertEqual(self.may(state, now=at(28, 11)), "")

    def test_never_inside_quiet_hours(self):
        why = self.may(presence.load(), now=at(28, 9), quiet=(22, 10))
        self.assertIn("quiet hours", why)

    def test_never_outside_the_day_even_without_quiet_hours(self):
        self.assertTrue(self.may(presence.load(), now=at(28, 6)))
        self.assertTrue(self.may(presence.load(), now=at(28, 22)))

    def test_never_to_somebody_away(self):
        self.assertIn("not home", self.may(presence.load(), home=False))

    def test_not_in_the_first_minutes_after_arriving_unless_it_is_the_greeting(self):
        state = presence.load()
        presence.note_departure(state, WREN, at(28, 5))
        self.assertTrue(presence.note_arrival(state, WREN, at(28, 9, 20)))
        self.assertIn("arrived", self.may(state, kind="morning"))
        self.assertEqual(self.may(state, kind="arrival"), "")
        self.assertEqual(self.may(state, kind="morning", now=at(28, 10)), "")

    def test_the_budget_numbers_are_small(self):
        self.assertEqual(presence.PER_PERSON_DAY, 1)
        self.assertLessEqual(presence.PER_PERSON_WEEK, 3)
        self.assertLessEqual(presence.HOUSE_DAY, 3)


class TestArrivals(StoreCase):

    def test_an_arrival_after_a_short_errand_is_not_one(self):
        state = presence.load()
        presence.note_departure(state, WREN, at(28, 9))
        self.assertFalse(presence.note_arrival(state, WREN, at(28, 9, 20)))

    def test_one_arrival_is_greeted_once(self):
        state = presence.load()
        presence.note_departure(state, WREN, at(28, 6))
        self.assertTrue(presence.note_arrival(state, WREN, at(28, 9)))
        # The phone's tracker flapping home → not_home → home a minute
        # later is the same arrival.
        presence.note_departure(state, WREN, at(28, 9, 1))
        self.assertFalse(presence.note_arrival(state, WREN, at(28, 9, 2)))

    def test_an_unknown_departure_is_not_an_arrival(self):
        # A restart sees somebody "arrive" with no record of leaving.
        self.assertFalse(presence.note_arrival(presence.load(), WREN, NOW))


class TestLearningFromReactions(StoreCase):

    def deliver(self, state, kind="morning", when=NOW, person=WREN):
        return presence.record_touch(state, person, PEOPLE[person],
                                     {"kind": kind, "text": "Hi.",
                                      "reason": "r"}, "phone", when)

    def test_not_now_stops_today_at_once_and_is_remembered(self):
        state = presence.load()
        t = self.deliver(state, when=at(28, 8, 30))
        presence.react(state, t["id"], "not_now", at(28, 8, 31), tz=UTC)
        presence.save(state)
        state = presence.load()
        why = presence.may_touch(state, WREN, "evening", at(28, 19), tz=UTC,
                                 home=True)
        self.assertIn("not now", why.lower())
        self.assertEqual(state["touches"][-1]["reaction"], "not_now")

    def test_less_of_this_retires_that_kind_for_that_person_only(self):
        state = presence.load()
        t = self.deliver(state, kind="morning", when=at(20, 9))
        presence.react(state, t["id"], "less", at(20, 9, 5), tz=UTC)
        why = presence.may_touch(state, WREN, "morning", NOW, tz=UTC,
                                 home=True)
        self.assertIn("less", why.lower())
        self.assertEqual(presence.may_touch(state, WREN, "evening", NOW,
                                            tz=UTC, home=True), "")
        self.assertEqual(presence.may_touch(state, ILO, "morning", NOW,
                                            tz=UTC, home=True), "")
        # And no new idea of that kind is accepted for that person.
        presence.add_ideas(state, [idea()], PEOPLE, NOW)
        self.assertEqual(presence.ideas_for(state, WREN), [])

    def test_repeated_swipes_retire_a_kind(self):
        state = presence.load()
        for day in (14, 17):
            t = self.deliver(state, kind="evening", when=at(day, 18))
            presence.react(state, t["id"], "cleared", at(day, 18, 1), tz=UTC)
        self.assertIn("evening", presence.retired_kinds(state, WREN))

    def test_three_unwanted_in_a_row_pause_the_person_for_a_week(self):
        state = presence.load()
        for day, kind in ((20, "morning"), (22, "evening"), (24, "followup")):
            t = self.deliver(state, kind=kind, when=at(day, 10))
            presence.react(state, t["id"], "ignored", at(day + 1, 11), tz=UTC)
        why = presence.may_touch(state, WREN, "occasion", at(26, 12), tz=UTC,
                                 home=True)
        self.assertIn("back", why.lower())
        self.assertEqual(presence.may_touch(state, WREN, "occasion",
                                            at(24, 10) + 8 * 86400, tz=UTC,
                                            home=True), "")

    def test_a_thanks_breaks_the_streak(self):
        state = presence.load()
        for day, reaction in ((14, "ignored"), (16, "ignored"),
                              (18, "thanks")):
            t = self.deliver(state, kind="followup", when=at(day, 10))
            presence.react(state, t["id"], reaction, at(day, 11), tz=UTC)
        self.assertEqual(presence.may_touch(state, WREN, "followup",
                                            at(24, 12), tz=UTC, home=True), "")
        # The same three with no thanks is a week's rest.
        state["touches"][-1]["reaction"] = "ignored"
        self.assertIn("back", presence.may_touch(
            state, WREN, "followup", at(24, 12), tz=UTC, home=True))

    def test_a_late_passive_outcome_never_overrides_a_spoken_answer(self):
        state = presence.load()
        t = self.deliver(state)
        presence.react(state, t["id"], "thanks", NOW + 30, tz=UTC)
        presence.absorb(state, [{"id": t["delivery"] or "d1",
                                 "outcome": "ignored"}], NOW + 2 * 86400)
        self.assertEqual(state["touches"][-1]["reaction"], "thanks")

    def test_the_ledger_says_what_happened_to_a_phone_touch(self):
        state = presence.load()
        t = presence.record_touch(state, WREN, "Wren",
                                  {"kind": "evening", "text": "Hi.",
                                   "reason": "r"}, "phone", NOW,
                                  delivery="abc123")
        presence.absorb(state, [{"id": "abc123", "outcome": "cleared"}],
                        NOW + 3600)
        self.assertEqual(state["touches"][-1]["reaction"], "cleared")
        self.assertEqual(t["id"], state["touches"][-1]["id"])

    def test_a_button_identifier_round_trips_and_rejects_everything_else(self):
        state = presence.load()
        t = self.deliver(state)
        for button in presence.buttons(t["id"]):
            verb, tid = presence.parse_action(button["action"])
            self.assertEqual(tid, t["id"])
            self.assertIn(verb, presence.REACTIONS)
        for other in ("brain.fixed.12", "brain_presence.rm.x", "",
                      "brain_presence.thanks", "something.else.entirely"):
            self.assertIsNone(presence.parse_action(other))


class TestTheNightlyAnswerIsReadStrictly(StoreCase):

    def parse(self, obj, state=None, growth=()):
        return presence.parse_reflection(obj, PEOPLE, state or presence.load(),
                                         recent_growth=list(growth))

    def good(self, **over):
        body = {
            "growth": [{"text": "Keep arrival greetings to one short line; "
                                "the longer ones went unanswered.",
                        "why": "Two long greetings were swiped away."}],
            "ideas": [idea(kind="evening",
                           text="Evening, Wren. The porch light is on a "
                                "timer now, as you asked.",
                           reason="Wren asked for the porch light on Monday.")],
            "notes": [{"person": WREN,
                       "text": "Likes a heads-up about the bins."}],
        }
        body.update(over)
        return body

    def test_a_good_answer_is_kept(self):
        got = self.parse(self.good())
        self.assertEqual(len(got["growth"]), 1)
        self.assertEqual(len(got["ideas"]), 1)
        self.assertEqual(got["ideas"][0]["person"], WREN)
        self.assertEqual(len(got["notes"]), 1)
        self.assertEqual(got["refused"], 0)

    def test_text_and_json_text_and_garbage(self):
        self.assertEqual(len(self.parse(json.dumps(self.good()))["ideas"]), 1)
        for junk in (None, "", "not json", [], 7, {"growth": "x"},
                     {"ideas": {"a": 1}}):
            got = self.parse(junk)
            self.assertEqual((got["growth"], got["ideas"], got["notes"]),
                             ([], [], []), junk)

    def test_an_item_missing_a_field_or_off_the_vocabulary_is_dropped(self):
        bad = [
            {"person": WREN, "kind": "morning", "text": "Hi."},          # no reason
            {"person": WREN, "kind": "serenade", "text": "Hi.", "reason": "r"},
            {"person": "person.stranger", "kind": "morning", "text": "Hi.",
             "reason": "r"},
            {"person": WREN, "kind": "morning", "text": "x" * 400,
             "reason": "r"},
        ]
        got = self.parse(self.good(ideas=bad))
        self.assertEqual(got["ideas"], [])
        self.assertEqual(got["refused"], 4)

    def test_sensitive_attributes_are_refused(self):
        for text in ("Ask Wren how the therapy session went.",
                     "Wren seemed depressed; cheer them up.",
                     "Remind Wren to take the medication.",
                     "Ask Ilo about church on Sunday.",
                     "Wren's diet is going badly.",
                     "Ask about Wren's salary review."):
            with self.subTest(text=text):
                got = self.parse(self.good(
                    ideas=[idea(text=text)], growth=[], notes=[]))
                self.assertEqual(got["ideas"], [])
                self.assertEqual(got["refused"], 1)

    def test_a_judgement_of_a_person_is_refused_everywhere(self):
        judged = "Wren is lazy about the dishes."
        for field, item in (
                ("ideas", idea(text=judged)),
                ("notes", {"person": WREN, "text": judged}),
                ("growth", {"text": "Ilo is always late, so greet later.",
                            "why": "w"})):
            with self.subTest(field=field):
                got = self.parse({"growth": [], "ideas": [], "notes": [],
                                  field: [item]})
                self.assertEqual(got[field], [])
                self.assertEqual(got["refused"], 1)

    def test_ids_and_the_voice_are_refused(self):
        got = self.parse(self.good(
            ideas=[idea(text="light.porch is on, Wren.")],
            growth=[{"text": "My voice is now Nova.", "why": "w"}],
            notes=[]))
        self.assertEqual((got["ideas"], got["growth"]), ([], []))
        self.assertEqual(got["refused"], 2)

    def test_growth_is_bounded_and_deduplicated(self):
        many = [{"text": f"Note number {i} about pacing greetings well.",
                 "why": "w"} for i in range(5)]
        got = self.parse(self.good(growth=many, notes=[]))
        self.assertLessEqual(len(got["growth"]), presence.GROWTH_PER_NIGHT)
        same = self.parse(self.good(notes=[]), growth=[
            "Keep arrival greetings to one short line; the long ones "
            "went unanswered."])
        self.assertEqual(same["growth"], [])

    def test_ideas_are_capped_per_person_and_per_night(self):
        ideas_ = [idea(kind=k, text=f"Hello Wren, {k} {i}.")
                  for i, k in enumerate(("morning", "evening", "followup",
                                         "occasion", "arrival"))]
        got = self.parse(self.good(ideas=ideas_, notes=[]))
        self.assertLessEqual(len(got["ideas"]), presence.IDEAS_PER_PERSON)


class TestGrowthNotesTheAssistantWrites(StoreCase):

    def setUp(self):
        super().setUp()
        personality.save("Sable", "Warm, brief, never fussy.", str(self.pers))

    def test_a_self_note_is_marked_and_never_touches_the_persona_or_voice(self):
        before = personality.load(str(self.pers))
        personality.add_growth("Greetings work best short; the voice is now "
                               "Nova for evenings.", path=str(self.pers),
                               by="self")
        after = personality.load(str(self.pers))
        self.assertEqual(after["persona"], before["persona"])
        self.assertEqual(after["name"], before["name"])
        self.assertEqual(after["voice"], before["voice"])
        self.assertEqual(after["growth"][-1]["by"], "self")

    def test_a_self_note_can_be_removed_and_a_household_note_cannot(self):
        mine = personality.add_growth("Keep it short.", path=str(self.pers),
                                      by="self")
        theirs = personality.add_growth("We settled on a dry wit.",
                                        path=str(self.pers))
        self.assertTrue(personality.remove_growth(mine["at"], mine["text"],
                                                  path=str(self.pers)))
        self.assertFalse(personality.remove_growth(theirs["at"],
                                                   theirs["text"],
                                                   path=str(self.pers)))
        texts = [g["text"] for g in personality.load(str(self.pers))["growth"]]
        self.assertEqual(texts, ["We settled on a dry wit."])

    def test_the_payload_says_which_notes_are_its_own(self):
        personality.add_growth("Keep it short.", path=str(self.pers), by="self")
        got = personality.payload(str(self.pers))
        self.assertEqual(got["growth"][0].get("by"), "self")

    def test_writing_the_nights_growth_respects_the_weekly_cap(self):
        written = 0
        for i in range(10):
            written += presence.write_growth(
                [{"text": f"Lesson {i}: pace greetings around dinner."}],
                at(20 + i % 7, 4), path=str(self.pers))
        self.assertLessEqual(written, presence.GROWTH_PER_WEEK + 2)
        mine = [g for g in personality.load(str(self.pers))["growth"]
                if g.get("by") == "self"]
        week = [g for g in mine if g["at"] >= at(20, 4) and g["at"] < at(27, 4)]
        self.assertLessEqual(len(week), presence.GROWTH_PER_WEEK)


class TestTheQueueAndThePanel(StoreCase):

    def test_ideas_expire_and_are_due_only_in_their_window(self):
        state = self.state_with(idea(kind="morning"), now=at(28, 3))
        self.assertEqual(presence.due_ideas(state, at(28, 6), tz=UTC), [])
        self.assertEqual(len(presence.due_ideas(state, at(28, 9), tz=UTC)), 1)
        self.assertEqual(presence.due_ideas(state, at(28, 14), tz=UTC), [])
        self.assertEqual(presence.due_ideas(state, at(30, 9), tz=UTC), [])

    def test_an_arrival_idea_is_never_due_on_the_clock(self):
        state = self.state_with(idea(kind="arrival"))
        self.assertEqual(presence.due_ideas(state, at(28, 12), tz=UTC), [])
        self.assertTrue(presence.idea_for(state, WREN, "arrival"))

    def test_skip_and_never(self):
        state = self.state_with(idea(kind="morning"), idea(kind="evening"))
        first = presence.ideas_for(state, WREN)[0]
        self.assertTrue(presence.skip_idea(state, WREN, first["id"]))
        presence.retire(state, WREN, "evening", NOW)
        self.assertEqual(presence.ideas_for(state, WREN), [])
        self.assertIn("evening", presence.retired_kinds(state, WREN))
        presence.unretire(state, WREN, "evening")
        self.assertNotIn("evening", presence.retired_kinds(state, WREN))

    def test_a_delivered_idea_leaves_the_queue_and_the_touch_has_its_reason(self):
        state = self.state_with(idea(kind="morning"))
        got = presence.ideas_for(state, WREN)[0]
        touch = presence.record_touch(state, WREN, "Wren", got, "phone", NOW)
        self.assertEqual(presence.ideas_for(state, WREN), [])
        self.assertEqual(touch["reason"], got["reason"])
        presence.save(state)
        back = presence.load()
        self.assertEqual(back["touches"][-1]["text"], got["text"])

    def test_the_payload_has_no_ids_in_its_words_and_is_compact(self):
        state = self.state_with(idea(kind="morning"))
        presence.record_touch(state, WREN, "Wren",
                              presence.ideas_for(state, WREN)[0], "phone", NOW)
        out = presence.payload(state, NOW, tz=UTC, on=True, why="",
                               people=PEOPLE)
        self.assertTrue(out["on"])
        row = out["touches"][0]
        self.assertEqual(row["name"], "Wren")
        self.assertNotIn("person.", row["kind_label"] + row["when"])
        self.assertLessEqual(len(out["touches"]), presence.PANEL_TOUCHES)
        self.assertEqual(out["budget"]["per_day"], presence.PER_PERSON_DAY)

    def test_notes_are_small_and_removable(self):
        state = presence.load()
        for i in range(5):
            presence.add_notes(state, [{"person": WREN,
                                        "text": f"Likes thing {i}."}],
                               PEOPLE, NOW + i)
        notes = presence.notes_for(state, WREN)
        self.assertLessEqual(len(notes), presence.NOTES_PER_PERSON)
        self.assertTrue(presence.remove_note(state, WREN, notes[0]["id"]))
        self.assertEqual(len(presence.notes_for(state, WREN)),
                         len(notes) - 1)

    def test_an_unreadable_store_is_an_empty_one(self):
        self.store.write_text("{nope", encoding="utf-8")
        state = presence.load()
        self.assertEqual(state["touches"], [])
        self.assertEqual(state["people"], {})

    def test_reflection_is_due_once_a_night(self):
        state = presence.load()
        self.assertTrue(presence.reflect_due(state, at(28, 3, 10), tz=UTC))
        self.assertFalse(presence.reflect_due(state, at(28, 14), tz=UTC))
        presence.note_reflected(state, at(28, 3, 10), {"ok": True})
        self.assertFalse(presence.reflect_due(state, at(28, 4), tz=UTC))
        self.assertTrue(presence.reflect_due(state, at(29, 3, 5), tz=UTC))


class TestNothingIsAboutAPersonInTheScorecard(unittest.TestCase):
    """The presence loop keeps its own small store and never writes the
    Resident's verdict log or a judgement fact (`outcomes._is_person_scope`
    is the rule it would break)."""

    def test_the_module_never_imports_outcomes_or_the_facts_store(self):
        src = (BASE_DIR / "brain" / "panel" / "presence.py").read_text()
        for name in ("import outcomes", "import facts_store",
                     "import findings_store"):
            self.assertNotIn(name, src)


if __name__ == "__main__":
    unittest.main()
