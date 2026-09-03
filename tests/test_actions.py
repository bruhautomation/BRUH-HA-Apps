#!/usr/bin/env python3
"""Tests for the action miner — who or what changed something.

Three things here are worth more than the rest.

The **writer and the reader are different processes**: the MCP server
appends to the action ledger as the `claude` user and the panel reads it
as root, and neither can import the other. So the real writer is driven
into the real reader rather than the shape being written down twice —
the same reasoning that put `saved_at` back to an epoch int.

The **proximate/root split** is asserted from both sides. An automation a
person started by hand is reported as the automation and remembers the
person; reporting either one alone is a different bug and both are easy
to write.

The **override rule** is asserted against the cases it must NOT fire on,
because "you keep undoing this automation" is a finding about somebody's
house and a false one is worse than none.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
MCP_DIR = BASE_DIR / "brain" / "ha-mcp-server"
sys.path.insert(0, str(PANEL_DIR))

import actions  # noqa: E402

NOW = 1_700_000_000.0


def entry(**over) -> dict:
    """One logbook entry as Home Assistant's REST endpoint formats it."""
    row = {
        "when": "2023-11-14T22:13:20+00:00",
        "entity_id": "light.kitchen",
        "name": "Kitchen",
        "state": "on",
    }
    row.update(over)
    return row


def act(ts, entity_id, state, cause, by="", by_name="") -> dict:
    return {"ts": ts, "entity_id": entity_id, "name": entity_id, "state": state,
            "cause": cause, "by": by, "by_name": by_name,
            "root_user": "", "root_user_name": ""}


class TestWhenComesInTwoShapes(unittest.TestCase):
    """The REST endpoint formats `when` as an ISO string and the WebSocket
    event stream as a float, out of the same processor. A reader that
    handles one works until somebody points it at the other transport."""

    def test_an_iso_string_parses(self):
        self.assertEqual(actions.parse_when("2023-11-14T22:13:20+00:00"), NOW)

    def test_a_float_parses(self):
        self.assertEqual(actions.parse_when(NOW), NOW)
        self.assertEqual(actions.parse_when(int(NOW)), float(NOW))

    def test_a_naive_stamp_is_read_as_utc_rather_than_refused(self):
        self.assertEqual(actions.parse_when("2023-11-14T22:13:20"), NOW)

    def test_nonsense_is_none_rather_than_now(self):
        for value in ("", None, "yesterday", True, {}):
            self.assertIsNone(actions.parse_when(value), value)


class TestWhoDidIt(unittest.TestCase):
    def test_an_automation_is_named(self):
        got = actions.classify(entry(
            context_entity_id="automation.evening",
            context_entity_id_name="Evening lights"))
        self.assertEqual(got["cause"], "automation")
        self.assertEqual(got["by"], "automation.evening")
        self.assertEqual(got["by_name"], "Evening lights")

    def test_an_automation_a_person_started_reports_both_halves(self):
        got = actions.classify(
            entry(context_entity_id="automation.evening",
                  context_entity_id_name="Evening lights",
                  context_user_id="u1"),
            users={"u1": "Ben"})
        # The automation changed the light; the person is why it ran.
        self.assertEqual(got["cause"], "automation")
        self.assertEqual(got["root_user_name"], "Ben")

    def test_a_person_with_no_automation_above_them_is_the_cause(self):
        got = actions.classify(entry(context_user_id="u1"), users={"u1": "Ben"})
        self.assertEqual(got["cause"], "person")
        self.assertEqual(got["by_name"], "Ben")

    def test_an_unnamed_person_is_still_a_person(self):
        """`config/auth/list` is an admin command and may not answer. That
        costs the timeline the name, never the attribution."""
        got = actions.classify(entry(context_user_id="u1"), users={})
        self.assertEqual(got["cause"], "person")
        self.assertTrue(got["by_name"])

    def test_a_conversation_agent_is_voice(self):
        got = actions.classify(entry(context_domain="conversation",
                                     context_name="Assist"))
        self.assertEqual(got["cause"], "voice")

    def test_a_service_call_domain_is_not_mistaken_for_a_runner(self):
        """`context_domain` is "light" for a plain `light.turn_on`. Reading
        it as the thing that ran would file every service call under a
        cause that does not exist."""
        got = actions.classify(entry(context_domain="light",
                                     context_service="turn_on"))
        self.assertEqual(got["cause"], "unattributed")

    def test_an_entity_that_is_its_own_context_is_not_its_own_cause(self):
        got = actions.classify(entry(entity_id="automation.evening",
                                     context_entity_id="automation.evening"))
        self.assertEqual(got["cause"], "unattributed")

    def test_a_change_with_no_context_says_so_rather_than_guessing(self):
        """A wall switch and a device's own integration arrive identically.
        Naming either is a guess, and a timeline that guesses is not
        evidence."""
        got = actions.classify(entry())
        self.assertEqual(got["cause"], "unattributed")
        self.assertEqual(got["by_name"], "")


