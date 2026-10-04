"""brAIn integration for Home Assistant.

Provides:
- A conversation agent ("brAIn") selectable in Settings > Voice Assistants
- Usage limit sensors for Anthropic account data
- brain.send_prompt          — send a one-shot prompt to Claude
- brain.run_task             — run a Claude task with optional notification
- brain.clear_conversation   — clear a persistent conversation session
- brain.add_memory           — queue a fact for the home memory store
- brain.answer_question      — answer one of brAIn's open guesses yes or no
- BRUH Power Tools                 — 65 registry-management admin services
  (areas, floors, labels, entities, devices, integrations, helpers, zones,
  persons, blueprints, statistics, users, diagnostics, dashboards, repairs)
  — see power_tools.py

Both conversation agent and sensors are independently toggleable per config entry.
"""

from __future__ import annotations

import json
import logging
import os
import time
from functools import partial

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import (
    async_call_later,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.template import Template
from homeassistant.util import dt as dt_util
from datetime import timedelta

try:
    from homeassistant.core import SupportsResponse
except ImportError:
    SupportsResponse = None  # type: ignore[assignment,misc]

try:
    # 2023.11+. Before it, a bad argument is an ordinary HomeAssistantError,
    # which still puts the sentence in the trace — the class only changes
    # how the frontend colours it.
    from homeassistant.exceptions import ServiceValidationError
except ImportError:
    ServiceValidationError = HomeAssistantError  # type: ignore[assignment,misc]

from .bridge import BrainRunError, ClaudeBridge
from .findings import FindingsWatcher
from .learning import LearningWatcher, read_open_hypotheses
from .requests import parse_action as parse_notification_action
from .requests import write_request as write_finding_request
from .const import (
    CONF_ENABLE_CONVERSATION,
    CONF_ENABLE_SENSORS,
    CONF_ENTRY_TYPE,
    CONF_INSIGHT_DAILY_AT,
    CONF_INSIGHT_INTERVAL,
    CONF_INSIGHT_NOTIFY,
    CONF_INSIGHT_PROMPT,
    CONF_INSIGHT_TEMPLATE,
    CONF_MODEL,
    CONF_SYSTEM_PROMPT,
    CONF_TIMEOUT,
    DEFAULT_INSIGHT_TIMEOUT,
    DEFAULT_MODEL,
    DEFAULT_SYSTEM_PROMPT,
    DEFAULT_TIMEOUT,
    DOMAIN,
    ENTRY_TYPE_AGENT,
    ENTRY_TYPE_INSIGHT,
    EVENT_INSIGHT_COMPLETE,
    EVENT_MOBILE_ACTION,
    INSIGHTS_DIR,
    MEMORY_DIR,
    MEMORY_INBOX_DIR,
    SHARED_DIR,
    SIGNAL_INSIGHT_UPDATE,
    STUDY_REQUESTS_DIR,
)
from .insight_format import (
    CAMERA_TEMPLATES,
    INSIGHT_TEMPLATES,
    build_card_yaml,
    make_preview,
    truncate_markdown,
)
from .power_tools import (
    POWER_TOOL_SERVICES,
    async_register_power_tools,
    async_require_admin,
)

_LOGGER = logging.getLogger(__name__)

# Capture the manifest version at import time so we know which version of the
# code is actually loaded in memory.  The on-disk manifest.json may be
# overwritten by the add-on before _check_restart_required runs, so reading
# it later would give the *new* version instead of the *running* version.
_LOADED_VERSION: str = "unknown"
try:
    with open(os.path.join(os.path.dirname(__file__), "manifest.json")) as _fh:
        _LOADED_VERSION = json.load(_fh).get("version", "unknown")
except (OSError, json.JSONDecodeError):
    # No manifest, or one we cannot parse, leaves the version "unknown" —
    # which is exactly what the restart check treats as "cannot tell".
    pass

SEND_PROMPT_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): str,
        vol.Optional("timeout"): vol.All(int, vol.Range(min=10, max=600)),
        vol.Optional("model"): str,
    }
)

# How much of the project grant one task may reach. A task runs in /config
# with `/config/.claude/settings.local.json` behind it, which holds Bash,
# Write, Edit, WebFetch, WebSearch and every MCP tool — and until this
# field existed, every `brain.run_task` call got all of it whatever it was
# asked to do, with no way for the automation that asked to say otherwise.
#
# `full` is the default and stays one — every automation written against
# this service asked for it by not asking — but it is no longer the reason
# BRight works: BRight's director writes its task files straight into the
# folder and never calls this service, so what the SERVICE grants and who
# may call it are decided here alone. The two narrower values are opt-in,
# and the listener derives both from the panel's own analyst lists rather
# than from a copy kept here.
TASK_TOOLS = ("full", "house", "read_only")
DEFAULT_TASK_TOOLS = "full"
# What a non-admin caller may ask for. `house` acts on the house through
# the Supervisor's token, which is an admin's reach whatever the caller's
# own account is, and `full` is a shell in /config; `read_only` is the
# analyst's own list and changes nothing. See `_require_admin_for`.
NON_ADMIN_TOOLS = ("read_only",)

RUN_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): str,
        vol.Optional("notify", default=False): bool,
        vol.Optional("notify_entity"): str,
        vol.Optional("timeout"): vol.All(int, vol.Range(min=10, max=600)),
        vol.Optional("tools", default=DEFAULT_TASK_TOOLS): vol.In(TASK_TOOLS),
        # Offered in services.yaml since the selector was written and
        # refused here until now — a valid-looking UI choice that failed
        # the call with "extra keys not allowed".
        vol.Optional("model"): str,
    }
)

CLEAR_CONVERSATION_SCHEMA = vol.Schema(
    {
        vol.Optional("conversation_id"): str,
    }
)

RUN_INSIGHT_SCHEMA = vol.Schema(
    {
        vol.Optional("name"): str,
    }
)

ADD_MEMORY_SCHEMA = vol.Schema(
    {
        vol.Required("fact"): vol.All(str, vol.Length(min=1)),
        vol.Optional("source", default="service"): str,
        vol.Optional("confidence", default="medium"): vol.In(
            ["high", "medium", "low"]
        ),
    }
)

