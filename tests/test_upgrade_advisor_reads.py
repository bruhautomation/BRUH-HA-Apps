#!/usr/bin/env python3
"""The upgrade advisor reads the device it is judging (#663, #660).

A firmware update for a Z-Wave switch was answered "Can't tell" because
the run held no tools at all: the facts it needed sat in the node's
configuration parameters, the quote check accepted only a line of the
YAML it was handed, and a correct answer resting on a parameter was
demoted. The reason was then cut at 500 characters mid-word, server side,
with nothing on the card to read the rest, and a safe verdict offered no
way to install it.

What is driven here, and against what:

  * `judge` accepts a configuration quote taken word for word from what a
    TOOL RETURNED, and never from what the run asked a tool (a quote of
    its own question is not a read): the anti-invention guard keeps its
    shape and widens its source;
  * the reason is stored whole; a runaway reply is cut at a word;
  * "Can't tell" says what brAIn could not reach;
  * end to end over a Core that records every command: a Z-Wave node
    whose parameters show the change has no effect is "safe", quoting the
    parameter line the tool returned — and the module itself still asks
    Core for nothing but the notes;
  * the MCP server's `get_device_details` reads the device and, for a
    Z-Wave node, its configuration parameters — three reads, no write —
    and is a reading tool on every list that sorts tools;
  * the run is `run_analyst` scoped to the advisor's reading tools, and
    the tool results come back off the run's own transcript;
  * Install is a person's press on a checked "safe" verdict, through the
    panel's typed-op path with its floors and its ledger row; nothing a
    timer starts reaches it;
  * an update card opens: `GET /api/case/<key>` answers with the whole
    reason, and `/api/cases` carries the cards its `open` count counts.
"""

