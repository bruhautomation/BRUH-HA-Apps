"""The queue from this house's fault list to a GitHub issue.

One fault, one issue, for as long as the fault exists. The rows are
`reports.faults` — the same sweep that opens every problem report and
⚙ › Diagnostics — so "what is wrong with this install" has one answer
whether a person or the loop is asking.

Four rules.

**A fingerprint is the fault, not the sentence.** `where` plus `what`
with every digit folded, so "3 of 12 runs failed" and "4 of 13 runs
failed" are one issue, and the number lives in the body where it can
move. Computed over the RAW text, never the aliased one, so a rename on
the house cannot split one fault into two issues.

**Nothing leaves without a press until review is turned off.** A new
fingerprint lands `pending`; Send moves it on, Discard ends it for good
(a discarded fingerprint is never queued again, which is the whole of
what the press means). The preview is the composed body, built by the
same function the sender calls, so what was read is what is sent.

**After the first send, the loop only ever says WHEN.** "Still happening
on 2.17.1", "not seen since Tuesday", "back again" — dates, versions and
counts, nothing from the house — so those follow-ups go without a press
even in review mode. They are what lets an issue close itself: a fix
that shipped is a fingerprint that stopped, said on the issue it fixed.

**It never raises.** It runs on the checks loop's tick, and a report
about a fault that took down the loop reporting it is the worse outcome
— `reports.file_incident`'s rule, one module over.

**The cloud's verdict comes home, and noise stops being filed.** The
routine closes every issue with a label saying what it was
(`devloop:fixed`, `declined`, `not-brain`, `duplicate`). Once an hour the
send pass reads them back with the listing call `find_issue` already
makes, and keeps the verdict beside the report (`verdicts.json`, apart
from the queue so a lost queue does not forget it). A report the cloud
called noise is never filed again by a stream that writes its own
sentences (`STAND_DOWN_STREAMS`): not under its fingerprint, and for the
Claude streams not under the part of brAIn it names either, since a run
rewords its sentence every time. A stream whose last `SLOW_WINDOW`
resolved reports were mostly noise runs half as often, says so, and can
be put back by a press. `fixed` is never noise, and a fixed fault coming
back is still *Back again*. A noise verdict also keeps what was filed and
the first line of the comment it was closed with, and the next Claude run
is shown those (`rejected`), so it learns why as well as what. Each new
report says how much it matters
(`impact`), and the most impactful are filed first under the day's cap.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import logging
import re
import threading
import time

import atomic_write
import reports
from textclip import clip

from . import STREAMS, data_dir, enabled, load_settings, read_token, stream_on
from . import github
from .aliases import Aliases
from .siblings import PRODUCTS, spec_by_name

log = logging.getLogger("brain.devloop")

# How often the fault list is swept into the queue. Hourly: the faults
# change over hours, and the diagnostics payload is not free to build.
SWEEP_INTERVAL_S = 3600
# At most this many new issues per pass, so a house that has just broken
# in twelve places does not file twelve issues in one second; the rest
# go on the next pass.
MAX_SENDS_PER_PASS = 5
# How long a sent fingerprint has to be absent before the issue is told it
# stopped. Two days, because a checks pass that skipped a check is not
# the fault going away and the next pass may bring it back.
CLEAR_AFTER_S = 48 * 3600
# A closed report is reopened only when its fault has gone on being seen
# for this long on a release the house installed AFTER the issue closed.
# The old rule reopened on any version change, and every update re-stamps
# every row a window still holds — a 24-hour journal, an all-time count, a
# Home Assistant restart that is owed after each install — so each update
# reopened every closed report at once, none of them new evidence.
REOPEN_AFTER_S = 24 * 3600
MAX_QUEUE = 60
MAX_ABRIDGED = 20_000
FP_RE = re.compile(r"^[0-9a-f]{16}$")
# Rows that are about the fault list itself rather than a fault.
SKIP_WHERE = frozenset({"This list"})
STATES = ("pending", "ready", "sent", "discarded", "retired")

# How often the verdicts the cloud left on filed issues are read back: the
# hourly sweep's clock, with the call the marker search already makes.
VERDICT_INTERVAL_S = SWEEP_INTERVAL_S
# Issues older than the newest three pages of the listing are asked for
# one at a time, at most this many a pass.
VERDICT_GETS_PER_PASS = 10
# Why a report was closed as noise is the first line of its closing
# comment, read once per report: at most this many a pass, given up on
# (the label standing in) after this many failed reads, and cut to this.
REASONS_PER_PASS = 5
REASON_TRIES = 3
REASON_CHARS = 200
# The version a fix shipped in, read off the cloud's closing comment
# ("Fixed in brAIn 3.1.0 (…)", the skill's own wording). It is the one fact
# that tells "the fix is here and held" from "the fix has not arrived":
# a fault still seen on a release OLDER than the fix is not evidence
# against the fix, and a house with auto-update off used to reopen every
# fixed report a day after its next unrelated update.
FIXED_IN_RE = re.compile(
    r"\bFixed in (brAIn|" + "|".join(re.escape(p) for p in PRODUCTS)
    + r") v?(\d+\.\d+\.\d+)")
FIXED_IN_PER_PASS = 10
# How long a fixed report waits for the house to update before the wait is
# said out loud (in the scorecard body and ⚙), rather than read as silence.
UPDATE_WAIT_S = 7 * 86400
# Label → verdict, first match wins. `fixed` leads: a fix is never noise.
VERDICT_LABELS = (("devloop:fixed", "fixed"), ("devloop:duplicate", "duplicate"),
                  ("devloop:not-brain", "not_brain"), ("devloop:declined", "declined"))
VERDICTS = ("fixed", "declined", "not_brain", "duplicate", "closed")
NOISE = frozenset({"declined", "not_brain", "duplicate"})
# The streams that write their own sentences, and so stand down on a
# report the cloud called noise. A fault, a wrong or a scorecard row is
# brAIn's own measurement and keeps its follow-ups whatever the label.
# A "What do you want to fix?" report is the owner asking, and is never on
# the list: a request declined once and asked again is the owner saying it
# still matters, and a pane named in a declined report must not swallow the
# next, different request about the same pane (it did, for Settings).
STAND_DOWN_STREAMS = frozenset({"gaps", "ideas", "design", "unmet"})
CLAUDE_STREAMS = frozenset({"gaps", "ideas", "design", "look"})
# A stream is slowed when at least SLOW_NOISE_SHARE of its last
# SLOW_WINDOW resolved reports were noise: its interval doubles, capped at
# SLOW_MAX_HOURS (or its own interval, if that is already longer).
SLOW_WINDOW = 8
SLOW_NOISE_SHARE = 0.75
SLOW_FACTOR = 2
SLOW_MAX_HOURS = 336
MAX_RESOLVED = 400
MAX_STOOD_DOWN = 400
MAX_DAYS = 60
# What a row may say about its own impact, all counts.
IMPACT_KEYS = ("count", "conversations", "days", "rows", "runs",
               "wrong", "confirmed", "endings")

_GITHUB_TOKEN_RE = re.compile(r"\b(?:github_pat_[A-Za-z0-9_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})\b")
_LOCK = threading.Lock()
STATE: dict = {"last_sweep": 0.0, "last_send": 0.0, "error": "", "running": False}


def _queue_file():
    return data_dir() / "queue.json"


def _load() -> dict:
    try:
        data = json.loads(_queue_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"items": {}}
    if not isinstance(data, dict) or not isinstance(data.get("items"), dict):
        return {"items": {}}
    return data


def _save(data: dict) -> None:
    atomic_write.write_json(_queue_file(), data, mode=0o600)


def _verdict_file():
    return data_dir() / "verdicts.json"


def _vload() -> dict:
    """What the cloud said about filed reports. Kept apart from the queue:
    a reinstall that loses the queue must not forget what was declined."""
    try:
        data = json.loads(_verdict_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    for key in ("resolved", "stood_down", "filed", "slowed", "unslowed"):
        if not isinstance(data.get(key), dict):
            data[key] = {}
    return data


def _vsave(data: dict) -> None:
    for key, cap in (("resolved", MAX_RESOLVED), ("stood_down", MAX_STOOD_DOWN)):
        rows = data.get(key) or {}
        if len(rows) > cap:
            for k in sorted(rows, key=lambda k: float(rows[k].get("at") or 0)
                            )[:len(rows) - cap]:
                rows.pop(k, None)
    atomic_write.write_json(_verdict_file(), data, mode=0o600)


def verdict_of(issue: dict) -> str:
    """``open`` for an open issue; for a closed one the cloud's label, or
    ``closed`` when it left none."""
    if (issue or {}).get("state") != "closed":
        return "open"
    names = github.label_names(issue)
    for label, verdict in VERDICT_LABELS:
        if label in names:
            return verdict
    return "closed"


def _norm(text: str) -> str:
    text = re.sub(r"\d+", "#", str(text or "").lower())
    return " ".join(re.sub(r"[^a-z#]+", " ", text).split())


def stand_down_keys(stream: str, fp: str, where: str = "") -> set[str]:
    """The keys a report the cloud called noise is refused under: its
    fingerprint, and for a Claude stream the part of brAIn it names (its
    title, case, digits and punctuation folded) — the run rewords its
    sentence every pass, and the title is the half it keeps."""
    keys = {fp}
    if stream in CLAUDE_STREAMS and _norm(where):
        keys.add(_digest("where|" + _norm(where)))
    return keys


def effective_hours(hours: int, slowed: bool) -> int:
    """A stream's interval, doubled while it is slowed and capped."""
    hours = int(hours or 0)
    if not hours or not slowed:
        return hours
    return min(hours * SLOW_FACTOR, max(hours, SLOW_MAX_HOURS))


