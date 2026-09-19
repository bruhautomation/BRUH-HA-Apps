#!/usr/bin/env python3
"""One habits module behind three ledgers.

`routines`, `override_ledger` and `manual_ledger` each kept a ledger AND a
private derivation of "the shape of when something happens" — days, share,
a circular median, a band, still-happening. Three answers to one question
is the drift a second copy always produces, so `habits.py` is the one
arithmetic and the three keep their files and their floors.

The load-bearing test is the comparison: the OLD arithmetic, copied here
from what shipped in 2.1, driven over the same stamps as the new, on every
case the prose names — a weekday habit, a weekend-only one, `every day`
earned twice, a bedtime either side of midnight, the 08:10 band that must
not report 05:00–09:00. A delegation that changed an answer would show up
as a number, not as a description.
"""

import datetime as dt
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import habit_lookup  # noqa: E402
import habits  # noqa: E402
import manual_ledger  # noqa: E402
import override_ledger  # noqa: E402
import rhythm  # noqa: E402
import routines  # noqa: E402

UTC = dt.timezone.utc


def at(day: int, hour: int, minute: int = 0, month: int = 9) -> float:
    """A stamp on a 2026 day, UTC."""
    return dt.datetime(2026, month, day, hour, minute, tzinfo=UTC).timestamp()


# --------------------------------------------------------------------------
# What shipped in 2.1 — `routines._grade` and `override_ledger._band`, as
# they were, so the comparison is against the code and not a description.
# --------------------------------------------------------------------------

def _old_in_shape(stamp, shape):
    weekend = stamp.weekday() >= 5
    return (shape == "every day"
            or (shape == "weekdays" and not weekend)
            or (shape == "weekends" and weekend))


def _old_eligible(shape, first, last, tz):
    start = dt.datetime.fromtimestamp(first, tz).date()
    end = dt.datetime.fromtimestamp(last, tz).date()
    n = 0
    day = start
    while day <= end:
        weekend = day.weekday() >= 5
        if (shape == "every day"
                or (shape == "weekdays" and not weekend)
                or (shape == "weekends" and weekend)):
            n += 1
        day += dt.timedelta(days=1)
    return n


def _old_grade(stamps, shape, tz):
    kept = [s for s in stamps if _old_in_shape(s, shape)]
    if not kept:
        return None
    days = {s.date() for s in kept}
    if len(days) < routines.MIN_DAYS:
        return None
    minutes = [s.hour * 60 + s.minute for s in kept]
    centre = rhythm.circular_median(minutes)
    if centre is None:
        return None
    spread = rhythm.circular_spread(minutes, centre)
    if spread > routines.MAX_SPREAD_MIN:
        return None
    first = min(s.timestamp() for s in kept)
    last = max(s.timestamp() for s in kept)
    eligible = _old_eligible(shape, first, last, tz)
    if eligible <= 0:
        return None
    share = len(days) / eligible
    if share < routines.MIN_SHARE:
        return None
    return {"when_days": shape, "minute": round(centre),
            "at": rhythm.clock(centre), "spread_min": round(spread, 1),
            "days": len(days), "eligible_days": eligible,
            "share": round(share, 3), "events": len(kept),
            "first": int(first), "last": int(last)}


def _old_best_shape(stamps, tz):
    week = _old_grade(stamps, "weekdays", tz)
    end = _old_grade(stamps, "weekends", tz)
    if week and end:
        apart = rhythm.circular_spread([end["minute"]], week["minute"])
        if apart <= routines.MAX_SPREAD_MIN:
            daily = _old_grade(stamps, "every day", tz)
            if daily:
                return daily
        return week if week["days"] >= end["days"] else end
    return week or end


def _old_band(hours):
    if not hours:
        return None
    best = None
    for start in range(24):
        offsets = sorted((h - start) % 24 for h in hours
                         if (h - start) % 24 < override_ledger.BAND_HOURS)
        if not offsets:
            continue
        rank = (len(offsets), -(offsets[-1] - offsets[0]))
        if best is None or rank > best[0]:
            best = (rank, start, offsets)
    if best is None:
        return None
    _rank, start, offsets = best
    return ((start + offsets[0]) % 24,
            (start + offsets[-1] + 1) % 24,
            len(offsets) / len(hours))


# --------------------------------------------------------------------------
# Fixtures: the cases the prose names
# --------------------------------------------------------------------------

