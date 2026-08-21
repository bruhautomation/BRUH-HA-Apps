"""LIFX LAN protocol packets, serialized by hand.

Why not aiolifx for this: the playback engine's whole job is to put a
pre-serialized datagram on the wire at a precise moment. aiolifx wraps
every send in discovery/retry machinery that is right for a lighting
integration and wrong for a cue scheduler — so the wire format lives here,
36-byte header plus typed payloads, little-endian throughout, and the
tests pin it byte-for-byte against the protocol documentation's own
example packet.

Everything here is pure functions over bytes. No sockets, no clocks.
"""
from __future__ import annotations

import struct

# Message types (the ones BRight speaks).
GET_SERVICE = 2
STATE_SERVICE = 3
GET_LABEL = 23
STATE_LABEL = 25
GET_VERSION = 32
STATE_VERSION = 33
ACKNOWLEDGEMENT = 45
ECHO_REQUEST = 58
ECHO_RESPONSE = 59
GET_COLOR = 101
SET_COLOR = 102
SET_WAVEFORM = 103
LIGHT_STATE = 107
SET_WAVEFORM_OPTIONAL = 119
SET_LIGHT_POWER = 117

# Waveform shapes SetWaveform runs on the bulb itself.
WAVEFORM_SAW = 0
WAVEFORM_SINE = 1
WAVEFORM_HALF_SINE = 2
WAVEFORM_TRIANGLE = 3
WAVEFORM_PULSE = 4

LIFX_PORT = 56700

# Header: frame (size, flags, source), frame address (target, reserved,
# res/ack flags, sequence), protocol header (reserved, type, reserved).
_HEADER = struct.Struct("<HHI8s6sBBQHH")
HEADER_SIZE = _HEADER.size  # 36

_PROTOCOL = 1024
_ADDRESSABLE = 1 << 12
_TAGGED = 1 << 13

_SET_COLOR = struct.Struct("<BHHHHI")
_SET_WAVEFORM = struct.Struct("<BBHHHHIfhB")
# SetWaveformOptional is SetWaveform plus one flag per HSBK channel: the
# bulb runs the same routine but only touches the channels whose flag is
# set. That is the whole reason it is here — every effect BRight had
# modulated BRIGHTNESS, because a waveform that carries a colour carries
# all of it. With these flags a bulb can drift its hue while the
# brightness the scene chose stays exactly where it is.
_SET_WAVEFORM_OPTIONAL = struct.Struct("<BBHHHHIfhBBBBB")
_SET_LIGHT_POWER = struct.Struct("<HI")
_STATE_SERVICE = struct.Struct("<BI")
_STATE_VERSION = struct.Struct("<III")
_LIGHT_STATE = struct.Struct("<HHHHhH32sQ")


def build(msg_type: int, payload: bytes = b"", *, target: bytes = b"",
          tagged: bool = False, source: int = 0, sequence: int = 0,
          ack_required: bool = False, res_required: bool = False) -> bytes:
    """One complete datagram: header + payload.

    ``target`` is the device's 6-byte serial (empty = all devices, which is
    what a tagged broadcast wants). ``source`` identifies us so replies can
    be told apart from other clients' traffic; ``sequence`` is the per-send
    counter replies echo back.
    """
    if len(target) not in (0, 6, 8):
        raise ValueError(f"target must be 0, 6 or 8 bytes, got {len(target)}")
    flags = _PROTOCOL | _ADDRESSABLE | (_TAGGED if tagged else 0)
    flags2 = (1 if res_required else 0) | (2 if ack_required else 0)
    header = _HEADER.pack(
        HEADER_SIZE + len(payload),
        flags,
        source,
        target.ljust(8, b"\x00"),
        b"\x00" * 6,
        flags2,
        sequence & 0xFF,
        0,
        msg_type,
        0,
    )
    return header + payload


# The source field sits at bytes 4..8 of the frame (little-endian u32),
# right after `size` and `flags`.
_SOURCE_OFFSET = 4


