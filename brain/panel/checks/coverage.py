"""Which parts of Home Assistant brAIn has looked at, and what it found.

A Findings tab that is empty says nothing about whether anything was
looked at: a house where every check ran and found nothing and a house
where half of them could not reach what they read look the same from the
list. The owner's rule is the other way round — *leave no part of Home
Assistant unexamined* — so every catalog entry names the AREA of the house
it examines (:data:`AREAS`), and after each checks pass this records, per
check, when it last ran, whether it could look, and how many rows it
found. An area's line is derived from its checks' records, never stored on
its own, so the line and the records cannot disagree.

Four answers an area can give, and they are four different claims:

* **found** — at least one of its checks filed something on its last run;
* **checked, nothing wrong** — every check in it looked, inside the last
  week, and found nothing;
* **could not look** — a check in it was skipped or broke, with the reason
  the snapshot gave (never "nothing wrong": "I could not ask" is not "it
  is fine", `clear_resolved`'s rule);
* **not set up here** — every check in it said the thing it reads is not
  in this house (no HACS, no Matter, no energy dashboard). That is an
  examined answer and it is said in those words.

A record older than :data:`WEEK_S` is not a look: the area says how long
it has been, because "checked, nothing wrong" a month ago is a claim about
a house that has since moved.

Some things inside an area cannot be read from inside an add-on at all;
:data:`GAPS` says which, so the line can say what it did not look at
rather than letting "nothing wrong" cover it.

The record is a file in ``/data`` (:data:`COVERAGE_FILE`), because the
checks state in the panel is in memory and a restart must not make a week
of looking read as "not checked yet". It is never created where its folder
does not exist (`facts_store.writable`'s rule) and nothing here raises.

Stdlib only, pure apart from :func:`load` / :func:`save`.
"""
from __future__ import annotations

import json
import os
import time

WEEK_S = 7 * 86400

COVERAGE_FILE = os.environ.get("BRAIN_CHECKS_COVERAGE_FILE",
                               "/data/checks-coverage.json")

# The parts of a house, in the order the owner listed them. The last is
# the devices and their readings themselves, which every other area is
# ABOUT rather than part of — a frozen thermometer is not a network, a
# backup or an integration's fault.
AREAS: list[tuple[str, str]] = [
    ("networks", "Networks"),
    ("integrations", "Integrations"),
    ("custom_integrations", "Custom integrations"),
    ("addons", "Add-ons"),
    ("host", "Host and hardware"),
    ("backups", "Backups"),
    ("recorder", "Recorder"),
    ("automations", "Automations and scripts"),
    ("dashboards", "Dashboards"),
    ("energy", "Energy"),
    ("people", "People and presence"),
    ("hacs", "HACS"),
    ("repairs", "Repairs"),
    ("devices", "Devices and readings"),
]
AREA_IDS = [a for a, _ in AREAS]
AREA_TITLES = dict(AREAS)

# What brAIn cannot read from inside an add-on, said on the area's line
# so "nothing wrong" never stands in for it.
GAPS: dict[str, str] = {
    "networks": "Thread border routers (Home Assistant does not say what "
                "is on a Thread network)",
    "host": "storage wear (the Supervisor does not report an SSD's or "
            "eMMC's remaining life)",
    "recorder": "which entities write the most rows (only the database "
                "itself can count them)",
    "hacs": "archived repositories (HACS does not publish that outside "
            "its own panel)",
}

STATES = ("found", "clear", "partial", "could_not_look", "absent", "never")


def load(path: str | None = None) -> dict:
    """The stored record, ``{"checks": {id: {...}}}``. An unreadable file
    is an empty record, which every area reads as "not checked yet"."""
    path = path or COVERAGE_FILE
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {"checks": {}}
    if not isinstance(data, dict) or not isinstance(data.get("checks"), dict):
        return {"checks": {}}
    return data


def save(state: dict, path: str | None = None) -> bool:
    """Write the record. Never raises; never creates its own folder."""
    path = path or COVERAGE_FILE
    if not os.path.isdir(os.path.dirname(path) or "."):
        return False
    try:
        import atomic_write  # noqa: PLC0415 — panel-local
        atomic_write.write_text(path, json.dumps(state, separators=(",", ":")))
        return True
    except Exception:  # noqa: BLE001 — accounting never fails a pass
        return False


def _reason(text: str, errors: dict) -> str:
    """A skip in words. `run_all` says which snapshot keys were missing;
    the snapshot says WHY each was, in a sentence a person can act on."""
    text = str(text or "")
    prefix = "snapshot is missing "
    if text.startswith(prefix):
        keys = [k.strip() for k in text[len(prefix):].split(",") if k.strip()]
        said = [str(errors.get(k) or "").strip() for k in keys]
        said = [s for s in said if s]
        if said:
            return "; ".join(dict.fromkeys(said))
        return "Home Assistant did not answer what it reads"
    return text


def record(state: dict | None, result: dict, now: float,
           errors: dict | None = None) -> dict:
    """The record after one checks pass. Pure: a new dict.

    A check that ran keeps when, how many it found and whether what it
    reads is not in this house (``absent``); a check that was skipped or
    raised keeps its last good run and records why this attempt could not
    look. A check this pass did not consider at all (a pass asked for a
    few checks only) is left exactly as it was.
    """
    errors = errors or {}
    old = (state or {}).get("checks") or {}
    out = {cid: dict(rec) for cid, rec in old.items() if isinstance(rec, dict)}
    per_check = result.get("per_check") or {}
    absent = result.get("absent") or {}
    for cid in result.get("ran") or ():
        out[cid] = {"ran_at": int(now), "attempt_at": int(now),
                    "found": int(per_check.get(cid) or 0),
                    "absent": str(absent.get(cid) or ""), "skipped": ""}
    for source in ("skipped", "errors"):
        for cid, why in (result.get(source) or {}).items():
            rec = out.get(cid) or {}
            rec = {**rec, "attempt_at": int(now),
                   "skipped": _reason(why, errors)
                   if source == "skipped" else
                   "the check broke: " + str(why)[:160]}
            out[cid] = rec
    return {"checks": out, "updated_at": int(now)}


