"""Which screens brAIn photographs besides its own, and how each is reached.

`screens.py` photographs brAIn's panel. The other BRUH add-ons have panels
too, and Lovelace cards, and Morph draws a whole dashboard, and none of
them could be seen by anything that files issues: a GardenRX table off the
edge of a phone was a thing the owner had to notice, screenshot and carry
to Claude Code by hand. This module is the catalog of those screens and
the arithmetic that turns the Supervisor's answer about an add-on into a
URL a browser on this box can open. It decides nothing and fetches nothing
itself (`locate` takes the Supervisor reader as an argument), so it is
driven in tests without a Supervisor.

**An add-on's panel is reached over the hassio network, never ingress.**
Minting an ingress session needs a Home Assistant administrator's token on
a current Supervisor (`esphome.py` says why), and every BRUH panel answers
the hassio bridge (172.30.32.0/23), because that is where the Supervisor's
ingress proxy reaches it from — BRight's and BRUH Minecraft's `_lan_gate`
allow exactly that network — so this container can open the panel the way
the proxy does, at the add-on's own address and ingress
port (the host's gateway for an add-on on the host network). GardenRX was
built to live under its ingress path and its gateway passes a request that
already carries it, so it is opened under that path.

**Nothing photographed here can change anything.** A sibling's panel is
somebody's printer, light show or Minecraft world, and the capture presses
tabs. So every target here is captured with the browser's write guard on
(`screens.py`): any request that is not a GET or HEAD is failed before it
leaves the browser, unless its path is one this catalog names as a read
(BRUH Print draws its previews with a POST), and WebSockets are blocked
outright. A panel that misdraws because a write was refused is a truer
picture of "what this screen looks like" than a panel that printed a label.

**The cards and Morph are drawn in a brAIn page** (`/devloop/harness/…`,
loopback only), because they live inside Home Assistant's frontend, which a
browser here cannot sign into. The page hands them a `hass` whose states
and reads are the house's own, through a read-only proxy, and whose
`callService` refuses: what is photographed is the card on this house's
data, and pressing nothing in it can reach the house.
"""
from __future__ import annotations

import os
import re

from . import siblings

# The host, seen from this container, for an add-on on the host network.
HOST_GATEWAY = os.environ.get("BRAIN_HOST_GATEWAY", "172.30.32.1")

# A screen is (slug, label, how). `how` is ("click", css selector) — the
# tab's own button, pressed the way a person presses it — or ("path",
# "/crops"), a route opened by URL. Slugs are short: they become file
# names together with the add-on's key.
PANELS: dict[str, dict] = {
    "gardenrx": {
        "prefix": True,
        "screens": [
            ("today", "Today", ("path", "/")),
            ("crops", "Crops", ("path", "/crops")),
            ("garden", "Garden", ("path", "/garden")),
            ("weather", "Weather", ("path", "/weather")),
            ("products", "Products", ("path", "/products")),
            ("inventory", "Inventory", ("path", "/inventory")),
            ("harvest", "Harvest", ("path", "/harvest")),
            ("tank", "Tank", ("path", "/tank")),
        ],
        # GardenRX's screens read through POST /api/db (its client half of
        # the supabase-js subset), which also carries its writes — so only
        # a body whose action is a select is let through.
        "reads": [{"path": r"/api/db$", "field": "action", "equals": "select"}],
    },
    "bruh-bambu-studio": {
        "screens": [
            ("printers", "Printers", ("click", '.tab[data-view="printers"]')),
            ("files", "Files", ("click", '.tab[data-view="files"]')),
            ("studio", "Studio", ("click", '.tab[data-view="studio"]')),
        ],
    },
    "bruh-print": {
        "screens": [
            ("quick", "Quick", ("click", '.tab[data-view="quick"]')),
            ("design", "Design", ("click", '.tab[data-view="design"]')),
            ("templates", "Templates", ("click", '.tab[data-view="templates"]')),
            ("printer", "Printer", ("click", '.tab[data-view="printer"]')),
            ("history", "History", ("click", '.tab[data-view="history"]')),
        ],
        # The preview is drawn by a POST that renders and returns a PNG.
        "reads": [{"path": r"/api/preview$"},
                  {"path": r"/api/template/[^/]+/preview$"}],
    },
    "bright": {
        "screens": [
            ("lab", "Lab", ("click", '.tab[data-tab="lab"]')),
            ("map", "Light Map", ("click", '.tab[data-tab="map"]')),
            ("effects", "Effects", ("click", '.tab[data-tab="effects"]')),
            ("library", "Library", ("click", '.tab[data-tab="library"]')),
            ("shows", "Shows", ("click", '.tab[data-tab="shows"]')),
            ("party", "Party", ("click", '.tab[data-tab="party"]')),
        ],
    },
    "bruh_minecraft_server": {
        "screens": [
            ("dashboard", "Dashboard", ("click", '.tab[data-tab="dashboard"]')),
            ("players", "Players", ("click", '.tab[data-tab="players"]')),
            ("properties", "Server Properties", ("click", '.tab[data-tab="properties"]')),
            ("addons", "Add-ons", ("click", '.tab[data-tab="addons"]')),
            ("backups", "Backups", ("click", '.tab[data-tab="backups"]')),
            ("worlds", "Worlds", ("click", '.tab[data-tab="worlds"]')),
        ],
    },
}

