#!/usr/bin/env python3
"""Scripts written into the running world, and plugin answers that only reach
the console.

#667: nothing outside the add-on could put a Skript script or a data pack
function into the world's folders, so a click-triggered item could not be
made. `write_script` / `remove_script` / `list_scripts` now do it through the
panel (panel/worldscripts.py), load it without a restart, and answer with the
loader's errors.

#669: a plugin command run through `rcon_command` (SkinsRestorer's `skin set`,
`sr status`) came back "" because the plugin answers the console logger, not
the RCON sender. The console lines the server writes right after the command
are now the reply (scripts/console_reply.py), in the bridge and the panel.

Fakes throughout: an RCON that returns "" and appends lines to a console file
the way the server would.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "bruh-minecraft-server"
SCRIPTS = ADDON / "scripts"
BRIDGE_PY = ADDON / "integrations" / "ha-bridge.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_minecraft_services as svc  # noqa: E402

Base, Call, HAError, Invalid = svc.Base, svc.Call, svc.HAError, svc.Invalid


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


console_reply = _load("console_reply_under_test", SCRIPTS / "console_reply.py")
worldscripts = _load("worldscripts_under_test", ADDON / "panel" / "worldscripts.py")


class FakeServer:
    """An RCON whose replies are scripted, writing console lines as it answers."""

    def __init__(self, log: Path, replies: dict[str, tuple[str, list[str]]] | None = None):
        self.log = log
        self.replies = replies or {}
        self.sent: list[str] = []

    def __call__(self, cmd: str) -> str:
        self.sent.append(cmd)
        reply, lines = self.replies.get(cmd, ("", []))
        lines = ["[12:00:00 INFO]: Thread RCON Client /127.0.0.1 started",
                 f"[12:00:00 INFO]: CONSOLE issued server command: /{cmd}", *lines,
                 "[12:00:00 INFO]: Thread RCON Client /127.0.0.1 shutting down"]
        with open(self.log, "a", encoding="utf-8") as fh:
            fh.write("".join(line + "\n" for line in lines))
        return reply


# ---------------------------------------------------------------------------
# #669: the console is the answer when RCON says nothing
# ---------------------------------------------------------------------------
class TestConsoleReply(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.log = Path(tmp.name) / "console.log"
        self.log.write_text("[11:59:00 INFO]: Done (3.1s)! For help, type \"help\"\n")

    def test_a_plugin_that_answers_the_console_is_heard(self):
        server = FakeServer(self.log, {"skin set Steve Notch": ("", [
            "[12:00:00 INFO]: \x1b[0;32;1m[SkinsRestorer] §aYour skin has been changed.\x1b[m",
        ])})
        got = console_reply.command(server, "skin set Steve Notch", self.log, wait=2.0)
        self.assertEqual(got, "[SkinsRestorer] Your skin has been changed.")

    def test_a_second_plugin_and_its_error(self):
        # Not the issue's command: a status line and an error from another
        # plugin, with chat in the same second that is not the answer.
        server = FakeServer(self.log, {"sr status": ("", [
            "[12:00:00 INFO]: <Alex> anyone home?",
            "[12:00:00 WARN]: [SkinsRestorer] Player not found",
        ])})
        got = console_reply.command(server, "sr status", self.log, wait=2.0)
        self.assertEqual(got, "[SkinsRestorer] Player not found")

    def test_an_rcon_reply_is_left_as_it_was(self):
        server = FakeServer(self.log, {"list": ("There are 0 of a max of 20 players online:",
                                                ["[12:00:00 INFO]: something else"])})
        self.assertEqual(console_reply.command(server, "list", self.log),
                         "There are 0 of a max of 20 players online:")

    def test_no_console_file_is_rcon_alone_and_does_not_wait(self):
        server = FakeServer(self.log)
        missing = self.log.with_name("nope.log")
        slept = []
        self.assertEqual(console_reply.command(lambda c: "", "x", missing,
                                               sleep=slept.append), "")
        self.assertEqual(slept, [])
        del server

    def test_silence_everywhere_is_empty_after_the_wait(self):
        now = [0.0]

        def sleep(s):
            now[0] += s

        got = console_reply.command(lambda c: "", "noop", self.log, wait=1.0,
                                    sleep=sleep, clock=lambda: now[0])
        self.assertEqual(got, "")
        self.assertGreaterEqual(now[0], 1.0)


def _load_bridge(panel_state: Path, run):
    rcon_mod = types.ModuleType("rcon_client")

    class Rcon:
        def __init__(self, *a, **kw):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def command(self, cmd):
            return run(cmd)

    rcon_mod.Rcon = Rcon
    saved = sys.modules.get("rcon_client")
    sys.modules["rcon_client"] = rcon_mod
    os.environ["MC_PANEL_STATE"] = str(panel_state)
    try:
        mod = _load("ha_bridge_world_scripts", BRIDGE_PY)
    finally:
        os.environ.pop("MC_PANEL_STATE", None)
        if saved is None:
            sys.modules.pop("rcon_client", None)
        else:
            sys.modules["rcon_client"] = saved
    return mod


class TestTheBridgeHearsTheConsole(unittest.TestCase):
    def test_rcon_command_returns_the_plugins_own_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "console.log"
            log.write_text("")
            server = FakeServer(log, {"skin set Steve Notch": ("", [
                "[12:00:00 INFO]: [SkinsRestorer] Your skin has been changed."])})
            bridge = _load_bridge(Path(tmp), server)
            got = asyncio.run(bridge.handle({"kind": "command",
                                             "payload": {"command": "/skin set Steve Notch"}}))
        self.assertEqual(got, {"ok": True,
                               "reply": "[SkinsRestorer] Your skin has been changed."})


class TestTheServiceJudgesTheHeardAnswer(Base):
    def test_a_console_error_is_a_refusal(self):
        self.answer = {"ok": True, "reply": "Player not found"}
        with self.assertRaises(HAError) as ctx:
            self.call("rcon_command", command="sr status")
        self.assertIn("Player not found", str(ctx.exception))

    def test_a_console_success_is_the_reply(self):
        self.answer = {"ok": True, "reply": "[SkinsRestorer] Your skin has been changed."}
        self.assertEqual(self.call("rcon_command", command="skin set Steve Notch"),
                         {"reply": "[SkinsRestorer] Your skin has been changed."})


# ---------------------------------------------------------------------------
# #667: scripts written into the world
# ---------------------------------------------------------------------------
SKRIPT_OK = ["[12:00:00 INFO]: [Skript] Reloading wand.sk...",
             "[12:00:00 INFO]: [Skript] Successfully reloaded wand.sk. (12ms)"]
SKRIPT_BAD = ["[12:00:00 INFO]: [Skript] Reloading wand.sk...",
              "[12:00:00 ERROR]: [Skript] Line 2: (wand.sk)",
              "    Can't understand this event: 'on rihgt click'",
              "    Line: on rihgt click:",
              "[12:00:00 INFO]: [Skript] Encountered 1 error while reloading wand.sk! (5ms)"]


class WorldBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.server_dir = Path(tmp.name) / "server"
        (self.server_dir / "plugins").mkdir(parents=True)
        (self.server_dir / "world").mkdir()
        self.log = Path(tmp.name) / "console.log"
        self.log.write_text("")
        self.server = FakeServer(self.log)

    def run_cmd(self, cmd, listen):
        if listen:
            # The fake writes its lines before it answers, so a short window
            # hears everything; a silent reload costs the whole window.
            return console_reply.command(self.server, cmd, self.log, always=True, wait=0.3,
                                         settle=0.1)
        return self.server(cmd)

    def write(self, kind, name, content, version="1.21.4"):
        return worldscripts.write(self.server_dir, "world", version, kind, name, content,
                                  self.run_cmd, by="brAIn")

    def remove(self, kind, name, version="1.21.4"):
        return worldscripts.remove(self.server_dir, "world", version, kind, name, self.run_cmd)

    def skript(self):
        (self.server_dir / "plugins" / "Skript-2.9.5.jar").write_bytes(b"jar")


class TestSkriptScripts(WorldBase):
    WAND = "on right click with blaze rod:\n    send \"zap\" to player\n"

    def test_refused_without_the_skript_plugin(self):
        (self.server_dir / "plugins" / "skript-reflect-2.5.jar").write_bytes(b"jar")
        with self.assertRaises(worldscripts.ScriptError) as ctx:
            self.write("skript", "wand", self.WAND)
        self.assertIn("Skript plugin is not installed", str(ctx.exception))
        self.assertEqual(self.server.sent, [])

    def test_written_reloaded_and_recorded(self):
        self.skript()
        self.server.replies["sk reload wand.sk"] = ("", SKRIPT_OK)
        got = self.write("skript", "wand", self.WAND)
        path = self.server_dir / "plugins" / "Skript" / "scripts" / "wand.sk"
        self.assertEqual(path.read_text(), self.WAND)
        self.assertTrue(got["reloaded"])
        self.assertIn("Successfully reloaded", got["reply"])
        self.assertEqual(self.server.sent, ["sk reload wand.sk"])
        listed = worldscripts.listing(self.server_dir)
        self.assertTrue(listed["skript_installed"])
        self.assertEqual([(r["kind"], r["name"], r["by"], r["loaded"], r["present"])
                          for r in listed["scripts"]],
                         [("skript", "wand", "brAIn", True, True)])

    def test_parse_errors_are_the_answer_and_the_file_stays_to_fix(self):
        self.skript()
        self.server.replies["sk reload wand.sk"] = ("", SKRIPT_BAD)
        with self.assertRaises(worldscripts.ScriptError) as ctx:
            self.write("skript", "wand", "on rihgt click:\n    stop\n")
        self.assertEqual(ctx.exception.status, 422)
        self.assertIn("Can't understand this event", str(ctx.exception))
        self.assertIn("[Skript] Line 2: (wand.sk)", ctx.exception.errors)
        self.assertFalse(any("Reloading" in e for e in ctx.exception.errors))
        self.assertFalse(worldscripts.listing(self.server_dir)["scripts"][0]["loaded"])
        # Its own script, so the fix may overwrite it.
        self.server.replies["sk reload wand.sk"] = ("", SKRIPT_OK)
        self.write("skript", "wand", self.WAND)

    def test_somebody_elses_script_is_never_overwritten_or_removed(self):
        self.skript()
        theirs = self.server_dir / "plugins" / "Skript" / "scripts" / "homes.sk"
        theirs.parent.mkdir(parents=True)
        theirs.write_text("command /home:\n")
        with self.assertRaises(worldscripts.ScriptError) as ctx:
            self.write("skript", "homes", self.WAND)
        self.assertIn("was not written here", str(ctx.exception))
        with self.assertRaises(worldscripts.ScriptError):
            self.remove("skript", "homes")
        self.assertEqual(theirs.read_text(), "command /home:\n")
        self.assertEqual(self.server.sent, [])

    def test_remove_unloads_and_deletes_only_its_own(self):
        self.skript()
        self.write("skript", "wand", self.WAND)
        got = self.remove("skript", "wand")
        self.assertEqual(got["removed"], "wand")
        self.assertIn("sk disable wand.sk", self.server.sent)
        self.assertFalse((self.server_dir / "plugins" / "Skript" / "scripts" / "wand.sk").exists())
        self.assertEqual(worldscripts.listing(self.server_dir)["scripts"], [])

    def test_names_and_sizes(self):
        self.skript()
        for bad in ("../../server", "a/b", "..", "", "Wand", "x" * 49, "wand.sh", "-x",
                    "a b", "plugins\\x"):
            with self.subTest(name=bad), self.assertRaises(worldscripts.ScriptError):
                self.write("skript", bad, self.WAND)
        with self.assertRaises(worldscripts.ScriptError) as ctx:
            self.write("skript", "big", "#" * (worldscripts.MAX_BYTES + 1))
        self.assertEqual(ctx.exception.status, 413)
        with self.assertRaises(worldscripts.ScriptError):
            self.write("shell", "wand", self.WAND)
        with self.assertRaises(worldscripts.ScriptError):
            self.write("skript", "wand", "  \n")
        self.assertEqual(self.server.sent, [])
        # `wand.sk` is the name `wand`.
        self.write("skript", "wand.sk", self.WAND)
        self.assertTrue((self.server_dir / "plugins" / "Skript" / "scripts" / "wand.sk").is_file())

    def test_a_server_that_is_down_keeps_the_script_for_its_start(self):
        self.skript()

        def down(cmd, listen):
            raise ConnectionRefusedError("refused")

        got = worldscripts.write(self.server_dir, "world", "1.21.4", "skript", "wand",
                                 self.WAND, down)
        self.assertFalse(got["reloaded"])
        self.assertIn("loads when it starts", got["note"])


class TestDatapackFunctions(WorldBase):
    def test_written_into_the_pack_and_reloaded(self):
        self.server.replies["minecraft:datapack list enabled"] = (
            'There are 2 data packs enabled: [vanilla (built-in)], [file/bruh_companion]', [])
        got = self.write("datapack_function", "zap", "particle minecraft:flame ~ ~1 ~\n")
        pack = self.server_dir / "world" / "datapacks" / "bruh_scripts"
        self.assertTrue((pack / "pack.mcmeta").is_file())
        self.assertEqual((pack / "data" / "bruh_scripts" / "function" / "zap.mcfunction")
                         .read_text(), "particle minecraft:flame ~ ~1 ~\n")
        self.assertEqual(got["call"], "bruh_scripts:zap")
        self.assertEqual(self.server.sent, ["minecraft:reload",
                                            "minecraft:datapack list enabled",
                                            'minecraft:datapack enable "file/bruh_scripts"'])

    def test_an_older_server_reads_the_functions_folder(self):
        self.write("datapack_function", "zap", "say hi\n", version="1.20.4")
        self.assertTrue((self.server_dir / "world" / "datapacks" / "bruh_scripts" / "data"
                         / "bruh_scripts" / "functions" / "zap.mcfunction").is_file())
        self.remove("datapack_function", "zap", version="1.20.4")
        self.assertFalse(any((self.server_dir / "world" / "datapacks").rglob("*.mcfunction")))

    def test_its_load_failure_is_the_answer_and_another_packs_is_not(self):
        self.server.replies["minecraft:reload"] = ("", [
            "[12:00:00 ERROR]: Failed to load function otherpack:tick",
            "java.lang.IllegalArgumentException: Whilst parsing command on line 1: Unknown "
            "or incomplete command, see below for error at position 0: <--[HERE]",
            "[12:00:00 ERROR]: Failed to load function bruh_scripts:zap",
            "java.util.concurrent.CompletionException: java.lang.IllegalArgumentException: "
            "Whilst parsing command on line 1: Unknown or incomplete command, see below for "
            "error at position 0: <--[HERE]",
            "\tat java.base/java.util.concurrent.CompletableFuture.encodeThrowable",
        ])
        with self.assertRaises(worldscripts.ScriptError) as ctx:
            self.write("datapack_function", "zap", "partcle flame\n")
        errors = ctx.exception.errors
        self.assertTrue(any("bruh_scripts:zap" in e for e in errors))
        self.assertFalse(any("otherpack" in e for e in errors))
        self.assertTrue(any("Whilst parsing" in e for e in errors))
        self.assertFalse(any("CompletableFuture" in e for e in errors))

    def test_a_world_that_does_not_exist_yet_is_refused(self):
        with self.assertRaises(worldscripts.ScriptError):
            worldscripts.write(self.server_dir, "other", "1.21.4", "datapack_function", "zap",
                               "say hi\n", self.run_cmd)

    def test_a_record_pointing_elsewhere_is_not_believed(self):
        self.write("datapack_function", "zap", "say hi\n")
        outside = self.server_dir / "server.properties"
        outside.write_text("motd=x\n")
        record = worldscripts.read_record(self.server_dir)
        record["datapack_function:zap"]["path"] = "server.properties"
        worldscripts.write_record(self.server_dir, record)
        self.remove("datapack_function", "zap")
        self.assertTrue(outside.is_file())


class TestScriptServices(Base):
    def test_write_remove_and_list_carry_the_request(self):
        self.answer = {"ok": True, "name": "wand", "reloaded": True}
        handler, mode = self.handlers["write_script"]
        self.assertEqual(mode, "optional")
        got = asyncio.run(handler(Call({"kind": "skript", "name": "wand.sk",
                                        "content": "on load:\n", "by": "brAIn\nx"})))
        self.assertEqual(got, {"name": "wand", "reloaded": True})
        self.assertEqual(self.sent[-1], ("script_write", {
            "kind": "skript", "name": "wand", "content": "on load:\n", "by": "brAIn x"}))
        asyncio.run(self.handlers["remove_script"][0](Call({"kind": "datapack_function",
                                                            "name": "zap"})))
        self.assertEqual(self.sent[-1], ("script_remove", {"kind": "datapack_function",
                                                           "name": "zap"}))
        self.assertEqual(self.handlers["list_scripts"][1], "only")
        self.call("list_scripts")
        self.assertEqual(self.sent[-1], ("script_list", {}))

    def test_a_script_that_did_not_load_is_an_error_with_its_errors(self):
        self.answer = {"ok": False, "error": "wand was saved but did not load: Line 2: (wand.sk)"}
        with self.assertRaises(HAError) as ctx:
            asyncio.run(self.handlers["write_script"][0](Call({
                "kind": "skript", "name": "wand", "content": "x"})))
        self.assertIn("Line 2", str(ctx.exception))

    def test_names_and_content_are_checked_before_anything_is_sent(self):
        for bad in ("../x", "a/b", "Wand", ""):
            with self.subTest(name=bad), self.assertRaises(Invalid):
                self.mod._script_name(bad)
        with self.assertRaises(Invalid):
            self.mod._script_content("x" * (64 * 1024 + 1))
        self.assertEqual(self.mod._script_name("zap.mcfunction"), "zap")


class TestTheBridgeCarriesScripts(unittest.TestCase):
    # Borrowed, not inherited, so the services file's own tests run once.
    load = svc.TestTheBridgeAnswersStatus.load
    serve = svc.TestTheBridgeAsksThePanelForAddons.serve

    def test_write_and_remove_reach_the_panel(self):
        url, seen = self.serve(200, {"ok": True, "name": "wand"})
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.load(tmp, "")
            mod.PANEL_URL = url
            got = asyncio.run(mod.handle({"kind": "script_write", "payload": {
                "kind": "skript", "name": "wand", "content": "on load:\n"}}))
            asyncio.run(mod.handle({"kind": "script_remove", "payload": {
                "kind": "skript", "name": "../wand"}}))
        self.assertTrue(got["ok"])
        self.assertEqual(seen[0][:2], ("POST", "/api/scripts"))
        self.assertEqual(json.loads(seen[0][2])["content"], "on load:\n")
        # The name is quoted into one path segment; the panel refuses it.
        self.assertEqual(seen[1][:2], ("DELETE", "/api/scripts/skript/..%2Fwand"))

    def test_the_panels_refusal_is_carried(self):
        url, _ = self.serve(422, {"error": "wand was saved but did not load: Line 2",
                                  "errors": ["Line 2"]})
        with tempfile.TemporaryDirectory() as tmp:
            mod = self.load(tmp, "")
            mod.PANEL_URL = url
            got = asyncio.run(mod.handle({"kind": "script_write", "payload": {
                "kind": "skript", "name": "wand", "content": "x"}}))
        self.assertFalse(got["ok"])
        self.assertIn("did not load", got["error"])


import test_minecraft_panel as panel_tests  # noqa: E402


class TestThePanelRoutes(panel_tests.PanelTestBase):
    """The panel is the one writer; its console box hears plugins too."""

    async def test_the_console_box_hears_a_plugin(self):
        log = self.state_dir / "console.log"
        log.write_text("")
        self.panel._rcon_sync = FakeServer(log, {"sr status": ("", [
            "[12:00:00 INFO]: [SkinsRestorer] Version 15.4.2, all good"])})
        resp = await self.client.request("POST", "/api/command", json={"command": "sr status"})
        self.assertEqual(await resp.json(), {"reply": "[SkinsRestorer] Version 15.4.2, all good"})

    async def test_write_list_and_remove(self):
        (self.server_dir / "world").mkdir()
        log = self.state_dir / "console.log"
        log.write_text("")
        self.panel._rcon_sync = FakeServer(log)
        self.panel.SCRIPT_LISTEN_S, self.panel.SCRIPT_SETTLE_S = 0.3, 0.1
        resp = await self.client.request("POST", "/api/scripts", json={
            "kind": "skript", "name": "wand", "content": "on load:\n"})
        self.assertEqual(resp.status, 409)
        self.assertIn("Skript plugin is not installed", (await resp.json())["error"])
        resp = await self.client.request("POST", "/api/scripts", json={
            "kind": "datapack_function", "name": "zap", "content": "say hi\n"})
        body = await resp.json()
        self.assertEqual(resp.status, 200, body)
        self.assertEqual(body["call"], "bruh_scripts:zap")
        listed = await (await self.client.request("GET", "/api/scripts")).json()
        self.assertEqual([r["name"] for r in listed["scripts"]], ["zap"])
        resp = await self.client.request("DELETE", "/api/scripts/datapack_function/zap")
        self.assertEqual(resp.status, 200)
        resp = await self.client.request("DELETE", "/api/scripts/datapack_function/zap")
        self.assertEqual(resp.status, 404)
        resp = await self.client.request("DELETE", "/api/scripts/skript/..%2F..%2Fserver")
        self.assertIn(resp.status, (400, 404))


if __name__ == "__main__":
    unittest.main()
