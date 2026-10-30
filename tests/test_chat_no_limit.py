#!/usr/bin/env python3
"""No limit on simultaneous conversations, and memory instead of a count.

The owner's ask: every conversation may be live and busy at once. So the
default ``chat_max_sessions`` is "no limit" and nothing is refused for lack
of a slot; a number a person sets still applies; and what keeps the box
safe is a memory floor that only ever puts IDLE conversations to sleep.

Real fake-CLI subprocesses through the real registry, like
``test_chat_terminal.TestManySessions``: the parts that break are lifecycle.
"""

import asyncio
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"
sys.path.insert(0, str(PANEL))


# The chat writes the run journal, the run-source ledger and the usage
# nudge as it goes; every one of them defaults to the real /data. Pointed at
# a directory of this file's own for the whole module (conftest's
# RealDataWrite), with the module attributes patched as well as the
# variables, because the modules read them once at import.
_DATA_ISOLATION = (
    ("BRAIN_JOURNAL_FILE", "journal", "JOURNAL_FILE", "journal.jsonl", str),
    ("BRAIN_RUN_SOURCES", "run_sources", "LEDGER", "run-sources.jsonl", Path),
    ("BRAIN_USAGE_NUDGE", "usage_store", "NUDGE_FILE", "usage-nudge", str),
    ("BRAIN_USAGE_FILE", "usage_store", "USAGE_FILE", "usage.json", str),
)
_DATA_SAVED: list = []
_DATA_TMP = None


def setUpModule():
    global _DATA_TMP
    _DATA_TMP = tempfile.TemporaryDirectory()
    for env, module_name, attr, leaf, kind in _DATA_ISOLATION:
        module = importlib.import_module(module_name)
        _DATA_SAVED.append((env, os.environ.get(env), module, attr,
                            getattr(module, attr)))
        path = os.path.join(_DATA_TMP.name, leaf)
        os.environ[env] = path
        setattr(module, attr, kind(path))


def tearDownModule():
    for env, value, module, attr, original in reversed(_DATA_SAVED):
        if value is None:
            os.environ.pop(env, None)
        else:
            os.environ[env] = value
        setattr(module, attr, original)
    _DATA_SAVED.clear()
    if _DATA_TMP is not None:
        _DATA_TMP.cleanup()

pytestmark = pytest.mark.slow


class _RegistryCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.meminfo = os.path.join(self.tmp.name, "meminfo")
        self._meminfo(4_000)
        for key, value in {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(self.tmp.name, "t.json"),
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(self.tmp.name, "chat"),
            "BRAIN_SETTINGS_FILE": os.path.join(self.tmp.name, "settings.json"),
            "BRAIN_CHAT_WORKDIR": self.tmp.name,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_MEMINFO": self.meminfo,
            "FAKE_CHAT_MODE": "ok",
            "FAKE_CHAT_DELAY": "3",
        }.items():
            os.environ[key] = value
        for key in ("FAKE_CHAT_LOG", "FAKE_CHAT_BROKEN", "FAKE_CHAT_NOPROMPTFLAG"):
            os.environ.pop(key, None)
        for name in ("engine", "settings_store", "chat_session"):
            setattr(self, name, importlib.reload(importlib.import_module(name)))
        self.reg = self.chat_session.SessionRegistry()

    async def asyncTearDown(self):
        await self.reg.stop_all()
        for key in ("FAKE_CHAT_MODE", "FAKE_CHAT_DELAY", "BRAIN_MEMINFO"):
            os.environ.pop(key, None)
        importlib.reload(self.chat_session)
        self.tmp.cleanup()

    def _meminfo(self, available_mb):
        with open(self.meminfo, "w", encoding="utf-8") as fh:
            fh.write("MemTotal:        8000000 kB\n"
                     "MemFree:          100000 kB\n"
                     f"MemAvailable:    {available_mb * 1024} kB\n")

    async def _wait(self, check, timeout=8.0):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while loop.time() < deadline:
            if check():
                return True
            await asyncio.sleep(0.05)
        return False

    async def _open(self, session_id):
        await self.reg.open(session_id, [])
        session = self.reg.get(session_id)
        self.assertIsNotNone(session, f"{session_id} did not open")
        return session

    async def _busy(self, session_id):
        os.environ["FAKE_CHAT_MODE"] = "slow"
        session = await self._open(session_id)
        await session.send("take your time")
        self.assertTrue(await self._wait(lambda: session.state == "busy"),
                        "the fixture never started answering")
        os.environ["FAKE_CHAT_MODE"] = "ok"
        return session


