"""Is brAIn working? One state and one sentence, for every surface.

The status line on Today, `sensor.brain_status` in Home Assistant and the
`status` object on `/api/status` all read this one derivation. Before it,
"restart required" was a Repairs entry and a buried line in ⚙, "paused"
was a chip, the health verdict was a sensor, and the four disagreed: the
health sensor said `ok` while Diagnostics said degraded, and nothing said
Home Assistant was still running last release's integration.

Five states, most pressing first — the first that applies wins:

``signed_out``     no Claude credential, or the last check of it failed:
                   nothing brAIn does that needs a model can run.
``needs_restart``  the add-on deployed a newer integration than Home
                   Assistant has loaded.
``paused``         brAIn is deliberately not looking: switched off by the
                   owner, the account's usage limit, or the budget.
``degraded``       the health verdict is not ok.
``watching``       none of the above.

``unknown`` is the sixth answer and only the integration gives it — for a
mirror it could not read — because the panel always knows enough to
answer one of the five.

Pure over what it is handed, so the panel can gather the inputs once and
the tests can drive every branch without a server. Never raises.
"""

from __future__ import annotations

import time

STATES = ("watching", "paused", "needs_restart", "signed_out", "degraded")
LABELS = {
    "watching": "Watching",
    "paused": "Paused",
    "needs_restart": "Needs restart",
    "signed_out": "Signed out",
    "degraded": "Degraded",
    "unknown": "Unknown",
}


def ago(seconds: float) -> str:
    """'just now', '9 min ago', '3 h ago', '2 days ago'."""
    s = max(0.0, float(seconds or 0))
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{int(s // 60)} min ago"
    if s < 86400:
        return f"{int(s // 3600)} h ago"
    days = int(s // 86400)
    return f"{days} day{'s' if days != 1 else ''} ago"


def _sentence(text: str) -> str:
    text = " ".join(str(text or "").split()).strip()
    if not text:
        return ""
    text = text[0].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def derive(*, signed_in: bool, auth_state: str = "", auth_checked_at: float = 0,
           restart_pending: bool = False, restart_since: float = 0,
           auto_enabled: bool = True, rate_limit_until: float = 0,
           budget: dict | None = None, health: dict | None = None,
           last_look_at: float = 0, now: float | None = None,
           clock=None) -> dict:
    """The status. See the module docstring for the order.

    ``clock(ts) -> str`` renders a time of day in the house's style; a
    plain 24-hour clock when not given.

    Returns ``{state, label, sentence, since, back_at, last_look_at}``:
    ``since`` is when the state began where that is known, ``back_at``
    when a pause ends where that is known, both epoch seconds or None.
    """
    now = time.time() if now is None else float(now)
    if clock is None:
        def clock(ts: float) -> str:  # noqa: E306
            return time.strftime("%H:%M", time.localtime(ts))
    look = float(last_look_at or 0) or None
    out = {"state": "watching", "since": None, "back_at": None,
           "last_look_at": int(look) if look else None}

    def done(state: str, sentence: str, since=None, back_at=None) -> dict:
        out.update(state=state, label=LABELS[state],
                   sentence=_sentence(sentence),
                   since=int(since) if since else None,
                   back_at=int(back_at) if back_at else None)
        return out

    try:
        if not signed_in:
            return done("signed_out",
                        "Not signed in to Claude — sign in under ⚙ › Account")
        if auth_state == "failed":
            return done("signed_out",
                        "Claude sign-in stopped working — sign in again "
                        "under ⚙ › Account", since=auth_checked_at)
        if restart_pending:
            return done("needs_restart",
                        "Restart Home Assistant to finish updating brAIn",
                        since=restart_since)
        if not auto_enabled:
            return done("paused", "Paused: automatic looks are switched off")
        until = float(rate_limit_until or 0)
        if until > now:
            return done("paused",
                        f"Paused: Claude limit reached, back at {clock(until)}",
                        back_at=until)
        budget = budget or {}
        if budget.get("blocked"):
            back = float(budget.get("resets_at") or 0)
            back = back if back > now else 0
            text = "Paused: usage budget reached"
            if back:
                text += f", back at {clock(back)}"
            return done("paused", text, back_at=back or None)
        health = health or {}
        if health.get("state") in ("degraded", "failed"):
            reason = str(health.get("reason") or "something is not working")
            return done("degraded", f"Not working fully: {reason}",
                        since=health.get("since"))
        text = "Watching"
        if look:
            text += f" · last look {ago(now - look)}"
        out.update(state="watching", label=LABELS["watching"],
                   sentence=text)
        return out
    except Exception:  # noqa: BLE001 — a status that could not be composed
        # is still an answer; watching with no sentence is the least wrong.
        out.update(state="watching", label=LABELS["watching"],
                   sentence="Watching")
        return out


__all__ = ["LABELS", "STATES", "ago", "derive"]
