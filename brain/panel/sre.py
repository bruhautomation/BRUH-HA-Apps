"""The overnight health check — one explained finding per ROOT CAUSE.

Every device check reads one row and files one row: four sensors upstairs
go quiet and the Findings tab carries four "check its batteries" cards,
when the truth is one sentence — *your bedtime automation switches off the
only Zigbee router upstairs*. Nothing that reads one row can say that,
because the cause is the relation between rows: a log line, a mesh table
and an automation's action list, side by side.

So once a night (gated like every scheduled run) this reads three things
Home Assistant keeps and nothing in brAIn read:

  * the **system log** (`system_log/list`) — what Core and the
    integrations have been complaining about, with counts;
  * the **Zigbee mesh** (`zha/devices`: each device's type, link quality,
    signal, last seen and — where the integration publishes them — its
    neighbours), and skips cleanly on a house with no ZHA, because no
    Zigbee is not an unhealthy Zigbee;
  * **Z-Wave node statistics**, from the statistics sensors Z-Wave JS
    publishes (dropped commands, timeouts, round-trip time) and the node
    status sensors, where the house has enabled them;

and adds the one cross-reference a mesh needs: which automations switch
off a device that is a Zigbee router. Every one of those is a RECORD with
an id in a digest, and the run is asked to group them into causes.

**A cause must cite records by id, and the ids are checked in code
against the digest** (`parse_causes`): a cause citing none that exist is
dropped, an id that is not in the digest is dropped from the cause and
counted, and what reaches the Findings tab carries the cited records as
its evidence. That is the difference between a root cause and a story.

**A cause is one problem, about one thing.** A log record carries the
entities (and, by their own names, the devices) its message names, so a
cause about one sensor is filed under it; the cited records are grouped by
the problem they are evidence of (the Zigbee mesh is one, each Z-Wave node
is its own, a log line belongs to the device it names), and records about
another problem are taken off a cause, with the sentences about them,
rather than riding in its detail under a fix for something else. And a log
record says whether anything the owner wrote refers to the entity it names
(`referenced_by_you`, read off their YAML and the UI template helpers by
`read_user_text`): a fix telling them to edit a template over a record that
says nothing of theirs refers to it is replaced with one naming the
integration.

The text a cause is filed under is the one stable thing about it, so it
is reused by **anchor** (the first record the cause cites): the same
router being the cause tomorrow is the same finding, whatever words the
run chooses, rather than a new card every night. And only a pass that
RAN may clear: a night whose system log could not be read clears nothing,
and a cause anchored in the Zigbee mesh is kept on a night ZHA did not
answer — `clear_resolved`'s rule, one producer over.
"""
from __future__ import annotations

import hashlib
import json
import os
import re

import atomic_write
import prompt_kit
import textclip
from checks._util import spell_integration

STORE = os.environ.get("BRAIN_SRE_FILE", "/data/sre.json")
SOURCE = "sre"
SOURCE_TITLE = "Overnight health check"

SEVERITIES = ("info", "warning", "serious")
MAX_LOG_RECORDS = 40
MAX_ZHA_RECORDS = 120
MAX_ZWAVE_RECORDS = 80
MAX_AUTO_RECORDS = 30
MAX_CAUSES = 5
MAX_TITLE = 120
MAX_DETAIL = 500
MAX_FIX = 400
MAX_ANCHORS = 200
TIMEOUT_S = 480

# Below these a mesh device is worth a line in the digest even when it is
# not a router — the floor for "this one is struggling".
WEAK_LQI = 60
UNSEEN_HOURS = 6.0
# What makes a night worth a run at all. A clean log and a healthy mesh
# spend nothing, the brief's rule: the decision not to ask is arithmetic.
WARNING_COUNT = 5
LOG_LEVELS = ("CRITICAL", "ERROR", "WARNING")
_STAT_RE = re.compile(r"\.statistics_([A-Za-z]+)$")
# Letters AND digits, no underscore: a token or an id, never an entity id.
_TOKENISH = re.compile(r"\b(?=[A-Za-z\-]*\d)(?=[0-9\-]*[A-Za-z])"
                       r"[A-Za-z0-9\-]{24,}\b")


def _redact(text: str) -> str:
    """A log message is somebody else's text: strip anything token-shaped
    before it goes anywhere, and cap it."""
    from capture import redact
    text = redact(str(text or ""))
    return textclip.clip(_TOKENISH.sub("[redacted]", text), 240)


def _rid(prefix: str, *parts: str) -> str:
    digest = hashlib.sha1("|".join(parts).encode("utf-8", "replace"))
    return f"{prefix}:{digest.hexdigest()[:10]}"


# ---------------------------------------------------------------------------
# Gathering
# ---------------------------------------------------------------------------

async def collect(session) -> dict:
    """Everything the pass reads, each source its own attempt.

    `available` says which answered; a source that did not is "I could not
    look" for the rest of the pass, and its records are simply absent.
    """
    import ha_data
    from checks.snapshot import load_configs

    out: dict = {"available": {}, "errors": {}, "log": [], "zha": [],
                 "states": {}, "entities": [], "devices": [],
                 "automations": []}
    try:
        (log_rows, zha, entities, devices, areas,
         manifests) = await ha_data._ws_calls(
            session, [
                {"type": "system_log/list"},
                {"type": "zha/devices"},
                {"type": "config/entity_registry/list"},
                {"type": "config/device_registry/list"},
                {"type": "config/area_registry/list"},
                {"type": "manifest/list"},
            ])
    except Exception as exc:  # noqa: BLE001 — every source is best effort
        out["errors"]["ws"] = str(exc)[:200]
        for key in ("log", "zha", "registry"):
            out["available"][key] = False
        return out
    rows = log_rows.get("result") if log_rows.get("ok") else None
    out["available"]["log"] = isinstance(rows, list)
    out["log"] = rows if isinstance(rows, list) else []
    if not out["available"]["log"]:
        out["errors"]["log"] = str(log_rows.get("error") or "no answer")[:200]
    zrows = zha.get("result") if zha.get("ok") else None
    out["available"]["zha"] = isinstance(zrows, list)
    out["zha"] = zrows if isinstance(zrows, list) else []
    erows = entities.get("result") if entities.get("ok") else None
    drows = devices.get("result") if devices.get("ok") else None
    out["available"]["registry"] = isinstance(erows, list)
    out["entities"] = erows if isinstance(erows, list) else []
    out["devices"] = drows if isinstance(drows, list) else []
    arows = areas.get("result") if areas.get("ok") else None
    out["areas"] = {str(a.get("area_id")): str(a.get("name") or "")
                    for a in arows or [] if isinstance(a, dict)}
    # Which loggers each integration declares: a library's logger
    # (`pywemo.…`) names no integration by itself. Every manifest, so a
    # finding names the integration the way a person sees it (#340).
    mrows = manifests.get("result") if manifests.get("ok") else None
    out["manifests"] = [m for m in mrows or [] if isinstance(m, dict)]
    # Each config entry's title, for an integration whose manifest has
    # no name of its own.
    try:
        [entries] = await ha_data._ws_calls(session, [
            {"type": "config_entries/get"},
        ])
        erows = entries.get("result") if entries.get("ok") else None
    except Exception as exc:  # noqa: BLE001 — names are a nicety
        out["errors"]["config_entries"] = str(exc)[:200]
        erows = None
    out["available"]["config_entries"] = isinstance(erows, list)
    out["config_entries"] = [e for e in erows or [] if isinstance(e, dict)]
    try:
        raw = await ha_data._rest_get(session, "/states", timeout=60)
        out["states"] = {s["entity_id"]: s for s in raw or []
                         if isinstance(s, dict) and s.get("entity_id")}
        out["available"]["states"] = True
    except Exception as exc:  # noqa: BLE001
        out["available"]["states"] = False
        out["errors"]["states"] = str(exc)[:200]
    cfg = load_configs()
    out["automations"] = cfg.get("automations") or []
    out["scripts"] = cfg.get("scripts") or {}
    out["scenes"] = cfg.get("scenes") or []
    # How often each automation, script and scene that calls an entity a
    # log line says was unavailable ran since that line first appeared:
    # the calls it made (`called_by`).
    try:
        out["caller_runs"] = await _caller_runs(session, out, ha_data)
    except Exception as exc:  # noqa: BLE001 — counts are best effort
        out["errors"]["caller_runs"] = str(exc)[:200]
        out["caller_runs"] = {}
    # What the owner wrote, read off the files Home Assistant loads them
    # from: a log line about an entity nothing of theirs refers to is the
    # integration's to answer for, not a template of theirs to edit.
    out["user_text"] = read_user_text()
    out["available"]["configs"] = out["user_text"] is not None
    return out


# A call to an entity that is not there. Core's own sentence, from the
# service helper or from the automation or script that made the call.
_MISSING_RE = re.compile(
    r"Referenced (?:entities|devices|areas)?\s*(.+?) (?:are|is) missing or "
    r"not currently available", re.I)
# The logger an automation, script or scene logs its own failures under.
_CALLER_LOGGER = re.compile(
    r"^homeassistant\.components\.(automation|script|scene)\.([a-z0-9_]+)$")
CALLER_WINDOW_S = 48 * 3600


