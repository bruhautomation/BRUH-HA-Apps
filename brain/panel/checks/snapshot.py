"""One snapshot of the house, fetched once, read by every check.

The shape every check reads (a key is absent, and marked unavailable, when
its fetch failed — a check whose ``needs`` include it then does not run,
and so cannot clear anything):

    now            epoch seconds
    states         {entity_id: {state, attributes, last_changed,
                    last_updated, last_reported}}
    entities       entity registry rows (entity_id, device_id, area_id,
                    platform, unique_id, disabled_by, hidden_by, name,
                    original_name, created_at)
    devices        device registry rows (id, name, name_by_user, area_id)
    areas          area registry rows (area_id, name)
    services       {"domain.service", ...}
    automations    the list in automations.yaml
    scripts        the mapping in scripts.yaml
    scenes         the list in scenes.yaml
    traces         {entity_id: [trace, ...]} from .storage/trace.saved_traces
    stats          {entity_id: [{start, mean, min, max}]} — 7 daily rows
                    for every numeric measurement sensor
    battery_stats  {entity_id: [{start, mean}]} — 60 daily rows for every
                    battery sensor
    dashboards     [{url_path, title, config}]
    supervisor     {backups, addons, host, core} — the Supervisor's own
                    view: what has been backed up, which add-ons are
                    running, how full the disk is. Each add-on row carries
                    the `boot` and `state` from its own /info, because the
                    list endpoint does not say whether it was meant to run
    zha_devices    [{name, ieee, available, last_seen}] — absent unless ZHA
                    is installed, which is what makes the key unavailable
    config_entries [{entry_id, domain, title, state, source, disabled_by,
                    reason}] — every integration entry and whether it set
                    itself up. Unavailable when Core would not answer, which
                    is a different claim from a house with nothing failing
    recorder       {db_bytes, db_path, purge_keep_days}
    closures       how much of each hour of the week each door, window,
                    lock and cover is normally open, as `panel/closures.py`
                    last measured it. Unavailable until the first nightly
                    pass, the same real state a fresh install has
    baselines      what is normal here, per entity per hour of the week,
                    as `panel/baselines.py` last measured it. Unavailable
                    until the first nightly pass has run, which is a real
                    state on a fresh install and not an unusual house
    thermal        how fast each room loses heat and how fast it gains it,
                    as `panel/thermal.py` last measured it, plus `recent`:
                    the last few hours of five-minute readings for those
                    rooms and their outdoor reference. Unavailable with no
                    outdoor temperature sensor, which is not a fault: every
                    number in it is a difference from outside
    actions        {actions, overrides, counts} — the last LOGBOOK_HOURS of
                    the logbook, with every state change filed under what
                    caused it. Unavailable when the logbook integration is
                    not installed, which is not the same as a quiet house
    blueprints_dir /config/blueprints
    available      {key: bool} — which of the above were actually fetched
    errors         {key: "why not"}

Everything network-shaped is best effort and independently so: a recorder
that is busy costs the statistics checks one run, not the whole batch.
aiohttp and yaml are imported inside the functions that need them, so the
package stays importable without the add-on runtime.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
import time
from typing import Any

log = logging.getLogger("brain.checks")

CONFIG_DIR = os.environ.get("BRAIN_HA_CONFIG_DIR", "/config")
TRACES_FILE = os.environ.get("BRAIN_TRACES_FILE",
                             os.path.join(CONFIG_DIR, ".storage", "trace.saved_traces"))
SUPERVISOR_API = os.environ.get("BRAIN_SUPERVISOR_API", "http://supervisor")
RECORDER_DB = os.environ.get(
    "BRAIN_RECORDER_DB", os.path.join(CONFIG_DIR, "home-assistant_v2.db"))
STATS_DAYS = 7
# How much of an appliance's recent draw a checks pass fetches. Long
# enough that a wash finished before breakfast is still visible at
# lunchtime, short enough to be a handful of rows per sensor.
APPLIANCE_HOURS = 14
THERMAL_HOURS = 4
BATTERY_DAYS = 60
# Statistics are one WebSocket call per batch; keep a batch to what the
# recorder answers comfortably on a Pi.
STATS_BATCH = 150
# How far back the action miner looks. A day plus a margin: the window
# has to cover the gap between two checks passes on the default interval
# without ever becoming "fetch a month of logbook every time".
LOGBOOK_HOURS = 26
# One /info request per installed add-on. They are local and cheap, and
# the cap is only there so a pathological install cannot make a checks
# pass unbounded.
MAX_ADDON_INFO = 40


# ---------------------------------------------------------------------------
# Config files — with Home Assistant's own tags tolerated
# ---------------------------------------------------------------------------

def load_yaml_file(path: str) -> Any:
    """Parse one of HA's YAML files, or None if it is absent or broken.

    ``!secret``, ``!include`` and friends are HA's tags, not YAML's; a
    loader that refuses them would refuse most real config files. They are
    read as None here — a check reading a value that was a secret sees
    nothing, which is the honest answer, not a crash.
    """
    try:
        import yaml
    except ImportError:
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        return None

    class _Loader(yaml.SafeLoader):
        pass

    def _tag(loader, suffix, node):
        return None

    _Loader.add_multi_constructor("!", _tag)
    try:
        return yaml.load(text, Loader=_Loader)  # noqa: S506 — SafeLoader subclass
    except yaml.YAMLError as exc:
        log.warning("could not parse %s: %s", path, str(exc)[:200])
        return None


def load_configs(config_dir: str = CONFIG_DIR) -> dict:
    """automations / scripts / scenes from their conventional files."""
    out: dict[str, Any] = {}
    auto = load_yaml_file(os.path.join(config_dir, "automations.yaml"))
    out["automations"] = auto if isinstance(auto, list) else None
    scripts = load_yaml_file(os.path.join(config_dir, "scripts.yaml"))
    out["scripts"] = scripts if isinstance(scripts, dict) else None
    scenes = load_yaml_file(os.path.join(config_dir, "scenes.yaml"))
    out["scenes"] = scenes if isinstance(scenes, list) else None
    return out


def load_traces(path: str = TRACES_FILE) -> dict | None:
    """The stored traces, keyed by entity id."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            store = json.load(fh)
    except (OSError, ValueError):
        return None
    data = store.get("data") if isinstance(store, dict) else None
    if not isinstance(data, dict):
        return None
    out: dict[str, list] = {}
    for key, rows in data.items():
        if isinstance(rows, dict) and not any(
                isinstance(v, dict) and "run_id" in v for v in rows.values()):
            # {"automation": {...}} nesting seen on some versions
            for inner_key, inner_rows in rows.items():
                eid = inner_key if "." in inner_key else f"{key}.{inner_key}"
                out[eid] = _trace_rows(inner_rows)
            continue
        out[key] = _trace_rows(rows)
    return out


