"""ESPHome devices: their YAML, their builds, their firmware and their logs.

Three different things live behind the word "ESPHome", and this module keeps
them apart because each one is reachable by a different route and fails in a
different way:

* **The configurations** are YAML files in `/config/esphome`. brAIn maps
  `/config` read-write, so listing, reading, writing, creating and archiving
  them needs nothing else to be running. Every write and every delete is
  snapshotted into the edit journal first (`automation_writer.snapshot`), so
  `brain undo` puts a device file back exactly as it puts back a Claude edit —
  one journal, one reverter.

* **The builds** — validate, compile, install over the air, clean, logs — are
  the ESPHome *dashboard's* job. brAIn's image is Alpine, and the toolchains
  PlatformIO downloads are glibc binaries, so compiling here is not a thing
  that can be made to work; what the dashboard offers is a WebSocket per
  command (`{"type": "spawn", "configuration": …}` in, `{"event": "line"}`
  and `{"event": "exit", "code": n}` out), and that is what this drives.

* **The devices in Home Assistant** — which HA device a file is, what area it
  is in, whether its firmware `update` entity says an update is waiting — come
  from the registries, which is also how `protected_entities` reaches this:
  flashing a device that carries a protected entity is acting on that entity.

**Reaching the dashboard is the part that took reading rather than guessing.**
The ESPHome add-on runs on the host network and its ingress nginx allows only
the Supervisor and loopback (`allow 172.30.32.2; allow 127.0.0.1; deny all`),
so a request straight from this container to its ingress port is refused by
design. What the Supervisor *does* serve is its ingress proxy,
`/ingress/<token>/<path>`, which authenticates with an `ingress_session`
cookie — and a session is minted the way Home Assistant's own frontend mints
one: the Core WebSocket's `supervisor/api` command, `POST /ingress/session`.
Through that route the request arrives at the add-on from the Supervisor's
address, nginx lets it in and marks it as ingress, and the dashboard treats it
as authenticated. A dashboard that is not the add-on (a container on another
machine) is named by the `esphome_dashboard_url` option instead, and that is
tried first because a person who typed a URL meant it.

**Nothing that fails here fails silently.** A dashboard that cannot be reached
is a sentence naming what was tried; a file whose YAML does not parse is saved
(it is somebody's file, and a half-edited one is still worth keeping) with the
parser's own line number beside it; an install that would flash a device
carrying a protected entity is refused naming the entity; and a registry that
could not be read while the protected list is non-empty is a refusal too,
because "I could not tell" and "nothing is protected" are different claims.
"""
from __future__ import annotations

import asyncio
import base64
import collections
import json
import logging
import os
import re
import secrets as _secrets
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp
import yaml
from aiohttp import web

import automation_writer
import ha_data

log = logging.getLogger("brain.esphome")

ESPHOME_DIR = Path(os.environ.get("BRAIN_ESPHOME_DIR", "/config/esphome"))
SUPERVISOR_API = os.environ.get("BRAIN_SUPERVISOR_API", "http://supervisor")
SECRETS_FILE = "secrets.yaml"
# Where the dashboard itself puts a deleted configuration, so a file archived
# here and one archived there end up in the same place.
ARCHIVE_DIR = "archive"

# How long a discovered dashboard route is trusted before it is looked up
# again. The Supervisor expires an ingress session after fifteen minutes of
# not being validated, so this stays well inside that.
ROUTE_TTL_S = 600
# A command that says nothing for this long is assumed to have hung; a
# compile prints constantly, so silence this long is not a slow build.
QUIET_LIMIT_S = 900
# Logs are an open-ended stream; a tab left open must not hold a device's
# API connection for ever.
LOGS_MAX_S = 30 * 60
MAX_JOB_LINES = 6000
MAX_JOBS = 24
MAX_CONFIG_BYTES = 512 * 1024

# What the dashboard's WebSocket commands are called, and whether they take
# a port. `run` is compile-and-upload, which is what the dashboard's own
# INSTALL button sends.
COMMANDS = {
    "validate": {"path": "validate", "port": False, "label": "Validate"},
    "compile": {"path": "compile", "port": False, "label": "Compile"},
    "install": {"path": "run", "port": True, "label": "Install"},
    "upload": {"path": "upload", "port": True, "label": "Upload"},
    "logs": {"path": "logs", "port": True, "label": "Logs"},
    "clean": {"path": "clean", "port": False, "label": "Clean build files"},
}
# The commands that change a device, and so have to ask protected_entities.
# A compile or a validate changes nothing outside the dashboard's own build
# folder; an upload replaces the firmware the device runs.
FLASHING = {"install", "upload", "update"}

# Platforms a new device can be created for, with the board the dashboard's
# own wizard defaults to. The key is the YAML block's name.
PLATFORMS = {
    "esp32": {"label": "ESP32", "board": "esp32dev",
              "framework": "esp-idf"},
    "esp8266": {"label": "ESP8266", "board": "d1_mini"},
    "rp2040": {"label": "Raspberry Pi Pico W (RP2040)", "board": "rpipicow"},
    "bk72xx": {"label": "Beken BK72xx (LibreTiny)",
               "board": "generic-bk7231n-qfn32-tuya"},
    "rtl87xx": {"label": "Realtek RTL87xx (LibreTiny)",
                "board": "generic-rtl8710bn-2mb-788k"},
}
PLATFORM_KEYS = tuple(PLATFORMS) + ("ln882x", "nrf52", "host", "libretiny")

# A configuration is a filename in one folder and it arrives off the wire, so
# it is checked for shape here and for place in `config_path`.
CONFIG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,120}\.ya?ml\Z")
# ESPHome's own rule for a node name: it becomes a hostname.
NODE_NAME_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,29}[a-z0-9])?$")
SECRET_KEY_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_-]{0,63}$")
ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


# ---------------------------------------------------------------------------
# Reading ESPHome YAML without ESPHome
# ---------------------------------------------------------------------------

class _AnyTagLoader(yaml.SafeLoader):
    """SafeLoader that reads every custom tag as its plain value.

    ESPHome YAML is full of tags PyYAML has never heard of — `!secret`,
    `!lambda`, `!include`, `!extend`, `!remove` — and `safe_load` refuses the
    whole document at the first one. What this module needs from a file is
    its name, its platform and whether it parses at all, so a tag is read as
    the scalar, list or mapping it decorates; a `!secret` is kept visible as
    `!secret <key>` so nothing downstream mistakes it for a literal value.
    """


