"""`brain doctor --rehearse` — planted defects, on the house this actually is.

Every house check has a fixture test: `tests/test_house_checks.py` asserts
each one silent on a clean house before asserting it finds the planted row.
What that cannot see is **this install** — its Home Assistant version, its
integrations, its data shapes — and reading the CLAUDE.md history, that is
where every late bug in this add-on has lived. A rule that is right against
a hand-built dict and wrong against a real registry passes the suite for
its whole life.

So this plants a small set of defects under a `brain_test_` prefix, runs
the checks and the analyst against them, scores both, and takes everything
back out. What it produces is a number: *on this house, this Home
Assistant version, this model, the analyst found 3 of 4 planted defects
and reported 1 thing that was not there.* That number is the point — it is
what makes a prompt change measurable somewhere other than the developer's
own home.

Seven rules, and most of them are refusals.

**Consent is a named step, and it is a 428.** A call without
``{"consent": true}`` is answered with the exact list of what would be
created — the ids, and what each one is for — and **nothing is created
before the answer comes back**. Writing automations into somebody's config
is a step some people will not want, so the offer has to be legible before
it is taken.

**Everything goes in through paths brAIn already owns.** Automations
through `automation_writer`'s write-reload-verify, which means the
rehearsal is also a real round trip of the writer and of the splice that
removes one; the helper through the WebSocket API the checks snapshot
already speaks. A rehearsal that used a private back door would be
rehearsing the back door.

**The checks are run with `checks.run_all`, never `server.run_checks`.**
The second one files to the store, notifies, and clears — so it would ring
somebody's phone about a defect brAIn planted, and a planted row could
clear a real one. This reads the rows and files nothing.

**A check whose floor is measured in days is named as not rehearsable
rather than counted as missed.** `auto.forgotten_off` needs thirty days
switched off, `dev.frozen` a week of statistics, `auto.condition_never_passes`
three stored traces of runs that all stopped at the same condition. A
rehearsal that planted for those and scored them would report a working
check as broken, every single time — which is worse than not testing it.

**The healthy planted row is part of the score.** The helper is planted
expecting *nothing* to fire on it; a check that reports it is a false
positive, and knowing about one is as valuable as knowing a defect was
found.

**Removal runs in a `finally`, and is verified against a fresh snapshot.**
A rehearsal that fails halfway still cleans up, and a cleanup that fails is
the loudest line in the report — because the thing left behind is in
somebody's `automations.yaml`.

**And the plain `brain doctor` is what catches the one that did not clean
up.** It warns on any `brain_test_*` automation, entity or helper and
names the command that removes it. That is the design page's own
recommendation, and it is what makes shipping this at all defensible.

The orchestration takes :class:`Hooks` for the same reason `doctor.py`
does: writing an automation and waiting for Core to run it is the panel's
`_apply_accepted`, and a second implementation of it here would be the
thing worth catching rather than the thing catching it.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import atomic_write
import doctor
import engine
import journal
import scoring

PREFIX = doctor.PREFIX
SOURCE = doctor.SOURCE

REHEARSAL_FILE = Path(os.environ.get("BRAIN_REHEARSAL_FILE",
                                     "/data/doctor-rehearsal.json"))

# The analyst gets one run and one card's worth of budget. It is the same
# category the scheduled automations card uses, so what is being measured
# is the prompt people actually get.
ANALYST_CATEGORY = "automations"
ANALYST_TIMEOUT = 480
ANALYST_MAX_TURNS = 12

# The helper. An `input_number` because it is the cheapest numeric entity
# in Home Assistant, and because a *numeric* one is what the baseline and
# frozen-sensor checks would read if they could see a week of it.
HELPER_ID = f"input_number.{PREFIX}reading"
HELPER_NAME = "brAIn test reading"
HELPER_VALUE = 21.5


def _automation(slug: str, config: dict) -> dict:
    """One planted automation, in the shape `automation_writer.apply` takes.

    The id carries the `brain_` prefix `entry_for` requires of a config
    that names its own, so the entry in `automations.yaml` says what it is
    to anybody who opens the file — which matters more here than anywhere,
    because this is the one thing brAIn writes that it also promises to
    delete.
    """
    entry_id = f"{PREFIX}{slug}"
    return {"ts": 0, "title": entry_id,
            "config": {"id": entry_id, "mode": "single", **config}}


# What gets planted, what it is for, and the check that should find it.
# `id` is what a person reads in the consent prompt and what the score
# matches a reported row against, so it is the entry id and the alias both.
PLAN: list[dict] = [
    {
        "id": f"{PREFIX}dead_ref",
        "kind": "automation",
        "check": "auto.dead_ref",
        "what": "an automation whose action names light."
                f"{PREFIX}missing — an entity that does not exist",
        "proves": "auto.dead_ref — automations naming missing entities",
        "row": _automation("dead_ref", {
            "trigger": [{"platform": "state", "entity_id": "sun.sun"}],
            "action": [{"service": "light.turn_on",
                        "target": {"entity_id": f"light.{PREFIX}missing"}}],
        }),
    },
    {
        "id": f"{PREFIX}dead_service",
        "kind": "automation",
        "check": "auto.dead_service",
        "what": f"an automation calling notify.{PREFIX}nowhere — a service "
                "that is not registered",
        "proves": "auto.dead_service — automations calling missing services",
        "row": _automation("dead_service", {
            "trigger": [{"platform": "state", "entity_id": "sun.sun"}],
            "action": [{"service": f"notify.{PREFIX}nowhere",
                        "data": {"message": "brAIn rehearsal"}}],
        }),
    },
    {
        "id": HELPER_ID,
        "kind": "helper",
        "check": "",
        "what": f"an {HELPER_ID} helper set to {HELPER_VALUE}",
        "proves": "that NOTHING fires on a healthy planted row — a check "
                  "that reports this one is a false positive worth knowing "
                  "about",
    },
]

# The checks a single pass structurally cannot rehearse, and why. Named
# rather than silently absent: "we did not test this" and "this passed"
# are different claims, and a report that made them look the same would be
# the fallback-read-as-the-real-thing failure in a new place.
NOT_REHEARSABLE: list[dict] = [
    {"check": "auto.forgotten_off",
     "why": "needs the automation to have been switched off for 30 days"},
    {"check": "auto.never_fired",
     "why": "needs the automation to have existed for 30 days without "
            "firing"},
    {"check": "auto.condition_never_passes",
     "why": "needs at least 3 stored traces of runs that all stopped at "
            "the same condition"},
    {"check": "auto.trace_error",
     "why": "needs a stored trace of a run that actually failed"},
    {"check": "dev.frozen",
     "why": "needs a week of hourly statistics reading the same value"},
    {"check": "dev.unavailable",
     "why": "needs the entity to have been unavailable for 24 hours"},
    {"check": "reg.unused_helper",
     "why": "gives a helper 30 days to be wired up to something"},
]


class Hooks:
    """The three things only the panel can do, handed in.

    ``write`` is `_apply_accepted`: the file, the reload and the entity
    existing in Core are three claims and only the third is the one that
    matters. ``remove`` is its mirror. ``snapshot`` is
    `checks.snapshot.collect`, and ``analyst`` runs the automations card's
    own prompt in a mode that persists no card.
    """

    def __init__(self, *, write, remove, snapshot, analyst, ws,
                 options=None):
        self.write = write          # (row) -> (written|None, error)
        self.remove = remove        # (entry_id, entity_id) -> (ok, error)
        self.snapshot = snapshot    # () -> snap
        self.analyst = analyst      # (planted) -> {"ok", "findings", "model", "error"}
        self.ws = ws                # (commands) -> list
        self.options = options or {}


# ---------------------------------------------------------------------------
# Consent
# ---------------------------------------------------------------------------

def plan(protected: list[str] | None = None) -> dict:
    """What a rehearsal would create, and whether it may.

    The answer to a call with no consent. `refused` is non-empty when the
    rehearsal will not run at all: a `protected_entities` pattern covering
    something it would create means the configuration has said not to touch
    that, and the honest response is to refuse *before* asking rather than
    to ask and then fail.
    """
    import automation_writer  # noqa: PLC0415 — deferred; it imports yaml
    patterns = automation_writer.protected_patterns(protected)
    covered = [row["id"] for row in PLAN
               if automation_writer.is_protected(_entity_for(row), patterns)]
    refused = ""
    if covered:
        refused = ("protected_entities covers "
                   + ", ".join(_entity_for(_row(i)) for i in covered)
                   + ", so brAIn will not create it. Narrow the pattern, or "
                     "run the rehearsal on a house where it does not match.")
    return {
        "plan": [{k: row[k] for k in ("id", "kind", "check", "what", "proves")}
                 for row in PLAN],
        "not_rehearsable": list(NOT_REHEARSABLE),
        "refused": refused,
    }


def _row(row_id: str) -> dict:
    return next(r for r in PLAN if r["id"] == row_id)


def _entity_for(row: dict) -> str:
    """The entity id the planted thing will have in Home Assistant."""
    if row["kind"] == "helper":
        return row["id"]
    return f"automation.{row['id']}"


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def _mentions(text: str, row: dict) -> bool:
    """Whether a reported row is about this planted one.

    Matched on the planted id, which is both the entry id and the alias, so
    it appears in a check's text (`Automation 'brain_test_dead_ref' …`) and
    in an entity id. Substring rather than equality because the sentence
    around it is the producer's to write.
    """
    return row["id"] in (text or "")


def score_checks(result: dict, planted: list[dict]) -> dict:
    """Which planted defects the checks found, and what else they said.

    Only rows that name something under the prefix are scored: findings
    about the real house are neither right nor wrong here, and counting
    them would make the number a property of how tidy the house is.
    """
    # Both halves: a check in `checks.SHADOW` still ran and still found
    # the planted defect, and scoring only the visible rows would report a
    # rule being trialled as a rule that does not work.
    rows = (result.get("findings") or []) + (result.get("shadow") or [])
    ours = [f for f in rows
            if PREFIX in f"{f.get('text', '')} {f.get('entity_id', '')}"]
    out: list[dict] = []
    matched: set[int] = set()
    for row in planted:
        if not row.get("check"):
            # The healthy one. Anything reported about it is a false
            # positive, and finding nothing is the pass.
            hits = [f for f in ours
                    if _mentions(f"{f.get('text', '')} "
                                 f"{f.get('entity_id', '')}", row)]
            for f in hits:
                matched.add(id(f))
            out.append({"id": row["id"], "check": "(nothing should fire)",
                        "verdict": "clean" if not hits else "false positive",
                        "reported": [f.get("text", "") for f in hits]})
            continue
        want = f"check:{row['check']}"
        hits = [f for f in ours if f.get("source") == want
                and _mentions(f"{f.get('text', '')} "
                              f"{f.get('entity_id', '')}", row)]
        for f in hits:
            matched.add(id(f))
        out.append({"id": row["id"], "check": row["check"],
                    "verdict": "found" if hits else "missed",
                    "reported": [f.get("text", "") for f in hits]})
    extra = [f for f in ours if id(f) not in matched]
    scored = [r for r in out if r["check"] != "(nothing should fire)"]
    # The arithmetic is `scoring.tally`'s, not a second copy of it: the
    # corpus replay grades the same producers against contributed houses,
    # and two answers to "precision against labels" is one too many.
    counts = scoring.tally(
        sum(1 for r in scored if r["verdict"] == "found"),
        len(scored), len(extra))
    return {
        "planted": counts["planted"],
        "found": counts["found"],
        "extra": counts["extra"],
        "extra_rows": [{"source": f.get("source", ""),
                        "text": f.get("text", "")} for f in extra[:10]],
        "rows": out,
        "ran": len(result.get("ran") or []),
        "skipped": len(result.get("skipped") or {}),
    }


def score_analyst(findings, planted: list[dict], model: str = "") -> dict:
    """Precision and recall over the planted rows, and nothing else.

    Both numbers are scoped to `brain_test_` rows on purpose. A finding
    about the real house is not a false positive — it may well be true —
    and folding one in would make "precision" a measurement of how tidy
    somebody's house is rather than of the prompt.
    """
    texts = []
    for f in findings or []:
        if isinstance(f, str):
            texts.append(f)
        elif isinstance(f, dict):
            texts.append(" ".join(str(f.get(k) or "") for k in
                                  ("text", "detail", "entity_id", "fix")))
    ours = [t for t in texts if PREFIX in t]
    scored = [r for r in planted if r.get("check")]
    rows = []
    matched = set()
    for row in scored:
        hits = [i for i, t in enumerate(ours) if _mentions(t, row)]
        matched.update(hits)
        rows.append({"id": row["id"],
                     "verdict": "found" if hits else "missed"})
    found = sum(1 for r in rows if r["verdict"] == "found")
    # Same arithmetic as the checks half and as the corpus replay, from one
    # place. `precision` is over the rows about planted things only: found
    # of everything the model said about a `brain_test_` id.
    counts = scoring.tally(found, len(scored), len(ours) - len(matched))
    return {
        "planted": counts["planted"],
        "found": counts["found"],
        "extra": counts["extra"],
        "recall": counts["recall"],
        "precision": counts["precision"],
        "reported": len(texts),
        "rows": rows,
        "model": model,
    }


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------

async def run(hooks: Hooks, *, progress=None) -> dict:
    """Plant, score, remove — and verify the removal.

    Returns ``{started_at, finished_at, created, checks, analyst, cleanup,
    not_rehearsable, error}``. Never raises: the cleanup is in a `finally`
    and its own sentence is what a failure here has to leave behind.
    """
    import checks  # noqa: PLC0415 — panel-local, and it pulls in the
                  # snapshot collector's aiohttp import lazily.

    started = time.time()
    out: dict = {"started_at": int(started), "finished_at": 0,
                 "created": [], "checks": {}, "analyst": {},
                 "cleanup": {}, "not_rehearsable": list(NOT_REHEARSABLE),
                 "error": ""}
    created: list[dict] = []

    def say(step: str) -> None:
        out["step"] = step
        if progress is not None:
            progress(dict(out))

    try:
        say("planting")
        for row in PLAN:
            made, why = await _plant(hooks, row)
            if made is None:
                out["error"] = f"could not create {row['id']}: {why}"
                return _finish(out, started)
            created.append(made)
            out["created"].append(row["id"])

        say("checking")
        snap = await hooks.snapshot()
        # `run_all`, not `server.run_checks`: this reads the rows and files
        # nothing, because filing would notify a phone about a defect brAIn
        # planted and let a planted row clear a real one.
        result = checks.run_all(snap, time.time())
        out["checks"] = score_checks(result, PLAN)

        say("asking the analyst")
        answer = await hooks.analyst(PLAN)
        if answer.get("ok"):
            out["analyst"] = {
                **score_analyst(answer.get("findings"), PLAN,
                                answer.get("model") or ""),
                "ran": True, "error": ""}
        else:
            out["analyst"] = {"ran": False,
                              "error": str(answer.get("error") or "")[:300],
                              "model": answer.get("model") or ""}
    except Exception as exc:  # noqa: BLE001 — the cleanup below is the
        # point; a traceback that skipped it would leave an automation in
        # somebody's file.
        out["error"] = f"{type(exc).__name__}: {exc}"[:300]
    finally:
        say("removing")
        out["cleanup"] = await _remove_all(hooks, created)
        _finish(out, started)
        journal.record(
            SOURCE, "ok" if out["cleanup"].get("ok") and not out["error"]
            else "error",
            ok=bool(out["cleanup"].get("ok") and not out["error"]),
            duration_s=out["duration_s"], error=out["error"],
            extra={"stage": "rehearsal",
                   "found": (out.get("checks") or {}).get("found", 0),
                   "planted": (out.get("checks") or {}).get("planted", 0)})
    return out


def _finish(out: dict, started: float) -> dict:
    out["finished_at"] = int(time.time())
    out["duration_s"] = round(time.time() - started, 1)
    out.pop("step", None)
    return out


async def _plant(hooks: Hooks, row: dict) -> tuple[dict | None, str]:
    if row["kind"] == "helper":
        made = (await hooks.ws([{
            "type": "input_number/create", "name": HELPER_NAME,
            "min": 0, "max": 100, "step": 0.1,
            "initial": HELPER_VALUE}]))[0]
        if not made:
            return None, "Home Assistant refused input_number/create"
        # The value is set separately: `initial` is what the helper reads
        # after a restart, and what a check reads is the state now.
        await hooks.ws([{"type": "call_service", "domain": "input_number",
                         "service": "set_value",
                         "service_data": {"entity_id": HELPER_ID,
                                          "value": HELPER_VALUE}}])
        return {"kind": "helper", "id": row["id"],
                "object_id": HELPER_ID.split(".", 1)[1]}, ""
    written, why = await hooks.write(row["row"])
    if written is None:
        return None, why
    return {"kind": "automation", "id": row["id"],
            "entry_id": written.get("automation_id") or row["id"],
            "entity_id": written.get("entity_id") or ""}, ""


async def _remove_all(hooks: Hooks, created: list[dict]) -> dict:
    """Take everything back out, then prove it with a fresh snapshot.

    Two claims and both are made: each removal reported success, AND
    nothing under the prefix is in the automations file, the entity
    registry or the states afterwards. The second is the one that matters —
    a splice that returned ok on a file Core never reloaded is exactly the
    failure `_apply_accepted` exists to prevent, read backwards.
    """
    problems: list[str] = []
    for made in created:
        if made["kind"] == "helper":
            answer = await hooks.ws([{"type": "input_number/delete",
                                      "input_number_id": made["object_id"]}])
            if answer and answer[0] is None:
                problems.append(f"Home Assistant would not delete "
                                f"{made['id']}")
            continue
        ok, why = await hooks.remove(made["entry_id"], made.get("entity_id"))
        if not ok:
            problems.append(f"{made['id']}: {why}")

    left: list[str] = []
    try:
        snap = await hooks.snapshot()
        left = leftovers(snap)
    except Exception as exc:  # noqa: BLE001
        problems.append(f"could not re-check the house afterwards: {exc}")
    if left:
        problems.append("still in the house: " + ", ".join(left[:8]))

    if not problems:
        return {"ok": True, "removed": len(created), "left": [],
                "sentence": f"removed all {len(created)} and checked they "
                            "are gone"}
    return {"ok": False, "removed": len(created), "left": left,
            "sentence": "SOMETHING WAS LEFT BEHIND — " + "; ".join(problems)}


def leftovers(snap: dict) -> list[str]:
    """Everything under the prefix a snapshot can still see.

    Three places, because a thing can survive in any of them
    independently: the automations file (the splice failed), the entity
    registry (Core did not reload), and the states (an entity nothing
    registered). Used by the removal check and worth reading on its own.
    """
    found: set[str] = set()
    for cfg in snap.get("automations") or []:
        if isinstance(cfg, dict) and str(cfg.get("id") or "").startswith(PREFIX):
            found.add(str(cfg["id"]))
    for eid in (snap.get("registry") or {}):
        if PREFIX in str(eid):
            found.add(str(eid))
    for eid in (snap.get("states") or {}):
        if PREFIX in str(eid):
            found.add(str(eid))
    return sorted(found)


# ---------------------------------------------------------------------------
# The analyst half
# ---------------------------------------------------------------------------

def analyst_prompt(planted: list[dict], build, cat: dict, orientation: dict,
                   framing: dict) -> str:
    """The automations card's own prompt, with one line appended.

    `build` is `categories.build_orientation_prompt` — the same builder the
    scheduled card uses, handed in rather than imported so this module
    stays importable without the web layer. The appended line does NOT say
    what was planted: a prompt that named the answers would measure whether
    the model can copy a list.
    """
    prompt = build(cat, orientation, **framing)
    return prompt + (
        "\n\nThis run is a self-test. Entities and automations whose id or "
        f"name begins with `{PREFIX}` were created moments ago on purpose. "
        "Report anything you find wrong with them exactly as you would "
        "report anything else — do not skip them, and do not treat them as "
        "expected.")


def run_analyst(prompt: str, system: str, model: str) -> dict:
    """One analyst run whose card is never persisted and whose findings
    are never filed. Same tools, same scoping, same budget."""
    result = engine.run_analyst(prompt, system, model, ANALYST_TIMEOUT,
                               ANALYST_MAX_TURNS, SOURCE)
    if not result.get("ok"):
        return {"ok": False, "findings": [], "model": model,
                "error": journal.scrub(result.get("error") or ""),
                "result": result}
    obj = engine.extract_json(result.get("text") or "")
    if not isinstance(obj, dict):
        return {"ok": False, "findings": [], "model": model,
                "error": "the analyst's reply was not the JSON the card "
                         "contract asks for",
                "result": result}
    findings = obj.get("findings")
    return {"ok": True, "model": model, "error": "",
            "findings": findings if isinstance(findings, list) else [],
            "result": result}


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save(payload: dict) -> None:
    try:
        REHEARSAL_FILE.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_json(REHEARSAL_FILE, payload)
    except OSError:
        # Same rule as the deep run's: the report has already been
        # answered, and this copy only feeds the diagnostics bundle.
        pass


def load() -> dict:
    try:
        data = json.loads(REHEARSAL_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def summary() -> dict:
    """What `/api/diagnostics` carries: the numbers, never the rows."""
    last = load()
    if not last:
        return {"ran_at": 0, "checks": {}, "analyst": {}}
    checks_ = last.get("checks") or {}
    analyst = last.get("analyst") or {}
    return {
        "ran_at": int(last.get("finished_at") or 0),
        "checks": {k: checks_.get(k, 0)
                   for k in ("planted", "found", "extra")},
        "analyst": {"precision": analyst.get("precision"),
                    "recall": analyst.get("recall"),
                    "model": analyst.get("model", ""),
                    "ran": bool(analyst.get("ran"))},
        "cleanup_ok": bool((last.get("cleanup") or {}).get("ok")),
    }
