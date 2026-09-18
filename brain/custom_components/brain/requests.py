"""An answer given inside Home Assistant, on its way to the add-on.

Two surfaces here can end a finding — a tick in the To-do app, a button
on a notification — and neither can reach the panel that owns the
findings store. Port 8099 is `null` in the add-on's `ports:` on purpose
(an unpublished port is the only kind that cannot answer the LAN without
a login in front of it), and it is going to stay that way.

So this writes a **request**, not a change: a small JSON file on the
shared volume the add-on already publishes its mirror to. The add-on
picks it up within seconds and applies it through the same code the
Findings tab's own buttons use, which is what stops a tick in the To-do
app teaching brAIn something different from the identical press on the
tab.

Three details are load-bearing:

* **The write is atomic** — a temporary name in the same directory, then
  a rename — because the add-on globs `*.json` and would otherwise be
  able to read half a request.
* **The name sorts chronologically**, so the add-on drains oldest first
  and a backlog is answered in the order the answers were given — the
  millisecond stamp alone does not give that, because several ticks in
  one burst land inside the same millisecond, so a process-lifetime
  counter breaks the tie.
* **Nothing here waits for a result.** The add-on may be stopped; the
  request sits until it is not. Blocking a To-do tick on an add-on that
  is not running would make the list unusable rather than merely stale.
"""

from __future__ import annotations

import json
import logging
import os
import itertools
import time
import uuid

from homeassistant.core import HomeAssistant

from .const import (ACTION_PREFIX, FINDING_REQUESTS_DIRNAME,
                    INTENT_REQUESTS_DIRNAME, SHARED_DIR)

_LOGGER = logging.getLogger(__name__)

ACTIONS = ("fixed", "wrong", "snooze")

# What can be asked of the to-do list from out here. They are the tab's
# own presses and nothing new: tick one off, take it off the list, put a
# new one on. `add` is the one that carries text instead of an id, which
# is why the writer takes both and checks which the action needs.
TODO_ACTIONS = ("done", "drop", "add")

# Breaks the tie between answers given inside one millisecond.
# A restart resets it, which cannot matter: the millisecond
# stamp in front of it has moved on by then.
_SEQUENCE = itertools.count()


def parse_action(identifier: str) -> tuple[str, int] | None:
    """`"brain.fixed.1720"` as `("fixed", 1720)`, or None for anything else.

    The companion app fires one event for every actionable notification
    in the house, brAIn's and everybody else's, so this rejects far more
    than it accepts.

    It lives here rather than in the integration's `__init__` for one
    reason: this module imports `homeassistant.core` and nothing else, so
    a test can drive the add-on's own writer straight into it. The two
    processes cannot import each other, and a wire format written down
    twice with only one side tested is a format that drifts.
    """
    parts = str(identifier or "").split(".")
    if len(parts) != 3 or parts[0] != ACTION_PREFIX:
        return None
    if parts[1] not in ACTIONS:
        return None
    try:
        return parts[1], int(parts[2])
    except (TypeError, ValueError):
        return None


def requests_dir(hass: HomeAssistant) -> str:
    return hass.config.path(SHARED_DIR, FINDING_REQUESTS_DIRNAME)


def write_request(hass: HomeAssistant, ts: int, action: str,
                  note: str = "", via: str = "", hours: float = 0) -> bool:
    """Drop one request. Returns whether it landed.

    Blocking: call it from the executor. A failure is logged and returned
    rather than raised — the surfaces that call this are a to-do item and
    a notification button, and neither has anywhere useful to show an
    exception.
    """
    if action not in ACTIONS:
        _LOGGER.warning("refusing to write an unknown finding action: %s", action)
        return False
    body = {"ts": int(ts), "action": action, "note": str(note or "")[:500],
            "via": str(via or "")[:32]}
    if hours:
        body["hours"] = float(hours)
    return _drop(hass, requests_dir(hass), body,
                 what=f"the answer for finding {ts}")


