"""A review of the whole house that somebody presses for, on the top tier.

Everything else brAIn writes is about one thing — a card about a category,
a case about a signal, a report about a week — and every one of those runs
on a tier chosen so that it can run often. What none of them can do is sit
with the whole house for a long while and say what it adds up to. That is
the `deep_review` job (`model_plan.JOBS`): Fable, high effort, reading
tools only, and the one job in the plan a scheduler may never name
(`model_plan.PRESS_ONLY`).

Four rules.

* **A press, and the press is told what it costs first.** `estimate` is
  read off the reviews this house has already paid for (their median) and
  a first guess before there are any, against the plan's own session
  allowance — so the button says roughly what share of a five-hour window
  it is about to spend, and says it is an estimate.
* **It reads; it files nothing.** No finding, no proposal, no memory line:
  a review is somebody asking for an opinion, and an opinion that quietly
  changed the work list or the memory would be a second producer nobody
  pressed for. What it says is kept here, capped, and read on the House
  tab; anything in it worth acting on is one question in the chat away.
* **It is told what is already known**, so the page is not a recap. The
  findings block, the measurements and the memory excerpt go in; the
  contract asks for what nothing in brAIn has already said.
* **"I could not read the reviews" is its own answer**, never an empty
  history, because a history that reads empty is a press nobody can
  compare against the last one.

Pure over what it is handed, apart from its own small store.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

import atomic_write
import textclip

STORE = Path(os.environ.get("BRAIN_DEEP_REVIEW_FILE", "/data/deep-review.json"))
MAX_REVIEWS = 6
MAX_OBSERVATIONS = 6
TIMEOUT_S = 1800
MAX_TURNS = 120
JOB = "deep_review"
# Before this house has paid for a review there is nothing to read the cost
# off, so the button says a first guess and says that is what it is. The
# design page's own range is 100–300k; the middle of it.
FIRST_GUESS_TOKENS = 150_000
KINDS = ("problem", "opportunity", "question", "working")

SYSTEM = """You are reviewing a whole home, once, because its owner asked.

You have read-only Home Assistant tools and a long budget. Use them: look at
how the house is actually set up and actually behaves — the automations,
the devices that drop out, the rooms, the energy, the habits brAIn has
measured — and say what it adds up to.

You are told what brAIn already knows and has already raised. Do not repeat
any of it. Your value is what nothing else in brAIn has said: a pattern
across rooms, a cause behind several symptoms, something set up in a way
that will bite later, something that is working well and should be kept.

Rules:
- Up to six observations, each one specific to THIS house: name the rooms
  and devices by their friendly names, say what you saw, say why it matters.
- `kind` is one of: problem, opportunity, question, working.
- `entities` lists the entity ids you actually looked at for it.
- `one_thing` is the single change that would matter most this month.
- `summary` is two or three plain sentences a person reads first.
- Never say anything about the people who live here — their health, their
  whereabouts, who is home, their sleep. The house only.
- No markdown in any field.

