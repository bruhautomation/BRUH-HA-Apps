"""A real Home Assistant for Morph's checks (docs/design/morph-on-lovelace.md §5).

Morph's cards, card types, view and layer run inside Home Assistant's own
frontend, and every other check of them is a stand-in for that page. This
starts the real thing: Home Assistant core and its frontend, the `demo`
integration for a house's worth of entities, Morph's frontend served from
`/local/morph/` and loaded on every page through `frontend.extra_module_url`
(exactly what the integration's `add_extra_js_url` does), an owner onboarded
by script, and a storage dashboard holding every Morph card kind.

    python tests/realha/ha_rig.py requirements  # the packages to install first
    python tests/realha/ha_rig.py up   <dir>   # configure, start, onboard; prints JSON
    python tests/realha/ha_rig.py down <dir>

`up` prints {"url", "token", "pid"} and leaves Home Assistant running; the
Playwright checks (`check-morph.mjs`) read it. It needs the `homeassistant`
package (and so `home-assistant-frontend`) in the interpreter that runs it.
"""
from __future__ import annotations

import asyncio
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "brain" / "custom_components" / "brain" / "morph" / "frontend"
CLIENT = "http://127.0.0.1:{port}/"

# What the checks need and no more: `default_config` brings in a dozen
# integrations (bluetooth, cloud, mobile_app…) whose packages Home Assistant
# installs at start, which a CI runner could not, and one that failed took
# `default_config` and the demo house with it. `requirements` prints what
# these need, from the installed release's own manifests.
INTEGRATIONS = ("config", "frontend", "history", "logbook", "person", "sun", "demo")
CONFIGURATION = "".join(f"{i}:\n" for i in INTEGRATIONS if i != "frontend") + """\
rig_eyes:
frontend:
  extra_module_url:
    - /local/morph/morph-ha.js
logger:
  default: warning
"""


# HA's own port: an `http:` block that moves it makes a new Home Assistant
# ask, in a dialog over every page, whether to keep the change.
PORT = 8123


def port_free(port: int) -> bool:
    with socket.socket() as s:
        try:
            s.bind(("127.0.0.1", port))
        except OSError:
            return False
        return True


# brAIn's eyes (custom_components/brain/morph/eyes.py) in a stand-in
# integration, against a stand-in for the dashboards half of
# morph/lovelace.py: the sign-in brAIn's screenshots use is Home
# Assistant's real auth, and that is what the checks drive.
EYES = ROOT / "brain" / "custom_components" / "brain" / "morph" / "eyes.py"
RIG_LOVELACE = '''
def dashboards(hass):
    data = hass.data.get("lovelace")
    found = getattr(data, "dashboards", None)
    if found is None and isinstance(data, dict):
        found = data.get("dashboards")  # a dict before 2025.2
    return found if isinstance(found, dict) else {}


def describe(hass):
    out = []
    for url, board in dashboards(hass).items():
        cfg = getattr(board, "config", None) or {}
        out.append({"key": url or "default", "url_path": url or "lovelace", "title": cfg.get("title") or url or "Overview",
                    "mode": str(getattr(board, "mode", "storage")), "morphed": False})
    return out


async def load_config(hass, key):
    board = dashboards(hass).get(None if key == "default" else key)
    try:
        return await board.async_load(False)
    except Exception:
        return None
'''
RIG_INIT = '''
from homeassistant.components import websocket_api
from .eyes import ws_eyes


async def async_setup(hass, config):
    websocket_api.async_register_command(hass, ws_eyes)
    return True
'''


def configure(cfg: Path, port: int) -> None:
    cfg.mkdir(parents=True, exist_ok=True)
    comp = cfg / "custom_components" / "rig_eyes"
    comp.mkdir(parents=True, exist_ok=True)
    (comp / "manifest.json").write_text(json.dumps({"domain": "rig_eyes", "name": "brAIn eyes (rig)", "version": "1.0.0",
                                                    "dependencies": ["lovelace", "websocket_api"], "codeowners": [],
                                                    "documentation": "https://example.invalid", "iot_class": "local_push"}))
    (comp / "__init__.py").write_text(RIG_INIT)
    (comp / "lovelace.py").write_text(RIG_LOVELACE)
    shutil.copyfile(EYES, comp / "eyes.py")
    (cfg / "configuration.yaml").write_text(CONFIGURATION)
    www = cfg / "www" / "morph"
    if www.exists():
        shutil.rmtree(www)
    shutil.copytree(FRONTEND, www)