def _clean_impact(raw) -> dict:
    out: dict = {}
    if isinstance(raw, dict):
        for key in IMPACT_KEYS:
            value = raw.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                out[key] = min(value, 1_000_000)
    return out


def impact_of(entry: dict) -> dict:
    """How often, over how many days, how much it touched, and what the
    house did about it — from the row's own counts where it gave them,
    else from the passes and days this queue saw it on."""
    imp = entry.get("impact") or {}
    counted = bool(imp.get("count"))
    return {
        "often": imp.get("count") or int(entry.get("seen") or 0),
        "unit": "times" if counted else "passes",
        "conversations": imp.get("conversations", 0),
        "days": imp.get("days") or len(entry.get("days") or []),
        "rows": imp.get("rows", 0), "runs": imp.get("runs", 0),
        "wrong": imp.get("wrong", 0), "endings": imp.get("endings", 0),
        "confirmed": imp.get("confirmed", 0),
    }


def impact_score(entry: dict) -> int:
    """One deterministic number to order reports by: a day it was seen on
    is worth ten passes, a person's Wrong or confirm five."""
    i = impact_of(entry)
    return (10 * i["days"] + i["often"] + i["rows"] + i["runs"]
            + 5 * (i["wrong"] + i["confirmed"]))


def _impact_lines(entry: dict) -> list[str]:
    i = impact_of(entry)
    days = f"{i['days']} day{'s' if i['days'] != 1 else ''}"
    often = f"{i['often']} {i['unit']}"
    if i["conversations"]:
        often += f" in {i['conversations']} conversations"
    lines = ["### Impact", "", f"- **How often:** {often} over {days}"]
    affected = [f"{i[k]} {k}" for k in ("rows", "runs") if i[k]]
    if affected:
        lines.append(f"- **Affected:** {', '.join(affected)}")
    if i["wrong"] or i["confirmed"]:
        acted = []
        if i["wrong"]:
            acted.append(f"marked Wrong {i['wrong']} of "
                         f"{i['endings'] or i['wrong']} times")
        if i["confirmed"]:
            acted.append(f"confirmed {i['confirmed']} "
                         f"time{'s' if i['confirmed'] != 1 else ''}")
        lines.append(f"- **The house acted:** {', '.join(acted)}")
    return lines


def fingerprint(where: str, what: str) -> str:
    norm = re.sub(r"\d+", "#", f"{where}|{what}".strip().lower())
    return hashlib.sha256(norm.encode("utf-8", "replace")).hexdigest()[:16]


def _digest(text: str) -> str:
    """An exact hash. A rolling issue's key and body change in exactly the
    digits `fingerprint` folds away (a version, a count), so folding them
    would file every release's scorecard into the first one and never
    rewrite a body whose only change is a number."""
    return hashlib.sha256(str(text).encode("utf-8", "replace")).hexdigest()[:16]


def scrub(text: str) -> str:
    """Everything credential-shaped out: the reports' own rules plus a
    GitHub token, which this package is the first to hold."""
    return _GITHUB_TOKEN_RE.sub("[redacted]", reports.redact(str(text or "")))


def _abridged(diagnostics: dict) -> str:
    small = reports.abridge(diagnostics)
    if isinstance(small, dict):
        small.pop("faults", None)  # the issue IS one of them
    text = json.dumps(small, indent=1, ensure_ascii=False, default=str)
    return text[:MAX_ABRIDGED]


def _version(diagnostics: dict) -> str:
    v = (diagnostics or {}).get("versions") or {}
    return str(v.get("addon") or "dev") if isinstance(v, dict) else "dev"


def version_tuple(version) -> tuple[int, ...] | None:
    """``"3.1.0"`` → ``(3, 1, 0)``; None for anything that is not a release
    number (``dev``, ``?``), which compares as nothing rather than as 0."""
    m = re.match(r"^v?(\d+)\.(\d+)\.(\d+)", str(version or ""))
    return tuple(int(x) for x in m.groups()) if m else None


def running_at_least(version, fixed_in) -> bool | None:
    """Whether the house runs the release a fix shipped in. None when
    either side is not a release number — "could not tell", which no
    caller may read as either answer."""
    have, need = version_tuple(version), version_tuple(fixed_in)
    if have is None or need is None:
        return None
    return have >= need


MAX_INSTALLED = 20


def _note_installed(data: dict, product: str, version: str, now: float) -> None:
    """When a sweep first saw this house running a release: the earliest
    moment brAIn can say a fix was installed, which is what "not reported
    since the fix arrived" is measured from (`verify.proof`). Kept per
    add-on and capped; a release already noted keeps its first sighting."""
    if not version_tuple(version):
        return
    seen = data.setdefault("installed", {}).setdefault(product, {})
    if not isinstance(seen, dict):
        seen = data["installed"][product] = {}
    if version not in seen:
        seen[version] = float(now)
        if len(seen) > MAX_INSTALLED:
            for old in sorted(seen, key=lambda v: seen[v])[:-MAX_INSTALLED]:
                seen.pop(old, None)


def installed_at(data: dict, product: str, fixed_in: str) -> float | None:
    """The first time a sweep saw this house on ``fixed_in`` or later for
    ``product``; None when no sweep has (or the release is not a number),
    which no caller may read as "installed long ago"."""
    seen = ((data or {}).get("installed") or {}).get(product) or {}
    if not isinstance(seen, dict):
        return None
    times = [float(at) for ver, at in seen.items()
             if isinstance(at, (int, float))
             and running_at_least(ver, fixed_in) is True]
    return min(times) if times else None


