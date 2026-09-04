"""BRUH Print integration entry point.

Registers:
* sensors reading the add-on's state mirror (printer, each roll, last print)
* the print services, forwarded to the add-on over the file bridge
* the Lovelace card as a frontend resource, so it appears in the card picker
  without anybody editing dashboard resources by hand
"""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_call_later

from .bridge import send_request
from .const import (
    CARD_FILE,
    CARD_RETRY_CANCEL,
    CARD_RETRY_SECONDS,
    CARD_RETRY_TRIES,
    DOCS_URL,
    DOMAIN,
    ISSUE_LOCAL_NOT_SERVED,
    LOCAL_PATH,
    SERVICE_PRINT_LABEL,
    SERVICE_PRINT_TEMPLATE,
    SERVICE_PRINT_TEST,
    SERVICE_PRINT_TEXT,
    SERVICE_REPRINT,
    SERVICE_SET_ROLL,
    card_url,
)
from .coordinator import BruhPrintCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

# `side` is no longer offered anywhere — not in services.yaml, not on the
# panel, not on the card. Which bay a label prints on is not a decision
# worth asking anybody to make: the add-on knows which roll holds which
# stock, so naming the stock has already named the bay, and two ways to say
# it is one way to contradict the other.
#
# The schemas below still ACCEPT it, deliberately and quietly. An automation
# written against 0.1.2 has `side: left` in it, and a field vanishing from a
# schema turns that into a validation error on a working automation — a
# worse outcome than an argument nobody is offered. It is honoured exactly
# as before; nothing suggests it.
SIDES = vol.In(["", "left", "right"])
COPIES = vol.All(vol.Coerce(int), vol.Range(min=1, max=500))

PRINT_TEXT_SCHEMA = vol.Schema({
    vol.Required("text"): cv.string,
    vol.Optional("stock"): cv.string,
    vol.Optional("side"): SIDES,
    vol.Optional("copies"): COPIES,
    vol.Optional("font"): cv.string,
    vol.Optional("rotate"): vol.In([0, 90, 180, 270]),
    vol.Optional("uppercase"): cv.boolean,
})

PRINT_TEMPLATE_SCHEMA = vol.Schema({
    vol.Required("template"): cv.string,
    vol.Optional("fields"): dict,
    vol.Optional("side"): SIDES,
    vol.Optional("copies"): COPIES,
})

PRINT_LABEL_SCHEMA = vol.Schema({
    vol.Required("label"): dict,
    vol.Optional("side"): SIDES,
    vol.Optional("copies"): COPIES,
})

REPRINT_SCHEMA = vol.Schema({
    vol.Optional("entry"): cv.string,
    vol.Optional("copies"): COPIES,
    vol.Optional("side"): SIDES,
})

SET_ROLL_SCHEMA = vol.Schema({
    vol.Required("side"): vol.In(["left", "right"]),
    vol.Required("stock"): cv.string,
    vol.Optional("remaining"): vol.All(vol.Coerce(int), vol.Range(min=0)),
})

PRINT_TEST_SCHEMA = vol.Schema({
    vol.Optional("stock"): cv.string,
    vol.Optional("side"): SIDES,
})