# Which guess, and yes or no. `ts` is the guess's id, which the "Waiting on
# you" sensor carries; `question` is its text, for an automation written
# before the id was on the sensor. One of the two is required, and that is
# checked in the handler, where the open guesses can be read.
ANSWER_QUESTION_SCHEMA = vol.Schema(
    {
        vol.Optional("ts"): vol.Coerce(int),
        vol.Optional("question"): vol.All(str, vol.Length(min=1)),
        vol.Required("answer"): vol.All(str, vol.Length(min=1, max=600)),
        vol.Optional("source", default="service"): str,
    }
)

# Topic is optional: with none, brAIn studies whatever has gone stalest,
# which is what makes a nightly "study something" automation worth having.
STUDY_SCHEMA = vol.Schema(
    {
        vol.Optional("topic", default=""): vol.All(str, vol.Length(max=200)),
    }
)

# `brain.ask`: a question with an optional JSON Schema, answered with the
# validated object as `data` beside the text. Read-only tools by default —
# an automation asking a question is not asking for its files to be
# edited — and `full` has to be typed. The schema may arrive as an object
# (a YAML automation writes one naturally) or as a JSON string (a
# template or a script that built it), and either becomes the same dict.


def _schema_value(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError as exc:
            raise vol.Invalid(f"schema is not valid JSON: {exc}") from exc
        if isinstance(parsed, dict):
            return parsed
    raise vol.Invalid("schema must be a JSON Schema object")


ASK_SCHEMA = vol.Schema(
    {
        vol.Required("question"): vol.All(str, vol.Length(min=1, max=4000)),
        vol.Optional("schema"): _schema_value,
        vol.Optional("timeout"): vol.All(int, vol.Range(min=10, max=600)),
        vol.Optional("tools", default="read_only"): vol.In(TASK_TOOLS),
    }
)

INTENT_SCHEMA = vol.Schema(
    {
        vol.Required("sentence"): vol.All(str, vol.Length(min=1, max=300)),
    }
)

ADD_TODO_SCHEMA = vol.Schema(
    {
        vol.Required("text"): vol.All(str, vol.Length(min=1, max=200)),
    }
)

# A checks pass takes no arguments: it looks at the whole house, and a
# field naming one check would be a second answer to "what is a pass" that
# `run_checks` does not have.
CHECK_SCHEMA = vol.Schema({})


def entry_type(entry: ConfigEntry) -> str:
    """Entries created before 3.0 have no type and are conversation agents."""
    return entry.data.get(CONF_ENTRY_TYPE, ENTRY_TYPE_AGENT)


def _get_platforms(entry: ConfigEntry) -> list[Platform]:
    """Return the list of platforms to set up for this config entry."""
    if entry_type(entry) == ENTRY_TYPE_INSIGHT:
        return [Platform.SENSOR, Platform.BUTTON]
    opts = {**entry.data, **entry.options}
    platforms: list[Platform] = []
    if opts.get(CONF_ENABLE_CONVERSATION, True):
        platforms.append(Platform.CONVERSATION)
    if opts.get(CONF_ENABLE_SENSORS, True):
        platforms.append(Platform.SENSOR)
        # The system health binary sensor rides with the sensors-owner entry
        platforms.append(Platform.BINARY_SENSOR)
        # ...and so does the Run-checks button, which sits on the same
        # brAIn System device. Until now BUTTON was an insight job's
        # platform only, so the main entry never set it up.
        platforms.append(Platform.BUTTON)
        # The work list rides with them too — it is the same findings
        # mirror the open-findings sensor counts, as items. Looked up
        # rather than named: `todo` arrived in 2023.11 and this
        # integration's floor is 2023.6, so on an older core the constant
        # does not exist and the list is simply absent. A missing
        # platform is a missing entity; naming one the core has never
        # heard of fails the whole entry.
        todo = getattr(Platform, "TODO", None)
        if todo is not None:
            platforms.append(todo)
        # brAIn as Home Assistant's AI Task provider ("Suggest with AI",
        # `ai_task.generate_data`). Core 2025.7+; looked up for `todo`'s
        # reason — an older core has no such platform and must not be
        # asked for one.
        ai_task = getattr(Platform, "AI_TASK", None)
        if ai_task is not None:
            platforms.append(ai_task)
    return platforms


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate config entries to the current version."""
    if config_entry.version < 2:
        _LOGGER.debug("Migrating config entry %s from version %s to 2",
                       config_entry.entry_id, config_entry.version)
        new_data = {**config_entry.data}
        new_data.setdefault(CONF_ENABLE_CONVERSATION, True)
        new_data.setdefault(CONF_ENABLE_SENSORS, True)
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=2
        )
    if config_entry.version < 3:
        _LOGGER.debug("Migrating config entry %s from version 2 to 3",
                       config_entry.entry_id)
        new_data = {**config_entry.data}
        new_data.setdefault(CONF_MODEL, DEFAULT_MODEL)
        new_data.setdefault(CONF_SYSTEM_PROMPT, DEFAULT_SYSTEM_PROMPT)
        new_data.setdefault(CONF_TIMEOUT, DEFAULT_TIMEOUT)
        hass.config_entries.async_update_entry(
            config_entry, data=new_data, version=3
        )
    return True


def _make_action_handler(hass: HomeAssistant):
    """A listener for the companion app's notification buttons."""

    async def _handle(event: Event) -> None:
        parsed = parse_notification_action((event.data or {}).get("action"))
        if parsed is None:
            # Somebody else's actionable notification. Not ours, not an
            # error, and not worth a log line at anything but debug —
            # this fires for every button in the house.
            return
        action, ts = parsed
        # A text-input action carries what was typed here: the Reply
        # button's box (2.3). For the three verbs it is empty and is
        # carried as the note, exactly as a reason typed on the tab is.
        reply = str((event.data or {}).get("reply_text") or "")[:500]
        await hass.async_add_executor_job(
            write_finding_request, hass, ts, action, reply, "notification",
            0,
        )

    return _handle


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up brAIn from a config entry."""
    opts = {**entry.data, **entry.options}
    timeout = opts.get(CONF_TIMEOUT, DEFAULT_TIMEOUT)
    bridge = ClaudeBridge(hass, timeout=timeout)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = bridge

    # Only forward platforms the user has enabled
    platforms = _get_platforms(entry)
    hass.data[DOMAIN][f"{entry.entry_id}_platforms"] = platforms

    await hass.config_entries.async_forward_entry_setups(entry, platforms)

    # Register services (only once, guarded by domain key)
    if not hass.services.has_service(DOMAIN, "send_prompt"):
        _register_services(hass)

    if entry_type(entry) == ENTRY_TYPE_INSIGHT:
        _setup_insight_schedule(hass, entry)
    elif not hass.data[DOMAIN].get("_learning_watcher"):
        # One watcher account-wide (memory is one store, not per entry):
        # fires a brain_learned logbook event per newly-learned fact, as
        # the docs promise. Primed to the log's current tip so a restart
        # does not replay the whole history into the logbook.
        watcher = LearningWatcher(hass)
        await hass.async_add_executor_job(watcher.prime)
        unsub_learning = async_track_time_interval(
            hass, watcher.async_poll, timedelta(seconds=60)
        )
        # Findings ride the same account-wide slot: one store, one watcher,
        # a brain_finding event per newly-reported problem. Primed for the
        # same reason — a restart must not replay the open list on the bus.
        findings_watcher = FindingsWatcher(hass)
        await hass.async_add_executor_job(findings_watcher.prime)
        unsub_findings = async_track_time_interval(
            hass, findings_watcher.async_poll, timedelta(seconds=60)
        )
        # And the buttons on those findings' notifications, coming back.
        # The companion app fires one event for every actionable
        # notification in the house, brAIn's and everybody else's, so
        # `parse_action` rejects far more than it accepts.
        unsub_actions = hass.bus.async_listen(
            EVENT_MOBILE_ACTION, _make_action_handler(hass))
        # brAIn's measurements, for other conversation agents and the MCP
        # Server integration: three read-only tools, exposure-respecting.
        # Account-wide, like the watchers — one house, one API.
        from .llm_api import async_register as _register_llm_api

        unsub_llm = _register_llm_api(hass)
        hass.data[DOMAIN]["_learning_watcher"] = entry.entry_id

        def _stop_learning() -> None:
            unsub_learning()
            unsub_findings()
            unsub_actions()
            if unsub_llm is not None:
                unsub_llm()
            # The Repairs entries are this watcher's, so they leave with
            # it: a reload puts them back on the first poll, and removing
            # the integration should not leave brAIn's rows on somebody's
            # Repairs page with nothing behind them.
            findings_watcher.clear_issues()
            hass.data[DOMAIN].pop("_learning_watcher", None)

        entry.async_on_unload(_stop_learning)

    # Check if the add-on deployed newer integration files that need a restart
    await _check_restart_required(hass)

    # Reload the entry when the user changes options (system prompt, timeout, etc.)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))

    # Listen for the add-on signalling that new files were deployed while HA is
    # running. Wrap in async_on_unload so the listener is removed when the entry
    # unloads/reloads — otherwise listeners accumulate on every options change.
    async def _on_restart_required(event: Event) -> None:
        await _check_restart_required(hass)

    entry.async_on_unload(
        hass.bus.async_listen("brain_restart_required", _on_restart_required)
    )

    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Reload the config entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    platforms = hass.data.get(DOMAIN, {}).get(
        f"{entry.entry_id}_platforms",
        _get_platforms(entry),
    )

    unload_ok = await hass.config_entries.async_unload_platforms(entry, platforms)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        hass.data[DOMAIN].pop(f"{entry.entry_id}_platforms", None)

        # Remaining configured entries (bridge instances), excluding the
        # metadata keys (_sensors_added, _sensors_entry, <id>_platforms).
        remaining = [
            eid for eid in hass.data[DOMAIN]
            if not eid.startswith("_") and not eid.endswith("_platforms")
        ]

        # If this entry owned the account-wide sensors, clear the flags so
        # another entry (or this one, on reload) can recreate them.
        if hass.data[DOMAIN].get("_health_entry") == entry.entry_id:
            hass.data[DOMAIN].pop("_health_entry", None)
            hass.data[DOMAIN].pop("_health_added", None)
        # The work list rides with the health sensor and claims its own
        # pair for the same reason: a flag left set over a reload is an
        # entity that never comes back until Home Assistant restarts.
        # The Run-checks button claims its own pair for the same reason:
        # a flag left set over a reload is an entity that never comes
        # back until Home Assistant restarts.
        if hass.data[DOMAIN].get("_checks_button_entry") == entry.entry_id:
            hass.data[DOMAIN].pop("_checks_button_entry", None)
            hass.data[DOMAIN].pop("_checks_button_added", None)
        if hass.data[DOMAIN].get("_todo_entry") == entry.entry_id:
            hass.data[DOMAIN].pop("_todo_entry", None)
            hass.data[DOMAIN].pop("_todo_added", None)
        if hass.data[DOMAIN].get("_ai_task_entry") == entry.entry_id:
            hass.data[DOMAIN].pop("_ai_task_entry", None)
            hass.data[DOMAIN].pop("_ai_task_added", None)
        if hass.data[DOMAIN].get("_sensors_entry") == entry.entry_id:
            hass.data[DOMAIN].pop("_sensors_entry", None)
            hass.data[DOMAIN].pop("_sensors_added", None)

            # Auto-migrate: reload another AGENT entry so it picks up sensor
            # duties. Insight entries return early from sensor setup without
            # claiming _sensors_added, so reloading one of those would leave
            # the usage sensors gone until HA restarts.
            for eid in remaining:
                candidate = hass.config_entries.async_get_entry(eid)
                if candidate is None or entry_type(candidate) == ENTRY_TYPE_INSIGHT:
                    continue
                hass.async_create_task(
                    hass.config_entries.async_reload(eid)
                )
                break

        # Last entry removed — tear down the domain services so they don't
        # linger and raise "not configured" if called with no bridge.
        if not remaining:
            for service in (
                "send_prompt",
                "run_task",
                "clear_conversation",
                "run_insight",
                "add_memory",
                "answer_question",
                "study",
                "check",
                "ask",
                "intent",
                "add_todo",
                *POWER_TOOL_SERVICES,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unload_ok


async def _check_restart_required(hass: HomeAssistant) -> None:
    """Check if the add-on deployed newer files and create/clear a repair issue."""
    marker_path = hass.config.path(".brain", "restart_required")
    marker = await hass.async_add_executor_job(_read_marker, marker_path)

    if marker is None:
        # No marker file — nothing to do, clear any stale repair
        ir.async_delete_issue(hass, DOMAIN, "restart_required")
        return

    required_version = marker.get("required_version", "")

    # Use the version captured at import time — NOT the on-disk manifest,
    # which the add-on may have already overwritten with the newer version.
    loaded_version = _LOADED_VERSION

    if required_version and required_version == loaded_version:
        # The restart already happened — we're running the new version
        await hass.async_add_executor_job(_remove_file, marker_path)
        ir.async_delete_issue(hass, DOMAIN, "restart_required")
        # Also dismiss any leftover persistent notification from older versions
        await hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": "brain_restart_needed"},
        )
        return

    # Files on disk are newer than what's loaded — prompt user to restart
    ir.async_create_issue(
        hass,
        DOMAIN,
        "restart_required",
        is_fixable=True,
        is_persistent=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="restart_required",
        translation_placeholders={"version": required_version},
    )

    # Also create a persistent notification as a visible fallback in case
    # the user doesn't check Settings > System > Repairs.
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"brAIn: Restart Required (v{required_version})",
                "message": (
                    f"The brAIn integration has been updated to v{required_version}. "
                    "Please restart Home Assistant to load the new version.\n\n"
                    "Go to **Settings > System > Restart**, or check "
                    "**Settings > System > Repairs** to fix automatically."
                ),
                "notification_id": "brain_restart_needed",
            },
        )
    except Exception:
        _LOGGER.debug("Could not create persistent notification for restart")


def _read_marker(path: str) -> dict | None:
    """Read the restart marker JSON file, return None if missing."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _read_json(path: str) -> dict | None:
    """Read a JSON file, return None on error."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None


def _remove_file(path: str) -> None:
    """Remove a file if it exists."""
    try:
        os.remove(path)
    except OSError:
        # Removing a file that is already gone is this function's goal, not
        # its failure.
        pass


# ---------------------------------------------------------------------------
# Home memory store (shared with the add-on's brain memory tooling)
#
# Contract (see the add-on's memory consolidator):
#   inbox/<epoch>-<source>.jsonl  one candidate fact per line:
#       {"ts": <epoch int>, "source": "...", "fact": "...",
#        "confidence": "high|medium|low"}
#
# An answer to one of brAIn's guesses is NOT written here: it is a request
# the panel applies with the guess's own confirm/reject (see
# `handle_answer_question`), because the guess is what has to close.
# ---------------------------------------------------------------------------

# Sources that carry an authority the pipeline acts on, and so may not be
# claimed by a service call. `correction` is the homeowner saying brAIn had
# something wrong, and the consolidator is told a correction is newer and
# WINS over the line it contradicts; `person` is never pruned to make room;
# `confirmed` is a guess the homeowner said yes to. A service that could
# file any of those could rewrite what every later run — voice, the fixer —
# is told about the house, under a label that says a person typed it.
RESERVED_MEMORY_SOURCES = frozenset({"correction", "person", "confirmed"})


def _sanitize_source(source: str) -> str:
    """Keep inbox filenames safe: alnum/underscore/dash only."""
    cleaned = "".join(c for c in str(source) if c.isalnum() or c in "_-")
    return cleaned or "service"


def _reserved_source(source: str) -> bool:
    """Whether a source names one of the authorities above, however spelled.

    Asked of the SANITIZED name, because that is what lands in the inbox:
    `"Correction!"` and `"correction"` are the same line once written.
    """
    return _sanitize_source(source).lower() in RESERVED_MEMORY_SOURCES


def _write_study_request(requests_dir: str, topic: str) -> str:
    """Drop a study request for the add-on's watcher. Executor-safe."""
    os.makedirs(requests_dir, exist_ok=True)
    now = int(time.time())
    path = os.path.join(requests_dir, f"{now}-{os.getpid()}.json")
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"ts": now, "topic": str(topic or "").strip()[:200]}, fh)
    # Atomic rename: the watcher must never see a half-written request.
    os.replace(tmp, path)
    return path