def weekday_habit():
    """Ten weekdays at about 18:40, over two working weeks (Sep 2026: the
    7th is a Monday)."""
    out = []
    for day in (7, 8, 9, 10, 11, 14, 15, 16, 17, 18):
        out.append(at(day, 18, 40 + (day % 3)))
    return out


def weekend_only():
    """Six weekend days at about 10:00 — three weekends."""
    return [at(d, 10, m) for d, m in ((5, 0), (6, 5), (12, 2), (13, 0),
                                       (19, 4), (20, 1))]


def ten_weekdays_one_sunday():
    return weekday_habit() + [at(13, 18, 41)]


def genuinely_daily():
    """Every day for three weeks at 07:00 — both halves hold up."""
    return [at(d, 7, d % 4) for d in range(1, 22)]


def bedtime_astride_midnight():
    """Settle times either side of midnight: 23:50, 23:55, 00:05, 00:10 —
    the case whose straight median is noon."""
    return [at(1, 23, 50), at(2, 23, 55), at(4, 0, 5), at(5, 0, 10),
            at(6, 23, 58), at(8, 0, 3), at(9, 23, 52), at(11, 0, 8)]


class TestTheDelegationIsTheSameArithmetic(unittest.TestCase):
    """The comparison. Every case is driven through what shipped and
    through `habits`, and the answers have to agree number for number."""

    CASES = {
        "weekday habit": weekday_habit,
        "weekend only": weekend_only,
        "ten weekdays and one sunday": ten_weekdays_one_sunday,
        "genuinely daily": genuinely_daily,
        "bedtime astride midnight": bedtime_astride_midnight,
    }

    def test_grade_agrees_with_what_shipped_on_every_shape(self):
        for name, make in self.CASES.items():
            stamps = make()
            whens = [dt.datetime.fromtimestamp(s, UTC) for s in stamps]
            for shape in habits.SHAPES:
                with self.subTest(case=name, shape=shape):
                    old = _old_grade(whens, shape, UTC)
                    new = routines._grade(whens, shape, UTC)
                    self.assertEqual(old, new)

    def test_best_shape_agrees_with_what_shipped(self):
        for name, make in self.CASES.items():
            whens = [dt.datetime.fromtimestamp(s, UTC) for s in make()]
            with self.subTest(case=name):
                self.assertEqual(_old_best_shape(whens, UTC),
                                 routines._best_shape(whens, UTC))

    def test_every_day_is_earned_twice(self):
        # Ten weekdays and one Sunday clears a whole-window share and is
        # NOT every day; three weeks of every morning is.
        mixed = [dt.datetime.fromtimestamp(s, UTC)
                 for s in ten_weekdays_one_sunday()]
        self.assertEqual(routines._best_shape(mixed, UTC)["when_days"],
                         "weekdays")
        daily = [dt.datetime.fromtimestamp(s, UTC) for s in genuinely_daily()]
        self.assertEqual(routines._best_shape(daily, UTC)["when_days"],
                         "every day")

    def test_a_bedtime_either_side_of_midnight_is_not_noon(self):
        whens = [dt.datetime.fromtimestamp(s, UTC)
                 for s in bedtime_astride_midnight()]
        found = habits.grade(bedtime_astride_midnight(), UTC, min_days=6)
        self.assertIsNotNone(found)
        # Within a few minutes of midnight, and nowhere near 12:00.
        centre = found["median_minute"]
        self.assertTrue(centre >= 23 * 60 + 40 or centre <= 20, centre)
        # The failure it replaced, on the same data.
        import statistics
        straight = statistics.median([w.hour * 60 + w.minute for w in whens])
        self.assertTrue(11 * 60 <= straight <= 13 * 60, straight)

    def test_the_band_reports_occupied_hours_not_the_search_window(self):
        hours = [8] * 15
        self.assertEqual(_old_band(hours), habits.band(hours))
        self.assertEqual(habits.band(hours)[:2], (8, 9))
        self.assertEqual(override_ledger._band(hours)[:2], (8, 9))
        # And it wraps: 22:00–01:00 is one bedtime, not two halves.
        late = [22, 23, 0, 0, 1, 23, 22]
        self.assertEqual(_old_band(late), habits.band(late))
        start, end, share = habits.band(late)
        self.assertEqual((start, end), (22, 2))
        self.assertEqual(share, 1.0)

    def test_a_band_share_floor_gates_rather_than_describes(self):
        scattered = [1, 5, 9, 13, 17, 21]
        self.assertIsNotNone(habits.band(scattered))
        self.assertIsNone(habits.band(scattered, band_share=0.75))

    def test_still_happening_is_read_off_the_last_stamp(self):
        stamps = weekday_habit()
        last = max(stamps)
        fresh = habits.grade(stamps, UTC, now=last + 86400, min_days=6,
                             recent_days=10)
        stale = habits.grade(stamps, UTC, now=last + 40 * 86400, min_days=6,
                             recent_days=10)
        self.assertTrue(fresh["still_happening"])
        self.assertFalse(stale["still_happening"])


