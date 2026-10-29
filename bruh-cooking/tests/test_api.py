"""Tests for the Breville cloud client against a local mock server.

Run with: python3 -m unittest discover -s tests
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import importlib.util
import json
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

API_PATH = Path(__file__).resolve().parent.parent / "custom_components" / "bruh_cooking" / "api.py"
spec = importlib.util.spec_from_file_location("breville_api", API_PATH)
api = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = api
spec.loader.exec_module(api)

SUB = "Salesforce|0051234"
SERIAL = "J123456"


def make_jwt(sub: str = SUB, exp_in: float = 3600) -> str:
    def part(obj):
        raw = base64.urlsafe_b64encode(json.dumps(obj).encode()).decode()
        return raw.rstrip("=")

    return f"{part({'alg': 'none'})}.{part({'sub': sub, 'exp': time.time() + exp_in})}.sig"


class MockCloud:
    """Just enough of the Breville cloud to exercise the client."""

    def __init__(self) -> None:
        self.requests: list[tuple[str, str, dict, object]] = []
        self.ws_messages: list[dict] = []
        self.ws_headers: dict[str, str] = {}
        self.valid_token = make_jwt()
        self.reject_next = False
        self.login_error: dict | None = None
        app = web.Application()
        app.router.add_post("/oauth/token", self.token)
        app.router.add_get("/user/v2/user/{sub}/appliances", self.appliances)
        app.router.add_post("/appliance/v1/appliances/{serial}/{action}", self.control)
        app.router.add_get("/ws", self.websocket)
        self.server = TestServer(app)

    def endpoints(self):
        base = str(self.server.make_url("")).rstrip("/")
        return api.Endpoints(
            token_url=f"{base}/oauth/token",
            user_api=f"{base}/user",
            control_api=f"{base}/appliance/v1",
            websocket=f"{base.replace('http', 'ws', 1)}/ws",
        )

    def authorized(self, request: web.Request) -> bool:
        return (
            request.headers.get("sf-id-token") == self.valid_token
            and request.headers.get("Authorization") == f"Bearer {self.valid_token}"
        )

    async def token(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.requests.append(("POST", request.path, dict(request.headers), body))
        if body["grant_type"].endswith("password-realm"):
            if self.login_error:
                return web.json_response(self.login_error, status=403)
            return web.json_response(
                {"id_token": self.valid_token, "refresh_token": "r1", "access_token": "a1"}
            )
        assert body["grant_type"] == "refresh_token"
        self.valid_token = make_jwt()
        return web.json_response({"id_token": self.valid_token, "access_token": "a2"})

    async def appliances(self, request: web.Request) -> web.Response:
        self.requests.append(("GET", request.path, dict(request.headers), None))
        if self.reject_next or not self.authorized(request):
            self.reject_next = False
            return web.json_response({"message": "Unauthorized"}, status=401)
        assert request.match_info["sub"] == SUB
        return web.json_response(
            {"appliances": [{"serialNumber": SERIAL, "model": "CSJ100"}], "ownedModels": ["CSJ100"]}
        )

    async def control(self, request: web.Request) -> web.Response:
        body = await request.json()
        self.requests.append(("POST", request.path, dict(request.headers), body))
        if not self.authorized(request):
            return web.json_response({"message": "Unauthorized"}, status=401)
        return web.json_response({"status": "ok"})

    async def websocket(self, request: web.Request) -> web.WebSocketResponse:
        self.ws_headers = dict(request.headers)
        if not self.authorized(request):
            raise web.HTTPUnauthorized()
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            data = json.loads(msg.data)
            self.ws_messages.append(data)
            if data["action"] == "addAppliance":
                await ws.send_json(
                    {
                        "serialNumber": data["serialNumber"],
                        "messageType": "stateReport",
                        "data": {"reported": dict(IDLE_STATE)},
                        "version": 722,
                    }
                )
        return ws


# Shapes below are trimmed from a real capture.
IDLE_STATE = {
    "state": "IDLE", "model": "CSJ100", "programStep": 0, "bathTemp": 54.5,
    "hardwareOptions": 1, "firmwareVersion": "123", "espFirmwareVersion": "52",
    "timeRemaining": 0, "errorState": 0,
}
COOKING_POINT = {
    "serialNumber": SERIAL,
    "messageType": "applianceDataPoint",
    "version": "1792804189503",
    "data": {
        "state": "ACTIVE", "model": "CSJ100", "programStep": 3, "bathTemp": 59.28,
        "setPoint": 58.900001525878906, "timeRemaining": 59, "cookTime": 60,
        "guideId": "manual_2gJa9PY9X1X7Qab4TE1Wio", "cookId": "2373910e4e314b9aa1451d7078ef6420",
    },
}


@pytest.mark.usefixtures("socket_enabled")  # local mock server
class ClientTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.cloud = MockCloud()
        await self.cloud.server.start_server()
        self.session = aiohttp.ClientSession()
        self.saved: list = []
        self.client = api.BrevilleClient(
            self.session, endpoints=self.cloud.endpoints(), on_tokens_updated=self.saved.append
        )

    async def asyncTearDown(self) -> None:
        await self.session.close()
        await self.cloud.server.close()

    async def test_login_uses_password_realm(self) -> None:
        tokens = await self.client.login("me@example.com", "pw")
        _, path, headers, body = self.cloud.requests[0]
        self.assertEqual(path, "/oauth/token")
        self.assertEqual(body["grant_type"], "http://auth0.com/oauth/grant-type/password-realm")
        self.assertEqual(body["client_id"], "A2IYXGeuX1g8s049YEri6WC6hu2wlrMZ")
        self.assertEqual(body["realm"], "Salesforce")
        self.assertEqual(body["scope"], "openid profile email offline_access")
        self.assertEqual(body["audience"], "https://iden-prod.us.auth0.com/userinfo")
        self.assertEqual(tokens.user_id, SUB)
        self.assertEqual(self.saved, [tokens])

    async def test_login_errors(self) -> None:
        self.cloud.login_error = {"error": "invalid_grant", "error_description": "Wrong email or password."}
        with self.assertRaisesRegex(api.BrevilleAuthError, "Wrong email"):
            await self.client.login("me@example.com", "bad")
        self.cloud.login_error = {"error": "mfa_required", "mfa_token": "x"}
        with self.assertRaises(api.BrevilleMfaRequired):
            await self.client.login("me@example.com", "pw")

    async def test_get_appliances_sends_id_token_headers(self) -> None:
        await self.client.login("me@example.com", "pw")
        data = await self.client.get_appliances()
        self.assertEqual(data["appliances"][0]["serialNumber"], SERIAL)
        _, _, headers, _ = self.cloud.requests[-1]
        self.assertEqual(headers["app"], "brevilleJoule")

    async def test_sage_uses_its_own_client_and_channel(self) -> None:
        ep = api.BRANDS["sage"]
        local = self.cloud.endpoints()
        sage = api.BrevilleClient(
            self.session,
            endpoints=dataclasses.replace(
                local, client_id=ep.client_id, app_channel=ep.app_channel
            ),
        )
        await sage.login("me@example.com", "pw")
        await sage.get_appliances()
        _, _, _, login = self.cloud.requests[0]
        self.assertEqual(login["client_id"], "Vp1NuYQ76uhbslASYk0iRRbeHUIsrGDa")
        _, _, headers, _ = self.cloud.requests[-1]
        self.assertEqual(headers["app"], "sageJoule")
        # Only the Auth0 client and app channel differ from Breville.
        self.assertEqual(
            dataclasses.replace(ep, client_id="", app_channel=""),
            dataclasses.replace(api.BRANDS["breville"], client_id="", app_channel=""),
        )

    async def test_requests_are_logged_without_path_ids(self) -> None:
        await self.client.login("me@example.com", "pw")
        await self.client.get_appliances()
        await self.client.finish_wait(SERIAL, "CSJ100")
        get, post = self.client.recent_requests
        self.assertEqual((get["method"], get["endpoint"], get["status"]), ("GET", "appliances", 200))
        self.assertNotIn("response", get)  # account details stay out of the log
        self.assertEqual((post["endpoint"], post["body"]["applianceModel"]), ("finish-wait", "CSJ100"))
        self.assertIn("response", post)

    async def test_401_refreshes_and_retries_once(self) -> None:
        await self.client.login("me@example.com", "pw")
        self.cloud.reject_next = True
        data = await self.client.get_appliances()
        self.assertEqual(len(data["appliances"]), 1)
        grants = [r[3]["grant_type"] for r in self.cloud.requests if r[1] == "/oauth/token"]
        self.assertEqual(grants[-1], "refresh_token")
        self.assertEqual(self.client.tokens.refresh_token, "r1")  # kept when not rotated

    async def test_expired_token_refreshes_before_request(self) -> None:
        self.client = api.BrevilleClient(
            self.session,
            api.Tokens(id_token=make_jwt(exp_in=-10), refresh_token="r1"),
            endpoints=self.cloud.endpoints(),
        )
        await self.client.get_appliances()
        self.assertEqual(self.cloud.requests[0][3]["grant_type"], "refresh_token")

    async def test_start_manual_cook(self) -> None:
        await self.client.login("me@example.com", "pw")
        firmware = api.csj_firmware(IDLE_STATE)
        steps = api.build_csj_manual_steps(55.04, 1800)
        await self.client.load_manual_recipe(SERIAL, "CSJ100", firmware, steps)
        _, path, _, body = self.cloud.requests[-1]
        self.assertEqual(path, f"/appliance/v1/appliances/{SERIAL}/load-manual-recipe")
        self.assertEqual(body["applianceModel"], "CSJ100")
        self.assertEqual(body["firmware"], {"commFirmware": "52", "ctrlFirmware": "123"})
        self.assertEqual(body["payload"]["locale"], "en-US")
        self.assertEqual(
            body["payload"]["steps"],
            [
                {
                    "defaultAutostart": False,
                    "holdingTemperature": 55.0,
                    "phases": [{"mode": "sousVide", "temperatureCelsius": 55.0, "seconds": 1800}],
                    "stepType": "default",
                    "title": "",
                    "type": "sousVideSteps",
                }
            ],
        )
        self.assertNotIn("userDefinedParams", body)

    async def test_edit_finish_wait_and_stop(self) -> None:
        await self.client.login("me@example.com", "pw")
        _, running = api.state_from_message(COOKING_POINT)
        await self.client.csj_update_program(
            SERIAL, api.build_csj_edit_program(running, set_point_c=60)
        )
        _, path, _, body = self.cloud.requests[-1]
        self.assertEqual(path, f"/appliance/v1/appliances/{SERIAL}/send-csj-message")
        self.assertEqual(body["messageType"], "startProgramRequest")
        program = body["message"]["circulatorProgram"]
        self.assertEqual(program["setPoint"], 60.0)
        self.assertEqual(program["cookTime"], 59)  # keeps the running timer
        self.assertEqual(program["programType"], 1)
        self.assertEqual(
            program["programMetadata"],
            {"cookId": "2373910e4e314b9aa1451d7078ef6420", "guideId": "manual_2gJa9PY9X1X7Qab4TE1Wio"},
        )

        await self.client.finish_wait(SERIAL, "CSJ100")
        _, path, _, body = self.cloud.requests[-1]
        self.assertEqual(path, f"/appliance/v1/appliances/{SERIAL}/finish-wait")
        self.assertEqual(sorted(body), ["applianceModel", "timestamp"])
        self.assertEqual(body["applianceModel"], "CSJ100")

        await self.client.finish_wait(SERIAL, "BSV600", {"cookUuid": "c", "wait": {"user": 2}})
        _, _, _, body = self.cloud.requests[-1]
        self.assertEqual(list(body), ["applianceModel", "timestamp", "cookUuid", "wait"])

        await self.client.send_step(SERIAL, "BOV950", {"ctrlFirmware": "1"}, "manual_x", 1)
        _, path, _, body = self.cloud.requests[-1]
        self.assertEqual(path, f"/appliance/v1/appliances/{SERIAL}/send-step")
        self.assertEqual(
            {k: v for k, v in body.items() if k != "timestamp"},
            {"applianceModel": "BOV950", "firmware": {"ctrlFirmware": "1"},
             "recipeId": "manual_x", "stepIndex": 1},
        )

        await self.client.stop_recipe(SERIAL, "CSJ100", firmware=api.csj_firmware(IDLE_STATE))
        _, path, _, body = self.cloud.requests[-1]
        self.assertEqual(path, f"/appliance/v1/appliances/{SERIAL}/stop-recipe")
        self.assertEqual(body["reason"], 1)
        self.assertEqual(body["firmware"], {"commFirmware": "52", "ctrlFirmware": "123"})

    async def test_websocket_subscribe_and_keepalive(self) -> None:
        await self.client.login("me@example.com", "pw")
        sock = self.client.websocket()
        with mock.patch.object(api, "WS_PING_AFTER_IDLE", 0.2), mock.patch.object(
            api, "WS_IDLE_CHECK_INTERVAL", 0.05
        ):
            await sock.connect()
            await sock.subscribe(SERIAL, "CSJ100")
            messages = sock.messages()
            first = await asyncio.wait_for(anext(messages), 2)
            self.assertEqual(api.state_from_message(first), (SERIAL, IDLE_STATE))
            await asyncio.sleep(0.5)
            await sock.close()
        self.assertEqual(
            self.cloud.ws_messages[0],
            {"action": "addAppliance", "serialNumber": SERIAL, "app": "brevilleJoule", "model": "CSJ100"},
        )
        self.assertIn({"action": "ping"}, self.cloud.ws_messages)
        self.assertEqual(self.cloud.ws_headers["sf-id-token"], self.cloud.valid_token)


class ProgramTest(unittest.TestCase):
    def test_manual_program_has_no_cook_time(self) -> None:
        program = api.build_circulator_program(60)
        self.assertNotIn("cookTime", program)
        self.assertEqual(program["programType"], 0)

    def test_program_type_as_name(self) -> None:
        program = api.build_circulator_program(60, 60, program_type_as_name=True)
        self.assertEqual(program["programType"], "AUTOMATIC")

    def test_rejects_out_of_range(self) -> None:
        with self.assertRaises(ValueError):
            api.build_circulator_program(99)
        with self.assertRaises(ValueError):
            api.build_csj_manual_steps(19.9)

    def test_hold_indefinitely_skips_timer(self) -> None:
        (step,) = api.build_csj_manual_steps(60)
        self.assertEqual(step["phases"], [{"mode": "sousVide", "temperatureCelsius": 60.0, "skipTimer": True}])

    def test_edit_before_timer_uses_cook_time(self) -> None:
        state = dict(COOKING_POINT["data"], programStep=1, timeRemaining=0)
        self.assertEqual(api.build_csj_edit_program(state)["cookTime"], 60)
        with self.assertRaises(ValueError):
            api.build_csj_edit_program(IDLE_STATE)

    def test_state_from_message_ignores_other_types(self) -> None:
        self.assertIsNone(api.state_from_message({"messageType": "syncCookHistoryReport", "data": {}}))
        self.assertIsNone(api.state_from_message("pong"))
        self.assertFalse(api.csj_is_ul_certified(IDLE_STATE))
        self.assertTrue(api.csj_is_ul_certified({"hardwareOptions": 0x10001}))


if __name__ == "__main__":
    unittest.main()
