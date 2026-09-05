"""A sentence that happens once, and then is not there any more.

Claude is stubbed throughout: the model writing an automation is the part
this cannot test and the part that is not under test. What IS under test
is everything around it — the parser, the two additions code makes and the
model is told not to, the refusals, the armed store's lifecycle, and the
fact that the two front doors write one wire format.

Each test names the mutation it catches:

  the disarm action        drop it -> a "one-off" that keeps running, and a
                           card saying it fired above an automation that
                           will fire again tomorrow
  `mode: single`           let the model choose -> a one-off that can run
                           twice at once is not one
  the replayable check     trust the model -> a card with no number on it
                           and nothing to check a never-fired trigger with
  `once: false`            arm it anyway -> a standing rule written as a
                           thing that happens once and then disarms
  no entity                arm it anyway -> an automation that does nothing,
                           indistinguishable from one that has not fired
  a protected target       arm it anyway -> a card offering something the
                           writer refuses, which is a wasted no
  `last_triggered`         read "the automation is off" instead -> somebody
                           switching it off by hand reads as it having fired
  the accept stamp         drop the `> accepted_at` test -> an automation
                           sharing a slug with one that fired last month
                           reads as done the moment it is armed
  the TTL is a label       delete on expiry -> a file that changed while
                           nobody was looking
  one wire format          write the shape down twice -> the two sides drift
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

# --- just enough Home Assistant for the integration's writer ---------------
if "homeassistant" not in sys.modules:
    sys.modules["homeassistant"] = types.ModuleType("homeassistant")
if "homeassistant.core" not in sys.modules:
    _core = types.ModuleType("homeassistant.core")
    _core.HomeAssistant = type("HomeAssistant", (), {})
    sys.modules["homeassistant.core"] = _core

_pkg = types.ModuleType("brain_cc")
_pkg.__path__ = [str(INTEGRATION_DIR)]
sys.modules.setdefault("brain_cc", _pkg)
brain_requests = importlib.import_module("brain_cc.requests")


class _Config:
    def __init__(self, base: str):
        self._base = base

    def path(self, *parts: str) -> str:
        return os.path.join(self._base, *parts)


class _Hass:
    def __init__(self, base: str):
        self.config = _Config(base)


ANSWER = {
    "once": True,
    "plain": "Turn the porch light off ten minutes after the front door shuts.",
    "trigger": [{"platform": "state", "entity_id": "binary_sensor.front_door",
                 "to": "off", "for": {"minutes": 10}}],
    "action": [{"service": "light.turn_off",
                "target": {"entity_id": "light.porch"}}],
}
SENTENCE = "when the guests leave, turn the porch light off"


class IntentCase(unittest.TestCase):
    """Its own request drop and its own store, both real files."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self._env = dict(os.environ)
        os.environ["BRAIN_INTENT_REQUESTS_DIR"] = str(root / "requests")
        os.environ["BRAIN_INTENTS_FILE"] = str(root / "intents.json")
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        self.addCleanup(self._restore)
        for name in ("intents", "automation_writer"):
            sys.modules.pop(name, None)
        self.intents = importlib.import_module("intents")

    def _restore(self):
        os.environ.clear()
        os.environ.update(self._env)
        for name in ("intents", "automation_writer"):
            sys.modules.pop(name, None)

    def build(self, answer=None, ts=1_700_000_000_000, patterns=None,
              sentence=SENTENCE):
        return self.intents.build(sentence, answer or dict(ANSWER), ts,
                                  patterns)


# ---------------------------------------------------------------------------
# The wire format, from both ends
# ---------------------------------------------------------------------------