class TestTheOverrideLedgerStillAnswersAsItDid(unittest.TestCase):
    def rows(self, hours, days):
        out = []
        for i, day in enumerate(days):
            out.append({"ts": at(day, hours[i % len(hours)], 10),
                        "entity_id": "light.hall", "by": "automation.evening",
                        "by_name": "Evening lights"})
        return out

    def test_a_pattern_carries_the_band_and_the_days(self):
        rows = self.rows([8, 8, 8, 8, 8], [7, 8, 9, 10, 11])
        found = override_ledger.pattern(rows, UTC, now=at(12, 12))
        self.assertIsNotNone(found)
        self.assertEqual((found["from_hour"], found["to_hour"]), (8, 9))
        self.assertEqual(found["days"], 5)
        self.assertEqual(found["when_days"], "weekdays")

    def test_a_pattern_that_stopped_is_no_pattern(self):
        rows = self.rows([8, 8, 8, 8, 8], [7, 8, 9, 10, 11])
        self.assertIsNone(override_ledger.pattern(
            rows, UTC, now=at(11, 12) + 30 * 86400))

    def test_too_few_days_is_no_pattern_whatever_the_count(self):
        rows = [{"ts": at(7, 8, m), "entity_id": "light.hall",
                 "by": "automation.evening"} for m in range(0, 40, 4)]
        self.assertIsNone(override_ledger.pattern(rows, UTC, now=at(7, 12)))


class TestTheManualLedgerStillAnswersAsItDid(unittest.TestCase):
    def rows(self, stamps, cause="person"):
        return [{"ts": s, "entity_id": "switch.sprinklers", "state": "on",
                 "cause": cause, "name": "Sprinklers"} for s in stamps]

    def test_shape_is_the_circular_median_over_the_span(self):
        found = manual_ledger.shape(self.rows(weekday_habit()), UTC,
                                    now=at(19, 12))
        self.assertIsNotNone(found)
        self.assertEqual(found["when_days"], "weekdays")
        self.assertEqual(found["days"], 10)
        self.assertTrue(18 * 60 + 39 <= found["minute"] <= 18 * 60 + 43)
        self.assertEqual(found["cause"], "person")

    def test_a_mixed_week_reads_as_any_day(self):
        found = manual_ledger.shape(self.rows(genuinely_daily()), UTC,
                                    now=at(22, 12))
        self.assertEqual(found["when_days"], "any day")

    def test_the_odd_press_is_measured_the_short_way_round(self):
        history = [at(d, 23, 50) for d in range(1, 9)]
        # 00:10 the next night is twenty minutes away, not twenty-three
        # hours — and so NOT odd against a 23:50 habit.
        near = habits.odd_press(at(9, 0, 10), history, UTC, spreads=3.0,
                                floor_min=90.0, min_days=6)
        self.assertIsNone(near)
        far = habits.odd_press(at(9, 14, 0), history, UTC, spreads=3.0,
                               floor_min=90.0, min_days=6)
        self.assertIsNotNone(far)
        self.assertGreater(far["away_min"], 90)

    def test_off_pattern_delegates_and_still_finds_the_two_am_press(self):
        history = [at(d, 19, 0 + d % 3) for d in range(1, 11)]
        odd = at(11, 2, 0)
        payload = {"rows": self.rows(history + [odd]), "automated": {}}
        out = manual_ledger.off_pattern(payload, UTC, now=odd + 3600)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["ts"], int(odd))
        self.assertEqual(out[0]["usually_at"], "19:01")


