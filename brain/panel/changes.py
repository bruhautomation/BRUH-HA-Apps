"""Changes brAIn made — every one, newest first, each with its own Undo.

The owner's words (#453): "One thing that's missing is a running list of all
the actions that brain has taken and changes it made. Each action should
have an undo button next to it. That way if something happens autonomously
it can easily be undone if necessary."

Everything brAIn changes was already written down; nothing READ it back as
one list. A file a run edited is a line in the edit journal
(`automation_writer.INDEX`, filled by the `PreToolUse` hook and by the
panel's own writes); a service call is a line in the action ledger
(`actions.read_ledger`); a name or room brAIn tidied is a batch in
`tidy.py`; a one-off automation is a row in `intents.py`; an approved plan
is a finding that says `fixed`. This module turns those into one list of
rows a person reads — what changed, on what, when, and from where — and
never invents a way to put any of them back:

  * a file edit is put back by `automation_writer.revert`, the reverter
    `brain undo` and a fix's Undo use (through `unfix.revert_edits`);
  * a service call is put back by the restore press over the before-state
    the chokepoint recorded (`unfix.restore_plan` / `restore_report`), with
    every one of its never-restored rules;
  * a tidy batch by `tidy.undo`, a one-off by the Remove it already has, and
    a plan-applied fix by its own `unfix` route.

A row that cannot be put back says WHY instead of offering a button, and
two rules make that honest rather than hopeful:

**Newest first, and only the newest of a pair can be undone.** Reverting an
older edit of a file puts back the bytes from before it — and with them
throws away every later edit. Restoring an older call's before-state over a
newer change is the same mistake on a light. So a row with a later change to
the same file or entity says to undo that one first.

**A file changed since brAIn wrote it is not brAIn's to put back.** The
journal records the bytes before an edit, not after, so the only evidence a
file was changed by somebody else is that it was written after brAIn's
write had landed (`OUTSIDE_EDIT_S`). Reverting it then would undo the
person's own edit, which is worse than not offering the press.

Pure over what it is handed: the server reads the stores and passes them
in, so the suite builds a house's history without a house.
"""
from __future__ import annotations

import os

import automation_writer
import unfix

# How far back the list reaches. The tidy window is the longest any undo in
# the panel promises; a journal line older than that may have lost its
# snapshot to the hook's own prune.
CHANGES_DAYS = 30
# What one page of the list holds, and the most a request may ask for.
PAGE = 50
PAGE_MAX = 200
# How long after brAIn's journal line its own write may land. A file whose
# modification time is later than this past the line, with no later line
# of brAIn's for it, was changed by somebody else.
OUTSIDE_EDIT_S = 120
# A panel write that belongs to an accepted suggestion is stamped this long
# before the suggestion is settled (write, reload, verify, then settle).
ACCEPT_MATCH_S = 120

# Where a change came from, in the words a person reads. The ledger and the
# journal carry the channel the process was started on (`BRAIN_CHANNEL`).
WHERE = {
    "chat": "from the chat",
    "terminal": "from the terminal",
    "voice": "by voice",
    "fix": "from a fix you approved",
    "restore": "putting a change back",
    "healing": "overnight repair",
    "timed": "a timed action",
    "task": "an automation task",
    "card": "from a card",
}
# Service calls whose effect is a message: nothing on a device to put back.
MESSAGE_DOMAINS = frozenset({"notify", "persistent_notification", "tts"})

VERB_WORDS = {
    "turn_on": "Turned on", "turn_off": "Turned off", "toggle": "Toggled",
    "open_cover": "Opened", "close_cover": "Closed", "stop_cover": "Stopped",
    "lock": "Locked", "unlock": "Unlocked", "set_temperature":
    "Set the temperature of", "set_hvac_mode": "Changed the mode of",
    "select_option": "Changed", "set_value": "Set", "press": "Pressed",
    "media_play": "Played", "media_pause": "Paused", "media_stop": "Stopped",
    "volume_set": "Set the volume of", "reload": "Reloaded",
    "apply": "Put back", "trigger": "Ran",
}


def where_words(channel: str) -> str:
    return WHERE.get(str(channel or "").strip().lower(), "")


def _name(eid: str, names: dict) -> str:
    row = names.get(eid) if isinstance(names, dict) else None
    name = (row or {}).get("name") if isinstance(row, dict) else ""
    if name:
        return str(name)
    # An id the last checks pass never saw: its object id read aloud, never
    # the raw id in a sentence.
    obj = eid.split(".", 1)[-1] if "." in eid else eid
    return obj.replace("_", " ").strip() or eid


def _join(words: list[str], limit: int = 3) -> str:
    shown = words[:limit]
    more = len(words) - len(shown)
    if more > 0:
        return ", ".join(shown) + f" and {more} more"
    if len(shown) <= 1:
        return "".join(shown)
    return ", ".join(shown[:-1]) + " and " + shown[-1]


