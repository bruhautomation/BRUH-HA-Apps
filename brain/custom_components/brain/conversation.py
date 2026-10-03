"""Conversation agent for brAIn.

Registers a ConversationEntity for each config entry so that multiple
personality agents can appear under Settings > Voice Assistants.

What Home Assistant hands an agent beyond the words — the satellite or
device a request came from, the user who spoke, an automation's
`extra_system_prompt`, and a chat log holding whatever was said before
brAIn was asked — is resolved here into plain facts (a room, a floor, a
person) and sent to the add-on as the request's `context`, where it
becomes a short block in the TURN (scripts/brain_voice_context.py says why
the turn and not the system prompt). Until this did, "turn off the lights"
said to the kitchen satellite had no room to resolve against, a
`start_conversation` flow lost its question, and a non-admin login could
address a Full-admin agent and get a shell.

Everything Home Assistant added after this integration's 2023.6 floor is
feature-detected, and a lookup that fails is a request with less context,
never a request that fails.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging

from homeassistant.components.conversation import (
    ConversationEntity,
    ConversationInput,
    ConversationResult,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import intent
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

try:
    from homeassistant.components.conversation import ConversationEntityFeature

    SUPPORTS_CONTROL = ConversationEntityFeature.CONTROL
except (ImportError, AttributeError):
    # CONTROL = 1 in HA 2024.2+. Hardcode the value so the agent always
    # declares device-control support, even on HA versions where the enum
    # doesn't exist yet (where the flag is simply ignored).
    SUPPORTS_CONTROL = 1

try:
    from homeassistant.helpers import area_registry as ar
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er
except ImportError:  # pragma: no cover — present on every supported core
    ar = dr = er = None  # type: ignore[assignment]

try:
    # 2024.4+. Before it, a room has no floor and none is said.
    from homeassistant.helpers import floor_registry as fr
except ImportError:
    fr = None  # type: ignore[assignment]

from .bridge import BrainRunError
from .const import (
    ACCESS_ADMIN,
    ACCESS_HOUSE,
    ACCESS_LEVELS,
    ACCESS_VOICE,
    CONF_ACCESS,
    DEFAULT_ACCESS,
    CONF_DENIED_SERVICES,
    CONF_MODEL,
    CONF_NAME,
    CONF_SYSTEM_PROMPT,
    DEFAULT_MODEL,
    DEFAULT_NAME,
    DOMAIN,
)

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

# Whether this core's ConversationResult can say "keep listening" (2025.4+).
# Asked of the dataclass rather than of a version string, because a field
# is the thing being relied on.
try:
    _RESULT_CONTINUES = "continue_conversation" in {
        f.name for f in dataclasses.fields(ConversationResult)}
except TypeError:
    _RESULT_CONTINUES = False

# What a reply that asks something ends with. Home Assistant's own
# `ChatLog.continue_conversation` reads these three, so a satellite keeps
# its microphone open after brAIn's "Which bedroom?" exactly as it does
# after one of its own agents'.
QUESTION_ENDINGS = ("?", ";", "？")

# The levels a non-admin speaker may not be given. A conversation agent's
# reach is set on the agent, and HA lists every agent in every user's
# Assist picker and lets `conversation.process` name any of them — so
# without this a wall tablet's login could address a Full-admin agent and
# get a shell in /config. The agent answers such a speaker at the voice
# level instead (see `turn_access`).
WIDE_LEVELS = (ACCESS_HOUSE, ACCESS_ADMIN)

# How much of the chat log brAIn did not write rides along: the last few
# turns, each one line, since that is all a follow-up needs and a chat log
# can hold a whole afternoon.
PRIOR_TURNS = 6
PRIOR_CHARS = 300


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the brAIn conversation entity."""
    bridge = hass.data[DOMAIN][config_entry.entry_id]
    async_add_entities([BruhClaudeConversationEntity(config_entry, bridge)])


# ---------------------------------------------------------------------------
# Where and who — each lookup never raises
# ---------------------------------------------------------------------------


def describe_place(hass, device_id=None, satellite_id=None) -> dict:
    """`{area, floor, device}` for the device or satellite a request came
    from, as far as the registries say. Never raises.

    A satellite is an entity, and an entity's own area beats its device's
    (that is Home Assistant's rule, and it is what somebody set when they
    moved one satellite of a pair into another room). An area that cannot
    be found leaves the device name, which still says where to ask.
    """
    out: dict = {}
    if er is None or dr is None or ar is None:
        return out
    try:
        area_id = None
        if satellite_id:
            entry = er.async_get(hass).async_get(satellite_id)
            if entry is not None:
                area_id = entry.area_id
                device_id = device_id or entry.device_id
        if device_id:
            device = dr.async_get(hass).async_get(device_id)
            if device is not None:
                name = device.name_by_user or device.name
                if name:
                    out["device"] = str(name)
                area_id = area_id or device.area_id
        if not area_id:
            return out
        area = ar.async_get(hass).async_get_area(area_id)
        if area is None:
            return out
        out["area"] = str(area.name)
        floor_id = getattr(area, "floor_id", None)
        if floor_id and fr is not None:
            floor = fr.async_get(hass).async_get_floor(floor_id)
            if floor is not None:
                out["floor"] = str(floor.name)
    except Exception:  # noqa: BLE001 — a request with less context still answers
        _LOGGER.debug("could not resolve where a request came from",
                      exc_info=True)
    return out


