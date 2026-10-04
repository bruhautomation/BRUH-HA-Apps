"""One reading of what a person typed, whichever box they typed it into.

brAIn has four places a person writes to it in their own words — the ask
bar, a Reply on a notification, the reason box on a Repairs dialog, and
the `brain.intent` service — and until 2.12 each one decided what the
words were by itself. The ask bar matched four regular expressions on the
first word ("learn …", "when …", "design … for …"); a Reply was always a
question for the Resident, so *"it's always like that in winter"* typed
under a frozen-sensor notification got an essay back and ended nothing;
the Repairs box was always a reason for Wrong, so *"remind me tomorrow"*
typed there became a permanent rule; and the service always meant an
automation. Each was right for the commonest sentence and wrong for the
second, and a person cannot see which box reads words which way.

So there is one reader, and it is cheap by contract: the `interpret` job
(a tool-less run on the cheap tier with a closed schema) maps the words
and the SURFACE they arrived on to one or more routes out of
:data:`KINDS`. Five rules.

**The model never names a case.** On a Reply or a Repairs dialog the case
is the one the person was looking at; the surface stamps it, and a route
only says what to DO with it (:data:`ENDINGS`). A model that could name a
case could end the wrong one.

**The vocabulary is closed and a surface narrows it** (:data:`ALLOWED`).
There is no case on the ask bar to end, and nothing on a lock screen to
draw a card on, so a route a surface cannot carry is dropped here rather
than half-executed there; a reply that leaves nothing a surface can carry
is read as no answer at all.

**No answer is the old behaviour, exactly.** Offline, no credential, the
day's runaway cap, a failed run, an unreadable reply: :func:`parse`
returns None and every caller runs the code it ran before 2.12 — the
regexes on the ask bar, the Resident's conversation on a Reply, a Wrong
with a note on Repairs, the intent drop on the service. The interpreter
can only ever make a box read words better; it cannot make one stop
working.

**Pressed surfaces skip the budget and nothing else** (:data:`PRESSED`).
The ask bar and a Reply are a person waiting on an answer, which is the
promise "asking by hand always runs" makes; they still need a credential,
because there is nothing to run without one.

**Nothing here changes the house.** Every route is handed to code that
already exists — a card question to the card queue, a sentence to the
intent drop, an ending to `_end_finding` — so what a route may do is what
that code may do, and the interpreter adds no new reach.

The explain path lives here too (:data:`EXPLAIN_SYSTEM`): *why did that
happen*, *why didn't it*, *why didn't you tell me* are read with the
decision trail, the traces and the logbook, and its contract is that "no
record of seeing it" and "decided not to" are different answers.

Stdlib only.
"""
from __future__ import annotations

import time

KINDS = ("card_question", "one_off", "standing_rule", "automation_edit",
         "case_ending", "defer", "remember", "study", "explain", "scenes",
         "chat")
ENDINGS = ("wrong", "done", "todo", "not_now")
SURFACES = ("ask_bar", "reply", "repairs", "service")

# What each surface can carry. A case ending needs a case, which only a
# reply and a Repairs dialog have; a card needs a screen to land on.
ALLOWED = {
    "ask_bar": frozenset({"card_question", "one_off", "standing_rule",
                          "automation_edit", "remember", "study", "explain",
                          "scenes", "chat"}),
    "reply": frozenset({"case_ending", "defer", "remember", "explain",
                        "one_off", "standing_rule", "chat"}),
    "repairs": frozenset({"case_ending", "defer", "remember"}),
    "service": frozenset({"one_off", "standing_rule", "automation_edit",
                          "remember", "study"}),
}
# A person is waiting on these: the budget does not stop them.
PRESSED = frozenset({"ask_bar", "reply", "repairs"})

MAX_ROUTES = 3
MAX_WORDS = 500
MAX_TEXT = 500
MAX_NOTE = 300
MAX_DEFER_H = 24 * 30
TIMEOUT_S = 45
# A runaway guard and not a budget, `triage.MAX_PER_DAY`'s kind: in
# memory, per local day, and past it every box reads words the old way.
MAX_PER_DAY = 400

STATE: dict = {"day": "", "runs": 0, "fallbacks": 0, "last_error": "",
               "last": 0.0, "routed": {}}


SYSTEM = """You read one message a homeowner typed to their smart home's \
assistant, brAIn, and say what they want done with it. You do not answer \
it and you do not act on it: you route it.

Routes (use only these words):
- card_question: a question about the house to answer with data ("how much \
power did the heating use this week?").
- one_off: something that should happen ONCE when a condition is met ("when \
the guests leave, turn the porch light off").
- standing_rule: something that should happen EVERY time ("turn the hall \
light on whenever the front door opens after dark").
- automation_edit: change an automation that already exists ("make the \
landing light stay on longer").
- case_ending: about the report they are looking at — ending is one of \
"wrong" (it is not a problem, with their reason as note), "done" (they \
fixed it), "todo" (they will do it later), "not_now" (dismiss for now).
- defer: remind them about that report later; hours if they said when.
- remember: a fact about the house to keep ("the garage freezer is \
switched off in winter").
- study: go and learn about something in depth ("figure out the boiler").
- explain: WHY something happened, why it did not happen, or why brAIn \
did not tell them ("why did the porch light come on at 3am?", "why didn't \
you tell me the garage was open?"). subject is the device they mean, as \
they named it.
- scenes: design lighting moods for a room; subject is the room.
- chat: anything else — a conversation.

text is the part of the message the route is about, in their words. A \
message may hold two or three things; give a route for each. Never invent \
a device, a report or a room that the message does not mention.

Answer only with the JSON object."""

