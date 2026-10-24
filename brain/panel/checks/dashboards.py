"""Dashboard checks.

A card pointing at an entity that no longer exists renders as a red
"Entity not available" tile that the person has usually stopped seeing.
One finding per missing entity, naming every dashboard that shows it — a
deleted scene on two dashboards is one thing to fix, and was filed twice
when the rows were per dashboard (#341). Entities missing from exactly the
same dashboards share a row, so a rebuilt integration that renamed forty
entities is still one row and not forty.
"""
from __future__ import annotations

from ._util import House, evidence_for, join_names, walk


def _dashboard_refs(house: House, config) -> set[str]:
    refs: set[str] = set()
    # Explicit keys first — they are the reliable ones. `entity` and
    # `entities` may hold a string, a list of strings, or a list of dicts
    # with an `entity` key, depending on the card.
    for node in walk(config):
        if not isinstance(node, dict):
            continue
        for key in ("entity", "entities"):
            val = node.get(key)
            if isinstance(val, str):
                refs.add(val)
            elif isinstance(val, list):
                for item in val:
                    if isinstance(item, str):
                        refs.add(item)
                    elif isinstance(item, dict) and isinstance(item.get("entity"), str):
                        refs.add(item["entity"])
    # Then anything that looks like an entity id in a template or a
    # conditional card's state test.
    refs |= house.entity_refs(config)
    return {r for r in refs if "." in r and " " not in r and "{" not in r}


def dead_ref(snap: dict, now: float) -> list[dict]:
    house = House(snap)
    # Which dashboards show each missing entity, in the order they are listed.
    shown_on: dict[str, list[str]] = {}
    for dash in snap.get("dashboards") or []:
        if not isinstance(dash, dict) or not isinstance(dash.get("config"), dict):
            continue
        title = str(dash.get("title") or dash.get("url_path") or "Overview")
        for ref in sorted(_dashboard_refs(house, dash["config"])):
            if house.exists(ref) or ref.split(".", 1)[0] not in house.known_domains:
                continue
            on = shown_on.setdefault(ref, [])
            if title not in on:
                on.append(title)
    # Entities missing from the same dashboards are one thing to fix there.
    groups: dict[tuple[str, ...], list[str]] = {}
    for ref in sorted(shown_on):
        if not house.should_report(ref, "org.dashboard_dead_ref"):
            continue
        groups.setdefault(tuple(shown_on[ref]), []).append(ref)
    out = []
    for titles, dead in sorted(groups.items(), key=lambda g: g[1][0]):
        first = house.label(dead[0])
        # The text names the first missing entity and never the dashboards
        # or a count, which move from pass to pass: it is the dedupe key.
        text = (f"{first} is on a dashboard but no longer exists"
                if len(dead) == 1 else
                f"{first} and other entities on a dashboard no longer exist")
        quoted = [f"'{t}'" for t in titles]
        out.append({
            "text": text[:1].upper() + text[1:],
            "detail": ("Missing: " + join_names([house.label(r) for r in dead], 8)
                       + ". Shown on "
                       + ("the dashboard " if len(titles) == 1 else "the dashboards ")
                       + join_names(quoted, 8) + ", where "
                       + ("it renders" if len(dead) == 1 else "each one renders")
                       + " as a red 'entity not available' tile."),
            "fix": ("Edit " + ("that dashboard" if len(titles) == 1
                               else "those dashboards")
                    + " and point those cards at the entities that replaced "
                    "them, or remove the cards."),
            "severity": "warning",
            "fixable": True,
            "entity_id": dead[0],
            "evidence": evidence_for(dead, "no longer exists"),
        })
    return out


CHECKS = [
    {"id": "org.dashboard_dead_ref", "area": "dashboards",
     "title": "Dashboards showing missing entities",
     "needs": ("states", "registry", "dashboards"), "run": dead_ref},
]
