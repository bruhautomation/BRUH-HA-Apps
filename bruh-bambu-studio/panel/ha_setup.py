"""Getting the bruh_bambu integration set up without anybody hunting for it.

The add-on copies the integration into /config/custom_components, and Home
Assistant loads a custom integration only when it STARTS. So after the first
install (and after an update) nothing appears — no sensors, no services, no
card in the card picker — until Home Assistant is restarted, and then only
once somebody accepts the discovered integration under Devices & services.
Nothing on screen said so.

This closes both gaps from the panel, through the Supervisor's proxy to
Core's REST API:

* once Core knows the integration and no entry exists, it starts the config
  flow itself and finishes it (the flow asks nothing), so the integration is
  set up the moment Home Assistant has loaded it;
* while Core does not know it yet (or runs an older copy than the one on
  disk), it says a restart is needed — on the Printers tab, and once per
  version as a Home Assistant notification — and offers the restart as a
  press, never on its own.

The integration writes /config/.bruh_bambu/integration.json when it sets
up, which is how a running copy's version is read without asking Core.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger("bruh_bambu.ha_setup")

DOMAIN = "bruh_bambu"
SUPERVISOR = os.environ.get("BAMBU_SUPERVISOR_URL", "http://supervisor")
SHARED = Path(os.environ.get("BAMBU_SHARED", "/config/.bruh_bambu"))
DEPLOYED = Path(os.environ.get("BAMBU_INTEGRATION_DIR", "/config/custom_components/bruh_bambu"))
NOTIFIED = Path(os.environ.get("BAMBU_DATA", "/data")) / "restart_notified"
CHECK_EVERY_S = 60
TIMEOUT = 15

STATE: dict = {"checked_at": None, "deployed": None, "running": None, "entry": None,
               "restart_needed": False, "reason": "", "error": ""}
_last = 0.0


def _token() -> str:
    return os.environ.get("SUPERVISOR_TOKEN", "")


def _call(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{SUPERVISOR}{path}", data=data, method=method,
        headers={"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read().decode() or "null"
            return response.status, json.loads(raw)
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read().decode() or "null")
        except (ValueError, OSError):
            return exc.code, None


def deployed_version() -> str | None:
    try:
        return json.loads((DEPLOYED / "manifest.json").read_text()).get("version")
    except (OSError, ValueError):
        return None


def running_version() -> str | None:
    """The version Core last set the integration up with, as it wrote it."""
    try:
        return json.loads((SHARED / "integration.json").read_text()).get("version")
    except (OSError, ValueError):
        return None


def entries() -> list | None:
    """This integration's config entries, or None when Core could not be asked."""
    status, body = _call("GET", f"/core/api/config/config_entries/entry?domain={DOMAIN}")
    if status != 200 or not isinstance(body, list):
        return None
    return [e for e in body if isinstance(e, dict) and e.get("domain") == DOMAIN]


def create_entry() -> tuple[bool, str]:
    """Start the user flow and finish it. (created, why not)."""
    status, body = _call("POST", "/core/api/config/config_entries/flow",
                         {"handler": DOMAIN, "show_advanced_options": False})
    if status in (400, 404) or not isinstance(body, dict):
        message = (body or {}).get("message", "") if isinstance(body, dict) else ""
        if "handler" in str(message).lower() or status == 404:
            return False, "not_loaded"
        return False, str(message or f"HTTP {status}")
    if body.get("type") == "abort":
        return body.get("reason") == "already_configured", str(body.get("reason") or "")
    flow_id = body.get("flow_id")
    while body.get("type") == "form" and flow_id:
        status, body = _call("POST", f"/core/api/config/config_entries/flow/{flow_id}", {})
        if not isinstance(body, dict):
            return False, f"HTTP {status}"
    if body.get("type") == "create_entry":
        return True, ""
    return False, str(body.get("reason") or body.get("type") or f"HTTP {status}")


def notify_restart(version: str) -> None:
    """One Home Assistant notification per version, never one per check."""
    try:
        if NOTIFIED.read_text().strip() == version:
            return
    except OSError:
        pass  # never notified
    _call("POST", "/core/api/services/persistent_notification/create", {
        "notification_id": "bruh_bambu_restart",
        "title": "BRUH Bambu Studio: restart Home Assistant",
        "message": ("The BRUH Bambu Studio integration (" + version + ") is installed, and Home "
                    "Assistant loads it when it starts. Restart Home Assistant (Settings > "
                    "System > Restart) to get the printer sensors, camera, services and the "
                    "dashboard card. The add-on sets the integration up by itself afterwards."),
    })
    try:
        NOTIFIED.write_text(version)
    except OSError:
        pass  # notified again next boot, which is harmless


def check(force: bool = False) -> dict:
    """Run on the panel's timer: at most once a minute unless forced."""
    global _last
    if not force and time.time() - _last < CHECK_EVERY_S:
        return STATE
    _last = time.time()
    deployed, running = deployed_version(), running_version()
    STATE.update(checked_at=int(time.time()), deployed=deployed, running=running, error="")
    if os.environ.get("ENABLE_HA_INTEGRATION", "true") != "true":
        STATE.update(restart_needed=False, reason="disabled", entry=None)
        return STATE
    if not _token() or deployed is None:
        STATE.update(restart_needed=False, reason="no_supervisor" if not _token() else "not_deployed")
        return STATE
    try:
        found = entries()
        if found is None:
            STATE.update(error="Home Assistant did not answer about its integrations.")
            return STATE
        if not found:
            created, why = create_entry()
            if created:
                log.info("Set up the bruh_bambu integration in Home Assistant")
                found = entries() or []
            elif why == "not_loaded":
                STATE.update(entry=None, restart_needed=True, reason="not_loaded")
                notify_restart(deployed)
                return STATE
            else:
                STATE.update(error=f"Home Assistant would not set the integration up: {why}")
        entry = found[0] if found else None
        STATE["entry"] = {"state": entry.get("state"), "entry_id": entry.get("entry_id")} if entry else None
        stale = bool(running and deployed and running != deployed)
        STATE.update(restart_needed=stale, reason="update" if stale else "")
        if stale:
            notify_restart(deployed)
    except (OSError, ValueError) as exc:
        STATE["error"] = f"Could not reach Home Assistant: {exc}"
    return STATE


def restart_core() -> tuple[bool, str]:
    """Home Assistant's own restart service: the Supervisor's /core/restart
    needs a role this add-on does not ask for, and the service is the same
    restart the Settings menu runs (it checks the configuration first)."""
    status, body = _call("POST", "/core/api/services/homeassistant/restart", {})
    if status == 200:
        return True, ""
    return False, (body or {}).get("message", f"HTTP {status}") if isinstance(body, dict) else f"HTTP {status}"


def status() -> dict:
    return {**STATE, "lovelace_card": Path("/config/www/bruh_bambu/bruh-bambu-card.js").is_file(),
            "morph_installed": Path("/config/morph").is_dir(),
            "morph_card": Path("/config/morph/cards/bruh-bambu-printer.js").is_file()}
