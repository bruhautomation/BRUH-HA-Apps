#!/usr/bin/env python3
"""Tests for the protected-entity policy in the MCP server.

DENIED_SERVICES restricts a channel; PROTECTED_ENTITIES restricts an
entity for every channel. Both are enforced in ``call_service``, the one
chokepoint every acting tool routes through, so the tests here drive
``call_service`` and the control_* tools rather than the helper — a helper
that answers correctly while the chokepoint forgets to ask it is the
bypass these tests exist to catch.
"""

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server"))

import ha_mcp_server  # noqa: E402


class ProtectedCase(unittest.TestCase):
    def setUp(self):
        self._denied = ha_mcp_server.DENIED_SERVICES
        self._protected = ha_mcp_server.PROTECTED_ENTITIES
        ha_mcp_server.DENIED_SERVICES = []
        ha_mcp_server.PROTECTED_ENTITIES = ["lock.front_door", "alarm_control_panel.*"]
        ha_mcp_server._PROTECTED_SCOPES.update(at=0.0, areas=set(), devices=set())

    def tearDown(self):
        ha_mcp_server.DENIED_SERVICES = self._denied
        ha_mcp_server.PROTECTED_ENTITIES = self._protected
        ha_mcp_server._PROTECTED_SCOPES.update(at=0.0, areas=set(), devices=set())


class TestEntityTargets(ProtectedCase):
    @patch("ha_mcp_server.ha_api_request")
    def test_every_way_of_naming_the_entity_is_refused(self, mock_api):
        for payload in (
            {"entity_id": "lock.front_door"},
            {"entity_id": ["light.x", "lock.front_door"]},
            {"entity_id": "light.x, lock.front_door"},
            {"target": {"entity_id": "LOCK.FRONT_DOOR"}},
            {"entity_id": "all"},
        ):
            result = ha_mcp_server.call_service("lock", "unlock", payload)
            self.assertIn("error", result, payload)
            self.assertIn("protected", result["error"], payload)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_a_domain_pattern_covers_the_whole_domain(self, mock_api):
        result = ha_mcp_server.call_service(
            "alarm_control_panel", "alarm_disarm",
            {"entity_id": "alarm_control_panel.house", "code": "1234"})
        self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_an_unprotected_entity_still_works(self, mock_api):
        mock_api.return_value = {"ok": True}
        ha_mcp_server.call_service("lock", "unlock", {"entity_id": "lock.shed"})
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_the_control_tools_route_through_the_policy(self, mock_api):
        result = ha_mcp_server.control_lock("lock.front_door", "unlock")
        self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_the_meta_service_cannot_bypass_it(self, mock_api):
        result = ha_mcp_server.call_service(
            "homeassistant", "turn_on", {"entity_id": "lock.front_door"})
        self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_a_registry_service_naming_the_entity_is_refused_too(self, mock_api):
        # "protected" means hands off, not "hands off unless it is a rename"
        result = ha_mcp_server.call_service(
            "brain", "rename_entity", {"entity_id": "lock.front_door", "name": "x"})
        self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_nothing_changes_with_an_empty_list(self, mock_api):
        ha_mcp_server.PROTECTED_ENTITIES = []
        mock_api.return_value = {"ok": True}
        ha_mcp_server.call_service("lock", "unlock", {"entity_id": "lock.front_door"})
        ha_mcp_server.call_service("light", "turn_on", {"area_id": "garage"})
        self.assertEqual(mock_api.call_count, 2)


class TestTargetsThisProcessCannotResolve(ProtectedCase):
    """Two more ways to reach a protected entity without naming it.

    Both used to pass: an event is not a service call and never reached
    `_protected_target`, and a meta-call with no target at all came back
    None from it, while `_meta_call_denied` — one function up, about the
    deny-list — has always read that same payload as "every entity".
    """

    @patch("ha_mcp_server.ha_api_request")
    def test_an_event_is_refused_while_anything_is_protected(self, mock_api):
        """An event reaches the house through whichever automations listen
        for it, and one of those may act on the lock — nothing here can
        tell which, so it is the label/floor rule: unresolvable, refused."""
        for event, data in (("custom_event", {"x": 1}),
                            ("unlock_the_door", None),
                            ("nothing_to_do_with_locks", {"room": "kitchen"})):
            with self.subTest(event=event):
                result = ha_mcp_server.fire_event(event, data)
                self.assertIn("error", result)
                self.assertIn("protected", result["error"])
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_the_event_goes_through_with_nothing_protected(self, mock_api):
        ha_mcp_server.PROTECTED_ENTITIES = []
        mock_api.return_value = {"ok": True}
        result = ha_mcp_server.fire_event("custom_event", {"x": 1})
        self.assertNotIn("error", result)
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_the_event_is_refused_through_the_dispatcher_too(self, mock_api):
        """The tool table is what a Claude run reaches, not the function."""
        fn = getattr(ha_mcp_server, ha_mcp_server.TOOL_IMPLEMENTATIONS["fire_event"])
        result = fn("custom_event", {"x": 1})
        self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_a_meta_call_with_no_target_is_every_entity(self, mock_api):
        """`homeassistant.turn_off` with nothing named is the whole house,
        and the whole house includes the front door."""
        for payload in (None, {}, {"transition": 2}, {"target": {}}):
            with self.subTest(payload=payload):
                result = ha_mcp_server.call_service("homeassistant", "turn_off", payload)
                self.assertIn("error", result, payload)
                self.assertIn("protected", result["error"], payload)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_the_two_meta_checks_now_agree(self, mock_api):
        """`_meta_call_denied` (deny-list) and `_protected_target` (protected
        list) are asked about the same payload at the same chokepoint; a
        payload one refuses as "all entities" the other may not wave on."""
        ha_mcp_server.DENIED_SERVICES = ["lock.unlock"]
        try:
            self.assertIsNotNone(ha_mcp_server._meta_call_denied({}))
            self.assertIsNotNone(
                ha_mcp_server._protected_target({}, empty_is_all=True))
        finally:
            ha_mcp_server.DENIED_SERVICES = []

    @patch("ha_mcp_server.ha_api_request")
    def test_a_service_that_takes_no_entity_still_works(self, mock_api):
        """The empty-target rule is the meta-services' and nobody else's:
        notify, reload and the brain.* registry services legitimately name
        no entity, and refusing them would take brAIn's own tooling away
        the moment anything is protected."""
        mock_api.return_value = {"ok": True}
        for domain, service, data in (
            ("notify", "mobile_app_phone", {"message": "hi"}),
            ("automation", "reload", None),
            ("brain", "create_area", {"name": "Loft"}),
        ):
            with self.subTest(service=f"{domain}.{service}"):
                result = ha_mcp_server.call_service(domain, service, data)
                self.assertNotIn("error", result)
        self.assertEqual(mock_api.call_count, 3)


