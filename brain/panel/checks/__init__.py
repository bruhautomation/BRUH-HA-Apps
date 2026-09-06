"""House checks — findings that cost nothing.

Every finding brAIn filed used to come out of a Claude run: the analyst
sweeping a category on a schedule, or a study session. Both are told that
an empty list is the honest answer, so most of those runs spent tens of
thousands of tokens to report nothing — while the problems that are
*deterministically* visible (an automation naming an entity that no longer
exists, a device that has been unavailable for a day, a battery running
down on a slope you can draw a line through) were found only when a model
happened to look in the right place.

A check is a pure function from a house snapshot to a list of findings in
the shape the findings inbox already takes. It reads the same registries,
states, statistics and stored traces the analyst reads, and it never calls
Claude. The results go through :func:`findings_store.add_many` under
``source: "check:<id>"`` and ride into the analyst's prompt block with
everything else, which turns the model's job from *discovery* into
*judgement*: "the ledger says these three things — what do they miss, and
which of them matter in this house?"

The bar for a check is the bar the card contract sets for the model:
something is actually wrong, it is specific and checkable, and the fix is
concrete. A check that fires on a healthy house is worse than no check,
because it is the one the person learns to ignore first — every rule below
has a floor or a window for that reason, and the producer scorecard on the
Findings tab is what proves each one earns its place.

**Finding text has to be stable across runs.** The store dedupes by
normalised text, so a number that changes every hour ("9 days left",
"unavailable for 27h") belongs in ``detail``, never in ``text``.
:func:`run_all` hands the fresh details back so the panel can refresh the
rows it already holds.

**A check that did not run must not clear anything.** A snapshot fetch can
fail (the recorder is busy, a WebSocket call times out); the check that
needed it then reports nothing, which is indistinguishable from "the
problem went away". So :func:`run_all` returns which checks actually ran,
and the panel only clears resolved rows for those.

Stdlib only: the snapshot collector (``checks.snapshot``) is the one part
that needs aiohttp, and it imports it lazily, so the test suite can drive
every check against a hand-built house without the add-on runtime.
"""
from __future__ import annotations

# ``snapshot`` is imported here too, so ``checks.snapshot.collect`` resolves
# off the package the way server.py calls it; its aiohttp import is lazy,
# inside the collector, so this costs the test suite nothing.
from . import (automations, baseline, chores, dashboards,  # noqa: F401
               devices, evening, forecasts, registry, snapshot, system,
               thermal)

# The catalog. Order is the order results are filed in, which is also the
# order the Findings tab shows a fresh batch: what breaks an automation
# before what tidies a registry.
CHECKS: list[dict] = [
    *automations.CHECKS,
    *devices.CHECKS,
    *dashboards.CHECKS,
    *registry.CHECKS,
    *system.CHECKS,
    *forecasts.CHECKS,
    # Last: everything above answers a question with a fixed answer, and
    # these answer one whose answer is different in every house.
    *baseline.CHECKS,
    *evening.CHECKS,
    *chores.CHECKS,
    *thermal.CHECKS,
]

CHECK_IDS = [c["id"] for c in CHECKS]

# Checks that run but do not reach the Findings tab. A new rule goes here
# FIRST: it files to `shadow_findings` instead of to the findings store,
# nothing renders it, nothing notifies about it, and for a fortnight its
# rows are compared with what was actually filed over the same window.
# It moves out of this set when its precision on the corpus and its
# agreement in shadow both clear the bar — a code change a person makes
# reading those two numbers, because a producer that promoted itself on a
# threshold would be a threshold nobody can see deciding what a house is
# told.
#
# Empty on purpose: every check shipped so far has earned its place, and
# a set with something in it "for now" is how a trial becomes permanent.
SHADOW: frozenset[str] = frozenset()


def is_shadow(check_id: str) -> bool:
    return check_id in SHADOW

# What a group's findings are labelled with on the tab, beside the
# severity. "Automation check" reads better under a card than "check:auto".
GROUP_TITLES = {
    "auto": "Automation check",
    "dev": "Device check",
    "org": "Dashboard check",
    "reg": "Registry check",
    "sys": "System check",
    "forecast": "Forecast",
    "base": "Baseline check",
    "evening": "Bedtime check",
    "chore": "Chore",
    "climate": "Climate check",
}


def source_for(check_id: str) -> str:
    return f"check:{check_id}"


def title_for(check_id: str) -> str:
    return GROUP_TITLES.get(check_id.split(".", 1)[0], "House check")


def get_check(check_id: str) -> dict | None:
    for c in CHECKS:
        if c["id"] == check_id:
            return c
    return None


def run_all(snap: dict, now: float | None = None,
            only: list[str] | None = None) -> dict:
    """Run every check the snapshot can feed.

    Returns ``{"findings": [...], "shadow": [...], "ran": [ids],
    "skipped": {id: reason}, "errors": {id: message}, "per_check":
    {id: count}}``. A check that raises is reported under ``errors`` and
    treated as not run: one bad rule must not take the batch down, and
    must not clear anything either.

    ``shadow`` is the rows from checks in :data:`SHADOW`, split out here
    rather than filtered by the caller — the catalog knows which rules are
    being trialled, and a caller that forgot to filter would put a
    trialled rule straight onto somebody's Findings tab, which is the one
    thing shadow mode exists to prevent. ``ran`` and ``per_check`` span
    both, because a shadow check that ran still ran and still may clear
    its own rows.
    """
    import time as _time
    now = _time.time() if now is None else now
    available = snap.get("available") or {}
    out: list[dict] = []
    hidden: list[dict] = []
    ran: list[str] = []
    skipped: dict[str, str] = {}
    errors: dict[str, str] = {}
    per_check: dict[str, int] = {}
    for check in CHECKS:
        cid = check["id"]
        if only and cid not in only:
            continue
        missing = [n for n in check.get("needs", ()) if not available.get(n)]
        if missing:
            skipped[cid] = "snapshot is missing " + ", ".join(missing)
            continue
        try:
            found = check["run"](snap, now) or []
        except Exception as exc:  # noqa: BLE001 — one rule must not sink the batch
            errors[cid] = f"{type(exc).__name__}: {exc}"[:200]
            continue
        ran.append(cid)
        per_check[cid] = len(found)
        into = hidden if is_shadow(cid) else out
        for f in found:
            f = dict(f)
            f["source"] = source_for(cid)
            f["source_title"] = title_for(cid)
            into.append(f)
    return {"findings": out, "shadow": hidden, "ran": ran, "skipped": skipped,
            "errors": errors, "per_check": per_check}
