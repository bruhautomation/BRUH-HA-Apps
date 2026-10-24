"""The parts of Home Assistant the other checks did not look at.

The owner's rule is *leave no part of Home Assistant unexamined*, and the
catalog grew area by area — automations, devices, the networks, the
machine — while some parts of a house were read by nothing at all: the
repairs Home Assistant itself raised and nobody answered, the Energy
dashboard's sensors, the phones that place people, the custom
integrations in ``/config/custom_components``, HACS, and an add-on an
integration needs that somebody stopped. Each is a check here, with the
floors every check carries (a check that fires on a healthy house is
worse than no check), its own snapshot key, and a card title naming its
area.

A check whose subject is not in this house at all — no HACS, no energy
dashboard, nobody set up as a person — says so through its catalog
entry's ``absent`` callable: it RAN and found nothing, and coverage says
"not set up here" rather than "checked, nothing wrong", because those are
different answers to "did you look at X".
"""
from __future__ import annotations

from ._util import House, age_days, evidence_for, join_names, parse_ts, when

DAY = 86400.0

# What the integration that is brAIn, and the other BRUH add-ons' own,
# are: set up by their panels rather than by a person, and never a row
# here about themselves.
OWN_DOMAINS = frozenset({"brain", "morph", "bruh_print", "bruh_minecraft",
                          "bright", "bruh_bambu", "gardenrx",
                          "bruh_task_manager"})

# Readings that are no reading: a tracker reading one of these is
# `dev.unavailable`'s to report, not a stale whereabouts.
_NO_READING = frozenset({"unavailable", "unknown", "", "none"})

REPAIRS_STALE_DAYS = 7
REPAIRS_STALE_TEXT = "Repairs Home Assistant raised have waited a week"
TRACKER_STALE_DAYS = 7
PHONE_SILENT_DAYS = 7
PHONE_MIN_SENSORS = 2
CUSTOM_GRACE_DAYS = 7
CUSTOM_UNUSED_TEXT = "Custom integrations are installed that nothing sets up"
HACS_WAIT_DAYS = 14
HACS_PENDING_TEXT = "HACS updates have waited two weeks"
ENERGY_MISSING_TEXT = "The Energy dashboard reads sensors that do not exist"
ENERGY_RATE_TEXT = "The Energy dashboard reads a rate where it needs a total"
MAX_NAMED = 6


def _seen(st: dict) -> float | None:
    """When an entity last reported anything: Core's `last_reported` (a
    write of the same value), else its last update."""
    stamps = [parse_ts(st.get(k)) for k in
              ("last_reported", "last_updated", "last_changed")]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def _humanise(key: str) -> str:
    return " ".join(str(key or "").replace("_", " ").split())


# ---------------------------------------------------------------------------
# repairs.stale — a repair Home Assistant raised, open for a week
# ---------------------------------------------------------------------------

def stale_repairs(snap: dict, now: float) -> list[dict]:
    """The open repairs older than :data:`REPAIRS_STALE_DAYS` that nobody
    ignored, never brAIn's own, oldest first."""
    out = []
    for issue in snap.get("repairs") or ():
        if not isinstance(issue, dict):
            continue
        domains = {str(issue.get("domain") or ""),
                   str(issue.get("issue_domain") or "")}
        if domains & OWN_DOMAINS:
            continue
        # Ignored or dismissed is somebody having acted on it.
        if issue.get("ignored") or issue.get("dismissed_version"):
            continue
        age = age_days(issue.get("created"), now)
        if age is None or age < REPAIRS_STALE_DAYS:
            continue
        out.append((age, issue))
    out.sort(key=lambda r: -r[0])
    return [i for _, i in out]


