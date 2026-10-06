"""Names, rooms and aliases — proposed by one press, applied by another.

`reg.hardware_name` has said *"ask brAIn to suggest names"* since it was
written, and nothing answered: an entity still called
`Plug 00158d0004a1b2c3` is unfindable in a picker and unsayable to Assist,
and the fix is forty renames somebody does one dialog at a time. This is
the thing that answers. One run reads the registries and proposes, in the
house's OWN style, a friendly name, a room for a device in none, and the
short phrases people actually say ("big light") as voice aliases; the
panel shows them as ONE table with a tick on every row; Apply writes the
ticked rows through Core's registry commands and keeps what each field
held before, for thirty days, so Undo can put it back.

Five rules, and every one is a refusal made in code over what the run
returned — a model's reply is a proposal and never a write:

  * **Only what was offered may be named.** The run is handed a digest of
    entities and devices; a row about an id that is not in it is dropped,
    because "ids checked against what was read" is the whole difference
    between a proposal and a guess about somebody else's house.
  * **A room must already exist.** An area is matched to the house's own
    area registry by id or name; nothing here creates one, because a room
    nobody made is a room nobody asked for.
  * **A protected entity is never touched** — renaming a lock is not acting
    on it, but a room move changes which "turn off the kitchen" reaches
    it, and the list the person wrote means "brAIn leaves this alone".
    A device carrying one is refused whole, `healing`'s reason.
  * **A name that is still hardware, a name another entity of the same
    kind already answers to, or a name two rows both propose is refused**,
    because Assist resolving "kitchen light" to one of two is a voice
    command that does the wrong thing at random.
  * **An area move says what it changes.** Moving a device into the
    kitchen changes what every automation that targets the kitchen
    reaches, so each area row carries the automations whose area targets
    gain or lose it (`area_reach`) — read off `automations.yaml`, never
    guessed, and only where the automation's service domain matches a
    domain the moved device actually has.

Apply re-reads every field from Core before it writes (a proposal is
minutes old; the registry is the truth), and Undo restores a field only
while it still holds what Apply wrote — somebody who renamed it again
since has made a newer decision, and an undo that overwrote it would be
brAIn arguing. Aliases are a set: Undo removes the ones it added and
leaves every other.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any

import atomic_write

STORE = os.environ.get("BRAIN_TIDY_FILE", "/data/tidy.json")

KINDS = ("name", "area", "alias")
TARGETS = ("entity", "device")

# How much of the house one run is handed. Hardware-named entities and
# those in no room come first; the rest of the budget is the house's own
# good names, which are the STYLE the proposals have to match.
MAX_CANDIDATES = 160
MAX_STYLE = 30
MAX_DEVICES = 60
# What one table may hold. Past this a table is a chore, not a review.
MAX_ROWS = 80
MAX_NAME = 60
MAX_ALIAS = 40
MAX_WHY = 160
MAX_ALIASES_PER_ENTITY = 4
UNDO_DAYS = 30
MAX_BATCHES = 20
MAX_REACH = 8
TIMEOUT_S = 300

# Domains that are software rather than a thing in a room: renaming one is
# not what this is for, and a room for a script is a category error.
SKIP_DOMAINS = frozenset({
    "automation", "script", "scene", "zone", "person", "sun", "group",
    "input_boolean", "input_number", "input_select", "input_text",
    "input_datetime", "input_button", "schedule", "timer", "counter",
    "tts", "conversation", "stt", "wake_word", "update", "tag", "event",
    "notify", "todo", "calendar", "device_tracker", "image", "button",
})
BACKGROUND = frozenset({"diagnostic", "config"})
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


# ---------------------------------------------------------------------------
# What the run is handed
# ---------------------------------------------------------------------------

def _house(snap: dict):
    from checks._util import House
    return House(snap)


def _hardware(text: str) -> str:
    from checks.registry import hardware_token
    return hardware_token(text)


def _protected(eid: str, patterns: list[str]) -> bool:
    import automation_writer
    return automation_writer.is_protected(eid, patterns)


def _in_picker(house, eid: str) -> bool:
    if eid.split(".", 1)[0] in SKIP_DOMAINS:
        return False
    if not house.enabled(eid):
        return False
    reg = house.registry.get(eid) or {}
    if reg.get("hidden_by"):
        return False
    return str(reg.get("entity_category") or "") not in BACKGROUND


def digest(snap: dict) -> dict:
    """The entities, devices and rooms a run may propose anything about.

    Deterministic and capped: the same house gives the same digest, so a
    second press is offered the same rows rather than a different sample.
    """
    house = _house(snap)
    areas = [{"id": a, "name": n} for a, n in sorted(house.areas.items())]
    rows: list[tuple[int, str, dict]] = []
    style: list[dict] = []
    for eid in sorted(house.states):
        if not _in_picker(house, eid):
            continue
        name = house.name(eid)
        attrs = (house.states.get(eid) or {}).get("attributes") or {}
        dev = house.device_of(eid) or {}
        row = {"id": eid, "name": name,
               "device": house.device_name(dev) if dev else "",
               "area": house.area_of(eid),
               "class": str(attrs.get("device_class") or "")[:30]}
        model = str(dev.get("model") or "")[:40]
        if model:
            row["model"] = model
        hw = bool(_hardware(name))
        if hw:
            rows.append((0, eid, {**row, "hardware": True}))
        elif not row["area"] and len(house.areas):
            rows.append((1, eid, {**row, "no_area": True}))
        else:
            rows.append((2, eid, row))
            if len(style) < MAX_STYLE and name != eid:
                style.append({"id": eid, "name": name, "area": row["area"]})
    rows.sort(key=lambda r: (r[0], r[1]))
    entities = [r[2] for r in rows[:MAX_CANDIDATES]]
    devices = []
    for dev_id, dev in sorted(house.devices.items()):
        if dev.get("area_id") or dev.get("disabled_by"):
            continue
        members = sorted(e.get("entity_id") for e in house.entities
                         if str(e.get("device_id") or "") == dev_id
                         and e.get("entity_id")
                         and _in_picker(house, e["entity_id"]))
        if not members:
            continue
        devices.append({"id": dev_id, "name": house.device_name(dev),
                        "model": str(dev.get("model") or "")[:40],
                        "entities": members[:4]})
        if len(devices) >= MAX_DEVICES:
            break
    return {"areas": areas, "entities": entities, "devices": devices,
            "style": style}


SYSTEM = """You tidy a Home Assistant house's names, rooms and voice aliases.

