#!/usr/bin/env python3
"""Ask follows the saved face, each viewer's conversation is its own, and
the terminal's Claudes are counted, listed and never opened twice.

The audit's findings, one class each:

* **Ask on a card flipped back to an empty chat.** The panel flipped its
  face locally to the terminal without saving it, so the next status poll
  put the saved face back. ``POST /api/ask`` decides on the SAVED face: a
  new chat conversation holding the prompt, or a terminal window.
* **Every device shared one "current conversation".** The phone sends into
  A; a desktop opens B; the phone's next message landed in B. Every action
  now names its conversation (``session_key`` / ``session_id``).
* **The terminal's Claudes were invisible and unbounded**, a second
  ``--resume`` could open beside a window already holding one, and one
  fixed handoff file raced between two quick asks.
* **Requests waited out START_GRACE** (10 s per spawn attempt) before
  answering, long enough for a proxy to give up on them.
"""

import asyncio
import importlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

import pytest

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
FAKE = Path(__file__).resolve().parent / "fake_claude_chat.py"
sys.path.insert(0, str(PANEL))

pytestmark = pytest.mark.slow

import findings_store  # noqa: E402

_ENV = ("BRAIN_CHAT_TRANSCRIPT", "BRAIN_CHAT_TRANSCRIPT_DIR", "BRAIN_CHAT_WORKDIR",
        "BRAIN_CLAUDE_BIN", "BRAIN_SETTINGS_FILE", "BRAIN_DIR", "BRAIN_SECRETS",
        "BRAIN_RUN_SOURCES", "BRAIN_CHAT_TRASH", "BRAIN_TERMINAL_HANDOFF",
        "BRAIN_CHAT_CONTEXT_HOOK", "BRAIN_JOURNAL_FILE", "BRAIN_USAGE_NUDGE",
        "BRAIN_USAGE_FILE", "BRAIN_MEMINFO", "BRAIN_CHAT_START_GRACE",
        "FAKE_CHAT_MODE", "FAKE_CHAT_DELAY", "BRAIN_TMUX_SESSION")


class FakeTmux:
    """tmux as far as the panel asks it anything: sessions, windows tagged
    with user options, and the four verbs it uses."""

    def __init__(self, sessions=("claude",)):
        self.sessions = list(sessions)
        self.windows: list[dict] = []
        self.calls: list[list[str]] = []
        self._next = 1

    def add_window(self, session_id="", nonce="n0", idle_s=0.0,
                   tmux_session="claude"):
        wid = f"@{self._next}"
        self._next += 1
        self.windows.append({"id": wid, "session": tmux_session,
                             "sid": session_id, "nonce": nonce,
                             "activity": time.time() - idle_s,
                             "argv": []})
        return wid

    def __call__(self, args, timeout=5):
        self.calls.append(list(args))
        verb = args[0]
        out, code = "", 0

        def opt(flag):
            return args[args.index(flag) + 1] if flag in args else ""

        if verb == "list-sessions":
            out = "\n".join(self.sessions)
            code = 0 if self.sessions else 1
        elif verb == "list-windows":
            out = "\n".join(
                "\t".join([w["session"], w["id"], "0", w["sid"], w["nonce"],
                           "0", str(int(w["activity"])), "claude"])
                for w in self.windows)
        elif verb in ("new-window", "new-session"):
            target = opt("-t") if verb == "new-window" else opt("-s")
            if verb == "new-window" and target not in self.sessions:
                code = 1
            else:
                if verb == "new-session":
                    self.sessions.append(target)
                wid = self.add_window(nonce="", tmux_session=target)
                self.windows[-1]["argv"] = args[args.index(opt("-c")) + 1:]
                out = wid
        elif verb == "set-option":
            w = next((w for w in self.windows if w["id"] == opt("-t")), None)
            if w is None:
                code = 1
            else:
                name, value = args[-2], args[-1]
                w["nonce" if name == "@brain_nonce" else "sid"] = value
        elif verb == "select-window":
            code = 0 if any(w["id"] == opt("-t") for w in self.windows) else 1
        elif verb == "kill-window":
            before = len(self.windows)
            self.windows = [w for w in self.windows if w["id"] != opt("-t")]
            code = 0 if len(self.windows) < before else 1
        return subprocess.CompletedProcess(args, code, out + "\n", "")