def _press(label: str, route: str, confirm: str = "",
           body: dict | None = None) -> dict:
    step = {"label": label, "route": route, "body": body or {}}
    if confirm:
        step["confirm"] = confirm
    return {"label": label, "steps": [step]}


def _row(rid: str, kind: str, title: str, at: float, where: str,
         press: dict | None = None, reason: str = "") -> dict:
    return {"id": rid, "kind": kind, "title": title, "at": int(at),
            "where": where, "press": press, "reason": "" if press else reason,
            "deletable": False}


def _in_window(ts: float, windows: list[tuple[float, float]]) -> bool:
    return any(a <= ts <= b for a, b in windows)


def call_title(row: dict, names: dict) -> str:
    domain = str(row.get("domain") or "")
    service = str(row.get("service") or "")
    things = [_name(str(e), names) for e in row.get("entities") or [] if e]
    if domain in MESSAGE_DOMAINS:
        return "Sent a message"
    verb = VERB_WORDS.get(service) or service.replace("_", " ").capitalize() \
        or "Changed"
    if things:
        return f"{verb} {_join(things)}"
    target = row.get("target") if isinstance(row.get("target"), dict) else {}
    if target:
        scope = ", ".join(sorted(k.replace("_id", "") for k in target))
        return f"{verb} everything in a {scope}"
    return f"{verb} ({domain})" if domain else verb


def edit_title(entry: dict) -> str:
    path = str(entry.get("path") or "")
    base = os.path.basename(path) or "a file"
    rel = path[len("/config/"):] if path.startswith("/config/") else base
    if not entry.get("existed"):
        return f"Created {rel}"
    return f"Edited {rel}"


