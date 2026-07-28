#!/usr/bin/env python3
"""Background daemon: poll the Minecraft server via RCON + MCStatus and write
/data/panel/stats.json plus /data/panel/players.json. The ingress panel and
the HA custom integration both read these files.

Polling cadence: every 15 seconds. Cheap enough to not matter, frequent enough
that HA sensors feel responsive.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rcon_client import Rcon  # noqa: E402
from mcstatus import JavaServer  # noqa: E402

POLL_INTERVAL = 15
RCON_HOST = "127.0.0.1"
RCON_PORT = 25575
QUERY_HOST = "127.0.0.1"
QUERY_PORT = 25565

PANEL = Path(os.environ.get("MC_PANEL_STATE", "/data/panel"))
STATS = PANEL / "stats.json"
PLAYERS = PANEL / "players.json"
RCON_SECRET = PANEL / "rcon.secret"


def _pw() -> str:
    env = os.environ.get("RCON_PASSWORD")
    if env:
        return env
    if RCON_SECRET.is_file():
        return RCON_SECRET.read_text().strip()
    return ""


_LIST_RE = re.compile(
    r"There are (?P<online>\d+) of a max(?: of)? (?P<max>\d+) players online:? ?(?P<players>.*)"
)
_TPS_RE = re.compile(r"TPS from last 1m, 5m, 15m:[^\d]*?([\d.]+),[^\d]*?([\d.]+),[^\d]*?([\d.]+)")


def _parse_list(reply: str) -> dict[str, Any]:
    # Strip Minecraft §-color codes
    plain = re.sub(r"§.", "", reply)
    m = _LIST_RE.search(plain)
    if not m:
        return {"online": 0, "max": 0, "players": []}
    names = [p.strip() for p in m.group("players").split(",") if p.strip()]
    return {
        "online": int(m.group("online")),
        "max": int(m.group("max")),
        "players": names,
    }


def _parse_tps(reply: str) -> list[float] | None:
    plain = re.sub(r"§.", "", reply)
    m = _TPS_RE.search(plain)
    if not m:
        return None
    return [float(m.group(i)) for i in (1, 2, 3)]


def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2))
    tmp.replace(path)


def _probe_rcon(password: str, want_version: bool = True) -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        with Rcon(RCON_HOST, password, port=RCON_PORT, timeout=5) as r:
            try:
                # `minecraft:list`, not `list`: Essentials overrides /list
                # and logs "Rcon issued server command" for every command it
                # handles — at our 15s cadence that's a third of console.log.
                # The namespaced form bypasses plugin overrides entirely and
                # always yields the vanilla format our regex parses.
                parsed = _parse_list(r.command("minecraft:list"))
                # Only adopt the parsed result if the regex actually matched
                # something useful. A zeros-only payload means the regex
                # missed the server's `/list` format and would otherwise
                # overwrite mcstatus's online/max during the later merge,
                # hiding any players from the panel.
                if parsed["max"] > 0 or parsed["players"]:
                    out.update(parsed)
            except Exception:  # noqa: BLE001
                pass
            try:
                tps = _parse_tps(r.command("tps"))
                if tps:
                    out["tps_1m"], out["tps_5m"], out["tps_15m"] = tps
            except Exception:  # noqa: BLE001
                pass
            # The brand string never changes while the JVM lives, and every
            # /version invocation makes Paper re-run its update check — which
            # now stack-traces into the server log for older MC versions
            # (api.papermc.io v2 is gone). Fetch it once and cache upstream.
            if want_version:
                try:
                    out["version_brand"] = r.command("version").strip()[:200]
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001 — server may simply be offline
        pass
    return out


def _probe_mcstatus() -> dict[str, Any]:
    out: dict[str, Any] = {}
    try:
        srv = JavaServer.lookup(f"{QUERY_HOST}:{QUERY_PORT}")
        status = srv.status()
        out["latency_ms"] = round(status.latency, 1)
        out["motd_rendered"] = str(status.description)[:300]
        out["version"] = status.version.name
        out["protocol"] = status.version.protocol
        if status.players:
            out.setdefault("online", status.players.online)
            out.setdefault("max", status.players.max)
            # `sample` is an optional list of currently-online players the
            # server advertises in its status ping. Paper always populates it
            # (capped at ~12). Use it as a fallback player-name source when
            # RCON `/list` parsing misses the format — which happens whenever
            # Paper tweaks the "There are X of a max of Y players…" string
            # between minor versions, causing the panel to show an empty
            # player list even though players are online.
            if getattr(status.players, "sample", None):
                out["players_sample"] = [p.name for p in status.players.sample]
    except Exception:  # noqa: BLE001
        pass
    return out


def write_stats(started_at: float, reachable: bool, last_rcon_ok: bool,
                payload: dict[str, Any]) -> None:
    # Player names come from RCON `/list` output when available; if the
    # parser missed the format (Paper tweaks it between versions) we fall
    # back to the mcstatus status-ping sample so the panel stays populated.
    players = payload.get("players") or []
    if not players and payload.get("players_sample"):
        players = payload["players_sample"]
    data: dict[str, Any] = {
        "updated_at": int(time.time()),
        "uptime_seconds": int(time.time() - started_at),
        "reachable": reachable,
        "rcon_ok": last_rcon_ok,
        "online": payload.get("online", 0),
        "max_players": payload.get("max", 0),
        "players": players,
        "tps_1m": payload.get("tps_1m"),
        "tps_5m": payload.get("tps_5m"),
        "tps_15m": payload.get("tps_15m"),
        "latency_ms": payload.get("latency_ms"),
        "motd": payload.get("motd_rendered"),
        "version": payload.get("version"),
        "protocol": payload.get("protocol"),
        "version_brand": payload.get("version_brand"),
    }
    _atomic_write(STATS, data)
    _atomic_write(PLAYERS, {
        "updated_at": data["updated_at"],
        "players": data["players"],
        "online": data["online"],
        "max": data["max_players"],
    })


def main() -> int:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))

    PANEL.mkdir(parents=True, exist_ok=True)
    started_at = time.time()
    version_brand: str | None = None

    while True:
        password = _pw()
        rcon_payload = (
            _probe_rcon(password, want_version=version_brand is None)
            if password else {}
        )
        rcon_ok = bool(rcon_payload)
        if rcon_payload.get("version_brand"):
            version_brand = rcon_payload["version_brand"]
        elif rcon_ok and version_brand is not None:
            rcon_payload["version_brand"] = version_brand
        elif not rcon_ok:
            # Server down (or restarting, possibly onto a new build) — drop
            # the cache so the next successful poll re-reads the brand.
            version_brand = None
        status_payload = _probe_mcstatus()
        merged = {**status_payload, **rcon_payload}
        reachable = bool(status_payload)
        write_stats(started_at, reachable, rcon_ok, merged)
        time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    sys.exit(main())