class TestAreaAndDeviceTargets(ProtectedCase):
    REGISTRY = [
        {"entity_id": "lock.front_door", "device_id": "dev-lock", "area_id": None},
        {"entity_id": "light.hall", "device_id": "dev-hall", "area_id": "hall"},
    ]
    DEVICES = [
        {"id": "dev-lock", "area_id": "porch"},
        {"id": "dev-hall", "area_id": "hall"},
    ]

    def _ws(self, payload, timeout=15):
        return {"config/entity_registry/list": self.REGISTRY,
                "config/device_registry/list": self.DEVICES}[payload["type"]]

    @patch("ha_mcp_server.ha_api_request")
    def test_an_area_holding_a_protected_entity_is_refused(self, mock_api):
        with patch("ha_mcp_server._ws_command", side_effect=self._ws):
            result = ha_mcp_server.call_service(
                "light", "turn_on", {"target": {"area_id": "porch"}})
            self.assertIn("error", result)
            self.assertIn("porch", result["error"])
            result = ha_mcp_server.call_service(
                "light", "turn_on", {"device_id": ["dev-lock"]})
            self.assertIn("error", result)
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_an_area_without_one_is_allowed(self, mock_api):
        mock_api.return_value = {"ok": True}
        with patch("ha_mcp_server._ws_command", side_effect=self._ws):
            ha_mcp_server.call_service("light", "turn_on", {"area_id": "hall"})
        mock_api.assert_called_once()

    @patch("ha_mcp_server.ha_api_request")
    def test_an_unreadable_registry_fails_closed(self, mock_api):
        with patch("ha_mcp_server._ws_command", side_effect=RuntimeError("down")):
            result = ha_mcp_server.call_service("light", "turn_on", {"area_id": "hall"})
        self.assertIn("error", result)
        self.assertIn("registry", result["error"])
        mock_api.assert_not_called()

    @patch("ha_mcp_server.ha_api_request")
    def test_labels_and_floors_cannot_be_checked_so_are_refused(self, mock_api):
        for payload in ({"label_id": "outside"}, {"target": {"floor_id": "ground"}}):
            result = ha_mcp_server.call_service("light", "turn_on", payload)
            self.assertIn("error", result, payload)
        mock_api.assert_not_called()

    def test_the_scope_lookup_is_cached(self):
        calls = []

        def ws(payload, timeout=15):
            calls.append(payload["type"])
            return self._ws(payload)
        with patch("ha_mcp_server._ws_command", side_effect=ws):
            ha_mcp_server._protected_scopes()
            ha_mcp_server._protected_scopes()
        self.assertEqual(len(calls), 2)


class TestMatching(unittest.TestCase):
    def test_patterns(self):
        old = ha_mcp_server.PROTECTED_ENTITIES
        try:
            ha_mcp_server.PROTECTED_ENTITIES = ["lock.front_door", "cover.*"]
            self.assertTrue(ha_mcp_server._entity_protected("lock.front_door"))
            self.assertTrue(ha_mcp_server._entity_protected("Lock.Front_Door"))
            self.assertTrue(ha_mcp_server._entity_protected("cover.garage"))
            self.assertFalse(ha_mcp_server._entity_protected("lock.shed"))
            self.assertFalse(ha_mcp_server._entity_protected(""))
            ha_mcp_server.PROTECTED_ENTITIES = ["*"]
            self.assertTrue(ha_mcp_server._entity_protected("light.anything"))
        finally:
            ha_mcp_server.PROTECTED_ENTITIES = old

    def test_the_option_reaches_the_server_by_env(self):
        """run.sh exports the option; the server reads the same name."""
        src = Path(__file__).resolve().parent.parent.joinpath("brain", "run.sh").read_text()
        self.assertIn('BRAIN_PROTECTED_ENTITIES="$protected_entities"', src)
        self.assertIn('export BRAIN_PROTECTED_ENTITIES="${protected_entities}"', src)
        server_src = Path(ha_mcp_server.__file__).read_text()
        self.assertIn('os.environ.get("BRAIN_PROTECTED_ENTITIES"', server_src)


if __name__ == "__main__":
    unittest.main()
