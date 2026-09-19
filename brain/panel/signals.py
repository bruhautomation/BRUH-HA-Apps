"""Signals — what the house just did, scored so it can be ordered, and
never a verdict about any of it.

Everything brAIn knows how to notice today ends in a rule deciding what a
household is told: a check files a finding, a baseline files a finding, a
producer composes a proposal. The Resident inverts that — the rules become
*senses* and the deciding moves to a model — and a sense needs one shape
to speak in. This is it.

A signal is a small dict. It says what kind of thing happened, what it
happened to, what was observed, when it was noticed, and one arithmetic
number that ORDERS a batch. It carries no verdict, no severity judgement
of its own, no advice and no text a person is ever shown as brAIn's
opinion — because the whole point of the first look is that the judging
happens once, in one place, by something that can read a house.

Three rules hold that line, and every function below is written against
them.

**Salience orders, it never decides.** It is a weighted sum of facts that
are already written down somewhere else — the row's own severity, the
producer's declared urgency, whether the entity is on the protected list,
whether its device class is one of the four that mean *the house is in
trouble*, whether it happened at an hour nobody is usually up, how long
ago, how many times. Every weight is a named constant with a reason. It
is deliberately legible and deliberately crude: a number that wanted to be
right would be a rule deciding again, and the thing that decides is one
tier up.

**`hot` is a closed set and nothing else may join it.** Hot means *look
now rather than on the timer*, which is the one thing a signal is allowed
to cause by itself, so it is four cases named in the plan and a test that
pins them: a leak, smoke, CO or gas sensor going on; a protected entity
moving; a person-level event at an hour this house is not usually up; a
trace error on an automation brAIn itself wrote. A `critical` finding is
not hot — severity is how bad a thing is and hot is how soon somebody has
to think about it, and a battery three weeks from flat is the case that
tells the two apart.

**Pure over what it is handed.** No fetches, no store reads, no clock but
the `now` every function takes. A signal is built from an event or a row
that somebody else already has, which is what lets the event bus build one
inside a WebSocket pump and lets a test build one out of a literal.

Where a fact already has a home, it is read from there rather than
restated: urgency is `notify_router.urgency_of`'s, which is declared per
producer; a check's own name is `checks.get_check`'s; the protected
patterns are `automation_writer`'s. The one window that is stated here is
the fallback night, and only because a house with no measured rhythm has
no other answer.

Panel-local only — the stdlib plus the modules that already own the facts
it reads — so the suite can import it without the add-on runtime and the
event bus can call it inside a socket pump. `notify_router` is the one
taken at import time because every adapter asks it something; the rest
(`checks`, `closures`, `automation_writer`, `rhythm`) are taken where they
are needed, which keeps this importable on its own and keeps it out of any
cycle a future caller draws.
"""
from __future__ import annotations

import datetime as dt
import math

import notify_router

# ---------------------------------------------------------------------------
# The vocabulary
# ---------------------------------------------------------------------------

# What a signal can be about. Closed, because every reader below switches
# on it and a kind nobody wrote a weight for would score as whatever the
# default happened to be — which is a rule deciding by omission.
KINDS = (
    "check",        # a house-check row; the existing checks, new destination
    "baseline",     # a reading outside its own measured band
    "thermal",      # a fall past a room's k, a freeze runway
    "appliance",    # a cycle ended and something is waiting to be emptied
    "state",        # a state_changed on an entity that matters
    "trace_error",  # an automation trace that ended in an error
    "override",     # a person put back what an automation had just done
    "presence",     # somebody arrived or left
    "reply",        # a person answered a notification, or asked from HA
    "time",         # a scheduled moment: the evening pass, the morning
)

# What a signal says about itself, and the only shape any reader may
# assume. `repeats` is always present and always at least 1 rather than
# appearing when `dedupe` has run: a reader that branches on a key being
# there is a second answer to "how many times", and the batch the first
# look is handed has been through `dedupe` by construction anyway.
#
#   kind      one of KINDS
#   subject   the entity id / automation id / person id / check id it is
#             about. One string, because it is what `dedupe` keys on and
#             what a model is asked to reason about.
#   salience  0..1. Orders. Never decides.
#   evidence  a short list of {entity, value, when} rows — what was
#             observed, not what it means. Capped both ways.
#   seen_at   epoch when this was noticed, which is not always when it
#             happened: a check filing at 06:00 about a battery that went
#             flat overnight is one of those.
#   source    who raised it, in the same vocabulary the findings store
#             uses ("check:dev.frozen", "eventbus", "thermal"). It is what
#             a mute, a scorecard and a log line all key on.
#   hot       look now rather than on the timer. The closed set above.
#   repeats   how many of the same (kind, subject) `dedupe` folded in.
#   text      one short line, taken from whatever raised it and never
#             composed into an opinion here. What `prompt_rows` renders.
SIGNAL_KEYS = ("kind", "subject", "salience", "evidence", "seen_at",
               "source", "hot", "repeats", "text")

# An evidence row is a thing that was read off the house, so all three
# fields are somebody else's data and all three are capped.
MAX_EVIDENCE = 6           # more than this is a report, not evidence
MAX_EVIDENCE_ENTITY = 120
MAX_EVIDENCE_VALUE = 80    # a state, a number, a short phrase
MAX_SUBJECT = 160
MAX_SOURCE = 64
MAX_TEXT = 200             # findings_store.MAX_TEXT, for the same reason

