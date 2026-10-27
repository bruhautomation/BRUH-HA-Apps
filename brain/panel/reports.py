"""One plain-text file per problem, where a person can find it.

Every failure this add-on has shipped was a quiet one, and the tools that
answered it were all pull-shaped: `brain doctor` if you knew to run it,
the Diagnostics section if you knew to open ⚙, `brain report` if you had
already been asked for one. By the time anybody looked, the journal row
that would have explained it was one of two thousand and the log line had
scrolled off. So the moment something fails, the evidence for it is
written down — as ONE text file a person can read, copy and attach,
never a directory of five files and a tarball.

Three producers, one writer:

* a journal row ending in a failure outcome (`FAILURE_OUTCOMES`) — every
  Claude run, checks pass, baseline build and overnight heal already
  passes through `journal.record`, so `server` registers one listener
  there and nothing else has to remember to report;
* the health verdict leaving `ok` (`note_health`), which is the one that
  catches a daemon that died and a credential that expired on a Tuesday;
* a notification that could not be delivered, which is the one failure
  whose only symptom was silence on a phone.

Four rules keep the folder readable. **A repeat is a line, not a file**:
the same failure inside `DEDUP_HOURS` appends ``seen again at HH:MM`` to
the file it already has, because forty files about one dead credential
are how the folder stops being opened. **Redaction is one function**,
`redact`, run over the WHOLE file after it is composed — `journal.scrub`
plus the JSON-field rule `brain-report.sh` has always applied — so a
section that "cannot hold a token" is covered the day it does. **The
folder is capped** (`MAX_REPORTS`, oldest first, never the one just
written). And **`file_incident` never raises**: it is called from
accounting code and a report that took down the run it was reporting on
is worse than no report.

The directory is `/share/brain/reports`, the same place `brain report`
has always written to, because `/share` is what the file editor and the
Samba share can see and `/data` is not. It is skipped silently on a dev
checkout with no `/share`, the rule the two mirrors follow.

This module must not import `server`: the diagnostics it abridges arrive
as a dict or a callable from whoever has one.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

import atomic_write
# Aliased because `health` is already a local name in this file three
# times over — the verdict dict in `abridge` and `faults`, and a
# keyword argument on `file_incident`. A module shadowed by a dict
# fails at the attribute rather than at the import, which is a
# traceback a long way from its cause.
import health as health_rules
import journal
import plain_words
import rule_record

log = logging.getLogger("brain.reports")

# Health problems the sweep reports with a row of its own.
HEALTH_ROWS_OF_THEIR_OWN = frozenset({"restart"})
# Health problems that, alone, are not worth a problem file: a restart owed
# after an ordinary update (the status line and Repairs already say it).
NOT_INCIDENTS = frozenset({"restart"})

REPORTS_DIR = Path(os.environ.get("BRAIN_REPORTS_DIR", "/share/brain/reports"))
INDEX_FILE = Path(os.environ.get("BRAIN_REPORTS_INDEX", "/data/reports-index.json"))
HEALTH_LAST_FILE = Path(os.environ.get("BRAIN_HEALTH_LAST", "/data/health-last.json"))
SUPERVISOR_URL = os.environ.get("BRAIN_SUPERVISOR_URL", "http://supervisor")

MAX_REPORTS = 30
DEDUP_HOURS = 24
LOG_LINES = 80
LOG_TIMEOUT_S = 5
# The abridged diagnostics and the optional full payload are both bounded:
# this file is what gets pasted into an issue, and an issue nobody can
# scroll is an issue nobody reads.
MAX_EXTRA_CHARS = 200_000

# The journal outcomes that are a problem — `journal`'s own set, not a
# second copy of it. `ok` with `extra.landed` is a run that worked;
# `fallback` is a quieter path that still produced a card; `applied` and
# `healed` are successes; `heal_skipped` and `denied` are refusals doing
# their job, and a refusal is not a fault. This module had its own list
# and `journal.summary` had a different rule (`outcome != "ok"`), so a
# successful heal was not worth a report and *was* worth a row at the top
# of the fault list — one answer now, in the module that owns the word.
FAILURE_OUTCOMES = journal.FAILURE_OUTCOMES

# Which option bounds a run of each source. The timeout sentence names the
# switch rather than the symptom, and the switch differs by who ran.
TIMEOUT_OPTION = {
    "insight": "generation_timeout_minutes",
    "card": "generation_timeout_minutes",
    "ask": "generation_timeout_minutes",
    "fix": "generation_timeout_minutes",
    "engine": "generation_timeout_minutes",
    "study": "study_timeout_minutes",
    "consolidator": "the consolidator's fixed 480s budget",
}

_FIELD_RE = re.compile(
    r'("(?:access_token|refresh_token|token|api_key|oauth_token|value)"'
    r'[ ]*:[ ]*")[^"]{8,}"')


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------

def redact(text: str) -> str:
    """`journal.scrub` plus the JSON-field rule the shell has always applied.

    One function for the whole file. The shell's `redact()` in
    `brain-report.sh` is the same four rules in sed, and
    `tests/test_reports.py` drives both over one fixture set.
    """
    return _FIELD_RE.sub(r'\1[redacted]"', journal.scrub(text))


# ---------------------------------------------------------------------------
# Where the files go
# ---------------------------------------------------------------------------

def available() -> bool:
    """`/share` exists — the dev-checkout rule the mirrors follow."""
    return REPORTS_DIR.parent.parent.exists()


def _safe_path(name: str) -> Path | None:
    """The file a name means, or None for anything that is not a bare
    ``*.txt`` under the reports directory.

    The name arrives off the wire. `basename` rejects a path, the suffix
    rejects the index and anything else somebody drops in the folder, and
    the normpath-and-prefix barrier is the same rule spelled the way a
    static analyser reads it (`chat_session.transcript_path`'s reasoning).
    """
    name = str(name or "")
    if (not name or name != os.path.basename(name) or name.startswith(".")
            or not name.endswith(".txt") or "/" in name or "\\" in name
            or ".." in name):
        return None
    root = os.path.normpath(str(REPORTS_DIR))
    full = os.path.normpath(os.path.join(root, name))
    if not full.startswith(root + os.sep):
        return None
    return Path(full)


# ---------------------------------------------------------------------------
# The index: fingerprints, so a repeat is a line and not a file
# ---------------------------------------------------------------------------

def _load_index() -> dict:
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_index(index: dict) -> None:
    try:
        atomic_write.write_json(INDEX_FILE, index)
    except OSError as exc:
        log.warning("could not write the reports index: %s", exc)


def fingerprint(kind: str, source: str, outcome: str, error: str) -> str:
    first = str(error or "").strip().splitlines()[0] if str(error or "").strip() else ""
    key = "|".join((str(kind or ""), str(source or ""), str(outcome or ""), first))
    return hashlib.sha1(key.encode("utf-8", "replace"), usedforsecurity=False).hexdigest()


# ---------------------------------------------------------------------------
# The sections
# ---------------------------------------------------------------------------

def fetch_addon_log(lines: int = LOG_LINES, timeout: float = LOG_TIMEOUT_S) -> str:
    """The tail of the add-on's own log, from the Supervisor.

    Called from a worker thread (never the event loop), so it may block
    for its timeout. A failure is a sentence in the section rather than
    an exception, because the log is one section of six and the other
    five are still worth having.
    """
    token = os.environ.get("SUPERVISOR_TOKEN", "")
    if not token:
        return "(no Supervisor token in this process; run `ha log` in the terminal)"
    req = urllib.request.Request(
        f"{SUPERVISOR_URL}/addons/self/logs",
        headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — fixed host
            raw = resp.read(2_000_000)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return f"(log unavailable: {exc})"
    text = raw.decode("utf-8", "replace")
    tail = text.splitlines()[-lines:] if lines > 0 else []
    return "\n".join(tail) if tail else "(log empty)"


def abridge(diagnostics) -> dict:
    """The subset of `/api/diagnostics` a report carries: versions, the
    health verdict, the journal's last day, the last checks pass and the
    auth state. Never the options, never the stores' shapes — those are
    the full payload's, and a manual report appends that whole."""
    if callable(diagnostics):
        try:
            diagnostics = diagnostics()
        except Exception as exc:  # noqa: BLE001 — a section, not the report
            return {"error": f"diagnostics unavailable: {exc}"}
    if not isinstance(diagnostics, dict):
        return {}
    if diagnostics.get("error") and len(diagnostics) == 1:
        # The payload could not be built — `compose` resolves the callable
        # once and puts the reason here, so this is the shape that arrives
        # when it failed. Carried through rather than flattened into a
        # page of nulls, which is what a report reading "state: null,
        # runs: null" would have been.
        return {"error": str(diagnostics["error"])[:300]}
    j = diagnostics.get("journal") or {}
    checks = diagnostics.get("checks") or {}
    health = diagnostics.get("health") or {}
    auth = diagnostics.get("auth") or {}
    return {
        "versions": diagnostics.get("versions") or {},
        "health": {k: health.get(k) for k in ("state", "reason", "fix")},
        "health_problems": [p.get("what") for p in (health.get("problems") or [])
                            if isinstance(p, dict)],
        "journal_24h": {k: j.get(k) for k in ("runs", "by_outcome", "by_source")},
        "checks_last": {k: checks.get(k) for k in (
            "finished_at", "created", "cleared", "skipped", "errors", "error")}
        if isinstance(checks, dict) else checks,
        "checks_ran": len(checks.get("ran") or []) if isinstance(checks, dict) else 0,
        "auth": {k: auth.get(k) for k in ("state", "checked_at", "error")},
        "daemons": {k: bool((v or {}).get("running")) if isinstance(v, dict) else v
                    for k, v in (diagnostics.get("daemons") or {}).items()},
        # The same rows the prose section above renders — one derivation,
        # so a person and a machine reading the same file cannot disagree
        # about what is wrong with this install.
        "faults": faults(diagnostics),
    }


# ---------------------------------------------------------------------------
# Everything that is wrong right now
# ---------------------------------------------------------------------------

# How many of any one repeated fault to name before saying how many more.
FAULTS_PER_KIND = 6
# Total cap on the section. Past this the report says how many it left out
# rather than becoming the thing nobody reads — the same trade every other
# capped list here makes.
MAX_FAULTS = 40
# A producer needs this many endings before "wrong more often than right"
# is a claim about the rule rather than an anecdote. `findings_store`'s own
# floor, restated here rather than imported because this module may not
# import the panel.
SCORE_MIN_ENDINGS = 4
# A producer's record is a fault only while people are still marking it
# Wrong: the scorecard is all-time, so a rule fixed in a release goes on
# carrying the Wrongs it earned before the fix, and a row read off the total
# alone reported a fixed rule for ever (and reopened its bug report on every
# update). A row whose newest Wrong is older than this is history.
SCORE_RECENT_S = 14 * 86400
# Producers that are not rules and cannot be muted: brAIn's own looks, the
# safety lane, the tripwire and the tripped-detector check. `cases`' own
# set, restated because this module must run with the panel down and
# `cases` reads the stores; `tests/test_fault_rows_say_why.py` holds the two
# equal. "Ignore all like this" is never offered on their cards, so a row
# telling somebody to tick it was advice nobody could follow.
UNMUTABLE_SOURCES = frozenset({"resident", "safety", "security",
                               "check:safety.tripped", "devloop_verify"})


def faults(diagnostics) -> list[dict]:
    """Every fault the diagnostics payload can see, as flat rows.

    **A report whose faults are buried is a report nobody reads.** What
    shipped opened with *"Nothing failed to produce this file"* and then
    six hundred lines of JSON, and the install that prompted this carried
    seven distinct faults inside it — a rehearsal that could not clean up,
    a usage credential refused for a reason nothing recognised, a
    notification that would not deliver, a deep check that had failed, a
    check that could not look, two measurement stores reading zero, and a
    house check the homeowner had marked Wrong six times out of six.
    Every one of them was in the file. None of them was *findable*.

    So this is the sweep, and it is deliberately exhaustive rather than
    clever: every surface the payload carries that can say something went
    wrong is read here, in one pass, and the rows go at the TOP of the
    report. Three rules.

    **It is pure over what it is handed.** No imports of the panel, no
    fetches, no clock beyond the payload's own stamps — so it runs when
    the panel is down, which is exactly when a report is most wanted, and
    `brain report`'s own assembled payload goes through the same function
    the live one does.

    **A refusal doing its job is not a fault.** `heal_skipped`, a
    `denied` run, a producer standing down because it could not read a
    file, a shadow check finding nothing — none of those is something
    broken, and a section that listed them would be a section people
    learn to skim. What IS listed is every claim of the form *this did
    not work*, *this could not look*, or *this is wrong about my house*.

    **It never raises.** It is called from the writer, and a fault sweep
    that took down the report it was summarising is worse than no sweep —
    `file_incident`'s rule, one function over. A section that could not
    be derived says so as its own row.
    """
    try:
        return _faults(diagnostics)
    except Exception as exc:  # noqa: BLE001 — see the docstring
        return [{"where": "this report",
                 "what": "brAIn could not work out what is wrong",
                 "detail": f"{type(exc).__name__}: {exc}"[:200],
                 "title": "This list",
                 "sentence": "brAIn could not work out what is wrong. "
                             "Use Report a problem below to send what it has.",
                 "technical": f"{type(exc).__name__}: {exc}"[:400]}]


def _sentence(*parts) -> str:
    """Join sentence parts, each ending in a full stop, first letter up."""
    out = []
    for part in parts:
        part = str(part or "").strip()
        if not part:
            continue
        part = part[:1].upper() + part[1:]
        if part[-1] not in ".!?…)":
            part += "."
        out.append(part)
    return " ".join(out)


def _row(out: list, where: str, what: str, detail: str = "", *,
         title: str | None = None, sentence: str | None = None,
         technical: str | None = None, seen_at: float = 0) -> None:
    """One fault row.

    `where`, `what` and `detail` are the machine fields: the report file
    prints them and the development loop fingerprints `where|what`, so
    their values do not move. `title`, `sentence` and `technical` are what
    ⚙ › Diagnostics shows — a name, what is not working and what to do, in
    words, and the ids and codes folded under it. A row given no human
    words is one whose machine words already are (`what` and its detail,
    as a sentence). `seen_at` is when the row's evidence last happened,
    for a row read off a record rather than the house now (a producer's
    newest Wrong): the development loop dates the row by it, so a count
    that has not moved since a fix is not the fault coming back."""
    if not what:
        return
    if sentence is None:
        sentence = _sentence(what, detail)
        if technical is None:
            technical = ""
    elif technical is None:
        technical = "; ".join(p for p in (f"{where}: {what}",
                                          str(detail or "")) if p)
    out.append({"where": where, "what": str(what)[:200],
                "detail": str(detail or "")[:400],
                "title": str(title or where)[:120],
                "sentence": str(sentence)[:500],
                "technical": str(technical or "")[:600]})
    if seen_at and seen_at > 0:
        out[-1]["seen_at"] = float(seen_at)


# The sentence `checks.run_all` writes for a check it could not run because
# the snapshot has no such key. Read as a shape rather than a lookup so a
# renamed key still folds; anything else is the check's own reason.
_MISSING_KEY_RE = re.compile(r"^snapshot is missing (\w+(?:, \w+)*)$")


def _missing_snapshot_keys(why) -> list[str]:
    """Every key a "snapshot is missing a, b" skip names (`run_all` joins
    them with ", "), or []."""
    match = _MISSING_KEY_RE.match(str(why or "").strip())
    return match.group(1).split(", ") if match else []


# A snapshot read that failed because Home Assistant itself did not answer
# (Core restarting: 502/503/504, refused or reset connection, a timeout).
# That is one fact about the house, not a fault in brAIn's reader, and it
# is said once however many keys and checks it took down.
_HA_DOWN_RE = re.compile(
    r"(?<!\d)50[234](?!\d)|bad gateway|service unavailable|gateway time"
    r"|connection (?:refused|reset|aborted|closed)|cannot connect to host"
    r"|connect call failed|server disconnected|timed? ?out|timeout"
    r"|broken pipe|remote end closed", re.I)


def _ha_did_not_answer(why) -> bool:
    return bool(_HA_DOWN_RE.search(str(why or "")))


# When a day's refused runs become a fault row: a share of the day's runs,
# with a floor so three refusals in five runs on a quiet house is not one.
# Findings still waiting for a first look: how many, and how long the oldest.
WAITING_LOOK_MIN = 2
WAITING_LOOK_AFTER_S = 2 * 3600

RATE_LIMITED_SHARE = 0.10
RATE_LIMITED_MIN = 5


# What a journal row says its run was about, best first. A caller that
# knew writes it into `extra` (`journal.record` keeps eight keys, scrubbed
# and capped); an id is the floor, because "energy" is a card somebody can
# find and "a run" is not.
_SUBJECT_KEYS = ("title", "label", "category_title", "about", "id")


def _run_subject(extra: dict) -> str:
    for key in _SUBJECT_KEYS:
        value = extra.get(key) if isinstance(extra, dict) else None
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return ""


def _clock(epoch) -> str:
    """A reset time as a person reads it, or "" for none."""
    try:
        epoch = float(epoch or 0)
    except (TypeError, ValueError):
        return ""
    if epoch <= 0:
        return ""
    return time.strftime("%a %H:%M", time.localtime(epoch))


def _why_looks_waited(runs, resident) -> str:
    """Why rows waited for a look, out of what the payload already says.

    The row used to send a reader to "the failed runs and the usage limit
    above", and the usage-limit row stands down under `RATE_LIMITED_SHARE`
    of the day's runs — so twelve refused looks (two hours of a look every
    ten minutes, this row's own threshold) produced a row pointing at
    nothing. It names the Resident's own refusals and failures, and what
    the Resident last said (a gate holding its looks says so there), and
    only falls back to the general sentence when the payload holds none.
    """
    by = ((runs or {}).get("by_source") or {}).get("resident") \
        if isinstance(runs, dict) else None
    by = by if isinstance(by, dict) else {}
    limited = int(by.get("rate_limited") or 0)
    failed = sum(int(n or 0) for word, n in by.items()
                 if word in journal.FAILURE_OUTCOMES
                 and isinstance(n, (int, float)))
    said = str((resident or {}).get("last_error") or "").strip() \
        if isinstance(resident, dict) else ""
    parts = []
    if limited:
        parts.append(f"The account's usage limit refused {limited} of "
                     "brAIn's checks in the last day; the rows are checked "
                     "once it lifts.")
    if failed:
        parts.append(f"{failed} of its runs failed.")
    if said:
        parts.append(f"brAIn's checks last said: {said[:140]}.")
    if not parts:
        parts.append("Each check that fails puts its rows back for the next "
                     "one, so this is checks failing or paused, not a row lost.")
    return " ".join(parts)


def _estimated_budget_note(resident, usage) -> str:
    """The sentence a budget hold owes when the budget is a guess, or "".

    When the account's own figures are not being reported the budget is
    brAIn's estimate of its own runs, and a house held its looks for ten
    hours on "the session usage budget is spent" with nothing saying the
    number behind it was an estimate (`budget_state`'s `source`, the
    fallback that is silent being read as the real thing).
    """
    said = str((resident or {}).get("last_error") or "") \
        if isinstance(resident, dict) else ""
    if "budget" not in said or not isinstance(usage, dict):
        return ""
    if usage.get("source") != "estimate":
        return ""
    return ("That budget figure is brAIn's own estimate of its runs, because "
            "the account's real usage figures are not being reported.")


def _rate_limited_row(runs: dict, usage: dict) -> tuple[str, str, str] | None:
    """The fault row for a day the account's usage limit refused a large
    share of brAIn's runs, or None. Pure over the journal summary and the
    usage block the diagnostics payload already carries."""
    if not isinstance(runs, dict):
        return None
    limited = int((runs.get("by_outcome") or {}).get("rate_limited") or 0)
    # Out of the Claude runs, where the summary counts them: a refusal is
    # a run a model was asked for, and the journal's other lines (checks
    # passes, summary rows) are not runs in any sentence a person reads.
    total = int(runs.get("claude_runs") or runs.get("runs") or 0)
    limited = min(limited, total)
    if limited < RATE_LIMITED_MIN or not total:
        return None
    if limited / total < RATE_LIMITED_SHARE:
        return None
    hours = runs.get("hours") or 24
    span = "day" if float(hours) == 24 else f"{hours:g} hours"
    usage = usage if isinstance(usage, dict) else {}
    when: list[str] = []
    resets = _clock(usage.get("resets_at"))
    if resets:
        when.append(f"the session window resets {resets}")
    week = usage.get("week_percent")
    week_resets = _clock(usage.get("week_resets_at"))
    if week_resets and isinstance(week, (int, float)) and week >= 90:
        when.append(f"the weekly window ({week:.0f}% used) resets "
                    f"{week_resets}")
    held = _clock((usage.get("rate_limit") or {}).get("until"))
    detail = ("The account's usage limit is refusing brAIn's runs — this is "
              "the account saying wait, not brAIn failing, and runs resume "
              "by themselves")
    detail += (": " + "; ".join(when) + ".") if when else "."
    if held:
        detail += f" Scheduled cards are paused until {held}."
    detail += (" A cheaper model, a lighter thinking dial or a lower usage "
               "budget in ⚙ spends less of the window.")
    return ("Claude usage limit",
            f"refused {limited} of {total} runs in the last {span}", detail)


# What a snapshot key is, as a person would say what brAIn could not read.
SNAPSHOT_WORDS = {
    "supervisor": "the add-ons and backups",
    "recorder": "the recorder database",
    "zha_devices": "the Zigbee devices",
    "traces": "the automation traces",
    "thermal": "the room temperatures",
    "baselines": "what is normal for each sensor",
    "closures": "the doors and windows",
    "appliances": "the machines' power use",
    "config_entries": "the integrations",
    "updates": "the waiting updates",
    "statistics": "the long-term statistics",
}


# What a failed run means, in words a homeowner reads, and whether anything
# needs doing — keyed on the closed word the run was journaled under. The
# voice pool and the automation listener journal their own codes as the
# row's `error` beside an `error` outcome (`partial`, `empty`, `permission`),
# so the code is read off the error first when it is one of these words.
# "brAIn tries again" is said only where the next run is scheduled anyway;
# a voice turn is somebody's request and is never repeated by brAIn.
RUN_MEANINGS = {
    "partial": ("a voice request started changing something and then broke " +
                "off partway, so the device may or may not have changed",
                "check the device it was about and ask again only if it did " +
                "not change; brAIn does not repeat a request that had begun " +
                "acting, so nothing happens twice"),
    "timeout": ("it ran past its time limit and was stopped, so anything it " +
                "had started may be only partly done",
                "nothing to do unless it keeps happening; a lighter model in " +
                "⚙ › Model & usage helps a long job finish in time"),
    "auth": ("it could not sign in to Claude",
             "press Sign in again in ⚙ › Account"),
    "crash": ("the Claude program stopped unexpectedly before it finished",
              "nothing to do unless it keeps happening, then use Report a " +
              "problem below"),
    "max_turns": ("it reached its step limit before it could answer, so it " +
                  "produced nothing",
                  "nothing to do unless it keeps happening, then use Report " +
                  "a problem below"),
    "unparseable": ("it answered, but not in the shape brAIn asked for, so " +
                    "the answer was set aside",
                    "nothing to do unless it keeps happening, then use " +
                    "Report a problem below"),
    "no_cli": ("the Claude program is missing from the add-on",
               "restart the add-on, which installs it again; if this stays, " +
               "use Report a problem below"),
    "empty": ("it finished without saying anything",
              "nothing to do unless it keeps happening, then use Report a " +
              "problem below"),
    "permission": ("a step it needed was not permitted, so it stopped",
                   "nothing to do unless it keeps happening, then use " +
                   "Report a problem below"),
    "heal_failed": ("an overnight repair did not work",
                    "the card it was for is still on Needs you"),
    "error": ("it stopped with an error",
              "nothing to do unless it keeps happening, then use Report a " +
              "problem below"),
}

# An error text that is a machine word or a bare exit status, not a line the
# CLI wrote — nothing in it a person could read as a reason.
_MACHINE_ERROR_RE = re.compile(
    r"^\s*(?:claude\s+)?(?:exited|exit)\s+-?\d+\s*$|^\s*\w+\s*$", re.I)


def _run_code(outcome: str, error: str) -> str:
    """The word a failed run's meaning is keyed on: the error when it is
    one of the closed codes a caller journals beside `error`, else the
    outcome."""
    word = str(error or "").strip().lower()
    if outcome == "error" and word in RUN_MEANINGS:
        return word
    return outcome if outcome in RUN_MEANINGS else "error"


def _run_said(error: str) -> str:
    """The CLI's own last line, when the row carries one a person can read."""
    text = str(error or "").strip()
    if not text or _MACHINE_ERROR_RE.match(text):
        return ""
    return text[:160]


def _run_meaning(outcome: str, error: str) -> tuple[str, str]:
    """(what happened, what to do) for a failed run, in plain words."""
    code = _run_code(outcome, error)
    meaning, action = RUN_MEANINGS[code]
    if code in ("crash", "error"):
        said = _run_said(error)
        meaning += (f"; Claude's last words were “{said}”" if said
                    else " and gave no reason")
    return meaning, action


def _run_sentence(outcome: str, n: int, when: str, error: str = "") -> str:
    """What a failed background job means for the owner, and what to do."""
    times = (f"{n} times in the last day" if n > 1 else "once in the last day")
    last = f", last at {when}" if when else ""
    meaning, action = _run_meaning(outcome, error)
    return _sentence(f"{meaning} ({times}{last})", action)


def _faults(diag) -> list[dict]:
    if callable(diag):
        try:
            diag = diag()
        except Exception as exc:  # noqa: BLE001
            return [{"where": "diagnostics", "what": "could not be read",
                     "detail": f"{type(exc).__name__}: {exc}"[:200],
                     "title": "Diagnostics",
                     "sentence": "brAIn could not read its own diagnostics. "
                                 "Restart the add-on; if this stays, use "
                                 "Report a problem below.",
                     "technical": f"{type(exc).__name__}: {exc}"[:400]}]
    if not isinstance(diag, dict):
        return []
    out: list[dict] = []
    if diag.get("error") and len(diag) == 1:
        _row(out, "Diagnostics", "could not be read", diag["error"],
             sentence="brAIn could not read its own diagnostics. Restart "
                      "the add-on; if this stays, use Report a problem below.")
        return out

    # The verdict first: it is the one thing derived from everything else,
    # and it names the switch rather than the symptom.
    health = diag.get("health") or {}
    if str(health.get("state") or "ok") != "ok":
        for problem in (health.get("problems") or []):
            # A pending restart has its own row below, with the versions in
            # it; saying it twice is one fact read as two.
            if isinstance(problem, dict) and problem.get("id") not in HEALTH_ROWS_OF_THEIR_OWN:
                _row(out, "Health", problem.get("what"), problem.get("fix"),
                     title="brAIn itself")
        if not (health.get("problems") or []):
            _row(out, "Health", health.get("reason"), health.get("fix"),
                 title="brAIn itself")

    # Runs that failed. The journal is the one place every Claude run, checks
    # pass, baseline build and overnight heal already passes through.
    runs = diag.get("journal") or {}
    failures = [f for f in (runs.get("failures") or [])
                if isinstance(f, dict) and journal.is_failure(f)]
    # One row per distinct failure, counted: the same refusal ten times in
    # ten minutes is one fact, and six identical lines is how the list
    # stops being read. Newest first, so the row says what is true now.
    #
    # And it names what the run was ABOUT when the row says (`_run_subject`)
    # and when it last happened: "Run (card): ended crash" named a kind of
    # run and nothing anybody could go and look at. The subject is in
    # `what` (it is stable per card); the time is in `detail`, because a
    # fingerprint is taken over `where|what` with digits folded and a
    # weekday is not a digit.
    grouped: dict[tuple, list] = {}
    for row in reversed(failures):
        extra = row.get("extra") if isinstance(row.get("extra"), dict) else {}
        stage = extra.get("stage") or ""
        key = (str(row.get("source") or "a run"), str(stage),
               str(row.get("outcome") or "badly"), str(row.get("error") or ""),
               _run_subject(extra))
        grouped.setdefault(key, [key, 0, 0])
        grouped[key][1] += 1
        grouped[key][2] = max(grouped[key][2], int(row.get("ts") or 0))
    distinct = list(grouped.values())
    for (where, stage, outcome, error, subject), n, last in \
            distinct[:FAULTS_PER_KIND]:
        when = _clock(last)
        # The machine half first (the code or the CLI's line, and when), then
        # what it means and whether to do anything: the detail is the body of
        # the issue a house files, and "partial; last at Mon 18:51" said
        # neither. `what` stays the fingerprint and does not carry it.
        meaning, action = _run_meaning(outcome, error)
        detail = "; ".join(part for part in (
            error[:160], f"last at {when}" if when else "") if part)
        detail = (detail.rstrip(".") + ". " if detail else "") \
            + _sentence(meaning, action)
        _row(out, f"Run ({where}{f' · {stage}' if stage else ''})",
             (f"{subject}: " if subject else "") + f"ended {outcome}"
             + (f" ({n} times)" if n > 1 else ""), detail,
             title=plain_words.job_name(where)
             + (f": {subject}" if subject else ""),
             sentence=_run_sentence(outcome, n, when, error))
    if len(distinct) > FAULTS_PER_KIND:
        rest = sum(n for _key, n, _last in distinct[FAULTS_PER_KIND:])
        _row(out, "Runs", f"{rest} more failed runs in the last day",
             "see the journal below", title="Other background jobs",
             sentence=f"{plain_words.plural(rest, 'more job')} did not "
                      "finish in the last day. Nothing to do unless it "
                      "keeps happening.")

    # Runs the account refused. A usage limit is not a failure — it is
    # absent from `FAILURE_OUTCOMES` on purpose, a window that resets, and
    # it must not turn the health verdict `degraded` — but a day where most
    # runs were refused is a day where most of what brAIn was asked to do
    # did not happen, and "no run failed" over 286 refusals in 518 is
    # technically true and useless. So it is a row here, worded as the
    # account saying wait, with when it stops saying it.
    rate_row = _rate_limited_row(runs, diag.get("usage") or {})
    if rate_row:
        _row(out, *rate_row,
             sentence=_sentence(rate_row[1].replace("refused", "The account "
                                                    "refused", 1), rate_row[2]))

    # The integration a version behind the add-on. run.sh deploys new
    # integration files at every start and Home Assistant runs the old ones
    # until it restarts; Repairs said so and nothing here did.
    versions = diag.get("versions") if isinstance(
        diag.get("versions"), dict) else {}
    integ = versions.get("integration") if isinstance(
        versions.get("integration"), dict) else {}
    if integ.get("restart_pending"):
        wanted = integ.get("required") or versions.get("addon")
        wanted = f"v{wanted}" if wanted else "a newer one"
        what = (f"running v{integ['loaded']}; the add-on deployed {wanted}"
                if integ.get("loaded")
                else f"has not loaded {wanted} yet")
        _row(out, "Home Assistant integration", what,
             "Home Assistant goes on running the integration it loaded until "
             "it restarts. Restart Home Assistant (Settings → System → "
             "Restart, or the brAIn entry under Settings → System → Repairs) "
             "to load it.")

    # Authentication, and the usage tracker's own verdict — different
    # questions, and a 403 on the second says nothing about the first.
    auth = diag.get("auth") or {}
    if str(auth.get("state") or "ok") not in ("ok", "unchecked"):
        _row(out, "Claude sign-in", f"the last check said {auth.get('state')}",
             auth.get("error"),
             sentence="brAIn could not confirm its Claude sign-in, so the "
                      "jobs that use Claude may not run. Press Sign in "
                      "again in ⚙ › Account.")
    usage = diag.get("usage") or {}
    limits = usage.get("limits") if isinstance(usage.get("limits"), dict) else {}
    if limits.get("needs_nothing"):
        # A refusal doing its job is not a fault, which is this sweep's own
        # rule and the one it was breaking most often: a credential between
        # refreshes put a row at the top of a report several hours out of
        # every day, under a heading that says what is wrong right now,
        # carrying a detail that says nothing is wrong. `usage_store`
        # decides which codes those are; this reads its answer.
        pass
    elif limits.get("code"):
        _row(out, "Usage figures",
             f"the tracker last answered {limits.get('code')}",
             limits.get("detail"),
             sentence=_sentence("Your account's usage figures are not "
                                "arriving", limits.get("detail")))
    elif usage.get("source") and usage.get("source") != "account":
        _row(out, "Usage figures",
             "the pill is showing brAIn's own estimate, not the account's",
             f"source: {usage.get('source')}",
             sentence="The usage figures are brAIn's own estimate, not your "
                      "account's. Nothing to do; they return when the "
                      "account answers.")

    # Checks that could not look. "I could not look" and "it went away" are
    # different claims, and only the first belongs here.
    #
    # A check skipped because a snapshot key could not be fetched is that
    # key's fault, not the check's: five climate checks skipped on "snapshot
    # is missing thermal" beside "Snapshot (thermal): could not be fetched"
    # is one fact written six times, and the report that prompted this
    # opened with exactly those six rows — plus a seventh from the store —
    # about a house whose one problem was that September nights are not
    # cold enough to fit a heat-loss model to yet. So the checks a missing
    # key took down are NAMED on the key's own row (every fault still
    # findable, which is this sweep's rule) and get no row of their own.
    checks = diag.get("checks") or {}
    snapshot_errors = {str(k): v for k, v in
                       (checks.get("snapshot_errors") or {}).items()}
    ha_down = {k for k, v in snapshot_errors.items()
               if _ha_did_not_answer(v)}
    taken_down: dict[str, list[str]] = {}
    own_skips: list[tuple[str, str]] = []
    for cid, why in sorted((checks.get("skipped") or {}).items()):
        keys = _missing_snapshot_keys(why)
        if keys and all(k in snapshot_errors for k in keys):
            # On the Home Assistant row when it did not answer, else on
            # the first real reader error among its keys.
            home = ("" if not all(k in ha_down for k in keys) else "\0ha")
            home = home or next(k for k in keys if k not in ha_down)
            taken_down.setdefault(home, []).append(cid)
        else:
            own_skips.append((cid, why))
    titles = diag.get("check_titles") if isinstance(
        diag.get("check_titles"), dict) else {}

    def check_name(cid) -> str:
        return str(titles.get(cid) or "") or plain_words.producer_name(
            f"check:{cid}")

    for cid, why in own_skips[:FAULTS_PER_KIND]:
        _row(out, f"Check {cid}", "could not run", why,
             title=f"House check: {check_name(cid)}"
             if cid in titles else check_name(cid),
             sentence="This check could not look at the house on its last "
                      "pass, so it is not watching for this right now. It "
                      "tries again on the next pass.")
    for cid, why in sorted((checks.get("errors") or {}).items())[:FAULTS_PER_KIND]:
        _row(out, f"Check {cid}", "raised while running", why,
             title=f"House check: {check_name(cid)}"
             if cid in titles else check_name(cid),
             sentence="This check broke while it ran, so it is not watching "
                      "for this right now. If it keeps happening, use "
                      "Report a problem below.")
    if checks.get("error"):
        _row(out, "House checks", "the pass itself failed", checks.get("error"),
             sentence="The last pass of house checks failed, so nothing "
                      "was checked. It runs again on its schedule.")
    if ha_down:
        skipped = taken_down.get("\0ha") or []
        first = str(snapshot_errors[sorted(ha_down)[0]] or "")
        detail = (f"{first} — {len(ha_down)} snapshot read"
                  f"{'s' if len(ha_down) != 1 else ''} ("
                  + ", ".join(sorted(ha_down)) + ") failed")
        if skipped:
            detail += (f" and {len(skipped)} check"
                       f"{'s' if len(skipped) != 1 else ''} did not run: "
                       + ", ".join(skipped))
        _row(out, "Home Assistant", "did not answer", detail,
             title="Home Assistant not answering",
             sentence="Home Assistant did not answer brAIn on its last "
                      "pass (it may have been restarting), so nothing "
                      "could be read from it. It tries again on the next "
                      "pass.")
    for key, why in sorted(snapshot_errors.items()):
        if key in ha_down:
            continue
        skipped = taken_down.get(key) or []
        detail = str(why or "")
        if skipped:
            detail = (f"{detail} — so {len(skipped)} check"
                      f"{'s' if len(skipped) != 1 else ''} did not run: "
                      + ", ".join(skipped)).strip(" —")
        _row(out, f"Snapshot ({key})", "could not be fetched", detail,
             title=f"Reading {SNAPSHOT_WORDS.get(key) or plain_words.words_of(key).lower()}",
             sentence=_sentence(
                 f"brAIn could not read "
                 f"{SNAPSHOT_WORDS.get(key) or plain_words.words_of(key).lower()} "
                 "from Home Assistant on its last pass",
                 f"so {plain_words.plural(len(skipped), 'check')} did not "
                 "run" if skipped else "",
                 "It tries again on the next pass"))

    # The measurement stores. A store that measured nothing of what it
    # asked about is the shape the doors-and-windows bug wore for the life
    # of the feature, and nothing anywhere said so.
    for key, label, unit in (("baselines", "Baselines", "sensors"),
                             ("closures", "Doors and windows", "closures"),
                             ("appliances", "Machines", "power sensors"),
                             ("thermal", "Rooms", "rooms")):
        store = diag.get(key)
        if not isinstance(store, dict):
            continue
        if store.get("error") or store.get("reason"):
            why = store.get("error") or store.get("reason")
            # The snapshot row above already carries this sentence when
            # the checks pass could not fetch this store for the same
            # reason: one fact, one row.
            if str(snapshot_errors.get(key) or "") != str(why):
                _row(out, label, "could not be measured", why)
            continue
        asked = store.get("asked")
        measured = store.get("measured")
        if isinstance(asked, int) and asked > 0 and measured == 0:
            _row(out, label, f"measured 0 of {asked} {unit}",
                 "the store is empty, so every check that reads it is "
                 "silent — which looks exactly like a house with nothing "
                 "wrong in it")
        if store.get("stale"):
            _row(out, label, "has gone stale",
                 "the nightly pass has not written it recently")

    # And the one that asks rather than measures. Only its own failure is
    # a fault: a feature that is off, still watching, or simply has
    # nothing it cannot account for is a refusal doing its job, and a
    # section that listed those is one people learn to skim — which is
    # the failure this sweep was written against.
    curious = diag.get("curiosity")
    if isinstance(curious, dict):
        if curious.get("error"):
            _row(out, "Why you did something", "could not be read",
                 curious.get("error"))
        else:
            failed = int((curious.get("counts") or {}).get("failed") or 0)
            if failed:
                _row(out, "Why you did something",
                     f"{failed} asking{'' if failed == 1 else 's'} ended "
                     "without an answer",
                     "the run spent its money and filed nothing; the run "
                     "journal above says what happened to it")

    # The rehearsal and the deep check: both are opt-in and both leave a
    # verdict nothing else reports.
    reh = diag.get("rehearsal") or {}
    if reh.get("ran_at"):
        if not reh.get("cleanup_ok"):
            _row(out, "Rehearsal", "left something behind",
                 "a `brain_test_*` automation, entity or helper is still in "
                 "the house — `brain doctor` names it and `brain doctor "
                 "--sweep` takes it out (⚙ → Diagnostics → Clear up what "
                 "was left). It creates nothing and spends nothing.",
                 sentence="A test run left a test automation or helper in "
                          "the house. Press Delete under Rehearsal in ⚙ › "
                          "Developer; it creates nothing and spends nothing.")
        if reh.get("swept"):
            _row(out, "Rehearsal", "had to clear up after an earlier run",
                 "took out: " + ", ".join(str(x) for x in reh["swept"][:8]))
        counts = reh.get("checks") or {}
        planted = counts.get("planted") or 0
        if planted and (counts.get("found") or 0) < planted:
            _row(out, "Rehearsal",
                 f"the checks found {counts.get('found') or 0} of {planted} "
                 "planted defects",
                 "a check that misses a defect planted on THIS house is the "
                 "thing the rehearsal exists to find")
        if counts.get("extra"):
            _row(out, "Rehearsal",
                 f"{counts['extra']} rows reported that were not planted")
    deep = diag.get("doctor_deep") or {}
    if deep.get("verdict") and deep.get("verdict") != "ok":
        _row(out, "Deep check", f"last run {deep.get('verdict')}",
             f"it stopped at the {deep.get('failed_stage') or 'unknown'} stage",
             title="The full self-test",
             sentence="The last full self-test did not pass. Press Run all "
                      "tests at the top of Diagnostics to see which step.")

    # Notifications: the one failure whose only symptom is silence.
    notify = diag.get("notify") or {}
    failed = notify.get("error") or notify.get("last_error")
    if failed:
        _row(out, "Notifications",
             "the last message brAIn tried to send did not go"
             + (f" ({notify['last_service']})" if notify.get("last_service")
                else ""),
             failed,
             sentence="The last message brAIn sent to your phone did not "
                      "arrive. Check the notification target in ⚙ › "
                      "Notifications.")
    # A row the dispatcher held to a time ("tell me at 7") is waiting by
    # design; only something that should already have left is a fault — an
    # untimed hold outside quiet hours, or a timed one whose time has passed.
    held = int(notify.get("held") or 0)
    dispatch = notify.get("dispatch") if isinstance(notify.get("dispatch"), dict) else {}
    timed = int(dispatch.get("timed_holds") or 0)
    next_at = float(dispatch.get("next_hold_at") or 0)
    stamp = float(diag.get("generated_at") or 0)
    overdue = held > timed or (timed and next_at and stamp and next_at <= stamp)
    if held and overdue and not notify.get("quiet_now"):
        _row(out, "Notifications",
             f"{notify['held']} held and not sent",
             "quiet hours are over, so the flush should have emptied this")
    for key, label in (("rhythm", "Morning brief"), ("weekly", "Weekly report")):
        part = diag.get(key) or {}
        err = part.get("brief_last_error") or part.get("last_error")
        if err:
            _row(out, label, "did not go out", err,
                 sentence=f"The last {label.lower()} did not go out. It "
                          "tries again next time.")

    # Producers the homeowner keeps marking Wrong. This is the Findings tab
    # saying a rule is wrong about this house, which is the whole reason
    # that number is on the screen — and it is a fault in brAIn rather than
    # in the home, which is exactly what a bug report is for.
    findings = diag.get("findings") or {}
    offered = set(findings.get("mute_offers_open") or [])
    for row in (findings.get("scorecard") or []):
        if not isinstance(row, dict):
            continue
        total = int(row.get("total") or 0)
        wrong = int(row.get("wrong") or 0)
        last_wrong = float(row.get("last_wrong_ts") or 0)
        if last_wrong and stamp and stamp - last_wrong > SCORE_RECENT_S:
            continue  # nobody has said it is wrong for a fortnight
        if total >= SCORE_MIN_ENDINGS and wrong > total - wrong:
            # Named by its title where the scorecard carries one, because
            # the id (`check:auto.conflict`) is what nobody recognises; the
            # id rides after it, since this is also a bug report.
            source = str(row.get("source") or "?")
            title = str(row.get("title") or "")
            name = f"{title} ({source})" if title and title != source else source
            friendly = plain_words.producer_name(source, title)
            record = plain_words.record_words(wrong, total)
            detail = ("this rule is firing on a healthy house, which is "
                      "worse than not having it")
            if source in UNMUTABLE_SOURCES:
                # Not a rule, and never mutable: say what was marked wrong
                # and the one thing that does teach it.
                detail = ("these are brAIn's own reports, not a rule, so "
                          "they cannot be muted; a reason given with Ignore "
                          "reaches brAIn's memory as a correction")
                sentence = _sentence(
                    f"{record}: you marked brAIn's own reports wrong more "
                    "often than right",
                    "They come from brAIn itself rather than a rule, so "
                    "they cannot be muted",
                    "When you press Ignore on one, say why in the box: the "
                    "reason reaches brAIn's memory as a correction and its "
                    "next looks read it")
            elif rule_record.qualifies(row):
                # brAIn quiets this one by itself (`rule_record`): its
                # first look is told the record and sets the rule's rows
                # aside unless one carries fresh evidence. A mute is still
                # the person's, and the row says how.
                detail = ("this rule is often wrong about this house; brAIn "
                          "now holds its rows back unless one carries fresh "
                          "evidence, and muting it stays your choice")
                ask = ("brAIn has asked on Needs you whether to stop raising "
                       "these; answer it there to stop it altogether"
                       if source in offered else
                       "To stop it altogether, Ignore one of its cards with "
                       "“Ignore all like this” ticked")
                sentence = _sentence(
                    f"{record}, so brAIn now holds this rule's cards back "
                    "unless one carries fresh, specific evidence", ask)
            elif source in offered:
                sentence = _sentence(
                    f"{record}. brAIn has asked on Needs you whether to "
                    "stop raising these; answer it there")
            else:
                sentence = _sentence(
                    f"{record}, so it is often wrong about this house",
                    "Ignore one of its cards with “Ignore all like this” "
                    "ticked to stop it")
            _row(out, f"Producer {name}",
                 f"ignored {wrong} of {total} times", detail,
                 title=friendly, sentence=sentence,
                 technical=f"{source}: {wrong} wrong, "
                           f"{total - wrong} confirmed",
                 seen_at=last_wrong)

    # Findings nothing has finished looking at. A look that fails leaves its
    # rows on `triaging` or showing "Nothing finished looking at this one",
    # and nothing said how many — a drain that stopped and one a minute from
    # draining read the same from the tab. Past a count and an age: a few
    # rows waiting minutes is the ordinary state of a drain.
    waiting = int(findings.get("waiting_for_look") or 0)
    oldest = int(findings.get("waiting_for_look_oldest_s") or 0)
    if waiting >= WAITING_LOOK_MIN and oldest >= WAITING_LOOK_AFTER_S:
        estimated = _estimated_budget_note(diag.get("resident"),
                                           diag.get("usage"))
        _row(out, "Looks",
             f"{waiting} findings are still waiting for a look",
             f"The oldest has waited {oldest // 3600} h "
             f"{oldest % 3600 // 60} min. "
             + _why_looks_waited(diag.get("journal"), diag.get("resident"))
             + (" " + estimated if estimated else ""),
             title="New findings waiting to be checked",
             sentence=f"brAIn checks each new finding before showing it, and "
                      f"{plain_words.plural(waiting, 'finding has', 'findings have')} "
                      f"waited, the oldest {oldest // 3600} h. They are "
                      "checked as soon as brAIn can run again; nothing to "
                      "do unless this stays for a day."
                      + (" " + estimated if estimated else ""))

    # Refusals a producer carried because nothing on the tab could show
    # them. Only the condition miner's are that: a pattern brAIn can see and
    # will not act on (an automation with no id, one that already stands
    # down then, a protected target) is deliberately not a card, so this is
    # the one place it is said — with each automation and its reason, or the
    # row is a count nobody can act on. A refused one-off is already a row
    # on the tab carrying its reason, and a refused scene design answered
    # the press that asked for it, so both are refusals doing their job and
    # are not faults (counted in the diagnostics, never listed here).
    props = diag.get("proposals") or {}
    cond = props.get("conditions") if isinstance(
        props.get("conditions"), dict) else {}
    refused = [r for r in (cond.get("refused") or [])
               if isinstance(r, (dict, str))] \
        if isinstance(cond.get("refused"), list) else []
    if refused:
        said = []
        for r in refused[:3]:
            if isinstance(r, dict):
                name = str(r.get("automation") or "an automation")[:60]
                why = str(r.get("why") or "no reason recorded")[:120]
                said.append(f"{name}: {why}")
            else:
                said.append(str(r)[:160])
        more = len(refused) - len(said)
        listed = "; ".join(said) + (f"; and {more} more" if more > 0 else "")
        _row(out, "Condition miner", f"refused {len(refused)}", listed,
             title="Automations you keep undoing",
             sentence=_sentence(
                 "brAIn saw you keep undoing "
                 + plain_words.plural(len(refused), "automation")
                 + " and did not suggest a change, because: " + listed,
                 "Each reason says what stands in the way; change that "
                 "automation yourself if you want brAIn to suggest the fix"))

    # The overnight healer: a skip is a refusal doing its job and is NOT a
    # fault; an attempt that failed is.
    for attempt in ((diag.get("healing") or {}).get("attempts") or []):
        if isinstance(attempt, dict) and attempt.get("error"):
            _row(out, "Overnight repair",
                 f"could not {attempt.get('remedy') or 'act'}",
                 attempt.get("error"),
                 sentence="An overnight repair did not work. The card it "
                          "was for is still on Needs you.")

    # Answers given in Home Assistant that were not applied are NOT a
    # fault: each is a request naming a finding already gone (an app still
    # holding last week's list), a pass already running, or a suggestion
    # already answered — a race or a refusal doing its job. The count
    # stays in the diagnostics payload and each one is logged with why.

    # And the roll-call — read against the options, never raw. A daemon
    # whose option is off was not asked for, and the assist channel is one
    # JOB with two implementations (`assist_fast_mode` decides which), so
    # the classic listener is CORRECTLY absent on a house running the
    # worker pool. Read raw this opened with `not running: assist_listener`
    # on every fast-mode install, softened by a sentence sending the reader
    # back up to a verdict that had deliberately not mentioned it — which
    # is "a refusal doing its job is not a fault" broken by the one
    # function whose docstring states it.
    #
    # `health.expected_daemons` is asked rather than answered again
    # here:
    # this module is the INVENTORY and `health` is the VERDICT, and they
    # may differ on how loud a thing is without ever differing on whether
    # it was wanted.
    daemons = diag.get("daemons") or {}
    options = diag.get("options") or {}
    wanted = health_rules.expected_daemons(options)
    down = sorted(name for name, row in daemons.items()
                  if isinstance(row, dict) and not row.get("running")
                  and name in wanted)
    if down:
        _row(out, "Daemons", "not running: " + ", ".join(down),
             "each of these was asked for by an option that is on — the "
             "health verdict above says which of them stops brAIn working",
             title="Background jobs",
             sentence=_sentence(
                 "Not running: " + ", ".join(dict.fromkeys(
                     plain_words.daemon_name(d) for d in down)),
                 "Restart the add-on to start them again"))

    if len(out) > MAX_FAULTS:
        extra = len(out) - MAX_FAULTS
        out = out[:MAX_FAULTS]
        _row(out, "This list", f"{extra} more not shown",
             "the full diagnostics below carry them",
             sentence=f"{plain_words.plural(extra, 'more thing')} not shown "
                      "here. Report a problem below carries them all.")
    return out


def faults_text(rows: list[dict]) -> str:
    """The section as a person reads it, or the sentence for an empty one."""
    if not rows:
        return ("Nothing. Every check ran, every daemon is up, no run failed "
                "in the last day and the health verdict is ok.")
    lines = []
    for row in rows:
        lines.append(f"* {row.get('where', '?')}: {row.get('what', '')}")
        if row.get("detail"):
            lines.append(f"    {row['detail']}")
    return "\n".join(lines)


def _kv(row: dict) -> str:
    out = []
    for k, v in (row or {}).items():
        if isinstance(v, dict):
            v = json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)
        out.append(f"{k}={v}")
    return "\n".join(out) if out else "(none)"