def repairs_stale(snap: dict, now: float) -> list[dict]:
    issues = stale_repairs(snap, now)
    if not issues:
        return []
    from ._util import spell_integration  # noqa: PLC0415
    named = []
    for i in issues:
        who = spell_integration(str(i.get("issue_domain") or i.get("domain")
                                    or ""))
        what = _humanise(i.get("translation_key") or i.get("issue_id") or "")
        named.append(f"{who} ({what}, since {when(i.get('created'))})"
                     if what else f"{who} (since {when(i.get('created'))})")
    serious = any(str(i.get("severity") or "") in ("error", "critical")
                  for i in issues)
    return [{
        "text": REPAIRS_STALE_TEXT,
        "detail": ("Settings > System > Repairs has had "
                   + ("this" if len(issues) == 1 else f"these {len(issues)}")
                   + " open for more than a week: "
                   + join_names(named, MAX_NAMED) + "."),
        "fix": ("Open Settings > System > Repairs and work through each one: "
                "most need one press, and a repair left open is often a "
                "warning about something that will stop working in a coming "
                "update. Ignore one there if it does not apply."),
        "severity": "warning" if serious else "info",
        "fixable": False,
        "entity_id": "",
    }]


# ---------------------------------------------------------------------------
# energy.missing_stat / energy.rate_sensor — the Energy dashboard's sensors
# ---------------------------------------------------------------------------

# A field of the energy preferences that names a TOTAL: what the dashboard
# adds up. `stat_rate` (a live power reading) and the cost fields are not.
_TOTAL_FIELDS = frozenset({"stat_energy_from", "stat_energy_to",
                           "stat_consumption"})
_RATE_UNITS = frozenset({"w", "kw", "mw", "gw", "m³/h", "m3/h", "l/min",
                         "l/h", "gal/min", "ft³/min", "ft³/h", "m³/s"})


def energy_stats(prefs: dict) -> list[tuple[str, str]]:
    """Every ``(field, statistic id)`` the energy preferences name, read by
    walking the whole document — the shape of a source has changed across
    Home Assistant releases, and every one of them spells a statistic
    under a key starting ``stat_``."""
    out: list[tuple[str, str]] = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(v, str) and str(k).startswith("stat_") and v:
                    out.append((str(k), v))
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(prefs or {})
    return out


def energy_absent(snap: dict) -> str | None:
    energy = snap.get("energy_prefs") or {}
    if not energy.get("configured") or not energy_stats(energy.get("prefs")):
        return "the Energy dashboard has not been set up"
    return None


def _energy_rows(snap: dict, check_id: str, picked: list[str], text: str,
                 detail: str, fix: str) -> list[dict]:
    house = House(snap)
    picked = [e for e in dict.fromkeys(picked)
              if house.should_report(e, check_id)]
    if not picked:
        return []
    names = [house.label(e) for e in picked]
    return [{
        "text": text,
        "detail": detail.format(names=join_names(names, MAX_NAMED)),
        "fix": fix,
        "severity": "warning",
        "fixable": False,
        "entity_id": picked[0] if len(picked) == 1 else "",
        "evidence": evidence_for(picked, "on the Energy dashboard"),
    }]


def energy_missing(snap: dict, now: float) -> list[dict]:
    states = snap.get("states") or {}
    registry = {e.get("entity_id") for e in snap.get("entities") or ()
                if isinstance(e, dict)}
    gone = []
    for _field, stat in energy_stats((snap.get("energy_prefs") or {})
                                     .get("prefs")):
        # `domain:name` is an external statistic (a utility's own), which
        # names no entity; only an entity-shaped id can be missing here.
        if ":" in stat or "." not in stat:
            continue
        if stat not in states and stat not in registry:
            gone.append(stat)
    return _energy_rows(
        snap, "energy.missing_stat", gone, ENERGY_MISSING_TEXT,
        "It is set to read {names}, which Home Assistant no longer has, so "
        "that part of the dashboard has stopped counting.",
        "Settings > Dashboards > Energy: pick the sensor that replaced it, "
        "or remove the source.")


def energy_rate(snap: dict, now: float) -> list[dict]:
    states = snap.get("states") or {}
    rates = []
    for field, stat in energy_stats((snap.get("energy_prefs") or {})
                                    .get("prefs")):
        if field not in _TOTAL_FIELDS:
            continue
        attrs = (states.get(stat) or {}).get("attributes") or {}
        unit = str(attrs.get("unit_of_measurement") or "").lower()
        if (str(attrs.get("device_class") or "") in ("power",
                                                     "volume_flow_rate")
                or unit in _RATE_UNITS
                or str(attrs.get("state_class") or "") == "measurement"):
            rates.append(stat)
    return _energy_rows(
        snap, "energy.rate_sensor", rates, ENERGY_RATE_TEXT,
        "{names} is a reading of how fast something is being used right "
        "now, and the dashboard adds its sources up as running totals, so "
        "what it shows for it is not what was used.",
        "Settings > Dashboards > Energy: use the sensor that counts the "
        "total (kWh, m³), or make one from this reading with an "
        "Integral helper (Settings > Devices & services > Helpers).")


