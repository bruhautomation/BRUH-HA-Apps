"""Config flow for BRUH Cooking: a Breville or Sage account login."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.hassio import HassioServiceInfo
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import (
    BRANDS,
    BrevilleAuthError,
    BrevilleClient,
    BrevilleError,
    BrevilleMfaRequired,
    Tokens,
)
from .const import (
    BRAND_BREVILLE,
    BRAND_SAGE,
    CONF_ALLOW_UNTESTED_CONTROL,
    CONF_BRAND,
    CONF_SHOW_SIDEBAR_PANEL,
    DOMAIN,
    SAGE_COUNTRIES,
)
from .coordinator import sidebar_panel_enabled

_LOGGER = logging.getLogger(__name__)

BRAND_SELECTOR = SelectSelector(
    SelectSelectorConfig(
        options=[BRAND_BREVILLE, BRAND_SAGE],
        translation_key=CONF_BRAND,
        mode=SelectSelectorMode.LIST,
    )
)
REAUTH_SCHEMA = vol.Schema({vol.Required(CONF_PASSWORD): str})



class BrevilleConfigFlow(ConfigFlow, domain=DOMAIN):
    """Log in with a Breville account."""

    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> BrevilleOptionsFlow:
        return BrevilleOptionsFlow()

    async def _login(
        self, email: str, password: str, brand: str
    ) -> tuple[Tokens | None, dict[str, str]]:
        client = BrevilleClient(async_get_clientsession(self.hass), endpoints=BRANDS[brand])
        try:
            return await client.login(email, password), {}
        except BrevilleMfaRequired:
            return None, {"base": "mfa_not_supported"}
        except BrevilleAuthError:
            return None, {"base": "invalid_auth"}
        except (BrevilleError, aiohttp.ClientError, TimeoutError):
            return None, {"base": "cannot_connect"}
        except Exception:
            _LOGGER.exception("Unexpected error logging in to Breville")
            return None, {"base": "unknown"}

    async def async_step_hassio(
        self, discovery_info: HassioServiceInfo
    ) -> ConfigFlowResult:
        """Offered by the BRUH Cooking add-on: the same login, one click from the tile.

        Only while no account is set up; a second account is added by hand.
        """
        await self.async_set_unique_id(f"{DOMAIN}_addon")
        if self._async_current_entries():
            return self.async_abort(reason="already_configured")
        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, errors = await self._login(
                user_input[CONF_EMAIL], user_input[CONF_PASSWORD], user_input[CONF_BRAND]
            )
            if tokens:
                await self.async_set_unique_id(tokens.user_id)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_EMAIL],
                    data={
                        CONF_EMAIL: user_input[CONF_EMAIL],
                        CONF_BRAND: user_input[CONF_BRAND],
                        **tokens.as_dict(),
                    },
                )
        # The brand people most likely have where they are.
        brand = BRAND_SAGE if self.hass.config.country in SAGE_COUNTRIES else BRAND_BREVILLE
        schema = vol.Schema(
            {
                vol.Required(CONF_EMAIL): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Required(CONF_BRAND, default=brand): BRAND_SELECTOR,
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                {
                    key: value
                    for key in (CONF_EMAIL, CONF_BRAND)
                    if (value := (user_input or {}).get(key)) is not None
                },
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            tokens, errors = await self._login(
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
                entry.data.get(CONF_BRAND, BRAND_BREVILLE),
            )
            if tokens:
                await self.async_set_unique_id(tokens.user_id)
                self._abort_if_unique_id_mismatch(reason="wrong_account")
                return self.async_update_reload_and_abort(
                    entry, data_updates=tokens.as_dict()
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


class BrevilleOptionsFlow(OptionsFlow):
    """Whether untested appliances may be controlled, and the sidebar panel."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            options = {
                CONF_ALLOW_UNTESTED_CONTROL: user_input.get(CONF_ALLOW_UNTESTED_CONTROL, False)
            }
            # Saved only when off, so the panel stays on by default.
            if user_input.get(CONF_SHOW_SIDEBAR_PANEL, sidebar_panel_enabled(self.config_entry)) is False:
                options[CONF_SHOW_SIDEBAR_PANEL] = False
            return self.async_create_entry(data=options)
        # Left out, the panel option keeps its value.
        schema = vol.Schema(
            {
                vol.Required(CONF_ALLOW_UNTESTED_CONTROL, default=False): bool,
                vol.Required(
                    CONF_SHOW_SIDEBAR_PANEL, default=sidebar_panel_enabled(self.config_entry)
                ): bool,
            }
        )
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.options),
        )
