"""Versions of a card: every version brAIn makes of it is kept, drawn live in
the card's own place, and any one of them can be made the card and back
again, so a person can try A against B for as long as they like.

A card's Tell asks brAIn for VERSIONS by default (the box's **Just do it**
is the single change ``tell.py`` makes). A versions round is a task like a
Tell, with three differences that are the point of it:

* **Nothing is changed while you choose.** The round runs with brAIn's
  ``read_only`` tools, so it cannot write a file or touch Home Assistant
  whatever its prompt says; the versions ride in its JSON answer, and
  everything a version would need from Home Assistant (``needs``) is made
  only when that version is picked. ``read_only`` also refuses ``Read``,
  so the round is handed the card's YAML, its text on screen and the card
  schema from AGENTS.md instead of a picture.
* **Every version is a card Morph can draw.** Each one goes through the
  store's own card normalizer (``store._card``) and one that does not read
  is dropped and counted, never shown broken; a version equal to one
  already kept is not a new version.
* **Picking one is one commit.** With no ``needs`` Morph writes the card
  into dashboard.yaml itself, only that card's lines (``store.write_card``;
  the whole file only when that cannot be done surely), the card's id
  kept, commits it authored ``person`` and files a
  small ``use`` record beside the Tells, so Undo is a Tell's Undo: a revert
  of that one commit, as a new commit. With ``needs`` it starts an ordinary
  Tell naming the version and the Home Assistant changes it needs.

**The versions are kept per card** in Morph's own state
(``/data/morph/card-versions.json``), never in /config/morph, where the
watcher commits everything: each one with a letter that never moves, the
words it was asked with and the version it came from. The card as it is on
the dashboard is always one of them (a card changed by hand or by a Tell is
added as it is, so using a version never loses that change). A round is
always built on one kept version, named by its key and read here, never a
card off the wire, and what it brings back is ADDED to the set. A person
removes a version themselves (never the card in use), and a removed one
can be put back; past ``KEEP`` the oldest the card is not using moves to Removed.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
import threading
import time

import brain
import gitrepo
import learning
import morphcode
import paths
import settings
import store
import tell
import wording

log = logging.getLogger("morph.versions")

TIMEOUT_S = 600
MAX_VERSIONS = 3
KEEP = 26
REMOVED_KEEP = 26
KEPT_CARDS = 300
LABEL_CHARS = 24
IDEA_CHARS = 140
ASK_CHARS = 240
NEED_CHARS = 240
MAX_NEEDS = 4
SCHEMA_CHARS = 9000
MARK_CHARS = 120
KEPT = paths.DATA / "card-versions.json"
CARD_ID = re.compile(r"^[a-z0-9_]{1,80}$")
KEY = re.compile(r"^k[0-9]{1,6}$")
ENTITY = re.compile(r"^[a-z_]+\.[a-z0-9_]{1,120}$")
HOWS = ("new", "more", "mark")
# What a person can point at on a drawn version. The panel reads it off the
# card's own markup; the words of a role are said here, not taken from it.
ROLES = {"title": "the card's title", "value": "a value it shows", "row": "a row",
         "chart": "the chart", "control": "a control (a button or slider)", "icon": "an icon",
         "text": "a line of text", "card": "the whole card"}

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["summary", "versions"],
    "properties": {
        "summary": {"type": "string",
                    "description": "One sentence a person reads: what the versions try."},
        "versions": {
            "type": "array", "maxItems": MAX_VERSIONS,
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["label", "idea", "card"],
                "properties": {
                    "label": {"type": "string", "description": "At most two words: the version's name."},
                    "idea": {"type": "string", "description": "One line: what is different about it."},
                    "card": {"type": "object",
                             "description": "The card's WHOLE config, the keys dashboard.yaml takes for "
                                            "a card (type, entity or entities, name, icon, span, color, "
                                            "options…), without `id`."},
                    "needs": {"type": "array", "maxItems": MAX_NEEDS, "items": {"type": "string"},
                              "description": "Only when this version needs something in Home Assistant "
                                             "that does not exist yet (a template sensor, a helper), one "
                                             "line each. Nothing is made unless the person picks it."},
                },
            },
            "description": "Two or three genuinely different versions of the card.",
        },
        "code_only": {"type": "string",
                      "description": "Only when what was asked can only be done in Morph's code (a new "
                                     "card type, a change to a card's JavaScript): say so in one sentence "
                                     "and give no versions."},
    },
}


# ------------------------------------------------------------------ kept

_KEPT_LOCK = threading.Lock()


def _strip(card: dict) -> dict:
    return {k: v for k, v in (card or {}).items() if k != "id"}


def _same(a: dict, b: dict) -> bool:
    """Whether two cards are the same card config, whatever their ids."""
    return _strip(a) == _strip(b)


def letter(n: int) -> str:
    """A, B, … Z, AA, AB …: the n-th version's letter, kept for good."""
    out = ""
    n += 1
    while n:
        n, r = divmod(n - 1, 26)
        out = chr(65 + r) + out
    return out