def coverage_text(diagnostics) -> str:
    """The coverage lines out of a diagnostics payload, one per area
    (`checks.coverage.summary`). Never raises."""
    try:
        cov = diagnostics.get("coverage") if isinstance(diagnostics, dict) else None
        lines = [str(x) for x in ((cov or {}).get("lines") or []) if x]
    except Exception:  # noqa: BLE001 — a section, not the report
        lines = []
    return "\n".join(lines) if lines else "(not recorded yet)"


def compose(kind: str, headline: str, what: str, look: str, *, now: float,
            run: dict | None, health: dict | None, extra_text: str,
            diagnostics, log_text: str) -> str:
    # Resolved once. `diagnostics` arrives as a dict or a callable (this
    # module must not import `server`), and two sections reading it would
    # otherwise build the whole payload twice — and could disagree, since
    # it is derived from a house that is still moving.
    if callable(diagnostics):
        try:
            diagnostics = diagnostics()
        except Exception as exc:  # noqa: BLE001 — a section, not the report
            diagnostics = {"error": f"diagnostics unavailable: {exc}"}
    stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
    version = os.environ.get("ADDON_VERSION", "dev")
    parts = [
        f"{stamp} · brAIn {version} · {headline}",
        "",
        "What happened:",
        str(what or "").strip() or "(no detail)",
        "",
        "Where to look:",
        str(look or "").strip() or "(no advice recorded)",
        "",
    ]
    if run:
        parts += ["--- run ---", _kv(run), ""]
    if health:
        parts += ["--- health ---",
                  f"{health.get('prev', '?')} → {health.get('new', '?')}: "
                  f"{health.get('reason', '')}".rstrip(": "),
                  ""]
        if health.get("fix"):
            parts += [str(health["fix"]), ""]
    # Everything wrong right now, ABOVE the log and the JSON. The report
    # this replaced opened with "Nothing failed to produce this file" and
    # then six hundred lines nobody could search — every fault on the
    # install that prompted it was in that file and none was findable.
    parts += ["--- what is wrong right now ---",
              faults_text(faults(diagnostics)), ""]
    # And what was looked at: one line per part of Home Assistant, so a
    # report says "checked, nothing wrong" or "could not look" for each
    # rather than leaving an empty fault list to stand for both.
    parts += ["--- what brAIn looked at ---", coverage_text(diagnostics), ""]
    parts += [f"--- add-on log, last {LOG_LINES} lines ---", log_text, ""]
    parts += ["--- diagnostics (abridged) ---",
              json.dumps(abridge(diagnostics), indent=1, ensure_ascii=False,
                         default=str),
              ""]
    if extra_text:
        parts += [str(extra_text)[:MAX_EXTRA_CHARS], ""]
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The writer
# ---------------------------------------------------------------------------

