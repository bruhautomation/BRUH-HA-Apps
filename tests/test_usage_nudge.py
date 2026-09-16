"""The usage figure is read when a run has just moved it, not on a timer.

The bug these exist for is two bugs that share a cause.

`POLL_INTERVAL` was 300s — 288 requests a day at an endpoint Claude Code
itself calls only from its `/usage` screen, on demand, never on a timer.
The account's utilisation moves when a run spends tokens and at no other
time, so 280-odd of those asked an unchanged question.

And polling harder could not fix the failure people actually saw. The
tracker sends the *access* token, which lives hours; only the CLI can mint
the next one from the refresh token, and only as part of a real run
(`claude auth status` is a local read — it refreshes nothing). So on a
quiet house the token lapses, the tracker correctly sends nothing, the
reading ages out at two hours and four sensors go unavailable until
something happens to run Claude. A 1.56.0 report from a real install
carried exactly that: `oauth_token_awaiting_refresh`, not `http_429`.

A finished run is therefore the one moment worth a request — it is both
when the number changed AND when the credential is certain to work. Hence
a slow heartbeat plus a nudge, and the rules those have to keep:

  * a nudge may only ever shorten the ORDINARY cadence; a 429 or
    five-failure backoff is served whole, because a run finishing is not
    news to an endpoint that has just refused us;
  * `MIN_SPACING_S` is a floor and not a filter — a nudge inside it waits,
    it is never dropped, because that run's spend is the unread one;
  * the nudge must fire for every Claude run of every kind and for no
    checks pass, keyed on the journal ROW rather than on a list of source
    names that would drift;
  * and the heartbeat must stay shorter than the staleness window, or a
    house that never nudges goes unavailable between two working polls.
"""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
TRACKER = BASE_DIR / "brain" / "scripts" / "usage-limits-tracker.py"
sys.path.insert(0, str(PANEL))

import journal  # noqa: E402
import usage_store  # noqa: E402


def load_tracker(env=None):
    """The tracker, imported with a given environment — its paths are
    module-level constants resolved at import time."""
    env = env or {}
    saved = {k: os.environ.get(k) for k in env}
    for key, value in env.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    try:
        spec = importlib.util.spec_from_file_location("usage_tracker_nudge",
                                                      TRACKER)
        module = importlib.util.module_from_spec(spec)
        sys.modules["usage_tracker_nudge"] = module
        spec.loader.exec_module(module)
        return module
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class Clock:
    """A clock and a sleeper that agree, so a wait can be driven whole
    without spending the time it is about."""

    def __init__(self):
        self.now = 0.0
        self.slept = []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds
        if len(self.slept) > 10000:  # a wait that will not end is a bug
            raise AssertionError("_wait did not terminate")


class TestTheTwoEndsAgreeOnThePath(unittest.TestCase):
    """The tracker is a separate process that imports nothing from the
    panel, so the nudge path is spelled twice. `AUTH_BACKUP_FILE` is the
    precedent: a rename that goes silent on one side is a feature that
    quietly stops working."""

    def test_the_panel_and_the_tracker_name_the_same_file(self):
        mod = load_tracker()
        self.assertEqual(mod.NUDGE_FILE, usage_store.NUDGE_FILE)

    def test_both_read_the_same_environment_override(self):
        """Not just equal defaults — the same env var, or a test (or a
        person) can move one end and not the other."""
        for source in (TRACKER, PANEL / "usage_store.py"):
            text = source.read_text()
            self.assertRegex(
                text, r'NUDGE_FILE\s*=\s*os\.environ\.get\(\s*"BRAIN_USAGE_NUDGE"',
                f"{source.name} does not take BRAIN_USAGE_NUDGE")


