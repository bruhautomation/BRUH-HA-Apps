"""Home Assistant data collection for BRUH Insights.

Talks to HA Core through the Supervisor proxy (REST + WebSocket) using
SUPERVISOR_TOKEN, then slims everything down to a compact JSON bundle that
fits a prompt budget. All trimming is deterministic and size-capped so a
10,000-entity install can't blow up the prompt.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
from typing import Any

import aiohttp

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
CORE_API = os.environ.get("BRUH_CORE_API", "http://supervisor/core/api")
CORE_WS = os.environ.get("BRUH_CORE_WS", "ws://supervisor/core/websocket")
CONTEXT_FILE = os.environ.get("BRUH_CONTEXT_FILE", "/config/CLAUDE.md")
# Learned facts about the home, maintained by the bruh_claude integration
# (memory features). Plain markdown; may not exist.
MEMORY_FILE = os.environ.get("BRUH_MEMORY_FILE", "/config/.bruh_claude/memory/memory.md")

# Hard caps that keep the bundle inside the prompt budget
MAX_ENTITIES = 500
MAX_HISTORY_ENTITIES = 28
MAX_STATE_CHANGES = 50
MAX_STAT_IDS = 24
MAX_BUNDLE_CHARS = 120_000
CONTEXT_CHARS = 4_000

# Per-domain extra attributes worth surfacing (kept tiny on purpose)
EXTRA_ATTRS: dict[str, list[str]] = {
    "climate": ["current_temperature", "temperature", "hvac_action", "preset_mode"],
    "media_player": ["media_title", "media_artist", "app_name", "source", "volume_level"],
    "light": ["brightness"],
    "cover": ["current_position"],
    "automation": ["last_triggered", "mode"],
    "script": ["last_triggered"],
    "update": ["installed_version", "latest_version"],
    "vacuum": ["battery_level", "status"],
    "person": ["source"],
    "sun": ["next_rising", "next_setting"],
    "weather": ["temperature", "humidity", "wind_speed"],
    "lock": ["changed_by"],
    "alarm_control_panel": ["changed_by"],
}


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# Raw fetchers
# ---------------------------------------------------------------------------

async def _rest_get(session: aiohttp.ClientSession, path: str, timeout: int = 30) -> Any:
    async with session.get(
        f"{CORE_API}{path}", headers=_headers(),
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def call_service(service: str, data: dict, timeout: int = 15) -> Any:
    """Call a bruh_claude.<service> HA service through the Supervisor proxy.

    Raises on HTTP errors / network failure — the integration may simply
    not be installed, so callers must treat failures as expected.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CORE_API}/services/bruh_claude/{service}", headers=_headers(),
            json=data, timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def _ws_commands(session: aiohttp.ClientSession, commands: list[dict]) -> list[Any]:
    """Run a list of WS API commands, returning results in order (None on error)."""
    # outer wait_for instead of ws timeout kwargs: the kwarg's type changed
    # across aiohttp versions and the base image's py3-aiohttp varies
    return await asyncio.wait_for(_ws_commands_inner(session, commands), timeout=90)


async def _ws_commands_inner(session: aiohttp.ClientSession, commands: list[dict]) -> list[Any]:
    results: list[Any] = [None] * len(commands)
    async with session.ws_connect(CORE_WS, heartbeat=20) as ws:
        authed = False
        pending: dict[int, int] = {}
        # auth handshake
        async for msg in ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                break
            data = msg.json()
            mtype = data.get("type")
            if mtype == "auth_required":
                await ws.send_json({"type": "auth", "access_token": SUPERVISOR_TOKEN})
            elif mtype == "auth_invalid":
                raise RuntimeError("WebSocket auth rejected by HA Core")
            elif mtype == "auth_ok":
                authed = True
                for i, cmd in enumerate(commands):
                    msg_id = i + 1
                    pending[msg_id] = i
                    await ws.send_json({"id": msg_id, **cmd})
            elif mtype == "result":
                idx = pending.pop(data.get("id"), None)
                if idx is not None and data.get("success"):
                    results[idx] = data.get("result")
                if not pending:
                    break
        if not authed:
            raise RuntimeError("WebSocket auth handshake did not complete")
    return results


# ---------------------------------------------------------------------------
# Registries → entity/area lookup
# ---------------------------------------------------------------------------

