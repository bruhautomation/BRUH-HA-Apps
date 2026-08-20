"""The light map, written out for a model to read.

The Claude director used to be told this much about the room:

    FIXTURES (role: count, left-to-right x positions):
      lamp: 3 at x=[0.10, 0.50, 0.90]

which is three facts short of being able to design anything. It cannot
name a light (no ids, so `select.ids` was in the schema and unusable), it
cannot tell one lamp from another (no labels — "the lamp behind the
couch" is a different instrument from "the lamp by the door" and the
model was shown neither), it cannot reason about depth (no y, while
`order` offers `y`, `-y`, `snake` and `center_out`), and it was never
told which zones exist even though `select.zones` and `order: "zone"`
both key on them. A vocabulary the prompt does not ground is a vocabulary
the model either avoids or hallucinates, and both showed: every generated
script selected by role, because role was the only thing it had.

So this is the room, once, in the form a reader needs it: a row per
light, the zones that exist, and the orderings **already worked out**.
That last part is deliberate. Sorting a dozen floats by hand is exactly
the sort of arithmetic a language model does badly and confidently, and
the whole value of the map is the travel order — so the sort happens
here, in Python, and the prompt carries the answer rather than the
homework.

One description, two callers: the show director and the single-effect
writer both open with it, because "what can I drive, and where is it"
is the same question whether you are writing four minutes or four bars.
"""
from __future__ import annotations

import math

from . import palettes

# How a role reads as an instrument. The rules themselves live in
# palettes.ROLE_RULES (and are enforced in the compiler whatever a script
# asks for); this is the sentence that explains one to a reader, so a
# model chooses a fixture for what it is rather than for its name.
ROLE_NOTES = {
    "candle": "ambience — warm and low, capped at 45% and kept out of "
              "strobes and hard pulses",
    "downlight": "ceiling light — the beat carrier, full range",
    "lamp": "table or floor lamp — the beat carrier, full range",
    "strip": "light strip — best for motion: sweeps, chases, rainbows",
    "party": "party light on a SWITCH — on or off only, no colour, and "
             "slow to react (a switch, not a bulb)",
    "laser": "laser on a SWITCH — on or off only, no colour, and slow to "
             "react (a switch, not a bulb)",
}


def _fmt(value: float) -> str:
    return f"{value:.2f}"


def _order_by(fixtures: list[dict], key) -> list[dict]:
    """A total order, always. Ties break on id so the answer is the same
    on every run — a show somebody liked on Friday is the show they get on
    Saturday, and that promise starts here rather than in the effect."""
    return sorted(fixtures, key=lambda f: (key(f), f.get("id") or ""))


def _nearest_neighbour(fixtures: list[dict]) -> list[dict]:
    """A walk through the room, each light to the closest one not yet
    visited, starting from the leftmost.

    This is the ordering a chase *wants* when a room is not a line — the
    map's own `snake` covers a grid, but a real living room is usually a
    loop of lamps around a sofa, and 'left to right' throws that away.
    Greedy and deterministic; it is a description for a reader, not a
    travelling-salesman solution.
    """
    remaining = _order_by(fixtures, lambda f: f.get("x", 0.5))
    if not remaining:
        return []
    walk = [remaining.pop(0)]
    while remaining:
        current = walk[-1]
        nearest = min(remaining, key=lambda f: (
            math.hypot(f.get("x", 0.5) - current.get("x", 0.5),
                       f.get("y", 0.5) - current.get("y", 0.5)),
            f.get("id") or ""))
        remaining.remove(nearest)
        walk.append(nearest)
    return walk


def zones(fixtures: list[dict]) -> list[str]:
    """The zone names in use, in a stable order. Unzoned lights are not a
    zone — an empty string is the absence of an answer, and offering it as
    a selectable group would be offering "the ones I never got round to"
    as a room."""
    found = {str(f.get("zone") or "").strip()
             for f in fixtures if str(f.get("zone") or "").strip()}
    return sorted(found)


def _names(fixtures: list[dict]) -> str:
    return ", ".join(f.get("label") or f.get("id") or "?" for f in fixtures)


