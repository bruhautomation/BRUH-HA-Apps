#!/usr/bin/env python3
"""The chat terminal: the second face of the Terminal tab.

Two things are worth testing and they are quite different:

* **The normaliser.** Everything that knows Claude Code's stream-json wire
  shape lives in ``chat_session._normalise``; if it drifts, the panel draws
  nothing and there is no error anywhere. These tests are pure and fast.
* **The session.** A real subprocess (``tests/fake_claude_chat.py``) driven
  through the real API, because the parts that break in practice — a turn
  that never ends, a CLI that dies mid-answer, "new chat" that keeps
  resuming the old one — are all lifecycle, not parsing.
"""

import asyncio
import importlib
import json
import os
import re
import sys
import tempfile
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"

sys.path.insert(0, str(PANEL))


class TestContextUsage(unittest.TestCase):
    """How full the conversation is, read off the CLI's own usage report.

    The prompt the CLI just sent IS the conversation so far, so the last
    model call's input tokens are the context in use — a measurement rather
    than an estimate. Cache reads count: a cached prompt still occupies the
    window, it is only cheaper.
    """

    @classmethod
    def setUpClass(cls):
        import chat_session
        cls.mod = chat_session

    def _session(self, model="claude-sonnet-5"):
        s = self.mod.ChatSession.__new__(self.mod.ChatSession)
        s.context = {}
        s.info = {"model": model}
        s.model = model
        s._emit = lambda *a, **k: None
        return s

    def test_the_window_follows_the_version_not_the_family(self):
        """Opus and Sonnet went to 1M at 4.6, and Haiku did not.

        A family-name lookup said 200K for every one of these, which is how
        a real conversation came to report several hundred percent of a
        window five times too small.
        """
        for model in ("claude-opus-5", "claude-sonnet-5", "claude-opus-4-8",
                      "claude-opus-4-6", "claude-sonnet-4-6", "claude-fable-5"):
            self.assertEqual(self.mod.context_window(model), 1_000_000, model)
        for model in ("claude-haiku-4-5", "claude-haiku-4-5-20251001",
                      "claude-opus-4-5-20251101", "claude-sonnet-4-5",
                      "claude-3-5-sonnet-20241022"):
            self.assertEqual(self.mod.context_window(model), 200_000, model)

    def test_a_trailing_date_stamp_is_not_a_version(self):
        self.assertEqual(self.mod.model_version("claude-opus-4-20250514"), (4, 0))
        self.assertEqual(
            self.mod.model_version("claude-haiku-4-5-20251001"), (4, 5))
        self.assertEqual(
            self.mod.model_version("claude-3-5-sonnet-20241022"), (3, 5))

    def test_an_unreadable_model_reports_no_window(self):
        # A percentage of a guessed denominator is worse than no percentage,
        # and the two candidate answers here are 5x apart.
        self.assertEqual(self.mod.context_window("some-future-model"), 0)
        self.assertEqual(self.mod.context_window("claude-opus-latest"), 0)
        self.assertEqual(self.mod.context_window(""), 0)

    def test_cache_reads_count_toward_the_window(self):
        s = self._session()
        s._take_context({
            "input_tokens": 1200,
            "cache_read_input_tokens": 40_000,
            "cache_creation_input_tokens": 800,
            "output_tokens": 900,     # not context until it comes back as input
        })
        self.assertEqual(s.context, {"tokens": 42_000, "window": 1_000_000})

    def test_usage_without_input_leaves_it_alone(self):
        s = self._session()
        s.context = {"tokens": 5, "window": 1_000_000}
        s._take_context(None)
        s._take_context("nonsense")
        s._take_context({"output_tokens": 10})
        self.assertEqual(s.context, {"tokens": 5, "window": 1_000_000})

    def test_an_unknown_model_still_reports_its_tokens(self):
        s = self._session(model="some-future-model")
        s._take_context({"input_tokens": 900})
        self.assertEqual(s.context, {"tokens": 900, "window": 0})