def build(*, journal: list[dict], ledger: list[dict], fixes: list[dict],
          tidy_batches: list[dict], intents: list[dict],
          accepted: list[dict], names: dict | None = None,
          mtime=None, protected=None, honeytokens=(),
          now: float = 0.0) -> list[dict]:
    """Every change, newest first, as History rows.

    ``mtime`` is ``path -> epoch | None`` (a file's modification time), and
    ``protected``/``honeytokens`` are the restore press's own refusals.
    """
    names = names or {}
    since = now - CHANGES_DAYS * 86400
    rows: list[dict] = []

    # Plan-applied fixes: one row each, and everything that ran inside the
    # fix's window is that row's, because its Undo puts all of it back.
    windows: list[tuple[float, float]] = []
    for f in fixes or []:
        start = float(f.get("fix_started") or 0)
        end = float(f.get("fix_ended") or 0)
        if start <= 0 or end <= 0 or end < since:
            continue
        windows.append((start, end))
        title = f"Fixed: {str(f.get('text') or 'a problem').strip()}"
        rows.append(_row(
            f"fix:{int(f['ts'])}", "fix", title, end, WHERE["fix"],
            _press("Undo", f"/api/finding/{int(f['ts'])}/unfix",
                   "Puts back every file this fix changed and reloads Home "
                   "Assistant. Devices it switched are listed, and putting "
                   "them back is a press of its own.")))

    # One-off automations brAIn wrote, and the suggestions you accepted.
    intent_ids = set()
    for row in intents or []:
        if row.get("status") == "refused" or not row.get("automation_id"):
            continue
        at = float(row.get("accepted_at") or 0)
        if at < since:
            continue
        intent_ids.add(str(row["automation_id"]))
        rows.append(_row(
            f"intent:{int(row['ts'])}", "intent",
            f"Added the one-off automation “{row.get('title') or 'a rule'}”",
            at, WHERE["card"],
            _press("Undo", f"/api/intent/{int(row['ts'])}/remove",
                   "Takes the automation out of automations.yaml and reloads "
                   "Home Assistant.")))
    accepts = [a for a in accepted or []
               if a.get("status") == "accepted"
               and float(a.get("settled_at") or 0) >= since]

    # The edit journal, newest first. A later line for the same path is
    # what makes an older one unsafe to put back on its own.
    newest_for: dict[str, float] = {}
    for entry in sorted(journal or [], key=lambda e: float(e.get("ts") or 0),
                        reverse=True):
        ts = float(entry.get("ts") or 0)
        if ts < since:
            continue
        path = str(entry.get("path") or "")
        if _in_window(ts, windows):
            continue
        tool = str(entry.get("tool") or "")
        where = where_words(entry.get("channel"))
        title = edit_title(entry)
        if tool == automation_writer.TOOL:
            where = WHERE["card"]
            match = next((a for a in accepts
                          if 0 <= float(a.get("settled_at") or 0) - ts
                          <= ACCEPT_MATCH_S), None)
            if match is not None:
                if str(match.get("automation_id") or "") in intent_ids:
                    continue        # the one-off's own row says this
                title = f"Added “{match.get('title') or 'a suggestion'}”"
        later = newest_for.get(path)
        newest_for.setdefault(path, ts)
        reason = ""
        if later is not None and later > ts:
            reason = ("A later change to this file is listed above — undo "
                      "that one first.")
        elif entry.get("existed") and not entry.get("snapshot"):
            reason = "brAIn kept no copy of the file from before this edit."
        elif mtime is not None:
            changed = mtime(path)
            if changed is not None and changed > ts + OUTSIDE_EDIT_S:
                reason = ("The file has been changed since, outside brAIn, "
                          "so putting brAIn's copy back would lose that "
                          "change. brain undo in the terminal can still "
                          "do it if you mean to.")
        press = None if reason else _press(
            "Undo", f"/api/changes/edit/{ts:.6f}/undo",
            "Puts this file back exactly as it was before this edit and "
            "reloads what reads it.")
        rows.append(_row(f"edit:{ts:.6f}", "edit", title, ts, where, press,
                         reason))

    # The action ledger, newest first, for the same reason.
    newest_call: dict[str, float] = {}
    for call in sorted(ledger or [], key=lambda r: float(r.get("ts") or 0),
                       reverse=True):
        ts = float(call.get("ts") or 0)
        if ts < since or _in_window(ts, windows):
            continue
        title = call_title(call, names)
        where = where_words(call.get("channel"))
        entities = [str(e) for e in call.get("entities") or [] if e]
        later = any(newest_call.get(e, 0) > ts for e in entities)
        for e in entities:
            newest_call.setdefault(e, ts)
        reason = ""
        if str(call.get("domain") or "") in MESSAGE_DOMAINS:
            reason = "A message cannot be unsent."
        elif not entities:
            reason = ("It named no single device, so there is no recorded "
                      "state to put back.")
        elif later:
            reason = ("A later change to the same device is listed above — "
                      "undo that one first.")
        else:
            plan = unfix.restore_plan([call], protected, honeytokens)
            if not plan["apply"]:
                why = (plan["refused"] or [("", "nothing was recorded")])[0][1]
                reason = f"It can't be put back: {why}."
        press = None if reason else _press(
            "Undo", f"/api/changes/call/{ts:.6f}/undo",
            "Puts each device back how brAIn recorded it before this change, "
            "then reads it again to check.")
        rows.append(_row(f"call:{ts:.6f}", "call", title, ts, where, press,
                         reason))

    # Names and rooms brAIn tidied, one row per batch you applied.
    for batch in tidy_batches or []:
        at = float(batch.get("at") or 0)
        if at < since or batch.get("undone_at"):
            continue
        subjects = [_name(str(e.get("subject") or ""), names)
                    for e in batch.get("entries") or []]
        title = (f"Tidied the names and rooms of {_join(subjects)}"
                 if subjects else "Tidied names and rooms")
        rows.append(_row(
            f"tidy:{batch.get('id')}", "tidy", title, at, "from a tidy-up card",
            _press("Undo", f"/api/tidy/undo/{batch.get('id')}",
                   "Puts back each field that still holds what brAIn wrote. "
                   "A field you changed since is left alone.")))

    rows.sort(key=lambda r: r["at"], reverse=True)
    return rows


def label(name: str = "brAIn") -> str:
    """The History filter's name, with the household's name for the
    assistant (`personality.assistant_name`)."""
    return f"Changes {' '.join(str(name or '').split()) or 'brAIn'} made"


def page(rows: list[dict], limit: int = PAGE, before: float | None = None) -> dict:
    """One page of the list, newest first: `{rows, total, more}`."""
    limit = max(1, min(int(limit or PAGE), PAGE_MAX))
    shown = [r for r in rows if before is None or r["at"] < before]
    return {"rows": shown[:limit], "total": len(rows),
            "more": len(shown) > limit}


def find_journal(entries: list[dict], ts: float) -> dict | None:
    """The journal line a Changes row named, by its stamp."""
    for entry in entries or []:
        try:
            if abs(float(entry.get("ts") or 0) - float(ts)) < 1e-5:
                return entry
        except (TypeError, ValueError):
            continue
    return None


def find_call(calls: list[dict], ts: float) -> dict | None:
    for call in calls or []:
        try:
            if abs(float(call.get("ts") or 0) - float(ts)) < 1e-5:
                return call
        except (TypeError, ValueError):
            continue
    return None


__all__ = ["CHANGES_DAYS", "OUTSIDE_EDIT_S", "PAGE", "PAGE_MAX", "WHERE",
           "build", "call_title", "label", "edit_title", "find_call", "find_journal",
           "page", "where_words"]
