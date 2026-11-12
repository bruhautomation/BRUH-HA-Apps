"""The owner's own verdict on a fix, asked once, after the fix has landed.

A fault verifies itself: its fingerprint stops appearing and the house
says "Held". A request somebody typed into *What do you want to fix?*
(and a thing the chat said it could not do) has no fingerprint to stop:
the cloud closes it "Fixed in brAIn x.y.z", the house installs x.y.z,
and nothing on either side ever learns whether the person who asked got
what they asked for. The `Done when:` line was the bar, and nobody held
the fix to it on the house it came from.

So, once the house runs the release the fix shipped in, ONE question
case is filed on Today — "brAIn x.y.z was meant to fix this. Is it fixed
here?" — and the answer goes back on the issue as the comment the cloud
reads: *The owner confirms this is fixed* closes the loop, *Not fixed on
brAIn x.y.z: <their words>* reopens it for the next run's drain. Three
rules. **Asked once per fix**: a report fixed again under a new release
is asked again, and never otherwise. **Only where the owner can answer**
(`VERIFY_STREAMS`): their own requests and the chat's unmet ones, never
a gap or an idea a model wrote, which reads as a quiz about somebody
else's sentence. Nothing is written to memory either way — this is a
fact about brAIn, not the house — and the press settles the question
under its own kind so the scorecard does not count it as a rule being
right or wrong. Pure over what it is handed: the server files and
records, `upstream.owner_answer` carries the answer to the queue.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import atomic_write
from textclip import clip

from . import data_dir
from .upstream import (
    _DONE_RE, _field, product_of, running_at_least, running_for, version_tuple)

log = logging.getLogger("brain.devloop")

SOURCE = "devloop_verify"
SOURCE_TITLE = "Development loop"
TEXT_PREFIX = "Is this fixed now: "
# How a question was worded before it was named in words: the report's
# fingerprint, then the release. A row filed that way is still found.
LEGACY_TEXT_PREFIX = "Was this fixed: "
_LEGACY_FP_RE = re.compile(r"^[0-9a-f]{8,64}$")
VERIFY_STREAMS = frozenset({"look", "unmet"})
MAX_PER_PASS = 1
MAX_STATE = 300
# How long an unanswered question stays on Today. Past it the question is
# a leftover nobody recognises (#605): it is withdrawn, nothing is posted.
QUESTION_TTL_DAYS = 14


def state_file() -> Path:
    return data_dir() / "verify.json"


def load() -> dict:
    try:
        data = json.loads(state_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(data: dict) -> None:
    if len(data) > MAX_STATE:
        keep = sorted(data.items(), key=lambda kv: float(
            (kv[1] or {}).get("at") or 0))[-MAX_STATE:]
        data = dict(keep)
    try:
        atomic_write.write_json(state_file(), data, mode=0o600)
    except OSError as exc:
        log.info("could not write the verify ledger: %s", exc)


def live_version(addon: str, integration: dict | None) -> str:
    """The brAIn release that is actually RUNNING here (#535).

    run.sh deploys a new integration at every start and Home Assistant goes
    on running the one it loaded until it restarts, so the add-on can be on
    a release whose fixes are not live yet. The older of the two is what a
    fix is checked against; "" ("could not tell") while a restart is owed
    and nothing says what Home Assistant loaded. ``integration`` is
    `server._integration_versions()`; None (not known) leaves the add-on's.
    """
    integ = integration or {}
    loaded = str(integ.get("loaded") or "")
    have, mine = version_tuple(loaded), version_tuple(addon)
    if integ.get("restart_pending") and have is None:
        return ""
    if have is not None and mine is not None and have < mine:
        return loaded
    return str(addon or "")


def due(items: dict, version: str, state: dict, live_ts: set[int],
        products: dict | None = None) -> list[dict]:
    """The reports of the next question due (`due_groups`), flattened."""
    return [e for group in due_groups(items, version, state, live_ts, products)
            for e in group]


def area_of(entry: dict) -> tuple[str, str, str]:
    """What one question covers: the add-on, the release and the place the
    reports were made ("Chat", "Today"; "" for the owner's own requests)."""
    return (product_of(entry), str(entry.get("fixed_in") or ""),
            _title_and_place(entry)[1].casefold())


def due_groups(items: dict, version: str, state: dict, live_ts: set[int],
               products: dict | None = None) -> list[list[dict]]:
    """The fixed reports whose fix this house now runs and nobody has been
    asked about under that release, one list per question: the fixes one
    release made to one area are asked about together (#535), five cards
    about one update being five interruptions with one answer. A fix whose
    release is unknown is never asked about: "is x.y.z here" has no answer
    when x.y.z is. ``version`` is brAIn's RUNNING release (`live_version`)."""
    groups: dict[tuple, list[dict]] = {}
    for entry in _eligible(items, version, state, live_ts, products):
        groups.setdefault(area_of(entry), []).append(entry)
    return list(groups.values())[:MAX_PER_PASS]


def _eligible(items: dict, version: str, state: dict, live_ts: set[int],
              products: dict | None = None) -> list[dict]:
    out = []
    for entry in sorted((e for e in items.values() if isinstance(e, dict)),
                        key=lambda e: float(e.get("closed_at") or 0)):
        if (entry.get("verdict") != "fixed"
                or str(entry.get("stream") or "") not in VERIFY_STREAMS
                or not entry.get("fixed_in")
                or running_at_least(running_for(entry, version, products),
                                    entry["fixed_in"]) is not True):
            continue
        rec = state.get(entry["fp"]) or {}
        if rec.get("fixed_in") == entry["fixed_in"]:
            # Asked under this release already, answered or still open.
            continue
        if int(rec.get("ts") or 0) in live_ts:
            continue
        out.append(entry)
    return out


def moot(entry: dict | None, rec: dict | None,
         now: float | None = None) -> str:
    """Why an open question is about a fix that is no longer the fix, or
    "" while it still stands: the report has gone from the queue, was
    reopened, or was fixed again in a newer release (which is asked about
    on its own). Everything else is the person's to answer.

    It also answered Yes for brAIn ("brAIn checked on brAIn V") when a
    report whose stream clears was not seen after the install. No such
    question is ever asked — only `VERIFY_STREAMS` are, and neither
    clears, because a request with no fingerprint has nothing to stop —
    so that branch could not run, and a cleared fault is said on its own
    issue by upstream's **Held** follow-up.
    """
    rec = rec or {}
    if not isinstance(entry, dict):
        return "the report is no longer on brAIn's list"
    if entry.get("verdict") != "fixed":
        return "the report was reopened, so the fix is being looked at again"
    asked_for = str(rec.get("fixed_in") or "")
    fixed_in = str(entry.get("fixed_in") or "")
    if asked_for and fixed_in and asked_for != fixed_in:
        return (f"it was fixed again in {fixed_in}, and that fix is "
                "asked about on its own")
    asked_at = float(rec.get("at") or 0)
    if (now is not None and asked_at and not rec.get("answer")
            and now - asked_at > QUESTION_TTL_DAYS * 86400):
        return (f"nobody answered it in {QUESTION_TTL_DAYS} days, so brAIn "
                "stopped asking")
    return ""


# The store's cap on a row's `text` (`findings_store.MAX_TEXT`). A text over
# it is cut by the store and the rest put at the head of the detail, which
# is how a card ended "…(Fix: Findings never" over a detail starting "say
# who acts:". The question is composed to fit, so the store never cuts it.
TEXT_CHARS = 200
# A report's place as the streams write it: "Fix: <title>" (a request, a
# report the chat wrote), "Gap: …", "Idea: …", "Design: …", optionally led
# by the add-on it is about ("GardenRX · Fix: …"). Anything else is a place
# ("Chat", "Today") and the report's sentence is its title.
_KIND_TITLE_RE = re.compile(
    r"^(?:(?P<addon>[^·]{1,40}?) · )?(?:Fix|Gap|Idea|Design): (?P<title>.+)$")
# A sentence a developer wrote for a developer: code quotes, a call, a
# CONSTANT_NAME, a snake_case name (a tool, a setting, a function) or a
# file. A person checking whether the fix held reads none of it.
_DEVELOPER_RE = re.compile(
    r"`|\w\(\)|\b\w+\([^)]*\)|\b[A-Z][A-Z0-9]*_[A-Z0-9_]+\b"
    r"|\b[a-z][a-z0-9]*_[a-z0-9_]+\b|\b[\w-]+\.(?:py|js|mjs|ts|css|sh|json|yaml)\b")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


def _title_and_place(entry: dict) -> tuple[str, str]:
    """``(title, place)``: the report's own title and, when its ``where``
    is a place rather than a title, that place."""
    where = " ".join(str(entry.get("where") or "").split())
    what = " ".join(str(entry.get("what") or "").split()).rstrip(" .")
    m = _KIND_TITLE_RE.match(where)
    if m:
        return m.group("title").strip().rstrip(" ."), ""
    return what, where


def _plain_sentences(text: str) -> str:
    """``text`` less every sentence written for a developer."""
    kept = [s for s in _SENTENCE_RE.split(" ".join(str(text or "").split()))
            if s and not _DEVELOPER_RE.search(s)]
    return " ".join(kept).strip()


def _done_when(entry: dict) -> str:
    """The report's own bar for the fix, in plain sentences, or ""."""
    said = _plain_sentences(_field(entry, "done_when", _DONE_RE))
    said = re.sub(r"^done when:?\s*", "", said, flags=re.I)
    return clip(said.rstrip(" ."), 240) if said else ""


def _checking(entry: dict, place: str, product: str) -> str:
    """What brAIn could not check itself, and the one thing to try (#605,
    #830), in the words of the screen: Ask, not "the chat", and no stream
    or component name.

    Only the owner's own requests and the chat's unmet ones are ever asked
    (`VERIFY_STREAMS`), and neither has an error brAIn can watch for: a
    fault that stops recurring is said on its own report, never asked. So
    the card says which it is, what to do to tell, and what the person
    will see when it is fixed — the report's own "Done when" when it has
    one."""
    stream = str(entry.get("stream") or "")
    bar = _done_when(entry)
    seen = (f" You will see: {bar}." if bar else
            " It is fixed when it does what you asked.")
    if stream == "unmet":
        cannot = ("brAIn cannot check this one itself: it could not do "
                  "this when you asked in Ask, and only asking again shows "
                  "whether it can now.")
        step = "Try this: ask the same thing in Ask again." + seen
    else:
        where = _household_place(place or ("" if product == "brAIn"
                                           else product))
        cannot = ("brAIn cannot check this one itself: it is about what you "
                  "see and use, which brAIn has no error to watch for.")
        step = (f"Try this: open {where} and do what you reported again."
                if where else
                "Try this: do what you reported again.") + seen
    return f"{cannot} {step}"


def _household_place(place: str) -> str:
    """A report's place as the screen names it: the chat is Ask."""
    return "Ask" if str(place or "").strip().casefold() == "chat" else place


def _reported(entry: dict) -> str:
    """Where and when the report was made, for a question that has been
    waiting: "You reported this on brAIn 4.0.9." ("" when unknown)."""
    release = str(entry.get("version") or "")
    if not version_tuple(release):
        return ""
    product = product_of(entry)
    return f"You reported this on {product} {release}."


def question_row(entry: dict) -> dict:
    """The question, named by the report's own title and where it was.

    It used to be named by the report's fingerprint with the release as
    its subject — "Was this fixed: 70766c7a7025546b (brAIn 3.8.6)" — which
    is the dedupe key on the screen. The fingerprint stays in the ledger
    (`record_asked`); what a person reads is the report.

    The text is the report's title, cut on a word (with "…" only when it
    was cut) so the whole row fits the store's cap; the detail is the
    report itself, less any sentence written for a developer, and where to
    look. Nothing explains where an answer goes: the buttons say that.
    """
    fixed_in = str(entry.get("fixed_in") or "")
    product = product_of(entry)
    title, place = _title_and_place(entry)
    place = _household_place(clip(place, 60).strip())
    in_place = f" ({place})" if place else ""
    tail = f" — after the {product} {fixed_in} update"
    room = TEXT_CHARS - len(TEXT_PREFIX) - len(in_place) - len(tail)
    named = clip(title, max(room, 20))
    what = _plain_sentences(entry.get("what") or "").rstrip(" .")
    if not what:
        what = _plain_sentences(title).rstrip(" .")
    look = place or (product if product != "brAIn" or not title
                     or _DEVELOPER_RE.search(title) else title)
    # "Where to look: brAIn" on brAIn's own screen names no place (#562).
    look = "" if look == "brAIn" else look
    detail = " ".join(p for p in (
        f"{what}." if what else "",
        _reported(entry),
        (f"{product} {fixed_in} was installed here to fix it."
         if fixed_in else f"A {product} update was installed here to fix it."),
        # A place the step names is not said twice, and a title is no place.
        f"Where to look: {product}." if not place and product != "brAIn"
        else "",
        _checking(entry, place, product)) if p)
    return {
        # Stable per fix: the report's words and the release it was fixed
        # in, so the store's dedupe and the settled ledger let the same
        # report be asked about again only under a NEW fix. The release
        # rides at the end, never as the subject.
        "text": f"{TEXT_PREFIX}{named}{in_place}{tail}",
        "claim": f"Is this fixed now: “{clip(title, 160)}”{in_place}?",
        "detail": detail,
        "kind": "question", "severity": "info", "stakes": "low",
        "fixable": False, "source": SOURCE, "source_title": SOURCE_TITLE,
        "entity_id": "", "evidence": [],
    }


def group_row(entries: list[dict]) -> dict:
    """One question for the fixes one release made to one area.

    A single report is the question it always was (`question_row`). Several
    are one row naming the release and the place once, its detail listing
    what changed — each change once, however many reports asked for it.
    """
    entries = [e for e in entries if isinstance(e, dict)]
    if len(entries) == 1:
        return question_row(entries[0])
    first = entries[0]
    fixed_in = str(first.get("fixed_in") or "")
    product = product_of(first)
    titles: list[str] = []
    place = ""
    for entry in entries:
        title, where = _title_and_place(entry)
        place = place or where
        plain = _plain_sentences(title).rstrip(" .") or title
        if plain and plain.casefold() not in {t.casefold() for t in titles}:
            titles.append(plain)
    if len(titles) == 1:
        return question_row(first)
    place = _household_place(clip(place, 60).strip())
    in_place = f" ({place})" if place else ""
    tail = f" — after the {product} {fixed_in} update"
    more = f" and {len(titles) - 1} more"
    room = TEXT_CHARS - len(TEXT_PREFIX) - len(more) - len(in_place) - len(tail)
    listed = "; ".join(clip(t, 120) for t in titles)
    quoted = [f"“{clip(t, 70)}”" for t in titles[:2]]
    named = (" and ".join(quoted) if len(titles) == 2 else
             f"{quoted[0]}, {quoted[1]} and {len(titles) - 2} more")
    look = place or ("" if product == "brAIn" else product)
    detail = " ".join(p for p in (
        f"{product} {fixed_in} was installed here to fix these: "
        f"{listed}.",
        f"Where to look: {_household_place(look)}." if look else "",
        _checking({"stream": first.get("stream")}, place, product)) if p)
    return {
        # Stable per question: the first change, how many others, the place
        # and the release — so a later question about the same release and
        # place is a different row, not one the settled ledger suppresses.
        "text": f"{TEXT_PREFIX}{clip(titles[0], max(room, 20))}{more}"
                f"{in_place}{tail}",
        "claim": f"Are these fixed now{in_place}: {named}?",
        "detail": detail,
        "kind": "question", "severity": "info", "stakes": "low",
        "fixable": False, "source": SOURCE, "source_title": SOURCE_TITLE,
        "entity_id": "", "evidence": [],
    }


def fps_for_finding(state: dict, finding: dict) -> list[str]:
    """Every report a question row is about: a question can cover several
    (`group_row`), all recorded under the row's id. Falls back to
    `fp_for_finding` for a row filed one report at a time."""
    ts = finding.get("ts")
    out = [fp for fp, rec in state.items()
           if isinstance(rec, dict) and ts is not None and rec.get("ts") == ts]
    if out:
        return out
    fp = fp_for_finding(state, finding)
    return [fp] if fp else []


def record_asked(state: dict, fp: str, ts: int, fixed_in: str, now: float,
                 *, text: str = "") -> dict:
    state[fp] = {"ts": int(ts), "at": int(now), "fixed_in": str(fixed_in),
                 "answer": ""}
    if text:
        state[fp]["text"] = str(text)[:400]
    return state


def fp_for_finding(state: dict, finding: dict) -> str:
    """The report a question row is about: by the row's id, then by its
    words, then — for a row filed the old way — the fingerprint its text
    began with."""
    ts = finding.get("ts")
    text = str(finding.get("text") or "")
    for fp, rec in state.items():
        if isinstance(rec, dict) and rec.get("ts") == ts:
            return fp
    for fp, rec in state.items():
        if isinstance(rec, dict) and text and rec.get("text") == text:
            return fp
    if text.startswith(LEGACY_TEXT_PREFIX):
        token = text[len(LEGACY_TEXT_PREFIX):].split(" ", 1)[0]
        if _LEGACY_FP_RE.match(token):
            return token
    return ""


def record_answer(state: dict, fp: str, accepted: bool, now: float) -> dict:
    rec = dict(state.get(fp) or {})
    rec["answer"] = "held" if accepted else "not_fixed"
    rec["answered_at"] = int(now)
    state[fp] = rec
    return state


def record_moot(state: dict, fp: str, now: float) -> dict:
    """A question withdrawn because the fix it asked about is no longer
    the fix. Nothing is posted: there is nothing to say about it."""
    rec = dict(state.get(fp) or {})
    rec["answer"] = "moot"
    rec["answered_at"] = int(now)
    state[fp] = rec
    return state


def forget_answer(state: dict, fp: str) -> dict:
    """Undo of either answer: the question is open again and the answer
    forgotten. A comment already posted stands — the next answer is
    posted beside it, which is still the truth in order."""
    rec = dict(state.get(fp) or {})
    if rec:
        rec["answer"] = ""
        rec.pop("answered_at", None)
        state[fp] = rec
    return state
