"""Integrations — what Home Assistant's own log says is going wrong.

An integration that cannot reach a device, or one that has lost its
footing after an update, rarely leaves a state that looks wrong; it logs
the same error every few seconds instead, for days, and the log is the
one place nobody reads. Core's live log (the Supervisor's `/core/logs`)
is read once a checks pass by the collector and folded here into groups
— one per logger and message, with addresses, hardware ids and numbers
folded so "timed out talking to 10.0.0.12 after 5 s" and "… 10.0.0.13
after 6 s" are one complaint — and a logger repeating an error more than
`FLOOD_MIN` times in a day is one row naming the integration and, where
the message names a device or an address the house knows, that device.

The folding (`summarise_log`) is pure and lives here so the collector and
the tests read one implementation; the check reads only its summary. What
is kept of a message is redacted through the reports' own scrub before it
is stored. brAIn's own logger is never reported here — the add-on's
faults are `health.py`'s, with the switch named (`devices.SELF_PLATFORMS`).

The two other halves of the integrations audit are older checks widened
rather than copied: `sys.entry_failed` (an entry stuck setting up for a
day) and `dev.battery_low` (a battery from any integration).
"""
from __future__ import annotations

import datetime as dt
import re

from ._util import House, spell_integration

# A logger repeating one error more than this in the window is a flood.
FLOOD_MIN = 100
WINDOW_H = 24
MAX_ROWS = 5
# How much of the log one pass reads at most.
LOG_MAX_LINES = 25000
MESSAGE_MAX = 160
GROUPS_MAX = 200

_ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LINE_RE = re.compile(
    r"(?P<ts>\d{4}-\d\d-\d\d[ T]\d\d:\d\d:\d\d)(?:[.,]\d+)?\s+"
    r"(?P<level>ERROR|CRITICAL)\s+\((?P<thread>[^)]*)\)\s+"
    r"\[(?P<logger>[^\]]+)\]\s*(?P<msg>.*)")
_IPV4 = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d+)?\b")
_MAC = re.compile(r"\b(?:[0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b", re.I)
_UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-"
                   r"[0-9a-f]{12}\b", re.I)
_HEX = re.compile(r"\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{8,}\b", re.I)
_NUM = re.compile(r"\d+(?:\.\d+)?")


def _redact(text: str) -> str:
    try:
        import reports  # noqa: PLC0415 — the one scrub the reports use
        return reports.redact(text)
    except Exception:  # noqa: BLE001
        try:
            import journal  # noqa: PLC0415
            return journal.scrub(text)
        except Exception:  # noqa: BLE001 — nothing kept is better than a leak
            return ""


def shown(message: str) -> str:
    """What a person reads of a message: addresses and ids as words,
    numbers kept (they are usually the point)."""
    text = _UUID.sub("an id", message)
    text = _MAC.sub("a hardware address", text)
    text = _IPV4.sub("an address", text)
    text = _HEX.sub("an id", text)
    return " ".join(text.split())[:MESSAGE_MAX]


def fold(message: str) -> str:
    """The grouping key: everything that changes between repeats folded."""
    return _NUM.sub("#", shown(message).lower())


def domain_of_logger(logger: str) -> str:
    parts = str(logger or "").split(".")
    if len(parts) >= 3 and parts[0] == "homeassistant" and parts[1] == "components":
        return parts[2]
    if len(parts) >= 2 and parts[0] == "custom_components":
        return parts[1]
    return ""


def summarise_log(text: str, now: float, tz: dt.tzinfo | None = None,
                  hours: int = WINDOW_H) -> dict:
    """`{hours, lines, groups: [{logger, domain, message, count, last,
    ips}]}` over the ERROR and CRITICAL lines of the last ``hours``.

    Pure: a line is read off its own timestamp (Home Assistant writes
    local time with no offset, read in the house's zone), a line with no
    timestamp (a traceback's continuation) is skipped, and what is kept of
    a message is redacted before it leaves here.
    """
    tz = tz or dt.timezone.utc
    since = now - hours * 3600
    groups: dict[tuple, dict] = {}
    lines = 0
    for raw in str(text or "").splitlines()[-LOG_MAX_LINES:]:
        line = _ANSI.sub("", raw).strip()
        m = LINE_RE.search(line)
        if not m:
            continue
        try:
            stamp = dt.datetime.fromisoformat(m.group("ts").replace("T", " "))
        except ValueError:
            continue
        ts = stamp.replace(tzinfo=tz).timestamp()
        if ts < since or ts > now + 300:
            continue
        lines += 1
        logger = m.group("logger").strip()
        msg = m.group("msg")
        key = (logger, fold(msg))
        g = groups.get(key)
        if g is None:
            if len(groups) >= GROUPS_MAX:
                continue
            g = groups[key] = {"logger": logger,
                               "domain": domain_of_logger(logger),
                               "message": _redact(shown(msg)),
                               "count": 0, "last": ts, "ips": []}
        g["count"] += 1
        g["last"] = max(g["last"], ts)
        for ip in _IPV4.findall(msg):
            ip = ip.split(":")[0]
            if ip not in g["ips"] and len(g["ips"]) < 5:
                g["ips"].append(ip)
    out = sorted(groups.values(), key=lambda g: -g["count"])
    return {"hours": hours, "lines": lines, "groups": out}


_ENTITY_ID_RE = re.compile(r"(?<![\w.])([a-z_]+\.[a-z0-9_]+)(?![\w])")
_CALLER_RE = re.compile(
    r"^homeassistant\.components\.(automation|script|scene)\.([a-z0-9_]+)$")