async def get_registries(session: aiohttp.ClientSession) -> dict[str, dict]:
    """Return {entity_id: area_name} plus the raw area list."""
    areas, devices, entities = await _ws_commands(session, [
        {"type": "config/area_registry/list"},
        {"type": "config/device_registry/list"},
        {"type": "config/entity_registry/list"},
    ])
    area_names = {a["area_id"]: a["name"] for a in (areas or [])}
    device_area = {d["id"]: d.get("area_id") for d in (devices or [])}
    ent_area: dict[str, str] = {}
    hidden: set[str] = set()
    for e in entities or []:
        eid = e.get("entity_id", "")
        if e.get("disabled_by") or e.get("hidden_by"):
            hidden.add(eid)
            continue
        area_id = e.get("area_id") or device_area.get(e.get("device_id") or "", None)
        name = area_names.get(area_id or "")
        if name:
            ent_area[eid] = name
    return {
        "entity_area": ent_area,
        "hidden": hidden,
        "areas": sorted(area_names.values()),
    }


# ---------------------------------------------------------------------------
# State slimming
# ---------------------------------------------------------------------------

def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def slim_state(state: dict, area: str | None) -> dict:
    attrs = state.get("attributes", {}) or {}
    domain = state.get("entity_id", ".").split(".")[0]
    out: dict[str, Any] = {
        "e": state.get("entity_id"),
        "s": state.get("state"),
    }
    name = attrs.get("friendly_name")
    if name:
        out["n"] = name
    if area:
        out["a"] = area
    unit = attrs.get("unit_of_measurement")
    if unit:
        out["u"] = unit
    dc = attrs.get("device_class")
    if dc:
        out["dc"] = dc
    lc = state.get("last_changed")
    if lc:
        out["lc"] = lc[:19]  # second precision is plenty
    extras = {}
    for key in EXTRA_ATTRS.get(domain, []):
        val = attrs.get(key)
        if val is not None:
            if isinstance(val, float):
                val = round(val, 2)
            extras[key] = val
    if extras:
        out["x"] = extras
    return out


def filter_states(
    states: list[dict],
    registries: dict,
    domains: list[str],
    device_classes: list[str],
    include_unavailable: bool = False,
) -> list[dict]:
    """Category filter: match by domain OR device_class; empty filters = all."""
    ent_area = registries["entity_area"]
    hidden = registries["hidden"]
    out = []
    for st in states:
        eid = st.get("entity_id", "")
        if eid in hidden:
            continue
        domain = eid.split(".")[0]
        state_val = st.get("state")
        if not include_unavailable and state_val in ("unavailable", "unknown"):
            continue
        dc = (st.get("attributes") or {}).get("device_class")
        if domains or device_classes:
            if domain not in domains and (dc or "") not in device_classes:
                continue
        out.append(slim_state(st, ent_area.get(eid)))
    return out[:MAX_ENTITIES]


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------

def _bucket_hourly(points: list[tuple[str, float]]) -> list[list]:
    """Downsample numeric points to hourly means: [[iso_hour, mean], ...]."""
    buckets: dict[str, list[float]] = {}
    for ts, val in points:
        buckets.setdefault(ts[:13], []).append(val)  # YYYY-MM-DDTHH
    return [
        [hour, round(sum(vals) / len(vals), 2)]
        for hour, vals in sorted(buckets.items())
    ]


async def get_history(
    session: aiohttp.ClientSession,
    entity_ids: list[str],
    start: dt.datetime,
) -> dict[str, list]:
    """Fetch and downsample history for the given entities."""
    if not entity_ids:
        return {}
    ids = entity_ids[:MAX_HISTORY_ENTITIES]
    path = (
        f"/history/period/{start.isoformat()}"
        f"?filter_entity_id={','.join(ids)}&minimal_response&no_attributes"
    )
    raw = await _rest_get(session, path, timeout=90)
    out: dict[str, list] = {}
    for series in raw or []:
        if not series:
            continue
        eid = series[0].get("entity_id", "")
        numeric: list[tuple[str, float]] = []
        changes: list[list] = []
        for point in series:
            ts = (point.get("last_changed") or point.get("last_updated") or "")[:19]
            val = _num(point.get("state"))
            if val is not None:
                numeric.append((ts, val))
            else:
                sv = point.get("state")
                if sv not in ("unavailable", "unknown", None):
                    changes.append([ts, sv])
        if len(numeric) >= max(3, len(changes)):
            out[eid] = _bucket_hourly(numeric)
        elif changes:
            out[eid] = changes[-MAX_STATE_CHANGES:]
    return out


# ---------------------------------------------------------------------------
# Long-term statistics (energy)
# ---------------------------------------------------------------------------