async def describe_speaker(hass, user_id) -> dict:
    """`{speaker, person, admin}` for the Home Assistant user who spoke.

    `admin` is False for a user that cannot be found — the reading that
    narrows rather than widens — and absent for a request with no user at
    all, which is a satellite or an automation: the system, whose reach is
    the agent's own (HA's rule for its admin services). The person is the
    `person.*` entity whose `user_id` attribute is this user, which is the
    link Home Assistant itself keeps between the two.
    """
    if not user_id:
        return {}
    out: dict = {"admin": False}
    try:
        user = await hass.auth.async_get_user(user_id)
    except Exception:  # noqa: BLE001 — unreadable is not an admin
        _LOGGER.debug("could not read the speaking user", exc_info=True)
        return out
    if user is None:
        return out
    out["admin"] = bool(getattr(user, "is_admin", False))
    if getattr(user, "name", None):
        out["speaker"] = str(user.name)
    try:
        for state in hass.states.async_all("person"):
            if state.attributes.get("user_id") == user_id:
                out["person"] = state.entity_id
                out["speaker"] = str(state.name or out.get("speaker") or "")
                break
    except Exception:  # noqa: BLE001 — no person is a speaker with a name
        _LOGGER.debug("could not read the person entities", exc_info=True)
    return out


def turn_access(level: str, user_id, speaker: dict) -> tuple[str, str]:
    """`(level this turn runs at, the level it was narrowed from or "")`.

    A Whole-house or Full-admin agent addressed by a non-admin login runs
    the turn at the voice level. Narrowed rather than refused, because the
    voice level is exactly what Home Assistant's own Assist gives any
    signed-in user — so a household member using a house-level agent from
    the app still gets their lights, and gets nothing an admin's agent
    adds. A request with no user (a satellite, an automation) keeps the
    agent's own level: who may stand near a satellite is the decision the
    level already is.
    """
    if level in WIDE_LEVELS and user_id and not speaker.get("admin"):
        return ACCESS_VOICE, level
    return level, ""


def foreign_turns(chat_log, own_agent_id) -> list[dict]:
    """What the chat log holds that brAIn did not write, since it last spoke.

    `assist_satellite.start_conversation` writes its announcement into the
    chat log as an assistant turn under the satellite's id, and "prefer
    handling commands locally" puts a turn Home Assistant answered itself
    there too — neither reaches brAIn any other way, so the person's "yes"
    arrived with no idea what it was a yes to. The current request's own
    words are the log's last entry and are left out; a log brAIn has
    written into is read only after its own last reply, because what came
    before that is already in its session.
    """
    try:
        content = list(getattr(chat_log, "content", None) or [])
    except TypeError:
        return []
    if content and getattr(content[-1], "role", "") == "user":
        content = content[:-1]
    start = 0
    for index, item in enumerate(content):
        if getattr(item, "role", "") == "assistant" and \
                getattr(item, "agent_id", None) == own_agent_id:
            start = index + 1
    out = []
    for item in content[start:]:
        role = getattr(item, "role", "")
        text = getattr(item, "content", None)
        if role not in ("user", "assistant") or not isinstance(text, str):
            continue
        text = " ".join(text.split())
        if text:
            out.append({"role": role, "text": text[:PRIOR_CHARS]})
    return out[-PRIOR_TURNS:]


def wants_reply(text) -> bool:
    """Whether a reply asks something, by Home Assistant's own test."""
    return isinstance(text, str) and text.strip().endswith(QUESTION_ENDINGS)