class TestNormalise(unittest.TestCase):
    """The wire shape → the six event types the panel knows how to draw."""

    @classmethod
    def setUpClass(cls):
        import chat_session
        cls.mod = chat_session

    def test_text_deltas_are_live_only(self):
        """The assistant event that follows carries the same text whole, so
        keeping the deltas too would double every answer on the next reload."""
        out = self.mod._normalise({
            "type": "stream_event",
            "event": {"delta": {"type": "text_delta", "text": "hi"}}})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "text_delta")
        self.assertFalse(out[0]["_keep"])

    def test_an_assistant_message_can_carry_three_kinds_of_block(self):
        out = self.mod._normalise({"type": "assistant", "message": {"content": [
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "hello"},
            {"type": "tool_use", "id": "t1", "name": "Read",
             "input": {"file_path": "/config/x.yaml"}},
        ]}})
        self.assertEqual([e["type"] for e in out],
                         ["thinking", "text", "tool"])
        self.assertEqual(out[2]["name"], "Read")
        # The chip shows the thing the call was aimed at, not a JSON blob.
        self.assertEqual(out[2]["summary"], "/config/x.yaml")
        self.assertIn("file_path", out[2]["input"])

    def test_a_user_event_from_the_cli_is_a_tool_result(self):
        """Not something the person typed — the CLI feeds results back as
        user messages, and rendering those as user turns would put words in
        their mouth."""
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "content": [{"type": "text", "text": "file contents"}]},
        ]}})
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["type"], "tool_result")
        self.assertEqual(out[0]["id"], "t1")
        self.assertTrue(out[0]["ok"])
        self.assertEqual(out[0]["text"], "file contents")

    def test_a_failed_tool_result_is_marked_failed(self):
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1", "is_error": True,
             "content": "boom"},
        ]}})
        self.assertFalse(out[0]["ok"])
        self.assertEqual(out[0]["text"], "boom")

    def _result(self, text, is_error=True):
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t1",
             "is_error": is_error, "content": text},
        ]}})
        return out[0]

    def test_a_refused_tool_call_is_marked_refused_not_broken(self):
        """Headless `-p` cannot prompt, so a refusal is final — and "that
        broke" sends you debugging while "not allowed" sends you to
        Settings. The panel has to be able to tell them apart."""
        denied = self._result(
            "Claude requested permissions to use Bash, but you haven't "
            "granted it yet.")
        self.assertFalse(denied["ok"])
        self.assertTrue(denied["denied"])

    def test_an_ordinary_failure_is_not_called_a_refusal(self):
        self.assertFalse(self._result("boom")["denied"])
        self.assertFalse(self._result("Traceback: KeyError")["denied"])

    def test_a_kernel_eacces_is_not_a_policy_decision(self):
        """`Permission denied` is what the OS says when a perfectly
        permitted Bash call touches a file it cannot read. Calling that a
        permission-set refusal would send people to change a setting that
        was never in the way."""
        self.assertFalse(
            self._result("cat: /root/x: Permission denied")["denied"])
        self.assertFalse(
            self._result("bash: ./run.sh: Permission denied")["denied"])

    def test_a_success_is_never_a_refusal(self):
        ok = self._result("file contents", is_error=False)
        self.assertTrue(ok["ok"])
        self.assertFalse(ok["denied"])

    def test_an_error_result_becomes_a_notice_in_words(self):
        out = self.mod._normalise({
            "type": "result", "is_error": True, "subtype": "error_max_turns"})
        self.assertEqual(out[0]["type"], "notice")
        self.assertEqual(out[0]["level"], "error")
        self.assertIn("turn limit", out[0]["text"])

    def test_a_successful_result_is_a_footnote_not_a_transcript_entry(self):
        out = self.mod._normalise({
            "type": "result", "is_error": False, "duration_ms": 1234,
            "num_turns": 2, "total_cost_usd": 0.01})
        self.assertEqual(out[0]["type"], "result")
        self.assertFalse(out[0]["_keep"])
        self.assertEqual(out[0]["duration_ms"], 1234)

    def test_unknown_events_are_dropped_rather_than_rendered_raw(self):
        for event in ({"type": "system", "subtype": "init"},
                      {"type": "control_response"},
                      {"type": "something_new"}):
            self.assertEqual(self.mod._normalise(event), [])

    def test_a_giant_tool_result_is_clipped(self):
        out = self.mod._normalise({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "t", "content": "x" * 99999},
        ]}})
        self.assertLess(len(out[0]["text"]), self.mod.MAX_RESULT_CHARS + 100)
        self.assertIn("truncated", out[0]["text"])

    def test_the_chip_summary_falls_back_to_any_string_argument(self):
        self.assertEqual(
            self.mod.tool_summary("Weird", {"thing": "a value"}), "a value")
        self.assertEqual(self.mod.tool_summary("Weird", {}), "")
        self.assertEqual(self.mod.tool_summary("Weird", None), "")

    def test_the_chip_summary_is_one_line(self):
        summary = self.mod.tool_summary("Bash", {"command": "ls\n# and more"})
        self.assertEqual(summary, "ls")