async def wait_up(url: str, deadline: float) -> None:
    async with aiohttp.ClientSession() as s:
        while time.time() < deadline:
            try:
                async with s.get(url + "api/onboarding") as r:
                    if r.status in (200, 401, 404):
                        return
            except aiohttp.ClientError:
                pass  # not listening yet: asked again in a second
            await asyncio.sleep(1)
    raise SystemExit("Home Assistant did not answer in time")


async def wait_running(url: str, token: str, deadline: float) -> None:
    """Onboarding answers while integrations are still loading, and a page
    opened then shows "Loading data" for as long as that takes."""
    async with aiohttp.ClientSession() as s:
        while time.time() < deadline:
            try:
                async with s.get(url + "api/config", headers={"Authorization": f"Bearer {token}"}) as r:
                    if r.status == 200 and (await r.json()).get("state") == "RUNNING":
                        return
            except aiohttp.ClientError:
                pass  # still starting: asked again in two seconds
            await asyncio.sleep(2)
    raise SystemExit("Home Assistant did not finish starting in time")


async def onboard(url: str) -> str:
    client = url
    async with aiohttp.ClientSession() as s:
        async with s.post(url + "api/onboarding/users", json={
                "client_id": client, "name": "Owner", "username": "owner",
                "password": "morph-rig-password", "language": "en"}) as r:
            code = (await r.json())["auth_code"]
        async with s.post(url + "auth/token", data={
                "grant_type": "authorization_code", "code": code, "client_id": client}) as r:
            tok = await r.json()
        h = {"Authorization": f"Bearer {tok['access_token']}"}
        async with s.post(url + "api/onboarding/core_config", headers=h) as r:
            await r.read()
        async with s.post(url + "api/onboarding/analytics", headers=h) as r:
            await r.read()
        async with s.post(url + "api/onboarding/integration", headers=h,
                          json={"client_id": client, "redirect_uri": client + "?auth_callback=1"}) as r:
            await r.read()
        # A long-lived token, so the checks never meet an expiry.
        async with s.ws_connect(url + "api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": tok["access_token"]})
            await ws.receive_json()
            await ws.send_json({"id": 1, "type": "auth/long_lived_access_token",
                                "client_name": "morph-rig", "lifespan": 30})
            return (await ws.receive_json())["result"]


# A Morph dashboard of every kind, as dashboard.yaml would hold it, for the
# converter to turn into the Home Assistant dashboard the checks save.
MORPH_DASH = {
    "title": "Home", "theme": "dark", "scenes": [],
    "floors": [{"title": "Downstairs", "sections": [
        {"title": "Living room", "groups": [{"cards": [
            {"id": "a", "type": "light", "entity": "light.ceiling_lights", "span": 2, "options": {"header": False}},
            {"id": "b", "type": "light", "entity": "light.kitchen_lights", "icon": "mdi:ceiling-light",
             "options": {"detail": {"type": "history-graph", "entities": ["light.kitchen_lights"]}}},
            {"id": "c", "type": "switch", "entity": "switch.decorative_lights", "options": {"header": True}},
            {"id": "d", "type": "climate", "entity": "climate.hvac"},
            {"id": "e", "type": "media", "entity": "media_player.living_room"},
            {"id": "f", "type": "sensor", "entity": "sensor.outside_temperature"},
            {"id": "g", "type": "readings", "entities": ["sensor.outside_temperature", "sensor.outside_humidity"]},
        ]}]},
        {"title": "Hall", "groups": [{"label": "Doors", "cards": [
            {"id": "h", "type": "lock", "entity": "lock.front_door"},
            {"id": "i", "type": "cover", "entity": "cover.garage_door"},
            {"id": "j", "type": "list", "entities": ["binary_sensor.basement_floor_wet", "binary_sensor.movement_backyard"]},
            {"id": "k", "type": "camera", "entity": "camera.demo_camera"},
            {"id": "l", "type": "alarm", "entity": "alarm_control_panel.security"},
        ]}]},
        {"title": "Outside", "groups": [{"cards": [
            {"id": "m", "type": "weather", "entity": "weather.demo_weather_south"},
            {"id": "n", "type": "meter", "entity": "sensor.total_energy_kwh"},
            {"id": "o", "type": "fan", "entity": "fan.living_room_fan"},
            {"id": "p", "type": "vacuum", "entity": "vacuum.demo_vacuum_0_ground_floor"},
            {"id": "q", "type": "person", "entity": "person.owner"},
            {"id": "r", "type": "button", "entity": "button.push"},
            {"id": "s", "type": "entity", "entity": "sensor.carbon_dioxide"},
            {"id": "t", "type": "note", "text": "A note for the house."},
            {"id": "u", "type": "lovelace", "card": {"type": "tile", "entity": "light.bed_light"}},
        ]}]},
    ]}],
}