def load_recorder(config_dir: str = CONFIG_DIR) -> dict | None:
    """How big the recorder database is, and how long it is told to keep.

    ``purge_keep_days`` is None when ``configuration.yaml`` does not set
    it *here* — an ``!include``d recorder block reads as None, which is
    the honest answer: the check falls back to Home Assistant's own
    default rather than claiming the file said something it did not.
    A database that cannot be stat-ed (a custom ``db_url``, Postgres,
    MariaDB) is not a smaller database — it is a question this check
    cannot answer, so the whole key goes unavailable.
    """
    db_path = RECORDER_DB
    try:
        db_bytes = os.stat(db_path).st_size
    except OSError:
        return None
    keep = None
    cfg = load_yaml_file(os.path.join(config_dir, "configuration.yaml"))
    if isinstance(cfg, dict) and isinstance(cfg.get("recorder"), dict):
        value = cfg["recorder"].get("purge_keep_days")
        if isinstance(value, int):
            keep = value
    return {"db_bytes": db_bytes, "db_path": db_path,
            "purge_keep_days": keep}


def _trace_rows(rows: Any) -> list:
    if isinstance(rows, dict):
        rows = list(rows.values())
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


# ---------------------------------------------------------------------------
# The live house
# ---------------------------------------------------------------------------

