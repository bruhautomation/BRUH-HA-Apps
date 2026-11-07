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
