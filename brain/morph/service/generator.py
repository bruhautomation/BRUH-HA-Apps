"""The first dashboard, built from the house's own registries.

Nobody should have to lay out a dashboard by hand before Morph is worth
opening, so the first ``dashboard.yaml`` is written from what Home
Assistant already knows: floors, areas, and what each area holds. It is a
STARTING POINT — the person changes it in Edit, brAIn changes it when told,
and the learning loop suggests what to change next — so it is deliberately
plain and deterministic: the same house always generates the same file, and
nothing here asks a model.

The shape follows the design (docs/design/morph-ui.md §2):

* **Floors** are the floor registry, ground floor first, then up, then
  down; areas with no floor go on a floor of their own. A house with no
  floors at all is one floor named after the house.
* **Rooms** hold what a person controls there: scenes as words, then lights,
  fans and blinds, switches, media, cameras.
* **Whole house** holds the systems: Climate (thermostats and every
  temperature and humidity reading, overlaid), Security (alarm, locks,
  doors and windows, who is home).

What is left out, and why: anything hidden or disabled, anything with an
entity category (configuration and diagnostics are not things people use),
brAIn's and Morph's own entities, and domains a dashboard has no business
drawing (updates, automations, numbers and selects).
"""
from __future__ import annotations

import re

import store

ROOM_DOMAINS = ("scene", "light", "fan", "cover", "switch", "input_boolean",
                "media_player", "camera", "vacuum", "script")
OPENING_CLASSES = {"door", "window", "garage_door", "opening"}
SAFETY_CLASSES = {"moisture", "smoke", "gas", "carbon_monoxide"}
SELF_PLATFORMS = {"brain", "morph"}
OUTDOOR = re.compile(r"\b(outside|outdoor|garden|yard|porch|patio|driveway|deck|balcony|pool)\b", re.I)
MAX_CARDS = 24


def _name(state: dict | None, eid: str) -> str:
    attrs = (state or {}).get("attributes") or {}
    return str(attrs.get("friendly_name") or eid.split(".", 1)[1].replace("_", " ").title())


# What may sit between a room's name and the rest of a card's name: spaces,
# and the separators people type into friendly names ("Kitchen - Bread
# Stretch", "Kitchen: Kettle", "Kitchen | Lamp"). The panel's shortName
# (frontend/util.js) strips the same set, so a card the generator left unnamed
# reads the same on the page.
SEPARATORS = " \t-\u2013\u2014:|/\u00b7,"
_SEP_RUN = "[" + re.escape(SEPARATORS) + "]+"


def _short(name: str, area: str) -> str:
    """Drop the room's name from the front of a card's name: "Kitchen Cans"
    in the Kitchen is "Cans", and "Kitchen - Bread Stretch" is "Bread
    Stretch" — the separator goes with the room, or the card reads "- Bread
    Stretch". The room has to end at a separator: "Kitchenette Lamp" in the
    Kitchen is somebody else's room."""
    if not area:
        return name
    m = re.match(re.escape(area) + _SEP_RUN, name, re.I)
    if not m:
        return name
    rest = name[m.end():].strip(SEPARATORS)
    return rest[:1].upper() + rest[1:] if rest else name


def _distinct(cards: list[dict], full: dict[str, str]) -> None:
    """Two cards in one section must not read the same.

    Shortening is per card, so two players called "Kitchen Mini" and
    "Kitchen mini" (a speaker and its Music Assistant copy) both came out
    "Mini". Where a shortened name repeats, every card sharing it goes back
    to its full friendly name, written on the card; where the full names repeat too, the part of
    the entity id the name does not already say is added ("Mini (mini 2)"),
    because a page with two identical words on it cannot be told apart."""
    def shown(card: dict) -> str:
        return card.get("name") or full[card["entity"]]

    groups: dict[str, list[dict]] = {}
    for card in cards:
        groups.setdefault(shown(card).lower(), []).append(card)
    for same in groups.values():
        if len(same) < 2:
            continue
        for card in same:
            # Written out, not left blank: the panel shortens an unnamed card
            # by the same rule, and would put the collision straight back.
            card["name"] = full[card["entity"]]
    groups = {}
    for card in cards:
        groups.setdefault(shown(card).lower(), []).append(card)
    for same in groups.values():
        if len(same) < 2:
            continue
        tails = {}
        for card in same:
            words = set(re.findall(r"[a-z0-9]+", full[card["entity"]].lower()))
            object_id = card["entity"].split(".", 1)[1]
            tails[card["entity"]] = " ".join(w for w in object_id.split("_") if w and w not in words)
        unique = len(set(tails.values())) == len(tails)
        for card in same:
            name, tail = full[card["entity"]], tails[card["entity"]]
            if not unique:
                # The ids say nothing apart either: the kind of thing does.
                tail = " ".join(x for x in (card["entity"].split(".", 1)[0].replace("_", " "), tail) if x)
            card["name"] = f"{name} ({tail})" if tail else name