# One first look reads this many signals. It is a prompt budget rather
# than a policy: past it the rest wait for the next look, which is minutes
# away, and `batch` says how many waited so nothing is silently dropped.
MAX_BATCH = 24


# ---------------------------------------------------------------------------
# Salience: arithmetic, and honest about being arithmetic
# ---------------------------------------------------------------------------

# Where a kind starts before anything is known about the particular row.
# A person speaking outranks anything a rule noticed, because somebody is
# waiting; a trace error outranks a reading, because something is already
# broken rather than possibly odd; a scheduled moment is the floor,
# because it is the one signal that says nothing happened at all.
KIND_BASE = {
    "reply": 0.30,
    "trace_error": 0.26,
    "thermal": 0.24,
    "check": 0.20,
    "baseline": 0.18,
    "override": 0.16,
    "state": 0.12,
    "appliance": 0.10,
    "presence": 0.10,
    "time": 0.05,
}

# How bad, as the producer already said. `findings_store.SEVERITIES`'
# four words, weighted rather than re-ordered — an `info` row contributes
# nothing here, which is the honest reading of a word that means "worth
# knowing and not worth doing anything about".
SEVERITY_WEIGHT = {"info": 0.0, "warning": 0.10, "serious": 0.22,
                   "critical": 0.34}
DEFAULT_SEVERITY = "warning"

# How soon, as `notify_router` already declared per producer. The two are
# different axes and both are here for the reason that module gives: a
# critical battery forecast is three weeks out and a `now` producer files
# plenty of rows that are merely a nuisance.
URGENCY_WEIGHT = {"whenever": 0.0, "today": 0.05, "now": 0.14}

# An entity somebody put on the protected list is one they have said out
# loud that brAIn may not touch — which is also a statement that it
# matters. It orders above an ordinary one for that reason and for no
# other; nothing here may act on it either way.
W_PROTECTED = 0.18
# A leak, smoke, CO or gas sensor. This is the largest single weight
# because it is the only one that is about the house being unsafe rather
# than about it being untidy.
W_SAFETY = 0.22
# brAIn already holds a fact about this entity, so whatever just happened
# has something to be read against. Small: it makes a signal more
# *answerable*, not more important.
W_KNOWN = 0.06
# Something happened at an hour this house is not usually up.
W_ODD_HOUR = 0.10

# Recency, as a half-life rather than a window: a signal does not stop
# mattering at a boundary, it stops mattering gradually, and a cliff is
# what makes two signals a second apart score a tenth apart.
W_RECENCY = 0.10
RECENCY_HALF_LIFE_S = 1800.0   # half an hour — one first-look interval or two

# Repeats. The same thing happening again is evidence it is real, and it
# stops being evidence quickly: five of anything says what three said.
W_REPEAT_EACH = 0.02
REPEAT_CAP = 4

# The night, when nothing measured says otherwise. Hours, local, and the
# window crosses midnight by construction — which is why the comparison is
# `notify_router.in_quiet_hours`' rather than a second `start <= h < end`
# that answers backwards at every hour of it.
NIGHT_START_H = 23
NIGHT_END_H = 6

# The device classes that make a state change hot. Deliberately narrower
# than `episodes.SAFETY_CLASSES`, which also carries `safety`, `problem`,
# `tamper`, `heat` and `cold` — that set answers "which section of a
# timeline does this row belong in", and this one answers "may this wake
# a house at three in the morning". `moisture` is Home Assistant's class
# for a leak detector, which is the one people would look for by another
# name.
HOT_SAFETY_CLASSES = frozenset({"smoke", "gas", "carbon_monoxide",
                                "moisture"})
# The states those sensors are in when they mean it.
HOT_SAFETY_STATES = frozenset({"on", "detected", "wet", "unsafe"})

# Person-level domains. A `person` is Home Assistant's own idea of a
# household member; a `device_tracker` is a phone, which is a weaker
# claim about the same thing and is why both are `presence` rather than
# one of them being authoritative.
PERSON_DOMAINS = frozenset({"person", "device_tracker"})

# An automation brAIn wrote carries this prefix on its id, which is
# `automation_writer.ID_PREFIX` and is read from there rather than
# restated — one spelling, because a rename on one side is a hot set that
# quietly stops firing.
BRAIN_ID_PREFIX = "brain_"

# States that are not a reading of anything.
EMPTY_STATES = frozenset({"", "unknown", "none"})


def _clamp(value: float) -> float:
    """0..1, rounded so two equal scores sort stably and print short."""
    return round(max(0.0, min(1.0, float(value))), 3)


def score(kind: str, *, severity: str = "", urgency: str = "",
          protected: bool = False, safety: bool = False,
          known: bool = False, odd_hour: bool = False,
          age_s: float = 0.0, repeats: int = 1) -> float:
    """How far up a batch this belongs. One sum, all weights named above.

    Every argument is a fact something else established: the severity is
    the producer's word, the urgency is `notify_router`'s table, protected
    is the option, safety is a device class, odd hour is the measured
    rhythm. Nothing is inferred here, which is what makes the number
    arguable — a person reading a batch can see why one row is above
    another without running anything.
    """
    total = KIND_BASE.get(kind, KIND_BASE["state"])
    total += SEVERITY_WEIGHT.get(severity, 0.0)
    total += URGENCY_WEIGHT.get(urgency, 0.0)
    if protected:
        total += W_PROTECTED
    if safety:
        total += W_SAFETY
    if known:
        total += W_KNOWN
    if odd_hour:
        total += W_ODD_HOUR
    if age_s >= 0:
        total += W_RECENCY * math.pow(0.5, age_s / RECENCY_HALF_LIFE_S)
    total += W_REPEAT_EACH * min(max(int(repeats) - 1, 0), REPEAT_CAP)
    return _clamp(total)


