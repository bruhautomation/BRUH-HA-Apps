"""First-run flow: learn the home, then propose cards worth having.

BRain used to ship nine cards — Energy, Climate, Lighting and so on — all
enabled from the moment you installed it. They generated before BRain knew
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

import hypotheses
import settings_store
import user_categories

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

RECOMMEND_SYSTEM = """You choose which recurring insight cards a specific home should have.

You are given what has been learned about this home and a snapshot of its data. Propose cards that are worth generating FOR THIS HOME — grounded in what is actually there, naming its real rooms, devices and patterns.

A good proposal could not have been written for a different house. "Energy" is not a proposal; "Heat pump vs. the rest — it is 60% of your usage" is. If the evidence for a card is not in what you were given, do not propose it.

Reply with ONE JSON object and nothing else:
{"recommendations": [{"title": "Short card name (max 40 chars)",
                      "icon": "one emoji",
                      "focus": "What Claude should analyse each run. Specific to this home: name the entities, rooms or patterns involved.",
                      "why": "One sentence to the homeowner explaining why this is worth having, citing what was found."}],
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
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE_FILE)


def _patch_state(**fields) -> dict:
    data = _read_state()
    data.update(fields)
    _write_state(data)
    return data


def is_onboarded() -> bool:
    return bool(settings_store.load().get("onboarded"))


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
    STUDY_REQUESTS_DIR.mkdir(parents=True, exist_ok=True)
    already = _studied_topics()
    queued = []
    for i, topic in enumerate(FIRST_TOPICS):
        if topic in already:
            continue  # resumable: don't re-study on a second click
        path = STUDY_REQUESTS_DIR / f"{int(time.time())}-{i}-onboarding-{topic}.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"ts": int(time.time()), "topic": topic}),
                       encoding="utf-8")
        tmp.replace(path)
        queued.append(topic)
    _patch_state(phase="learning", started_at=int(time.time()))
    return {"queued": queued, "already_known": sorted(already)}


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

def build_prompt(memory: str, bundle: dict) -> str:
    parts = ["WHAT HAS BEEN LEARNED ABOUT THIS HOME:", memory.strip() or "(nothing yet)"]
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

    sparse = bool(obj.get("sparse")) or not out
    return {
        "recommendations": out,
        "sparse": sparse,
        "missing": str(obj.get("missing") or "").strip()[:400] if sparse else "",
    }


def save_recommendations(result: dict) -> dict:
    _patch_state(phase="choosing", recommendations=result["recommendations"],
                 sparse=result["sparse"], missing=result["missing"],
                 recommended_at=int(time.time()))
    return result


def stored_recommendations() -> dict:
    state = _read_state()
    return {
        "recommendations": state.get("recommendations") or [],
        "sparse": bool(state.get("sparse")),
        "missing": state.get("missing") or "",
    }


# ---------------------------------------------------------------------------
# Phase 3 — choose
# ---------------------------------------------------------------------------

def accept(indexes: list[int]) -> list[dict]:
    """Create the chosen proposals as user categories and finish onboarding.

    Onboarding completes even when nothing is chosen: someone who reads the
    list and wants none of it is done, not stuck. They can add cards later.
    """
    proposals = stored_recommendations()["recommendations"]
    created = []
    for i in indexes:
        if not isinstance(i, int) or not 0 <= i < len(proposals):
            continue
        p = proposals[i]
        try:
            created.append(user_categories.create({
                "title": p["title"], "icon": p["icon"], "focus": p["focus"],
            }))
        except ValueError as exc:
            log.warning("could not create %r: %s", p["title"], exc)
    settings_store.save({"onboarded": True})
    _patch_state(phase="done", finished_at=int(time.time()),
                 accepted=[p["title"] for p in created])
    return created


def skip() -> None:
    """Finish without cards — the dashboard stays empty until asked."""
    settings_store.save({"onboarded": True})
    _patch_state(phase="done", finished_at=int(time.time()), accepted=[])


def reset() -> None:
    """Run the flow again (Settings). Existing cards are left alone."""
    settings_store.save({"onboarded": False})
    _write_state({"phase": "learning"})


def state() -> dict:
    """Everything the panel needs to render the flow."""
    stored = _read_state()
    return {
        "onboarded": is_onboarded(),
        "phase": stored.get("phase") or "learning",
        "learning": learning_progress(),
        **stored_recommendations(),
    }