You are given the entities and devices that need it, the house's rooms, and
examples of names the household already uses. Propose changes a person will
review one row at a time. Nothing you write is applied without their tick.

Rules:
- Match the house's OWN naming style (look at the examples): its word
  order, its room-first or thing-first habit, its capitalisation.
- A name never contains a serial number, MAC, IEEE address or hex id.
- `name` rows rename an entity (target "entity") or a device (target
  "device"). Keep names short: what somebody would call it out loud.
- `area` rows put a device (target "device") or an entity (target
  "entity") into one of the listed rooms. The value is the room's id
  exactly as listed. Never invent a room; if none fits, propose nothing.
- `alias` rows add a short spoken phrase for an entity (target "entity"),
  such as "big light" or "telly", that Assist should also understand.
  Only aliases a person would plausibly say; at most two per entity.
- Only use ids exactly as given. Never propose for anything not listed.
- `why` is one short clause saying what you went on.
- Propose nothing rather than a guess. An empty list is a fine answer.

Answer with JSON only: {"rows": [{"kind": "name"|"area"|"alias",
"target": "entity"|"device", "id": "...", "value": "...", "why": "..."}]}
"""

SCHEMA = {
    "type": "object",
    "properties": {
        "rows": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "target": {"type": "string", "enum": list(TARGETS)},
                    "id": {"type": "string"},
                    "value": {"type": "string"},
                    "why": {"type": "string"},
                },
                "required": ["kind", "target", "id", "value"],
            },
        },
    },
    "required": ["rows"],
}


def frame(dig: dict) -> str:
    return (
        "THE HOUSE'S ROOMS:\n" + json.dumps(dig["areas"], ensure_ascii=False)
        + "\n\nNAMES THE HOUSEHOLD ALREADY USES (the style to match):\n"
        + json.dumps(dig["style"], ensure_ascii=False)
        + "\n\nENTITIES (hardware: still named after its id; no_area: in no "
          "room):\n" + json.dumps(dig["entities"], ensure_ascii=False)
        + "\n\nDEVICES IN NO ROOM:\n"
        + json.dumps(dig["devices"], ensure_ascii=False)
        + f"\n\nPropose at most {MAX_ROWS} rows.")


# ---------------------------------------------------------------------------
# What came back, checked
# ---------------------------------------------------------------------------

def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _key(text: str) -> str:
    return _norm(text).casefold()


def _area_id(value: str, house) -> str:
    """The registry id for a room the run named, or ''."""
    value = _norm(value)
    if value in house.areas:
        return value
    for aid, name in house.areas.items():
        if _key(name) == _key(value):
            return aid
    return ""


def _domains_of(house, target: str, subject: str) -> set[str]:
    if target == "entity":
        return {subject.split(".", 1)[0]}
    return {str(e.get("entity_id") or "").split(".", 1)[0]
            for e in house.entities
            if str(e.get("device_id") or "") == subject and e.get("entity_id")}


def _area_ids(value: Any) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {str(v) for v in value if isinstance(v, str)}
    return set()


def area_reach(snap: dict, target: str, subject: str, old_area: str,
               new_area: str) -> list[dict]:
    """Automations whose area targets gain or lose this subject.

    Read off the config: an action naming `area_id` A (in `target:`, in
    `data:`, or at its own top level) with a service whose domain is one
    the moved thing has — or `homeassistant`, which spans domains. A light
    moving into the kitchen does not change what `climate.set_temperature`
    on the kitchen reaches, so it is not listed.
    """
    from checks._util import walk
    house = _house(snap)
    domains = _domains_of(house, target, subject)
    watched = {a for a in (old_area, new_area) if a}
    if not watched or not domains:
        return []
    out: list[dict] = []
    for auto in snap.get("automations") or []:
        if not isinstance(auto, dict):
            continue
        hits: set[str] = set()
        for node in walk(auto):
            if not isinstance(node, dict):
                continue
            service = node.get("action") or node.get("service")
            if not isinstance(service, str) or "." not in service:
                continue
            sdomain = service.split(".", 1)[0]
            if sdomain != "homeassistant" and sdomain not in domains:
                continue
            areas: set[str] = set()
            for holder in (node, node.get("target"), node.get("data")):
                if isinstance(holder, dict):
                    areas |= _area_ids(holder.get("area_id"))
            hits |= areas & watched
        for area in sorted(hits):
            out.append({
                "id": str(auto.get("id") or "")[:64],
                "alias": str(auto.get("alias") or auto.get("id")
                             or "an automation")[:80],
                "area": house.areas.get(area, area),
                "change": ("will now reach it" if area == new_area
                           else "will stop reaching it"),
            })
            if len(out) >= MAX_REACH:
                return out
    return out


def parse(answer: dict | None, dig: dict, snap: dict,
          patterns: list[str]) -> dict:
    """`{rows, refused, dropped}` — only what passed every rule is a row.

    `refused` carries each rejected row with the sentence that refused it,
    because a proposal that vanished without trace reads as the run having
    had nothing to say; `dropped` counts rows that were not even shaped
    like a proposal.
    """
    house = _house(snap)
    offered_e = {r["id"]: r for r in dig.get("entities") or []}
    offered_d = {r["id"]: r for r in dig.get("devices") or []}
    # A device may also be renamed when one of its offered entities is
    # what made it worth looking at — `Plug 00158d…` is usually the
    # device's own name, inherited by every entity on it.
    offered_devices = set(offered_d) | {
        str((house.device_of(eid) or {}).get("id") or "")
        for eid in offered_e} - {""}
    rows_in = (answer or {}).get("rows") if isinstance(answer, dict) else None
    rows: list[dict] = []
    refused: list[dict] = []
    dropped = 0
    taken_names: dict[tuple[str, str], str] = {}
    aliases_for: dict[str, int] = {}
    # Every friendly name the house already answers to, per domain — the
    # ones a proposal must not collide with.
    existing: dict[str, set[str]] = {}
    for eid in house.states:
        existing.setdefault(eid.split(".", 1)[0], set()).add(_key(house.name(eid)))

    seen_refusals: set[tuple] = set()

    def refuse(row: dict, why: str) -> None:
        # One refusal per subject and value: the same row twice in a reply
        # is one thing that was not done, not two lines on the card.
        key = (row.get("target"), row.get("subject"), row.get("kind"),
               _key(str(row.get("value") or "")), why)
        if key in seen_refusals:
            return
        seen_refusals.add(key)
        refused.append({**row, "refused": why})

    for raw in rows_in if isinstance(rows_in, list) else []:
        if len(rows) >= MAX_ROWS:
            break
        if not isinstance(raw, dict):
            dropped += 1
            continue
        kind, target = raw.get("kind"), raw.get("target")
        subject = str(raw.get("id") or "").strip()
        value = _norm(raw.get("value"))
        why = _norm(raw.get("why"))[:MAX_WHY]
        if kind not in KINDS or target not in TARGETS or not subject or not value:
            dropped += 1
            continue
        row = {"kind": kind, "target": target, "subject": subject,
               "value": value, "why": why}
        if target == "entity":
            if subject not in offered_e:
                refuse(row, "brAIn was not asked about that entity")
                continue
            label = offered_e[subject]["name"]
            members = [subject]
        else:
            if subject not in offered_devices or subject not in house.devices:
                refuse(row, "brAIn was not asked about that device")
                continue
            dev = house.devices.get(subject) or {}
            label = house.device_name(dev) if dev else subject
            members = sorted(e.get("entity_id") for e in house.entities
                             if str(e.get("device_id") or "") == subject
                             and e.get("entity_id"))
        if any(_protected(m, patterns) for m in members):
            refuse(row, "it is on your protected list, so brAIn leaves it alone")
            continue
        if _CONTROL.search(value):
            dropped += 1
            continue
        row["label"] = label
        if kind == "name":
            if len(value) > MAX_NAME:
                refuse(row, "the name is too long to say")
                continue
            if _hardware(value):
                refuse(row, "the name still carries a hardware id")
                continue
            if _key(value) == _key(label):
                continue  # no change: not a refusal, just nothing to do
            domain = subject.split(".", 1)[0] if target == "entity" else "device"
            if target == "entity" and _key(value) in existing.get(domain, set()):
                refuse(row, "another one of these is already called that")
                continue
            if (domain, _key(value)) in taken_names:
                refuse(row, "two rows proposed the same name")
                continue
            taken_names[(domain, _key(value))] = subject
            row["before_label"] = label
        elif kind == "area":
            aid = _area_id(value, house)
            if not aid:
                refuse(row, "that room does not exist in Home Assistant")
                continue
            if target == "entity":
                reg = house.registry.get(subject) or {}
                dev = house.device_of(subject) or {}
                current = str(reg.get("area_id") or dev.get("area_id") or "")
            else:
                current = str((house.devices.get(subject) or {}).get("area_id") or "")
            if current == aid:
                continue
            row["value"] = aid
            row["area_name"] = house.areas.get(aid, aid)
            row["from_area"] = house.areas.get(current, "") if current else ""
            row["reach"] = area_reach(snap, target, subject, current, aid)
        else:  # alias
            if target != "entity":
                refuse(row, "only an entity can have a voice alias")
                continue
            if len(value) > MAX_ALIAS:
                refuse(row, "the alias is too long to say")
                continue
            if _key(value) == _key(label):
                continue
            if aliases_for.get(subject, 0) >= MAX_ALIASES_PER_ENTITY:
                refuse(row, "enough aliases for one thing")
                continue
            aliases_for[subject] = aliases_for.get(subject, 0) + 1
        row["id"] = f"r{len(rows)}"
        rows.append(row)
    return {"rows": rows, "refused": refused[:MAX_ROWS], "dropped": dropped}


# ---------------------------------------------------------------------------
# The store: one proposal, and the batches Undo can still reach
# ---------------------------------------------------------------------------

def load(path: str | None = None) -> dict:
    """`{proposal, batches, unreadable}` — never raises.

    `unreadable` is its own answer: a store that could not be read is not
    a house with no proposal and nothing to undo, and the panel says so
    rather than offering an empty table.
    """
    path = path or STORE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {"proposal": None, "batches": [], "unreadable": False}
    except (OSError, ValueError):
        return {"proposal": None, "batches": [], "unreadable": True}
    if not isinstance(data, dict):
        return {"proposal": None, "batches": [], "unreadable": True}
    batches = [b for b in (data.get("batches") or []) if isinstance(b, dict)]
    proposal = data.get("proposal") if isinstance(data.get("proposal"), dict) else None
    return {"proposal": proposal, "batches": batches, "unreadable": False}


def _save(data: dict, path: str | None = None) -> None:
    data = {"proposal": data.get("proposal"),
            "batches": (data.get("batches") or [])[-MAX_BATCHES:]}
    atomic_write.write_json(path or STORE, data)


def save_proposal(result: dict, *, run_id: str = "", error: str = "",
                  now: float | None = None, path: str | None = None) -> dict:
    data = load(path)
    proposal = {"at": int(now if now is not None else time.time()),
                "run_id": str(run_id or "")[:64],
                "rows": result.get("rows") or [],
                "refused": result.get("refused") or [],
                "dropped": int(result.get("dropped") or 0),
                "areas": [a for a in result.get("areas") or []
                          if isinstance(a, dict) and a.get("id")],
                "error": str(error or "")[:300]}
    data["proposal"] = proposal
    _save(data, path)
    return proposal


def revise(row_id: str, value: str, dig: dict, snap: dict,
           patterns: list[str], path: str | None = None) -> dict:
    """Change one proposed row to what the person typed instead.

    "No, call it this" is an answer to a proposal, not a new run: the
    value goes through exactly the rules `parse` holds the model's to — an
    offered id, a room that exists, no protected entity, no hardware
    name, no name somebody else answers to — and also through the names
    the other rows on the table already propose, because two rows giving
    two things one name is the collision the parse refuses. The row keeps
    its id, so a tick on it stays a tick, and carries `edited` so the card
    can say whose value it is. Returns `{ok, row, error, proposal}`.
    """
    data = load(path)
    proposal = data.get("proposal") or {}
    rows = list(proposal.get("rows") or [])
    old = next((r for r in rows if r.get("id") == row_id), None)
    if old is None:
        return {"ok": False, "error": "That row is no longer on the table.",
                "row": None, "proposal": proposal}
    value = _norm(value)
    if not value:
        return {"ok": False, "error": "Type what it should be instead.",
                "row": None, "proposal": proposal}
    answer = {"rows": [{"kind": old["kind"], "target": old["target"],
                        "id": old["subject"], "value": value,
                        "why": "you chose this"}]}
    parsed = parse(answer, dig, snap, patterns)
    if parsed["refused"]:
        return {"ok": False, "error": "brAIn can't use that: "
                + parsed["refused"][0]["refused"] + ".",
                "row": None, "proposal": proposal}
    if not parsed["rows"]:
        return {"ok": False, "error": "That is what it is already — untick "
                "the row if you want it left as it is.",
                "row": None, "proposal": proposal}
    new = {**parsed["rows"][0], "id": row_id, "edited": True}
    if new["kind"] == "name":
        domain = new["subject"].split(".", 1)[0] if new["target"] == "entity" else "device"
        for other in rows:
            if other is old or other.get("kind") != "name":
                continue
            o_domain = (other["subject"].split(".", 1)[0]
                        if other.get("target") == "entity" else "device")
            if o_domain == domain and _key(other.get("value", "")) == _key(new["value"]):
                return {"ok": False, "error": "Another row on this table "
                        "already proposes that name.", "row": None,
                        "proposal": proposal}
    proposal["rows"] = [new if r is old else r for r in rows]
    data["proposal"] = proposal
    _save(data, path)
    return {"ok": True, "row": new, "error": "", "proposal": proposal}


def discard(path: str | None = None) -> None:
    data = load(path)
    data["proposal"] = None
    _save(data, path)


def undoable(batches: list[dict], now: float) -> list[dict]:
    """Batches Undo can still reach: inside the window, not undone yet."""
    return [b for b in batches
            if not b.get("undone_at")
            and now - float(b.get("at") or 0) <= UNDO_DAYS * 86400]


# ---------------------------------------------------------------------------
# Apply and Undo — through Core's own registry commands
# ---------------------------------------------------------------------------

ENTITY_FIELDS = {"name": "name", "area": "area_id", "alias": "aliases"}
DEVICE_FIELDS = {"name": "name_by_user", "area": "area_id"}


def group_updates(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """Ticked rows folded into one update per subject.

    Two aliases for one entity are one `aliases` list, and a rename plus a
    room move are one command — so a refusal can never land halfway
    through a single thing.
    """
    out: dict[tuple[str, str], dict] = {}
    for row in rows:
        key = (row["target"], row["subject"])
        entry = out.setdefault(key, {"name": None, "area": None,
                                     "aliases": [], "rows": []})
        if row["kind"] == "alias":
            entry["aliases"].append(row["value"])
        else:
            entry[row["kind"]] = row["value"]
        entry["rows"].append(row["id"])
    return out


async def _current(session, updates: dict) -> dict[tuple[str, str], dict | None]:
    """What every touched field holds right now, from Core."""
    import ha_data
    entity_ids = [s for (t, s) in updates if t == "entity"]
    calls = [{"type": "config/entity_registry/get", "entity_id": e}
             for e in entity_ids]
    if any(t == "device" for (t, _s) in updates):
        calls.append({"type": "config/device_registry/list"})
    answers = await ha_data._ws_calls(session, calls) if calls else []
    out: dict[tuple[str, str], dict | None] = {}
    for eid, answer in zip(entity_ids, answers):
        row = answer.get("result") if answer.get("ok") else None
        out[("entity", eid)] = ({"name": row.get("name"),
                                 "area_id": row.get("area_id"),
                                 "aliases": sorted(row.get("aliases") or [])}
                                if isinstance(row, dict) else None)
    if any(t == "device" for (t, _s) in updates):
        listing = answers[-1].get("result") if answers and answers[-1].get("ok") else None
        by_id = {str(d.get("id")): d for d in listing or [] if isinstance(d, dict)}
        for (t, s) in updates:
            if t != "device":
                continue
            d = by_id.get(s) if listing is not None else None
            out[("device", s)] = ({"name_by_user": d.get("name_by_user"),
                                   "area_id": d.get("area_id")}
                                  if isinstance(d, dict) else None)
    return out


def _command(target: str, subject: str, fields: dict) -> dict:
    if target == "entity":
        return {"type": "config/entity_registry/update", "entity_id": subject,
                **fields}
    return {"type": "config/device_registry/update", "device_id": subject,
            **fields}


async def apply(session, ids: list[str], *, now: float | None = None,
                path: str | None = None) -> dict:
    """Write the ticked rows. Returns `{batch, applied, skipped, error}`.

    One command per subject; each answer is read for itself, so one row
    Core refused does not take the others with it — and only what Core
    ACCEPTED is recorded for Undo, because putting back a field that was
    never written would be writing somebody else's value over it.
    """
    import ha_data
    now = time.time() if now is None else now
    data = load(path)
    proposal = data.get("proposal") or {}
    wanted = set(ids or [])
    rows = [r for r in proposal.get("rows") or [] if r.get("id") in wanted]
    if not rows:
        return {"batch": None, "applied": [], "skipped": [],
                "error": "nothing ticked that is still on the table"}
    updates = group_updates(rows)
    current = await _current(session, updates)
    commands: list[tuple[tuple[str, str], dict, dict, dict]] = []
    skipped: list[dict] = []
    for (target, subject), want in updates.items():
        have = current.get((target, subject))
        if have is None:
            skipped.append({"subject": subject,
                            "why": "Home Assistant no longer has it"})
            continue
        fields = ENTITY_FIELDS if target == "entity" else DEVICE_FIELDS
        before, after = {}, {}
        if want["name"] is not None:
            before[fields["name"]] = have.get(fields["name"])
            after[fields["name"]] = want["name"]
        if want["area"] is not None:
            before["area_id"] = have.get("area_id")
            after["area_id"] = want["area"]
        if want["aliases"] and target == "entity":
            had = list(have.get("aliases") or [])
            added = [a for a in want["aliases"]
                     if _key(a) not in {_key(h) for h in had}]
            if added:
                before["aliases"] = had
                after["aliases"] = had + added
        if not after:
            continue
        commands.append(((target, subject), before, after, want))
    if not commands:
        return {"batch": None, "applied": [], "skipped": skipped,
                "error": "everything ticked already holds that value"}
    answers = await ha_data._ws_calls(
        session, [_command(t, s, after) for (t, s), _b, after, _w in commands])
    applied: list[dict] = []
    done_rows: set[str] = set()
    for ((target, subject), before, after, want), answer in zip(commands, answers):
        if not answer.get("ok"):
            skipped.append({"subject": subject,
                            "why": str(answer.get("error") or
                                       "Home Assistant refused it")[:200]})
            continue
        applied.append({"target": target, "subject": subject,
                        "before": before, "after": after})
        done_rows.update(want["rows"])
    batch = None
    if applied:
        batch = {"id": f"b{int(now * 1000)}", "at": int(now),
                 "entries": applied, "undone_at": 0}
        taken = {b.get("id") for b in data.get("batches") or []}
        while batch["id"] in taken:
            batch["id"] = f"b{int(batch['id'][1:]) + 1}"
        data.setdefault("batches", []).append(batch)
    # The rows that landed leave the table; the rest stay to be looked at.
    if proposal:
        proposal["rows"] = [r for r in proposal.get("rows") or []
                            if r.get("id") not in done_rows]
        data["proposal"] = proposal
    _save(data, path)
    return {"batch": batch, "applied": applied, "skipped": skipped, "error": ""}


def _same(a, b) -> bool:
    if isinstance(a, list) or isinstance(b, list):
        return sorted(_key(x) for x in a or []) == sorted(_key(x) for x in b or [])
    return (a or None) == (b or None)


async def undo(session, batch_id: str, *, now: float | None = None,
               path: str | None = None) -> dict:
    """Put a batch back, field by field. Returns `{restored, kept, error}`.

    A field is restored only while it still holds what Apply wrote; one
    changed since is KEPT and named, because the person changed it again
    and theirs is the newer decision. Aliases are a set: the ones this
    batch added are removed and every other alias stays.
    """
    import ha_data
    now = time.time() if now is None else now
    data = load(path)
    batch = next((b for b in data.get("batches") or []
                  if b.get("id") == batch_id), None)
    if batch is None:
        return {"restored": [], "kept": [], "error": "no such batch"}
    if batch.get("undone_at"):
        return {"restored": [], "kept": [], "error": "already undone"}
    if now - float(batch.get("at") or 0) > UNDO_DAYS * 86400:
        return {"restored": [], "kept": [],
                "error": f"older than {UNDO_DAYS} days — change it in Home "
                         "Assistant instead"}
    entries = batch.get("entries") or []
    updates = {(e["target"], e["subject"]): e for e in entries}
    current = await _current(session, updates)
    commands, plans, kept = [], [], []
    for (target, subject), entry in updates.items():
        have = current.get((target, subject))
        if have is None:
            kept.append({"subject": subject, "why": "Home Assistant no longer has it"})
            continue
        fields: dict = {}
        for field, wrote in (entry.get("after") or {}).items():
            was = (entry.get("before") or {}).get(field)
            now_value = have.get(field)
            if field == "aliases":
                added = [a for a in wrote if _key(a) not in
                         {_key(x) for x in was or []}]
                fields["aliases"] = [a for a in now_value or []
                                     if _key(a) not in {_key(x) for x in added}]
                continue
            if _same(now_value, wrote):
                fields[field] = was
            else:
                kept.append({"subject": subject, "field": field,
                             "why": "changed again since — left as it is"})
        if fields:
            commands.append(_command(target, subject, fields))
            plans.append(subject)
    restored: list[str] = []
    if commands:
        answers = await ha_data._ws_calls(session, commands)
        for subject, answer in zip(plans, answers):
            if answer.get("ok"):
                restored.append(subject)
            else:
                kept.append({"subject": subject,
                             "why": str(answer.get("error") or
                                        "Home Assistant refused it")[:200]})
    # Undone only if everything that could be put back was: a half-undone
    # batch stays undoable, so a second press can finish what the first
    # was refused.
    if not any(k.get("why", "").startswith("Home Assistant refused") for k in kept):
        batch["undone_at"] = int(now)
    _save(data, path)
    return {"restored": restored, "kept": kept, "error": ""}


__all__ = ["KINDS", "MAX_ROWS", "SCHEMA", "SYSTEM", "UNDO_DAYS", "apply",
           "area_reach", "digest", "discard", "frame", "group_updates",
           "load", "parse", "save_proposal", "undo", "undoable"]