# ---------------------------------------------------------------------------
# What counts as an odd hour
# ---------------------------------------------------------------------------

def night_window(rhythm_payload: dict | None = None,
                 when: dt.datetime | None = None) -> tuple[int, int]:
    """The hours this house is not usually up, as (start, end).

    Measured where there is a measurement: `rhythm.settle_minute` and
    `rhythm.wake_minute` are what this house actually does, and a fixed
    23–6 is somebody else's evening. The payload is passed in rather than
    loaded, so this stays pure and a caller with no rhythm store — a
    fresh install, a test — gets the fallback and knows it did. So does a
    caller with a payload and no `when`: see below.

    The two are read for the SAME day, which is what makes a window that
    crosses midnight come out as one: a settle of 23:10 and a wake of
    07:20 is (23, 7), and the comparison that reads it handles the wrap.
    """
    if not isinstance(rhythm_payload, dict) or not rhythm_payload:
        return NIGHT_START_H, NIGHT_END_H
    if when is None:
        # A measured night is measured per KIND of day — a weekday
        # settle and a weekend one are two shapes — so reading one needs
        # to know which day it is, and taking that off the wall clock is
        # the one clock reach this module does not make. Without a
        # moment the honest answer is the fallback.
        return NIGHT_START_H, NIGHT_END_H
    import rhythm  # noqa: PLC0415 — panel-local, and only needed here

    settle = rhythm.settle_minute(rhythm_payload, when)
    wake = rhythm.wake_minute(rhythm_payload, when)
    if settle is None or wake is None:
        return NIGHT_START_H, NIGHT_END_H
    start = int(settle // 60) % 24
    end = int(wake // 60) % 24
    # A measured pair that lands on the same hour is a house with no
    # night — which is not a thing, so it is a measurement this cannot
    # use. `in_quiet_hours` reads start == end as "no window" for the
    # same reason, and falling back says which answer is being given.
    if start == end:
        return NIGHT_START_H, NIGHT_END_H
    return start, end


def is_odd_hour(now: float, rhythm_payload: dict | None = None,
                tz: dt.tzinfo | None = None) -> bool:
    """Whether `now` is inside this house's night.

    The wrap is `notify_router.in_quiet_hours`' arithmetic and not a
    second copy of it: the two windows are different questions — one is a
    setting about phones, this is a measurement about people — but
    "is this hour inside a window that crosses midnight" has one answer,
    and writing it twice is how the two stop agreeing.
    """
    start, end = night_window(
        rhythm_payload, dt.datetime.fromtimestamp(now, tz or dt.timezone.utc))
    return notify_router.in_quiet_hours(now, start, end, tz)


# ---------------------------------------------------------------------------
# What brAIn knows about an entity when an event arrives
# ---------------------------------------------------------------------------

class RegistryContext:
    """The handful of questions an adapter asks about an entity id.

    It is a small object rather than four arguments because the event bus
    refreshes it on a timer and hands the same one to every event in
    between — and because the questions are the questions, so a caller
    that only has some of the answers gets `False` for the rest rather
    than guessing. Everything it knows is either a list somebody set
    (`protected`) or a set somebody computed (`known`); the per-entity
    facts — a closure, a person, a safety class — are read off the event's
    own attributes, which is why they take one.
    """

    __slots__ = ("protected", "known", "built_at")

    def __init__(self, protected: list[str] | None = None,
                 known: set[str] | frozenset[str] | None = None,
                 built_at: float = 0.0):
        self.protected = [str(p).strip().lower()
                          for p in (protected or []) if str(p).strip()]
        self.known = frozenset(known or ())
        self.built_at = float(built_at or 0.0)

    def is_protected(self, entity_id: str) -> bool:
        """`automation_writer.is_protected`, never a second matcher.

        The option is parsed in one place and matched in one place because
        two readings of it are two answers to "may brAIn touch this", and
        the wrong one is the one that acts.
        """
        if not self.protected:
            return False
        import automation_writer  # noqa: PLC0415 — panel-local
        return automation_writer.is_protected(entity_id, self.protected)

    def is_known(self, entity_id: str) -> bool:
        """Whether brAIn holds a fact about this entity."""
        return str(entity_id or "") in self.known

    @staticmethod
    def is_closure(entity_id: str, attrs: dict | None = None) -> bool:
        """`closures.is_closure`, for its reason: a door this module filed
        as ordinary and `evening.left_open` filed as a closure is one house
        with two answers about the same front door."""
        import closures  # noqa: PLC0415 — panel-local
        return closures.is_closure(entity_id, attrs or {})

    @staticmethod
    def is_person(entity_id: str) -> bool:
        return domain_of(entity_id) in PERSON_DOMAINS

    @staticmethod
    def safety_class(attrs: dict | None = None) -> str:
        """The hot safety class this entity carries, or "".

        The class is read off the state's own attributes rather than off a
        registry, because that is where Home Assistant puts it and because
        an adapter that needed a registry could not run inside a socket
        pump.
        """
        klass = str((attrs or {}).get("device_class") or "").strip().lower()
        return klass if klass in HOT_SAFETY_CLASSES else ""


def domain_of(entity_id: str) -> str:
    return str(entity_id or "").split(".", 1)[0]


EMPTY_CONTEXT = RegistryContext()


# ---------------------------------------------------------------------------
# Building one
# ---------------------------------------------------------------------------

def evidence_row(entity: str, value, when: float) -> dict:
    """One observation, capped. Values are stringified here rather than at
    every call site: an evidence row goes into a prompt, and a float that
    renders as 21.300000000000001 is four tokens of nothing."""
    if isinstance(value, float):
        rendered = f"{value:g}"
    elif isinstance(value, bool):
        rendered = "true" if value else "false"
    else:
        rendered = str(value if value is not None else "")
    return {
        "entity": str(entity or "")[:MAX_EVIDENCE_ENTITY],
        "value": rendered[:MAX_EVIDENCE_VALUE],
        "when": float(when or 0.0),
    }


def make(kind: str, subject: str, *, now: float, source: str = "",
         text: str = "", evidence: list[dict] | None = None,
         salience: float = 0.0, hot: bool = False,
         repeats: int = 1) -> dict:
    """One signal, in the one shape. Every adapter ends here.

    A kind outside :data:`KINDS` is refused rather than filed as
    something: a reader switching on an unknown word would take whichever
    branch happened to be last, and a signal nobody can read is worse than
    a signal that was never made.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown signal kind: {kind!r}")
    rows = [r for r in (evidence or []) if isinstance(r, dict)][:MAX_EVIDENCE]
    return {
        "kind": kind,
        "subject": str(subject or "")[:MAX_SUBJECT],
        "salience": _clamp(salience),
        "evidence": rows,
        "seen_at": float(now),
        "source": str(source or "")[:MAX_SOURCE],
        "hot": bool(hot),
        "repeats": max(1, int(repeats)),
        "text": str(text or "")[:MAX_TEXT],
    }


# ---------------------------------------------------------------------------
# Adapters — one per door something already comes through
# ---------------------------------------------------------------------------

def _check_id(source: str) -> str:
    return source[len("check:"):] if source.startswith("check:") else ""


def _check_title(source: str) -> str:
    """The check's own name, off the catalog.

    A muted producer is named by its own title rather than by its group's
    (`Sensors frozen on one value`, never `Device check` three times over)
    and the same holds here, because this string is what a person reads in
    a batch. The import is lazy and its failure is an empty title: the
    checks package reaches for `snapshot`, which a dev checkout may not be
    able to import, and a signal is worth more without a name than not at
    all.
    """
    cid = _check_id(source)
    if not cid:
        return ""
    try:
        import checks  # noqa: PLC0415 — panel-local, and heavy
    except ImportError:
        return ""
    entry = checks.get_check(cid)
    return str((entry or {}).get("title") or "")


def from_finding(row: dict, now: float,
                 ctx: RegistryContext | None = None) -> dict | None:
    """A findings-store row as a signal, or None if there is nothing in it.

    Takes the shape `findings_store._shape` and `coerce` both produce, so
    a row read back off the store and a row a producer just built go the
    same way. Two facts are read from where they already live rather than
    from the row's words: the urgency is `notify_router.urgency_of`'s,
    which is keyed on the producer because a row's sentence is written by
    a model or an f-string and gets reworded; the check's title is the
    catalog's.

    It is deliberately NOT hot. A finding is a rule's opinion about one
    instant — which is precisely what the first look exists to grade — and
    a rule that could set the house looking immediately would be the old
    architecture with a new word for it. What makes a finding urgent is its
    severity and its producer's urgency, which are weights.
    """
    if not isinstance(row, dict):
        return None
    text = str(row.get("text") or "").strip()
    if not text:
        return None
    source = str(row.get("source") or "")
    entity = str(row.get("entity_id") or "").strip()
    subject = entity or _check_id(source) or source or text[:MAX_SUBJECT]
    severity = str(row.get("severity") or "").strip().lower()
    if severity not in SEVERITY_WEIGHT:
        severity = DEFAULT_SEVERITY
    ctx = ctx or EMPTY_CONTEXT
    seen_at = float(row.get("ts") or now)
    ev = []
    if entity:
        ev.append(evidence_row(entity, row.get("detail") or severity, seen_at))
    title = _check_title(source) or str(row.get("source_title") or "")
    # Every finding is a `check` signal, whoever filed it. The kind says
    # *a rule wrote a row about this*, which is as true of an insight run's
    # side channel as of `dev.frozen` — and the producer is already on
    # `source`, which is what a mute, a scorecard and the weights key on.
    return make(
        "check", subject, now=now, source=source or "finding",
        text=f"{title}: {text}" if title else text,
        evidence=ev,
        salience=score(
            "check", severity=severity,
            urgency=notify_router.urgency_of(row),
            protected=ctx.is_protected(entity) if entity else False,
            known=ctx.is_known(entity) if entity else False,
            age_s=max(0.0, now - seen_at)),
    )


def from_state_change(event: dict, ctx: RegistryContext, now: float,
                      rhythm_payload: dict | None = None,
                      tz: dt.tzinfo | None = None) -> dict | None:
    """Home Assistant's `state_changed` data as a signal, or None.

    **Most state changes are not signals, and returning None is the whole
    filter.** A house publishes tens of thousands of readings a day and a
    listener that turned each into a row would hand the first look a batch
    of sensors reporting numbers. What survives is what brAIn has a reason
    to care about: a protected entity, a person, a closure, a safety
    sensor, or something it already holds a fact about. Everything else is
    read by the checks pass on its own six hours, where the arithmetic is
    cheaper than attention.

    `event` is the event's `data`: `entity_id`, `old_state`, `new_state`
    and the event's `context`. A change with no new state is an entity
    being removed, which is a registry event wearing a state change's
    clothes and is not this module's business.
    """
    if not isinstance(event, dict):
        return None
    entity = str(event.get("entity_id") or "").strip()
    new_state = event.get("new_state")
    if not entity or not isinstance(new_state, dict):
        return None
    old_state = event.get("old_state") if isinstance(
        event.get("old_state"), dict) else {}
    value = str(new_state.get("state") or "").strip()
    was = str((old_state or {}).get("state") or "").strip()
    if value.lower() in EMPTY_STATES or value == was:
        return None

    attrs = new_state.get("attributes") if isinstance(
        new_state.get("attributes"), dict) else {}
    ctx = ctx or EMPTY_CONTEXT
    protected = ctx.is_protected(entity)
    person = ctx.is_person(entity)
    safety_class = ctx.safety_class(attrs)
    closure = ctx.is_closure(entity, attrs)
    known = ctx.is_known(entity)
    if not (protected or person or safety_class or closure or known):
        return None

    # A safety sensor is hot when it is *tripped*, never when it clears —
    # a leak detector going dry is good news, and good news at 3am is a
    # phone nobody thanks you for.
    tripped = bool(safety_class) and value.lower() in HOT_SAFETY_STATES
    odd = is_odd_hour(now, rhythm_payload, tz)
    # The closed hot set, and the two person cases are one case: a person
    # or their phone moving at an hour this house is not usually up.
    hot = tripped or protected or (person and odd)

    friendly = str(attrs.get("friendly_name") or entity)
    text = f"{friendly} {was or 'unknown'} → {value}" if was \
        else f"{friendly} → {value}"
    kind = "presence" if person else "state"
    return make(
        kind, entity, now=now, source="eventbus", text=text,
        evidence=[evidence_row(entity, value, now)],
        hot=hot,
        salience=score(
            kind,
            # A leak detector reading wet is the one state change that is
            # a `critical` `now` on its own, and saying so here is the
            # same claim `notify_router` makes about `climate.freeze`:
            # a weight, on a fact (the device class and the state), not a
            # verdict about what to do. Without it a battery three weeks
            # from flat — `critical` because a rule said so — outranks a
            # leak, which is the ordering this whole table exists to get
            # right.
            severity="critical" if tripped else "",
            urgency="now" if tripped else "",
            protected=protected, safety=bool(safety_class), known=known,
            # Anything that reached this line is an entity brAIn has a
            # reason to care about, and it happening when nobody is
            # usually up is more notable than the same thing at noon —
            # whichever of the five reasons let it through.
            odd_hour=odd, age_s=0.0),
    )


def from_trace(trace_row: dict, now: float) -> dict | None:
    """An automation trace that ended in an error.

    The shape is Home Assistant's saved-trace summary, which the checks
    snapshot already reads: an `item_id` (the automation's own id, which
    is what `automation_writer` stamps), a `timestamp` and an `error`.

    **A trace error on an automation brAIn wrote is hot.** Not because
    brAIn's automations matter more than anybody else's, but because it is
    the one failure brAIn is responsible for — something it wrote, that it
    was told worked, that has stopped — and the honest answer to that is
    to go and look now rather than to report it at six in the morning with
    everything else.
    """
    if not isinstance(trace_row, dict):
        return None
    error = str(trace_row.get("error") or "").strip()
    if not error:
        return None
    item = str(trace_row.get("item_id") or trace_row.get("id") or "").strip()
    if not item:
        return None
    when = _stamp(trace_row.get("timestamp"), now)
    ours = item.startswith(BRAIN_ID_PREFIX)
    return make(
        "trace_error", item, now=now, source="trace",
        text=f"automation {item} failed: {error}",
        evidence=[evidence_row(item, error, when)],
        hot=ours,
        salience=score("trace_error", severity="serious",
                       urgency="now" if ours else "today",
                       age_s=max(0.0, now - when)),
    )


def from_override(override: dict, now: float,
                  ctx: RegistryContext | None = None) -> dict | None:
    """A person putting back what an automation had just done.

    `actions.find_overrides`' row, unchanged — `{ts, entity_id, name,
    from_state, to_state, by, by_name, person, after_s}` — because that
    detector already carries the three floors that make an override mean
    something (the state has to differ, one move is undone once, an
    automation undoing an automation is a conflict and not this). Rebuilding
    any of that here would be a second answer to "did somebody disagree".
    """
    if not isinstance(override, dict):
        return None
    entity = str(override.get("entity_id") or "").strip()
    if not entity:
        return None
    ctx = ctx or EMPTY_CONTEXT
    when = float(override.get("ts") or now)
    rule = str(override.get("by_name") or override.get("by") or "an automation")
    text = (f"{override.get('name') or entity} put back to "
            f"{override.get('to_state') or '?'} after {rule} set it to "
            f"{override.get('from_state') or '?'}")
    return make(
        "override", entity, now=now, source="override",
        text=text,
        evidence=[evidence_row(entity, override.get("to_state"), when),
                  evidence_row(str(override.get("by") or rule),
                               override.get("from_state"), when)],
        salience=score("override",
                       protected=ctx.is_protected(entity),
                       known=ctx.is_known(entity),
                       age_s=max(0.0, now - when)),
    )


def from_presence(event: dict, now: float,
                  rhythm_payload: dict | None = None,
                  tz: dt.tzinfo | None = None) -> dict | None:
    """Somebody arrived or left.

    A `person` or `device_tracker` change, taken by the same door as any
    other state change and given its own adapter because the caller often
    already knows which it has. **A person-level event at an hour this
    house is not usually up is hot** — that is the plan's third case, and
    it is the one worth stating out loud: nothing here is being asked
    whether somebody should be up, only whether it is worth looking at
    the house now rather than in fifteen minutes.
    """
    if not isinstance(event, dict):
        return None
    entity = str(event.get("entity_id") or "").strip()
    if not entity or not RegistryContext.is_person(entity):
        return None
    new_state = event.get("new_state") if isinstance(
        event.get("new_state"), dict) else {}
    old_state = event.get("old_state") if isinstance(
        event.get("old_state"), dict) else {}
    value = str(new_state.get("state") or "").strip()
    was = str(old_state.get("state") or "").strip()
    if not value or value == was:
        return None
    attrs = new_state.get("attributes") if isinstance(
        new_state.get("attributes"), dict) else {}
    odd = is_odd_hour(now, rhythm_payload, tz)
    friendly = str(attrs.get("friendly_name") or entity)
    return make(
        "presence", entity, now=now, source="eventbus",
        text=f"{friendly} {was or 'unknown'} → {value}",
        evidence=[evidence_row(entity, value, now)],
        hot=odd,
        salience=score("presence", odd_hour=odd, age_s=0.0),
    )


def from_reply(request: dict, now: float) -> dict | None:
    """A person answered — a notification reply, or a request from HA.

    Every field is another process's, so every field is validated and
    capped the way `finding_requests.parse` validates the same hand-off.
    It is the highest base weight in the table and it is deliberately not
    hot: somebody typing an answer is not an emergency, and the first look
    is minutes away — what a reply must not do is sit behind a hundred
    sensors, which is what the weight is for.
    """
    if not isinstance(request, dict):
        return None
    action = str(request.get("action") or request.get("verb") or "").strip()
    note = str(request.get("note") or request.get("reply_text")
               or request.get("message") or "").strip()
    if not action and not note:
        return None
    subject = str(request.get("subject") or request.get("entity_id")
                  or request.get("ts") or action or "reply").strip()
    via = str(request.get("via") or "")[:32]
    text = f"{action}: {note}".strip(": ") if action else note
    return make(
        "reply", subject, now=now, source=f"reply:{via}" if via else "reply",
        text=text,
        evidence=[evidence_row(subject, action or note, now)],
        salience=score("reply", urgency="today", age_s=0.0),
    )


def from_time(label: str, now: float, *, text: str = "",
              salience_hint: str = "") -> dict:
    """A scheduled moment — the evening pass, the morning, a checks pass.

    The one adapter that cannot return None: a moment happened whether or
    not anything else did, and that is the point of it. It carries the
    lowest base weight in the table for the same reason, because a batch
    that is nothing but the clock is a batch the first look should read in
    one line and put down.
    """
    return make(
        "time", str(label or "moment"), now=now, source="schedule",
        text=text or f"scheduled: {label}",
        evidence=[],
        salience=score("time", urgency=salience_hint, age_s=0.0),
    )


def from_baseline(row: dict, now: float,
                  ctx: RegistryContext | None = None) -> dict | None:
    """A reading outside its own measured band.

    `baselines.deviation`'s answer, handed in: `{entity_id, value,
    deviation, source}` where `deviation` is in the entity's own spreads
    and `source` says whether the band came from this hour of the week or
    from the whole history. Both ride into the evidence, because "six
    spreads from its Tuesday-at-seven normal" and "six spreads from its
    normal" are different claims and only the reading knows which it is.
    """
    return _measured(row, "baseline", now, ctx)


def from_thermal(row: dict, now: float,
                 ctx: RegistryContext | None = None) -> dict | None:
    """A fall past a room's own `k`, or a freeze runway.

    `thermal`'s numbers, handed in. It is the highest-weighted measurement
    kind because the two things it says — a window is open on a cold
    night, a room reaches freezing in four hours — are both about the next
    few hours rather than about the building.
    """
    return _measured(row, "thermal", now, ctx)


def from_appliance(row: dict, now: float,
                   ctx: RegistryContext | None = None) -> dict | None:
    """A cycle ended and something is waiting to be emptied.

    `appliances`' measured answer. It is the lowest-weighted measurement
    kind on purpose: an emptied dishwasher at eight in the morning is the
    same dishwasher, which is the same judgement `notify_router` makes
    about the same producer.
    """
    return _measured(row, "appliance", now, ctx)


def _measured(row: dict, kind: str, now: float,
              ctx: RegistryContext | None) -> dict | None:
    """The three measurement stores share one adapter because they share
    one shape: an entity, a reading, a sentence, and a time. What differs
    is the weight, which is the kind, which is the argument."""
    if not isinstance(row, dict):
        return None
    entity = str(row.get("entity_id") or row.get("entity")
                 or row.get("area") or "").strip()
    text = str(row.get("text") or row.get("detail") or "").strip()
    if not entity and not text:
        return None
    ctx = ctx or EMPTY_CONTEXT
    when = float(row.get("ts") or row.get("when") or now)
    severity = str(row.get("severity") or "").strip().lower()
    if severity not in SEVERITY_WEIGHT:
        severity = DEFAULT_SEVERITY
    ev = []
    for key in ("value", "deviation", "source"):
        if row.get(key) is not None:
            ev.append(evidence_row(f"{entity}.{key}" if entity else key,
                                   row.get(key), when))
    return make(
        kind, entity or text[:MAX_SUBJECT], now=now,
        source=str(row.get("source") or kind),
        text=text or f"{entity} outside its measured normal",
        evidence=ev,
        salience=score(kind, severity=severity,
                       protected=ctx.is_protected(entity) if entity else False,
                       known=ctx.is_known(entity) if entity else False,
                       age_s=max(0.0, now - when)),
    )


def _stamp(value, now: float) -> float:
    """A trace's timestamp, which Core writes as an ISO string.

    A stamp that cannot be read is `now` rather than zero: zero makes a
    fresh trace look weeks old, which is the recency weight reading a
    parse failure as a fact about the house.
    """
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    text = str(value or "").strip()
    if not text:
        return now
    try:
        return dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return now


# ---------------------------------------------------------------------------
# A batch
# ---------------------------------------------------------------------------

# The same thing twice inside this long is the same thing. Five minutes is
# under the first-look interval by design: a batch is meant to arrive with
# its repeats already folded, and a window longer than the interval would
# fold a signal into the batch before it rather than into this one.
DEDUPE_WINDOW_S = 300.0


def dedupe(signals: list[dict], window_s: float = DEDUPE_WINDOW_S) -> list[dict]:
    """One signal per (kind, subject) inside the window, with a count.

    A door opened four times in a minute is one door, and a batch that
    said it four times would spend four lines of the first look's
    attention on one fact. What is kept is the **freshest** of each group
    — its evidence, its text, its salience — with `repeats` saying how
    many there were, because the newest reading is the one that is still
    true and the older ones are what makes it worth reading.

    Salience is recomputed off the repeat count rather than carried, or a
    thing that happened five times would score exactly as the once did.
    The recomputation is additive and bounded (`REPEAT_CAP`), so it can
    only ever move a signal a little way up a batch — which is the whole
    licence a count has.

    Order is preserved by first appearance, because `rank` is what sorts
    and a dedupe that also reordered would make the two impossible to
    reason about separately.
    """
    window = max(0.0, float(window_s))
    order: list[tuple[str, str]] = []
    groups: dict[tuple[str, str], list[dict]] = {}
    for sig in signals or []:
        if not isinstance(sig, dict) or sig.get("kind") not in KINDS:
            continue
        key = (str(sig.get("kind")), str(sig.get("subject") or ""))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(sig)

    out: list[dict] = []
    for key in order:
        rows = sorted(groups[key], key=lambda s: float(s.get("seen_at") or 0.0))
        # Walk oldest first and close a run when the gap opens: two bursts
        # an hour apart are two signals, which is what the window means.
        run: list[dict] = []
        for row in rows:
            if run and float(row.get("seen_at") or 0.0) - \
                    float(run[-1].get("seen_at") or 0.0) > window:
                out.append(_folded(run))
                run = []
            run.append(row)
        if run:
            out.append(_folded(run))
    rank_of = {key: i for i, key in enumerate(order)}
    out.sort(key=lambda s: rank_of[(s["kind"], s["subject"])])
    return out


def _folded(run: list[dict]) -> dict:
    """One run of the same (kind, subject) as a single signal."""
    newest = run[-1]
    repeats = sum(max(1, int(s.get("repeats") or 1)) for s in run)
    folded = dict(newest)
    folded["repeats"] = repeats
    # Hot survives any member of the run: a leak sensor that tripped and
    # cleared and tripped again is still a leak sensor that tripped, and
    # reading only the newest would let the clear cancel the trip.
    folded["hot"] = any(bool(s.get("hot")) for s in run)
    extra = W_REPEAT_EACH * min(repeats - 1, REPEAT_CAP) \
        - W_REPEAT_EACH * min(max(int(newest.get("repeats") or 1) - 1, 0),
                              REPEAT_CAP)
    folded["salience"] = _clamp(float(newest.get("salience") or 0.0) + extra)
    return folded


def rank(signals: list[dict]) -> list[dict]:
    """Highest salience first, newest first inside a tie.

    A stable, total order, because the first look reads a numbered list
    and a batch that shuffled between two passes over the same house
    would make every comparison of one pass against another meaningless.
    """
    return sorted(
        signals or [],
        key=lambda s: (-float(s.get("salience") or 0.0),
                       -float(s.get("seen_at") or 0.0),
                       str(s.get("kind") or ""), str(s.get("subject") or "")))


def batch(signals: list[dict], cap: int = MAX_BATCH) -> dict:
    """The top `cap`, and how many waited.

    `{"batch": [...], "waiting": n, "hot": n}`. The surplus **waits** — it
    is not surfaced unjudged and it is not dropped — which is `triage`'s
    rule for the same reason: the cap exists so one look fits in a prompt,
    and spending it on the busiest houses' overflow would be the cap
    deciding what a house is told. The next look is minutes away, the
    order is by salience so nothing loses the same lottery twice at
    random, and `waiting` is what makes a queue that stopped draining
    visible instead of quiet.
    """
    cap = max(1, int(cap))
    ranked = rank(signals)
    # **A hot signal is never left waiting.** Hot is what made the look
    # run now instead of on its timer, so a batch that could push the
    # reason for the look out past the cap would be the cap answering the
    # question the look was called to answer. Past the cap even in hot
    # rows there is nothing better than their own order, which is what
    # `rank` is; that a house can produce more than `MAX_BATCH` leaks in
    # five minutes is a house with one fault, not two dozen.
    hot = [s for s in ranked if s.get("hot")]
    cool = [s for s in ranked if not s.get("hot")]
    taken = (hot + cool)[:cap]
    return {
        "batch": taken,
        "waiting": max(0, len(ranked) - len(taken)),
        "hot": len(hot),
    }


# ---------------------------------------------------------------------------
# What the first look reads
# ---------------------------------------------------------------------------

# One line per signal, and a line is a line. A hundred and twenty
# characters is about what fits on a terminal row and about what a model
# reads as one item; past it a row starts carrying a paragraph, which is
# how a batch of twenty-four becomes a prompt nobody costed.
ROW_CHARS = 120
# How many evidence values ride on the row before the rest are left to the
# investigation that asks for them. Two, because the useful pair is nearly
# always "what it reads now" and "what it read before".
ROW_EVIDENCE = 2


def prompt_rows(signals: list[dict], now: float | None = None, *,
                numbered: bool = True) -> list[str]:
    """A batch as compact lines, one per signal.

    **No JSON, and no whole states.** The first look is the cheapest tier
    and it is run every few minutes; a row that pasted an entity's
    attributes would put the day's token budget into the one place it buys
    nothing, because what is being asked is *does this deserve a look*,
    which is answerable from a sentence.

    `now` is optional and only decides the age each row reports; without
    it the ages are left off rather than computed against the wall clock,
    which is this module's rule about clocks.

    **`numbered=False` is for a caller that numbers them itself.** A
    signal is named back to a model by its POSITION and never by its
    subject — `triage.frame`'s rule, because a model retyping an entity id
    can name the wrong entity and a number cannot be nearly right — so a
    prompt builder that lays the rows out in its own list is doing the
    right thing, and two numbers on one row (`1. 1. [check] …`) is the
    shape where a reply that says "3" means two different signals
    depending on which one it counted. The default numbers them, because
    this function's own output has to be a complete rendering for a
    caller that just pastes it.
    """
    out: list[str] = []
    for i, sig in enumerate(signals or [], 1):
        if not isinstance(sig, dict):
            continue
        head = (f"{i}. " if numbered else "") + (
            f"[{sig.get('kind')}] {sig.get('subject') or '?'}"
            f" s={float(sig.get('salience') or 0.0):.2f}")
        if sig.get("hot"):
            head += " HOT"
        repeats = int(sig.get("repeats") or 1)
        if repeats > 1:
            head += f" x{repeats}"
        if now is not None:
            head += f" {_ago(now - float(sig.get('seen_at') or now))}"
        row = f"{head} — {str(sig.get('text') or '').strip()}"
        for ev in (sig.get("evidence") or [])[:ROW_EVIDENCE]:
            if not isinstance(ev, dict):
                continue
            piece = f" ({ev.get('entity')}={ev.get('value')})"
            if len(row) + len(piece) > ROW_CHARS:
                break
            row += piece
        out.append(row[:ROW_CHARS])
    return out


def _ago(seconds: float) -> str:
    """How long ago, in the fewest characters that still say it."""
    seconds = max(0.0, float(seconds))
    if seconds < 90:
        return f"{int(seconds)}s"
    if seconds < 5400:
        return f"{int(seconds // 60)}m"
    if seconds < 172800:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


__all__ = [
    "BRAIN_ID_PREFIX", "DEDUPE_WINDOW_S", "EMPTY_CONTEXT",
    "HOT_SAFETY_CLASSES", "HOT_SAFETY_STATES", "KINDS", "KIND_BASE",
    "MAX_BATCH", "MAX_EVIDENCE", "MAX_TEXT", "NIGHT_END_H", "NIGHT_START_H",
    "PERSON_DOMAINS", "REPEAT_CAP", "ROW_CHARS", "RegistryContext",
    "SEVERITY_WEIGHT", "SIGNAL_KEYS", "URGENCY_WEIGHT", "W_KNOWN",
    "W_ODD_HOUR", "W_PROTECTED", "W_RECENCY", "W_REPEAT_EACH", "W_SAFETY",
    "batch", "dedupe", "domain_of", "evidence_row", "from_appliance",
    "from_baseline", "from_finding", "from_override", "from_presence",
    "from_reply", "from_state_change", "from_thermal", "from_time",
    "from_trace", "is_odd_hour", "make", "night_window", "prompt_rows",
    "rank", "score",
]