async def collect_rooms(now: float | None = None) -> dict:
    """The four keys a `House` needs to answer "what is in this room".

    `collect` fetches statistics, traces, a week of daily means and the
    Supervisor, which is minutes of work and exactly right for a checks
    pass — and completely wrong for somebody who has just typed *"design
    my evening for the living room"* and is watching a spinner. This is
    the states, the three registries and `scenes.yaml`, and nothing else.

    It is here rather than in the caller so there is one answer to what a
    snapshot's `states`/`entities`/`devices`/`areas` look like: a second
    assembly of the same four keys would be a `House` built two ways.
    """
    import aiohttp

    import ha_data

    now = time.time() if now is None else now
    snap: dict[str, Any] = {"now": now, "available": {}, "errors": {}}
    cfg = load_configs()
    snap["scenes"] = cfg["scenes"]
    snap["automations"] = cfg["automations"]
    async with aiohttp.ClientSession() as session:
        raw = await ha_data._rest_get(session, "/states", timeout=60)
        snap["states"] = {
            s["entity_id"]: {
                "state": s.get("state"),
                "attributes": s.get("attributes") or {},
            } for s in (raw or []) if isinstance(s, dict) and s.get("entity_id")}
        areas, devices, entities = await ha_data._ws_commands(session, [
            {"type": "config/area_registry/list"},
            {"type": "config/device_registry/list"},
            {"type": "config/entity_registry/list"},
        ])
        if entities is None:
            raise RuntimeError("the entity registry did not answer")
        snap["areas"] = areas or []
        snap["devices"] = devices or []
        snap["entities"] = entities or []
    snap["services"] = set()
    return snap