def _missing_targets(rows: list) -> set[str]:
    out: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        message = row.get("message")
        first = message[0] if isinstance(message, list) and message else message
        m = _MISSING_RE.search(str(first or ""))
        if m:
            out |= {x.group(1) for x in _ID_IN_TEXT.finditer(m.group(1))}
    return out


def _callers_of(target: str, collected: dict) -> list[tuple[str, str, str]]:
    """``[(entity id, kind, name)]`` — every automation, script and scene
    whose config names ``target``, as Home Assistant knows it."""
    states = collected.get("states") or {}

    def by_config_id(domain: str, cid) -> str:
        for eid, st in states.items():
            if (eid.startswith(domain + ".") and isinstance(st, dict)
                    and str((st.get("attributes") or {}).get("id")) == str(cid)):
                return eid
        return ""

    def name_of(eid: str, given) -> str:
        st = states.get(eid) or {}
        friendly = str((st.get("attributes") or {}).get("friendly_name") or "")
        return friendly or str(given or "") or eid.split(".", 1)[-1].replace("_", " ")

    out = []
    for item in collected.get("automations") or []:
        if isinstance(item, dict) and _refers(json.dumps(item), target):
            eid = by_config_id("automation", item.get("id"))
            out.append((eid, "automation", name_of(eid, item.get("alias"))))
    scripts = collected.get("scripts") or {}
    for key, item in (scripts.items() if isinstance(scripts, dict) else ()):
        if isinstance(item, dict) and _refers(json.dumps(item), target):
            eid = f"script.{key}"
            out.append((eid, "script", name_of(eid, item.get("alias"))))
    for item in collected.get("scenes") or []:
        if isinstance(item, dict) and _refers(json.dumps(item), target):
            eid = by_config_id("scene", item.get("id"))
            out.append((eid, "scene", name_of(eid, item.get("name"))))
    return out


async def _caller_runs(session, collected: dict, ha_data) -> dict:
    """``{entity id: runs}`` since the earliest missing-entity line, at most
    `CALLER_WINDOW_S` back, off the logbook: an automation's "triggered",
    a script's "started", a scene's activation — each run is one call."""
    import datetime as dt  # noqa: PLC0415
    targets = _missing_targets(collected.get("log") or [])
    callers = sorted({eid for t in targets for eid, _k, _n in
                      _callers_of(t, collected) if eid})
    if not callers:
        return {}
    firsts = [float(r.get("first_occurred") or r.get("timestamp") or 0)
              for r in collected.get("log") or [] if isinstance(r, dict)]
    import time as _time  # noqa: PLC0415
    now = _time.time()
    start = max(min([f for f in firsts if f] or [now]), now - CALLER_WINDOW_S)
    [answer] = await ha_data._ws_calls(session, [{
        "type": "logbook/get_events",
        "start_time": dt.datetime.fromtimestamp(start, dt.timezone.utc).isoformat(),
        "entity_ids": callers}])
    rows = answer.get("result") if answer.get("ok") else None
    runs: dict[str, int] = {}
    for row in rows if isinstance(rows, list) else []:
        eid = str((row or {}).get("entity_id") or "")
        if eid not in callers:
            continue
        message = str(row.get("message") or "")
        if eid.startswith("automation.") and not message.startswith("triggered"):
            continue
        if eid.startswith("script.") and not message.startswith("started"):
            continue
        runs[eid] = runs.get(eid, 0) + 1
    return runs


def called_by(rec: dict, collected: dict) -> list[dict]:
    """What made the failed calls a missing-entity log line counts, and how
    many each: the automation or script the line's own logger names (with
    the line's count), or else every one whose config names the entity
    (with its runs since the line first appeared, None where the logbook
    did not say)."""
    m = _CALLER_LOGGER.match(str(rec.get("logger") or ""))
    states = collected.get("states") or {}
    if m:
        eid = f"{m.group(1)}.{m.group(2)}"
        st = states.get(eid) or {}
        name = str((st.get("attributes") or {}).get("friendly_name") or "") \
            or m.group(2).replace("_", " ")
        return [{"name": name, "kind": m.group(1), "calls": rec["count"]}]
    runs = collected.get("caller_runs") or {}
    out, seen = [], set()
    for target in rec.get("entities") or []:
        for eid, kind, name in _callers_of(target, collected):
            key = eid or f"{kind}:{name}"
            if key in seen:
                continue
            seen.add(key)
            out.append({"name": name, "kind": kind,
                        "calls": runs.get(eid) if eid else None})
    return out[:8]


# Bounds on reading the owner's config: a house with a thousand package
# files is still read in a moment, and one that is not is asked about
# what it was possible to read rather than held up.
MAX_USER_FILES = 300
MAX_USER_BYTES = 4_000_000
_INCLUDE_DIR_RE = re.compile(r"!include_dir_\w+\s+['\"]?([^\s'\"#]+)")
_REFUSED_NAMES = frozenset({"secrets.yaml", "secrets.yml"})


def read_user_text(config_dir: str | None = None) -> str | None:
    """Everything the owner wrote that could refer to an entity, as one
    string, or None when the config folder cannot be read at all.

    The top-level YAML (never ``secrets.yaml``), ``packages/`` and every
    folder ``configuration.yaml`` names with ``!include_dir_*``, plus the
    options of the template helpers made in the UI (their templates live
    in ``.storage/core.config_entries``, not in any YAML). Read as text on
    purpose: whether an entity id appears anywhere the owner wrote is the
    whole question, and a structural parse misses what HA's tags hide.
    """
    from checks.snapshot import CONFIG_DIR  # noqa: PLC0415
    root = config_dir or CONFIG_DIR
    if not os.path.isdir(root):
        return None
    parts: list[str] = []
    budget = [MAX_USER_BYTES, MAX_USER_FILES]

    def take(path: str) -> None:
        if budget[0] <= 0 or budget[1] <= 0:
            return
        if os.path.basename(path).lower() in _REFUSED_NAMES:
            return
        if os.path.islink(path) or not os.path.isfile(path):
            return
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as fh:
                text = fh.read(budget[0])
        except OSError:
            return
        budget[0] -= len(text)
        budget[1] -= 1
        parts.append(text)

    def walk(folder: str) -> None:
        real_root = os.path.realpath(root)
        real = os.path.realpath(folder)
        if not real.startswith(real_root + os.sep) or not os.path.isdir(real):
            return
        for here, dirs, files in os.walk(real, followlinks=False):
            dirs[:] = sorted(d for d in dirs if not d.startswith("."))
            for name in sorted(files):
                if name.endswith((".yaml", ".yml")) and not name.startswith("."):
                    take(os.path.join(here, name))

    try:
        top = sorted(os.listdir(root))
    except OSError:
        return None
    for name in top:
        if name.endswith((".yaml", ".yml")) and not name.startswith("."):
            take(os.path.join(root, name))
    walk(os.path.join(root, "packages"))
    try:
        with open(os.path.join(root, "configuration.yaml"), "r",
                  encoding="utf-8", errors="replace") as fh:
            for m in _INCLUDE_DIR_RE.finditer(fh.read()):
                rel = m.group(1)
                if (rel.startswith(("/", ".")) or ".." in rel.split("/")):
                    continue
                walk(os.path.join(root, rel))
    except OSError:
        # No configuration.yaml to read is fewer folders, not a failure:
        # the top-level files and packages above were still read.
        pass
    try:
        with open(os.path.join(root, ".storage", "core.config_entries"), "r",
                  encoding="utf-8") as fh:
            entries = (json.load(fh).get("data") or {}).get("entries") or []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("domain") == "template":
                parts.append(json.dumps(entry.get("options") or {}))
    except (OSError, ValueError, AttributeError):
        # The UI helpers are one more place a reference could be; without
        # them the YAML read above still answers.
        pass
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The digest: records with ids
# ---------------------------------------------------------------------------

# An entity id anywhere in a message, overlapping matches included, so
# "states.sensor.x.attributes" still offers "sensor.x"; only ids the house
# has are kept, which is what keeps a file name or a version out.
_ID_IN_TEXT = re.compile(r"(?=(?<![a-z0-9_])([a-z_]+\.[a-z0-9_]+))")
MIN_DEVICE_NAME = 6


_ADDRESS_RE = re.compile(r"(?<![\d.])(\d{1,3}(?:\.\d{1,3}){3})(?![\d.])")


def _host_of(url) -> str:
    """The host of a device's configuration URL, or "" — how a log line
    that names only an address is traced to the device at it."""
    from urllib.parse import urlparse  # noqa: PLC0415
    try:
        return str(urlparse(str(url or "")).hostname or "")
    except ValueError:
        return ""


def _named_in(message: str, known: set[str], devices: list,
              integration: str = "",
              device_domains: dict | None = None) -> tuple[list, list]:
    """``(entity ids, device ids)`` a log message names: ids the house has,
    and registry devices whose own name (or address) appears in it.

    **A device is named only by its own integration's line** (#434). A
    word match is a guess, and a guess across integrations is how "LIFX is
    logging the same error" was filed on an unrelated motion sensor whose
    name happened to be in the message: the device has to carry an entity
    of the integration the line came from. A line whose integration cannot
    be told names no device by its name at all — there is nothing to check
    the guess against. An entity id written out in the message is not a
    guess and is kept whoever logged it."""
    text = str(message or "")
    ents = sorted({m.group(1) for m in _ID_IN_TEXT.finditer(text)
                   if m.group(1) in known})
    devs = []
    addresses = set(_ADDRESS_RE.findall(text))
    for d in devices or []:
        if not isinstance(d, dict) or not d.get("id"):
            continue
        if device_domains is not None and (
                not integration
                or integration not in (device_domains.get(str(d["id"]))
                                       or ())):
            continue
        host = _host_of(d.get("configuration_url"))
        if host and host in addresses:
            devs.append(str(d["id"]))
            continue
        for name in {str(d.get("name_by_user") or ""), str(d.get("name") or "")}:
            if len(name) >= MIN_DEVICE_NAME and re.search(
                    r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.I):
                devs.append(str(d["id"]))
                break
    return ents[:4], sorted(set(devs))[:4]


