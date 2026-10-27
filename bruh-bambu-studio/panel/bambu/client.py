"""One live MQTT session per printer.

The printer is the broker (port 8883, TLS, user `bblp`, password = the
access code shown on its screen under LAN settings), so there is nothing to
install and nothing in the cloud: this connects, subscribes to the report
topic, asks for a `pushall`, and merges every delta that follows into one
status.

paho runs its own network thread (`loop_start`), so nothing here blocks the
panel's event loop; the panel reads `summary()` and calls `send()`. paho
1.x and 2.x construct differently, and Debian ships 1.6 while pip ships 2.x,
so `_make_client` tries the 2.x signature first.

Newer firmware also requires LAN-only mode and Developer mode on the
printer before a third-party client may CONTROL it (it will still report
status without). A command the printer ignores looks identical to one it
obeyed, so `send` returns the request's sequence id and the panel reads the
printer's echo off the report to say which happened.
"""
from __future__ import annotations

import json
import logging
import ssl
import threading
import time

from . import protocol

try:
    import paho.mqtt.client as mqtt
except ImportError:  # pragma: no cover - the image ships python3-paho-mqtt
    mqtt = None

LOG = logging.getLogger("bruh_bambu.mqtt")
PORT = 8883
# A P1/A1 is documented to stall if asked for a full report more often than
# every few minutes; the deltas keep the status current in between.
PUSHALL_EVERY_S = 300
# No report for this long while connected means the session is not
# hearing the printer even though the socket is up.
STALE_AFTER_S = 120
ECHO_WAIT_S = 8
# Firmware with Bambu's authorization echoes an unsigned command like any
# other and then raises protocol.COMMAND_REFUSED_HMS in its next report, so
# a command is not called done until this long after it was sent.
REFUSAL_WAIT_S = 4


class CommandRefused(RuntimeError):
    """The printer said no to a command (its echo, or the verification HMS)."""


def _make_client(client_id: str):
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=client_id,
                           protocol=mqtt.MQTTv311)
    except (AttributeError, TypeError):
        return mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)


