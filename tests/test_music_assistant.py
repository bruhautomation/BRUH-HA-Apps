#!/usr/bin/env python3
"""Music Assistant, driven against a server that speaks its protocol.

The fake below is a real aiohttp WebSocket server doing what Music
Assistant's `websocket_client.py` does: it sends its server info first,
refuses every command before `auth` from schema 28 on, answers an
unauthenticated token with `InvalidToken` (23), splits a long list into
`partial` chunks, pushes events between results, and refuses a provider
change from a `service` user with `InsufficientPermissions` (22) — the
shapes read off the server's source rather than guessed, because a fake
that accepts whatever it is handed proves only that it matches the code
that mocked it.
"""

import asyncio
import http.server
import json
import os
import sys
import tempfile
import threading
import unittest
import unittest.mock as mock
from pathlib import Path

from aiohttp import web

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))

import music_assistant as ma  # noqa: E402

SERVICE_TOKEN = "ha-integration-token"
ADMIN_TOKEN = "admin-token"

PROVIDERS = [
    {"instance_id": "chromecast--abc", "domain": "chromecast", "name": "Chromecast",
     "type": "player", "available": True},
    {"instance_id": "spotify--1", "domain": "spotify", "name": "Spotify",
     "type": "music", "available": True},
]
PROVIDER_CONFIGS = [
    {"instance_id": "chromecast--abc", "domain": "chromecast", "enabled": True},
    {"instance_id": "spotify--1", "domain": "spotify", "enabled": True},
    # Configured and failed to load: absent from `providers` entirely.
    {"instance_id": "sonos--9", "domain": "sonos", "name": "Sonos",
     "type": "player", "enabled": True, "last_error": "no Sonos found"},
]


def _player(pid, name, provider="chromecast--abc", available=True, state="idle"):
    return {"player_id": pid, "provider": provider, "type": "player",
            "name": name, "available": available, "device_info": {"model": "Nest"},
            "playback_state": state, "volume_level": 30, "powered": True,
            "current_media": {"title": "Song", "artist": "Band", "uri": "x://1"}
            if state == "playing" else None}