def _load() -> dict:
    data = paths.read_json(KEPT, {}) or {}
    cards = data.get("cards") if isinstance(data, dict) else None
    return {"cards": cards if isinstance(cards, dict) else {}}


def _row(data: dict, card_id: str) -> dict:
    row = data["cards"].get(card_id)
    if not isinstance(row, dict) or not isinstance(row.get("versions"), list):
        # A card kept by the release before this one (the cards a pick
        # replaced, under "past") starts its set from those.
        old = [p for p in ((row or {}).get("past") or []) if isinstance(p, dict) and isinstance(p.get("card"), dict)]
        row = {"next": 0, "versions": [], "removed": []}
        for p in reversed(old):
            _add(row, p["card"], label=str(p.get("label") or "Earlier"), idea="A card this one was before.",
                 at=float(p.get("at") or time.time()))
        data["cards"][card_id] = row
    row["versions"] = [v for v in row["versions"] if isinstance(v, dict) and isinstance(v.get("card"), dict)
                       and KEY.match(str(v.get("key") or ""))]
    row["removed"] = [v for v in (row.get("removed") or []) if isinstance(v, dict)
                      and isinstance(v.get("card"), dict) and KEY.match(str(v.get("key") or ""))]
    row["next"] = int(row.get("next") or 0)
    return row


def _add(row: dict, card: dict, *, label: str, idea: str = "", needs: list | None = None, ask: str = "",
         came_from: str = "", at: float | None = None) -> dict:
    n = row["next"]
    row["next"] = n + 1
    entry = {"key": f"k{n}", "letter": letter(n), "label": " ".join(str(label).split())[:LABEL_CHARS],
             "idea": " ".join(str(idea or "").split())[:IDEA_CHARS], "card": _strip(card),
             "needs": list(needs or []), "ask": wording.clip(ask, ASK_CHARS) if ask else "",
             "from": came_from, "at": round(at or time.time(), 3)}
    row["versions"].append(entry)
    return entry


def _current(row: dict, card: dict) -> str:
    """The key of the kept version that is the card now, adding the card as
    it is when none is: the card in use is always one of the set."""
    for v in row["versions"]:
        if _same(v["card"], card):
            return v["key"]
    first = not row["versions"]
    key = _add(row, card, label="Original" if first else "Edited",
               idea=("The card as it was before any version." if first
                     else "The card as it was changed outside Versions."))["key"]
    _trim(row, key)
    return key


def _trim(row: dict, *keep: str) -> None:
    """Past KEEP the oldest version goes to the card's Removed list, where
    Put back can return it; never the card in use, nor what this very call
    added or put back (``keep``)."""
    while len(row["versions"]) > KEEP:
        old = next((v for v in row["versions"] if v["key"] not in keep), None)
        if old is None:
            return
        row["versions"].remove(old)
        row["removed"] = ([old] + row["removed"])[:REMOVED_KEEP]


