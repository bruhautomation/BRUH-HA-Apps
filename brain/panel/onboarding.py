"""First-run flow: learn the home, then propose cards worth having.

brAIn used to ship nine cards — Energy, Climate, Lighting and so on — all
enabled from the moment you installed it. They generated before brAIn knew
anything about the house, so they said generic things about a home it had
never looked at, and most of them were never read.

This inverts that. A fresh install has **no cards at all**. It studies the
home first, and only then proposes cards grounded in what it actually
found: not "Climate", but "three rooms drift 4°C overnight — worth
watching?". You pick from that list; nothing generates until you do.

There is deliberately **no canned fallback**. If the home is too sparse to
learn anything from, generic cards would be noise, so the honest answer is
to say what is missing and stop.

Three phases, each resumable — the panel can be closed and reopened mid-run:

  learn      study requests queued; the add-on's watcher runs them
  recommend  one tool-free pass over the memory document + a home snapshot
  choose     the accepted proposals become user categories

Stdlib plus the panel's own modules only, so it is importable in tests.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import categories as shipped_categories
import hypotheses
import prompt_store
import settings_store
import user_categories

import atomic_write

log = logging.getLogger("brain.onboarding")

SHARED_DIR = Path(os.environ.get("BRAIN_SHARED_DIR", "/config/.brain"))
MEMORY_DIR = Path(os.environ.get("BRAIN_MEMORY_DIR", str(SHARED_DIR / "memory")))
STUDY_REQUESTS_DIR = Path(
    os.environ.get("BRAIN_STUDY_REQUESTS", str(SHARED_DIR / "study_requests")))
CURRICULUM_FILE = MEMORY_DIR / "curriculum.json"
MEMORY_FILE = Path(os.environ.get("BRAIN_MEMORY_FILE", str(MEMORY_DIR / "memory.md")))
STATE_FILE = Path(os.environ.get("BRAIN_ONBOARDING_STATE", "/data/onboarding.json"))

# The opening syllabus. Not the whole curriculum — this runs while someone
# is watching, so it covers the topics that most shape what a card should
# be, and leaves the rest to the ongoing schedule.
FIRST_TOPICS = ("naming", "presence", "energy", "climate", "devices")

MAX_RECOMMENDATIONS = 8
MIN_MEMORY_CHARS = 200

# The one card that exists before anything has been studied. It runs from
# the orientation map in search mode, so it costs a small prompt and a
# few lookups rather than the whole house, and it is here because an
# Insights tab with nothing on it for the twenty minutes the syllabus
# takes is indistinguishable from one that is broken.
FIRST_CARD = "overview"

# What an onboarding study session may spend. `brain learn` has no turn
# cap at all by design — depth is the deliverable and the wall clock is
# the guard — but five of them run back to back while somebody watches a
# progress bar, so this path trades depth for arriving.
#
# It rides in the request file as `max_turns`, which is the only route
# onboarding has to the CLI side. `scripts/brain-study-watcher.sh` reads
# `.topic` out of the same file and has to read this one beside it and
# export BRAIN_LEARN_MAX_TURNS for `brain-learn.sh`, which already
# honours that variable.
STUDY_MAX_TURNS = 20

RECOMMEND_SYSTEM = """You choose which recurring insight cards a specific home should have.

You are given what has been learned about this home and a snapshot of its data. Propose cards that are worth generating FOR THIS HOME — grounded in what is actually there, naming its real rooms, devices and patterns.

A good proposal could not have been written for a different house. "Energy" is not a proposal; "Heat pump vs. the rest — it is 60% of your usage" is. If the evidence for a card is not in what you were given, do not propose it.

You are also given a list of GENERAL cards that ship with the add-on. Say which of those fit THIS home — by id, and only where the home has the entities and the history to make one worth generating. A general card on a home with three lights is a card that says the same thing every week. Most homes should get one or two; some should get none.

