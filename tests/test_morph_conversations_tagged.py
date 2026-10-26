#!/usr/bin/env python3
"""What Morph sends brAIn is listed under Morph, not under Your chats.

Morph hands brAIn three kinds of task through the automation listener: a
change request (a Tell), a learning pass, and a conversation (Ask). The
first two were claimed as Automation and the third left unclaimed, which is
what "a person typed it" looks like — so the Chats list showed the person
pages of Morph's change requests as conversations they had had, and a Morph
conversation could not be told from one started in brAIn.

Every Morph task already carries ``"source": "morph"`` (`morph/service/
brain.py`'s `submit`). The listener honours it: the session is claimed as
Morph, a conversation included — still in /config's store, so it stays a
conversation the chat can carry on, never a record. Transcripts already on
disk are relabelled once, by the openers Morph's own code writes.
"""
from __future__ import annotations

import importlib
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_task_failures as tf  # noqa: E402


class TestTheLedgerKnowsMorph(unittest.TestCase):
    def test_morph_is_a_source_in_the_chat_store(self):
        import run_sources
        self.assertIn("morph", run_sources.SOURCES)
        self.assertEqual(run_sources.label("morph"), "Morph")
        # In /config's store: a Morph conversation stays resumable.
        self.assertNotIn("morph", run_sources.ENGINE_SOURCES)


class TestTheListenerClaimsMorphsTasks(tf.ListenerCase):
    """The real `process_task`, with the real run-source library sourced."""

    def run_claimed(self, task: dict) -> dict:
        ledger = self.tmp / "run-sources.jsonl"
        task = {"id": "t1", "prompt": "hello", "ts": time.time(), "timeout": 120, **task}
        (self.tmp / "tasks" / "t1.json").write_text(json.dumps(task))
        body = "\n\n".join(tf.lift(n) for n in tf.LIFTED)
        body = body.replace("cd /config", 'cd "$WORK_DIR"')
        script = "\n".join([
            "set -u",
            "bashio::log.info() { :; }", "bashio::log.warning() { :; }",
            "bashio::log.error() { :; }", "bashio::log.debug() { :; }",
            "verify_mcp_config_fast() { :; }", "verify_mcp_config_full() { :; }",
            "cleanup_stale_files() { :; }", "curl() { :; }",
            f'source "{tf.SCRIPTS_DIR}/brain-run-source.sh"',
            f'TASKS_DIR="{self.tmp}/tasks"', f'RESULTS_DIR="{self.tmp}/results"',
            f'LOG_DIR="{self.tmp}/logs"', f'SHARED_DIR="{self.tmp}"',
            f'TASK_IMAGE_DIR="{self.tmp}/task_images"',
            'MAX_TURNS=200', 'CLAUDE_TIMEOUT=300', 'TIMEOUT_MARGIN=15',
            'SUPERVISOR_TOKEN=""',
            f'CLAUDE_BIN="{sys.executable} {tf.FAKE_CLAUDE}"',
            tf.lift_line("AUTH_REMEDY="), tf.lift_line("export BRAIN_CHANNEL="),
            body, f'process_task "{self.tmp}/tasks/t1.json"', "wait",
        ])
        env = {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(self.tmp),
            "WORK_DIR": str(self.tmp / "work"), "FAKE_MODE": "ok",
            "FAKE_JSON_ENVELOPE": "1",
            "BRAIN_RUN_SOURCES": str(ledger),
            "BRAIN_PANEL_DIR": str(tf.PANEL_DIR), "BRAIN_SCRIPTS_DIR": str(tf.SCRIPTS_DIR),
            "BRAIN_JOURNAL_FILE": str(self.journal),
            "BRAIN_USAGE_NUDGE": str(self.tmp / "usage-nudge"),
            "BRAIN_USAGE_FILE": str(self.tmp / "usage.json"),
            "BRAIN_USAGE_LIMITS": str(self.tmp / "usage_limits.json"),
            "BRAIN_SETTINGS_FILE": str(self.settings),
            "BRAIN_MEMORY_FILE": str(self.memory),
            "BRAIN_FACTS_FILE": str(self.tmp / "facts.json"),
            "BRAIN_FACTS_INGEST_STATE": str(self.tmp / "facts-ingest.json"),
        }
        proc = subprocess.run(["bash", "-c", script], env=env, capture_output=True,
                              text=True, timeout=120, check=False)
        self.assertTrue((self.tmp / "results" / "t1.json").is_file(), proc.stderr)
        if not ledger.is_file():
            return {}
        return {json.loads(line)["id"]: json.loads(line)["source"]
                for line in ledger.read_text().splitlines() if line.strip()}

    def test_a_change_request_is_claimed_as_morph(self):
        claims = self.run_claimed({"source": "morph", "tools": "full"})
        self.assertEqual(set(claims.values()), {"morph"}, claims)

    def test_a_morph_conversation_is_claimed_as_morph(self):
        claims = self.run_claimed({"source": "morph", "kind": "conversation"})
        self.assertEqual(set(claims.values()), {"morph"}, claims)

    def test_anybody_elses_task_is_still_automation(self):
        claims = self.run_claimed({"source": "bright"})
        self.assertEqual(set(claims.values()), {"automation"}, claims)

    def test_a_conversation_from_anybody_else_stays_unclaimed(self):
        self.assertEqual(self.run_claimed({"kind": "conversation"}), {})