def _any_tag(loader, tag_suffix, node):  # noqa: ARG001 — PyYAML's signature
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
        return f"!{tag_suffix} {value}" if tag_suffix == "secret" else value
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    return loader.construct_mapping(node, deep=True)


_AnyTagLoader.add_multi_constructor("!", _any_tag)


def parse_yaml(text: str) -> tuple[Any, str]:
    """(document, "") or (None, the parser's own sentence with its line)."""
    try:
        return yaml.load(text, Loader=_AnyTagLoader), ""  # noqa: S506
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1}, column {mark.column + 1})" if mark else ""
        problem = getattr(exc, "problem", None) or str(exc).splitlines()[0]
        return None, f"{problem}{where}"


def _substitute(value: Any, subs: dict) -> Any:
    if not isinstance(value, str) or "$" not in value:
        return value
    out = value
    for key, sub in subs.items():
        out = out.replace("${" + key + "}", str(sub)).replace("$" + key, str(sub))
    return out


def describe(text: str) -> dict:
    """Name, friendly name, platform and board, read off one file.

    `substitutions` are applied to the two names because the dashboard's own
    wizard writes `name: ${name}` — without this every device made by it
    would be called `${name}`. Anything that cannot be read is left empty
    rather than guessed, and `error` says the file does not parse.
    """
    doc, error = parse_yaml(text)
    info = {"name": "", "friendly_name": "", "platform": "", "board": "",
            "comment": "", "error": error}
    if not isinstance(doc, dict):
        if not error and doc is not None:
            info["error"] = "the file is not a YAML mapping"
        return info
    subs = doc.get("substitutions") if isinstance(doc.get("substitutions"), dict) else {}
    core = doc.get("esphome") if isinstance(doc.get("esphome"), dict) else {}
    info["name"] = str(_substitute(core.get("name") or "", subs) or "")
    info["friendly_name"] = str(_substitute(core.get("friendly_name") or "", subs) or "")
    info["comment"] = str(_substitute(core.get("comment") or "", subs) or "")
    for key in PLATFORM_KEYS:
        if key in doc:
            info["platform"] = key
            block = doc.get(key)
            if isinstance(block, dict):
                info["board"] = str(_substitute(block.get("board") or "", subs) or "")
            break
    else:
        # The pre-2022 spelling: `esphome: platform: ESP32`.
        legacy = str(core.get("platform") or "").lower()
        if legacy:
            info["platform"] = legacy
            info["board"] = str(core.get("board") or "")
    return info


# ---------------------------------------------------------------------------
# The files
# ---------------------------------------------------------------------------

def _root() -> str:
    return os.path.realpath(str(ESPHOME_DIR))


def config_path(configuration: str) -> Path | None:
    """The file a configuration name means, or None when it is not one.

    Checked twice on purpose, `chat_session.transcript_path`'s arrangement:
    once for shape (`CONFIG_RE` — no slash, no leading dot) and once for
    place, spelled with `normpath` and a string prefix because that is the
    form a static analyser reads as a barrier. The second is unreachable
    past the first and is kept because a guard nothing can see is a guard
    somebody deletes.
    """
    name = str(configuration or "").strip()
    if not CONFIG_RE.match(name) or name.startswith("."):
        return None
    root = _root()
    full = os.path.normpath(os.path.join(root, name))
    if not full.startswith(root.rstrip(os.sep) + os.sep):
        return None
    return Path(full)


def _is_device_file(path: Path) -> bool:
    return (path.is_file() and CONFIG_RE.match(path.name) is not None
            and path.name != SECRETS_FILE and not path.name.startswith("."))


def list_configs() -> list[dict]:
    """Every device file in the folder, read for what it is."""
    if not ESPHOME_DIR.is_dir():
        return []
    rows = []
    for path in sorted(ESPHOME_DIR.iterdir(), key=lambda p: p.name.lower()):
        if not _is_device_file(path):
            continue
        try:
            stat = path.stat()
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            rows.append({"configuration": path.name, "error": str(exc)})
            continue
        info = describe(text)
        # A file whose YAML does not parse carries no `esphome:` block,
        # which usually means it is a package or an include that other
        # files pull in rather than a device. Both are listed; only one
        # is marked as a device.
        rows.append({"configuration": path.name, **info,
                     "is_device": bool(info["name"]) or bool(info["error"]),
                     "mtime": stat.st_mtime, "size": stat.st_size})
    return rows


def read_config(configuration: str) -> dict:
    path = config_path(configuration)
    if path is None:
        return {"ok": False, "error": f"{configuration!r} is not a configuration "
                                      "file name (letters, digits, - _ . and "
                                      "ending .yaml)"}
    if not path.is_file():
        return {"ok": False, "missing": True,
                "error": f"there is no {path.name} in {ESPHOME_DIR}"}
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": f"brAIn could not read {path.name}: {exc}"}
    return {"ok": True, "configuration": path.name, "content": text,
            "mtime": path.stat().st_mtime, **describe(text)}


def write_config(configuration: str, content: str, *,
                 expect_mtime: float | None = None,
                 create: bool = False) -> dict:
    """Save a configuration, snapshotting what was there first.

    `expect_mtime` is the stamp the editor read the file at: a file that has
    changed since — somebody saved it in the ESPHome dashboard meanwhile —
    is refused rather than overwritten, because the one edit that silently
    loses somebody's work is the one that wins a race nobody could see.
    A file that does not parse is still saved, and says so.
    """
    path = config_path(configuration)
    if path is None:
        return {"ok": False, "error": f"{configuration!r} is not a configuration "
                                      "file name"}
    if not isinstance(content, str):
        return {"ok": False, "error": "content must be the file's text"}
    data = content.encode("utf-8")
    if len(data) > MAX_CONFIG_BYTES:
        return {"ok": False, "error": "that file is larger than brAIn will "
                                      f"write ({MAX_CONFIG_BYTES // 1024} KB)"}
    exists = path.is_file()
    if create and exists:
        return {"ok": False, "conflict": True,
                "error": f"{path.name} already exists — open it instead"}
    if not create and not exists and expect_mtime is not None:
        return {"ok": False, "conflict": True,
                "error": f"{path.name} has been deleted since you opened it"}
    if exists and expect_mtime is not None:
        try:
            current = path.stat().st_mtime
        except OSError:
            current = None
        if current is not None and abs(current - float(expect_mtime)) > 1e-3:
            return {"ok": False, "conflict": True,
                    "error": f"{path.name} changed on disk after you opened it "
                             "(saved from the ESPHome dashboard?). Reload it "
                             "before saving, or your edit would replace that one."}
    try:
        ESPHOME_DIR.mkdir(parents=True, exist_ok=True)
        journalled = automation_writer.snapshot(path)
    except OSError as exc:
        return {"ok": False, "error": f"brAIn could not snapshot {path.name} "
                                      f"before writing it, so it did not: {exc}"}
    try:
        _write_text(path, content)
    except OSError as exc:
        return {"ok": False, "error": f"brAIn could not write {path.name}: {exc}"}
    info = describe(content)
    out = {"ok": True, "configuration": path.name, "created": not exists,
           "mtime": path.stat().st_mtime, "journal_ts": journalled["ts"], **info}
    if info["error"]:
        out["warning"] = (f"Saved, but the YAML does not parse: {info['error']}. "
                          "ESPHome will refuse it until that is fixed.")
    return out