Reply with ONE JSON object and nothing else:
{"recommendations": [{"title": "Short card name (max 40 chars)",
                      "icon": "one emoji",
                      "focus": "What Claude should analyse each run. Specific to this home: name the entities, rooms or patterns involved.",
                      "why": "One sentence to the homeowner explaining why this is worth having, citing what was found."}],
 "shipped": [{"id": "one of the general card ids you were given",
              "why": "One sentence on why this home in particular has enough for it."}],
 "sparse": false,
 "missing": "Only when sparse is true: one sentence on what this home would need before insights are worth generating."}

Propose at most 8, and fewer is better — four sharp cards beat eight vague ones.

If what you were given is too thin to justify ANY card — barely any entities, no history, nothing learned — set "sparse": true, return an empty recommendations list, and say plainly in "missing" what is absent. Do not pad with generic cards; a card about a home you know nothing about wastes tokens on every run and teaches the homeowner to ignore the dashboard."""


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

def _read_state() -> dict:
    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_state(data: dict) -> None:
    atomic_write.write_json(STATE_FILE, data)


def _patch_state(**fields) -> dict:
    data = _read_state()
    data.update(fields)
    _write_state(data)
    return data


def is_onboarded() -> bool:
    return bool(settings_store.load().get("onboarded"))


# ---------------------------------------------------------------------------
# Step 0 — where brAIn is allowed to speak, and when it may not
# ---------------------------------------------------------------------------
# Everything brAIn learns lands on a tab somebody has to open. The morning
# brief is the one place it reaches a person where they already are, and
# it is off by default and gated on a notify service — so on a fresh
# install the most useful thing the add-on does is switched off behind two
# Configuration-tab options nobody has been told about. Asking here costs
# one screen and is the difference between a dashboard and a house that
# tells you things.
#
# What this CANNOT do is write those options. `addon_options.write` maps a
# settings name onto a Configuration key and knows only the six generation
# options; `findings_notify_service`, the two quiet hours and
# `morning_brief` are not among them. So the choice is stored in the
# panel's own settings, every reader consults that as a fallback under the
# Supervisor's value, and `manual_lines` says exactly what to paste for
# somebody who would rather have it in the Configuration tab where the
# rest of their options live.

# A service that can take a message. `notify.*` is the domain; a
# `mobile_app_*` service is the one that can also carry buttons, which is
# why it is ranked first rather than merely included.
MAX_NOTIFY_CHOICES = 40


def notify_candidates(services) -> list[dict]:
    """The notify services this house has, phones first.

    `services` is whatever the checks snapshot's own services set holds —
    `{"domain.service", ...}` — so this reads what Home Assistant really
    registered rather than a list composed here. A house with none gets an
    empty list and the step says so; it does not invent `notify.persistent
    _notification`, because a brief nobody sees is the thing this step
    exists to prevent.
    """
    rows: list[dict] = []
    for name in sorted(str(s) for s in (services or ())):
        if not name.startswith("notify."):
            continue
        service = name.split(".", 1)[1]
        if service in ("send_message",):
            # The 2024.8 entity-based transport: it takes an `entity_id`
            # rather than a target, so calling it the way everything here
            # calls a notify service does nothing.
            continue
        phone = service.startswith("mobile_app_")
        rows.append({
            "service": name,
            "label": service.replace("mobile_app_", "").replace("_", " "),
            "phone": phone,
            # Only a mobile app can carry the answer buttons a finding
            # notification puts on a message — see notify_router.can_answer.
            "buttons": phone,
        })
    rows.sort(key=lambda r: (not r["phone"], r["service"]))
    return rows[:MAX_NOTIFY_CHOICES]


def _hour(value) -> str | None:
    """An hour of the day as the string the add-on option stores, or None."""
    if value is None or value == "":
        return None
    try:
        hour = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError("quiet hours must be a whole hour, 0-23") from None
    if not 0 <= hour <= 23:
        raise ValueError("quiet hours must be a whole hour, 0-23")
    return str(hour)


def save_notify(service: str | None, quiet_start=None, quiet_end=None,
                brief: bool | None = None) -> dict:
    """Store step 0's answers and say what still needs pasting by hand.

    `brief` defaults to ON whenever a service was chosen, because that is
    the whole point of having asked — but it is stored as an explicit
    boolean rather than inferred later, so somebody who says no is not
    asked again by a rule that reads the service.
    """
    chosen = (service or "").strip() or None
    fields = {
        "findings_notify_service": chosen,
        "notify_quiet_start": _hour(quiet_start),
        "notify_quiet_end": _hour(quiet_end),
        "morning_brief": bool(chosen) if brief is None else bool(brief),
    }
    settings_store.save(fields)
    _patch_state(notify_asked=int(time.time()))
    return {**fields, "manual": manual_lines(fields)}


def manual_lines(fields: dict) -> list[str]:
    """The Configuration-tab lines for the options the panel cannot write.

    Returned rather than logged: a person who has just made a choice is
    the one person who will act on it, and an add-on that quietly kept a
    setting somewhere the Configuration tab does not show is the drift
    `_options_sync` exists to end.
    """
    out = []
    for key in ("findings_notify_service", "notify_quiet_start",
                "notify_quiet_end"):
        value = fields.get(key)
        if value:
            out.append(f'{key}: "{value}"')
    if fields.get("morning_brief"):
        out.append("morning_brief: true")
    return out


def notify_state() -> dict:
    """What step 0 has been answered with, for the panel to render."""
    stored = settings_store.load()
    fields = {k: stored.get(k) for k in
              ("findings_notify_service", "notify_quiet_start",
               "notify_quiet_end", "morning_brief")}
    return {
        **fields,
        "asked": bool(_read_state().get("notify_asked")),
        "manual": manual_lines(fields),
    }


# ---------------------------------------------------------------------------
# Phase 1 — learn
# ---------------------------------------------------------------------------

def _studied_topics() -> set[str]:
    try:
        data = json.loads(CURRICULUM_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    if not isinstance(data, dict):
        return set()
    return {k for k, v in data.items()
            if isinstance(v, dict) and int(v.get("ts") or 0) > 0}


def start_learning() -> dict:
    """Queue the opening syllabus for the add-on's study watcher.

    Requests rather than direct runs: a study session takes minutes and
    needs the MCP tools, which live on the CLI side. The watcher already
    exists for `brain.study`, so this reuses it rather than inventing a
    second path that could disagree with it.
    """
    already = _studied_topics()
    queued = []
    for i, topic in enumerate(FIRST_TOPICS):
        if topic in already:
            continue  # resumable: don't re-study on a second click
        request_study(topic, tag=f"{i}-onboarding", max_turns=STUDY_MAX_TURNS)
        queued.append(topic)
    _patch_state(phase="learning", started_at=int(time.time()))
    return {"queued": queued, "already_known": sorted(already)}


def request_study(topic: str = "", tag: str = "ask",
                  max_turns: int | None = None) -> str:
    """Queue ONE study session for the watcher and say what it will study.

    The single writer of the study-request format — the opening syllabus and
    the panel's ask bar both go through here, so the CLI watcher's contract
    has one author. An empty topic means "whatever has gone stalest", which
    is what ``brain learn`` with no argument does, so the two faces of
    learning behave alike.
    """
    topic = str(topic or "").strip()[:200]
    STUDY_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")[:40] or "stalest"
    now = int(time.time())
    path = STUDY_REQUESTS_DIR / f"{now}-{tag}-{slug}.json"
    request = {"ts": now, "topic": topic}
    # Only when it is being narrowed. An absent key means "whatever the
    # watcher's own default is", which is the no-cap `brain learn`
    # behaviour every other caller wants.
    if max_turns:
        request["max_turns"] = int(max_turns)
    atomic_write.write_json(path, request)
    return topic


def learning_progress() -> dict:
    studied = _studied_topics()
    done = [t for t in FIRST_TOPICS if t in studied]
    try:
        memory_chars = len(MEMORY_FILE.read_text(encoding="utf-8"))
    except OSError:
        memory_chars = 0
    return {
        "topics": list(FIRST_TOPICS),
        "done": done,
        "remaining": [t for t in FIRST_TOPICS if t not in studied],
        "complete": len(done) == len(FIRST_TOPICS),
        "memory_chars": memory_chars,
        # Facts reach the document only at consolidation, so a finished
        # syllabus with an empty document means "wait", not "nothing found".
        "memory_ready": memory_chars >= MIN_MEMORY_CHARS,
    }


# ---------------------------------------------------------------------------
# Phase 2 — recommend
# ---------------------------------------------------------------------------

def shipped_choices() -> list[dict]:
    """The general cards, as the recommend step offers them.

    Read off `categories.CATEGORIES` rather than listed here: the catalog
    is the definition, and a second copy of it in a prompt is one that
    goes stale the first time a card is renamed.
    """
    return [{"id": c["id"], "title": c["title"], "icon": c.get("icon", "✨"),
             "description": c.get("description", "")}
            for c in shipped_categories.CATEGORIES]


def build_prompt(memory: str, bundle: dict) -> str:
    parts = ["WHAT HAS BEEN LEARNED ABOUT THIS HOME:", memory.strip() or "(nothing yet)"]
    parts.append("\nGENERAL CARDS THAT SHIP WITH THE ADD-ON — pick the few "
                 "that fit this home, by id:")
    parts += [f"- {c['id']}: {c['title']} — {c['description']}"
              for c in shipped_choices()]
    if hypotheses.list_all("rejected"):
        parts.append("\nLINES OF INQUIRY THE HOMEOWNER REJECTED — do not build a card on these:")
        parts += [f"- {t}" for t in hypotheses.dead_ends()]
    parts.append(
        "\nHOME DATA SNAPSHOT (JSON): areas, entities (e=entity_id, s=state, "
        "n=friendly name, a=area, u=unit, dc=device_class), and recent history "
        "where available.")
    parts.append(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
    parts.append("\nNow produce the single JSON object per the contract. JSON only.")
    return "\n".join(parts)


def parse_recommendations(text: str) -> dict:
    """Validate the model's reply into {recommendations, sparse, missing}."""
    obj = None
    stripped = re.sub(r"^```(?:json)?\s*|\s*```$", "", (text or "").strip())
    try:
        obj = json.loads(stripped)
    except ValueError:
        match = re.search(r"\{.*\}", stripped, re.S)
        if match:
            try:
                obj = json.loads(match.group(0))
            except ValueError:
                obj = None
    if not isinstance(obj, dict):
        raise ValueError("recommendations were not valid JSON")

    out = []
    for item in (obj.get("recommendations") or [])[:MAX_RECOMMENDATIONS]:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:40]
        focus = str(item.get("focus") or "").strip()[:4000]
        if not title or not focus:
            continue
        out.append({
            "title": title,
            "icon": (str(item.get("icon") or "✨").strip() or "✨")[:4],
            "focus": focus,
            "why": str(item.get("why") or "").strip()[:300],
        })

    # The shipped half. An id the catalog does not hold is dropped rather
    # than created: the model is picking from a list it was given, and a
    # made-up id would become a card with no definition behind it.
    known = {c["id"]: c for c in shipped_choices()}
    picked: list[dict] = []
    seen: set[str] = set()
    for item in (obj.get("shipped") or [])[:len(known)]:
        cat_id = (item.get("id") if isinstance(item, dict) else item)
        cat_id = str(cat_id or "").strip()
        if cat_id not in known or cat_id in seen:
            continue
        seen.add(cat_id)
        why = str(item.get("why") or "").strip()[:300] \
            if isinstance(item, dict) else ""
        picked.append({**known[cat_id], "why": why})

    # `sparse` is about whether this home has enough for ANY card, so a
    # reply that proposed nothing custom but did pick a general one is
    # not a sparse home — reading it as one would show the "there is not
    # enough here" screen above a list of things to accept.
    sparse = bool(obj.get("sparse")) or not (out or picked)
    return {
        "recommendations": out,
        "shipped": picked,
        "sparse": sparse,
        "missing": str(obj.get("missing") or "").strip()[:400] if sparse else "",
    }