def _is_frontend(logger: str) -> bool:
    """A record the browser wrote: Home Assistant files a frontend error
    under ``frontend.js.<build>.<version>``."""
    name = str(logger or "")
    return name == "frontend" or name.startswith("frontend.")


def _refers(user_text: str, eid: str) -> bool:
    return bool(re.search(r"(?<![\w])" + re.escape(eid) + r"(?![\w])",
                          user_text))


def _device_domains(platforms: dict | None,
                    entity_devices: dict | None) -> dict | None:
    """``{device id: {integrations}}`` off the registry's entities, or None
    when the registry was not handed in (nothing to check a name against,
    so a caller with no registry keeps the old reading)."""
    if not platforms or entity_devices is None:
        return None
    out: dict[str, set] = {}
    for eid, dev in entity_devices.items():
        if dev and platforms.get(eid):
            out.setdefault(str(dev), set()).add(str(platforms[eid]))
    return out


def _log_records(rows: list, now: float, known: set[str] | None = None,
                 devices: list | None = None, user_text: str | None = None,
                 platforms: dict | None = None,
                 manifests: list | None = None,
                 entity_devices: dict | None = None) -> list[dict]:
    out = []
    for row in rows:
        if not isinstance(row, dict) or row.get("level") not in LOG_LEVELS:
            continue
        count = int(row.get("count") or 1)
        if row.get("level") == "WARNING" and count < 2:
            continue
        message = row.get("message")
        first = message[0] if isinstance(message, list) and message else message
        source = row.get("source")
        where = (f"{source[0]}:{source[1]}" if isinstance(source, list)
                 and len(source) >= 2 else str(source or ""))
        logger = str(row.get("name") or "")
        rec = {
            "id": _rid("log", logger, where, str(first or "")[:80]),
            "kind": "log", "level": row.get("level"), "logger": logger[:80],
            "integration": integration_of(logger, manifests),
            "where": where[:120], "message": _redact(first or ""),
            "count": count,
            "last_hours_ago": round(max(0.0, now - float(
                row.get("timestamp") or now)) / 3600, 1),
        }
        # A browser's error line carries the browser's user agent, and a
        # phone's model in it is not the device the error is about: the
        # frontend's records name no device by name.
        ents, devs = _named_in(str(first or ""), known or set(),
                               None if _is_frontend(logger) else devices,
                               rec["integration"],
                               _device_domains(platforms, entity_devices))
        if ents:
            rec["entities"] = ents
            owners = sorted({(platforms or {}).get(e) for e in ents} - {None, ""})
            if len(owners) == 1:
                # The integration that provides what the line is about —
                # which is not always the logger that printed it.
                rec["owner"] = owners[0]
            if user_text is not None:
                # Whether anything the owner wrote refers to it: a template
                # entity is theirs by construction, and otherwise the id
                # has to appear in their config. Absent means "could not
                # tell", never "no".
                rec["referenced_by_you"] = any(
                    (platforms or {}).get(e) == "template"
                    or _refers(user_text, e) for e in ents)
        if devs:
            rec["devices"] = devs
        out.append(rec)
    order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2}
    out.sort(key=lambda r: (order.get(r["level"], 3), -r["count"], r["id"]))
    return out[:MAX_LOG_RECORDS]


_LOGGER_RE = re.compile(
    r"^(?:homeassistant\.components|custom_components)\.([a-z0-9_]+)")


def integration_of(logger: str, manifests: list | None = None) -> str:
    """The integration a log line came from, off its logger name, or "".

    Core's and a custom integration's own loggers carry the domain; a
    library's (`pywemo.ouimeaux_device`) is matched against the loggers
    each integration's manifest declares."""
    name = str(logger or "")
    for m in manifests or []:
        if not isinstance(m, dict) or not m.get("domain"):
            continue
        for prefix in m.get("loggers") or []:
            prefix = str(prefix or "")
            if prefix and (name == prefix or name.startswith(prefix + ".")):
                return str(m["domain"])
    match = _LOGGER_RE.match(name)
    return match.group(1) if match else ""


def _hours_since(value, now: float) -> float | None:
    from checks._util import parse_ts
    ts = parse_ts(value)
    return None if ts is None else round(max(0.0, now - ts) / 3600, 1)


def _zha_records(rows: list, now: float, areas: dict) -> list[dict]:
    out = []
    for dev in rows:
        if not isinstance(dev, dict) or not dev.get("ieee"):
            continue
        dtype = str(dev.get("device_type") or "")
        lqi = dev.get("lqi")
        seen = _hours_since(dev.get("last_seen"), now)
        weak = isinstance(lqi, (int, float)) and lqi < WEAK_LQI
        unseen = seen is not None and seen > UNSEEN_HOURS
        down = dev.get("available") is False
        # Every router (the mesh is made of them) and every device that is
        # struggling; a healthy end device is noise in a root-cause table.
        if dtype not in ("Router", "Coordinator") and not (weak or unseen or down):
            continue
        rec = {"id": f"zha:{dev['ieee']}", "kind": "zigbee",
               "name": str(dev.get("user_given_name") or dev.get("name")
                           or dev["ieee"])[:80],
               "type": dtype or "unknown",
               "power": str(dev.get("power_source") or "")[:30],
               "available": dev.get("available") is not False,
               "lqi": lqi, "rssi": dev.get("rssi"), "last_seen_hours": seen,
               "area": areas.get(str(dev.get("area_id") or ""), "")}
        neighbours = dev.get("neighbors")
        if isinstance(neighbours, list) and neighbours:
            rec["neighbours"] = [
                {"ieee": str(n.get("ieee") or "")[:30],
                 "relationship": str(n.get("relationship") or "")[:20],
                 "lqi": n.get("lqi")}
                for n in neighbours[:6] if isinstance(n, dict)]
        if dev.get("device_reg_id"):
            rec["device_id"] = str(dev["device_reg_id"])
        out.append(rec)
    out.sort(key=lambda r: (r["type"] != "Coordinator", r["type"] != "Router",
                            r["id"]))
    return out[:MAX_ZHA_RECORDS]


def _zwave_records(states: dict, entities: list, devices: list) -> list[dict]:
    # One answer to "is this the node status sensor" — the registered
    # translation key or unique id, never the entity id's suffix alone.
    from checks.devices import is_node_status
    names = {str(d.get("id")): str(d.get("name_by_user") or d.get("name") or "")
             for d in devices if isinstance(d, dict)}
    by_device: dict[str, dict] = {}
    # What each node carries, as the Zigbee records name theirs: so a
    # cause about the node can name the pump a person knows it as, and the
    # entity a run names is one the records hold (`parse_causes`).
    owned: dict[str, list] = {}
    for reg in entities:
        if not isinstance(reg, dict) or reg.get("platform") != "zwave_js":
            continue
        dev_id = str(reg.get("device_id") or "")
        eid = str(reg.get("entity_id") or "")
        if not dev_id or not eid:
            continue
        owned.setdefault(dev_id, []).append(
            (1 if reg.get("entity_category") else 0, eid))
        uid = str(reg.get("unique_id") or "")
        state = (states.get(eid) or {}).get("state")
        match = _STAT_RE.search(uid)
        if match:
            by_device.setdefault(dev_id, {})[match.group(1)] = state
        elif is_node_status(eid, reg):
            by_device.setdefault(dev_id, {})["status"] = state
    out = []
    for dev_id, stats in sorted(by_device.items()):
        status = stats.get("status")
        dropped = sum(_num(stats.get(k)) for k in
                      ("commandsDroppedTX", "commandsDroppedRX"))
        timeouts = _num(stats.get("timeoutResponse"))
        if status not in ("dead",) and dropped <= 0 and timeouts <= 0:
            continue
        out.append({"id": f"zw:{dev_id}", "kind": "zwave",
                    "name": names.get(dev_id, dev_id)[:80],
                    "status": status, "stats": {k: v for k, v in stats.items()
                                                if k != "status"},
                    "entities": [e for _c, e in sorted(owned.get(dev_id)
                                                       or [])][:4]})
    return out[:MAX_ZWAVE_RECORDS]


