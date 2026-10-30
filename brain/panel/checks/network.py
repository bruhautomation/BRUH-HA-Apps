"""Network health — Wi-Fi (UniFi), the Z-Wave mesh and the Zigbee mesh.

A device that keeps dropping off is the commonest complaint about a smart
home and the one Home Assistant explains least: an entity goes
`unavailable`, comes back, goes again, and nothing anywhere says whether
it was the device, the radio it talks through or the integration. Each of
the three networks a house runs keeps its own record of the answer, and
none of it reaches a state:

* **Wi-Fi.** The UniFi integration publishes a tracker per client saying
  which access point and radio it is associated with. A device whose
  tracker says it is connected while its own entities (another
  integration on the same device, joined through the device registry's
  MAC connection) have been unavailable for hours is a *hung association*
  — the radio holds the client and the client has stopped talking — and
  when several hang on one access point it is the access point, so they
  are one row naming it. A device that went unavailable many separate
  times in a week while UniFi never saw it leave is *flapping*.
* **Z-Wave.** `last_changed` resets at every restart, which is how a dead
  battery node stayed hidden for a year. Z-Wave JS keeps its own "last
  seen" per node (`zwave_js/node_statistics`), and the node's status says
  whether it sleeps on a battery; a battery node silent past three of its
  wake-up intervals (or a day and a bit when the interval is unknown) has
  dropped off. The same statistics carry the link's signal and
  round-trip time.
* **Zigbee.** ZHA records `last_seen`, link quality and the power source
  per device (`zha/devices`, already read for `dev.zha_unseen`).

**What is not a device dropping is said apart, or not at all.** A minute
in which Home Assistant restarted, or in which every UniFi tracker went
unavailable together, is the house or the integration; it is never
counted as a device's drop, and the second happening repeatedly is a
sentence of its own on the card.

**Every device dropping off is ONE card** (`connectivity`, check
`net.connectivity`): hung, flapping, silent on Z-Wave and quiet on Zigbee
are what it lists, kept up to date in place, and the per-device checks
it replaced (`REPLACED`) file nothing. One device is reported by one check: a hung association
is this module's, not `dev.unavailable`'s (which asks
:func:`wifi_hung_devices`), and a quiet Zigbee device is either
`net.zigbee_silent`'s (hours) or `dev.zha_unseen`'s (a week), decided by
one classifier (:func:`zigbee_quiet`) — `dev.unavailable` and
`dev.zwave_dead`'s arrangement.
"""
from __future__ import annotations

import re

from numfmt import count

from ._registry_facts import SELF_PLATFORMS, entry_not_loaded, is_node_status
from ._util import (DAY, SOFTWARE_DOMAINS, CouldNotLook, House,
                    after_restart, domain_of, num, without_mac, parse_ts, when)

# The integration whose trackers are the Wi-Fi clients.
UNIFI_PLATFORMS = frozenset({"unifi"})
# What the UniFi integration calls each radio.
RADIO_BANDS = {"ng": "2.4 GHz", "na": "5 GHz", "6e": "6 GHz"}
# A device whose own entities have all been unavailable this long while its
# tracker says it is connected is hung. Two hours rather than minutes: an
# integration that polls slowly, or a device rebooting after an update,
# is unavailable for a while with nothing wrong.
HUNG_MIN_S = 2 * 3600
# An integration with at least this many devices, every one of them down
# and spread over more than one access point, is the integration rather
# than the Wi-Fi — `sys.entry_failed` and the log say why.
OUTAGE_MIN_DEVICES = 3
# How much Wi-Fi history a checks pass fetches, and for how many clients:
# bounded the way the appliance and job fetches are.
FLAP_DAYS = 7
FLAP_FETCH_MAX = 30
# A device that went unavailable at least this many separate times in the
# window, with its tracker never leaving, is flapping.
FLAP_MIN_SPELLS = 10
# Changes this close together across this many entities are one event (a
# restart, an integration losing its server), never a device's own drop.
MASS_WINDOW_S = 90
MASS_MIN = 3
# Every UniFi tracker going down together this many times in the window is
# the integration's own row.
UNIFI_DROPS_MIN = 3
UNIFI_DROP_SHARE = 0.8
# Rows a check files at most; past it the rest go on the decision trail.
MAX_ROWS = 6

# The domains a probe entity is chosen from, best first: a switch or a
# light changes when somebody uses it, a sensor may change every few
# seconds and would make the history fetch a week of readings.
PROBE_DOMAINS = ("switch", "light", "binary_sensor", "lock", "cover", "fan",
                 "climate", "media_player", "valve", "siren", "vacuum",
                 "humidifier", "water_heater", "sensor")

# A label a person puts on a device they are not using. Matched as whole
# words against the label's name (and its id, which is the name slugified,
# for a label registry that could not be read).
NOT_IN_USE_PHRASES = ("not in use", "not used", "unused", "spare", "storage",
                      "stored", "inactive", "retired", "decommissioned",
                      "disabled", "offline")

# Z-Wave JS's node status (`NodeStatus`, an int over the WebSocket, a word
# on some payloads).
ZWAVE_STATUS = {0: "unknown", 1: "asleep", 2: "awake", 3: "dead", 4: "alive"}
ZWAVE_BATTERY_STATUSES = frozenset({"asleep", "awake"})
# A battery node checks in at least this often when its wake-up interval
# is unknown.
ZWAVE_SILENT_FALLBACK_S = 26 * 3600
# Three missed check-ins, never fewer than this however short the interval.
ZWAVE_MISSED_WAKEUPS = 3
ZWAVE_SILENT_FLOOR_S = 2 * 3600
# A link this weak or this slow is worth moving something for.
ZWAVE_RSSI_WEAK = -90
ZWAVE_RTT_SLOW_MS = 150
# Fewer commands than this since the statistics last reset and the signal
# and round trip are a handful of samples, not a link.
ZWAVE_MIN_COMMANDS = 5