def _unique_name(stem: str) -> str:
    name = f"{stem}.txt"
    n = 2
    while (REPORTS_DIR / name).exists():
        name = f"{stem}-{n}.txt"
        n += 1
    return name


def _prune(keep: str, index: dict) -> None:
    """Oldest first, never the file just written. The index drops the
    entries of anything pruned, so a fingerprint cannot point at a file
    that is gone and a repeat then appends to nothing."""
    files = sorted(
        (p for p in REPORTS_DIR.glob("*.txt") if p.is_file()),
        key=lambda p: (p.name, p.stat().st_mtime))
    excess = len(files) - MAX_REPORTS
    for p in files:
        if excess <= 0:
            break
        if p.name == keep:
            continue
        try:
            p.unlink()
        except OSError as exc:
            log.debug("could not prune %s: %s", p, exc)
            continue
        excess -= 1
        for fp in [k for k, v in index.items()
                   if isinstance(v, dict) and v.get("name") == p.name]:
            index.pop(fp, None)


def file_incident(kind: str, headline: str, what: str, look: str, *,
                  run: dict | None = None, health: dict | None = None,
                  extra_text: str = "", diagnostics=None, dedup: bool = True,
                  now: float | None = None) -> str | None:
    """Write one report, or add a line to the one this problem already has.

    Returns the file name, or None when nothing was written — the
    directory is not available, or something went wrong, which is logged
    and never raised: this is called from accounting code.
    """
    try:
        return _file_incident(kind, headline, what, look, run=run, health=health,
                              extra_text=extra_text, diagnostics=diagnostics,
                              dedup=dedup, now=now)
    except Exception as exc:  # noqa: BLE001 — never out of accounting
        log.warning("could not write a problem report (%s): %s", kind, exc)
        return None