def _num(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _router_switch_records(automations: list, zha: list[dict],
                           entities: list) -> list[dict]:
    """Automations that switch off something that is a Zigbee router."""
    from checks._util import walk
    routers = {r["device_id"]: r["id"] for r in zha
               if r.get("type") == "Router" and r.get("device_id")}
    if not routers:
        return []
    owned = {str(e.get("entity_id")): routers[str(e.get("device_id"))]
             for e in entities if isinstance(e, dict)
             and str(e.get("device_id") or "") in routers}
    out = []
    for auto in automations or []:
        if not isinstance(auto, dict):
            continue
        hits: set[str] = set()
        for node in walk(auto):
            if not isinstance(node, dict):
                continue
            service = node.get("action") or node.get("service")
            if not isinstance(service, str) or not service.endswith(
                    (".turn_off", ".toggle")):
                continue
            for holder in (node, node.get("target"), node.get("data")):
                if not isinstance(holder, dict):
                    continue
                ids = holder.get("entity_id")
                for eid in ids if isinstance(ids, list) else [ids]:
                    if isinstance(eid, str) and eid in owned:
                        hits.add(eid)
        if hits:
            aid = str(auto.get("id") or auto.get("alias") or "")
            out.append({"id": _rid("auto", aid), "kind": "automation",
                        "automation": str(auto.get("alias") or aid)[:80],
                        "automation_id": aid[:64],
                        "switches_off": sorted(hits),
                        "routers": sorted({owned[e] for e in hits})})
        if len(out) >= MAX_AUTO_RECORDS:
            break
    return out


def _representatives(entities: list) -> tuple[dict, dict]:
    """`({device id: entity}, {integration: entity})` — one deterministic
    entity a cause about a device or an integration is filed under.

    The first sorted entity id, preferring one with no entity category: a
    node's status or statistics sensor is a reading ABOUT the device, and a
    cause filed under it would fold and be corrected against a diagnostic
    nobody looks at. Only ids the registry holds; never an invented one.
    """
    by_device: dict[str, list] = {}
    by_platform: dict[str, list] = {}
    for e in entities or []:
        if not isinstance(e, dict) or not e.get("entity_id"):
            continue
        # A device_tracker is where the device is, never what went wrong
        # with it, so it is the last choice of subject.
        rank = (1 if e.get("entity_category") else 0,
                1 if str(e["entity_id"]).startswith("device_tracker.") else 0,
                str(e["entity_id"]))
        if e.get("device_id"):
            by_device.setdefault(str(e["device_id"]), []).append(rank)
        if e.get("platform"):
            by_platform.setdefault(str(e["platform"]), []).append(rank)
    return ({k: min(v)[-1] for k, v in by_device.items()},
            {k: min(v)[-1] for k, v in by_platform.items()})


# Which records name a device or a rule (the cause is ABOUT it) and which
# name an integration (a log line: the cause happened IN it). A cause
# citing both is filed under the device.
_DEVICE_KINDS = ("zigbee", "zwave", "automation")


# The integrations whose entities are each a rule somebody wrote, not a
# device: one of them standing for "the integration" is an arbitrary
# automation, and a cause about automations filed under it was a finding
# about a rule its config never touched (#434).
RULE_DOMAINS = frozenset({"automation", "script", "scene", "template"})


def log_subjects(rec: dict, platforms: dict, known: set[str]) -> list[str]:
    """The entities a log record may be filed under, best first (#434).

    Resolved from the line itself and never from a word match against
    some other integration's thing: the automation, script or scene its
    own logger names; an entity id the message writes out that belongs to
    the integration the line came from (or any such id when the logger
    names no integration, or a rule's id); and nothing else here — a
    device the message names is already its own integration's
    (`_named_in`) and is resolved through it by the caller.
    """
    out: list[str] = []
    m = _CALLER_LOGGER.match(str(rec.get("logger") or ""))
    if m:
        caller = f"{m.group(1)}.{m.group(2)}"
        if caller in known:
            out.append(caller)
    integration = str(rec.get("integration") or "")
    for eid in rec.get("entities") or []:
        domain = eid.split(".", 1)[0]
        if (not integration or platforms.get(eid) == integration
                or domain in RULE_DOMAINS):
            if eid not in out:
                out.append(eid)
    return out


def _subjects(records: list[dict], entities: list,
              wide: dict | None = None,
              known: set[str] | None = None) -> dict[str, str]:
    """`{record id: entity}` for every record a subject is known for.

    ``wide``, when handed, is filled with ``{record id: integration}`` for
    the log records filed under their integration's representative rather
    than under anything the line names: such a row is about the
    integration as a whole, which is what lets every check that saw the
    same outage be one card (`findings_store`'s integration fold)."""
    devices, platforms = _representatives(entities)
    entity_platform = {str(e["entity_id"]): str(e.get("platform") or "")
                       for e in entities or []
                       if isinstance(e, dict) and e.get("entity_id")}
    by_device: dict[str, list[str]] = {}
    for e in entities or []:
        if isinstance(e, dict) and e.get("entity_id") and e.get("device_id"):
            by_device.setdefault(str(e["device_id"]), []).append(
                str(e["entity_id"]))
    out: dict[str, str] = {}
    for rec in records:
        eid = ""
        if rec["kind"] == "zigbee":
            eid = devices.get(str(rec.get("device_id") or ""), "")
        elif rec["kind"] == "zwave":
            eid = devices.get(rec["id"].split(":", 1)[1], "")
        elif rec["kind"] == "automation":
            eid = (sorted(rec.get("switches_off") or []) or [""])[0]
        elif rec["kind"] == "log":
            integration = str(rec.get("integration") or "")
            named = log_subjects(rec, entity_platform,
                                 set(entity_platform) | set(known or ()))
            devs = rec.get("devices") or []
            if len(named) == 1 or (named and named[0].split(".", 1)[0]
                                   in RULE_DOMAINS
                                   and _CALLER_LOGGER.match(
                                       str(rec.get("logger") or ""))):
                eid = named[0]
            elif not named and len(devs) == 1:
                # The device's own entity of the integration that logged,
                # never another integration's entity on the same box.
                own = sorted(e for e in by_device.get(devs[0], [])
                             if not integration
                             or entity_platform.get(e) == integration)
                rep = devices.get(devs[0], "")
                eid = rep if rep in own else (own[0] if own else "")
            if not eid and not (rec.get("entities") or devs):
                domain = integration or str(rec.get("owner") or "")
                if domain and domain not in RULE_DOMAINS:
                    eid = platforms.get(domain, "")
                    if eid and wide is not None:
                        wide[rec["id"]] = domain
        if eid:
            out[rec["id"]] = eid
    return out


def subject_of(records: list[str], dig: dict) -> str:
    """The entity a cause citing ``records`` is filed under, or "".

    Read off the digest's own records, device-level ones before log lines,
    in the order the cause cites them — so the same cause is the same
    entity every night, and a cause about nothing the registry holds stays
    about nothing.
    """
    subjects = dig.get("subjects") or {}
    kinds = {r["id"]: r["kind"] for r in dig.get("records") or []}
    for wanted in (True, False):
        for rid in records:
            if (kinds.get(rid) in _DEVICE_KINDS) == wanted and subjects.get(rid):
                return subjects[rid]
    return ""


def digest(collected: dict, now: float, set_aside=frozenset()) -> dict:
    """The records a pass reasons over, with ids.

    ``set_aside`` is the entities the owner set aside on the offline check
    (answered Wrong, snoozed): a log line about one of them — by an entity
    it names, or the device it is on — is held back the way that check
    holds its row, so the overnight pass does not file the same device
    under a new name."""
    zha = _zha_records(collected.get("zha") or [], now,
                       collected.get("areas") or {})
    # What each mesh device carries, so a cause about a router can name
    # the light or plug a person knows it as.
    owned: dict[str, list[str]] = {}
    for e in collected.get("entities") or []:
        if isinstance(e, dict) and e.get("device_id") and e.get("entity_id"):
            owned.setdefault(str(e["device_id"]), []).append(str(e["entity_id"]))
    for rec in zha:
        if rec.get("device_id") in owned:
            rec["entities"] = sorted(owned[rec["device_id"]])[:4]
    reg = [e for e in collected.get("entities") or [] if isinstance(e, dict)
           and e.get("entity_id")]
    known = ({str(e["entity_id"]) for e in reg}
             | set((collected.get("states") or {}).keys()))
    platforms = {str(e["entity_id"]): str(e.get("platform") or "") for e in reg}
    manifests = collected.get("manifests") or []
    logs = _log_records(collected.get("log") or [], now, known,
                        collected.get("devices") or [],
                        collected.get("user_text"), platforms, manifests,
                        {str(e["entity_id"]): str(e.get("device_id") or "")
                         for e in reg if e.get("device_id")})
    manifest_names = {str(m.get("domain")): str(m.get("name") or "")
                      for m in manifests if isinstance(m, dict)
                      and m.get("domain") and m.get("name")}
    aside = {str(e) for e in set_aside or ()}
    aside_devices = {str(e.get("device_id")) for e in reg
                     if str(e["entity_id"]) in aside and e.get("device_id")}
    kept = []
    for rec in logs:
        ents = set(rec.get("entities") or [])
        devs = set(rec.get("devices") or [])
        if (ents or devs) and ents <= aside and devs <= aside_devices:
            continue
        if rec.get("integration") in manifest_names:
            rec["integration_name"] = manifest_names[rec["integration"]]
        if _MISSING_RE.search(rec.get("message") or ""):
            callers = called_by(rec, collected)
            if callers:
                rec["called_by"] = callers
        kept.append(rec)
    logs = kept
    records = (logs + zha
               + _zwave_records(collected.get("states") or {},
                                collected.get("entities") or [],
                                collected.get("devices") or [])
               + _router_switch_records(collected.get("automations") or [],
                                        zha, collected.get("entities") or []))
    # `subjects` rides beside the records and never in the prompt (`frame`
    # sends the records alone): it is the code's answer to which entity a
    # cause is about, not something for the run to choose from.
    # Which device each entity is on, for the entities a cause can name —
    # so "which problem is this cause about" can be asked of a device.
    named: set[str] = set()
    for r in records:
        named |= _record_entities(r)
    entity_device = {str(e["entity_id"]): str(e.get("device_id") or "")
                     for e in reg if e.get("device_id")
                     and str(e["entity_id"]) in named}
    # What every entity and device is called, for `_unrelated`: a cause's
    # prose may name only what its own records are about. Beside the
    # records and never in the prompt, `subjects`' reason.
    names = {}
    for eid, st in (collected.get("states") or {}).items():
        attrs = (st or {}).get("attributes") if isinstance(st, dict) else None
        friendly = str((attrs or {}).get("friendly_name") or "").strip()
        names[str(eid)] = friendly
    for eid in known:
        names.setdefault(eid, "")
    device_names = {}
    for d in collected.get("devices") or []:
        if isinstance(d, dict) and d.get("id"):
            device_names[str(d["id"])] = [
                n for n in {str(d.get("name_by_user") or ""),
                            str(d.get("name") or "")} if n]
    entity_devices = {str(e["entity_id"]): str(e.get("device_id") or "")
                      for e in reg if e.get("device_id")}
    wide: dict[str, str] = {}
    return {"records": records,
            "integration_names": integration_names(
                records, collected.get("config_entries") or [],
                collected.get("manifests") or []),
            "subjects": _subjects(records, collected.get("entities") or [],
                                  wide, known),
            "wide": wide,
            "platforms": platforms,
            "entity_device": entity_device,
            "names": names, "device_names": device_names,
            "entity_devices": entity_devices,
            "area_names": sorted({str(v).lower() for v in
                                  (collected.get("areas") or {}).values() if v}),
            "available": dict(collected.get("available") or {})}


def integration_names(records: list[dict], entries: list[dict],
                      manifests: list[dict]) -> dict[str, str]:
    """`{domain: name}` for every integration a record names, as Home
    Assistant shows it: the manifest's name, else the title of its only
    config entry, else the domain spelled as words. Never the domain."""
    by_manifest = {str(m.get("domain") or ""): str(m.get("name") or "").strip()
                   for m in manifests if m.get("domain")}
    titles: dict[str, list[str]] = {}
    for e in entries:
        if e.get("domain") and str(e.get("title") or "").strip():
            titles.setdefault(str(e["domain"]), []).append(
                str(e["title"]).strip())
    out: dict[str, str] = {}
    for rec in records:
        for key in ("integration", "owner"):
            domain = str(rec.get(key) or "")
            if not domain or domain in out:
                continue
            only = titles.get(domain) or []
            out[domain] = (by_manifest.get(domain)
                           or (only[0] if len(only) == 1 else "")
                           or spell_integration(domain))
    return out


def integration_name(domain: str, dig: dict) -> str:
    return ((dig.get("integration_names") or {}).get(domain)
            or spell_integration(domain))


def plain_slugs(text: str, dig: dict) -> str:
    """``text`` with every integration domain the digest knows that a
    person would read as a key (`bambu_lab`) said as the integration's
    name."""
    for domain, name in (dig.get("integration_names") or {}).items():
        if "_" in domain and name:
            text = re.sub(r"(?<![\w.])" + re.escape(domain) + r"(?![\w])",
                          name, text)
    return text


def worth_a_run(dig: dict) -> bool:
    """Is there anything here a cause could be made of — decided before
    anything is spawned, so a healthy night costs nothing."""
    for r in dig.get("records") or []:
        if r["kind"] == "log" and (r["level"] in ("CRITICAL", "ERROR")
                                   or r["count"] >= WARNING_COUNT):
            return True
        if r["kind"] == "zigbee" and (not r["available"] or (
                isinstance(r.get("lqi"), (int, float)) and r["lqi"] < WEAK_LQI)
                or (r.get("last_seen_hours") or 0) > UNSEEN_HOURS):
            return True
        if r["kind"] == "zwave":
            return True
    return False


# Person-facing: each cause is filed as a finding the homeowner reads, in
# its title, detail and fix. Log messages are integration text, hence the
# fence. A tool-less schema run; SCHEMA's descriptions carry the limits,
# and `parse_causes` throws away a cause that cites no record it was given.
SYSTEM = prompt_kit.assemble(
    "You are a site-reliability engineer for one Home Assistant house. You "
    "group what went wrong overnight into ROOT CAUSES: the smallest number "
    "of underlying problems that explain the records.",
    inputs=(
        "You are given RECORDS, each with an id: system-log entries, Zigbee "
        "mesh devices (routers and struggling devices, with link quality "
        "and neighbours), Z-Wave nodes with dropped commands or dead "
        "status, and automations that switch off a device that is a Zigbee "
        "router."),
    tools="",
    good=(
        "One cause that explains five records is worth more than five "
        "causes. Each cause says what the records show and the one thing "
        "to do, and cites its records most fundamental first."),
    example=(
        "title \"The bedtime automation switches off the upstairs Zigbee "
        "router\"; detail \"The Landing Lamp plug routes for three "
        "upstairs sensors. The Bedtime automation turns it off at 23:00, "
        "and all three go unavailable within minutes.\"; fix \"Leave the "
        "Landing Lamp plug powered and turn the lamp off at the bulb "
        "instead.\"; severity serious; records the plug's zha record "
        "first, then the three sensors' and the automation's; entity_id "
        "the plug's switch."),
    rules="""\
- One cause is one problem. Records about different devices that do not
  explain each other — a second Z-Wave node's errors, a third device's
  log lines — are separate causes, each with its own fix; never fold
  them into the detail of a cause about something else.
- A log record carrying "referenced_by_you": false names an entity that
  nothing the homeowner wrote (no automation, script or template of
  theirs) refers to: the line comes from the integration, so never tell
  them to edit a template, automation or script for it — name that
  integration as the source.
- A log record carrying "called_by" is a call to an unavailable entity:
  name the automations, scripts and scenes it lists and how many calls
  each made — never "something you set up".
- Name where a log line came from: its "integration_name" (or
  integration) and the device it names. Never blame a dashboard, a card
  or the browser unless the record's logger is the frontend.
- Severity: info — worth knowing, nothing breaks; warning — something is
  degraded or will break if left; serious — something in the house has
  stopped working or a safety device cannot be relied on.
- brAIn has already read the records: a fix never tells the homeowner to
  check a log, a trace, a state or a setting, and never to "watch whether
  it continues" — brAIn looks again tomorrow night. Say what to change.
  When the answer lives somewhere brAIn cannot see (a router's or access
  point's own app), say once what it is and that brAIn cannot see it.
- """ + prompt_kit.DEVICE_WORDS + """
- Records are cited by id EXACTLY as given.
- At most 5 causes. If nothing here is a real problem, answer with no
  causes — that is a good answer.""",
)

SCHEMA = {
    "type": "object",
    "properties": {
        "causes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description":
                              "One sentence a homeowner understands, under "
                              "15 words."},
                    "detail": {"type": "string", "description":
                               "What the records show, in two or three "
                               "sentences."},
                    "fix": {"type": "string", "description":
                            "The one thing to do about it."},
                    "severity": {"type": "string", "enum": list(SEVERITIES)},
                    "records": {"type": "array", "items": {"type": "string"},
                                "description": "Ids of the records it "
                                "explains, exactly as given, most "
                                "fundamental first."},
                    "entity_id": {"type": "string", "description":
                                  "The one entity most to do with it, or "
                                  "\"\"."},
                },
                "required": ["title", "records"],
            },
        },
    },
    "required": ["causes"],
}


