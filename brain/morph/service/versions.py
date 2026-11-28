"""Versions of a card: say what should change, see two or three answers in
the card's own place, and keep the one you like.

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
  is dropped and counted, never shown broken; a version equal to the card,
  or to one before it, is not a version.
* **Picking one is one commit.** With no ``needs`` Morph writes the card
  into dashboard.yaml itself, only that card's lines (``store.write_card``;
  the whole file only when that cannot be done surely), the card's id
  kept, commits it authored ``person`` and files a
  small ``use`` record beside the Tells, so Undo is a Tell's Undo: a revert
  of that one commit, as a new commit. With ``needs`` it starts an ordinary
  Tell naming the version and the Home Assistant changes it needs.

The round's versions live in its state file under /config/.morph/tells
(pruned with the Tells), never in /config/morph, where the watcher commits
everything. The cards a pick replaced are kept per card, the last
``HISTORY_KEEP``, in Morph's own state (``/data/morph``), so an earlier
version can be shown live and put back the same way.
"""
from __future__ import annotations

import asyncio
import copy
import logging
import re
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
HISTORY_KEEP = 5
HISTORY_CARDS = 300
LABEL_CHARS = 24
IDEA_CHARS = 140
NEED_CHARS = 240
MAX_NEEDS = 4
SCHEMA_CHARS = 9000
HISTORY = paths.DATA / "card-versions.json"
CARD_ID = re.compile(r"^[a-z0-9_]{1,80}$")
HOWS = ("new", "more", "revise")

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
            "description": "Two or three genuinely different versions of the card (exactly one when "
                           "revising one version).",
        },
        "code_only": {"type": "string",
                      "description": "Only when what was asked can only be done in Morph's code (a new "
                                     "card type, a change to a card's JavaScript): say so in one sentence "
                                     "and give no versions."},
    },
}


# ---------------------------------------------------------------- history

def _history() -> dict:
    data = paths.read_json(HISTORY, {}) or {}
    cards = data.get("cards")
    return {"cards": cards if isinstance(cards, dict) else {}}


def _same(a: dict, b: dict) -> bool:
    """Whether two cards are the same card config, whatever their ids."""
    strip = lambda c: {k: v for k, v in (c or {}).items() if k != "id"}  # noqa: E731
    return strip(a) == strip(b)


def remember(card_id: str, replaced: dict, now_label: str = "") -> None:
    """Keep the card a pick replaced, with the label it was shown under,
    newest first, the last HISTORY_KEEP for the card."""
    data = _history()
    row = data["cards"].get(card_id) or {}
    past = [p for p in (row.get("past") or []) if isinstance(p, dict) and isinstance(p.get("card"), dict)]
    past = [p for p in past if not _same(p["card"], replaced)]
    past.insert(0, {"card": {k: v for k, v in replaced.items() if k != "id"},
                    "label": str(row.get("now") or "")[:LABEL_CHARS], "at": round(time.time(), 3)})
    data["cards"][card_id] = {"now": now_label[:LABEL_CHARS], "past": past[:HISTORY_KEEP],
                              "at": time.time()}
    if len(data["cards"]) > HISTORY_CARDS:
        keep = sorted(data["cards"].items(), key=lambda kv: -float(kv[1].get("at") or 0))[:HISTORY_CARDS]
        data["cards"] = dict(keep)
    paths.write_json(HISTORY, data)


def history(card_id: str) -> dict:
    """The earlier cards one card was, for its Versions list. One equal to
    the card as it is now is not an earlier version, so it is left out."""
    if not CARD_ID.match(card_id or ""):
        return {"ok": False, "error": "That is not a card on this dashboard."}
    now = _find(store.read()[0], card_id)
    if now is None:
        return {"ok": False, "error": "That card is not on the dashboard any more."}
    row = _history()["cards"].get(card_id) or {}
    out = []
    for p in row.get("past") or []:
        if isinstance(p, dict) and isinstance(p.get("card"), dict) and not _same(p["card"], now):
            out.append({"label": p.get("label") or "", "at": p.get("at"), "card": {**p["card"], "id": card_id}})
    return {"ok": True, "history": out, "now": row.get("now") or ""}


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