async def get_statistics(
    session: aiohttp.ClientSession,
    statistic_ids: list[str],
    start: dt.datetime,
) -> dict[str, list]:
    if not statistic_ids:
        return {}
    ids = statistic_ids[:MAX_STAT_IDS]
    results = await _ws_commands(session, [{
        "type": "recorder/statistics_during_period",
        "start_time": start.isoformat(),
        "statistic_ids": ids,
        "period": "hour",
        "types": ["sum", "mean"],
    }])
    stats = results[0] or {}
    out: dict[str, list] = {}
    for sid, rows in stats.items():
        series = []
        prev_sum = None
        for row in rows:
            ts = row.get("start")
            if isinstance(ts, (int, float)):
                ts = dt.datetime.fromtimestamp(ts / 1000, tz=dt.timezone.utc).isoformat()[:13]
            else:
                ts = str(ts)[:13]
            if row.get("sum") is not None:
                # convert cumulative sum to per-hour delta (usable consumption)
                cur = row["sum"]
                delta = round(cur - prev_sum, 3) if prev_sum is not None else None
                prev_sum = cur
                if delta is not None and delta >= 0:
                    series.append([ts, delta])
            elif row.get("mean") is not None:
                series.append([ts, round(row["mean"], 2)])
        if series:
            out[sid] = series
    return out


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

def _read_capped(path: str, limit: int) -> str:
    if limit <= 0:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read(limit).strip()
    except OSError:
        return ""


def _read_context() -> str:
    """Learned memory (memory.md) first, then the CLAUDE.md excerpt.

    Memory facts lead because they are distilled knowledge about this home;
    the CLAUDE.md excerpt fills whatever budget remains.
    """
    parts: list[str] = []
    memory = _read_capped(MEMORY_FILE, CONTEXT_CHARS)
    if memory:
        parts.append(memory)
    claude_md = _read_capped(CONTEXT_FILE, CONTEXT_CHARS - len(memory))
    if claude_md:
        parts.append(claude_md)
    return "\n\n".join(parts)


def _shrink_to_budget(bundle: dict) -> dict:
    """Drop the heaviest sections until the serialized bundle fits."""
    def size() -> int:
        return len(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))

    if size() <= MAX_BUNDLE_CHARS:
        return bundle
    # 1. halve history series (drop longest first)
    for key in ("statistics", "history"):
        section = bundle.get(key) or {}
        while section and size() > MAX_BUNDLE_CHARS:
            longest = max(section, key=lambda k: len(json.dumps(section[k])))
            del section[longest]
    # 2. trim entity list from the tail — raw entity rows go before the
    #    learned context, which is distilled knowledge about this home
    ents = bundle.get("entities") or []
    while len(ents) > 20 and size() > MAX_BUNDLE_CHARS:
        del ents[len(ents) // 2:]  # keep the front half
    # 3. drop free-text context only as a last resort
    if size() > MAX_BUNDLE_CHARS:
        bundle.pop("context", None)
    return bundle


async def collect_bundle(category: dict, history_days: int, question: str | None = None) -> dict:
    """Collect and slim everything the category needs into one prompt bundle."""
    now = dt.datetime.now().astimezone()
    async with aiohttp.ClientSession() as session:
        config, states, registries = await asyncio.gather(
            _rest_get(session, "/config"),
            _rest_get(session, "/states", timeout=60),
            get_registries(session),
        )

        include_unavail = bool(category.get("include_unavailable"))
        entities = filter_states(
            states, registries,
            category.get("domains", []),
            category.get("device_classes", []),
            include_unavailable=include_unavail,
        )
        # For ad-hoc questions, give Claude the whole (slimmed) home
        if question is not None:
            entities = filter_states(states, registries, [], [], include_unavailable=True)

        bundle: dict[str, Any] = {
            "meta": {
                "now": now.isoformat()[:19],
                "timezone": config.get("time_zone"),
                "location": config.get("location_name"),
                "ha_version": config.get("version"),
                "period_days": history_days,
            },
            "areas": registries["areas"],
            "entities": entities,
        }

        start = now - dt.timedelta(days=history_days)

        if category.get("history") and question is None:
            # prefer numeric sensors + primary domain entities for history
            ids = [e["e"] for e in entities if e.get("u")]
            if len(ids) < MAX_HISTORY_ENTITIES:
                primary = [
                    e["e"] for e in entities
                    if e["e"].split(".")[0] in category.get("domains", []) and e["e"] not in ids
                ]
                ids += primary
            try:
                hist = await get_history(session, ids, start)
                if hist:
                    bundle["history"] = hist
            except Exception:  # noqa: BLE001 — history is best-effort
                pass

        if category.get("stats") and question is None:
            ids = [
                e["e"] for e in entities
                if e.get("dc") in ("energy", "power") or (e.get("u") in ("kWh", "Wh", "W", "kW"))
            ]
            try:
                stats = await get_statistics(session, ids, start)
                if stats:
                    bundle["statistics"] = stats
            except Exception:  # noqa: BLE001 — stats are best-effort
                pass

        context = _read_context()
        if context:
            bundle["context"] = context

        return _shrink_to_budget(bundle)