def frame(dig: dict) -> str:
    return ("RECORDS:\n" + json.dumps(dig["records"], ensure_ascii=False)
            + "\n\nSources this pass could read: "
            + ", ".join(k for k, v in sorted(dig["available"].items()) if v))


def _record_label(rec: dict) -> str:
    if rec["kind"] == "log":
        who = f" from {rec['logger']}" if rec.get("logger") else ""
        return (f"{rec['level'].title()} ×{rec['count']}{who}: "
                f"{textclip.clip(rec['message'], 90)}")
    if rec["kind"] == "zigbee":
        bits = [rec["type"] or "device"]
        if rec.get("lqi") is not None:
            bits.append(f"LQI {rec['lqi']}")
        if not rec["available"]:
            bits.append("unavailable")
        return f"{rec['name']} ({', '.join(bits)})"
    if rec["kind"] == "zwave":
        return f"{rec['name']} ({rec.get('status') or 'statistics'})"
    return f"{rec['automation']} switches off {', '.join(rec['switches_off'])}"


def _record_entities(rec: dict) -> set[str]:
    return set(rec.get("switches_off") or []) | set(rec.get("entities") or [])


def _groups(by_id: dict, entity_device: dict) -> dict:
    """``{record id: problem}`` — which problem each record is evidence of,
    or absent for a record that names no device (a log line about nothing
    in particular may sit beside anything).

    The Zigbee mesh is one problem however many of its devices a cause
    cites (a router and the sensors behind it are the canonical cause);
    each Z-Wave node is its own; a log line is about the one device it
    names, which is that node's or the mesh's problem when it is one of
    theirs.
    """
    zw = {rid.split(":", 1)[1]: rid for rid, r in by_id.items()
          if r["kind"] == "zwave"}
    mesh = {str(r.get("device_id")) for r in by_id.values()
            if r["kind"] == "zigbee" and r.get("device_id")}

    def of_device(dev: str) -> str:
        if dev in zw:
            return zw[dev]
        if dev in mesh:
            return "mesh"
        return f"dev:{dev}"

    out: dict[str, str] = {}
    for rid, r in by_id.items():
        if r["kind"] in ("zigbee", "automation"):
            out[rid] = "mesh"
        elif r["kind"] == "zwave":
            out[rid] = rid
        elif r["kind"] == "log":
            devs = set(r.get("devices") or [])
            devs |= {entity_device[e] for e in r.get("entities") or []
                     if entity_device.get(e)}
            if len(devs) == 1:
                out[rid] = of_device(devs.pop())
    return out


