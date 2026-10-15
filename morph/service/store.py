"""The dashboard document: read it, check it, write it, mirror it.

``/config/morph/dashboard.yaml`` is the one source of truth, and three
writers share it: Edit (through the integration, over the request folder),
brAIn (editing the file directly with its own tools), and an approved
suggestion (which is a brAIn run). This module is how a document becomes
something the frontend can trust:

* ``normalize`` fills what may be left out (ids, widths, colours) and
  drops what cannot be drawn, collecting a sentence per problem rather than
  refusing the file — a dashboard with one bad card is a dashboard with one
  missing card, never a blank screen;
* ``publish`` writes the JSON mirror the integration serves, stamped with a
  revision, so a save made against an older revision can be refused instead
  of silently overwriting somebody else's change (brAIn's, usually).

The schema is written out for brAIn in ``defaults/AGENTS.md``; a field this
module learns to read is a field that page has to describe.
"""
from __future__ import annotations

import hashlib
import re
import time

import yaml

import morphcode
import paths

COLORS = ("amber", "sand", "sky", "violet", "teal", "lime", "rose", "peach", "indigo")

# The card types the panel draws itself. Anything else is a Lovelace card
# passed through untouched (`type: lovelace` with its config under `card`,
# or any `custom:`/core card type written directly).
MORPH_TYPES = (
    "light", "light_group", "fan", "cover", "lock", "switch", "climate",
    "sensor", "readings", "meter", "media", "camera", "list", "person",
    "weather", "vacuum", "alarm", "scenes", "button", "entity", "note",
    "lovelace",
)

_SLUG = re.compile(r"[^a-z0-9]+")
ENTITY_RE = re.compile(r"^[a-z_]+\.[a-z0-9_]+$")


def slug(text: str, fallback: str = "x") -> str:
    s = _SLUG.sub("_", str(text or "").lower()).strip("_")
    return s[:48] or fallback


def _pre(prefix: str, text) -> str:
    """An id with its kind in front, exactly once — a normalised document
    normalised again must keep every id it had."""
    s = slug(text)
    return s if s.startswith(prefix) else prefix + s


def empty() -> dict:
    return {"title": "Home", "greeting": True, "story": True, "ask": True, "coming_up": True,
            "scenes": [], "floors": []}


UNREADABLE = "dashboard.yaml could not be read"


def clip_lines(text: str, limit: int, rest: str) -> str:
    """``text`` cut to whole lines within ``limit``, ending in a line that
    says how much was cut and where the rest is. A cut nobody marks reads
    as the end of the file, and a model then edits a dashboard it has only
    seen the top of. One helper, because a Tell and a learning pass both
    show brAIn part of dashboard.yaml."""
    text = (text or "").rstrip("\n")
    if len(text) <= limit:
        return text
    lines = text.split("\n")
    kept, size = [], 0
    for ln in lines:
        if size + len(ln) + 1 > limit:
            break
        kept.append(ln)
        size += len(ln) + 1
    cut = len(lines) - len(kept)
    return "\n".join(kept + [f"# … {cut} more line{'' if cut == 1 else 's'} cut; {rest}"])


def load_text(text: str) -> tuple[dict, list[str]]:
    """Parse and normalise. Never raises: an unreadable file comes back as
    an empty dashboard and the parser's own sentence."""
    try:
        raw = yaml.safe_load(text) if text and text.strip() else {}
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        where = f" (line {mark.line + 1})" if mark is not None else ""
        return empty(), [f"{UNREADABLE}{where}: {exc}"]
    return normalize(raw)


def read() -> tuple[dict, list[str], str]:
    try:
        text = paths.DASHBOARD.read_text(encoding="utf-8")
    except OSError:
        return empty(), [], ""
    dash, problems = load_text(text)
    return dash, problems, text


def _entities(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if isinstance(v, str) and ENTITY_RE.match(v.strip())]


def guess_type(entity: str) -> str:
    domain = entity.split(".", 1)[0]
    return {
        "light": "light", "fan": "fan", "cover": "cover", "lock": "lock",
        "switch": "switch", "input_boolean": "switch", "siren": "switch",
        "climate": "climate", "sensor": "sensor", "media_player": "media",
        "camera": "camera", "binary_sensor": "list", "person": "person",
        "device_tracker": "person", "weather": "weather", "vacuum": "vacuum",
        "alarm_control_panel": "alarm", "scene": "scenes", "script": "button",
        "button": "button", "input_button": "button", "automation": "switch",
    }.get(domain, "entity")