def _ago(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))} min ago"
    if seconds < 2 * 86400:
        return f"{int(seconds // 3600)} h ago"
    return f"{int(seconds // 86400)} days ago"


def area_view(state: dict | None, catalog: list[dict],
              now: float | None = None) -> list[dict]:
    """One row per area: what it is, what its checks last said, the line.

    ``[{id, title, state, line, last_ran, found, checks, could_not_look}]``
    in :data:`AREAS` order. ``could_not_look`` is ``{check title: reason}``
    for every check in the area whose last attempt could not look, or that
    has not run inside :data:`WEEK_S`.
    """
    now = time.time() if now is None else float(now)
    recs = (state or {}).get("checks") or {}
    out = []
    for area, title in AREAS:
        members = [c for c in catalog if c.get("area") == area]
        ids = [c["id"] for c in members]
        last_ran = 0
        found = 0
        looked = 0
        absent: list[str] = []
        blind: dict[str, str] = {}
        for c in members:
            rec = recs.get(c["id"]) or {}
            name = str(c.get("title") or c["id"])
            ran_at = int(rec.get("ran_at") or 0)
            last_ran = max(last_ran, ran_at)
            if rec.get("skipped"):
                blind[name] = str(rec["skipped"])
                continue
            if not ran_at:
                blind[name] = "it has not run yet"
                continue
            if now - ran_at > WEEK_S:
                blind[name] = f"it last ran {_ago(now - ran_at)}"
                continue
            looked += 1
            if rec.get("absent"):
                absent.append(str(rec["absent"]))
                continue
            found += int(rec.get("found") or 0)
        if not any(recs.get(i) for i in ids):
            st = "never"
        elif found:
            st = "found"
        elif looked and len(absent) == looked and not blind:
            st = "absent"
        elif blind and not looked:
            st = "could_not_look"
        elif blind:
            st = "partial"
        else:
            st = "clear"
        when = f" (last looked {_ago(now - last_ran)})" if last_ran else ""
        if st == "never":
            line = f"{title}: not checked yet"
        elif st == "found":
            line = (f"{title}: {found} finding{'' if found == 1 else 's'}"
                    f"{when}")
        elif st == "absent":
            line = (f"{title}: not set up in this house — "
                    + "; ".join(dict.fromkeys(absent)) + when)
        elif st == "could_not_look":
            line = f"{title}: could not look — " + _blind_text(blind)
        elif st == "partial":
            line = (f"{title}: checked, nothing wrong{when}; could not look "
                    "at " + _blind_text(blind))
        else:
            line = f"{title}: checked, nothing wrong{when}"
        if area in GAPS and st != "absent":
            line += f". Not looked at: {GAPS[area]}"
        out.append({"id": area, "title": title, "state": st, "line": line,
                    "last_ran": last_ran, "found": found, "checks": ids,
                    "could_not_look": blind})
    return out


def _blind_text(blind: dict[str, str]) -> str:
    parts = [f"{name.lower()} ({why})" for name, why in sorted(blind.items())]
    if len(parts) > 3:
        parts = parts[:3] + [f"and {len(blind) - 3} more"]
    return "; ".join(parts)


def summary(state: dict | None, catalog: list[dict],
            now: float | None = None) -> dict:
    """What `/api/diagnostics` carries under ``coverage``."""
    areas = area_view(state, catalog, now)
    return {"updated_at": int((state or {}).get("updated_at") or 0),
            "areas": areas,
            "lines": [a["line"] for a in areas]}


def lines_text(coverage) -> str:
    """The report's section: one line per area, or a sentence saying why
    there are none."""
    if not isinstance(coverage, dict):
        return "(coverage not recorded)"
    lines = [str(x) for x in (coverage.get("lines") or []) if x]
    return "\n".join(lines) if lines else "(coverage not recorded)"


def checked_rows(areas: list[dict], now: float, tz=None) -> list[dict]:
    """The decision trail's "checked, nothing wrong" rows: one per area
    whose checks looked and found nothing, keyed by the local DATE so the
    trail holds one per area per day (and folds that day's passes into
    it). An area that found something, could not look at all or is not in
    this house writes none — the first is on the Findings tab, the other
    two are not a look that came back clean."""
    import datetime as dt  # noqa: PLC0415
    day = dt.datetime.fromtimestamp(now, tz=tz).strftime("%Y-%m-%d")
    out = []
    for a in areas:
        if a.get("state") not in ("clear", "partial"):
            continue
        reason = (f"checked on {day}: every check in it looked and found "
                  "nothing") if a["state"] == "clear" else (
            f"checked on {day}: found nothing, but could not look at "
            + _blind_text(a.get("could_not_look") or {}))
        out.append({"kind": "checked", "subject": "",
                    "check": f"area.{a['id']}", "reason": reason,
                    "text": f"{a['title']}: checked, nothing wrong",
                    "checks": list(a.get("checks") or [])})
    return out


__all__ = ["AREAS", "AREA_IDS", "AREA_TITLES", "COVERAGE_FILE", "GAPS",
           "STATES", "WEEK_S", "area_view", "checked_rows", "lines_text",
           "load", "record", "save", "summary"]
