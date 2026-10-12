"""Morph's usage log end to end, and the names the generator gives cards.

The usage half drives the integration's real ``morph/usage`` handler (Home
Assistant stubbed only where the module merely imports it) into the shared
file, and the add-on's real digest out of the same file — the two halves are
different processes, and a row shape written down once in each is a shape
that drifts. The panel half (that a tap is logged, and that a log the page
could not send is kept and sent later) is driven in a browser by
tests/manual/measure-morph.mjs.
"""
import asyncio
import importlib
import json
import re
import sys
import types
import unittest
import unittest.mock
from pathlib import Path

from morph_env import MorphEnv

INTEGRATION = Path(__file__).resolve().parent.parent / "morph" / "custom_components" / "morph"
PANEL_JS = INTEGRATION / "frontend" / "morph-panel.js"
UTIL_JS = INTEGRATION / "frontend" / "util.js"


def _load_websocket():
    """Import custom_components.morph.websocket with Home Assistant stubbed,
    and put sys.modules back afterwards."""
    names = ("voluptuous", "homeassistant", "homeassistant.components",
             "homeassistant.components.websocket_api", "homeassistant.core",
             "homeassistant.helpers", "homeassistant.helpers.event",
             "custom_components", "custom_components.morph",
             "custom_components.morph.const", "custom_components.morph.bridge",
             "custom_components.morph.websocket")
    saved = {n: sys.modules.get(n) for n in names}

    def passthrough(*_a, **_k):
        return lambda f: f

    vol = types.ModuleType("voluptuous")
    vol.Required = vol.Optional = lambda key, **_k: key
    vol.In = lambda opts: opts
    ws_api = types.ModuleType("homeassistant.components.websocket_api")
    ws_api.websocket_command = passthrough
    ws_api.async_response = lambda f: f
    ws_api.require_admin = lambda f: f
    ws_api.event_message = lambda mid, data: {"id": mid, "event": data}
    ws_api.async_register_command = lambda hass, handler: None
    components = types.ModuleType("homeassistant.components")
    components.websocket_api = ws_api
    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.callback = lambda f: f
    event = types.ModuleType("homeassistant.helpers.event")
    event.async_track_time_interval = lambda *a, **k: (lambda: None)
    helpers = types.ModuleType("homeassistant.helpers")
    pkg = types.ModuleType("custom_components")
    pkg.__path__ = [str(INTEGRATION.parent)]
    morph_pkg = types.ModuleType("custom_components.morph")
    morph_pkg.__path__ = [str(INTEGRATION)]
    sys.modules.update({
        "voluptuous": vol, "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.components": components,
        "homeassistant.components.websocket_api": ws_api, "homeassistant.core": core,
        "homeassistant.helpers": helpers, "homeassistant.helpers.event": event,
        "custom_components": pkg, "custom_components.morph": morph_pkg,
    })
    for n in ("custom_components.morph.const", "custom_components.morph.bridge",
              "custom_components.morph.websocket"):
        sys.modules.pop(n, None)
    try:
        return importlib.import_module("custom_components.morph.websocket")
    finally:
        for n, mod in saved.items():
            if mod is None:
                sys.modules.pop(n, None)
            else:
                sys.modules[n] = mod


class _Hass:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


class _Connection:
    def __init__(self):
        self.results = []

    def send_result(self, mid, data=None):
        self.results.append((mid, data))

    def send_error(self, mid, code, message):
        self.results.append((mid, {"error": code, "message": message}))


DASH = {
    "title": "Home",
    "floors": [{"title": "Ground", "sections": [{
        "title": "Kitchen", "id": "s_kitchen",
        "groups": [{"cards": [
            {"id": "c_cans", "type": "light_group", "entity": "light.kitchen_cans"},
            {"id": "c_kettle", "type": "switch", "entity": "switch.kettle"},
        ]}],
    }]}],
}


