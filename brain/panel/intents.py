"""A sentence that happens once, and then is not there any more.

*"Turn the porch light off when the guests leave."* It is the sentence
people already try to say to their house, and no automation model fits
it: an automation is a standing rule, and this is a thing to do next
time. Building it by hand means writing a rule, remembering it exists,
and going back to delete it — which is why nobody does, and why the
houses that try end up with a folder of automations nobody dares turn
off.

**Home Assistant does the running and the card does the cleanup.** What
gets written is an ordinary automation with `mode: single` and one extra
action nobody asked the model for: `automation.turn_off` on itself. So it
fires once and disarms, there is no listener in the add-on to keep alive
across a restart, and nothing is left behind that is still *doing*
anything. What is left is a row on the tab saying it fired and offering
to take it out, because **nothing removes it on its own**: an automation
that vanished from somebody's file while they were not looking is a file
they cannot trust.

**Claude writes the config once, with reading tools only.**
`engine.run_analyst` can search the house for the entity a sentence
names and cannot act on it — the middle of the three Claude paths, and
the right one here for the reason it is the right one for an unattended
card. What comes back is checked before it becomes anything:

*The trigger has to be replayable.* `shadow.check_replayable` is asked of
every config, and the prompt says so and says why — not because a one-off
needs a shadow week, but because the replay on the card is the only
sanity check there is on a trigger that has never fired. A `webhook` or a
`device` trigger would give a card with no number on it and nothing to
read but the model's own restatement of itself.

*It has to act once.* The model is asked for a boolean, and `once: false`
is a **refusal with the restatement shown** rather than a silent
rewrite: *"every evening at sunset"* is a standing rule, it is a good
thing to want, and it belongs on the ordinary path where it gets a
replay, a trial and a week. Saying which it heard is what lets somebody
correct the sentence rather than wonder.

*It has to name something.* A sentence with no entity behind it produces
an automation that does nothing, and an automation that does nothing is
indistinguishable from one that has not fired yet.

*And it may not touch a protected entity.* Asked here as well as at the
writer, because a card offering something `automation_writer` will refuse
is a wasted no.

**Two front doors, one request file.** The ask bar routes a sentence
beginning *when…* / *once…* / *the next time…* here, and the integration's
`brain.intent` service lets voice reach it. Both write the same small
JSON file on the shared volume that `finding_requests.py` established the
shape of, and the panel drains it — so the expensive half has one
implementation and one place to be wrong.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.intents")

# The drop directory. `finding_requests.py`'s shape and its reasons: the
# panel owns the store, Home Assistant cannot reach 8099, and what
# crosses the gap is a request rather than a write.
REQUEST_DIR = Path(os.environ.get(
    "BRAIN_INTENT_REQUESTS_DIR", "/config/.brain/intent-requests"))
STORE = Path(os.environ.get("BRAIN_INTENTS_FILE", "/data/intents.json"))

# A sentence, not an essay. Past this it is a specification and belongs on
# the ordinary ask path where it gets a card and a conversation.
MAX_SENTENCE = 300
# A request is a few hundred bytes; anything larger is not one.
MAX_BYTES = 8 * 1024
MAX_PER_PASS = 5
MAX_QUEUED = 100
KEEP_S = 7 * 86400

# How many one-offs may be armed at once. More than this and the tab has
# stopped being a short list of things about to happen.
MAX_ARMED = 6
MAX_ROWS = 60
# An intent that has not fired in a fortnight is almost certainly about
# something that already happened. It is **offered** a Remove at that
# point and never removed: see the module docstring.
INTENT_TTL_DAYS = 14

# One turn of searching, a handful of tool calls. It is not an insight
# run: the whole job is to find one entity and write four lines of YAML.
TIMEOUT_S = 180
MAX_TURNS = 8

ID_PREFIX = "brain_intent_"
# `armed` is waiting on the house, `fired` has happened, and `refused` is
# a sentence brAIn will not arm. All three are on the tab and all three
# can be answered, which is the contract the Proposals tab keeps: a
# refusal that was only a log line would be somebody typing a sentence
# and watching nothing happen.
STATUSES = ("armed", "fired", "refused")
# A stream of sentences brAIn cannot use must not push the armed ones off
# the tab, so the refusals are pruned oldest-first among themselves.
MAX_REFUSED = 5

# What `run_analyst` is told. The contract is the whole of it, because the
# checks that follow are refusals and a model that knows them wastes fewer
# of them.
SYSTEM = """You turn one sentence from the person who lives in a house
into one Home Assistant automation that runs ONCE.

