"""Emergency playbooks: the automation brAIn would write for a bad night.

Smoke, a leak, a freeze with the heating gone. Each is an event the house
can already detect and nobody has written the response to, because
writing it means listing every light, every thermostat and every blind by
hand and then never testing it.

**brAIn never runs a playbook.** It writes one, offers it as a proposal,
and Home Assistant runs it if — and only if — the person accepted it.
That is the whole difference between this and the capability page's
"acting without asking": the asking happens once, in advance, on a card
that lists every entity the automation would touch by name.

**Composed deterministically, from the registries.** No Claude run picks
which valve closes or which lights come on: a model choosing that is a
guess wearing a config, and it is a guess nobody can check afterwards
because the automation looks the same either way. Claude is used for
exactly one optional thing — the paragraph on the card that says what
this does in plain English — and a run that fails leaves the
deterministic sentence in place.

**No playbook unlocks anything, ever.** The capability page lists doors
unlocked under smoke, and it is wrong: a lock is the canonical protected
entity, a smoke detector is the sensor in a house most likely to fire on
burnt toast, and unlocking the house on a false alarm at three in the
morning is the worst outcome anything on this page could produce. The
front door being locked has never been what stopped somebody leaving a
burning building from the inside. `LOCK_DOMAINS` is refused across every
generated action and `tests/test_playbooks.py` asserts it over the whole
config rather than over the branch that would have written it.

**Protection is asked at the producer as well as the writer.** A card
offering to close a valve `automation_writer` will refuse to write is a
wasted no — the same reason `_offer_routines` reads the patterns — so a
protected entity is dropped from the config and **listed on the card as
skipped**, which is the honest version: you can see that brAIn knows the
valve is there and knows it may not touch it.

**A playbook with nothing left to do is not offered.** Every action
removed by protection or absence leaves a notification, and a
notification is not a playbook — except for `freeze`, which is a
notification playbook by design, because nothing here may turn a boiler
on.

**There is no trial button on one.** A trial is a replay of the week you
lived through, and replaying a smoke alarm over last month answers a
question about a month with no smoke alarm in it. Saying that on the card
is better than a button that cannot help.

Stdlib only; the registries arrive in the checks snapshot.
"""
from __future__ import annotations

import re

from checks._util import House

# Every class this file knows how to write, in the order they are offered.
CLASSES = ("smoke", "leak", "freeze")

# The one refusal that is not about this house. See the module docstring.
LOCK_DOMAINS = ("lock", "alarm_control_panel")

SMOKE_CLASSES = ("smoke", "carbon_monoxide", "gas")
LEAK_CLASSES = ("moisture",)
# A blind, a shade or a curtain opens. A garage door and a window do not:
# one is an exit nobody drives through in a fire and the other lets air
# in, and neither is what "get the light in and be seen from outside" is
# about.
OPENABLE_COVERS = ("blind", "shade", "curtain")

# What a switch has to say for brAIn to believe it is a water shutoff.
# `valve` as a DOMAIN always qualifies — that is what the domain is — but
# a switch is named by a person, so the word has to be the whole word:
# `domain` contains "main" and so does `switch.main_bedroom_lamp`, and a
# leak playbook that turns the bedroom lamp off is a playbook somebody
# deletes. "main" alone is deliberately NOT here for that reason; a
# shutoff called only "Main" is missed, which costs a line on a card
# somebody can read, where the other way round costs trust.
WATER_WORDS = ("water", "valve", "stopcock", "mains", "shutoff")

# The temperature at which water in an outside wall starts to be at risk,
# well before a room's thermometer reads freezing. `checks/thermal.py`
# uses the same floor and for the same reason.
FREEZE_C = 5.0
FREEZE_F = 41.0
# How long the heating has to have been doing nothing before this is a
# failure rather than a thermostat between cycles.
IDLE_MINUTES = 30

# How many targets a card lists before it counts the rest. The CONFIG is
# never capped — an emergency playbook that turns on sixty of eighty
# lights is a playbook that was guessed at — so this is a rendering
# limit, and the count beside it is the whole number.
CARD_MAX = 12

# One paragraph, and the model is not asked to choose anything.
DESCRIBE_TIMEOUT_S = 90
DESCRIBE_MAX_TURNS = 2
DESCRIBE_MAX_CHARS = 600

SYSTEM = """You explain one emergency automation to the person who lives
in the house it was written for.

You are given exactly what it does: what sets it off, and every entity it
acts on. Say it back in ONE short paragraph of plain sentences — what
happens, in the order it happens, and nothing else.

Rules that matter more than style:
- Say only what the list says. Never add an action, a device or a
  safeguard that is not in it.
- No greeting, no sign-off, no markdown, no bullet points, no headings.
- Do not reassure anybody and do not tell them what to do about it.
- Do not say whether this is a good idea. They are about to decide that.
"""


