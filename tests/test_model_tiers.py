"""Which tier a run is CHARGED to, and which one a timer may never reach.

The plan says what a job is planned at; the `thinking` dial and a typed
model move it. Two things read the answer and both used to read the table
instead: the Resident's ledger (so `generous` ran investigations on Opus
against the Sonnet allowance, and a typed Opus ran first looks on Opus
against nothing), and nothing at all on the override's side (so a typed
Fable put every scheduled run on the press-only tier). Driven through the
real `model_plan`, the real `resident.Ledger` on disk, and the server's own
ledger helpers.
"""
from __future__ import annotations

import datetime as dt
import sys
import tempfile
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import model_plan  # noqa: E402
import resident  # noqa: E402


class TestTierOf(unittest.TestCase):
    def test_aliases_ids_and_unknowns(self):
        self.assertEqual(model_plan.tier_of("opus"), "opus")
        self.assertEqual(model_plan.tier_of("claude-opus-5-5"), "opus")
        self.assertEqual(model_plan.tier_of("claude-sonnet-4-6"), "sonnet")
        self.assertEqual(model_plan.tier_of("claude-haiku-4-5"), "haiku")
        self.assertEqual(model_plan.tier_of("fable"), "fable")
        # A name holding no tier is unknown, never guessed.
        self.assertIsNone(model_plan.tier_of("claude-fake-9"))
        self.assertIsNone(model_plan.tier_of(""))


class TestTheOverridesOneGuard(unittest.TestCase):
    def test_fable_on_a_timer_falls_back_with_a_sentence(self):
        model, why = model_plan.guard_override("card", "fable")
        self.assertEqual(model, "")
        self.assertIn("press", why)
        model, why = model_plan.guard_override("first_look", "claude-fable-1")
        self.assertEqual((model, bool(why)), ("", True))

    def test_a_press_and_a_lower_tier_pass(self):
        self.assertEqual(model_plan.guard_override("card", "fable", pressed=True),
                         ("fable", ""))
        self.assertEqual(model_plan.guard_override("card", "claude-opus-5-5"),
                         ("claude-opus-5-5", ""))
        self.assertEqual(model_plan.guard_override("card", "sonnet"), ("sonnet", ""))
        self.assertEqual(model_plan.guard_override("card", ""), ("", ""))

    def test_the_shell_half_meets_it_too(self):
        """The consolidator and study run on timers; voice and the apply
        tier are somebody's request."""
        out = model_plan.env_exports("fable")
        self.assertEqual(out["BRAIN_MODEL_MEMORY"], "haiku")
        self.assertEqual(out["BRAIN_MODEL_STUDY"], "sonnet")
        self.assertEqual(out["BRAIN_MODEL_VOICE"], "fable")
        self.assertEqual(out["BRAIN_MODEL_OPUS"], "fable")
        # A typed Opus still overrides every export, as it always did.
        self.assertTrue(all(v == "claude-opus-5" for k, v in
                            model_plan.env_exports("claude-opus-5").items()
                            if k.startswith("BRAIN_MODEL_")))


class TestRunTier(unittest.TestCase):
    def test_the_dial_and_the_override_move_the_charge(self):
        self.assertEqual(model_plan.run_tier("investigate", "normal"), "sonnet")
        self.assertEqual(model_plan.run_tier("investigate", "generous"), "opus")
        self.assertEqual(model_plan.run_tier("first_look", "normal"), "haiku")
        self.assertEqual(model_plan.run_tier("first_look", "normal",
                                             "claude-opus-5-5"), "opus")
        # A refused Fable is charged where it actually ran.
        self.assertEqual(model_plan.run_tier("first_look", "normal", "fable"),
                         "haiku")
        # A model with no tier in its name is charged at the plan's.
        self.assertEqual(model_plan.run_tier("investigate", "generous",
                                             "claude-fake-9"), "opus")


class LedgerCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "ledger.json"