def write_todo_request(hass: HomeAssistant, action: str, *, item_id: int = 0,
                       text: str = "", note: str = "", via: str = "") -> bool:
    """Drop one request about the to-do list. Returns whether it landed.

    Same directory and same drain as a finding's answer, with a ``kind``
    naming which store it is about. A second directory was the obvious
    shape and is the wrong one: these arrive from the same two surfaces,
    in an order that matters between them (ticking off an item brAIn has
    just created), and two queues sorted into one at the far end is the
    arrangement `INTENT_REQUESTS_DIRNAME` exists because it is NOT.

    An id is required for everything except `add`, which has no item yet
    — checked here rather than left to the add-on, because a request that
    can never be applied should not be written.
    """
    if action not in TODO_ACTIONS:
        _LOGGER.warning("refusing to write an unknown to-do action: %s", action)
        return False
    text = str(text or "").strip()[:200]
    if action == "add" and not text:
        _LOGGER.warning("refusing to add an empty to-do")
        return False
    if action != "add" and not item_id:
        _LOGGER.warning("refusing a to-do %s with no item", action)
        return False
    body = {"kind": "todo", "action": action, "id": int(item_id),
            "text": text, "note": str(note or "")[:500],
            "via": str(via or "")[:32]}
    return _drop(hass, requests_dir(hass), body, what=f"to-do {action}")


def write_checks_request(hass: HomeAssistant, via: str = "") -> bool:
    """Ask the add-on to run its house checks now. Returns whether it landed.

    A third kind on one queue, and it rides here rather than in a
    directory of its own for `write_todo_request`'s reason turned up a
    notch: the ORDER between kinds matters. An ending given a second
    before this — "I've fixed it", from the same phone, in the same
    burst — has to be applied before the pass runs, or the pass re-files
    what was just settled and the answer reads as having been ignored.
    Two queues sorted into one at the far end is the arrangement that
    cannot promise that.

    It carries no id because it is not about a row: everything the
    add-on needs is the word `checks`, and `via` for the log line.
    """
    return _drop(hass, requests_dir(hass), {"kind": "checks",
                                            "via": str(via or "")[:32]},
                 what="a house checks pass")


def _drop(hass: HomeAssistant, directory: str, body: dict,
          *, what: str) -> bool:
    """The write itself: atomic, chronologically named, never waited on.

    Lifted out of `write_request` when the to-do half arrived rather than
    copied into it — the three rules in this module's docstring are one
    implementation or they are two that drift, and the atomic rename is
    exactly the kind of detail a copy gets subtly wrong.
    """
    name = (f"{int(time.time() * 1000):013d}"
            f"-{next(_SEQUENCE):06d}-{uuid.uuid4().hex[:8]}.json")
    target = os.path.join(directory, name)
    scratch = target + ".tmp"
    try:
        os.makedirs(directory, exist_ok=True)
        with open(scratch, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(body))
        # The add-on globs "*.json", so the scratch name is invisible to
        # it until this rename makes the file whole and visible at once.
        os.replace(scratch, target)
    except OSError as exc:
        _LOGGER.warning("could not record %s: %s", what, exc)
        try:
            os.unlink(scratch)
        except OSError:
            # There may be no scratch file to remove — the failure above
            # is usually the `open` itself — and if there is one, the
            # add-on cannot see it: it globs "*.json".
            pass
        return False
    return True


# ---------------------------------------------------------------------------
# One-off intents — the same shape, a different drop
# ---------------------------------------------------------------------------

def intent_requests_dir(hass: HomeAssistant) -> str:
    return hass.config.path(SHARED_DIR, INTENT_REQUESTS_DIRNAME)


def write_intent(hass: HomeAssistant, sentence: str, via: str = "") -> bool:
    """Drop one sentence for the add-on to turn into a one-off automation.

    `write_request`'s three rules, for the same three reasons — the
    atomic rename because the add-on globs `*.json`, the chronological
    name because a backlog is answered in the order it was given, and no
    waiting because the add-on may be stopped and a voice command must
    not hang on that.

    It is `brain.intent`'s half of a wire format the add-on's
    `intents.request` writes the other half of, and `tests/test_intents.py`
    drives this one straight into the add-on's parser rather than writing
    the shape down twice.
    """
    text = str(sentence or "").strip()[:300]
    if not text:
        _LOGGER.warning("refusing to queue an empty intent")
        return False
    directory = intent_requests_dir(hass)
    name = (f"{int(time.time() * 1000):013d}"
            f"-{next(_SEQUENCE):06d}-{uuid.uuid4().hex[:8]}.json")
    target = os.path.join(directory, name)
    scratch = target + ".tmp"
    body = {"ts": int(time.time()), "sentence": text,
            "via": str(via or "")[:32]}
    try:
        os.makedirs(directory, exist_ok=True)
        with open(scratch, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(body))
        os.replace(scratch, target)
    except OSError as exc:
        _LOGGER.warning("could not queue the one-off intent: %s", exc)
        try:
            os.unlink(scratch)
        except OSError:
            pass                     # see write_request: usually no scratch
        return False
    return True