Use the read-only tools to find the entities the sentence is about. Search
by name; do not guess an entity id.

Answer with ONE JSON object and nothing else. No markdown fence, no
commentary.

  {"once": true,
   "plain": "<one sentence: what you understood, in their words>",
   "trigger": [ ... ], "condition": [ ... ], "action": [ ... ]}

Rules, and each of them is something brAIn will refuse the answer over:

* `trigger` may only use `time`, `state`, `numeric_state` or `template`.
  Those are the four Home Assistant's recorder can replay, and the card
  this becomes shows the person how often the trigger would have fired
  over the last month — which is the only check there is on a trigger
  that has never fired. Any other kind (`device`, `event`, `webhook`,
  `mqtt`, `sun`, `zone`) makes the answer unusable.
* `action` is what to do, and it names entities by id. Do not add an
  action that switches the automation off — brAIn writes that itself.
* `condition` may be omitted or empty.
* Do not set `id`, `alias`, `mode` or `description`.
* `once` is `false` if what they asked for is a standing rule — something
  that should keep happening — rather than a single thing to do next
  time. Say so in `plain` and leave the rest out; brAIn will offer them
  the other path.
* If nothing in the house matches what they named, answer
  {"once": true, "error": "<what you looked for and did not find>"}.

Be literal. A sentence you half-understood, written as an automation,
is a thing that happens in somebody's house."""


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# The request file — one shape, two front doors
# ---------------------------------------------------------------------------

def request(sentence: str, via: str = "panel",
            now: float | None = None) -> str:
    """Queue one sentence. Returns what was queued, or "" for nothing.

    The panel's own writer. The integration writes the identical shape
    from Home Assistant's side (`custom_components/brain/requests.py`), and
    `tests/test_intents.py` drives both into `parse_request` rather than
    writing the format down twice.
    """
    text = str(sentence or "").strip()[:MAX_SENTENCE]
    if not text:
        return ""
    now = _now() if now is None else now
    REQUEST_DIR.mkdir(parents=True, exist_ok=True)
    # Milliseconds and a counter, because several sentences in one burst
    # land inside the same millisecond and the stamp alone does not order
    # them — the reason the integration's own writer carries one too.
    stamp = f"{int(now * 1000)}-{next(_COUNTER):04d}"
    # `atomic_write` rather than a hand-rolled scratch-and-rename: its own
    # scratch is a dotted random name that ends in `.tmp`, so the drain's
    # `*.json` glob cannot see half a request, and this file does not get
    # to invent a second answer to "how is a file replaced safely".
    atomic_write.write_json(REQUEST_DIR / f"{stamp}.json",
                            {"ts": int(now), "sentence": text,
                             "via": str(via or "")[:32]})
    return text


def _counter():
    n = 0
    while True:
        n = (n + 1) % 10000
        yield n


_COUNTER = _counter()


def parse_request(obj) -> dict | None:
    """A validated request, or None for anything that is not one.

    Every field is data from another process: the stamp is a number or
    the request is dropped, the sentence is capped, and `via` is a label
    for the log line and for nothing else — an intent is an intent
    whichever surface asked for it, and a per-surface rule here would be
    a second policy nobody can see.
    """
    if not isinstance(obj, dict):
        return None
    ts = obj.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return None
    sentence = str(obj.get("sentence") or "").strip()[:MAX_SENTENCE]
    if not sentence:
        return None
    return {"ts": int(ts), "sentence": sentence,
            "via": str(obj.get("via") or "")[:32]}


def _files() -> list[Path]:
    try:
        found = [p for p in REQUEST_DIR.glob("*.json") if p.is_file()]
    except OSError:
        return []
    found.sort(key=lambda p: p.name)
    return found


def _drop_file(path: Path) -> None:
    try:
        path.unlink()
    except OSError as exc:
        log.info("could not remove %s: %s", path, exc)


