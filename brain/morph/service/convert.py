"""Morph's own dashboard as a Home Assistant dashboard (docs/design/morph-on-lovelace.md §3).

``to_lovelace`` turns /config/morph/dashboard.yaml (as ``store`` reads it)
into a Lovelace config that looks like the dashboard the house knows:

* a floor is a view (tab) of Home Assistant's own **sections** type, so
  every editing feature HA has works on it (add, move and resize sections
  and cards, badges, columns) and HA's grid does the layout. The room rail
  comes along as the view's ``morph: {rail: true}``, which brAIn's layer
  draws on any sections view; lifting a room that needs somebody and
  folding a quiet one are the same switches (``order``, ``fold``), off;
* a room is a section: a heading with the room's name (and a switch Morph
  showed in the room's title row as one of the heading's entities), a
  group's label as a smaller heading, and each card;
* each of Morph's card kinds is its Home Assistant card,
  ``custom:morph-<kind>-card``, with the same entity, name, icon, colour,
  buttons and opened-card (``detail``) as plain keys HA's visual editor
  edits, and a width the house set (``span``) as HA's ``grid_options``; a
  kind this house's own copy of Morph's cards added is its own card too; a
  hosted Lovelace card is copied as it is;
* a room with an area gets brAIn's cases for that area (a card that hides
  itself while there are none), and Ask, the house-wide scenes and the
  theme come along when the dashboard had them.

Nothing is guessed silently: what could not come along is said in
``report``, one line each, and the old dashboard is left exactly as it was.
"""
from __future__ import annotations

import re

KINDS = ("light", "light_group", "fan", "cover", "lock", "switch", "button", "vacuum", "climate", "sensor",
         "readings", "meter", "media", "camera", "list", "person", "weather", "alarm", "scenes", "entity", "note")
# "Morph" follows each person's light/dark setting, which is what "auto"
# meant; a dashboard that WAS light or dark stays it (morph-fixed.yaml).
THEMES = {"medium": "Morph Medium", "dark": "Morph Dark", "light": "Morph Light", "auto": "Morph"}
# The layer's switches a converted view starts with: the rail, which is
# navigation; reordering and folding are a house's choice to turn on.
VIEW_MORPH = {"rail": True, "order": False, "fold": False}
URL_PATH = "morph-home"


def tag(kind: str) -> str:
    return "custom:morph-" + kind.replace("_", "-") + "-card"


def _slug(text: str, used: set) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-") or "view"
    cand, n = base, 2
    while cand in used:
        cand, n = f"{base}-{n}", n + 1
    used.add(cand)
    return cand


def columns(span) -> int | None:
    """A width the house set in Morph (``span``, 1 to 4 of a room) as HA's
    12 columns; None when it set none (the kind's own size then)."""
    try:
        n = int(span)
    except (TypeError, ValueError):
        return None
    return max(1, min(4, n)) * 3


def card(c: dict, report: list[str], where: str, house: tuple = ()) -> dict | None:
    """One Morph card as its Home Assistant card. ``house`` is the kinds this
    house's own copy of Morph's cards adds (morphcode.card_types)."""
    kind = c.get("type")
    if kind == "lovelace":
        inner = c.get("card")
        if isinstance(inner, dict) and inner.get("type"):
            return dict(inner)
        report.append(f"{where}: a Lovelace card with no config was left out.")
        return None
    if kind not in KINDS and kind in house:
        pass  # the house's own kind: morph-cards.js registers it from the copy
    elif kind not in KINDS:
        report.append(f"{where}: the card type “{kind}” came from this house's own copy of Morph's code, "
                      "which a Home Assistant dashboard does not run; it is shown as a plain entity card.")
        kind = "entity"
        if not c.get("entity"):
            return None
    out: dict = {"type": tag(kind)}
    for key in ("entity", "name", "icon", "text", "color"):
        if c.get(key):
            out[key] = c[key]
    if c.get("entities"):
        out["entities"] = list(c["entities"])
    opts = dict(c.get("options") or {})
    if kind == "climate" and opts.get("actions"):
        out["actions"] = opts.pop("actions")
    opts.pop("header", None)  # the section's heading carries it (to_lovelace)
    if isinstance(opts.get("detail"), dict) and opts["detail"].get("type"):
        out["detail"] = opts.pop("detail")
    if opts:
        out["options"] = opts
    cols = columns(c.get("span"))
    if cols:
        out["grid_options"] = {"columns": cols}
    return out