def _append_memory_fact(
    memory_dir: str, fact: str, source: str, confidence: str
) -> str:
    """Append one candidate fact to a new memory-inbox JSONL file.

    Returns the path written. Executor-safe (blocking file IO).
    """
    source = _sanitize_source(source)
    if confidence not in ("high", "medium", "low"):
        confidence = "medium"
    inbox = os.path.join(memory_dir, MEMORY_INBOX_DIR)
    os.makedirs(inbox, exist_ok=True)
    now = int(time.time())
    record = {
        "ts": now,
        "source": source,
        "fact": str(fact).strip(),
        "confidence": confidence,
    }
    path = os.path.join(inbox, f"{now}-{source}.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")
    return path


# A guess is answered yes or no. Read off the first word, because that is
# how people answer a yes/no question in a text box — "yes", "no — it's the
# beer fridge" — and a no may carry its reason, which is the half that
# teaches (the panel files it as a correction).
_YES_WORDS = frozenset({"yes", "y", "yeah", "yep", "yup", "true", "correct",
                        "right", "confirm", "confirmed", "affirmative"})
_NO_WORDS = frozenset({"no", "n", "nope", "nah", "false", "wrong",
                       "incorrect", "reject", "rejected", "negative"})


def _verdict(answer: str) -> tuple[str, str]:
    """`("confirm", "")` or `("reject", reason)` for an answer, or raise.

    A free-text answer that is neither is refused rather than guessed at:
    the old service filed whatever was typed as a high-confidence fact and
    left the guess open, so a "no" became a fact and the question stayed on
    every surface until it expired. An answer that names neither yes nor no
    is a fact, and `brain.add_memory` is the door for one.
    """
    text = str(answer or "").strip()
    head, _, rest = text.replace(",", " ").replace("—", " ").replace(
        ":", " ").replace(".", " ").replace("!", " ").partition(" ")
    word = head.strip().lower()
    if word in _YES_WORDS:
        return "confirm", ""
    if word in _NO_WORDS:
        # The reason is what followed the word, as it was typed.
        reason = text[len(head):].lstrip(" ,.:;!—-").strip()
        return "reject", reason[:500]
    raise ServiceValidationError(
        "brain.answer_question answers one of brAIn's guesses yes or no — "
        "start the answer with yes or no (a reason after a no is kept). "
        "To teach brAIn a fact instead, use brain.add_memory."
    )


