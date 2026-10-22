"""Level 1: every app, Home Assistant and the Supervisor, from the Supervisor.

The Supervisor already measures each container (it is what Settings → System
→ Hardware draws), so this module only asks and does arithmetic. Two details
matter.

**CPU is computed here, from the cumulative counters.** The v1 stats route
can compute a windowed percentage itself, but only by making Docker take two
samples a second apart — per app, per poll. Asking for a one-shot sample and
dividing the change in `cpu_usage` by the change in `cpu_system_usage`
between two of OUR polls is the same formula the Supervisor uses
(`DockerStats._calc_cpu_percent`: a share of the whole machine), costs one
quick read, and covers the whole poll interval rather than one second of it.
An older Supervisor ignores `one_shot` and fills `cpu_percent`, which is the
fallback for the very first reading.

**Every action names its consequence first** (`impact`), because "Stop" on a
row that is actually your MQTT broker is a different press from the same word
on a row that is an idle file editor, and the Supervisor knows which
integrations talk to which app.
"""
from __future__ import annotations

import asyncio
import os
import time

import aiohttp

SUPERVISOR_URL = os.environ.get("TASK_MANAGER_SUPERVISOR_URL", "http://supervisor")
HISTORY = 60

PLUGINS = {
    "dns": "DNS (Supervisor plugin)",
    "audio": "Audio (Supervisor plugin)",
    "multicast": "Multicast (Supervisor plugin)",
    "observer": "Observer (Supervisor plugin)",
    "cli": "CLI (Supervisor plugin)",
}
# Plugins the Supervisor documents a restart for. Observer and CLI are
# measured but get no button: a restart of either fixes nothing a person
# would come here to fix.
RESTARTABLE_PLUGINS = ("dns", "audio", "multicast")


class SupervisorError(Exception):
    pass


class Supervisor:
    """A thin client: unwrap {"result", "data"} and say what went wrong."""

    def __init__(self, base: str = SUPERVISOR_URL, token: str | None = None,
                 session: aiohttp.ClientSession | None = None) -> None:
        self.base = base.rstrip("/")
        self.token = token if token is not None else os.environ.get("SUPERVISOR_TOKEN", "")
        self._session = session

    async def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def request(self, method: str, path: str, *, json=None,
                      params=None, timeout: float = 15):
        session = await self.session()
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with session.request(
                method, self.base + path, json=json, params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                try:
                    body = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError):
                    body = None
                if resp.status >= 400 or not isinstance(body, dict) \
                        or body.get("result") == "error":
                    message = (body or {}).get("message") if isinstance(body, dict) else None
                    raise SupervisorError(
                        message or f"The Supervisor answered HTTP {resp.status} to {path}.")
                return body.get("data", {})
        except asyncio.TimeoutError:
            raise SupervisorError(f"The Supervisor did not answer {path} in time.") from None
        except aiohttp.ClientError as exc:
            raise SupervisorError(f"Could not reach the Supervisor ({exc}).") from None

    async def get(self, path: str, **kwargs):
        return await self.request("GET", path, **kwargs)

    async def post(self, path: str, **kwargs):
        return await self.request("POST", path, **kwargs)