def header_switch(c: dict) -> str | None:
    """A switch Morph drew as a pill in its room's title row, or None."""
    opts = c.get("options") or {}
    return c.get("entity") if c.get("type") == "switch" and c.get("entity") and opts.get("header") is True else None


def to_lovelace(dash: dict, title: str = "", house: tuple = ()) -> tuple[dict, list[str]]:
    """(Lovelace config, report). ``dash`` is ``store.normalize``'s form;
    ``house`` the kinds this house's own copy of Morph's cards adds."""
    report: list[str] = []
    used: set = set()
    views = []
    has_area = any(sec.get("area") for fl in dash.get("floors") or [] for sec in fl.get("sections") or [])
    for fi, fl in enumerate(dash.get("floors") or []):
        sections = []
        for sec in fl.get("sections") or []:
            name = sec.get("title") or "Room"
            if sec.get("hidden"):
                report.append(f"{fl.get('title')} › {name}: hidden in Morph, so it was not brought over.")
                continue
            heading: dict = {"type": "heading", "heading": name}
            cards: list[dict] = [heading]
            pills = [header_switch(c) for g in sec.get("groups") or [] for c in g.get("cards") or []]
            if any(pills):
                heading["entities"] = [{"entity": e, "tap_action": {"action": "toggle"}} for e in pills if e]
            if sec.get("area"):
                cards.append({"type": "custom:morph-cases-card", "area": sec["area"]})
            for g in sec.get("groups") or []:
                if g.get("label"):
                    words = g["label"] + (f" · {g['note']}" if g.get("note") else "")
                    cards.append({"type": "heading", "heading": words, "heading_style": "subtitle"})
                for c in g.get("cards") or []:
                    if header_switch(c):
                        continue  # on the heading, where Morph drew it
                    got = card(c, report, f"{fl.get('title')} › {name} › {c.get('name') or c.get('entity') or c.get('type')}", house)
                    if got:
                        cards.append(got)
            sections.append({"type": "grid", "cards": cards})
        top = []
        if fi == 0:
            if dash.get("ask", True):
                top.append({"type": "custom:morph-ask-card"})
            if not has_area:
                top.append({"type": "custom:morph-cases-card"})
            if dash.get("scenes"):
                top.append({"type": tag("scenes"), "entities": list(dash["scenes"])})
        if top:
            sections.insert(0, {"type": "grid", "cards": top})
        view = {"title": fl.get("title") or f"Floor {fi + 1}", "path": _slug(fl.get("title"), used),
                "type": "sections", "max_columns": 4, "sections": sections, "morph": dict(VIEW_MORPH)}
        theme = THEMES.get(dash.get("theme") or "auto")
        if theme:
            view["theme"] = theme
        views.append(view)
    if not views:
        views.append({"title": "Home", "path": "home", "type": "sections", "max_columns": 4, "sections": [],
                      "morph": dict(VIEW_MORPH)})
    if dash.get("story", True):
        report.append("The story line at the top is Morph's panel's own; on a Home Assistant dashboard Ask "
                      "and brAIn's cases say what is going on.")
    if dash.get("coming_up", True):
        report.append("Coming up is Morph's panel's own and was not brought over.")
    return {"title": title or dash.get("title") or "Home", "views": views}, report


def from_morph_view(view: dict) -> dict | None:
    """A view a 5.0 conversion wrote as ``custom:morph-view``, as HA's own
    sections view (5.1): the same sections and cards, its ``morph`` switches
    kept (the layer reads them on a sections view), reordering and folding
    off unless the view had turned them on by name. None when it is not one."""
    if not isinstance(view, dict) or view.get("type") != "custom:morph-view":
        return None
    out = {k: v for k, v in view.items() if k != "type"}
    out["type"] = "sections"
    out.setdefault("max_columns", 4)
    had = view.get("morph") if isinstance(view.get("morph"), dict) else {}
    out["morph"] = {**VIEW_MORPH, **{k: bool(had[k]) for k in ("rail", "order", "fold") if k in had}}
    return out


def migrate(config: dict) -> tuple[dict, int]:
    """(config, how many views changed): every Morph view a sections view."""
    if not isinstance(config, dict) or not isinstance(config.get("views"), list):
        return config, 0
    views, n = [], 0
    for v in config["views"]:
        new = from_morph_view(v)
        views.append(new if new is not None else v)
        n += new is not None
    return ({**config, "views": views} if n else config), n