def _file_incident(kind, headline, what, look, *, run, health, extra_text,
                   diagnostics, dedup, now) -> str | None:
    if not available():
        return None
    now = time.time() if now is None else float(now)
    kind = re.sub(r"[^a-z0-9_-]", "", str(kind or "problem").lower())[:24] or "problem"
    run = dict(run) if run else None
    source = (run or {}).get("source") or (health or {}).get("source") or kind
    outcome = (run or {}).get("outcome") or (health or {}).get("new") or kind
    error = (run or {}).get("error") or (health or {}).get("reason") or headline
    fp = fingerprint(kind, source, outcome, error) if dedup else fingerprint(
        kind, source, outcome, f"{error}|{now}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    index = _load_index()
    seen = index.get(fp)
    if (dedup and isinstance(seen, dict)
            and now - float(seen.get("ts") or 0) < DEDUP_HOURS * 3600):
        path = _safe_path(seen.get("name", ""))
        if path is not None and path.exists():
            stamp = time.strftime("%H:%M", time.localtime(now))
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"seen again at {stamp}\n")
            seen["count"] = int(seen.get("count") or 1) + 1
            seen["last"] = int(now)
            index[fp] = seen
            _save_index(index)
            return seen["name"]

    log_text = fetch_addon_log()
    text = redact(compose(kind, headline, what, look, now=now, run=run,
                          health=health, extra_text=extra_text,
                          diagnostics=diagnostics, log_text=log_text))
    name = _unique_name(time.strftime("%Y-%m-%d-%H%M", time.localtime(now)) + f"-{kind}")
    atomic_write.write_text(REPORTS_DIR / name, text)
    index[fp] = {"name": name, "ts": int(now), "last": int(now), "count": 1,
                 "kind": kind, "headline": redact(str(headline))[:160]}
    _prune(name, index)
    _save_index(index)
    return name


