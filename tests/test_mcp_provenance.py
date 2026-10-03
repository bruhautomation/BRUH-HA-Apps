#!/usr/bin/env python3
"""Who asked: the channel on a remembered fact and on a ledger row.

The MCP server serves voice, the chat, the terminal, the fixer and the
automation listener alike, and it wrote every fact as `source: "assist"`
and every service call as an anonymous ledger row. So a preference typed
into the chat was filed as voice-taught with no run to look back at, and a
person saying "turn the hall light back on" to a brAIn voice agent a minute
after the motion rule turned it off was filed as brAIn's own automated move
— not an override, and on its second time round, `'Hall motion' and
'brAIn' keep undoing each other`.

The writer and the readers are different processes that cannot import each
other (the MCP server runs as the `claude` user; the panel's facts store
and action miner run as root), so these drive the real writer into the
real readers rather than writing either shape down twice.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "brain" / "ha-mcp-server"))
sys.path.insert(0, str(REPO / "brain" / "panel"))

import actions  # noqa: E402
import facts_store  # noqa: E402
import ha_mcp_server as m  # noqa: E402

SESSION = "6f1c2a9e-3b7d-4c55-9a10-2f8e4d1b7c63"


def env_for(**values):
    """The environment a launcher hands the CLI, which hands it to us."""
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("BRAIN_") and k != "CLAUDE_CODE_SESSION_ID"}
    env.update(values)
    return patch.dict(os.environ, env, clear=True)


class TestTheChannelIsRead(unittest.TestCase):
    def test_the_launcher_names_it(self):
        with env_for(BRAIN_CHANNEL="Chat"):
            self.assertEqual(m._channel(), "chat")
        with env_for(BRAIN_CHANNEL="card; rm -rf /"):
            self.assertEqual(m._channel(), "cardrm-rf")

    def test_the_voice_launchers_are_known_by_what_they_already_set(self):
        with env_for(BRAIN_ASSIST_ACCESS="house"):
            self.assertEqual(m._channel(), "voice")
        # The classic listener sets the gate to 0 or 1 and nothing else.
        with env_for(BRAIN_EXPOSED_ONLY="0"):
            self.assertEqual(m._channel(), "voice")

    def test_anything_else_is_unknown_not_a_guess(self):
        with env_for():
            self.assertEqual(m._channel(), "")

    def test_the_session_is_claude_codes_own(self):
        with env_for(CLAUDE_CODE_SESSION_ID=SESSION):
            self.assertEqual(m._run_id(), SESSION)
        with env_for(CLAUDE_CODE_SESSION_ID="../../etc/passwd"):
            self.assertEqual(m._run_id(), "")


class TestAFactSaysWhoTaughtIt(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.memory = root / "memory"
        for p in (patch.object(m, "MEMORY_DIR", str(self.memory)),
                  patch.object(m, "EXPOSED_ONLY", False),
                  patch.object(facts_store, "FACTS_FILE", root / "facts.json"),
                  patch.object(facts_store, "INGEST_STATE_FILE",
                               root / "facts-ingest.json")):
            p.start()
            self.addCleanup(p.stop)

    def lines(self):
        out = []
        for path in sorted((self.memory / "inbox").glob("*.jsonl")):
            out += [(path.name, json.loads(line))
                    for line in path.read_text().splitlines() if line.strip()]
        return out

    def test_a_chat_fact_is_the_chats_and_names_its_run(self):
        with env_for(BRAIN_CHANNEL="chat", CLAUDE_CODE_SESSION_ID=SESSION):
            got = m.remember_fact("Ben likes the lounge at 21", subject="area:lounge")
        self.assertEqual(got["status"], "remembered")
        ((name, record),) = self.lines()
        self.assertTrue(name.endswith("-chat.jsonl"))
        self.assertEqual((record["source"], record["run_id"]), ("chat", SESSION))

    def test_voice_is_voice_and_an_unknown_face_is_not_called_voice(self):
        with env_for(BRAIN_ASSIST_ACCESS="voice"):
            m.remember_fact("We call the office lamp the beacon")
        with env_for():
            m.remember_fact("The porch light stays on at night")
        sources = [r["source"] for _n, r in self.lines()]
        self.assertEqual(sorted(sources), ["conversation", "voice"])
        self.assertNotIn("assist", sources)
        self.assertTrue(all("run_id" not in r for _n, r in self.lines()))

    def test_the_facts_store_files_it_under_the_channel_and_the_run(self):
        with env_for(BRAIN_CHANNEL="terminal", CLAUDE_CODE_SESSION_ID=SESSION):
            m.remember_fact("The boiler is a 2019 Worcester", subject="climate.boiler")
        processed = self.memory / "processed"
        processed.mkdir()
        created = facts_store.ingest_inbox(self.memory / "inbox", processed)
        self.assertEqual(created, 1)
        (fact,) = facts_store.recall(subject="climate.boiler")
        self.assertEqual((fact["source"], fact["run_id"]), ("terminal", SESSION))

    def test_voice_cannot_file_a_fact_about_what_it_cannot_see(self):
        with env_for(BRAIN_EXPOSED_ONLY="1"), \
                patch.object(m, "EXPOSED_ONLY", True), \
                patch.object(m, "_entity_exposed", lambda eid: eid == "light.kitchen"):
            got = m.remember_fact("The front door sticks", subject="lock.front_door")
            self.assertIn("not exposed", got["error"])
            self.assertEqual(m.remember_fact("Kitchen light is the big one",
                                             subject="light.kitchen")["status"],
                             "remembered")
            self.assertEqual(m.remember_fact("We eat at 7", subject="house")["status"],
                             "remembered")
        self.assertEqual(len(self.lines()), 2)


NOW = 1_789_800_000.0


def logbook(when, state, **ctx):
    return {"when": when, "entity_id": "light.hall", "name": "Hall light",
            "state": state, **ctx}


class TestALedgerRowSaysWhoAsked(unittest.TestCase):
    """A spoken correction of a motion rule is an override, not a fight."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "actions.jsonl")

    def call(self, ts, **env):
        """The real writer, at a chosen moment, as a launcher set it up."""
        with env_for(**env), patch.object(m, "ACTION_LEDGER", self.path), \
                patch.object(m.time, "time", lambda: ts):
            m.record_action("light", "turn_on", {"entity_id": "light.hall"})

    def mine(self):
        entries = [
            logbook(NOW, "off", context_entity_id="automation.hall_motion",
                    context_entity_id_name="Hall motion"),
            logbook(NOW + 60, "on", context_user_id="supervisor"),
        ]
        return actions.mine(entries, users={"supervisor": "Supervisor"},
                            brain_calls=actions.read_ledger(0, self.path))["actions"]

    def test_the_writer_stamps_the_channel(self):
        self.call(NOW + 59.5, BRAIN_ASSIST_ACCESS="voice",
                  CLAUDE_CODE_SESSION_ID=SESSION)
        (row,) = actions.read_ledger(0, self.path)
        self.assertEqual((row["channel"], row["run_id"]), ("voice", SESSION))

    def test_voice_through_brain_is_an_override_of_the_rule(self):
        self.call(NOW + 59.5, BRAIN_ASSIST_ACCESS="voice")
        mined = self.mine()
        self.assertEqual(mined[1]["cause"], "voice")
        self.assertEqual(mined[1]["via"], "brain")
        (override,) = actions.find_overrides(mined)
        self.assertEqual((override["by"], override["to_state"]),
                         ("automation.hall_motion", "on"))
        self.assertEqual(actions.find_conflicts(mined), [])

    def test_the_chat_and_the_terminal_are_a_person(self):
        for channel in ("chat", "terminal"):
            with self.subTest(channel=channel):
                os.remove(self.path) if os.path.exists(self.path) else None
                self.call(NOW + 59.5, BRAIN_CHANNEL=channel)
                mined = self.mine()
                self.assertEqual(mined[1]["cause"], "person")
                self.assertEqual(len(actions.find_overrides(mined)), 1)

    def test_an_unattended_run_is_still_brain_and_still_a_conflict(self):
        """The safe direction: a card or a fix filed as a person would invent
        the very overrides this exists to find. And a row from before rows
        said who asked reads exactly as it always did."""
        for env in ({"BRAIN_CHANNEL": "resident"}, {}):
            with self.subTest(env=env):
                os.remove(self.path) if os.path.exists(self.path) else None
                self.call(NOW + 59.5, **env)
                mined = self.mine()
                self.assertEqual((mined[1]["cause"], mined[1]["by_name"]),
                                 ("brain", "brAIn"))
                self.assertEqual(actions.find_overrides(mined), [])
                self.assertEqual(len(actions.find_conflicts(mined)), 1)

    def test_the_writer_never_makes_its_own_directory(self):
        """run.sh makes /config/.brain; a writer that made it grew a stray
        one on every machine the suite ran on, which the facts store then
        read as a real install."""
        missing = os.path.join(self.tmp.name, "no-such-dir", "actions.jsonl")
        with patch.object(m, "ACTION_LEDGER", missing):
            m.record_action("light", "turn_on", {"entity_id": "light.hall"})
        self.assertFalse(os.path.exists(os.path.dirname(missing)))

    def test_the_nearest_call_explains_the_change(self):
        self.call(NOW + 45, BRAIN_CHANNEL="card")
        self.call(NOW + 59.5, BRAIN_CHANNEL="chat")
        self.assertEqual(self.mine()[1]["cause"], "person")


if __name__ == "__main__":
    unittest.main()