def _normalise_guess(text: str) -> str:
    return " ".join(str(text or "").casefold().split()).rstrip(" ?.!")


def _which_guess(open_guesses: list[dict], ts=None, question=None) -> int:
    """The id of the open guess an answer is about, or raise.

    By id first — that is what the sensor carries and it cannot be
    ambiguous — and by text for an automation that has the question in
    hand: exactly, then as the one guess containing what was given. Two
    guesses matching is a refusal, because answering the wrong one closes
    it and files its dead end for good.
    """
    if ts is not None:
        for guess in open_guesses:
            if int(guess.get("ts") or 0) == int(ts):
                return int(ts)
        raise ServiceValidationError(
            f"No open guess has the id {ts} — it may have been answered "
            "already or expired. The \"Waiting on you\" sensor lists the "
            "open ones with their ids.")
    want = _normalise_guess(question or "")
    if not want:
        raise ServiceValidationError(
            "Say which guess you are answering: its ts (from the \"Waiting "
            "on you\" sensor) or its question.")
    exact = [g for g in open_guesses if _normalise_guess(g.get("text")) == want]
    near = exact or [g for g in open_guesses
                     if want in _normalise_guess(g.get("text"))]
    if len(near) == 1:
        return int(near[0].get("ts") or 0)
    if not near:
        raise ServiceValidationError(
            f"No open guess matches \"{question}\". The \"Waiting on you\" "
            "sensor lists the open ones with their ids.")
    raise ServiceValidationError(
        f"{len(near)} open guesses match \"{question}\" — answer by ts "
        "instead, from the \"Waiting on you\" sensor.")


