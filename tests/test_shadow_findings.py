#!/usr/bin/env python3
"""Shadow mode — a check that runs and reaches nobody.

The claim is negative and it is five claims, not one: a shadow row does
not reach the Findings tab payload, the badge, the analyst's prompt block,
the notify router or the To-do mirror. A test of "it is not rendered"
would be a test of whichever one the author happened to think of, so each
is asserted separately — and each is verified against the same row filed
to the *real* store instead, because a surface that shows nothing for
either reason proves nothing about the reason.

The rest is about the two numbers that decide whether a trialled check
ships: how much it said, and how much of that something else said too.
"""
from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import checks  # noqa: E402
import findings_store  # noqa: E402
import notify_router  # noqa: E402
import shadow_findings  # noqa: E402

DAY = 86400.0
NOW = 1_800_000_000.0

ROW = {"text": "The porch sensor has not reported since Tuesday",
       "detail": "last seen 3 Sep", "fix": "Re-pair it",
       "severity": "critical", "source": "check:dev.example",
       "source_title": "Device check"}


class ShadowCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        self._old = (shadow_findings.SHADOW_FILE,
                     findings_store.FINDINGS_FILE,
                     findings_store.SETTLED_FILE,
                     findings_store.STATE_FILE)
        shadow_findings.SHADOW_FILE = base / "findings-shadow.json"
        findings_store.FINDINGS_FILE = base / "findings.json"
        findings_store.SETTLED_FILE = base / "settled.json"
        # The mirror's grandparent must not exist, or a dev checkout grows
        # a stray /config — the store's own rule, and here it is also what
        # makes "the mirror was never written" checkable.
        findings_store.STATE_FILE = base / "cfg" / ".brain" / "findings_state.json"

    def tearDown(self):
        (shadow_findings.SHADOW_FILE, findings_store.FINDINGS_FILE,
         findings_store.SETTLED_FILE, findings_store.STATE_FILE) = self._old
        self.tmp.cleanup()


# ---------------------------------------------------------------------------
# It reaches nobody — one assertion per surface
# ---------------------------------------------------------------------------

class TestAShadowRowReachesNobody(ShadowCase):
    """Each of these is verified by filing the SAME row to the real store
    and watching the surface light up. A surface that shows nothing either
    way proves nothing about the reason."""

    def shadow_row(self):
        made = shadow_findings.add_many([ROW], NOW)
        self.assertEqual(len(made), 1)
        return made[0]

    def real_row(self):
        made = findings_store.add_many([ROW])
        self.assertEqual(len(made), 1)
        return made[0]

    def test_it_is_not_in_the_tab_payload(self):
        self.shadow_row()
        self.assertEqual(findings_store.listing()["findings"], [])
        # ...and the same row filed for real IS.
        self.real_row()
        self.assertEqual(len(findings_store.listing()["findings"]), 1)

    def test_it_is_not_counted_by_the_badge(self):
        self.shadow_row()
        self.assertEqual(findings_store.open_count(), 0)
        self.real_row()
        self.assertEqual(findings_store.open_count(), 1)

    def test_it_is_not_in_the_analysts_prompt_block(self):
        self.shadow_row()
        self.assertEqual(findings_store.prompt_block(), "")
        self.real_row()
        self.assertIn(ROW["text"], findings_store.prompt_block())

    def test_the_notify_router_is_never_handed_one(self):
        """`_announce_findings` is given `add_many`'s CREATED list, and a
        shadow row was never in it. Driven through the router's own
        `worth_sending` so the claim is about what would be sent rather
        than about a call nobody made."""
        row = self.shadow_row()
        # The row is `critical`, so it clears every floor the router has:
        # if it ever reached the router it would certainly be sent.
        self.assertTrue(notify_router.worth_sending([dict(row)], "info"))
        # And the created list the panel actually announces is empty.
        self.assertEqual(findings_store.add_many([]), [])
        self.assertEqual(findings_store.list_all(), [])

    def test_the_shared_volume_mirror_is_never_written(self):
        """The mirror is what the integration's sensor, its event watcher
        and `todo.brain` all read — one file, three surfaces, and none of
        them may see a trialled rule."""
        findings_store.STATE_FILE.parent.parent.mkdir(parents=True)
        self.shadow_row()
        self.assertFalse(findings_store.STATE_FILE.exists())
        # The same row filed for real writes it.
        self.real_row()
        self.assertTrue(findings_store.STATE_FILE.exists())

    def test_it_cannot_suppress_a_real_report_of_the_same_thing(self):
        """The whole reason this is a separate store rather than a status.
        `add_many` dedupes by normalised text across EVERY status and the
        settled ledger, so a shadow row sharing the file would silence the
        analyst about a problem on the say-so of a rule nobody has agreed
        to yet."""
        self.shadow_row()
        created = findings_store.add_many([ROW])
        self.assertEqual(len(created), 1, "the real report was suppressed")

    def test_a_real_ending_does_not_delete_the_shadow_row(self):
        """The other direction. Settling a real finding removes its row;
        the shadow copy is a measurement of what a trialled check said and
        stays until the check stops saying it."""
        real = self.real_row()
        self.shadow_row()
        findings_store.settle_and_clear(real["ts"], "ignored", note="no")
        self.assertEqual(len(shadow_findings.listing()), 1)


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

