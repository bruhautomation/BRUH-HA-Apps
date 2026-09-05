#!/usr/bin/env python3
"""Regenerate the two entries whose ground truth is known by construction.

    python tests/corpus/build.py

Neither of these is hand-written, and that is the point. `clean-house.json`
is `tests/test_house_checks.py`'s own fixture — the house every check is
asserted silent on — and `rehearsal-house.json` is that house with
`panel/rehearsal.py`'s `PLAN` planted in it, which is the same set of
defects `brain doctor --rehearse` creates on a real install. A second
house written by hand would be a second thing to keep true, and its labels
would be a guess where these two are arithmetic.

**The output is frozen on purpose.** Nothing asserts that the committed
entries still match what this script would produce today: a corpus entry
whose expectations are regenerated from the current code cannot fail when
the code changes, which is the one thing it exists to do. Run this when
you have *decided* an entry should move, read the diff, and commit it.

Every timestamp inside an entry is relative to the snapshot's own ``now``,
which is stored with it — so a replay a year from today grades exactly
what a replay today does.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
REPO = BASE.parent.parent
sys.path.insert(0, str(REPO / "brain" / "panel"))
sys.path.insert(0, str(REPO / "tests"))

import rehearsal  # noqa: E402
import test_house_checks as fixture  # noqa: E402


def clean_house() -> dict:
    """The healthy fixture, exactly as the suite builds it.

    ``services`` is a set in the fixture and a list here — `checks` reads
    it through `set(...)` at every use, so the two are the same house; JSON
    simply has no set.
    """
    snap = fixture.house()
    snap["services"] = sorted(snap["services"])
    return snap


def rehearsal_house() -> dict:
    """The same house with `rehearsal.PLAN`'s defects planted in it.

    Built from the plan rather than transcribed from it, so a defect added
    to the rehearsal appears here the next time this is run instead of
    silently not being in the corpus.
    """
    snap = clean_house()
    now = fixture.NOW
    for row in rehearsal.PLAN:
        if row["kind"] != "automation":
            continue
        config = dict(row["row"]["config"])
        # The rehearsal's own writer sets no alias — the entry id IS the
        # name a check quotes — so the fixture states it the way Home
        # Assistant would have it once the file is loaded.
        config["alias"] = row["id"]
        snap["automations"].append(config)
        entity_id = f"automation.{row['id']}"
        snap["states"][entity_id] = {
            "state": "on",
            "attributes": {"friendly_name": row["id"],
                           "last_triggered": fixture.iso(3600)},
            "last_changed": fixture.iso(3600)}
        snap["entities"].append({"entity_id": entity_id,
                                 "platform": "automation",
                                 "unique_id": config["id"],
                                 "created_at": now - 600})
    # Both planted automations trigger on `sun.sun`, which every real house
    # has and this fixture did not — without it `auto.dead_ref` would
    # report the trigger as well as the action, and the entry's labels
    # would be measuring the fixture rather than the check.
    snap["states"]["sun.sun"] = {"state": "above_horizon", "attributes": {},
                                 "last_changed": fixture.iso(600)}
    snap["entities"].append({"entity_id": "sun.sun", "platform": "sun"})
    # The healthy planted row. Nothing should fire on it, and a check that
    # does is a false positive worth knowing about — which is why it is in
    # the entry with an empty `checks` list rather than left out.
    snap["states"][rehearsal.HELPER_ID] = {
        "state": str(rehearsal.HELPER_VALUE),
        "attributes": {"friendly_name": rehearsal.HELPER_NAME},
        "last_changed": fixture.iso(300), "last_updated": fixture.iso(300)}
    snap["entities"].append({"entity_id": rehearsal.HELPER_ID,
                             "platform": "input_number",
                             "created_at": now - 600})
    return snap


def entry(name: str, title: str, note: str, snap: dict,
          labels: list[dict]) -> dict:
    return {
        "schema": 1,
        "kind": "checks",
        "id": name,
        "title": title,
        "note": note,
        "captured_at": int(fixture.NOW),
        "source": "fixture",
        "snapshot": snap,
        "labels": labels,
    }


def main() -> int:
    out = BASE / "entries"
    out.mkdir(parents=True, exist_ok=True)

    files = {
        "clean-house.json": entry(
            "clean-house",
            "A small, healthy house",
            "Every check has to be silent here. This entry is the floor "
            "under every other one: a rule that starts firing on a house "
            "with nothing wrong with it is the rule people learn to "
            "ignore first, and this is what fails when one does.",
            clean_house(), []),
        "rehearsal-house.json": entry(
            "rehearsal-house",
            "The same house with the rehearsal's defects planted in it",
            "The defects `brain doctor --rehearse` creates on a real "
            "install, in the fixture house. Ground truth by construction: "
            "the labels are `rehearsal.PLAN`, not somebody's reading of "
            "what the checks found.",
            rehearsal_house(),
            [{"check": row["check"], "entity_id": row["id"],
              "verdict": "found", "why": row["proves"]}
             for row in rehearsal.PLAN if row.get("check")]),
    }
    for name, data in files.items():
        (out / name).write_text(
            json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False)
            + "\n", encoding="utf-8")
        print(f"wrote {out / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