# ---------------------------------------------------------------------------
# Reading back
# ---------------------------------------------------------------------------

def _name_ts(name: str) -> int:
    try:
        return int(time.mktime(time.strptime(name[:15], "%Y-%m-%d-%H%M")))
    except ValueError:
        return 0


def list_reports() -> list[dict]:
    """Newest first. The headline is read off the file's own first line,
    so a report written by the shell fallback lists like any other."""
    if not REPORTS_DIR.is_dir():
        return []
    by_name = {v.get("name"): v for v in _load_index().values() if isinstance(v, dict)}
    out = []
    for p in REPORTS_DIR.glob("*.txt"):
        if not p.is_file():
            continue
        try:
            with p.open("r", encoding="utf-8", errors="replace") as fh:
                first = fh.readline().strip()
            size = p.stat().st_size
        except OSError:
            continue
        head = first.split(" · ", 2)
        meta = by_name.get(p.name) or {}
        rest = p.name[16:-4] if len(p.name) > 20 else p.name[:-4]
        kind = re.sub(r"-\d+$", "", rest) or meta.get("kind") or "problem"
        out.append({
            "name": p.name,
            "ts": _name_ts(p.name) or int(p.stat().st_mtime),
            "kind": kind,
            "headline": (head[2] if len(head) == 3 else first)[:160],
            "count": int(meta.get("count") or 1),
            "bytes": size,
        })
    out.sort(key=lambda r: (r["ts"], r["name"]), reverse=True)
    return out