def product_of(entry: dict) -> str:
    """Which BRUH add-on a report is about: brAIn unless the row said."""
    product = str((entry or {}).get("product") or "")
    return product if product in PRODUCTS else "brAIn"


def running_for(entry: dict, version: str, products: dict | None) -> str:
    """The release of the report's OWN add-on this house runs. brAIn's is
    the queue's ``version``; another add-on's is what the siblings stream
    last read off the Supervisor, or "" ("could not tell") when nothing
    has. A GardenRX fix compared against brAIn's version would be
    "installed" or "missing" by accident of two unrelated numbers."""
    product = product_of(entry)
    if product == "brAIn":
        return str(version or "")
    return str((products or {}).get(product) or "")


# ---------------------------------------------------------------------------
# Sweeping
# ---------------------------------------------------------------------------

def sweep(diagnostics: dict, names: dict | None = None,
          now: float | None = None) -> dict:
    """Fold the current fault list into the queue. Never raises.

    The faults stream's own door, kept because it is the one the hourly
    tick has always called; every stream goes through `ingest`."""
    from . import streams  # noqa: PLC0415 — streams imports reports too
    rows = streams.faults(diagnostics) if stream_on("faults") else []
    return ingest("faults", rows, diagnostics, names, now)


def ingest(stream: str, rows: list[dict], diagnostics: dict | None = None,
           names: dict | None = None, now: float | None = None, *,
           products: dict | None = None, unread=()) -> dict:
    """File one stream's rows into the queue and stamp the stream as run.

    ``products`` is the installed version of each other BRUH add-on this
    pass read; ``unread`` names the add-ons it could NOT look at, whose
    reports in this stream are marked unlooked so none is told it has not
    been seen since. Never raises."""
    try:
        with _LOCK:
            return _ingest(stream, rows or [], diagnostics or {}, names or {},
                           now or time.time(), products or {}, tuple(unread or ()))
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        log.warning("devloop %s pass failed: %s", stream, exc)
        STATE["error"] = f"{stream} pass failed: {exc}"[:300]
        return {"error": STATE["error"]}


def _ingest(stream: str, rows: list[dict], diagnostics: dict, names: dict,
            now: float, products: dict | None = None, unread: tuple = ()) -> dict:
    if stream not in STREAMS:
        raise ValueError(f"unknown stream: {stream}")
    settings = load_settings()
    aliases = Aliases.load()
    aliases.learn(names)
    data = _load()
    items: dict = data["items"]
    version = _version(diagnostics)
    health = (diagnostics or {}).get("health") or {}
    abridged = _abridged(diagnostics) if stream == "faults" else ""
    rolling = bool(STREAMS[stream].get("rolling"))
    seen_now: set[str] = set()
    added = stood_down = 0
    stood = _vload()["stood_down"] if stream in STAND_DOWN_STREAMS else {}
    for row in rows:
        where, what = str(row.get("where") or ""), str(row.get("what") or "")
        if not what:
            continue
        # A row that names its own key (a rolling stream's one issue, an
        # unmet capability) is that key; any other is the fault, digits
        # folded.
        fp = _digest(f"{stream}|{row['key']}") if row.get("key") \
            else fingerprint(where, what)
        if fp in seen_now:
            continue
        seen_now.add(fp)
        # The cloud called this noise: not under its fingerprint, and not
        # under the part of brAIn it names.
        if stood and stand_down_keys(stream, fp, where) & stood.keys():
            stood_down += 1
            continue
        entry = items.get(fp)
        if entry is None:
            entry = items[fp] = {
                "fp": fp, "first_seen": now, "seen": 0, "stream": stream,
                "state": "pending" if settings["review"] else "ready",
            }
            added += 1
        # A row that says when it was last true (Morph's ledger keeps a
        # fault for a fortnight after it last happened, and republishes it
        # every pass) is seen THEN, not now: re-reading an old row is not
        # a new sighting, and treating it as one said "Still happening" on
        # every update about a trace nobody had seen in a week.
        seen_at = _seen_at(row, now)
        fresh = seen_at > float(entry.get("last_seen") or 0)
        # A report about another BRUH add-on is dated by THAT add-on's
        # release, which is what its fix will be read against.
        product = str(row.get("product") or "")
        if product in PRODUCTS:
            entry["product"] = product
            entry["addon"] = str(row.get("addon") or "")[:40]
        row_version = (str(row.get("product_version") or "")
                       or str((products or data.get("products") or {}).get(product) or "")
                       or "?") if product in PRODUCTS else version
        entry.update({
            "stream": stream, "rolling": rolling,
            # Cut on a word, never mid-word (`clip`): these are what the
            # issue says, and a slice ended the owner's words mid-word.
            "where": clip(where, 200), "what": clip(what, 300),
            "detail": clip(str(row.get("detail") or ""), 400),
            "body": clip(str(row.get("body") or ""), 20_000),
            "health": f"{health.get('state') or '?'}"
                      + (f" — {health.get('reason')}" if health.get("reason") else ""),
            "abridged": abridged,
        })
        if fresh:
            if entry.get("cleared_noted"):
                entry["returned"] = True
                entry["returned_at"] = seen_at
                entry["cleared_noted"] = False
            if row_version != entry.get("version") or not entry.get("version_since"):
                # The first sighting on this release, which is what a
                # closed report is reopened against (`_follow_up`).
                entry["version_since"] = seen_at
            entry.update(last_seen=seen_at, version=row_version,
                         seen=int(entry.get("seen") or 0) + 1)
            day = _day(seen_at)
            days = [d for d in (entry.get("days") or []) if isinstance(d, str)]
            if day not in days:
                days.append(day)
            entry["days"] = days[-MAX_DAYS:]
        entry.setdefault("version", row_version)
        entry.pop("unlooked", None)
        if "impact" in row:
            entry["impact"] = _clean_impact(row.get("impact"))
        # A report about a screen of the panel. The label tells the cloud to
        # look at that pane: a Screens issue brings the house's own pictures
        # of it, and anything else is driven and photographed on a fixture.
        entry["ux"] = row.get("ux") is True
        if isinstance(row.get("gallery"), list):
            entry["gallery"] = _clean_gallery(row["gallery"])
            entry["capture"] = str(row.get("capture") or "")[:20]
    # What this pass could not look at: its reports stay, and say nothing.
    if unread:
        for entry in items.values():
            if (isinstance(entry, dict) and entry.get("stream") == stream
                    and entry.get("fp") not in seen_now
                    and product_of(entry) in unread):
                entry["unlooked"] = True
    if products:
        known = data.setdefault("products", {})
        for name, ver in products.items():
            if name in PRODUCTS and ver:
                known[name] = str(ver)[:40]
                _note_installed(data, name, str(ver)[:40], now)
    _prune(items)
    data["swept_at"] = now
    # The release this house runs, read by `awaiting_update` and the
    # scorecard: the one number that says whether a fix has arrived.
    if version_tuple(version):
        data["version"] = version
        _note_installed(data, "brAIn", version, now)
    data.setdefault("last_run", {})[stream] = now
    _save(data)
    aliases.save()
    STATE["last_sweep"] = now
    return {"stream": stream, "rows": len(seen_now), "added": added,
            "stood_down": stood_down}


# ---------------------------------------------------------------------------
# The schedule and the caps
# ---------------------------------------------------------------------------

def _seen_at(row: dict, now: float) -> float:
    """When a row says it was last true, never later than now; ``now`` for
    a row that does not say (every stream but Morph's)."""
    try:
        at = float(row.get("seen_at") or 0)
    except (TypeError, ValueError):
        at = 0.0
    return min(at, now) if at > 0 else now


