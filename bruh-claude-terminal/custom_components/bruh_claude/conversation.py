"""Conversation agent for BRUH Claude.

Registers a ConversationEntity so that "BRUH Claude" appears as a selectable
conversation agent under Settings > Voice Assistants.
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

from .const import DOMAIN

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
    """Conversation agent that routes requests to the Claude Terminal add-on."""

    _attr_has_entity_name = True
    _attr_name = "BRUH Claude"
    _attr_should_poll = False

    def __init__(self, config_entry: ConfigEntry, bridge) -> None:
        self._bridge = bridge
        self._attr_unique_id = f"{config_entry.entry_id}_conversation"

    @property
    def supported_languages(self) -> list[str] | str:
        """Claude handles all languages."""
        return "*"

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Process a conversation turn by forwarding to the Claude add-on."""
        conversation_id = user_input.conversation_id or ""

        _LOGGER.debug(
            "Processing conversation: %s (id=%s)",
            user_input.text,
            conversation_id,
        )

        try:
            response_text = await self._bridge.async_send_conversation(
                text=user_input.text,
                conversation_id=conversation_id or None,
            )
        except TimeoutError:
            response_text = (
                "Sorry, Claude didn't respond in time. "
                "Make sure the BRUH Claude Terminal add-on is running."
            )
        except Exception:
            _LOGGER.exception("Error communicating with Claude add-on")
            response_text = (
                "Sorry, something went wrong communicating with the "
                "Claude Terminal add-on."
            )

        response = intent.IntentResponse(language=user_input.language)
        response.async_set_speech(response_text)
        return ConversationResult(
            response=response,
            conversation_id=conversation_id,
        )
