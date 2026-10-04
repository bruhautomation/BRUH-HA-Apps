"""brAIn as Home Assistant's AI Task entity, and as an LLM API for others.

Both are feature-detected — a core without the AI Task platform is never
asked for it, and one without the LLM helper registers nothing — and both
read and never act:

* the AI Task entity sends a `read_only` task with brAIn's memory, hands a
  requested structure to the CLI as a JSON Schema and validates the answer
  against Home Assistant's own schema before returning it;
* the LLM API offers three measurements (`what_is_normal`, `recall`,
  `explain_change`) answered by the MCP server's own functions through the
  add-on's API, refusing an entity the asking assistant cannot see and
  leaving facts about one out of `recall`.

The integration is loaded for real (`tests/brain_ha_env.py`), the pool's
endpoint is stood up on a real socket, and the bridge is driven into it.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

import brain_ha_env as env  # noqa: E402


def run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class FakeHass:
    def __init__(self, base):
        self.data = {}
        self.config = types.SimpleNamespace(
            path=lambda *parts: os.path.join(str(base), *parts))

    async def async_add_executor_job(self, fn, *args):
        return fn(*args)


class IntegrationCase(unittest.TestCase):
    llm = True
    ai_task = True

    def setUp(self):
        self.pkg = env.load_integration(llm=self.llm, ai_task=self.ai_task)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.hass = FakeHass(self.tmp.name)
        self.sent: list[dict] = []
        self.tool_calls: list[tuple] = []
        self.answer: object = {"text": "All quiet.", "data": None}
        self.tool_answer: dict = {"usual": {"median": 4.1}}
        test = self

        class RecordingBridge(self.pkg.bridge.ClaudeBridge):
            async def async_send_task_full(self, **kw):
                test.sent.append(kw)
                if isinstance(test.answer, Exception):
                    raise test.answer
                return test.answer

            async def async_llm_tool(self, name, args, timeout=45):
                test.tool_calls.append((name, args))
                return dict(test.tool_answer)

        self.hass.data[self.pkg.const.DOMAIN] = {"entry": RecordingBridge(self.hass)}


class TestThePlatformIsAskedForOnlyWhereItExists(IntegrationCase):
    def platforms(self, with_ai_task):
        names = dict(CONVERSATION="conversation", SENSOR="sensor",
                     BINARY_SENSOR="binary_sensor", BUTTON="button", TODO="todo")
        if with_ai_task:
            names["AI_TASK"] = "ai_task"
        entry = types.SimpleNamespace(data={}, options={})
        with patch.object(self.pkg, "Platform", types.SimpleNamespace(**names)):
            return self.pkg._get_platforms(entry)

    def test_a_core_with_ai_task_gets_the_entity_and_an_older_one_is_not_asked(self):
        self.assertIn("ai_task", self.platforms(True))
        self.assertNotIn("ai_task", self.platforms(False))


class TestTheAITaskEntity(IntegrationCase):
    def entity(self):
        if getattr(self, "_entity", None) is not None:
            return self._entity
        added = []
        entry = types.SimpleNamespace(entry_id="e1", data={}, options={})
        run(self.pkg.ai_task.async_setup_entry(self.hass, entry, added.extend))
        run(self.pkg.ai_task.async_setup_entry(self.hass, entry, added.extend))
        self.assertEqual(len(added), 1, "one AI Task entity per house")
        ent = added[0]
        ent.hass = self.hass
        self._entity = ent
        return ent

    def generate(self, task):
        chat_log = types.SimpleNamespace(conversation_id="conv-1")
        return run(self.entity()._async_generate_data(task, chat_log))

    def test_it_reads_with_memory_and_answers_in_text(self):
        task = env.GenDataTask(name="Suggest", instructions="Name the busiest room.")
        self.answer = {"text": "The kitchen.", "data": None}
        result = self.generate(task)
        self.assertEqual((result.conversation_id, result.data), ("conv-1", "The kitchen."))
        [sent] = self.sent
        self.assertEqual(sent["tools"], "read_only")
        self.assertIs(sent["memory"], True)
        self.assertIsNone(sent["schema"])
        self.assertIn("Name the busiest room.", sent["prompt"])

    def test_a_structure_is_asked_for_and_validated(self):
        def structure(data):
            if not isinstance(data, dict) or not isinstance(data.get("room"), str):
                raise ValueError("expected a room")
            return {"room": data["room"].strip()}

        task = env.GenDataTask(name="Suggest", instructions="Busiest room?",
                               structure=structure)
        self.answer = {"text": "", "data": {"room": " Kitchen "}}
        self.assertEqual(self.generate(task).data, {"room": "Kitchen"})
        self.assertIn("JSON only", self.sent[-1]["prompt"])
        # An older CLI: no validated object, the JSON is read out of the text.
        self.answer = {"text": '```json\n{"room": "Hall"}\n```', "data": None}
        self.assertEqual(self.generate(task).data, {"room": "Hall"})

    def test_an_answer_that_does_not_fit_is_an_error_never_data(self):
        def structure(data):
            raise ValueError("room is required")

        task = env.GenDataTask(name="Suggest", instructions="?", structure=structure)
        self.answer = {"text": "", "data": {"place": "kitchen"}}
        with self.assertRaises(env.HomeAssistantError) as caught:
            self.generate(task)
        self.assertIn("did not fit", str(caught.exception))
        self.answer = {"text": "not json at all", "data": None}
        with self.assertRaises(env.HomeAssistantError):
            self.generate(task)

    def test_a_failed_run_is_an_error_with_its_sentence(self):
        self.answer = self.pkg.bridge.BrainRunError("Claude's saved login has expired.", "auth")
        with self.assertRaises(env.HomeAssistantError) as caught:
            self.generate(env.GenDataTask(name="x", instructions="y"))
        self.assertIn("expired", str(caught.exception))


class TestTheLLMAPI(IntegrationCase):
    def registered(self):
        unregister = self.pkg.llm_api.async_register(self.hass)
        self.assertTrue(callable(unregister))
        api = self.hass.llm_apis[self.pkg.llm_api.API_ID]
        instance = run(api.async_get_api_instance(env.LLMContext(assistant="conversation")))
        return unregister, {t.name: t for t in instance.tools}, instance

    def call(self, tools, name, args, exposed):
        with patch.dict(sys.modules, env.exposure_modules(exposed)):
            return run(tools[name].async_call(
                self.hass, env.LLMToolInput(tool_name=name, tool_args=args),
                env.LLMContext(assistant="conversation")))

    def test_three_read_only_tools_under_names_that_cannot_collide(self):
        unregister, tools, instance = self.registered()
        self.assertEqual(sorted(tools), ["brain_explain_change", "brain_recall",
                                         "brain_what_is_normal"])
        self.assertIn("only read", instance.api_prompt)
        unregister()
        self.assertNotIn(self.pkg.llm_api.API_ID, self.hass.llm_apis)

    def test_an_exposed_entity_is_answered_by_the_add_on(self):
        _u, tools, _i = self.registered()
        got = self.call(tools, "brain_what_is_normal",
                        {"entity_id": "sensor.freezer"}, lambda a, e: True)
        self.assertEqual(got, {"usual": {"median": 4.1}})
        self.assertEqual(self.tool_calls, [("what_is_normal", {"entity_id": "sensor.freezer"})])

    def test_an_entity_the_assistant_cannot_see_is_refused_before_anything_is_asked(self):
        _u, tools, _i = self.registered()
        got = self.call(tools, "brain_explain_change",
                        {"entity_id": "lock.front"}, lambda a, e: False)
        self.assertIn("not exposed", got["error"])
        self.assertEqual(self.tool_calls, [])

    def test_an_exposure_that_cannot_be_checked_refuses(self):
        _u, tools, _i = self.registered()
        got = run(tools["brain_what_is_normal"].async_call(
            self.hass, env.LLMToolInput("brain_what_is_normal", {"entity_id": "sensor.x"}),
            env.LLMContext()))
        self.assertIn("could not check", got["error"])
        self.assertEqual(self.tool_calls, [])

    def test_recall_leaves_out_facts_about_what_the_assistant_cannot_see(self):
        _u, tools, _i = self.registered()
        self.tool_answer = {"facts": [
            {"text": "The front door lock is old.", "subjects": ["lock.front"]},
            {"text": "The kitchen is cold.", "subjects": ["area:kitchen", "sensor.kitchen"]},
            {"text": "We keep the heating low.", "subject": "house"},
        ]}
        got = self.call(tools, "brain_recall", {"query": "cold"},
                        lambda a, e: e != "lock.front")
        self.assertEqual([f["text"] for f in got["facts"]],
                         ["The kitchen is cold.", "We keep the heating low."])


class TestAnOlderCoreRegistersNothing(IntegrationCase):
    llm = False
    ai_task = False

    def test_no_helper_no_api(self):
        self.assertIsNone(self.pkg.llm_api.async_register(self.hass))
        self.assertFalse(hasattr(self.pkg, "ai_task"))


# ---------------------------------------------------------------------------
# The add-on's half: the pool's endpoint, on a real socket, and the bridge
# ---------------------------------------------------------------------------

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_the_pool_answers_with_the_mcp_servers_own_functions(tmp_path, monkeypatch):
    import http.client
    from test_pool_http import load_pool_module, shutdown, start_server

    mod = load_pool_module(tmp_path, monkeypatch)
    mcp = mod._mcp_module()
    calls = []
    monkeypatch.setattr(mcp, "what_is_normal",
                        lambda e: calls.append(("normal", e)) or {"usual": {"median": 3}})
    monkeypatch.setattr(mcp, "recall",
                        lambda **kw: calls.append(("recall", kw)) or {"facts": []})
    monkeypatch.setattr(mcp, "explain_change",
                        lambda e, hours=24: calls.append(("why", e, hours)) or {"changes": []})
    pool = mod.Pool()
    port = _free_port()
    try:
        start_server(mod, pool, port)
        token = Path(mod.API_TOKEN_FILE).read_text().strip()

        def post(body, tok=token):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            conn.request("POST", "/llm/tool", json.dumps(body),
                         {"X-BRUH-Token": tok, "Content-Type": "application/json"})
            resp = conn.getresponse()
            out = (resp.status, json.loads(resp.read() or b"{}"))
            conn.close()
            return out

        assert post({"name": "recall", "args": {}}, tok="wrong")[0] == 401
        status, out = post({"name": "what_is_normal", "args": {"entity_id": "sensor.freezer"}})
        assert status == 200 and out["result"] == {"usual": {"median": 3}}
        assert post({"name": "explain_change",
                     "args": {"entity_id": "light.hall", "hours": 6}})[1]["result"] == {"changes": []}
        assert "error" in post({"name": "call_service", "args": {}})[1]["result"]
        assert "error" in post({"name": "what_is_normal",
                                "args": {"entity_id": "../etc"}})[1]["result"]
        assert calls == [("normal", "sensor.freezer"), ("why", "light.hall", 6)]
    finally:
        shutdown(pool)


def test_the_bridge_reaches_the_pool_end_to_end(tmp_path, monkeypatch):
    import aiohttp
    from test_pool_http import load_bridge, load_pool_module, shutdown, start_server

    mod = load_pool_module(tmp_path, monkeypatch)
    mcp = mod._mcp_module()
    monkeypatch.setattr(mcp, "recall", lambda **kw: {"facts": [{"text": kw["query"]}]})
    pool = mod.Pool()
    port = _free_port()
    try:
        start_server(mod, pool, port)
        endpoint = json.loads(Path(mod.API_ENDPOINT_FILE).read_text())
        endpoint["host"] = "127.0.0.1"
        Path(mod.API_ENDPOINT_FILE).write_text(json.dumps(endpoint))
        bridge_mod = load_bridge(tmp_path)

        class Config:
            def path(self, *parts):
                return os.path.join(str(tmp_path / "shared"), *parts[1:]) \
                    if parts and parts[0] == ".brain" \
                    else os.path.join(str(tmp_path), *parts)

        class Hass:
            config = Config()

            async def async_add_executor_job(self, fn, *args):
                return fn(*args)

        async def main():
            hass = Hass()
            hass.aiohttp_session = aiohttp.ClientSession()
            try:
                bridge = bridge_mod.ClaudeBridge(hass, timeout=30)
                got = await bridge.async_llm_tool("recall", {"query": "heating"})
                assert got == {"facts": [{"text": "heating"}]}
            finally:
                await hass.aiohttp_session.close()

        asyncio.new_event_loop().run_until_complete(main())
    finally:
        shutdown(pool)


if __name__ == "__main__":
    unittest.main()