class TestOneWireFormatTwoFrontDoors(IntentCase):
    """The panel's writer and the integration's write the same file, and the
    panel's parser reads both. Neither process can import the other, so the
    only way to know they agree is to drive one into the other."""

    def test_the_panel_s_own_request_round_trips(self):
        self.intents.request("when the dryer finishes, tell me", "panel")
        queued = self.intents.collect()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["sentence"], "when the dryer finishes, tell me")
        self.assertEqual(queued[0]["via"], "panel")

    def test_the_integration_s_request_is_read_by_the_add_on_s_parser(self):
        hass = _Hass(self.tmp.name)
        # Point the add-on at the directory Home Assistant's side writes to,
        # which is the one thing the two have to agree about beyond the body.
        os.environ["BRAIN_INTENT_REQUESTS_DIR"] = \
            brain_requests.intent_requests_dir(hass)
        sys.modules.pop("intents", None)
        addon = importlib.import_module("intents")

        self.assertTrue(brain_requests.write_intent(hass, SENTENCE, "service"))
        queued = addon.collect()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["sentence"], SENTENCE)
        self.assertEqual(queued[0]["via"], "service")

    def test_an_empty_sentence_is_written_by_neither(self):
        hass = _Hass(self.tmp.name)
        self.assertFalse(brain_requests.write_intent(hass, "   "))
        self.assertEqual(self.intents.request("  "), "")

    def test_the_drain_removes_what_it_read(self):
        self.intents.request(SENTENCE)
        self.intents.collect()
        self.assertEqual(self.intents.collect(), [])
        self.assertEqual(self.intents.pending(), 0)

    def test_a_request_that_is_not_one_is_dropped_rather_than_raising(self):
        self.intents.request(SENTENCE)
        for path in Path(os.environ["BRAIN_INTENT_REQUESTS_DIR"]).glob("*.json"):
            path.write_text("{oh no", encoding="utf-8")
        self.assertEqual(self.intents.collect(), [])

    def test_every_field_is_checked_because_it_is_another_process_s(self):
        self.assertIsNone(self.intents.parse_request({"sentence": "x"}))
        self.assertIsNone(self.intents.parse_request({"ts": 1, "sentence": ""}))
        self.assertIsNone(self.intents.parse_request({"ts": True,
                                                      "sentence": "x"}))
        self.assertIsNone(self.intents.parse_request("nope"))
        req = self.intents.parse_request({"ts": 1, "sentence": "x" * 900})
        self.assertEqual(len(req["sentence"]), self.intents.MAX_SENTENCE)

    def test_the_queue_is_bounded(self):
        for i in range(self.intents.MAX_PER_PASS + 3):
            self.intents.request(f"when thing {i} happens, do something")
        self.assertEqual(len(self.intents.collect()),
                         self.intents.MAX_PER_PASS)


# ---------------------------------------------------------------------------
# Reading what Claude said
# ---------------------------------------------------------------------------

class TestParsingTheAnswer(IntentCase):

    def test_a_bare_object(self):
        self.assertEqual(self.intents.parse_answer('{"once": true}'),
                         {"once": True})

    def test_a_fenced_block_is_tolerated(self):
        text = 'Here you go:\n```json\n{"once": false}\n```'
        self.assertEqual(self.intents.parse_answer(text), {"once": False})

    def test_prose_around_an_object(self):
        self.assertEqual(
            self.intents.parse_answer('Sure. {"once": true} Hope that helps.'),
            {"once": True})

    def test_nothing_usable_is_None_rather_than_a_guess(self):
        self.assertIsNone(self.intents.parse_answer("I could not do that."))
        self.assertIsNone(self.intents.parse_answer(""))
        self.assertIsNone(self.intents.parse_answer("[1, 2]"))


# ---------------------------------------------------------------------------
# What code adds, and the model is told not to
# ---------------------------------------------------------------------------

