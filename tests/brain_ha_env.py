"""Just enough Home Assistant to import and DRIVE the brain integration.

The integration's own modules are loaded for real — `__init__.py` with its
service handlers, `conversation.py` with its entity, `bridge.py`,
`power_tools.py` — behind stubs for the parts of Home Assistant they
import. Two rules make the stubs honest:

  * what the code under test BRANCHES on is a real class here, never a
    MagicMock: the exceptions it raises and catches, the intent response
    it fills in, the conversation result it builds, the registries it
    reads. A mock answers every question with "yes", which is how a test
    passes against the bug it was written for.
  * what it merely imports and never asks about (a schema helper, a
    dispatcher) is an auto-module, so a new import in the integration does
    not break every test that loads it.

And sys.modules is put back exactly as it was found when the load is
done: several test modules install partial `homeassistant` stubs, and the
first to load would otherwise win a shared table (the power-tools device
cycle test's rule). The loaded package keeps references to the stubs it
imported, which is all it needs.
"""
from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import sys
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock

REPO = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = REPO / "brain" / "custom_components" / "brain"


# ---------------------------------------------------------------------------
# The real classes
# ---------------------------------------------------------------------------


class HomeAssistantError(Exception):
    pass


class Unauthorized(HomeAssistantError):
    def __init__(self, context=None, user_id=None, **kwargs):
        super().__init__("Unauthorized")
        self.context = context
        self.user_id = user_id


class UnknownUser(Unauthorized):
    pass


class ServiceValidationError(HomeAssistantError):
    pass


class Context:
    def __init__(self, user_id=None):
        self.user_id = user_id
        self.id = uuid.uuid4().hex


class IntentResponseErrorCode:
    UNKNOWN = "unknown"
    FAILED_TO_HANDLE = "failed_to_handle"


class IntentResponse:
    def __init__(self, language=None):
        self.language = language
        self.speech = None
        self.error = None

    def async_set_speech(self, text):
        self.speech = text

    def async_set_error(self, code, message):
        self.error = (code, message)


class ConversationEntity:
    hass = None
    entity_id = None


def make_result_class(continues: bool):
    if continues:
        @dataclasses.dataclass
        class ConversationResult:
            response: object
            conversation_id: str | None = None
            continue_conversation: bool = False
    else:
        @dataclasses.dataclass
        class ConversationResult:
            response: object
            conversation_id: str | None = None
    return ConversationResult


class _AutoModule(types.ModuleType):
    """Every attribute exists, as a mock: for what is imported and not asked.

    Except the names in `missing`, which raise — so a `from … import` of a
    helper this core is too old to have fails the way it would there."""

    missing: frozenset = frozenset()

    def __getattr__(self, name):
        if name.startswith("__") or name in self.missing:
            raise AttributeError(name)
        stub = MagicMock(name=f"{self.__name__}.{name}")
        setattr(self, name, stub)
        return stub


# ---------------------------------------------------------------------------
# Registries the conversation entity reads
# ---------------------------------------------------------------------------


def _registry_module(name: str, kind: str):
    mod = types.ModuleType(name)
    mod.async_get = lambda hass: hass.registries[kind]
    return mod


class EntityRegistry:
    def __init__(self, entries=None):
        self.entries = entries or {}

    def async_get(self, entity_id):
        return self.entries.get(entity_id)


class DeviceRegistry:
    def __init__(self, devices=None):
        self.devices = devices or {}

    def async_get(self, device_id):
        return self.devices.get(device_id)


class AreaRegistry:
    def __init__(self, areas=None):
        self.areas = areas or {}

    def async_get_area(self, area_id):
        return self.areas.get(area_id)


class FloorRegistry:
    def __init__(self, floors=None):
        self.floors = floors or {}

    def async_get_floor(self, floor_id):
        return self.floors.get(floor_id)


# ---------------------------------------------------------------------------
# Installing them
# ---------------------------------------------------------------------------