def fixtures(cfg: Path) -> None:
    """What the checks read besides Home Assistant: the converted Morph
    dashboard (convert.py, the real one) and the screenshot guard's script
    (screens.py's own text, so the check drives the code that ships)."""
    sys.path.insert(0, str(ROOT / "brain" / "morph" / "service"))
    import convert  # noqa: PLC0415 — pure: re only
    sys.path.pop(0)
    config, report = convert.to_lovelace(MORPH_DASH)
    (cfg / "converted.json").write_text(json.dumps({"config": config, "report": report}))
    text = (ROOT / "brain" / "panel" / "devloop" / "screens.py").read_text()
    guard = text.split('_HA_SOCKET_GUARD_JS = r"""', 1)[1].split('"""', 1)[0]
    (cfg / "guard.js").write_text(guard)


def up(cfg: Path) -> dict:
    port = PORT
    if not port_free(port):
        raise SystemExit(f"port {port} is taken: another Home Assistant is running")
    configure(cfg, port)
    url = CLIENT.format(port=port)
    # The child keeps its own copy of the descriptor after this one closes.
    with open(cfg / "rig.log", "w") as log:
        proc = subprocess.Popen([sys.executable, "-m", "homeassistant", "-c", str(cfg)],
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    asyncio.run(wait_up(url, time.time() + 600))
    token = asyncio.run(onboard(url))
    asyncio.run(wait_running(url, token, time.time() + 900))
    fixtures(cfg)
    out = {"url": url, "token": token, "pid": proc.pid, "config": str(cfg)}
    (cfg / "rig.json").write_text(json.dumps(out))
    return out


def down(cfg: Path) -> None:
    """Stop it, and wait until it has: the next `up` needs the port."""
    try:
        pid = json.loads((cfg / "rig.json").read_text())["pid"]
        os.killpg(pid, signal.SIGTERM)
    except (OSError, ValueError, KeyError):
        return
    deadline = time.time() + 90
    while time.time() < deadline:
        try:
            os.killpg(pid, 0)
        except OSError:
            break
        time.sleep(0.5)
    else:
        try:
            os.killpg(pid, signal.SIGKILL)
        except OSError:
            pass  # it exited between the last check and the kill
    while time.time() < deadline + 10 and not port_free(PORT):
        time.sleep(0.5)


def requirements() -> list[str]:
    """Every package the configured integrations need, with their
    dependencies', read off this release's manifests (stream for the demo
    camera, conversation's hassil for the demo, and so on)."""
    import importlib.util  # noqa: PLC0415

    comps = Path(importlib.util.find_spec("homeassistant").origin).parent / "components"
    seen: set[str] = set()
    out: list[str] = []
    todo = list(INTEGRATIONS) + ["stream", "camera", "lovelace", "onboarding", "auth", "http", "websocket_api"]
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        try:
            man = json.loads((comps / name / "manifest.json").read_text())
        except (OSError, ValueError):
            continue
        out += [r for r in man.get("requirements") or [] if r not in out]
        todo += list(man.get("dependencies") or []) + list(man.get("after_dependencies") or [])
    return out


if __name__ == "__main__":
    if sys.argv[1] == "requirements":
        print("\n".join(requirements()))
        sys.exit(0)
    cmd, where = sys.argv[1], Path(sys.argv[2])
    if cmd == "up":
        print(json.dumps(up(where)))
    else:
        down(where)
