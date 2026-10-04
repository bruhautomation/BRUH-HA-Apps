"""A correction has a scope and a lifetime, and the press only had neither.

Wrong on a check's row writes one rule (`server._record_exception`): THIS
check stands down for THIS entity, for ever. That is right for the
commonest correction — "that sensor is a contact on a cupboard nobody
opens" — and wrong for the two shapes people say just as often:

* **narrower in time.** *"It's always like that in winter"* is not "never
  tell me again"; it is "not until spring". A permanent rule written off
  that sentence is a stuck sensor in July that nothing will ever report.
* **wider in space.** *"None of the plugs in the garage matter"* is a
  statement about a room, and answering it one row at a time is the loop
  the Wrong button exists to end.

So the reason a person typed gets a second, cheap look (`correct` job: a
tool-less run with a closed schema) that answers two questions — which of
four SCOPES the sentence means, and until when — and this module turns
that answer into rules the checks read through `House.should_report`.

Four rules, each a guardrail the tests drive.

**The model never names what the rule is about.** The entity, the check
and the room come off the finding that was pressed — the surface stamps
them — and the reply only picks a scope out of :data:`SCOPES` and a
lifetime out of :data:`LIFETIMES`. A model that could name an entity
could stand down a check on one nobody was talking about.

**A scope wider than one entity is OFFERED, never written.** "Every plug
in the garage" and "this rule everywhere" are questions filed as a case
(:func:`offer_row`) the person answers with Yes or No; only the Yes writes
the rule (:func:`accept_offer`). One entity — this check on it, or any
check on it — is the press's own reach and is applied directly, with the
sentence that says so (:func:`confirmation`).

**No scope covers a safety-class or protected entity.** A smoke, gas, CO
or leak sensor, a lock, an alarm panel, an id on the protected list and
the freeze check are clamped to the press's own rule — and refused again
at READ time (`House._never_covered`, fed by :func:`scope_map`'s
``never``), because a scope written in March cannot know what was fitted
in May.

**Every rule this writes carries the report's finding key**, so the toast's
Undo (`facts_store.forget_exceptions`) and "Let brAIn raise it again"
take back what this pass added as well as what the press wrote — and a
pass that finishes after an Undo writes nothing, because the press's own
rule is gone and :func:`apply_plan` checks for it first.

Stdlib plus `facts_store` and `atomic_write`. Never raises out of a
reading function: a correction that could not be read stands nothing
down, the direction in which being wrong shows a card.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import threading
import time
from pathlib import Path

import atomic_write
import facts_store

log = logging.getLogger("brain.corrections")

# Narrowest first. `House.withheld_by` reads them in this order.
SCOPES = ("entity_check", "entity", "check_area", "check")
# Offered as a question, never written straight from a reply.
WIDE_SCOPES = frozenset({"check_area", "check"})
LIFETIMES = ("permanent", "date", "month", "season")
SEASONS = ("spring", "summer", "autumn", "winter")
# Meteorological seasons, northern; a southern house reads them swapped.
_SEASON_MONTHS = {"spring": (3, 4, 5), "summer": (6, 7, 8),
                  "autumn": (9, 10, 11), "winter": (12, 1, 2)}
_SOUTH = {"spring": "autumn", "summer": "winter", "autumn": "spring",
          "winter": "summer"}
# A resume date further out than this is a person meaning "for good" in
# a long-winded way, and is read as permanent rather than as a date
# nobody will remember setting.
MAX_DAYS = 2 * 366

# What no wide scope may ever cover. Domains and device classes are the
# ones `signals` and `checks.automations` already treat as safety; the
# freeze check is `signals.SAFETY_CHECKS`. The tests hold these equal to
# their sources rather than importing them here, because this module is
# read by the checks snapshot and must stay a leaf.
NEVER_DOMAINS = frozenset({"lock", "alarm_control_panel"})
NEVER_CLASSES = frozenset({"smoke", "gas", "carbon_monoxide", "moisture",
                           "safety"})
NEVER_CHECKS = frozenset({"climate.freeze"})

# Who files an offer, so the ending that answers it can tell it apart from
# every other question on the feed (`server._end_finding`).
SOURCE = "correction"
SOURCE_TITLE = "A correction you gave"

OFFERS_FILE = Path(os.environ.get("BRAIN_CORRECTION_OFFERS_FILE",
                                  "/data/correction-offers.json"))
OFFERS_MAX = 60
OFFER_TTL_S = 60 * 86400
MAX_REASON = 300

_LOCK = threading.Lock()
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTHS = ("January", "February", "March", "April", "May", "June", "July",
           "August", "September", "October", "November", "December")


# ---------------------------------------------------------------------------
# The second look
# ---------------------------------------------------------------------------

SYSTEM = """You read one correction a homeowner gave about a report from \
their smart home, and you say two things about it: how WIDE it is meant to \
be and how LONG it should last. You do not decide anything else, you do not \
name entities, and you do not write the rule — the report already says what \
it was about.