# What is drawn in brAIn's harness page: (product key, slug, label, the
# harness's name for it). Morph has no panel of its own to open — it is
# brAIn's Home tab, drawn by Home Assistant — so the harness is how it is
# seen at all.
HARNESS: list[tuple[str, str, str, str]] = [
    ("morph", "dashboard", "Dashboard", "morph"),
    ("bruh-print", "card", "Lovelace card", "print-card"),
    ("bruh-bambu-studio", "card", "Lovelace card", "bambu-card"),
    ("gardenrx", "cards", "Lovelace cards", "gardenrx-cards"),
]

# The harness's card files, as (name → the paths it may be read from, in
# order). A name off the URL is looked up here and nowhere else.
CARD_FILES: dict[str, tuple[str, ...]] = {
    "bruh-print-card.js": ("/config/www/bruh_print/bruh-print-card.js",),
    "bruh-bambu-card.js": ("/config/www/bruh_bambu/bruh-bambu-card.js",
                           "/config/morph/cards/bruh-bambu-printer.js"),
    "gardenrx-cards.js": ("/config/custom_components/gardenrx/frontend/gardenrx-cards.js",
                          "/config/morph/cards/gardenrx.js"),
}
MORPH_FRONTEND = os.environ.get("BRAIN_MORPH_FRONTEND",
                                "/config/custom_components/brain/morph/frontend")
MORPH_CARDS = os.environ.get("BRAIN_MORPH_CARDS", "/config/morph/cards")
MODULE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,60}\.js$")

# The Home Assistant WebSocket commands the harness may ask, all of which
# only read. Everything else is refused in the proxy, whatever the page
# asks: a card that tries to write meets the same answer a button would.
READ_COMMANDS = frozenset({
    "get_states", "get_config", "morph/load", "morph/tell_status",
    "history/history_during_period", "recorder/statistics_during_period",
    "logbook/get_events",
})
# A service whose answer is data and which changes nothing (Morph's
# weather card asks for the forecast this way).
READ_SERVICES = frozenset({("weather", "get_forecasts")})


def key_for(product: str) -> str:
    """The catalog key of a product name, or "" for brAIn and strangers."""
    spec = siblings.spec_by_name(product)
    return spec["key"] if spec else ""


def file_key(key: str) -> str:
    """A catalog key as it may appear in a picture's file name."""
    return re.sub(r"[^a-z0-9-]", "-", str(key or "").lower())


# Morph is part of brAIn since 4.0, so it is no add-on of the catalog's: it
# is drawn while its switch (⚙ › Features) is on, at brAIn's own version.
MORPH_PRODUCT = "Morph"


def morph_on() -> bool:
    try:
        import features  # noqa: PLC0415 — panel-local
        return features.on("morph")
    except Exception:  # noqa: BLE001 — an unreadable switch draws nothing
        return False


def product_for(key: str) -> str:
    if key == "morph":
        return MORPH_PRODUCT
    for s in siblings.CATALOG:
        if s["key"] == key:
            return s["name"]
    return ""


def panel_url(info: dict, prefix: bool = False) -> str:
    """The URL this container opens an add-on's panel at, or "" when the
    Supervisor's answer does not say where it is (no ingress, no port)."""
    if not isinstance(info, dict) or not info.get("ingress"):
        return ""
    try:
        port = int(info.get("ingress_port") or 0)
    except (TypeError, ValueError):
        return ""
    if not 0 < port < 65536:
        return ""
    host = HOST_GATEWAY if info.get("host_network") else str(info.get("ip_address") or "")
    if not re.fullmatch(r"[0-9a-fA-F.:]{3,45}|[a-z0-9][a-z0-9.-]{0,62}", host or ""):
        return ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    base = f"http://{host}:{port}"
    if prefix:
        entry = str(info.get("ingress_entry") or "")
        if not re.fullmatch(r"/api/hassio_ingress/[A-Za-z0-9_-]{8,128}", entry.rstrip("/")):
            return ""
        base += entry.rstrip("/")
    return base + "/"


def screen_script(how) -> str:
    """The page script that shows a click-screen, or "" for a path screen.
    It raises in the page when the button is not there, which is a
    screen that could not be opened rather than a picture of the wrong
    tab."""
    if not how or how[0] != "click":
        return ""
    sel = str(how[1]).replace("\\", "\\\\").replace("'", "\\'")
    return (f"(() => {{ const b = document.querySelector('{sel}'); "
            f"if (!b) throw new Error('no such tab'); b.click(); "
            f"return new Promise((r) => setTimeout(r, 400)); }})()")