def _entry(**kw):
    return json.dumps(kw) + "\n"


def _user(text):
    return _entry(type="user", message={"role": "user", "content": text})


class TestOldTranscriptsAreRelabelled(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        os.environ["CLAUDE_CONFIG_DIR"] = str(root)
        os.environ["BRAIN_RUN_SOURCES"] = str(root / "ledger.jsonl")
        os.environ["BRAIN_SOURCES_BACKFILL_MARKER"] = str(root / "marker-old")
        os.environ["BRAIN_MORPH_RELABEL_MARKER"] = str(root / "marker-morph")
        import run_sources
        self.rs = importlib.reload(run_sources)
        import conversations
        self.mod = importlib.reload(conversations)
        self.project = root / "projects" / "-config"
        self.project.mkdir(parents=True)
        pad = " " * 220

        def write(sid, text):
            (self.project / f"{sid}.jsonl").write_text(_user(text + pad))

        sys.path.insert(0, str(BASE_DIR / "morph" / "service"))
        write("tell-1", "MORPH · a change request for this house's dashboard "
                        "(Morph, in /config/morph).\n\nTHE REQUEST\nAsked: “brighter”")
        write("learn-1", "MORPH · learning pass. Morph is this house's dashboard.")
        write("ask-1", "Someone typed this into the Ask line of Morph, the house's "
                       "dashboard,\nwhich is brAIn's face.\n\nThey wrote:\nis the door shut")
        write("ask-2", "The card they were using sent this with their words. It is "
                       "context for\nthe question, not what they said:\nThe hall card"
                       "\n\nSomeone typed this into the Ask line of Morph, the house's "
                       "dashboard,\nwhich is brAIn's face.\n\nThey wrote:\nwhy")
        write("mine", "Why does the porch light come on at three")
        write("bright-1", "Write a light show for this track")
        self.rs.record("tell-1", "automation")
        self.rs.record("bright-1", "automation")

    def tearDown(self):
        for key in ("BRAIN_RUN_SOURCES", "BRAIN_SOURCES_BACKFILL_MARKER",
                    "BRAIN_MORPH_RELABEL_MARKER"):
            os.environ.pop(key, None)
        self.tmp.cleanup()

    def test_morphs_openers_are_relabelled_and_nothing_else_is(self):
        self.mod.relabel_morph("/config")
        claims = self.rs.lookup(["tell-1", "learn-1", "ask-1", "ask-2", "mine", "bright-1"])
        self.assertEqual(claims, {"tell-1": "morph", "learn-1": "morph", "ask-1": "morph",
                                  "ask-2": "morph", "bright-1": "automation"})
        listed = {r["id"] for r in self.mod.listing("/config", 30, ("morph",))}
        self.assertEqual(listed, {"tell-1", "learn-1", "ask-1", "ask-2"})
        yours = {r["id"] for r in self.mod.listing("/config", 30, ("you",))}
        self.assertEqual(yours, {"mine"})

    def test_the_openers_are_the_ones_morph_writes(self):
        """Read off Morph's own code, so a reworded prompt fails here rather
        than silently filing new Morph runs among the person's chats."""
        import converse
        prompts = [converse.prompt_for("is the door shut"),
                   converse.prompt_for("why", context="The hall card")]
        tell_src = (BASE_DIR / "morph" / "service" / "tell.py").read_text()
        learn_src = (BASE_DIR / "morph" / "service" / "learning.py").read_text()
        for text in prompts:
            folded = " ".join(text.split())
            self.assertTrue(any(folded.startswith(p) for p in self.mod.MORPH_OPENERS), folded)
        self.assertIn('"MORPH · a change request', tell_src)
        self.assertIn('"MORPH · learning pass.', learn_src)

    def test_it_runs_once(self):
        self.mod.relabel_morph("/config")
        (self.project / "ask-9.jsonl").write_text(
            _user("Someone typed this into the Ask line of Morph, the house's dashboard,"
                  " which is brAIn's face." + " " * 220))
        self.assertEqual(self.mod.relabel_morph("/config"), 0)


if __name__ == "__main__":
    unittest.main()