def _names_of(rec: dict) -> set[str]:
    names = {rec["id"]} | _record_entities(rec)
    for key in ("name", "automation"):
        if rec.get(key) and len(str(rec[key])) >= 4:
            names.add(str(rec[key]))
    return names


_SENTENCES = re.compile(r"(?<=[.!?])\s+")


def _without(text: str, names: set[str]) -> str:
    """``text`` less every sentence that mentions one of ``names``."""
    if not text or not names:
        return text
    lowered = [n.lower() for n in names if n]
    kept = [s for s in _SENTENCES.split(text)
            if not any(n in s.lower() for n in lowered)]
    return " ".join(kept).strip()


_TEMPLATE_WORDS = re.compile(r"\btemplates?\b", re.I)


def _without_words(text: str, pattern) -> str:
    """``text`` less every sentence ``pattern`` matches."""
    if not text:
        return text
    return " ".join(x for x in _SENTENCES.split(text)
                    if not pattern.search(x)).strip()


def _name_the_callers(recs: list[dict], dig: dict, title: str, detail: str,
                      fix: str) -> tuple[str, str, str]:
    """A cause citing a line about calls to an unavailable entity names the
    automations, scripts and scenes that made them, with how many each —
    never "something you set up", which is what a model writes when it
    was not told."""
    callers, seen, target = [], set(), ""
    names = dig.get("names") or {}
    for rec in recs:
        for c in rec.get("called_by") or []:
            if c["name"] not in seen:
                seen.add(c["name"])
                callers.append(c)
        if rec.get("called_by") and not target and rec.get("entities"):
            eid = rec["entities"][0]
            target = names.get(eid) or eid
    if not callers:
        return title, detail, fix
    listing = ", ".join(f"{c['name']} ({c['kind']}, {_calls_said(c['calls'])})"
                        for c in callers)
    said = (f"{target} is unavailable, and these still try to control it: "
            f"{listing}.")
    rest = _without_words(detail, _VAGUE_RE)
    detail = f"{said} {rest}".strip()
    who = _and([c["name"] for c in callers])
    fix = (f"Bring {target} back online, or take it out of {who} if it is "
           "gone for good.")
    if _VAGUE_RE.search(title) or target.lower() not in title.lower():
        title = textclip.clip(f"{who} still control {target}, which is "
                              "unavailable", MAX_TITLE)
    return title, detail, fix


def _with_source(logs: list[dict], dig: dict, detail: str) -> str:
    """The detail says what the lines came from — the integration and the
    device — when it does not already."""
    rec = logs[0]
    thing, where = _thing_of(rec, dig), _source_of(rec, dig)
    low = detail.lower()
    if (not thing or thing.lower() in low) and (not where or where.lower() in low):
        return detail
    bits = []
    if where:
        bits.append(f"the {where} integration")
    if thing:
        bits.append(f"about {thing}")
    return f"{detail} The lines come from {' '.join(bits)}.".strip()


def _record_fix(rec: dict, dig: dict) -> str:
    """What to do about one record, in plain words, for a cause that came
    back with no fix of its own."""
    if rec["kind"] == "zigbee":
        return ("Check it has power, then move it closer to the Zigbee "
                "coordinator or a mains-powered Zigbee device, or add one "
                "between them.")
    if rec["kind"] == "zwave":
        return ("Check it has power, then open it in Settings > Devices & "
                "services > Z-Wave and re-interview it.")
    if rec["kind"] == "automation":
        return ("Edit that automation so it no longer switches the plug off: "
                "a Zigbee router has to stay powered for the devices behind "
                "it.")
    return _not_your_template_fix([rec], dig)


def _not_your_template_fix(logs: list[dict], dig: dict | None = None) -> str:
    who = next((str(r.get("owner") or r.get("integration") or "")
                for r in logs if r.get("owner") or r.get("integration")), "")
    where = (f"the {integration_name(who, dig or {})} integration" if who
             else "an integration")
    return (f"This comes from {where}, not from anything you wrote: check "
            "that integration's settings, or report it to its author if it "
            "keeps happening.")


# Integration names that are also everyday words in a fix ("the sensor",
# "a template") or Home Assistant's own plumbing: never read as naming
# another integration.
_PLAIN_INTEGRATIONS = frozenset({
    "sensor", "binary_sensor", "switch", "light", "template", "automation",
    "script", "scene", "homeassistant", "recorder", "http", "frontend",
    "zha", "zwave_js", "mqtt", "default_config", "history", "logbook",
})


def _own_names(real: list[str], by_id: dict, dig: dict, eid: str) -> set[str]:
    """Everything a cause citing ``real`` may name: its records' entities,
    their names and devices, and the integrations its log lines are from."""
    names = dig.get("names") or {}
    dev_names = dig.get("device_names") or {}
    ent_dev = dig.get("entity_devices") or {}
    own: set[str] = set()
    devices: set[str] = set()
    entities: set[str] = {eid} if eid else set()
    for rid in real:
        rec = by_id[rid]
        own |= {n for n in _names_of(rec) if n}
        entities |= _record_entities(rec)
        devices |= set(rec.get("devices") or [])
        if rec.get("device_id"):
            devices.add(str(rec["device_id"]))
        if rec["kind"] == "zwave":
            devices.add(rid.split(":", 1)[1])
        for key in ("integration", "owner"):
            if rec.get(key):
                own.add(str(rec[key]))
    for e in entities:
        own.add(e)
        if names.get(e):
            own.add(names[e])
        if ent_dev.get(e):
            devices.add(ent_dev[e])
    for dev in devices:
        own |= set(dev_names.get(dev) or [])
    return {n.lower() for n in own if n}


def _house_names(dig: dict, by_id: dict) -> set[str]:
    """Every name a sentence could use for a thing in this house: entity
    ids, friendly names of two words or more, device names, and the
    integrations tonight's log lines came from — less room names, which a
    sentence about anything may say."""
    areas = set(dig.get("area_names") or ())
    out: set[str] = set()
    for eid, friendly in (dig.get("names") or {}).items():
        out.add(eid.lower())
        f = str(friendly or "").strip().lower()
        if len(f.split()) >= 2 and len(f) >= MIN_DEVICE_NAME and f not in areas:
            out.add(f)
    for dev_list in (dig.get("device_names") or {}).values():
        for n in dev_list or []:
            n = str(n).strip().lower()
            if len(n) >= MIN_DEVICE_NAME and n not in areas:
                out.add(n)
    for rec in by_id.values():
        out |= {n.lower() for n in _record_entities(rec)}
        for key in ("name", "automation"):
            n = str(rec.get(key) or "").strip().lower()
            if len(n) >= MIN_DEVICE_NAME and n not in areas:
                out.add(n)
        for key in ("integration", "owner"):
            n = str(rec.get(key) or "").strip().lower()
            if len(n) >= 4 and n not in _PLAIN_INTEGRATIONS:
                out.add(n)
    return out


def _unrelated(text: str, pattern, own: set[str]) -> bool:
    """Whether ``text`` names a thing of this house that is not ``own``.
    Longest name first, so "Kitchen motion" is not read as "Kitchen"."""
    if not text or pattern is None:
        return False
    for match in pattern.finditer(text):
        if match.group(1).lower() not in own:
            return True
    return False


def _names_pattern(names: set[str]):
    names = [n for n in names if n]
    if not names:
        return None
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(r"(?<![\w.])(" + alts + r")(?![\w])", re.I)


def _plain_title(rec: dict, dig: dict) -> str:
    """A title naming only what this record is about, for a cause whose own
    title named something else."""
    names = dig.get("names") or {}
    if rec["kind"] == "zigbee":
        return f"{rec.get('name') or 'A Zigbee device'} is struggling on the Zigbee network"
    if rec["kind"] == "zwave":
        return f"The Z-Wave device {rec.get('name') or ''} is having trouble".replace("  ", " ")
    if rec["kind"] == "automation":
        return f"{rec.get('automation') or 'An automation'} switches off a Zigbee router"
    ents = rec.get("entities") or []
    if rec.get("called_by") and ents:
        target = names.get(ents[0]) or ents[0]
        return (f"{_and([c['name'] for c in rec['called_by']])} still "
                f"control {target}, which is unavailable")
    thing = _thing_of(rec, dig)
    where = _source_of(rec, dig)
    if thing and where:
        return f"Errors in the log from the {where} integration about {thing}"
    if thing:
        return f"Errors in the log about {thing}"
    return (f"Errors in the log from the {where} integration" if where
            else f"Errors in the log from {rec.get('logger') or 'Home Assistant'}")