class ChatSessionCase(unittest.IsolatedAsyncioTestCase):
    """The lifecycle, against a real subprocess."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["BRAIN_CHAT_TRANSCRIPT"] = os.path.join(self.tmp.name, "t.json")
        os.environ["BRAIN_CHAT_WORKDIR"] = self.tmp.name
        os.environ["BRAIN_CLAUDE_BIN"] = str(FAKE)
        # Explicit rather than popped: several tests below set a failure
        # mode, and "whatever the last test left" is not a fixture.
        os.environ["FAKE_CHAT_MODE"] = "ok"
        os.environ.pop("FAKE_CHAT_LOG", None)
        os.environ.pop("FAKE_CHAT_BROKEN", None)
        import engine
        importlib.reload(engine)
        import chat_session
        self.mod = importlib.reload(chat_session)
        self.session = self.mod.ChatSession()

    async def asyncTearDown(self):
        await self.session.stop()
        self.tmp.cleanup()

    async def _invocations(self, log, count, timeout=5.0):
        """The argv of each spawn so far, once there are ``count`` of them.

        create_subprocess_exec returns as soon as the child is forked, not
        once it has run — so reading the log straight after a restart races
        the child's first write and passes or fails by scheduling luck.
        """
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        lines = []
        while loop.time() < deadline:
            try:
                lines = [json.loads(l)
                         for l in Path(log).read_text().splitlines() if l.strip()]
            except OSError:
                lines = []
            if len(lines) >= count:
                return lines
            await asyncio.sleep(0.05)
        # `raise`, not `self.fail` — same failure, but the function now has
        # one kind of exit rather than a return and a fall-through.
        raise AssertionError(f"only {len(lines)} of {count} spawns were logged")

    async def _drain(self, until, timeout=10.0):
        """Collect events until ``until(events)`` is true, or give up."""
        queue = self.session.subscribe()
        got = []
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        try:
            while loop.time() < deadline:
                remaining = deadline - loop.time()
                try:
                    got.append(await asyncio.wait_for(queue.get(), remaining))
                except asyncio.TimeoutError:
                    break
                if until(got):
                    return got
        finally:
            self.session.unsubscribe(queue)
        return got

    async def test_a_turn_produces_the_events_the_panel_draws(self):
        await self.session.start()
        self.assertTrue(self.session.alive())
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "state" and e.get("state") == "ready"
                            for e in evs[1:])))
        await asyncio.sleep(0.05)
        await self.session.send("why is the porch light off")
        events = await task
        kinds = [e["type"] for e in events]
        for expected in ("text_delta", "thinking", "text", "tool",
                         "tool_result", "result"):
            self.assertIn(expected, kinds, f"no {expected} in {kinds}")
        tool = next(e for e in events if e["type"] == "tool")
        self.assertEqual(tool["name"], "Read")
        result = next(e for e in events if e["type"] == "tool_result")
        self.assertEqual(result["id"], tool["id"])

    async def test_context_is_one_model_call_not_the_whole_turn(self):
        """The pill measures the conversation, not the work.

        The fixture's turn is two model calls — 41.2k then 41.8k — and a
        result envelope carrying their sum. Reading that envelope is what
        made the pill claim more tokens than the window it was measuring
        against, and it got worse the more tools a turn used.
        """
        await self.session.start()
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "state" and e.get("state") == "ready"
                            for e in evs[1:])))
        await asyncio.sleep(0.05)
        await self.session.send("why is the porch light off")
        events = await task

        contexts = [e for e in events if e.get("type") == "context"]
        self.assertTrue(contexts, "the panel was never told how full the context is")
        self.assertEqual(contexts[-1]["tokens"], 41_800)
        self.assertEqual(self.session.context["tokens"], 41_800)
        self.assertLess(self.session.context["tokens"],
                        self.session.context["window"])

    async def test_the_transcript_survives_a_restart_but_the_deltas_dont(self):
        await self.session.start()
        await self.session.send("hello")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        await self.session.stop()

        reloaded = self.mod.ChatSession()
        kinds = [e["type"] for e in reloaded.events]
        self.assertIn("user", kinds)
        self.assertIn("text", kinds)
        self.assertNotIn("text_delta", kinds, "a reload would repeat every answer")
        self.assertNotIn("result", kinds, "run stats are about a run, not the record")
        self.assertEqual(reloaded.session_id, self.session.session_id)

    async def test_a_new_chat_does_not_resume_the_old_one(self):
        """Keeping the resume id would make "New chat" mean "same
        conversation, blank screen" — the one thing it must not mean."""
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        await self.session.start()
        await self.session.send("first")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        self.assertTrue(self.session.session_id)

        await self.session.reset()
        self.assertEqual(self.session.events, [])
        # No assertion that session_id is still None here: start() now waits
        # for the CLI's first event, so by the time reset() returns the FRESH
        # session may already have announced its own id. What "new chat"
        # must mean is on the argv — no --resume — not in that race.
        invocations = await self._invocations(log, 2)
        self.assertNotIn("--resume", invocations[-1])

    async def test_a_second_turn_while_busy_is_refused(self):
        os.environ["FAKE_CHAT_MODE"] = "hang"
        await self.session.start()
        await self.session.send("one")
        await asyncio.sleep(0.3)
        self.assertEqual(self.session.state, "busy")
        with self.assertRaises(RuntimeError):
            await self.session.send("two")

    async def test_a_current_cli_is_stopped_by_asking(self):
        """When the control request is answered, nothing is killed and the
        session carries straight on."""
        os.environ["FAKE_CHAT_MODE"] = "hang"
        self.mod.INTERRUPT_GRACE = 3.0
        await self.session.start()
        proc = self.session.proc
        await self.session.send("hang please")
        await asyncio.sleep(0.3)
        out = await self.session.interrupt()
        self.assertEqual(out["method"], "interrupt")
        self.assertIs(self.session.proc, proc, "it killed a session that answered")
        self.assertEqual(self.session.state, "ready")

    async def test_an_older_cli_is_stopped_by_killing_and_resuming(self):
        """The polite interrupt is what a current CLI answers; an older one
        ignores it silently, which is indistinguishable from thinking. So
        the fallback is unconditional and the conversation survives it,
        because the CLI is the thing that persisted it."""
        os.environ["FAKE_CHAT_MODE"] = "deaf"
        self.mod.INTERRUPT_GRACE = 0.4
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        await self.session.start()
        await self.session.send("hang please")
        await asyncio.sleep(0.3)
        out = await self.session.interrupt()
        self.assertEqual(out["method"], "restart")
        self.assertTrue(self.session.alive())
        invocations = await self._invocations(log, 2)
        self.assertIn("--resume", invocations[-1],
                      "the restart threw the conversation away")

    async def test_a_crash_mid_turn_reports_instead_of_hanging(self):
        os.environ["FAKE_CHAT_MODE"] = "crash"
        await self.session.start()
        events = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "state" and e.get("state") == "error"
                            for e in evs),
            timeout=6))
        await asyncio.sleep(0.05)
        await self.session.send("boom")
        got = await events
        self.assertTrue(any(e.get("state") == "error" for e in got),
                        "a dead session left the page waiting forever")

    async def test_an_error_envelope_is_shown_as_a_notice(self):
        os.environ["FAKE_CHAT_MODE"] = "error"
        await self.session.start()
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "notice" for e in evs)))
        await asyncio.sleep(0.05)
        await self.session.send("hit the cap")
        got = await task
        notice = next(e for e in got if e["type"] == "notice")
        self.assertIn("turn limit", notice["text"])

    async def test_the_session_reports_what_the_cli_says_about_itself(self):
        """The model, the version, and two facts that are load-bearing: the
        working directory (which is what `claude --resume` keys conversations
        by) and whether an API key is paying."""
        await self.session.start()
        await asyncio.sleep(0.4)
        info = self.session.info
        self.assertEqual(info["model"], "claude-sonnet-5")
        self.assertEqual(info["cwd"], self.tmp.name)
        self.assertEqual(info["api_key_source"], "none")
        self.assertEqual(self.session.snapshot()["info"], info)

    async def test_the_command_list_is_the_clis_own(self):
        """A hardcoded list is wrong the first time someone drops a command
        into /config/.claude/commands. The CLI announces its own."""
        await self.session.start()
        await asyncio.sleep(0.4)
        names = [c["name"] for c in self.session.commands]
        self.assertIn("compact", names)
        self.assertIn("model", names)
        self.assertNotIn("__internal", names, "internal plumbing is not a command")
        self.assertEqual(names, sorted(names))
        model = next(c for c in self.session.commands if c["name"] == "model")
        self.assertEqual(model["hint"], "[model]")
        self.assertTrue(model["description"])

    async def test_a_slash_command_is_sent_as_an_ordinary_message(self):
        """They are not a client-side feature to reimplement — the CLI
        executes them itself when they arrive as text."""
        await self.session.start()
        task = asyncio.create_task(self._drain(
            lambda evs: any(e.get("type") == "text" for e in evs)))
        await asyncio.sleep(0.05)
        await self.session.send("/compact")
        got = await task
        user = next(e for e in got if e["type"] == "user")
        self.assertEqual(user["text"], "/compact")

    async def test_handing_off_releases_the_session_and_names_it(self):
        """While the panel holds the conversation open, the terminal is being
        asked to resume something still in use."""
        await self.session.start()
        await self.session.send("hello")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        sid = self.session.session_id
        self.assertTrue(sid)
        out = await self.session.handoff()
        self.assertEqual(out["session_id"], sid)
        self.assertEqual(out["command"], f"claude --resume {sid}")
        self.assertFalse(self.session.alive(), "the session is still held open")
        # The transcript is untouched — this is a handover, not a reset.
        self.assertTrue(self.session.events)

    async def test_resuming_replays_the_conversation_into_the_pane(self):
        """"Interchangeable" has to mean you can see what was said. A pane
        that opens empty with a promise that Claude remembers is a handoff,
        not a swap."""
        replay = [
            {"type": "user", "text": "why is the porch light off"},
            {"type": "text", "text": "Its trigger never fires."},
        ]
        out = await self.session.resume("dead-beef", replay)
        self.assertEqual(out["session_id"], "dead-beef")
        self.assertEqual(self.session.session_id, "dead-beef")
        self.assertEqual([e["type"] for e in self.session.events],
                         ["user", "text"])
        # And it survives a reload, like any other transcript.
        reloaded = self.mod.ChatSession()
        self.assertEqual(len(reloaded.events), 2)
        self.assertEqual(reloaded.session_id, "dead-beef")

    async def test_resuming_a_conversation_we_cannot_replay_still_says_so(self):
        out = await self.session.resume("dead-beef", [])
        self.assertTrue(out["ok"])
        self.assertEqual(self.session.events[0]["type"], "notice")

    async def test_a_working_resume_reports_that_it_resumed(self):
        out = await self.session.resume("dead-beef", [])
        self.assertTrue(out["resumed"])
        self.assertEqual(out["session_id"], "dead-beef")

    async def test_a_resume_the_cli_refuses_falls_back_to_a_fresh_session(self):
        """The docstring always promised this fallback; it has to be real.

        A conversation pruned from the CLI's store used to leave a chat tab
        that spawned, died silently, and errored on every send — with the
        restored resume id respawning the same failure forever. The spawn is
        watched now: died-before-speaking with --resume on the argv drops
        the id, says so in the transcript, and opens fresh.
        """
        os.environ["FAKE_CHAT_MODE"] = "noresume"
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        out = await self.session.resume("gone-forever",
                                        [{"type": "user", "text": "old history"}])
        self.assertTrue(out["ok"])
        self.assertFalse(out["resumed"])
        self.assertTrue(self.session.alive(), "no session to type into")
        self.assertNotEqual(self.session.session_id, "gone-forever")
        # Two spawns: the refused resume, then the fresh one without it.
        invocations = await self._invocations(log, 2)
        self.assertIn("--resume", invocations[0])
        self.assertNotIn("--resume", invocations[1])
        # The transcript keeps the replayed history AND says what happened —
        # a pane that silently forgot its context is worse than one that
        # admits it.
        kinds = [e["type"] for e in self.session.events]
        self.assertIn("user", kinds)
        notice = next(e for e in self.session.events
                      if e["type"] == "notice" and "resume" in e["text"])
        self.assertIn("fresh", notice["text"])

    async def test_a_resume_refused_in_band_falls_back_deterministically(self):
        """A current CLI (2.1.x) refuses a --resume by emitting an error
        `result` event — "No conversation found with session ID" — and may
        stay alive a moment before exiting. Watching for the death alone
        made the fallback a coin flip between the honest notice and a
        cryptic `error_during_execution` beside a doomed resume id that
        every later spawn retried. The event is the deterministic signal.
        """
        os.environ["FAKE_CHAT_MODE"] = "noresume-live"
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        out = await self.session.resume("gone-forever",
                                        [{"type": "user", "text": "old history"}])
        self.assertTrue(out["ok"])
        self.assertFalse(out["resumed"])
        self.assertTrue(self.session.alive(), "no session to type into")
        invocations = await self._invocations(log, 2)
        self.assertIn("--resume", invocations[0])
        self.assertNotIn("--resume", invocations[1])
        # The honest notice, carrying the CLI's own reason — and not the
        # raw error envelope, which reads as a crash and names nothing.
        notice = next(e for e in self.session.events
                      if e["type"] == "notice" and "resume" in e["text"])
        self.assertIn("No conversation found", notice["text"])
        self.assertFalse(
            [e for e in self.session.events
             if e.get("text") == "error_during_execution"],
            "the raw error envelope leaked into the transcript")

    async def test_a_fresh_spawn_that_dies_is_an_error_not_a_shrug(self):
        """Died-before-speaking with nothing to resume is a startup failure,
        and the stderr tail is the only witness — it must reach the state."""
        os.environ["FAKE_CHAT_MODE"] = "noresume"
        self.session.session_id = "gone-forever"
        # Both spawns refuse: the fallback's fresh spawn dies too.
        os.environ["FAKE_CHAT_BROKEN"] = "1"
        try:
            await self.session.start()
        finally:
            os.environ.pop("FAKE_CHAT_BROKEN", None)
        self.assertEqual(self.session.state, "error")
        self.assertTrue(self.session.error)

    async def test_changing_the_model_restarts_with_resume(self):
        """The model is an argv flag, so a live session keeps the one it was
        started with — applying a new one is a stop and a --resume, the same
        trick stopping an old CLI already relies on."""
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        await self.session.start()
        await self.session.send("hello")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        sid = self.session.session_id

        out = await self.session.set_model("claude-opus-5")
        self.assertTrue(out["restarted"])
        self.assertTrue(self.session.alive())
        invocations = await self._invocations(log, 2)
        argv = invocations[-1]
        self.assertIn("--model", argv)
        self.assertEqual(argv[argv.index("--model") + 1], "claude-opus-5")
        self.assertIn("--resume", argv, "the model change threw the conversation away")
        self.assertEqual(argv[argv.index("--resume") + 1], sid)

    async def test_setting_the_model_it_already_runs_is_a_no_op(self):
        await self.session.start()
        self.session.model = "claude-opus-5"
        out = await self.session.set_model("claude-opus-5")
        self.assertFalse(out["restarted"])

    async def test_a_model_change_mid_answer_is_refused(self):
        os.environ["FAKE_CHAT_MODE"] = "hang"
        await self.session.start()
        await self.session.send("thinking…")
        await asyncio.sleep(0.3)
        with self.assertRaises(RuntimeError):
            await self.session.set_model("claude-opus-5")

    async def test_resuming_nothing_is_refused(self):
        with self.assertRaises(ValueError):
            await self.session.resume("", [])

    async def test_the_handoff_leaves_the_terminal_something_to_pick_up(self):
        """The file is the contract — brain-terminal-start reads it on
        launch, so even a terminal that has never been opened comes up
        inside the conversation. The tmux window is the nicety on top."""
        handoff = os.path.join(self.tmp.name, "handoff.json")
        self.mod.HANDOFF_FILE = handoff
        self.mod.TMUX_SESSION = "brain-test-nosuch"
        await self.session.start()
        await self.session.send("hello")
        await self._drain(lambda evs: any(
            e.get("type") == "state" and e.get("state") == "ready" for e in evs[1:]))
        out = await self.session.handoff()
        written = json.loads(Path(handoff).read_text())
        self.assertEqual(written["session_id"], out["session_id"])
        self.assertIsInstance(written["ts"], int)
        # No tmux server for that session name here, so it reports honestly
        # rather than claiming to have opened a window.
        self.assertFalse(out["opened"])

    async def test_an_empty_message_is_refused(self):
        with self.assertRaises(ValueError):
            await self.session.send("   ")

    async def test_a_subscriber_that_stopped_reading_is_dropped_not_grown(self):
        """A suspended phone must not grow a queue until the add-on runs out
        of memory; it reconnects to a snapshot instead."""
        queue = self.session.subscribe()
        for _ in range(queue.maxsize + 5):
            self.session._emit({"type": "notice", "text": "x"}, keep=False)
        self.assertNotIn(queue, self.session._subs)

    async def test_the_transcript_is_capped(self):
        self.mod.MAX_EVENTS = 10
        for i in range(40):
            self.session._emit({"type": "notice", "text": str(i)})
        self.assertEqual(len(self.session.events), 10)
        self.assertEqual(self.session.events[-1]["text"], "39")


