"""Putting back what a fix changed — the durable undo behind a fixed card.

Every other undo in the panel is the toast's: `undo_store`, in memory, 300
seconds, a ring of 32, and it reverses a *row* — a finding settled, a key
in the ledger, a line queued for memory. That is the right shape for "I
misclicked", and it is the wrong shape entirely for the one press that
sends a tool-enabled Claude run at somebody's house. What a fix leaves
behind is **durable**: bytes in `/config`, an automation Home Assistant
has reloaded, a light that is off. Five minutes is not the window in
which somebody works out that a change was wrong, and a token that has
expired is an offer the panel cannot make.

So this one is a **button on the card, for as long as the row says
`fixed`** — the same span the card spends waiting for somebody to press
Got it. It reverses out of two files the run already writes, so there is
nothing new to keep true:

  * the **edit journal** (`/data/.brain/edits/`), which
    `scripts/brain-edit-snapshot.py` fills from the `PreToolUse` hook on
    every Write/Edit under `/config`, and which `brain undo` and
    `automation_writer` already read and revert. The reverter here is
    `automation_writer.revert` — not a copy of it — because two answers
    to "put this file back" is exactly the drift a second implementation
    always produces, and `brain undo` would then disagree with the panel
    about the same journal line.
  * the **action ledger** (`/config/.brain/actions.jsonl`), which
    `ha_mcp_server.record_action` appends to at the `call_service`
    chokepoint and `actions.read_ledger` reads.

**The files are put back and the service calls are LISTED.** That
asymmetry is the whole design and not a shortcut. A file has a snapshot:
the bytes before the edit are on disk, so putting them back is exact. A
service call has no such thing — `light.turn_off` at 3pm does not record
what the light was doing at 2:59, the house has moved on since, and
"reversing" one would mean brAIn guessing at a prior state and then
acting on the guess, unattended, in somebody's home. The honest answer is
to say what it did and let a person decide, which is also what makes the
line worth reading: *brAIn also called light.turn_off on light.hall
during the fix; that is not reversed.*

Three more rules.

**The window is the row's** (`fix_started`/`fix_ended`, stamped by the
server either side of the agent run). Both files are append-only and
stamped in epoch seconds, so "what did THIS fix change" is answerable
only as "what either of them recorded between these two instants" — which
is why the start is written to disk *before* the run is spawned rather
than being held in memory.

**Only the fix run's own edits are reverted.** The journal is shared: the
panel writes into it too (`automation_writer.TOOL`), and an accepted
proposal landing in the same minute is a different press with its own
undo. Keying on the hook's tool names is what keeps this button about the
fix. The cost is named rather than hidden — an edit the run made with a
shell command never reaches the hook at all, so it is in no journal and
cannot be put back by anything, which is why the card reports the number
of files it restored rather than claiming the house is as it was.

**Newest first**, so a file the run edited three times ends at the bytes
it held before the first of them. That is `brain undo --all-today`'s
order, for its reason.

Stdlib plus two panel modules (both stdlib-only), so the test suite can
import it without the add-on runtime. Nothing here reloads anything: the
reload is an `await` against Core and belongs to the server, so this
hands back the domains that need one.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import actions
import automation_writer

# The tools the PreToolUse hook journals. `automation_writer.TOOL`
# ("brain-panel") is deliberately absent: those lines are the panel's own
# writes, which belong to whichever press made them.
CLAUDE_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")

# Which reload a restored file needs, by file name. The two brAIn writes
# itself are read out of `automation_writer.TARGETS` rather than written
# down again, because a second copy of "scenes.yaml is reloaded by
# scene.reload" is a copy that drifts; the rest are Home Assistant's own
# default include names. A file that is not in here is REPORTED as
# needing a reload rather than being guessed at: calling the wrong
# domain's reload does nothing useful, and `homeassistant.reload_all` is
# a decision about the whole house that this button was not given.
RELOADS: dict[str, tuple[str, str]] = {
    str(spec["file"]): tuple(spec["reload"])          # type: ignore[misc]
    for spec in automation_writer.TARGETS.values()
}
RELOADS.setdefault("scripts.yaml", ("script", "reload"))
RELOADS.setdefault("groups.yaml", ("group", "reload"))

# What the card's `result` can hold about one undo. A fix that touched
# forty files is a sentence about forty files, not forty sentences.
MAX_LISTED = 12


def _index_path() -> Path:
    """The journal index, read at call time.

    `automation_writer` resolves `JOURNAL_DIR` from the environment at
    import, and a test points both halves somewhere else by assigning to
    the module. Reading it through the module rather than binding a copy
    is what makes that work here too.
    """
    return automation_writer.INDEX


def journal_entries(started: float, ended: float,
                    also: tuple | list | set = ()) -> list[dict]:
    """The fix run's own edits inside the window, NEWEST FIRST.

    ``also`` names the journal stamps of edits the PANEL made for this same
    fix — a typed `edit_automation` op goes through `automation_writer`,
    whose lines carry `TOOL` rather than a hook's tool name — so the one
    Undo reverses both halves of one approved plan and nothing else the
    panel wrote in the same minute.

    A malformed line is skipped rather than taking the read down: the
    index is appended to by a hook running inside a process that can be
    killed mid-write, which is the same tolerance `brain undo` and
    `actions.read_ledger` apply to their own files.
    """
    if ended <= 0 or started <= 0 or ended < started:
        return []
    wanted = {round(float(t), 3) for t in also or ()
              if isinstance(t, (int, float))}
    out: list[dict] = []
    try:
        with open(_index_path(), "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(row, dict):
                    continue
                try:
                    ts = float(row.get("ts") or 0)
                except (TypeError, ValueError):
                    continue
                if not started <= ts <= ended:
                    continue
                tool = str(row.get("tool") or "")
                if tool not in CLAUDE_TOOLS and not (
                        tool == automation_writer.TOOL
                        and round(ts, 3) in wanted):
                    continue
                row["ts"] = ts
                out.append(row)
    except OSError:
        return []
    out.sort(key=lambda r: r["ts"], reverse=True)
    return out


def service_calls(started: float, ended: float) -> list[dict]:
    """Every service call brAIn made inside the window.

    `actions.read_ledger` is the reader — the ledger's writer is a
    different process running as a different user, and one reader is what
    keeps the wire format a contract rather than a guess.
    """
    if ended <= 0 or started <= 0 or ended < started:
        return []
    return [row for row in actions.read_ledger(started)
            if float(row.get("ts") or 0) <= ended]


def call_line(row: dict) -> str:
    """One service call, in the words a person can act on.

    Names the entities it was aimed at, and an area or device target as
    the target it was — `actions._ledger_index`'s rule: resolving one
    needs the registries as they were at the time of the call, and a wrong
    expansion would tell somebody brAIn touched an entity it did not.
    """
    call = f"{row.get('domain', '?')}.{row.get('service', '?')}"
    where = [str(e) for e in (row.get("entities") or []) if str(e).strip()]
    if not where:
        target = row.get("target") or {}
        if isinstance(target, dict):
            where = [f"{k.replace('_id', '')} {v}" for k, v in target.items()]
    return f"{call} on {', '.join(where)}" if where else call


def revert_edits(entries: list[dict]) -> dict:
    """Put each journalled file back, newest first. Never raises.

    Every entry is attempted even after one fails, because a half-undo
    that stopped at the first missing snapshot leaves a house in a state
    nobody chose — the remaining files are still the fix's, and the report
    names what could not be put back so the difference is visible.

    Returns `{restored, removed, failed, reloads}`: paths that were
    rewritten, paths that were deleted (the edit had created them),
    `(path, reason)` for each refusal, and the `(domain, service)` reloads
    the restored files ask for, deduped and in the order they were met.
    """
    restored: list[str] = []
    removed: list[str] = []
    failed: list[tuple[str, str]] = []
    reloads: list[tuple[str, str]] = []

    for entry in entries:
        path = str(entry.get("path") or "")
        try:
            answer = automation_writer.revert(entry)
        except Exception as exc:  # noqa: BLE001 — an undo must report, not raise
            failed.append((path, str(exc)[:200]))
            continue
        if not answer.get("ok"):
            failed.append((path, str(answer.get("error") or "brAIn could not "
                                     "put it back")))
            continue
        if answer.get("removed"):
            removed.append(path)
        else:
            restored.append(path)
        pair = RELOADS.get(os.path.basename(path))
        if pair and pair not in reloads:
            reloads.append(pair)

    return {"restored": restored, "removed": removed, "failed": failed,
            "reloads": reloads}


def summary(result: dict, calls: list[dict]) -> str:
    """What the card says after an undo, in one block of prose.

    The two halves are reported separately and in those words, because
    *files put back* and *service calls made* are different claims and the
    person reading this is deciding whether anything is left to do. A
    window that held neither says so out loud rather than rendering as a
    success with nothing in it — `sweep_only`'s rule: a press always has
    an answer.
    """
    parts: list[str] = []
    back = len(result.get("restored") or []) + len(result.get("removed") or [])
    if back:
        names = [os.path.basename(p) for p in
                 (result.get("restored") or []) + (result.get("removed") or [])]
        shown = ", ".join(names[:MAX_LISTED])
        more = len(names) - MAX_LISTED
        parts.append(f"Put back {back} file{'s' if back != 1 else ''} the fix "
                     f"had changed: {shown}"
                     + (f", and {more} more." if more > 0 else "."))
    for path, reason in (result.get("failed") or [])[:MAX_LISTED]:
        parts.append(f"Could not put back {path}: {reason}")

    if calls:
        lines = [call_line(row) for row in calls[:MAX_LISTED]]
        more = len(calls) - MAX_LISTED
        parts.append(
            f"brAIn also made {len(calls)} service call"
            f"{'s' if len(calls) != 1 else ''} during the fix, and those are "
            "NOT reversed — a call records what was asked for, never what the "
            "entity was doing before it, so putting one back would be a guess: "
            + "; ".join(lines) + (f"; and {more} more." if more > 0 else "."))

    if calls and restorable(calls):
        parts.append("brAIn recorded what those entities were doing before "
                     "it changed them, so “Put them back” on the card can "
                     "restore them — you press it; brAIn never does that on "
                     "its own.")

    if not parts:
        return ("There was nothing to put back: this fix changed no files "
                "under /config and made no service calls, so undoing it "
                "changes nothing. The finding is back on the list.")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Restoring what a service call changed — a press, never a timer
# ---------------------------------------------------------------------------
#
# The asymmetry above was right for a ledger that recorded what was ASKED
# for: putting a call back meant guessing the prior state. The ledger now
# records the before-state at the chokepoint (one state read per named
# entity, `ha_mcp_server._read_before` and `typed_fix.before_of`), so a
# restore is no longer a guess about the past — it is the past, read back.
# It is still never automatic: the house has moved on since, and only a
# person can say the recorded state is the one they want. Hence a button,
# per-entity answers, and four refusals.

# Domains Home Assistant can put back from a recorded state (each has a
# `reproduce_state`, which is what `scene.apply` drives). A sensor is a
# reading, not a setting, and is said rather than attempted.
RESTORABLE_DOMAINS = frozenset({
    "light", "switch", "fan", "cover", "climate", "media_player",
    "input_boolean", "input_number", "input_select", "input_text",
    "humidifier", "water_heater", "siren", "valve", "number", "select",
    "lock", "alarm_control_panel", "automation", "vacuum",
})
# Attributes a state carries that are not settings and must not be sent.
NOT_SETTINGS = frozenset({"friendly_name", "device_class", "color_mode"})
# Restoring INTO these states would make a house less secure, so a restore
# never does it; it says so, and the person does it by hand if they mean it.
LESS_SECURE = {
    "lock": frozenset({"unlocked", "open", "opening", "unlocking"}),
    "alarm_control_panel": frozenset({"disarmed"}),
}
OPENING_COVER_CLASSES = frozenset({"garage", "door", "gate"})
COVER_OPEN = frozenset({"open", "opening"})


def _before_rows(calls: list[dict]) -> dict[str, dict]:
    """Per entity, the state before brAIn's FIRST call on it in the window.

    Oldest call first: a fix that turned a light off and then on again has
    two before-states, and only the first is how the house was."""
    out: dict[str, dict] = {}
    for row in sorted(calls or [], key=lambda r: float(r.get("ts") or 0)):
        before = row.get("before") if isinstance(row.get("before"), dict) else {}
        for eid in row.get("entities") or []:
            eid = str(eid)
            if eid in out:
                continue
            out[eid] = before.get(eid) if isinstance(before.get(eid), dict) \
                else {"missing": True}
    return out


def restorable(calls: list[dict]) -> bool:
    return any("state" in b for b in _before_rows(calls).values())


def restore_plan(calls: list[dict], protected=None,
                 honeytokens=()) -> dict:
    """What a restore would set, and why each refused entity is refused.

    `{"apply": {entity: {"state", **attributes}}, "refused": [(entity,
    reason)]}` — pure over the ledger rows and the two lists, so the route
    and the card ask one function.
    """
    patterns = automation_writer.protected_patterns(protected)
    tokens = {str(t).lower() for t in honeytokens or ()}
    apply: dict[str, dict] = {}
    refused: list[tuple[str, str]] = []
    for eid, before in _before_rows(calls).items():
        domain = eid.split(".", 1)[0]
        if eid.lower() in tokens or automation_writer.is_protected(eid, patterns):
            refused.append((eid, "it is protected, so brAIn will not change it"))
            continue
        if before.get("missing"):
            refused.append((eid, "brAIn did not record how it was before"))
            continue
        if before.get("unknown") or "state" not in before:
            refused.append((eid, "brAIn could not read how it was before"))
            continue
        state = str(before["state"])
        if state in ("unavailable", "unknown"):
            refused.append((eid, f"it was {state} before, which is not a "
                                 "state anything can be put back to"))
            continue
        if domain not in RESTORABLE_DOMAINS:
            refused.append((eid, "it is a reading, not something brAIn sets"))
            continue
        attrs = dict(before.get("attributes") or {})
        if state in LESS_SECURE.get(domain, ()) or (
                domain == "cover" and state in COVER_OPEN
                and attrs.get("device_class") in OPENING_COVER_CLASSES):
            refused.append((eid, f"putting it back means it would be "
                                 f"{state}, which makes the house less secure "
                                 "— do that yourself if you mean it"))
            continue
        apply[eid] = {"state": state,
                      **{k: v for k, v in attrs.items()
                         if k not in NOT_SETTINGS}}
    return {"apply": apply, "refused": refused}


def restore_report(plan: dict, after: dict[str, dict | None],
                   error: str = "") -> list[dict]:
    """One line per entity: restored, or could not restore and why.

    Read off a state taken AFTER the call: Home Assistant accepting
    `scene.apply` is the request being taken, not the light being on.
    """
    rows = [{"entity_id": eid, "restored": False, "why": why}
            for eid, why in plan.get("refused") or []]
    for eid, target in (plan.get("apply") or {}).items():
        if error:
            rows.append({"entity_id": eid, "restored": False,
                         "why": f"Home Assistant refused it: {error}"[:300]})
            continue
        now = after.get(eid)
        if not isinstance(now, dict):
            rows.append({"entity_id": eid, "restored": False,
                         "why": "brAIn could not read it afterwards"})
        elif str(now.get("state")) == str(target.get("state")):
            rows.append({"entity_id": eid, "restored": True,
                         "why": f"back to {target['state']}"})
        else:
            rows.append({"entity_id": eid, "restored": False,
                         "why": f"it now reads {now.get('state')}, not "
                                f"{target['state']}"})
    return rows


def restore_text(rows: list[dict]) -> str:
    ok = [r for r in rows if r["restored"]]
    bad = [r for r in rows if not r["restored"]]
    parts = []
    if ok:
        parts.append(f"Put back {len(ok)} "
                     f"entit{'y' if len(ok) == 1 else 'ies'}: "
                     + ", ".join(f"{r['entity_id']} ({r['why']})"
                                 for r in ok[:MAX_LISTED]) + ".")
    for r in bad[:MAX_LISTED]:
        parts.append(f"Could not restore {r['entity_id']}: {r['why']}.")
    return "\n".join(parts) or ("There was nothing recorded to put back.")


__all__ = ["CLAUDE_TOOLS", "MAX_LISTED", "RELOADS", "RESTORABLE_DOMAINS",
           "call_line", "journal_entries", "restorable", "restore_plan",
           "restore_report", "restore_text", "revert_edits", "service_calls",
           "summary"]