def _store(data: dict, card_id: str, row: dict) -> None:
    row["at"] = time.time()
    data["cards"][card_id] = row
    if len(data["cards"]) > KEPT_CARDS:
        keep = sorted(data["cards"].items(), key=lambda kv: -float((kv[1] or {}).get("at") or 0))[:KEPT_CARDS]
        data["cards"] = dict(keep)
    paths.write_json(KEPT, data)


def _out(row: dict, card_id: str, cur: str) -> dict:
    vs = [{**{k: v[k] for k in ("key", "letter", "label", "idea", "needs", "ask", "from", "at") if k in v},
           "card": {**v["card"], "id": card_id}} for v in row["versions"]]
    return {"ok": True, "versions": vs, "current": cur, "keep": KEEP,
            "removed": [{"key": g["key"], "letter": g.get("letter") or "", "label": g.get("label") or ""}
                        for g in row["removed"]]}


def _entry(row: dict, key: str) -> dict | None:
    return next((v for v in row["versions"] if v["key"] == key), None)


def kept(card_id: str) -> dict:
    """A card's kept versions for its Versions box, the one in use named."""
    if not CARD_ID.match(card_id or ""):
        return {"ok": False, "error": "That is not a card on this dashboard."}
    now = _find(store.read()[0], card_id)
    if now is None:
        return {"ok": False, "error": "That card is not on the dashboard any more."}
    with _KEPT_LOCK:
        data = _load()
        was = copy.deepcopy(data["cards"].get(card_id))
        row = _row(data, card_id)
        cur = _current(row, now)
        if row != was:
            _store(data, card_id, row)
        return _out(row, card_id, cur)


def remove(card_id: str, key: str, back: bool = False) -> dict:
    """Take a version out of the set, or (``back``) put the last one taken
    out back in. The card in use is never removed: it is the card."""
    if not CARD_ID.match(card_id or "") or not KEY.match(key or ""):
        return {"ok": False, "error": "That is not one of the versions."}
    now = _find(store.read()[0], card_id)
    if now is None:
        return {"ok": False, "error": "That card is not on the dashboard any more."}
    with _KEPT_LOCK:
        data = _load()
        row = _row(data, card_id)
        cur = _current(row, now)
        if back:
            gone = next((v for v in row["removed"] if v["key"] == key), None)
            if gone is None:
                return {"ok": False, "error": "That version is not there to put back any more."}
            row["removed"].remove(gone)
            row["versions"].append(gone)
            row["versions"].sort(key=lambda v: int(v["key"][1:]))
            _trim(row, cur, key)
        else:
            entry = _entry(row, key)
            if entry is None:
                return {"ok": False, "error": "That version is gone already."}
            if key == cur:
                return {"ok": False, "error": "That version is the card now. Use another one first."}
            row["versions"].remove(entry)
            row["removed"] = ([entry] + row["removed"])[:REMOVED_KEEP]
        _store(data, card_id, row)
        return _out(row, card_id, cur)


def add(card_id: str, current: dict, got: list[dict], *, ask: str, came_from: str) -> tuple[list[str], int]:
    """Add a round's versions to the card's set: the keys added, and how
    many were already kept (the same card config is one version)."""
    with _KEPT_LOCK:
        data = _load()
        row = _row(data, card_id)
        cur = _current(row, current)
        keys, dup = [], 0
        for v in got:
            if any(_same(v["card"], k["card"]) for k in row["versions"]):
                dup += 1
                continue
            keys.append(_add(row, v["card"], label=v["label"], idea=v["idea"], needs=v["needs"], ask=ask,
                             came_from=came_from)["key"])
        _trim(row, cur, *keys)
        _store(data, card_id, row)
        return keys, dup


# ------------------------------------------------------------------ cards

def _find(dash: dict, card_id: str) -> dict | None:
    for fl in dash.get("floors") or []:
        for sec in fl.get("sections") or []:
            for g in sec.get("groups") or []:
                for c in g.get("cards") or []:
                    if c.get("id") == card_id:
                        return c
    return None