# ---------------------------------------------------------------------------
# Insight jobs
# ---------------------------------------------------------------------------


def _setup_insight_schedule(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Wire up interval/daily triggers and an initial run for an insight job."""
    opts = {**entry.data, **entry.options}

    async def _scheduled_run(_now=None) -> None:
        await _async_run_insight(hass, entry, scheduled=True)

    interval = opts.get(CONF_INSIGHT_INTERVAL) or 0
    if isinstance(interval, (int, float)) and interval >= 5:
        entry.async_on_unload(
            async_track_time_interval(
                hass, _scheduled_run, timedelta(minutes=int(interval))
            )
        )

    daily_at = (opts.get(CONF_INSIGHT_DAILY_AT) or "").strip()
    if daily_at:
        try:
            hour, minute = (int(part) for part in daily_at.split(":", 1))
            entry.async_on_unload(
                async_track_time_change(
                    hass, _scheduled_run, hour=hour, minute=minute, second=0
                )
            )
        except (ValueError, TypeError):
            _LOGGER.warning(
                "Insight job '%s' has invalid daily_at '%s' (expected HH:MM)",
                entry.title, daily_at,
            )

    # One run shortly after setup so the sensor isn't empty until the first
    # scheduled slot. Delay gives the add-on time to come up after a restart.
    entry.async_on_unload(
        async_call_later(hass, 90, _scheduled_run)
    )


async def _async_run_insight(hass: HomeAssistant, entry: ConfigEntry,
                             scheduled: bool = False) -> None:
    """Run one insight job: render prompt -> task channel -> sensor + event.

    An insight job is an UNATTENDED run — it fires on a timer, and once
    90 seconds after every setup — so it is held to the rules every other
    unattended run is: the analyst's read-only tools (it used to inherit
    the project grant, Bash and file edits included), the panel's pause
    switch and usage budget when nobody pressed anything (`scheduled`),
    and what brAIn knows about the house through the panel's own
    retrieval rather than the first 2 KB of memory.md cut mid-fact. A run
    the listener says failed is recorded as an ERROR on the sensor and
    never as a report: an expired login used to be pushed to a phone as
    that morning's briefing.
    """
    running = hass.data[DOMAIN].setdefault("_insights_running", set())
    if entry.entry_id in running:
        _LOGGER.debug("Insight '%s' already running — skipped", entry.title)
        return
    running.add(entry.entry_id)
    try:
        opts = {**entry.data, **entry.options}
        prompt_text = (opts.get(CONF_INSIGHT_PROMPT) or "").strip()
        template_key = opts.get(CONF_INSIGHT_TEMPLATE, "daily_briefing")
        # Only the preset's own words get the snapshot tool: a custom prompt
        # asked for nothing about cameras.
        wants_cameras = not prompt_text and template_key in CAMERA_TEMPLATES
        if not prompt_text:
            prompt_text = INSIGHT_TEMPLATES.get(
                template_key, INSIGHT_TEMPLATES["daily_briefing"]
            )

        # Custom prompts may embed HA Jinja ({{ states(...) }}) for
        # deterministic data injection — render before sending.
        try:
            prompt = Template(prompt_text, hass).async_render(parse_result=False)
        except Exception:  # noqa: BLE001 — template errors fall back to raw text
            _LOGGER.warning(
                "Insight '%s': prompt template failed to render; sending raw",
                entry.title,
            )
            prompt = prompt_text

        # The previous report, so a recurring insight builds on what it
        # said last time instead of rediscovering the house every run. What
        # brAIn KNOWS about the house is not read here any more: the
        # listener puts the panel's own retrieval block in front of the
        # prompt (`memory=True`), which is one implementation of "what is
        # known" rather than a byte-cut of the document in a second place.
        prior = await hass.async_add_executor_job(
            load_insight_payload, hass, entry.entry_id
        )
        prev_markdown = ((prior or {}).get("markdown") or "").strip()
        if prev_markdown:
            prompt = (
                "Previous report (for continuity, note meaningful changes "
                "rather than rediscovering):\n" + prev_markdown[:1536]
                + "\n\n" + prompt
            )

        bridge = _get_bridge(hass)
        timeout = opts.get(CONF_TIMEOUT) or DEFAULT_INSIGHT_TIMEOUT
        model = opts.get(CONF_MODEL) or "default"
        started = time.monotonic()
        payload: dict
        try:
            result = await bridge.async_send_task(
                prompt=prompt, timeout=timeout, model=model,
                tools="read_only", memory=True, scheduled=scheduled,
                cameras=wants_cameras,
            )
            payload = {
                "markdown": truncate_markdown(result),
                "last_success": dt_util.utcnow().isoformat(),
                "duration_s": round(time.monotonic() - started, 1),
                "error": None,
                "error_code": None,
            }
        except Exception as exc:  # noqa: BLE001 — surface failure on the sensor
            # The last good report and when it landed are kept beside the
            # error, on disk as well as on the sensor: a run that failed
            # says nothing new about the house, and a card that went blank
            # after a restart because the failure overwrote the file would
            # be the failure costing more than the run did.
            payload = {
                **{k: v for k, v in (prior or {}).items()
                   if k in ("markdown", "last_success", "ever_succeeded")},
                "duration_s": round(time.monotonic() - started, 1),
                "error": str(exc) or type(exc).__name__,
                "error_code": getattr(exc, "code", None)
                or ("timeout" if isinstance(exc, TimeoutError) else "error"),
            }

        # Onboarding: after a job's FIRST successful run, send one
        # notification containing the ready-to-paste dashboard card —
        # the bridge from "it ran" to "I can see it".
        # (`prior` was loaded above, before the run, for the context block.)
        payload["ever_succeeded"] = bool(
            (prior or {}).get("ever_succeeded") or payload.get("error") is None
        )
        if payload.get("error") is None and not (prior or {}).get("ever_succeeded"):
            await _notify_first_success(hass, entry, payload)

        await hass.async_add_executor_job(
            _persist_insight, hass.config.path(SHARED_DIR, INSIGHTS_DIR),
            entry.entry_id, payload,
        )
        async_dispatcher_send(
            hass, SIGNAL_INSIGHT_UPDATE.format(entry.entry_id), payload
        )

        # Optional push: deliver the report to a notify service on every
        # successful run (e.g. the morning briefing straight to a phone).
        notify_service = (opts.get(CONF_INSIGHT_NOTIFY) or "").strip()
        notify_service = notify_service.removeprefix("notify.")
        if notify_service and payload.get("error") is None:
            try:
                await hass.services.async_call(
                    "notify", notify_service,
                    {
                        "title": entry.title,
                        "message": (payload.get("markdown") or "")[:2000],
                    },
                )
            except Exception:  # noqa: BLE001 — a bad target can't fail the run
                _LOGGER.warning(
                    "Insight '%s': notify.%s failed", entry.title, notify_service
                )

        hass.bus.async_fire(
            EVENT_INSIGHT_COMPLETE,
            {
                "name": entry.title,
                "entry_id": entry.entry_id,
                "entity_id": _insight_entity_id(hass, entry),
                "success": payload.get("error") is None,
                "preview": make_preview(payload.get("markdown"), limit=240),
            },
        )
    finally:
        running.discard(entry.entry_id)


def _insight_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> str | None:
    """Resolve an insight job's sensor entity_id from the registry."""
    try:
        from homeassistant.helpers import entity_registry as er

        return er.async_get(hass).async_get_entity_id(
            "sensor", DOMAIN, f"{entry.entry_id}_insight"
        )
    except Exception:  # noqa: BLE001
        return None


