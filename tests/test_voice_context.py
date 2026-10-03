#!/usr/bin/env python3
"""What Home Assistant hands a conversation agent beyond the words.

Every turn arrives with the device or satellite it came from, the user who
spoke, maybe an automation's `extra_system_prompt`, and a chat log holding
whatever was said before brAIn was asked. brAIn's entity threw all of it
away: "turn off the lights" said to the kitchen satellite had no room to
resolve against, a `start_conversation` flow lost its question, and a
non-admin login could address a Full-admin agent and get a shell.

Driven through the REAL conversation entity (tests/brain_ha_env.py), and
for the claim that matters most — the room reaches the model — through the
real bridge's file IPC into the real worker pool and out of the fake CLI
the pool spawns, because "the entity built a dict" and "the words reached
the turn" are different claims and only the second decides what is said.
"""
from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import json
import os
import shutil
import sys
import tempfile
import types
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import brain_ha_env as env  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "brain" / "scripts"
POOL_PATH = REPO / "brain" / "integrations" / "assist-worker-pool.py"
FAKE_CLAUDE = Path(__file__).resolve().parent / "fake_claude.py"

sys.path.insert(0, str(SCRIPTS))
import brain_voice_context  # noqa: E402


# ---------------------------------------------------------------------------
# A house with one satellite, one person and one guest
# ---------------------------------------------------------------------------


class FakeStates:
    def __init__(self, states):
        self.states = states

    def async_all(self, domain=None):
        return [s for s in self.states
                if domain is None or s.entity_id.startswith(domain + ".")]


class FakeAuth:
    def __init__(self, users):
        self.users = users

    async def async_get_user(self, user_id):
        return self.users.get(user_id)


class FakeHass:
    def __init__(self, base: Path):
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(str(base), *parts))
        self.registries = {
            "entity": env.EntityRegistry({
                "assist_satellite.kitchen": types.SimpleNamespace(
                    area_id=None, device_id="dev-kitchen"),
                "assist_satellite.landing": types.SimpleNamespace(
                    area_id="landing", device_id="dev-hall"),
            }),
            "device": env.DeviceRegistry({
                "dev-kitchen": types.SimpleNamespace(
                    name="Kitchen satellite", name_by_user=None,
                    area_id="kitchen"),
                "dev-hall": types.SimpleNamespace(
                    name="Hall satellite", name_by_user="Stairs speaker",
                    area_id="hall"),
                "dev-nowhere": types.SimpleNamespace(
                    name="Garage speaker", name_by_user=None, area_id=None),
            }),
            "area": env.AreaRegistry({
                "kitchen": types.SimpleNamespace(name="Kitchen", floor_id="ground"),
                "hall": types.SimpleNamespace(name="Hall", floor_id="ground"),
                "landing": types.SimpleNamespace(name="Landing", floor_id="first"),
            }),
            "floor": env.FloorRegistry({
                "ground": types.SimpleNamespace(name="Ground floor"),
                "first": types.SimpleNamespace(name="First floor"),
            }),
        }
        self.auth = FakeAuth({
            "u-ben": types.SimpleNamespace(id="u-ben", is_admin=True, name="ben"),
            "u-guest": types.SimpleNamespace(id="u-guest", is_admin=False,
                                             name="Wall tablet"),
        })
        self.states = FakeStates([
            types.SimpleNamespace(entity_id="person.ben", name="Ben",
                                  attributes={"user_id": "u-ben"}),
        ])
        self.chat_logs: dict = {}

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)

    def async_create_task(self, coro):
        return asyncio.ensure_future(coro)

    # The chat-log half (HA 2025.x), used only by the streaming tests.
    def chat_session_for(self, conversation_id):
        return contextlib.nullcontext(types.SimpleNamespace(
            conversation_id=conversation_id or "minted-by-ha"))

    def chat_log_for(self, session, user_input):
        log = self.chat_logs.setdefault(session.conversation_id,
                                        FakeChatLog(session.conversation_id))
        log.content.append(types.SimpleNamespace(
            role="user", agent_id=None, content=user_input.text))
        return contextlib.nullcontext(log)