# Zigbee: a router under this link quality weakens everything behind it.
ZIGBEE_WEAK_LQI = 40
# A weak router is only worth a card if it has also dropped out lately: the
# window its availability is read over, and how many routers are asked about.
ZIGBEE_DROPOUT_HOURS = 48
ZIGBEE_FETCH_MAX = 30
ZIGBEE_MAINS_QUIET_S = 6 * 3600
ZIGBEE_BATTERY_QUIET_S = 26 * 3600
# A device quieter than this has dropped off the mesh: `dev.zha_unseen`'s.
# Sleepy sensors check in daily at the very least; a week is not a sleep.
ZIGBEE_DROPPED_DAYS = 7


# ---------------------------------------------------------------------------
# shared
# ---------------------------------------------------------------------------

def _named(name: str, fallback: str) -> str:
    """A name with any hardware address taken out; the fallback when the
    name WAS the address (UniFi names a client with no host name by it)."""
    return without_mac(name) or fallback


def _self_platforms() -> frozenset:
    return SELF_PLATFORMS


def _phrase_words(text: str) -> str:
    return " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip() + " "


def _label_names(house: House, ids) -> list[str]:
    known = {}
    for row in house.snap.get("labels") or []:
        if isinstance(row, dict) and row.get("label_id"):
            known[str(row["label_id"])] = str(row.get("name") or "")
    out = []
    for label in ids or ():
        out.append(str(label))
        if known.get(str(label)):
            out.append(known[str(label)])
    return out


def not_in_use(house: House, device: dict | None, entity_id: str = "") -> bool:
    """A device somebody disabled, or labelled as not in use.

    Asked by every check here: a spare plug in a drawer and a sensor taken
    down for the summer go quiet because they are meant to, and a card
    about one is a card about a decision somebody already made.
    """
    labels: list = []
    if device:
        if device.get("disabled_by"):
            return True
        labels += list(device.get("labels") or ())
    reg = house.registry.get(entity_id) or {} if entity_id else {}
    if reg.get("disabled_by"):
        return True
    labels += list(reg.get("labels") or ())
    for name in _label_names(house, labels):
        words = _phrase_words(name)
        if any(f" {p} " in words for p in NOT_IN_USE_PHRASES):
            return True
    return False


def _device_entities(house: House, device_id: str) -> list[str]:
    return sorted(str(r["entity_id"]) for r in house.entities
                  if r.get("device_id") == device_id and r.get("entity_id"))


def _report_entity(house: House, device_id: str) -> str:
    """The entity a device's row is filed under: its first enabled one."""
    for eid in _device_entities(house, device_id):
        if house.enabled(eid):
            return eid
    return ""


# ---------------------------------------------------------------------------
# Wi-Fi (UniFi)
# ---------------------------------------------------------------------------

def norm_mac(value) -> str:
    return str(value or "").strip().lower().replace("-", ":")


def _mac_index(house: House) -> dict[str, list[str]]:
    """MAC → the device ids whose registry connections carry it."""
    out: dict[str, list[str]] = {}
    for dev_id, dev in house.devices.items():
        for conn in dev.get("connections") or ():
            if (isinstance(conn, (list, tuple)) and len(conn) == 2
                    and str(conn[0]).lower() == "mac"):
                out.setdefault(norm_mac(conn[1]), []).append(dev_id)
    return out


def device_keys(snap) -> dict[str, str]:
    """``{entity id: device id}`` for every entity that is on a device —
    the device a finding about it is ABOUT (#440).

    The registry's own device for most entities. A Wi-Fi client UniFi
    tracks is the exception: its tracker is joined to the device it is a
    client OF through the registry's MAC connection (`unifi_clients`' own
    join), and that device — the plug, the camera — is the key, so a drop
    filed on the plug's switch and one filed on its tracker are one
    device's. Where the MAC names several devices, the one carrying an
    entity of another integration than UniFi is the device itself. Pure
    over the snapshot, so the panel and the tests read one answer.
    """
    house = snap if isinstance(snap, House) else House(snap)
    out: dict[str, str] = {}
    for row in house.entities:
        if row.get("entity_id") and row.get("device_id"):
            out[str(row["entity_id"])] = str(row["device_id"])
    index = _mac_index(house)
    real: dict[str, bool] = {}
    for row in house.entities:
        if row.get("device_id") and row.get("platform") not in UNIFI_PLATFORMS:
            real[str(row["device_id"])] = True
    for eid in sorted(house.states):
        if domain_of(eid) != "device_tracker":
            continue
        attrs = (house.states.get(eid) or {}).get("attributes") or {}
        if not attrs.get("mac"):
            continue
        devs = sorted(index.get(norm_mac(attrs.get("mac")), ()))
        if not devs:
            continue
        own = [d for d in devs if real.get(d)]
        out[eid] = (own or devs)[0]
    return out


def ap_name(house: House, ap_mac: str) -> tuple[str, str]:
    """(name, entity id to file under) of the access point with this MAC."""
    mac = norm_mac(ap_mac)
    for dev_id in _mac_index(house).get(mac, ()):
        dev = house.devices[dev_id]
        return (_named(house.device_name(dev), "one access point"),
                _report_entity(house, dev_id))
    for eid, st in house.states.items():
        attrs = st.get("attributes") or {}
        if norm_mac(attrs.get("mac")) == mac and not attrs.get("ap_mac"):
            return _named(house.label(eid), "one access point"), eid
    return "one access point", ""