class TestChatRoutes(unittest.IsolatedAsyncioTestCase):
    """The API the panel actually calls, including the SSE stream."""

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        for key, value in {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(self.tmp.name, "t.json"),
            "BRAIN_CHAT_WORKDIR": self.tmp.name,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_SETTINGS_FILE": os.path.join(self.tmp.name, "settings.json"),
            "BRAIN_DIR": os.path.join(self.tmp.name, "insights"),
            "BRAIN_SECRETS": os.path.join(self.tmp.name, "secrets"),
            "BRAIN_RUN_SOURCES": os.path.join(self.tmp.name, "run-sources.jsonl"),
            "BRAIN_CHAT_TRASH": os.path.join(self.tmp.name, "chat-trash"),
            "BRAIN_CHAT_TITLES": os.path.join(self.tmp.name, "chat-titles.json"),
        }.items():
            os.environ[key] = value
        os.environ.pop("FAKE_CHAT_MODE", None)
        for name in ("engine", "settings_store", "run_sources", "conversations",
                     "chat_session", "server"):
            module = importlib.import_module(name)
            setattr(self, name, importlib.reload(module))

        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        await self.client.close()
        self.tmp.cleanup()

    async def test_the_stream_opens_with_a_snapshot(self):
        """One request, not two: a client that has to stitch "what the
        transcript was" onto "what happened next" drops an event eventually."""
        resp = await self.client.get("/api/chat/stream")
        self.assertEqual(resp.status, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
        line = await asyncio.wait_for(resp.content.readline(), 5)
        payload = json.loads(line.decode().split("data: ", 1)[1])
        self.assertEqual(payload["type"], "snapshot")
        self.assertIn("state", payload)
        self.assertEqual(payload["events"], [])
        resp.close()

    async def test_a_message_streams_back_as_events(self):
        resp = await self.client.get("/api/chat/stream")
        await asyncio.wait_for(resp.content.readline(), 5)   # snapshot
        await asyncio.wait_for(resp.content.readline(), 5)   # blank

        send = await self.client.post("/api/chat/send", json={"text": "hello"})
        self.assertEqual(send.status, 200)

        kinds = set()
        deadline = asyncio.get_running_loop().time() + 10
        while asyncio.get_running_loop().time() < deadline:
            line = await asyncio.wait_for(resp.content.readline(), 5)
            text = line.decode()
            if not text.startswith("data: "):
                continue
            event = json.loads(text[6:])
            kinds.add(event.get("type"))
            # "ready" fires twice — once when the session spins up and again
            # when the turn lands. Only the second one ends this loop.
            if ("user" in kinds and event.get("type") == "state"
                    and event.get("state") == "ready"):
                break
        resp.close()
        for expected in ("user", "text", "tool", "tool_result"):
            self.assertIn(expected, kinds, f"no {expected} in {sorted(kinds)}")

    async def test_an_empty_message_is_a_400(self):
        resp = await self.client.post("/api/chat/send", json={"text": " "})
        self.assertEqual(resp.status, 400)

    async def test_the_snapshot_carries_the_session_facts(self):
        """A viewer who connects after startup would otherwise never see the
        model, the project directory or the command list — the CLI announces
        them once and does not repeat itself."""
        resp = await self.client.post("/api/chat/send", json={"text": "hi"})
        self.assertEqual(resp.status, 200)
        await asyncio.sleep(0.6)
        snap = await (await self.client.get("/api/chat/state")).json()
        self.assertEqual(snap["info"]["api_key_source"], "none")
        self.assertTrue(snap["info"]["model"])
        self.assertIn("compact", [c["name"] for c in snap["commands"]])
        self.assertTrue(snap["session_id"])

    async def test_handoff_stops_the_session_and_returns_the_command(self):
        await self.client.post("/api/chat/send", json={"text": "hi"})
        await asyncio.sleep(0.6)
        out = await (await self.client.post("/api/chat/handoff")).json()
        self.assertTrue(out["session_id"])
        self.assertTrue(out["command"].startswith("claude --resume "))
        self.assertEqual((await (await self.client.get("/api/chat/state")).json())["state"],
                         "idle")

    def _fake_conversation(self, session_id, text, age_s=0):
        """A transcript in Claude Code's own store, as the classic terminal
        would have left one behind."""
        import conversations
        project = (Path(self.tmp.name) / "projects"
                   / re.sub(r"[^A-Za-z0-9]", "-", self.tmp.name))
        project.mkdir(parents=True, exist_ok=True)
        path = project / f"{session_id}.jsonl"
        path.write_text(json.dumps({
            "type": "user", "cwd": self.tmp.name,
            "message": {"role": "user", "content": text}}) + "\n"
            + "x" * 300 + "\n", encoding="utf-8")
        if age_s:
            when = time.time() - age_s
            os.utime(path, (when, when))
        conversations.CONFIG_DIR = self.tmp.name
        return path

    async def test_switching_back_to_chat_picks_up_the_terminal(self):
        """The other half of the handoff. We cannot ask the tmux Claude what
        it is doing, but Claude Code writes its transcript as it goes, so the
        most recently written conversation IS what the terminal was last on.
        Without this, switching back lands you in a different conversation
        and the two faces are two rooms."""
        self._fake_conversation("older-one", "an older chat", age_s=7200)
        self._fake_conversation("terminal-one", "what the terminal was doing")

        out = await (await self.client.post("/api/chat/adopt")).json()
        self.assertTrue(out["adopted"])
        self.assertEqual(out["session_id"], "terminal-one")
        self.assertEqual(out["title"], "what the terminal was doing")

        snap = await (await self.client.get("/api/chat/state")).json()
        self.assertEqual(snap["session_id"], "terminal-one")
        # ...and the conversation is on screen, not merely promised
        self.assertIn("what the terminal was doing",
                      [e.get("text") for e in snap["events"]])

    async def test_adopting_the_conversation_we_are_already_in_is_a_no_op(self):
        await self.client.post("/api/chat/send", json={"text": "hi"})
        await asyncio.sleep(0.6)
        current = (await (await self.client.get("/api/chat/state")).json())["session_id"]
        self._fake_conversation(current, "the one we are already in")

        out = await (await self.client.post("/api/chat/adopt")).json()
        self.assertFalse(out["adopted"])
        self.assertEqual(out["session_id"], current)

    async def test_nothing_to_adopt_is_not_an_error(self):
        """A first run has no store at all. Switching faces must still work —
        not finding a conversation to carry is a worse chat, not a broken
        button."""
        import conversations
        conversations.CONFIG_DIR = os.path.join(self.tmp.name, "nothing-here")
        out = await (await self.client.post("/api/chat/adopt")).json()
        self.assertFalse(out["adopted"])

    async def test_adopting_mid_answer_is_refused(self):
        """Adopting stops our process. Losing an answer being written is
        worse than making somebody wait for it."""
        self._fake_conversation("terminal-one", "what the terminal was doing")
        os.environ["FAKE_CHAT_MODE"] = "slow"
        self.chat_session.session().state = "busy"
        try:
            resp = await self.client.post("/api/chat/adopt")
            self.assertEqual(resp.status, 409)
        finally:
            os.environ["FAKE_CHAT_MODE"] = "ok"
            self.chat_session.session().state = "idle"

    # ---------------------------------------------------------------
    # Who ran what.
    #
    # /config is not only where you type: voice, the automation listener
    # and the memory consolidator drive the same Claude Code from there,
    # and Claude Code files all of it in one directory. Left alone, the
    # rail became a column of near-identical machine prompts with a
    # person's own chats somewhere underneath, and "switch back from the
    # terminal" adopted whichever of them had run most recently.
    # ---------------------------------------------------------------

    def _claim(self, session_id, source):
        self.assertTrue(self.run_sources.record(session_id, source))

    async def test_the_rail_shows_yours_and_says_so_for_the_rest(self):
        self._fake_conversation("mine", "why is the porch light on", age_s=60)
        self._fake_conversation("machine", "You maintain a small long-term memory file")
        self._claim("machine", "memory")

        data = await (await self.client.get("/api/chat/conversations")).json()
        self.assertEqual([c["id"] for c in data["conversations"]], ["mine"])
        self.assertEqual(data["conversations"][0]["source"], "you")

        data = await (await self.client.get(
            "/api/chat/conversations?source=memory")).json()
        self.assertEqual([c["id"] for c in data["conversations"]], ["machine"])
        self.assertEqual(data["conversations"][0]["source"], "memory")

        # ...and nothing is hidden: "all" is still one request away.
        data = await (await self.client.get(
            "/api/chat/conversations?source=all")).json()
        self.assertEqual({c["id"] for c in data["conversations"]},
                         {"mine", "machine"})

    async def test_the_filter_only_offers_faces_that_have_run_here(self):
        """A house with no voice assistant should not be given a Voice
        filter that is empty forever, or told the concept exists."""
        self._fake_conversation("mine", "hello")
        data = await (await self.client.get("/api/chat/conversations")).json()
        self.assertEqual([s["id"] for s in data["sources"]], ["you"])

        self._fake_conversation("v1", "turn off the kitchen lights")
        self._claim("v1", "voice")
        data = await (await self.client.get("/api/chat/conversations")).json()
        self.assertEqual([s["id"] for s in data["sources"]], ["you", "voice"])
        self.assertEqual([s["count"] for s in data["sources"]], [1, 1])

    async def test_a_full_page_of_machine_chats_still_returns_yours(self):
        """Filtering server-side is what makes the page size mean rows you
        asked for. A house whose voice assistant makes a session per
        command would otherwise spend a whole page on those."""
        for n in range(40):
            self._claim(f"v{n}", "voice")
            self._fake_conversation(f"v{n}", f"voice turn {n}")
        self._fake_conversation("mine", "the one I actually had", age_s=7200)

        data = await (await self.client.get("/api/chat/conversations")).json()
        self.assertEqual([c["id"] for c in data["conversations"]], ["mine"])

    async def test_switching_back_never_adopts_a_machines_conversation(self):
        """The consolidator writes a transcript on its own schedule, so on a
        busy house the newest file in /config was routinely not yours."""
        self._fake_conversation("terminal-one", "what the terminal was doing",
                                age_s=120)
        self._fake_conversation("consolidator", "You maintain a small memory file")
        self._claim("consolidator", "memory")

        out = await (await self.client.post("/api/chat/adopt")).json()
        self.assertTrue(out["adopted"])
        self.assertEqual(out["session_id"], "terminal-one")

    async def test_the_chat_model_is_the_chats_own_choice(self):
        """Picked from the chat, stored as the panel's chat_model — never
        the global model option, which would silently change what every
        insight run costs."""
        snap = await (await self.client.get("/api/chat/state")).json()
        self.assertTrue(snap["models"], "the picker has nothing to offer")
        self.assertEqual(snap["chat_model"], "")

        resp = await self.client.post("/api/chat/model",
                                      json={"model": "claude-haiku-4-5"})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["chat_model"], "claude-haiku-4-5")
        snap = await (await self.client.get("/api/chat/state")).json()
        self.assertEqual(snap["chat_model"], "claude-haiku-4-5")
        settings = (await (await self.client.get("/api/settings")).json())["settings"]
        self.assertFalse(settings["model"], "the chat's choice leaked global")

        # Clearing it follows the global model again.
        resp = await self.client.post("/api/chat/model", json={"model": None})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["chat_model"], "")

    async def test_the_chat_model_reaches_the_spawn(self):
        log = os.path.join(self.tmp.name, "argv.log")
        os.environ["FAKE_CHAT_LOG"] = log
        try:
            await self.client.post("/api/chat/model",
                                   json={"model": "claude-haiku-4-5"})
            await self.client.post("/api/chat/send", json={"text": "hi"})
            await asyncio.sleep(0.6)
            argv = [json.loads(l) for l in Path(log).read_text().splitlines()][-1]
            self.assertIn("--model", argv)
            self.assertEqual(argv[argv.index("--model") + 1], "claude-haiku-4-5")
        finally:
            os.environ.pop("FAKE_CHAT_LOG", None)

    async def test_deleting_a_conversation_offers_a_working_undo(self):
        self._fake_conversation("goner", "delete me please", age_s=60)
        self._fake_conversation("keeper", "leave me alone")

        resp = await self.client.post("/api/chat/conversation/goner/delete")
        self.assertEqual(resp.status, 200)
        out = await resp.json()
        self.assertEqual(out["deleted"], "goner")
        self.assertTrue(out["undo"])
        data = await (await self.client.get(
            "/api/chat/conversations?source=all")).json()
        self.assertEqual([c["id"] for c in data["conversations"]], ["keeper"])

        undo = await (await self.client.post(f"/api/undo/{out['undo']}")).json()
        self.assertTrue(undo["undone"])
        self.assertEqual(undo["restored_conversation"], "goner")
        data = await (await self.client.get(
            "/api/chat/conversations?source=all")).json()
        self.assertEqual({c["id"] for c in data["conversations"]},
                         {"goner", "keeper"})

    async def test_deleting_the_open_conversation_is_refused(self):
        """Deleting the ground the live session stands on either kills it or
        quietly forks it — "start a new chat first" beats both."""
        await self.client.post("/api/chat/send", json={"text": "hi"})
        await asyncio.sleep(0.6)
        current = (await (await self.client.get("/api/chat/state")).json())["session_id"]
        path = self._fake_conversation(current, "the open one")
        resp = await self.client.post(f"/api/chat/conversation/{current}/delete")
        self.assertEqual(resp.status, 409)
        self.assertTrue(path.is_file(), "refused, but deleted it anyway")

    async def test_deleting_a_conversation_that_is_not_there_is_a_404(self):
        resp = await self.client.post("/api/chat/conversation/never-was/delete")
        self.assertEqual(resp.status, 404)

    async def test_renaming_a_conversation_overlays_the_derived_title(self):
        """The name is panel-side metadata: Claude Code has no title concept,
        so the CLI's file is never touched — and clearing the name brings the
        opening-message title back rather than pinning an empty one."""
        path = self._fake_conversation("keeper", "the opening message")
        before = path.read_bytes()

        resp = await self.client.post(
            "/api/chat/conversation/keeper/rename",
            json={"title": "  Frame TV   automation  "})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["title"], "Frame TV automation")
        data = await (await self.client.get(
            "/api/chat/conversations?source=all")).json()
        row = next(c for c in data["conversations"] if c["id"] == "keeper")
        self.assertEqual(row["title"], "Frame TV automation")
        self.assertTrue(row["renamed"])
        self.assertEqual(path.read_bytes(), before,
                         "renaming edited the CLI's own file")

        resp = await self.client.post(
            "/api/chat/conversation/keeper/rename", json={"title": ""})
        self.assertEqual(resp.status, 200)
        data = await (await self.client.get(
            "/api/chat/conversations?source=all")).json()
        row = next(c for c in data["conversations"] if c["id"] == "keeper")
        self.assertEqual(row["title"], "the opening message")
        self.assertFalse(row["renamed"])

    async def test_renaming_a_conversation_that_is_not_there_is_a_404(self):
        """No stored names for ghosts — and no path is built from an id that
        could not be one."""
        resp = await self.client.post(
            "/api/chat/conversation/never-was/rename", json={"title": "x"})
        self.assertEqual(resp.status, 404)
        resp = await self.client.post(
            "/api/chat/conversation/..%2Fescape/rename", json={"title": "x"})
        self.assertNotEqual(resp.status, 200)

    async def test_the_terminal_ui_setting_round_trips(self):
        resp = await self.client.get("/api/settings")
        self.assertEqual((await resp.json())["settings"]["terminal_ui"], "chat")
        resp = await self.client.put("/api/settings", json={"terminal_ui": "classic"})
        self.assertEqual(resp.status, 200)
        self.assertEqual((await resp.json())["settings"]["terminal_ui"], "classic")
        resp = await self.client.get("/api/status")
        self.assertEqual((await resp.json())["settings"]["terminal_ui"], "classic")
        resp = await self.client.put("/api/settings", json={"terminal_ui": "vim"})
        self.assertEqual(resp.status, 400)


