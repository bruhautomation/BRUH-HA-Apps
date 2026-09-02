"""Dashboard checks.

A card pointing at an entity that no longer exists renders as a red
"Entity not available" tile that the person has usually stopped seeing.
One finding per dashboard, listing the entities, so a rebuilt integration
that renamed forty entities is one row and not forty.
"""
from __future__ import annotations

from ._util import House, join_names, walk


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
    out = []
    for dash in snap.get("dashboards") or []:
        if not isinstance(dash, dict) or not isinstance(dash.get("config"), dict):
            continue
        refs = _dashboard_refs(house, dash["config"])
        dead = sorted(r for r in refs if not house.exists(r)
                      and r.split(".", 1)[0] in house.known_domains)
        if not dead:
            continue
        title = str(dash.get("title") or dash.get("url_path") or "Overview")
        out.append({
            "text": f"Dashboard '{title}' shows entities that no longer exist",
            "detail": "Missing: " + join_names(dead, 8) + ". Each one renders "
                      "as a red 'entity not available' tile.",
            "fix": "Edit the dashboard and point those cards at the entities "
                   "that replaced them, or remove the cards.",
            "severity": "warning",
            "fixable": True,
            "entity_id": dead[0],
        })
    return out


CHECKS = [
    {"id": "org.dashboard_dead_ref",
     "title": "Dashboards showing missing entities",
     "needs": ("states", "registry", "dashboards"), "run": dead_ref},
]
