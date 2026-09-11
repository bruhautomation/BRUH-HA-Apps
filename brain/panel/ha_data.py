"""Home Assistant data collection for brAIn.

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
import re
from typing import Any

import aiohttp

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
CORE_API = os.environ.get("BRAIN_CORE_API", "http://supervisor/core/api")
CORE_WS = os.environ.get("BRAIN_CORE_WS", "ws://supervisor/core/websocket")
CONTEXT_FILE = os.environ.get("BRAIN_CONTEXT_FILE", "/config/CLAUDE.md")
# Learned facts about the home, maintained by the brain integration
# (memory features). Plain markdown; may not exist.
MEMORY_FILE = os.environ.get("BRAIN_MEMORY_FILE", "/config/.brain/memory/memory.md")

# Hard caps that keep the bundle inside the prompt budget
MAX_ENTITIES = 500
MAX_HISTORY_ENTITIES = 28
MAX_STATE_CHANGES = 50
MAX_STAT_IDS = 24
MAX_BUNDLE_CHARS = 120_000
CONTEXT_CHARS = 4_000
# Learned memory gets its own budget rather than sharing CONTEXT_CHARS.
# It used to be read with `_read_capped(MEMORY_FILE, CONTEXT_CHARS)` and the
# CLAUDE.md excerpt handed whatever was left, which had two failure modes at
# once: a memory document larger than 4 KB was silently truncated mid-fact,
# and a document that filled the budget starved the house context entirely.
# Sized to hold a full memory.md (memory_max_kb, 32 by default) plus slack.
MEMORY_CHARS = 34_000
# Device-context expansion (sibling sensors of presence trackers)
MAX_CONTEXT_ENTITIES = 150
MAX_CONTEXT_PER_DEVICE = 40

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
    "person": ["source", "device_trackers"],
    "device_tracker": ["source_type", "battery_level", "gps_accuracy"],
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
# Asking Core for history, once
# ---------------------------------------------------------------------------
#
# Three callers built this query by hand — `get_history` here,
# `closures.fetch_history` and `shadow.fetch_history` — each pasting
# `','.join(ids)` into the URL after the `?`. `_rest_get`'s own docstring
# says not to, and says why, and all three were written past it.
#
# It is not only a style rule. On the replay path the ids come out of an
# automation config that arrived in an HTTP body, so an id carrying `&`
# or `#` is a second parameter or a fragment rather than a value — which
# is what CodeQL reported as a partial SSRF, correctly. Off that path the
# ids come from the registry and the same character corrupts the call
# quietly instead, which is the failure nobody would ever trace.
#
# So the query is built in one place, out of ids that have been checked
# against what an entity id may contain, and handed to aiohttp as
# `params` so it does the encoding. `tests/test_ha_history_query.py`
# greps for the old shape, because the thing to stop is a fourth copy.

ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def is_entity_id(value: str) -> bool:
    """Whether this is an entity id, by the only characters Core makes."""
    return bool(ENTITY_ID_RE.match(str(value or "")))


def safe_entity_ids(ids) -> list[str]:
    """The ids that are ids, in order, deduped.

    Dropped rather than escaped: an id that is not an id names nothing,
    so encoding it would spend a request asking Core about a string
    somebody made up. `actions._logbook` already refuses this way.
    """
    seen, out = set(), []
    for raw in ids or []:
        eid = str(raw or "")
        if is_entity_id(eid) and eid not in seen:
            seen.add(eid)
            out.append(eid)
    return out


def history_params(ids, end: dt.datetime, *,
                   minimal: bool = False,
                   no_attributes: bool = False) -> dict[str, str]:
    """Core's `/history/period` query, as params rather than as a string.

    The flags are valueless in Core's API, and aiohttp will not send a
    bare key — `""` is what reaches the wire as `&minimal_response=`,
    which Core reads as present. That is the one detail that makes this
    a drop-in for the strings it replaces.

    **`end` has no default, and that is the whole of this bug.** Core's
    `/history/period/<start>` does not run to now when `end_time` is
    absent — it defaults to **start + one day** — so a caller that omits
    it does not get "everything since `start`", it gets a single day
    ending 27 days ago. `closures.fetch_history` asked for 28 days that
    way and got a day outside the recorder's 10-day retention: `[]` for
    every door in the house, every night, which is a list, so the fetch
    read it as "this house's history holds nothing" rather than as a
    refusal, wrote an empty store with no error, and left
    `evening.left_open` permanently skipped on `snapshot is missing
    closures`. `get_history` omitted it too, which is the same bug where
    it is much harder to see: every insight card built on the snapshot
    path got one day of history from `history_days` ago and presented it
    as current.

    So the parameter is positional and required. A caller that genuinely
    wants Core's own default has to write the date that produces it,
    which is a thing a reader can see and argue with; `None` would be
    the invisible spelling that cost two features and could not be
    grepped for, since the bug is in the argument that is NOT there.
    """
    params: dict[str, str] = {}
    kept = safe_entity_ids(ids)
    if kept:
        params["filter_entity_id"] = ",".join(kept)
    params["end_time"] = end.isoformat()
    if minimal:
        params["minimal_response"] = ""
    if no_attributes:
        params["no_attributes"] = ""
    return params


def history_path(start: dt.datetime) -> str:
    """The path half, which holds a timestamp and nothing a caller typed."""
    return f"/history/period/{start.isoformat()}"


# ---------------------------------------------------------------------------
# Raw fetchers
# ---------------------------------------------------------------------------

async def _rest_get(session: aiohttp.ClientSession, path: str,
                    timeout: int = 30, params: dict | None = None) -> Any:
    """GET one of Core's REST endpoints.

    ``params`` rather than a hand-built query string, for anything whose
    value did not come from this file: aiohttp encodes it, so a value
    holding an `&` becomes a value rather than a second parameter, and
    nothing a caller passes can steer the request into being a different
    request. Building a query with `+` is how that happens, and it is
    equally how an ordinary entity id with an odd character in it would
    silently corrupt the call.
    """
    async with session.get(
        f"{CORE_API}{path}", headers=_headers(), params=params or None,
        timeout=aiohttp.ClientTimeout(total=timeout),
    ) as resp:
        resp.raise_for_status()
        return await resp.json()


async def call_service(service: str, data: dict, timeout: int = 15) -> Any:
    """Call a brain.<service> HA service through the Supervisor proxy.

    Raises on HTTP errors / network failure — the integration may simply
    not be installed, so callers must treat failures as expected.
    """
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CORE_API}/services/brain/{service}", headers=_headers(),
            json=data, timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def call_core_service(domain: str, service: str,
                            data: dict | None = None,
                            timeout: int = 30) -> Any:
    """Call any `<domain>.<service>` on Core. Raises on anything but 2xx.

    `call_service` above is `brain.*`-only by construction — it exists to
    reach the integration and hardcodes the domain, which is what keeps a
    caller from turning a request for brAIn's own service into a request
    for anybody's. This is the general one, and it has exactly one caller
    on purpose: the accept path's `automation.reload`. Both halves of the
    path are in the URL rather than in a body, so both are checked here
    against the shape a domain and a service can have — an add-on that
    pasted a name off the wire into a path is how `history_params` became
    a partial SSRF.
    """
    for part in (domain, service):
        if not re.fullmatch(r"[a-z0-9_]+", str(part or "")):
            raise ValueError(f"{part!r} is not a service name")
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CORE_API}/services/{domain}/{service}", headers=_headers(),
            json=data or {}, timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            resp.raise_for_status()
            return await resp.json()


async def entity_exists(entity_id: str, timeout: int = 15) -> bool:
    """Whether Core currently has a state for this entity.

    The half that separates "the file was written" from "the automation
    exists" — the distinction BRight's `playback_check` draws between a
    service call being accepted and a speaker making a sound. A 404 is
    the answer, not an error; anything else raises, because "Core did not
    answer" and "Core says it is not there" are different claims.
    """
    if not is_entity_id(str(entity_id or "")):
        return False
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{CORE_API}/states/{entity_id}", headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 404:
                return False
            resp.raise_for_status()
            return True


async def entity_state(entity_id: str, timeout: int = 15) -> dict | None:
    """Core's current state row for one entity, or None if it has none.

    `entity_exists`' sibling, and separate for the same reason it draws
    its own distinction: an armed intent is watched by reading
    `last_triggered` off the automation, which is an **attribute** — a
    boolean answer cannot carry one, and asking twice would be two
    questions about an entity that may change between them. A 404 is the
    answer; anything else raises, because "Core did not answer" and
    "Core says it is not there" are different claims.
    """
    if not is_entity_id(str(entity_id or "")):
        return None
    async with aiohttp.ClientSession() as session:
        async with session.get(
            f"{CORE_API}/states/{entity_id}", headers=_headers(),
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            if resp.status == 404:
                return None
            resp.raise_for_status()
            data = await resp.json()
            return data if isinstance(data, dict) else None


async def entity_states(entity_ids: list[str],
                        timeout: int = 15) -> dict[str, dict]:
    """Current state rows for a handful of named entities.

    One session for the lot, and one request each — rather than `/states`,
    which is the whole house and is hundreds of kilobytes on a real one.
    That trade only holds for a SHORT list; this is called on a timer by
    every insight card currently on screen, and `server.MAX_LIVE_ENTITIES`
    is what keeps it short.

    An entity Core does not have is absent from the answer rather than
    present-and-empty: a card asking about something that has since been
    removed should show what it was drawn with, not a blank.
    """
    wanted = [e for e in dict.fromkeys(entity_ids) if is_entity_id(e)]
    if not wanted:
        return {}
    out: dict[str, dict] = {}

    async with aiohttp.ClientSession() as session:
        async def one(eid: str) -> None:
            try:
                async with session.get(
                    f"{CORE_API}/states/{eid}", headers=_headers(),
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
            except Exception:  # noqa: BLE001 — one entity that would not
                # answer is one entity missing from the refresh, never a
                # refresh that failed.
                return
            if isinstance(data, dict):
                out[eid] = data

        await asyncio.gather(*(one(e) for e in wanted))
    return out


async def send_notification(service: str, title: str, message: str,
                            timeout: int = 15, data: dict | None = None) -> None:
    """Deliver one notification through a notify.<service> HA service.

    ``service`` may arrive with or without the ``notify.`` prefix — people
    paste both, and the insight-job option on the integration side already
    tolerates both. Raises on failure; the caller decides whether a missed
    notification is worth a log line or a retry.

    ``data`` is the notifier-specific payload (the companion app's
    ``actions``, and nothing else so far). It is **omitted entirely when
    empty** rather than sent as ``{}``: several notifiers treat the key's
    presence as a request to be parsed, and the caller decides whether a
    given service can take one — see ``notify_router.can_answer``.
    """
    service = str(service or "").strip().removeprefix("notify.")
    if not service:
        raise ValueError("no notify service given")
    payload: dict = {"title": title, "message": message}
    if data:
        payload["data"] = data
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CORE_API}/services/notify/{service}", headers=_headers(),
            json=payload,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            resp.raise_for_status()


async def _ws_commands(session: aiohttp.ClientSession, commands: list[dict]) -> list[Any]:
    """Run a list of WS API commands, returning results in order (None on error).

    Right for every command that ASKS for something: a registry list, a
    statistics window, the energy prefs. Wrong for one that CHANGES
    something, because Core answers a successful mutation with
    ``result: null`` — which lands here as the same ``None`` that means
    the call failed. Those callers want :func:`_ws_calls`.
    """
    return [c["result"] for c in await _ws_calls(session, commands)]


async def _ws_calls(session: aiohttp.ClientSession,
                    commands: list[dict]) -> list[dict]:
    """The same round trip, with success reported rather than inferred.

    ``[{"ok": bool, "result": Any, "error": str}, ...]``, in order.

    `_ws_commands` collapses the two things Core distinguishes: it hands
    back the ``result`` field, and a successful delete's ``result`` is
    ``null``. So `input_number/delete` — which really did delete the
    helper — was indistinguishable from a refusal, and the rehearsal
    reported *"Home Assistant would not delete
    input_number.brain_test_reading"* on every clean run while its own
    leftovers scan, reading the states, could see the helper was gone.
    Two answers to "did that work", and the louder one was wrong.

    One implementation, with `_ws_commands` layered on it, because two
    round trips would be two chances to disagree about what Core said.
    """
    # outer wait_for instead of ws timeout kwargs: the kwarg's type changed
    # across aiohttp versions and the base image's py3-aiohttp varies
    return await asyncio.wait_for(_ws_commands_inner(session, commands), timeout=90)


async def _ws_commands_inner(session: aiohttp.ClientSession,
                             commands: list[dict]) -> list[dict]:
    results: list[dict] = [
        {"ok": False, "result": None, "error": "no answer from Home Assistant"}
        for _ in commands]
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
                if idx is not None:
                    if data.get("success"):
                        results[idx] = {"ok": True, "result": data.get("result"),
                                        "error": ""}
                    else:
                        err = data.get("error") or {}
                        results[idx] = {
                            "ok": False, "result": None,
                            "error": str(err.get("message")
                                         or err.get("code") or "refused")}
                if not pending:
                    break
        if not authed:
            raise RuntimeError("WebSocket auth handshake did not complete")
    return results


# ---------------------------------------------------------------------------
# Registries → entity/area lookup
# ---------------------------------------------------------------------------

async def get_registries(session: aiohttp.ClientSession) -> dict[str, dict]:
    """Return {entity_id: area_name}, entity→device mappings, and the raw
    area list. The device mappings power device-context expansion: finding
    the sibling sensors (SSID, geocoded location, activity…) that live on
    the same physical device as a presence tracker."""
    areas, devices, entities = await _ws_commands(session, [
        {"type": "config/area_registry/list"},
        {"type": "config/device_registry/list"},
        {"type": "config/entity_registry/list"},
    ])
    area_names = {a["area_id"]: a["name"] for a in (areas or [])}
    device_area = {d["id"]: d.get("area_id") for d in (devices or [])}
    device_names = {
        d["id"]: (d.get("name_by_user") or d.get("name") or "")
        for d in (devices or [])
    }
    ent_area: dict[str, str] = {}
    ent_device: dict[str, str] = {}
    hidden: set[str] = set()
    for e in entities or []:
        eid = e.get("entity_id", "")
        if e.get("disabled_by") or e.get("hidden_by"):
            hidden.add(eid)
            continue
        device_id = e.get("device_id")
        if device_id:
            ent_device[eid] = device_id
        area_id = e.get("area_id") or device_area.get(device_id or "", None)
        name = area_names.get(area_id or "")
        if name:
            ent_area[eid] = name
    return {
        "entity_area": ent_area,
        "entity_device": ent_device,
        "device_names": device_names,
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


def _slug(text: str) -> str:
    """Home Assistant's own object-id slugification, near enough."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _minutes_since(stamp: str, now: dt.datetime | None) -> int | None:
    """An ISO timestamp as whole minutes before ``now``.

    None when it can't be parsed or ``now`` wasn't supplied — the field is
    then simply absent, which is what a row with no last_changed already
    looked like.
    """
    if not stamp or now is None:
        return None
    try:
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    return max(0, int((now - when).total_seconds() // 60))


def slim_state(state: dict, area: str | None,
               now: dt.datetime | None = None) -> dict:
    """One entity as the fewest characters that still carry every signal.

    Three of the encodings here were chosen for size, and each keeps what
    the field is actually read for:

    * ``lc`` is minutes-since, not an ISO timestamp. Staleness is the only
      thing last_changed is ever read for, and 19 characters of absolute
      time cost three times what the answer does — while making the model
      diff it against ``meta.now`` to get there. Minutes rather than hours
      because "it changed 6 minutes ago" is a different fact from "it
      changed an hour ago" and the two encodings cost the same.
    * ``n`` is dropped when it is just the slugified entity_id, which is
      what Home Assistant names an entity by default. It is a second copy
      of a string already on the row; a renamed entity still carries it.
    * an unavailable entity keeps only ``e``/``s``/``a``. Its unit, device
      class and attributes describe a reading that is not there, and "this
      exists and is down" is the whole of what the row has to say.
    """
    attrs = state.get("attributes", {}) or {}
    entity_id = state.get("entity_id") or ""
    domain = entity_id.split(".")[0]
    value = state.get("state")
    out: dict[str, Any] = {"e": entity_id, "s": value}
    if value in ("unavailable", "unknown"):
        if area:
            out["a"] = area
        return out
    name = attrs.get("friendly_name")
    if name and _slug(str(name)) != entity_id.split(".", 1)[-1]:
        out["n"] = name
    if area:
        out["a"] = area
    unit = attrs.get("unit_of_measurement")
    if unit:
        out["u"] = unit
    dc = attrs.get("device_class")
    if dc:
        out["dc"] = dc
    minutes = _minutes_since(state.get("last_changed") or "", now)
    if minutes is not None:
        out["lc"] = minutes
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
    now: dt.datetime | None = None,
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
        out.append(slim_state(st, ent_area.get(eid), now))
    return out[:MAX_ENTITIES]


def related_device_entities(
    states: list[dict],
    registries: dict,
    present_ids: set[str],
    now: dt.datetime | None = None,
) -> list[dict]:
    """Sibling entities of presence trackers — the phone context.

    A `device_tracker.*` entity says "home"/"not_home"; the *interesting*
    signals (WiFi SSID, geocoded address, detected activity, battery/charging
    state, distance sensors) are separate `sensor.*` entities that live on
    the same physical device (the companion-app phone). Category filters
    never match them, so this walks the device registry: every device that
    owns a tracker contributes its other entities, slimmed and tagged with
    the device name (`d`) so the analyst can group signals per phone.
    """
    ent_device = registries.get("entity_device") or {}
    device_names = registries.get("device_names") or {}
    hidden = registries.get("hidden") or set()
    ent_area = registries.get("entity_area") or {}

    tracker_devices: list[str] = []
    for st in states:
        eid = st.get("entity_id", "")
        if not eid.startswith("device_tracker.") or eid in hidden:
            continue
        device_id = ent_device.get(eid)
        if device_id and device_id not in tracker_devices:
            tracker_devices.append(device_id)
    if not tracker_devices:
        return []

    by_device: dict[str, list[dict]] = {d: [] for d in tracker_devices}
    for st in states:
        eid = st.get("entity_id", "")
        if eid in present_ids or eid in hidden:
            continue
        if st.get("state") in ("unavailable", "unknown"):
            continue
        device_id = ent_device.get(eid)
        if device_id not in by_device:
            continue
        if len(by_device[device_id]) >= MAX_CONTEXT_PER_DEVICE:
            continue
        slim = slim_state(st, ent_area.get(eid), now)
        name = device_names.get(device_id)
        if name:
            slim["d"] = name
        by_device[device_id].append(slim)

    out: list[dict] = []
    for device_id in tracker_devices:
        out.extend(by_device[device_id])
    return out[:MAX_CONTEXT_ENTITIES]


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
    end: dt.datetime | None = None,
) -> dict[str, list]:
    """Fetch and downsample history for the given entities.

    ``end`` defaults to now, which is what every caller here means by
    "history since `start`" — and is emphatically not what Core does with
    an absent `end_time`. See :func:`history_params`: leaving it off asked
    for one day starting `history_days` ago, so a card built on a week of
    history was reading a single day of it, six days stale, and saying
    nothing about that.
    """
    if not entity_ids:
        return {}
    ids = entity_ids[:MAX_HISTORY_ENTITIES]
    finish = end or dt.datetime.now(dt.timezone.utc)
    raw = await _rest_get(
        session, history_path(start), timeout=90,
        params=history_params(ids, finish, minimal=True, no_attributes=True))
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
    memory = _read_capped(MEMORY_FILE, MEMORY_CHARS)
    if memory:
        parts.append(memory)
    claude_md = _read_capped(CONTEXT_FILE, CONTEXT_CHARS)
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
    # 1b. trim device context from the tail (it's ordered per-device, so the
    #     front devices keep their full context)
    ctx = bundle.get("device_context") or []
    while len(ctx) > 20 and size() > MAX_BUNDLE_CHARS:
        del ctx[len(ctx) // 2:]
    # 2. trim entity list from the tail — raw entity rows go before the
    #    learned context, which is distilled knowledge about this home
    ents = bundle.get("entities") or []
    while len(ents) > 20 and size() > MAX_BUNDLE_CHARS:
        del ents[len(ents) // 2:]  # keep the front half
    # 3. trim the free-text context, and only drop it outright if trimming
    #    it away still isn't enough. Popping it was fine when it was 4 KB;
    #    now that a full memory document fits in it, "drop it all" would
    #    throw away everything brAIn has learned about the home to save a
    #    few hundred characters.
    ctx_text = bundle.get("context") or ""
    while ctx_text and size() > MAX_BUNDLE_CHARS:
        ctx_text = ctx_text[:len(ctx_text) // 2]
        if len(ctx_text) < 500:
            break
        bundle["context"] = ctx_text
    if size() > MAX_BUNDLE_CHARS:
        bundle.pop("context", None)
    return bundle


# An orientation is a map, not the territory: how many of each domain exist,
# which areas they sit in, and the few singleton entities worth naming
# outright. Anything longer defeats the point — the moment it enumerates
# entity ids it is a full bundle wearing a smaller name.
MAX_ORIENTATION_AREAS = 60
MAX_ORIENTATION_DOMAINS = 30
# Domains where naming every entity is cheaper than making Claude search for
# them, because a home has a handful and they anchor almost every question.
ANCHOR_DOMAINS = ("person", "climate", "weather", "alarm_control_panel")
MAX_ANCHORS = 40


async def collect_orientation(question: str | None = None) -> dict:
    """What the home CONTAINS — the small bundle the searching path starts on.

    The single-shot path posts every entity because it has one turn to work
    with and cannot ask for more. This one posts the shape of the house:
    domain counts, area names, and the handful of anchor entities almost
    every question touches. Claude then calls the read-only MCP tools for
    the rows it decides it needs.

    That is the whole saving. An INDEX of every entity id would cost nearly
    as much as the slimmed rows themselves — measured — so this deliberately
    does not enumerate ids. Claude searches by domain and by name substring,
    the way a person would.
    """
    now = dt.datetime.now().astimezone()
    async with aiohttp.ClientSession() as session:
        config, states, registries = await asyncio.gather(
            _rest_get(session, "/config"),
            _rest_get(session, "/states", timeout=60),
            get_registries(session),
        )

    hidden = registries["hidden"]
    ent_area = registries["entity_area"]
    domains: dict[str, int] = {}
    per_area: dict[str, int] = {}
    unavailable = 0
    anchors: list[dict] = []
    for st in states:
        eid = st.get("entity_id", "")
        if not eid or eid in hidden:
            continue
        domain = eid.split(".")[0]
        domains[domain] = domains.get(domain, 0) + 1
        area = ent_area.get(eid)
        if area:
            per_area[area] = per_area.get(area, 0) + 1
        if st.get("state") in ("unavailable", "unknown"):
            unavailable += 1
        if domain in ANCHOR_DOMAINS and len(anchors) < MAX_ANCHORS:
            anchors.append(slim_state(st, area, now))

    ranked_domains = dict(sorted(domains.items(), key=lambda kv: -kv[1])
                          [:MAX_ORIENTATION_DOMAINS])
    ranked_areas = dict(sorted(per_area.items(), key=lambda kv: -kv[1])
                        [:MAX_ORIENTATION_AREAS])
    out: dict[str, Any] = {
        "meta": {
            "now": now.isoformat()[:19],
            "timezone": config.get("time_zone"),
            "location": config.get("location_name"),
            "ha_version": config.get("version"),
        },
        "entity_count": sum(domains.values()),
        "unavailable_count": unavailable,
        "domains": ranked_domains,
        "areas": ranked_areas,
        "anchors": anchors,
    }
    if question is not None:
        out["question"] = question
    context = _read_context()
    if context:
        out["context"] = context
    return out


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
            now=now,
        )
        # For ad-hoc questions, give Claude the whole (slimmed) home
        if question is not None:
            entities = filter_states(states, registries, [], [],
                                     include_unavailable=True, now=now)

        device_context: list[dict] = []
        if category.get("device_context") or question is not None:
            present = {e["e"] for e in entities}
            device_context = related_device_entities(
                states, registries, present, now=now)

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
        if device_context:
            bundle["device_context"] = device_context

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
            if len(ids) < MAX_HISTORY_ENTITIES:
                # device-context state changes (SSID joins, geocoded address
                # moves) carry the arrival/departure story for presence
                ids += [e["e"] for e in device_context if e["e"] not in ids]
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