import ast
import asyncio
import json
import os
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
MCP_DIR = BASE_DIR / "brain" / "ha-mcp-server"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(MCP_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import conversations  # noqa: E402
import engine  # noqa: E402
import ha_data  # noqa: E402
import upgrades  # noqa: E402
from fake_core_ws import FakeCore, ok  # noqa: E402

# An invented in-wall switch and its firmware notes. The change is to a
# parameter's DEFAULT; this node's parameter was set by hand, so the
# change does not reach it — the answer lives on the device, not in YAML.
NOTES = """# Firmware 1.3

## Changes

- The LED indicator parameter (3) now defaults to "On when load is off"; a value already set is kept.
- Faster association reports.
"""

UPDATE = {"entity_id": "update.workshop_switch_firmware",
          "title": "Workshop switch firmware", "installed": "1.2",
          "latest": "1.3", "summary": "", "release_url": "",
          "in_progress": False}

PARAM_LINE = "parameter 3: LED indicator = Always off (value 2)"
# What `get_device_details` hands back, as the MCP server serialises it
# (compact JSON, ASCII-escaped — the em dash arrives as —).
TOOL_RESULT = json.dumps({
    "device": {"name": "Workshop switch", "manufacturer": "Acme",
               "model": "ZW-1", "sw_version": "1.2",
               "integrations": ["zwave_js"]},
    "configuration_parameters": [
        PARAM_LINE + " — Which way the LED shows the load",
        "parameter 7: Ramp rate = 3 (value 3)",
    ]}, separators=(",", ":"))

SAFE = {"verdict": "safe_tonight",
        "reason": "The switch's LED setting was set by hand to Always off, "
                  "and this release only changes the default.",
        "note_quote": "The LED indicator parameter (3) now defaults to "
                      "\"On when load is off\"; a value already set is kept.",
        "config_quote": PARAM_LINE}

READ_TOOLS = ["mcp__home-assistant__get_device_details"]


class TestTheQuoteMayComeFromWhatItRead(unittest.TestCase):
    config = "integrations in use: zwave_js"

    def test_a_safe_resting_on_a_device_parameter_stands(self):
        out = upgrades.judge(SAFE, NOTES, self.config, TOOL_RESULT)
        self.assertEqual(out["verdict"], "safe_tonight", out["reason"])
        self.assertEqual(out["config_quote"], PARAM_LINE)
        self.assertEqual(out["quote_from"], "device")
        self.assertTrue(out["checked"])

    def test_the_config_still_answers_first(self):
        answer = {**SAFE, "config_quote": "integrations in use: zwave_js"}
        out = upgrades.judge(answer, NOTES, self.config, TOOL_RESULT)
        self.assertEqual(out["verdict"], "safe_tonight")
        self.assertEqual(out["quote_from"], "config")

    def test_a_quote_from_nowhere_is_still_not_a_quote(self):
        answer = {**SAFE, "config_quote": "parameter 3: LED indicator = On"}
        out = upgrades.judge(answer, NOTES, self.config, TOOL_RESULT)
        self.assertEqual(out["verdict"], "unknown")
        self.assertFalse(out["checked"])
        self.assertIn("read", out["reason"])

    def test_with_nothing_read_the_old_guard_holds(self):
        out = upgrades.judge(SAFE, NOTES, self.config)
        self.assertEqual(out["verdict"], "unknown")

    def test_an_escaped_character_in_a_result_is_read_as_itself(self):
        lines = upgrades.tool_lines(TOOL_RESULT)
        self.assertIn(PARAM_LINE + " — Which way the LED shows the load",
                      lines)
        self.assertTrue(upgrades.quoted(
            PARAM_LINE + " — Which way", lines))

    def test_an_error_a_tool_returned_is_not_something_read(self):
        """An error message echoes the argument it was given, and the
        argument is the run's own words."""
        echoed = json.dumps({"error": "Unknown entity: " + PARAM_LINE})
        out = upgrades.judge(SAFE, NOTES, self.config, echoed)
        self.assertEqual(out["verdict"], "unknown")


class TestAQuoteOfItsOwnQuestionIsNotARead(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._dir = conversations.CONFIG_DIR
        conversations.CONFIG_DIR = self.tmp.name
        self.addCleanup(setattr, conversations, "CONFIG_DIR", self._dir)
        cwd = "/data/home"
        project = Path(self.tmp.name) / "projects" / conversations._escape(cwd)
        project.mkdir(parents=True)
        rows = [
            {"cwd": cwd, "type": "user", "message": {"role": "user",
                                                      "content": "prompt"}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t1",
                 "name": "mcp__home-assistant__recall",
                 "input": {"query": PARAM_LINE}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t1",
                 "content": [{"type": "text", "text": "{\"facts\":[]}"}]}]}},
            {"type": "assistant", "message": {"content": [
                {"type": "tool_use", "id": "t2",
                 "name": "mcp__home-assistant__get_device_details",
                 "input": {"entity_id": UPDATE["entity_id"]}}]}},
            {"type": "user", "message": {"content": [
                {"type": "tool_result", "tool_use_id": "t2",
                 "content": TOOL_RESULT}]}},
        ]
        (project / "sess-1.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        self.cwd = cwd

    def test_the_results_and_the_tool_names_and_never_the_inputs(self):
        reads = conversations.tool_reads(self.cwd, "sess-1")
        self.assertEqual(reads["tools"], ["mcp__home-assistant__recall",
                                          "mcp__home-assistant__get_device_details"])
        self.assertIn("Workshop switch", reads["results"])
        # The recall's QUERY is the run's own text: it is not a read.
        out = upgrades.judge(SAFE, NOTES, "",
                             reads["results"].replace(PARAM_LINE, "x" * 8))
        self.assertEqual(out["verdict"], "unknown")
        self.assertEqual(reads["results"].count(PARAM_LINE), 1)

    def test_a_result_that_echoes_its_question_is_not_a_read(self):
        reads = conversations.tool_reads(self.cwd, "sess-1")
        echo = json.dumps({"query": PARAM_LINE, "facts": []})
        out = upgrades.judge(SAFE, NOTES, "", echo, asked=reads["asked"])
        self.assertEqual(out["verdict"], "unknown")
        # The same line, read off the device, still stands beside it.
        out = upgrades.judge(SAFE, NOTES, "", reads["results"],
                             asked=json.dumps({"entity_id": UPDATE["entity_id"]}))
        self.assertEqual(out["verdict"], "safe_tonight")

    def test_a_transcript_that_is_not_there_is_none(self):
        self.assertIsNone(conversations.tool_reads(self.cwd, "nope"))


class TestTheWholeReason(unittest.TestCase):
    def test_a_long_reason_is_stored_whole(self):
        reason = ("The switch keeps its LED setting because it was set by "
                  "hand. ") * 25   # ~1,500 characters
        out = upgrades.judge({"verdict": "unknown", "reason": reason},
                             NOTES, "")
        self.assertTrue(out["reason"].startswith(reason.strip()))

    def test_a_runaway_reply_is_cut_at_a_word(self):
        reason = "alpha bravo charlie " * 600
        out = upgrades.judge({"verdict": "unknown", "reason": reason},
                             NOTES, "")
        text = out["reason"]
        self.assertTrue(text.endswith("…"), text[-20:])
        last = text[:-1].split()[-1]
        self.assertIn(last, ("alpha", "bravo", "charlie"))


class TestCantTellSaysWhatItCouldNotReach(unittest.TestCase):
    def test_the_runs_own_words_for_it(self):
        out = upgrades.judge({"verdict": "unknown", "reason": "Not sure.",
                              "could_not_reach": "the switch's configuration "
                                                 "parameters"},
                             NOTES, "", "", tools=READ_TOOLS)
        self.assertEqual(out["unreached"],
                         "the switch's configuration parameters")
        self.assertIn("could not reach the switch's configuration parameters",
                      out["reason"])

    def test_a_run_that_read_nothing_says_so(self):
        out = upgrades.judge({"verdict": "unknown", "reason": "Not sure."},
                             NOTES, "", None, tools=[])
        self.assertIn("read nothing in Home Assistant", out["reason"])


class TestEndToEndOverTheDevice(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        Path(self.tmp.name, "configuration.yaml").write_text(
            "homeassistant:\n  name: Home\n", encoding="utf-8")
        self.core = await FakeCore({
            "update/release_notes": lambda cmd: ok(NOTES)}).start()
        self._ws = ha_data.CORE_WS
        ha_data.CORE_WS = self.core.url
        self.prompts: list[str] = []
        self.systems: list[str] = []

    async def asyncTearDown(self):
        ha_data.CORE_WS = self._ws
        await self.core.close()
        self.tmp.cleanup()

    async def advise(self, reply):
        import aiohttp

        async def run(prompt, system, schema):
            self.prompts.append(prompt)
            self.systems.append(system)
            return reply

        async with aiohttp.ClientSession() as session:
            return await upgrades.advise(session, dict(UPDATE), run,
                                         root=self.tmp.name)

    async def test_a_node_whose_parameters_show_no_effect_is_safe(self):
        verdict = await self.advise({
            "ok": True, "meta": {"session_id": "s1"}, "data": SAFE,
            "tool_read": TOOL_RESULT, "tools": READ_TOOLS})
        self.assertEqual(verdict["verdict"], "safe_tonight", verdict["reason"])
        self.assertEqual(verdict["config_quote"], PARAM_LINE)
        self.assertEqual(verdict["quote_from"], "device")
        self.assertEqual(verdict["read_tools"], ["get_device_details"])
        # The run is told which entity to read, and that it can.
        self.assertIn(UPDATE["entity_id"], self.prompts[0])
        self.assertIn("get_device_details", self.systems[0])
        # The module itself asked Core for the notes and nothing else.
        self.assertEqual(self.core.types(), ["update/release_notes"])

    async def test_the_same_answer_with_nothing_read_is_not_safe(self):
        verdict = await self.advise({"ok": True, "data": SAFE})
        self.assertEqual(verdict["verdict"], "unknown")


class _FakeWs:
    def __init__(self, zwave=True):
        self.asked: list[dict] = []
        self.zwave = zwave

    def __call__(self, payload, timeout=15):
        self.asked.append(payload)
        kind = payload["type"]
        if kind == "config/entity_registry/get":
            return {"entity_id": payload["entity_id"], "device_id": "dev1",
                    "platform": "zwave_js" if self.zwave else "esphome"}
        if kind == "config/device_registry/list":
            return [{"id": "dev0", "name": "Other"},
                    {"id": "dev1", "name": "Workshop switch",
                     "name_by_user": None, "manufacturer": "Acme",
                     "model": "ZW-1", "sw_version": "1.2", "hw_version": "3",
                     "area_id": "workshop",
                     "identifiers": [["zwave_js", "4242-12"]] if self.zwave
                     else [["esphome", "aa:bb"]]}]
        if kind == "zwave_js/get_config_parameters":
            return {
                "12-112-0-3": {"property": 3, "property_key": None,
                               "endpoint": 0, "value": 2,
                               "metadata": {"label": "LED indicator",
                                            "description": "Which way the LED shows the load",
                                            "states": {"0": "On when load is on",
                                                       "1": "On when load is off",
                                                       "2": "Always off"}}},
                "12-112-0-7": {"property": 7, "property_key": None,
                               "endpoint": 0, "value": 3,
                               "metadata": {"label": "Ramp rate", "unit": "s"}},
            }
        raise AssertionError(payload)


class TestTheDeviceTool(unittest.TestCase):
    def setUp(self):
        import ha_mcp_server
        self.m = ha_mcp_server

    def test_a_zwave_node_comes_with_its_parameters(self):
        fake = _FakeWs()
        with unittest.mock.patch.object(self.m, "_ws_command", fake):
            out = self.m.get_device_details(entity_id=UPDATE["entity_id"])
        self.assertEqual(out["device"]["name"], "Workshop switch")
        self.assertEqual(out["device"]["sw_version"], "1.2")
        self.assertIn(PARAM_LINE + " — Which way the LED shows the load",
                      out["configuration_parameters"])
        self.assertIn("parameter 7: Ramp rate = 3 s (value 3)",
                      out["configuration_parameters"])
        self.assertEqual([a["type"] for a in fake.asked],
                         ["config/entity_registry/get",
                          "config/device_registry/list",
                          "zwave_js/get_config_parameters"])

    def test_another_device_is_read_without_a_zwave_command(self):
        fake = _FakeWs(zwave=False)
        with unittest.mock.patch.object(self.m, "_ws_command", fake):
            out = self.m.get_device_details(device_id="dev1")
        self.assertNotIn("configuration_parameters", out)
        self.assertNotIn("zwave_js/get_config_parameters",
                         [a["type"] for a in fake.asked])

    def test_it_is_a_reading_tool_everywhere_tools_are_sorted(self):
        name = f"{engine.MCP}get_device_details"
        self.assertIn(name, engine.ANALYST_TOOLS)
        self.assertNotIn(name, engine.ANALYST_DENIED)
        self.assertIn("get_device_details", self.m.TOOL_IMPLEMENTATIONS)
        self.assertIn("get_device_details", self.m.VOICE_REFUSED_TOOLS)


class TestTheAdvisorsRun(unittest.TestCase):
    def test_the_advisor_reads_and_cannot_act(self):
        allow = set(engine.ADVISOR_TOOLS)
        self.assertLessEqual(allow, set(engine.ANALYST_TOOLS))
        self.assertFalse(allow & set(engine.ANALYST_DENIED))
        for name in ("get_device_details", "get_entity_state", "recall",
                     "get_registry", "get_history"):
            self.assertIn(f"{engine.MCP}{name}", allow)

    def test_run_analyst_scoped_denies_the_rest(self):
        seen = {}

        def fake_cli(prompt, flags, *a, **k):
            seen["flags"] = flags
            return {"ok": True}

        with unittest.mock.patch.object(engine, "_run_cli", fake_cli):
            engine.run_analyst("p", "s", allow=list(engine.ADVISOR_TOOLS))
        flags = seen["flags"]
        allowed = flags[flags.index("--allowedTools") + 1].split(",")
        denied = flags[flags.index("--disallowedTools") + 1].split(",")
        self.assertEqual(sorted(allowed), sorted(engine.ADVISOR_TOOLS))
        for name in engine.ANALYST_TOOLS:
            if name not in engine.ADVISOR_TOOLS:
                self.assertIn(name, denied)
        for name in engine.ANALYST_DENIED:
            self.assertIn(name, denied)

    def test_a_scope_outside_the_reading_tools_is_refused(self):
        with self.assertRaises(ValueError):
            engine.run_analyst("p", "s", allow=[f"{engine.MCP}call_service"])

    def test_the_server_runs_it_with_tools_and_reads_back_what_they_returned(self):
        import server
        seen = {}

        def fake_analyst(prompt, system, model="", timeout=0, max_turns=0,
                         source="", **kw):
            seen.update(model=model, max_turns=max_turns, **kw)
            return {"ok": True, "meta": {"session_id": "sess-9"}, "data": {}}

        with unittest.mock.patch.object(server.engine, "run_analyst", fake_analyst), \
                unittest.mock.patch.object(server.engine, "run_claude",
                                  side_effect=AssertionError("tool-less")), \
                unittest.mock.patch.object(server.conversations, "tool_reads",
                                  lambda cwd, sid: {"results": TOOL_RESULT,
                                                    "tools": READ_TOOLS}):
            out = server._advise_run("p", upgrades.SYSTEM, upgrades.SCHEMA)
        self.assertEqual(seen["allow"], engine.ADVISOR_TOOLS)
        self.assertEqual(seen["job"], "upgrade_advice")
        self.assertGreaterEqual(seen["max_turns"], 20)
        self.assertFalse(seen["pressed"])
        self.assertEqual(out["tool_read"], TOOL_RESULT)
        self.assertEqual(out["tools"], READ_TOOLS)

    def test_a_pressed_check_runs_on_the_chats_model(self):
        import server
        seen = {}

        def fake_analyst(prompt, system, model="", *a, **kw):
            seen.update(model=model, **kw)
            return {"ok": False, "error": "x"}

        with unittest.mock.patch.object(server.engine, "run_analyst", fake_analyst), \
                unittest.mock.patch.object(server, "eff_chat_model", lambda: "opus"):
            server._advise_run("p", "s", {}, pressed=True)
        self.assertEqual(seen["model"], "opus")
        self.assertTrue(seen["pressed"])


def _call(handler, *, body=None, match=None):
    from aiohttp.test_utils import make_mocked_request
    req = make_mocked_request("POST" if body is not None else "GET", "/x",
                              match_info=match or {})

    async def go():
        import server
        with unittest.mock.patch.object(server, "_json_body",
                               unittest.mock.AsyncMock(return_value=body or {})):
            return await handler(req)
    return asyncio.run(go())


class _Store(unittest.TestCase):
    def setUp(self):
        import server
        self.server = server
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        store = os.path.join(self.tmp.name, "upgrades.json")
        p = unittest.mock.patch.object(upgrades, "STORE", store)
        p.start()
        self.addCleanup(p.stop)
        hidden = unittest.mock.patch.object(server.today_mod, "HIDDEN_FILE",
                                   Path(self.tmp.name) / "hidden.json")
        hidden.start()
        self.addCleanup(hidden.stop)
        self.pending = [dict(UPDATE)]

        async def pending():
            return self.pending
        p = unittest.mock.patch.object(server, "_pending_updates", pending)
        p.start()
        self.addCleanup(p.stop)

    def remember(self, verdict="safe_tonight", checked=True, reason="Fine."):
        upgrades.remember({**UPDATE, "verdict": verdict, "checked": checked,
                           "reason": reason, "at": 1})


class _Hooks:
    def __init__(self, supported=8):
        self.calls: list = []
        self.rows: list = []
        self.supported = supported

    def make(self):
        import typed_fix

        async def call(domain, service, data):
            self.calls.append((domain, service, data))

        async def state(eid):
            return {"entity_id": eid, "state": "on",
                    "attributes": {"supported_features": self.supported}}

        async def nothing(*a, **k):
            return None

        return typed_fix.Hooks(apply_edit=nothing, revert_edit=nothing,
                               call=call, state=state, ws=nothing,
                               ledger=self.rows.append)


class TestInstallIsAPersonsPress(_Store):
    def install(self, hooks, body=None, protected=()):
        s = self.server
        with unittest.mock.patch.object(s, "_typed_hooks", hooks.make), \
                unittest.mock.patch.object(s.automation_writer, "protected_patterns",
                                  lambda *a: list(protected)), \
                unittest.mock.patch.object(s.security, "honeytoken_ids", lambda: []):
            return _call(s.h_upgrades_install, body=body or {
                "entity_id": UPDATE["entity_id"], "latest": UPDATE["latest"]})

    def test_a_checked_safe_verdict_installs_with_a_backup_where_offered(self):
        self.remember()
        hooks = _Hooks()
        resp = self.install(hooks)
        self.assertEqual(resp.status, 200)
        self.assertEqual(hooks.calls, [("update", "install", {
            "backup": True, "entity_id": [UPDATE["entity_id"]]})])
        self.assertEqual(hooks.rows[0]["channel"], "panel")
        self.assertEqual(hooks.rows[0]["service"], "install")

    def test_no_backup_flag_where_the_update_does_not_offer_one(self):
        self.remember()
        hooks = _Hooks(supported=1)
        self.install(hooks)
        self.assertEqual(hooks.calls[0][2], {"entity_id": [UPDATE["entity_id"]]})

    def test_wait_and_cant_tell_are_never_installed_from_here(self):
        from aiohttp import web
        for verdict, checked in (("wait", True), ("unknown", False),
                                 ("safe_tonight", False)):
            self.remember(verdict, checked)
            hooks = _Hooks()
            with self.subTest(verdict=verdict, checked=checked):
                with self.assertRaises(web.HTTPConflict):
                    self.install(hooks)
                self.assertEqual(hooks.calls, [])

    def test_a_version_that_moved_on_is_not_installed(self):
        from aiohttp import web
        self.remember()
        self.pending = [{**UPDATE, "latest": "1.4"}]
        hooks = _Hooks()
        with self.assertRaises(web.HTTPConflict):
            self.install(hooks)
        self.assertEqual(hooks.calls, [])

    def test_the_protected_list_still_stands(self):
        from aiohttp import web
        self.remember()
        hooks = _Hooks()
        with self.assertRaises(web.HTTPConflict):
            self.install(hooks, protected=["update.*"])
        self.assertEqual(hooks.calls, [])


class TestNothingUnattendedInstalls(unittest.TestCase):
    """Read off the AST: the one function in the server that names the
    install service is the press's own, and it is reached from one POST
    route and from nothing a loop calls."""

    def test_install_is_named_once_and_only_a_route_reaches_it(self):
        src = (PANEL_DIR / "server.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        owners = set()
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for node in ast.walk(fn):
                if isinstance(node, ast.Constant) and node.value in (
                        "install", "update.install"):
                    owners.add(fn.name)
        self.assertEqual(owners, {"h_upgrades_install"})
        callers = [n for n in ast.walk(tree) if isinstance(n, ast.Name)
                   and n.id == "h_upgrades_install"]
        self.assertEqual(len(callers), 1, "reached from somewhere else")
        self.assertIn('app.router.add_post("/api/upgrades/install", '
                      'h_upgrades_install)', src)


class TestTheCardOpens(_Store):
    def test_an_update_key_opens_with_the_whole_reason(self):
        reason = ("word " * 300).strip()
        self.remember(reason=reason)
        with unittest.mock.patch.object(self.server, "UPGRADES_SEEN",
                               {"updates": [dict(UPDATE)], "at": 1}):
            key = self.server.today_mod.update_key(UPDATE)
            resp = _call(self.server.h_case_get, match={"id": key})
        data = json.loads(resp.body)
        self.assertEqual(data["kind"], "update")
        self.assertEqual(data["card"]["advice"]["reason"], reason)

    def test_an_unknown_id_is_a_404(self):
        from aiohttp import web
        with self.assertRaises(web.HTTPNotFound):
            _call(self.server.h_case_get, match={"id": "update:update.nope:1"})

    def test_the_cases_listing_carries_what_its_count_counts(self):
        self.remember()
        with unittest.mock.patch.object(self.server, "UPGRADES_SEEN",
                               {"updates": [dict(UPDATE)], "at": 1}), \
                unittest.mock.patch.object(self.server.cases, "list_cases",
                                  lambda now=None: []), \
                unittest.mock.patch.object(self.server.cases, "queue_count",
                                  lambda now=None: 0):
            payload = self.server._cases_payload()
        self.assertEqual(payload["open"], 1)
        self.assertEqual([u["entity_id"] for u in payload["today"]["updates"]],
                         [UPDATE["entity_id"]])


if __name__ == "__main__":
    unittest.main()