# ---------------------------------------------------------------------------
# people.tracker_stale / people.phone_silent — what places people
# ---------------------------------------------------------------------------

def people_absent(snap: dict) -> str | None:
    states = snap.get("states") or {}
    if not any(e.startswith("person.") for e in states):
        return "nobody is set up as a person in Home Assistant"
    return None


def silent_phones(snap: dict, now: float) -> dict[str, tuple[float, list]]:
    """``{device_id: (last heard, [entity ids])}`` for every phone running
    the Home Assistant app whose sensors have all stopped reporting for
    :data:`PHONE_SILENT_DAYS`. Shared by both people checks so a silent
    phone is one card, never also its tracker's."""
    states = snap.get("states") or {}
    by_device: dict[str, list[str]] = {}
    for row in snap.get("entities") or ():
        if not isinstance(row, dict) or row.get("platform") != "mobile_app":
            continue
        eid = str(row.get("entity_id") or "")
        dev = str(row.get("device_id") or "")
        if dev and eid in states and eid.split(".")[0] in (
                "sensor", "binary_sensor", "device_tracker"):
            by_device.setdefault(dev, []).append(eid)
    out = {}
    for dev, eids in by_device.items():
        if len(eids) < PHONE_MIN_SENSORS:
            continue
        seen = [_seen(states[e]) for e in eids]
        if any(s is None for s in seen):
            continue
        last = max(seen)
        if now - last >= PHONE_SILENT_DAYS * DAY:
            out[dev] = (last, sorted(eids))
    return out