def _write_text(path: Path, text: str) -> None:
    """tmp + rename in the target's own folder, keeping mode and owner."""
    import atomic_write
    atomic_write.write_text(path, text)


def archive_config(configuration: str) -> dict:
    """Move a device file into `archive/`, the folder the dashboard uses.

    A move rather than a delete, and snapshotted as well, so both the
    dashboard's own habit and `brain undo` can bring it back.
    """
    path = config_path(configuration)
    if path is None or not path.is_file():
        return {"ok": False, "missing": True,
                "error": f"there is no {configuration} to delete"}
    if path.name == SECRETS_FILE:
        return {"ok": False, "error": "secrets.yaml is not a device"}
    archive = ESPHOME_DIR / ARCHIVE_DIR
    try:
        automation_writer.snapshot(path)
        archive.mkdir(parents=True, exist_ok=True)
        target = archive / path.name
        n = 1
        while target.exists():
            target = archive / f"{path.stem}-{n}{path.suffix}"
            n += 1
        shutil.move(str(path), str(target))
    except OSError as exc:
        return {"ok": False, "error": f"brAIn could not archive {path.name}: {exc}"}
    return {"ok": True, "configuration": path.name,
            "archived_to": str(target.relative_to(ESPHOME_DIR))}


def _key_b64() -> str:
    return base64.b64encode(_secrets.token_bytes(32)).decode("ascii")


def new_config_text(name: str, friendly_name: str, platform: str,
                    board: str = "") -> str:
    """The file the dashboard's wizard would write, and nothing more.

    Fresh credentials per device (an API encryption key, an OTA password and
    a fallback hotspot password), because a device made from a template that
    shared them with every other device is a house with one key for every
    door. Wi-Fi comes from `secrets.yaml`, which is the ESPHome convention
    and the one place the network password is kept.
    """
    spec = PLATFORMS[platform]
    board = board or spec["board"]
    ap_ssid = (friendly_name or name).replace('"', "")[:24] + " Fallback"
    lines = [
        "substitutions:",
        f"  name: {name}",
        f"  friendly_name: {json.dumps(friendly_name or name)}",
        "",
        "esphome:",
        "  name: ${name}",
        "  friendly_name: ${friendly_name}",
        "",
        f"{platform}:",
        f"  board: {board}",
    ]
    if spec.get("framework"):
        lines += ["  framework:", f"    type: {spec['framework']}"]
    lines += [
        "",
        "# Logging over the network and the serial port.",
        "logger:",
        "",
        "# The Home Assistant API, encrypted with a key made for this device.",
        "api:",
        "  encryption:",
        f'    key: "{_key_b64()}"',
        "",
        "ota:",
        "  - platform: esphome",
        f'    password: "{_secrets.token_hex(16)}"',
        "",
        "wifi:",
        "  ssid: !secret wifi_ssid",
        "  password: !secret wifi_password",
        "  # If Wi-Fi fails, the device opens its own hotspot to fix it from.",
        "  ap:",
        f"    ssid: {json.dumps(ap_ssid)}",
        f'    password: "{_secrets.token_hex(6)}"',
        "",
        "captive_portal:",
        "",
    ]
    return "\n".join(lines)


def create_config(name: str, friendly_name: str = "", platform: str = "esp32",
                  board: str = "") -> dict:
    name = str(name or "").strip().lower()
    if not NODE_NAME_RE.match(name):
        return {"ok": False, "error": "a device name is lowercase letters, "
                                      "digits and hyphens, up to 31 characters, "
                                      "and cannot start or end with a hyphen — "
                                      "it becomes the device's hostname"}
    if platform not in PLATFORMS:
        return {"ok": False, "error": f"brAIn can start a {', '.join(PLATFORMS)} "
                                      f"device; {platform!r} is not one of them"}
    board = str(board or "").strip()
    if board and not re.match(r"^[A-Za-z0-9_.+-]{1,60}$", board):
        return {"ok": False, "error": "that board id has characters no "
                                      "PlatformIO board has"}
    text = new_config_text(name, str(friendly_name or "").strip()[:60],
                           platform, board)
    result = write_config(f"{name}.yaml", text, create=True)
    if result.get("ok"):
        missing = [k for k in ("wifi_ssid", "wifi_password")
                   if k not in secret_keys()]
        if missing:
            result["warning"] = ("secrets.yaml has no " + " or ".join(missing)
                                 + " yet — set them before the first install, "
                                 "or the build will stop at the Wi-Fi block.")
    return result


# ---------------------------------------------------------------------------
# secrets.yaml — keys readable, values write-only
# ---------------------------------------------------------------------------

def _secrets_path() -> Path:
    return ESPHOME_DIR / SECRETS_FILE


