"""Which cameras brAIn may look at when nobody is in front of the panel.

A camera frame is the most private thing a house holds, and until 2.12
brAIn looked through them on two paths nobody had agreed to: the voice
prompt told every Assist turn to "check a camera" with `get_camera_snapshot`
whenever it liked, and the `camera_check` insight preset looked at every
camera in the house on a timer. Neither asked which cameras, and neither
was counted.

The rule is one list and one counter, and every unattended path answers to
both:

* **Opt-in, per camera** (`settings_store.camera_confirm`). Empty by
  default, so a house that never opens the setting has no camera brAIn
  looks at on its own. A person typing in the chat or the terminal is not
  an unattended path — they are the person looking — and is not asked.
* **A daily cap** (`PER_DAY` looks, across voice, tasks and the Resident),
  counted in a small ledger keyed on the house's own day. A ledger that
  cannot be read or written REFUSES, because a cap nobody can count is no
  cap, and the direction in which being wrong costs a look rather than a
  picture is the one to take.
* **The Resident looks only to confirm a safety trip or a closure**
  (`trip_kind`), and only in the investigation — the first look never
  holds the tool. Which cameras an investigation may use is a GRANT the
  panel hands the run (`grant_for`): the opted-in cameras in the same room
  as the thing that tripped, or every opted-in camera when none shares it.
* **The MCP server is the chokepoint** (`ha_mcp_server._camera_refusal`),
  and it asks this module through `POST /api/camera/permit` on every
  governed snapshot, so the grant, the list and the count are one answer
  rather than three copies in three processes.

Nothing here fetches a frame; it decides whether one may be fetched.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import atomic_write

LEDGER = Path(os.environ.get("BRAIN_CAMERA_USES", "/data/camera-uses.json"))
# How many cameras may be on the list. A house with more than this is
# asking brAIn to watch the house, which is a different product.
MAX_CAMERAS = 20
# Governed looks per house day, across every unattended path. A trip that
# needs more than a dozen frames to confirm is not being confirmed by
# frames; a voice assistant asked about the porch twelve times today has
# answered.
PER_DAY = 12
# Rows kept in the ledger: today's, plus enough of yesterday to say so.
MAX_ROWS = 200
_CAMERA_RE = re.compile(r"^camera\.[a-z0-9_]+$")
# The domains a closure is by domain alone (`closures.is_closure`'s own
# first answer); a binary sensor needs its device class, which the panel
# reads off the bus at the moment it is admitted.
CLOSURE_DOMAINS = ("lock", "cover")
CLOSURE_SOURCES = ("check:evening.left_open",)


def clean_cameras(value) -> list[str]:
    """A list of camera entity ids — trimmed, deduped, capped — or ValueError."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("camera_confirm must be a list of camera entity ids")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("every camera is an entity id")
        item = item.strip().lower()
        if not _CAMERA_RE.match(item):
            raise ValueError(f"{item!r} is not a camera entity id")
        if item not in out:
            out.append(item)
    if len(out) > MAX_CAMERAS:
        raise ValueError(f"at most {MAX_CAMERAS} cameras can be allowed")
    return out


def _read() -> tuple[list[dict], str]:
    """`(rows, error)`. A missing ledger is no looks yet; an unreadable one
    is an error, never zero — zero is the answer that lets a look through."""
    try:
        raw = LEDGER.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], ""
    except OSError as exc:
        return [], f"the camera ledger could not be read ({exc})"
    try:
        data = json.loads(raw)
    except ValueError:
        return [], "the camera ledger is not valid JSON"
    rows = data.get("uses") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return [], "the camera ledger is not in the shape brAIn writes"
    return [r for r in rows if isinstance(r, dict)], ""


def used(day: str) -> tuple[int, str]:
    """How many governed looks the house has spent on `day`, or an error."""
    rows, error = _read()
    if error:
        return 0, error
    return sum(1 for r in rows if r.get("day") == day), ""