def collect(now: float | None = None) -> list[dict]:
    """Take what is waiting: validated requests, files removed.

    Bounded, for the reason the findings queue is: an add-on off for a
    week must not spend its first minute on a directory nothing drained.
    """
    now = _now() if now is None else now
    files = _files()
    stale = []
    for path in files:
        try:
            if now - path.stat().st_mtime > KEEP_S:
                stale.append(path)
        except OSError:
            continue
    keep = [p for p in files if p not in stale]
    if len(keep) > MAX_QUEUED:
        stale += keep[:len(keep) - MAX_QUEUED]
        keep = keep[len(keep) - MAX_QUEUED:]
    for path in stale:
        _drop_file(path)

    out: list[dict] = []
    for path in keep[:MAX_PER_PASS]:
        req = None
        try:
            if path.stat().st_size <= MAX_BYTES:
                req = parse_request(json.loads(
                    path.read_text(encoding="utf-8", errors="replace")))
        except (OSError, ValueError):
            req = None
        _drop_file(path)
        if req is None:
            log.info("ignored an unreadable intent request: %s", path.name)
            continue
        out.append(req)
    return out


def pending() -> int:
    return len(_files())


# ---------------------------------------------------------------------------
# Asking Claude, and reading what comes back
# ---------------------------------------------------------------------------

def prompt(sentence: str, orientation: dict | None = None) -> str:
    """The sentence, and the map of the house it is about.

    `collect_orientation`'s small bundle rather than the whole house, for
    the reason `gather_mode: search` exists at all: a card fetches what it
    needs, and one sentence about a porch light does not want five
    hundred rows. The map names the areas and the domain counts; the
    entity is Claude's to find.
    """
    orientation = orientation or {}
    lines = [f'They said: "{str(sentence).strip()}"', ""]
    areas = orientation.get("areas") or {}
    names = list(areas) if isinstance(areas, dict) else list(areas)
    if names:
        lines.append("Areas in this house: "
                     + ", ".join(str(a) for a in names[:60]))
    domains = orientation.get("domains") or {}
    if isinstance(domains, dict) and domains:
        lines.append("What it has: " + ", ".join(
            f"{k} ({v})" for k, v in sorted(domains.items())[:30]))
    stamp = (orientation.get("meta") or {}).get("now")
    if stamp:
        lines.append(f"It is now {stamp}.")
    lines += ["", "Search for what they named, then answer with the one "
                  + "JSON object."]
    return "\n".join(lines)


_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def parse_answer(text: str) -> dict | None:
    """Claude's JSON, or None if there is none in there.

    A fenced block is tolerated because the model sometimes adds one
    despite being told not to, and refusing over punctuation would spend
    somebody's sentence on a formatting rule.
    """
    raw = str(text or "").strip()
    match = _FENCE.search(raw)
    if match:
        raw = match.group(1).strip()
    if not raw.startswith("{"):
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            return None
        raw = raw[start:end + 1]
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def title_for(sentence: str) -> str:
    """What the automation is called in somebody's automations list.

    Their own sentence, because in six months that is the only thing that
    says why it is there — and because it is what `automation_writer`
    turns into the entity id the disarming action targets.
    """
    text = " ".join(str(sentence or "").split())[:120]
    return text[:1].upper() + text[1:] if text else "A one-off from brAIn"


def disarm(entity_id: str) -> dict:
    """The action brAIn adds and the model is told not to.

    Written by code rather than asked for, because it is the whole
    difference between a one-off and a rule somebody has to remember to
    delete — and a model that forgot it once would leave a standing
    automation behind under a card that says it fired.
    """
    return {"service": "automation.turn_off",
            "target": {"entity_id": entity_id},
            "data": {"stop_actions": False}}


def _listify(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, (list, tuple)) else [value]