class _Routes(unittest.IsolatedAsyncioTestCase):
    """The panel's routes over the fake CLI, everything in a temp dir."""

    face = "chat"

    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        tmp = self.tmp.name
        self._saved_env = {k: os.environ.get(k) for k in _ENV}
        for key, value in {
            "BRAIN_CHAT_TRANSCRIPT": os.path.join(tmp, "t.json"),
            "BRAIN_CHAT_TRANSCRIPT_DIR": os.path.join(tmp, "chat"),
            "BRAIN_CHAT_WORKDIR": tmp,
            "BRAIN_CLAUDE_BIN": str(FAKE),
            "BRAIN_SETTINGS_FILE": os.path.join(tmp, "settings.json"),
            "BRAIN_DIR": os.path.join(tmp, "insights"),
            "BRAIN_SECRETS": os.path.join(tmp, "secrets"),
            "BRAIN_RUN_SOURCES": os.path.join(tmp, "run-sources.jsonl"),
            "BRAIN_CHAT_TRASH": os.path.join(tmp, "chat-trash"),
            "BRAIN_TERMINAL_HANDOFF": os.path.join(tmp, "terminal-handoff.json"),
            "BRAIN_CHAT_CONTEXT_HOOK": os.path.join(tmp, "no-hook.py"),
            "BRAIN_JOURNAL_FILE": os.path.join(tmp, "journal.jsonl"),
            "BRAIN_USAGE_NUDGE": os.path.join(tmp, "usage-nudge"),
            "BRAIN_USAGE_FILE": os.path.join(tmp, "usage.json"),
            "BRAIN_MEMINFO": os.path.join(tmp, "no-meminfo"),
            "FAKE_CHAT_MODE": "ok",
        }.items():
            os.environ[key] = value
        os.environ.pop("BRAIN_TMUX_SESSION", None)
        for name in ("journal", "usage_store", "engine", "settings_store",
                     "run_sources", "conversations", "chat_session", "server"):
            setattr(self, name, importlib.reload(importlib.import_module(name)))
        self.chat_session._LAST_HANDOFF.clear()
        self.conversations.CONFIG_DIR = tmp
        self.tmux = FakeTmux()
        self.chat_session._tmux = self.tmux
        self.chat_session.TERMINAL_START = "/usr/local/bin/brain-terminal-start"
        self._olds = (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
                      findings_store.STATE_FILE, findings_store.INBOX_DIR)
        findings_store.FINDINGS_FILE = Path(tmp) / "findings.json"
        findings_store.SETTLED_FILE = Path(tmp) / "settled.json"
        findings_store.STATE_FILE = Path(tmp) / "nowhere" / ".brain" / "s.json"
        findings_store.INBOX_DIR = Path(tmp) / "findings-inbox"
        self.settings_store.save({"terminal_ui": self.face})
        self.server.TERMINAL_PROMPT_FILE = Path(tmp) / "prompt.md"

        from aiohttp.test_utils import TestClient, TestServer
        self.client = TestClient(TestServer(self.server.make_app()))
        await self.client.start_server()

    async def asyncTearDown(self):
        # The panel runs its slow start-up work after it binds; let that
        # finish before the temporary directory it writes into is removed,
        # or cleanup races its last write ("Directory not empty").
        startup = self.client.server.app.get("startup")
        if startup is not None and not startup.done():
            try:
                await asyncio.wait_for(asyncio.shield(startup), 30)
            except (asyncio.TimeoutError, asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await self.client.close()
        await self.chat_session.registry().stop_all()
        (findings_store.FINDINGS_FILE, findings_store.SETTLED_FILE,
         findings_store.STATE_FILE, findings_store.INBOX_DIR) = self._olds
        for key, value in self._saved_env.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        for name in ("journal", "usage_store"):
            importlib.reload(importlib.import_module(name))
        self.tmp.cleanup()

    def registry(self):
        return self.chat_session.registry()

    async def _until(self, check, timeout=10.0):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if check():
                return True
            await asyncio.sleep(0.05)
        return False

    async def _post(self, path, body=None):
        resp = await self.client.post(path, json=body or {})
        text = await resp.text()
        self.assertEqual(resp.status, 200, f"{path}: {resp.status} {text} "
                                           f"{resp.reason}")
        return json.loads(text)

    def _users(self, session):
        return [e.get("text") for e in session.events if e.get("type") == "user"]

    def _fake_conversation(self, session_id, text):
        """A conversation in the CLI's own store, for resume to replay."""
        project = (Path(self.tmp.name) / "projects"
                   / re.sub(r"[^A-Za-z0-9]", "-", self.tmp.name))
        project.mkdir(parents=True, exist_ok=True)
        (project / f"{session_id}.jsonl").write_text(json.dumps({
            "type": "user", "cwd": self.tmp.name,
            "message": {"role": "user", "content": text}}) + "\n"
            + "x" * 300 + "\n", encoding="utf-8")
        self.conversations.CONFIG_DIR = self.tmp.name


class TestAskFollowsTheSavedFace(_Routes):

    async def test_ask_on_the_chat_face_opens_a_new_chat_holding_the_prompt(self):
        """The flip: Ask must land in a NEW chat conversation that starts
        with the card's words — never the terminal, and never an empty
        chat."""
        opened = []
        self.chat_session._open_in_terminal = \
            lambda *a, **k: opened.append(a) or True
        out = await self._post("/api/ask", {"prompt": "Tell me about the porch"})
        self.assertEqual(out["face"], "chat")
        self.assertTrue(out["key"])
        self.assertEqual(opened, [], "the chat face opened a terminal window")
        session = self.registry().by_key(out["key"])
        self.assertIsNotNone(session)
        self.assertTrue(await self._until(
            lambda: "Tell me about the porch" in self._users(session)),
            self._users(session))
        # The stream for that key opens on that conversation.
        snap = await (await self.client.get(
            f"/api/chat/state?session_key={out['key']}")).json()
        self.assertEqual(snap["key"], out["key"])
        self.assertIn("Tell me about the porch",
                      [e.get("text") for e in snap["events"]])

    async def test_two_asks_are_two_conversations(self):
        a = await self._post("/api/ask", {"prompt": "first thing"})
        session_a = self.registry().by_key(a["key"])
        await self._until(lambda: self._users(session_a))
        b = await self._post("/api/ask", {"prompt": "second thing",
                                          "session_key": a["key"]})
        self.assertNotEqual(a["key"], b["key"])
        self.assertEqual(self._users(session_a), ["first thing"])

    async def test_two_discussions_at_once_are_two_conversations(self):
        """Both answer before either prompt has landed, so the first one's
        conversation still looks empty when the second asks."""
        e1, _ = findings_store.add("Porch light never comes on",
                                   entity_id="light.porch",
                                   source="check:auto.dead_ref")
        e2, _ = findings_store.add("Freezer drifting warm",
                                   source="check:base.unusual")
        r1, r2 = await asyncio.gather(
            self.client.post(f"/api/finding/{e1['ts']}/discuss"),
            self.client.post(f"/api/finding/{e2['ts']}/discuss"))
        o1, o2 = await r1.json(), await r2.json()
        self.assertNotEqual(o1["key"], o2["key"])
        s1 = self.registry().by_key(o1["key"])
        s2 = self.registry().by_key(o2["key"])
        self.assertEqual({s1.finding_ts, s2.finding_ts}, {e1["ts"], e2["ts"]})
        for session in (s1, s2):
            self.assertTrue(await self._until(lambda: len(self._users(session)) == 1))
        self.assertIn("Porch", self._users(s1 if s1.finding_ts == e1["ts"] else s2)[0])

    async def test_an_empty_ask_is_refused(self):
        resp = await self.client.post("/api/ask", json={"prompt": "  "})
        self.assertEqual(resp.status, 400)


class TestAskOnTheClassicFace(_Routes):
    face = "classic"

    async def test_the_classic_face_opens_the_terminal(self):
        out = await self._post("/api/ask", {"prompt": "Tell me about the porch"})
        self.assertEqual(out["face"], "terminal")
        self.assertTrue(out["opened"])
        self.assertEqual(self.registry().sessions(), [],
                         "the terminal face spawned a chat")


class TestEachViewerHasItsOwnConversation(_Routes):

    async def _conversation(self, text):
        out = await self._post("/api/chat/new", {})
        key = out["key"]
        await self._post("/api/chat/send", {"text": text, "session_key": key})
        session = self.registry().by_key(key)
        self.assertTrue(await self._until(
            lambda: session.state == "ready" and session.session_id))
        return session

    async def test_the_phone_lands_in_its_own_conversation(self):
        """The audit's two-device scenario: phone in A, desktop opens B,
        the phone's next message lands in A."""
        phone = await self._conversation("phone's first")
        desktop = await self._conversation("desktop's first")
        self.assertIs(self.registry().attached(), desktop)
        out = await self._post("/api/chat/send", {
            "text": "phone again", "session_key": phone.key,
            "session_id": phone.session_id})
        self.assertEqual(out["key"], phone.key)
        self.assertTrue(await self._until(
            lambda: "phone again" in self._users(phone)))
        self.assertNotIn("phone again", self._users(desktop))

    async def test_an_id_alone_reaches_a_conversation_nobody_holds(self):
        """After a restart the registry holds nothing but the attached one;
        a named id is held again — not attached, so no view moves."""
        desktop = await self._conversation("desktop")
        self._fake_conversation("phone-conv", "phone's old words")
        await self._post("/api/chat/send", {"text": "carry on",
                                            "session_id": "phone-conv"})
        held = self.registry().get("phone-conv")
        self.assertIsNotNone(held)
        self.assertTrue(await self._until(
            lambda: "carry on" in self._users(held)))
        self.assertIs(self.registry().attached(), desktop)
        self.assertNotIn("carry on", self._users(desktop))

    async def test_a_name_that_matches_nothing_is_refused_not_redirected(self):
        await self._conversation("somebody's")
        resp = await self.client.post("/api/chat/send", json={
            "text": "hello", "session_key": "f" * 32})
        self.assertEqual(resp.status, 404)

    async def test_stop_and_model_go_to_the_named_conversation(self):
        desktop = await self._conversation("desktop")
        # A phone whose CLI never finishes a turn (spawned that way).
        os.environ["FAKE_CHAT_MODE"] = "hang"
        try:
            out = await self._post("/api/chat/new", {})
            phone = self.registry().by_key(out["key"])
            await self._post("/api/chat/send", {"text": "think hard",
                                                "session_key": phone.key})
            self.assertTrue(await self._until(lambda: phone.state == "busy"))
            # The model is refused for the BUSY one it names, not applied
            # to the idle one somebody else is looking at.
            resp = await self.client.post("/api/chat/model", json={
                "model": "claude-haiku-4-5", "session_key": phone.key})
            self.assertEqual(resp.status, 409)
            await self._post("/api/chat/stop", {"session_key": phone.key})
            self.assertTrue(await self._until(lambda: phone.state != "busy"))
            self.assertEqual(desktop.state, "ready")
        finally:
            os.environ["FAKE_CHAT_MODE"] = "ok"

    async def test_another_devices_switch_is_not_this_viewers(self):
        """The stream named by key serves that conversation, and a switch
        elsewhere does not end it with `switched`."""
        phone = await self._conversation("phone")
        resp = await self.client.get(
            f"/api/chat/stream?session_key={phone.key}")
        line = await asyncio.wait_for(resp.content.readline(), 5)
        snap = json.loads(line.decode().split("data: ", 1)[1])
        self.assertEqual(snap["key"], phone.key)
        await self._conversation("desktop")          # attaches elsewhere
        seen = []
        try:
            while True:
                line = await asyncio.wait_for(resp.content.readline(), 0.5)
                if line.startswith(b"data: "):
                    seen.append(json.loads(line[6:]))
        except asyncio.TimeoutError:
            # Half a second of silence is the end of what this stream had.
            pass
        resp.close()
        self.assertNotIn("switched", [e.get("type") for e in seen])


class TestRequestsAnswerPromptly(_Routes):
    """A spawn is watched for START_GRACE; a request is not held for it."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # A CLI that takes 4 s to say its first word, under a grace long
        # enough to wait for it: the old send held the request all 4 s.
        slow = Path(self.tmp.name) / "slow-claude"
        slow.write_text(f"#!/bin/sh\nsleep 4\nexec {sys.executable} {FAKE} \"$@\"\n")
        slow.chmod(0o755)
        os.environ["BRAIN_CLAUDE_BIN"] = str(slow)
        importlib.reload(self.engine)
        self.chat_session.START_GRACE = 10
        self.server.SEND_HOLD_S = 0.5

    async def test_a_send_that_must_spawn_answers_at_once(self):
        loop = asyncio.get_running_loop()
        started = loop.time()
        out = await self._post("/api/chat/send", {"text": "hello there"})
        self.assertLess(loop.time() - started, 2.5)
        self.assertTrue(out.get("pending"), out)
        session = self.registry().by_key(out["key"])
        self.assertTrue(await self._until(
            lambda: "hello there" in self._users(session), timeout=15))

    async def test_discuss_answers_at_once(self):
        entry, _ = findings_store.add("Porch light never comes on",
                                      entity_id="light.porch",
                                      source="check:auto.dead_ref")
        loop = asyncio.get_running_loop()
        started = loop.time()
        out = await self._post(f"/api/finding/{entry['ts']}/discuss")
        self.assertLess(loop.time() - started, 2.5)
        self.assertEqual(out["face"], "chat")
        session = self.registry().by_key(out["key"])
        self.assertEqual(session.finding_ts, entry["ts"])
        self.assertTrue(await self._until(
            lambda: any("Porch light" in (t or "")
                        for t in self._users(session)), timeout=15))


class TestTerminalWindows(_Routes):
    face = "classic"

    async def test_a_held_id_is_selected_not_resumed_twice(self):
        wid = self.tmux.add_window(session_id="conv-1", nonce="n1")
        out = await self._post("/api/terminal/open", {"session_id": "conv-1"})
        self.assertTrue(out["opened"])
        verbs = [c[0] for c in self.tmux.calls]
        self.assertIn("select-window", verbs)
        self.assertNotIn("new-window", verbs)
        self.assertIn(["select-window", "-t", wid], self.tmux.calls)

    async def test_the_chat_will_not_open_a_second_process_on_it(self):
        self.tmux.add_window(session_id="conv-1", nonce="n1")
        out = await self._post("/api/chat/resume", {"session_id": "conv-1"})
        self.assertTrue(out["in_terminal"])
        self.assertIsNone(self.registry().get("conv-1"))
        resp = await self.client.post("/api/chat/send", json={
            "text": "hi", "session_id": "conv-1"})
        self.assertEqual(resp.status, 409)

    async def test_windows_are_listed_and_marked(self):
        self.tmux.add_window(session_id="conv-1", nonce="n1")
        self.tmux.add_window(nonce="n2")
        self.tmux.windows.append({"id": "@99", "session": "claude", "sid": "",
                                  "nonce": "", "activity": time.time(),
                                  "argv": []})          # somebody's own shell
        self._fake_conversation("conv-1", "the porch")
        data = await (await self.client.get("/api/chat/conversations")).json()
        ids = [w["window_id"] for w in data["terminal"]]
        self.assertEqual(sorted(ids), ["@1", "@2"], "a person's shell was listed")
        rows = {r["id"]: r for r in data["conversations"]}
        self.assertEqual(rows["conv-1"]["terminal"]["window_id"], "@1")
        await self._post("/api/terminal/select", {"window_id": "@2"})
        resp = await self.client.post("/api/terminal/select",
                                      json={"window_id": "@99"})
        self.assertEqual(resp.status, 404, "selected a window brAIn did not open")

    async def test_two_quick_asks_each_get_their_own_handoff(self):
        await self._post("/api/ask", {"prompt": "first question"})
        await self._post("/api/ask", {"prompt": "second question"})
        opened = [w for w in self.tmux.windows if w["argv"]]
        self.assertEqual(len(opened), 2)
        paths = [w["argv"][w["argv"].index("--handoff") + 1] for w in opened]
        self.assertEqual(len(set(paths)), 2, paths)
        import base64
        said = [base64.b64decode(json.loads(Path(p).read_text())["prompt_b64"])
                .decode() for p in paths]
        self.assertEqual(said, ["first question", "second question"])
        self.assertFalse(Path(os.environ["BRAIN_TERMINAL_HANDOFF"]).exists())
        # Each window is tagged with its own request.
        self.assertEqual(len({w["nonce"] for w in opened}), 2)

    async def test_with_no_terminal_yet_the_request_waits_in_the_fixed_file(self):
        self.tmux.sessions = []
        out = await self._post("/api/ask", {"prompt": "first question"})
        self.assertFalse(out["opened"])
        record = json.loads(Path(os.environ["BRAIN_TERMINAL_HANDOFF"]).read_text())
        self.assertIn("prompt_b64", record)

    async def test_the_pickers_session_is_targeted(self):
        """auto_launch_claude: false — ttyd shows `claude-picker`."""
        self.tmux.sessions = ["claude-picker"]
        out = await self._post("/api/ask", {"prompt": "hello"})
        self.assertTrue(out["opened"])
        new = [c for c in self.tmux.calls if c[0] == "new-window"]
        self.assertEqual(new[0][new[0].index("-t") + 1], "claude-picker")

    async def test_windows_count_against_a_persons_cap(self):
        """With a cap of 2 and two windows open, a chat can only start by
        closing the idle window — and never a window that is in use."""
        self.settings_store.save({"chat_max_sessions": 2})
        busy_window = self.tmux.add_window(session_id="conv-a", nonce="a")
        idle_window = self.tmux.add_window(session_id="conv-b", nonce="b",
                                           idle_s=3600)
        reg = self.registry()
        session = reg.attached()
        await reg.room_for(session)
        ids = [w["id"] for w in self.tmux.windows]
        self.assertIn(busy_window, ids)
        self.assertNotIn(idle_window, ids)

    async def test_low_memory_closes_an_idle_window_only_when_no_chat_is_idle(self):
        meminfo = Path(os.environ["BRAIN_MEMINFO"])
        self.chat_session.MEMINFO = str(meminfo)
        meminfo.write_text("MemAvailable:   100000 kB\n")
        recent = self.tmux.add_window(session_id="conv-a", nonce="a")
        stale = self.tmux.add_window(session_id="conv-b", nonce="b",
                                     idle_s=3600)
        await self.registry().room_for(self.registry().attached())
        ids = [w["id"] for w in self.tmux.windows]
        self.assertIn(recent, ids, "closed a window somebody is using")
        self.assertNotIn(stale, ids)


class TestTheHandoffArgument(unittest.TestCase):
    """brain-terminal-start reads the file it is handed, and only that."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.fixed = root / "terminal-handoff.json"
        self.log = root / "argv.json"
        run = root / "claude-run"
        run.write_text("#!/usr/bin/env python3\nimport json, sys\n"
                       f"open({str(self.log)!r}, 'w').write(json.dumps(sys.argv[1:]))\n")
        run.chmod(0o755)
        self.env = {"PATH": os.environ["PATH"],
                    "BRAIN_TERMINAL_HANDOFF": str(self.fixed),
                    "BRAIN_TERMINAL_PROMPT_FILE": str(root / "none.md"),
                    "BRAIN_PERMISSIONS_FILE": str(root / "no-perms"),
                    "BRAIN_PERMS_ENV_FILE": str(root / "no-env"),
                    "BRAIN_CLAUDE_RUN": str(run)}

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, path, prompt):
        import base64
        path.write_text(json.dumps({"ts": int(time.time()), "prompt_b64":
                                    base64.b64encode(prompt.encode()).decode()}))

    def _start(self, *args):
        script = BASE_DIR / "brain" / "scripts" / "brain-terminal-start.sh"
        out = subprocess.run(["bash", str(script), *args], env=self.env,
                             capture_output=True, text=True, timeout=10)
        self.assertEqual(out.returncode, 0, out.stderr)
        return json.loads(self.log.read_text())

    def test_each_window_takes_its_own_file(self):
        one = self.fixed.with_name("terminal-handoff-aaaa.json")
        two = self.fixed.with_name("terminal-handoff-bbbb.json")
        self._write(one, "first")
        self._write(two, "second")
        self.assertEqual(self._start("--handoff", str(two))[-1], "second")
        self.assertFalse(two.exists())
        self.assertTrue(one.exists(), "a window took another request's file")
        self.assertEqual(self._start("--handoff", str(one))[-1], "first")

    def test_the_old_fixed_file_is_still_read(self):
        self._write(self.fixed, "from an older panel")
        self.assertEqual(self._start()[-1], "from an older panel")

    def test_a_path_elsewhere_is_ignored(self):
        other = Path(self.tmp.name) / "sub"
        other.mkdir()
        stray = other / "terminal-handoff-cccc.json"
        self._write(stray, "not mine")
        argv = self._start("--handoff", str(stray))
        self.assertNotIn("not mine", argv)
        self.assertNotIn("--handoff", argv)


