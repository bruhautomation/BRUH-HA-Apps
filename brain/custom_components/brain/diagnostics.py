"""Diagnostics for the brAIn integration.

Home Assistant puts a *Download diagnostics* button on every integration's
page, and it is the button people already know how to find and the one
issue templates already ask for. Until now brAIn's did nothing. It now
returns the same bundle ``brain report`` writes, read from the files the
add-on publishes on the shared volume:

  * ``.brain/diagnostics.json`` — versions, options, the run journal's last
    day, findings and memory statistics, the producer scorecard, and the
    last house-checks pass (written by the panel, refreshed hourly and
    after every checks run)
  * ``.brain/findings_state.json`` — the open findings mirror
  * ``.brain/usage_limits.json`` — the usage tracker's status

Nothing here is a secret by construction (the add-on scrubs credential
shapes before it writes the diagnostics file, and the other two never held
any), and the config entry's own data goes through ``async_redact_data``
regardless, because a redaction that is skipped for a field "that can't
hold a token" is the one that misses the day it does.
"""

from __future__ import annotations

import json
import os
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

try:
    from homeassistant.components.diagnostics import async_redact_data
except ImportError:  # pragma: no cover — very old cores, or a partial stub
    def async_redact_data(data: Any, to_redact: Any) -> Any:  # type: ignore[misc]
        return data

from .const import DIAGNOSTICS_FILENAME, FINDINGS_STATE_FILENAME, SHARED_DIR
USAGE_FILENAME = "usage_limits.json"
# Any of these files hand-edited into something enormous must not stall
# the event loop's executor for long.
MAX_BYTES = 512 * 1024

TO_REDACT = {"token", "api_key", "access_token", "refresh_token", "password"}


def _read_json(path: str) -> Any:
    try:
        if os.path.getsize(path) > MAX_BYTES:
            return {"error": f"{os.path.basename(path)} is over {MAX_BYTES} bytes"}
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        return {"error": f"{os.path.basename(path)}: {exc}"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    base = hass.config.path(SHARED_DIR)

    def _read_all() -> dict[str, Any]:
        return {
            "addon": _read_json(os.path.join(base, DIAGNOSTICS_FILENAME)),
            "findings": _read_json(os.path.join(base, FINDINGS_STATE_FILENAME)),
            "usage": _read_json(os.path.join(base, USAGE_FILENAME)),
        }

    files = await hass.async_add_executor_job(_read_all)
    if files["addon"] is None:
        files["addon"] = {
            "error": "the add-on has not published diagnostics yet — is it "
                     "running? `brain report` in its terminal writes a fuller "
                     "bundle"}
    return {
        "entry": {
            "entry_id": entry.entry_id,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        **async_redact_data(files, TO_REDACT),
    }