class FakeMusicAssistant:
    """Just enough of Music Assistant's WebSocket API to be honest about."""

    def __init__(self, schema=30):
        self.schema = schema
        self.players = [
            _player("kitchen", "Kitchen", state="playing"),
            _player("media_player.den", "Den", provider="hass--1"),
            _player("aircast-held", "Old bridge", provider="aircast--2",
                    available=False),
        ]
        self.player_configs = [{"player_id": p["player_id"], "provider": p["provider"],
                                "name": p["name"]} for p in self.players]
        # Three remembered, never seen since — the AirCast leftovers.
        for i in range(3):
            self.player_configs.append({"player_id": f"aircast-{i}",
                                        "provider": "aircast--2",
                                        "name": f"AirCast {i}"})
        self.calls = []

    def app(self):
        app = web.Application()
        app.router.add_get("/ws", self.handle)
        return app

    async def handle(self, request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        await ws.send_json({"server_id": "abc", "server_version": "2.9.0",
                            "schema_version": self.schema,
                            "min_supported_schema_version": 24,
                            "homeassistant_addon": True, "name": "Music Assistant"})
        user = None
        async for msg in ws:
            data = json.loads(msg.data)
            mid, command, args = data["message_id"], data["command"], data.get("args") or {}
            self.calls.append((command, args))
            if command == "auth":
                token = args.get("token")
                role = {SERVICE_TOKEN: "service", ADMIN_TOKEN: "admin"}.get(token)
                if role is None:
                    await ws.send_json({"message_id": mid, "error_code": 23,
                                        "details": "Invalid or expired token"})
                    continue
                user = {"username": "homeassistant" if role == "service" else "me",
                        "display_name": "Home Assistant Integration"
                        if role == "service" else "Me", "role": role}
                await ws.send_json({"message_id": mid,
                                    "result": {"authenticated": True, "user": user}})
                continue
            if self.schema >= 28 and user is None:
                await ws.send_json({"message_id": mid, "error_code": 20,
                                    "details": "Authentication required."})
                continue
            # An event arriving between a command and its answer.
            await ws.send_json({"event": "player_updated", "object_id": "kitchen",
                                "data": {}})
            try:
                result = self.run(command, args, user)
            except ma.MAError as exc:
                await ws.send_json({"message_id": mid, "error_code": exc.code,
                                    "details": exc.details})
                continue
            if command == "players/all":
                # A long list arrives in partial chunks, then the rest.
                for item in result[:-1]:
                    await ws.send_json({"message_id": mid, "result": [item],
                                        "partial": True})
                result = result[-1:]
            await ws.send_json({"message_id": mid, "result": result})
        return ws

    def run(self, command, args, user):
        role = (user or {}).get("role")
        if command == "providers":
            return PROVIDERS
        if command == "config/providers":
            return PROVIDER_CONFIGS
        if command == "players/all":
            return self.players
        if command == "config/players":
            return self.player_configs
        if command == "config/providers/save":
            if role != "admin":
                raise ma.MAError(22, "Insufficient permissions: config.providers.write")
            return {"instance_id": args["instance_id"]}
        if command == "config/players/remove":
            pid = args["player_id"]
            if not any(c["player_id"] == pid for c in self.player_configs):
                raise ma.MAError(0, f"Player configuration for {pid} does not exist")
            if any(p["player_id"] == pid for p in self.players):
                raise ma.MAError(19, "Can not remove config for an active player!")
            self.player_configs = [c for c in self.player_configs
                                   if c["player_id"] != pid]
            return None
        if command == "config/players/save":
            return {"player_id": args["player_id"], "values": args["values"]}
        if command.startswith("players/cmd/") or command.startswith("player_queues/"):
            return None
        if command == "music/search":
            return {"tracks": [{"uri": "spotify://track/1", "name": args["search_query"]}]}
        raise ma.MAError(12, f"Invalid command: {command}")


class _Served(unittest.TestCase):
    token = SERVICE_TOKEN
    schema = 30

    def setUp(self):
        self.loop = asyncio.new_event_loop()
        self.addCleanup(self.loop.close)
        self.fake = FakeMusicAssistant(schema=self.schema)
        self.runner = web.AppRunner(self.fake.app())
        self.loop.run_until_complete(self.runner.setup())
        site = web.TCPSite(self.runner, "127.0.0.1", 0)
        self.loop.run_until_complete(site.start())
        port = self.runner.addresses[0][1]
        self.url = f"http://127.0.0.1:{port}"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        storage = Path(self._tmp.name)
        self.write_entry(storage, self.url, self.token)
        for p in (mock.patch.object(ma, "STORAGE_DIR", storage),
                  mock.patch.object(ma.ha_data, "SUPERVISOR_TOKEN", ""),
                  mock.patch.dict(os.environ, {"BRAIN_MUSIC_ASSISTANT_URL": "",
                                               "BRAIN_MUSIC_ASSISTANT_TOKEN": "",
                                               "BRAIN_PROTECTED_ENTITIES": ""})):
            p.start()
            self.addCleanup(p.stop)

    def tearDown(self):
        self.loop.run_until_complete(self.runner.cleanup())

    @staticmethod
    def write_entry(storage, url, token):
        (storage / "core.config_entries").write_text(json.dumps({"data": {"entries": [
            {"domain": "hue", "data": {"host": "1.2.3.4"}},
            {"domain": "music_assistant", "title": "Music Assistant",
             "disabled_by": None, "data": {"url": url, "token": token}},
        ]}}))

    def go(self, coro):
        return self.loop.run_until_complete(coro)


class TestSigningIn(_Served):

    def test_it_connects_where_home_assistant_connects_with_its_token(self):
        result = self.go(ma.overview())
        server = result["server"]
        self.assertTrue(server["reachable"], server)
        self.assertEqual(server["via"], "entry")
        self.assertEqual(server["role"], "service")
        self.assertFalse(server["admin"])
        self.assertEqual(self.fake.calls[0], ("auth", {"token": SERVICE_TOKEN}))

    def test_an_admin_token_is_tried_first(self):
        with mock.patch.dict(os.environ, {"BRAIN_MUSIC_ASSISTANT_TOKEN": ADMIN_TOKEN}):
            server = self.go(ma.overview())["server"]
        self.assertTrue(server["admin"])
        self.assertEqual(server["via"], "entry+token")

    def test_a_dead_admin_token_falls_back_to_home_assistants(self):
        with mock.patch.dict(os.environ, {"BRAIN_MUSIC_ASSISTANT_TOKEN": "revoked"}):
            server = self.go(ma.overview())["server"]
        self.assertTrue(server["reachable"])
        self.assertEqual(server["via"], "entry")

    def test_a_refused_token_is_a_sentence_naming_the_address(self):
        self.write_entry(ma.STORAGE_DIR, self.url, "wrong")
        server = self.go(ma.overview())["server"]
        self.assertFalse(server["reachable"])
        self.assertIn("Invalid or expired token", server["reason"])
        self.assertIn(self.url, server["reason"])

    def test_no_integration_and_no_supervisor_says_so(self):
        (ma.STORAGE_DIR / "core.config_entries").write_text(
            json.dumps({"data": {"entries": []}}))
        server = self.go(ma.overview())["server"]
        self.assertFalse(server["reachable"])
        self.assertIn("no Music Assistant integration", server["reason"])


class TestAnOldServerNeedsNoToken(_Served):
    schema = 26
    token = ""

    def test_before_schema_28_nothing_is_sent_before_the_command(self):
        result = self.go(ma.run_command("players/all", {}))
        self.assertTrue(result["ok"], result)
        self.assertNotIn("auth", [c for c, _ in self.fake.calls])


class TestWhatIsThere(_Served):

    def test_partial_chunks_are_joined_and_events_are_skipped(self):
        result = self.go(ma.run_command("players/all", {}))
        self.assertEqual([p["player_id"] for p in result["result"]],
                         ["kitchen", "media_player.den", "aircast-held"])

    def test_a_provider_that_failed_to_load_is_listed_with_its_error(self):
        providers = self.go(ma.overview())["providers"]
        sonos = next(p for p in providers if p["instance_id"] == "sonos--9")
        self.assertFalse(sonos["available"])
        self.assertEqual(sonos["last_error"], "no Sonos found")

    def test_stale_players_are_the_remembered_and_the_unavailable(self):
        stale = self.go(ma.overview())["stale_players"]
        kinds = {s["player_id"]: s["kind"] for s in stale}
        self.assertEqual(kinds, {"aircast-0": "remembered", "aircast-1": "remembered",
                                 "aircast-2": "remembered",
                                 "aircast-held": "unavailable"})
        self.assertNotIn("kitchen", kinds)

    def test_what_is_playing_rides_on_the_player(self):
        players = self.go(ma.overview())["players"]
        kitchen = next(p for p in players if p["player_id"] == "kitchen")
        self.assertEqual(kitchen["state"], "playing")
        self.assertEqual(kitchen["now_playing"]["title"], "Song")


class TestCommands(_Served):

    def test_a_scope_refusal_says_which_token_would_do_it(self):
        result = self.go(ma.run_command("config/providers/save",
                                        {"instance_id": "spotify--1", "values": {}}))
        self.assertFalse(result["ok"])
        self.assertEqual(result["code"], 22)
        self.assertIn("music_assistant_token", result["error"])

    def test_an_admin_can_do_what_the_integration_cannot(self):
        with mock.patch.dict(os.environ, {"BRAIN_MUSIC_ASSISTANT_TOKEN": ADMIN_TOKEN}):
            result = self.go(ma.run_command("config/providers/save",
                                            {"instance_id": "spotify--1", "values": {}}))
        self.assertTrue(result["ok"], result)

    def test_the_read_only_door_refuses_a_change_before_connecting(self):
        result = self.go(ma.run_command("players/cmd/play", {"player_id": "kitchen"},
                                        read_only=True))
        self.assertTrue(result["refused"])
        self.assertEqual(self.fake.calls, [])

    def test_a_command_name_is_checked_for_shape(self):
        for bad in ("players/../x", "Players/all", "players/all?x=1", ""):
            self.assertFalse(self.go(ma.run_command(bad, {}))["ok"], bad)
        self.assertEqual(self.fake.calls, [])

    def test_auth_cannot_be_sent_through_the_generic_door(self):
        self.assertTrue(self.go(ma.run_command("auth", {"token": "x"}))["refused"])

    def test_player_actions_become_the_servers_commands(self):
        self.assertTrue(self.go(ma.player_action("kitchen", "volume", "250"))["ok"])
        self.assertIn(("players/cmd/volume_set",
                       {"player_id": "kitchen", "volume_level": 100}), self.fake.calls)
        self.go(ma.player_action("kitchen", "shuffle", "on"))
        self.assertIn(("player_queues/shuffle",
                       {"queue_id": "kitchen", "shuffle_enabled": True}), self.fake.calls)
        self.go(ma.player_action("kitchen", "disable"))
        self.assertIn(("config/players/save",
                       {"player_id": "kitchen", "values": {"enabled": False}}),
                      self.fake.calls)

    def test_an_unknown_action_is_refused_by_name(self):
        result = self.go(ma.player_action("kitchen", "explode"))
        self.assertIn("explode", result["error"])
        self.assertEqual(self.fake.calls, [])


class TestRemovingPlayers(_Served):

    def test_a_dry_run_lists_and_changes_nothing(self):
        result = self.go(ma.remove_players())
        self.assertTrue(result["dry_run"])
        self.assertEqual(len(result["candidates"]), 4)
        self.assertNotIn("config/players/remove", [c for c, _ in self.fake.calls])

    def test_a_real_run_forgets_the_remembered_and_reports_the_held(self):
        result = self.go(ma.remove_players(dry_run=False))
        self.assertEqual(sorted(result["removed"]), ["aircast-0", "aircast-1", "aircast-2"])
        self.assertEqual(result["held_by_provider"][0]["player_id"], "aircast-held")
        self.assertFalse(result["held_by_provider"][0]["disabled"])
        self.assertIn("disable_if_held", result["note"])
        left = {c["player_id"] for c in self.fake.player_configs}
        self.assertNotIn("aircast-0", left)
        self.assertIn("kitchen", left)

    def test_a_held_player_can_be_disabled_instead(self):
        result = self.go(ma.remove_players(["aircast-held"], dry_run=False,
                                           disable_if_held=True))
        self.assertEqual(result["held_by_provider"], [{"player_id": "aircast-held",
                                                       "disabled": True}])

    def test_a_working_player_is_never_swept_up(self):
        result = self.go(ma.remove_players(["kitchen", "aircast-0"], dry_run=False))
        self.assertEqual(result["removed"], ["aircast-0"])
        self.assertEqual(result["not_eligible"][0]["player_id"], "kitchen")
        self.assertIn("working", result["not_eligible"][0]["reason"])

    def test_a_provider_filter_reads_the_domain(self):
        result = self.go(ma.remove_players(provider="aircast"))
        self.assertEqual(len(result["candidates"]), 4)
        result = self.go(ma.remove_players(provider="chromecast"))
        self.assertEqual(result["candidates"], [])

    def test_everything_needs_a_name(self):
        result = self.go(ma.remove_players(stale_only=False))
        self.assertFalse(result["ok"])


class TestProtectedPlayers(_Served):

    def setUp(self):
        super().setUp()
        self.registry = [
            [{"id": "dev1", "identifiers": [["music_assistant", "kitchen"]]}],
            [{"entity_id": "media_player.kitchen_speaker", "device_id": "dev1",
              "platform": "music_assistant"},
             # No device row: matched on the entity's own unique_id.
             {"entity_id": "media_player.aircast_0", "device_id": None,
              "platform": "music_assistant", "unique_id": "aircast-0"}],
        ]

        async def ws_commands(session, commands):
            if self.registry is None:
                raise OSError("Core is down")
            return self.registry

        p = mock.patch.object(ma.ha_data, "_ws_commands", ws_commands)
        p.start()
        self.addCleanup(p.stop)

    def test_a_player_that_is_a_protected_entity_is_refused(self):
        with mock.patch.dict(os.environ, {"BRAIN_PROTECTED_ENTITIES":
                                          "media_player.kitchen_speaker"}):
            result = self.go(ma.player_action("kitchen", "play"))
        self.assertTrue(result["refused"])
        self.assertIn("media_player.kitchen_speaker", result["error"])
        self.assertNotIn("players/cmd/play", [c for c, _ in self.fake.calls])

    def test_a_home_assistant_player_is_checked_as_its_own_entity(self):
        with mock.patch.dict(os.environ, {"BRAIN_PROTECTED_ENTITIES": "media_player.den"}):
            result = self.go(ma.run_command("players/cmd/group_many", {
                "target_player": "kitchen", "child_player_ids": ["media_player.den"]}))
        self.assertTrue(result["refused"])

    def test_an_unreadable_registry_refuses_while_the_list_is_set(self):
        self.registry = None
        with mock.patch.dict(os.environ, {"BRAIN_PROTECTED_ENTITIES": "lock.front"}):
            result = self.go(ma.player_action("kitchen", "play"))
        self.assertTrue(result["refused"])
        self.assertIn("could not read", result["error"])

    def test_reading_is_never_refused(self):
        with mock.patch.dict(os.environ, {"BRAIN_PROTECTED_ENTITIES":
                                          "media_player.kitchen_speaker"}):
            result = self.go(ma.run_command("player_queues/items",
                                            {"queue_id": "kitchen"}))
        self.assertNotIn("refused", result)

    def test_removal_asks_too(self):
        with mock.patch.dict(os.environ, {"BRAIN_PROTECTED_ENTITIES":
                                          "media_player.aircast_0"}):
            result = self.go(ma.remove_players(dry_run=False))
        self.assertTrue(result["refused"])
        self.assertIn("media_player.aircast_0", result["error"])
        self.assertNotIn("config/players/remove", [c for c, _ in self.fake.calls])

    def test_a_stale_player_home_assistant_never_had_carries_nothing(self):
        with mock.patch.dict(os.environ, {"BRAIN_PROTECTED_ENTITIES": "media_player.*"}):
            result = self.go(ma.remove_players(["aircast-1"], dry_run=False))
        self.assertEqual(result["removed"], ["aircast-1"])


class TestTheReadOnlyTable(unittest.TestCase):

    def test_reads(self):
        for c in ("players/all", "music/search", "music/tracks/library_items",
                  "music/artists/artist_albums", "config/providers/get_entries",
                  "music/tracks/get_by_external_id"):
            self.assertTrue(ma.is_read_only(c), c)

    def test_writes_that_look_like_reads(self):
        for c in ("music/playlists/add_playlist_tracks",
                  "music/playlists/remove_playlist_tracks",
                  "music/playlists/create_playlist", "music/albums/update",
                  "music/radios/import_radios", "players/cmd/play",
                  "config/players/remove", "auth/tokens", "diagnostics/get"):
            self.assertFalse(ma.is_read_only(c), c)


class TestWhereTheServerIs(unittest.TestCase):

    def test_an_enabled_entry_beats_a_disabled_one(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(ma, "STORAGE_DIR", Path(tmp)):
            (Path(tmp) / "core.config_entries").write_text(json.dumps({"data": {
                "entries": [
                    {"domain": "music_assistant", "disabled_by": "user",
                     "data": {"url": "http://old:8095", "token": "a"}},
                    {"domain": "music_assistant", "disabled_by": None,
                     "data": {"url": "http://d5369777-music-assistant:8094/",
                              "token": "b"}}]}}))
            entry = ma.ha_entry()
        self.assertEqual(entry["url"], "http://d5369777-music-assistant:8094")
        self.assertEqual(entry["token"], "b")

    def test_the_addon_is_picked_stable_and_running_first(self):
        rows = [{"slug": "d5369777_music_assistant_beta", "state": "started"},
                {"slug": "d5369777_music_assistant", "state": "stopped"},
                {"slug": "core_mosquitto", "state": "started"}]
        self.assertEqual(ma.pick_addon(rows)["slug"], "d5369777_music_assistant_beta")
        rows[1]["state"] = "started"
        self.assertEqual(ma.pick_addon(rows)["slug"], "d5369777_music_assistant")

    def test_ws_url(self):
        self.assertEqual(ma.ws_url("http://h:8094/"), "ws://h:8094/ws")
        self.assertEqual(ma.ws_url("https://h/ws"), "wss://h/ws")


class TestTheMcpTools(unittest.TestCase):
    """The tools go through the panel; voice is sent to the HA service."""

    @classmethod
    def setUpClass(cls):
        import ha_mcp_server
        cls.mcp = ha_mcp_server
        cls.seen = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _answer(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_POST(self):
                body = json.loads(self.rfile.read(
                    int(self.headers.get("Content-Length") or 0)) or b"{}")
                cls.seen.append((self.path, body))
                if "/player/" in self.path:
                    self._answer(409, {"ok": False, "refused": True,
                                       "error": "is media_player.kitchen"})
                else:
                    self._answer(200, {"ok": True, "path": self.path})

            def do_GET(self):
                self._answer(200, {"ok": True, "path": self.path})

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.url = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.seen.clear()
        for p in (mock.patch.object(self.mcp, "PANEL_URL", self.url),
                  mock.patch.object(self.mcp, "EXPOSED_ONLY", False)):
            p.start()
            self.addCleanup(p.stop)

    def test_the_query_tool_asks_the_panel_for_a_read(self):
        self.mcp.handle_tool_call("music_assistant_query", {"command": "players/all"})
        self.assertEqual(self.seen[0][1]["read_only"], True)

    def test_the_command_tool_does_not(self):
        self.mcp.handle_tool_call("music_assistant_command",
                                  {"command": "players/cmd/play",
                                   "args": {"player_id": "x"}})
        self.assertNotIn("read_only", self.seen[0][1])

    def test_a_refusal_carries_the_panels_sentence(self):
        result = self.mcp.handle_tool_call("music_assistant_player",
                                           {"player_id": "a b/c", "action": "play"})
        self.assertIn("media_player.kitchen", result["error"])
        self.assertEqual(self.seen[0][0], "/api/music-assistant/player/a%20b%2Fc/play")

    def test_removal_is_a_dry_run_unless_asked(self):
        self.mcp.handle_tool_call("music_assistant_remove_players", {})
        self.assertTrue(self.seen[0][1]["dry_run"])

    def test_voice_is_sent_to_the_home_assistant_service(self):
        with mock.patch.object(self.mcp, "EXPOSED_ONLY", True):
            for name, args in (("music_assistant_status", {}),
                               ("music_assistant_play",
                                {"player_id": "x", "media": "y"}),
                               ("music_assistant_command", {"command": "info"})):
                result = self.mcp.handle_tool_call(name, args)
                self.assertIn("music_assistant.play_media", result["error"], name)
        self.assertEqual(self.seen, [])


if __name__ == "__main__":
    unittest.main()