def _card(raw, problems: list[str], where: str, extra: tuple = ()) -> dict | None:
    if not isinstance(raw, dict):
        problems.append(f"{where}: a card must be a mapping")
        return None
    card: dict = {}
    ctype = str(raw.get("type") or "").strip()
    # A Lovelace card written directly (`type: tile`, `type: custom:x`) is
    # wrapped, so the frontend has one shape to read.
    if ctype and ctype not in MORPH_TYPES and ctype not in extra:
        card["type"] = "lovelace"
        card["card"] = {k: v for k, v in raw.items() if k not in ("id", "span", "morph_name")}
    elif ctype == "lovelace":
        inner = raw.get("card")
        if not isinstance(inner, dict) or not inner.get("type"):
            problems.append(f"{where}: a lovelace card needs `card:` with a `type`")
            return None
        card["type"] = "lovelace"
        card["card"] = inner
    else:
        ents = _entities(raw.get("entities")) or _entities(raw.get("entity"))
        if ctype in ("note",):
            card["type"] = "note"
            card["text"] = str(raw.get("text") or "")[:2000]
        elif not ents:
            problems.append(f"{where}: no entity, so nothing to draw")
            return None
        else:
            card["type"] = ctype or guess_type(ents[0])
            if len(ents) == 1 and card["type"] not in ("scenes", "list", "readings"):
                card["entity"] = ents[0]
            else:
                card["entities"] = ents
    for key in ("name", "icon", "unit"):
        if raw.get(key):
            card[key] = str(raw[key])[:80]
    if raw.get("span") is not None:
        try:
            card["span"] = max(1, min(4, int(raw["span"])))
        except (TypeError, ValueError):
            pass  # a span that is not a number leaves the card its natural size
    if isinstance(raw.get("color"), str) and raw["color"] in COLORS:
        card["color"] = raw["color"]
    if isinstance(raw.get("options"), dict):
        card["options"] = raw["options"]
    # Keep here (vision §11): a pin keeps the card in the Now band, always
    # (`true`) or while it is on (`active`, the written form of "always show
    # the printer while it runs").
    if raw.get("pin") is True or raw.get("pin") in ("always", "active"):
        card["pin"] = True if raw["pin"] in (True, "always") else "active"
    card["id"] = str(raw.get("id") or "")
    return card


def normalize(raw) -> tuple[dict, list[str]]:
    problems: list[str] = []
    if not isinstance(raw, dict):
        if raw not in (None, {}):
            problems.append("dashboard.yaml must be a mapping at the top")
        raw = {}
    out = empty()
    out["title"] = str(raw.get("title") or "Home")[:60]
    for flag in ("greeting", "story", "ask", "coming_up"):
        if flag in raw:
            out[flag] = bool(raw[flag])
    out["scenes"] = _entities(raw.get("scenes"))
    if isinstance(raw.get("theme"), str) and raw["theme"] in ("auto", "dark", "light", "medium"):
        out["theme"] = raw["theme"]

    used: set[str] = set()
    # Types a copy of cards.js in /config/morph/frontend adds are Morph's own
    # for as long as that copy is served (morphcode.card_types).
    extra = tuple(morphcode.card_types())

    def unique(base: str) -> str:
        cand, n = base, 2
        while cand in used:
            cand = f"{base}_{n}"
            n += 1
        used.add(cand)
        return cand

    floors = raw.get("floors")
    if floors is None and isinstance(raw.get("sections"), list):
        floors = [{"title": out["title"], "sections": raw["sections"]}]
    for fi, fraw in enumerate(floors if isinstance(floors, list) else []):
        if not isinstance(fraw, dict):
            problems.append(f"floor {fi + 1}: must be a mapping")
            continue
        ftitle = str(fraw.get("title") or f"Floor {fi + 1}")[:60]
        floor = {"id": unique(_pre("f_", fraw.get("id") or ftitle)), "title": ftitle,
                 "sections": []}
        if fraw.get("heading") is False:
            floor["heading"] = False
        for si, sraw in enumerate(fraw.get("sections") or []):
            if not isinstance(sraw, dict):
                problems.append(f"{ftitle} › section {si + 1}: must be a mapping")
                continue
            stitle = str(sraw.get("title") or "Section")[:60]
            sec = {"id": unique(_pre("s_", sraw.get("id") or stitle)), "title": stitle,
                   "color": sraw.get("color") if sraw.get("color") in COLORS else COLORS[si % len(COLORS)],
                   "width": 2, "groups": []}
            try:
                sec["width"] = max(1, min(4, int(sraw.get("width") or 2)))
            except (TypeError, ValueError):
                pass  # a width that is not a number keeps the default of 2
            if sraw.get("area"):
                sec["area"] = str(sraw["area"])[:64]
            if sraw.get("hidden"):
                sec["hidden"] = True
            groups = sraw.get("groups")
            if groups is None and isinstance(sraw.get("cards"), list):
                groups = [{"cards": sraw["cards"]}]
            for gi, graw in enumerate(groups if isinstance(groups, list) else []):
                if not isinstance(graw, dict):
                    continue
                group = {"cards": []}
                if graw.get("label"):
                    group["label"] = str(graw["label"])[:40]
                if graw.get("note"):
                    group["note"] = str(graw["note"])[:80]
                for ci, craw in enumerate(graw.get("cards") or []):
                    card = _card(craw, problems, f"{ftitle} › {stitle} › card {ci + 1}", extra)
                    if not card:
                        continue
                    inner = card.get("card") or {}
                    base = card.pop("id") or (card.get("entity") or inner.get("entity")
                                              or card.get("name")
                                              or (card.get("entities") or [card["type"]])[0])
                    group["cards"].append({"id": unique(_pre("c_", base)), **card})
                if group["cards"]:
                    sec["groups"].append(group)
            floor["sections"].append(sec)
        out["floors"].append(floor)
    return out, problems