SCOPE — pick exactly one:
- "entity_check": only this rule, only this device. The default, and the \
right answer whenever the sentence is about this one thing.
- "entity": every rule about this device ("ignore that sensor", "it's a \
dummy, don't tell me anything about it").
- "check_area": this rule for every device in the same room ("none of the \
garage plugs matter").
- "check": this rule for every device in the house ("I never care about \
this").
Never pick a wider scope than the sentence plainly says. When unsure, \
"entity_check".

LIFETIME — pick exactly one:
- "permanent": no end is mentioned or implied.
- "date": a specific day it should start reporting again; give it as \
until_date YYYY-MM-DD (the day reporting RESUMES).
- "month": "until October", "till next spring month" — until_month 1-12, \
the month reporting resumes.
- "season": "it's like that every winter", "only in summer" — season is \
the season the condition belongs to; reporting resumes when it ends.

reason: the standing truth the correction implies, in one plain sentence \
about the house (not about the report), or "" when there is none.

Answer only with the JSON object."""

SCHEMA = {
    "type": "object",
    "properties": {
        "scope": {"type": "string", "enum": list(SCOPES)},
        "lifetime": {"type": "string", "enum": list(LIFETIMES)},
        "until_date": {"type": "string"},
        "until_month": {"type": "integer", "minimum": 0, "maximum": 12},
        "season": {"type": "string", "enum": ["", *SEASONS]},
        "reason": {"type": "string"},
    },
    "required": ["scope", "lifetime"],
    "additionalProperties": False,
}


def prompt(finding: dict, note: str, *, entity_name: str = "",
           area_name: str = "", check_title: str = "",
           today: dt.date | None = None) -> str:
    """The run's whole input: the report, what it was about, the words."""
    today = today or dt.date.today()
    lines = [
        f"Today is {today.isoformat()}.",
        f"The report: “{str(finding.get('text') or '')[:240]}”",
    ]
    if check_title:
        lines.append(f"The rule that raised it: {check_title}")
    if entity_name:
        lines.append(f"The device it is about: {entity_name}")
    if area_name:
        lines.append(f"The room that device is in: {area_name}")
    lines.append(f"The homeowner said it is not a problem, because: "
                 f"“{str(note or '')[:MAX_REASON]}”")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Lifetime arithmetic
# ---------------------------------------------------------------------------

def _first_of(year: int, month: int) -> dt.date:
    return dt.date(year, month, 1)


def _next_first(today: dt.date, month: int) -> dt.date:
    """The next first-of-`month` strictly after today."""
    year = today.year
    candidate = _first_of(year, month)
    if candidate <= today:
        candidate = _first_of(year + 1, month)
    return candidate


def season_resume(season: str, today: dt.date, *,
                  southern: bool = False) -> dt.date | None:
    """The first day after the season ends, next time it ends.

    "It's like that every winter" is said in winter or as it comes on, so
    the answer is the next first-of-the-month after the season's last
    month: said in October or in January it is the first of March. A
    southern house names its seasons the other way round, so its "winter"
    is the months a northern one calls summer.
    """
    season = str(season or "").lower()
    if season == "fall":
        season = "autumn"
    if season not in SEASONS:
        return None
    months = _SEASON_MONTHS[_SOUTH[season] if southern else season]
    return _next_first(today, months[-1] % 12 + 1)


def resume_date(reply: dict, today: dt.date, *,
                southern: bool = False) -> dt.date | None:
    """When reporting starts again, or None for a permanent correction.

    Every answer the model can give is checked here: a date in the past,
    a month out of range or a season nobody has is no lifetime at all,
    and a resume date past :data:`MAX_DAYS` is read as permanent.
    """
    kind = str(reply.get("lifetime") or "permanent")
    when: dt.date | None = None
    if kind == "date":
        raw = str(reply.get("until_date") or "").strip()
        if _DATE_RE.match(raw):
            try:
                when = dt.date.fromisoformat(raw)
            except ValueError:
                when = None
    elif kind == "month":
        month = reply.get("until_month")
        if isinstance(month, int) and not isinstance(month, bool) \
                and 1 <= month <= 12:
            when = _next_first(today, month)
    elif kind == "season":
        when = season_resume(str(reply.get("season") or ""), today,
                             southern=southern)
    if when is None or when <= today:
        return None
    if (when - today).days > MAX_DAYS:
        return None
    return when