def save_recommendations(result: dict) -> dict:
    _patch_state(phase="choosing", recommendations=result["recommendations"],
                 shipped=result.get("shipped") or [],
                 sparse=result["sparse"], missing=result["missing"],
                 recommended_at=int(time.time()))
    return result


def stored_recommendations() -> dict:
    state = _read_state()
    return {
        "recommendations": state.get("recommendations") or [],
        "shipped": state.get("shipped") or [],
        "sparse": bool(state.get("sparse")),
        "missing": state.get("missing") or "",
    }


# ---------------------------------------------------------------------------
# Phase 3 — choose
# ---------------------------------------------------------------------------

def accept(indexes: list[int], shipped: list[str] | None = None) -> list[dict]:
    """Create exactly what was ticked, and finish onboarding.

    Two lists because there are two kinds of card and only one of them is
    created: a custom proposal becomes a user category, while a shipped
    one already exists in the code and is *admitted* — recorded in
    `prompt_store`'s accepted set, which is what `visible_categories`
    reads once this install is curated.

    `curated_categories` is written here and only here, and it is what
    makes the nine shipped cards stop appearing by default. It is written
    even when nothing was ticked, because "I was asked and chose none" is
    an answer and the empty dashboard it produces is the one the person
    asked for.

    Onboarding completes even when nothing is chosen: someone who reads
    the list and wants none of it is done, not stuck.
    """
    proposals = stored_recommendations()["recommendations"]
    created = []
    for i in indexes or ():
        if not isinstance(i, int) or not 0 <= i < len(proposals):
            continue
        p = proposals[i]
        try:
            created.append(user_categories.create({
                "title": p["title"], "icon": p["icon"], "focus": p["focus"],
            }))
        except ValueError as exc:
            log.warning("could not create %r: %s", p["title"], exc)
    admitted = _admit_shipped(shipped)
    settings_store.save({"onboarded": True, "curated_categories": True})
    _patch_state(phase="done", finished_at=int(time.time()),
                 accepted=[p["title"] for p in created],
                 accepted_shipped=admitted)
    return created