class TestWhatCountsAsARun(unittest.TestCase):
    """Driven through the REAL `journal.record`, never over hand-written
    dicts: a fixture that writes the row shape down itself is a fixture
    agreeing with the guess the code made."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "journal.jsonl")
        self._saved = journal.JOURNAL_FILE
        journal.JOURNAL_FILE = self.path
        self.addCleanup(lambda: setattr(journal, "JOURNAL_FILE", self._saved))

    def test_an_engine_run_is_a_run(self):
        row = journal.record("insight", "ok", duration_s=12.0,
                             model="claude-opus-5", tokens=41230, turns=6,
                             run_id="abc-123")
        self.assertTrue(journal.is_claude_run(row))

    def test_a_chat_turn_is_a_run(self):
        """The chat records no tokens and no model — the CLI's own result
        envelope always carries `num_turns` (verified against the bundle:
        every `type:"result"` it yields sets it), so `turns` is what makes
        a chat turn identifiable."""
        row = journal.record("chat", "ok", duration_s=3.5, turns=2)
        self.assertTrue(journal.is_claude_run(row))

    def test_a_run_that_ended_on_its_first_turn_is_a_run(self):
        """Presence, not truthiness. `turns: 0` is what the CLI reports on
        its `error_during_execution` path, and a truthiness test reads it
        as no run at all — which is the one run most worth asking about,
        since it still spent whatever it spent getting there."""
        row = journal.record("chat", "error", error="boom", turns=0)
        self.assertEqual(row.get("turns"), 0)
        self.assertTrue(journal.is_claude_run(row))

    def test_a_checks_pass_is_not_a_run(self):
        row = journal.record("checks", "ok", duration_s=8.0,
                             extra={"ran": 30, "found": 2})
        self.assertFalse(journal.is_claude_run(row))

    def test_a_baseline_build_is_not_a_run(self):
        row = journal.record("baselines", "error", error="no recorder",
                             extra={"builder": "thermal"})
        self.assertFalse(journal.is_claude_run(row))

    def test_an_overnight_heal_is_not_a_run(self):
        """`healing` runs no model at all — by design, because a model
        choosing what to restart is a guess wearing a remediation."""
        row = journal.record("healing", "healed", ok=True,
                             extra={"remedy": "addon_start"})
        self.assertFalse(journal.is_claude_run(row))

    def test_rubbish_is_not_a_run(self):
        for value in (None, "", 7, [], {}):
            self.assertFalse(journal.is_claude_run(value))


class TestTheNudgeFile(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "sub", "usage-nudge")
        self._saved = usage_store.NUDGE_FILE
        usage_store.NUDGE_FILE = self.path
        self.addCleanup(
            lambda: setattr(usage_store, "NUDGE_FILE", self._saved))

    def test_nothing_nudged_yet_is_zero_not_an_error(self):
        self.assertEqual(usage_store.nudged_at(), 0.0)

    def test_a_nudge_creates_its_directory_and_is_readable_back(self):
        self.assertTrue(usage_store.nudge())
        self.assertGreater(usage_store.nudged_at(), 0.0)

    def test_an_unwritable_nudge_is_false_and_never_raises(self):
        """It is called from the journal listener, which may not fail the
        run it is being told about."""
        usage_store.NUDGE_FILE = os.path.join(self.tmp.name, "wall", "x")
        os.makedirs(os.path.join(self.tmp.name, "wall"))
        os.chmod(os.path.join(self.tmp.name, "wall"), 0o500)
        self.addCleanup(os.chmod, os.path.join(self.tmp.name, "wall"), 0o700)
        if os.access(os.path.join(self.tmp.name, "wall"), os.W_OK):
            self.skipTest("running as a user permissions do not bind")
        self.assertFalse(usage_store.nudge())
        self.assertEqual(usage_store.nudged_at(), 0.0)


class TestTheListenerIsWiredToTheRealJournal(unittest.TestCase):
    """The end-to-end claim: a real `journal.record` for a real run reaches
    the real nudge file through the real listener.

    The predicate tests above prove `is_claude_run` answers correctly; this
    proves something asks it. Registering a listener and never calling it
    is the shape of failure this repo keeps finding (`unsettle`'s route with
    no caller, `trial_due` with no caller outside its own tests)."""

    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.nudge_path = os.path.join(self.tmp.name, "usage-nudge")
        self._saved_nudge = usage_store.NUDGE_FILE
        usage_store.NUDGE_FILE = self.nudge_path
        self.addCleanup(
            lambda: setattr(usage_store, "NUDGE_FILE", self._saved_nudge))
        self._saved_journal = journal.JOURNAL_FILE
        journal.JOURNAL_FILE = os.path.join(self.tmp.name, "journal.jsonl")
        self.addCleanup(
            lambda: setattr(journal, "JOURNAL_FILE", self._saved_journal))
        # The listener the panel registers at startup, registered here for
        # the length of one test rather than booting the whole app.
        journal.on_record(self.server._journal_usage_listener)
        self.addCleanup(journal.off_record,
                        self.server._journal_usage_listener)

    def test_a_finished_insight_run_nudges_the_tracker(self):
        self.assertEqual(usage_store.nudged_at(), 0.0)
        journal.record("insight", "ok", duration_s=30.0,
                       model="claude-opus-5", tokens=33000, turns=4,
                       run_id="sess-1")
        self.assertGreater(usage_store.nudged_at(), 0.0)

    def test_a_finished_chat_turn_nudges_the_tracker(self):
        journal.record("chat", "ok", duration_s=2.0, turns=1)
        self.assertGreater(usage_store.nudged_at(), 0.0)

    def test_a_failed_run_nudges_too(self):
        """It spent whatever it spent before it failed, so the figure moved
        — a nudge is about the number having changed, not about the run
        having gone well."""
        journal.record("insight", "timeout", error="timed out",
                       model="claude-opus-5", turns=12, run_id="sess-2")
        self.assertGreater(usage_store.nudged_at(), 0.0)

    def test_a_checks_pass_does_not_nudge(self):
        journal.record("checks", "ok", duration_s=9.0,
                       extra={"ran": 31, "found": 0})
        self.assertEqual(usage_store.nudged_at(), 0.0)

    def test_the_panel_registers_it_beside_the_report_writer(self):
        """Both listeners are hooked at the same place for the same
        reason; one of them being registered is not evidence about the
        other."""
        text = (PANEL / "server.py").read_text()
        block = text[text.index("journal.on_record("):]
        block = block[:400]
        self.assertIn("_journal_report_listener", block)
        self.assertIn("_journal_usage_listener", block)


class TestTheWait(unittest.TestCase):
    """The real `_wait`, driven over a clock that does not spend the time."""

    def setUp(self):
        self.mod = load_tracker()
        self.clock = Clock()

    def wait(self, delay, seen, stamp, interruptible=True):
        return self.mod._wait(
            delay, seen, interruptible=interruptible,
            sleeper=self.clock.sleep, clock=self.clock.time, stamp=stamp)

    def test_a_quiet_wait_runs_its_full_length(self):
        answered = self.wait(1800, 0.0, lambda: 0.0)
        self.assertEqual(answered, 0.0)
        self.assertAlmostEqual(sum(self.clock.slept), 1800, places=3)

    def test_a_nudge_cuts_the_wait_short(self):
        answered = self.wait(1800, 0.0, lambda: 500.0)
        self.assertEqual(answered, 500.0)
        # It asks at the floor, not at the full heartbeat.
        self.assertAlmostEqual(sum(self.clock.slept),
                               self.mod.MIN_SPACING_S, places=3)

    def test_a_nudge_waits_out_the_floor_rather_than_asking_at_once(self):
        """A checks pass that triages, files and heals is several runs in a
        minute: one thing happened to the figure, not five questions."""
        self.wait(1800, 0.0, lambda: 500.0)
        self.assertGreaterEqual(sum(self.clock.slept), self.mod.MIN_SPACING_S)

    def test_a_nudge_inside_the_floor_is_held_and_not_dropped(self):
        """The run that fired it is exactly the one whose spend is
        unread, so the floor may delay the request and never cancel it."""
        fired = {"at": None}

        def stamp():
            # Lands one slice in, well inside the floor.
            if self.clock.now >= self.mod.NUDGE_CHECK_S:
                fired["at"] = fired["at"] or self.clock.now
                return 900.0
            return 0.0

        answered = self.wait(1800, 0.0, stamp)
        self.assertEqual(answered, 900.0)
        self.assertLess(fired["at"], self.mod.MIN_SPACING_S)
        self.assertGreaterEqual(sum(self.clock.slept), self.mod.MIN_SPACING_S)
        self.assertLess(sum(self.clock.slept), 1800)

    def test_a_stamp_already_answered_is_not_a_nudge(self):
        """Or every wait after one run would return immediately, for ever."""
        answered = self.wait(1800, 500.0, lambda: 500.0)
        self.assertEqual(answered, 500.0)
        self.assertAlmostEqual(sum(self.clock.slept), 1800, places=3)

    def test_a_nudge_that_landed_during_the_request_is_not_lost(self):
        """`seen` is what this process has answered, not when the wait
        began — a run finishing while the request was on the wire is still
        pending when the wait starts."""
        answered = self.wait(1800, 100.0, lambda: 101.0)
        self.assertEqual(answered, 101.0)
        self.assertLess(sum(self.clock.slept), 1800)

    def test_a_backoff_is_served_whole_however_many_runs_finish(self):
        """The rule `Retry-After: 0` taught: a wait that exists because
        asking cannot help is not shortened by news that has nothing to do
        with the refusal."""
        answered = self.wait(3600, 0.0, lambda: 500.0, interruptible=False)
        self.assertEqual(answered, 0.0)
        self.assertEqual(self.clock.slept, [3600])

    def test_the_wait_terminates_when_the_stamp_keeps_moving(self):
        """A nudge per slice must not become a wait that never returns."""
        answered = self.wait(1800, 0.0, lambda: self.clock.now + 1)
        self.assertGreater(answered, 0.0)
        self.assertGreaterEqual(sum(self.clock.slept), self.mod.MIN_SPACING_S)


class TestTheCadenceInvariants(unittest.TestCase):

    def setUp(self):
        self.mod = load_tracker()

    def test_the_heartbeat_is_shorter_than_the_staleness_window(self):
        """The invariant this release introduces. A house that never
        nudges — nothing scheduled, nobody in the chat — has only the
        heartbeat, and a heartbeat longer than the window means two
        successful polls with the sensors unavailable between them."""
        self.assertLess(self.mod.POLL_INTERVAL, usage_store.LIMITS_MAX_AGE_S)
        # And with room for a missed one: a single failed poll deliberately
        # leaves a fresh reading alone to age out rather than blanking four
        # working sensors, which is only true while the window holds two
        # heartbeats.
        self.assertGreaterEqual(usage_store.LIMITS_MAX_AGE_S,
                                2 * self.mod.POLL_INTERVAL)

    def test_the_two_staleness_answers_still_agree(self):
        self.assertEqual(self.mod.STALE_AFTER_S, usage_store.LIMITS_MAX_AGE_S)

    def test_the_floor_is_shorter_than_the_heartbeat(self):
        """Or the floor is the cadence and the nudge does nothing."""
        self.assertLess(self.mod.MIN_SPACING_S, self.mod.POLL_INTERVAL)

    def test_the_slice_is_shorter_than_the_floor(self):
        """The wait has to be able to notice a nudge inside the floor in
        order to hold it."""
        self.assertLess(self.mod.NUDGE_CHECK_S, self.mod.MIN_SPACING_S)

    def test_every_backoff_still_backs_off_past_the_new_heartbeat(self):
        """Lengthening the poll is what broke this invariant last time,
        in the other direction: a step shorter than the heartbeat means a
        failing tracker asks more often than a working one."""
        for step in self.mod.RATE_LIMIT_BACKOFF_S:
            self.assertGreater(step, self.mod.POLL_INTERVAL)
        self.assertGreater(self.mod.FAILURE_BACKOFF_S, self.mod.POLL_INTERVAL)

    def test_the_heartbeat_asks_for_far_less_than_it_used_to(self):
        """288 requests a day was the number that prompted this. The
        endpoint's own client asks on demand and never on a timer, so the
        bar is not 'sustainable' but 'defensible'."""
        per_day = 86400 / self.mod.POLL_INTERVAL
        self.assertLessEqual(per_day, 60)


if __name__ == "__main__":
    unittest.main()