class TestHabitOfJoinsTheThreeRealLedgers(unittest.TestCase):
    """Driven through the three modules' own `record`/`load`, into temp
    files, so the join reads the shapes the ledgers really write."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = {name: os.path.join(self.tmp.name, name + ".json")
                      for name in ("routines", "overrides", "manual")}

    def tearDown(self):
        self.tmp.cleanup()

    def test_one_entity_one_answer(self):
        now = at(19, 12)
        actions = [{"entity_id": "light.porch", "state": "on", "cause": "person",
                    "ts": s, "name": "Porch light"} for s in weekday_habit()]
        routines.record(actions, now=now, path=self.paths["routines"])
        manual_ledger.record(actions, now=now, path=self.paths["manual"])
        overrides = [{"ts": at(d, 18, 45), "entity_id": "light.porch",
                      "by": "automation.dusk", "by_name": "Dusk lights",
                      "by_cause": "automation", "from_state": "on",
                      "to_state": "off"}
                     for d in (14, 15, 16, 17, 18)]
        override_ledger.record(overrides, now=now, path=self.paths["overrides"])

        ledger = routines.load(self.paths["routines"])
        answer = habit_lookup.habit_of(
            "light.porch", routine_rows=ledger.get("rows") or [],
            override_rows=override_ledger.load(self.paths["overrides"]),
            manual_rows=manual_ledger.load(self.paths["manual"]).get("rows") or [],
            automated=ledger.get("automated") or {}, tz=UTC, now=now)

        self.assertEqual(answer["entity_id"], "light.porch")
        self.assertIsNotNone(answer["habit"], answer)
        self.assertEqual(answer["habit"]["shape"], "weekdays")
        self.assertEqual(answer["state"], "on")
        self.assertIn("porch", answer["sentence"].lower())
        self.assertIn("weekday", answer["sentence"].lower())
        # An automation somebody keeps undoing IS something that already
        # does this.
        self.assertTrue(answer["automated"])
        self.assertEqual(len(answer["overrides"]), 1)
        self.assertEqual(answer["overrides"][0]["automation"], "automation.dusk")

    def test_an_entity_nobody_touches_has_no_habit_and_says_so(self):
        answer = habit_lookup.habit_of("light.attic", tz=UTC, now=at(19, 12))
        self.assertIsNone(answer["habit"])
        self.assertEqual(answer["overrides"], [])
        self.assertFalse(answer["automated"])
        self.assertTrue(answer["sentence"])


class TestTheOldArithmeticIsGone(unittest.TestCase):
    """A grep, on purpose: "this pattern is absent" is the one claim a grep
    can honestly make. Each ledger's private copy of the circular median
    or the band search must not come back."""

    def test_no_ledger_keeps_its_own_copy(self):
        for name in ("routines.py", "override_ledger.py", "manual_ledger.py"):
            src = (PANEL / name).read_text(encoding="utf-8")
            with self.subTest(module=name):
                self.assertNotIn("rhythm.circular_median(", src)
                self.assertNotIn("rhythm.circular_spread(", src)
                self.assertNotIn("(h - start) % 24", src)
                self.assertIsNotNone(re.search(r"^import habits$", src, re.M))

    def test_habits_is_the_one_place_the_median_is_taken(self):
        src = (PANEL / "habits.py").read_text(encoding="utf-8")
        self.assertIn("circular.circular_median(", src)
        self.assertIn("circular.circular_distance(", src)

    def test_the_clock_arithmetic_has_one_home_and_rhythm_re_exports_it(self):
        # `circular.py` is a leaf on purpose: `rhythm` reads `house`, `house`
        # reads the ledgers, the ledgers read `habits`, and `habits` reading
        # `rhythm` for the median closed the ring. The names every caller
        # uses still resolve through `rhythm`, and to the same functions.
        import circular
        self.assertIs(rhythm.circular_median, circular.circular_median)
        self.assertIs(rhythm.circular_spread, circular.circular_spread)
        self.assertIs(rhythm.circular_distance, circular.circular_distance)
        self.assertIs(rhythm.clock, circular.clock)
        src = (PANEL / "rhythm.py").read_text(encoding="utf-8")
        self.assertNotIn("def circular_median(", src)
        leaf = (PANEL / "circular.py").read_text(encoding="utf-8")
        self.assertNotIn("import baselines", leaf)
        self.assertNotIn("import house", leaf)
        # And the join over the ledgers is not in the module they import.
        self.assertNotIn("def habit_of(", src)
        self.assertNotIn("def habit_of(", (PANEL / "habits.py").read_text(encoding="utf-8"))

    def test_no_import_ring_through_habits(self):
        # Driven rather than grepped: each module imported fresh, alone,
        # in its own interpreter, which is the order an import ring breaks in.
        import subprocess
        import sys as _sys
        for name in ("habits", "habit_lookup", "rhythm", "routines",
                     "override_ledger", "manual_ledger", "house", "circular"):
            with self.subTest(module=name):
                proc = subprocess.run(
                    [_sys.executable, "-c", f"import {name}"],
                    cwd=str(PANEL), capture_output=True, text=True, timeout=60)
                self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main()