class FakeChatLog:
    def __init__(self, conversation_id):
        self.conversation_id = conversation_id
        self.content: list = []
        self.continue_conversation = False
        self.extra_system_prompt = None
        self.streamed: list[str] = []

    async def async_add_delta_content_stream(self, agent_id, stream):
        async for item in stream:
            if "content" in item:
                self.streamed.append(item["content"])
            yield item
        self.content.append(types.SimpleNamespace(
            role="assistant", agent_id=agent_id,
            content="".join(self.streamed)))


def user_input(text="turn off the lights", *, satellite_id=None, device_id=None,
               user_id=None, conversation_id=None, extra_system_prompt=None,
               agent_id="conversation.brain_agent", language="en"):
    return types.SimpleNamespace(
        text=text, conversation_id=conversation_id, device_id=device_id,
        satellite_id=satellite_id, context=env.Context(user_id),
        language=language, agent_id=agent_id,
        extra_system_prompt=extra_system_prompt)


class RecordingBridge:
    def __init__(self, answer="Done."):
        self.sent: list[dict] = []
        self.answer = answer

    async def async_send_conversation(self, **kw):
        self.sent.append(kw)
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer

    async def async_send_conversation_streaming(self, **kw):
        self.sent.append(kw)
        if isinstance(self.answer, Exception):
            raise self.answer
        listener = kw.get("delta_listener")
        for chunk in kw.pop("_chunks", None) or [self.answer]:
            listener(chunk)
        return self.answer


class EntityCase(unittest.TestCase):
    chat_log = False
    continues = True

    def setUp(self):
        self.pkg = env.load_integration(chat_log=self.chat_log,
                                        continues=self.continues)
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.hass = FakeHass(self.tmp)
        self.bridge = RecordingBridge()

    def entity(self, access="voice", bridge=None):
        entry = types.SimpleNamespace(
            entry_id="e1", data={"name": "brAIn", "access": access},
            options={})
        ent = self.pkg.conversation.BruhClaudeConversationEntity(
            entry, bridge or self.bridge)
        ent.hass = self.hass
        ent.entity_id = "conversation.brain_agent"
        return ent

    def process(self, ent, inp):
        return asyncio.new_event_loop().run_until_complete(
            ent.async_process(inp))


# ---------------------------------------------------------------------------
# Where and who
# ---------------------------------------------------------------------------


class TestWhereTheRequestCameFrom(EntityCase):

    def test_a_satellite_turn_carries_its_room_and_floor(self):
        self.process(self.entity(),
                     user_input(satellite_id="assist_satellite.kitchen"))
        context = self.bridge.sent[0]["context"]
        self.assertEqual(context["area"], "Kitchen")
        self.assertEqual(context["floor"], "Ground floor")
        self.assertEqual(context["device"], "Kitchen satellite")

    def test_a_satellite_in_another_room_than_its_device_is_in_that_room(self):
        """An entity's own area beats its device's: Home Assistant's rule."""
        self.process(self.entity(),
                     user_input(satellite_id="assist_satellite.landing"))
        context = self.bridge.sent[0]["context"]
        self.assertEqual(context["area"], "Landing")
        self.assertEqual(context["floor"], "First floor")
        # The name somebody gave the device wins over the integration's.
        self.assertEqual(context["device"], "Stairs speaker")

    def test_a_device_with_no_room_still_says_which_device(self):
        self.process(self.entity(), user_input(device_id="dev-nowhere"))
        context = self.bridge.sent[0]["context"]
        self.assertNotIn("area", context)
        self.assertEqual(context["device"], "Garage speaker")
        self.assertIn("ask which room", brain_voice_context.preamble(context))

    def test_a_core_before_floors_says_the_room_and_no_floor(self):
        pkg = env.load_integration(floors=False)
        self.assertIsNone(pkg.conversation.fr)
        place = pkg.conversation.describe_place(
            self.hass, satellite_id="assist_satellite.kitchen")
        self.assertEqual(place, {"area": "Kitchen", "device": "Kitchen satellite"})

    def test_a_registry_that_raises_is_a_request_with_less_context(self):
        self.hass.registries["area"] = None   # .async_get_area -> AttributeError
        self.process(self.entity(),
                     user_input(satellite_id="assist_satellite.kitchen"))
        self.assertEqual(self.bridge.sent[0]["context"],
                         {"device": "Kitchen satellite", "language": "en"})

    def test_a_request_with_nothing_to_say_sends_no_context(self):
        self.process(self.entity(), user_input(language="*"))
        self.assertIsNone(self.bridge.sent[0]["context"])