def secret_keys() -> list[str]:
    """The names in secrets.yaml, never the values.

    The values are Wi-Fi passwords and API keys, and nothing in the panel
    or any tool needs to show one to be useful: the editor needs to know a
    `!secret wifi_ssid` resolves, not what it resolves to.
    """
    path = _secrets_path()
    try:
        doc, _ = parse_yaml(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return []
    return sorted(str(k) for k in doc) if isinstance(doc, dict) else []


def set_secret(key: str, value: str) -> dict:
    """Set one secret, touching only its own line.

    A top-level `key: value` line is replaced in place, and a new key is
    appended; the rest of the file keeps its bytes and its comments. A key
    whose value spans several lines is refused rather than half-replaced.
    The value is written as a JSON string, which is a valid YAML
    double-quoted scalar for every character a password can hold.
    """
    key = str(key or "").strip()
    if not SECRET_KEY_RE.match(key):
        return {"ok": False, "error": "a secret's name is letters, digits, "
                                      "_ and -"}
    if not isinstance(value, str) or "\n" in value or len(value) > 512:
        return {"ok": False, "error": "a secret is one line of up to 512 "
                                      "characters"}
    path = _secrets_path()
    try:
        text = path.read_text(encoding="utf-8") if path.is_file() else ""
    except (OSError, UnicodeDecodeError) as exc:
        return {"ok": False, "error": f"brAIn could not read secrets.yaml: {exc}"}
    line = f"{key}: {json.dumps(value)}"
    pattern = re.compile(rf"^{re.escape(key)}[ \t]*:(.*)$", re.MULTILINE)
    match = pattern.search(text)
    if match:
        rest = match.group(1).strip()
        if rest in ("", "|", ">", "|-", ">-") or rest.startswith(("|", ">")):
            return {"ok": False, "error": f"{key} spans several lines in "
                                          "secrets.yaml — edit that one by hand"}
        new_text = text[:match.start()] + line + text[match.end():]
    else:
        sep = "" if not text or text.endswith("\n") else "\n"
        new_text = f"{text}{sep}{line}\n"
    doc, error = parse_yaml(new_text)
    if error or not isinstance(doc, dict) or doc.get(key) != value:
        return {"ok": False, "error": "brAIn could not set that without "
                                      "breaking secrets.yaml"
                                      + (f" ({error})" if error else "")}
    try:
        ESPHOME_DIR.mkdir(parents=True, exist_ok=True)
        automation_writer.snapshot(path)
        _write_text(path, new_text)
    except OSError as exc:
        return {"ok": False, "error": f"brAIn could not write secrets.yaml: {exc}"}
    return {"ok": True, "key": key, "replaced": bool(match)}


# ---------------------------------------------------------------------------
# The dashboard
# ---------------------------------------------------------------------------

class Route:
    """How to reach one dashboard: a base URL, and the cookie it wants."""

    def __init__(self, base: str, via: str, cookies: dict | None = None,
                 addon: dict | None = None):
        self.base = base.rstrip("/")
        self.via = via
        self.cookies = cookies or {}
        self.addon = addon or {}
        self.made = time.time()

    def url(self, path: str) -> str:
        return f"{self.base}/{path.lstrip('/')}"

    def ws_url(self, path: str) -> str:
        url = self.url(path)
        if url.startswith("https://"):
            return "wss://" + url[len("https://"):]
        if url.startswith("http://"):
            return "ws://" + url[len("http://"):]
        return url

    def headers(self) -> dict:
        if not self.cookies:
            return {}
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cookies.items())}


_ROUTE: dict[str, Any] = {"route": None, "status": None, "at": 0.0}
_ROUTE_LOCK: asyncio.Lock | None = None


def _lock() -> asyncio.Lock:
    global _ROUTE_LOCK
    if _ROUTE_LOCK is None:
        _ROUTE_LOCK = asyncio.Lock()
    return _ROUTE_LOCK


def dashboard_url_option() -> str:
    return os.environ.get("BRAIN_ESPHOME_DASHBOARD_URL", "").strip()


async def _supervisor_get(session: aiohttp.ClientSession, path: str) -> Any:
    async with session.get(
            f"{SUPERVISOR_API}{path}",
            headers={"Authorization": f"Bearer {ha_data.SUPERVISOR_TOKEN}"},
            timeout=aiohttp.ClientTimeout(total=15)) as resp:
        resp.raise_for_status()
        body = await resp.json(content_type=None)
    return body.get("data") if isinstance(body, dict) else None


def pick_addon(addons: list) -> dict | None:
    """The ESPHome add-on, when the store has more than one.

    The official one is `5c53de3b_esphome`, with `_beta` and `_dev` twins,
    and a community repository may publish its own; all end in `esphome`
    once the channel suffix is off. A running one beats a stopped one, and
    the stable channel beats beta beats dev, so a house that installed the
    beta to test something and left it stopped is not driven through it.
    """
    rows = []
    for row in addons or []:
        if not isinstance(row, dict):
            continue
        slug = str(row.get("slug") or "")
        base = re.sub(r"[-_](beta|dev)$", "", slug)
        if not base.endswith("esphome"):
            continue
        channel = 0 if base == slug else (1 if slug.endswith("beta") else 2)
        running = 0 if row.get("state") == "started" else 1
        rows.append((running, channel, slug, row))
    rows.sort(key=lambda r: r[:3])
    return rows[0][3] if rows else None


async def _ingress_session(session: aiohttp.ClientSession) -> str:
    """An ingress session, minted the way Home Assistant's frontend does.

    The Supervisor only creates sessions for Home Assistant, so the request
    goes through Core's `supervisor/api` WebSocket command, which the
    Supervisor user is admin enough to call. The direct Supervisor call is
    tried second, for a Supervisor that has started accepting add-ons there.
    """
    calls = await ha_data._ws_calls(session, [{
        "type": "supervisor/api", "endpoint": "/ingress/session",
        "method": "post"}])
    first = calls[0] if calls else {}
    result = first.get("result") if first.get("ok") else None
    if isinstance(result, dict) and result.get("session"):
        return str(result["session"])
    try:
        async with session.post(
                f"{SUPERVISOR_API}/ingress/session",
                headers={"Authorization": f"Bearer {ha_data.SUPERVISOR_TOKEN}"},
                timeout=aiohttp.ClientTimeout(total=15)) as resp:
            body = await resp.json(content_type=None)
        data = body.get("data") if isinstance(body, dict) else None
        if isinstance(data, dict) and data.get("session"):
            return str(data["session"])
    except (aiohttp.ClientError, asyncio.TimeoutError, ValueError):  # the fallback
        pass  # failing too is the refusal below, which names Core's answer
    raise RuntimeError("Home Assistant would not open an ingress session "
                       f"({first.get('error') or 'no session in the answer'})")


