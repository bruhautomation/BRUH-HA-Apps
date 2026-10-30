"""Shared fixtures."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bruh_cooking.const import DOMAIN

from .common import APPLIANCES, PROFILE, FakeSocket, flush, make_jwt


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


@pytest.fixture
def socket() -> FakeSocket:
    return FakeSocket()


@pytest.fixture
def client_class(socket: FakeSocket) -> Generator[MagicMock]:
    with patch("custom_components.bruh_cooking.BrevilleClient", autospec=True) as cls:
        mock = cls.return_value
        mock.get_appliances.return_value = APPLIANCES
        mock.websocket.return_value = socket
        yield cls


@pytest.fixture
def client(client_class: MagicMock) -> MagicMock:
    return client_class.return_value


@pytest.fixture
async def entry(hass: HomeAssistant, client: MagicMock, socket: FakeSocket) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="Salesforce|1",
        title="me@example.com",
        data={"email": "me@example.com", "id_token": make_jwt(**PROFILE), "refresh_token": "refresh"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await flush(hass)
    return entry
