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
STATS_DAYS = 7
BATTERY_DAYS = 60
# Statistics are one WebSocket call per batch; keep a batch to what the
# recorder answers comfortably on a Pi.
STATS_BATCH = 150


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


def _trace_rows(rows: Any) -> list:
    if isinstance(rows, dict):
        rows = list(rows.values())
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


# ---------------------------------------------------------------------------
# The live house
# ---------------------------------------------------------------------------

async def collect(now: float | None = None) -> dict:
    """Fetch everything the checks read. Never raises."""
    import aiohttp

    import ha_data

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

    return snap


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