Answer with JSON only, in exactly the shape the schema asks for."""

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "observations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "detail": {"type": "string"},
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "entities": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "detail", "kind"],
            },
        },
        "one_thing": {"type": "string"},
    },
    "required": ["summary", "observations", "one_thing"],
}


def frame(*, findings: str = "", house: str = "", memory: str = "",
          weekly: str = "") -> str:
    """What the review is told before it starts looking."""
    parts = ["Review this home. What follows is what brAIn already knows; "
             "use your tools to look past it."]
    for title, body in (("What brAIn has already raised and been told", findings),
                        ("What brAIn has measured", house),
                        ("What brAIn remembers about this home", memory),
                        ("This week's report", weekly)):
        text = str(body or "").strip()
        if text:
            parts += ["", f"## {title}", text[:12000]]
    parts += ["", "Now look for yourself, then answer."]
    return "\n".join(parts)


def _clean(text, cap: int) -> str:
    return textclip.clip(" ".join(str(text or "").split()), cap)


def parse(answer: dict | None) -> dict | None:
    """The review out of a validated reply, or None if there is none.

    A reply with no summary and no observations is no review: storing it
    would put an empty page where the last real one was.
    """
    if not isinstance(answer, dict):
        return None
    observations = []
    for obs in answer.get("observations") or []:
        if not isinstance(obs, dict):
            continue
        title = _clean(obs.get("title"), 140)
        detail = _clean(obs.get("detail"), 800)
        if not title:
            continue
        kind = obs.get("kind") if obs.get("kind") in KINDS else "problem"
        ents = [e for e in (obs.get("entities") or [])
                if isinstance(e, str) and "." in e][:12]
        observations.append({"title": title, "detail": detail, "kind": kind,
                             "entities": ents})
        if len(observations) >= MAX_OBSERVATIONS:
            break
    summary = _clean(answer.get("summary"), 800)
    if not summary and not observations:
        return None
    return {"summary": summary, "observations": observations,
            "one_thing": _clean(answer.get("one_thing"), 300)}


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load() -> dict:
    """``{"reviews": [...newest first], "error": ""}``.

    A store that is missing is an empty history; one that is there and
    cannot be read says so, because "no reviews yet" and "the reviews are
    unreadable" are different answers to somebody about to pay for another.
    """
    try:
        raw = STORE.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"reviews": [], "error": ""}
    except OSError as exc:
        return {"reviews": [], "error": f"the saved reviews could not be read ({exc})"}
    try:
        data = json.loads(raw)
    except ValueError:
        return {"reviews": [], "error": "the saved reviews are not valid JSON"}
    reviews = [r for r in (data.get("reviews") if isinstance(data, dict) else []) or []
               if isinstance(r, dict)]
    return {"reviews": reviews, "error": ""}


def save(review: dict, now: float | None = None) -> dict:
    """Keep one more review, newest first, capped. Returns what was stored."""
    now = time.time() if now is None else now
    entry = {"id": int(now * 1000), "at": int(now), **review}
    current = load()
    if current["error"]:
        # Overwriting a file we could not read would lose whatever was in
        # it; refusing to keep the new one loses a review somebody paid
        # for. Keep the new one beside a copy of the unreadable original.
        try:
            STORE.replace(STORE.with_suffix(".unreadable"))
        except OSError:
            # The copy is a courtesy; the write below goes ahead either
            # way, because the review just paid for is the thing to keep.
            pass
    reviews = [entry] + [r for r in current["reviews"] if r.get("id") != entry["id"]]
    reviews = reviews[:MAX_REVIEWS]
    STORE.parent.mkdir(parents=True, exist_ok=True)
    atomic_write.write_text(str(STORE), json.dumps({"reviews": reviews}, indent=1))
    return entry


def estimate(reviews: list[dict], plan_session_tokens: int | None) -> dict:
    """What the next review will probably cost, and what that is a share of.

    ``{"tokens", "basis", "percent"}``. The median of what earlier reviews
    on this house actually spent, the first guess otherwise — and the
    share of the plan's estimated five-hour allowance, which is the only
    unit a person has an intuition for.
    """
    spent = [int(r["tokens"]) for r in reviews or []
             if isinstance(r, dict) and isinstance(r.get("tokens"), int)
             and r["tokens"] > 0][:3]
    if spent:
        tokens = int(statistics.median(spent))
        basis = (f"what the last {len(spent)} review{'s' if len(spent) > 1 else ''} "
                 "on this house cost")
    else:
        tokens = FIRST_GUESS_TOKENS
        basis = "a first guess — no review has run here yet"
    percent = None
    if plan_session_tokens:
        percent = min(100, round(tokens / plan_session_tokens * 100))
    return {"tokens": tokens, "basis": basis, "percent": percent}


__all__ = ["FIRST_GUESS_TOKENS", "JOB", "KINDS", "MAX_OBSERVATIONS",
           "MAX_REVIEWS", "SCHEMA", "STORE", "SYSTEM", "estimate", "frame",
           "load", "parse", "save"]