class TestWhoSpoke(EntityCase):

    def test_the_speaker_is_their_person(self):
        self.process(self.entity(), user_input(user_id="u-ben"))
        context = self.bridge.sent[0]["context"]
        self.assertEqual(context["person"], "person.ben")
        self.assertEqual(context["speaker"], "Ben")
        self.assertEqual(brain_voice_context.person_id(context), "ben")

    def test_a_satellite_turn_has_no_user_and_keeps_the_agents_level(self):
        self.process(self.entity("house"),
                     user_input(satellite_id="assist_satellite.kitchen"))
        self.assertEqual(self.bridge.sent[0]["access"], "house")


class TestAWideAgentAskedByANonAdmin(EntityCase):
    """HA lists every agent in every user's Assist picker and lets
    `conversation.process` name any of them."""

    def test_a_full_admin_agent_answers_a_guest_at_the_voice_level(self):
        self.process(self.entity("admin"), user_input(user_id="u-guest"))
        sent = self.bridge.sent[0]
        self.assertEqual(sent["access"], "voice")
        self.assertEqual(sent["context"]["narrowed_from"], "admin")
        self.assertIn("not a Home Assistant administrator",
                      brain_voice_context.preamble(sent["context"]))

    def test_a_house_agent_is_narrowed_too(self):
        self.process(self.entity("house"), user_input(user_id="u-guest"))
        self.assertEqual(self.bridge.sent[0]["access"], "voice")

    def test_an_admin_keeps_the_agents_level(self):
        self.process(self.entity("admin"), user_input(user_id="u-ben"))
        self.assertEqual(self.bridge.sent[0]["access"], "admin")
        self.assertNotIn("narrowed_from", self.bridge.sent[0]["context"])

    def test_a_user_that_cannot_be_found_is_narrowed_not_widened(self):
        self.process(self.entity("admin"), user_input(user_id="u-gone"))
        self.assertEqual(self.bridge.sent[0]["access"], "voice")


# ---------------------------------------------------------------------------
# What the reply does next
# ---------------------------------------------------------------------------


class TestTheClassicPath(EntityCase):

    def test_a_question_keeps_the_satellite_listening(self):
        self.bridge.answer = "Which bedroom?"
        result = self.process(self.entity(), user_input())
        self.assertTrue(result.continue_conversation)

    def test_an_answer_does_not(self):
        result = self.process(self.entity(), user_input())
        self.assertFalse(result.continue_conversation)

    def test_a_core_that_cannot_be_told_gets_no_such_field(self):
        pkg = env.load_integration(continues=False)
        self.pkg = pkg
        self.bridge.answer = "Which bedroom?"
        result = self.process(self.entity(), user_input())
        self.assertFalse(hasattr(result, "continue_conversation"))

    def test_the_minted_conversation_id_is_the_one_returned(self):
        """The bridge records history under the id it is given, so handing
        back the caller's None meant the next turn never continued."""
        result = self.process(self.entity(), user_input())
        self.assertTrue(result.conversation_id)
        self.assertEqual(result.conversation_id,
                         self.bridge.sent[0]["conversation_id"])
        again = self.process(self.entity(), user_input(
            "and the hall", conversation_id=result.conversation_id))
        self.assertEqual(again.conversation_id, result.conversation_id)

    def test_a_failure_is_an_error_response_and_never_speech(self):
        self.bridge.answer = self.pkg.bridge.BrainRunError(
            "Claude is not signed in. Open brAIn and press Sign in again.",
            "auth")
        result = self.process(self.entity(), user_input())
        self.assertIsNone(result.response.speech)
        code, message = result.response.error
        self.assertEqual(code, env.IntentResponseErrorCode.UNKNOWN)
        self.assertIn("Sign in again", message)
        self.assertFalse(result.continue_conversation)

    def test_an_automations_prompt_rides_along(self):
        self.process(self.entity(), user_input(
            "yes", extra_system_prompt="Ask whether to close the garage."))
        context = self.bridge.sent[0]["context"]
        self.assertEqual(context["extra_system_prompt"],
                         "Ask whether to close the garage.")
        self.assertIn("Ask whether to close the garage",
                      brain_voice_context.preamble(context))