class TestChatChrome(unittest.TestCase):
    """The parts of the chat tab that are markup and CSS rather than events."""

    @classmethod
    def setUpClass(cls):
        cls.js = (PANEL / "app.js").read_text()
        cls.css = (PANEL / "style.css").read_text()
        cls.html = (PANEL / "index.html").read_text()

    def test_the_last_message_is_not_flush_against_the_composer(self):
        """Scrolled fully down, 8px of bottom padding put the last line of an
        answer hard against the composer's border — which reads as the
        message being cut off rather than as the end of it."""
        block = self.css.split(".chatlog {")[1].split("}")[0]
        pad = block.split("padding:")[1].split(";")[0].split()
        self.assertGreaterEqual(int(pad[2].replace("px", "")), 20)

    def test_the_safe_area_inset_is_on_whatever_is_bottom_most(self):
        """The meta line sits BELOW the composer, so the composer is no
        longer the thing that has to clear an iPhone's home indicator — and
        which element is last depends on whether the meta line is showing.
        The container is always last, so it carries the inset."""
        chat = self.css.split("\n.chat {")[1].split("}")[0]
        self.assertIn("env(safe-area-inset-bottom)", chat)
        self.assertIn("box-sizing: border-box", chat)
        bar = self.css.split(".chatbar {")[1].split("}")[0]
        self.assertNotIn("safe-area-inset", bar)

    def test_the_rail_is_a_wide_screen_affordance_only(self):
        """248px of conversations is most of a phone. Below the breakpoint
        the rail is not rendered and ⋯ → Conversations is still the way in,
        so nothing is only reachable from a screen you don't have."""
        self.assertIn('id="chatRail"', self.html)
        self.assertIn('id="chatOpen"', self.html)   # the menu route survives
        self.assertIn(".chatrail {\n  display: none;", self.css)
        self.assertIn("@media (min-width: 1100px)", self.css)

    def test_a_new_chat_does_not_claim_the_old_one_is_lost(self):
        """Claude Code keeps the conversation and it stays in the list, so
        "Claude forgets its context" overstated what a new chat costs."""
        self.assertNotIn("Claude forgets its context", self.js)
        self.assertIn("This one is kept", self.js)

    def test_an_unknown_model_gets_a_count_and_no_percentage(self):
        """A percentage of a guessed context window is worse than none."""
        self.assertIn("tokens of context", self.js)
        self.assertIn("if (ctx.window > 0)", self.js)


if __name__ == "__main__":
    unittest.main()
