"""Conversation agent for BRUH Claude.

Registers a ConversationEntity for each config entry so that multiple
personality agents can appear under Settings > Voice Assistants.
"""

from __future__ import annotations

import logging

from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.components.conversation import ConversationEntityFeature

    SUPPORTS_CONTROL = ConversationEntityFeature.CONTROL
except (ImportError, AttributeError):
    SUPPORTS_CONTROL = 0

from .const import CONF_NAME, CONF_SYSTEM_PROMPT, DEFAULT_NAME, DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the BRUH Claude conversation entity."""
    bridge = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([BruhClaudeConversationEntity(config_entry, bridge)])


class BruhClaudeConversationEntity(ConversationEntity):
    """Conversation agent that routes requests to the Claude Terminal app.

    Each config entry can specify a unique name and system prompt,
    allowing multiple personalities to coexist as separate agents.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_supported_features = SUPPORTS_CONTROL
    _attr_icon = "mdi:robot"

    def __init__(self, config_entry: ConfigEntry, bridge) -> None:
        self._bridge = bridge
        self._system_prompt = config_entry.data.get(CONF_SYSTEM_PROMPT, "")
        self._attr_name = config_entry.data.get(CONF_NAME, DEFAULT_NAME)
        self._attr_unique_id = f"{config_entry.entry_id}_conversation"

    @property
    def supported_languages(self) -> list[str] | str:
        """Claude handles all languages."""
        return "*"

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Process a conversation turn by forwarding to the Claude app."""
        conversation_id = user_input.conversation_id

        _LOGGER.debug(
            "Processing conversation [%s]: %s (id=%s)",
            self._attr_name,
            user_input.text,
            conversation_id,
        )

        try:
            response_text = await self._bridge.async_send_conversation(
                text=user_input.text,
                conversation_id=conversation_id,
                system_prompt=self._system_prompt or None,
            )
        except TimeoutError:
            response_text = (
                "Sorry, Claude didn't respond in time. "
                "Make sure the BRUH Claude Terminal app is running."
            )
        except Exception:
            _LOGGER.exception("Error communicating with Claude app")
            response_text = (
                "Sorry, something went wrong communicating with the "
                "Claude Terminal app."
            )

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(response_text)
        return ConversationResult(
            response=response,
            conversation_id=conversation_id,
        )
