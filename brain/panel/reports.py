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
import journal

log = logging.getLogger("brain.reports")

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

# The journal outcomes that are a problem. `ok` with `extra.landed` is a run
# that worked; `fallback` is a quieter path that still produced a card;
# `applied`/`healed` are successes; `heal_skipped` and `denied` are refusals
# doing their job, and a refusal is not a fault.
FAILURE_OUTCOMES = frozenset({
    "timeout", "crash", "unparseable", "auth", "no_cli", "error",
    "heal_failed", "max_turns",
})

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
                 "detail": f"{type(exc).__name__}: {exc}"[:200]}]


def _row(out: list, where: str, what: str, detail: str = "") -> None:
    if what:
        out.append({"where": where, "what": str(what)[:200],
                    "detail": str(detail or "")[:400]})


def _faults(diag) -> list[dict]:
    if callable(diag):
        try:
            diag = diag()
        except Exception as exc:  # noqa: BLE001
            return [{"where": "diagnostics", "what": "could not be read",
                     "detail": f"{type(exc).__name__}: {exc}"[:200]}]
    if not isinstance(diag, dict):
        return []
    out: list[dict] = []
    if diag.get("error") and len(diag) == 1:
        _row(out, "Diagnostics", "could not be read", diag["error"])
        return out

    # The verdict first: it is the one thing derived from everything else,
    # and it names the switch rather than the symptom.
    health = diag.get("health") or {}
    if str(health.get("state") or "ok") != "ok":
        for problem in (health.get("problems") or []):
            if isinstance(problem, dict):
                _row(out, "Health", problem.get("what"), problem.get("fix"))
        if not (health.get("problems") or []):
            _row(out, "Health", health.get("reason"), health.get("fix"))

    # Runs that failed. The journal is the one place every Claude run, checks
    # pass, baseline build and overnight heal already passes through.
    journal = diag.get("journal") or {}
    failures = [f for f in (journal.get("failures") or []) if isinstance(f, dict)]
    for row in failures[:FAULTS_PER_KIND]:
        stage = (row.get("extra") or {}).get("stage") if isinstance(
            row.get("extra"), dict) else ""
        where = str(row.get("source") or "a run")
        _row(out, f"Run ({where}{f' · {stage}' if stage else ''})",
             f"ended {row.get('outcome') or 'badly'}", row.get("error"))
    if len(failures) > FAULTS_PER_KIND:
        _row(out, "Runs", f"{len(failures) - FAULTS_PER_KIND} more failed runs "
                          "in the last day", "see the journal below")

    # Authentication, and the usage tracker's own verdict — different
    # questions, and a 403 on the second says nothing about the first.
    auth = diag.get("auth") or {}
    if str(auth.get("state") or "ok") not in ("ok", "unchecked"):
        _row(out, "Claude sign-in", f"the last check said {auth.get('state')}",
             auth.get("error"))
    usage = diag.get("usage") or {}
    limits = usage.get("limits") if isinstance(usage.get("limits"), dict) else {}
    if limits.get("code"):
        _row(out, "Usage figures",
             f"the tracker last answered {limits.get('code')}",
             limits.get("detail"))
    elif usage.get("source") and usage.get("source") != "account":
        _row(out, "Usage figures",
             "the pill is showing brAIn's own estimate, not the account's",
             f"source: {usage.get('source')}")

    # Checks that could not look. "I could not look" and "it went away" are
    # different claims, and only the first belongs here.
    checks = diag.get("checks") or {}
    for cid, why in sorted((checks.get("skipped") or {}).items())[:FAULTS_PER_KIND]:
        _row(out, f"Check {cid}", "could not run", why)
    for cid, why in sorted((checks.get("errors") or {}).items())[:FAULTS_PER_KIND]:
        _row(out, f"Check {cid}", "raised while running", why)
    if checks.get("error"):
        _row(out, "House checks", "the pass itself failed", checks.get("error"))
    for key, why in sorted((checks.get("snapshot_errors") or {}).items()):
        _row(out, f"Snapshot ({key})", "could not be fetched", why)

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
            _row(out, label, "could not be measured",
                 store.get("error") or store.get("reason"))
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

    # The rehearsal and the deep check: both are opt-in and both leave a
    # verdict nothing else reports.
    reh = diag.get("rehearsal") or {}
    if reh.get("ran_at"):
        if not reh.get("cleanup_ok"):
            _row(out, "Rehearsal", "left something behind",
                 "a `brain_test_*` automation, entity or helper is still in "
                 "the house — `brain doctor` names it")
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
             f"it stopped at the {deep.get('failed_stage') or 'unknown'} stage")

    # Notifications: the one failure whose only symptom is silence.
    notify = diag.get("notify") or {}
    failed = notify.get("error") or notify.get("last_error")
    if failed:
        _row(out, "Notifications",
             "the last message brAIn tried to send did not go"
             + (f" ({notify['last_service']})" if notify.get("last_service")
                else ""),
             failed)
    if (notify.get("held") or 0) and not notify.get("quiet_now"):
        _row(out, "Notifications",
             f"{notify['held']} held and not sent",
             "quiet hours are over, so the flush should have emptied this")
    for key, label in (("rhythm", "Morning brief"), ("weekly", "Weekly report")):
        part = diag.get(key) or {}
        err = part.get("brief_last_error") or part.get("last_error")
        if err:
            _row(out, label, "did not go out", err)

    # Producers the homeowner keeps marking Wrong. This is the Findings tab
    # saying a rule is wrong about this house, which is the whole reason
    # that number is on the screen — and it is a fault in brAIn rather than
    # in the home, which is exactly what a bug report is for.
    findings = diag.get("findings") or {}
    for row in (findings.get("scorecard") or []):
        if not isinstance(row, dict):
            continue
        total = int(row.get("total") or 0)
        wrong = int(row.get("wrong") or 0)
        if total >= SCORE_MIN_ENDINGS and wrong > total - wrong:
            _row(out, f"Producer {row.get('source') or '?'}",
                 f"marked Wrong {wrong} of {total} times",
                 "this rule is firing on a healthy house, which is worse "
                 "than not having it")

    # Refusals a producer carried because nothing on the tab could show
    # them. These are not cards anybody can answer.
    props = diag.get("proposals") or {}
    for key, label in (("conditions", "Condition miner"),
                       ("intents", "One-off intents"),
                       ("scenes", "Scene designer")):
        part = props.get(key) if isinstance(props.get(key), dict) else {}
        refused = part.get("refused")
        if isinstance(refused, list) and refused:
            _row(out, label, f"refused {len(refused)}",
                 "; ".join(str(r)[:80] for r in refused[:3]))
        elif isinstance(refused, int) and refused:
            _row(out, label, f"refused {refused}")

    # The overnight healer: a skip is a refusal doing its job and is NOT a
    # fault; an attempt that failed is.
    for attempt in ((diag.get("healing") or {}).get("attempts") or []):
        if isinstance(attempt, dict) and attempt.get("error"):
            _row(out, "Overnight repair",
                 f"could not {attempt.get('remedy') or 'act'}",
                 attempt.get("error"))

    # Answers given in Home Assistant that never reached the store.
    reqs = diag.get("finding_requests") or {}
    if reqs.get("missed"):
        _row(out, "Answers from Home Assistant",
             f"{reqs['missed']} could not be applied",
             "a tick in the To-do app or a notification button that named a "
             "finding already gone")

    # And the roll-call, read raw. `health` interprets it against the
    # options and is the right place for a verdict; this is here because a
    # bug report has to carry the fact as well as the interpretation.
    down = sorted(name for name, row in (diag.get("daemons") or {}).items()
                  if isinstance(row, dict) and not row.get("running"))
    if down:
        _row(out, "Daemons", "not running: " + ", ".join(down),
             "some of these are optional — the health verdict above says "
             "which of them matters")

    if len(out) > MAX_FAULTS:
        extra = len(out) - MAX_FAULTS
        out = out[:MAX_FAULTS]
        _row(out, "This list", f"{extra} more not shown",
             "the full diagnostics below carry them")
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