class TestTtydIsSupervised(unittest.TestCase):

    def test_ttyd_runs_under_a_restart_loop_with_backoff(self):
        run = (BASE_DIR / "brain" / "run.sh").read_text()
        start = run.index("start_web_terminal() {")
        body = run[start:run.index("\nstart_panel() {")]
        loop = body[body.index("while true; do"):]
        # The loop starts ttyd, waits on it, logs the restart and backs off.
        self.assertIn("start_ttyd", loop[:loop.index("done")])
        self.assertIn('wait "${ttyd_pid}"', loop)
        self.assertIn("restarting it in", loop)
        self.assertIn('sleep "${delay}"', loop)
        self.assertIn("exec ttyd", body)
        # ttyd itself is started nowhere else.
        self.assertEqual(run.count("ttyd \\\n"), 1)
        subprocess.run(["bash", "-n", str(BASE_DIR / "brain" / "run.sh")],
                       check=True)

    def test_the_panel_is_told_which_tmux_session_ttyd_shows(self):
        run = (BASE_DIR / "brain" / "run.sh").read_text()
        self.assertIn('export BRAIN_TMUX_SESSION="claude-picker"', run)
        self.assertIn("export BRAIN_TERMINAL_CREATE=1", run)


if __name__ == "__main__":
    unittest.main()