def describe(fixtures: list[dict], *, orders: bool = True) -> str:
    """The room as prompt text. Empty map gets a sentence saying so."""
    if not fixtures:
        return ("THE ROOM: no lights are on the map, so nothing can be "
                "driven. (The Light Map tab is where lights are placed.)")

    lines = [
        "THE ROOM — every light BRight can drive, and where it is.",
        "",
        "Positions are a floor plan in 0..1 as the person placed them by "
        "hand: x runs left (0) to right (1), y runs near/front (0) to "
        "far/back (1). They describe the real room, so an effect that "
        "travels by x really does cross it.",
        "",
        "  id / name / role / zone / x / y / how it is driven",
    ]
    for fixture in _order_by(fixtures, lambda f: (f.get("role") or "",
                                                  f.get("x", 0.5))):
        role = fixture.get("role") or "?"
        zone = fixture.get("zone") or "—"
        channel = ("LIFX bulb over the LAN, instant"
                   if fixture.get("kind") == "lifx"
                   else "Home Assistant switch, ~200ms late")
        lines.append(
            f"  {fixture.get('id')} | {fixture.get('label') or fixture.get('id')}"
            f" | {role} | {zone} | x={_fmt(fixture.get('x', 0.5))}"
            f" | y={_fmt(fixture.get('y', 0.5))} | {channel}")
        if fixture.get("reachable") is False:
            lines[-1] += "  (NOT ANSWERING right now)"

    lines += ["", "WHAT EACH ROLE IS FOR:"]
    for role in sorted({f.get("role") for f in fixtures if f.get("role")}):
        note = ROLE_NOTES.get(role, "")
        count = sum(1 for f in fixtures if f.get("role") == role)
        lines.append(f"  {role} ({count}) — {note}")

    zone_names = zones(fixtures)
    lines.append("")
    if zone_names:
        lines.append("ZONES on this map (a zone is a named group of lights, "
                     "usually a room or a cluster):")
        for name in zone_names:
            members = [f for f in fixtures
                       if str(f.get("zone") or "").strip() == name]
            lines.append(f"  {name} ({len(members)}): {_names(members)}")
        unzoned = [f for f in fixtures if not str(f.get("zone") or "").strip()]
        if unzoned:
            lines.append(f"  (not in any zone: {_names(unzoned)})")
        lines.append('  Select {"zones": ["' + zone_names[0] + '"]} to drive '
                     'one area, or order:"zone" to travel zone by zone.')
    else:
        lines.append("ZONES: none defined on this map — do not use "
                     '`select.zones` or order:"zone", there is nothing for '
                     "them to match.")

    if orders:
        movers = [f for f in fixtures
                  if not palettes.ROLE_RULES.get(f.get("role"), {}).get("switch")]
        lines += ["", "TRAVEL ORDERS, already worked out for you — a chase, "
                  "sweep or build steps through its selection in the order "
                  "you name, so these are what those orders will actually do "
                  "(colour-capable lights only; switches do not travel):"]
        if movers:
            lines += [
                f'  order:"x"  (left to right): {_names(_order_by(movers, lambda f: f.get("x", 0.5)))}',
                f'  order:"y"  (front to back): {_names(_order_by(movers, lambda f: f.get("y", 0.5)))}',
                f"  around the room (each to its nearest neighbour — often the "
                f"best-looking chase in a room that is not a straight line; "
                f'write it as order:"listed" with select.ids in this order): '
                f"{_names(_nearest_neighbour(movers))}",
            ]
            xs = [f.get("x", 0.5) for f in movers]
            ys = [f.get("y", 0.5) for f in movers]
            lines.append(
                f"  they span x {_fmt(min(xs))}..{_fmt(max(xs))}, "
                f"y {_fmt(min(ys))}..{_fmt(max(ys))} — "
                + ("spread across the room, so travel reads clearly"
                   if max(xs) - min(xs) > 0.4
                   else "clustered close together, so a chase will read as a "
                        "flicker more than as movement"))
            if len(movers) < 3:
                lines.append(f"  NOTE: only {len(movers)} light(s) can take "
                             "colour. A chase across fewer than three is a "
                             "flicker — use theater (alternating) instead.")
        else:
            lines.append("  none — every light on this map is a switch.")

    return "\n".join(lines)