async def collect(now: float | None = None) -> dict:
    """Fetch everything the checks read. Never raises."""
    import aiohttp

    import actions
    import appliances
    import baselines
    import closures
    import ha_data
    import thermal

    now = time.time() if now is None else now
    snap: dict[str, Any] = {"now": now, "available": {}, "errors": {},
                            "blueprints_dir": os.path.join(CONFIG_DIR, "blueprints")}

    def _mark(key: str, ok: bool, err: str = "") -> None:
        snap["available"][key] = ok
        if err:
            snap["errors"][key] = err[:200]

    # Files first: they cost nothing and cannot time out.
    cfg = load_configs()
    for key in ("automations", "scripts", "scenes"):
        snap[key] = cfg[key]
    _mark("automations", cfg["automations"] is not None,
          "" if cfg["automations"] is not None else "automations.yaml not readable")
    traces = load_traces()
    snap["traces"] = traces or {}
    _mark("traces", traces is not None,
          "" if traces is not None else "no stored traces")

    async with aiohttp.ClientSession() as session:
        try:
            raw = await ha_data._rest_get(session, "/states", timeout=60)
            snap["states"] = {
                s["entity_id"]: {
                    "state": s.get("state"),
                    "attributes": s.get("attributes") or {},
                    "last_changed": s.get("last_changed"),
                    "last_updated": s.get("last_updated"),
                    "last_reported": s.get("last_reported"),
                } for s in (raw or []) if isinstance(s, dict) and s.get("entity_id")}
            _mark("states", True)
        except Exception as exc:  # noqa: BLE001 — every fetch is best effort
            snap["states"] = {}
            _mark("states", False, str(exc))

        try:
            areas, devices, entities = await ha_data._ws_commands(session, [
                {"type": "config/area_registry/list"},
                {"type": "config/device_registry/list"},
                {"type": "config/entity_registry/list"},
            ])
            if entities is None:
                raise RuntimeError("entity registry did not answer")
            snap["areas"] = areas or []
            snap["devices"] = devices or []
            snap["entities"] = entities or []
            _mark("registry", True)
        except Exception as exc:  # noqa: BLE001
            snap["areas"], snap["devices"], snap["entities"] = [], [], []
            _mark("registry", False, str(exc))

        try:
            raw = await ha_data._rest_get(session, "/services", timeout=30)
            services: set[str] = set()
            for svc in raw or []:
                domain = str(svc.get("domain") or "").lower()
                for name in (svc.get("services") or {}):
                    services.add(f"{domain}.{str(name).lower()}")
            snap["services"] = services
            _mark("services", bool(services),
                  "" if services else "no services listed")
        except Exception as exc:  # noqa: BLE001
            snap["services"] = set()
            _mark("services", False, str(exc))

        # Statistics: daily min/max/mean for numeric sensors, and a longer
        # mean-only window for batteries.
        try:
            stats, battery = await _statistics(session, snap.get("states") or {}, now)
            snap["stats"] = stats
            snap["battery_stats"] = battery
            _mark("stats", True)
            _mark("battery_stats", True)
        except Exception as exc:  # noqa: BLE001
            snap["stats"], snap["battery_stats"] = {}, {}
            _mark("stats", False, str(exc))
            _mark("battery_stats", False, str(exc))

        try:
            snap["dashboards"] = await _dashboards(session)
            _mark("dashboards", True)
        except Exception as exc:  # noqa: BLE001
            snap["dashboards"] = []
            _mark("dashboards", False, str(exc))

        try:
            zha = (await ha_data._ws_commands(session, [{"type": "zha/devices"}]))[0]
            snap["zha_devices"] = zha if isinstance(zha, list) else []
            # ZHA not installed answers with an error, which _ws_commands
            # hands back as None — no ZHA is not an unhealthy ZHA.
            _mark("zha_devices", isinstance(zha, list),
                  "" if isinstance(zha, list) else "ZHA is not installed")
        except Exception as exc:  # noqa: BLE001
            snap["zha_devices"] = []
            _mark("zha_devices", False, str(exc))

        # Every integration entry and whether it loaded. A Core that
        # would not answer leaves the key UNAVAILABLE rather than empty:
        # "no entry is failing" and "I could not ask" are different
        # claims, and only the first may clear a row.
        try:
            entries = (await ha_data._ws_commands(
                session, [{"type": "config_entries/get"}]))[0]
            snap["config_entries"] = entries if isinstance(entries, list) else []
            _mark("config_entries", isinstance(entries, list),
                  "" if isinstance(entries, list)
                  else "Home Assistant did not list its config entries")
        except Exception as exc:  # noqa: BLE001
            snap["config_entries"] = []
            _mark("config_entries", False, str(exc))

        sup = await _supervisor(session)
        snap["supervisor"] = sup
        # The Supervisor is four independent questions and one key. It is
        # available when it answered the two that carry every check —
        # backups and add-ons; `host` alone failing costs sys.disk_space
        # its floor, which it tests for itself.
        _mark("supervisor", sup.get("backups") is not None
              and sup.get("addons") is not None,
              sup.get("error") or "")

        # The appliance shapes are read from the nightly store, but what
        # each one is doing *now* is a live question, so this is the one
        # measurement the checks pass fetches for itself — and it is
        # cheap by construction: a handful of profiled sensors over a few
        # hours, never the whole house over a month.
        try:
            shapes = appliances.load()
            live = {}
            ids = sorted(shapes.get("entities") or {})
            if ids:
                start = dt.datetime.fromtimestamp(
                    now - APPLIANCE_HOURS * 3600, tz=dt.timezone.utc)
                live = await appliances.fetch(session, ids, start)
            snap["appliances"] = {"entities": shapes.get("entities") or {},
                                  "built_at": shapes.get("built_at", 0),
                                  "recent": live}
            _mark("appliances", bool(ids),
                  "" if ids else
                  "brAIn has not measured any appliances here yet — the "
                  "first pass runs overnight, and it needs a power sensor "
                  "on one")
        except Exception as exc:  # noqa: BLE001
            snap["appliances"] = {"entities": {}, "built_at": 0, "recent": {}}
            _mark("appliances", False, str(exc))

        # The nightly store says how each room behaves; whether one is
        # cooling faster than it can is a live question, so this is the
        # second measurement the checks pass fetches for itself. Cheap
        # by the same construction as the appliance one: the rooms that
        # already have a model, over a few hours.
        try:
            model = thermal.load()
            rooms = sorted(model.get("rooms") or {})
            recent = {}
            if rooms and model.get("outdoor"):
                start = dt.datetime.fromtimestamp(
                    now - THERMAL_HOURS * 3600, tz=dt.timezone.utc)
                recent = await thermal.fetch_recent(
                    session, rooms + [model["outdoor"]], start)
            model["recent"] = recent
            snap["thermal"] = model
            _mark("thermal", bool(rooms),
                  "" if rooms else
                  (model.get("reason")
                   or "brAIn has not measured how this house holds its "
                      "heat yet — the first pass runs overnight"))
        except Exception as exc:  # noqa: BLE001
            snap["thermal"] = {"rooms": {}, "recent": {}, "built_at": 0}
            _mark("thermal", False, str(exc))

        try:
            mined = await actions.collect(
                session, now - LOGBOOK_HOURS * 3600, now,
                await _users(session))
            snap["actions"] = mined
            _mark("actions", mined["available"], mined.get("error") or "")
        except Exception as exc:  # noqa: BLE001
            snap["actions"] = {"available": False, "actions": [],
                               "overrides": [], "counts": {}}
            _mark("actions", False, str(exc))

    # Read, never built: the nightly pass in the panel measures the house
    # and this only picks up what it left. A checks pass that rebuilt them
    # would spend minutes of statistics queries every six hours to answer
    # a question whose answer changes over weeks.
    # Read, never built — same rule as the baselines below: the nightly
    # pass measures and a checks pass only picks up what it left.
    snap["closures"] = closures.load()
    _mark("closures", bool(snap["closures"].get("entities")),
          "" if snap["closures"].get("entities") else
          "brAIn has not measured what is normally open here yet — the "
          "first pass runs overnight")

    snap["baselines"] = baselines.load()
    _mark("baselines", bool(snap["baselines"].get("entities")),
          "" if snap["baselines"].get("entities") else
          "brAIn has not measured what is normal here yet — the first "
          "pass runs overnight")


    recorder = load_recorder()
    snap["recorder"] = recorder or {}
    _mark("recorder", recorder is not None,
          "" if recorder is not None else
          "the recorder database is not a file under /config "
          "(a remote database answers this question itself)")

    return snap