def _epoch(iso) -> float:
    """GitHub's ``2026-10-19T01:43:19Z`` as an epoch; 0 when unreadable."""
    try:
        return float(calendar.timegm(time.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ")))
    except (TypeError, ValueError):
        return 0.0


def _day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(now))


def due_streams(now: float | None = None) -> list[str]:
    """The streams whose schedule says a pass is owed now."""
    now = now or time.time()
    settings = load_settings()
    if not settings.get("enabled"):
        return []
    last = _load().get("last_run") or {}
    slowed = _vload()["slowed"]
    out = []
    for name in STREAMS:
        hours = effective_hours((settings.get("schedule") or {}).get(name) or 0,
                                name in slowed)
        if not hours or not (settings.get("streams") or {}).get(name):
            continue
        if now - float(last.get(name) or 0) >= hours * 3600:
            out.append(name)
    return out


def runs_left(now: float | None = None) -> int:
    """How many Claude-run passes today's cap still allows."""
    now = now or time.time()
    used = _load().get("runs") or {}
    count = int(used.get("count") or 0) if used.get("day") == _day(now) else 0
    return max(0, int(load_settings().get("max_runs_per_day") or 0) - count)


def spend_run(now: float | None = None) -> bool:
    """Take one Claude-run pass from today's cap, or say there is none."""
    now = now or time.time()
    with _LOCK:
        if runs_left(now) <= 0:
            return False
        data = _load()
        used = data.get("runs") or {}
        count = int(used.get("count") or 0) if used.get("day") == _day(now) else 0
        data["runs"] = {"day": _day(now), "count": count + 1}
        _save(data)
    return True


def mark_run(stream: str, now: float | None = None) -> None:
    """Stamp a stream as run without filing anything (a pass that found
    nothing still ran, and must not be asked again until it is due)."""
    with _LOCK:
        data = _load()
        data.setdefault("last_run", {})[stream] = now or time.time()
        _save(data)


def _issues_today(items: dict, now: float) -> int:
    return sum(1 for e in items.values() if isinstance(e, dict)
               and now - float(e.get("sent_at") or 0) < 86400
               and e.get("created_here"))


def _prune(items: dict) -> None:
    if len(items) <= MAX_QUEUE:
        return
    # Discarded and long-quiet entries go first; a pending one somebody has
    # not looked at yet is kept over a sent one that has been fixed.
    def rank(e: dict) -> tuple:
        order = {"discarded": 0, "sent": 1, "ready": 2, "pending": 3}
        return (order.get(e.get("state"), 0), e.get("last_seen") or 0)
    for fp in sorted(items, key=lambda k: rank(items[k]))[:len(items) - MAX_QUEUE]:
        items.pop(fp, None)


# ---------------------------------------------------------------------------
# Composing — the one function the preview and the sender both call
# ---------------------------------------------------------------------------

def _date(epoch) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(float(epoch or 0)))


def _clean_gallery(rows: list) -> list[dict]:
    from . import screens  # noqa: PLC0415 — screens imports scrub from here
    out = []
    for r in rows[:60]:
        if not isinstance(r, dict) or not screens.SHOT_RE.match(str(r.get("name") or "")):
            continue
        out.append({"name": r["name"], "screen": str(r.get("screen") or "")[:60],
                    "width": int(r.get("width") or 0),
                    "scheme": "dark" if r.get("scheme") == "dark" else "light",
                    "sha": str(r.get("sha") or "")[:64]})
    return out


def _gallery_lines(entry: dict) -> list[str]:
    """The pictures, one row per screen and a column per view. Built from
    the catalog's own labels and the links GitHub gave back, and never
    through the aliases: a link renamed by them leads nowhere."""
    gallery = entry.get("gallery") or []
    if not gallery:
        return []
    uploaded = entry.get("uploaded") or {}
    views: list[tuple[int, str]] = []
    screens_seen: list[str] = []
    cells: dict[tuple[str, int, str], str] = {}
    for g in gallery:
        view = (int(g.get("width") or 0), str(g.get("scheme") or "light"))
        if view not in views:
            views.append(view)
        if g["screen"] not in screens_seen:
            screens_seen.append(g["screen"])
        up = uploaded.get(g["name"]) or {}
        url = up.get("url") if up.get("sha") == g.get("sha") else ""
        cells[(g["screen"],) + view] = (f"![{g['screen']}, {view[0]}px {view[1]}]({url})"
                                        if url else f"`{g['name']}` (sent with the issue)")
    head = "| Screen | " + " | ".join(f"{w}px {sch}" for w, sch in views) + " |"
    lines = ["## Screens", "", head, "|---" * (len(views) + 1) + "|"]
    for name in screens_seen:
        lines.append(f"| {name} | " + " | ".join(
            cells.get((name, w, sch), "—") for w, sch in views) + " |")
    return lines + [""]


def compose(entry: dict, aliases: Aliases | None = None) -> dict:
    """``{"title", "body"}`` exactly as they would be sent."""
    aliases = aliases or Aliases.load()

    def clean(text: str) -> str:
        return aliases.apply(scrub(text))

    where, what = clean(entry.get("where", "")), clean(entry.get("what", ""))
    title = clip(f"[{where}] {what}" if where else what, 120)
    lines = [
        github.MARKER.format(fp=entry.get("fp", "")),
        ("Filed by brAIn's development loop from a house that switched it "
         + "on. Entity ids, names and rooms are replaced with stable aliases "
         + "and anything credential-shaped is removed."),
        "",
        f"**Where:** {where}",
        f"**What:** {what}",
    ]
    if entry.get("detail"):
        lines.append(f"**Detail:** {clean(entry['detail'])}")
    # A rolling issue is rewritten when what it says changes, so it carries
    # no impact counts: they move every pass.
    if not entry.get("rolling"):
        lines += [""] + [clean(line) for line in _impact_lines(entry)]
    if entry.get("body"):
        lines += ["", clean(entry["body"])]
    if entry.get("gallery"):
        lines += [""] + _gallery_lines(entry)
    lines += ["", "| | |", "|---|---|",
              f"| {product_of(entry)} | {clean(entry.get('version', '?'))} |",
              f"| First seen | {_date(entry.get('first_seen'))} |"]
    # A rolling issue is rewritten only when what it says changes, so it
    # carries no per-pass counter: one would make every pass a rewrite.
    if not entry.get("rolling"):
        lines += [f"| Last seen | {_date(entry.get('last_seen'))} |",
                  f"| Seen on | {int(entry.get('seen') or 0)} passes |"]
    lines += [f"| Health | {clean(entry.get('health', '?'))} |", ""]
    if entry.get("abridged"):
        lines += [
            "<details><summary>Diagnostics (abridged)</summary>",
            "",
            "```json",
            clean(entry["abridged"]),
            "```",
            "</details>",
        ]
    lines += ["", f"Stream: `{entry.get('stream') or 'faults'}`"]
    return {"title": title, "body": "\n".join(lines)}


# ---------------------------------------------------------------------------
# The person's presses
# ---------------------------------------------------------------------------

def listing() -> list[dict]:
    rows = []
    for e in _load()["items"].values():
        if not isinstance(e, dict):
            continue
        row = {k: e.get(k) for k in (
            "fp", "stream", "where", "what", "state", "seen", "first_seen", "last_seen",
            "issue", "issue_url", "error", "cleared_noted", "verdict", "stood_down")}
        row["impact"] = impact_score(e)
        rows.append(row)
    # What is waiting is listed most impactful first: the order it is sent.
    order = {"pending": 0, "ready": 1, "sent": 2, "discarded": 3}
    rows.sort(key=lambda r: (order.get(r["state"], 9), -r["impact"],
                             -(r["last_seen"] or 0)))
    return rows