class TestAUseReachesTheDigest(unittest.TestCase):
    """What the panel sends to morph/usage is what the learning pass reads."""

    def setUp(self):
        self.ws = _load_websocket()

    def send(self, usage_path, events):
        conn = _Connection()
        with unittest.mock.patch.object(self.ws, "USAGE", usage_path):
            asyncio.run(self.ws.ws_usage(_Hass(), conn, {"id": 7, "type": "morph/usage",
                                                         "events": events}))
        return conn.results[-1][1]

    def test_the_integration_and_the_add_on_name_the_same_file(self):
        with MorphEnv() as env:
            rel_integration = self.ws.USAGE.relative_to("/config")
            rel_service = Path(env.paths.USAGE).relative_to(env.shared.parent)
            self.assertEqual(rel_integration, rel_service)

    def test_taps_written_by_the_integration_are_counted_by_the_digest(self):
        with MorphEnv() as env:
            answer = self.send(env.paths.USAGE, [
                {"kind": "toggle", "card": "c_cans", "section": "s_kitchen"},
                {"kind": "open", "card": "c_kettle", "section": "s_kitchen"},
                {"kind": "slide", "card": "c_cans", "section": "s_kitchen"},
                {"kind": "not-a-kind", "card": "c_cans"},
            ])
            self.assertEqual({"ok": True, "kept": 3}, answer)
            d = env.learning.digest(DASH)
            self.assertEqual(3, d["events"])
            self.assertEqual(1, d["days_with_use"])
            uses = {c["id"]: c["uses"] for c in d["cards"]}
            self.assertEqual({"c_cans": 2, "c_kettle": 1}, uses)
            self.assertEqual(3, d["sections"][0]["uses"])

    def test_a_press_logged_without_its_card_counts_toward_the_card_showing_the_entity(self):
        """A button or a light group's member logged before the panel tied it
        to its tile still names the entity it acted on."""
        with MorphEnv() as env:
            self.send(env.paths.USAGE, [{"kind": "toggle", "detail": "switch.kettle"},
                                        {"kind": "scene", "detail": "scene.dinner"}])
            uses = {c["id"]: c["uses"] for c in env.learning.digest(DASH)["cards"]}
            self.assertEqual({"c_cans": 0, "c_kettle": 1}, uses)

    def test_a_card_with_its_id_is_not_counted_twice(self):
        with MorphEnv() as env:
            self.send(env.paths.USAGE, [{"kind": "toggle", "card": "c_kettle",
                                         "section": "s_kitchen", "detail": "switch.kettle"}])
            uses = {c["id"]: c["uses"] for c in env.learning.digest(DASH)["cards"]}
            self.assertEqual(1, uses["c_kettle"])

    def test_rows_on_disk_are_the_shape_the_digest_reads(self):
        with MorphEnv() as env:
            self.send(env.paths.USAGE, [{"kind": "toggle", "card": "c_cans", "section": "s_kitchen"}])
            row = json.loads(Path(env.paths.USAGE).read_text().splitlines()[0])
            self.assertEqual({"ts", "kind", "hour", "weekday", "card", "section"}, set(row))


class TestThePanelKeepsLoggingAcrossAReconnect(unittest.TestCase):
    """Home Assistant takes a hidden panel out of the page and puts the SAME
    element back; boot() does not run again. These read the source because
    the lifecycle is a browser's — measure-morph.mjs drives it for real."""

    def setUp(self):
        self.src = PANEL_JS.read_text()

    def body(self, name):
        start = self.src.index(f"\n  {name}(")
        end = self.src.index("\n  }\n", start)
        return self.src[start:end]

    def test_reconnecting_starts_the_flush_again(self):
        self.assertIn("this.startLive()", self.body("connectedCallback"))
        self.assertIn("setInterval", self.body("startLive"))
        self.assertIn("flushUsage", self.body("startLive"))

    def test_a_failed_send_puts_the_events_back(self):
        body = self.body("flushUsage")
        self.assertRegex(body, r"catch\(\(\) => \{ this\.usage = events\.concat\(this\.usage\)")

    def test_hiding_the_page_flushes(self):
        self.assertIn("visibilitychange", self.body("startLive"))