def expires_for(resume: dt.date | None) -> str:
    """`facts_store`'s `expires` for a resume date: the day before it.

    A fact is live through its `expires` day (`facts_store._expired` is
    `stamp < today`), so the rule stops standing the check down on the
    morning reporting is meant to resume.
    """
    if resume is None:
        return ""
    return (resume - dt.timedelta(days=1)).isoformat()


def until_words(resume: dt.date | None) -> str:
    """'until October', 'until 14 March', or '' for permanent."""
    if resume is None:
        return ""
    if resume.day == 1:
        return f"until {_MONTHS[resume.month - 1]}"
    return f"until {resume.day} {_MONTHS[resume.month - 1]}"


def house_southern(config_dir: str = "/config") -> bool:
    """Whether the house is south of the equator, read off Core's config.

    Best effort and False on anything unreadable: a season is the one
    lifetime that depends on it, and the northern reading is the one most
    houses need.
    """
    try:
        with open(os.path.join(config_dir, ".storage", "core.config"),
                  encoding="utf-8") as fh:
            data = json.load(fh).get("data") or {}
        return float(data.get("latitude") or 0.0) < 0.0
    except (OSError, ValueError, TypeError, AttributeError):
        return False


# ---------------------------------------------------------------------------
# The plan: a reply, checked
# ---------------------------------------------------------------------------

def _domain(entity_id: str) -> str:
    return entity_id.split(".", 1)[0] if "." in entity_id else ""


def never_covered(entity_id: str, check_id: str, *, device_class: str = "",
                  protected=()) -> bool:
    """Is this a pair no scope wider than the press may reach?

    The write-time half of `House._never_covered`; the read-time half is
    the one that cannot be walked round, this one stops a question being
    asked that could only be refused.
    """
    if check_id in NEVER_CHECKS:
        return True
    if _domain(entity_id) in NEVER_DOMAINS:
        return True
    if device_class and device_class in NEVER_CLASSES:
        return True
    target = entity_id.lower()
    return any(p in (target, f"{_domain(target)}.*", "*")
               for p in (str(x).lower() for x in protected or ()))


def check_of(finding: dict) -> str:
    source = str(finding.get("source") or "")
    return source[len("check:"):] if source.startswith("check:") else ""


def plan(reply: dict | None, finding: dict, *, today: dt.date | None = None,
         area_id: str = "", device_class: str = "", protected=(),
         southern: bool = False) -> dict:
    """What a reply may do to this finding's rule. Never raises.

    ``{"scope", "resume", "expires", "until", "reason", "check",
    "entity_id", "area_id", "offer", "clamped"}`` — `offer` is True for a
    scope only a Yes may write, and `clamped` names why a wider scope was
    brought back to the press's own (a safety device, a non-check row, a
    room nobody knows).
    """
    today = today or dt.date.today()
    reply = reply if isinstance(reply, dict) else {}
    check_id = check_of(finding)
    entity_id = str(finding.get("entity_id") or "")
    scope = str(reply.get("scope") or "entity_check")
    clamped = ""
    if scope not in SCOPES:
        scope, clamped = "entity_check", "the reply named no scope brAIn knows"
    if scope != "entity_check" and not (check_id and entity_id):
        scope, clamped = "entity_check", "only a rule's report can be widened"
    if scope != "entity_check" and never_covered(
            entity_id, check_id, device_class=device_class,
            protected=protected):
        scope, clamped = ("entity_check",
                          "a safety device or a protected one is never "
                          "covered by a wider correction")
    if scope == "check_area" and not area_id:
        scope, clamped = "entity_check", "brAIn does not know which room it is in"
    resume = resume_date(reply, today, southern=southern)
    reason = " ".join(str(reply.get("reason") or "").split())[:MAX_REASON]
    return {
        "scope": scope,
        "resume": resume.isoformat() if resume else "",
        "expires": expires_for(resume),
        "until": until_words(resume),
        "reason": reason,
        "check": check_id,
        "entity_id": entity_id,
        "area_id": area_id if scope == "check_area" else "",
        "offer": scope in WIDE_SCOPES,
        "clamped": clamped,
    }


