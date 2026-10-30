#!/usr/bin/env python3
"""The presence loop's server half, driven for real with only Home
Assistant and the CLI stubbed.

What is driven: the bus hook (`_on_bus_event`) with a person coming home
and with a button pressed on a greeting, the nightly pass
(`_presence_pass`) through the run queue, and delivery through the real
`_send_notification` into the real delivery ledger. What is asserted is
what the household was promised: off means nothing at all; an arrival is
greeted once, inside the budget, never in the quiet hours and never on
somebody else's phone; "Less like this" stops that kind at once; the
nightly run is one cheap job a day whose answer is read strictly; and
nothing it does is written into the Resident's verdict log or the facts
store about a person.

The people (Wren, Ilo) and the assistant's name (Sable) are invented.
"""

import asyncio
import datetime as dt
import json
import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_dispatch import DispatchCase  # noqa: E402

UTC = dt.timezone.utc
WREN = "person.wren"
ILO = "person.ilo"


def person(eid, name, state, trackers=()):
    return {"entity_id": eid, "state": state,
            "attributes": {"friendly_name": name,
                           "device_trackers": list(trackers)}}


class PresenceCase(DispatchCase):

    def setUp(self):
        super().setUp()
        srv = self.server
        root = Path(self.tmp.name)
        self.features = root / "features.json"
        self.pers = root / "personality.json"
        for mod in self.copies("presence"):
            self._restore += [(mod, a, getattr(mod, a)) for a in (
                "STORE", "FEATURES_FILE", "DAY_START_H", "DAY_END_H",
                "REFLECT_HOURS")]
            mod.STORE = root / "presence.json"
            mod.FEATURES_FILE = str(self.features)
            # The test runs at whatever hour the machine says: the day is
            # the whole day here, and the quiet hours are set per test.
            mod.DAY_START_H, mod.DAY_END_H = 0, 24
            mod.REFLECT_HOURS = (0, 24)
        for mod in self.copies("personality"):
            self._restore += [(mod, a, getattr(mod, a)) for a in (
                "STORE", "FEATURES_FILE")]
            mod.STORE = str(self.pers)
            mod.FEATURES_FILE = str(self.features)
        # The stores a send and a run touch on their way past, kept in
        # this test's own directory (conftest's RealDataWrite rule).
        import checks.coverage  # noqa: F401 — so `copies` finds it
        import decision_trail  # noqa: F401
        import journal  # noqa: F401
        import usage_store  # noqa: F401
        for modname, attr, name in (
                ("decision_trail", "TRAIL_FILE", "decisions.jsonl"),
                ("journal", "JOURNAL_FILE", "journal.jsonl"),
                ("usage_store", "NUDGE_FILE", "usage-nudge"),
                ("checks.coverage", "COVERAGE_FILE", "checks-coverage.json")):
            for mod in self.copies(modname):
                if not hasattr(mod, attr):
                    continue
                current = getattr(mod, attr)
                self._restore.append((mod, attr, current))
                setattr(mod, attr, str(root / name)
                        if isinstance(current, str) else Path(root / name))
        self.presence = srv.presence
        self.personality = srv.personality
        self.personality.save("Sable", "Warm, brief, never fussy.")
        self.switch(True, True)
        self._saved_presence = (srv._presence_tz, srv._presence_read_house,
                                srv.PRESENCE_ARRIVAL_DELAY_S,
                                srv._write_terminal_prompt, srv._speak_enabled)
        srv._presence_tz = lambda: UTC
        srv.PRESENCE_ARRIVAL_DELAY_S = 0
        srv._write_terminal_prompt = lambda: True
        srv._speak_enabled = lambda: False
        self.house_reads = 0
        self.states = [
            person(WREN, "Wren", "home", ["device_tracker.phone"]),
            person(ILO, "Ilo", "home", ["device_tracker.ilos_tablet"])]

        async def read_house():
            self.house_reads += 1
            return {"states": self.states, "services": []}

        srv._presence_read_house = read_house

    def tearDown(self):
        srv = self.server
        (srv._presence_tz, srv._presence_read_house,
         srv.PRESENCE_ARRIVAL_DELAY_S, srv._write_terminal_prompt,
         srv._speak_enabled) = self._saved_presence
        super().tearDown()

    # -- helpers ---------------------------------------------------------
    def switch(self, personality_on: bool, learning_on: bool):
        self.features.write_text(json.dumps(
            {"personality": personality_on, "learning_loop": learning_on}),
            encoding="utf-8")

    def queue(self, pid, kind, text, reason="Because they asked."):
        state = self.presence.load()
        self.presence.add_ideas(state, [{"person": pid, "kind": kind,
                                         "text": text, "reason": reason}],
                                {WREN: "Wren", ILO: "Ilo"}, time.time())
        self.presence.save(state)

    def left(self, pid, hours_ago=3.0):
        state = self.presence.load()
        self.presence.note_departure(state, pid, time.time() - hours_ago * 3600)
        self.presence.save(state)

    def bus(self, *events):
        """Hand events to the bus hook inside a loop and wait for whatever
        they started."""
        srv = self.server

        async def run():
            for event_type, data in events:
                srv._on_bus_event(event_type, data)
                await asyncio.sleep(0)
                pending = [t for t in list(srv.PRESENCE_TASKS) if not t.done()]
                if pending:
                    await asyncio.gather(*pending)

        asyncio.run(run())

    def arrive(self, pid):
        return ("state_changed", {"entity_id": pid,
                                  "old_state": {"state": "not_home"},
                                  "new_state": {"state": "home"}})

    def go(self, pid):
        return ("state_changed", {"entity_id": pid,
                                  "old_state": {"state": "home"},
                                  "new_state": {"state": "not_home"}})

    def presses(self):
        return [b["action"] for s in self.sent
                for b in ((s.get("data") or {}).get("actions") or [])]


