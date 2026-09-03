#!/usr/bin/env python3
"""Getting the bytes to the printer, and saying why when they don't arrive.

pyusb is imported lazily and its absence is a *reported state*, not an
exception at import: the panel has to be able to start, render, and explain
itself on a machine with no libusb at all — that is the dev checkout, and it
is also every screenshot in the docs. A panel that will not boot without a
printer attached is a panel nobody can set a template up on.

Every failure here is a sentence rather than a code. `LIBUSB_ERROR_ACCESS`
means the container cannot open the device node, which on a Home Assistant
add-on means `usb: true` is missing from config.yaml or the Supervisor has
not restarted the add-on since it was added; `LIBUSB_ERROR_BUSY` means the
kernel's usblp driver has claimed it first, which this module then detaches
and takes back. Both are things a person can act on and neither is guessable
from a stack trace.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from . import printers, protocol

log = logging.getLogger("bruh_print.usb")

# Bulk transfers are chunked. A full 4" label is ~100 KB after compression
# and libusb will happily take it in one call, but a single huge transfer
# that times out tells you nothing about how far it got; 16 KB chunks turn a
# stall into "wrote 3 of 7 chunks", which is the difference between "the
# printer is off" and "the printer stopped halfway".
CHUNK = 16 * 1024
WRITE_TIMEOUT_MS = 15_000
READ_TIMEOUT_MS = 2_000

# One printer, one job at a time. The panel is async and the Lovelace card,
# the panel and an automation can all press print within the same second;
# two interleaved bulk writes to one endpoint is a label with another
# label's raster in the middle of it.
_bus_lock = threading.Lock()


class UsbUnavailable(RuntimeError):
    """libusb or pyusb is not usable in this container."""


class PrinterNotFound(RuntimeError):
    """No DYMO on the bus, or not the one that was asked for."""


class PrinterBusy(RuntimeError):
    """The device is there and something else owns it."""


def _usb() -> Any:
    try:
        import usb.core  # noqa: PLC0415
        import usb.util  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover - depends on the image
        raise UsbUnavailable(
            "pyusb is not installed in this container, so no USB printer can "
            "be reached. This is expected in a dev checkout; on a real "
            "install it means the add-on image is broken."
        ) from exc
    return usb


def available() -> bool:
    """Whether USB can be used at all — asked before it is blamed."""
    try:
        _usb()
    except UsbUnavailable:
        return False
    return True


def _string(device: Any, index: int) -> str:
    """A USB string descriptor, or "".

    Reading one needs the device opened, which is exactly what fails on a
    permissions problem — and a discovery pass that raises on the first
    device with a locked-down node reports *no printers* when the truth is
    "one printer, no access". So this swallows and the caller reports the
    claim error separately.
    """
    if not index:
        return ""
    try:
        import usb.util  # noqa: PLC0415
        return (usb.util.get_string(device, index) or "").strip()
    except Exception:  # noqa: BLE001 - any failure means "could not read"
        return ""


def discover() -> list[printers.Discovered]:
    """Every DYMO on the bus, in a stable order.

    Sorted by (bus, address) so the panel's list does not reshuffle between
    polls — a printer picker whose rows move while you are reaching for one
    is a picker that prints on the wrong roll.
    """
    usb = _usb()
    found: list[printers.Discovered] = []
    for device in usb.core.find(find_all=True,
                                idVendor=printers.DYMO_VENDOR_ID) or []:
        product = _string(device, getattr(device, "iProduct", 0))
        serial = _string(device, getattr(device, "iSerialNumber", 0))
        model, recognised = printers.describe(device.idProduct, product)
        found.append(printers.Discovered(
            product_id=device.idProduct,
            model=model,
            serial=serial,
            bus=getattr(device, "bus", 0) or 0,
            address=getattr(device, "address", 0) or 0,
            recognised=recognised,
            claim_error="" if product or not serial else "",
        ))
    found.sort(key=lambda d: (d.bus, d.address))
    return found


def _find_device(key: str | None) -> tuple[Any, printers.Discovered]:
    usb = _usb()
    candidates = discover()
    if not candidates:
        raise PrinterNotFound(
            "No DYMO printer is on the USB bus. Check the cable and the "
            "power brick — a LabelWriter with no power does not enumerate — "
            "then confirm the add-on has USB access (Settings > Add-ons > "
            "BRUH Print > restart after enabling it)."
        )

    chosen = None
    if key:
        chosen = next((c for c in candidates if c.key == key), None)
        if chosen is None:
            names = ", ".join(c.key for c in candidates)
            raise PrinterNotFound(
                f"The saved printer ({key}) is not plugged in. What is "
                f"connected: {names}. Pick it again in the Printer tab, or "
                f"plug the other one back in."
            )
    else:
        chosen = candidates[0]

    device = usb.core.find(
        idVendor=printers.DYMO_VENDOR_ID,
        idProduct=chosen.product_id,
        custom_match=lambda d: (getattr(d, "bus", 0) or 0) == chosen.bus
        and (getattr(d, "address", 0) or 0) == chosen.address,
    )
    if device is None:  # pragma: no cover - lost between discover and here
        raise PrinterNotFound(
            f"{chosen.model.name} disappeared from the bus between being "
            f"listed and being opened — try again.")
    return device, chosen


class Link:
    """An open, claimed printer. Use it as a context manager.

    Claiming is the part that goes wrong in practice, and it goes wrong in
    two ways with the same symptom. The kernel's `usblp` driver binds
    LabelWriters on sight, so the interface is already claimed by the host
    before this container ever looks; `detach_kernel_driver` takes it back,
    and it is re-attached on the way out so the host's own CUPS (if anybody
    has one) is not left broken by our having printed. And a device node the
    container may not open raises ACCESS, which is the `usb: true` case and
    is worded as such.
    """

    def __init__(self, key: str | None = None):
        self._key = key
        self._usb = _usb()
        self.device: Any = None
        self.info: printers.Discovered | None = None
        self._interface = 0
        self._detached = False
        self._out = None
        self._in = None

    # -- lifecycle ---------------------------------------------------------
    def open(self) -> "Link":
        self.device, self.info = _find_device(self._key)
        try:
            config = self.device.get_active_configuration()
        except Exception:  # noqa: BLE001 - unconfigured device
            try:
                self.device.set_configuration()
                config = self.device.get_active_configuration()
            except Exception as exc:  # noqa: BLE001
                raise self._explain(exc) from exc

        interface = config[(0, 0)]
        self._interface = interface.bInterfaceNumber

        try:
            if self.device.is_kernel_driver_active(self._interface):
                self.device.detach_kernel_driver(self._interface)
                self._detached = True
        except NotImplementedError:
            # Not every backend can answer this; on those, claiming either
            # works or fails below with a sentence of its own.
            pass
        except Exception as exc:  # noqa: BLE001
            raise self._explain(exc) from exc

        self._out = self._endpoint(interface, out=True)
        self._in = self._endpoint(interface, out=False)
        if self._out is None:
            raise PrinterNotFound(
                f"{self.info.model.name} has no bulk OUT endpoint, which "
                f"means it is not in printing mode. Unplug it, wait for the "
                f"light to go out, and plug it back in.")
        return self

    def _endpoint(self, interface: Any, *, out: bool) -> Any:
        usb = self._usb
        wanted = (usb.util.ENDPOINT_OUT if out else usb.util.ENDPOINT_IN)
        for endpoint in interface:
            direction = usb.util.endpoint_direction(endpoint.bEndpointAddress)
            kind = usb.util.endpoint_type(endpoint.bmAttributes)
            if direction == wanted and kind == usb.util.ENDPOINT_TYPE_BULK:
                return endpoint
        return None

    def close(self) -> None:
        if self.device is None:
            return
        try:
            self._usb.util.dispose_resources(self.device)
        except Exception:  # noqa: BLE001
            pass
        if self._detached:
            try:
                self.device.attach_kernel_driver(self._interface)
            except Exception:  # noqa: BLE001 - best effort, never fatal
                pass
        self.device = None

    def __enter__(self) -> "Link":
        return self.open()

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # -- io ----------------------------------------------------------------
    def write(self, payload: bytes) -> int:
        """Send a job, in chunks, and say how far it got if it stops."""
        written = 0
        total = len(payload)
        for offset in range(0, total, CHUNK):
            chunk = payload[offset:offset + CHUNK]
            try:
                written += self._out.write(chunk, WRITE_TIMEOUT_MS)
            except Exception as exc:  # noqa: BLE001
                raise self._explain(
                    exc,
                    prefix=f"Sent {written} of {total} bytes before the "
                           f"printer stopped accepting them",
                ) from exc
        return written

    def status(self) -> protocol.Status:
        """Ask the printer how it is. Silence is an answer of its own.

        A LabelWriter that is mid-feed does not reply, and neither does one
        whose firmware predates the status command — so a timeout here is
        `answered=False` rather than a raised error. The caller renders that
        as "no status reported", which is honest, where rendering it as
        ready would be the panel inventing good news.
        """
        if self._in is None:
            return protocol.Status(answered=False)
        try:
            self._out.write(protocol.status_request(), WRITE_TIMEOUT_MS)
            block = self._in.read(32, READ_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 - timeout is the ordinary case
            return protocol.Status(answered=False)
        return protocol.parse_status(bytes(block))

    # -- errors ------------------------------------------------------------
    def _explain(self, exc: Exception, prefix: str = "") -> Exception:
        text = str(exc)
        name = self.info.model.name if self.info else "The printer"
        head = f"{prefix}. " if prefix else ""
        if "ACCESS" in text or "Access denied" in text or "Permission" in text:
            return PrinterBusy(
                f"{head}{name} is connected but this add-on may not open it. "
                f"That is a permissions answer from the kernel, not a printer "
                f"fault: BRUH Print needs USB access, which the Supervisor "
                f"only grants on a restart after it is enabled. Restart the "
                f"add-on; if it persists, check that Protection mode is off "
                f"is NOT required — this add-on does not need it — and that "
                f"the printer is not claimed by another add-on."
            )
        if "BUSY" in text or "Resource busy" in text:
            return PrinterBusy(
                f"{head}{name} is claimed by something else on this machine. "
                f"If you run a CUPS or print-server add-on, stop it, or "
                f"unbind the printer there — two drivers cannot own one "
                f"LabelWriter."
            )
        if "TIMEOUT" in text or "timed out" in text.lower():
            return PrinterBusy(
                f"{head}{name} stopped responding. The usual cause is the lid "
                f"being open or the roll having run out mid-job — check both, "
                f"then press the form-feed button on the printer once and try "
                f"again."
            )
        if "NO_DEVICE" in text or "No such device" in text:
            return PrinterNotFound(
                f"{head}{name} was unplugged while the job was running.")
        return PrinterBusy(f"{head}{name} refused the job: {text}")


def send(payload: bytes, key: str | None = None) -> dict:
    """Open, write, read status, close — under the one-job-at-a-time lock."""
    with _bus_lock:
        with Link(key) as link:
            written = link.write(payload)
            status = link.status()
            info = link.info
    return {
        "bytes": written,
        "printer": info.as_dict() if info else {},
        "status": status.summary,
        "status_ok": status.ok,
        "status_answered": status.answered,
    }


def probe(key: str | None = None) -> dict:
    """Status only — the panel's "is it ready" without printing anything."""
    with _bus_lock:
        with Link(key) as link:
            status = link.status()
            info = link.info
    return {
        "printer": info.as_dict() if info else {},
        "status": status.summary,
        "status_ok": status.ok,
        "status_answered": status.answered,
    }