def build_prompt(target: dict, words: str, current: str, *, how: str = "new", base: dict | None = None,
                 view: dict | None = None) -> str:
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
    if base and how in ("more", "revise"):
        label = base.get("label") or "this version"
        lines += ([f"MAKE VARIATIONS ON THIS VERSION, “{label}” ({base.get('idea') or 'no idea given'}), "
                   "not on the card as it is now:"] if how == "more" else
                  [f"REVISE ONLY THIS VERSION, “{label}” ({base.get('idea') or 'no idea given'}), as the "
                   "request says, and answer with exactly ONE version:"])
        lines += ["```yaml", _yaml(base.get("card") or {}), "```"]
        if base.get("needs"):
            lines.append("It needs from Home Assistant: " + "; ".join(base["needs"]))
        lines.append("")
    learned = tell.lessons()
    if learned.strip():
        lines += ["HOUSEHOLD RULES (/config/morph/LEARNED.md; follow them unless the request says otherwise.",
                  "A line marked (you) is one the household wrote itself):", learned.strip(), ""]
    count = "exactly ONE version" if how == "revise" else "two or three versions"
    house_types = list(morphcode.card_types())
    lines += [
        "WHAT TO DO",
        f"- Answer with {count} of this card. The person sees each one drawn live in the card's place,",
        "  with the house's real states, and picks one; Morph then makes it the card.",
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

def start(target: dict, words: str, *, view: dict | None = None, base_from: dict | None = None) -> dict:
    """Begin a versions round for one card. The card is named by its id and
    everything else about it is read here; a round built on an earlier
    version reads that version from the round that offered it, never from
    the wire."""
    fitted = wording.fit(words, "", cap=tell.MAX_WORDS)
    words = fitted["words"]
    if not words:
        return {"error": "Say what should change."}
    if not brain.available():
        return {"error": brain.status()["sentence"]}
    card_id = str((target or {}).get("id") or "")
    if (target or {}).get("kind") != "card" or not CARD_ID.match(card_id):
        return {"error": "Versions are made for one card."}
    now = _find(store.read()[0], card_id)
    if now is None:
        return {"error": "That card is not on the dashboard any more."}
    named = tell.target_for("card", card_id)
    how, base, prior, index = "new", None, [], -1
    if isinstance(base_from, dict) and base_from.get("id"):
        how = base_from.get("how") if base_from.get("how") in HOWS else "more"
        was = tell.read_state(str(base_from.get("id") or "")) or {}
        try:
            index = int(base_from.get("index"))
        except (TypeError, ValueError):
            index = -1
        offered = was.get("versions") or []
        if was.get("mode") != "versions" or (was.get("target") or {}).get("id") != card_id \
                or not 0 <= index < len(offered):
            return {"error": "That version is gone. Ask again."}
        base = offered[index]
        # The versions this round is built on stay on it, so a round that
        # fails or brings nothing back still has them to choose from.
        prior = offered
    tid = brain.new_id("morph")
    state = {"id": tid, "mode": "versions", "how": how, "text": words, "target": named,
             "phase": "sending", "steps": [], "started": time.time(), "scope": "ui",
             "view": tell.clean_view(view), "origin": "panel", "person_words": words,
             "was": copy.deepcopy(now)}
    if base:
        state["base"] = base
    if prior:
        state["prior"] = prior
        state["revising"] = index
    tell._save(state)
    tell._RUNNING[tid] = asyncio.get_running_loop().create_task(_run(state))
    return state


async def _run(state: dict) -> None:
    tid = state["id"]
    try:
        target = state["target"]
        tell._step(state, f"Reading {target.get('path') or tell.what_of(target)}")
        current_yaml = await asyncio.to_thread(tell.target_yaml, target)
        prompt = build_prompt(target, state["text"], current_yaml, how=state.get("how") or "new",
                              base=state.get("base"), view=state.get("view"))
        state["payload"] = prompt
        model = settings.load().get("tell_model") or ""
        await asyncio.to_thread(brain.submit, tid, prompt, schema=SCHEMA, tools="read_only",
                                timeout=TIMEOUT_S, model=model, person_words=state["person_words"])
        state["phase"] = "waiting"
        tell._step(state, f"Asked {brain.who()} for " + ("one revised version" if state.get("how") == "revise"
                                                         else "versions") + " — nothing changes until you pick one")
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
        settle(state, data, text, error, store.read()[0])
        await asyncio.to_thread(learning.record_outcome, {
            "kind": "versions", "id": tid, "text": state["text"], "target": "card",
            "phase": state["phase"], "versions": len(state.get("versions") or []),
            "dropped": state.get("dropped", 0), "error": error, "at": time.time()})
        tell._save(state)
    except Exception as exc:  # noqa: BLE001 — a round must always end in a sentence
        log.exception("versions %s failed", tid)
        state["phase"] = "failed"
        state["say"] = f"Morph could not finish asking for versions: {exc}"
        if state.get("prior"):
            state["versions"] = state["prior"]
            state["shown"] = max(0, int(state.get("revising", 0)))
            state["say"] += " The versions you had are still here."
        tell._save(state)
    finally:
        tell._RUNNING.pop(tid, None)


def settle(state: dict, data, text: str, error: str, dash: dict) -> None:
    """Put brAIn's answer on the round: the versions that read, how many
    did not, and the sentence it ends on. Written onto ``state`` only; the
    caller saves it."""
    who = brain.who()
    card_id = (state.get("target") or {}).get("id") or ""
    current = _find(dash, card_id) or {}
    summary = wording.clip((data or {}).get("summary") or "", 600)
    state["summary"] = summary
    prior = [dict(v) for v in (state.get("prior") or [])]
    i = int(state.get("revising", -1))
    base_label = (state.get("base") or {}).get("label") or "that version"
    if error or data is None:
        state["phase"] = "failed"
        why = "it did not answer in time" if error == "timeout" else (error or "its answer did not read")
        if prior:
            # A revise or More like this that failed: the versions it was
            # built on are still the ones to choose from.
            ask = (f"revise “{base_label}”" if state.get("how") == "revise"
                   else f"make more like “{base_label}”")
            state["say"] = f"{who} could not {ask} ({why}). The versions you had are still here."
            state["versions"] = prior
            state["shown"] = i if 0 <= i < len(prior) else 0
            return
        state["say"] = (f"{who} did not answer in time." if error == "timeout"
                        else f"{who} could not make versions this time ({why}).")
        state["versions"] = []
        return
    got, dropped = clean(data.get("versions"), current, card_id)
    code_only = wording.clip(str(data.get("code_only") or "").strip(), 400)
    if state.get("how") == "revise":
        if got and 0 <= i < len(prior):
            label = prior[i]["label"]
            fresh = got[0]
            fresh["label"] = (label if label.endswith(" · revised") else label + " · revised")[:LABEL_CHARS + 10]
            dropped += len(got) - 1
            prior[i] = fresh
            state["versions"] = prior
            state["shown"] = i
        else:
            state["versions"] = prior
            state["shown"] = i
            got = []
    else:
        state["versions"] = got
        state["shown"] = 0 if got else -1
    state["dropped"] = dropped
    if code_only:
        state["code_only"] = code_only
    n = len(got)
    if not n and prior:
        # Nothing usable came back from a revise or More like this: the
        # versions it was built on stay, and that is what is said.
        state["versions"] = prior
        state["shown"] = i if 0 <= i < len(prior) else 0
        state["phase"] = "done"
        state["say"] = ((code_only + " ") if code_only else
                        f"{who} brought back no new version Morph could draw"
                        + (f" ({dropped} did not read)" if dropped else "") + ". ") \
            + "The versions you had are still here."
        return
    if not n:
        state["phase"] = "done"
        state["say"] = (code_only or f"{who} offered no version Morph could draw"
                        + (f" ({dropped} did not read)" if dropped else "") + ".") \
            + " Nothing changed. Just do it asks for the single change instead."
        state["empty"] = True
        return
    state["phase"] = "done"
    if state.get("how") == "revise":
        state["say"] = f"Revised “{state['versions'][state['shown']]['label']}”."
    else:
        state["say"] = f"{n} version{'' if n == 1 else 's'} of this card. Nothing changes until you pick one."
    if dropped:
        state["say"] += f" {dropped} more {'was' if dropped == 1 else 'were'} left out because Morph could not draw {'it' if dropped == 1 else 'them'}."


# -------------------------------------------------------------------- use

def _source(p: dict) -> tuple[dict | None, str, str, dict | None]:
    """(version, card id, error, the card the round was made from) for a
    Use this press: a round's version by its index, or an earlier card from
    the history by when it was kept. Both are read from what Morph stored;
    nothing about the card comes off the wire but where to find it."""
    version, card_id, error = _pick(p)
    was = None
    if version is not None and p.get("round"):
        was = (tell.read_state(str(p.get("round") or "")) or {}).get("was")
    return version, card_id, error, was if isinstance(was, dict) else None


def _pick(p: dict) -> tuple[dict | None, str, str]:
    if p.get("round"):
        st = tell.read_state(str(p.get("round") or "")) or {}
        if st.get("mode") != "versions":
            return None, "", "Those versions are gone. Ask again."
        try:
            i = int(p.get("index"))
        except (TypeError, ValueError):
            return None, "", "That is not one of the versions."
        offered = st.get("versions") or []
        if not 0 <= i < len(offered):
            return None, "", "That is not one of the versions."
        return offered[i], str((st.get("target") or {}).get("id") or ""), ""
    card_id = str(p.get("card") or "")
    if not CARD_ID.match(card_id):
        return None, "", "That is not a card on this dashboard."
    try:
        at = float(p.get("at"))
    except (TypeError, ValueError):
        return None, "", "That earlier version is gone."
    row = _history()["cards"].get(card_id) or {}
    for past in row.get("past") or []:
        if isinstance(past, dict) and isinstance(past.get("card"), dict) and abs(float(past.get("at") or 0) - at) < 0.001:
            return {"label": past.get("label") or "the earlier card", "idea": "", "needs": [],
                    "card": {**past["card"], "id": card_id}}, card_id, ""
    return None, "", "That earlier version is gone."


def needs_words(version: dict) -> str:
    """The words a version that needs Home Assistant changes is started
    with as an ordinary Tell, so those changes are made only for the
    version that was picked."""
    return ("Use this version of the card (“" + version.get("label", "") + "”):\n```yaml\n"
            + _yaml(version.get("card") or {}) + "\n```\nand make these Home Assistant changes it needs: "
            + "; ".join(version.get("needs") or []) + ". Keep the card's id.")


def use(p: dict) -> dict:
    """Make a version the card. Runs under morphd's lock."""
    version, card_id, error, was = _source(p)
    if error:
        return {"ok": False, "error": error}
    gitrepo.commit_pending()
    base = gitrepo.head()
    dash, problems, text = store.read()
    if problems and problems[0].startswith(store.UNREADABLE):
        return {"ok": False, "error": "dashboard.yaml does not read right now, so Morph will not write into it. "
                                      "Fix it or Undo the last change first."}
    card = _find(dash, card_id)
    if card is None:
        return {"ok": False, "error": "That card is not on the dashboard any more."}
    label = version.get("label") or "that version"
    if was is not None and not _same(card, was) and p.get("over") is not True:
        # The card changed after this round was made (by hand, by brAIn, or
        # by another pick): using a version now would undo that change, so
        # it is said first and the person decides.
        return {"ok": False, "stale": True,
                "error": "This card was changed after these versions were made, so using one now "
                         "would undo that change. Use it anyway, or ask for new versions of the card as it is."}
    target = tell.target_for("card", card_id)
    if version.get("needs"):
        # Home Assistant changes are a Tell's, made only for the version the
        # person picked; the card it replaces is kept now, while it is known.
        words = needs_words(version)
        st = tell.start(target, words, origin="version", note=label, person_words=words)
        if "error" in st:
            return {"ok": False, "error": st["error"]}
        remember(card_id, copy.deepcopy(card), label)
        return {"ok": True, "tell": True, **st}
    replaced = copy.deepcopy(card)
    card.clear()
    card.update({"id": card_id, **{k: v for k, v in version["card"].items() if k != "id"}})
    store.write_card(text, dash, card_id)
    commit = gitrepo.commit(f"Used the version “{label}” of {target.get('label') or 'a card'}", "person")
    if not commit:
        return {"ok": False, "error": "That version is the card already."}
    remember(card_id, replaced, label)
    back = tell.read_back(base, commit, target)
    tid = brain.new_id("morph")
    state = {"id": tid, "mode": "use", "text": f"Use this version: {label}", "target": target, "phase": "done",
             "started": time.time(), "commit": commit, "shows": back["shows"],
             "say": f"“{label}” is the card now.", "used": {"label": label, "card": version["card"]},
             "replaced": replaced, "steps": [{"t": f"Wrote “{label}” into dashboard.yaml as one change",
                                              "tone": "good", "at": time.time()}]}
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


def after_undo(tid: str) -> None:
    """A pick that was undone: the card it put in is kept as an earlier
    version, so taking it back never loses it."""
    st = tell.read_state(tid) or {}
    if st.get("mode") != "use" or not st.get("undone"):
        return
    card_id = str((st.get("target") or {}).get("id") or "")
    used = st.get("used") or {}
    if not CARD_ID.match(card_id) or not isinstance(used.get("card"), dict):
        return
    replaced = st.get("replaced") or {}
    used_card = {k: v for k, v in used["card"].items() if k != "id"}
    data = _history()
    row = data["cards"].get(card_id) or {}
    back_label, kept = "", []
    for x in row.get("past") or []:
        if not isinstance(x, dict) or not isinstance(x.get("card"), dict):
            continue
        if _same(x["card"], replaced):
            back_label = back_label or str(x.get("label") or "")
            continue
        if not _same(x["card"], used_card):
            kept.append(x)
    kept.insert(0, {"card": used_card, "label": str(used.get("label") or "")[:LABEL_CHARS],
                    "at": round(time.time(), 3)})
    data["cards"][card_id] = {"now": back_label, "past": kept[:HISTORY_KEEP], "at": time.time()}
    paths.write_json(HISTORY, data)