def drawable(body, extra: tuple = ()) -> bool:
    """Whether a version's type is one Morph can draw: one of Morph's own
    kinds (or a kind this house's copy of Morph adds), a ``custom:`` card,
    or a Lovelace card brAIn wrapped on purpose (``type: lovelace`` with the
    card under ``card``). A bare type that is none of those is a mistyped
    kind as often as a Home Assistant card, and Morph keeps no list of Home
    Assistant's own to tell them apart, so the store would wrap it and the
    panel would draw an error: such a version is dropped, not offered."""
    if not isinstance(body, dict):
        return True  # store._card says why, and it is counted there
    ctype = str(body.get("type") or "").strip()
    return not ctype or ctype in store.MORPH_TYPES or ctype in extra or ctype.startswith("custom:")


def clean(raw, current: dict, card_id: str) -> tuple[list[dict], int]:
    """brAIn's versions as the panel may draw them, and how many were
    dropped: each card through the store's normalizer, the card's own id
    put on it, and none equal to the card or to a version before it."""
    if not isinstance(raw, list):
        return [], 0
    extra = tuple(morphcode.card_types())
    out: list[dict] = []
    dropped = 0
    for i, item in enumerate(raw[:MAX_VERSIONS + 2]):
        if not isinstance(item, dict):
            dropped += 1
            continue
        problems: list[str] = []
        body = item.get("card")
        if isinstance(body, dict):
            body = {k: v for k, v in body.items() if k != "id"}
        if not drawable(body, extra):
            dropped += 1
            continue
        card = store._card(body, problems, f"version {i + 1}", extra)
        if not card or len(out) >= MAX_VERSIONS:
            dropped += 1
            continue
        card["id"] = card_id
        if _same(card, current) or any(_same(card, v["card"]) for v in out):
            dropped += 1
            continue
        label = " ".join(str(item.get("label") or "").split())[:LABEL_CHARS] or f"Version {len(out) + 1}"
        needs = [wording.clip(" ".join(str(n).split()), NEED_CHARS) for n in (item.get("needs") or [])
                 if isinstance(n, str) and n.strip()][:MAX_NEEDS] if isinstance(item.get("needs"), list) else []
        out.append({"label": label, "idea": " ".join(str(item.get("idea") or "").split())[:IDEA_CHARS],
                    "card": card, "needs": needs})
    return out, dropped


def card_schema() -> str:
    """The part of AGENTS.md that says what a card may hold, cut on a line.
    The round cannot Read the file (read_only refuses it), so it rides in
    the prompt; the house's own copy first, Morph's when there is none."""
    text = ""
    for path in (paths.AGENTS, paths.DEFAULTS / "AGENTS.md"):
        try:
            text = path.read_text(encoding="utf-8")
            break
        except OSError:
            continue
    start = text.find("Optional keys on any card")
    end = text.find("## What dashboard.yaml does not hold")
    part = text[start:end] if 0 <= start < end else ""
    return store.clip_lines(part.strip(), SCHEMA_CHARS, "the rest is in /config/morph/AGENTS.md.")


def _yaml(obj) -> str:
    import yaml
    return yaml.safe_dump({k: v for k, v in obj.items() if k != "id"}, sort_keys=False,
                          allow_unicode=True).strip()


def _path_of(card, entity: str, at: str = "") -> str:
    """Where ``entity`` sits in a card's config, as a YAML path
    (``entities[2]``, ``options.detail.entity``), or "" when it does not."""
    if isinstance(card, dict):
        for k, v in card.items():
            if k == "id":
                continue
            hit = _path_of(v, entity, f"{at}.{k}" if at else str(k))
            if hit:
                return hit
    elif isinstance(card, list):
        for n, v in enumerate(card):
            hit = _path_of(v, entity, f"{at}[{n}]")
            if hit:
                return hit
    elif card == entity:
        return at
    return ""


