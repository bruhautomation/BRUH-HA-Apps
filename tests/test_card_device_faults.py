#!/usr/bin/env python3
"""A device fault a card names is on the Findings list too.

A real house's card said a lock had been offline since Saturday and a
bridge had dropped four times; neither was a finding, so the one place a
person decides what to do about the house never heard of either. After a
card is written, every entity it names (by id or by the name it goes by)
that Home Assistant reports unavailable either already has a live finding —
which the card now links, because a card names devices by name and the
link read ids only — or gets one, filed through the card's own `findings`
and `triage.gate` like everything the card reports, never a new door.
"""

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings_store  # noqa: E402

from test_card_findings_clear import ClearCase  # noqa: E402

LOCK = "lock.front_door"


def iso(seconds_ago: float) -> str:
    import datetime as dt
    return dt.datetime.fromtimestamp(time.time() - seconds_ago,
                                     tz=dt.timezone.utc).isoformat()


class LockCase(ClearCase):
    def setUp(self):
        super().setUp()
        self._names = dict(self.server._NAMES)
        self.server._NAMES.clear()
        self.server._NAMES[LOCK] = {"name": "Front door lock",
                                    "area": "Hall"}
        self.server._NAMES["light.hall"] = {"name": "Hall light",
                                            "area": "Hall"}
        self._states = self.server._card_states

        async def states():
            return {LOCK: {"entity_id": LOCK, "state": "unavailable",
                           "last_changed": iso(48 * 3600),
                           "attributes": {"friendly_name": "Front door lock"}},
                    "light.hall": {"entity_id": "light.hall", "state": "on",
                                   "last_changed": iso(600),
                                   "attributes": {}}}

        self.server._card_states = states
        self.reply.update(
            title="Hall: evening lights on 3 h",
            summary="The Hall light ran 3 h last night; the Front door lock "
                    "has been offline since Saturday.")
        self.reply.pop("findings", None)

    def tearDown(self):
        self.server._card_states = self._states
        self.server._NAMES.clear()
        self.server._NAMES.update(self._names)
        super().tearDown()

    def lock_rows(self):
        return [f for f in findings_store.list_all()
                if f.get("entity_id") == LOCK]


class TestTheCardFilesIt(LockCase):
    def test_one_lock_finding_with_a_next_step_the_card_links(self):
        self.generate()
        [row] = self.lock_rows()
        self.assertEqual(row["source"], "lighting")
        self.assertIn("Front door lock", row["text"])
        self.assertTrue(row["fix"])
        self.assertNotIn("light.hall", [f.get("entity_id")
                                        for f in findings_store.list_all()])

    def test_a_second_run_does_not_file_it_twice(self):
        self.generate()
        self.generate()
        self.assertEqual(len(self.lock_rows()), 1)


class TestAnExistingFindingIsLinked(LockCase):
    def test_the_card_links_the_offline_checks_row(self):
        findings_store.add_many([{
            "text": "Front door lock has been unavailable for more than a day",
            "severity": "serious", "entity_id": LOCK,
            "source": "check:dev.unavailable", "status": "open",
            "fix": "Check its power and its connection, then reload its "
                   "integration."}])
        card = self.generate()
        self.assertEqual(len(self.lock_rows()), 1)
        self.assertEqual(self.lock_rows()[0]["source"], "check:dev.unavailable")
        self.assertIn(LOCK, self.server._card_entities(card))


if __name__ == "__main__":
    unittest.main()
