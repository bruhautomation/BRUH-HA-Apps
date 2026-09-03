"""Is brAIn working — one verdict, and the sentence that goes with it.

`brain doctor` answers this when somebody runs it. Nothing answered it
the rest of the time, which is the whole gap: the failures this add-on
has actually shipped were quiet ones — a listener that died, a credential
that expired on a Tuesday, a consolidator running and landing nothing —
and every one of them was visible from inside the add-on hours before
anybody noticed from outside it.

Four rules shape what is here.

**A verdict is a state and a sentence, never a score.** One number over a
house hides its worst problem inside an average, and an average that
moves from 92 to 88 is not something anybody can act on. The state is the
worst thing found, the reason names that thing, and the whole list rides
along underneath.

**Every problem names the switch, not the symptom.** "degraded" on its
own sends somebody to the log; "the automation listener is not running —
turn on `enable_automations`, or its exit is in the add-on log" sends
them to the thing that fixes it.

**Optional is not broken.** The daemon roll-call is deliberately
descriptive — a house with the terminal switched off has no ttyd and
nothing is wrong — so the interpretation happens here, against the
options, and a daemon nothing asked for is never a fault.

**"I could not look" is its own answer.** A missing figure is reported as
unknown rather than folded in as healthy; the same rule the checks
snapshot applies to every key it fetches. The one exception is the panel
itself: whoever is reading this verdict got it from the panel, so a
verdict that could not be built at all is `failed` by construction, and
that is what the mirror's own age answers for a reader who is not the
panel.
"""
from __future__ import annotations

import time

# The three states, worst last. `sensor.brain_health` carries one of these
# as its state, so they are a closed vocabulary and an automation may key
# on them.
STATES = ("ok", "degraded", "failed")

# A checks pass this far past its own interval has stopped happening.
# Three intervals rather than one: a pass takes minutes, a Pi under load
# takes longer, and a health sensor that cries wolf on a slow morning is a
# health sensor people disable.
CHECKS_OVERDUE_FACTOR = 3.0
# The consolidator runs every five minutes and files when there is
# something to file. A day and a bit with nothing landing is the same
# threshold the stale-queue warning uses.
CONSOLIDATION_STALE_H = 26.0
# Below this many runs, a failure rate is an anecdote.
MIN_RUNS_FOR_RATE = 6
FAILURE_RATE_DEGRADED = 0.5
# The mirror is rewritten after every checks pass and hourly in between.
# Twice that is a panel that has stopped writing.
MIRROR_STALE_H = 2.5

# Which daemons matter, and what turns each one on. A daemon whose option
# is off is not missing; it was not asked for.
DAEMONS = {
    "usage_tracker": {
        "always": True,
        "what": "the usage tracker",
        "fix": "It reports your Claude usage. Restart the add-on; if it "
               "stays down, its error is in the add-on log.",
        "severity": "degraded",
    },
    "memory_consolidator": {
        "always": True,
        "what": "the memory consolidator",
        "fix": "Nothing is filing what brAIn learns into memory.md. "
               "Restart the add-on.",
        "severity": "degraded",
    },
    "study_watcher": {
        "always": True,
        "what": "the study watcher",
        "fix": "Study requests from the ask bar will not be picked up. "
               "Restart the add-on.",
        "severity": "degraded",
    },
    "automation_listener": {
        "option": "enable_automations",
        "what": "the automation listener",
        "fix": "brain.run_task and brain.send_prompt will time out with "
               "nothing reading them. Restart the add-on; if it stays "
               "down, its exit is in the add-on log.",
        "severity": "failed",
    },
    "ttyd": {
        "option": "enable_terminal",
        "what": "the terminal",
        "fix": "The Terminal tab's classic face has nothing behind it. "
               "Restart the add-on.",
        "severity": "degraded",
    },
}


def _problem(state: str, what: str, fix: str, key: str) -> dict:
    return {"state": state, "what": what, "fix": fix, "id": key}


def _assist_daemon(diag: dict, options: dict) -> list[dict]:
    """The assist channel is one job with two implementations.

    Either the worker pool or the classic listener answers voice, and
    which one depends on `assist_fast_mode` — so asking after both by
    name would report the one that is correctly absent. What matters is
    that *something* is listening.
    """
    if not options.get("enable_assist"):
        return []
    daemons = diag.get("daemons") or {}
    if not daemons:
        return []
    alive = any((daemons.get(name) or {}).get("running")
                for name in ("assist_worker_pool", "assist_listener"))
    if alive:
        return []
    return [_problem(
        "failed", "nothing is listening for voice",
        "Assist is switched on and neither the worker pool nor the classic "
        "listener is running. Restart the add-on; the reason it exited is "
        "in the add-on log.", "assist")]