# ---------------------------------------------------------------------------
# Writing it
# ---------------------------------------------------------------------------

def _rows_by_id(ids) -> list[dict]:
    wanted = {str(i) for i in ids or () if i}
    if not wanted:
        return []
    return [r for r in facts_store.export_rows() if str(r.get("id")) in wanted]


def apply_plan(the_plan: dict, finding: dict, base_ids, note: str, *,
               finding_key: str, about: str = "") -> dict:
    """Write what the plan may write. Returns ``{"ids", "written", "why"}``.

    Only the press's reach: a lifetime on the rules the press already
    wrote, and the whole-entity rule beside them. A wide scope writes
    nothing here — :func:`offer_row` files the question. A press whose
    own rule is gone (the toast's Undo landed first) writes nothing at
    all, because the person has taken the correction back.
    """
    rows = _rows_by_id(base_ids)
    if not rows:
        return {"ids": [], "written": False,
                "why": "the correction was taken back before it was scoped"}
    ids: list[str] = []
    expires = the_plan.get("expires") or ""
    if expires:
        for row in rows:
            got, _ = facts_store.add(
                str(row.get("text") or note), subject=str(row.get("subject")),
                extra_subjects=[s for s in row.get("subjects") or ()
                                if s != row.get("subject")],
                source=str(row.get("source") or "correction"),
                predicate=str(row.get("predicate") or ""),
                expires=expires, run_id=str(row.get("run_id") or ""),
                about=str(row.get("about") or about),
                finding_key=finding_key)
            if got:
                ids.append(got["id"])
    if the_plan.get("scope") == "entity" and the_plan.get("entity_id"):
        got, _ = facts_store.add(
            note.strip()[:MAX_REASON] or the_plan.get("reason")
            or "Not a problem here", subject=the_plan["entity_id"],
            source="correction",
            predicate=facts_store.EXCEPTION_PREFIX + "*",
            expires=expires, confidence=0.95,
            about=about or str(finding.get("text") or ""),
            finding_key=finding_key)
        if got:
            ids.append(got["id"])
    return {"ids": ids, "written": bool(ids), "why": ""}


def _friendly_scope(the_plan: dict, *, entity_name: str, area_name: str,
                    check_title: str) -> str:
    rule = f"“{check_title}”" if check_title else "that"
    scope = the_plan.get("scope")
    if scope == "entity":
        return f"anything about {entity_name or 'it'}"
    if scope == "check_area":
        return f"{rule} for anything in the {area_name or 'room'}"
    if scope == "check":
        return f"{rule} for anything in the house"
    return f"{rule} for {entity_name}" if entity_name else "it"


def confirmation(the_plan: dict, *, entity_name: str = "",
                 area_name: str = "", check_title: str = "") -> str:
    """The one sentence a person is told, built by code and never a model.

    "Got it — I'll stop flagging it until October." A wide scope is a
    question rather than a promise, so its sentence asks.
    """
    until = the_plan.get("until") or ""
    what = _friendly_scope(the_plan, entity_name=entity_name,
                           area_name=area_name, check_title=check_title)
    if the_plan.get("offer"):
        return (f"Got it — I'll stop flagging it for "
                f"{entity_name or 'this one'}"
                + (f" {until}" if until else "")
                + f". Want me to stop flagging {what} too? It's on your "
                "Findings list to answer.")
    if the_plan.get("scope") == "entity":
        return (f"Got it — I'll stop flagging {what}"
                + (f" {until}." if until else "."))
    if until:
        return f"Got it — I'll stop flagging it {until}."
    return "Got it — I won't flag that again."


# ---------------------------------------------------------------------------
# A wide scope is a question
# ---------------------------------------------------------------------------

def _offer_key(text: str) -> str:
    return hashlib.sha256(
        facts_store.normalize(text).encode("utf-8", "replace")).hexdigest()[:16]