def _floor_order(floor: dict) -> tuple:
    level = floor.get("level")
    if level is None:
        return (2, 0, floor.get("name") or "")
    return (0 if level >= 0 else 1, abs(level), floor.get("name") or "")


def build(house: dict) -> dict:
    states = {s["entity_id"]: s for s in house.get("states") or [] if isinstance(s, dict) and s.get("entity_id")}
    devices = {d["id"]: d for d in house.get("devices") or [] if isinstance(d, dict) and d.get("id")}
    areas = {a["area_id"]: a for a in house.get("areas") or [] if isinstance(a, dict) and a.get("area_id")}
    floors = sorted([f for f in house.get("floors") or [] if isinstance(f, dict) and f.get("floor_id")],
                    key=_floor_order)

    by_area: dict[str, list[str]] = {}
    house_wide: list[str] = []
    seen: set[str] = set()
    for ent in house.get("entities") or []:
        if not isinstance(ent, dict):
            continue
        eid = ent.get("entity_id") or ""
        if (not eid or eid not in states or ent.get("hidden_by") or ent.get("disabled_by")
                or ent.get("entity_category") or ent.get("platform") in SELF_PLATFORMS):
            continue
        seen.add(eid)
        area = ent.get("area_id") or (devices.get(ent.get("device_id") or "") or {}).get("area_id")
        if area in areas:
            by_area.setdefault(area, []).append(eid)
        else:
            house_wide.append(eid)
    # States with no registry entry (YAML entities with no unique_id) still
    # belong to the house; they just have no room.
    house_wide += [e for e in states if e not in seen]

    def cls(eid: str) -> str:
        return str(((states.get(eid) or {}).get("attributes") or {}).get("device_class") or "")

    def is_group(eid: str) -> bool:
        members = ((states.get(eid) or {}).get("attributes") or {}).get("entity_id")
        return isinstance(members, list) and len(members) > 1

    global_scenes: list[str] = []
    climate: list[str] = []
    temps: list[str] = []
    hums: list[str] = []
    security: list[str] = []
    openings: list[str] = []
    people: list[str] = []
    weather: list[str] = []

    def collect_house(eid: str) -> None:
        domain = eid.split(".", 1)[0]
        dc = cls(eid)
        if domain == "climate":
            climate.append(eid)
        elif domain == "sensor" and dc == "temperature":
            temps.append(eid)
        elif domain == "sensor" and dc == "humidity":
            hums.append(eid)
        elif domain in ("lock", "alarm_control_panel"):
            security.append(eid)
        elif domain == "binary_sensor" and dc in OPENING_CLASSES | SAFETY_CLASSES:
            openings.append(eid)
        elif domain == "person":
            people.append(eid)
        elif domain == "weather":
            weather.append(eid)

    def room_section(area: dict, eids: list[str], index: int) -> dict | None:
        aname = area.get("name") or area["area_id"]
        buckets: dict[str, list[dict]] = {k: [] for k in
                                          ("scenes", "lights", "motion", "switches", "media", "cameras")}
        scenes: list[str] = []
        for eid in sorted(eids, key=lambda e: _name(states.get(e), e).lower()):
            collect_house(eid)
            domain = eid.split(".", 1)[0]
            if domain not in ROOM_DOMAINS:
                continue
            name = _short(_name(states.get(eid), eid), aname)
            card = {"entity": eid}
            if name != _name(states.get(eid), eid):
                card["name"] = name
            if domain == "scene":
                scenes.append(eid)
            elif domain == "light":
                if is_group(eid):
                    card["type"] = "light_group"
                buckets["lights"].append(card)
            elif domain in ("fan", "cover"):
                buckets["motion"].append(card)
            elif domain in ("switch", "input_boolean", "script", "vacuum"):
                buckets["switches"].append(card)
            elif domain == "media_player":
                buckets["media"].append(card)
            elif domain == "camera":
                buckets["cameras"].append(card)
        _distinct([c for key in ("lights", "motion", "switches", "media", "cameras")
                   for c in buckets[key]],
                  {e: _name(states.get(e), e) for e in eids})
        groups = []
        if scenes:
            groups.append({"cards": [{"type": "scenes", "entities": scenes[:8]}]})
        # Fans and blinds are how a room feels rather than how it is lit, and
        # the prototype keeps them apart under a quiet "Comfort" label.
        labels = {"motion": "Comfort"}
        for key in ("lights", "motion", "switches", "media", "cameras"):
            if buckets[key]:
                group = {"cards": buckets[key]}
                if key in labels:
                    group["label"] = labels[key]
                groups.append(group)
        count = sum(len(g["cards"]) for g in groups)
        if not count:
            return None
        while count > MAX_CARDS and groups:
            groups[-1]["cards"].pop()
            if not groups[-1]["cards"]:
                groups.pop()
            count -= 1
        return {"id": "s_" + store.slug(area["area_id"]), "title": aname,
                "area": area["area_id"], "color": store.COLORS[index % len(store.COLORS)],
                "width": 3 if count > 8 else 2, "groups": groups}

    out_floors: list[dict] = []
    index = 0
    placed: set[str] = set()

    def floor_of(floor_id: str | None, title: str) -> None:
        nonlocal index
        sections = []
        for area in sorted(areas.values(), key=lambda a: (a.get("name") or "").lower()):
            if (area.get("floor_id") or None) != floor_id or area["area_id"] in placed:
                continue
            placed.add(area["area_id"])
            sec = room_section(area, by_area.get(area["area_id"], []), index)
            if sec:
                sections.append(sec)
                index += 1
        if sections:
            out_floors.append({"title": title, "sections": sections})

    if floors and house.get("floors_read", True):
        for fl in floors:
            floor_of(fl["floor_id"], fl.get("name") or "Floor")
        floor_of(None, "Other rooms")
    else:
        # No floors: rooms go indoors or outside by name, which is a guess
        # made where being wrong costs a section in the wrong place.
        indoor = [a for a in areas.values() if not OUTDOOR.search(a.get("name") or "")]
        outdoor = [a for a in areas.values() if OUTDOOR.search(a.get("name") or "")]
        for title, group in (("Home", indoor), ("Outside", outdoor)):
            sections = []
            for area in sorted(group, key=lambda a: (a.get("name") or "").lower()):
                sec = room_section(area, by_area.get(area["area_id"], []), index)
                if sec:
                    sections.append(sec)
                    index += 1
            if sections:
                out_floors.append({"title": title, "sections": sections})

    for eid in house_wide:
        collect_house(eid)
        if eid.startswith("scene."):
            global_scenes.append(eid)

    systems = []
    clim_groups = []
    if weather:
        clim_groups.append({"cards": [{"entity": weather[0]}]})
    if climate:
        clim_groups.append({"cards": [{"entity": e} for e in sorted(climate)[:6]]})
    if len(temps) >= 2:
        clim_groups.append({"cards": [{"type": "readings", "entities": sorted(temps)[:12],
                                       "name": "Temperature"}]})
    elif temps:
        clim_groups.append({"cards": [{"entity": temps[0]}]})
    if len(hums) >= 2:
        clim_groups.append({"cards": [{"type": "readings", "entities": sorted(hums)[:12],
                                       "name": "Humidity"}]})
    if clim_groups:
        systems.append({"id": "s_climate", "title": "Climate", "color": "sky", "width": 3,
                        "groups": clim_groups})
    sec_groups = []
    if security:
        sec_groups.append({"cards": [{"entity": e} for e in sorted(security)[:8]]})
    if openings:
        sec_groups.append({"label": "Doors and windows", "cards": [
            {"type": "list", "entities": sorted(openings)[:20], "name": "Doors and windows"}]})
    if people:
        sec_groups.append({"label": "People", "cards": [{"entity": e} for e in sorted(people)[:6]]})
    if sec_groups:
        systems.append({"id": "s_security", "title": "Security", "color": "rose", "width": 2,
                        "groups": sec_groups})
    if systems:
        out_floors.append({"title": "Whole house", "sections": systems})

    dash = {"title": "Home", "story": True, "ask": True, "coming_up": True,
            "scenes": sorted(global_scenes)[:8], "floors": out_floors}
    dash, _ = store.normalize(dash)
    return dash