def preview(fp: str) -> dict | None:
    if not FP_RE.match(fp or ""):
        return None
    entry = _load()["items"].get(fp)
    if not isinstance(entry, dict):
        return None
    doc = compose(entry)
    # The pictures that would go with it, served from this box so the
    # review is of exactly what is sent (`api/devloop/screen/...`).
    if entry.get("gallery") and entry.get("capture"):
        doc["images"] = [{"src": f"api/devloop/screen/{entry['capture']}/{g['name']}",
                          "label": f"{g['screen']}, {g['width']}px {g['scheme']}"}
                         for g in entry["gallery"]]
    return doc


def mark(fp: str, state: str) -> bool:
    """Send (``ready``) or Discard (``discarded``) one fingerprint."""
    if not FP_RE.match(fp or "") or state not in ("ready", "discarded"):
        return False
    with _LOCK:
        data = _load()
        entry = data["items"].get(fp)
        if not isinstance(entry, dict) or entry.get("state") == "sent":
            return False
        entry["state"] = state
        entry.pop("error", None)
        _save(data)
    return True


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------

def send_due(now: float | None = None) -> dict:
    """Send what is ready and say what changed on what was sent. Never raises."""
    try:
        with _LOCK:
            return _send_due(now or time.time())
    except Exception as exc:  # noqa: BLE001 — see the module docstring
        log.warning("devloop send failed: %s", exc)
        STATE["error"] = f"send failed: {exc}"[:300]
        return {"error": STATE["error"]}


def _send_due(now: float) -> dict:
    if not enabled():
        return {"skipped": "the development loop is off"}
    settings = load_settings()
    token, repo = read_token(), settings["repo"]
    if not token or not repo:
        STATE["error"] = "set a repository and a token to send"
        return {"skipped": STATE["error"]}
    data = _load()
    items: dict = data["items"]
    work = [e for e in items.values() if isinstance(e, dict) and (
        e.get("state") == "ready" or (e.get("state") == "sent" and e.get("issue")))]
    if not work:
        STATE["error"] = ""
        return {"sent": 0, "updated": 0}
    ok, why = github.check_repo(token, repo)
    if not ok:
        STATE["error"] = why
        return {"error": why}
    aliases = Aliases.load()
    verdicts = _vload()
    if now - float(verdicts.get("at") or 0) >= VERDICT_INTERVAL_S:
        _refresh_verdicts(token, repo, items, verdicts, now)
    stood = verdicts["stood_down"]
    sent = updated = 0
    # The day's cap counts only issues this house CREATED: a fingerprint
    # found again by its marker, a comment and a rewritten scorecard file
    # nothing new and cost nobody's attention.
    room = max(0, int(settings.get("max_issues_per_day") or 0)
               - _issues_today(items, now))
    capped = 0
    # New reports go most impactful first, so the day's cap is spent on
    # what matters; the rest keep the order they were found in.
    work.sort(key=lambda e: (e.get("state") != "ready",
                             -impact_score(e) if e.get("state") == "ready" else 0,
                             e.get("first_seen") or 0, e.get("fp") or ""))
    for entry in work:
        if entry["state"] == "ready":
            if _stand_down(entry, stood):
                continue
            if sent >= min(MAX_SENDS_PER_PASS, room):
                capped += 1
                continue
            if _file(token, repo, entry, aliases, now, verdicts):
                sent += 1
                if entry.get("rolling"):
                    updated += _retire_superseded(token, repo, items, entry)
        elif entry.get("state") != "sent":
            continue  # stood down by the verdicts read above
        elif entry.get("rolling"):
            if _rewrite(token, repo, entry, aliases):
                updated += 1
        elif _follow_up(token, repo, entry, now, aliases,
                        running=running_for(entry, str(data.get("version") or ""),
                                            data.get("products"))):
            updated += 1
    # The owner's answers to "is this fixed?", posted after the follow-ups
    # so a "Not fixed" reopen is the last word on the issue this pass.
    updated += _post_owner_answers(token, repo, items, aliases,
                                   running=str(data.get("version") or ""),
                                   products=data.get("products"))
    _save(data)
    _vsave(verdicts)
    aliases.save()
    STATE.update(last_send=now, error="")
    return {"sent": sent, "updated": updated, "capped": capped}


def _refresh_verdicts(token: str, repo: str, items: dict, v: dict,
                      now: float) -> None:
    """Read back what the cloud said about every filed report, and decide
    which streams are noise. A listing that fails leaves the old verdicts
    standing and is asked again next tick: "I could not look" is not
    "nothing changed"."""
    tracked: dict[int, dict] = {}
    for entry in items.values():
        if isinstance(entry, dict) and int(entry.get("issue") or 0) > 0:
            tracked[int(entry["issue"])] = entry
    if not tracked:
        return
    rows, err = github.list_issues(token, repo)
    if err or rows is None:
        log.info("devloop: could not read the verdicts: %s", err)
        return
    by_number = {int(r.get("number") or 0): r for r in rows}
    asked = 0
    for number in sorted(tracked):
        if number not in by_number and asked < VERDICT_GETS_PER_PASS:
            asked += 1
            issue, _ = github.get_issue(token, repo, number)
            if issue:
                by_number[number] = issue
    resolved, stood = v["resolved"], v["stood_down"]
    for number, entry in tracked.items():
        issue = by_number.get(number)
        if not issue:
            continue
        verdict = verdict_of(issue)
        fp, stream = entry["fp"], str(entry.get("stream") or "faults")
        if verdict != entry.get("verdict"):
            entry["verdict_at"] = now
        entry["verdict"] = verdict
        entry["closed_at"] = _epoch(issue.get("closed_at")) if verdict != "open" else 0
        if verdict == "open":
            resolved.pop(fp, None)
        else:
            old = resolved.get(fp) or {}
            same = old.get("verdict") == verdict
            row = {"stream": stream, "verdict": verdict, "issue": number,
                   "at": old.get("at") if same else now,
                   # What was filed, so the next run can be told what was
                   # turned down after the queue entry itself is pruned.
                   "where": clip(str(entry.get("where") or ""), 120),
                   "what": clip(str(entry.get("what") or ""), 200)}
            if same:
                for k in ("reason", "reason_tries", "fixed_in", "fixed_in_tries"):
                    if k in old:
                        row[k] = old[k]
            resolved[fp] = row
            if row.get("fixed_in"):
                entry["fixed_in"] = row["fixed_in"]
        for key in [k for k, row in stood.items() if row.get("fp") == fp]:
            stood.pop(key)
        if verdict in NOISE and stream in STAND_DOWN_STREAMS:
            for key in stand_down_keys(stream, fp, entry.get("where") or ""):
                stood[key] = {"fp": fp, "stream": stream, "verdict": verdict,
                              "issue": number, "at": now}
    # A report still waiting for a press that the cloud has since called
    # noise (under its title) is not one anybody needs to review.
    for entry in items.values():
        if isinstance(entry, dict) and entry.get("state") in ("pending", "ready"):
            _stand_down(entry, stood)
    _fetch_reasons(token, repo, resolved)
    _fetch_fixed_in(token, repo, resolved, tracked)
    _evaluate_slow(v, now)
    v["at"] = now


def _first_line(text: str) -> str:
    """A closing comment's first line of prose: markdown markers, blank
    lines and whitespace taken off, cut on a word."""
    for line in str(text or "").splitlines():
        line = re.sub(r"^[\s>#-]+", "", re.sub(r"\*\*|__|`", "", line)).strip()
        if line:
            return clip(" ".join(line.split()), REASON_CHARS)
    return ""


