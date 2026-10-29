"""Async client for the Breville+ cloud.

Unofficial. Endpoints and payloads were recovered from the Breville+ Cooking
Android app (com.breville.cookingapp 1.96.0). This module has no Home
Assistant imports so it can be exercised from scripts and tests.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import logging
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import IntEnum
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

APP_CHANNEL = "brevilleJoule"
# Sage, the brand in the UK and Europe, has its own app on the same cloud.
SAGE_APP_CHANNEL = "sageJoule"
SAGE_CLIENT_ID = "Vp1NuYQ76uhbslASYk0iRRbeHUIsrGDa"
MODEL_CSJ100 = "CSJ100"

# CSJ100 manual cook limits from the app's csj100ModeConfigs.
CSJ_MIN_TEMP_C = 20.0
CSJ_MAX_TEMP_C = 98.0
# On UL-certified Joules the app expects a physical button press above this
# holding temperature. UL certification is a bit in reported hardwareOptions.
CSJ_COMPLIANCE_PRESS_ABOVE_C = 85.0
CSJ_HARDWARE_OPTION_UL_CERTIFIED = 0x10000

MODE_SOUS_VIDE = "sousVide"
STEP_TYPE_SOUS_VIDE = "sousVideSteps"

# Websocket messageType values.
MSG_STATE_REPORT = "stateReport"  # full shadow under data.reported
MSG_CHANGE_REPORT = "changeReport"  # partial shadow under data.reported
MSG_DATA_POINT = "applianceDataPoint"  # live state, flat under data
MSG_COOK_HISTORY = "syncCookHistoryReport"


class CsjProgramStep(IntEnum):
    """Reported programStep of a Joule."""

    UNKNOWN = 0
    PRE_HEAT = 1
    WAIT_FOR_FOOD = 2
    COOK = 3
    WAIT_FOR_REMOVE_FOOD = 4
    ERROR = 5
    WAIT_FOR_UPDATE = 6

# The app checks every 5 s and pings when the socket has been quiet for 15 s.
WS_PING_AFTER_IDLE = 15.0
WS_IDLE_CHECK_INTERVAL = 5.0

# Recent REST requests kept for diagnostics.
REQUEST_LOG_SIZE = 20


@dataclass(frozen=True)
class Endpoints:
    """Production endpoints for the Breville brand; see BRANDS for Sage."""

    token_url: str = "https://my.breville.com/oauth/token"
    client_id: str = "A2IYXGeuX1g8s049YEri6WC6hu2wlrMZ"
    audience: str = "https://iden-prod.us.auth0.com/userinfo"
    realm: str = "Salesforce"
    scope: str = "openid profile email offline_access"
    user_api: str = "https://iot-api.breville.com/user"
    control_api: str = "https://iot-api.breville.com/appliance/v1"
    websocket: str = "wss://iot-api-ws.breville.com/applianceProxy"
    # Sent as the REST "app" header and in websocket subscriptions.
    app_channel: str = APP_CHANNEL


# The Sage app logs in the same way with its own Auth0 client (from the app's
# brand configs); everything else is shared. Untested with a Sage account.
BRANDS: dict[str, Endpoints] = {
    "breville": Endpoints(),
    "sage": Endpoints(client_id=SAGE_CLIENT_ID, app_channel=SAGE_APP_CHANNEL),
}


class ProgramType(IntEnum):
    """CSJ circulator program type (proto ProgramType)."""

    MANUAL = 0  # hold the setpoint until stopped
    AUTOMATIC = 1  # run for cookTime seconds


class StopRecipeReason(IntEnum):
    """Reason sent with /stop-recipe."""

    COMPLETE = 0
    CANCEL = 1
    ERROR = 2


class BrevilleError(Exception):
    """Base error for the Breville cloud client."""


class BrevilleAuthError(BrevilleError):
    """Credentials were rejected or the session can no longer be refreshed."""


class BrevilleMfaRequired(BrevilleAuthError):
    """The account requires multi-factor authentication."""


class BrevilleApiError(BrevilleError):
    """Unexpected HTTP response from the cloud."""

    def __init__(self, method: str, url: str, status: int, body: Any) -> None:
        super().__init__(f"{method} {url} -> HTTP {status}: {body!r}"[:500])
        self.method = method
        self.url = url
        self.status = status
        self.body = body


def decode_jwt_claims(token: str) -> dict[str, Any]:
    """Return the (unverified) claims of a JWT."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError) as err:
        raise BrevilleAuthError("Malformed id_token") from err