class TestTheShadowSet(unittest.TestCase):
    def test_every_id_in_it_is_a_real_check(self):
        """A typo here is a rule that files to neither store and is
        reported by nothing — which looks exactly like a rule that found
        nothing."""
        for check_id in checks.SHADOW:
            self.assertIn(check_id, checks.CHECK_IDS, check_id)

    def test_it_ships_empty(self):
        """Every check shipped so far has earned its place, and a set with
        something in it "for now" is how a trial becomes permanent."""
        self.assertEqual(set(checks.SHADOW), set())

    def test_run_all_splits_by_it(self):
        """Driven with a real id moved into the set, because the claim is
        about `run_all`'s behaviour and not about the set being empty."""
        import test_house_checks as fixture
        snap = fixture.house(automations=[{
            "id": "a1", "alias": "Broken",
            "triggers": [{"trigger": "time", "at": "07:00:00"}],
            "actions": [{"action": "light.turn_on",
                         "target": {"entity_id": "light.gone"}}]}])
        plain = checks.run_all(snap, fixture.NOW)
        self.assertTrue(plain["findings"])
        self.assertEqual(plain["shadow"], [])

        old = checks.SHADOW
        checks.SHADOW = frozenset({"auto.dead_ref"})
        try:
            split = checks.run_all(snap, fixture.NOW)
        finally:
            checks.SHADOW = old
        self.assertEqual(split["findings"], [])
        self.assertEqual(len(split["shadow"]), 1)
        self.assertEqual(split["shadow"][0]["source"], "check:auto.dead_ref")
        # It still RAN, and a check that ran may still clear its own rows.
        self.assertIn("auto.dead_ref", split["ran"])
        self.assertEqual(split["per_check"]["auto.dead_ref"], 1)


# ---------------------------------------------------------------------------
# The comparison
# ---------------------------------------------------------------------------