async def _notify_first_success(
    hass: HomeAssistant, entry: ConfigEntry, payload: dict
) -> None:
    """One-time persistent notification with the dashboard card YAML."""
    try:
        entity_id = _insight_entity_id(hass, entry) or "sensor.<your insight sensor>"
        preview = make_preview(payload.get("markdown"), limit=240) or ""
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"Insight '{entry.title}' ran — put it on a dashboard",
                "message": (
                    f"{preview}\n\n"
                    "To display it, add a card to any dashboard "
                    "(Add card > Manual) and paste:\n\n"
                    f"```yaml\n{build_card_yaml(entity_id, entry.title)}\n```\n\n"
                    "This notification only appears after the first successful run."
                ),
                "notification_id": f"brain_insight_{entry.entry_id}",
            },
        )
    except Exception:  # noqa: BLE001 — onboarding must never fail the run
        _LOGGER.debug("Could not send first-run insight notification")


def _persist_insight(directory: str, entry_id: str, payload: dict) -> None:
    """Persist the latest result so insights survive HA restarts."""
    try:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{entry_id}.json")
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    except OSError:
        _LOGGER.debug("Could not persist insight result for %s", entry_id)


def load_insight_payload(hass: HomeAssistant, entry_id: str) -> dict | None:
    """Read the persisted result for an insight job (executor-safe)."""
    path = hass.config.path(SHARED_DIR, INSIGHTS_DIR, f"{entry_id}.json")
    return _read_json(path)


def _get_bridge(hass: HomeAssistant) -> ClaudeBridge:
    """Return the first available bridge instance."""
    domain_data = hass.data.get(DOMAIN, {})
    for key, value in domain_data.items():
        if isinstance(value, ClaudeBridge):
            return value
    raise ValueError("brAIn integration is not configured")