async def _users(session) -> dict[str, str]:
    """{user_id: name}, so an action can say who rather than a uuid.

    Best effort on purpose: `config/auth/list` is an admin command and a
    token that cannot run it should cost the timeline the *names*, not the
    attribution. An unnamed person is still a person.
    """
    import ha_data
    try:
        rows = (await ha_data._ws_commands(session, [{"type": "config/auth/list"}]))[0]
    except Exception:  # noqa: BLE001
        return {}
    if not isinstance(rows, list):
        return {}
    return {str(r.get("id")): str(r.get("name") or "")
            for r in rows if isinstance(r, dict) and r.get("id")}


# ---------------------------------------------------------------------------
# The Supervisor's own view
# ---------------------------------------------------------------------------

async def _supervisor_get(session, path: str, timeout: int = 20) -> Any:
    """One Supervisor endpoint, unwrapped from its {result, data} envelope."""
    import aiohttp

    import ha_data

    async with session.get(
        f"{SUPERVISOR_API}{path}",
        headers={"Authorization": f"Bearer {ha_data.SUPERVISOR_TOKEN}"},
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as resp:
        resp.raise_for_status()
        body = await resp.json()
    return body.get("data") if isinstance(body, dict) else None


async def _supervisor(session) -> dict:
    """Backups, add-ons, the host and Core — each one best effort.

    Four endpoints, gathered rather than awaited in turn: they are
    independent, and a Supervisor that is busy restoring a backup should
    cost the pass one wait, not four.
    """
    paths = (("backups", "/backups"), ("addons", "/addons"),
             ("host", "/host/info"), ("core", "/core/info"))
    results = await asyncio.gather(
        *(_supervisor_get(session, path) for _, path in paths),
        return_exceptions=True)
    out: dict[str, Any] = {}
    errors: list[str] = []
    for (key, path), result in zip(paths, results):
        if isinstance(result, BaseException):
            out[key] = None
            errors.append(f"{path}: {str(result)[:80]}")
            continue
        if not isinstance(result, dict):
            # It answered, but not with the envelope this knows. That is
            # not "you have no backups" — it is another way of not having
            # been able to look, so the key stays None and the checks that
            # need it do not run.
            out[key] = None
            errors.append(f"{path}: unexpected response")
            continue
        if key == "backups":
            out[key] = result.get("backups") or []
        elif key == "addons":
            out[key] = result.get("addons") or []
        else:
            out[key] = result
    if out.get("addons"):
        out["addons"] = await _addon_details(session, out["addons"])
    if errors:
        out["error"] = "; ".join(errors)
    return out


async def _addon_details(session, addons: list) -> list:
    """Fold each add-on's own /info into its row.

    `boot` is the field that separates "somebody stopped this on purpose"
    from "this was meant to be running", and the list endpoint does not
    carry it. An add-on whose /info did not answer keeps its list row and
    no `boot`, which reads as "I could not look" rather than as a fault.
    """
    slugs = [str(a.get("slug")) for a in addons
             if isinstance(a, dict) and a.get("slug")][:MAX_ADDON_INFO]
    results = await asyncio.gather(
        *(_supervisor_get(session, f"/addons/{slug}/info", timeout=10)
          for slug in slugs),
        return_exceptions=True)
    info = {slug: r for slug, r in zip(slugs, results)
            if isinstance(r, dict)}
    out = []
    for row in addons:
        if not isinstance(row, dict):
            continue
        extra = info.get(str(row.get("slug") or ""))
        if extra:
            row = {**row, **{k: extra[k] for k in
                             ("boot", "state", "watchdog", "startup")
                             if k in extra}}
        out.append(row)
    return out


def _stat_candidates(states: dict) -> tuple[list[str], list[str]]:
    numeric: list[str] = []
    batteries: list[str] = []
    for eid, st in states.items():
        if not eid.startswith("sensor."):
            continue
        attrs = st.get("attributes") or {}
        if attrs.get("state_class") != "measurement":
            continue
        if attrs.get("device_class") == "battery":
            batteries.append(eid)
        else:
            numeric.append(eid)
    return numeric, batteries


async def _statistics(session, states: dict, now: float) -> tuple[dict, dict]:
    import ha_data

    numeric, batteries = _stat_candidates(states)
    stats: dict[str, list] = {}
    battery: dict[str, list] = {}

    async def fetch(ids: list[str], days: int, types: list[str]) -> dict:
        start = dt.datetime.fromtimestamp(now - days * 86400, tz=dt.timezone.utc)
        out: dict[str, list] = {}
        for i in range(0, len(ids), STATS_BATCH):
            batch = ids[i:i + STATS_BATCH]
            results = await ha_data._ws_commands(session, [{
                "type": "recorder/statistics_during_period",
                "start_time": start.isoformat(),
                "statistic_ids": batch,
                "period": "day",
                "types": types,
            }])
            for sid, rows in (results[0] or {}).items():
                clean = []
                for row in rows or []:
                    start_ts = row.get("start")
                    if isinstance(start_ts, (int, float)):
                        start_ts = start_ts / 1000.0
                    clean.append({"start": start_ts, "mean": row.get("mean"),
                                  "min": row.get("min"), "max": row.get("max")})
                out[sid] = clean
        return out

    if numeric:
        stats = await fetch(numeric, STATS_DAYS, ["mean", "min", "max"])
    if batteries:
        battery = await fetch(batteries, BATTERY_DAYS, ["mean"])
    return stats, battery


async def _dashboards(session) -> list[dict]:
    import ha_data

    listed = (await ha_data._ws_commands(session, [
        {"type": "lovelace/dashboards/list"}]))[0] or []
    targets: list[dict] = [{"url_path": None, "title": "Overview"}]
    for d in listed:
        if isinstance(d, dict) and d.get("mode") == "storage" and d.get("url_path"):
            targets.append({"url_path": d["url_path"],
                            "title": d.get("title") or d["url_path"]})
    commands = []
    for t in targets:
        cmd: dict[str, Any] = {"type": "lovelace/config", "force": False}
        if t["url_path"]:
            cmd["url_path"] = t["url_path"]
        commands.append(cmd)
    configs = await ha_data._ws_commands(session, commands)
    out = []
    for t, cfg in zip(targets, configs):
        # A YAML-mode or auto-generated dashboard answers with an error,
        # which _ws_commands hands back as None — nothing to check there.
        if isinstance(cfg, dict):
            out.append({"url_path": t["url_path"] or "lovelace",
                        "title": t["title"], "config": cfg})
    await asyncio.sleep(0)
    return out