class PrinterClient:
    def __init__(self, host: str, serial: str, access_code: str, model: str = ""):
        self.host, self.serial, self.code = host, serial, access_code
        # The saved model: it says whether the AMS is an AMS Lite.
        self.model = model
        self.status: dict = {}
        self.connected = False
        self.last_report = 0.0
        self.last_error = ""
        self._lock = threading.Lock()
        self._seq = int(time.time()) % 100000
        self._echoes: dict[str, dict] = {}
        # When a report last carried the command-refused HMS entry.
        self._refused_at = 0.0
        self._last_pushall = 0.0
        self._client = None

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> None:
        if mqtt is None:
            self.last_error = "paho-mqtt is not installed in this image."
            return
        client = _make_client(f"bruh-bambu-{self.serial[-6:]}-{int(time.time())}")
        client.username_pw_set("bblp", self.code)
        context = ssl.create_default_context()
        # The printer's certificate is self-signed per device; the access
        # code is what authenticates, as it is for Bambu Studio on a LAN.
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        client.tls_set_context(context)
        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message
        client.reconnect_delay_set(min_delay=2, max_delay=60)
        self._client = client
        try:
            client.connect_async(self.host, PORT, keepalive=30)
        except (OSError, ValueError) as exc:
            self.last_error = f"Could not reach {self.host}: {exc}"
        client.loop_start()

    def stop(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            finally:
                self._client.loop_stop()
        self._client = None
        self.connected = False

    # -- paho callbacks (its thread) ---------------------------------------
    def _on_connect(self, client, _userdata, _flags, rc, *_):
        code = getattr(rc, "value", rc)
        if code != 0:
            self.connected = False
            self.last_error = {
                4: "The printer refused the access code.",
                5: "The printer refused the connection (is LAN-only mode on?).",
            }.get(code, f"The printer refused the connection (code {code}).")
            LOG.warning("%s (%s): %s", self.serial, self.host, self.last_error)
            return
        self.connected = True
        self.last_error = ""
        client.subscribe(f"device/{self.serial}/report")
        self._publish(protocol.pushall())

    def _on_disconnect(self, _client, _userdata, rc, *_):
        self.connected = False
        code = getattr(rc, "value", rc)
        if code:
            self.last_error = f"Lost the connection to the printer (code {code})."
            LOG.info("%s (%s): %s", self.serial, self.host, self.last_error)

    def _on_message(self, _client, _userdata, message):
        try:
            report = json.loads(message.payload.decode("utf-8", "replace"))
        except ValueError:
            return  # a frame that is not JSON carries no status
        if not isinstance(report, dict):
            return
        with self._lock:
            protocol.deep_merge(self.status, report)
            self.last_report = time.time()
            section = report.get("print")
            if isinstance(section, dict) and isinstance(section.get("hms"), list) and any(
                    isinstance(h, dict) and protocol.hms_code(h) == protocol.COMMAND_REFUSED_HMS
                    for h in section["hms"]):
                self._refused_at = time.time()
            for section in report.values():
                if isinstance(section, dict) and "sequence_id" in section:
                    self._echoes[str(section["sequence_id"])] = section
            if len(self._echoes) > 64:
                for key in list(self._echoes)[:-32]:
                    self._echoes.pop(key, None)

    # -- the panel's half --------------------------------------------------
    def _publish(self, payload: dict) -> str:
        with self._lock:
            self._seq += 1
            seq = str(self._seq)
        if self._client is None:
            raise ConnectionError("Not connected to the printer.")
        self._client.publish(f"device/{self.serial}/request",
                             protocol.request(payload, int(seq)))
        if "pushing" in payload:
            self._last_pushall = time.time()
        return seq

    def send(self, payload: dict) -> dict:
        """Publish one request and wait briefly for the printer's echo.

        The echo carries `result` ("success"/"fail") and sometimes `reason`.
        No echo is reported as such — not as a success. An echo is not the
        last word: the verification HMS raised after it (REFUSAL_WAIT_S) is
        a refusal, raised as CommandRefused naming Developer Mode.
        """
        if not self.connected:
            raise ConnectionError(self.last_error or "Not connected to the printer.")
        sent = time.time()
        seq = self._publish(payload)
        echo = None
        while True:
            with self._lock:
                if echo is None:
                    echo = self._echoes.pop(seq, None)
                refused = self._refused_at >= sent
            if refused:
                raise CommandRefused(protocol.COMMAND_REFUSED)
            if echo is not None and str(echo.get("result") or "").lower() == "fail":
                reason = echo.get("reason") or echo.get("err_code") or "no reason given"
                raise CommandRefused(f"The printer refused it: {reason}")
            now = time.time()
            if echo is not None and now - sent >= min(REFUSAL_WAIT_S, ECHO_WAIT_S):
                return {"acknowledged": True,
                        "result": str(echo.get("result") or "").lower() or "ok"}
            if now - sent >= ECHO_WAIT_S:
                return {"acknowledged": False}
            time.sleep(0.1)

    def tick(self) -> None:
        """Called on the panel's timer: an occasional full report."""
        if self.connected and time.time() - self._last_pushall > PUSHALL_EVERY_S:
            try:
                self._publish(protocol.pushall())
            except ConnectionError:
                pass  # the reconnect will ask on its own

    def summary(self) -> dict:
        with self._lock:
            status = json.loads(json.dumps(self.status))
            last = self.last_report
        out = protocol.summarise(status, model=self.model, serial=self.serial)
        stale = bool(last) and time.time() - last > STALE_AFTER_S
        out["online"] = self.connected and not stale
        out["last_report"] = last or None
        out["connection_error"] = self.last_error or (
            "Connected, but the printer has stopped reporting." if self.connected and stale else "")
        return out