def build(sentence: str, answer: dict, ts: int,
          patterns: list[str] | None = None) -> dict:
    """One proposal from one answer, or one carrying `refused`.

    Never raises and never returns None: a sentence somebody typed always
    gets an answer, and *"brAIn could not do this and here is why"* is one
    of them. The refusals are the module docstring's, in its order.
    """
    import automation_writer  # noqa: PLC0415 — panel-local
    import shadow  # noqa: PLC0415

    plain = str(answer.get("plain") or "").strip()[:400]
    out = {
        "kind": "intent",
        "source": "intent",
        "title": title_for(sentence),
        "sentence": str(sentence).strip()[:MAX_SENTENCE],
        "plain": plain,
    }

    if answer.get("error"):
        out["refused"] = (
            "brAIn could not find what that sentence is about: "
            f"{str(answer['error'])[:200]}")
        return out
    if answer.get("once") is False:
        out["refused"] = (
            "that sounds like a standing rule rather than a one-off — "
            "something that should keep happening. brAIn only writes a "
            "one-off here. Ask for it as an ordinary change instead and it "
            "gets a replay, a trial week and a report.")
        return out

    triggers = _listify(answer.get("trigger") or answer.get("triggers"))
    steps = _listify(answer.get("action") or answer.get("actions"))
    if not triggers or not steps:
        out["refused"] = ("brAIn did not get an automation back it could "
                          "use — there was no trigger or no action in it.")
        return out

    alias = out["title"]
    entity_id = f"automation.{automation_writer.slugify(alias)}"
    config = {
        "id": f"{ID_PREFIX}{int(ts)}",
        "trigger": triggers,
        "condition": _listify(answer.get("condition")
                              or answer.get("conditions")),
        "action": list(steps) + [disarm(entity_id)],
        # Not the model's to choose. A one-off that could run twice at
        # once is a one-off that is not one.
        "mode": "single",
    }

    try:
        shadow.check_replayable(config)
    except shadow.Refused as exc:
        out["refused"] = (
            f"brAIn will not arm this: {exc} — and without a replay there "
            "is nothing to check a trigger that has never fired against.")
        return out

    named = set()
    for call in shadow.would_do(config):
        if call.get("service") == "automation.turn_off":
            continue                 # brAIn's own, and not evidence of one
        raw = call.get("entity_id")
        named |= {str(e) for e in _listify(raw) if e}
        if any(call.get(f"{k}_id")
               for k in ("area", "device", "label", "floor")):
            named.add("a target")
    if not named:
        out["refused"] = ("that sentence did not name anything in this "
                          "house that brAIn could act on, so the automation "
                          "would have done nothing.")
        return out

    refusal = automation_writer._protected_refusal(
        config, automation_writer.protected_patterns(patterns))
    if refusal:
        out["refused"] = refusal
        return out

    out["config"] = config
    out["entity_id"] = entity_id
    out["why"] = why_for(sentence, plain)
    out["intent"] = {"sentence": out["sentence"], "plain": plain,
                     "entity_id": entity_id, "ttl_days": INTENT_TTL_DAYS}
    return out


def why_for(sentence: str, plain: str) -> str:
    said = plain or "brAIn did not say what it understood."
    return (f'You asked: "{str(sentence).strip()}". brAIn understood: '
            f"{said} It runs once and switches itself off; nothing removes "
            "it from your automations until you press Remove.")


# ---------------------------------------------------------------------------
# The armed store — what is waiting to happen, and what already has
# ---------------------------------------------------------------------------

def _read() -> list[dict]:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = data.get("intents") if isinstance(data, dict) else data
    return [r for r in (rows or []) if isinstance(r, dict)]


def listing() -> list[dict]:
    """Every armed or fired intent, newest first."""
    return sorted(_read(), key=lambda r: r.get("ts", 0), reverse=True)


def _write(rows: list[dict]) -> None:
    atomic_write.write_json(STORE, {"intents": rows[-MAX_ROWS:]})


def armed_count(rows: list[dict] | None = None) -> int:
    rows = listing() if rows is None else rows
    return sum(1 for r in rows if r.get("status") == "armed")


def arm(row: dict, applied: dict, now: float | None = None) -> dict | None:
    """Record an accepted intent as waiting to happen.

    Called after the automation is written, reloaded and verified — never
    before. A row here says the house is holding something, and one that
    said so about an automation Home Assistant never loaded would be the
    "the file was written" / "the automation exists" confusion with a
    card on top of it.
    """
    now = _now() if now is None else now
    rows = listing()
    ts = int(row.get("ts") or now * 1000)
    if any(int(r.get("ts") or 0) == ts for r in rows):
        return None
    entry = {
        "ts": ts,
        "title": str(row.get("title") or "")[:160],
        "sentence": str((row.get("intent") or {}).get("sentence")
                        or row.get("sentence") or "")[:MAX_SENTENCE],
        "plain": str((row.get("intent") or {}).get("plain") or "")[:400],
        "automation_id": str(applied.get("automation_id") or ""),
        "entity_id": str(applied.get("entity_id") or ""),
        "status": "armed",
        "accepted_at": int(now),
        "fired_at": 0,
    }
    rows.append(entry)
    _write(rows)
    return entry