class TestTheAgreementCount(ShadowCase):
    def test_a_row_something_else_reported_counts_as_agreed(self):
        shadow_findings.add_many([ROW], NOW)
        findings_store.add_many([{**ROW, "source": "automations",
                                  "source_title": "Automations"}])
        got = shadow_findings.compare(shadow_findings.known_keys(), NOW)
        self.assertEqual(got["dev.example"]["rows"], 1)
        self.assertEqual(got["dev.example"]["agreed"], 1)

    def test_a_row_nothing_else_reported_does_not(self):
        shadow_findings.add_many([ROW], NOW)
        got = shadow_findings.compare(shadow_findings.known_keys(), NOW)
        self.assertEqual(got["dev.example"]["agreed"], 0)

    def test_an_answered_problem_still_counts_as_agreement(self):
        """Settling deletes the row, so reading the list alone would make a
        shadow check look worse the better the house is kept."""
        real = findings_store.add_many([{**ROW, "source": "automations"}])[0]
        findings_store.settle_and_clear(real["ts"], "fixed")
        shadow_findings.add_many([ROW], NOW)
        got = shadow_findings.compare(shadow_findings.known_keys(), NOW)
        self.assertEqual(got["dev.example"]["agreed"], 1)

    def test_days_ride_with_the_count(self):
        """Fourteen rows over one day is one evening; fourteen over nine
        days is a pattern, and a count with no window is read as
        whichever the reader expected."""
        for i in range(4):
            shadow_findings.add_many(
                [{**ROW, "text": f"Something is wrong ({i})"}],
                NOW - (8 - i) * DAY)
        got = shadow_findings.compare(set(), NOW)
        self.assertEqual(got["dev.example"]["rows"], 4)
        self.assertEqual(got["dev.example"]["days"], 9)

    def test_one_row_is_one_day_and_never_zero(self):
        shadow_findings.add_many([ROW], NOW)
        got = shadow_findings.compare(set(), NOW)
        self.assertEqual(got["dev.example"]["days"], 1)

    def test_the_same_thing_said_twice_is_one_row(self):
        shadow_findings.add_many([ROW], NOW)
        again = shadow_findings.add_many([ROW], NOW + 3600)
        self.assertEqual(again, [])
        self.assertEqual(len(shadow_findings.listing()), 1)

    def test_a_row_the_visible_store_already_holds_is_still_filed(self):
        """Deduping across stores would make every agreement invisible and
        the agreement count permanently zero — the one number the whole
        feature produces."""
        findings_store.add_many([{**ROW, "source": "automations"}])
        made = shadow_findings.add_many([ROW], NOW)
        self.assertEqual(len(made), 1)

    def test_diagnostics_names_a_trialled_check_that_found_nothing(self):
        """"This rule is being trialled and has found nothing" and "no rule
        is being trialled" are different answers, and only one of them is
        a rule that may be ready."""
        old = checks.SHADOW
        checks.SHADOW = frozenset({"auto.dead_ref"})
        try:
            got = shadow_findings.diagnostics(NOW)
        finally:
            checks.SHADOW = old
        self.assertEqual(got["checks"], ["auto.dead_ref"])
        self.assertEqual(got["by_check"]["auto.dead_ref"]["rows"], 0)


# ---------------------------------------------------------------------------
# The lifecycle
# ---------------------------------------------------------------------------

class TestClearingAndPruning(ShadowCase):
    def test_a_row_a_check_that_ran_no_longer_reports_is_cleared(self):
        shadow_findings.add_many([ROW], NOW)
        gone = shadow_findings.clear_resolved({"check:dev.example"}, set())
        self.assertEqual(len(gone), 1)
        self.assertEqual(shadow_findings.listing(), [])

    def test_a_check_that_did_not_run_clears_nothing(self):
        """"I could not look" and "it went away" are different claims and
        only the second may delete a row — the same rule the real store
        follows, from the same function."""
        shadow_findings.add_many([ROW], NOW)
        gone = shadow_findings.clear_resolved(set(), set())
        self.assertEqual(gone, [])
        self.assertEqual(len(shadow_findings.listing()), 1)

    def test_a_re_reported_row_survives_the_pass_that_re_reported_it(self):
        shadow_findings.add_many([ROW], NOW)
        gone = shadow_findings.clear_resolved(
            {"check:dev.example"},
            {findings_store.normalize(ROW["text"])})
        self.assertEqual(gone, [])
        self.assertEqual(len(shadow_findings.listing()), 1)

    def test_the_two_stores_clear_by_the_same_rule(self):
        """Not asserted by reading the source — both are driven with the
        same rows and the same arguments, and their answers compared. A
        trialled check with a different lifecycle from the one it is being
        compared against is two measurements, not one."""
        shadow_findings.add_many([ROW], NOW)
        findings_store.add_many([ROW])
        args = ({"check:dev.example"}, set())
        theirs = findings_store.clear_resolved(*args)
        mine = shadow_findings.clear_resolved(*args)
        self.assertEqual(len(theirs), len(mine))
        self.assertEqual(theirs[0]["text"], mine[0]["text"])

    def test_rows_past_the_window_are_pruned(self):
        shadow_findings.add_many([{**ROW, "text": "Old"}],
                                 NOW - 40 * DAY)
        shadow_findings.add_many([{**ROW, "text": "Recent"}], NOW - DAY)
        self.assertEqual(shadow_findings.prune(NOW), 1)
        self.assertEqual([f["text"] for f in shadow_findings.listing()],
                         ["Recent"])

    def test_the_window_outlasts_the_fortnight_it_is_read_over(self):
        """The design page's comparison window is two weeks; keeping
        exactly two weeks means the fortnight is half gone by the time
        anybody reads it."""
        self.assertGreaterEqual(shadow_findings.KEEP_DAYS, 28)