async def _probe(session: aiohttp.ClientSession, route: Route) -> str:
    """The dashboard's version, or raise saying what answered instead."""
    for path in ("version", "devices"):
        async with session.get(route.url(path), headers=route.headers(),
                               timeout=aiohttp.ClientTimeout(total=15),
                               allow_redirects=False) as resp:
            if resp.status == 404 and path == "version":
                continue
            if resp.status in (401, 403):
                raise RuntimeError(f"the dashboard refused brAIn (HTTP {resp.status})")
            if resp.status in (301, 302, 303):
                raise RuntimeError("the dashboard asked for a login — "
                                   "brAIn cannot sign in to it with a password")
            if resp.status != 200:
                raise RuntimeError(f"it answered HTTP {resp.status}")
            try:
                body = await resp.json(content_type=None)
            except (ValueError, aiohttp.ContentTypeError):
                raise RuntimeError("it answered, but not like an ESPHome "
                                   "dashboard") from None
            if path == "version":
                return str((body or {}).get("version") or "")
            if isinstance(body, dict) and "configured" in body:
                return ""
            raise RuntimeError("it answered, but not like an ESPHome dashboard")
    raise RuntimeError("no dashboard answered")


async def discover(session: aiohttp.ClientSession) -> tuple[Route | None, dict]:
    """Find a dashboard this panel can drive, and say how or why not."""
    tried: list[str] = []
    option = dashboard_url_option()
    if option:
        route = Route(option, "option")
        try:
            version = await _probe(session, route)
            return route, {"reachable": True, "via": "option",
                           "url": option, "version": version}
        except Exception as exc:  # noqa: BLE001 — every failure is a sentence
            tried.append(f"{option} (the esphome_dashboard_url option): {exc}")

    addon = None
    if ha_data.SUPERVISOR_TOKEN:
        try:
            listing = await _supervisor_get(session, "/addons")
            addon = pick_addon((listing or {}).get("addons") or [])
        except Exception as exc:  # noqa: BLE001
            tried.append(f"the Supervisor's add-on list: {exc}")
    if addon is not None:
        slug = str(addon.get("slug"))
        info: dict = {}
        try:
            info = await _supervisor_get(session, f"/addons/{slug}/info") or {}
        except Exception as exc:  # noqa: BLE001
            tried.append(f"the {slug} add-on's info: {exc}")
        described = {"slug": slug, "name": addon.get("name") or "ESPHome",
                     "state": info.get("state") or addon.get("state"),
                     "version": info.get("version") or addon.get("version"),
                     "update_available": bool(info.get("update_available")
                                              or addon.get("update_available"))}
        entry = str(info.get("ingress_entry") or "")
        token = entry.rstrip("/").rsplit("/", 1)[-1] if entry else ""
        if described["state"] != "started":
            tried.append(f"the {described['name']} add-on is "
                         f"{described['state'] or 'not running'} — start it")
        elif not token:
            tried.append(f"the {described['name']} add-on has no ingress entry")
        else:
            try:
                ingress = await _ingress_session(session)
                route = Route(f"{SUPERVISOR_API}/ingress/{token}", "ingress",
                              {"ingress_session": ingress}, described)
                version = await _probe(session, route)
                return route, {"reachable": True, "via": "ingress",
                               "addon": described, "version": version}
            except Exception as exc:  # noqa: BLE001
                tried.append(f"the {described['name']} add-on through "
                             f"Home Assistant ingress: {exc}")
        status = {"reachable": False, "addon": described}
    else:
        status = {"reachable": False, "addon": None}
        if ha_data.SUPERVISOR_TOKEN and not tried:
            tried.append("no ESPHome add-on is installed")
    if not ha_data.SUPERVISOR_TOKEN and not option:
        tried.append("there is no Supervisor to ask (not running as an add-on)")
    status["reason"] = ("brAIn could not reach an ESPHome dashboard: "
                        + "; ".join(tried) + ". Editing files still works; "
                        "building and installing needs the dashboard — install "
                        "and start the ESPHome add-on, or set "
                        "esphome_dashboard_url to a dashboard on your network.")
    return None, status


async def route(session: aiohttp.ClientSession, *, fresh: bool = False
                ) -> tuple[Route | None, dict]:
    """The cached route, re-discovered when stale or asked to."""
    async with _lock():
        now = time.time()
        if (not fresh and _ROUTE["status"] is not None
                and now - _ROUTE["at"] < (ROUTE_TTL_S if _ROUTE["route"] else 60)):
            return _ROUTE["route"], _ROUTE["status"]
        found, status = await discover(session)
        _ROUTE.update(route=found, status=status, at=now)
        return found, status


def forget_route() -> None:
    _ROUTE.update(route=None, status=None, at=0.0)


async def dashboard_json(session: aiohttp.ClientSession, path: str) -> Any:
    """GET one JSON endpoint on the dashboard, re-routing once on a 401."""
    for attempt in (0, 1):
        found, status = await route(session, fresh=bool(attempt))
        if found is None:
            raise RuntimeError(status.get("reason") or "no dashboard")
        async with session.get(found.url(path), headers=found.headers(),
                               timeout=aiohttp.ClientTimeout(total=20),
                               allow_redirects=False) as resp:
            if resp.status in (401, 403) and not attempt:
                forget_route()
                continue
            resp.raise_for_status()
            return await resp.json(content_type=None)
    raise RuntimeError("the dashboard refused brAIn twice")


# ---------------------------------------------------------------------------
# Home Assistant's side: which device a file is, and what it carries
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


async def ha_devices(session: aiohttp.ClientSession) -> dict:
    """ESPHome devices in the registries, with their entities and updates.

    `{"ok": bool, "error": str, "devices": [{id, name, area_id, entities,
    update_entity}]}` — `ok: False` is "I could not look", which the
    protected check must not read as "there is nothing here".
    """
    try:
        devices, entities = await ha_data._ws_commands(session, [
            {"type": "config/device_registry/list"},
            {"type": "config/entity_registry/list"},
        ])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "devices": []}
    if not isinstance(devices, list) or not isinstance(entities, list):
        return {"ok": False, "error": "Home Assistant did not return its "
                                      "registries", "devices": []}
    by_device: dict[str, list[str]] = collections.defaultdict(list)
    for row in entities:
        if isinstance(row, dict) and row.get("platform") == "esphome" \
                and row.get("device_id"):
            by_device[row["device_id"]].append(str(row.get("entity_id") or ""))
    out = []
    for dev in devices:
        if not isinstance(dev, dict) or dev.get("id") not in by_device:
            continue
        ids = sorted(by_device[dev["id"]])
        update = next((e for e in ids if e.startswith("update.")), "")
        out.append({"id": dev["id"], "name": dev.get("name") or "",
                    "name_by_user": dev.get("name_by_user") or "",
                    "area_id": dev.get("area_id") or "",
                    "sw_version": dev.get("sw_version") or "",
                    "entities": ids, "update_entity": update})
    return {"ok": True, "error": "", "devices": out}