def note(obj: dict, now: float | None = None) -> dict | None:
    """Record a sentence brAIn will not arm, with the reason on it.

    A person typed something and is waiting for an answer, so *"brAIn
    could not do this and here is why"* is one — and it goes on the tab
    rather than into the log, because a refusal nobody sees is
    indistinguishable from a feature that does nothing. It is answerable:
    the answer is Dismiss.
    """
    now = _now() if now is None else now
    rows = listing()
    ts = int(now * 1000)
    taken = {int(r.get("ts") or 0) for r in rows}
    while ts in taken:               # two refusals inside one millisecond
        ts += 1
    entry = {
        "ts": ts,
        "title": str(obj.get("title")
                     or title_for(obj.get("sentence") or ""))[:160],
        "sentence": str(obj.get("sentence") or "")[:MAX_SENTENCE],
        "plain": str(obj.get("plain") or "")[:400],
        "status": "refused",
        "refused": str(obj.get("refused") or "")[:600],
        "automation_id": "", "entity_id": "",
        "accepted_at": 0, "fired_at": 0,
    }
    rows.append(entry)
    refused = [r for r in rows if r.get("status") == "refused"]
    if len(refused) > MAX_REFUSED:
        drop_ts = {int(r.get("ts") or 0)
                   for r in sorted(refused, key=lambda r: r.get("ts", 0))
                   [:len(refused) - MAX_REFUSED]}
        rows = [r for r in rows if int(r.get("ts") or 0) not in drop_ts]
    _write(rows)
    return entry


def get(ts: int) -> dict | None:
    for row in listing():
        if int(row.get("ts") or 0) == int(ts):
            return row
    return None


def mark_fired(ts: int, when: float) -> dict | None:
    rows = listing()
    for row in rows:
        if int(row.get("ts") or 0) == int(ts) and row.get("status") == "armed":
            row["status"] = "fired"
            row["fired_at"] = int(when)
            _write(rows)
            return row
    return None


def drop(ts: int) -> dict | None:
    """Take one row off the list. The Remove press's half of the work."""
    rows = listing()
    for i, row in enumerate(rows):
        if int(row.get("ts") or 0) == int(ts):
            rows.pop(i)
            _write(rows)
            return row
    return None


def restore(row: dict) -> bool:
    """Put a removed row back — the undo half. Refuses over an occupied id.

    Keyed on the original `ts` for the reason `findings_store.restore` and
    `proposals.reopen` are: that id is what the pending token and any open
    dialog hold, and a row that came back under a new one would be a
    different row to everything referring to it.
    """
    ts = int(row.get("ts") or 0)
    if not ts:
        return False
    rows = listing()
    if any(int(r.get("ts") or 0) == ts for r in rows):
        return False
    rows.append(dict(row))
    _write(rows)
    return True


def expired(row: dict, now: float | None = None) -> bool:
    """Whether an armed intent has been waiting longer than anyone meant.

    It is a **label**, never a deletion: what a fortnight of silence means
    is almost always that the thing already happened and nobody told the
    house, and the answer to that is a card that says so with a Remove on
    it, not a file that quietly changed.
    """
    now = _now() if now is None else now
    return (row.get("status") == "armed"
            and (now - (row.get("accepted_at") or 0))
            > INTENT_TTL_DAYS * 86400)


def fired_from_state(row: dict, state: dict | None) -> float:
    """When this intent fired, from Core's own row, or 0.

    `last_triggered` is read rather than the automation being `off`,
    because a person switching it off by hand is not it having fired —
    and the stamp has to be **after** the accept, or an automation that
    happens to share a slug with one that fired last month reads as done.
    """
    import datetime as dt  # noqa: PLC0415

    attrs = (state or {}).get("attributes") or {}
    stamp = attrs.get("last_triggered")
    if not stamp:
        return 0.0
    try:
        parsed = dt.datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        # `.timestamp()` reads a naive value as LOCAL time, and Core
        # stamps this in UTC. The error is the house's own offset, in
        # whichever direction: east of Greenwich a fired one-off resolves
        # to before its own accept and goes on reading as waiting, west
        # of it something that ran before the accept reads as this firing.
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    when = parsed.timestamp()
    return when if when > (row.get("accepted_at") or 0) else 0.0


__all__ = [
    "ID_PREFIX", "INTENT_TTL_DAYS", "MAX_ARMED", "MAX_PER_PASS",
    "MAX_QUEUED", "MAX_REFUSED", "MAX_ROWS", "MAX_SENTENCE",
    "REQUEST_DIR", "STATUSES",
    "STORE", "SYSTEM", "TIMEOUT_S", "MAX_TURNS", "arm", "armed_count",
    "build", "collect", "disarm", "drop", "expired", "fired_from_state",
    "get", "listing", "mark_fired", "note", "parse_answer",
    "parse_request",
    "pending", "prompt", "request", "restore", "title_for", "why_for",
]