SCHEMA = {
    "type": "object",
    "properties": {
        "routes": {
            "type": "array",
            "minItems": 1,
            "maxItems": MAX_ROUTES,
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "text": {"type": "string"},
                    "ending": {"type": "string", "enum": ["", *ENDINGS]},
                    "note": {"type": "string"},
                    "hours": {"type": "number", "minimum": 0},
                    "subject": {"type": "string"},
                },
                "required": ["kind"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["routes"],
    "additionalProperties": False,
}


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def gate(surface: str, *, has_auth: bool, auto_enabled: bool = True,
         budget_ok: bool = True, now: float | None = None) -> str:
    """Why this surface may not spend an interpreter run now, or ''.

    The reasons are sentences for the log, and every one of them means
    the caller runs its old code — the interpreter's refusal is never a
    person's refusal.
    """
    now = time.time() if now is None else float(now)
    if surface not in SURFACES:
        return f"unknown surface {surface!r}"
    if not has_auth:
        return "no Claude credential"
    if STATE["day"] != _day(now):
        STATE.update(day=_day(now), runs=0)
    if STATE["runs"] >= MAX_PER_DAY:
        return f"the interpreter has run {MAX_PER_DAY} times today"
    if surface not in PRESSED:
        if not auto_enabled:
            return "automatic runs are paused"
        if not budget_ok:
            return "the usage budget is spent"
    return ""


def note_run(now: float | None = None) -> None:
    now = time.time() if now is None else float(now)
    if STATE["day"] != _day(now):
        STATE.update(day=_day(now), runs=0)
    STATE["runs"] += 1
    STATE["last"] = now


def note_fallback(reason: str) -> None:
    STATE["fallbacks"] += 1
    STATE["last_error"] = str(reason or "")[:200]


def prompt(words: str, surface: str, case: dict | None = None) -> str:
    """The run's input: the surface, the case it is under, the words."""
    lines = [{
        "ask_bar": "They typed this into the question bar of the panel.",
        "reply": "They typed this as a reply to a notification about a report.",
        "repairs": "They typed this into the reason box under “Not a "
                   "problem” on a report.",
        "service": "An automation sent this sentence.",
    }.get(surface, "They typed this.")]
    if case:
        lines.append("The report they are looking at: “"
                     + str(case.get("claim") or case.get("text") or "")[:240]
                     + "”")
        detail = str(case.get("detail") or "").strip()
        if detail:
            lines.append(f"Its detail: {detail[:300]}")
    lines.append(f"Message: “{str(words or '')[:MAX_WORDS]}”")
    return "\n".join(lines)


def _clean_route(item, surface: str, words: str) -> dict | None:
    if not isinstance(item, dict):
        return None
    kind = str(item.get("kind") or "")
    if kind not in KINDS or kind not in ALLOWED.get(surface, ()):
        return None
    text = " ".join(str(item.get("text") or "").split())[:MAX_TEXT] or words
    route: dict = {"kind": kind, "text": text}
    if kind == "case_ending":
        ending = str(item.get("ending") or "")
        if ending not in ENDINGS:
            return None
        route["ending"] = ending
        route["note"] = " ".join(str(item.get("note") or "").split())[:MAX_NOTE]
    elif kind == "defer":
        hours = item.get("hours")
        if isinstance(hours, (int, float)) and not isinstance(hours, bool) \
                and 0 < hours <= MAX_DEFER_H:
            route["hours"] = float(hours)
    elif kind in ("explain", "scenes"):
        subject = " ".join(str(item.get("subject") or "").split())[:120]
        if kind == "scenes" and not subject:
            return None
        route["subject"] = subject
    return route


def parse(data, surface: str, words: str) -> list[dict] | None:
    """The routes a reply may take on this surface, or None.

    None — the caller's old path — for a reply that is not an object, has
    no route list, or leaves nothing this surface can carry. Routes past
    :data:`MAX_ROUTES` are dropped, and so is a second ending: one press
    ends a case once, and two endings in one message would be the later
    one silently overwriting the first.
    """
    if not isinstance(data, dict):
        return None
    items = data.get("routes")
    if not isinstance(items, list):
        return None
    words = " ".join(str(words or "").split())[:MAX_WORDS]
    out: list[dict] = []
    ended = False
    for item in items[:MAX_ROUTES * 2]:
        route = _clean_route(item, surface, words)
        if route is None:
            continue
        if route["kind"] in ("case_ending", "defer"):
            if ended:
                continue
            ended = True
        out.append(route)
        if len(out) >= MAX_ROUTES:
            break
    if not out:
        return None
    for route in out:
        STATE["routed"][route["kind"]] = STATE["routed"].get(route["kind"], 0) + 1
    return out


# ---------------------------------------------------------------------------
# The explain path
# ---------------------------------------------------------------------------

EXPLAIN_KINDS = ("why_happened", "why_not_happened", "why_not_told")

EXPLAIN_SYSTEM = """You answer one WHY question a homeowner asked about \
their smart home, as brAIn, the assistant that watches it. There are three \
kinds and you say which: why something happened (an automation, a person, \
a device); why something did NOT happen (an automation that did not run, a \
condition that stopped it); why brAIn did NOT tell them about something.

You have Home Assistant's reading tools, including explain_decision (what \
brAIn decided not to say, and why), get_automation_config, \
get_automation_trace, search_related, explain_change and get_logbook. \
Look before you answer. You cannot change anything.

Rules:
- Cite what you read: every claim names the trace, logbook row or decision \
row it came from, in cited.
- "brAIn has no record of seeing it" and "brAIn saw it and decided not to \
say" are different answers. A decision row is the second; no row at all \
is the first — say so in those words, and never guess a reason for a \
silence nothing recorded.
- Write for a person: plain words and the names they use, under 120 words, \
no markdown.
- offer is one change brAIn could make about it next, phrased as \
something they could ask for ("Raise these again for the garage freezer"), \
or "" when none fits.

Answer only with the JSON object."""

EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "kind": {"type": "string", "enum": list(EXPLAIN_KINDS)},
        "answer": {"type": "string"},
        "cited": {"type": "array", "maxItems": 8,
                  "items": {"type": "string"}},
        "offer": {"type": "string"},
        "no_record": {"type": "boolean"},
    },
    "required": ["kind", "answer"],
    "additionalProperties": False,
}

