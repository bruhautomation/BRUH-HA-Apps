"""Home Assistant Core API access for the panel — and the latency probe.

The request helper is lifted from brAIn's ha_mcp_server.py: SUPERVISOR_TOKEN
bearer auth, /api/* routed to Core through the Supervisor proxy, errors as
dicts rather than exceptions. The transport is injectable so the tests can
fake HA without a server.

The latency probe is the reason this file exists in the Lab phase: aux
lights (party light, laser on a smart plug) ride HA service calls during a
show, and their cues have to be scheduled EARLY by however long that path
actually takes in this house. Nobody should guess that number.
"""
from __future__ import annotations

import asyncio
import json
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable

SUPERVISOR_TOKEN = os.environ.get("SUPERVISOR_TOKEN", "")
HA_BASE_URL = os.environ.get("HA_BASE_URL", "http://supervisor/core/api")


def ha_api_request(endpoint: str, method: str = "GET", data: dict | None = None,
                   *, opener: Callable = urllib.request.urlopen,
                   timeout: float = 15.0) -> Any:
    """One HA Core API call. Returns parsed JSON, or {"error": ...}."""
    if not SUPERVISOR_TOKEN:
        return {"error": "SUPERVISOR_TOKEN not set (not running under the Supervisor?)"}
    url = f"{HA_BASE_URL}{endpoint}"
    body = json.dumps(data).encode() if data is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {SUPERVISOR_TOKEN}",
            "Content-Type": "application/json",
        },
    )
    try:
        with opener(request, timeout=timeout) as response:
            text = response.read().decode()
    except urllib.error.HTTPError as exc:
        return {"error": f"HTTP {exc.code} from {endpoint}"}
    except (urllib.error.URLError, OSError) as exc:
        return {"error": f"cannot reach Home Assistant: {exc}"}
    try:
        return json.loads(text) if text else None
    except json.JSONDecodeError:
        return {"error": f"non-JSON answer from {endpoint}"}


def get_states(domain: str | None = None, *, opener=urllib.request.urlopen) -> list[dict]:
    states = ha_api_request("/states", opener=opener)
    if not isinstance(states, list):
        return []
    if domain:
        prefix = f"{domain}."
        states = [s for s in states if s.get("entity_id", "").startswith(prefix)]
    return states


def get_state(entity_id: str, *, opener=urllib.request.urlopen) -> dict:
    state = ha_api_request(f"/states/{entity_id}", opener=opener)
    return state if isinstance(state, dict) else {"error": "no state"}


def call_service(domain: str, service: str, data: dict | None = None,
                 *, opener=urllib.request.urlopen) -> Any:
    return ha_api_request(f"/services/{domain}/{service}", method="POST",
                          data=data or {}, opener=opener)


def play_media(entity_id: str, media_content_id: str,
               media_content_type: str = "music",
               *, opener=urllib.request.urlopen) -> Any:
    return call_service("media_player", "play_media", {
        "entity_id": entity_id,
        "media_content_id": media_content_id,
        "media_content_type": media_content_type,
    }, opener=opener)


def position_snapshot(entity_id: str, *, opener=urllib.request.urlopen) -> dict:
    """What the player says about its own position, for the reliability
    check the drift corrector depends on."""
    state = get_state(entity_id, opener=opener)
    attributes = state.get("attributes") or {}
    return {
        "state": state.get("state"),
        "media_position": attributes.get("media_position"),
        "media_position_updated_at": attributes.get("media_position_updated_at"),
    }


# ---------------------------------------------------------------------------
# The service-call latency probe
# ---------------------------------------------------------------------------
_TOGGLABLE = ("switch", "light", "input_boolean")


def _probe_once(entity_id: str, *, opener, poll_s: float, timeout_s: float,
                clock: Callable[[], float] = time.monotonic,
                sleep: Callable[[float], None] = time.sleep) -> float | None:
    """One toggle: call the service, poll until the state flips, return ms.

    Measures the full round trip a show cue takes: our request → Core →
    the device's integration → the state machine reporting the change.
    """
    domain = entity_id.split(".", 1)[0]
    before = get_state(entity_id, opener=opener).get("state")
    if before not in ("on", "off"):
        return None
    target = "off" if before == "on" else "on"
    started = clock()
    call_service(domain, "toggle", {"entity_id": entity_id}, opener=opener)
    deadline = started + timeout_s
    while clock() < deadline:
        if get_state(entity_id, opener=opener).get("state") == target:
            return (clock() - started) * 1000.0
        sleep(poll_s)
    return None


def latency_probe(entity_id: str, rounds: int = 6, *,
                  opener=urllib.request.urlopen, poll_s: float = 0.05,
                  timeout_s: float = 5.0,
                  clock: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep) -> dict:
    """Toggle the entity `rounds` times, measuring call→state-change each
    time, and leave it in the state it started in (rounds is forced even
    for exactly that reason). Blocking — run via asyncio.to_thread."""
    domain = entity_id.split(".", 1)[0]
    if domain not in _TOGGLABLE:
        return {"error": f"can only probe {', '.join(_TOGGLABLE)} entities"}
    rounds = max(2, rounds + (rounds % 2))  # even, so the state comes home
    samples: list[float] = []
    timeouts = 0
    for i in range(rounds):
        sample = _probe_once(entity_id, opener=opener, poll_s=poll_s,
                             timeout_s=timeout_s, clock=clock, sleep=sleep)
        if sample is None:
            timeouts += 1
        else:
            samples.append(round(sample, 1))
        if i + 1 < rounds:
            sleep(0.5)  # let the device settle; some plugs debounce
    result: dict[str, Any] = {
        "entity_id": entity_id,
        "rounds": rounds,
        "samples_ms": samples,
        "timeouts": timeouts,
    }
    if samples:
        ordered = sorted(samples)
        result["p50_ms"] = ordered[len(ordered) // 2]
        result["max_ms"] = ordered[-1]
    return result


# ---------------------------------------------------------------------------
# Async wrappers for the panel's handlers
# ---------------------------------------------------------------------------
async def async_get_states(domain: str | None = None) -> list[dict]:
    return await asyncio.to_thread(get_states, domain)


async def async_latency_probe(entity_id: str, rounds: int = 6) -> dict:
    return await asyncio.to_thread(latency_probe, entity_id, rounds)