# Reports somebody ASKED for — ⚙ → "Copy for a bug report", `brain report`
# and its shell fallback all write `kind: manual`. They are files in the
# same folder and nothing failed to produce them, so they are never counted
# as problems: two of them read "2 problems since yesterday" on a house
# whose one problem was somebody asking for a report.
REQUESTED_KINDS = frozenset({"manual"})


def problems_since(cutoff: float) -> int:
    """How many problem reports were written since ``cutoff``, leaving out
    the ones somebody asked for."""
    return len([r for r in list_reports()
                if (r.get("ts") or 0) >= cutoff
                and r.get("kind") not in REQUESTED_KINDS])


def read_report(name: str) -> str | None:
    path = _safe_path(name)
    if path is None or not path.is_file():
        return None
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def delete_report(name: str) -> bool:
    path = _safe_path(name)
    if path is None or not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    index = _load_index()
    for fp in [k for k, v in index.items()
               if isinstance(v, dict) and v.get("name") == path.name]:
        index.pop(fp, None)
    _save_index(index)
    return True


def combined(names: list[str]) -> str:
    """Several reports as one text, for one paste."""
    parts = []
    for name in names or []:
        text = read_report(name)
        if text is None:
            continue
        parts.append(f"==== {name} ====\n{text.rstrip()}\n")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# The producers
