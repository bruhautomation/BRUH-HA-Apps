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

import re

from ._registry_facts import FEATURE_PLATFORMS
from ._util import (House, _kind_of, entity_list, evidence_for, join_names,
                    walk)

# What a person carries: a phone or tablet through the companion app. The
# same platforms whose entities are features of the device
# (`_registry_facts.FEATURE_PLATFORMS`).
PERSONAL_PLATFORMS = FEATURE_PLATFORMS


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


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(name or "").casefold()).strip("_")


def _id_words(entity_id: str) -> list[str]:
    return [w for w in entity_id.partition(".")[2].split("_") if w]


def by_device(house: House, dead: list[str]) -> list[dict]:
    """The missing entities by the device they belonged to, in the words a
    household uses: ``[{"name", "members", "present"}]``, first seen first.

    Read off structure, never off the words: an entity the registry still
    puts on a device is that device's; otherwise Home Assistant built its
    id from the device's name, so an id that starts with a device's name
    (as an id) is that device's, the longest name winning; otherwise the
    ids that share their first two words are one device that is gone,
    called by the words they all start with. ``present`` is whether the
    device is still in the house (a card pointing at readings it no longer
    has) or gone with them; ``device`` is its registry row when present."""
    slugs = {}
    for dev in house.devices.values():
        slug = _slug(house.device_name(dev))
        if slug and slug not in slugs:
            slugs[slug] = dev
    order: list[tuple] = []
    groups: dict[tuple, dict] = {}

    def put(key: tuple, name: str, present: bool, eid: str,
            device: dict | None = None) -> None:
        if key not in groups:
            groups[key] = {"name": name, "members": [], "present": present,
                           "device": device}
            order.append(key)
        groups[key]["members"].append(eid)

    for eid in dead:
        dev = house.device_of(eid)
        if dev and dev.get("id"):
            put(("dev", str(dev["id"])), house.device_name(dev), True, eid,
                dev)
            continue
        obj = eid.partition(".")[2]
        owner = max((s for s in slugs if obj == s or obj.startswith(s + "_")),
                    key=len, default="")
        if owner:
            dev = slugs[owner]
            put(("dev", str(dev.get("id") or owner)), house.device_name(dev),
                True, eid, dev)
            continue
        words = _id_words(eid)
        put(("gone", tuple(words[:2]) if len(words) >= 3 else tuple(words)),
            "", False, eid)
    out = []
    for key in order:
        group = groups[key]
        if key[0] == "gone":
            split = [_id_words(m) for m in group["members"]]
            common = []
            for words in zip(*split):
                if len(set(words)) != 1:
                    break
                common.append(words[0])
            group["name"] = " ".join(common or split[0])
        out.append(group)
    return out


def personal(house: House, device: dict | None) -> bool:
    """Whether a device is something a person carries (a phone through the
    companion app), read off the registry: one of its entities comes from,
    or the device is identified by, a personal platform. Its own readings
    gone from a dashboard touch nothing in the house."""
    if not isinstance(device, dict) or not device.get("id"):
        return False
    for ident in device.get("identifiers") or ():
        if isinstance(ident, (list, tuple)) and ident \
                and str(ident[0]) in PERSONAL_PLATFORMS:
            return True
    return any(row.get("device_id") == device["id"]
               and str(row.get("platform") or "") in PERSONAL_PLATFORMS
               for row in house.entities)


def _personal_owner(house: House, dead: list[str]) -> str:
    """The personal device every missing entity belonged to, by name, or
    "" when any of them was the house's or an automation, script or scene
    still names one (then it touches the house: `auto.dead_ref`'s)."""
    groups = by_device(house, dead)
    if len(groups) != 1 or not personal(house, groups[0]["device"]):
        return ""
    configs = [*(house.snap.get("automations") or ()),
               *((house.snap.get("scripts") or {}).values()
                 if isinstance(house.snap.get("scripts"), dict) else ()),
               *(house.snap.get("scenes") or ())]
    if set(dead) & house.entity_refs(configs):
        return ""
    return groups[0]["name"]


def _removal_fix(dead: list[str], titles, personal_name: str) -> str:
    """The change the row proposes, naming the dashboard and every entity
    whose card goes (as many as fit; the rest are on the card's list)."""
    where = ("the " + join_names([f"'{t}'" for t in titles], 8, budget=150)
             + (" dashboard" if len(list(titles)) == 1 else " dashboards"))
    ids = join_names(dead, limit=len(dead), budget=360)
    if personal_name:
        return (f"Remove the cards showing {ids} from {where}: they are "
                f"{personal_name}'s own readings and nothing in the house "
                "uses them. Leave every other card as it is.")
    return (f"Edit {where}: point the cards showing {ids} at the entities "
            "that replaced them, or remove those cards. Leave every other "
            "card as it is.")