class TestTheTwoAdditions(IntentCase):

    def test_the_last_action_switches_the_automation_off(self):
        """The whole difference between a one-off and a rule somebody has to
        remember to delete."""
        row = self.build()
        self.assertNotIn("refused", row)
        last = row["config"]["action"][-1]
        self.assertEqual(last["service"], "automation.turn_off")
        self.assertEqual(last["target"]["entity_id"], row["entity_id"])
        self.assertEqual(len(row["config"]["action"]), 2)

    def test_it_disarms_the_entity_the_writer_will_actually_create(self):
        """The alias becomes the object id, so the two have to be derived the
        same way — one implementation, `automation_writer.slugify`."""
        import automation_writer

        row = self.build()
        self.assertEqual(
            row["entity_id"],
            f"automation.{automation_writer.slugify(row['title'])}")

    def test_the_mode_is_single_and_is_not_the_model_s_to_choose(self):
        row = self.build(dict(ANSWER, mode="queued"))
        self.assertEqual(row["config"]["mode"], "single")

    def test_the_id_says_what_it_is_and_carries_the_writer_s_prefix(self):
        import automation_writer

        row = self.build(ts=1_700_000_000_123)
        self.assertEqual(row["config"]["id"], "brain_intent_1700000000123")
        self.assertTrue(row["config"]["id"].startswith(
            automation_writer.ID_PREFIX))

    def test_the_card_carries_the_sentence_and_the_restatement_apart(self):
        row = self.build()
        self.assertEqual(row["kind"], "intent")
        self.assertEqual(row["source"], "intent")
        self.assertEqual(row["sentence"], SENTENCE)
        self.assertEqual(row["plain"], ANSWER["plain"])
        self.assertEqual(row["intent"]["sentence"], SENTENCE)
        self.assertIn(SENTENCE, row["why"])
        self.assertIn(ANSWER["plain"], row["why"])

    def test_the_condition_key_is_present_even_when_empty(self):
        row = self.build()
        self.assertEqual(row["config"]["condition"], [])

    def test_both_spellings_of_the_trigger_key_are_read(self):
        answer = {"once": True, "plain": "x",
                  "triggers": ANSWER["trigger"], "actions": ANSWER["action"]}
        self.assertNotIn("refused", self.build(answer))


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------