# ---------------------------------------------------------------------------

def _timeout_sentence(source: str) -> str:
    opt = TIMEOUT_OPTION.get(source, "")
    if not opt:
        return ("The run hit its deadline. Its budget is fixed for this source; "
                "the add-on log has the last thing it did.")
    if opt.startswith("the "):
        return f"The run hit {opt}. The add-on log has the last thing it did."
    return (f"The run hit its deadline. Raise `{opt}` on the Configuration tab "
            "if the house is large or the model is slow, and read the add-on "
            "log for the last thing it did.")


def describe_run(row: dict) -> tuple[str, str, str]:
    """(headline, what happened, where to look) for a failed journal row."""
    source = str(row.get("source") or "?")
    outcome = str(row.get("outcome") or "error")
    err = str(row.get("error") or "").strip()
    first = err.splitlines()[0] if err else ""
    headline = f"{source} run ended {outcome}" + (f": {first[:80]}" if first else "")
    what = {
        "timeout": f"A {source} run was killed at its deadline"
                   + (f" after {row['duration_s']}s" if row.get("duration_s") else "") + ".",
        "crash": f"The claude process behind a {source} run exited without an answer.",
        "unparseable": f"A {source} run answered, and the answer was not the shape asked for.",
        "auth": f"The credential was refused on a {source} run.",
        "no_cli": "The claude binary could not be found.",
        "max_turns": f"A {source} run stopped at its turn cap before finishing.",
        "heal_failed": "An overnight remediation made its call and the call failed.",
        "error": f"A {source} run failed.",
    }.get(outcome, f"A {source} run ended {outcome}.")
    if err:
        what += f"\nThe error was: {err[:300]}"
    look = {
        "timeout": _timeout_sentence(source),
        "crash": "The add-on log below carries the CLI's own last line. If it "
                 "mentions the credential, sign in again under ⚙.",
        "unparseable": "Usually a model that wrote prose around its JSON. Regenerate "
                       "the card; if it repeats, pick a larger model under ⚙ → Model.",
        "auth": "Sign in again under ⚙ → Claude account. If the terminal still "
                "works, the panel is reading a different store — `ha login --status` "
                "names all three.",
        "no_cli": "Restart the add-on; run.sh installs the CLI at startup. If it "
                  "persists, the add-on log names the install error.",
        "max_turns": f"Raise the turn cap for this source, or narrow what it was "
                     f"asked (a {source} run re-sends its conversation every turn).",
        "heal_failed": "The finding stays on the Findings tab; the next checks pass "
                       "says whether the house fixed itself. Press Fix it to try "
                       "with Claude watching.",
        "error": "The add-on log below is the first place; `brain doctor --deep` "
                 "walks every face if it is not obvious.",
    }.get(outcome, "The add-on log below.")
    return headline, what, look