def _fetch_reasons(token: str, repo: str, resolved: dict) -> None:
    """Why the cloud closed a report as noise: the first line of its
    closing comment. One request per closed report, at most
    REASONS_PER_PASS a pass, and only for the streams whose next run is
    told. A comment GitHub would not hand over is asked again on a later
    pass, REASON_TRIES times, and then the label stands in for the reason —
    a verdict with no reason is still worth showing, and asking for ever is
    not."""
    asked = 0
    for row in sorted(resolved.values(), key=lambda r: -float(r.get("at") or 0)):
        if asked >= REASONS_PER_PASS:
            break
        if (row.get("verdict") not in NOISE or row.get("reason")
                or row.get("stream") not in STAND_DOWN_STREAMS):
            continue
        asked += 1
        body, err = github.last_comment(token, repo, int(row.get("issue") or 0))
        if body is None:
            row["reason_tries"] = int(row.get("reason_tries") or 0) + 1
            if row["reason_tries"] < REASON_TRIES:
                log.info("devloop: could not read why #%s was closed: %s",
                         row.get("issue"), err)
                continue
        row["reason"] = _first_line(body or "") or f"labelled {row['verdict']}"
        row.pop("reason_tries", None)


def _fetch_fixed_in(token: str, repo: str, resolved: dict,
                    tracked: dict[int, dict]) -> None:
    """Which release each fixed report's fix shipped in, read once off the
    cloud's closing comment. A comment with no version in it (a hand
    close) is asked for REASON_TRIES times and then left as unknown, and
    unknown is never read as "already here": `_follow_up` and
    `awaiting_update` both treat it as could-not-tell."""
    asked = 0
    for fp, row in sorted(resolved.items(), key=lambda kv: -float(kv[1].get("at") or 0)):
        if asked >= FIXED_IN_PER_PASS:
            break
        if (row.get("verdict") != "fixed" or row.get("fixed_in")
                or int(row.get("fixed_in_tries") or 0) >= REASON_TRIES):
            continue
        asked += 1
        body, err = github.last_comment(token, repo, int(row.get("issue") or 0))
        entry = tracked.get(int(row.get("issue") or 0))
        want = product_of(entry) if isinstance(entry, dict) else ""
        matches = list(FIXED_IN_RE.finditer(body or ""))
        # A batch comment can name two products; the one this report is
        # about wins, and any is better than none.
        m = next((x for x in matches if x.group(1) == want), None) \
            or (matches[0] if matches else None)
        if not m:
            row["fixed_in_tries"] = int(row.get("fixed_in_tries") or 0) + 1
            if body is None:
                log.info("devloop: could not read which release fixed #%s: %s",
                         row.get("issue"), err)
            continue
        row["fixed_in"] = m.group(2)
        row.pop("fixed_in_tries", None)
        if isinstance(entry, dict) and entry.get("fp") == fp:
            entry["fixed_in"] = m.group(2)


def awaiting_update(items: dict | None = None, version: str = "",
                    products: dict | None = None) -> list[dict]:
    """Fixed reports whose fix is in a release this house does not run
    yet: the issue, what it was about, the release it needs and how long
    it has waited. A fix nothing has installed is not a fix that held,
    and until this the cloud read that silence as success."""
    if items is None:
        data = _load()
        items, version = data["items"], version or str(data.get("version") or "")
        products = products if products is not None else data.get("products")
    out = []
    for entry in items.values():
        if not isinstance(entry, dict) or entry.get("verdict") != "fixed":
            continue
        need = entry.get("fixed_in")
        if not need or running_at_least(
                running_for(entry, version, products), need) is not False:
            continue
        out.append({"issue": int(entry.get("issue") or 0),
                    "product": product_of(entry),
                    "what": clip(str(entry.get("what") or ""), 120),
                    "fixed_in": str(need),
                    "since": float(entry.get("closed_at") or 0)})
    out.sort(key=lambda r: (r["fixed_in"], r["issue"]))
    return out


def cloud_last_seen(v: dict | None = None) -> float:
    """When the cloud last closed one of this house's reports: the newest
    close among the verdicts read back, or 0 when none has been. A loop
    whose cloud half has stopped answering looks, from the house, exactly
    like one whose reports are all still open; this is what tells them
    apart."""
    v = _vload() if v is None else v
    return max((float((r or {}).get("at") or 0)
                for r in (v.get("resolved") or {}).values()
                if isinstance(r, dict)), default=0.0)


def rejected() -> list[dict]:
    """The reports the cloud closed as noise, with what they said and why
    they were closed: what `streams.rejected_block` shows the next run."""
    return [dict(r) for r in _vload()["resolved"].values()
            if isinstance(r, dict) and r.get("verdict") in NOISE
            and r.get("stream") in STAND_DOWN_STREAMS]


def note_unreadable(stream: str, why: str, now: float | None = None) -> None:
    """Count a Claude stream's reply that could not be read. It used to be
    dropped as if the run had found nothing, which reads the same as a run
    that looked and had nothing to say; this is what tells them apart in
    the status the panel shows. Never raises."""
    if stream not in STREAMS:
        return
    try:
        with _LOCK:
            data = _load()
            seen = data.setdefault("unreadable", {})
            row = seen.get(stream) if isinstance(seen.get(stream), dict) else {}
            seen[stream] = {"count": int(row.get("count") or 0) + 1,
                            "at": now or time.time(), "why": str(why or "")[:200]}
            _save(data)
    except Exception as exc:  # noqa: BLE001 — accounting must not fail a pass
        log.warning("devloop: could not count an unreadable %s reply: %s",
                    stream, exc)


def _stand_down(entry: dict, stood: dict) -> bool:
    """Discard a report the cloud already called noise, saying which issue
    said so. True when it was."""
    if entry.get("stream") not in STAND_DOWN_STREAMS:
        return False
    keys = stand_down_keys(entry["stream"], entry["fp"],
                           entry.get("where") or "") & stood.keys()
    if not keys:
        return False
    match = stood[sorted(keys)[0]]
    entry.update(state="discarded",
                 stood_down=f"{match.get('verdict')} on #{match.get('issue')}")
    return True


def _window(v: dict, stream: str) -> list[dict]:
    after = float(v["unslowed"].get(stream) or 0)
    rows = [dict(r, fp=fp) for fp, r in v["resolved"].items()
            if r.get("stream") == stream and float(r.get("at") or 0) > after]
    rows.sort(key=lambda r: (float(r.get("at") or 0), r["fp"]))
    return rows[-SLOW_WINDOW:]


def _evaluate_slow(v: dict, now: float) -> None:
    """Slowed is derived, every refresh: it holds while the window is
    mostly noise and lifts itself the pass it is not."""
    slowed = v["slowed"]
    for stream in STREAMS:
        window = _window(v, stream)
        noise = sum(1 for r in window if r.get("verdict") in NOISE)
        if len(window) >= SLOW_WINDOW and noise >= SLOW_NOISE_SHARE * SLOW_WINDOW:
            row = slowed.setdefault(stream, {"since": now})
            row.update(noise=noise, of=len(window), why=(
                f"{noise} of its last {len(window)} closed reports were declined, "
                "not brAIn's, or duplicates, so it runs half as often"))
        else:
            slowed.pop(stream, None)