class TestBrainKnowsWhatBrainDid(unittest.TestCase):
    """brAIn calls Core with the Supervisor's token like every other add-on,
    so nothing in a context chain identifies it. The only honest answer is
    the ledger the MCP server writes."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "actions.jsonl")

    def write(self, rows):
        with open(self.path, "w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row) + "\n")

    def test_a_change_just_after_a_brain_call_is_brains(self):
        self.write([{"ts": NOW, "domain": "light", "service": "turn_on",
                     "entities": ["light.kitchen"]}])
        index = actions._ledger_index(actions.read_ledger(0, self.path))
        got = actions.classify(entry(when=NOW + 2), brain_index=index)
        self.assertEqual(got["cause"], "brain")

    def test_a_change_long_after_is_not(self):
        self.write([{"ts": NOW, "domain": "light", "service": "turn_on",
                     "entities": ["light.kitchen"]}])
        index = actions._ledger_index(actions.read_ledger(0, self.path))
        got = actions.classify(
            entry(when=NOW + actions.BRAIN_MATCH_S + 30), brain_index=index)
        self.assertEqual(got["cause"], "unattributed")

    def test_a_change_before_the_call_is_not(self):
        self.write([{"ts": NOW, "domain": "light", "service": "turn_on",
                     "entities": ["light.kitchen"]}])
        index = actions._ledger_index(actions.read_ledger(0, self.path))
        got = actions.classify(entry(when=NOW - 5), brain_index=index)
        self.assertEqual(got["cause"], "unattributed")

    def test_brain_beats_an_automation_on_the_same_entity(self):
        """brAIn calling a service is a fact; the context chain around it is
        whatever Core happened to record. The fact wins."""
        self.write([{"ts": NOW, "domain": "light", "service": "turn_on",
                     "entities": ["light.kitchen"]}])
        index = actions._ledger_index(actions.read_ledger(0, self.path))
        got = actions.classify(
            entry(when=NOW + 1, context_entity_id="automation.evening"),
            brain_index=index)
        self.assertEqual(got["cause"], "brain")

    def test_a_missing_ledger_is_an_empty_one_not_an_error(self):
        self.assertEqual(actions.read_ledger(0, self.path + ".nope"), [])

    def test_a_half_written_line_is_skipped_and_the_rest_survive(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(json.dumps({"ts": NOW, "entities": ["light.a"]}) + "\n")
            fh.write('{"ts": 1, "entit\n')
            fh.write(json.dumps({"ts": NOW, "entities": ["light.b"]}) + "\n")
        rows = actions.read_ledger(0, self.path)
        self.assertEqual(len(rows), 2)

    def test_the_real_writer_lands_in_the_real_reader(self):
        """The two halves are in different processes and cannot import each
        other, so the contract is driven rather than described."""
        saved = dict(sys.modules)
        sys.path.insert(0, str(MCP_DIR))
        os.environ["BRAIN_ACTION_LEDGER"] = self.path
        try:
            for name in list(sys.modules):
                if name == "ha_mcp_server":
                    del sys.modules[name]
            import ha_mcp_server  # noqa: PLC0415
            ha_mcp_server.ACTION_LEDGER = self.path
            ha_mcp_server.record_action("light", "turn_on",
                                        {"entity_id": "light.kitchen"})
            ha_mcp_server.record_action(
                "climate", "set_temperature",
                {"target": {"entity_id": ["climate.hall"], "area_id": "hall"}})
        finally:
            sys.path.remove(str(MCP_DIR))
            os.environ.pop("BRAIN_ACTION_LEDGER", None)
            sys.modules.clear()
            sys.modules.update(saved)

        rows = actions.read_ledger(0, self.path)
        self.assertEqual(len(rows), 2)
        index = actions._ledger_index(rows)
        self.assertIn("light.kitchen", index)
        self.assertIn("climate.hall", index)
        # An area target is recorded and deliberately not resolved: a wrong
        # expansion would attribute somebody else's change to brAIn.
        self.assertEqual(rows[1]["target"], {"area_id": "hall"})


class TestMining(unittest.TestCase):
    def test_entries_without_an_entity_are_dropped(self):
        """A logbook line about an automation triggering is the CAUSE of the
        rows around it. Keeping it too reports every run twice."""
        mined = actions.mine([
            entry(),
            {"when": NOW, "name": "Evening lights", "message": "triggered"},
        ])
        self.assertEqual(len(mined["actions"]), 1)

    def test_rows_come_back_oldest_first_whatever_order_they_arrived(self):
        mined = actions.mine([entry(when=NOW + 10), entry(when=NOW)])
        self.assertEqual([a["ts"] for a in mined["actions"]], [NOW, NOW + 10])

    def test_the_cap_is_reported_rather_than_applied_quietly(self):
        mined = actions.mine([entry() for _ in range(10)], cap=4)
        self.assertTrue(mined["capped"])
        self.assertEqual(len(mined["actions"]), 4)

    def test_counts_carry_every_cause_including_the_empty_ones(self):
        mined = actions.mine([entry()])
        self.assertEqual(set(mined["counts"]), set(actions.CAUSES))


class TestOverrides(unittest.TestCase):
    def test_a_person_undoing_an_automation_is_an_override(self):
        found = actions.find_overrides([
            act(NOW, "light.k", "on", "automation", "automation.evening", "Evening"),
            act(NOW + 60, "light.k", "off", "person", "u1", "Ben"),
        ])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["by"], "automation.evening")
        self.assertEqual(found[0]["to_state"], "off")

    def test_agreeing_with_an_automation_is_not_a_fight(self):
        """A person pressing on after a rule turned it on is agreement.
        Counting it would put the best-behaved automation in the house at
        the top of the list."""
        self.assertEqual(actions.find_overrides([
            act(NOW, "light.k", "on", "automation", "automation.evening", "Evening"),
            act(NOW + 60, "light.k", "on", "person", "u1", "Ben"),
        ]), [])

    def test_an_unrelated_decision_hours_later_is_not_an_override(self):
        self.assertEqual(actions.find_overrides([
            act(NOW, "light.k", "on", "automation", "automation.evening", "Evening"),
            act(NOW + 4 * 3600, "light.k", "off", "person", "u1", "Ben"),
        ]), [])

    def test_a_different_entity_is_not_an_override(self):
        self.assertEqual(actions.find_overrides([
            act(NOW, "light.k", "on", "automation", "automation.evening", "Evening"),
            act(NOW + 60, "light.hall", "off", "person", "u1", "Ben"),
        ]), [])

    def test_one_automation_move_is_undone_once(self):
        """Somebody nudging a dimmer three times is one disagreement, not
        three."""
        found = actions.find_overrides([
            act(NOW, "light.k", "on", "automation", "automation.evening", "Evening"),
            act(NOW + 30, "light.k", "off", "person", "u1", "Ben"),
            act(NOW + 60, "light.k", "on", "person", "u1", "Ben"),
            act(NOW + 90, "light.k", "off", "person", "u1", "Ben"),
        ])
        self.assertEqual(len(found), 1)

    def test_brain_is_something_that_can_be_overridden_too(self):
        found = actions.find_overrides([
            act(NOW, "light.k", "on", "brain", "", "brAIn"),
            act(NOW + 60, "light.k", "off", "person", "u1", "Ben"),
        ])
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["by_cause"], "brain")

    def test_an_automation_undoing_an_automation_is_not_an_override(self):
        """Two rules disagreeing is a conflict, and a different finding. This
        one is about a PERSON disagreeing with their house."""
        self.assertEqual(actions.find_overrides([
            act(NOW, "light.k", "on", "automation", "automation.a", "A"),
            act(NOW + 60, "light.k", "off", "automation", "automation.b", "B"),
        ]), [])

    def test_grouping_gathers_them_under_what_was_undone(self):
        groups = actions.group_overrides(actions.find_overrides([
            act(NOW, "light.k", "on", "automation", "automation.evening", "Evening"),
            act(NOW + 60, "light.k", "off", "person", "u1", "Ben"),
            act(NOW + 3600, "light.hall", "on", "automation",
                "automation.evening", "Evening"),
            act(NOW + 3660, "light.hall", "off", "person", "u1", "Ben"),
        ]))
        self.assertEqual(groups["automation.evening"]["count"], 2)
        self.assertEqual(sorted(groups["automation.evening"]["entities"]),
                         ["light.hall", "light.k"])


class TestExplain(unittest.TestCase):
    def test_one_entitys_changes_come_back_newest_first(self):
        rows = actions.explain([
            act(NOW, "light.k", "on", "automation", "automation.a", "A"),
            act(NOW + 60, "light.k", "off", "person", "u1", "Ben"),
            act(NOW + 30, "light.hall", "on", "person", "u1", "Ben"),
        ], "light.k")
        self.assertEqual([r["state"] for r in rows], ["off", "on"])

    def test_an_entity_nothing_touched_answers_empty_rather_than_wrong(self):
        self.assertEqual(actions.explain([
            act(NOW, "light.k", "on", "automation", "automation.a", "A"),
        ], "light.nothing"), [])


class TestTheOverriddenCheck(unittest.TestCase):
    """The check reads the miner's overrides rather than recomputing them —
    there must not be a second copy of the window, the "state has to
    differ" rule, or the one-undo-per-move rule."""

    def setUp(self):
        sys.path.insert(0, str(PANEL_DIR))
        from checks import automations as auto  # noqa: PLC0415
        self.auto = auto

    def snap(self, overrides):
        return {"actions": {"available": True, "overrides": overrides}}

    def override(self, entity="light.k", by="automation.evening"):
        return {"ts": NOW, "entity_id": entity, "name": entity,
                "from_state": "on", "to_state": "off", "by": by,
                "by_name": "Evening lights", "by_cause": "automation",
                "person": "Ben", "after_s": 60}

    def test_silent_below_the_floor(self):
        """Once is a one-off and twice is a coincidence. A check that fires
        on a healthy house is the one people learn to ignore first."""
        for n in range(self.auto.OVERRIDE_MIN):
            snap = self.snap([self.override() for _ in range(n)])
            self.assertEqual(self.auto.overridden(snap, NOW), [], f"{n} overrides")

    def test_it_speaks_at_the_floor_and_names_the_automation(self):
        snap = self.snap([self.override() for _ in range(self.auto.OVERRIDE_MIN)])
        found = self.auto.overridden(snap, NOW)
        self.assertEqual(len(found), 1)
        self.assertIn("Evening lights", found[0]["text"])
        self.assertEqual(found[0]["entity_id"], "automation.evening")
        # The count changes between runs and the store dedupes by text, so
        # the number lives in the detail.
        self.assertNotIn(str(self.auto.OVERRIDE_MIN), found[0]["text"])
        self.assertIn(str(self.auto.OVERRIDE_MIN), found[0]["detail"])

    def test_overriding_brain_is_not_an_automation_finding(self):
        """brAIn's own actions are a different conversation, and one this
        check is not equipped to have."""
        rows = [dict(self.override(), by="", by_name="brAIn", by_cause="brain")
                for _ in range(self.auto.OVERRIDE_MIN + 2)]
        self.assertEqual(self.auto.overridden(self.snap(rows), NOW), [])

    def test_two_automations_are_two_findings(self):
        rows = ([self.override(by="automation.a")
                 for _ in range(self.auto.OVERRIDE_MIN)]
                + [self.override(by="automation.b")
                   for _ in range(self.auto.OVERRIDE_MIN)])
        self.assertEqual(len(self.auto.overridden(self.snap(rows), NOW)), 2)

    def test_a_window_that_could_not_be_read_files_nothing(self):
        self.assertEqual(self.auto.overridden({}, NOW), [])


