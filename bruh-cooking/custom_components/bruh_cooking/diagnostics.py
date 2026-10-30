"""Diagnostics: raw appliance state and recent traffic, to support new models and firmware.

Testers post these publicly, and untested models may report fields nobody has
seen, so fields are masked by the words in their names rather than a fixed
list. Personal values (the account's email and IDs, the profile in the login
token, appliance names and serial numbers) are masked wherever they appear,
even inside other text, and so is anything that looks like an email or MAC
address.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict
from itertools import pairwise
import re
from typing import Any

from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant

from . import BrevilleConfigEntry
from .api import BrevilleAuthError, decode_jwt_claims
from .appliance import MODELS
from .coordinator import sidebar_panel_enabled
from .frontend import panel_module_url, registered_title
from .panel_api import async_panel_diagnostics
from .panel_spec import detect_finish

REDACTED = "**REDACTED**"

# A field is masked when one word of its name is listed here, or two
# neighbouring words are a pair below. fooBar and foo_bar split the same way.
SENSITIVE_WORDS = frozenset({
    "token", "tokens", "password", "secret", "mfa",
    "email", "phone", "address", "street", "city", "zip", "postal", "postcode",
    "latitude", "longitude", "lat", "lng", "lon", "location", "geolocation",
    "birthday", "birthdate", "username", "nickname", "customer", "owner", "account",
    "picture", "avatar", "photo", "serial", "uuid",
    "ssid", "bssid", "mac", "ip", "ipv4", "ipv6", "gateway", "dns", "netmask",
    "subnet", "router", "hostname",
})
SENSITIVE_PAIRS = frozenset({
    ("e", "mail"), ("first", "name"), ("last", "name"), ("given", "name"),
    ("family", "name"), ("full", "name"), ("display", "name"), ("nick", "name"),
    ("user", "name"), ("host", "name"), ("user", "id"), ("device", "id"),
    ("appliance", "id"), ("circulator", "id"), ("cook", "id"),
})
WORD = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+|\d+")

# Login token claims that say nothing about the person; the others are masked.
TECHNICAL_CLAIMS = frozenset(
    {"iss", "aud", "azp", "iat", "exp", "nbf", "auth_time", "email_verified", "updated_at"}
)
EMAIL = r"[^\s@\"']+@[^\s@\"']+\.[a-z]{2,}"
MAC_ADDRESS = r"\b[0-9a-f]{2}(?:[:-][0-9a-f]{2}){5}\b"


def sensitive_key(key: str) -> bool:
    if key.lower() == "sub":  # the user ID in JWT claims
        return True
    words = [word.lower() for word in WORD.findall(key)]
    return any(word in SENSITIVE_WORDS for word in words) or any(
        pair in SENSITIVE_PAIRS for pair in pairwise(words)
    )


class Redactor:
    """Copies data with sensitive fields and personal values masked."""

    def __init__(self, personal: Iterable[str | None] = ()) -> None:
        values = {value for value in personal if value}
        self._exact = {value.casefold() for value in values}
        # Values too short to mask inside other text are only masked whole.
        inside = sorted((value for value in values if len(value) >= 4), key=len, reverse=True)
        self._inside = re.compile(
            "|".join([*map(re.escape, inside), EMAIL, MAC_ADDRESS]), re.IGNORECASE
        )

    def __call__(self, value: Any) -> Any:
        if isinstance(value, dict):
            # Keys too: some data is keyed by serial number or cook.
            return {
                self._text(str(key)): self._field(str(key), item) for key, item in value.items()
            }
        if isinstance(value, list | tuple):
            return [self(item) for item in value]
        if isinstance(value, str):
            return self._text(value)
        return value

    def _text(self, text: str) -> str:
        if text.casefold() in self._exact:
            return REDACTED
        return self._inside.sub(REDACTED, text)

    def _field(self, key: str, value: Any) -> Any:
        if value is None or value == "":
            return value
        if sensitive_key(key):
            return REDACTED
        return self(value)


def personal_values(entry: BrevilleConfigEntry) -> list[str]:
    """Values that identify the account holder or their appliances."""
    values = [entry.data.get(CONF_EMAIL), entry.unique_id, entry.title]
    try:
        claims = decode_jwt_claims(entry.data.get("id_token") or "")
    except BrevilleAuthError:
        claims = {}
    values += [
        value
        for claim, value in claims.items()
        if claim not in TECHNICAL_CLAIMS and isinstance(value, str)
    ]
    for appliance in entry.runtime_data.appliances.values():
        values += [appliance.serial, appliance.name]
        # The appliance's own state names it too: a BOV950's name is its serial.
        values += [appliance.state.get("serialNumber"), appliance.state.get("name")]
    return [value for value in values if isinstance(value, str) and value]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: BrevilleConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    redact = Redactor(personal_values(entry))
    return {
        "entry": redact(dict(entry.data)),
        "options": redact(dict(entry.options)),
        "websocket_connected": coordinator.connected,
        "recent_requests": redact(coordinator.client.recent_requests),
        "panel": {
            "enabled": sidebar_panel_enabled(entry),
            "registered": panel_module_url(hass) is not None,
            "title": registered_title(hass),
            "module_url": panel_module_url(hass),
            **await async_panel_diagnostics(hass),
        },
        "appliances": [
            {
                "model": appliance.model,
                "item_number": appliance.item_number,
                "finish": detect_finish(appliance.model, appliance.item_number, appliance.serial),
                "tested": MODELS[appliance.model].tested,
                "status": redact(asdict(appliance.status)),
                "settings": asdict(appliance.settings),
                "reported": redact(appliance.state),
                "recent_messages": redact(list(appliance.messages)),
            }
            for appliance in coordinator.appliances.values()
        ],
    }