def unifi_clients(house: House) -> list[dict]:
    """Every wireless client the UniFi integration tracks, with the devices
    its MAC joins it to and their own entities (never UniFi's)."""
    index = _mac_index(house)
    selfp = _self_platforms()
    out = []
    for eid in sorted(house.states):
        if domain_of(eid) != "device_tracker":
            continue
        reg = house.registry.get(eid) or {}
        if reg.get("platform") not in UNIFI_PLATFORMS or not house.enabled(eid):
            continue
        st = house.states.get(eid) or {}
        attrs = st.get("attributes") or {}
        # A client is associated with an access point; the access points
        # and switches UniFi also tracks carry no `ap_mac`.
        if not attrs.get("ap_mac") or attrs.get("is_wired") is True:
            continue
        devices = set(index.get(norm_mac(attrs.get("mac")), ()))
        if reg.get("device_id"):
            devices.add(str(reg["device_id"]))
        own = []
        for row in house.entities:
            if row.get("device_id") not in devices or not row.get("entity_id"):
                continue
            other = str(row["entity_id"])
            if row.get("platform") in UNIFI_PLATFORMS | selfp:
                continue
            if row.get("disabled_by") or row.get("hidden_by") == "user":
                continue
            if str(row.get("entity_category") or "") in ("diagnostic", "config"):
                continue
            if domain_of(other) in SOFTWARE_DOMAINS or other not in house.states:
                continue
            own.append(other)
        if not own:
            continue
        devs = [house.devices[d] for d in sorted(devices) if d in house.devices]
        if any(not_in_use(house, d) for d in devs):
            continue
        out.append({"tracker": eid, "home": st.get("state") == "home",
                    "ap_mac": norm_mac(attrs.get("ap_mac")),
                    "band": RADIO_BANDS.get(str(attrs.get("radio") or "")),
                    "devices": sorted(devices), "own": sorted(own),
                    "name": _named(house.device_name(devs[0]) if devs
                                   else house.label(eid),
                                   "A device with no name")})
    return out


def _probe(house: House, own: list[str]) -> str:
    """The one entity a client's history is fetched for (`PROBE_DOMAINS`)."""
    rank = {d: i for i, d in enumerate(PROBE_DOMAINS)}
    ranked = sorted((rank.get(domain_of(e), len(rank)), e) for e in own)
    return ranked[0][1] if ranked and ranked[0][0] < len(rank) else ""


def wifi_history_candidates(snap: dict) -> list[dict]:
    """The clients whose week the checks pass fetches: a tracker and one
    probe entity each, at most `FLAP_FETCH_MAX`. Shared by the collector
    and the checks so they agree on what was asked."""
    house = House(snap)
    out = []
    for client in unifi_clients(house):
        probe = _probe(house, client["own"])
        if probe:
            out.append({**client, "probe": probe})
    return out[:FLAP_FETCH_MAX]


def _entry_down(house: House, eid: str) -> bool:
    return entry_not_loaded(house.snap, house.registry.get(eid) or {})


def _hung_clients(house: House, now: float) -> list[dict]:
    candidates = []
    for client in unifi_clients(house):
        if not client["home"]:
            continue
        own = client["own"]
        states = [house.states.get(e) or {} for e in own]
        if any(s.get("state") != "unavailable" for s in states):
            continue
        # The integration did not set up: `sys.entry_failed`'s row.
        if any(_entry_down(house, e) for e in own):
            continue
        downs = [parse_ts(s.get("last_changed")) for s in states]
        if any(t is None for t in downs):
            continue
        since = max(downs)
        if now - since < HUNG_MIN_S:
            continue
        candidates.append({**client, "since": min(downs)})
    # An integration whose every device is down, across more than one
    # access point, is the integration rather than the radio.
    by_platform: dict[str, set] = {}
    for row in house.entities:
        if row.get("device_id") and row.get("platform"):
            by_platform.setdefault(str(row["platform"]), set()).add(
                row["device_id"])
    hung_devices = {d for c in candidates for d in c["devices"]}
    out = []
    for c in candidates:
        platforms = {str((house.registry.get(e) or {}).get("platform") or "")
                     for e in c["own"]}
        outage = False
        for p in platforms:
            devs = by_platform.get(p, set())
            if len(devs) >= OUTAGE_MIN_DEVICES and devs <= hung_devices:
                aps = {x["ap_mac"] for x in candidates
                       if set(x["devices"]) & devs}
                if len(aps) > 1:
                    outage = True
        if not outage:
            out.append(c)
    return out


def wifi_hung_devices(snap: dict, now: float) -> set[str]:
    """Device ids a hung association claims — `dev.unavailable` stands
    down for them, so one box is never two rows under two fixes."""
    house = snap if isinstance(snap, House) else House(snap)
    return {d for c in _hung_clients(house, now) for d in c["devices"]}


def _rows(history: dict, eid: str) -> list[tuple[float, str]]:
    out = []
    for row in history.get(eid) or ():
        if not isinstance(row, dict):
            continue
        ts = parse_ts(row.get("last_changed") or row.get("lc")
                      or row.get("last_updated"))
        if ts is not None:
            out.append((ts, str(row.get("state") if "state" in row
                                else row.get("s"))))
    return sorted(out)


def _went_down(rows: list[tuple[float, str]]) -> list[float]:
    """The moments a series went INTO unavailable from something else."""
    out, prev = [], None
    for ts, state in rows:
        if state == "unavailable" and prev not in (None, "unavailable"):
            out.append(ts)
        prev = state
    return out


def _mass_moments(drops: dict[str, list[float]], minimum: int) -> list[float]:
    """The moments at least `minimum` of these series went down together."""
    events = sorted((t, e) for e, ts in drops.items() for t in ts)
    out: list[float] = []
    for i, (t, _e) in enumerate(events):
        near = {e for tt, e in events[i:] if tt - t <= MASS_WINDOW_S}
        if len(near) >= minimum and (not out or t - out[-1] > MASS_WINDOW_S):
            out.append(t)
    return out


def _near(t: float, moments: list[float], before: float = MASS_WINDOW_S,
          after: float = MASS_WINDOW_S) -> bool:
    return any(-before <= t - m <= after for m in moments)


