"""BRUH Claude integration for Home Assistant.

Provides:
- A conversation agent ("BRUH Claude") selectable in Settings > Voice Assistants
- Usage limit sensors for Anthropic account data
- bruh_claude.send_prompt          — send a one-shot prompt to Claude
- bruh_claude.run_task             — run a Claude task with optional notification
- bruh_claude.clear_conversation   — clear a persistent conversation session
- bruh_claude.add_memory           — queue a fact for the home memory store
- bruh_claude.answer_question      — answer an open memory question
- BRUH Power Tools                 — 41 registry-management admin services
  (areas, floors, labels, entities, devices, integrations, zones, persons,
  blueprints, statistics, users, diagnostics, repairs) — see power_tools.py

Both conversation agent and sensors are independently toggleable per config entry.
"""

from __future__ import annotations

import json
import logging
import os
import time

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant, ServiceCall
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

from .bridge import ClaudeBridge
from .const import (
    CONF_ENABLE_CONVERSATION,
    CONF_ENABLE_SENSORS,
    CONF_ENTRY_TYPE,
    CONF_INSIGHT_DAILY_AT,
    CONF_INSIGHT_NOTIFY,
    CONF_INSIGHT_INTERVAL,
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
    INSIGHTS_DIR,
    MEMORY_DIR,
    MEMORY_FILE,
    MEMORY_INBOX_DIR,
    QUESTIONS_FILE,
    SHARED_DIR,
    SIGNAL_INSIGHT_UPDATE,
)
from .insight_format import (
    INSIGHT_TEMPLATES,
    build_card_yaml,
    make_preview,
    truncate_markdown,
)
from .power_tools import POWER_TOOL_SERVICES, async_register_power_tools

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
    pass

SEND_PROMPT_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): str,
        vol.Optional("timeout"): vol.All(int, vol.Range(min=10, max=600)),
        vol.Optional("model"): str,
    }
)