class TestTheChatLogPath(EntityCase):
    chat_log = True

    def stream(self, inp, chunks=None, ent=None):
        bridge = self.bridge
        original = bridge.async_send_conversation_streaming

        async def with_chunks(**kw):
            kw["_chunks"] = chunks
            return await original(**kw)
        bridge.async_send_conversation_streaming = with_chunks
        return self.process(ent or self.entity(), inp)

    def test_a_question_keeps_the_satellite_listening(self):
        self.bridge.answer = "Which bedroom?"
        result = self.stream(user_input(conversation_id="c1"))
        self.assertTrue(result.continue_conversation)

    def test_the_chat_logs_own_flag_keeps_it_listening_too(self):
        log = FakeChatLog("c1")
        log.continue_conversation = True
        self.hass.chat_logs["c1"] = log
        result = self.stream(user_input(conversation_id="c1"))
        self.assertTrue(result.continue_conversation)

    def test_what_was_said_before_brain_was_asked_rides_along(self):
        """`start_conversation` writes its announcement into the chat log
        under the satellite's id; brAIn never saw it, so the person's "yes"
        arrived with no idea what it was a yes to."""
        log = FakeChatLog("c1")
        log.content.append(types.SimpleNamespace(
            role="assistant", agent_id="assist_satellite.kitchen",
            content="The garage has been open for an hour. Close it?"))
        self.hass.chat_logs["c1"] = log
        self.stream(user_input("yes", conversation_id="c1"))
        prior = self.bridge.sent[0]["context"]["prior"]
        self.assertEqual(prior, [{"role": "assistant",
                                  "text": "The garage has been open for an "
                                          "hour. Close it?"}])
        self.assertIn("Close it?",
                      brain_voice_context.preamble(self.bridge.sent[0]["context"]))

    def test_its_own_earlier_turns_are_not_sent_back_to_it(self):
        log = FakeChatLog("c1")
        log.content += [
            types.SimpleNamespace(role="user", agent_id=None, content="hi"),
            types.SimpleNamespace(role="assistant",
                                  agent_id="conversation.brain_agent",
                                  content="Hello."),
        ]
        self.hass.chat_logs["c1"] = log
        self.stream(user_input("and the lights", conversation_id="c1"))
        self.assertNotIn("prior", self.bridge.sent[0]["context"] or {})

    def test_the_answer_is_the_last_thing_in_the_chat_log(self):
        """Deltas from an attempt that died before the spoken answer would
        otherwise leave the log ending on what nobody heard."""
        self.bridge.answer = "The lights are off."
        self.stream(user_input(conversation_id="c1"),
                    chunks=["I'll check."])
        log = self.hass.chat_logs["c1"]
        self.assertEqual("".join(log.streamed),
                         "I'll check.\n\nThe lights are off.")

    def test_a_streamed_answer_is_not_said_twice(self):
        self.bridge.answer = "The lights are off."
        self.stream(user_input(conversation_id="c1"),
                    chunks=["The lights ", "are off."])
        self.assertEqual("".join(self.hass.chat_logs["c1"].streamed),
                         "The lights are off.")

    def test_a_failure_on_the_stream_is_an_error_response(self):
        self.bridge.answer = self.pkg.bridge.BrainRunError(
            "Sorry, the connection to Claude dropped mid-response.", "partial")
        result = self.stream(user_input(conversation_id="c1"))
        self.assertIsNone(result.response.speech)
        self.assertIn("dropped", result.response.error[1])


# ---------------------------------------------------------------------------
# The words, as the model reads them
# ---------------------------------------------------------------------------