def _tokens(text: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", str(text or "").lower()) if t}


def is_lock(entity_id: str) -> bool:
    """Whether this is the one thing no playbook may act on."""
    return str(entity_id or "").split(".", 1)[0] in LOCK_DOMAINS


# ---------------------------------------------------------------------------
# Finding the entities
# ---------------------------------------------------------------------------

def _row(house: House, eid: str) -> dict:
    return {"entity_id": eid, "name": house.name(eid),
            "area": house.area_of(eid)}


def _pick(house: House, predicate) -> list[dict]:
    """Every enabled entity the predicate takes, by entity id.

    Sorted, because the config is what `proposals.key_for` hashes: a set
    that came out in a different order would re-offer, under a new key,
    a playbook somebody has already declined.
    """
    out = []
    for eid, st in sorted((house.states or {}).items()):
        if is_lock(eid) or not house.enabled(eid):
            continue
        if predicate(eid, (st.get("attributes") or {})):
            out.append(_row(house, eid))
    return out


def _domain_class(domain: str, classes: tuple[str, ...]):
    def pick(eid: str, attrs: dict) -> bool:
        return (eid.startswith(f"{domain}.")
                and str(attrs.get("device_class") or "") in classes)
    return pick


def _water_shutoff(eid: str, attrs: dict) -> bool:
    if eid.startswith("valve."):
        return True
    if not eid.startswith("switch."):
        return False
    words = _tokens(eid.split(".", 1)[1]) | _tokens(attrs.get("friendly_name"))
    return bool(words & set(WATER_WORDS))


# ---------------------------------------------------------------------------
# Protection
# ---------------------------------------------------------------------------

def _split(rows: list[dict], patterns: list[str]) -> tuple[list[dict], list[dict]]:
    """`(kept, skipped)`. A skipped row keeps its name, and why."""
    import automation_writer  # noqa: PLC0415 — panel-local; one answer to
                              # "is this protected", asked at both ends

    kept, skipped = [], []
    for row in rows:
        if automation_writer.is_protected(row["entity_id"], patterns):
            skipped.append({**row, "reason": "protected"})
        else:
            kept.append(row)
    return kept, skipped


def _ids(rows: list[dict]) -> list[str]:
    return [r["entity_id"] for r in rows]


def _group(verb: str, service: str, rows: list[dict], to: str = "",
           data: dict | None = None) -> dict:
    return {"verb": verb, "service": service, "to": to,
            "data": dict(data or {}), "targets": rows}


def _step(group: dict) -> dict:
    step: dict = {"service": group["service"],
                  "target": {"entity_id": _ids(group["targets"])}}
    if group.get("data"):
        step["data"] = dict(group["data"])
    return step


# ---------------------------------------------------------------------------
# Where to say it
# ---------------------------------------------------------------------------

def notify_targets(snap: dict, configured: str = "") -> list[str]:
    """The notify services a playbook should shout down.

    The configured one if there is one — it is where every other message
    brAIn sends already goes — and every companion app otherwise, because
    an emergency is the one message that should reach whoever is holding
    a phone rather than whoever set the option.
    """
    services = {str(s).lower() for s in (snap.get("services") or set())}
    name = str(configured or "").strip().removeprefix("notify.")
    if name and f"notify.{name}" in services:
        return [f"notify.{name}"]
    if name:
        return [f"notify.{name}"]     # configured and unlisted is still theirs
    return sorted(s for s in services
                  if s.startswith("notify.mobile_app_"))


def _notify_steps(targets: list[str], title: str, message: str) -> list[dict]:
    return [{"service": svc, "data": {"title": title, "message": message}}
            for svc in targets]


def _where(rows: list[dict]) -> str:
    """The template that names the area the sensor that fired is in.

    A playbook watches every detector in the house, so which room it is
    cannot be written down at compose time — only looked up when it
    fires. `area_name` is Home Assistant's own function and
    `trigger.entity_id` is what a state trigger sets.
    """
    if not rows:
        return "the house"
    return "{{ area_name(trigger.entity_id) or 'the house' }}"


# ---------------------------------------------------------------------------
# The three playbooks
# ---------------------------------------------------------------------------

NO_UNLOCK = ("This will not unlock any door and will not disarm the alarm "
             "— a false smoke alarm at 3am must not open the house.")

NO_TRIAL = ("There is no week to try this against: a trial replays the days "
            "you have already lived, and those days had no emergency in "
            "them. Rehearse it instead, or set the detector off on purpose "
            "and read the automation's trace afterwards.")


def _smoke(house: House, snap: dict, patterns: list[str],
           notify: list[str]) -> dict | None:
    sensors = _pick(house, _domain_class("binary_sensor", SMOKE_CLASSES))
    if not sensors:
        return None

    lights, skipped = _split(_pick(house, lambda e, a: e.startswith("light.")),
                             patterns)
    climate, s2 = _split(_pick(house, lambda e, a: e.startswith("climate.")),
                         patterns)
    covers, s3 = _split(
        _pick(house, _domain_class("cover", OPENABLE_COVERS)), patterns)
    skipped += s2 + s3

    groups = []
    if lights:
        groups.append(_group("Every light to full brightness",
                             "light.turn_on", lights, "on",
                             {"brightness_pct": 100}))
    if climate:
        groups.append(_group("Heating and cooling off",
                             "climate.set_hvac_mode", climate, "off",
                             {"hvac_mode": "off"}))
    if covers:
        groups.append(_group("Blinds and curtains open",
                             "cover.open_cover", covers, "open"))
    if not groups:
        return None

    where = _where(sensors)
    steps = [_step(g) for g in groups] + _notify_steps(
        notify, "Smoke or CO alarm",
        f"Smoke or CO detected in {where}. Lights are on full, heating is "
        "off, blinds are open.")
    return {
        "class": "smoke",
        "title": "Emergency playbook: smoke or carbon monoxide",
        "sensors": sensors,
        "groups": groups,
        "skipped": skipped,
        "notify": notify,
        "note": NO_UNLOCK,
        "config": {
            "trigger": [{"platform": "state",
                         "entity_id": _ids(sensors), "to": "on"}],
            "action": steps,
            "mode": "single",
            "id": "brain_playbook_smoke",
        },
    }


def _leak(house: House, snap: dict, patterns: list[str],
          notify: list[str]) -> dict | None:
    sensors = _pick(house, _domain_class("binary_sensor", LEAK_CLASSES))
    if not sensors:
        return None

    shutoffs, skipped = _split(_pick(house, _water_shutoff), patterns)
    heaters, s2 = _split(
        _pick(house, lambda e, a: e.startswith("water_heater.")), patterns)
    skipped += s2

    valves = [r for r in shutoffs if r["entity_id"].startswith("valve.")]
    switches = [r for r in shutoffs if r["entity_id"].startswith("switch.")]

    groups = []
    if valves:
        groups.append(_group("Water valves closed", "valve.close_valve",
                             valves, "closed"))
    if switches:
        groups.append(_group("Water switches off", "switch.turn_off",
                             switches, "off"))
    if heaters:
        groups.append(_group("Water heaters off", "water_heater.turn_off",
                             heaters, "off"))
    if not groups:
        # A leak playbook that only sends a message is a notification, and
        # brAIn already sends those. See the module docstring.
        return None

    where = _where(sensors)
    steps = [_step(g) for g in groups] + _notify_steps(
        notify, "Water leak",
        f"Water detected in {where}. The water has been shut off.")
    return {
        "class": "leak",
        "title": "Emergency playbook: water leak",
        "sensors": sensors,
        "groups": groups,
        "skipped": skipped,
        "notify": notify,
        "note": ("Check the list above before you accept this — brAIn "
                 "matched these by name, and a switch it has read wrong is "
                 "one it would turn off in a leak."),
        "config": {
            "trigger": [{"platform": "state",
                         "entity_id": _ids(sensors), "to": "on"}],
            "action": steps,
            "mode": "single",
            "id": "brain_playbook_leak",
        },
    }


def _climate_in_area(house: House, area: str) -> str:
    """The climate entity in this room, or "".

    A different question from `checks.thermal._target_for`, which asks
    what setpoint the room is being held at — this asks which box is
    doing the holding, and answers with the first by id so two
    thermostats in one room give the same answer every night.
    """
    if not area:
        return ""
    for eid in sorted(house.states or {}):
        if eid.startswith("climate.") and house.area_of(eid) == area:
            return eid
    return ""


def coldest_room(snap: dict) -> dict | None:
    """The modelled room that has been seen coldest, with its climate box.

    `coolest` is what the month actually recorded, which is the honest
    answer to "which room freezes first" — a model's extrapolated floor
    is a number nothing has ever seen.
    """
    house = House(snap)
    store = snap.get("thermal") or {}
    best = None
    for eid, entry in sorted((store.get("rooms") or {}).items()):
        coolest = entry.get("coolest")
        if not isinstance(coolest, (int, float)):
            continue
        if eid not in (house.states or {}):
            continue
        if best is None or coolest < best["coolest"]:
            best = {"entity_id": eid, "coolest": float(coolest),
                    "name": house.name(eid),
                    "area": entry.get("area") or house.area_of(eid),
                    "unit": str(entry.get("unit") or store.get("unit") or "")}
    if not best:
        return None
    best["climate"] = _climate_in_area(house, best["area"])
    return best


def _freeze(house: House, snap: dict, patterns: list[str],
            notify: list[str]) -> dict | None:
    room = coldest_room(snap)
    if not room or not room["climate"] or not notify:
        # No modelled room, no thermostat in it, or nowhere to say it.
        # This one is a notification playbook by design, so with no
        # notifier there is nothing left of it at all.
        return None

    unit = room["unit"].lower()
    below = FREEZE_F if "f" in unit and "c" not in unit else FREEZE_C
    where = room["area"] or room["name"]
    message = (f"{where} is below {below:g}° and the heating has been doing "
               f"nothing for {IDLE_MINUTES} minutes. Pipes in an outside "
               "wall are at risk.")
    idle = ["idle", "off"]
    return {
        "class": "freeze",
        "title": "Emergency playbook: freezing with the heating stopped",
        "sensors": [{"entity_id": room["entity_id"], "name": room["name"],
                     "area": room["area"]}],
        "groups": [],
        "skipped": [],
        "notify": notify,
        "note": ("This one only tells you. Nothing here turns a boiler on: "
                 "brAIn cannot know why the heating stopped, and a "
                 "playbook that fires one up unattended is a different and "
                 "much larger promise."),
        "config": {
            # Either half can move first, so both are triggers and both
            # are conditions: whichever fires, the automation re-asks the
            # other. A trigger alone would fire on a cold room in a house
            # whose heating is working perfectly.
            "trigger": [
                {"platform": "numeric_state",
                 "entity_id": room["entity_id"], "below": below},
                {"platform": "state", "entity_id": room["climate"],
                 "attribute": "hvac_action", "to": idle,
                 "for": f"00:{IDLE_MINUTES:02d}:00"},
            ],
            "condition": [
                {"condition": "numeric_state",
                 "entity_id": room["entity_id"], "below": below},
                {"condition": "state", "entity_id": room["climate"],
                 "attribute": "hvac_action", "state": idle,
                 "for": {"minutes": IDLE_MINUTES}},
            ],
            "action": _notify_steps(notify, "Freeze risk", message),
            "mode": "single",
            "id": "brain_playbook_freeze",
        },
    }


BUILDERS = {"smoke": _smoke, "leak": _leak, "freeze": _freeze}


# ---------------------------------------------------------------------------
# What comes out
# ---------------------------------------------------------------------------

def _why(spec: dict) -> str:
    """The deterministic sentence. The model's paragraph replaces it, and
    a model that did not answer leaves it exactly here."""
    sensors = spec["sensors"]
    where = sorted({s["area"] for s in sensors if s["area"]})
    lead = "{} detector{}".format(len(sensors), "" if len(sensors) == 1 else "s")
    if spec["class"] == "freeze":
        lead = f"{sensors[0]['name']}"
    parts = [f"Written from what this house has: {lead}"
             + (" in " + ", ".join(where[:4]) if where else "") + "."]
    for group in spec["groups"]:
        n = len(group["targets"])
        parts.append(f"{group['verb']} ({n})." if n != 1
                     else f"{group['verb']} (1).")
    if spec["notify"]:
        parts.append("Then it tells you, naming the room.")
    if spec["skipped"]:
        parts.append("{} protected entit{} left out.".format(
            len(spec["skipped"]), "y is" if len(spec["skipped"]) == 1
            else "ies are"))
    return " ".join(parts)


def _assert_no_locks(spec: dict) -> None:
    """The one invariant checked over the finished config, not the branch.

    A rule enforced where the config is written is a rule that holds for
    the branches somebody remembered. This walks what actually came out.
    """
    import shadow  # noqa: PLC0415 — panel-local; the one reader of an
                   # action list, shared with `automation_writer`

    for call in shadow.would_do(spec["config"]):
        entity = call.get("entity_id")
        ids = [entity] if isinstance(entity, str) else list(entity or [])
        for eid in ids:
            if is_lock(str(eid)):
                raise AssertionError(
                    f"a playbook may never act on {eid}")
        if str(call.get("service") or "").split(".", 1)[0] in LOCK_DOMAINS:
            raise AssertionError(
                f"a playbook may never call {call.get('service')}")


def build(snap: dict, patterns: list[str] | None = None,
          notify_service: str = "") -> list[dict]:
    """Every playbook this house can have, as `proposals.add` takes one.

    An empty list is the ordinary answer for a house with no smoke
    detector and no leak sensor, which is most houses.
    """
    house = House(snap)
    patterns = list(patterns or [])
    notify = notify_targets(snap, notify_service)
    out = []
    for name in CLASSES:
        spec = BUILDERS[name](house, snap, patterns, notify)
        if not spec:
            continue
        _assert_no_locks(spec)
        out.append({
            "kind": "playbook",
            "title": spec["title"],
            "why": _why(spec),
            "source": "playbook",
            "config": spec["config"],
            "playbook": {
                "class": spec["class"],
                "sensors": spec["sensors"],
                "groups": [{k: v for k, v in g.items() if k != "data"}
                           for g in spec["groups"]],
                "skipped": spec["skipped"],
                "notify": spec["notify"],
                "note": spec["note"],
                "no_trial": NO_TRIAL,
                "card_max": CARD_MAX,
            },
        })
    return out


# ---------------------------------------------------------------------------
# Rehearsal — what it would do, against what is true right now
# ---------------------------------------------------------------------------

def rehearsal(row: dict, states: dict) -> dict:
    """Every call this playbook would make, with each target's state now.

    It **executes nothing**, and it deliberately does not use Home
    Assistant's `automation.trigger`, which would run the actions — which
    is not a rehearsal, it is the emergency. What a real rehearsal looks
    like is setting the detector off on purpose and reading the trace
    afterwards, and the card says so.
    """
    book = (row or {}).get("playbook") or {}
    groups = []
    for group in book.get("groups") or []:
        to = str(group.get("to") or "")
        targets = []
        already = 0
        for target in group.get("targets") or []:
            state = str((states.get(target["entity_id"]) or {}).get("state")
                        or "unknown")
            match = bool(to) and state == to
            already += 1 if match else 0
            targets.append({**target, "state": state, "already": match})
        groups.append({"verb": group.get("verb", ""),
                       "service": group.get("service", ""),
                       "to": to, "count": len(targets),
                       "already": already, "targets": targets})
    return {
        "class": book.get("class", ""),
        "ts": row.get("ts"),
        "groups": groups,
        "notify": book.get("notify") or [],
        "skipped": book.get("skipped") or [],
        # Said in the payload rather than only in the panel, because
        # `brain` on the command line reads this too.
        "executes_nothing": True,
        "note": NO_TRIAL,
    }


# ---------------------------------------------------------------------------
# The one optional Claude run
# ---------------------------------------------------------------------------

def describe_prompt(obj: dict) -> str:
    book = obj.get("playbook") or {}
    lines = [f"Explain this emergency automation: {obj.get('title')}", "",
             "It runs when any of these turns on:"]
    for sensor in (book.get("sensors") or [])[:12]:
        where = f" in the {sensor['area']}" if sensor.get("area") else ""
        lines.append(f"- {sensor['name']}{where}")
    lines.append("")
    lines.append("What it then does, in order:")
    for group in book.get("groups") or []:
        names = ", ".join(t["name"] for t in group["targets"][:8])
        more = len(group["targets"]) - 8
        lines.append(f"- {group['verb']}: {names}"
                     + (f", and {more} more" if more > 0 else ""))
    if book.get("notify"):
        lines.append("- Sends a notification naming the room it happened in.")
    if book.get("skipped"):
        lines.append("")
        lines.append("Deliberately left out, because they are on the "
                     "protected entities list: "
                     + ", ".join(s["name"] for s in book["skipped"][:8]))
    lines += ["", "Write the paragraph and nothing else."]
    return "\n".join(lines)


def tidy_description(text: str, fallback: str = "") -> str:
    """One paragraph, capped, or the deterministic sentence.

    A model that answered in four words has not answered, and a card with
    four words of explanation is worse than one with the list."""
    body = " ".join(str(text or "").split())
    if len(body) < 60:
        return fallback
    return body[:DESCRIBE_MAX_CHARS]


__all__ = [
    "CARD_MAX", "CLASSES", "DESCRIBE_MAX_TURNS", "DESCRIBE_TIMEOUT_S",
    "FREEZE_C", "FREEZE_F", "IDLE_MINUTES", "LOCK_DOMAINS", "NO_TRIAL",
    "NO_UNLOCK", "SYSTEM", "WATER_WORDS", "build", "coldest_room",
    "describe_prompt", "is_lock", "notify_targets", "rehearsal",
    "tidy_description",
]
