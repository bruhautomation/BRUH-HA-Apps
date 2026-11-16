"""Saying, in Home Assistant, that it still runs an older copy of this integration.

Home Assistant loads a custom integration's code when it starts and never
again. The add-on copies a new release into /config when it updates and says
in its own log that a restart is owed, and nobody reads that log: an update
could sit on disk for days while the older code went on answering, so a fix
looked as if it had not worked. So the copy Home Assistant loaded checks the
copy on disk (by `fingerprint`, the rule the add-on's run.sh uses) and raises
a Repairs issue while they differ. The issue is not persistent: the restart
that loads the new code is what clears it.
"""

from __future__ import annotations

from datetime import timedelta
import json
import os

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval

from .const import DOMAIN
from .fingerprint import LOADED_FINGERPRINT, fingerprint

ISSUE_ID = "restart_required"
# The add-on deploys at its start and then every ten minutes.
RESTART_CHECK = timedelta(minutes=5)
_HERE = os.path.dirname(os.path.abspath(__file__))


def _on_disk() -> tuple[str | None, str | None]:
    """The fingerprint and manifest version of the copy on disk now."""
    try:
        with open(os.path.join(_HERE, "manifest.json"), encoding="utf-8") as fh:
            version = json.load(fh).get("version")
    except (OSError, ValueError, AttributeError):
        version = None
    return fingerprint(_HERE), version if isinstance(version, str) else None


async def async_check_restart(hass: HomeAssistant, loaded_version: str | None) -> None:
    """Raise the Repairs issue while the code on disk differs from the code running."""
    on_disk, version = await hass.async_add_executor_job(_on_disk)
    if on_disk is None:
        # Unreadable, or the add-on is copying it right now: say nothing yet.
        return
    if on_disk != LOADED_FINGERPRINT:
        ir.async_create_issue(
            hass,
            DOMAIN,
            ISSUE_ID,
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key=ISSUE_ID,
            translation_placeholders={
                "version": version or "a newer version",
                "loaded": loaded_version or "an older version",
            },
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)


@callback
def async_watch_restart(hass: HomeAssistant, loaded_version: str | None) -> None:
    """Check now and every RESTART_CHECK until Home Assistant stops."""

    async def check(_now=None) -> None:
        await async_check_restart(hass, loaded_version)

    hass.async_create_task(check(), f"{DOMAIN} restart check")
    async_track_time_interval(hass, check, RESTART_CHECK, cancel_on_shutdown=True)