async def _require_admin_for(hass: HomeAssistant, call: ServiceCall,
                             tools: str) -> None:
    """Refuse a non-admin caller anything wider than `NON_ADMIN_TOOLS`.

    A task runs with the Supervisor's token behind every Home Assistant
    tool and, at `full`, a shell in /config — so the reach is an admin's
    whatever the caller's own account is, and a wall tablet's or a guest's
    login could get a root-equivalent run by naming a field. Home
    Assistant does not stop it: only `async_register_admin_service` is
    admin-gated, and that registration cannot return response data. So
    the gate is the power tools' own (`async_require_admin`), asked here
    for the scopes that need it. A context with no user — an automation,
    a script one started — is the system and passes, as it does there.
    """
    if tools not in NON_ADMIN_TOOLS:
        await async_require_admin(hass, call.context)


def _failed(exc: Exception, what: str) -> HomeAssistantError:
    """The error a service raises for a run that did not answer.

    `HomeAssistantError` because that is what puts the sentence in an
    automation's trace — the rule BRight's and BRUH Minecraft's services
    already follow. A run that failed used to come back as `response`
    with `data: None`, which an automation branching on the data read as
    a real answer: `| default(false)` turned an expired login into
    "nothing unusual".
    """
    if isinstance(exc, BrainRunError):
        return HomeAssistantError(exc.text or f"{what} failed ({exc.code}).")
    if isinstance(exc, TimeoutError):
        return HomeAssistantError(
            f"{what} did not finish in time. Make sure the brAIn add-on is "
            "running; its log says what it was doing.")
    return HomeAssistantError(f"{what} failed: {exc}")


