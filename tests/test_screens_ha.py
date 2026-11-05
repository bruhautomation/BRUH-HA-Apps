"""brAIn photographs Home Assistant's own dashboards (devloop/screen_targets.ha_targets,
screens._HA_SOCKET_GUARD_JS).

The real sign-in and the guard are driven in a real Home Assistant by
tests/realha (CI's morph-real-ha). These hold the parts a stand-in can:
every tab of every dashboard is a screen with a name a picture may carry,
the sign-in script writes the token for Home Assistant's origin and no
other, nothing is offered without a token, and the guard's rule drops
every message that changes something while letting the frontend's reads
through.
"""
from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL))

from devloop import screen_targets, screens  # noqa: E402

EYES = {"port": 8123, "ssl": False, "access_token": "tok-abc", "expires_in": 1800, "dashboards": [
    {"key": "default", "url_path": "lovelace", "title": "Overview", "views": [{"index": 0, "path": "0", "title": "Overview"}]},
    {"key": "morph-home", "url_path": "morph-home", "title": "Home", "views": [
        {"index": 0, "path": "downstairs", "title": "Downstairs"},
        {"index": 1, "path": "a-very-long-view-path-that-goes-on-and-on-and-on", "title": "Long"}]},
    {"key": "bad", "url_path": "../etc", "title": "Bad", "views": [{"index": 0, "path": "0"}]},
]}


class Targets(unittest.TestCase):
    def test_every_tab_is_a_screen_and_a_bad_path_is_not(self):
        (t,) = screen_targets.ha_targets(EYES)
        self.assertEqual(t["product"], "Home Assistant")
        self.assertTrue(t["guard"] and t["sockets"])
        urls = [s["url"] for s in t["screens"]]
        self.assertEqual(urls[:2], ["http://homeassistant:8123/lovelace/0", "http://homeassistant:8123/morph-home/downstairs"])
        self.assertFalse([u for u in urls if ".." in u])
        self.assertEqual(t["screens"][1]["label"], "Home Assistant › Home › Downstairs")
        for s in t["screens"]:
            self.assertRegex(f"{s['slug']}-1200-light.png", screens.SHOT_RE)
        self.assertEqual(len({s["slug"] for s in t["screens"]}), len(t["screens"]))

    def test_nothing_is_offered_without_a_token(self):
        self.assertEqual(screen_targets.ha_targets({**EYES, "access_token": ""}), [])
        self.assertEqual(screen_targets.ha_targets(None), [])

    def test_https_and_another_port_are_followed(self):
        self.assertEqual(screen_targets.ha_base({"port": 8443, "ssl": True}), "https://homeassistant:8443")
        self.assertEqual(screen_targets.ha_base({"port": "nope"}), "http://homeassistant:8123")

    def test_the_sign_in_writes_the_token_for_home_assistants_origin_only(self):
        js = screen_targets.ha_init("http://homeassistant:8123", "tok-abc", 1800)
        self.assertIn('location.origin !== "http://homeassistant:8123"', js)
        data = json.loads(re.search(r"const d = (\{.*?\});", js).group(1))
        self.assertEqual((data["hassUrl"], data["access_token"]), ("http://homeassistant:8123", "tok-abc"))
        self.assertIn("localStorage.setItem('hassTokens'", js)


class Guard(unittest.TestCase):
    def rule(self):
        js = screens._HA_SOCKET_GUARD_JS
        pat = js.split("const WRITE = /", 1)[1].split("/;", 1)[0]
        return re.compile(pat.replace("\\/", "/"))

    def test_every_write_is_dropped(self):
        rule = self.rule()
        for kind in ("call_service", "execute_script", "fire_event", "conversation/process",
                     "lovelace/config/save", "lovelace/config/delete", "lovelace/dashboards/create",
                     "config/entity_registry/update", "config/device_registry/remove_config_entry",
                     "frontend/set_user_data", "todo/item/update", "homeassistant/reload"):
            self.assertTrue(rule.search(kind), kind)

    def test_what_the_frontend_reads_goes_through(self):
        rule = self.rule()
        for kind in ("auth/current_user", "subscribe_entities", "subscribe_events", "get_config", "get_services",
                     "get_panels", "lovelace/config", "lovelace/resources", "frontend/get_themes",
                     "frontend/get_translations", "frontend/subscribe_user_data", "render_template",
                     "history/stream", "recorder/statistics_during_period", "config/area_registry/list",
                     "config/entity_registry/list_for_display", "manifest/list", "todo/item/subscribe",
                     "repairs/list_issues", "supported_features", "morph/load"):
            self.assertFalse(rule.search(kind), kind)

    def test_a_guarded_page_with_sockets_is_not_refused_its_socket(self):
        src = (PANEL / "devloop" / "screens.py").read_text()
        block = src.split("if sockets:", 1)[1].split("await cdp.call(\"Fetch.enable\"", 1)[0]
        self.assertIn("_HA_SOCKET_GUARD_JS", block.split("else:", 1)[0])
        self.assertIn("_NO_SOCKETS_JS", block.split("else:", 1)[1])


class Handler(unittest.TestCase):
    def test_a_home_assistant_dashboard_is_never_pressed(self):
        src = (PANEL / "server.py").read_text()
        handler = src.split("async def h_devloop_screenshot", 1)[1].split("\nasync def ", 1)[0]
        self.assertIn('if focus and target.get("sockets"):', handler)
        # The token is asked for only when a dashboard is being photographed.
        self.assertIn("_ha_eyes(token=photographing_ha)", handler)


if __name__ == "__main__":
    unittest.main()