def _num(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


class Rates:
    """Turns cumulative counters into per-poll figures, per app."""

    def __init__(self, clock=time.monotonic) -> None:
        self.clock = clock
        self._prev: dict[str, tuple] = {}
        self.history: dict[str, list] = {}

    def update(self, key: str, stats: dict) -> dict:
        now = self.clock()
        cur = (now, _num(stats.get("cpu_usage")), _num(stats.get("cpu_system_usage")),
               _num(stats.get("network_rx")), _num(stats.get("network_tx")),
               _num(stats.get("blk_read")), _num(stats.get("blk_write")))
        prev = self._prev.get(key)
        self._prev[key] = cur
        cpu = None
        rates = [None, None, None, None]
        if prev is not None:
            elapsed = max(now - prev[0], 1e-6)
            if None not in (cur[1], cur[2], prev[1], prev[2]):
                sys_delta = cur[2] - prev[2]
                cpu_delta = cur[1] - prev[1]
                if sys_delta > 0:
                    cpu = round(max(cpu_delta, 0) / sys_delta * 100.0, 2)
            for i in range(4):
                a, b = cur[3 + i], prev[3 + i]
                if a is not None and b is not None and a >= b:
                    rates[i] = round((a - b) / elapsed)
        if cpu is None:
            cpu = _num(stats.get("cpu_percent"))
        hist = self.history.setdefault(key, [])
        hist.append(cpu)
        del hist[:-HISTORY]
        return {
            "cpu": cpu,
            "mem_bytes": _num(stats.get("memory_usage")),
            "mem_percent": _num(stats.get("memory_percent")),
            "net_rx_rate": rates[0], "net_tx_rate": rates[1],
            "disk_read_rate": rates[2], "disk_write_rate": rates[3],
            "history": list(hist),
        }

    def forget(self, keep) -> None:
        for key in list(self._prev):
            if key not in keep:
                self._prev.pop(key, None)
                self.history.pop(key, None)


def actions_for(kind: str, state: str, is_self: bool) -> list[str]:
    if is_self:
        return []
    if kind == "addon":
        return ["restart", "stop"] if state == "started" else ["start"]
    if kind in ("core", "supervisor"):
        return ["restart"]
    return []


class AppSampler:
    def __init__(self, supervisor: Supervisor, clock=time.monotonic) -> None:
        self.supervisor = supervisor
        self.rates = Rates(clock)
        self.self_slug: str | None = None
        self.names: dict[str, str] = {}
        self.error: str | None = None

    async def _self(self) -> None:
        if self.self_slug:
            return
        try:
            info = await self.supervisor.get("/addons/self/info")
            self.self_slug = info.get("slug")
        except SupervisorError:
            # Asked again next pass; until then no row is marked "this app",
            # which only means its Restart button is offered one pass early.
            pass

    async def _stats(self, path: str):
        try:
            return await self.supervisor.get(path, params={"one_shot": ""}, timeout=12)
        except SupervisorError:
            return None

    async def sample(self) -> list[dict]:
        await self._self()
        try:
            listing = await self.supervisor.get("/addons")
        except SupervisorError as exc:
            self.error = str(exc)
            return []
        self.error = None
        addons = listing.get("addons") or []
        targets = [("core", "core", "Home Assistant", "started", "/core/stats", None),
                   ("supervisor", "supervisor", "Supervisor", "started",
                    "/supervisor/stats", None)]
        for name, label in PLUGINS.items():
            targets.append((f"plugin:{name}", "plugin", label, "started",
                            f"/{name}/stats", name))
        for addon in addons:
            slug = addon.get("slug")
            if not slug:
                continue
            self.names[slug] = addon.get("name") or slug
            targets.append((f"addon:{slug}", "addon", addon.get("name") or slug,
                            addon.get("state") or "unknown",
                            f"/addons/{slug}/stats" if addon.get("state") == "started" else None,
                            slug))

        sem = asyncio.Semaphore(6)

        async def one(target):
            key, kind, name, state, path, slug = target
            stats = None
            if path:
                async with sem:
                    stats = await self._stats(path)
            if stats is None and kind == "plugin":
                return None  # a plugin this Supervisor does not have
            is_self = kind == "addon" and slug == self.self_slug
            row = {
                "key": key, "kind": kind, "name": name, "slug": slug,
                "state": state, "is_self": is_self,
                "actions": actions_for(kind, state, is_self)
                + (["restart"] if kind == "plugin" and slug in RESTARTABLE_PLUGINS else []),
            }
            if stats is not None:
                row.update(self.rates.update(key, stats))
            else:
                row.update({"cpu": None, "mem_bytes": None, "mem_percent": None,
                            "history": []})
            return row

        rows = [r for r in await asyncio.gather(*(one(t) for t in targets)) if r]
        self.rates.forget({r["key"] for r in rows})
        rows.sort(key=lambda r: (-(r.get("cpu") or 0), r["name"].lower()))
        return rows


# ----------------------------------------------------------------------------
# Actions and what they cost
# ----------------------------------------------------------------------------

def action_path(key: str, action: str) -> str | None:
    if key == "core" and action == "restart":
        return "/core/restart"
    if key == "supervisor" and action == "restart":
        return "/supervisor/restart"
    if key.startswith("plugin:") and action == "restart":
        name = key.split(":", 1)[1]
        return f"/{name}/restart" if name in RESTARTABLE_PLUGINS else None
    if key.startswith("addon:") and action in ("restart", "stop", "start"):
        return f"/addons/{key.split(':', 1)[1]}/{action}"
    return None


def impact(key: str, action: str, name: str, info: dict | None) -> list[str]:
    """What pressing this will do, in sentences, before it is pressed."""
    info = info or {}
    if key == "core":
        return ["Automations, dashboards and voice stop for about a minute "
                + "while Home Assistant restarts.",
                "It shuts down cleanly first, so nothing is lost."]
    if key == "supervisor":
        return ["Your apps keep running.",
                "The Supervisor's own pages, updates and backups are "
                + "unavailable for about a minute."]
    if key == "plugin:dns":
        return ["Apps cannot look up names for a few seconds."]
    if key == "plugin:audio":
        return ["Sound from apps stops for a few seconds."]
    if key.startswith("plugin:"):
        return ["This part of the Supervisor restarts in a few seconds."]
    lines = []
    if action == "stop":
        lines.append(f"{name} stays stopped until you start it again"
                     + (" or Home Assistant restarts (it is set to start at boot)."
                        if info.get("boot") == "auto" else "."))
    elif action == "restart":
        lines.append(f"{name} is down for a few seconds to a minute while it restarts.")
    else:
        lines.append(f"{name} starts.")
    if action in ("stop", "restart"):
        found = [d for d in (info.get("discovery") or []) if isinstance(d, str)]
        if found:
            lines.append("Home Assistant integrations that talk to it ("
                         + ", ".join(found) + ") show as unavailable while it is down.")
        if info.get("ingress"):
            lines.append("Its panel in the sidebar will not open while it is down.")
    if action == "stop" and info.get("watchdog"):
        lines.append("Its watchdog does not restart an app you stopped yourself.")
    return lines
