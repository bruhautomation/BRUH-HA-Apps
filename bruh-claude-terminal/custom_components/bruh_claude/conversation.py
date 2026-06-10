"""Conversation agent for BRUH Claude.

Registers a ConversationEntity for each config entry so that multiple
personality agents can appear under Settings > Voice Assistants.
"""

from __future__ import annotations

import asyncio
import logging

from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.components.conversation import ConversationEntityFeature

    SUPPORTS_CONTROL = ConversationEntityFeature.CONTROL
except (ImportError, AttributeError):
    # CONTROL = 1 in HA 2024.2+. Hardcode the value so the agent always
    # declares device-control support, even on HA versions where the enum
    # doesn't exist yet (where the flag is simply ignored).
    SUPPORTS_CONTROL = 1

from .const import CONF_MODEL, CONF_NAME, CONF_SYSTEM_PROMPT, DEFAULT_MODEL, DEFAULT_NAME, DOMAIN

# Chat-log streaming (HA 2025.x): when available and the add-on publishes
# its HTTP API, deltas stream into the chat log so TTS can start speaking at
# the first sentence. Every piece is feature-detected; any failure falls
# back to the classic whole-reply flow.
try:
    from homeassistant.components.conversation import async_get_chat_log
    from homeassistant.helpers import chat_session

    _CHAT_LOG_AVAILABLE = True
except ImportError:
    _CHAT_LOG_AVAILABLE = False

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
    _attr_icon = "mdi:creation"

    def __init__(self, config_entry: ConfigEntry, bridge) -> None:
        self._bridge = bridge
        # Options (from the options flow) override the original data values
        opts = {**config_entry.data, **config_entry.options}
        self._system_prompt = opts.get(CONF_SYSTEM_PROMPT, "")
        self._model = opts.get(CONF_MODEL, DEFAULT_MODEL)
        name = config_entry.data.get(CONF_NAME, DEFAULT_NAME)
        self._attr_name = "Agent"  # Short — the device name provides context
        self._attr_unique_id = f"{config_entry.entry_id}_conversation"

        # Give each conversation agent its own device so it appears as a
        # distinct card in Settings > Devices, separate from the usage sensors.
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"agent_{config_entry.entry_id}")},
            name=name,
            manufacturer="BRUH Automation",
            model="Claude Conversation Agent",
        )

    @property
    def supported_languages(self) -> list[str] | str:
        """Claude handles all languages."""
        return "*"

    async def async_process(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Process a conversation turn by forwarding to the Claude app.

        Prefers the streaming chat-log path (modern HA + add-on HTTP API);
        any failure there falls back to the classic file-bridge flow.
        """
        if _CHAT_LOG_AVAILABLE:
            try:
                return await self._process_streaming(user_input)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                # Only chat-session/chat-log SETUP can raise here —
                # _process_streaming handles everything after the bridge
                # task starts, so this fallback can never re-send a command.
                _LOGGER.exception(
                    "Chat-log setup failed — falling back to classic flow"
                )
        return await self._process_classic(user_input)

    async def _process_streaming(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Stream deltas into the chat log while the turn runs."""
        with (
            chat_session.async_get_chat_session(
                self.hass, user_input.conversation_id
            ) as session,
            async_get_chat_log(self.hass, session, user_input) as chat_log,
        ):
            queue: asyncio.Queue = asyncio.Queue()
            done = object()

            def on_delta(text: str) -> None:
                queue.put_nowait(text)

            task = self.hass.async_create_task(
                self._bridge.async_send_conversation_streaming(
                    text=user_input.text,
                    conversation_id=chat_log.conversation_id,
                    system_prompt=self._system_prompt or None,
                    model=self._model if self._model != "default" else None,
                    delta_listener=on_delta,
                )
            )
            task.add_done_callback(lambda _t: queue.put_nowait(done))

            agent_id = getattr(user_input, "agent_id", None) or self.entity_id

            async def _stream():
                yield {"role": "assistant"}
                saw_delta = False
                while True:
                    item = await queue.get()
                    if item is done:
                        # No deltas (e.g. file fallback inside the bridge):
                        # emit the final text as a single chunk instead.
                        if not saw_delta and not task.exception():
                            text = task.result()
                            if text:
                                yield {"content": text}
                        break
                    saw_delta = True
                    yield {"content": item}

            # From here on the bridge task is in flight: chat-log plumbing
            # failures must NOT escape to the classic-resend fallback (the
            # command may already be executing). Degrade to plain result.
            try:
                async for _content in chat_log.async_add_delta_content_stream(
                    agent_id, _stream()
                ):
                    pass
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.exception("chat-log delta streaming failed mid-turn")

            try:
                response_text = await task
            except TimeoutError:
                response_text = (
                    "Sorry, Claude didn't respond in time. "
                    "Make sure the BRUH Claude Terminal app is running."
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                _LOGGER.exception("Conversation request failed")
                response_text = (
                    "Sorry, something went wrong communicating with the "
                    "Claude Terminal app."
                )

            response = intent.IntentResponse(language=user_input.language)
            response.async_set_speech(response_text)
            return ConversationResult(
                response=response,
                conversation_id=chat_log.conversation_id,
            )

    async def _process_classic(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Whole-reply flow over the file bridge (pre-3.0 behavior)."""
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
                model=self._model if self._model != "default" else None,
            )
        except TimeoutError:
            response_text = (
                "Sorry, Claude didn't respond in time. "
                "Make sure the BRUH Claude Terminal app is running."
            )
        except asyncio.CancelledError:
            # HA cancelled the pipeline (dialog closed, voice timeout).
            # Swallowing this breaks asyncio cancellation semantics — re-raise.
            _LOGGER.debug("Conversation cancelled for [%s]", conversation_id)
            raise
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