def unslow(stream: str) -> bool:
    """A person putting a slowed stream back to its own schedule. It is not
    slowed again until reports resolved after this press say so."""
    if stream not in STREAMS:
        return False
    with _LOCK:
        v = _vload()
        ats = [float(r.get("at") or 0) for r in v["resolved"].values()
               if r.get("stream") == stream]
        v["unslowed"][stream] = max(ats, default=0.0)
        was = v["slowed"].pop(stream, None)
        _vsave(v)
    return was is not None


def usefulness(v: dict | None = None) -> dict:
    """Per stream: issues this house filed, and what the cloud said about
    the ones it closed."""
    v = v if v is not None else _vload()
    out = {name: {"filed": int(v["filed"].get(name) or 0),
                  **{verdict: 0 for verdict in VERDICTS}} for name in STREAMS}
    for row in v["resolved"].values():
        counts = out.get(str(row.get("stream")))
        if counts is not None and row.get("verdict") in counts:
            counts[row["verdict"]] += 1
    return out


def _upload_gallery(token: str, repo: str, entry: dict) -> bool:
    """Put the entry's pictures in the repository before the issue that
    shows them. A picture already there with the same bytes is not sent
    again. Any failure stops the issue: an issue pointing at pictures that
    are not there is a page of broken images."""
    gallery = entry.get("gallery") or []
    if not gallery:
        return True
    from . import screens  # noqa: PLC0415
    from . import data_dir  # noqa: PLC0415
    uploaded = dict(entry.get("uploaded") or {})
    for g in gallery:
        if (uploaded.get(g["name"]) or {}).get("sha") == g.get("sha"):
            continue
        path = screens.local_file(data_dir(), entry.get("capture", ""), g["name"])
        if path is None:
            entry["error"] = ("the pictures for this report are no longer on "
                              "this box — run Screens again")
            return False
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != g.get("sha"):
            entry["error"] = "a picture changed on disk after it was redacted"
            return False
        url, err = github.put_file(
            token, repo, screens.repo_path(entry.get("version", "dev"), g["name"],
                                           product_of(entry)),
            data, f"brAIn screens: {g['screen']} at {g['width']}px {g['scheme']}")
        if err:
            entry["error"] = err
            return False
        uploaded[g["name"]] = {"sha": g["sha"], "url": url}
    entry["uploaded"] = {g["name"]: uploaded[g["name"]] for g in gallery
                         if g["name"] in uploaded}
    return True


def _rewrite(token: str, repo: str, entry: dict, aliases: Aliases) -> bool:
    """A rolling issue is one issue whose body is the current answer: the
    body is rewritten when what it says has changed, and never commented
    on — a scorecard with a comment a day is a scorecard nobody reads."""
    if not _upload_gallery(token, repo, entry):
        return False
    doc = compose(entry, aliases)
    digest = _digest(doc["body"])
    if digest == entry.get("body_digest"):
        return False
    ok, err = github.update_issue(token, repo, int(entry.get("issue") or 0),
                                  doc["title"], doc["body"])
    if not ok:
        entry["error"] = err
        return False
    entry["body_digest"] = digest
    entry.pop("error", None)
    return True


def _addon_labels(entry: dict) -> list[str]:
    """``devloop:<key>`` for a report about another BRUH add-on, which is
    how the cloud routine knows the directory its fix belongs in."""
    spec = spec_by_name(product_of(entry))
    return [f"devloop:{spec['key']}"] if spec and entry.get("stream") != "morph" else []


def _file(token: str, repo: str, entry: dict, aliases: Aliases, now: float,
          verdicts: dict | None = None) -> bool:
    number, err = github.find_issue(token, repo, entry["fp"])
    if err:
        entry["error"] = err
        return False
    if number:
        issue, err = github.get_issue(token, repo, number)
    else:
        if not _upload_gallery(token, repo, entry):
            return False
        doc = compose(entry, aliases)
        issue, err = github.create_issue(
            token, repo, doc["title"], doc["body"],
            labels=[github.LABEL, f"devloop:{entry.get('stream') or 'faults'}"]
            + (["devloop:ux"] if entry.get("ux") is True else [])
            + _addon_labels(entry))
        if issue:
            entry["created_here"] = True
            entry["body_digest"] = _digest(doc["body"])
            if verdicts is not None:
                stream = str(entry.get("stream") or "faults")
                verdicts["filed"][stream] = int(verdicts["filed"].get(stream) or 0) + 1
    if err or not issue:
        entry["error"] = err or "GitHub did not return the issue"
        return False
    entry.update(state="sent", issue=int(issue.get("number") or 0),
                 issue_url=str(issue.get("html_url") or ""), sent_at=now,
                 noted_version=entry.get("version"), cleared_noted=False,
                 returned=False)
    entry.pop("error", None)
    return True


OWNER_NOTE_CHARS = 400


def owner_answer(fp: str, accepted: bool, note: str = "",
                 now: float | None = None, *, by: str = "owner") -> bool:
    """Record the answer to "is this fixed?" on the queue entry; the next
    send pass posts it (`_post_owner_answers`). Recorded and not posted
    here because posting needs the token and the lock the send pass
    already holds, and a press must not wait on GitHub.

    ``by`` is who answered: ``owner`` (a press) or ``brain`` (brAIn proved
    it from what it measures, `verify.proof`), and the comment says which
    — brAIn's answer never reads as the owner confirming anything."""
    if not FP_RE.match(fp or ""):
        return False
    with _LOCK:
        data = _load()
        entry = data["items"].get(fp)
        if not isinstance(entry, dict) or not int(entry.get("issue") or 0):
            return False
        entry["owner"] = {"verdict": "held" if accepted else "not_fixed",
                          "note": clip(str(note or ""), OWNER_NOTE_CHARS),
                          "at": now or time.time(), "posted": False,
                          "by": "brain" if by == "brain" else "owner"}
        _save(data)
    return True


def forget_owner_answer(fp: str) -> bool:
    """Undo: an answer not yet posted is dropped; one already posted
    stands, and the next answer is posted beside it."""
    if not FP_RE.match(fp or ""):
        return False
    with _LOCK:
        data = _load()
        entry = data["items"].get(fp)
        if not isinstance(entry, dict) or not isinstance(entry.get("owner"), dict):
            return False
        if entry["owner"].get("posted"):
            return False
        entry.pop("owner", None)
        _save(data)
    return True


def _post_owner_answers(token: str, repo: str, items: dict, aliases: Aliases,
                        running: str = "", products: dict | None = None) -> int:
    """The owner's verdict on a fix, as the comment the cloud reads: a
    confirmation, or "Not fixed" with their words and the issue reopened
    so the next run's drain takes it. Their words are aliased and
    scrubbed exactly as an issue body is."""
    posted = 0
    for entry in items.values():
        if not isinstance(entry, dict):
            continue
        owner = entry.get("owner")
        if not isinstance(owner, dict) or owner.get("posted"):
            continue
        number = int(entry.get("issue") or 0)
        # The release the house runs now, which is what the owner answered
        # about; the entry's own version is the release the report was
        # last SEEN on, and a request has never been seen since it was
        # filed.
        product = product_of(entry)
        version = (running_for(entry, running, products)
                   or str(entry.get("version") or "?"))
        if owner.get("verdict") == "held" and owner.get("by") == "brain":
            # brAIn's own proof, said as brAIn's: the owner has not
            # answered, and nothing here may read as them confirming it.
            words = scrub(str(owner.get("note") or "")).strip()
            text = f"brAIn checked on {product} {version}" + (
                f": {words}" if words else ".")
            text += " (Not answered by the owner.)"
            reopen = False
        elif owner.get("verdict") == "held":
            text, reopen = f"The owner confirms this is fixed on {product} {version}.", False
        else:
            words = aliases.apply(scrub(str(owner.get("note") or "")))
            text = f"Not fixed on {product} {version}" + (f": {words}" if words else ".")
            reopen = True
        ok, err = github.comment(token, repo, number, text, reopen=reopen)
        if not ok:
            entry["error"] = err
            continue
        owner["posted"] = True
        owner["posted_at"] = time.time()
        if reopen:
            entry.update(verdict="open", closed_at=0)
        entry.pop("error", None)
        posted += 1
    return posted