def clean_mark(mark, card: dict) -> dict | None:
    """The part of a drawn version a person pointed at, as a typed
    reference: its role, the entity it belongs to (one the version names),
    where that sits in the version's YAML, and the words it showed. The
    words it showed are quoted as what was on screen, never followed."""
    if not isinstance(mark, dict) or mark.get("role") not in ROLES:
        return None
    role = mark["role"]
    entity = str(mark.get("entity") or "")
    where = _path_of(card, entity) if ENTITY.match(entity) else ""
    if not where:
        entity = ""
    if role == "title" and "name" in card:
        where = "name"
    if role == "icon" and "icon" in card:
        where = "icon"
    try:
        nth = max(0, min(int(mark.get("nth") or 0), 99))
    except (TypeError, ValueError):
        nth = 0
    return {"role": role, "entity": entity, "where": where, "nth": nth,
            "shows": wording.clip(" ".join(str(mark.get("shows") or "").split()), MARK_CHARS)}


def mark_lines(mark: dict, words: str) -> list[str]:
    lines = ["THE MARKED PART (the person pointed at it on the version drawn on screen):",
             f"- What: {ROLES[mark['role']]}" + (f" (number {mark['nth'] + 1} of its kind on the card)"
                                                  if mark["nth"] and mark["role"] not in ("title", "card") else "")]
    if mark["entity"]:
        lines.append(f"- Entity: {mark['entity']}")
    if mark["where"]:
        lines.append(f"- In the YAML at: {mark['where']}")
    if mark["shows"]:
        lines.append(f"- It showed: “{mark['shows']}”")
    lines += [f"- What is wrong with it: “{words}”",
              "Make each version a different answer to THAT part; keep the rest of the version as it is.", ""]
    return lines


def build_prompt(target: dict, words: str, current: str, *, how: str = "new", base: dict | None = None,
                 view: dict | None = None, mark: dict | None = None, kept_labels: list[str] | None = None) -> str:
    what = tell.what_of(target)
    lines = ["MORPH · versions of one card on this house's dashboard (Morph, in /config/morph).", "",
             "THE REQUEST", f"Asked: “{words}”", f"Target: {what}"]
    if target.get("path"):
        lines.append(f"Where: {str(target['path'])[:240]}")
    if target.get("entity"):
        lines.append(f"Entity: {str(target['entity'])[:120]}")
    lines.append("")
    view = view or {}
    if view.get("text"):
        lines += ["What the card shows on screen now, as text"
                  + (f" ({view['w']}×{view['h']} px)" if view.get("w") and view.get("h") else "")
                  + f": {view['text']}", ""]
    lines += ["THE CARD NOW (Morph's normalized form: defaults filled in)", "```yaml", current.strip(), "```", ""]
    if base:
        name = f"{base.get('letter') or ''} “{base.get('label') or 'this version'}”".strip()
        lines += [{"more": f"MAKE VARIATIONS ON VERSION {name} ({base.get('idea') or 'no idea given'}), "
                           "not on the card as it is now:",
                   "mark": f"CHANGE ONE PART OF VERSION {name} ({base.get('idea') or 'no idea given'}):",
                   }.get(how, f"START FROM VERSION {name} ({base.get('idea') or 'no idea given'}), "
                             "not from the card as it is now:"),
                  "```yaml", _yaml(base.get("card") or {}), "```"]
        if base.get("needs"):
            lines.append("It needs from Home Assistant: " + "; ".join(base["needs"]))
        lines.append("")
    if mark:
        lines += mark_lines(mark, words)
    if kept_labels:
        lines += ["The person already has these versions of the card (do not repeat them): "
                  + "; ".join(kept_labels[:KEEP]) + ".", ""]
    learned = tell.lessons()
    if learned.strip():
        lines += ["HOUSEHOLD RULES (/config/morph/LEARNED.md; follow them unless the request says otherwise.",
                  "A line marked (you) is one the household wrote itself):", learned.strip(), ""]
    house_types = list(morphcode.card_types())
    lines += [
        "WHAT TO DO",
        "- Answer with two or three versions of this card. The person sees each one drawn live in the",
        "  card's place, with the house's real states, keeps all of them and switches between them;",
        "  Morph makes one the card only when the person picks it.",
        "- Change NOTHING: not dashboard.yaml, not Home Assistant, not Morph's code. This run can only",
        "  read (your Home Assistant read tools work; files do not), and the versions ride in your answer.",
        "- Each version is the card's WHOLE config, with the keys dashboard.yaml takes for one card (below).",
        "  Leave out `id`: Morph keeps the card's own. A Lovelace card is `type: lovelace` with its config",
        "  under `card:` (a `custom:` card may be written directly); a version of any other type is not shown.",
        "- Make them genuinely different ideas (a different type, layout or emphasis), not three shades of",
        "  one. Keep the card's entities unless the request asks otherwise, and check any entity you add",
        "  exists with your read tools.",
        "- `label` is at most two words; `idea` is one line saying what is different.",
        "- `needs` only when a version needs something in Home Assistant that does not exist yet (a template",
        "  sensor, a helper), one line each. Nothing is made unless the person picks that version.",
        "- When what was asked can only be done in Morph's own code (a new card type, a card's JavaScript),",
        "  give no versions and say so in `code_only`: the person can then ask for the single change.",
        "- Follow the design rules in /config/morph/AGENTS.md as you know them: one control in one place,",
        "  quiet by default, no tooltips or empty-state text.",
        "",
        "WHAT A CARD MAY HOLD (from /config/morph/AGENTS.md):",
        card_schema(),
    ]
    if house_types:
        lines.append("Card types this house's own copy of Morph adds: " + ", ".join(house_types[:20]) + ".")
    lines += ["", "ANSWER with the JSON object the schema describes: summary, versions, and code_only only",
              "when it applies."]
    return "\n".join(lines)


