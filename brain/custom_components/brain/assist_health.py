"""Whether voice is answering, for `binary_sensor.brain_assist_healthy`.

No Home Assistant import, so the suite drives the rule directly — the
`house_state.py` arrangement.

It read on while Assist was down, for three reasons, and each is a rule:

**A pool that answers HTTP is not a pool going round.** The worker pool
serves `/health` from its own HTTP thread, which keeps answering `ok` while
the main loop that claims Assist's requests is wedged. The pool now says
how long ago that loop last went round (`loop_age_s`, and `status:
stalled` past the window); either one past `HEARTBEAT_FRESH_S` is off.

**A heartbeat is aged by its FILE, never by a stamp inside it.** A clock
corrected backwards leaves a `ts` in the future, and an age that is never
positive reads fresh for ever — `BrainHealthSensor`'s rule.

**The panel has already looked, and its answer is in the diagnostics
mirror.** A fresh verdict naming voice as down (`assist`, `assist_pool`)
turns this off; the mirror's roll-call is also the only route to a
classic-listener house, which has no pool to ask and used to see this
entity unavailable with no reason. A mirror past its own `stale_after_h`
says nothing either way.

It never goes unavailable: nothing to read is `None` (unknown) with a
`reason`, because Home Assistant hides an unavailable entity's attributes
and the reason is the point.
"""
from __future__ import annotations

# Held equal to the panel's `health.POOL_HEARTBEAT_STALE_S` by a test. The
# pool rewrites its heartbeat every 30s, so this is five missed beats.
HEARTBEAT_FRESH_S = 150
# The panel's own fallback for a mirror that does not publish its window.
MIRROR_STALE_H = 2.5
# The panel's health problem ids that mean voice is not answering.
VOICE_DOWN_IDS = ("assist", "assist_pool")
TELEMETRY = ("workers", "spare_ready", "uptime_s", "tool_access")


def _num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fresh_mirror(mirror, mirror_age_h):
    if not isinstance(mirror, dict) or mirror_age_h is None:
        return None
    health = mirror.get("health") if isinstance(mirror.get("health"), dict) else {}
    window = _num(health.get("stale_after_h")) or MIRROR_STALE_H
    return mirror if mirror_age_h <= window else None


def judge(*, http: dict | None = None, heartbeat: dict | None = None,
          heartbeat_age_s: float | None = None, mirror: dict | None = None,
          mirror_age_h: float | None = None, now: float | None = None
          ) -> tuple[bool | None, dict]:
    """`(is_on, attributes)`. `is_on` is None for "nothing says". Never raises."""
    del now  # every age is handed in already measured
    attrs: dict = {"transport": None}
    fresh = _fresh_mirror(mirror, mirror_age_h)

    def telemetry(status: dict) -> None:
        for key in TELEMETRY:
            if key in status:
                attrs[key] = status[key]
        last = status.get("last_request") or {}
        if isinstance(last, dict) and last:
            attrs["last_request_duration_s"] = last.get("duration_s")
            attrs["last_request_mode"] = last.get("mode")

    # 1. A live answer from the pool is the best evidence there is.
    if isinstance(http, dict):
        attrs["transport"] = "http"
        telemetry(http)
        loop_age = _num(http.get("loop_age_s"))
        if loop_age is not None:
            attrs["loop_age_s"] = int(loop_age)
        if http.get("status") != "ok" or (
                loop_age is not None and loop_age > HEARTBEAT_FRESH_S):
            mins = int((loop_age or 0) // 60)
            attrs["reason"] = (
                f"the voice worker pool answers but has not gone round in "
                f"{mins} minutes, so nothing is picking up what Assist asks"
                if loop_age is not None else
                f"the voice worker pool answered '{http.get('status')}'")
            return False, attrs
        return True, attrs

    # 2. The panel looked at its own processes and said voice is down.
    if fresh is not None:
        problems = (fresh.get("health") or {}).get("problems") or []
        for problem in problems:
            if isinstance(problem, dict) and problem.get("id") in VOICE_DOWN_IDS:
                attrs["transport"] = "panel"
                attrs["reason"] = str(problem.get("what") or "voice is down")
                return False, attrs

    # 3. The pool's heartbeat file, aged by its mtime.
    if isinstance(heartbeat, dict) and heartbeat_age_s is not None:
        attrs["transport"] = "file"
        telemetry(heartbeat)
        attrs["heartbeat_age_s"] = int(heartbeat_age_s)
        if heartbeat_age_s > HEARTBEAT_FRESH_S:
            attrs["reason"] = (
                f"the voice worker pool's heartbeat is "
                f"{int(heartbeat_age_s // 60)} minutes old")
            return False, attrs
        return True, attrs

    # 4. No pool to ask: the panel's roll-call answers for the listener.
    if fresh is not None:
        options = fresh.get("options") if isinstance(fresh.get("options"), dict) else {}
        daemons = fresh.get("daemons") if isinstance(fresh.get("daemons"), dict) else {}
        if options and not options.get("enable_assist_integration"):
            attrs["reason"] = "Assist is switched off in the add-on's options"
            return None, attrs
        listener = daemons.get("assist_listener") or {}
        pool = daemons.get("assist_worker_pool") or {}
        if listener.get("running"):
            attrs["transport"] = "listener"
            return True, attrs
        if daemons and not pool.get("running"):
            attrs["transport"] = "panel"
            attrs["reason"] = ("neither the voice worker pool nor the classic "
                               "listener is running")
            return False, attrs

    attrs["reason"] = ("brAIn has not said whether voice is answering — the "
                       "add-on may be starting or stopped")
    return None, attrs


__all__ = ["HEARTBEAT_FRESH_S", "VOICE_DOWN_IDS", "judge"]
