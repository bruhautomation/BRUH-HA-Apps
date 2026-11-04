"""Morph's own dashboard as a Home Assistant dashboard (docs/design/morph-on-lovelace.md §3).

``to_lovelace`` turns /config/morph/dashboard.yaml (as ``store`` reads it)
into a Lovelace config that looks like the dashboard the house knows:

* a floor is a view (tab) of type ``custom:morph-view``, so rooms that need
  somebody still rise and quiet ones still fold;
* a room is a section: a heading with the room's name, a group's label as a
  smaller heading, and each card;
* each of Morph's card kinds is its Home Assistant card,
  ``custom:morph-<kind>-card``, with the same entity, name, colour and
  options; a hosted Lovelace card is copied as it is;
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
THEMES = {"medium": "Morph Medium", "dark": "Morph", "light": "Morph", "auto": "Morph"}
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


def card(c: dict, report: list[str], where: str) -> dict | None:
    """One Morph card as its Home Assistant card."""
    kind = c.get("type")
    if kind == "lovelace":
        inner = c.get("card")
        if isinstance(inner, dict) and inner.get("type"):
            return dict(inner)
        report.append(f"{where}: a Lovelace card with no config was left out.")
        return None
    if kind not in KINDS:
        report.append(f"{where}: the card type “{kind}” came from this house's own copy of Morph's code, "
                      "which a Home Assistant dashboard does not run; it is shown as a plain entity card.")
        kind = "entity"
        if not c.get("entity"):
            return None
    out: dict = {"type": tag(kind)}
    for key in ("entity", "name", "text", "color"):
        if c.get(key):
            out[key] = c[key]
    if c.get("entities"):
        out["entities"] = list(c["entities"])
    opts = dict(c.get("options") or {})
    if kind == "climate" and opts.get("actions"):
        out["actions"] = opts.pop("actions")
    if opts.pop("header", None):
        report.append(f"{where}: a switch shown in its room's title row is an ordinary switch card now.")
    if opts.get("detail"):
        report.append(f"{where}: the card shown under it when opened is left in `options.detail`; "
                      "Home Assistant's own more-info opens from the card.")
    if opts:
        out["options"] = opts
    return out


def to_lovelace(dash: dict, title: str = "") -> tuple[dict, list[str]]:
    """(Lovelace config, report). ``dash`` is ``store.normalize``'s form."""
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
            cards: list[dict] = [{"type": "heading", "heading": name}]
            if sec.get("area"):
                cards.append({"type": "custom:morph-cases-card", "area": sec["area"]})
            for g in sec.get("groups") or []:
                if g.get("label"):
                    words = g["label"] + (f" · {g['note']}" if g.get("note") else "")
                    cards.append({"type": "heading", "heading": words, "heading_style": "subtitle"})
                for c in g.get("cards") or []:
                    got = card(c, report, f"{fl.get('title')} › {name} › {c.get('name') or c.get('entity') or c.get('type')}")
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
                "type": "custom:morph-view", "sections": sections}
        theme = THEMES.get(dash.get("theme") or "auto")
        if theme:
            view["theme"] = theme
        views.append(view)
    if not views:
        views.append({"title": "Home", "path": "home", "type": "custom:morph-view", "sections": []})
    if dash.get("story", True):
        report.append("The story line at the top is Morph's panel's own; on a Home Assistant dashboard Ask "
                      "and brAIn's cases say what is going on.")
    if dash.get("coming_up", True):
        report.append("Coming up is Morph's panel's own and was not brought over.")
    return {"title": title or dash.get("title") or "Home", "views": views}, report