def offer_row(the_plan: dict, note: str, *, entity_name: str = "",
              area_name: str = "", check_title: str = "",
              finding_key: str = "", about: str = "",
              now: float | None = None) -> dict | None:
    """The case that asks, and the offer it carries. None when not wide.

    The case goes through `findings_store.add_case` (the caller files it)
    as a `question` with `source` :data:`SOURCE`, so the feed renders Yes
    and No and the settled ledger stops it being asked twice; the offer
    itself — what Yes writes — is kept here, keyed by the case's text,
    because a findings row is not a place to keep a rule half-written.
    """
    if not the_plan.get("offer"):
        return None
    now = time.time() if now is None else float(now)
    check_id = the_plan.get("check") or ""
    until = the_plan.get("until") or ""
    what = _friendly_scope(the_plan, entity_name=entity_name,
                           area_name=area_name, check_title=check_title)
    text = f"Stop flagging {what}?"
    claim = (f"You said {entity_name or 'one of these'} is not a problem; "
             f"should the same go for {what.split(' for ', 1)[-1]}"
             + (f" {until}" if until else "") + "?")
    detail = (f"Your words: “{note.strip()[:MAX_REASON]}”. "
              "brAIn only stood the rule down for the one device you were "
              "looking at; Yes widens it, No leaves it there.")
    hint = (the_plan.get("reason") or
            f"The homeowner says {what.split(' for ', 1)[-1]} is not a "
            f"problem for {check_title or 'that rule'}")
    offer = {
        "key": _offer_key(text),
        "scope": the_plan.get("scope"),
        "check": check_id,
        "area_id": the_plan.get("area_id") or "",
        "expires": the_plan.get("expires") or "",
        "until": until,
        "text": note.strip()[:MAX_REASON] or hint,
        "about": about,
        "finding_key": finding_key,
        "created": int(now),
    }
    _save_offer(offer, now)
    return {
        "text": text,
        "claim": claim[:240],
        "detail": detail,
        "kind": "question",
        "severity": "info",
        "stakes": "low",
        "source": SOURCE,
        "source_title": SOURCE_TITLE,
        "fixable": False,
        "memory_hint": hint[:240],
        "entity_id": the_plan.get("entity_id") or "",
    }