class TestRoomPrefixes(unittest.TestCase):

    def test_the_separator_goes_with_the_room(self):
        with MorphEnv() as env:
            short = env.generator._short
            self.assertEqual("Bread Stretch", short("Kitchen - Bread Stretch", "Kitchen"))
            self.assertEqual("Kettle", short("Kitchen – Kettle", "kitchen"))
            self.assertEqual("Kettle", short("Kitchen — Kettle", "Kitchen"))
            self.assertEqual("Tap", short("Kitchen: Tap", "Kitchen"))
            self.assertEqual("Lamp", short("Kitchen | Lamp", "Kitchen"))
            self.assertEqual("Cans", short("Kitchen Cans", "Kitchen"))

    def test_only_a_whole_room_name_is_dropped(self):
        with MorphEnv() as env:
            short = env.generator._short
            self.assertEqual("Kitchenette Lamp", short("Kitchenette Lamp", "Kitchen"))
            self.assertEqual("Kitchen", short("Kitchen", "Kitchen"))
            self.assertEqual("Kitchen -", short("Kitchen -", "Kitchen"),
                             "nothing after the room is no name at all")

    def test_the_panel_strips_the_same_separators(self):
        src = UTIL_JS.read_text()
        js = re.search(r"const SEPARATORS = '([^']*)'", src).group(1)
        with MorphEnv() as env:
            py = env.generator.SEPARATORS
        decoded = js.encode().decode("unicode_escape")
        self.assertEqual(set(py), set(decoded))


class TestNamesInASectionDoNotCollide(unittest.TestCase):

    def house(self, players):
        def st(eid, name):
            return {"entity_id": eid, "state": "idle", "attributes": {"friendly_name": name}}
        return {
            "floors": [], "devices": [],
            "areas": [{"area_id": "kitchen", "name": "Kitchen"}],
            "states": [st(e, n) for e, n in players.items()],
            "entities": [{"entity_id": e, "area_id": "kitchen"} for e in players],
        }

    def names(self, env, players):
        dash, _ = env.store.normalize(env.generator.build(self.house(players)))
        sec = next(s for f in dash["floors"] for s in f["sections"] if s["title"] == "Kitchen")
        return {c["entity"]: c.get("name") for g in sec["groups"] for c in g["cards"]}

    def test_two_players_that_would_both_be_mini_keep_their_full_names(self):
        with MorphEnv() as env:
            names = self.names(env, {"media_player.kitchen_mini": "Kitchen Mini",
                                     "media_player.kitchen_nest_mini": "Kitchen - Mini"})
            self.assertEqual({"media_player.kitchen_mini": "Kitchen Mini",
                              "media_player.kitchen_nest_mini": "Kitchen - Mini"}, names,
                             "a collided card is NAMED in full, or the panel re-shortens it")

    def test_identical_full_names_keep_what_the_ids_say_apart(self):
        with MorphEnv() as env:
            names = self.names(env, {"media_player.kitchen_mini": "Kitchen Mini",
                                     "media_player.kitchen_mini_2": "Kitchen Mini"})
            shown = list(names.values())
            self.assertEqual(len(shown), len({n.lower() for n in shown}), shown)
            self.assertEqual("Kitchen Mini (2)", names["media_player.kitchen_mini_2"])

    def test_names_that_do_not_collide_are_still_shortened(self):
        with MorphEnv() as env:
            names = self.names(env, {"media_player.kitchen_mini": "Kitchen Mini",
                                     "media_player.kitchen_soundbar": "Kitchen Soundbar"})
            self.assertEqual({"media_player.kitchen_mini": "Mini",
                              "media_player.kitchen_soundbar": "Soundbar"}, names)


if __name__ == "__main__":
    unittest.main()