def _platform(house: House, eid: str) -> str:
    return str((house.registry.get(eid) or {}).get("platform") or "")


def _of_domain(house: House, dev_id: str, domain: str) -> list[str]:
    """The entities on a device that the integration ``domain`` provides."""
    return sorted(str(r["entity_id"]) for r in house.entities
                  if r.get("device_id") == dev_id and r.get("entity_id")
                  and r.get("platform") == domain)


def _device_named(house: House, group: dict) -> tuple[str, str]:
    """(device name, entity to file under) the message points at (#434).

    Resolved from the line itself, and only to something of the
    integration that logged it: the automation or script its own logger
    names; an entity id the message writes out that the integration
    provides; a device at an address the message names, or whose name it
    says, that carries one of that integration's entities. A word match
    against another integration's device is never used, and when nothing
    resolves the row is about the integration and no entity."""
    logger = str(group.get("logger") or "")
    domain = str(group.get("domain") or domain_of_logger(logger))
    m = _CALLER_RE.match(logger)
    if m:
        caller = f"{m.group(1)}.{m.group(2)}"
        if caller in house.states or caller in house.registry:
            return house.label(caller), caller
    message = str(group.get("message") or "")
    for eid in sorted(set(_ENTITY_ID_RE.findall(message))):
        if (eid in house.states or eid in house.registry) and domain \
                and _platform(house, eid) == domain:
            dev = house.device_of(eid)
            return (house.device_name(dev) if dev else house.label(eid)), eid
    if not domain:
        return "", ""
    for ip in group.get("ips") or ():
        for eid, st in sorted(house.states.items()):
            attrs = st.get("attributes") or {}
            if ip not in (str(attrs.get("ip") or ""),
                          str(attrs.get("ip_address") or ""),
                          str(attrs.get("host") or "")):
                continue
            dev = house.device_of(eid)
            dev_id = str((house.registry.get(eid) or {}).get("device_id") or "")
            if _platform(house, eid) != domain and not (
                    dev_id and _of_domain(house, dev_id, domain)):
                # An address another integration's device answers on: not
                # this integration's line about it.
                continue
            return (house.device_name(dev) if dev else house.label(eid)), eid
    low = " " + message.lower() + " "
    for dev_id, dev in sorted(house.devices.items()):
        name = house.device_name(dev)
        if len(name) < 4 or not re.search(
                r"(?<![\w])" + re.escape(name.lower()) + r"(?![\w])", low):
            continue
        own = _of_domain(house, dev_id, domain)
        if own:
            return name, own[0]
    return "", ""


def _integration_name(snap: dict, domain: str, logger: str) -> str:
    entries = [e for e in snap.get("config_entries") or []
               if isinstance(e, dict) and e.get("domain") == domain
               and e.get("title")]
    if len(entries) == 1:
        return str(entries[0]["title"])
    if domain:
        return spell_integration(domain)
    return f"The {logger.split('.')[0]} library"


def log_flood(snap: dict, now: float) -> list[dict]:
    from .devices import SELF_PLATFORMS  # noqa: PLC0415
    house = House(snap)
    summary = snap.get("core_log") or {}
    hours = int(summary.get("hours") or WINDOW_H)
    by_logger: dict[str, list[dict]] = {}
    for g in summary.get("groups") or ():
        if not isinstance(g, dict) or int(g.get("count") or 0) <= FLOOD_MIN:
            continue
        logger = str(g.get("logger") or "")
        domain = str(g.get("domain") or domain_of_logger(logger))
        if domain in SELF_PLATFORMS or logger.split(".")[0] in SELF_PLATFORMS:
            continue
        by_logger.setdefault(logger, []).append(g)
    rows = []
    for logger, groups in by_logger.items():
        groups.sort(key=lambda g: -int(g.get("count") or 0))
        top = groups[0]
        domain = str(top.get("domain") or domain_of_logger(logger))
        who = _integration_name(snap, domain, logger)
        device, entity = _device_named(house, top)
        if entity and not house.should_report(entity, "integ.log_flood"):
            continue
        detail = (f"{who} logged this {int(top['count'])} times in the "
                  f"last {hours} hours: "
                  f"\u201c{top.get('message') or 'an error'}\u201d.")
        if device:
            detail += f" It is about {device}."
        if len(groups) > 1:
            detail += (f" {len(groups) - 1} other error"
                       + ("s" if len(groups) > 2 else "")
                       + " from it repeat as often.")
        rows.append({
            "text": (f"{spell_integration(domain) if domain else who} is "
                     "logging the same error over and over"),
            "detail": detail,
            "fix": ("Read what the error says is wrong in Settings > System > "
                    "Logs. Fixing the device or address it names, or reloading "
                    "the integration from Settings > Devices & services, "
                    "usually stops it. A log this busy also wears the storage "
                    "and buries other errors."),
            "severity": "warning",
            "fixable": False,
            "entity_id": entity,
            # A line that names nothing of the integration's is about the
            # integration as a whole (#440): one card with every other
            # check's row about it.
            **({} if entity else {"integration": domain} if domain else {}),
            "_count": int(top["count"]),
        })
    rows.sort(key=lambda r: -r["_count"])
    for r in rows:
        r.pop("_count", None)
    if len(rows) > MAX_ROWS:
        house.gave_up("integ.log_flood", rows[MAX_ROWS:],
                      "more flooding loggers than one card each can say")
        rows = rows[:MAX_ROWS]
    return rows


INTEGRATIONS = "Integrations"

CHECKS = [
    {"id": "integ.log_flood", "area": "integrations", "title": "Integrations repeating an error",
     "source_title": INTEGRATIONS, "needs": ("core_log",), "run": log_flood},
]