def _load_offers() -> list[dict]:
    try:
        with open(OFFERS_FILE, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    rows = data.get("offers") if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def _write_offers(rows: list[dict]) -> None:
    if not OFFERS_FILE.parent.is_dir():
        return
    atomic_write.write_json(OFFERS_FILE, {"offers": rows[-OFFERS_MAX:]})


def _save_offer(offer: dict, now: float) -> None:
    with _LOCK:
        rows = [r for r in _load_offers()
                if r.get("key") != offer["key"]
                and now - float(r.get("created") or 0) < OFFER_TTL_S]
        rows.append(offer)
        try:
            _write_offers(rows)
        except OSError as exc:
            log.warning("could not keep a correction offer: %s", exc)


def is_offer(finding: dict) -> bool:
    return str(finding.get("source") or "") == SOURCE


def find_offer(case_text: str, now: float | None = None) -> dict | None:
    now = time.time() if now is None else float(now)
    key = _offer_key(case_text)
    for row in _load_offers():
        if row.get("key") == key and \
                now - float(row.get("created") or 0) < OFFER_TTL_S:
            return dict(row)
    return None


def accept_offer(case_text: str, *, protected=(),
                 now: float | None = None) -> dict:
    """Yes to a wide correction: write the rule it offered.

    ``{"ids", "why"}``. An offer that has lapsed or names a never-covered
    rule writes nothing and says so. The rule carries the ORIGINAL
    report's finding key, so "Let brAIn raise it again" on that report
    takes the wide rule back with the narrow one.
    """
    offer = find_offer(case_text, now)
    if offer is None:
        return {"ids": [], "why": "that offer has lapsed — mark the next "
                                  "report Not a problem to ask again"}
    check_id = str(offer.get("check") or "")
    if not check_id or check_id in NEVER_CHECKS:
        return {"ids": [], "why": "that rule is never stood down widely"}
    scope = offer.get("scope")
    if scope == "check_area" and offer.get("area_id"):
        subject = f"area:{offer['area_id']}"
    elif scope == "check":
        subject = f"check:{check_id}"
    else:
        return {"ids": [], "why": "that offer is not one brAIn can widen"}
    got, _ = facts_store.add(
        str(offer.get("text") or "Not a problem here"), subject=subject,
        source="correction", predicate=facts_store.EXCEPTION_PREFIX + check_id,
        expires=str(offer.get("expires") or ""), confidence=0.95,
        about=str(offer.get("about") or ""),
        finding_key=str(offer.get("finding_key") or ""))
    if not got:
        return {"ids": [], "why": "the facts store could not take it"}
    return {"ids": [got["id"]], "why": ""}


def withdraw(finding_key: str) -> list[str]:
    """Drop every offer made off this report. Returns the case texts.

    The toast's Undo on the press that made them: a question about
    widening a correction the person has taken back is a question about
    nothing.
    """
    key = str(finding_key or "")
    if not key:
        return []
    with _LOCK:
        rows = _load_offers()
        gone = [r for r in rows if r.get("finding_key") == key]
        if not gone:
            return []
        try:
            _write_offers([r for r in rows if r.get("finding_key") != key])
        except OSError as exc:
            log.warning("could not withdraw a correction offer: %s", exc)
    return [str(r.get("key")) for r in gone]


def offer_key_for(case_text: str) -> str:
    return _offer_key(case_text)


# ---------------------------------------------------------------------------
# What the checks read
# ---------------------------------------------------------------------------

def _resume_of(expires: str) -> str:
    if not expires:
        return ""
    try:
        return (dt.date.fromisoformat(expires)
                + dt.timedelta(days=1)).isoformat()
    except ValueError:
        return ""


def scope_map(now: float | None = None, *, protected=None) -> dict:
    """Every live correction, by scope, for `House.should_report`.

    ``{"entity": {eid: {check|*: rule}}, "area": {area_id: {check: rule}},
    "check": {check: rule}, "never": {checks, domains, classes,
    protected}}`` where a rule is ``{"text", "until", "id"}``. The entity
    table holds exactly what `facts_store.exception_map` holds (same rows,
    same expiry), so a snapshot built with this answers every legacy rule
    the way it always did. Raises on an unreadable store — the collector
    leaves the key out then, and `House` falls back to `snap["facts"]`.
    """
    now = time.time() if now is None else float(now)
    if protected is None:
        raw = os.environ.get("BRAIN_PROTECTED_ENTITIES", "").split(",")
        protected = [p.strip().lower() for p in raw if p.strip()]
    table = {"entity": {}, "area": {}, "check": {},
             "never": {"checks": sorted(NEVER_CHECKS),
                       "domains": sorted(NEVER_DOMAINS),
                       "classes": sorted(NEVER_CLASSES),
                       "protected": list(protected)}}
    for row in facts_store.export_rows():
        predicate = str(row.get("predicate") or "")
        if not predicate.startswith(facts_store.EXCEPTION_PREFIX):
            continue
        if facts_store._expired(row, now):  # noqa: SLF001 — the store's own rule
            continue
        check_id = predicate[len(facts_store.EXCEPTION_PREFIX):].strip()
        if not check_id:
            continue
        rule = {"text": str(row.get("text") or "")[:MAX_REASON],
                "until": _resume_of(str(row.get("expires") or "")),
                "id": str(row.get("id") or "")}
        subjects = row.get("subjects")
        if not isinstance(subjects, list) or not subjects:
            subjects = [row.get("subject") or ""]
        for subject in subjects:
            subject = str(subject or "")
            kind = facts_store.subject_kind(subject)
            if kind == "entity" and subject != "house":
                table["entity"].setdefault(subject, {})[check_id] = rule
            elif kind == "area" and check_id != "*":
                area = subject.split(":", 1)[1]
                table["area"].setdefault(area, {})[check_id] = rule
            elif kind == "check" and check_id != "*" \
                    and subject.split(":", 1)[1] == check_id:
                table["check"][check_id] = rule
    return table


def summary(now: float | None = None) -> dict:
    """What `/api/diagnostics` carries: how many of each scope are live."""
    try:
        table = scope_map(now)
    except Exception as exc:  # noqa: BLE001 — diagnostics never fail
        return {"readable": False, "error": str(exc)[:200]}
    return {"readable": True,
            "entity": sum(len(v) for v in table["entity"].values()),
            "area": sum(len(v) for v in table["area"].values()),
            "check": len(table["check"]),
            "offers": len(_load_offers())}


__all__ = ["LIFETIMES", "NEVER_CHECKS", "NEVER_CLASSES", "NEVER_DOMAINS",
           "SCHEMA", "SCOPES", "SEASONS", "SOURCE", "SYSTEM", "WIDE_SCOPES",
           "accept_offer", "apply_plan", "check_of", "confirmation",
           "expires_for", "find_offer", "house_southern", "is_offer",
           "never_covered", "offer_key_for", "offer_row", "plan", "prompt",
           "resume_date", "scope_map", "season_resume", "summary",
           "until_words", "withdraw"]