def permit(entity_id: str, channel: str, grant: list[str] | None,
           opted_in: list[str], day: str, now: float) -> tuple[bool, str]:
    """`(allowed, reason)` for one look, recording it when allowed.

    The reasons are sentences a voice assistant can say out loud, because
    on that path they are what the person hears.
    """
    entity_id = str(entity_id or "").strip().lower()
    if not _CAMERA_RE.match(entity_id):
        return False, f"{entity_id or 'that'} is not a camera."
    if entity_id not in (opted_in or []):
        return False, (f"brAIn has not been allowed to look at {entity_id} on "
                       "its own. The homeowner can allow it in the brAIn panel "
                       "under ⚙ → Generation defaults → Cameras.")
    if grant is not None and entity_id not in grant:
        return False, (f"this run was only allowed to look at "
                       f"{', '.join(grant) or 'no camera'}.")
    rows, error = _read()
    if error:
        return False, (f"brAIn could not count today's camera looks, so it "
                       f"will not take one: {error}.")
    today = sum(1 for r in rows if r.get("day") == day)
    if today >= PER_DAY:
        return False, (f"brAIn has used today's {PER_DAY} camera looks; it can "
                       "look again tomorrow.")
    rows.append({"day": day, "ts": int(now), "entity_id": entity_id,
                 "channel": str(channel or "")[:16]})
    rows = rows[-MAX_ROWS:]
    try:
        LEDGER.parent.mkdir(parents=True, exist_ok=True)
        atomic_write.write_text(str(LEDGER), json.dumps({"uses": rows}))
    except OSError as exc:
        # A look nobody could count is a look past the cap for all anybody
        # knows. Refused, and said.
        return False, f"brAIn could not record a camera look, so it will not take one ({exc})."
    return True, ""


# The checks a trip of which is a safety trip. `signals.SAFETY_CHECKS` is
# the authority and a test holds the two equal: importing it here closed an
# import ring (signals -> notify_router -> settings_store -> camera_policy),
# and a ring is a module whose answer depends on which neighbour loaded first.
SAFETY_CHECKS = frozenset({"climate.freeze"})


def trip_kind(signal: dict, *, safety_subjects=(), closure_subjects=()) -> str:
    """"safety", "closure" or "" — whether an investigation may use a camera.

    Read off what the panel already knows about the subject, never off the
    signal's words: a safety trip is a signal flagged `safety`, the safety
    lane's own case, a check the signal module already calls safety, or a
    subject the bus saw trip; a closure is a lock or a cover by domain, the
    bedtime check's rows, or a subject the bus saw as a door or window.
    """
    if not isinstance(signal, dict):
        return ""
    subject = str(signal.get("subject") or "")
    source = str(signal.get("source") or "")
    check = source[len("check:"):] if source.startswith("check:") else ""
    if (signal.get("safety") or source == "safety"
            or check in SAFETY_CHECKS or subject in safety_subjects):
        return "safety"
    if (subject.split(".", 1)[0] in CLOSURE_DOMAINS
            or source in CLOSURE_SOURCES or subject in closure_subjects):
        return "closure"
    return ""


def grant_for(subject: str, opted_in: list[str],
              entity_areas: dict[str, str] | None = None) -> list[str]:
    """The cameras an investigation of `subject` may look at.

    The opted-in cameras in the same room when there are any — the kitchen
    camera for the kitchen's smoke alarm — and otherwise every opted-in
    camera, because the person who ticked them ticked them for this.
    """
    cams = list(opted_in or [])
    areas = entity_areas or {}
    room = areas.get(str(subject or ""))
    if room:
        same = [c for c in cams if areas.get(c) == room]
        if same:
            return same
    return cams


def prompt_line(grant: list[str], kind: str) -> str:
    """What an investigation is told when it may use a camera."""
    if not grant:
        return ""
    what = "the safety alarm" if kind == "safety" else "the door, window or lock"
    return ("\n\nCameras: to confirm " + what + ", you may look at "
            + ", ".join(grant) + " with get_camera_snapshot — once each at "
            "most, and only if a frame would settle the question. Describe "
            "what the frame shows about the house; never describe a person.")


__all__ = ["CLOSURE_DOMAINS", "LEDGER", "MAX_CAMERAS", "PER_DAY", "SAFETY_CHECKS",
           "clean_cameras", "grant_for", "permit", "prompt_line", "trip_kind",
           "used"]