class TestAnEntityIdReachesAUrl(unittest.TestCase):
    """The one piece of user input on this path, and it ends up in the
    query of a request the panel makes to Core.

    So it is validated at the edge (the route refuses a 400), validated
    again at the last line before the request leaves, and quoted on the
    way out. A barrier only at the edge is a barrier the next caller
    forgets, and quoting alone would stop the `&` while letting
    everything else through.
    """

    def test_a_real_entity_id_passes(self):
        for eid in ("light.kitchen", "binary_sensor.back_door_2",
                    "sensor.a", "input_boolean.x_1"):
            self.assertTrue(actions.is_entity_id(eid), eid)

    def test_anything_that_could_steer_a_url_is_refused(self):
        for bad in ("light.kitchen&entity=other", "light.kitchen#x",
                    "../../states", "light.kitchen?end_time=0",
                    "http://elsewhere/x", "light kitchen", "light.KITCHEN",
                    "light.", ".kitchen", "kitchen", "", None,
                    "light.kitchen\nX-Injected: 1"):
            self.assertFalse(actions.is_entity_id(bad), repr(bad))

    def test_the_fetch_refuses_before_it_asks_rather_than_asking_carefully(self):
        """Driven, not read: the request must not be made at all."""
        import asyncio  # noqa: PLC0415

        asked = []

        class Boom:
            pass

        async def fake_rest_get(session, path, timeout=30, params=None):
            asked.append((path, params))
            return []

        import ha_data  # noqa: PLC0415
        original = ha_data._rest_get
        ha_data._rest_get = fake_rest_get
        try:
            got = asyncio.run(actions.fetch_logbook(
                Boom(), 0, 100, "light.kitchen&entity=lock.front_door"))
            self.assertIsNone(got)
            self.assertEqual(asked, [])
            asyncio.run(actions.fetch_logbook(Boom(), 0, 100, "light.kitchen"))
            self.assertEqual(len(asked), 1)
            path, params = asked[0]
            # The id is a PARAMETER, not part of a path this file built. The
            # client encodes it, so a value holding an `&` stays a value.
            self.assertNotIn("entity", path)
            self.assertEqual(params["entity"], "light.kitchen")
        finally:
            ha_data._rest_get = original

    def test_nothing_builds_the_logbook_query_by_hand(self):
        """The guard is the API contract; `params` is the safety property.
        A future edit that goes back to concatenating a query would pass
        every other test in this class."""
        source = (PANEL_DIR / "actions.py").read_text()
        body = source.split("async def fetch_logbook", 1)[1].split("\nasync def", 1)[0]
        for banned in ("&entity=", "?end_time=", "path +="):
            self.assertNotIn(banned, body,
                             f"{banned!r} is a query built by hand again")

    def test_the_refusal_does_not_put_the_refused_value_in_a_log(self):
        """A log line is read by somebody else later, and the one string
        this function has just refused is the last thing that should be
        able to write into one. The caller is told what it sent; the log
        records that it happened."""
        source = (PANEL_DIR / "actions.py").read_text()
        body = source.split("async def fetch_logbook", 1)[1].split("\nasync def", 1)[0]
        refusal = body.split("if not is_entity_id", 1)[1].split("return None", 1)[0]
        self.assertIn("len(entity_id)", refusal)
        self.assertNotIn("entity_id[", refusal)

    def test_the_route_and_the_tool_hold_the_same_shape(self):
        """Three layers, one rule. A second spelling of it is a second
        answer, and the loosest one is the one that decides."""
        server = (PANEL_DIR / "server.py").read_text()
        self.assertIn("actions.is_entity_id(entity_id)", server)
        mcp = (MCP_DIR / "ha_mcp_server.py").read_text()
        self.assertIn(actions.ENTITY_RE.pattern, mcp)


class TestTheCauseVocabularyIsClosed(unittest.TestCase):
    def test_every_cause_a_classifier_can_emit_is_in_the_list(self):
        """Every reader switches on this vocabulary — the check, the tab's
        filter, the MCP tool. A cause outside it is a bug, not a new kind
        of cause."""
        cases = [
            entry(),
            entry(context_user_id="u1"),
            entry(context_entity_id="automation.a"),
            entry(context_entity_id="script.a"),
            entry(context_entity_id="scene.a"),
            entry(context_domain="conversation"),
        ]
        for case in cases:
            self.assertIn(actions.classify(case)["cause"], actions.CAUSES, case)

    def test_the_panel_and_the_ui_agree_about_the_words(self):
        """The tab renders a label per cause. A cause with no label renders
        as its own identifier, which is how `unattributed` would reach
        somebody's screen."""
        app_js = (PANEL_DIR / "app.js").read_text()
        block = app_js.split("const CAUSE_WORDS = {", 1)[1].split("};", 1)[0]
        for cause in actions.CAUSES:
            self.assertIn(f"{cause}:", block, f"{cause} has no label in app.js")


if __name__ == "__main__":
    unittest.main()
