"""Saying in Repairs that BRUH Cooking's update waits on a restart (#1185).

BRUH Cooking's add-on copies a new bruh_cooking integration into /config and
writes what it deployed (`/config/.bruh_cooking/deployed.json`, a version and
the code's fingerprint); the integration Home Assistant loaded writes what it
loaded (`integration.json`) as it sets up. While the two differ, Home
Assistant is still running the older code. The add-on has no Home Assistant
API access, and bruh_cooking 0.1.10 raises its own Repairs issue only from
inside a loaded copy that has it, so the first restart after updating from an
older one could never be said by it. brAIn's integration is already loaded,
so it says it, and stands aside while BRUH Cooking's own issue is up.

The comparison is the one `ha_mcp_server._cooking_restart_owed` makes for
the cooking_status tool. That server is another process, so this is its own
small reader rather than an import. It differs in one place, which is the
add-on's run.sh rule: when the integration is loaded and its record carries
no fingerprint (written by a copy too old to write one), a restart is owed.
"""
from __future__ import annotations

import json
import os

ISSUE_ID = "cooking_restart_required"
COOKING_DOMAIN = "bruh_cooking"
# BRUH Cooking's own issue (its restart.py): while it is up, or dismissed by
# somebody, this one is not raised beside it.
COOKING_OWN_ISSUE = "restart_required"
SHARED_DIR = ".bruh_cooking"


def _read(path: str) -> dict:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def restart_owed(config_dir: str, loaded: bool) -> dict | None:
    """``{"version", "loaded"}`` when Home Assistant runs an older
    bruh_cooking than BRUH Cooking deployed, else None.

    ``loaded`` is whether Home Assistant has the integration loaded at all:
    one that is not loaded runs no old code, and loads the new copy when it
    is set up. No deployed record (BRUH Cooking not installed, or it never
    deployed) is nothing to say.
    """
    shared = os.path.join(config_dir, SHARED_DIR)
    deployed = _read(os.path.join(shared, "deployed.json"))
    want = deployed.get("fingerprint")
    if not loaded or not isinstance(want, str) or not want:
        return None
    record = _read(os.path.join(shared, "integration.json"))
    if record.get("fingerprint") == want:
        return None
    return {"version": str(deployed.get("version") or "") or "a newer version",
            "loaded": str(record.get("version") or "") or "an older version"}


async def async_check(hass, domain: str) -> None:
    """Raise or clear brAIn's issue for BRUH Cooking's restart."""
    from homeassistant.helpers import issue_registry as ir  # noqa: PLC0415

    owed = await hass.async_add_executor_job(
        restart_owed, hass.config.config_dir,
        COOKING_DOMAIN in hass.config.components)
    if owed and ir.async_get(hass).async_get_issue(
            COOKING_DOMAIN, COOKING_OWN_ISSUE) is not None:
        owed = None
    if owed is None:
        ir.async_delete_issue(hass, domain, ISSUE_ID)
        return
    ir.async_create_issue(
        hass, domain, ISSUE_ID,
        is_fixable=False, is_persistent=False,
        severity=ir.IssueSeverity.WARNING,
        translation_key=ISSUE_ID,
        translation_placeholders=owed)