def _wifi_week(snap: dict) -> tuple[dict, list[dict], dict, dict]:
    hist = (snap.get("wifi_history") or {}).get("entities") or {}
    cands = [c for c in wifi_history_candidates(snap)
             if c["probe"] in hist and c["tracker"] in hist]
    probe_drops = {c["probe"]: _went_down(_rows(hist, c["probe"]))
                   for c in cands}
    tracker_drops = {c["tracker"]: _went_down(_rows(hist, c["tracker"]))
                     for c in cands}
    return hist, cands, probe_drops, tracker_drops


def _unifi_moments(tracker_drops: dict) -> list[float]:
    n = len(tracker_drops)
    if n < MASS_MIN:
        return []
    return _mass_moments(tracker_drops, max(MASS_MIN,
                                            int(n * UNIFI_DROP_SHARE + 0.999)))


# ---------------------------------------------------------------------------
# Z-Wave
# ---------------------------------------------------------------------------

def zwave_status(node: dict) -> str:
    raw = (node.get("status") or {}).get("status") if isinstance(
        node.get("status"), dict) else None
    if isinstance(raw, bool):
        return "unknown"
    if isinstance(raw, int):
        return ZWAVE_STATUS.get(raw, "unknown")
    return str(raw or "unknown").lower()


def _device_has_battery(house: House, device_id: str) -> bool:
    for eid in _device_entities(house, device_id):
        attrs = (house.states.get(eid) or {}).get("attributes") or {}
        if attrs.get("device_class") == "battery":
            return True
    return False


def _zwave_entity_value(house: House, device_id: str, *names: str):
    """The state of a Z-Wave JS entity on this device named by its
    translation key or the end of its unique id."""
    for eid in _device_entities(house, device_id):
        reg = house.registry.get(eid) or {}
        if reg.get("platform") != "zwave_js":
            continue
        uid = str(reg.get("unique_id") or "")
        key = str(reg.get("translation_key") or "")
        if any(key == n or uid.endswith("." + n) or uid.endswith("-" + n)
               for n in names):
            st = (house.states.get(eid) or {}).get("state")
            if st not in (None, "unknown", "unavailable"):
                return st
    return None


def wake_interval_s(house: House, device_id: str, node: dict) -> float | None:
    """The node's wake-up interval in seconds, where anything says it."""
    for part in (node.get("status"), node.get("statistics")):
        if isinstance(part, dict):
            v = num(part.get("wake_up_interval") or part.get("wakeUpInterval"))
            if v and v > 0:
                return v
    v = num(_zwave_entity_value(house, device_id, "wake_up_interval",
                                "wakeUpInterval", "132-0-wakeUpInterval"))
    return v if v and v > 0 else None


def zwave_last_seen(house: House, device_id: str, node: dict) -> float | None:
    """When Z-Wave JS last heard from the node — its own record, which a
    restart does not reset. Never `last_changed`."""
    stats = node.get("statistics") if isinstance(node.get("statistics"), dict) else {}
    ts = parse_ts(stats.get("last_seen") or stats.get("lastSeen"))
    if ts is not None:
        return ts
    return parse_ts(_zwave_entity_value(house, device_id, "last_seen"))


def _zwave_nodes(house: House):
    for dev_id, node in sorted((house.snap.get("zwave_nodes") or {}).items()):
        if not isinstance(node, dict):
            continue
        dev = house.devices.get(dev_id)
        if not dev or not_in_use(house, dev):
            continue
        status = node.get("status") if isinstance(node.get("status"), dict) else {}
        if status.get("is_controller_node"):
            continue
        entity = ""
        for eid in _device_entities(house, dev_id):
            if is_node_status(eid, house.registry.get(eid) or {}):
                entity = eid
                break
        entity = entity or _report_entity(house, dev_id)
        if entity and not_in_use(house, dev, entity):
            continue
        yield dev_id, dev, node, entity


def _silent_nodes(house: House, now: float) -> list[dict]:
    out = []
    for dev_id, dev, node, entity in _zwave_nodes(house):
        status = zwave_status(node)
        if status == "dead":
            continue                     # `dev.zwave_dead`'s
        if status not in ZWAVE_BATTERY_STATUSES and not (
                status == "unknown" and _device_has_battery(house, dev_id)):
            continue
        seen = zwave_last_seen(house, dev_id, node)
        if seen is None:
            continue                     # could not tell — never last_changed
        interval = wake_interval_s(house, dev_id, node)
        limit = (max(ZWAVE_MISSED_WAKEUPS * interval, ZWAVE_SILENT_FLOOR_S)
                 if interval else ZWAVE_SILENT_FALLBACK_S)
        if now - seen < limit:
            continue
        out.append({"device_id": dev_id,
                    "name": _named(house.device_name(dev), "A Z-Wave device"),
                    "entity": entity, "seen": seen, "interval": interval})
    return out


def zwave_silent_devices(snap, now: float) -> set[str]:
    """Device ids `net.zwave_silent` claims — `dev.battery_low` stands down
    for them: a battery a silent node last reported is not news."""
    house = snap if isinstance(snap, House) else House(snap)
    return {n["device_id"] for n in _silent_nodes(house, now)}