MAX_ANSWER = 900
MAX_CITED = 8


def explain_prompt(question: str, *, subject: str = "", trail: dict | None = None,
                   case: dict | None = None) -> str:
    """The question, the subject, and what the decision trail holds."""
    lines = [f"The homeowner asks: “{str(question or '')[:MAX_WORDS]}”"]
    if subject:
        lines.append(f"The device they mean: {subject}")
    if case:
        lines.append("They asked it about this report: “"
                     + str(case.get("claim") or case.get("text") or "")[:240]
                     + "”")
    if trail is not None:
        if not trail.get("readable", True):
            lines.append("brAIn's decision trail could not be read, so whether "
                         "it decided not to say something is unknown — say so.")
        elif trail.get("rows"):
            lines.append("What brAIn decided not to say about it (newest "
                         "first; cite these by their time):")
            for row in trail["rows"][:12]:
                stamp = time.strftime("%Y-%m-%d %H:%M",
                                      time.localtime(int(row.get("ts") or 0)))
                lines.append(f"- {stamp} {row.get('kind')}: "
                             f"{row.get('meaning', '')}"
                             + (f" — {row['reason']}" if row.get("reason") else "")
                             + (f" ({row['check']})" if row.get("check") else ""))
        else:
            lines.append("brAIn's decision trail holds NO decision about it: "
                         "if they ask why they were not told, brAIn has no "
                         "record of deciding not to — it may never have seen it.")
    return "\n".join(lines)


def parse_explain(data) -> dict | None:
    """A checked explanation, or None. The words are the model's; the
    shape and the caps are this module's."""
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind") or "")
    answer = " ".join(str(data.get("answer") or "").split())[:MAX_ANSWER]
    if kind not in EXPLAIN_KINDS or not answer:
        return None
    cited = [" ".join(str(c).split())[:200] for c in data.get("cited") or []
             if isinstance(c, str) and c.strip()][:MAX_CITED]
    offer = " ".join(str(data.get("offer") or "").split())[:200]
    return {"kind": kind, "answer": answer, "cited": cited, "offer": offer,
            "no_record": bool(data.get("no_record") is True)}


def summary() -> dict:
    return {"day": STATE["day"], "runs": STATE["runs"],
            "fallbacks": STATE["fallbacks"], "last_error": STATE["last_error"],
            "last": int(STATE["last"]), "routed": dict(STATE["routed"])}


__all__ = ["ALLOWED", "ENDINGS", "EXPLAIN_KINDS", "EXPLAIN_SCHEMA",
           "EXPLAIN_SYSTEM", "KINDS", "MAX_PER_DAY", "MAX_ROUTES", "PRESSED",
           "SCHEMA", "STATE", "SURFACES", "SYSTEM",
           "explain_prompt", "gate", "note_fallback", "note_run", "parse",
           "parse_explain", "prompt", "summary"]