def match_device(info: dict, devices: list[dict]) -> dict | None:
    """The HA device a configuration is, by its node or friendly name.

    ESPHome registers a device under its friendly name when it has one and
    its node name otherwise, and a person's rename lands in `name_by_user`
    without touching either — so the file's two names are compared against
    the registry's own `name`, normalised, and never against the rename.
    """
    wanted = {_norm(info.get("name")), _norm(info.get("friendly_name"))} - {""}
    if not wanted:
        return None
    for dev in devices:
        if _norm(dev.get("name")) in wanted:
            return dev
    return None


async def protected_refusal(session: aiohttp.ClientSession,
                            info: dict) -> str | None:
    """Why this device may not be flashed, or None.

    A device that is not in Home Assistant at all carries no entities and
    so nothing protected — that is a real answer. A registry that could not
    be read is not one, and while the list is non-empty it refuses.
    """
    patterns = automation_writer.protected_patterns()
    if not patterns:
        return None
    ha = await ha_devices(session)
    if not ha["ok"]:
        return ("brAIn could not read Home Assistant's device registry "
                f"({ha['error']}), so it cannot tell whether this device "
                "carries a protected entity — and protected_entities is set, "
                "so it will not flash it")
    dev = match_device(info, ha["devices"])
    if dev is None:
        return None
    hit = [e for e in dev["entities"]
           if automation_writer.is_protected(e, patterns)]
    if hit:
        return (f"{info.get('friendly_name') or info.get('name')} carries "
                f"{', '.join(hit[:4])}, which protected_entities covers — "
                "brAIn will not replace its firmware. Install it from the "
                "ESPHome dashboard yourself, or take it off that list.")
    return None


# ---------------------------------------------------------------------------
# Jobs: a command's output, kept where a poll can read it
# ---------------------------------------------------------------------------

class Job:
    def __init__(self, kind: str, configuration: str, via: str):
        self.id = uuid.uuid4().hex[:12]
        self.kind = kind
        self.configuration = configuration
        self.via = via
        self.started = time.time()
        self.ended: float | None = None
        self.state = "running"
        self.exit_code: int | None = None
        self.error = ""
        self.lines: collections.deque[str] = collections.deque(maxlen=MAX_JOB_LINES)
        self.dropped = 0
        self.task: asyncio.Task | None = None
        self.stop_requested = False
        self.heard = time.monotonic()

    def add(self, text: str) -> None:
        for line in ANSI_RE.sub("", str(text)).replace("\r\n", "\n").split("\n"):
            line = line.rstrip("\r")
            if not line and self.lines and not self.lines[-1]:
                continue
            if len(self.lines) == self.lines.maxlen:
                self.dropped += 1
            self.lines.append(line)

    def finish(self, state: str, exit_code: int | None = None,
               error: str = "") -> None:
        if self.ended is not None:
            return
        self.state, self.exit_code, self.error = state, exit_code, error
        self.ended = time.time()

    def as_dict(self, since: int = 0) -> dict:
        total = self.dropped + len(self.lines)
        start = max(0, int(since) - self.dropped)
        return {"id": self.id, "kind": self.kind,
                "label": COMMANDS.get(self.kind, {}).get("label")
                or ("Update firmware" if self.kind == "update" else self.kind),
                "configuration": self.configuration, "via": self.via,
                "state": self.state, "exit_code": self.exit_code,
                "error": self.error, "started": self.started,
                "ended": self.ended, "total": total,
                "lines": list(self.lines)[start:]}


JOBS: "collections.OrderedDict[str, Job]" = collections.OrderedDict()


def _remember(job: Job) -> None:
    JOBS[job.id] = job
    while len(JOBS) > MAX_JOBS:
        oldest = next((j for j in JOBS.values() if j.state != "running"), None)
        if oldest is None:
            break
        JOBS.pop(oldest.id, None)


def running_for(configuration: str) -> Job | None:
    return next((j for j in JOBS.values()
                 if j.configuration == configuration and j.state == "running"),
                None)


async def _run_ws(job: Job, route_: Route, spec: dict, port: str) -> None:
    """Drive one dashboard WebSocket command until it exits."""
    payload = {"type": "spawn", "configuration": job.configuration}
    if spec["port"]:
        payload["port"] = port or "OTA"
    limit = LOGS_MAX_S if job.kind == "logs" else None
    deadline = time.monotonic() + limit if limit else None
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(route_.ws_url(spec["path"]),
                                      headers=route_.headers(),
                                      heartbeat=30) as ws:
            await ws.send_json(payload)
            while True:
                if job.stop_requested:
                    job.add("— stopped by request —")
                    job.finish("stopped")
                    return
                if deadline is not None and time.monotonic() >= deadline:
                    job.add(f"— log stream closed after {LOGS_MAX_S // 60} minutes —")
                    job.finish("stopped")
                    return
                try:
                    # One second at a time, so a stop press is noticed
                    # within a second whatever the command is doing.
                    msg = await asyncio.wait_for(ws.receive(), timeout=1.0)
                except asyncio.TimeoutError:
                    if time.monotonic() - job.heard > QUIET_LIMIT_S:
                        job.finish("failed", error="the dashboard went quiet for "
                                   f"{QUIET_LIMIT_S // 60} minutes")
                        return
                    continue
                if msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSE,
                                aiohttp.WSMsgType.CLOSING, aiohttp.WSMsgType.ERROR):
                    if job.kind == "logs":
                        job.finish("stopped")
                    else:
                        job.finish("failed", error="the dashboard closed the "
                                   "connection before the command finished")
                    return
                if msg.type != aiohttp.WSMsgType.TEXT:
                    continue
                job.heard = time.monotonic()
                try:
                    data = json.loads(msg.data)
                except ValueError:
                    job.add(msg.data)
                    continue
                event = data.get("event")
                if event == "line":
                    job.add(data.get("data") or "")
                elif event == "exit":
                    code = data.get("code")
                    code = int(code) if isinstance(code, (int, float)) else None
                    job.finish("succeeded" if code == 0 else "failed", code,
                               "" if code == 0 else
                               f"{COMMANDS[job.kind]['label']} ended with exit "
                               f"code {code}")
                    return