def file_run_failure(row: dict, diagnostics=None, now: float | None = None) -> str | None:
    """One report for a failed journal row. The row IS the run section, and
    its own ``ts`` is the report's time — the file is about when the run
    failed, not about when the reports thread got to it."""
    if not isinstance(row, dict) or row.get("outcome") not in FAILURE_OUTCOMES:
        return None
    if now is None and isinstance(row.get("ts"), (int, float)) and row["ts"] > 0:
        now = float(row["ts"])
    headline, what, look = describe_run(row)
    return file_incident("run", headline, what, look, run=row,
                         diagnostics=diagnostics, now=now)


def health_transition(prev: str, new: str, reason: str, diagnostics=None,
                      fix: str = "", now: float | None = None) -> str | None:
    """The verdict moved off `ok`. One report, naming both states."""
    headline = f"health went {prev} → {new}: {reason}"[:200]
    what = (f"brAIn's own health verdict changed from {prev} to {new}. "
            f"The reason it gives: {reason}")
    look = fix or ("⚙ → Diagnostics shows the verdict and everything underneath "
                   "it; `brain doctor` walks the same list from the terminal.")
    return file_incident("health", headline, what, look,
                         health={"prev": prev, "new": new, "reason": reason,
                                 "fix": fix, "source": "health"},
                         diagnostics=diagnostics, now=now)


def tracks_health() -> bool:
    """Whether the last-verdict record can be kept — /data exists."""
    return HEALTH_LAST_FILE.parent.is_dir()


def _read_last_health() -> str:
    try:
        data = json.loads(HEALTH_LAST_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "ok"
    state = (data or {}).get("state") if isinstance(data, dict) else None
    return state if state in ("ok", "degraded", "failed") else "ok"


def note_health(health: dict, diagnostics=None, now: float | None = None) -> str | None:
    """Compare this verdict with the last one and file on a change for the
    worse. Returning to `ok` only updates the record. Never raises.

    A missing record reads as `ok`: the first verdict after an upgrade
    that is not ok is news, and a fresh install that starts degraded is
    exactly the case somebody would want a file about.
    """
    try:
        new = str((health or {}).get("state") or "")
        if new not in ("ok", "degraded", "failed") or not tracks_health():
            return None
        # A restart Home Assistant owes after every add-on update is the
        # verdict's to say and not a problem file's: recorded as ok, so the
        # update files nothing and a real fault beside it still reads as
        # the change it is.
        ids = {p.get("id") for p in (health.get("problems") or [])
               if isinstance(p, dict)}
        if ids and ids <= NOT_INCIDENTS:
            new = "ok"
        prev = _read_last_health()
        now = time.time() if now is None else float(now)
        try:
            atomic_write.write_json(HEALTH_LAST_FILE, {
                "state": new, "reason": str(health.get("reason") or "")[:300],
                "at": int(now)})
        except OSError as exc:
            log.debug("could not record the health verdict: %s", exc)
        if new == prev or new == "ok":
            return None
        return health_transition(prev, new, str(health.get("reason") or ""),
                                 diagnostics=diagnostics,
                                 fix=str(health.get("fix") or ""), now=now)
    except Exception as exc:  # noqa: BLE001 — never out of publish
        log.warning("could not note the health verdict: %s", exc)
        return None


def notify_failure(service: str, error: str, context: str = "",
                   diagnostics=None, now: float | None = None) -> str | None:
    """A notification that did not arrive. The one failure whose only
    other symptom is a phone that stayed quiet."""
    err = str(error or "").strip()
    what = (f"A notification via {service or '(no service)'} could not be sent"
            + (f" ({context})" if context else "") + "."
            + (f"\nHome Assistant said: {err[:300]}" if err else ""))
    look = ("Check `findings_notify_service` on the Configuration tab names a "
            "service that exists (Developer tools → Actions lists them), and "
            "that the device it targets is still signed in to the companion app.")
    return file_incident("notify", f"notification via {service or '?'} failed",
                         what, look,
                         run={"source": str(service or "notify")[:64],
                              "outcome": "notify", "error": err[:300],
                              "context": context[:80]},
                         diagnostics=diagnostics, now=now)