def _retire_superseded(token: str, repo: str, items: dict, newest: dict) -> int:
    """Close the stream's older rolling issues once a new one is filed.

    The scorecard is one issue PER RELEASE, so every update filed a new one
    and left the last beside it, open for ever: ten scorecards in the open
    list, nine of them about releases no house runs. The newest is the
    answer; the older ones are history, closed with a pointer to it."""
    closed = 0
    for entry in items.values():
        if (not isinstance(entry, dict) or entry is newest
                or entry.get("stream") != newest.get("stream")
                or not entry.get("rolling") or entry.get("state") != "sent"
                or not int(entry.get("issue") or 0)
                or int(entry["issue"]) == int(newest.get("issue") or 0)):
            continue
        ok, err = github.close_issue(
            token, repo, int(entry["issue"]),
            f"Superseded by #{newest.get('issue')} (brAIn "
            f"{newest.get('version') or '?'}).")
        if not ok:
            entry["error"] = err
            continue
        entry["state"] = "retired"
        entry.pop("error", None)
        closed += 1
    return closed


def _follow_up(token: str, repo: str, entry: dict, now: float,
               aliases: Aliases | None = None, running: str = "") -> bool:
    """One comment, when there is something to say: it stopped, it came
    back, or it is still happening on a newer version. Dates and versions
    only — nothing composed from the house.

    A CLOSED report is the cloud's decision, and three rules keep the house
    from arguing with it by accident. **A noise verdict is final**:
    not-brAIn, duplicate and declined are never commented on or reopened —
    a restart owed after every install is still not brAIn's, however often
    it is seen, and a person who disagrees reopens it by hand. **A fixed
    report is reopened only on evidence**: its fault went away and came
    back after the close, or has been seen for `REOPEN_AFTER_S` on a release
    first seen AFTER the close — so a row a window still holds from before
    the fix says nothing. **Anything else
    says nothing either**, and the house asks again next pass."""
    number = int(entry.get("issue") or 0)
    last_seen = float(entry.get("last_seen") or 0)
    absent = now - last_seen
    version = str(entry.get("version") or "?")
    product = product_of(entry)
    text, reopen = "", False
    # "Not seen" is a claim only a sweep that LOOKED can make: with the
    # stream switched off nothing was looking, and silence is not the
    # fault going away (`clear_resolved`'s rule).
    stream = str(entry.get("stream") or "faults")
    if not STREAMS.get(stream, {}).get("clears"):
        # A request, an idea or a gap is said once; whether it stopped is
        # not a question the stream can answer.
        return False
    if entry.get("verdict") in NOISE:
        return False
    looked = stream_on(stream) and not entry.get("unlooked")
    fixed_in = str(entry.get("fixed_in") or "")
    # Whether the fix is installed is asked of the release the house RUNS
    # (the queue's, stamped by every sweep), never the one the fault was
    # last seen on: a fault that stopped was last seen on the old release
    # by definition.
    running = running or (version if product == "brAIn" else "")
    arrived = running_at_least(running, fixed_in) if fixed_in else None
    if looked and absent >= CLEAR_AFTER_S and not entry.get("cleared_noted"):
        if entry.get("verdict") == "fixed" and arrived:
            # The fix is installed and the fault stopped: the one sentence
            # that closes the loop, said as the claim it is.
            text = (f"Held: not seen since {_date(entry.get('last_seen'))} "
                    f"on {product} {running} (fixed in {fixed_in}).")
        else:
            text = (f"Not seen since {_date(entry.get('last_seen'))} "
                    f"({product} {version}).")
        entry["cleared_noted"] = True
    elif absent < CLEAR_AFTER_S and (entry.get("returned")
                                     or version != entry.get("noted_version")):
        verdict = entry.get("verdict")
        closed_at = float(entry.get("closed_at") or 0)
        if verdict in (None, "open"):
            # Not yet read back this hour: ask, once, and keep the answer.
            issue, err = github.get_issue(token, repo, number)
            if err or not issue:
                entry["error"] = err
                return False
            verdict = verdict_of(issue)
            closed_at = _epoch(issue.get("closed_at")) if verdict != "open" else 0
            entry.update(verdict=verdict, closed_at=closed_at)
            if verdict in NOISE:
                return False
        if verdict != "open":
            if verdict == "fixed" and arrived is False:
                # The fix shipped in a release this house does not run
                # yet. Seeing the fault on the OLD release says nothing
                # about the fix, so nothing is said and nothing reopened;
                # `awaiting_update` is where the wait is reported.
                return False
            since = float(entry.get("version_since") or 0)
            # Gone for two days and seen again after the close is a fault
            # that came back; a row that never went away has to outlast a
            # day on a release first seen after the close.
            came_back = (entry.get("returned")
                         and float(entry.get("returned_at") or 0) > closed_at)
            persisted = since > closed_at and last_seen - since >= REOPEN_AFTER_S
            if not (came_back or persisted):
                # Not evidence yet: say nothing, and look again next pass.
                return False
            reopen = True
            text = (f"Back again on {product} {version} after this was closed "
                    f"(last seen {_date(entry.get('last_seen'))}).")
        elif entry.get("returned"):
            text = f"Back again on {product} {version}."
        else:
            text = f"Still happening on {product} {version}."
        entry["returned"] = False
        entry["noted_version"] = version
    if not text:
        return False
    ok, err = github.comment(token, repo, number, text, reopen=reopen)
    if not ok:
        entry["error"] = err
        return False
    if reopen:
        entry.update(verdict="open", closed_at=0)
    if aliases is not None and not text.startswith("Not seen since"):
        # A fault that is still happening is read from its BODY, and the
        # body was written once: "18 findings are still waiting" stood for
        # ten days while the count moved, so nobody could aim a fix at it.
        # The current numbers go in with the comment that says it is live.
        doc = compose(entry, aliases)
        digest = _digest(doc["body"])
        if digest != entry.get("body_digest"):
            done, _ = github.update_issue(token, repo, number, doc["title"], doc["body"])
            if done:
                entry["body_digest"] = digest
    entry.pop("error", None)
    return True


def status() -> dict:
    data = _load()
    v = _vload()
    waiting = awaiting_update(data["items"], str(data.get("version") or ""),
                              data.get("products") or {})
    return {
        "usefulness": usefulness(v),
        "slowed": v["slowed"],
        "verdicts_at": float(v.get("at") or 0),
        # The newest close the cloud made, so a cloud half that has
        # stopped answering is a date going stale rather than a silence.
        "cloud_last_seen": cloud_last_seen(v),
        # Fixed reports whose fix this house has not installed yet: how
        # many, and the oldest release they need.
        "awaiting_update": len(waiting),
        "awaiting_version": waiting[0]["fixed_in"] if waiting else "",
        "version": str(data.get("version") or ""),
        "last_run": data.get("last_run") or {},
        "runs_left": runs_left(),
        "last_sweep": STATE["last_sweep"] or data.get("swept_at") or 0,
        "last_send": STATE["last_send"],
        "error": STATE["error"],
        "running": STATE["running"],
        # Claude replies that could not be read, per stream: count, when the
        # last one was, and why (`note_unreadable`).
        "unreadable": data.get("unreadable") or {},
    }