def with_source(data: bytes, source: int) -> bytes:
    """`data` with its source field rewritten.

    The source id identifies THIS connection, and a compiled show is a file
    that outlives the process that compiled it — so the id cannot be part
    of what gets saved. Cue packets are pre-serialized at compile time and
    replayed weeks later; stamping the live id here, at the one place every
    outbound packet passes through, is what keeps a show portable between
    runs (and between installs) while letting the id itself be chosen
    freshly and unpredictably each time.

    Raises ValueError on a datagram too short to carry the field, rather
    than silently returning something that is not a LIFX packet.
    """
    if len(data) < _SOURCE_OFFSET + 4:
        raise ValueError("datagram shorter than a LIFX frame header")
    return (bytes(data[:_SOURCE_OFFSET])
            + struct.pack("<I", source & 0xFFFFFFFF)
            + bytes(data[_SOURCE_OFFSET + 4:]))


def parse_header(data: bytes) -> dict:
    """The fields a reply reader needs. Raises ValueError on a short/alien
    datagram — port 56700 hears other clients' traffic too."""
    if len(data) < HEADER_SIZE:
        raise ValueError("datagram shorter than a LIFX header")
    (size, flags, source, target, _resv, _flags2, sequence,
     _resv2, msg_type, _resv3) = _HEADER.unpack_from(data)
    if flags & 0xFFF != _PROTOCOL:
        raise ValueError("not LIFX protocol 1024")
    return {
        "size": size,
        "source": source,
        "target": target[:6],
        "sequence": sequence,
        "type": msg_type,
        "payload": data[HEADER_SIZE:size] if size <= len(data) else data[HEADER_SIZE:],
    }


# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------
def get_service(*, source: int = 0, sequence: int = 0) -> bytes:
    """Discovery broadcast. Tagged with no target = every device answers."""
    return build(GET_SERVICE, tagged=True, source=source, sequence=sequence,
                 res_required=True)


def get_label(**hdr) -> bytes:
    return build(GET_LABEL, res_required=True, **hdr)


def get_version(**hdr) -> bytes:
    return build(GET_VERSION, res_required=True, **hdr)


def get_color(**hdr) -> bytes:
    return build(GET_COLOR, res_required=True, **hdr)


def echo_request(blob: bytes, **hdr) -> bytes:
    """64-byte echo — the RTT probe. The bulb sends the blob straight back,
    so a unique blob per send matches responses to requests without
    trusting sequence numbers alone."""
    return build(ECHO_REQUEST, blob[:64].ljust(64, b"\x00"),
                 res_required=True, **hdr)


def set_color(hue: int, saturation: int, brightness: int, kelvin: int,
              duration_ms: int, **hdr) -> bytes:
    """HSBK move over ``duration_ms``. All four channels are u16 —
    hue 0..65535 maps 0..360 degrees."""
    payload = _SET_COLOR.pack(0, hue & 0xFFFF, saturation & 0xFFFF,
                              brightness & 0xFFFF, kelvin & 0xFFFF,
                              duration_ms & 0xFFFFFFFF)
    return build(SET_COLOR, payload, **hdr)


def set_waveform(*, transient: bool, hue: int, saturation: int,
                 brightness: int, kelvin: int, period_ms: int, cycles: float,
                 skew_ratio: int = 0, waveform: int = WAVEFORM_SINE,
                 **hdr) -> bytes:
    """A periodic effect the BULB runs — the sync trick. One datagram
    carries `cycles` beats of motion at `period_ms` per beat, executed
    locally, immune to network jitter for its whole run.

    ``skew_ratio`` (i16) shapes PULSE's duty cycle; ``transient`` means
    "return to the current color afterwards".
    """
    payload = _SET_WAVEFORM.pack(0, 1 if transient else 0, hue & 0xFFFF,
                                 saturation & 0xFFFF, brightness & 0xFFFF,
                                 kelvin & 0xFFFF, period_ms & 0xFFFFFFFF,
                                 float(cycles), skew_ratio, waveform)
    return build(SET_WAVEFORM, payload, **hdr)