# ----------------------------------------------------------------- rounds

def start(target: dict, words: str, *, view: dict | None = None, base_from: dict | None = None,
          mark=None) -> dict:
    """Begin a versions round for one card, built on one of its kept
    versions. The card is named by its id and the version by its key;
    everything else about them is read here, never off the wire."""
    fitted = wording.fit(words, "", cap=tell.MAX_WORDS)
    words = fitted["words"]
    if not words:
        return {"error": "Say what should change."}
    if not brain.available():
        return {"error": brain.status()["sentence"]}
    card_id = str((target or {}).get("id") or "")
    if (target or {}).get("kind") != "card" or not CARD_ID.match(card_id):
        return {"error": "Versions are made for one card."}
    have = kept(card_id)
    if not have.get("ok"):
        return {"error": have["error"]}
    named = tell.target_for("card", card_id)
    base_from = base_from if isinstance(base_from, dict) else {}
    how = base_from.get("how") if base_from.get("how") in HOWS else "new"
    key = str(base_from.get("key") or have["current"])
    base = next((v for v in have["versions"] if v["key"] == key), None)
    if base is None:
        return {"error": "That version is gone. Pick another one."}
    picked = None
    if how == "mark":
        picked = clean_mark(mark, base["card"])
        if picked is None:
            return {"error": "Point at the part of the card that is wrong first."}
    tid = brain.new_id("morph")
    state = {"id": tid, "mode": "versions", "how": how, "text": words, "target": named,
             "phase": "sending", "steps": [], "started": time.time(), "scope": "ui",
             "view": tell.clean_view(view) if key == have["current"] else {},
             "origin": "panel", "person_words": words, "from": key,
             "base": {k: base.get(k) for k in ("key", "letter", "label", "idea", "card", "needs")},
             "kept": [f"{v['letter']} {v['label']}" for v in have["versions"]]}
    if picked:
        state["mark"] = picked
    tell._save(state)
    tell._RUNNING[tid] = asyncio.get_running_loop().create_task(_run(state))
    return state


