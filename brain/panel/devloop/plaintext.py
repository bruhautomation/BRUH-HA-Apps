"""Plain text for a report: no terminal colour codes, no control characters.

A leaf module on purpose: both `streams` (the log excerpt) and `upstream`
(every string a report carries) strip with it, and `upstream` already
imports `streams`, so the helper cannot live in either without a cycle.
"""

from __future__ import annotations

import re

# A terminal's colour codes and every other control character a log line
# can carry. An add-on log excerpt arrived with raw ESC sequences (shown as
# ^[[33m) in a report whose block the cloud could not parse; nothing a
# person reads needs them, so no string reaches a report with one in it.
_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
                      r"|\x1b[@-_]|\^\[\[[0-9;]*m")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def plain(text: str) -> str:
    """``text`` without ANSI escape sequences or control characters; line
    breaks and tabs kept, a lone carriage return read as a line break."""
    text = _ANSI_RE.sub("", str(text or "")).replace("\r\n", "\n").replace("\r", "\n")
    return _CONTROL_RE.sub("", text)


# A network address of this house's LAN: an IPv4 (with its port), an IPv6
# or a MAC. Read by shape, never by word. A finding's step keeps the
# address it acts on for the household (`house_words.addresses(step=True)`),
# and nothing of that leaves the house: every string a report or a picture
# carries goes through `upstream.scrub`, and the design review's own block
# (`streams.design_context`) is read without them. A version (three parts)
# and a clock time (no "::", fewer than eight groups) are not addresses.
_OCTET = r"(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)"
_H = r"[0-9A-Fa-f]{1,4}"
_NET_ADDRESS_RE = re.compile(
    r"(?<![\w:])(?:[0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}(?![\w:])"
    r"|(?<![\w:.])(?:(?:" + _H + r":){7}" + _H
    + r"|(?:" + _H + r":){1,7}:(?:" + _H + r"(?::" + _H + r"){0,6})?"
    + r"|::" + _H + r"(?::" + _H + r"){0,6})(?:%\w+)?(?![\w:])"
    r"|(?<![\d.])" + _OCTET + r"(?:\." + _OCTET + r"){3}(?::\d{1,5})?(?![\d]|\.\d)")
ADDRESS_WORD = "[address]"


def without_addresses(text: str) -> str:
    """``text`` with every IPv4, IPv6 and MAC address said as
    "[address]"."""
    return _NET_ADDRESS_RE.sub(ADDRESS_WORD, str(text or ""))