class TestOffMeansNothing(PresenceCase):

    def test_with_either_switch_off_an_arrival_reads_and_sends_nothing(self):
        for on in ((False, True), (True, False)):
            with self.subTest(switches=on):
                self.switch(*on)
                self.queue(WREN, "arrival", "Welcome back, Wren.")
                self.left(WREN)
                self.bus(self.arrive(WREN))
                self.assertEqual(self.sent, [])
                self.assertEqual(self.house_reads, 0)

    def test_with_a_switch_off_the_nightly_pass_asks_nothing(self):
        self.switch(True, False)
        out = asyncio.run(self.server._presence_pass(time.time()))
        self.assertIn("Learning loop", out["off"])
        self.assertEqual(self.look_calls, [])
        self.assertEqual(self.house_reads, 0)


class TestTheArrivalGreeting(PresenceCase):

    def test_an_arrival_is_greeted_once_in_the_assistants_voice(self):
        self.queue(WREN, "arrival", "Welcome back, Wren — brAIn put the "
                                    "porch light on.")
        self.left(WREN)
        self.bus(self.arrive(WREN))
        self.assertEqual(len(self.sent), 1)
        msg = self.sent[0]
        self.assertEqual(msg["service"], "mobile_app_phone")
        self.assertEqual(msg["title"], "Sable")
        self.assertIn("Sable put the porch light on", msg["body"])
        self.assertTrue(all(a.startswith("brain_presence.")
                            for a in self.presses()))
        # The ledger has it, under its own kind.
        rows = self.deliveries.fold() or []
        self.assertEqual(rows[0]["kind"], "presence")
        # The history has it, with its reason.
        touch = self.presence.load()["touches"][-1]
        self.assertEqual((touch["person"], touch["kind"], touch["reason"]),
                         (WREN, "arrival", "Because they asked."))
        self.assertEqual(touch["delivery"], rows[0]["id"])
        # The tracker flapping is the same arrival; and a fresh greeting
        # queued for later the same day is held by the budget.
        self.queue(WREN, "arrival", "Hello again, Wren.")
        self.bus(self.go(WREN), self.arrive(WREN))
        self.assertEqual(len(self.sent), 1)

    def test_never_in_the_quiet_hours(self):
        hour = dt.datetime.now(UTC).hour
        self.server._quiet_hours = lambda: (hour, (hour + 1) % 24)
        self.queue(WREN, "arrival", "Welcome back, Wren.")
        self.left(WREN)
        self.bus(self.arrive(WREN))
        self.assertEqual(self.sent, [])
        self.assertIn("quiet", self.server.PRESENCE_STATE["last_skip"])

    def test_never_to_somebody_elses_phone(self):
        # The notify target is Wren's phone; Ilo is greeted nowhere, since
        # Speak first is off.
        self.queue(ILO, "arrival", "Welcome back, Ilo.")
        self.left(ILO)
        self.bus(self.arrive(ILO))
        self.assertEqual(self.sent, [])
        self.assertIn("Speak first", self.server.PRESENCE_STATE["last_skip"])

    def test_no_queued_greeting_is_no_greeting(self):
        self.left(WREN)
        self.bus(self.arrive(WREN))
        self.assertEqual(self.sent, [])

    def test_less_like_this_on_the_phone_stops_that_kind_at_once(self):
        self.queue(WREN, "arrival", "Welcome back, Wren.")
        self.left(WREN)
        self.bus(self.arrive(WREN))
        less = next(a for a in self.presses() if ".less." in a)
        self.bus(("mobile_app_notification_action", {"action": less}))
        state = self.presence.load()
        self.assertEqual(state["touches"][-1]["reaction"], "less")
        self.assertIn("arrival", self.presence.retired_kinds(state, WREN))
        # And the bus never turned the press into a case to look at.
        sig = self.server.EVENT_BUS
        self.assertIsNone(sig)  # the bus is not running in this test
        import eventbus
        bus = eventbus.EventBus(lambda s: None)
        self.assertIsNone(bus._to_signal(
            "mobile_app_notification_action", {"action": less}, time.time()))