def _register_services(hass: HomeAssistant) -> None:
    """Register brain services."""

    async def handle_send_prompt(call: ServiceCall):
        bridge = _get_bridge(hass)
        prompt = call.data["prompt"]
        timeout = call.data.get("timeout")

        # A prompt goes down the conversation channel with no access level,
        # which the add-on reads as the narrowest (voice) — so it needs no
        # admin gate, any more than Assist itself does.
        try:
            result = await bridge.async_send_conversation(
                text=prompt, timeout=timeout, model=call.data.get("model")
            )
        except (BrainRunError, TimeoutError) as exc:
            raise _failed(exc, "Claude") from exc

        return {"response": result}

    async def handle_run_task(call: ServiceCall):
        tools = call.data.get("tools", DEFAULT_TASK_TOOLS)
        await _require_admin_for(hass, call, tools)
        bridge = _get_bridge(hass)
        prompt = call.data["prompt"]
        notify = call.data.get("notify", False)
        notify_entity = call.data.get("notify_entity")
        timeout = call.data.get("timeout")

        try:
            answer = await bridge.async_send_task_full(
                prompt=prompt,
                notify=notify,
                notify_entity=notify_entity,
                timeout=timeout,
                model=call.data.get("model"),
                tools=tools,
            )
        except (BrainRunError, TimeoutError) as exc:
            raise _failed(exc, "The task") from exc

        return {"response": answer["text"], "data": answer.get("data")}

    async def handle_ask(call: ServiceCall):
        """A question, and optionally the shape the answer must take.

        A failed run RAISES. The data an automation branches on is only
        ever the object the CLI validated off a run that answered, never
        a `None` standing beside an error sentence.
        """
        tools = call.data.get("tools", "read_only")
        await _require_admin_for(hass, call, tools)
        bridge = _get_bridge(hass)
        schema = call.data.get("schema")
        try:
            answer = await bridge.async_send_task_full(
                prompt=call.data["question"],
                timeout=call.data.get("timeout"),
                tools=tools,
                schema=schema if isinstance(schema, dict) else None,
            )
        except (BrainRunError, TimeoutError) as exc:
            raise _failed(exc, "The question") from exc
        return {"response": answer["text"], "data": answer.get("data")}

    async def handle_run_insight(call: ServiceCall):
        name = (call.data.get("name") or "").strip().lower()
        entries = [
            e for e in hass.config_entries.async_entries(DOMAIN)
            if entry_type(e) == ENTRY_TYPE_INSIGHT
            and (not name or e.title.lower() == name)
        ]
        if not entries:
            raise ValueError(
                f"No insight job matches '{name}'" if name
                else "No insight jobs configured"
            )
        for e in entries:
            # A press: the pause switch and the budget are for runs nobody
            # asked for, and asking by hand always runs.
            hass.async_create_task(_async_run_insight(hass, e, scheduled=False))

    async def handle_clear_conversation(call: ServiceCall):
        bridge = _get_bridge(hass)
        conversation_id = call.data.get("conversation_id")
        await bridge.async_clear_conversation(conversation_id)
        _LOGGER.info(
            "Cleared conversation session: %s",
            conversation_id or "ALL",
        )

    async def handle_add_memory(call: ServiceCall):
        """Queue one fact. Admin only, and never under a person's authority.

        Memory is handed to every later run — voice, the fixer, every card
        — so a fact filed here is a standing instruction to all of them,
        which is an admin's to give. And a `correction` (or a `person`, or
        a `confirmed`) is what the pipeline treats as the homeowner having
        typed it, so a caller may not claim one.
        """
        await async_require_admin(hass, call.context)
        source = call.data.get("source", "service")
        if _reserved_source(source):
            raise ServiceValidationError(
                f"\"{source}\" is a source brAIn keeps for the homeowner's own "
                "answers (corrections, confirmations, typed preferences), so "
                "a service call cannot file under it. Leave source out, or "
                "name where the fact came from.")
        memory_dir = hass.config.path(SHARED_DIR, MEMORY_DIR)
        await hass.async_add_executor_job(
            _append_memory_fact,
            memory_dir,
            call.data["fact"],
            source,
            call.data.get("confidence", "medium"),
        )
        _LOGGER.debug("Queued memory fact from %s", call.data.get("source"))

    async def handle_study(call: ServiceCall):
        """Send brAIn off to study a topic.

        Fire-and-forget by design: a study session can run for many minutes,
        which is far longer than a service call should block. What it finds
        goes through the memory inbox like everything else, so the result
        shows up in memory rather than in this call's response — which is
        also why it is admin only: what a study files is handed to every
        later run.
        """
        await async_require_admin(hass, call.context)
        requests_dir = hass.config.path(SHARED_DIR, STUDY_REQUESTS_DIR)
        await hass.async_add_executor_job(
            _write_study_request, requests_dir, call.data.get("topic", ""))
        _LOGGER.info("Queued study session: %s", call.data.get("topic") or "(stalest topic)")

    async def handle_intent(call: ServiceCall):
        """Turn one sentence into an automation that runs once.

        Fire-and-forget, exactly as `study` is and for the same reason:
        Claude has to search the house for what the sentence names, which
        is far longer than a service call should block — and a voice
        command that waited would be a voice command that timed out. What
        comes back is a card on the Proposals tab, because **nothing brAIn
        writes is enabled on its own**; a sentence it will not arm gets a
        card there too, with the reason on it.
        """
        from .requests import write_intent  # noqa: PLC0415 — that module
        # imports homeassistant.core and nothing else on purpose

        # Admin only: what it drafts is an automation, and writing one is
        # an admin's to do in Home Assistant itself.
        await async_require_admin(hass, call.context)
        sentence = call.data["sentence"]
        await hass.async_add_executor_job(
            write_intent, hass, sentence, "service")
        _LOGGER.info("Queued a one-off intent: %s", sentence)

    async def handle_add_todo(call: ServiceCall):
        """Put something on brAIn's to-do list.

        The same drop the To-do app's own Add button writes, so an
        automation and a person land on one list through one path — and
        it is fire-and-forget for `handle_intent`'s reason, narrowed:
        the add-on may be stopped, and a chore that could not be written
        for thirty seconds is worth waiting for where a service call
        that blocked on it is not.
        """
        from .requests import write_todo_request  # noqa: PLC0415 — that
        # module imports homeassistant.core and nothing else on purpose

        text = call.data["text"]
        await hass.async_add_executor_job(
            partial(write_todo_request, hass, "add", text=text,
                    via="service"))
        _LOGGER.info("Queued a to-do: %s", text)

    async def handle_check(call: ServiceCall):
        """Ask the add-on to run its house checks now.

        Fire-and-forget, for `handle_study`'s reason with a shorter clock:
        a pass collects a snapshot of the whole house, runs every check
        against it and triages what it filed, which is minutes rather than
        the seconds a service call should block for — and what it finds
        arrives on the Findings tab, in the mirror, and through the
        ``brain_finding`` event, not in this call's response.

        It crosses the gap as a request file, exactly as an ending given in
        the To-do app does: the panel owns the checks and Home Assistant
        cannot reach port 8099.
        """
        from .requests import write_checks_request  # noqa: PLC0415 — that
        # module imports homeassistant.core and nothing else on purpose

        await hass.async_add_executor_job(write_checks_request, hass, "service")
        _LOGGER.info("Asked brAIn to run its house checks")

    async def handle_answer_question(call: ServiceCall):
        """Answer one of brAIn's guesses, yes or no, from anywhere in HA.

        It crosses to the panel as a REQUEST, the way a finding's ending
        does, because the guess has to CLOSE: the panel confirms or
        rejects it through the same code the Findings tab's Yes and No
        use — the claim filed as memory, or the dead end recorded and the
        reason filed as a correction. The old service appended to a file
        nothing read and queued the typed answer as a high-confidence
        fact, so a "no" became a fact and the guess stayed open on every
        surface until it expired.

        Fire-and-forget, `write_request`'s rule: the add-on may be
        stopped, and the answer is applied when it is not. What is
        refused here is what could never be applied — an answer that is
        neither yes nor no, a guess that is not open.
        """
        from .requests import write_hypothesis_request  # noqa: PLC0415 —
        # that module imports homeassistant.core and nothing else on purpose

        await async_require_admin(hass, call.context)
        verdict, reason = _verdict(call.data["answer"])
        open_guesses = await hass.async_add_executor_job(
            read_open_hypotheses, hass)
        ts = _which_guess(open_guesses, call.data.get("ts"),
                          call.data.get("question"))
        landed = await hass.async_add_executor_job(
            partial(write_hypothesis_request, hass, ts, verdict, note=reason,
                    via=_sanitize_source(call.data.get("source", "service"))))
        if not landed:
            raise HomeAssistantError(
                "brAIn could not record the answer — /config/.brain is not "
                "writable. Nothing was changed.")
        _LOGGER.info("Answered guess %s: %s", ts, verdict)

    extra_kwargs: dict = {}
    if SupportsResponse is not None:
        extra_kwargs["supports_response"] = SupportsResponse.OPTIONAL

    hass.services.async_register(
        DOMAIN,
        "send_prompt",
        handle_send_prompt,
        schema=SEND_PROMPT_SCHEMA,
        **extra_kwargs,
    )

    hass.services.async_register(
        DOMAIN,
        "run_task",
        handle_run_task,
        schema=RUN_TASK_SCHEMA,
        **extra_kwargs,
    )

    hass.services.async_register(
        DOMAIN,
        "clear_conversation",
        handle_clear_conversation,
        schema=CLEAR_CONVERSATION_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "run_insight",
        handle_run_insight,
        schema=RUN_INSIGHT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "add_memory",
        handle_add_memory,
        schema=ADD_MEMORY_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "answer_question",
        handle_answer_question,
        schema=ANSWER_QUESTION_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "study",
        handle_study,
        schema=STUDY_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "ask",
        handle_ask,
        schema=ASK_SCHEMA,
        **extra_kwargs,
    )

    hass.services.async_register(
        DOMAIN,
        "intent",
        handle_intent,
        schema=INTENT_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "add_todo",
        handle_add_todo,
        schema=ADD_TODO_SCHEMA,
    )

    hass.services.async_register(
        DOMAIN,
        "check",
        handle_check,
        schema=CHECK_SCHEMA,
    )

    # BRUH Power Tools: registry-management admin services (power_tools.py)
    async_register_power_tools(hass)