def dump(dash: dict) -> str:
    """The document a person and brAIn read. Ids are kept, because Undo,
    notes and the usage log key on them, and losing them on a round trip
    would make every save look like a whole new dashboard."""
    header = ("# Morph dashboard. Edited by Morph's Edit mode, by brAIn, and by hand.\n"
              "# Every change is a git commit in this folder; see AGENTS.md for the schema.\n")
    return header + yaml.safe_dump(dash, sort_keys=False, allow_unicode=True, width=100)


def revision(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def publish(head: str = "") -> dict:
    """Write the mirror the integration serves. The revision is a hash of
    the file's text, so it moves with ANY change, including one made by an
    editor that never told anybody."""
    dash, problems, text = read()
    modules = []
    try:
        for f in sorted(paths.CARDS_DIR.glob("*.js")):
            if re.fullmatch(r"[A-Za-z0-9_.-]{1,80}\.js", f.name):
                modules.append({"name": f.name, "v": int(f.stat().st_mtime)})
    except OSError:
        pass  # no cards folder yet is no custom cards, not an error
    held = False
    if problems and problems[0].startswith(UNREADABLE):
        # A file that does not parse is somebody mid-edit, not a request
        # for an empty house: keep showing the last dashboard that read,
        # and say why it is not the file on disk.
        before = paths.read_json(paths.MIRROR, {}) or {}
        if isinstance(before.get("dashboard"), dict) and before["dashboard"].get("floors"):
            dash, held = before["dashboard"], True
    mirror = {"revision": revision(text), "commit": head, "dashboard": dash,
              "problems": problems, "held": held, "card_modules": modules,
              "at": time.time()}
    paths.write_json(paths.MIRROR, mirror)
    return mirror


def write(dash: dict) -> str:
    dash, _ = normalize(dash)
    text = dump(dash)
    paths.write_text(paths.DASHBOARD, text)
    paths.hand_to_brain(paths.DASHBOARD)
    return text


def all_entities(dash: dict) -> list[str]:
    out: list[str] = []
    for fl in dash.get("floors") or []:
        for sec in fl.get("sections") or []:
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    if c.get("entity"):
                        out.append(c["entity"])
                    out.extend(c.get("entities") or [])
    return out


def locate(dash: dict, card_id: str) -> tuple[str, str] | None:
    """(floor title, section title) of a card, for the path a prompt shows."""
    for fl in dash.get("floors") or []:
        for sec in fl.get("sections") or []:
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    if c.get("id") == card_id:
                        return fl["title"], sec["title"]
    return None