@dataclass
class Tokens:
    """Auth0 tokens. The Breville API authenticates with the id_token."""

    id_token: str
    refresh_token: str | None = None
    access_token: str | None = None

    @property
    def claims(self) -> dict[str, Any]:
        return decode_jwt_claims(self.id_token)

    @property
    def user_id(self) -> str:
        return self.claims["sub"]

    @property
    def expires_at(self) -> float:
        return float(self.claims.get("exp", 0))

    def expires_within(self, seconds: float) -> bool:
        return time.time() >= self.expires_at - seconds

    def as_dict(self) -> dict[str, Any]:
        return {
            "id_token": self.id_token,
            "refresh_token": self.refresh_token,
            "access_token": self.access_token,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Tokens:
        return cls(
            id_token=data["id_token"],
            refresh_token=data.get("refresh_token"),
            access_token=data.get("access_token"),
        )


async def _read_body(resp: aiohttp.ClientResponse) -> Any:
    text = await resp.text()
    if not text:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return text


def _checked_temp(set_point_c: float) -> float:
    if not CSJ_MIN_TEMP_C <= set_point_c <= CSJ_MAX_TEMP_C:
        raise ValueError(
            f"setpoint {set_point_c} °C outside {CSJ_MIN_TEMP_C}-{CSJ_MAX_TEMP_C} °C"
        )
    return round(set_point_c * 10) / 10


def build_circulator_program(
    set_point_c: float,
    cook_time_s: int | None = None,
    *,
    cook_id: str | None = None,
    guide_id: str = "",
    program_type_as_name: bool = False,
) -> dict[str, Any]:
    """Build a CSJ circulatorProgram the way the app does.

    A cook time makes it an AUTOMATIC (timed) program; without one the Joule
    holds the setpoint until stopped.
    """
    program_type = ProgramType.AUTOMATIC if cook_time_s else ProgramType.MANUAL
    program: dict[str, Any] = {"setPoint": _checked_temp(set_point_c)}
    if cook_time_s:
        program["cookTime"] = int(cook_time_s)
    program["programType"] = (
        program_type.name if program_type_as_name else int(program_type)
    )
    program["programMetadata"] = {
        "cookId": cook_id or uuid.uuid4().hex,
        "guideId": guide_id,
    }
    program["turboCookState"] = 0
    return program


def build_csj_edit_program(
    state: dict[str, Any],
    *,
    set_point_c: float | None = None,
    cook_time_s: int | None = None,
) -> dict[str, Any]:
    """Program that changes a running cook, keeping its cookId and timer.

    Mirrors buildCsjCirculatorProgramForEditCook: start from the reported
    program, using timeRemaining once the timer is running.
    """
    if not state.get("cookId") or state.get("setPoint") is None:
        raise ValueError("No cook is running")
    remaining = state.get("timeRemaining")
    cook_time = remaining if remaining else state.get("cookTime")
    if cook_time_s is not None:
        cook_time = cook_time_s
    return build_circulator_program(
        state["setPoint"] if set_point_c is None else set_point_c,
        int(cook_time) if cook_time and cook_time >= 1 else None,
        cook_id=state["cookId"],
        guide_id=state.get("guideId") or "",
    )


def build_csj_manual_steps(
    set_point_c: float, cook_time_s: int | None = None, *, auto_start_timer: bool = False
) -> list[dict[str, Any]]:
    """Recipe steps for a manual Joule cook (getCSJ100ManualCookSteps).

    Without a cook time the Joule holds the temperature until stopped. With
    one, it waits after preheat for the food to go in unless auto_start_timer.
    """
    temp = _checked_temp(set_point_c)
    phase: dict[str, Any] = {"mode": MODE_SOUS_VIDE, "temperatureCelsius": temp}
    if cook_time_s:
        phase["seconds"] = int(cook_time_s)
    else:
        phase["skipTimer"] = True
    return [
        {
            "defaultAutostart": auto_start_timer,
            "holdingTemperature": temp,
            "phases": [phase],
            "stepType": "default",
            "title": "",
            "type": STEP_TYPE_SOUS_VIDE,
        }
    ]


def csj_firmware(state: dict[str, Any]) -> dict[str, Any]:
    """Firmware descriptor the app sends with Joule commands."""
    return {
        "commFirmware": state.get("espFirmwareVersion"),
        "ctrlFirmware": state.get("firmwareVersion"),
    }


def csj_is_ul_certified(state: dict[str, Any]) -> bool:
    return bool((state.get("hardwareOptions") or 0) & CSJ_HARDWARE_OPTION_UL_CERTIFIED)


@dataclass(frozen=True)
class StateUpdate:
    """Appliance state carried by one websocket message."""

    serial: str
    message_type: str
    state: dict[str, Any]
    replace: bool  # stateReport replaces the shadow; the others merge into it
    version: int | None


def parse_message(msg: Any) -> StateUpdate | None:
    """Decode a websocket message that carries appliance state."""
    if not isinstance(msg, dict) or not isinstance(msg.get("data"), dict):
        return None
    serial, message_type = msg.get("serialNumber"), msg.get("messageType")
    if message_type in (MSG_STATE_REPORT, MSG_CHANGE_REPORT):
        state = msg["data"].get("reported")
    elif message_type == MSG_DATA_POINT:
        state = msg["data"]
    else:
        return None
    if not serial or not isinstance(state, dict):
        return None
    version = msg.get("version")
    try:
        version = int(version) if version is not None else None
    except (TypeError, ValueError):
        version = None
    return StateUpdate(
        serial, message_type, state, message_type == MSG_STATE_REPORT, version
    )


def state_from_message(msg: Any) -> tuple[str, dict[str, Any]] | None:
    """Return (serial, state) for websocket messages that carry appliance state."""
    update = parse_message(msg)
    return (update.serial, update.state) if update else None


class BrevilleClient:
    """Talks to the Breville+ cloud on behalf of one account."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        tokens: Tokens | None = None,
        *,
        endpoints: Endpoints = Endpoints(),
        on_tokens_updated: Callable[[Tokens], None] | None = None,
    ) -> None:
        self._session = session
        self._tokens = tokens
        self._endpoints = endpoints
        self._on_tokens_updated = on_tokens_updated
        self._refresh_lock = asyncio.Lock()
        self._request_log: deque[dict[str, Any]] = deque(maxlen=REQUEST_LOG_SIZE)

    @property
    def tokens(self) -> Tokens | None:
        return self._tokens

    @property
    def recent_requests(self) -> list[dict[str, Any]]:
        """The last few REST requests, oldest first. Unredacted."""
        return list(self._request_log)

    @property
    def endpoints(self) -> Endpoints:
        return self._endpoints

    # -- authentication -------------------------------------------------

    async def _token_request(self, body: dict[str, Any]) -> dict[str, Any]:
        ep = self._endpoints
        async with self._session.post(
            ep.token_url, json={"client_id": ep.client_id, **body}
        ) as resp:
            data = await _read_body(resp)
            if resp.status == 200 and isinstance(data, dict):
                return data
        error = data.get("error") if isinstance(data, dict) else None
        if error == "mfa_required":
            raise BrevilleMfaRequired("Account requires multi-factor authentication")
        if error in ("invalid_grant", "access_denied", "unauthorized_client"):
            desc = data.get("error_description") or error
            raise BrevilleAuthError(desc)
        raise BrevilleApiError("POST", ep.token_url, resp.status, data)

    def _store_tokens(self, data: dict[str, Any]) -> Tokens:
        previous = self._tokens
        if "id_token" not in data:
            raise BrevilleAuthError("Token response did not include an id_token")
        self._tokens = Tokens(
            id_token=data["id_token"],
            refresh_token=data.get("refresh_token")
            or (previous.refresh_token if previous else None),
            access_token=data.get("access_token"),
        )
        if self._on_tokens_updated:
            self._on_tokens_updated(self._tokens)
        return self._tokens

    async def login(self, email: str, password: str) -> Tokens:
        """Log in with the Breville account email and password."""
        ep = self._endpoints
        data = await self._token_request(
            {
                "grant_type": "http://auth0.com/oauth/grant-type/password-realm",
                "username": email,
                "password": password,
                "realm": ep.realm,
                "scope": ep.scope,
                "audience": ep.audience,
            }
        )
        return self._store_tokens(data)

    async def refresh(self) -> Tokens:
        """Exchange the refresh token for a new id_token."""
        if not self._tokens or not self._tokens.refresh_token:
            raise BrevilleAuthError("No refresh token; log in again")
        data = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": self._tokens.refresh_token,
            }
        )
        return self._store_tokens(data)

    async def id_token(self, *, force_refresh: bool = False) -> str:
        """Return a valid id_token, refreshing it when close to expiry."""
        async with self._refresh_lock:
            if not self._tokens:
                raise BrevilleAuthError("Not logged in")
            if force_refresh or self._tokens.expires_within(300):
                await self.refresh()
            return self._tokens.id_token

    # -- REST -----------------------------------------------------------

    async def request(
        self, method: str, url: str, body: Any = None, *, _retry: bool = True
    ) -> Any:
        """Authenticated JSON request, retried once after a 401."""
        token = await self.id_token()
        headers = {
            "Accept": "application/json",
            "sf-id-token": token,
            "Authorization": f"Bearer {token}",
            "app": self._endpoints.app_channel,
        }
        kwargs: dict[str, Any] = {"headers": headers}
        if body is not None:
            kwargs["json"] = body
        # Path IDs (serial, user) stay out of the log: only the last segment.
        record: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            "method": method,
            "endpoint": url.rsplit("/", 1)[-1],
            "body": body,
        }
        self._request_log.append(record)
        try:
            async with self._session.request(method, url, **kwargs) as resp:
                status = resp.status
                data = await _read_body(resp)
        except (aiohttp.ClientError, TimeoutError) as err:
            record["error"] = repr(err)
            raise
        record["status"] = status
        if method != "GET":  # GET responses are account details, not command results
            record["response"] = data
        if status == 401 and _retry:
            await self.id_token(force_refresh=True)
            return await self.request(method, url, body, _retry=False)
        if status >= 400:
            raise BrevilleApiError(method, url, status, data)
        return data

    async def get_appliances(self) -> dict[str, Any]:
        """Return {"appliances": [...], "ownedModels": [...]} for the account."""
        await self.id_token()
        url = f"{self._endpoints.user_api}/v2/user/{self._tokens.user_id}/appliances"
        data = await self.request("GET", url) or {}
        return {
            "appliances": data.get("appliances") or [],
            "ownedModels": data.get("ownedModels") or [],
        }

    def appliance_url(self, serial: str, action: str) -> str:
        return f"{self._endpoints.control_api}/appliances/{serial}/{action}"

    async def get_model(self, serial: str) -> Any:
        """Return the cloud's model record for an appliance."""
        return await self.request("GET", self.appliance_url(serial, "model"))

    async def send_csj_message(
        self, serial: str, message_type: str, message: dict[str, Any]
    ) -> Any:
        """Relay a ChefSteps Joule RPC message through the cloud."""
        return await self.request(
            "POST",
            self.appliance_url(serial, "send-csj-message"),
            {"messageType": message_type, "message": message},
        )

    async def csj_update_program(
        self, serial: str, circulator_program: dict[str, Any]
    ) -> Any:
        """Change a running Joule cook (see build_csj_edit_program).

        On an idle Joule this only loads the program; it does not start
        heating. Start cooks with load_manual_recipe.
        """
        return await self.send_csj_message(
            serial, "startProgramRequest", {"circulatorProgram": circulator_program}
        )

    async def load_manual_recipe(
        self,
        serial: str,
        model: str,
        firmware: Any,
        steps: list[dict[str, Any]],
        *,
        locale: str = "en-US",
        user_defined_params: dict[str, Any] | None = None,
    ) -> Any:
        """Start a manual cook; the cloud runs the steps on the appliance."""
        body: dict[str, Any] = {
            "applianceModel": model,
            "firmware": firmware,
            "payload": {"locale": locale, "steps": steps},
            "timestamp": int(time.time() * 1000),
        }
        if user_defined_params is not None:
            body["userDefinedParams"] = user_defined_params
        return await self.request(
            "POST", self.appliance_url(serial, "load-manual-recipe"), body
        )

    async def finish_wait(
        self, serial: str, model: str, extra: dict[str, Any] | None = None
    ) -> Any:
        """Virtual button press: food is in (starts the timer) or food is out.

        `extra` is merged in as the app does with Object.assign: newer
        appliances need the cook's position (appliance.build_finish_wait).
        """
        return await self.request(
            "POST",
            self.appliance_url(serial, "finish-wait"),
            {"applianceModel": model, "timestamp": int(time.time() * 1000), **(extra or {})},
        )

    async def send_step(
        self, serial: str, model: str, firmware: Any, recipe_id: str, step_index: int
    ) -> Any:
        """Go on to a step of the running recipe (the app's next-step button)."""
        return await self.request(
            "POST",
            self.appliance_url(serial, "send-step"),
            {
                "applianceModel": model,
                "firmware": firmware,
                "recipeId": recipe_id,
                "stepIndex": step_index,
                "timestamp": int(time.time() * 1000),
            },
        )

    async def update_cook(
        self,
        serial: str,
        model: str,
        updates: list[dict[str, Any]],
        *,
        uuid: str = "",
        step: int = 0,
    ) -> Any:
        """Apply {"name", "value"} updates (cookSetPoint, cookTime, autoStartTimer)."""
        return await self.request(
            "POST",
            self.appliance_url(serial, "update-cook"),
            {"model": model, "step": step, "updates": updates, "uuid": uuid},
        )

    async def stop_recipe(
        self,
        serial: str,
        model: str,
        *,
        firmware: Any = None,
        reason: StopRecipeReason = StopRecipeReason.CANCEL,
    ) -> Any:
        """Stop the running cook."""
        return await self.request(
            "POST",
            self.appliance_url(serial, "stop-recipe"),
            {
                "applianceModel": model,
                "firmware": firmware,
                "reason": int(reason),
                "timestamp": int(time.time() * 1000),
            },
        )

    def websocket(self) -> ApplianceSocket:
        return ApplianceSocket(self, self._session)


class ApplianceSocket:
    """Live appliance updates from the applianceProxy websocket."""

    def __init__(self, client: BrevilleClient, session: aiohttp.ClientSession) -> None:
        self._client = client
        self._session = session
        self._ws: aiohttp.ClientWebSocketResponse | None = None
        self._keepalive: asyncio.Task[None] | None = None
        self._last_activity = 0.0

    @property
    def connected(self) -> bool:
        return self._ws is not None and not self._ws.closed

    async def connect(self) -> None:
        url = self._client.endpoints.websocket
        for attempt in (1, 2):
            token = await self._client.id_token(force_refresh=attempt == 2)
            try:
                self._ws = await self._session.ws_connect(
                    url,
                    headers={"sf-id-token": token, "Authorization": f"Bearer {token}"},
                )
                break
            except aiohttp.WSServerHandshakeError as err:
                if err.status == 401 and attempt == 1:
                    continue
                if err.status in (401, 403):
                    raise BrevilleAuthError(f"Websocket rejected: {err.status}") from err
                raise BrevilleApiError("GET", url, err.status, err.message) from err
        self._last_activity = time.monotonic()
        self._keepalive = asyncio.create_task(self._keepalive_loop())

    async def _send(self, payload: dict[str, Any]) -> None:
        if not self.connected:
            raise BrevilleError("Websocket is not connected")
        await self._ws.send_json(payload)
        self._last_activity = time.monotonic()

    async def subscribe(self, serial: str, model: str) -> None:
        await self._send(
            {
                "action": "addAppliance",
                "serialNumber": serial,
                "app": self._client.endpoints.app_channel,
                "model": model,
            }
        )

    async def unsubscribe(self, serial: str) -> None:
        await self._send({"action": "removeAppliance", "serialNumber": serial})

    async def _keepalive_loop(self) -> None:
        while self.connected:
            await asyncio.sleep(WS_IDLE_CHECK_INTERVAL)
            if time.monotonic() - self._last_activity >= WS_PING_AFTER_IDLE:
                with contextlib.suppress(Exception):
                    await self._send({"action": "ping"})

    async def messages(self) -> AsyncIterator[Any]:
        """Yield decoded messages until the socket closes."""
        if not self._ws:
            raise BrevilleError("Websocket is not connected")
        async for msg in self._ws:
            self._last_activity = time.monotonic()
            if msg.type == aiohttp.WSMsgType.TEXT:
                try:
                    yield json.loads(msg.data)
                except ValueError:
                    yield msg.data
            elif msg.type == aiohttp.WSMsgType.BINARY:
                yield msg.data
            elif msg.type == aiohttp.WSMsgType.ERROR:
                break

    async def close(self) -> None:
        if self._keepalive:
            self._keepalive.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive
            self._keepalive = None
        if self._ws and not self._ws.closed:
            await self._ws.close()
