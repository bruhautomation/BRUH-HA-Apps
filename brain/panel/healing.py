"""Overnight self-healing: a closed playbook of three safe remediations.

Every other acting path in brAIn is a person's press. This one is not:
it runs while the house is asleep and nobody is looking, which is the
whole point and also the reason it is the narrowest thing on this page.

**A remediation is a function from one open finding to at most one call.**
Not a plan, not a loop, not a model. The three that ship are the three
where the call is what a person would have pressed and the failure mode
of getting it wrong is nothing:

    check:sys.addon_down    start it        the Supervisor's own
                                            /addons/<slug>/start. It was
                                            set to run at boot and it is
                                            not running; starting it is
                                            what boot would have done.
    check:dev.zwave_dead    ping the node   a read with a side effect —
                                            the controller re-marks the
                                            node if it answers. Nothing
                                            in the house moves.
    check:sys.entry_failed  reload it       homeassistant.reload_config_entry
                                            on an entry that has already
                                            failed to set up. A reload of
                                            something already broken
                                            cannot make it more broken.

**There is no power-cycling of anything, and no Claude run anywhere in
this file.** Both were on the roadmap page and both are deliberately not
here: switching a plug off and on again is an action whose failure mode
is a freezer, and a model choosing what to restart is a guess wearing a
remediation.

**Verification is free, and it is the only kind worth having.** Nothing
here reads back whether the call worked, because the call returning 200
is the Supervisor accepting a request — the distinction BRight draws
between a `play_media` call and a speaker making a sound. What proves a
heal is the *next checks pass*: the finding clears, or it does not, and
the morning brief says which.

Six rules, each of them a refusal:

**Off by default.** `self_healing` ships `false`. Nothing here runs until
somebody switched it on.

**Only in the window.** Once a night, inside quiet hours; where quiet
hours are unset, an hour after the settle time `rhythm` has measured;
where there is no rhythm yet, **not at all** — and the diagnostics say
so, because a self-healer that has never run looks exactly like one that
had nothing to do.

**One attempt per finding per night**, keyed on the finding's id and
written to disk before the next one is tried, so a restart at three in
the morning does not start the same add-on twice. The unit is the
*finding* rather than the target because the finding is what clears, and
the clearing is the verification: a house with three add-ons down gets
one started and keeps its row, which is the honest bounded answer.

**Never more than `MAX_PER_NIGHT`.** A house with nine broken things at
once is not a house to fix unattended; it is a house to look at.

**Never on a protected entity, area or device.** `protected_entities` is
enforced at the MCP server's `call_service`, and neither a Supervisor
request nor an unattended service call from this loop is one of its
callers — so this asks the same question with the same patterns
`automation_writer` uses. An attempt whose targets cannot be resolved to
plain entities is **skipped, not guessed**: a wrong expansion here would
act on something somebody said not to touch, which is the one mistake
the list exists to prevent.

**Never a finding a person has touched.** Only `open` rows, never
`fixing`, `fixed` or snoozed. Somebody who pressed *Fix it* on Tuesday is
mid-conversation with brAIn about that row.

Stdlib plus the two callers' own transports, imported inside the
functions that need them, so the module stays importable without the
add-on runtime.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import time
from pathlib import Path

import atomic_write

log = logging.getLogger("brain.healing")

STORE = Path(os.environ.get("BRAIN_HEALING_FILE", "/data/healing.json"))
SUPERVISOR_API = os.environ.get("BRAIN_SUPERVISOR_API", "http://supervisor")

# Three is not a budget, it is a ceiling on how wrong one night can go.
MAX_PER_NIGHT = 3
# How long the Supervisor gets to take a start request. Starting an
# add-on is not instant and the request blocks until it has: this is a
# ceiling on a hang, not a budget for a success.
CALL_TIMEOUT_S = 60
# What a night is, in hours before local midnight. A pass at 03:00 and a
# pass at 23:00 belong to different calendar days and the same night, and
# the once-a-night key has to agree with the way people say it.
NIGHT_PIVOT_H = 12
# How long the window stays open once it opens, where it is derived from
# the settle time rather than from quiet hours. Same grace the morning
# brief uses, for the same reason: a panel restarted at 04:00 must not
# heal at lunchtime.
SETTLE_GRACE_MIN = 45
# And how long after the house settles. Bedtime is when people are still
# moving about; an hour later is when the house is actually quiet.
SETTLE_OFFSET_MIN = 60

# The outcome words this file writes to the run journal. Kept beside the
# store so the vocabulary and the thing it describes are one file.
OUTCOME_OK = "healed"
OUTCOME_FAIL = "heal_failed"
OUTCOME_SKIP = "heal_skipped"


def _now() -> float:
    return time.time()


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------

def night_key(local: dt.datetime) -> str:
    """Which night an instant belongs to, as `YYYY-MM-DD`.

    Shifted back by half a day, so 23:40 on Monday and 03:10 on Tuesday
    are the same night. A key that changed at midnight would let a pass
    at 23:50 and a pass at 00:10 both run, twenty minutes apart, which is
    exactly the duplicate the key exists to prevent.
    """
    return (local - dt.timedelta(hours=NIGHT_PIVOT_H)).strftime("%Y-%m-%d")


def window(local: dt.datetime, quiet_start: int | None, quiet_end: int | None,
           settle_minute: float | None) -> tuple[bool, str]:
    """Whether this is the moment, and the sentence for why not.

    Quiet hours first, because they are what somebody set: a house with a
    22→07 window has already said when it is asleep, and a second answer
    derived from the rhythm would disagree with it on the nights the two
    drift apart.

    With no quiet hours the settle time is the only measurement of when
    this house goes quiet, and an hour past it is when it actually is.
    With neither, this returns **False and says so** rather than picking
    an hour: a self-healer running at a number somebody typed nowhere is
    a self-healer acting on a guess about when nobody is looking.
    """
    import notify_router  # noqa: PLC0415 — panel-local, and the one
                          # implementation of "is it quiet here now"

    if quiet_start is not None and quiet_end is not None \
            and quiet_start != quiet_end:
        if notify_router.in_quiet_hours(local.timestamp(), quiet_start,
                                        quiet_end, local.tzinfo):
            return True, "inside quiet hours"
        return False, (f"outside quiet hours ({quiet_start:02d}:00–"
                       f"{quiet_end:02d}:00)")

    if settle_minute is None:
        return False, ("no quiet hours are set and this house's settle time "
                       + "has not been measured yet, so brAIn does not know "
                       + "when nobody is looking — set quiet hours, or wait "
                       + "for the rhythm to gather enough nights")

    target = (int(settle_minute) + SETTLE_OFFSET_MIN) % 1440
    minute_now = local.hour * 60 + local.minute
    if 0 <= (minute_now - target) <= SETTLE_GRACE_MIN:
        return True, "an hour after this house settles"
    return False, (f"outside the window — an hour after this house settles, "
                   f"which is {target // 60:02d}:{target % 60:02d}")


# ---------------------------------------------------------------------------
# The store
# ---------------------------------------------------------------------------

def load(path: Path | None = None) -> dict:
    """The last night's pass, or an empty one. Never raises.

    Every way of failing to read this reads as *no pass has run*, which
    costs at most one duplicate attempt at a remediation that is
    idempotent by construction — where a stamp wrongly read as "already
    done" would silently switch the whole feature off. Same trade
    `schedule_store` makes, and for the same reason.
    """
    try:
        data = json.loads((path or STORE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"night": "", "attempts": [], "skips": []}
    if not isinstance(data, dict):
        return {"night": "", "attempts": [], "skips": []}
    data.setdefault("night", "")
    data.setdefault("attempts", [])
    data.setdefault("skips", [])
    return data


def save(state: dict, path: Path | None = None) -> None:
    target = path or STORE
    if not target.parent.is_dir():
        return                       # a dev checkout has no /data
    try:
        atomic_write.write_json(target, state)
    except OSError as exc:
        log.warning("could not write the healing store: %s", exc)


def attempted_tonight(state: dict, night: str) -> set[int]:
    """The finding ids already tried this night."""
    if state.get("night") != night:
        return set()
    return {int(a.get("ts") or 0) for a in state.get("attempts") or []}


# ---------------------------------------------------------------------------
# Protection — the same question `automation_writer` asks, asked here too
# ---------------------------------------------------------------------------

def _protected_refusal(entity_ids, resolvable: bool,
                       patterns: list[str]) -> str | None:
    """Why this attempt may not be made, or None.

    `resolvable` is the caller saying whether it could work out what the
    call would touch at all. A `False` with a non-empty protected list is
    a refusal in as many words, because "I could not tell" and "nothing
    is protected" are different answers and only one of them is safe to
    act on — the conservatism `_meta_call_denied` and
    `automation_writer._protected_refusal` already apply to an area or a
    device target.
    """
    import automation_writer  # noqa: PLC0415 — panel-local

    if not patterns:
        return None
    if "*" in patterns:
        # Somebody has said brAIn may not act on this house. An add-on or
        # a config entry is not an entity and so cannot match anything
        # narrower, but `*` is not a pattern about entities — it is the
        # whole answer.
        return "everything is on the protected entities list"
    if not resolvable:
        return ("brAIn could not work out which entities this would touch, "
                "and protected entities are set")
    for eid in entity_ids or []:
        if automation_writer.is_protected(str(eid), patterns):
            return f"{eid} is on the protected entities list"
    return None


# ---------------------------------------------------------------------------
# The three remediations
# ---------------------------------------------------------------------------

def _addon_targets(snap: dict) -> list[dict]:
    """The add-ons that were set to start at boot and are not running.

    An add-on in an **error** state is excluded here as well as by the
    row that names it: the Supervisor could not start it, or it started
    and exited, and asking again is asking for the same answer. That is
    the case for a person and a log, not for a loop at 3am.
    """
    out = []
    for a in (snap.get("supervisor") or {}).get("addons") or []:
        if not isinstance(a, dict) or not a.get("installed", True):
            continue
        slug = str(a.get("slug") or "")
        state = str(a.get("state") or "")
        if not slug or state in ("started", "error", ""):
            continue
        if str(a.get("boot") or "") != "auto":
            continue
        out.append({"slug": slug,
                    "label": str(a.get("name") or slug)})
    return sorted(out, key=lambda r: r["slug"])


def _addon_attempts(finding: dict, snap: dict, patterns: list[str]) -> list[dict]:
    from checks import system as sys_checks  # noqa: PLC0415

    # The row's text is its identity: the store dedupes on it, so it is
    # the one stable id a finding has. `addon_down` files two rows and
    # only one of them is startable.
    if str(finding.get("text") or "") != sys_checks.ADDON_STOPPED_TEXT:
        return []
    out = []
    for target in _addon_targets(snap):
        # An add-on is a container, not an entity, and expanding a slug
        # into the entities the `hassio` integration created for it means
        # matching on a unique_id shape nothing guarantees. So it is not
        # expanded: there is nothing to resolve, and `*` — which is not a
        # claim about entities at all — is what stands this down.
        out.append({
            "remedy": "addon.start",
            "verb": "start",
            "kind": "supervisor",
            "path": f"/addons/{target['slug']}/start",
            "target": target["slug"],
            "label": target["label"],
            "entities": [],
            "resolvable": True,
            "sentence": f"started the {target['label']} add-on",
        })
    return out


def _zwave_attempts(finding: dict, snap: dict, patterns: list[str]) -> list[dict]:
    from checks.devices import zwave_dead_nodes  # noqa: PLC0415

    house_entities = snap.get("entities") or []
    by_device: dict[str, list[str]] = {}
    for e in house_entities:
        dev = e.get("device_id")
        if dev and e.get("entity_id"):
            by_device.setdefault(dev, []).append(e["entity_id"])

    out = []
    for node in zwave_dead_nodes(snap):
        # Everything on the node's own device, not only the sensor being
        # pinged: a ping reaches the box, and the box may be a lock.
        touched = sorted(set(by_device.get(node["device_id"], []))
                         | {node["entity_id"]})
        out.append({
            "remedy": "zwave.ping",
            "verb": "ping",
            "kind": "service",
            "domain": "zwave_js",
            "service": "ping",
            "data": {"entity_id": node["entity_id"]},
            "target": node["entity_id"],
            "label": node["name"],
            "entities": touched,
            "resolvable": True,
            "sentence": f"pinged the Z-Wave node {node['name']}",
        })
    return out


def _entry_attempts(finding: dict, snap: dict, patterns: list[str]) -> list[dict]:
    from checks import system as sys_checks  # noqa: PLC0415

    rows = snap.get("entities") or []
    # Whether the entity registry in this snapshot carries the link at
    # all. An older Core does not, and then nothing here can say which
    # entities an entry owns — which is a refusal, not an empty list.
    linked = any("config_entry_id" in e for e in rows)
    out = []
    for entry in sys_checks.failed_entries(snap):
        entry_id = str(entry.get("entry_id"))
        owned = sorted(e["entity_id"] for e in rows
                       if e.get("entity_id")
                       and e.get("config_entry_id") == entry_id)
        name = sys_checks.entry_name(entry)
        out.append({
            "remedy": "entry.reload",
            "verb": "reload",
            "kind": "service",
            # The documented service, so this rides the same
            # `call_core_service` the accept path uses — one place that
            # validates a domain and a service name against the shape one
            # can have, rather than a second hand-built URL.
            "domain": "homeassistant",
            "service": "reload_config_entry",
            "data": {"entry_id": entry_id},
            "target": entry_id,
            "label": name,
            "entities": owned,
            "resolvable": linked,
            "sentence": f"reloaded the {name} integration",
        })
    return out


# The closed playbook. A source that is not a key here is a finding
# nothing may heal, which is every other producer in the add-on.
#
# `NEEDS` is the same claim `checks.run_all` makes about a check, in the
# half that acts: a snapshot key that could not be fetched means **I
# could not look**, which is a skip rather than "nothing matches this row
# any more". Without it a Supervisor that did not answer would read as
# every add-on having come back.
REMEDIES = {
    "check:sys.addon_down": _addon_attempts,
    "check:dev.zwave_dead": _zwave_attempts,
    "check:sys.entry_failed": _entry_attempts,
}
NEEDS = {
    "check:sys.addon_down": ("supervisor",),
    "check:dev.zwave_dead": ("states", "registry"),
    "check:sys.entry_failed": ("config_entries", "registry"),
}


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------

def eligible(finding: dict, now: float) -> str:
    """Why this row may not be healed, or `""`.

    A separate function because every one of these is a refusal somebody
    could disagree with, and a refusal buried inside a loop is a refusal
    nothing can test on its own.
    """
    status = str(finding.get("status") or "open")
    if status != "open":
        return f"a person has already answered this one ({status})"
    if int(finding.get("snoozed_until") or 0) > now:
        return "it is snoozed"
    if str(finding.get("source") or "") not in REMEDIES:
        return "nothing in the playbook heals this"
    return ""


def plan(findings: list[dict], snap: dict, patterns: list[str],
         done: set[int] | None = None, max_actions: int = MAX_PER_NIGHT,
         now: float | None = None) -> dict:
    """What tonight would do, and everything it will not do and why.

    Pure: it reads a snapshot and a list of findings and calls nothing.
    The split `baselines.py`, `closures.py` and `thermal.py` keep — a
    planner that also acted would be two rules in one place with the
    refusals invisible.
    """
    now = _now() if now is None else now
    done = done or set()
    attempts: list[dict] = []
    skips: list[dict] = []

    def skip(row: dict, why: str) -> None:
        skips.append({"ts": int(row.get("ts") or 0),
                      "source": str(row.get("source") or ""),
                      "text": str(row.get("text") or "")[:120],
                      "reason": why})

    # Oldest first, so a night that hits the cap takes the same three
    # every time rather than whatever order the store happened to be in.
    for row in sorted(findings or [], key=lambda f: int(f.get("ts") or 0)):
        why = eligible(row, now)
        if why:
            # A row nothing heals is not a skip worth recording — every
            # finding in the house would be one, and a list of them is a
            # list nobody reads.
            if str(row.get("source") or "") in REMEDIES:
                skip(row, why)
            continue
        ts = int(row.get("ts") or 0)
        if ts in done:
            skip(row, "already tried tonight")
            continue

        missing = [k for k in NEEDS.get(row["source"], ())
                   if not (snap.get("available") or {}).get(k)]
        if missing:
            # See `NEEDS`. This is not "the problem went away".
            skip(row, "brAIn could not read " + ", ".join(missing)
                 + " this pass, so it did not try")
            continue

        found = REMEDIES[row["source"]](row, snap, patterns)
        if not found:
            skip(row, "nothing in the house matches this row any more")
            continue
        # One attempt per finding. See the module docstring: the finding
        # is the unit that clears, and the clearing is the verification.
        candidate = found[0]
        refusal = _protected_refusal(candidate.get("entities"),
                                     bool(candidate.get("resolvable")),
                                     patterns)
        if refusal:
            skip(row, refusal)
            continue
        if len(attempts) >= max_actions:
            skip(row, f"tonight's limit of {max_actions} is already used")
            continue
        attempts.append({**candidate, "ts": ts,
                         "source": str(row.get("source") or ""),
                         "text": str(row.get("text") or "")[:120]})
    return {"attempts": attempts, "skips": skips}


# ---------------------------------------------------------------------------
# Doing it
# ---------------------------------------------------------------------------

async def perform(session, attempt: dict) -> tuple[bool, str]:
    """Make the one call. Returns `(ok, why not)` and never raises.

    A failure is recorded and **not retried tonight**, which needs no
    machinery: the attempt is written to the store whatever happened to
    it, and the store is what the next pass reads.
    """
    kind = str(attempt.get("kind") or "")
    try:
        if kind == "supervisor":
            import aiohttp  # noqa: PLC0415

            url = f"{SUPERVISOR_API}{attempt['path']}"
            headers = {"Authorization":
                       f"Bearer {os.environ.get('SUPERVISOR_TOKEN', '')}"}
            async with session.post(
                url, headers=headers,
                timeout=aiohttp.ClientTimeout(total=CALL_TIMEOUT_S),
            ) as resp:
                if resp.status >= 400:
                    body = (await resp.text())[:200]
                    return False, f"the Supervisor answered {resp.status}: {body}"
                return True, ""
        if kind == "service":
            import ha_data  # noqa: PLC0415

            await ha_data.call_core_service(
                attempt["domain"], attempt["service"],
                dict(attempt.get("data") or {}), timeout=CALL_TIMEOUT_S)
            return True, ""
    except Exception as exc:  # noqa: BLE001 — every way a call can fail is
        # the same answer to the morning: it did not take.
        return False, f"{type(exc).__name__}: {exc}"[:200]
    return False, f"brAIn does not know how to make a {kind!r} call"


# ---------------------------------------------------------------------------
# What the morning says
# ---------------------------------------------------------------------------

def brief_lines(state: dict, open_ids: set[int], tz=None,
                limit: int = 3) -> list[str]:
    """One sentence per attempt, and whether it stuck.

    Composed here rather than in `brief.py` because the sentence needs
    the house's own clock and this file's vocabulary, and `brief.py`
    holds neither. **Whether it stuck is the finding still being open** —
    the next checks pass is the only verification there is, so a heal
    that cannot be checked yet says the honest thing rather than
    claiming success.
    """
    out = []
    for a in (state.get("attempts") or [])[:limit]:
        when = dt.datetime.fromtimestamp(
            float(a.get("at") or 0), tz or dt.timezone.utc).strftime("%H:%M")
        sentence = str(a.get("sentence") or "made a change")
        if not a.get("ok"):
            out.append(f"brAIn tried to fix something overnight and could "
                       f"not: it {sentence} at {when} — "
                       f"{a.get('error') or 'the call failed'}")
            continue
        stuck = int(a.get("ts") or 0) not in open_ids
        out.append(f"brAIn {sentence} at {when}; "
                   + ("it is working now" if stuck
                      else "it has not cleared yet"))
    return out


__all__ = [
    "CALL_TIMEOUT_S", "MAX_PER_NIGHT", "OUTCOME_FAIL", "OUTCOME_OK",
    "NEEDS", "OUTCOME_SKIP", "REMEDIES", "SETTLE_GRACE_MIN",
    "SETTLE_OFFSET_MIN",
    "STORE", "SUPERVISOR_API", "attempted_tonight", "brief_lines",
    "eligible", "load", "night_key", "perform", "plan", "save", "window",
]