async def _run_job(job: Job, route_: Route, spec: dict, port: str) -> None:
    job.heard = time.monotonic()
    try:
        await _run_ws(job, route_, spec, port)
    except asyncio.CancelledError:
        job.finish("stopped")
        raise
    except Exception as exc:  # noqa: BLE001 — a job reports; it never raises
        forget_route()
        job.finish("failed", error=f"the dashboard connection failed: {exc}")
    finally:
        job.finish("failed", error="the command ended without an exit code")
        # The file name passed `CONFIG_RE` already; flattened again here
        # with literal replaces, `server.log_safe`'s barrier, because a
        # log line is evidence only while every line in it is ours.
        name = job.configuration.replace("\r", " ").replace("\n", " ")
        log.info("esphome %s %s: %s", job.kind, name[:128], job.state)


async def _run_update(job: Job, entity_id: str) -> None:
    """Firmware through Home Assistant's own `update.install`.

    For the house whose dashboard this panel cannot reach but Home
    Assistant can: Core's ESPHome integration is linked to the add-on and
    compiles-and-uploads on `update.install`. Core's REST call returns
    within ten seconds and the install goes on, so progress is read off
    the entity's own `in_progress` until it settles.
    """
    job.heard = time.monotonic()
    try:
        job.add(f"Asking Home Assistant to install the update on {entity_id}…")
        await ha_data.call_core_service("update", "install",
                                        {"entity_id": entity_id}, timeout=30)
        deadline = time.monotonic() + 40 * 60
        seen_progress = False
        while time.monotonic() < deadline:
            if job.stop_requested:
                job.add("— stopped watching; the install goes on in Home Assistant —")
                job.finish("stopped")
                return
            state = await ha_data.entity_state(entity_id) or {}
            attrs = state.get("attributes") or {}
            progress = attrs.get("in_progress")
            if progress:
                seen_progress = True
                pct = attrs.get("update_percentage")
                job.add(f"Installing{f' ({pct}%)' if isinstance(pct, (int, float)) else ''}…")
            elif seen_progress or state.get("state") == "off":
                if state.get("state") == "off":
                    job.add(f"Installed {attrs.get('installed_version') or ''}".strip())
                    job.finish("succeeded", 0)
                else:
                    job.finish("failed", 1, "Home Assistant finished, but the "
                               "entity still reports an update waiting — see "
                               "Home Assistant's log for the build output")
                return
            await asyncio.sleep(5)
        job.finish("failed", error="the install did not settle within 40 minutes")
    except asyncio.CancelledError:
        job.finish("stopped")
        raise
    except Exception as exc:  # noqa: BLE001
        job.finish("failed", error=f"Home Assistant refused the install: {exc}")


async def start(kind: str, configuration: str, *, port: str = "OTA") -> dict:
    """Start a command for one configuration; the answer is a job to poll."""
    if kind not in COMMANDS and kind != "update":
        return {"ok": False, "error": f"{kind!r} is not something brAIn can "
                                      "ask ESPHome to do"}
    path = config_path(configuration)
    if path is None or not path.is_file():
        return {"ok": False, "missing": True,
                "error": f"there is no {configuration} in {ESPHOME_DIR}"}
    busy = running_for(path.name)
    if busy is not None:
        return {"ok": False, "conflict": True, "job": busy.as_dict(),
                "error": f"{busy.as_dict()['label']} is already running for "
                         f"{path.name} — stop it or wait for it"}
    port = str(port or "OTA").strip()
    if not re.match(r"^[A-Za-z0-9_./:-]{1,64}$", port):
        return {"ok": False, "error": "that is not a device address or port"}
    info = describe(path.read_text(encoding="utf-8", errors="replace"))
    async with aiohttp.ClientSession() as session:
        if kind in FLASHING:
            refusal = await protected_refusal(session, info)
            if refusal:
                return {"ok": False, "refused": True, "error": refusal}
        if kind == "update":
            ha = await ha_devices(session)
            dev = match_device(info, ha["devices"]) if ha["ok"] else None
            entity = dev["update_entity"] if dev else ""
            if not entity:
                return {"ok": False, "error": "Home Assistant has no firmware "
                        "update entity for this device (it appears once the "
                        "ESPHome integration is linked to the dashboard)"}
            state = await ha_data.entity_state(entity) or {}
            if state.get("state") != "on":
                return {"ok": False, "error": f"{entity} says the firmware is "
                        "up to date, and Home Assistant only installs an "
                        "update that is waiting — use Install instead"}
            job = Job(kind, path.name, "home_assistant")
            _remember(job)
            job.task = asyncio.create_task(_run_update(job, entity))
            return {"ok": True, "job": job.as_dict()}
        found, status = await route(session)
    if found is None:
        return {"ok": False, "unreachable": True, "error": status.get("reason")}
    job = Job(kind, path.name, found.via)
    _remember(job)
    job.task = asyncio.create_task(_run_job(job, found, COMMANDS[kind], port))
    return {"ok": True, "job": job.as_dict()}


def stop(job_id: str) -> dict:
    job = JOBS.get(str(job_id or ""))
    if job is None:
        return {"ok": False, "missing": True, "error": "no such job"}
    if job.state == "running":
        job.stop_requested = True
        # Closing the socket is what tells the dashboard to kill the
        # process; the task notices the flag within a second and closes it.
    return {"ok": True, "job": job.as_dict()}


async def wait(job_id: str, seconds: float) -> Job | None:
    job = JOBS.get(str(job_id or ""))
    if job is None or job.task is None:
        return job
    try:
        await asyncio.wait_for(asyncio.shield(job.task), timeout=max(0.0, seconds))
    except asyncio.TimeoutError:  # still running is an answer: the job says so
        pass
    except Exception:  # noqa: BLE001 — the job carries its own ending
        pass
    return job


# ---------------------------------------------------------------------------
# One payload for the tab and the tools
# ---------------------------------------------------------------------------