def phone_silent(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    rows = []
    for dev_id, (last, eids) in sorted(silent_phones(snap, now).items()):
        device = house.devices.get(dev_id) or {"id": dev_id}
        trackers = [e for e in eids if e.startswith("device_tracker.")]
        entity = (trackers or eids)[0]
        if not house.should_report(entity, "people.phone_silent"):
            continue
        rows.append({
            "text": f"{house.device_name(device)} has stopped reporting to "
                    "Home Assistant",
            "detail": (f"None of its {len(eids)} sensors from the Home "
                       f"Assistant app has reported since {when(last)}."),
            "fix": ("Open the Home Assistant app on it: it may be signed out, "
                    "or its background updates switched off. If the phone is "
                    "no longer used, delete it under Settings > Devices & "
                    "services > Mobile App so it stops placing anybody."),
            "severity": "info",
            "fixable": False,
            "entity_id": entity,
            "evidence": evidence_for(eids, "last reported " + when(last)),
        })
    return rows


def tracker_stale(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    states = snap.get("states") or {}
    silent = set(silent_phones(snap, now))
    rows = []
    for pid, pst in sorted(states.items()):
        if not pid.startswith("person."):
            continue
        attrs = pst.get("attributes") or {}
        for tracker in attrs.get("device_trackers") or ():
            tst = states.get(str(tracker))
            if not tst or str(tst.get("state") or "").lower() in _NO_READING:
                continue
            # A router or a Bluetooth tracker reads "home" for as long as
            # somebody is home and writes nothing; only a GPS tracker is
            # expected to keep reporting.
            if (tst.get("attributes") or {}).get("source_type") != "gps":
                continue
            dev = house.device_of(str(tracker))
            if dev and dev.get("id") in silent:
                continue
            seen = _seen(tst)
            if seen is None or now - seen < TRACKER_STALE_DAYS * DAY:
                continue
            if not house.should_report(str(tracker), "people.tracker_stale"):
                continue
            person = house.label(pid)
            rows.append({
                "text": f"{house.label(str(tracker))} has stopped updating "
                        f"where {person} is",
                "detail": (f"It is one of the trackers that place {person}, "
                           f"and it has not reported since {when(seen)}, so "
                           f"anything that runs when {person} comes or goes "
                           "is reading where they were then."),
                "fix": (f"Check the device it follows is still in use and "
                        "allowed to share its location. If it is gone, take "
                        f"it off {person} under Settings > People."),
                "severity": "info",
                "fixable": False,
                "entity_id": str(tracker),
            })
    return rows


# ---------------------------------------------------------------------------
# integ.custom_unused — a custom integration nothing sets up
# ---------------------------------------------------------------------------

def custom_absent(snap: dict) -> str | None:
    found = (snap.get("custom_components") or {}).get("integrations") or []
    if not [c for c in found if c.get("domain") not in OWN_DOMAINS]:
        return "no custom integrations are installed"
    return None


def custom_unused(snap: dict, now: float) -> list[dict]:
    cc = snap.get("custom_components") or {}
    referenced = set(cc.get("referenced") or ())
    entries = {str(e.get("domain") or "") for e in snap.get("config_entries")
               or () if isinstance(e, dict)}
    integrations = [c for c in cc.get("integrations") or ()
                    if isinstance(c, dict)]
    needed = set()
    for c in integrations:
        for key in ("dependencies", "after_dependencies"):
            needed.update(str(d) for d in c.get(key) or ())
    unused = []
    for c in integrations:
        dom = str(c.get("domain") or "")
        if not dom or dom in OWN_DOMAINS or dom in entries:
            continue
        if dom in referenced or dom in needed:
            continue
        mtime = c.get("mtime")
        if mtime is None or now - float(mtime) < CUSTOM_GRACE_DAYS * DAY:
            continue
        unused.append(str(c.get("name") or dom))
    if not unused:
        return []
    unused.sort(key=str.lower)
    return [{
        "text": CUSTOM_UNUSED_TEXT,
        "detail": (join_names(unused, MAX_NAMED)
                   + (" is" if len(unused) == 1 else " are")
                   + " in the custom integrations folder with no integration "
                     "set up for it and no mention in configuration.yaml. "
                     "Home Assistant still reads every custom integration it "
                     "finds there at start."),
        "fix": ("If you meant to use one, add it under Settings > Devices & "
                "services. If not, remove it — through HACS if HACS "
                "installed it — and restart Home Assistant."),
        "severity": "info",
        "fixable": False,
        "entity_id": "",
    }]


# ---------------------------------------------------------------------------
# addon.needed_stopped — an add-on an integration needs, stopped
# ---------------------------------------------------------------------------

def needed_stopped(snap: dict) -> list[tuple[dict, list[dict]]]:
    """``[(add-on, [entries])]``: an add-on that announced a service an
    integration was set up from (`source: hassio`, the Supervisor's own
    discovery), stopped. Only `boot: manual` — `sys.addon_down` reports an
    add-on that is meant to start on boot, and one with no `boot` is one
    whose info nobody could read. Shared with `sys.entry_failed`, which
    stands down for these entries: the integration failing is this."""
    entries = [e for e in snap.get("config_entries") or ()
               if isinstance(e, dict) and e.get("source") == "hassio"
               and not e.get("disabled_by")]
    out = []
    for a in (snap.get("supervisor") or {}).get("addons") or ():
        if not isinstance(a, dict) or not a.get("installed", True):
            continue
        if str(a.get("boot") or "") != "manual":
            continue
        if str(a.get("state") or "") in ("started", "startup", "error", ""):
            continue
        offers = {str(d) for d in a.get("discovery") or ()}
        needs = [e for e in entries if str(e.get("domain") or "") in offers]
        if needs:
            out.append((a, needs))
    return out


def addon_needed(snap: dict, now: float) -> list[dict]:
    rows = []
    for addon, needs in needed_stopped(snap):
        name = str(addon.get("name") or addon.get("slug") or "an add-on")
        who = join_names(sorted({str(e.get("title") or e.get("domain"))
                                 for e in needs}))
        rows.append({
            "text": f"{who} needs the {name} add-on, and it is stopped",
            "detail": (f"{who} was set up from the {name} add-on, which is "
                       "stopped and set to start only by hand, so "
                       + ("it has" if len(needs) == 1 else "they have")
                       + " nothing to talk to."),
            "fix": (f"Start {name} under Settings > Add-ons and turn on "
                    f"Start on boot, or delete {who} under Settings > "
                    "Devices & services if you no longer use it."),
            "severity": "warning",
            "fixable": False,
            "entity_id": "",
        })
    return rows


# ---------------------------------------------------------------------------
# hacs.update_pending — HACS updates waiting for weeks
# ---------------------------------------------------------------------------

def hacs_absent(snap: dict) -> str | None:
    if not any(isinstance(e, dict) and e.get("domain") == "hacs"
               and e.get("state") == "loaded"
               for e in snap.get("config_entries") or ()):
        return "HACS is not installed"
    return None


def hacs_pending(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    waiting = []
    for row in house.entities:
        eid = str(row.get("entity_id") or "")
        if row.get("platform") != "hacs" or not eid.startswith("update."):
            continue
        st = house.states.get(eid) or {}
        if st.get("state") != "on":
            continue
        age = age_days(st.get("last_changed"), now)
        if age is None or age < HACS_WAIT_DAYS:
            continue
        attrs = st.get("attributes") or {}
        name = str(attrs.get("title") or house.label(eid))
        latest = attrs.get("latest_version")
        waiting.append((eid, f"{name} ({latest})" if latest else name))
    waiting = [(e, n) for e, n in waiting
               if house.should_report(e, "hacs.update_pending")]
    if not waiting:
        return []
    waiting.sort(key=lambda r: r[1].lower())
    return [{
        "text": HACS_PENDING_TEXT,
        "detail": ("HACS has had " + join_names([n for _, n in waiting],
                                                MAX_NAMED)
                   + " waiting for more than two weeks."),
        "fix": ("Read each one's release notes in HACS, then update it there "
                "and restart Home Assistant. A custom integration left "
                "behind is often the one that breaks on the next Home "
                "Assistant update."),
        "severity": "info",
        "fixable": False,
        "entity_id": waiting[0][0] if len(waiting) == 1 else "",
        "evidence": evidence_for([e for e, _ in waiting], "update waiting"),
    }]


REPAIRS = "Repairs"
ENERGY = "Energy"
PEOPLE = "People"
CUSTOM = "Custom integrations"
ADDONS = "Add-ons"
HACS = "HACS"

CHECKS = [
    {"id": "repairs.stale", "area": "repairs",
     "title": "Repairs left open for a week", "source_title": REPAIRS,
     "needs": ("repairs",), "run": repairs_stale},
    {"id": "energy.missing_stat", "area": "energy",
     "title": "Energy dashboard sensors that are gone", "source_title": ENERGY,
     "needs": ("energy_prefs", "states", "registry"),
     "absent": energy_absent, "run": energy_missing},
    {"id": "energy.rate_sensor", "area": "energy",
     "title": "Energy dashboard reading a rate", "source_title": ENERGY,
     "needs": ("energy_prefs", "states"),
     "absent": energy_absent, "run": energy_rate},
    {"id": "people.phone_silent", "area": "people",
     "title": "Phones that stopped reporting", "source_title": PEOPLE,
     "needs": ("states", "registry"),
     "absent": people_absent, "run": phone_silent},
    {"id": "people.tracker_stale", "area": "people",
     "title": "Trackers that stopped placing people", "source_title": PEOPLE,
     "needs": ("states", "registry"),
     "absent": people_absent, "run": tracker_stale},
    {"id": "integ.custom_unused", "area": "custom_integrations",
     "title": "Custom integrations nothing sets up", "source_title": CUSTOM,
     "needs": ("custom_components", "config_entries"),
     "absent": custom_absent, "run": custom_unused},
    {"id": "addon.needed_stopped", "area": "addons",
     "title": "Stopped add-ons an integration needs", "source_title": ADDONS,
     "needs": ("supervisor", "config_entries"), "run": addon_needed},
    {"id": "hacs.update_pending", "area": "hacs",
     "title": "HACS updates waiting", "source_title": HACS,
     "needs": ("states", "registry", "config_entries"),
     "absent": hacs_absent, "run": hacs_pending},
]


__all__ = ["OWN_DOMAINS", "CHECKS", "energy_stats", "needed_stopped",
           "silent_phones", "stale_repairs"]