class TestNoLimitByDefault(_RegistryCase):

    def test_the_default_is_no_limit(self):
        self.assertIsNone(self.chat_session.max_sessions())
        self.assertIsNone(self.settings_store.load()["chat_max_sessions"])

    async def test_many_busy_conversations_and_another_still_opens(self):
        """Five answering at once, and a sixth opens: no 409, no queue,
        and none of the five was stopped to make way for it."""
        busy = [await self._busy(f"conv-{n}") for n in range(5)]
        extra = await self._open("conv-extra")
        self.assertTrue(extra.alive())
        for session in busy:
            self.assertTrue(session.alive(), session.session_id)
            self.assertEqual(session.state, "busy", session.session_id)
        self.assertEqual(self.reg.summary()["evicted"], 0)
        self.assertIsNone(self.reg.summary()["max"])

    async def test_a_new_conversation_opens_beside_busy_ones(self):
        await self._busy("conv-a")
        await self._busy("conv-b")
        await self.reg.attach("conv-b")
        self.reg.attached().events.append({"type": "user", "text": "x"})
        out = await self.reg.new()
        self.assertTrue(out["ok"])
        self.assertTrue(self.reg.get("conv-a").alive())

    async def test_a_number_the_person_set_still_applies(self):
        self.settings_store.save({"chat_max_sessions": 1})
        self.assertEqual(self.chat_session.max_sessions(), 1)
        await self._busy("conv-busy")
        with self.assertRaises(self.chat_session.SessionCapReached):
            await self.reg.open("conv-other", [])

    def test_no_limit_can_be_chosen_back_and_the_range_is_wider(self):
        self.settings_store.save({"chat_max_sessions": 32})
        self.assertEqual(self.chat_session.max_sessions(), 32)
        self.settings_store.save({"chat_max_sessions": None})
        self.assertIsNone(self.chat_session.max_sessions())
        with self.assertRaises(ValueError):
            self.settings_store.save({"chat_max_sessions": 33})
        with self.assertRaises(ValueError):
            self.settings_store.save({"chat_max_sessions": 0})


class TestTheMemoryFloor(_RegistryCase):

    def test_meminfo_is_read_in_megabytes(self):
        self._meminfo(1234)
        self.assertEqual(self.chat_session.mem_available_mb(), 1234)
        os.remove(self.meminfo)
        self.assertIsNone(self.chat_session.mem_available_mb())

    async def test_low_memory_puts_idle_ones_to_sleep_never_a_busy_one(self):
        busy = await self._busy("conv-busy")
        idle_old = await self._open("conv-idle-old")
        idle_new = await self._open("conv-idle-new")
        idle_old.last_activity -= 100        # the quieter of the two
        # Short until one idle process has gone, then fine again: it
        # stops at the floor rather than emptying the box.
        alive = lambda: sum(1 for s in self.reg.sessions() if s.alive())  # noqa: E731
        start = alive()
        self.chat_session.mem_available_mb = (
            lambda: 500 if alive() >= start else 900)
        with self.assertLogs("brain.chat", level="INFO") as logs:
            fresh = await self._open("conv-fresh")
        self.assertTrue(fresh.alive())
        self.assertTrue(busy.alive(), "memory took an answer being written")
        self.assertFalse(idle_old.alive(), "the quietest idle one was kept")
        self.assertTrue(idle_new.alive(), "it went past the floor")
        self.assertIn("memory is short", "\n".join(logs.output))
        notice = [e for e in idle_old.events if e["type"] == "notice"]
        self.assertIn("memory was short", notice[-1]["text"])
        state = self.reg.row_state("conv-idle-old")
        self.assertEqual(state["state"], "paused_room")
        self.assertIn("memory", state["hint"])

    async def test_low_memory_with_nothing_idle_starts_it_anyway(self):
        busy = await self._busy("conv-busy")
        self._meminfo(100)
        with self.assertLogs("brain.chat", level="WARNING") as logs:
            fresh = await self._open("conv-fresh")
        self.assertTrue(fresh.alive())
        self.assertTrue(busy.alive())
        self.assertIn("starting another anyway", "\n".join(logs.output))

    async def test_enough_memory_stops_nothing(self):
        idle = await self._open("conv-idle")
        self._meminfo(5000)
        await self._open("conv-two")
        self.assertTrue(idle.alive())


if __name__ == "__main__":
    unittest.main()