class TestThePreamble(unittest.TestCase):

    def test_no_context_is_no_block(self):
        self.assertEqual(brain_voice_context.preamble({}), "")
        self.assertEqual(brain_voice_context.preamble(None), "")

    def test_it_says_it_is_context_and_not_the_persons_words(self):
        block = brain_voice_context.preamble({"area": "Kitchen"})
        self.assertIn("not words the person said", block)
        self.assertIn('"turn off the lights" mean the Kitchen area', block)

    def test_another_processes_text_is_one_capped_line(self):
        block = brain_voice_context.preamble(
            {"extra_system_prompt": "x\n" * 5000})
        self.assertNotIn("x\nx", block)
        self.assertLess(len(block), brain_voice_context.PROMPT_MAX * 3)

    def test_the_person_id_is_only_ever_a_slug(self):
        for bad in ("person.ben; rm -rf", "../ben", "Ben Smith", 7):
            self.assertEqual(brain_voice_context.person_id({"person": bad}), "")
        self.assertEqual(brain_voice_context.person_id({"person": "person.ben_2"}),
                         "ben_2")

    def test_the_cli_reads_a_whole_request(self):
        import subprocess  # noqa: PLC0415
        out = subprocess.run(
            [sys.executable, str(SCRIPTS / "brain_voice_context.py"), "preamble"],
            input=json.dumps({"id": "r", "context": {"area": "Kitchen"}}),
            capture_output=True, text=True, check=True).stdout
        self.assertIn("Kitchen area", out)


# ---------------------------------------------------------------------------
# End to end: satellite -> entity -> real bridge -> real pool -> the CLI
# ---------------------------------------------------------------------------


def load_pool(tmp: Path, case: unittest.TestCase):
    """The real pool, with its environment held for the whole test: the CLI
    command is resolved per spawn, not at import."""
    pool_env = {
        "BRAIN_SHARED_DIR": str(tmp / ".brain"),
        "BRAIN_ASSIST_WORKDIR": str(tmp),
        "BRAIN_CLAUDE_BIN": f"{sys.executable} {FAKE_CLAUDE}",
        "FAKE_CLAUDE_LOG": str(tmp / "argv.log"),
        "BRAIN_RUN_SOURCES": str(tmp / "run-sources.jsonl"),
        "BRAIN_ENV_FILE": str(tmp / "brain_env"),
    }
    patcher = patch.dict(os.environ, pool_env)
    patcher.start()
    case.addCleanup(patcher.stop)
    os.environ.pop("SUPERVISOR_TOKEN", None)
    os.environ.pop("FAKE_MODE", None)
    spec = importlib.util.spec_from_file_location(
        f"assist_pool_{uuid.uuid4().hex}", POOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for d in (mod.REQUESTS_DIR, mod.RESPONSES_DIR, mod.SESSIONS_DIR,
              mod.CACHE_DIR, mod.LOG_DIR):
        os.makedirs(d, exist_ok=True)
    mod.journal_turn = lambda *a, **kw: None
    return mod


class TestASatelliteTurnReachesTheModelWithItsRoom(EntityCase):

    def test_the_room_is_in_the_turn_the_cli_was_handed(self):
        pool_mod = load_pool(self.tmp, self)
        pool = pool_mod.Pool()
        bridge = self.pkg.bridge.ClaudeBridge(self.hass, timeout=60)
        self.addCleanup(lambda: [w.kill() for w in list(pool.workers.values())])
        self.addCleanup(lambda: pool.spare and pool.spare.kill())

        async def serve_one():
            # The add-on's half: the request file the bridge wrote, handed
            # to the pool exactly as the pool's own watcher would.
            for _ in range(500):
                names = [n for n in os.listdir(bridge.requests_dir)
                         if n.endswith(".json")] \
                    if os.path.isdir(bridge.requests_dir) else []
                if names:
                    path = Path(bridge.requests_dir, names[0])
                    req = json.loads(path.read_text())
                    path.unlink()
                    await asyncio.to_thread(pool.handle, req)
                    return req
                await asyncio.sleep(0.02)
            raise AssertionError("the bridge wrote no request")

        async def main():
            server = asyncio.ensure_future(serve_one())
            result = await self.entity(bridge=bridge).async_process(
                user_input("turn off the lights",
                           satellite_id="assist_satellite.kitchen"))
            return result, await server

        result, req = asyncio.new_event_loop().run_until_complete(main())
        # The fake CLI echoes the message it was sent on stdin.
        spoken = result.response.speech
        self.assertIn("Kitchen area", spoken)
        self.assertIn("Ground floor", spoken)
        self.assertIn("turn off the lights", spoken)
        self.assertLess(spoken.index("Kitchen area"),
                        spoken.index("turn off the lights"))
        # In the TURN, never the system prompt — which keys the spare.
        self.assertNotIn("Kitchen", json.dumps(req.get("system_prompt") or ""))


if __name__ == "__main__":
    unittest.main()
