"""Make brAIn's findings visible inside Home Assistant.

The Findings tab is where brAIn reports what it thinks is broken — and the
tab is the problem: a critical finding discovered by the 3am scheduler was
completely silent until somebody happened to open the panel. The findings
store itself lives in the add-on's /data, which Home Assistant cannot see,
so the add-on republishes a compact mirror to /config/.brain on every
change and this module reads it:

  * a ``brain_finding`` event per NEW finding, so "brAIn found something"
    can trigger an automation, reach a phone, or land in the logbook next
    to the lights and doors
  * an "Open findings" sensor, so a dashboard (or a numeric_state trigger)
    can answer "how much is waiting on me" without the panel

Everything here is read-only over a file the add-on owns, same contract as
learning.py: nothing in this module writes findings, and if the add-on is
stopped the sensor goes stale rather than disagreeing with it.
"""

from __future__ import annotations

import json
import os

from homeassistant.core import HomeAssistant

from .const import EVENT_FINDING, FINDINGS_STATE_FILENAME, SHARED_DIR

# The mirror is capped by the add-on (STATE_MAX_ROWS = 50 short rows), but a
# corrupted or hand-edited file must not be able to stall the event loop.
MAX_STATE_BYTES = 256 * 1024


def findings_state_path(hass: HomeAssistant) -> str:
    return hass.config.path(SHARED_DIR, FINDINGS_STATE_FILENAME)


def read_findings_state(hass: HomeAssistant) -> dict | None:
    """The add-on's published findings mirror, or None if it never wrote one.

    Shape: {ts, open, by_severity: {info/warning/serious/critical: n},
    findings: [{ts, text, severity, status, entity_id, fixable,
    source_title}, ...]} — newest first, live rows only.
    """
    path = findings_state_path(hass)
    try:
        if os.path.getsize(path) > MAX_STATE_BYTES:
            return None
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    rows = data.get("findings")
    data["findings"] = [f for f in rows if isinstance(f, dict) and f.get("text")] \
        if isinstance(rows, list) else []
    return data


class FindingsWatcher:
    """Fires a ``brain_finding`` event for each newly-reported finding.

    The watermark is the set of finding ids (their ``ts`` — the id the panel
    acts on) already seen, primed from the file's current content at startup
    so a restart does not replay the whole open list onto the bus. The
    add-on's store dedupes across every status and the settled ledger, so an
    id that appears here is genuinely news.
    """

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._seen: set[int] | None = None

    def prime(self) -> None:
        """Adopt the current list without announcing it."""
        state = read_findings_state(self.hass)
        self._seen = {int(f.get("ts") or 0)
                      for f in (state or {}).get("findings", [])}

    async def async_poll(self, _now=None) -> None:
        state = await self.hass.async_add_executor_job(
            read_findings_state, self.hass)
        if state is None:
            return
        current = {int(f.get("ts") or 0): f for f in state["findings"]}
        if self._seen is None:
            self._seen = set(current)
            return
        fresh = [current[ts] for ts in sorted(current) if ts not in self._seen]
        # Ids leave the mirror when a finding is settled; forgetting them
        # here keeps the watermark from growing forever, and cannot re-fire
        # a settled finding because the add-on's settled ledger stops the
        # same problem ever re-entering the list.
        self._seen = set(current)
        for finding in fresh:
            self.hass.bus.async_fire(EVENT_FINDING, {
                "ts": int(finding.get("ts") or 0),
                "finding": str(finding.get("text") or ""),
                "severity": str(finding.get("severity") or "warning"),
                "entity_id": str(finding.get("entity_id") or ""),
                "fixable": bool(finding.get("fixable", True)),
                "source": str(finding.get("source_title") or ""),
                # The logbook renders these verbatim, so it has to read as a
                # sentence rather than a field dump.
                "name": "brAIn",
                "message": f"found a problem: {finding.get('text')}",
            })