def _span(seconds: float) -> str:
    """'45 minutes', '1 hour', '3 days': the noun agrees with its count."""
    if seconds < 3600:
        return count(max(1, int(seconds // 60)), "minute")
    hours = seconds / 3600
    if hours < 48:
        return count(int(hours), "hour")
    return count(int(hours / 24), "day")


def zwave_link(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    silent = {n["device_id"] for n in _silent_nodes(house, now)}
    rows = []
    for dev_id, dev, node, entity in _zwave_nodes(house):
        if dev_id in silent or zwave_status(node) == "dead":
            continue
        stats = node.get("statistics")
        if not isinstance(stats, dict):
            continue
        sent = num(stats.get("commands_tx"))
        if sent is not None and sent < ZWAVE_MIN_COMMANDS:
            continue
        rssi = num(stats.get("rssi"))
        rtt = num(stats.get("rtt"))
        # Z-Wave JS reports 125-127 for "no reading"; a signal is negative.
        weak = rssi is not None and -128 < rssi < 0 and rssi <= ZWAVE_RSSI_WEAK
        slow = rtt is not None and rtt >= ZWAVE_RTT_SLOW_MS
        if not (weak or slow):
            continue
        if entity and not house.should_report(entity, "net.zwave_link"):
            continue
        said = []
        if weak:
            said.append(f"its signal is {rssi:g} dBm (under {ZWAVE_RSSI_WEAK} "
                        "is weak)")
        if slow:
            said.append(f"a command takes {rtt:g} ms to come back (over "
                        f"{ZWAVE_RTT_SLOW_MS} ms is slow)")
        rows.append({
            "text": f"{_named(house.device_name(dev), 'A Z-Wave device')} "
                    "has a weak Z-Wave link",
            "detail": "Z-Wave JS says " + " and ".join(said)
                      + ". Commands to it are retried and can be lost.",
            "fix": ("Move it or the controller closer, or add a plugged-in "
                    "Z-Wave device between them (a smart plug works), then "
                    "rebuild its routes from its device page."),
            "severity": "warning",
            "fixable": False,
            "entity_id": entity,
            "_order": rssi if weak else 0,
        })
    rows.sort(key=lambda r: r["_order"])
    for r in rows:
        r.pop("_order", None)
    if len(rows) > MAX_ROWS:
        house.gave_up("net.zwave_link", rows[MAX_ROWS:],
                      "more weak links than one card a node can say")
        rows = rows[:MAX_ROWS]
    return rows


# ---------------------------------------------------------------------------
# Zigbee
# ---------------------------------------------------------------------------

def _zha_mains(dev: dict) -> bool:
    power = str(dev.get("power_source") or "").lower()
    return power.startswith("mains") or str(dev.get("device_type") or "") == "Router"


def zigbee_quiet(dev: dict, now: float) -> str | None:
    """`dropped` (a week: `dev.zha_unseen`'s), `quiet` (hours, by power
    source: `net.zigbee_silent`'s) or None. One classifier, so one device
    is never both."""
    seen = parse_ts(dev.get("last_seen"))
    if seen is None:
        return None
    quiet = now - seen
    if quiet >= ZIGBEE_DROPPED_DAYS * DAY:
        return "dropped"
    limit = ZIGBEE_MAINS_QUIET_S if _zha_mains(dev) else ZIGBEE_BATTERY_QUIET_S
    return "quiet" if quiet >= limit else None


def zigbee_devices(house: House):
    """`(zha row, registry device or None, entity to file under)` for every
    Zigbee device a check may speak about: never the coordinator, a
    disabled device or one labelled not in use."""
    for dev in house.snap.get("zha_devices") or []:
        if not isinstance(dev, dict):
            continue
        if str(dev.get("device_type") or "") == "Coordinator":
            continue
        reg_id = str(dev.get("device_reg_id") or "")
        reg = house.devices.get(reg_id)
        entity = _report_entity(house, reg_id) if reg else ""
        if not_in_use(house, reg, entity):
            continue
        yield dev, reg, entity


def zigbee_name(dev: dict, reg: dict | None, house: House) -> str:
    if reg:
        return _named(house.device_name(reg), "A Zigbee device")
    return _named(str(dev.get("user_given_name") or dev.get("name") or ""),
                  "A Zigbee device")


def zigbee_quiet_devices(snap, now: float) -> set[str]:
    """Registry device ids a Zigbee silence check claims (either class) —
    `dev.unavailable` stands down for them."""
    house = snap if isinstance(snap, House) else House(snap)
    return {str(d.get("device_reg_id")) for d, reg, _e in zigbee_devices(house)
            if reg and zigbee_quiet(d, now)}


def zigbee_history_candidates(snap: dict) -> list[str]:
    """The entity each plugged-in Zigbee device's availability is read off:
    what the collector fetches and `zigbee_weak` reads, so they agree."""
    house = House(snap)
    return [entity for dev, _reg, entity in zigbee_devices(house)
            if entity and _zha_mains(dev)][:ZIGBEE_FETCH_MAX]


def _dropouts(snap: dict, entity: str, now: float) -> list[float] | None:
    """When this entity went unavailable inside the window, or None when the
    recorder was not asked / would not answer (the check then goes on what
    the device reports now, as it always did)."""
    hist = snap.get("zigbee_history")
    if not isinstance(hist, dict) or entity not in (hist.get("entities") or {}):
        return None
    rows = _rows(hist["entities"], entity)
    start = now - ZIGBEE_DROPOUT_HOURS * 3600
    out = _went_down(rows)
    # Already unavailable when the window opened and back since is a drop too.
    before = [st for ts, st in rows if ts < start]
    inside = [t for t in out if t >= start]
    if before and before[-1] == "unavailable" and any(
            ts >= start and st != "unavailable" for ts, st in rows):
        inside.append(start)
    return sorted(inside)


def zigbee_weak(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    rows = []
    for dev, reg, entity in zigbee_devices(house):
        if not _zha_mains(dev) or zigbee_quiet(dev, now):
            continue
        if dev.get("available") is False:
            continue
        lqi = num(dev.get("lqi"))
        # 0 is "not measured" on most coordinators, never a link.
        if lqi is None or not 0 < lqi < ZIGBEE_WEAK_LQI:
            continue
        if entity and not house.should_report(entity, "net.zigbee_weak"):
            continue
        # A router that has held its link for two days is not a router with
        # a problem, whatever its quality number says now.
        drops = _dropouts(snap, entity, now) if entity else None
        if drops is not None and not drops:
            continue
        # The name and the entity both come from this one device record.
        name = zigbee_name(dev, reg, house)
        seen = ("" if drops is None else
                f" It dropped out {len(drops)} time"
                f"{'' if len(drops) == 1 else 's'} in the past "
                f"{ZIGBEE_DROPOUT_HOURS} hours, last {when(drops[-1])}.")
        rows.append({
            "text": f"{name} is a Zigbee router with a weak link",
            "detail": (f"{name}'s link quality is {lqi:g} out of 255 (under "
                       f"{ZIGBEE_WEAK_LQI} is weak)." + seen +
                       " Other Zigbee devices route through a plugged-in "
                       "one, so a weak router weakens everything behind it."),
            "fix": ("Move it or the coordinator closer, put the coordinator "
                    "on a USB extension cable away from USB 3 ports and the "
                    "Wi-Fi router, or add another plugged-in Zigbee device "
                    "between them."),
            "severity": "warning",
            "fixable": False,
            "entity_id": entity,
            "_lqi": lqi,
        })
    rows.sort(key=lambda r: r["_lqi"])
    for r in rows:
        r.pop("_lqi", None)
    if len(rows) > MAX_ROWS:
        house.gave_up("net.zigbee_weak", rows[MAX_ROWS:],
                      "too many weak routers at once to be the routers")
        rows = rows[:MAX_ROWS]
    return rows



# ---------------------------------------------------------------------------
# One card for every device dropping off the network
# ---------------------------------------------------------------------------
#
# A device hung on Wi-Fi, one that keeps dropping, a Z-Wave node gone
# silent and a Zigbee device gone quiet were each their own card, per
# device, and most of them were about a failure that had passed by the
# time anybody read it. They are one row now, under one stable text, so
# the store keeps it in place rather than filing it again: `add_many`
# dedupes it, `refresh_details` rewrites what it lists (`detail`, `items`,
# `fix`) as devices come and go, `items` carries the devices — a Wrong is
# an answer about each, and a device that turns up later is not swallowed
# by it (`findings_store.answered_items`) — and `clear_resolved` takes the
# row off when nothing is left. The detectors above are unchanged in what
# they count; what changed is that a device is LISTED only when it has
# been gone for hours (hung two, Zigbee six or a day, Z-Wave three
# wake-ups) or dropped again and again with the last drop recent, never a
# phone or a tracker, and never when many went at once.

CONNECTIVITY_TEXT = "Some devices keep dropping off the network"
CONNECTIVITY = "net.connectivity"
# The checks this one replaced. A Wrong given to one of them still stands
# down the device it was given about; their rows are cleared by this one
# (`checks.sources_ran`).
REPLACED = ("net.wifi_hung", "net.wifi_flapping", "net.unifi_dropped",
            "net.zwave_silent", "net.zigbee_silent")
# Repeated drops are listed only while the last one is this recent: a
# device that flapped last week and has held since has recovered.
RECENT_S = 3 * DAY
# Half or more of a mesh quiet at once is the coordinator or a restart,
# not the devices.
MASS_SHARE = 0.5
# A phone (or anything a person carries) leaves and comes back by design.
PHONE_PLATFORMS = frozenset({"mobile_app"})
PHONE_DOMAINS = frozenset({"device_tracker", "person"})
# How many devices the detail names before "and N more"; every one is in
# `items`, which the card's Show all lists.
DETAIL_NAMES = 4
# Each network's snapshot key and the platforms that say a house has it:
# a house with the integration whose source could not be read is "could
# not look", and a house without it simply has nothing there.
SOURCES = {"Wi-Fi": ("wifi_history", UNIFI_PLATFORMS),
           "Z-Wave": ("zwave_nodes", frozenset({"zwave_js"})),
           "Zigbee": ("zha_devices", frozenset({"zha"}))}


def _carried(house: House, devices, entity: str) -> bool:
    """Whether this is a phone or a tracker: something a person carries,
    which leaves and comes back by design."""
    if domain_of(entity) in PHONE_DOMAINS:
        return True
    for row in house.entities:
        if row.get("device_id") in set(devices or ()) and \
                str(row.get("platform") or "") in PHONE_PLATFORMS:
            return True
    return str((house.registry.get(entity) or {}).get("platform") or "") \
        in PHONE_PLATFORMS


def _wifi_entries(house: House, snap: dict, now: float) -> tuple[list, list, str]:
    """`(devices, access point sentences, UniFi sentence)` for Wi-Fi."""
    out, aps = [], []
    by_ap: dict[str, list[dict]] = {}
    for c in _hung_clients(house, now):
        by_ap.setdefault(c["ap_mac"], []).append(c)
        ap, _e = ap_name(house, c["ap_mac"])
        radio = f" on its {c['band']} radio" if c["band"] else ""
        out.append({"entity": c["own"][0], "devices": c["devices"],
                    "name": c["name"], "network": "Wi-Fi",
                    "old": ("net.wifi_hung", c["tracker"]),
                    "said": f"connected to {ap}{radio} but not answering "
                            f"since {when(c['since'])}",
                    "value": "connected but unavailable", "fix": "hung"})
    for mac, clients in by_ap.items():
        if len(clients) > 1:
            ap, _e = ap_name(house, mac)
            aps.append(f"{len(clients)} of them hang on {ap} at once, which "
                       "is the access point's radio rather than the devices.")
    hist, cands, probe_drops, tracker_drops = _wifi_week(snap)
    unifi = _unifi_moments(tracker_drops)
    probe_mass = _mass_moments(probe_drops, max(MASS_MIN,
                                                (len(probe_drops) + 1) // 2))
    days = int((snap.get("wifi_history") or {}).get("days") or FLAP_DAYS)
    hung = {d for c in _hung_clients(house, now) for d in c["devices"]}
    for c in cands:
        if set(c["devices"]) & hung:
            continue
        states = {st for _t, st in _rows(hist, c["tracker"])}
        if "not_home" in states or "home" not in states:
            continue
        spells = [t for t in probe_drops[c["probe"]]
                  if now - t <= days * DAY
                  and not _near(t, probe_mass) and not _near(t, unifi)
                  and after_restart(snap, t) is None]
        if len(spells) < FLAP_MIN_SPELLS or now - spells[-1] > RECENT_S:
            continue
        out.append({"entity": c["probe"], "devices": c["devices"],
                    "name": c["name"], "network": "Wi-Fi",
                    "old": ("net.wifi_flapping", c["probe"]),
                    "said": f"dropped {len(spells)} times in {days} days, "
                            f"last {when(spells[-1])}",
                    "value": f"{len(spells)} drops", "fix": "flapping"})
    counted = [t for t in unifi if now - t <= days * DAY
               and not _near(t, probe_mass) and after_restart(snap, t) is None]
    said = ""
    if len(counted) >= UNIFI_DROPS_MIN and now - counted[-1] <= RECENT_S:
        said = (f"Every UniFi tracker also went unavailable together "
                f"{len(counted)} times in {days} days, last "
                f"{when(counted[-1])}: that is the UniFi integration losing "
                "its controller, and those minutes are not counted against "
                "any device.")
    return out, aps, said


def _zwave_entries(house: House, now: float) -> tuple[list, int]:
    out = []
    for n in _silent_nodes(house, now):
        quiet = now - n["seen"]
        wake = (f", {int(quiet // n['interval'])} wake-ups missed"
                if n["interval"] else "")
        out.append({"entity": n["entity"], "devices": [n["device_id"]],
                    "name": n["name"], "network": "Z-Wave",
                    "old": ("net.zwave_silent", n["entity"]),
                    "said": f"not heard from since {when(n['seen'])}{wake}",
                    "value": f"silent {_span(quiet)}", "fix": "zwave",
                    "serious": quiet >= 7 * DAY})
    return out, sum(1 for _ in _zwave_nodes(house))


def _zigbee_entries(house: House, now: float) -> tuple[list, int]:
    out, total = [], 0
    for dev, reg, entity in zigbee_devices(house):
        total += 1
        if zigbee_quiet(dev, now) != "quiet":
            continue
        seen = parse_ts(dev.get("last_seen")) or now
        out.append({"entity": entity,
                    "devices": [str(dev.get("device_reg_id") or "")],
                    "name": zigbee_name(dev, reg, house), "network": "Zigbee",
                    "old": ("net.zigbee_silent", entity),
                    "said": f"quiet since {when(seen)}",
                    "value": f"quiet {_span(now - seen)}",
                    "fix": "zigbee_mains" if _zha_mains(dev) else "zigbee"})
    return out, total


_FIXES = {
    "hung": ("Wi-Fi, still connected: block and unblock it in the UniFi "
             "Network app, or power-cycle it."),
    "flapping": ("Wi-Fi, dropping: check its signal in the UniFi Network "
                 "app and move it or the access point closer, or give it a "
                 "2.4 GHz network of its own with band steering off."),
    "zwave": ("Z-Wave: wake it and check its battery; if it does not answer, "
              "re-interview it from its device page."),
    "zigbee_mains": ("Zigbee, plugged in: check it still has power (a socket "
                     "or a wall switch turned off is the usual cause)."),
    "zigbee": ("Zigbee, on a battery: press its button and check its "
               "battery; re-pair it near the coordinator if it does not "
               "come back."),
}


def _house_has(house: House, platforms) -> bool:
    return any(str(r.get("platform") or "") in platforms for r in house.entities)


def connectivity(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    available = snap.get("available") or {}
    for network_name, (key, platforms) in SOURCES.items():
        if not available.get(key) and _house_has(house, platforms):
            raise CouldNotLook(f"the {network_name} record ({key}) could not "
                               "be read, and a device missing from it is not "
                               "a device that came back")
    wifi, ap_lines, unifi_line = _wifi_entries(house, snap, now)
    zwave, zwave_total = _zwave_entries(house, now)
    zigbee, zigbee_total = _zigbee_entries(house, now)
    entries = list(wifi)
    for name, found, total in (("Z-Wave", zwave, zwave_total),
                               ("Zigbee", zigbee, zigbee_total)):
        if len(found) >= MASS_MIN and len(found) >= MASS_SHARE * total:
            house.gave_up(CONNECTIVITY, [{"entity_id": e["entity"],
                                          "text": e["name"]} for e in found],
                          f"{len(found)} of {total} {name} devices went quiet "
                          "at once: that is a restart or the network itself, "
                          "not the devices", kind="cap")
            continue
        entries += found
    listed = []
    for e in entries:
        if not e["entity"] or _carried(house, e["devices"], e["entity"]):
            continue
        old_check, old_subject = e["old"]
        if not house.should_report(e["entity"], CONNECTIVITY):
            continue
        if old_subject and not house.should_report(old_subject, old_check):
            continue
        if any(x["entity"] == e["entity"] for x in listed):
            continue
        listed.append(e)
    if not listed and not unifi_line:
        return []
    order = {"Wi-Fi": 0, "Z-Wave": 1, "Zigbee": 2}
    listed.sort(key=lambda e: (order[e["network"]], e["name"]))
    phrases = [f"{e['name']} ({e['network']}), {e['said']}" for e in listed]
    shown = phrases[:DETAIL_NAMES]
    rest = len(phrases) - len(shown)
    detail = ""
    if listed:
        detail = (("One device is" if len(listed) == 1 else
                   f"{len(listed)} devices are")
                  + " off the network for hours or keep dropping off: "
                  + "; ".join(shown)
                  + (f"; and {rest} more" if rest else "") + ". "
                  + " ".join(ap_lines)
                  + " Devices that came back are taken off this list, and a "
                    "restart, or many devices at once, is not counted.")
    if unifi_line:
        detail = f"{detail} {unifi_line}".strip()
    kinds = []
    for e in listed:
        if e["fix"] not in kinds:
            kinds.append(e["fix"])
    fix = " ".join(_FIXES[k] for k in kinds)
    if unifi_line:
        fix = (fix + " UniFi: check the UniFi Network application stays up "
               "and reachable from Home Assistant.").strip()
    return [{
        "text": CONNECTIVITY_TEXT,
        "detail": " ".join(detail.split()),
        "fix": fix,
        "severity": ("serious" if any(e.get("serious") for e in listed)
                     else "warning"),
        "fixable": False,
        # Filed on no one entity: the row is about every device it lists
        # (`items`), and an entity_id would stay the first device's after
        # that one came back, since the store refreshes the rest in place.
        "entity_id": "",
        **({"items": [e["entity"] for e in listed]} if listed else
           {"integration": "unifi"}),
        "evidence": [{"entity": e["entity"], "value": e["value"], "when": ""}
                     for e in listed[:8]],
    }]


# ---------------------------------------------------------------------------
# net.matter_empty — Matter set up with nothing on it
# net.bluetooth_faint — a Bluetooth device heard only faintly
# ---------------------------------------------------------------------------

MATTER_GRACE_DAYS = 7
MATTER_EMPTY_TEXT = "Matter is set up with nothing on it"
# Below this a BLE advertisement is barely heard: one wall more, or a
# fridge door, and the device drops out between readings.
BLUETOOTH_FAINT_DBM = -90


def _loaded(snap: dict, domain: str) -> list[dict]:
    return [e for e in snap.get("config_entries") or ()
            if isinstance(e, dict) and e.get("domain") == domain
            and e.get("state") == "loaded"]


def matter_absent(snap: dict) -> str | None:
    return None if _loaded(snap, "matter") else "Matter is not set up"


def matter_empty(snap: dict, now: float) -> list[dict]:
    rows = []
    for entry in _loaded(snap, "matter"):
        eid = str(entry.get("entry_id") or "")
        on_it = [d for d in snap.get("devices") or ()
                 if isinstance(d, dict) and eid in (d.get("config_entries") or ())]
        if on_it:
            continue
        # A fabric set up this week is somebody about to pair the first
        # device. An entry that does not say when it was made is judged
        # anyway: it is an info row about a controller with nothing on it.
        made = parse_ts(entry.get("created_at"))
        if made is not None and now - made < MATTER_GRACE_DAYS * 86400:
            continue
        rows.append({
            "text": MATTER_EMPTY_TEXT,
            "detail": ("The Matter integration is running with no device "
                       "paired to it, so it and the Matter server it talks "
                       "to do nothing in this house."),
            "fix": ("Pair a Matter device under Settings > Devices & "
                    "services > Matter, or delete the integration (and the "
                    "Matter Server add-on) if nothing here uses Matter."),
            "severity": "info",
            "fixable": False,
            "entity_id": "",
        })
        break
    return rows


def bluetooth_absent(snap: dict) -> str | None:
    return None if _loaded(snap, "bluetooth") else "Bluetooth is not set up"


def bluetooth_faint(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    heard = {str(a).lower(): r for a, r in
             ((snap.get("bluetooth") or {}).get("rssi") or {}).items()}
    rows = []
    for dev_id, dev in sorted(house.devices.items()):
        macs = [str(c[1]).lower() for c in dev.get("connections") or ()
                if isinstance(c, (list, tuple)) and len(c) == 2
                and c[0] == "bluetooth"]
        rssi = [heard[m] for m in macs if isinstance(heard.get(m), (int, float))]
        if not rssi or max(rssi) > BLUETOOTH_FAINT_DBM:
            continue
        entity = next((str(r.get("entity_id")) for r in house.entities
                       if r.get("device_id") == dev_id and r.get("entity_id")),
                      "")
        if not entity or not house.should_report(entity, "net.bluetooth_faint"):
            continue
        rows.append({
            "text": f"{house.device_name(dev)} is barely heard over Bluetooth",
            "detail": (f"The strongest receiver hears it at {max(rssi):g} dBm "
                       f"(at or under {BLUETOOTH_FAINT_DBM} is faint), so its "
                       "readings arrive late or not at all."
                       + house.placed(entity, house.device_name(dev))),
            "fix": ("Move the Bluetooth adapter or an ESPHome Bluetooth proxy "
                    "closer to it, or add a proxy in that room; a USB adapter "
                    "on an extension cable away from USB 3 ports helps too."),
            "severity": "info",
            "fixable": False,
            "entity_id": entity,
            "_rssi": max(rssi),
        })
    rows.sort(key=lambda r: r["_rssi"])
    for r in rows:
        r.pop("_rssi", None)
    if len(rows) > MAX_ROWS:
        house.gave_up("net.bluetooth_faint", rows[MAX_ROWS:],
                      "more faint Bluetooth devices than one card each can say")
        rows = rows[:MAX_ROWS]
    return rows

WIFI = "Network (Wi-Fi)"
ZWAVE = "Network (Z-Wave)"
ZIGBEE = "Network (Zigbee)"
MATTER = "Network (Matter)"
BLUETOOTH = "Network (Bluetooth)"

CHECKS = [
    # Every device dropping off, on any network, is one card
    # (`connectivity`); it replaced the per-device checks in `REPLACED`.
    {"id": "net.connectivity", "area": "networks",
     "title": "Devices dropping off the network", "source_title": "Network",
     "needs": ("states", "registry"), "replaces": REPLACED,
     "run": connectivity},
    {"id": "net.zwave_link", "area": "networks", "title": "Z-Wave nodes with a weak link",
     "source_title": ZWAVE, "needs": ("states", "registry", "zwave_nodes"),
     "run": zwave_link},
    {"id": "net.zigbee_weak", "area": "networks", "title": "Zigbee routers with a weak link",
     "source_title": ZIGBEE, "needs": ("registry", "zha_devices"),
     "run": zigbee_weak},
    {"id": "net.matter_empty", "area": "networks",
     "title": "Matter set up with nothing on it",
     "source_title": MATTER, "needs": ("registry", "config_entries"),
     "absent": matter_absent, "run": matter_empty},
    {"id": "net.bluetooth_faint", "area": "networks",
     "title": "Bluetooth devices heard only faintly",
     "source_title": BLUETOOTH,
     "needs": ("registry", "config_entries", "bluetooth"),
     "absent": bluetooth_absent, "run": bluetooth_faint},
]
