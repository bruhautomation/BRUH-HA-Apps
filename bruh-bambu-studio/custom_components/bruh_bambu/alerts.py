"""Telling somebody a print is going wrong, and taking their answer back.

The add-on decides; this only delivers. Each new alert in the state mirror
(print failure detection's `alert`, per printer) becomes:

* a Home Assistant notification, always, so it is in the bell whatever else
  is set up;
* a `bruh_bambu_print_alert` event, for an automation that wants to flash a
  light or speak;
* a message to the notify service chosen on the panel (a phone), with the
  frame brAIn judged as its picture and buttons that answer it — Ignore and
  Pause for a warning, Resume (a false alarm) and Stop for a print that was
  paused.

A button press comes back as `mobile_app_notification_action` and is
forwarded to the add-on as `print_alert_action`, naming the alert it
answers, so a press on yesterday's notification is refused rather than
applied to today's print. An alert that closes (answered on the panel, the
next look found the print fine, the print finished) takes its notification
with it.

Alerts already open when Home Assistant starts are not sent again: a
restart is not news.
"""
from __future__ import annotations

import logging
import time

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .const import ALERT_ACTION_PREFIX, ALERT_TAG, DOMAIN, SERVICE_ALERT_ACTION

_LOGGER = logging.getLogger(__name__)
EVENT = "bruh_bambu_print_alert"
# An alert older than this when the integration first sees it was raised
# before Home Assistant started, and was delivered then.
FRESH_S = 180

BUTTONS = {
    "warning": [("ignore", "Ignore"), ("pause", "Pause print")],
    "failure": [("resume", "Resume — not a failure"), ("stop", "Stop print")],
    "failure_unpaused": [("pause", "Pause print"), ("ignore", "Ignore")],
}


def parse_action(action: str) -> tuple[str, str, str] | None:
    """(action, printer, alert) out of a button's id, or None if not ours."""
    parts = str(action or "").split(":")
    if len(parts) != 4 or parts[0] != ALERT_ACTION_PREFIX:
        return None
    _, verb, pid, alert = parts
    if verb not in {v for buttons in BUTTONS.values() for v, _ in buttons} or not pid:
        return None
    return verb, pid, alert


def message_for(name: str, alert: dict) -> tuple[str, str, str]:
    """(title, message, which buttons) for one alert."""
    summary = alert.get("summary") or "Something looks wrong with the print."
    if alert.get("level") == "failure":
        if alert.get("paused"):
            return (f"{name}: print paused", f"{summary} The print was paused so you can look. "
                    "Resume it if this is a false alarm.", "failure")
        why = f" {alert['pause_error']}" if alert.get("pause_error") else ""
        return (f"{name}: print looks failed", f"{summary}{why}", "failure_unpaused")
    return (f"{name}: print may be failing", summary, "warning")


class AlertNotifier:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator, forward) -> None:
        self.hass, self.entry, self.coordinator, self.forward = hass, entry, coordinator, forward
        self.sent: dict[str, str] = {}  # printer id -> alert id we delivered
        self.started = time.time()

    def start(self):
        remove_listener = self.coordinator.async_add_listener(self._update)
        remove_bus = self.hass.bus.async_listen("mobile_app_notification_action", self._action)
        self._update()

        def stop() -> None:
            remove_listener()
            remove_bus()
        return stop

    @callback
    def _update(self) -> None:
        data = self.coordinator.data or {}
        if not data.get("available"):
            return
        target = str((data.get("watch") or {}).get("notify") or "")
        for printer in data.get("printers") or []:
            pid = printer.get("id")
            watch = printer.get("failure_detection") or {}
            alert = watch.get("alert") or {}
            open_id = alert.get("id") if alert.get("open") else None
            known = self.sent.get(pid)
            if open_id and open_id != known:
                self.sent[pid] = open_id
                if (alert.get("at") or 0) >= self.started - FRESH_S:
                    self.hass.async_create_task(self._send(printer, alert, target))
            elif known and not open_id:
                self.sent.pop(pid, None)
                self.hass.async_create_task(self._clear(pid, target))

    def _camera_entity(self, pid: str) -> str | None:
        return er.async_get(self.hass).async_get_entity_id(
            "camera", DOMAIN, f"{self.entry.entry_id}_{pid}_last_check")

    async def _send(self, printer: dict, alert: dict, target: str) -> None:
        pid = printer["id"]
        name = printer.get("name") or pid
        title, message, kind = message_for(name, alert)
        self.hass.bus.async_fire(EVENT, {
            "printer": pid, "printer_name": name, "alert": alert.get("id"),
            "level": alert.get("level"), "problem": alert.get("problem"),
            "summary": alert.get("summary"), "paused": bool(alert.get("paused"))})
        try:
            await self.hass.services.async_call("persistent_notification", "create", {
                "title": title, "message": message, "notification_id": f"{ALERT_TAG}{pid}"},
                blocking=False)
        except HomeAssistantError as exc:
            _LOGGER.warning("Could not raise the print alert notification: %s", exc)
        if not target.startswith("notify."):
            return
        service = target.split(".", 1)[1]
        if not self.hass.services.has_service("notify", service):
            _LOGGER.warning("The print alert's notify service %s does not exist", target)
            return
        data = {"tag": f"{ALERT_TAG}{pid}", "group": "bruh_bambu",
                "actions": [{"action": f"{ALERT_ACTION_PREFIX}:{verb}:{pid}:{alert.get('id')}",
                             "title": label} for verb, label in BUTTONS[kind]]}
        camera = self._camera_entity(pid)
        if camera and alert.get("image"):
            data["image"] = f"/api/camera_proxy/{camera}"
        if alert.get("level") == "failure":
            data["push"] = {"interruption-level": "time-sensitive"}
            data["priority"] = "high"
        try:
            await self.hass.services.async_call("notify", service, {
                "title": title, "message": message, "data": data}, blocking=False)
        except HomeAssistantError as exc:
            _LOGGER.warning("Could not send the print alert to %s: %s", target, exc)

    async def _clear(self, pid: str, target: str) -> None:
        try:
            await self.hass.services.async_call("persistent_notification", "dismiss", {
                "notification_id": f"{ALERT_TAG}{pid}"}, blocking=False)
        except HomeAssistantError:
            pass  # a notification already gone needs no dismissing
        if target.startswith("notify.") and self.hass.services.has_service("notify", target[7:]):
            try:
                await self.hass.services.async_call("notify", target[7:], {
                    "message": "clear_notification", "data": {"tag": f"{ALERT_TAG}{pid}"}},
                    blocking=False)
            except HomeAssistantError:
                pass  # a phone that cannot be told keeps a stale alert, nothing worse

    async def _action(self, event: Event) -> None:
        parsed = parse_action((event.data or {}).get("action"))
        if parsed is None:
            return
        verb, pid, alert = parsed
        try:
            await self.forward(SERVICE_ALERT_ACTION, {"printer": pid, "action": verb, "alert": alert})
        except HomeAssistantError as exc:
            await self.hass.services.async_call("persistent_notification", "create", {
                "title": "BRUH Bambu Studio", "message": f"Could not {verb} the print: {exc}",
                "notification_id": f"{ALERT_TAG}{pid}_answer"}, blocking=False)
