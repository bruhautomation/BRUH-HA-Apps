"""Config flow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bruh_cooking.api import (
    BrevilleAuthError,
    BrevilleError,
    BrevilleMfaRequired,
    Tokens,
)
from custom_components.bruh_cooking.const import CONF_ALLOW_UNTESTED_CONTROL, CONF_BRAND, DOMAIN

from .common import make_jwt

LOGIN = "custom_components.bruh_cooking.config_flow.BrevilleClient.login"
SETUP_ENTRY = "custom_components.bruh_cooking.async_setup_entry"
USER = {CONF_EMAIL: "me@example.com", CONF_PASSWORD: "pw"}


def tokens(sub: str = "Salesforce|1") -> Tokens:
    return Tokens(id_token=make_jwt(sub), refresh_token="refresh")


async def test_user_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    with patch(LOGIN, AsyncMock(return_value=tokens())), patch(SETUP_ENTRY, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "me@example.com"
    assert result["result"].unique_id == "Salesforce|1"
    assert result["data"]["refresh_token"] == "refresh"
    assert result["data"][CONF_BRAND] == "breville"
    assert CONF_PASSWORD not in result["data"]


@pytest.mark.parametrize(
    ("country", "user_input", "brand", "client_id"),
    [
        ("US", USER, "breville", "A2IYXGeuX1g8s049YEri6WC6hu2wlrMZ"),
        ("GB", USER, "sage", "Vp1NuYQ76uhbslASYk0iRRbeHUIsrGDa"),
        ("US", {**USER, CONF_BRAND: "sage"}, "sage", "Vp1NuYQ76uhbslASYk0iRRbeHUIsrGDa"),
    ],
)
async def test_brand(
    hass: HomeAssistant, country: str, user_input: dict, brand: str, client_id: str
) -> None:
    """The brand defaults to the one sold in the country, and picks the login client."""
    hass.config.country = country
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(LOGIN, autospec=True, return_value=tokens()) as login, patch(
        SETUP_ENTRY, AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], user_input)
    assert result["data"][CONF_BRAND] == brand
    client = login.await_args.args[0]
    assert client.endpoints.client_id == client_id


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (BrevilleAuthError("bad"), "invalid_auth"),
        (BrevilleMfaRequired("mfa"), "mfa_not_supported"),
        (BrevilleError("down"), "cannot_connect"),
        (RuntimeError("boom"), "unknown"),
    ],
)
async def test_user_flow_errors(hass: HomeAssistant, error: Exception, key: str) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(LOGIN, AsyncMock(side_effect=error)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": key}

    with patch(LOGIN, AsyncMock(return_value=tokens())), patch(SETUP_ENTRY, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_already_configured(hass: HomeAssistant) -> None:
    MockConfigEntry(domain=DOMAIN, unique_id="Salesforce|1", data={}).add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    with patch(LOGIN, AsyncMock(return_value=tokens())):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.parametrize(
    ("sub", "reason"), [("Salesforce|1", "reauth_successful"), ("Salesforce|2", "wrong_account")]
)
async def test_reauth(hass: HomeAssistant, sub: str, reason: str) -> None:
    entry = MockConfigEntry(
        domain=DOMAIN,
        unique_id="Salesforce|1",
        data={CONF_EMAIL: "me@example.com", "id_token": "old", "refresh_token": "old"},
    )
    entry.add_to_hass(hass)
    result = await entry.start_reauth_flow(hass)
    assert result["step_id"] == "reauth_confirm"
    with patch(LOGIN, AsyncMock(return_value=tokens(sub))) as login, patch(
        SETUP_ENTRY, AsyncMock(return_value=True)
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "new"}
        )
    login.assert_awaited_once_with("me@example.com", "new")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == reason
    if reason == "reauth_successful":
        assert entry.data["refresh_token"] == "refresh"
        assert entry.data[CONF_EMAIL] == "me@example.com"
    else:
        assert entry.data["refresh_token"] == "old"


async def test_options_flow(hass: HomeAssistant) -> None:
    entry = MockConfigEntry(domain=DOMAIN, unique_id="Salesforce|1", data={CONF_EMAIL: "me@example.com"})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_ALLOW_UNTESTED_CONTROL: True}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options == {CONF_ALLOW_UNTESTED_CONTROL: True}


async def test_the_add_on_offers_the_login(hass: HomeAssistant) -> None:
    """The add-on's discovery opens the same login; once an account is set up it offers nothing."""
    from homeassistant.config_entries import SOURCE_HASSIO
    from homeassistant.helpers.service_info.hassio import HassioServiceInfo

    info = HassioServiceInfo(config={}, name="BRUH Cooking", slug="bruh_cooking", uuid="1")
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_HASSIO}, data=info)
    assert (result["type"], result["step_id"]) == (FlowResultType.FORM, "user")
    with patch(LOGIN, AsyncMock(return_value=tokens())), patch(SETUP_ENTRY, AsyncMock(return_value=True)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], USER)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "Salesforce|1"

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_HASSIO}, data=info)
    assert (result["type"], result["reason"]) == (FlowResultType.ABORT, "already_configured")