RUN_TASK_SCHEMA = vol.Schema(
    {
        vol.Required("prompt"): str,
        vol.Optional("notify", default=False): bool,
        vol.Optional("notify_entity"): str,
        vol.Optional("timeout"): vol.All(int, vol.Range(min=10, max=600)),
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

ANSWER_QUESTION_SCHEMA = vol.Schema(
    {
        vol.Required("question"): vol.All(str, vol.Length(min=1)),
        vol.Required("answer"): vol.All(str, vol.Length(min=1)),
        vol.Optional("source", default="service"): str,
    }
)


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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up BRUH Claude from a config entry."""
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
        hass.bus.async_listen("bruh_claude_restart_required", _on_restart_required)
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
        if hass.data[DOMAIN].get("_sensors_entry") == entry.entry_id:
            hass.data[DOMAIN].pop("_sensors_entry", None)
            hass.data[DOMAIN].pop("_sensors_added", None)

            # Auto-migrate: reload another entry so it picks up sensor duties.
            if remaining:
                hass.async_create_task(
                    hass.config_entries.async_reload(remaining[0])
                )

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
                *POWER_TOOL_SERVICES,
            ):
                if hass.services.has_service(DOMAIN, service):
                    hass.services.async_remove(DOMAIN, service)
    return unload_ok


async def _check_restart_required(hass: HomeAssistant) -> None:
    """Check if the add-on deployed newer files and create/clear a repair issue."""
    marker_path = hass.config.path(".bruh_claude", "restart_required")
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
            {"notification_id": "bruh_claude_restart_needed"},
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
                "title": f"BRUH Claude: Restart Required (v{required_version})",
                "message": (
                    f"The BRUH Claude integration has been updated to v{required_version}. "
                    "Please restart Home Assistant to load the new version.\n\n"
                    "Go to **Settings > System > Restart**, or check "
                    "**Settings > System > Repairs** to fix automatically."
                ),
                "notification_id": "bruh_claude_restart_needed",
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
        pass


def _read_text_capped(path: str, cap: int) -> str:
    """Read at most `cap` bytes of a text file; '' on any error."""
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read(cap)
    except OSError:
        return ""


# ---------------------------------------------------------------------------
# Home memory store (shared with the add-on's ha-memory tooling)
#
# Contract (see the add-on's ha-memory-consolidate.sh):
#   inbox/<epoch>-<source>.jsonl  one candidate fact per line:
#       {"ts": <epoch int>, "source": "...", "fact": "...",
#        "confidence": "high|medium|low"}
#   questions.jsonl               question + answer records; an answer is
#       {"q": "...", "a": "...", "source": "...", "ts": <epoch int>}
# ---------------------------------------------------------------------------


def _sanitize_source(source: str) -> str:
    """Keep inbox filenames safe: alnum/underscore/dash only."""
    cleaned = "".join(c for c in str(source) if c.isalnum() or c in "_-")
    return cleaned or "service"


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


def _append_question_answer(
    memory_dir: str, question: str, answer: str, source: str
) -> None:
    """Record an answer in questions.jsonl AND queue it as an inbox fact."""
    source = _sanitize_source(source)
    os.makedirs(memory_dir, exist_ok=True)
    record = {
        "q": str(question).strip(),
        "a": str(answer).strip(),
        "source": source,
        "ts": int(time.time()),
    }
    with open(
        os.path.join(memory_dir, QUESTIONS_FILE), "a", encoding="utf-8"
    ) as fh:
        fh.write(json.dumps(record) + "\n")
    _append_memory_fact(
        memory_dir,
        f"Q: {record['q']} → A: {record['a']}",
        source,
        "high",
    )


# ---------------------------------------------------------------------------
# Insight jobs
# ---------------------------------------------------------------------------


def _setup_insight_schedule(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Wire up interval/daily triggers and an initial run for an insight job."""
    opts = {**entry.data, **entry.options}

    async def _scheduled_run(_now=None) -> None:
        await _async_run_insight(hass, entry)

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


async def _async_run_insight(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Run one insight job: render prompt -> task channel -> sensor + event."""
    running = hass.data[DOMAIN].setdefault("_insights_running", set())
    if entry.entry_id in running:
        _LOGGER.debug("Insight '%s' already running — skipped", entry.title)
        return
    running.add(entry.entry_id)
    try:
        opts = {**entry.data, **entry.options}
        prompt_text = (opts.get(CONF_INSIGHT_PROMPT) or "").strip()
        if not prompt_text:
            template_key = opts.get(CONF_INSIGHT_TEMPLATE, "daily_briefing")
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

        # Context blocks: learned home memory + the previous report, so
        # recurring insights build on what's known instead of rediscovering
        # the house every run.
        prior = await hass.async_add_executor_job(
            load_insight_payload, hass, entry.entry_id
        )
        memory_text = await hass.async_add_executor_job(
            _read_text_capped,
            hass.config.path(SHARED_DIR, MEMORY_DIR, MEMORY_FILE),
            2048,
        )
        context_blocks = []
        if memory_text.strip():
            context_blocks.append(
                "Known about this home:\n" + memory_text.strip()
            )
        prev_markdown = ((prior or {}).get("markdown") or "").strip()
        if prev_markdown:
            context_blocks.append(
                "Previous report (for continuity, note meaningful changes "
                "rather than rediscovering):\n" + prev_markdown[:1536]
            )
        if context_blocks:
            prompt = "\n\n".join(context_blocks) + "\n\n" + prompt

        bridge = _get_bridge(hass)
        timeout = opts.get(CONF_TIMEOUT) or DEFAULT_INSIGHT_TIMEOUT
        model = opts.get(CONF_MODEL) or "default"
        started = time.monotonic()
        payload: dict
        try:
            result = await bridge.async_send_task(
                prompt=prompt, timeout=timeout, model=model
            )
            payload = {
                "markdown": truncate_markdown(result),
                "last_success": dt_util.utcnow().isoformat(),
                "duration_s": round(time.monotonic() - started, 1),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001 — surface failure on the sensor
            payload = {
                "duration_s": round(time.monotonic() - started, 1),
                "error": str(exc),
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
                "notification_id": f"bruh_claude_insight_{entry.entry_id}",
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
    raise ValueError("BRUH Claude integration is not configured")


def _register_services(hass: HomeAssistant) -> None:
    """Register bruh_claude services."""

    async def handle_send_prompt(call: ServiceCall):
        bridge = _get_bridge(hass)
        prompt = call.data["prompt"]
        timeout = call.data.get("timeout")

        try:
            result = await bridge.async_send_conversation(
                text=prompt, timeout=timeout, model=call.data.get("model")
            )
        except TimeoutError:
            result = "Claude did not respond in time."

        return {"response": result}

    async def handle_run_task(call: ServiceCall):
        bridge = _get_bridge(hass)
        prompt = call.data["prompt"]
        notify = call.data.get("notify", False)
        notify_entity = call.data.get("notify_entity")
        timeout = call.data.get("timeout")

        try:
            result = await bridge.async_send_task(
                prompt=prompt,
                notify=notify,
                notify_entity=notify_entity,
                timeout=timeout,
            )
        except TimeoutError:
            result = "Claude task did not complete in time."

        return {"response": result}

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
            hass.async_create_task(_async_run_insight(hass, e))

    async def handle_clear_conversation(call: ServiceCall):
        bridge = _get_bridge(hass)
        conversation_id = call.data.get("conversation_id")
        await bridge.async_clear_conversation(conversation_id)
        _LOGGER.info(
            "Cleared conversation session: %s",
            conversation_id or "ALL",
        )

    async def handle_add_memory(call: ServiceCall):
        memory_dir = hass.config.path(SHARED_DIR, MEMORY_DIR)
        await hass.async_add_executor_job(
            _append_memory_fact,
            memory_dir,
            call.data["fact"],
            call.data.get("source", "service"),
            call.data.get("confidence", "medium"),
        )
        _LOGGER.debug("Queued memory fact from %s", call.data.get("source"))

    async def handle_answer_question(call: ServiceCall):
        memory_dir = hass.config.path(SHARED_DIR, MEMORY_DIR)
        await hass.async_add_executor_job(
            _append_question_answer,
            memory_dir,
            call.data["question"],
            call.data["answer"],
            call.data.get("source", "service"),
        )
        _LOGGER.debug("Recorded answer for memory question")

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

    # BRUH Power Tools: registry-management admin services (power_tools.py)
    async_register_power_tools(hass)