def set_waveform_optional(*, transient: bool, hue: int, saturation: int,
                          brightness: int, kelvin: int, period_ms: int,
                          cycles: float, skew_ratio: int = 0,
                          waveform: int = WAVEFORM_SINE,
                          set_hue: bool = False, set_saturation: bool = False,
                          set_brightness: bool = False,
                          set_kelvin: bool = False, **hdr) -> bytes:
    """A waveform that moves only the channels you name.

    `set_waveform` above hands the bulb a whole HSBK colour to travel to,
    so every routine it can run is a brightness routine — which is why an
    audit of BRight's effects found thirteen of seventeen showing nothing
    but the palette's three colours, and only two moving brightness
    through more than two levels. The vocabulary was "which light is
    bright, and when".

    This is the same engine with a mask. Set `set_hue` alone and the bulb
    walks its hue around the wheel at the level the scene left it at —
    colour that moves without anything flickering, which no combination
    of the messages BRight already spoke could produce. It still costs one
    packet for the whole run, and it still executes on the bulb, so it
    keeps time through network jitter exactly as the others do.

    A routine with no flag set does nothing at all, which the caller is
    responsible for not asking for — the bulb will happily accept it.
    """
    payload = _SET_WAVEFORM_OPTIONAL.pack(
        0, 1 if transient else 0, hue & 0xFFFF, saturation & 0xFFFF,
        brightness & 0xFFFF, kelvin & 0xFFFF, period_ms & 0xFFFFFFFF,
        float(cycles), skew_ratio, waveform,
        1 if set_hue else 0, 1 if set_saturation else 0,
        1 if set_brightness else 0, 1 if set_kelvin else 0)
    return build(SET_WAVEFORM_OPTIONAL, payload, **hdr)


# How long the halting waveform below runs for. A bulb runs ONE waveform
# at a time, so sending another is what ends the one in flight; this one is
# over almost before it starts, which is the point.
HALT_PERIOD_MS = 20


def halt_waveform(*, hue: int = 0, saturation: int = 0, brightness: int = 0,
                  kelvin: int = 3500, **hdr) -> bytes:
    """Stop whatever this bulb is running, now.

    `SetWaveform` hands the bulb a routine it executes ON ITS OWN — that
    is the whole sync trick, and it is also why "stop the show" did not
    stop the lights: we stop sending, and a bulb three seconds into a
    forty-cycle strobe carries on strobing to the end. Nothing we stop
    doing can reach it.

    A bulb runs one waveform at a time, so the way to end one is to send
    another. This is that other: a single cycle, twenty milliseconds long,
    `transient` so the bulb **returns to the colour it held before the
    waveform started** rather than to whatever this packet carries. That
    is why the colour arguments default to something arbitrary and why
    nothing here has to know what the light was doing — the bulb kept that
    for us, and this asks for it back.

    `SetColor` was what stop used to send, and it is not this: it moves the
    light to a colour while the routine underneath keeps running, so the
    strobe carries on around the new value.
    """
    return set_waveform(transient=True, hue=hue, saturation=saturation,
                        brightness=brightness, kelvin=kelvin,
                        period_ms=HALT_PERIOD_MS, cycles=1.0,
                        waveform=WAVEFORM_SINE, **hdr)


def set_light_power(level: int, duration_ms: int, **hdr) -> bytes:
    """0 = off, 65535 = on, faded over duration."""
    return build(SET_LIGHT_POWER,
                 _SET_LIGHT_POWER.pack(level & 0xFFFF, duration_ms & 0xFFFFFFFF),
                 **hdr)


# ---------------------------------------------------------------------------
# Reply parsers
# ---------------------------------------------------------------------------
def parse_state_service(payload: bytes) -> dict:
    service, port = _STATE_SERVICE.unpack_from(payload)
    return {"service": service, "port": port}


def parse_state_label(payload: bytes) -> str:
    return payload[:32].split(b"\x00", 1)[0].decode("utf-8", "replace")


def parse_state_version(payload: bytes) -> dict:
    vendor, product, _version = _STATE_VERSION.unpack_from(payload)
    return {"vendor": vendor, "product": product}


def parse_light_state(payload: bytes) -> dict:
    (hue, saturation, brightness, kelvin, _resv, power,
     label, _resv2) = _LIGHT_STATE.unpack_from(payload)
    return {
        "hue": hue,
        "saturation": saturation,
        "brightness": brightness,
        "kelvin": kelvin,
        "power": power,
        "label": label.split(b"\x00", 1)[0].decode("utf-8", "replace"),
    }