class TestTheLedgerChargesWhatRan(LedgerCase):
    def test_an_opus_first_look_is_capped_where_a_haiku_one_never_is(self):
        """The cheap tier is never stopped by the ledger, which is right
        for a cheap tier and was a hole for an Opus one charged as cheap."""
        led = resident.Ledger(self.path)
        now = 1_800_000_000.0
        cap = resident.OPUS_PER_DAY["normal"]
        tier = model_plan.run_tier(resident.JOB_FIRST_LOOK, "normal", "opus")
        for _ in range(cap):
            self.assertTrue(led.allows(tier, "normal", now=now)[0])
            led.record(resident.JOB_FIRST_LOOK, 10, now, tier=tier)
        allowed, why = led.allows(tier, "normal", now=now)
        self.assertFalse(allowed)
        self.assertIn("opus", why)
        # The same looks charged by the table would never have stopped.
        self.assertTrue(led.allows(resident.tier_for(resident.JOB_FIRST_LOOK),
                                   "normal", now=now)[0])
        self.assertEqual(led.today(now)["tiers"]["opus"]["runs"], cap)

    def test_the_server_reads_the_tier_off_the_model_it_sent(self):
        import server
        self.assertEqual(server._ran_tier({"meta": {"model": "claude-opus-5-5"}},
                                          resident.JOB_FIRST_LOOK), "opus")
        # No model on the result (the account's default) is the plan's tier.
        self.assertEqual(server._ran_tier({"meta": {}}, resident.JOB_INVESTIGATE),
                         "sonnet")


class TestTheLedgerDayIsTheHouses(LedgerCase):
    def _zone(self, name):
        zone = None
        try:
            from zoneinfo import ZoneInfo
            zone = ZoneInfo(name)
        except Exception:  # noqa: BLE001 — no tz database in this image
            zone = None
        return zone

    def test_a_reader_is_asked_each_time(self):
        zone = self._zone("Pacific/Auckland")
        if zone is None:
            self.skipTest("no timezone database")
        calls = []

        def reader():
            calls.append(1)
            return zone

        led = resident.Ledger(self.path, tz=reader)
        # 11:00 and 13:00 UTC are one UTC day and two Auckland days.
        evening = dt.datetime(2026, 9, 19, 11, tzinfo=dt.timezone.utc).timestamp()
        after = dt.datetime(2026, 9, 19, 13, tzinfo=dt.timezone.utc).timestamp()
        self.assertNotEqual(led.summary(evening)["day"], led.summary(after)["day"])
        self.assertGreaterEqual(len(calls), 2)

    def test_a_reader_that_fails_is_utc_and_not_a_failed_run(self):
        def broken():
            raise OSError("no cache")

        led = resident.Ledger(self.path, tz=broken)
        led.record(resident.JOB_INVESTIGATE, 5, 1_800_000_000.0)
        self.assertEqual(led.today(1_800_000_000.0)["jobs"],
                         {resident.JOB_INVESTIGATE: 1})

    def test_the_server_ledger_keeps_the_house_clock(self):
        zone = self._zone("Pacific/Auckland")
        if zone is None:
            self.skipTest("no timezone database")
        import baselines
        import server
        cache = Path(self.tmp.name) / "tz"
        cache.write_text("Pacific/Auckland\n")
        old = baselines.TZ_CACHE
        baselines.TZ_CACHE = str(cache)
        try:
            when = dt.datetime(2026, 9, 19, 13, tzinfo=dt.timezone.utc).timestamp()
            self.assertEqual(server.LEDGER.summary(when)["day"], "2026-09-20")
        finally:
            baselines.TZ_CACHE = old


class TestThePickerLeadsWithTheCurrentGeneration(unittest.TestCase):
    """A pin in ⚙ is a GLOBAL override, so a stale top pin moves a whole
    install onto an older, dearer model than the alias beside it."""

    def test_the_pins_are_the_current_releases_first(self):
        import engine
        pinned = [c["id"] for c in engine.MODEL_CHOICES
                  if c["group"] == "Pinned versions"]
        self.assertEqual(pinned[:2], ["claude-opus-5-5", "claude-sonnet-5-5"])
        previous = [c["id"] for c in engine.MODEL_CHOICES
                    if c["group"] == "Previous generation"]
        for old in ("claude-opus-5", "claude-sonnet-5"):
            self.assertIn(old, previous)
            self.assertNotIn(old, pinned)

    def test_every_pin_names_its_own_version(self):
        import chat_session
        import engine
        for choice in engine.MODEL_CHOICES:
            if choice["group"] in ("Pinned versions", "Previous generation"):
                self.assertEqual(chat_session.pretty_model(choice["id"]),
                                 choice["label"], choice["id"])


if __name__ == "__main__":
    unittest.main()