async def _run(state: dict) -> None:
    tid = state["id"]
    try:
        target = state["target"]
        tell._step(state, f"Reading {target.get('path') or tell.what_of(target)}")
        current_yaml = await asyncio.to_thread(tell.target_yaml, target)
        base = state.get("base") or {}
        # The card as it is needs no second copy: the base block is for a
        # version that is not the card now.
        on_card = (base.get("card") or {}) == _strip(_find(store.read()[0], target.get("id") or "") or {})
        prompt = build_prompt(target, state["text"], current_yaml, how=state.get("how") or "new",
                              base=None if on_card and state.get("how") == "new" else base,
                              view=state.get("view"), mark=state.get("mark"), kept_labels=state.get("kept"))
        state["payload"] = prompt
        model = settings.load().get("tell_model") or ""
        await asyncio.to_thread(brain.submit, tid, prompt, schema=SCHEMA, tools="read_only",
                                timeout=TIMEOUT_S, model=model, person_words=state["person_words"])
        state["phase"] = "waiting"
        tell._step(state, f"Asked {brain.who()} for versions — nothing changes until you pick one")
        deadline = time.time() + brain.CLAIM_GRACE_S
        while not brain.claimed(tid):
            if time.time() > deadline:
                brain.withdraw(tid)
                state["phase"] = "failed"
                state["say"] = ("Nothing picked the request up. brAIn's Automation integration "
                                "has to be on for Morph to reach it.")
                tell._step(state, "Nothing is listening", "bad")
                return
            await asyncio.sleep(brain.POLL_S)
        state["phase"] = "working"
        tell._step(state, f"{brain.who()} is on it")
        deadline = time.time() + TIMEOUT_S + 120
        res, seen = None, 0
        while res is None:
            if time.time() > deadline:
                break
            seen = await asyncio.to_thread(tell._follow, state, seen)
            res = await asyncio.to_thread(brain.result, tid)
            if res is None:
                await asyncio.sleep(brain.POLL_S)
        await asyncio.to_thread(tell._follow, state, seen)
        data, text, error = brain.answer_data(res) if res else (None, "", "timeout")
        await asyncio.to_thread(settle, state, data, text, error, store.read()[0])
        await asyncio.to_thread(learning.record_outcome, {
            "kind": "versions", "id": tid, "text": state["text"], "target": "card",
            "phase": state["phase"], "versions": len(state.get("added") or []),
            "dropped": state.get("dropped", 0), "error": error, "at": time.time()})
        tell._save(state)
    except Exception as exc:  # noqa: BLE001 — a round must always end in a sentence
        log.exception("versions %s failed", tid)
        state["phase"] = "failed"
        state["say"] = f"Morph could not finish asking for versions: {exc} The versions you had are still here."
        tell._save(state)
    finally:
        tell._RUNNING.pop(tid, None)


def settle(state: dict, data, text: str, error: str, dash: dict) -> None:
    """Put brAIn's answer on the card's kept set and the round: the keys
    added, how many did not read, and the sentence it ends on. The round
    is written onto ``state`` only; the caller saves it. Whatever happens,
    the versions already kept stay as they were."""
    who = brain.who()
    card_id = (state.get("target") or {}).get("id") or ""
    current = _find(dash, card_id)
    state["summary"] = wording.clip((data or {}).get("summary") or "", 600)
    state["added"] = []
    if error or data is None:
        state["phase"] = "failed"
        why = "it did not answer in time" if error == "timeout" else (error or "its answer did not read")
        state["say"] = f"{who} could not make versions this time ({why}). The versions you had are still here."
        return
    if current is None:
        state["phase"] = "failed"
        state["say"] = "That card is not on the dashboard any more."
        return
    got, dropped = clean(data.get("versions"), current, card_id)
    added, dup = add(card_id, current, got, ask=state.get("text") or "", came_from=state.get("from") or "")
    dropped += dup
    state["added"] = added
    state["dropped"] = dropped
    code_only = wording.clip(str(data.get("code_only") or "").strip(), 400)
    if code_only:
        state["code_only"] = code_only
    state["phase"] = "done"
    n = len(added)
    if not n:
        state["empty"] = True
        state["say"] = (code_only or f"{who} brought back no new version Morph could draw"
                        + (f" ({dropped} did not read or was one you have)" if dropped else "") + ".") \
            + " Nothing changed. Just do it asks for the single change instead."
        return
    state["say"] = (f"{n} new version{'' if n == 1 else 's'}, added to the ones you have. "
                    "Nothing changes until you use one.")
    if dropped:
        state["say"] += f" {dropped} more {'was' if dropped == 1 else 'were'} left out (Morph could not draw {'it' if dropped == 1 else 'them'}, or you have {'it' if dropped == 1 else 'them'} already)."


