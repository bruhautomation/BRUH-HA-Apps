"""Test helpers."""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant


def make_jwt(sub: str = "Salesforce|0051234", exp_in: float = 3600, **claims: Any) -> str:
    def part(obj: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")

    payload = {"sub": sub, "exp": time.time() + exp_in, **claims}
    return f"{part({'alg': 'none'})}.{part(payload)}.sig"


JOULE, OVEN = "J123456", "A950123456"
# The profile claims a real Breville login token carries.
PROFILE = {
    "email": "me@example.com", "name": "Pat Example", "nickname": "patex",
    "customer_id": "C-123456", "https://breville.com/crm_user_id": "CRM-98765",
}
APPLIANCES = {
    "appliances": [
        {"model": "CSJ100", "serialNumber": JOULE, "name": "Countertop", "itemNumber": "CS10001"},
        {"model": "BOV950", "serialNumber": OVEN, "name": "Kitchen Oven", "itemNumber": "BOV950BSS"},
        {"model": "BES995", "serialNumber": "espresso1", "name": "Espresso"},
    ],
    "ownedModels": ["CSJ100", "BOV950", "BES995"],
}


class FakeSocket:
    """Stands in for ApplianceSocket; tests push messages into it."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[Any] = asyncio.Queue()
        self.subscribed: list[tuple[str, str]] = []
        self.unsubscribed: list[str] = []
        self.connected = False
        self.connect_error: Exception | None = None

    async def connect(self) -> None:
        if self.connect_error:
            raise self.connect_error
        self.connected = True

    async def subscribe(self, serial: str, model: str) -> None:
        self.subscribed.append((serial, model))

    async def unsubscribe(self, serial: str) -> None:
        self.unsubscribed.append(serial)

    async def messages(self):
        while (msg := await self.queue.get()) is not None:
            yield msg

    async def close(self) -> None:
        self.connected = False


def csj(state: str, step: int, **extra: Any) -> dict:
    csj.ts += 1000
    return {
        "serialNumber": JOULE,
        "messageType": "applianceDataPoint",
        "version": str(1792805500000 + csj.ts),
        "data": {
            "state": state, "model": "CSJ100", "programStep": step, "bathTemp": 55.1,
            "setPoint": 56.0, "cookTime": 300, "timeRemaining": 0, "errorState": 0,
            "eventReason": 0, "cookId": "cook1", "guideId": "manual_x",
            "firmwareVersion": "123", "espFirmwareVersion": "52", "hardwareOptions": 1,
            "timestamp": csj.ts, **extra,
        },
    }


csj.ts = 1_000_000

OVEN_IDLE = {
    "serialNumber": OVEN,
    "messageType": "stateReport",
    "version": 10,
    "data": {
        "reported": {
            "state": "idle", "model": "BOV950", "heaters": [{"cur_temp": 22.0, "state": 0}],
            "door": {"state": 1}, "appliance": {"mode": 3}, "errors": [],
            "firmware": {"comm_mcu": "1.0", "host_mcu": "2.0"},
        }
    },
}


async def flush(hass: HomeAssistant) -> None:
    for _ in range(5):
        await asyncio.sleep(0)
    await hass.async_block_till_done()


async def push(hass: HomeAssistant, socket: FakeSocket, *messages: dict) -> None:
    for msg in messages:
        socket.queue.put_nowait(msg)
    await flush(hass)


async def call(hass: HomeAssistant, domain: str, service: str, entity_id: str, **data: Any) -> None:
    await hass.services.async_call(
        domain, service, {ATTR_ENTITY_ID: entity_id, **data}, blocking=True
    )


def real_oven(version: int, **reported: Any) -> dict:
    """A stateReport shaped like the real BOV950's in issue #1 (set to °F, baking at 350 °F)."""
    return {
        "serialNumber": OVEN, "messageType": "stateReport", "version": version,
        "data": {"reported": {
            "state": "active", "model": "BOV950", "door": 1, "motor": 1, "errors": [],
            "cfg": {"temp_unit": 1, "vol": 11}, "timers": [None, None],
            "firmware": {"commFirmware": "1.10.131", "teFirmware": "2.4.0", "ctrlFirmware": "1.10.21"},
            "heater": {"state": 2, "temp_sp": 175, "temp_sp_f": 350, "temp_sp_m": 161, "cur_temp": 160},
            "appliance": {"mode": 3, "rotate_state": 0, "preset": 0, "cook_segment": 0, "frozen": 0},
            "recipe": "manual_x", "cookUUID": "cook-7", "currentStage": 0, "currentStep": 0,
            "currentInstruction": 10, "currentStepState": "active", **reported,
        }},
    }