def _device_words(group: dict) -> str:
    """"the energy monitor" for a gone device named from its ids, a
    device's own name as the house writes it otherwise."""
    return group["name"] if group["present"] else f"the {group['name']}"


def _on_dashboards(titles) -> str:
    titles = list(titles)
    if len(titles) == 1:
        title = titles[0]
        return (f"the {title}" if title.casefold().endswith("dashboard")
                else f"the {title} dashboard")
    return f"{len(titles)} dashboards"


def headline(house: House, dead: list[str], titles) -> str:
    """What the card says: which dashboard, and which device in household
    words ("The energy monitor cards on the Kitchen dashboard point at a
    device that is gone"). Shown over the row's `text`, which stays its key
    (#1326), so it may name what moves from pass to pass."""
    groups = by_device(house, dead)
    where = _on_dashboards(titles)
    if len(groups) == 1 and not groups[0]["present"] \
            and len(groups[0]["members"]) == 1:
        # One entity of no known device: a scene, a helper. Said by what
        # it was, never called a device.
        lead = ("A card on" if len(list(titles)) == 1 else "Cards on")
        verb = "points" if lead == "A card on" else "point"
        return (f"{lead} {where} {verb} at "
                f"{house.label(groups[0]['members'][0])}, which is gone")
    if len(groups) == 1:
        group = groups[0]
        cards = "card" if len(group["members"]) == 1 else "cards"
        verb = "points" if cards == "card" else "point"
        if group["present"]:
            return (f"The {group['name']} {cards} on {where} {verb} at "
                    "readings that device no longer has")
        return (f"The {group['name']} {cards} on {where} {verb} at a "
                "device that is gone")
    gone = not any(g["present"] for g in groups)
    if len(groups) == 2:
        names = " and ".join(g["name"] for g in groups)
        return (f"The {names} cards on {where} point at "
                + ("devices that are gone" if gone else
                   "entities that are gone"))
    return (f"Cards on {where} point at {len(groups)} devices that are gone"
            if gone else
            f"Cards on {where} point at missing entities of "
            f"{len(groups)} devices")


def missing_line(house: House, dead: list[str], budget: int = 160) -> str:
    """"Missing: 7 sensors from the energy monitor and 2 entities from
    Garage heater plug." — one part a device, whole parts only."""
    parts = [house.label(g["members"][0])
             if not g["present"] and len(g["members"]) == 1 else
             f"{_kind_of(g['members'], len(g['members']))} from "
             f"{_device_words(g)}" for g in by_device(house, dead)]
    listed = join_names(parts, limit=len(parts), budget=budget)
    if ", " in listed and " more" not in listed:
        head, _, last = listed.rpartition(", ")
        listed = f"{head} and {last}"
    return f"Missing: {listed}."


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
        # Only a personal device's own readings (a phone's health sensors):
        # nothing in the house is touched, so it is a tidy-up, not a
        # warning, and the proposal is the removal of exactly those cards.
        owner = _personal_owner(house, dead)
        out.append({
            "text": text[:1].upper() + text[1:],
            # One label a device, numbered copies merged, every one said
            # while they fit (#1334).
            "detail": ("Missing: " + entity_list(house, dead, budget=240)
                       + ". Shown on "
                       + ("the dashboard " if len(titles) == 1 else "the dashboards ")
                       + join_names(quoted, 8, budget=150) + ", where "
                       + ("it renders" if len(dead) == 1 else "each one renders")
                       + " as a red 'entity not available' tile."),
            "fix": _removal_fix(dead, titles, owner),
            # What the card shows (#1326): the dashboard and the device in
            # household words, over `text` and `detail`, which stay what
            # the row is keyed and compared by.
            "headline": headline(house, dead, titles),
            "shown_detail": ((missing_line(house, dead) + " Each shows"
                              if len(dead) > 1 else "It shows")
                             + " as a red "
                             "'entity not available' tile"
                             + ("." if len(titles) == 1 else
                                ", on " + join_names(quoted, 8, budget=150)
                                + ".")
                             + (f" They are {owner}'s own readings; nothing "
                                "in the house uses them." if owner else "")),
            "severity": "info" if owner else "warning",
            "fixable": True,
            "entity_id": dead[0],
            "evidence": evidence_for(dead, "no longer exists"),
            # Every missing entity, for the card's Show all and so a Wrong
            # answers each (the sentence names only what fits).
            "items": dead,
        })
    return out


CHECKS = [
    {"id": "org.dashboard_dead_ref", "area": "dashboards",
     "title": "Dashboards showing missing entities",
     "needs": ("states", "registry", "dashboards"), "run": dead_ref},
]