def _admit_shipped(ids) -> list[str]:
    """Record which shipped cards this home has, keeping the first one.

    `FIRST_CARD` is already on the dashboard by the time anybody reaches
    the choose step — it is generated at sign-in so the tab is never
    empty — and dropping it here because it was not ticked would delete a
    card somebody has been reading for the length of the syllabus.
    """
    picked = set(prompt_store.load_overrides()["accepted"])
    picked |= {str(i) for i in (ids or ())}
    return prompt_store.set_accepted(picked)


def skip() -> None:
    """Finish without cards — the dashboard stays empty until asked."""
    _admit_shipped(None)
    settings_store.save({"onboarded": True, "curated_categories": True})
    _patch_state(phase="done", finished_at=int(time.time()), accepted=[])


def reset() -> None:
    """Run the flow again (Settings). Existing cards are left alone."""
    settings_store.save({"onboarded": False})
    _write_state({"phase": "learning"})


def admit_first_card() -> list[str]:
    """Put `FIRST_CARD` on this home's list of shipped cards.

    Called where the card is generated rather than here, because the two
    are one act: a card on the dashboard that `visible_categories` does
    not return is a file `load_insights` skips, which is a Claude run
    spent on something nobody can see.
    """
    return prompt_store.accept(FIRST_CARD)


def state() -> dict:
    """Everything the panel needs to render the flow."""
    stored = _read_state()
    return {
        "onboarded": is_onboarded(),
        "phase": stored.get("phase") or "learning",
        "learning": learning_progress(),
        "notify": notify_state(),
        **stored_recommendations(),
    }