# -------------------------------------------------------------------- use

def needs_words(version: dict) -> str:
    """The words a version that needs Home Assistant changes is started
    with as an ordinary Tell, so those changes are made only for the
    version that was picked."""
    return ("Use this version of the card (“" + version.get("label", "") + "”):\n```yaml\n"
            + _yaml(version.get("card") or {}) + "\n```\nand make these Home Assistant changes it needs: "
            + "; ".join(version.get("needs") or []) + ". Keep the card's id.")


def use(p: dict) -> dict:
    """Make a kept version the card. Runs under morphd's lock. ``seen`` is
    the version the person saw as the card: when the card is not that any
    more, using one now would overwrite a change made since, so it is said
    first (``stale``) and the person decides (``over``)."""
    card_id = str(p.get("card") or "")
    key = str(p.get("key") or "")
    if not CARD_ID.match(card_id) or not KEY.match(key):
        return {"ok": False, "error": "That is not one of the versions."}
    gitrepo.commit_pending()
    base = gitrepo.head()
    dash, problems, text = store.read()
    if problems and problems[0].startswith(store.UNREADABLE):
        return {"ok": False, "error": "dashboard.yaml does not read right now, so Morph will not write into it. "
                                      "Fix it or Undo the last change first."}
    card = _find(dash, card_id)
    if card is None:
        return {"ok": False, "error": "That card is not on the dashboard any more."}
    with _KEPT_LOCK:
        data = _load()
        row = _row(data, card_id)
        seen = _entry(row, str(p.get("seen") or ""))
        cur = _current(row, card)  # a change made since is kept as a version, never lost
        _store(data, card_id, row)
        version = copy.deepcopy(_entry(row, key))
    if version is None:
        return {"ok": False, "error": "That version is gone. Pick another one."}
    if (seen is None or not _same(seen["card"], card)) and p.get("over") is not True:
        return {"ok": False, "stale": True,
                "error": "This card was changed after you opened its versions, so using one now would "
                         "replace that change (it is kept as a version). Use it anyway, or look again."}
    if key == cur:
        return {"ok": False, "error": "That version is the card already."}
    label = f"{version['letter']} · {version['label']}"
    target = tell.target_for("card", card_id)
    if version.get("needs"):
        # Home Assistant changes are a Tell's, made only for the version the
        # person picked.
        words = needs_words(version)
        st = tell.start(target, words, origin="version", note=label, person_words=words)
        if "error" in st:
            return {"ok": False, "error": st["error"]}
        return {"ok": True, "tell": True, **st}
    card.clear()
    card.update({"id": card_id, **version["card"]})
    store.write_card(text, dash, card_id)
    commit = gitrepo.commit(f"Used the version “{label}” of {target.get('label') or 'a card'}", "person")
    if not commit:
        return {"ok": False, "error": "That version is the card already."}
    back = tell.read_back(base, commit, target)
    tid = brain.new_id("morph")
    state = {"id": tid, "mode": "use", "text": f"Use this version: {label}", "target": target, "phase": "done",
             "started": time.time(), "commit": commit, "shows": back["shows"],
             "say": f"“{label}” is the card now. The others are still here.",
             "used": {"label": label, "key": key, "was": cur},
             "steps": [{"t": f"Wrote “{label}” into dashboard.yaml as one change", "tone": "good",
                        "at": time.time()}]}
    if back["dropped"]:
        state["dropped"] = back["dropped"]
    if tell.ON_PUBLISH:
        mirror = tell.ON_PUBLISH()
        if isinstance(mirror, dict) and mirror.get("revision"):
            state["revision"] = mirror["revision"]
    tell._save(state)
    learning.record_outcome({"kind": "version_use", "id": tid, "label": label, "card": card_id,
                             "commit": commit, "base": base, "at": time.time()})
    return {"ok": True, **state}