async def overview(*, fresh: bool = False) -> dict:
    """Every device file, what the dashboard and Home Assistant know of it."""
    configs = await asyncio.to_thread(list_configs)
    async with aiohttp.ClientSession() as session:
        found, status = await route(session, fresh=fresh)
        dash: dict[str, dict] = {}
        online: dict[str, Any] = {}
        importable: list = []
        if found is not None:
            try:
                body = await dashboard_json(session, "devices")
                for row in (body or {}).get("configured") or []:
                    if isinstance(row, dict) and row.get("configuration"):
                        dash[row["configuration"]] = row
                importable = [
                    {k: row.get(k) for k in ("name", "friendly_name",
                                             "package_import_url", "network")}
                    for row in (body or {}).get("importable") or []
                    if isinstance(row, dict)]
            except Exception as exc:  # noqa: BLE001
                status = {**status, "devices_error": str(exc)}
            try:
                ping = await dashboard_json(session, "ping")
                if isinstance(ping, dict):
                    online = ping
            except Exception:  # noqa: BLE001 — online is a nicety
                pass
        ha = await ha_devices(session)
    patterns = automation_writer.protected_patterns()
    rows = []
    for cfg in configs:
        d = dash.get(cfg["configuration"], {})
        dev = match_device(cfg, ha["devices"]) if ha["ok"] else None
        deployed = str(d.get("deployed_version") or "")
        current = str(d.get("current_version") or "")
        rows.append({
            **cfg,
            "address": d.get("address") or "",
            "web_port": d.get("web_port"),
            "deployed_version": deployed,
            "current_version": current,
            "update_available": bool(deployed and current and deployed != current),
            "online": online.get(cfg["configuration"]),
            "loaded_integrations": sorted(d.get("loaded_integrations") or [])[:60],
            "ha_device_id": dev["id"] if dev else "",
            "ha_name": (dev["name_by_user"] or dev["name"]) if dev else "",
            "area_id": dev["area_id"] if dev else "",
            "entity_count": len(dev["entities"]) if dev else 0,
            "update_entity": dev["update_entity"] if dev else "",
            "protected": bool(dev and any(
                automation_writer.is_protected(e, patterns)
                for e in dev["entities"])),
            "job": (running_for(cfg["configuration"]).as_dict(since=10**9)
                    if running_for(cfg["configuration"]) else None),
        })
    return {"dir": str(ESPHOME_DIR), "dir_exists": ESPHOME_DIR.is_dir(),
            "dashboard": status, "devices": rows, "importable": importable,
            "ha_registry_ok": ha["ok"], "secret_keys": secret_keys(),
            "platforms": [{"id": k, "label": v["label"], "board": v["board"]}
                          for k, v in PLATFORMS.items()],
            "jobs": [j.as_dict(since=10**9) for j in reversed(JOBS.values())]}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def _json(data: dict, status: int = 200) -> web.Response:
    return web.json_response(data, status=status)


def _status_for(result: dict) -> int:
    if result.get("ok"):
        return 200
    if result.get("missing"):
        return 404
    if result.get("conflict") or result.get("refused"):
        return 409
    if result.get("unreachable"):
        return 503
    return 400


async def _body(request: web.Request) -> dict:
    try:
        body = await request.json()
    except (ValueError, UnicodeDecodeError):
        return {}
    return body if isinstance(body, dict) else {}


async def h_overview(request: web.Request) -> web.Response:
    fresh = request.query.get("fresh") in ("1", "true")
    return _json(await overview(fresh=fresh))


async def h_config_get(request: web.Request) -> web.Response:
    result = await asyncio.to_thread(read_config, request.match_info["name"])
    return _json(result, _status_for(result))


async def h_config_put(request: web.Request) -> web.Response:
    body = await _body(request)
    mtime = body.get("mtime")
    try:
        mtime = float(mtime) if mtime is not None else None
    except (TypeError, ValueError):
        mtime = None
    result = await asyncio.to_thread(
        write_config, request.match_info["name"], body.get("content"),
        expect_mtime=mtime, create=bool(body.get("create")))
    return _json(result, _status_for(result))


async def h_create(request: web.Request) -> web.Response:
    body = await _body(request)
    result = await asyncio.to_thread(
        create_config, body.get("name"), body.get("friendly_name") or "",
        body.get("platform") or "esp32", body.get("board") or "")
    return _json(result, _status_for(result))


async def h_action(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    action = request.match_info["action"]
    body = await _body(request)
    if action == "delete":
        path = config_path(name)
        info = describe(path.read_text(encoding="utf-8", errors="replace")) \
            if path is not None and path.is_file() else {}
        async with aiohttp.ClientSession() as session:
            refusal = await protected_refusal(session, info) if info else None
        if refusal:
            return _json({"ok": False, "refused": True, "error": refusal}, 409)
        result = await asyncio.to_thread(archive_config, name)
        return _json(result, _status_for(result))
    result = await start(action, name, port=str(body.get("port") or "OTA"))
    return _json(result, _status_for(result))


async def h_job(request: web.Request) -> web.Response:
    job = JOBS.get(request.match_info["id"])
    if job is None:
        return _json({"ok": False, "error": "no such job"}, 404)
    try:
        since = int(request.query.get("since") or 0)
    except ValueError:
        since = 0
    wait_s = request.query.get("wait")
    if wait_s and job.state == "running":
        try:
            await wait(job.id, min(float(wait_s), 600.0))
        except ValueError:  # an unreadable wait is no wait, not a refusal
            pass
    return _json({"ok": True, "job": job.as_dict(since)})


async def h_job_stop(request: web.Request) -> web.Response:
    result = stop(request.match_info["id"])
    return _json(result, _status_for(result))


async def h_secrets(request: web.Request) -> web.Response:
    return _json({"ok": True, "keys": await asyncio.to_thread(secret_keys)})


async def h_secret_put(request: web.Request) -> web.Response:
    body = await _body(request)
    result = await asyncio.to_thread(set_secret, request.match_info["key"],
                                     body.get("value"))
    return _json(result, _status_for(result))


def setup(app: web.Application) -> None:
    """Register the /api/esphome routes."""
    app.router.add_get("/api/esphome", h_overview)
    app.router.add_post("/api/esphome/create", h_create)
    app.router.add_get("/api/esphome/secrets", h_secrets)
    app.router.add_put("/api/esphome/secret/{key}", h_secret_put)
    app.router.add_get("/api/esphome/job/{id}", h_job)
    app.router.add_post("/api/esphome/job/{id}/stop", h_job_stop)
    app.router.add_get("/api/esphome/config/{name}", h_config_get)
    app.router.add_put("/api/esphome/config/{name}", h_config_put)
    app.router.add_post("/api/esphome/config/{name}/{action}", h_action)