SERVICES = {
    SERVICE_PRINT_TEXT: PRINT_TEXT_SCHEMA,
    SERVICE_PRINT_TEMPLATE: PRINT_TEMPLATE_SCHEMA,
    SERVICE_PRINT_LABEL: PRINT_LABEL_SCHEMA,
    SERVICE_REPRINT: REPRINT_SCHEMA,
    SERVICE_SET_ROLL: SET_ROLL_SCHEMA,
    SERVICE_PRINT_TEST: PRINT_TEST_SCHEMA,
}


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    hass.data.setdefault(DOMAIN, {})
    _register_services(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = BruhPrintCoordinator(hass)
    await coordinator.async_config_entry_first_refresh()
    hass.data[DOMAIN][entry.entry_id] = coordinator
    await _register_card(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        _cancel_card_retry(hass)
    return unloaded


def _cancel_card_retry(hass: HomeAssistant) -> None:
    """Stop a pending look for the card file.

    A timer that outlives the entry that scheduled it fires into a
    half-unloaded integration and registers a resource nobody asked for, so
    the cancel callable is kept where it can be found again rather than in a
    closure nothing holds.
    """
    cancel = hass.data.get(DOMAIN, {}).pop(CARD_RETRY_CANCEL, None)
    if cancel is not None:
        cancel()


async def _register_card(hass: HomeAssistant, tries: int = 0) -> None:
    """Put the Lovelace card in front of the dashboard picker.

    `add_extra_js_url` rather than writing a resource row into .storage: it
    works in storage mode and YAML mode alike, needs no restart, and cannot
    corrupt somebody's dashboard config. The cost is that the card is loaded
    on every dashboard rather than only where it is used, which for one small
    file is the right trade.

    The URL carries a hash of the file (`card_url`), because /local is served
    with a 31-day cache header and the add-on updates the card in place —
    without it an update reaches nobody until they clear their browser cache.

    The file's existence is still checked first, because registering a URL
    that 404s puts a red error in everybody's browser console on every page
    load, about a feature they may have turned off. But it is checked
    *again*: Core can set this entry up before the add-on has copied the card
    in — a first install, or an add-on update while Core was already
    running — and a one-shot check there means no card until the next
    restart of Core, which is a long way to go for a file that arrives forty
    seconds later.
    """
    def _url() -> str | None:
        return card_url(CARD_FILE) if CARD_FILE.is_file() else None

    url = await hass.async_add_executor_job(_url)
    if url is None:
        _LOGGER.debug("Lovelace card not at %s yet (attempt %d of %d)",
                      CARD_FILE, tries + 1, CARD_RETRY_TRIES)
        _schedule_card_retry(hass, tries)
        return
    try:
        from homeassistant.components.frontend import add_extra_js_url
    except ImportError:  # pragma: no cover - frontend is always there in core
        return
    add_extra_js_url(hass, url)
    _sync_local_issue(hass)
    if tries:
        # Worth a line at info: somebody whose card appeared four minutes
        # after Home Assistant started should be able to see why.
        _LOGGER.info("Registered the BRUH Print card at %s", url)
    else:
        _LOGGER.debug("Registered the BRUH Print card at %s", url)


def _local_is_served(hass: HomeAssistant) -> bool:
    """Is Home Assistant actually serving the folder the card is in?

    It decides that once, while it is starting, and only if the folder is
    already there — this is core's own frontend setup, verbatim:

        local = hass.config.path("www")
        if await hass.async_add_executor_job(os.path.isdir, local):
            static_paths_configs.append(StaticPathConfig("/local", local, ...))

    BRUH Print's run.sh creates /config/www/bruh_print when the ADD-ON
    starts, which on any ordinary install is after Home Assistant started.
    So on a house that had no /config/www at all — and you only have one if
    you have already installed a custom card or HACS — /local is not a route
    on this run, every request for the card is a 404, and the dashboard says
    "Custom element doesn't exist: bruh-print-card". Restarting the add-on
    cannot fix that; only restarting Home Assistant can, and then only once.

    Asked of the running app's own router rather than by fetching the URL.
    A request has to guess a base URL, cross the network stack and a proxy,
    and can fail for half a dozen reasons that are not the question — the
    same reasoning BRight's playback check follows: walk the links, do not
    infer them.

    It FAILS OPEN. This is a diagnosis and never a gate: an answer it cannot
    get means "assume it is served", because being wrong that way costs
    nothing and being wrong the other way nags a house whose card works.
    """
    try:
        routes = [getattr(resource, "canonical", None)
                  for resource in hass.http.app.router.resources()]
    except Exception:  # noqa: BLE001 - a diagnosis may not fail a setup
        _LOGGER.debug("Could not ask the router whether %s is served",
                      LOCAL_PATH, exc_info=True)
        return True
    if not routes:
        # A router with nothing on it is not a Home Assistant serving
        # nothing; it is the question asked somewhere it cannot be
        # answered. Same rule as a house check that could not look.
        _LOGGER.debug("The router listed no routes at all; taking %s as served",
                      LOCAL_PATH)
        return True
    return LOCAL_PATH in routes


@callback
def _sync_local_issue(hass: HomeAssistant) -> bool:
    """Raise the one-restart repair, or take it away once it is done.

    The card is registered either way — the URL it is registered at works
    the moment Home Assistant restarts, and refusing to register would leave
    a repair nothing could clear. This only says so where somebody looks:
    the card being missing is otherwise invisible from every surface the
    add-on has, and the message Home Assistant shows in its place blames
    the card.

    Deleted again the next time the check passes, so a house that has
    restarted stops being told to.
    """
    served = _local_is_served(hass)
    if served:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_LOCAL_NOT_SERVED)
        return True
    ir.async_create_issue(
        hass,
        DOMAIN,
        ISSUE_LOCAL_NOT_SERVED,
        is_fixable=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_LOCAL_NOT_SERVED,
        learn_more_url=DOCS_URL,
    )
    return False


def _schedule_card_retry(hass: HomeAssistant, tries: int) -> None:
    """Look again in a while, a bounded number of times.

    Bounded because `install_lovelace_card: false` is a real answer, and a
    timer that never stops asking about a file the user has switched off is
    the same mistake as registering a URL that 404s, one layer quieter.
    """
    _cancel_card_retry(hass)
    if tries + 1 >= CARD_RETRY_TRIES:
        _LOGGER.debug("Giving up on the Lovelace card at %s; the add-on may "
                      "have install_lovelace_card turned off", CARD_FILE)
        return

    @callback
    def _look_again(_now) -> None:
        hass.data.get(DOMAIN, {}).pop(CARD_RETRY_CANCEL, None)
        hass.async_create_task(_register_card(hass, tries + 1))

    hass.data.setdefault(DOMAIN, {})[CARD_RETRY_CANCEL] = async_call_later(
        hass, CARD_RETRY_SECONDS, _look_again)


async def _forward(kind: str, data: dict) -> dict:
    """Send one request and make the add-on's answer the caller's.

    A dropped answer is a green tick and no label. The add-on's refusals are
    the useful kind — "the left roll holds Cryogenic Labels and this label is
    for Chemical-Resistant Cryo Labels" — and a `HomeAssistantError` is what
    puts that sentence in the automation trace and the UI's red toast rather
    than in a log nobody is reading.
    """
    try:
        response = await send_request(kind, data)
    except TimeoutError as exc:
        raise HomeAssistantError(str(exc)) from exc
    except OSError as exc:
        raise HomeAssistantError(
            f"BRUH Print could not be reached: {exc}. The add-on and Home "
            f"Assistant share a folder under /config, so this usually means "
            f"the add-on is stopped."
        ) from exc
    if isinstance(response, dict) and response.get("ok") is False:
        raise HomeAssistantError(
            str(response.get("error") or f"BRUH Print refused {kind}"))
    return response if isinstance(response, dict) else {}


def _register_services(hass: HomeAssistant) -> None:
    def make(kind: str):
        async def handler(call: ServiceCall) -> dict:
            result = await _forward(kind, dict(call.data))
            # Response data, so a script can branch on which roll it landed
            # on or how many came out — and so `print_text` in the developer
            # tools shows something rather than a bare "success".
            return {
                "printed": result.get("printed", 0),
                "side": result.get("side", ""),
                "notes": result.get("notes", []),
                "status": result.get("status", ""),
            }
        return handler

    for name, schema in SERVICES.items():
        if hass.services.has_service(DOMAIN, name):
            continue
        hass.services.async_register(
            DOMAIN, name, make(name), schema=schema,
            supports_response=SupportsResponse.OPTIONAL)