def _and(names: list[str]) -> str:
    names = [n for n in names if n]
    return (", ".join(names[:-1]) + " and " + names[-1]
            if len(names) > 1 else (names[0] if names else ""))


def _source_of(rec: dict, dig: dict | None = None) -> str:
    """The integration a log record came from, as a person knows it:
    never its domain."""
    if rec.get("integration_name"):
        return str(rec["integration_name"])
    domain = str(rec.get("owner") or rec.get("integration") or "")
    return integration_name(domain, dig or {}) if domain else ""


def _thing_of(rec: dict, dig: dict) -> str:
    """The device or entity a log record is about, by name, or ""."""
    for dev in rec.get("devices") or []:
        named = (dig.get("device_names") or {}).get(dev) or []
        if named:
            return sorted(named)[0]
    for eid in rec.get("entities") or []:
        return (dig.get("names") or {}).get(eid) or eid
    return ""


def _ago(hours) -> str:
    try:
        h = float(hours)
    except (TypeError, ValueError):
        return ""
    if h < 1:
        return "within the last hour"
    if h < 1.5:
        return "about an hour ago"
    if h < 36:
        return f"about {round(h)} hours ago"
    return f"about {round(h / 24)} days ago"


def _log_said(logs: list[dict], dig: dict, detail: str = "",
              quote: bool = True) -> str | None:
    """The sentence a log-error finding owes its reader (#444): what the
    log said, in plain words, how many times and when it last did.

    Taken off the first cited line that has a message, the message with
    addresses and ids as words (`checks.integrations.shown`) after the
    redaction the record already had. ``None`` when no cited line says
    anything; "" when ``detail`` already quotes the line and its count."""
    from checks.integrations import shown  # noqa: PLC0415 — one wording
    for rec in logs:
        message = shown(str(rec.get("message") or "")).strip()
        if not message:
            continue
        count = int(rec.get("count") or 1)
        when = _ago(rec.get("last_hours_ago"))
        times = "once" if count == 1 else f"{count} times"
        tail = f"{times}, most recently {when}" if when else times
        low = detail.lower()
        if message[:40].lower() in low:
            return "" if str(count) in low else f"It was logged {tail}."
        where = _source_of(rec, dig)
        who = f"The {where} integration" if where else "Home Assistant"
        if not quote:
            # A template warning inside an integration nothing of theirs
            # refers to: quoting the word sends them looking for a template
            # of their own, so the line is said by who, how often and when.
            thing = _thing_of(rec, dig)
            about = f" about {thing}" if thing else ""
            return f"{who} logged this{about} {tail}."
        return f"{who} logged \u201c{textclip.clip(message, 160)}\u201d {tail}."
    return None


# Words a fix may use about anything, which say nothing about which error
# it answers.
_GENERIC_FIX_WORDS = frozenset(
    "check restart reload settings devices device services integration home "
    "assistant make sure that this with from then again your open error "
    "errors logs system keep keeps stop stops until after there their them "
    "they will into once look what when have does should could would".split())
_FIX_WORD = re.compile(r"[a-z]{4,}")


def _fix_follows(fix: str, logs: list[dict], dig: dict) -> bool:
    """Whether a fix says something the error it answers is about: a word
    of the logged message, of an entity the message writes out, or of an
    automation or script that made the failing calls (#444)."""
    names = dig.get("names") or {}
    about = []
    for rec in logs:
        about.append(str(rec.get("message") or ""))
        for eid in rec.get("entities") or []:
            about += [eid, str(names.get(eid) or "")]
        for c in rec.get("called_by") or []:
            about.append(str(c.get("name") or ""))
    said = set(_FIX_WORD.findall(" ".join(about).lower()))
    words = set(_FIX_WORD.findall(str(fix or "").lower())) - _GENERIC_FIX_WORDS
    return bool(words & said)


def _error_fix(logs: list[dict], dig: dict) -> str:
    """A fix for the error a log-only cause describes, when the run's own
    fix said nothing about it."""
    rec = logs[0]
    thing, where = _thing_of(rec, dig), _source_of(rec, dig)
    if thing:
        return (f"The error is about {thing}: open it in Settings > Devices "
                "& services, put right what the error says is wrong, then "
                + (f"reload the {where} integration." if where
                   else "reload its integration."))
    if where:
        return (f"Put right what the error says is wrong in the {where} "
                "integration's settings in Settings > Devices & services, "
                "then reload it.")
    return ("Read the error in Settings > System > Logs and put right what "
            "it names.")


def _source_fix(logs: list[dict], dig: dict) -> str:
    """A fix for what the log lines came from, when the run's own fix was
    about something else."""
    rec = logs[0]
    thing, where = _thing_of(rec, dig), _source_of(rec, dig)
    if thing:
        return (f"Check that {thing} is powered on and reachable on the "
                "network, or remove it from "
                + (f"the {where} integration" if where else "its integration")
                + " if it is gone for good.")
    if where:
        return (f"Check the {where} integration in Settings > Devices & "
                "services, then reload it.")
    return ""


# Prose that blames a thing without naming it. A cause citing a line that
# says what made the calls names them instead.
_VAGUE_RE = re.compile(
    r"\bsomething (?:you|the household|the homeowner|they|somebody) "
    r"(?:have |has )?set up\b|\bwhatever (?:still )?controls?\b", re.I)
# The frontend's words. A cause may use them only when it cites a line the
# frontend (the browser, a dashboard, a card) wrote.
_FRONTEND_WORDS = re.compile(
    r"\b(?:dashboards?|morph|browsers?|frontend|lovelace|custom cards?)\b",
    re.I)


def _from_frontend(rec: dict) -> bool:
    return rec["kind"] == "log" and (
        _is_frontend(rec.get("logger") or "")
        or rec.get("integration") in ("morph", "frontend", "lovelace"))


def _calls_said(calls) -> str:
    if calls is None:
        return "runs not counted"
    return f"{calls} call" + ("" if calls == 1 else "s")