class TestTheRefusals(IntentCase):
    """Every one carries the sentence and none of them is silent: somebody
    typed something and is waiting for an answer."""

    def refused(self, answer=None, **kw) -> str:
        row = self.build(answer, **kw)
        self.assertIn("refused", row, row)
        self.assertNotIn("config", row)
        self.assertEqual(row["sentence"], kw.get("sentence", SENTENCE))
        return row["refused"]

    def test_a_standing_rule_is_refused_with_the_restatement_shown(self):
        answer = {"once": False,
                  "plain": "Turn the porch light on at sunset every evening."}
        row = self.build(answer)
        self.assertIn("standing rule", row["refused"])
        self.assertIn("ordinary change", row["refused"])
        # The restatement is what lets somebody correct the sentence rather
        # than wonder which half brAIn misread.
        self.assertEqual(row["plain"], answer["plain"])

    def test_a_trigger_outside_the_replayable_set_is_refused_by_name(self):
        answer = dict(ANSWER, trigger=[{"platform": "webhook",
                                        "webhook_id": "abc"}])
        self.assertIn("webhook", self.refused(answer))

    def test_a_device_trigger_is_refused(self):
        answer = dict(ANSWER, trigger=[{"platform": "device",
                                        "device_id": "abc"}])
        self.assertIn("device", self.refused(answer))

    def test_a_sentence_with_nothing_behind_it_is_refused(self):
        answer = dict(ANSWER, error="no entity called 'the guests'")
        self.assertIn("guests", self.refused(answer))

    def test_an_action_that_names_nothing_is_refused(self):
        """An automation that does nothing is indistinguishable from one that
        has not fired yet, which is the one state this card cannot have."""
        answer = dict(ANSWER, action=[{"service": "homeassistant.update_entity"}])
        self.assertIn("did not name anything", self.refused(answer))

    def test_brAIns_own_disarm_action_is_not_evidence_of_a_target(self):
        """The mutation: count `automation.turn_off` as the entity the
        sentence named, and every empty automation passes."""
        answer = dict(ANSWER, action=[{
            "service": "automation.turn_off",
            "target": {"entity_id": "automation.something"}}])
        self.assertIn("did not name anything", self.refused(answer))

    def test_a_protected_target_is_refused(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.porch"
        self.assertIn("protected", self.refused(patterns=["light.porch"]))

    def test_an_area_target_is_refused_while_the_list_is_set(self):
        answer = dict(ANSWER, action=[{"service": "light.turn_off",
                                       "target": {"area_id": "porch"}}])
        self.assertIn("area", self.refused(answer, patterns=["lock.front"]))

    def test_an_answer_with_no_trigger_or_no_action_is_refused(self):
        self.assertIn("no trigger", self.refused(
            {"once": True, "plain": "x", "action": ANSWER["action"]}))
        self.assertIn("no action", self.refused(
            {"once": True, "plain": "x", "trigger": ANSWER["trigger"]}))

    def test_build_never_raises_and_never_returns_None(self):
        for answer in ({}, {"once": True}, {"trigger": "nonsense"},
                       {"once": True, "trigger": [{}], "action": [{}]}):
            row = self.intents.build(SENTENCE, answer, 1)
            self.assertIsInstance(row, dict)
            self.assertTrue(row.get("refused") or row.get("config"))


# ---------------------------------------------------------------------------
# The armed store
# ---------------------------------------------------------------------------

APPLIED = {"automation_id": "brain_intent_1700000000000",
           "entity_id": "automation.when_the_guests_leave"}


class TestTheArmedStore(IntentCase):

    def arm(self, ts=1_700_000_000_000, now=1_700_000_100.0):
        row = self.build(ts=ts)
        row["ts"] = ts
        return self.intents.arm(row, APPLIED, now)

    def test_arming_records_what_the_accept_produced(self):
        entry = self.arm()
        self.assertEqual(entry["status"], "armed")
        self.assertEqual(entry["automation_id"], APPLIED["automation_id"])
        self.assertEqual(entry["entity_id"], APPLIED["entity_id"])
        self.assertEqual(entry["sentence"], SENTENCE)
        self.assertEqual(self.intents.armed_count(), 1)

    def test_arming_the_same_proposal_twice_is_refused(self):
        self.arm()
        self.assertIsNone(self.arm())
        self.assertEqual(len(self.intents.listing()), 1)

    def test_it_moves_to_fired_and_stays_on_the_list(self):
        entry = self.arm()
        moved = self.intents.mark_fired(entry["ts"], 1_700_003_600)
        self.assertEqual(moved["status"], "fired")
        self.assertEqual(moved["fired_at"], 1_700_003_600)
        self.assertEqual(len(self.intents.listing()), 1)
        # And only once: a second pass over an already-fired row changes
        # nothing, because the stamp on the card is when it happened.
        self.assertIsNone(self.intents.mark_fired(entry["ts"], 1_700_009_999))

    def test_last_triggered_after_the_accept_is_what_counts_as_fired(self):
        entry = self.arm()
        state = {"state": "on", "attributes": {
            "last_triggered": "2023-11-14T22:20:00+00:00"}}
        self.assertGreater(self.intents.fired_from_state(entry, state), 0)

    def test_a_stamp_from_BEFORE_the_accept_is_not_this_intent_firing(self):
        """An automation sharing a slug with one that ran last month would
        otherwise read as done the moment it is armed."""
        entry = self.arm()
        old = {"attributes": {"last_triggered": "2020-01-01T00:00:00+00:00"}}
        self.assertEqual(self.intents.fired_from_state(entry, old), 0.0)

    def test_the_automation_being_off_is_not_it_having_fired(self):
        """Somebody switching it off by hand is not the thing happening."""
        entry = self.arm()
        self.assertEqual(
            self.intents.fired_from_state(entry, {"state": "off",
                                                  "attributes": {}}), 0.0)
        self.assertEqual(self.intents.fired_from_state(entry, None), 0.0)

    def test_a_stamp_with_no_timezone_is_read_as_UTC(self):
        """`datetime.timestamp()` on a naive value reads it as LOCAL time.

        Home Assistant stamps `last_triggered` in UTC with an offset on
        it, so this is the shape of a Core that stopped bothering rather
        than one anybody sees today — but the failure it produces is the
        worst kind: on a house east of Greenwich the naive stamp resolves
        *earlier* than it happened, which can put it back before the
        accept and read a fired one-off as still waiting; west of it, it
        resolves later and an automation that ran before the accept reads
        as this one firing. Neither is a crash and neither is visible.
        """
        entry = self.arm()                       # accepted at 1_700_000_100
        # 2023-11-14T22:20:00Z, written without its offset.
        naive = {"attributes": {"last_triggered": "2023-11-14T22:20:00"}}
        aware = {"attributes": {
            "last_triggered": "2023-11-14T22:20:00+00:00"}}
        self.assertEqual(self.intents.fired_from_state(entry, naive),
                         self.intents.fired_from_state(entry, aware))

    def test_an_unreadable_stamp_is_not_a_firing(self):
        entry = self.arm()
        self.assertEqual(self.intents.fired_from_state(
            entry, {"attributes": {"last_triggered": "soon"}}), 0.0)

    def test_the_ttl_is_a_label_and_never_a_deletion(self):
        entry = self.arm()
        late = 1_700_000_100.0 + (self.intents.INTENT_TTL_DAYS + 1) * 86400
        self.assertTrue(self.intents.expired(entry, late))
        self.assertFalse(self.intents.expired(entry, 1_700_000_200.0))
        # Nothing removed it, and asking did not.
        self.assertEqual(len(self.intents.listing()), 1)

    def test_a_fired_row_is_never_overdue(self):
        entry = self.arm()
        self.intents.mark_fired(entry["ts"], 1_700_003_600)
        late = 1_700_000_100.0 + 40 * 86400
        self.assertFalse(self.intents.expired(self.intents.get(entry["ts"]),
                                              late))

    def test_dropping_and_restoring_is_the_undo(self):
        entry = self.arm()
        dropped = self.intents.drop(entry["ts"])
        self.assertEqual(self.intents.listing(), [])
        self.assertTrue(self.intents.restore(dropped))
        self.assertEqual(len(self.intents.listing()), 1)
        # Refused over an occupied id, exactly as every other restore is.
        self.assertFalse(self.intents.restore(dropped))

    def test_a_refusal_is_a_row_that_can_be_dismissed(self):
        row = self.build({"once": False, "plain": "every evening"})
        noted = self.intents.note(row, 1_700_000_100.0)
        self.assertEqual(noted["status"], "refused")
        self.assertIn("standing rule", noted["refused"])
        self.assertEqual(self.intents.armed_count(), 0)
        self.assertTrue(self.intents.drop(noted["ts"]))

    def test_two_refusals_in_one_millisecond_are_two_rows(self):
        a = self.intents.note({"sentence": "one", "refused": "no"}, 1_700.0)
        b = self.intents.note({"sentence": "two", "refused": "no"}, 1_700.0)
        self.assertNotEqual(a["ts"], b["ts"])
        self.assertEqual(len(self.intents.listing()), 2)

    def test_refusals_are_pruned_among_themselves_and_never_over_armed_rows(self):
        armed = self.arm()
        for i in range(self.intents.MAX_REFUSED + 3):
            self.intents.note({"sentence": f"no {i}", "refused": "no"},
                              1_700.0 + i)
        rows = self.intents.listing()
        self.assertEqual(sum(1 for r in rows if r["status"] == "refused"),
                         self.intents.MAX_REFUSED)
        self.assertIsNotNone(self.intents.get(armed["ts"]))


class TestThePrompt(IntentCase):

    def test_the_sentence_and_the_map_go_in_and_nothing_else(self):
        text = self.intents.prompt(SENTENCE, {
            "areas": {"Porch": 3, "Hall": 8},
            "domains": {"light": 12, "binary_sensor": 20},
            "meta": {"now": "2026-09-05T01:00:00"},
        })
        self.assertIn(SENTENCE, text)
        self.assertIn("Porch", text)
        self.assertIn("light (12)", text)
        self.assertIn("2026-09-05", text)

    def test_a_map_brAIn_could_not_read_is_a_smaller_prompt_not_a_crash(self):
        self.assertIn(SENTENCE, self.intents.prompt(SENTENCE, {}))
        self.assertIn(SENTENCE, self.intents.prompt(SENTENCE, None))

    def test_the_contract_names_the_four_replayable_kinds(self):
        import shadow

        for kind in shadow.REPLAYABLE:
            self.assertIn(kind, self.intents.SYSTEM)
        # And tells the model not to write the thing code writes.
        self.assertIn("switches the automation off", self.intents.SYSTEM)


class TestNothingHereCallsTheHouse(unittest.TestCase):

    def test_the_module_talks_to_no_network(self):
        """It composes and it stores; asking Claude and asking Core are the
        server's, so a failure here can only ever be a file."""
        source = (BASE_DIR / "brain" / "panel" / "intents.py").read_text()
        code = "\n".join(line for line in source.splitlines()
                         if not line.lstrip().startswith("#"))
        for forbidden in ("import aiohttp", "import requests", "http://",
                          "urllib", "import engine"):
            self.assertNotIn(forbidden, code, forbidden)


if __name__ == "__main__":                    # pragma: no cover
    unittest.main()