def build_result(response, conversation_id, continue_conversation=False):
    """A ConversationResult, keeping the satellite listening where this
    core can be told to. Never names a field the core does not have."""
    kwargs = {"response": response, "conversation_id": conversation_id}
    if _RESULT_CONTINUES:
        kwargs["continue_conversation"] = bool(continue_conversation)
    return ConversationResult(**kwargs)


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
        self._denied_services = opts.get(CONF_DENIED_SERVICES) or []
        # What this agent may reach. Missing (or the retired "follow the
        # add-on") means it never chose, which is the narrowest level.
        access = opts.get(CONF_ACCESS)
        self._access = access if access in ACCESS_LEVELS else DEFAULT_ACCESS
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

    async def _turn(self, user_input, chat_log=None, agent_id=None) -> tuple[dict, str]:
        """`(context, access)` for one turn: where, who, what came before.

        Context is the add-on's to word (`brain_voice_context`); this only
        resolves ids into names and decides the level the turn runs at.
        """
        context: dict = describe_place(
            self.hass, getattr(user_input, "device_id", None),
            getattr(user_input, "satellite_id", None))
        user_id = getattr(getattr(user_input, "context", None), "user_id", None)
        speaker = await describe_speaker(self.hass, user_id)
        for key in ("speaker", "person"):
            if speaker.get(key):
                context[key] = speaker[key]
        access, narrowed = turn_access(self._access, user_id, speaker)
        if narrowed:
            context["narrowed_from"] = narrowed
            _LOGGER.info(
                "%s is set to %s and was asked by a user who is not an "
                "admin — answering at the voice level", self.entity_id,
                narrowed)
        extra = getattr(user_input, "extra_system_prompt", None) or \
            getattr(chat_log, "extra_system_prompt", None)
        if isinstance(extra, str) and extra.strip():
            context["extra_system_prompt"] = extra.strip()
        if chat_log is not None:
            prior = foreign_turns(chat_log, agent_id)
            if prior:
                context["prior"] = prior
        language = getattr(user_input, "language", None)
        if language and language != "*":
            context["language"] = language
        return context, access

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

            agent_id = getattr(user_input, "agent_id", None) or self.entity_id
            context, access = await self._turn(user_input, chat_log, agent_id)

            task = self.hass.async_create_task(
                self._bridge.async_send_conversation_streaming(
                    text=user_input.text,
                    conversation_id=chat_log.conversation_id,
                    system_prompt=self._system_prompt or None,
                    model=self._model if self._model != "default" else None,
                    delta_listener=on_delta,
                    denied_services=self._denied_services or None,
                    access=access,
                    context=context or None,
                )
            )
            task.add_done_callback(lambda _t: queue.put_nowait(done))

            async def _stream():
                yield {"role": "assistant"}
                streamed: list[str] = []
                while True:
                    item = await queue.get()
                    if item is done:
                        # The final text, where what was streamed does not
                        # already end with it: no deltas at all (the file
                        # fallback inside the bridge), or deltas from an
                        # attempt that died before the answer that was
                        # spoken. Either way the chat log ends on what the
                        # person heard. A failure writes nothing here — its
                        # sentence is the error response's.
                        if not task.cancelled() and not task.exception():
                            text = task.result() or ""
                            sofar = "".join(streamed).rstrip()
                            if text and not sofar.endswith(text.strip()):
                                yield {"content": ("\n\n" if sofar else "") + text}
                        break
                    streamed.append(item)
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

            response = intent.IntentResponse(language=user_input.language)
            response_text = await self._answer(task, response)
            follow_up = response_text is not None and (
                wants_reply(response_text)
                or bool(getattr(chat_log, "continue_conversation", False)))
            return build_result(response, chat_log.conversation_id, follow_up)

    async def _answer(self, waiting, response) -> str | None:
        """Set the speech for an answer or the error for a failure.

        Returns the answer's text, or None for a failure. A failure is an
        ERROR response rather than speech, so Home Assistant's pipeline can
        tell it from an answer — the sentence is the same either way, and
        it is what the person hears.
        """
        code = intent.IntentResponseErrorCode.UNKNOWN
        try:
            text = await waiting
        except BrainRunError as exc:
            response.async_set_error(code, exc.text or "Sorry, that failed.")
            return None
        except TimeoutError:
            response.async_set_error(
                code, "Sorry, Claude didn't respond in time. "
                "Make sure the brAIn app is running.")
            return None
        except asyncio.CancelledError:
            # HA cancelled the pipeline (dialog closed, voice timeout).
            # Swallowing this breaks asyncio cancellation semantics.
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Conversation request failed")
            response.async_set_error(
                code, "Sorry, something went wrong communicating with the "
                "brAIn app.")
            return None
        response.async_set_speech(text)
        return text

    async def _process_classic(
        self, user_input: ConversationInput
    ) -> ConversationResult:
        """Whole-reply flow over the file bridge (pre-3.0 behavior).

        The conversation id is minted HERE when the caller sent none, and
        that is the id returned: the bridge records history under the id it
        is given, so returning the caller's `None` meant the next turn sent
        `None` again, got a fresh id, and the conversation never continued
        — on exactly the cores old enough to have no chat log.
        """
        conversation_id = user_input.conversation_id or _new_conversation_id()

        _LOGGER.debug(
            "Processing conversation [%s]: %s (id=%s)",
            self._attr_name,
            user_input.text,
            conversation_id,
        )

        context, access = await self._turn(user_input)
        response = intent.IntentResponse(language=user_input.language)
        response_text = await self._answer(
            self._bridge.async_send_conversation(
                text=user_input.text,
                conversation_id=conversation_id,
                system_prompt=self._system_prompt or None,
                model=self._model if self._model != "default" else None,
                denied_services=self._denied_services or None,
                access=access,
                context=context or None,
            ),
            response,
        )
        return build_result(response, conversation_id,
                            response_text is not None
                            and wants_reply(response_text))


def _new_conversation_id() -> str:
    """A conversation id in Home Assistant's own format where it has one."""
    try:
        from homeassistant.util.ulid import ulid_now  # noqa: PLC0415

        return ulid_now()
    except Exception:  # noqa: BLE001 — any unique string serves
        import uuid  # noqa: PLC0415

        return uuid.uuid4().hex