def problems(diag: dict, options: dict | None = None,
             now: float | None = None) -> list[dict]:
    """Everything wrong, worst first. Empty is a healthy add-on."""
    now = time.time() if now is None else now
    options = options or diag.get("options") or {}
    found: list[dict] = []

    auth = diag.get("auth") or {}
    if auth.get("state") not in (None, "ok", "checking"):
        found.append(_problem(
            "failed", "Claude is not signed in",
            "Nothing that needs a Claude turn can run — insights, the chat, "
            "voice and the consolidator all stop. Open Settings and sign in "
            "again." + (f" ({auth['error']})" if auth.get("error") else ""),
            "auth"))

    daemons = diag.get("daemons") or {}
    if daemons:
        for name, spec in DAEMONS.items():
            if not spec.get("always") and not options.get(spec["option"]):
                continue
            if (daemons.get(name) or {}).get("running"):
                continue
            found.append(_problem(spec["severity"], spec["what"] + " is not running",
                                  spec["fix"], f"daemon:{name}"))
    found.extend(_assist_daemon(diag, options))

    consol = (daemons.get("memory_consolidator") or {})
    age = consol.get("last_pass_hours_ago")
    # A missing marker is a fresh install, not a stale one — reported by
    # the field's absence rather than by a made-up number.
    if isinstance(age, (int, float)) and age > CONSOLIDATION_STALE_H:
        found.append(_problem(
            "degraded", "nothing has been filed into memory recently",
            f"The last consolidation pass landed {int(age)} hours ago. The "
            "consolidator is running, so it is finding nothing to file or "
            "failing every pass — the add-on log says which.",
            "consolidation"))

    last = diag.get("checks") or {}
    if last.get("error"):
        found.append(_problem(
            "degraded", "the last house-checks pass failed",
            f"{last['error']} The Findings tab is serving whatever the last "
            "good pass found. Press 'Run checks now' to see it happen.",
            "checks"))
    interval = _num(options.get("checks_interval_hours"))
    finished = _num(last.get("finished_at"))
    if interval and finished:
        overdue_h = (now - finished) / 3600.0
        if overdue_h > interval * CHECKS_OVERDUE_FACTOR:
            found.append(_problem(
                "degraded", "the house checks have stopped running",
                f"The last pass was {int(overdue_h)} hours ago on a "
                f"{interval:g}-hour interval. Nothing is watching for a flat "
                "battery or a dead automation. Restart the add-on.",
                "checks_overdue"))

    journal = diag.get("journal") or {}
    runs = _num(journal.get("runs")) or 0
    by_outcome = journal.get("by_outcome") or {}
    failures = sum(n for outcome, n in by_outcome.items() if outcome != "ok")
    if runs >= MIN_RUNS_FOR_RATE and failures / runs >= FAILURE_RATE_DEGRADED:
        worst = max((o for o in by_outcome if o != "ok"),
                    key=lambda o: by_outcome[o], default="error")
        found.append(_problem(
            "degraded", "most Claude runs are failing",
            f"{failures} of {int(runs)} runs in the last day did not "
            f"succeed, most often '{worst}'. The Diagnostics section under "
            "the settings dialog lists the last few with their reasons.",
            "runs"))

    usage = diag.get("usage") or {}
    if usage.get("limits"):
        found.append(_problem(
            "degraded", "usage figures are not being reported",
            "The pill is showing brAIn's own local estimate rather than "
            "your account's real usage. Press the pill for what the tracker "
            "last said and when it tries again.",
            "usage"))

    order = {s: i for i, s in enumerate(STATES)}
    found.sort(key=lambda p: -order[p["state"]])
    return found


def verdict(diag: dict, options: dict | None = None,
            now: float | None = None) -> dict:
    """The whole answer: a state, the sentence for the worst thing, and
    everything else underneath.

    ``ok`` really means ok. A verdict that hedges — "mostly fine" — is one
    nobody reads twice, and this is the entity somebody puts on a
    dashboard precisely so they can stop checking.
    """
    found = problems(diag, options, now)
    state = found[0]["state"] if found else "ok"
    return {
        "state": state,
        "reason": found[0]["what"] if found else "everything brAIn runs is running",
        "fix": found[0]["fix"] if found else "",
        "problems": found,
        "checked_at": int(time.time() if now is None else now),
        # How long this answer is good for, published rather than agreed:
        # the integration reads it out of a file and has to know when to
        # stop believing it, and a second copy of the number on that side
        # is a second copy that drifts.
        "stale_after_h": MIRROR_STALE_H,
    }


def from_mirror(diag: dict | None, mirror_age_h: float | None,
                now: float | None = None) -> dict:
    """The verdict a reader OUTSIDE the panel gets, mirror age included.

    The integration reads a file the panel writes, so it has one question
    the panel does not: is this still true? A stale mirror is not a
    healthy add-on with old numbers — it is a panel that has stopped
    writing, and reporting the last good verdict would be a reading
    nothing can correct. Same failure the usage sensors had.
    """
    if not diag:
        return {"state": "failed",
                "reason": "brAIn has not published its state",
                "fix": "The add-on may be starting, stopped, or unable to "
                       "write to /config/.brain. Check that it is running.",
                "problems": [], "checked_at": int(time.time() if now is None else now)}
    out = verdict(diag, None, now)
    if mirror_age_h is not None and mirror_age_h > MIRROR_STALE_H:
        stale = _problem(
            "failed", "brAIn has stopped publishing its state",
            f"The last update was {mirror_age_h:.1f} hours ago. The panel "
            "writes this after every checks pass and hourly in between, so "
            "it is not running. Check the add-on is started.", "mirror")
        out["problems"] = [stale] + out["problems"]
        out["state"] = "failed"
        out["reason"] = stale["what"]
        out["fix"] = stale["fix"]
    return out


def _num(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