class TestThePassFilesBothStores(ShadowCase):
    """Through `server.run_checks`'s own `apply`, because the split being
    right in `run_all` and forgotten in the panel is the failure that
    would put a trialled rule on somebody's tab."""

    def setUp(self):
        super().setUp()
        self.server = importlib.import_module("server")
        import test_house_checks as fixture
        self.fixture = fixture
        snap = fixture.house(automations=[{
            "id": "a1", "alias": "Broken",
            "triggers": [{"trigger": "time", "at": "07:00:00"}],
            "actions": [{"action": "light.turn_on",
                         "target": {"entity_id": "light.gone"}}]}])

        async def collect(_started=None):
            return snap

        async def nothing(*a, **kw):
            return 0

        self._patched = {}
        for name, value in (
                ("_record_overrides", lambda *a: None),
                ("_record_rhythm", lambda *a: None),
                ("_record_routines", lambda *a: None),
                ("_announce_findings", nothing),
                ("_offer_routines", nothing),
                ("_offer_playbooks", nothing),
                ("_offer_conditions", nothing),
                ("_offer_scene_schedule", nothing),
                ("_evaluate_trials", nothing),
                ("_poll_intents", nothing),
                ("publish_diagnostics", lambda: None)):
            self._patched[name] = getattr(self.server, name)
            setattr(self.server, name, value)
        self._collect = checks.snapshot.collect
        checks.snapshot.collect = collect
        self._shadow = checks.SHADOW

    def tearDown(self):
        for name, value in self._patched.items():
            setattr(self.server, name, value)
        checks.snapshot.collect = self._collect
        checks.SHADOW = self._shadow
        self.server.CHECKS_STATE["last"] = None
        super().tearDown()

    def test_a_trialled_check_files_to_the_shadow_store_and_not_the_tab(self):
        """Driven through the real pass, because the split being right in
        `run_all` and forgotten in the panel is exactly the failure that
        would put a trialled rule on somebody's Findings tab."""
        import asyncio
        checks.SHADOW = frozenset({"auto.dead_ref"})
        summary = asyncio.run(self.server.run_checks("test"))
        self.assertEqual(summary.get("error"), None, summary)
        self.assertEqual(summary["shadow"]["created"], 1)
        rows = shadow_findings.listing()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source"], "check:auto.dead_ref")
        # And nothing about it reached the tab.
        self.assertEqual(
            [f for f in findings_store.list_all()
             if f["source"] == "check:auto.dead_ref"], [])

    def test_the_same_check_out_of_shadow_files_to_the_tab_instead(self):
        """The mutation, run as a test: with the id out of the set the row
        goes where every other check's rows go."""
        import asyncio
        checks.SHADOW = frozenset()
        summary = asyncio.run(self.server.run_checks("test"))
        self.assertEqual(summary["shadow"]["created"], 0)
        self.assertEqual(shadow_findings.listing(), [])
        self.assertEqual(
            len([f for f in findings_store.list_all()
                 if f["source"] == "check:auto.dead_ref"]), 1)

    def test_diagnostics_carries_the_numbers(self):
        server = importlib.import_module("server")
        payload = server._diagnostics_payload()
        self.assertIn("shadow_checks", payload)
        self.assertIn("by_check", payload["shadow_checks"])


if __name__ == "__main__":
    unittest.main()
