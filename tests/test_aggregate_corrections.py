#!/usr/bin/env python3
"""A Wrong on a row about several things answers every one it named.

Reported from a house (devloop #276, #290, #291): `reg.no_area`,
`reg.unused_helper`, `reg.orphan_device` and `sec.lock_cloud_voice` file ONE
row about several items with stable text. A Wrong settled that text as
`ignored` for good, so a NEW item never raised anything, while the
exception was written only under the row's one anchor entity, so the other
items it named were still not answered.

Now a row carries `items`, a Wrong writes the exception under every one,
the check leaves answered items out, and the settled text stops
suppressing a row that names something nobody answered. Driven through the
real `_end_finding`, the real facts store, the real `corrections.scope_map`
and the real checks.
"""
from __future__ import annotations

import asyncio
import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(BASE_DIR / "tests"))

import corrections  # noqa: E402
import findings_store  # noqa: E402
from checks import registry, security  # noqa: E402
from test_scoped_corrections import RouteCase  # noqa: E402

NOW = time.time()


def area_snap(devices: list[str]) -> dict:
    states, entities, devs = {}, [], []
    for d in devices:
        eid = f"light.{d}_lamp"
        states[eid] = {"state": "on", "attributes": {"friendly_name":
                                                     f"{d.title()} lamp"}}
        entities.append({"entity_id": eid, "device_id": d, "platform": "hue"})
        devs.append({"id": d, "name": f"{d.title()} lamp"})
    return {"states": states, "entities": entities, "devices": devs,
            "areas": [{"area_id": a, "name": a.title()}
                      for a in ("kitchen", "hall", "office")],
            "_trail": []}


def orphan_snap(devices: list[str]) -> dict:
    return {"states": {}, "entities": [],
            "devices": [{"id": d, "name": f"{d.title()} bridge"}
                        for d in devices],
            "areas": [], "_trail": []}


class AggregateCase(RouteCase):
    def file(self, rows, check):
        return findings_store.add_many(
            [{**r, "source": f"check:{check}"} for r in rows])

    def wrong(self, row):
        async def body(_client):
            await self.server._end_finding(
                row, self.server.FINDING_VERBS["wrong"], "")
            await asyncio.gather(*list(self.server._CORRECTION_TASKS))
        self.drive(body)

    def with_rules(self, snap):
        snap["corrections"] = corrections.scope_map(protected=[])
        return snap


class TestNoArea(AggregateCase):
    def test_a_new_device_after_a_wrong_is_one_row_naming_only_it(self):
        rows = registry.no_area(area_snap(["alpha", "beta"]), NOW)
        self.assertEqual(len(rows), 1)
        created = self.file(rows, "reg.no_area")
        self.assertEqual(len(created), 1)
        self.wrong(created[0])

        # The same two devices: nothing.
        again = registry.no_area(self.with_rules(area_snap(["alpha", "beta"])),
                                 NOW)
        self.assertEqual(again, [])

        # A third device appears: one row, naming only it, and it is filed.
        rows = registry.no_area(
            self.with_rules(area_snap(["alpha", "beta", "gamma"])), NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn("Gamma lamp", rows[0]["detail"])
        self.assertNotIn("Alpha lamp", rows[0]["detail"])
        self.assertNotIn("Beta lamp", rows[0]["detail"])
        filed = self.file(rows, "reg.no_area")
        self.assertEqual(len(filed), 1, "the settled text swallowed a new item")

    def test_a_re_report_of_the_answered_set_is_still_suppressed(self):
        rows = registry.no_area(area_snap(["alpha", "beta"]), NOW)
        created = self.file(rows, "reg.no_area")
        self.wrong(created[0])
        # Even a pass whose snapshot carries no rules (an older collector)
        # does not refile the set somebody answered.
        self.assertEqual(self.file(rows, "reg.no_area"), [])


class TestOrphanDevice(AggregateCase):
    def test_answered_orphans_stay_answered_and_a_new_one_files(self):
        rows = registry.orphan_device(orphan_snap(["one", "two"]), NOW)
        created = self.file(rows, "reg.orphan_device")
        self.assertEqual(len(created), 1)
        self.wrong(created[0])
        self.assertEqual(registry.orphan_device(
            self.with_rules(orphan_snap(["one", "two"])), NOW), [])
        rows = registry.orphan_device(
            self.with_rules(orphan_snap(["one", "two", "three"])), NOW)
        self.assertEqual(len(rows), 1)
        self.assertIn("Three bridge", rows[0]["detail"])
        self.assertNotIn("One bridge", rows[0]["detail"])
        self.assertEqual(len(self.file(rows, "reg.orphan_device")), 1)


class TestLockCloudVoiceAsksTheOneQuestion(unittest.TestCase):
    def snap(self):
        return {"states": {"lock.front_door": {"state": "locked",
                                               "attributes": {}}},
                "entities": [{"entity_id": "lock.front_door"}],
                "exposure": {"lock.front_door": {"cloud.alexa": True}},
                "devices": [], "areas": [], "_trail": [],
                "corrections": {"entity": {"lock.front_door": {
                    "sec.lock_cloud_voice": {"text": "", "until": ""}}},
                    "area": {}, "check": {},
                    "never": {"checks": [], "domains": ["lock"],
                              "classes": [], "protected": []}}}

    def test_a_scoped_correction_is_read(self):
        self.assertEqual(security.lock_cloud_voice(self.snap(), NOW), [])

    def test_a_rule_wide_one_never_covers_a_lock(self):
        snap = self.snap()
        snap["corrections"]["entity"] = {}
        snap["corrections"]["check"] = {"sec.lock_cloud_voice":
                                        {"text": "", "until": ""}}
        self.assertEqual(len(security.lock_cloud_voice(snap, NOW)), 1)


if __name__ == "__main__":
    unittest.main()