def parse_causes(answer: dict | None, dig: dict) -> dict:
    """`{causes, refused, invented, bundled, rewritten, unrelated}` — only
    causes citing real records, each about one problem.

    `invented` counts ids that were not in the digest at all: a cause can
    survive one of those if it also cites a real record, and the number is
    kept because a run that keeps making ids up is a run worth reading.
    `bundled` counts causes that cited records about another problem as
    well (those records, and the sentences about them, are taken off), and
    `rewritten` the fixes that told the homeowner to edit a template no
    template of theirs could be behind. `unrelated` counts the causes whose
    prose named a device, entity or integration their own records are not
    about: the sentence naming it is taken out of the detail and the fix,
    and a title naming it is replaced by one naming the cause's own record.
    """
    by_id = {r["id"]: r for r in dig.get("records") or []}
    house_names = _house_names(dig, by_id)
    entities: set[str] = set()
    for r in by_id.values():
        entities |= _record_entities(r)
    entity_device = dig.get("entity_device") or {}
    groups = _groups(by_id, entity_device)
    causes_in = (answer or {}).get("causes") if isinstance(answer, dict) else None
    causes, refused, invented = [], 0, 0
    bundled = rewritten = unrelated = unstated = unfollowed = 0
    for raw in causes_in if isinstance(causes_in, list) else []:
        if len(causes) >= MAX_CAUSES:
            break
        if not isinstance(raw, dict):
            refused += 1
            continue
        cited = [str(c) for c in raw.get("records") or [] if isinstance(c, str)]
        real = [c for c in dict.fromkeys(cited) if c in by_id]
        invented += len([c for c in cited if c not in by_id])
        title = textclip.clip(
            re.sub(r"\s+", " ", str(raw.get("title") or "")).strip(), MAX_TITLE)
        if not real or not title:
            refused += 1
            continue
        severity = raw.get("severity")
        eid = str(raw.get("entity_id") or "").strip()
        cited: set[str] = set()
        for r in real:
            cited |= _record_entities(by_id[r])
        # The entity has to be one the cause's OWN records name: a cause
        # about the cellar node is not filed under the landing plug because
        # that plug is somewhere else in tonight's digest.
        eid = eid if eid in entities and eid in cited else ""
        if eid and all(by_id[r]["kind"] == "log" for r in real):
            # A cause about log lines is filed only under what those lines
            # resolve to (`log_subjects`): an entity the run picked from a
            # line of another integration's is a guess (#434).
            platforms = dig.get("platforms") or {}
            allowed: set[str] = set()
            for r in real:
                allowed |= set(log_subjects(by_id[r], platforms,
                                            set(platforms) | entities))
            if eid not in allowed:
                eid = ""
        detail = re.sub(r"\s+", " ", str(raw.get("detail") or "")).strip()
        fix = re.sub(r"\s+", " ", str(raw.get("fix") or "")).strip()
        # One cause, one problem: the one its entity is on, else the one
        # its first (most fundamental) record is evidence of.
        subject = ""
        if eid and entity_device.get(eid):
            dev = entity_device[eid]
            subject = next((g for rid, g in groups.items()
                            if rid.split(":", 1)[-1] == dev
                            or (g == "mesh" and by_id[rid].get("device_id") == dev)
                            or g == f"dev:{dev}"), f"dev:{dev}")
        if not subject or not any(groups.get(r) == subject for r in real):
            # An entity on a device none of the cited records is about says
            # nothing about which of them the cause is.
            subject = next((groups[r] for r in real if r in groups), "")
        others = [r for r in real if r in groups and groups[r] != subject]
        if subject and others:
            real = [r for r in real if r not in others]
            mine: set[str] = set()
            for r in real:
                mine |= _names_of(by_id[r])
            gone: set[str] = set()
            for r in others:
                gone |= _names_of(by_id[r]) - mine
            detail = _without(detail, gone)
            if eid and eid not in mine:
                eid = ""
            bundled += 1
        logs = [by_id[r] for r in real if by_id[r]["kind"] == "log"]
        not_theirs = False
        if (logs and any(r.get("referenced_by_you") is False for r in logs)
                and not any(r.get("referenced_by_you") for r in logs)
                and not any(by_id[r]["kind"] == "automation" for r in real)
                and (_TEMPLATE_WORDS.search(fix)
                     or _TEMPLATE_WORDS.search(detail))):
            # Nothing the homeowner wrote refers to what the line is about,
            # so "edit the template" sends them looking for a template
            # that is not theirs. The integration is the source.
            fix = _not_your_template_fix(logs, dig)
            kept = [s for s in _SENTENCES.split(detail)
                    if not _TEMPLATE_WORDS.search(s)]
            detail = " ".join(kept).strip()
            rewritten += 1
            not_theirs = True
        # A cause names only what its own records are about. A fix telling
        # somebody to reload an integration entry none of them came from,
        # or a title about a sensor its template never reads, is a sentence
        # about another problem — `bundled`'s rule for prose.
        own = _own_names(real, by_id, dig, eid)
        pattern = _names_pattern(house_names | own)
        touched = False
        for field in ("detail", "fix"):
            value = detail if field == "detail" else fix
            kept = [sent for sent in _SENTENCES.split(value)
                    if not _unrelated(sent, pattern, own)]
            if len(kept) != len(_SENTENCES.split(value)) and value:
                touched = True
                value = " ".join(kept).strip()
                if field == "detail":
                    detail = value
                else:
                    fix = value
        if _unrelated(title, pattern, own):
            title = textclip.clip(_plain_title(by_id[real[0]], dig), MAX_TITLE)
            touched = True
        if not any(_from_frontend(by_id[r]) for r in real):
            # The dashboard, a card, the browser: the frontend's own
            # words, about a cause none of whose lines the frontend wrote.
            detail = _without_words(detail, _FRONTEND_WORDS)
            kept_fix = _without_words(fix, _FRONTEND_WORDS)
            touched = touched or kept_fix != fix
            fix = kept_fix
            if _FRONTEND_WORDS.search(title):
                title = textclip.clip(_plain_title(by_id[real[0]], dig),
                                      MAX_TITLE)
                touched = True
        if touched:
            unrelated += 1
        title, detail, fix = _name_the_callers(
            [by_id[r] for r in real], dig, title, detail, fix)
        title, detail, fix = (plain_slugs(title, dig), plain_slugs(detail, dig),
                              plain_slugs(fix, dig))
        only_logs = bool(logs) and len(logs) == len(real)
        said = _log_said(logs, dig, detail, quote=not not_theirs) \
            if logs else ""
        if only_logs and said is None:
            # A finding about log errors that cannot say what the error
            # was is a card with nothing in it (#444): held back, counted.
            unstated += 1
            continue
        if only_logs and fix and not _fix_follows(fix, logs, dig):
            # A fix that says nothing the error is about ("restart it on
            # its dock" under a cloud error) is replaced by one that does.
            fix = _error_fix(logs, dig)
            unfollowed += 1
        if logs and not fix:
            fix = _source_fix(logs, dig)
        if not fix:
            # A run that wrote no fix, or one whose every sentence was about
            # another problem: the card still says what to do (#342).
            fix = _record_fix(by_id[real[0]], dig)
        if said:
            detail = f"{detail} {said}".strip()
        if logs:
            detail = _with_source(logs, dig, detail)
        causes.append({
            "title": title,
            "detail": textclip.clip(detail, MAX_DETAIL),
            "fix": textclip.clip(fix, MAX_FIX),
            "severity": severity if severity in SEVERITIES else "warning",
            "records": real,
            "anchor": real[0],
            "entity_id": eid,
        })
    return {"causes": causes, "refused": refused, "invented": invented,
            "bundled": bundled, "rewritten": rewritten,
            "unrelated": unrelated, "unstated": unstated,
            "unfollowed": unfollowed}


# ---------------------------------------------------------------------------
# Rows for the findings store, and the anchors that keep their text stable
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    path = path or STORE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"anchors": {}, "last": None}
    except (OSError, ValueError):
        return {"anchors": {}, "last": None, "unreadable": True}
    if not isinstance(data, dict):
        return {"anchors": {}, "last": None, "unreadable": True}
    anchors = data.get("anchors") if isinstance(data.get("anchors"), dict) else {}
    return {"anchors": anchors, "last": data.get("last")}


def save(state: dict, path: str | None = None) -> None:
    anchors = state.get("anchors") or {}
    if len(anchors) > MAX_ANCHORS:
        keep = sorted(anchors, key=lambda k: anchors[k].get("at", 0))[-MAX_ANCHORS:]
        anchors = {k: anchors[k] for k in keep}
    atomic_write.write_json(path or STORE,
                            {"anchors": anchors, "last": state.get("last")})


def rows(causes: list[dict], dig: dict, state: dict,
         now: float) -> list[dict]:
    """Findings-store rows, one per cause, with the cited records as their
    evidence and the text reused by anchor."""
    by_id = {r["id"]: r for r in dig.get("records") or []}
    anchors = state.setdefault("anchors", {})
    out = []
    for cause in causes:
        # The model's entity when it named one the records hold; otherwise
        # the one the cited records are about (`subject_of`) — a cause
        # with no entity could not fold, be corrected per entity, or match
        # the To Do item somebody moved it to.
        entity = cause["entity_id"] or subject_of(cause["records"], dig)
        known = anchors.get(cause["anchor"])
        if not (isinstance(known, dict) and known.get("text")) and entity:
            # A new anchor about an entity an earlier cause was filed under
            # is that cause cited from another record: the same text, so
            # the row it already has is refreshed rather than a second
            # filed beside it (or folded into it and then cleared by the
            # pass that refiled it).
            known = next((v for v in anchors.values() if isinstance(v, dict)
                          and v.get("entity") == entity and v.get("text")),
                         None)
        text = known["text"] if isinstance(known, dict) and known.get("text") \
            else cause["title"]
        # A title reused from an earlier night was written before the
        # integration had a name here.
        text = plain_slugs(text, dig)
        anchors[cause["anchor"]] = {"text": text, "at": int(now),
                                    "entity": entity}
        evidence = [{"entity": rid, "value": textclip.clip(
                         _record_label(by_id[rid]), 120),
                     "when": ""} for rid in cause["records"][:8]]
        # A cause every cited line of which is one integration's, filed
        # under that integration's stand-in rather than under anything a
        # line names, is about the integration as a whole: it says so, so
        # it is the same card as another check's row about that outage.
        wide = dig.get("wide") or {}
        domains = {wide.get(r) for r in cause["records"]}
        integration = (next(iter(domains)) if not cause["entity_id"]
                       and len(domains) == 1 and None not in domains else "")
        # The entities the cause is about, for the sweep that takes a row
        # off once every one of them is reporting again (#441): the
        # evidence names records, not entities.
        about: list[str] = []
        for rid in cause["records"]:
            for e in sorted(_record_entities(by_id[rid])):
                if e not in about:
                    about.append(e)
        out.append({
            "text": text,
            "detail": cause["detail"] or cause["title"],
            "fix": cause["fix"],
            "severity": cause["severity"],
            "fixable": False,
            "entity_id": entity,
            "source": SOURCE,
            "source_title": SOURCE_TITLE,
            "kind": "problem",
            "claim": cause["title"],
            "evidence": evidence,
            **({"integration": integration} if integration else {}),
            **({"about": about[:8]} if about else {}),
        })
    return out


def keep_keys(open_rows: list[dict], state: dict, available: dict,
              reported: set[str] | frozenset = frozenset()) -> set[str]:
    """The texts this pass may NOT clear: rows whose anchor lives in a
    source that did not answer tonight. 'I could not look' at the mesh is
    not the mesh having healed. Nor may it clear a row about an entity it
    reported again (``reported``): a cause in new words about the same
    entity folds into the row already there (`findings_store`'s subject
    fold), and the row it folded into is the one still being reported."""
    import findings_store
    by_text = {findings_store.normalize(v.get("text", "")): k
               for k, v in (state.get("anchors") or {}).items()
               if isinstance(v, dict)}
    family = {"log": "log", "zha": "zha", "zw": "registry", "auto": "zha"}
    keep = set()
    for row in open_rows:
        key = findings_store.normalize(row.get("text", ""))
        if row.get("entity_id") and row["entity_id"] in reported:
            keep.add(key)
            continue
        anchor = by_text.get(key, "")
        source = family.get(anchor.split(":", 1)[0], "log")
        if not available.get(source):
            keep.add(key)
    return keep


__all__ = ["SCHEMA", "SOURCE", "SYSTEM", "collect", "digest", "frame",
           "integration_of", "keep_keys", "load", "parse_causes",
           "read_user_text", "rows", "save", "subject_of", "worth_a_run"]