class TestTheNightlyReflection(PresenceCase):

    def answer(self):
        body = {
            "growth": [{"text": "Keep greetings to one short line; the "
                                "long ones went unanswered.",
                        "why": "Two long ones were swiped."}],
            "ideas": [
                {"person": WREN, "kind": "evening",
                 "text": "Evening, Wren — the bins go out tonight.",
                 "reason": "Wren asked about the bins on Monday."},
                {"person": ILO, "kind": "morning",
                 "text": "Morning, Ilo. You seemed stressed yesterday.",
                 "reason": "Ilo is always late."}],
            "notes": [{"person": WREN, "text": "Wren is lazy about the bins."}],
        }
        return {"ok": True, "data": body, "text": json.dumps(body),
                "meta": {"session_id": "presence-1"}}

    def test_one_cheap_run_a_night_read_strictly(self):
        self.looks.append(self.answer())
        now = time.time()
        out = asyncio.run(self.server._presence_pass(now))
        self.assertEqual(len(self.look_calls), 1)
        call = self.look_calls[0]
        self.assertEqual(call.get("job"), "presence")
        self.assertIn("schema", call)
        self.assertIn("Wren", call["prompt"])
        self.assertTrue(out["reflect"]["ok"])
        # One idea kept, the judging one and the judging note refused.
        state = self.presence.load()
        self.assertEqual(len(self.presence.ideas_for(state, WREN)), 1)
        self.assertEqual(self.presence.ideas_for(state, ILO), [])
        self.assertEqual(self.presence.notes_for(state, WREN), [])
        self.assertEqual(out["reflect"]["refused"], 2)
        # Growth written as its own, the persona untouched.
        pers = self.personality.load()
        self.assertEqual(pers["persona"], "Warm, brief, never fussy.")
        self.assertEqual(pers["growth"][-1]["by"], "self")
        # Not again tonight.
        asyncio.run(self.server._presence_pass(now + 600))
        self.assertEqual(len(self.look_calls), 1)

    def test_nothing_is_written_to_the_scorecard_or_the_facts(self):
        import outcomes
        self.looks.append(self.answer())
        verdicts = Path(outcomes.VERDICTS_FILE)
        before = verdicts.read_text() if verdicts.exists() else None
        facts = self.server.facts_store
        added = []
        real = facts.add
        facts.add = lambda *a, **k: added.append((a, k)) or real(*a, **k)
        try:
            asyncio.run(self.server._presence_pass(time.time()))
        finally:
            facts.add = real
        after = verdicts.read_text() if verdicts.exists() else None
        self.assertEqual(before, after)
        self.assertEqual(added, [])

    def test_a_gate_holds_the_run_and_says_so(self):
        self.server.settings_store.save({"auto_enabled": False})
        out = asyncio.run(self.server._presence_pass(time.time()))
        self.assertEqual(self.look_calls, [])
        self.assertIn("paused", out["reflect"]["held"])

    def test_a_due_idea_goes_inside_its_window(self):
        state = self.presence.load()
        state["reflect"] = {"at": int(time.time())}
        self.presence.save(state)
        for mod in self.copies("presence"):
            self._restore.append((mod, "WINDOWS", mod.WINDOWS))
            mod.WINDOWS = {**mod.WINDOWS, "followup": (0, 24)}
        self.queue(WREN, "followup", "Wren, the filter you asked about "
                                     "arrives Thursday.")
        out = asyncio.run(self.server._presence_pass(time.time()))
        self.assertEqual(out.get("sent"), 1)
        self.assertEqual(len(self.sent), 1)
        # The budget: the second pass the same day sends nothing more.
        self.queue(WREN, "followup", "Wren, one more thing.")
        asyncio.run(self.server._presence_pass(time.time() + 120))
        self.assertEqual(len(self.sent), 1)


if __name__ == "__main__":
    unittest.main()