def locate(get) -> dict:
    """Every installed BRUH add-on's panel, as targets ``screens.capture``
    takes, plus the products this pass could not reach.

    ``get`` is the Supervisor reader (`siblings._get`'s shape). Answers
    ``{"targets": [...], "versions": {product: version}, "unreached":
    {product: why}}``. Never raises: a Supervisor that will not answer is
    a sentence, and every catalog add-on is then unreached."""
    out = {"targets": [], "versions": {}, "unreached": {}}
    if morph_on():
        out["versions"][MORPH_PRODUCT] = os.environ.get("ADDON_VERSION", "dev")[:40]
    try:
        listing = get("/addons")
    except Exception as exc:  # noqa: BLE001 — one sentence for all of them
        for s in siblings.CATALOG:
            out["unreached"][s["name"]] = f"could not list the add-ons: {exc}"[:160]
        return out
    rows = (listing or {}).get("addons") if isinstance(listing, dict) else listing
    seen: dict[str, str] = {}
    for row in rows or []:
        if isinstance(row, dict):
            spec = siblings.spec_for(row.get("slug"), row.get("name"))
            if spec and spec["key"] not in seen:
                seen[spec["key"]] = str(row["slug"])
    for spec in siblings.CATALOG:
        key, name = spec["key"], spec["name"]
        if key not in seen:
            out["unreached"][name] = "not installed"
            continue
        try:
            info = get(f"/addons/{seen[key]}/info")
        except Exception as exc:  # noqa: BLE001
            out["unreached"][name] = f"could not read its info: {exc}"[:160]
            continue
        if not isinstance(info, dict):
            out["unreached"][name] = "its info could not be read"
            continue
        out["versions"][name] = str(info.get("version") or "?")[:40]
        panel = PANELS.get(key)
        if not panel:
            continue          # drawn in the harness, nothing to open
        if info.get("state") != "started":
            out["unreached"][name] = f"it is {info.get('state') or 'not running'}"
            continue
        url = panel_url(info, prefix=bool(panel.get("prefix")))
        if not url:
            out["unreached"][name] = "the Supervisor did not say where its panel is"
            continue
        out["targets"].append(target(key, name, url))
    return out


def target(key: str, product: str, url: str) -> dict:
    """One add-on's panel as a capture target."""
    panel = PANELS[key]
    fkey = file_key(key)
    screens = []
    base = url.rstrip("/")
    for slug, label, how in panel["screens"]:
        if how[0] == "path":
            screens.append({"slug": f"{fkey}-{slug}", "label": f"{product} › {label}",
                            "url": base + how[1], "script": ""})
        else:
            screens.append({"slug": f"{fkey}-{slug}", "label": f"{product} › {label}",
                            "url": url, "script": screen_script(how)})
    return {"key": key, "product": product, "url": url, "guard": True,
            "reads": list(panel.get("reads") or []), "screens": screens}


def harness_targets(panel_base: str, products: dict[str, str]) -> list[dict]:
    """The cards and Morph, drawn in brAIn's own harness page. Only an
    installed add-on's card is drawn (``products`` is name → version)."""
    out = []
    base = panel_base.rstrip("/")
    for key, slug, label, name in HARNESS:
        product = product_for(key)
        if product not in products:
            continue
        out.append({"key": key, "product": product, "url": f"{base}/devloop/harness/{name}",
                    "guard": True, "reads": [],
                    "screens": [{"slug": f"{file_key(key)}-{slug}", "label": f"{product} › {label}",
                                 "url": f"{base}/devloop/harness/{name}", "script":
                                 "window.__harnessReady || Promise.resolve()"}]})
    return out


def card_file(name: str) -> str:
    """The path a harness card file is read from, or "" when there is none
    on this box (the add-on is not installed, or never copied it)."""
    for path in CARD_FILES.get(str(name or ""), ()):
        if os.path.isfile(path):
            return path
    return ""


def module_file(root: str, name: str) -> str:
    """A Morph module or card file by name under ``root``, or ""."""
    if not MODULE_RE.match(str(name or "")):
        return ""
    base = os.path.normpath(root)
    full = os.path.normpath(os.path.join(base, name))
    if not full.startswith(base + os.sep) or not os.path.isfile(full):
        return ""
    return full


def morph_module(name: str) -> str:
    """One of Morph's own frontend modules, or ""."""
    return module_file(MORPH_FRONTEND, name)


def morph_card(name: str) -> str:
    """A card file from the house's /config/morph/cards, or ""."""
    return module_file(MORPH_CARDS, name)


def allowed_ws(msg) -> str:
    """Why a harness WebSocket message is refused, or "" when it may go.
    Only reads go; the id is the proxy's own."""
    if not isinstance(msg, dict):
        return "not a message"
    kind = str(msg.get("type") or "")
    if kind in READ_COMMANDS:
        return ""
    if kind == "call_service":
        pair = (str(msg.get("domain") or ""), str(msg.get("service") or ""))
        if pair in READ_SERVICES and msg.get("return_response"):
            return ""
    return f"brAIn's preview only reads ({kind or 'unknown'} is refused)"


__all__ = ["CARD_FILES", "key_for", "HARNESS", "PANELS", "READ_COMMANDS", "allowed_ws",
           "card_file", "harness_targets", "locate", "module_file", "morph_card",
           "morph_module", "panel_url",
           "product_for", "screen_script", "target"]