def _stubs(*, chat_log: bool, continues: bool, floors: bool) -> dict:
    mods: dict = {}

    def auto(name):
        mods[name] = _AutoModule(name)
        return mods[name]

    for name in ("voluptuous", "homeassistant", "homeassistant.config_entries",
                 "homeassistant.const", "homeassistant.helpers",
                 "homeassistant.helpers.config_validation",
                 "homeassistant.helpers.issue_registry",
                 "homeassistant.helpers.dispatcher",
                 "homeassistant.helpers.event",
                 "homeassistant.helpers.template",
                 "homeassistant.helpers.entity_platform",
                 "homeassistant.helpers.aiohttp_client",
                 "homeassistant.helpers.label_registry",
                 "homeassistant.util", "homeassistant.components"):
        auto(name)

    core = types.ModuleType("homeassistant.core")
    core.HomeAssistant = object
    core.ServiceCall = object
    core.Event = object
    core.Context = Context
    core.callback = lambda func: func
    core.SupportsResponse = types.SimpleNamespace(
        NONE="none", OPTIONAL="optional", ONLY="only")
    mods["homeassistant.core"] = core

    exc = types.ModuleType("homeassistant.exceptions")
    exc.HomeAssistantError = HomeAssistantError
    exc.Unauthorized = Unauthorized
    exc.UnknownUser = UnknownUser
    exc.ServiceValidationError = ServiceValidationError
    mods["homeassistant.exceptions"] = exc

    helpers = mods["homeassistant.helpers"]
    intent = types.ModuleType("homeassistant.helpers.intent")
    intent.IntentResponse = IntentResponse
    intent.IntentResponseErrorCode = IntentResponseErrorCode
    mods["homeassistant.helpers.intent"] = intent
    helpers.intent = intent

    for short, kind in (("area_registry", "area"), ("device_registry", "device"),
                        ("entity_registry", "entity")):
        mod = _registry_module(f"homeassistant.helpers.{short}", kind)
        mods[mod.__name__] = mod
        setattr(helpers, short, mod)
    mods["homeassistant.helpers.device_registry"].DeviceInfo = \
        lambda **kw: dict(kw)
    if floors:
        mod = _registry_module("homeassistant.helpers.floor_registry", "floor")
        mods[mod.__name__] = mod
        helpers.floor_registry = mod
    else:
        # A core before floors: the import has to FAIL, not hand back a mock.
        helpers.missing = helpers.missing | {"floor_registry"}
        mods["homeassistant.helpers.floor_registry"] = None
    for name in ("issue_registry", "config_validation", "dispatcher", "event",
                 "template", "entity_platform", "label_registry"):
        setattr(helpers, name, mods[f"homeassistant.helpers.{name}"])

    conv = types.ModuleType("homeassistant.components.conversation")
    conv.ConversationEntity = ConversationEntity
    conv.ConversationInput = object
    conv.ConversationResult = make_result_class(continues)
    conv.ConversationEntityFeature = types.SimpleNamespace(CONTROL=1)
    mods[conv.__name__] = conv
    if chat_log:
        conv.async_get_chat_log = lambda hass, session, user_input: \
            hass.chat_log_for(session, user_input)
        chat_session = types.ModuleType("homeassistant.helpers.chat_session")
        chat_session.async_get_chat_session = \
            lambda hass, conversation_id: hass.chat_session_for(conversation_id)
        mods[chat_session.__name__] = chat_session
        helpers.chat_session = chat_session
    else:
        helpers.missing = helpers.missing | {"chat_session"}
        mods["homeassistant.helpers.chat_session"] = None
    return mods


def load_integration(*, chat_log: bool = False, continues: bool = True,
                     floors: bool = True):
    """The brain package, loaded under a unique name, plus its submodules
    as attributes: ``pkg``, ``pkg.conversation``, ``pkg.bridge``…"""
    stubs = _stubs(chat_log=chat_log, continues=continues, floors=floors)
    saved = dict(sys.modules)
    pkg_name = f"brain_ha_{uuid.uuid4().hex[:10]}"
    try:
        # A name mapped to None makes its import raise ImportError, which
        # is the "this core predates it" answer.
        sys.modules.update(stubs)
        spec = importlib.util.spec_from_file_location(
            pkg_name, INTEGRATION_DIR / "__init__.py",
            submodule_search_locations=[str(INTEGRATION_DIR)])
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = pkg
        spec.loader.exec_module(pkg)
        for sub in ("conversation", "bridge", "requests", "learning",
                    "power_tools", "findings", "const"):
            setattr(pkg, sub, importlib.import_module(f"{pkg_name}.{sub}"))
        return pkg
    finally:
        # The package's own modules stay importable under their unique name,
        # because several handlers import a sibling at call time
        # (`from .requests import …`); everything else is put back.
        own = {k: v for k, v in sys.modules.items()
               if k == pkg_name or k.startswith(pkg_name + ".")}
        sys.modules.clear()
        sys.modules.update(saved)
        sys.modules.update(own)
