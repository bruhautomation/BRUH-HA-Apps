"""The redesign's three new reads: History rows a person can delete, facts
browsed by the room or device they are about, and the Timeline narrowed to a
room, a kind of thing and words.

Each is driven through the real function rather than its markup, because a
delete that only hid the row on screen, or a filter applied after a block was
capped, both render correctly and are both wrong.
"""
import sys
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

PANEL_DIR = Path(__file__).resolve().parent.parent / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import facts_store  # noqa: E402
import today  # noqa: E402


def _settled(text, kind, ts):
    return {"text": text, "kind": kind, "ts": ts, "key": text.lower()}


def _history(settled, **kw):
    return today.history(findings=[], settled=settled, muted=[], snoozed_cases=[],
                         todo_done=[], tidy_batches=[], hidden_rows={}, **kw)


class TestDeletingFromHistory(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = unittest.mock.patch.object(today, "HIDDEN_FILE",
                                       Path(self.tmp.name) / "hidden.json")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self.tmp.cleanup)

    def test_a_deleted_row_is_gone_and_the_rest_stay(self):
        settled = [_settled("Lounge TV standby", "ignored", 100),
                   _settled("Loft Mini renamed", "ignored", 200)]
        rows = _history(settled)["rows"]["ignored"]
        self.assertEqual(len(rows), 2)
        gone = next(r for r in rows if r["title"] == "Lounge TV standby")
        self.assertTrue(gone["deletable"])
        self.assertEqual(today.clear([{"id": gone["id"], "at": gone["at"]}]), 1)
        left = _history(settled)["rows"]["ignored"]
        self.assertEqual([r["title"] for r in left], ["Loft Mini renamed"])
        # The count on the filter follows the rows.
        counts = {f["id"]: f["count"] for f in _history(settled)["filters"]}
        self.assertEqual(counts["ignored"], 1)

    def test_something_newer_under_the_same_title_comes_back(self):
        """Deleting last month's answer must not hide next month's."""
        row = _history([_settled("Battery low", "fixed", 100)])["rows"]["done"][0]
        today.clear([{"id": row["id"], "at": row["at"]}])
        self.assertEqual(_history([_settled("Battery low", "fixed", 100)])["rows"]["done"], [])
        again = _history([_settled("Battery low", "fixed", 500)])["rows"]["done"]
        self.assertEqual(len(again), 1)

    def test_a_snoozed_row_cannot_be_deleted(self):
        """A snooze comes back on its own date whatever the record says, so a
        delete there would be a promise the queue breaks."""
        case = {"id": "f:1", "claim": "Fridge warm", "snoozed_until": time.time() + 3600,
                "created_at": 100}
        rows = today.history(findings=[], settled=[], muted=[], snoozed_cases=[case],
                             todo_done=[], tidy_batches=[], hidden_rows={})["rows"]["snoozed"]
        self.assertFalse(rows[0]["deletable"])
        self.assertEqual(today.clear([{"id": rows[0]["id"], "at": 999}]), 0)

    def test_deleting_keeps_what_was_hidden(self):
        today.hide("update:light.x:1.0", "ignored", "Update light")
        today.clear([{"id": "ignored|x", "at": 1}])
        self.assertTrue(today.is_hidden("update:light.x:1.0"))

    def test_rubbish_is_refused(self):
        self.assertEqual(today.clear([{"id": "nope"}, "str", {"id": "done|a", "at": "x"}]), 0)


class TestBrowsingBySubject(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE)
        facts_store.FACTS_FILE = root / "facts.json"
        facts_store.INGEST_STATE_FILE = root / "ingest.json"
        facts_store.add("The fridge sits at 4 C.", subject="sensor.fridge")
        facts_store.add("The fridge door sticks.", subject="sensor.fridge")
        facts_store.add("Nobody cooks before 6.", subject="area:kitchen")
        facts_store.add("Bins go out Thursday.", subject="house")

    def tearDown(self):
        facts_store.FACTS_FILE, facts_store.INGEST_STATE_FILE = self._old
        self.tmp.cleanup()

    def test_every_subject_is_offered_with_its_count_and_room(self):
        got = facts_store.browse(names={"sensor.fridge": "Fridge"},
                                 subject_areas={"sensor.fridge": "Kitchen"})
        subjects = {s["id"]: s for s in got["facets"]["subjects"]}
        self.assertEqual(subjects["sensor.fridge"]["count"], 2)
        self.assertEqual(subjects["sensor.fridge"]["name"], "Fridge")
        self.assertEqual(subjects["sensor.fridge"]["area"], "Kitchen")
        self.assertEqual(subjects["area:kitchen"]["kind"], "area")
        self.assertEqual(subjects["house"]["kind"], "house")

    def test_picking_a_subject_does_not_shrink_the_list_of_subjects(self):
        got = facts_store.browse(subject="sensor.fridge")
        self.assertEqual(got["total"], 2)
        self.assertEqual(len(got["facets"]["subjects"]), 3)

    def test_the_search_narrows_the_subjects_too(self):
        got = facts_store.browse(query="fridge")
        self.assertEqual([s["id"] for s in got["facets"]["subjects"]], ["sensor.fridge"])


    def test_one_room_filed_under_two_ids_is_one_row(self):
        # The rail read "Laundry, laundry room" and "Irrigation, Irrigation":
        # one room twice, with half its facts under each.
        facts_store.add("The washer drains slowly.", subject="area:laundry")
        facts_store.add("The dryer vent is long.", subject="area:laundry_room")
        facts_store.add("Zone 2 is the hedge.", subject="area:irrigation")
        facts_store.add("Zone 3 is the lawn.", subject="area:irrigation_2")
        names = {"area:laundry": "Laundry", "area:irrigation": "Irrigation",
                 "area:irrigation_2": "Irrigation", "area:kitchen": "Kitchen"}
        got = facts_store.browse(names=names)
        rooms = [s for s in got["facets"]["subjects"] if s["kind"] == "area"]
        self.assertEqual(sorted(s["name"] for s in rooms),
                         ["Irrigation", "Kitchen", "Laundry"])
        laundry = next(s for s in rooms if s["name"] == "Laundry")
        self.assertEqual(laundry["count"], 2)
        picked = facts_store.browse(names=names, subject=laundry["id"])
        self.assertEqual(sorted(f["text"] for f in picked["facts"]),
                         ["The dryer vent is long.", "The washer drains slowly."])

    def test_two_different_rooms_are_not_folded(self):
        facts_store.add("Cold in winter.", subject="area:living_room")
        got = facts_store.browse(names={"area:living_room": "Living Room",
                                        "area:kitchen": "Kitchen"})
        ids = {s["id"] for s in got["facets"]["subjects"] if s["kind"] == "area"}
        self.assertEqual(ids, {"area:kitchen", "area:living_room"})


class TestNarrowingTheTimeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import server  # noqa: PLC0415 — heavy, and only this class needs it
        cls.server = server

    def _grouped(self):
        return {"episodes": [
            {"entity_id": "light.kitchen", "name": "Kitchen light", "subject": "lights"},
            {"entity_id": "light.lounge", "name": "Lounge lamp", "subject": "lights"},
            {"entity_id": "binary_sensor.back_door", "name": "Back door", "subject": "doors"},
            {"entity_id": "", "name": "Home Assistant restarted", "subject": "system"},
        ]}

    def _narrow(self, **q):
        names = {"light.kitchen": {"name": "Kitchen light", "area": "Kitchen"},
                 "light.lounge": {"name": "Lounge lamp", "area": "Lounge"},
                 "binary_sensor.back_door": {"name": "Back door", "area": "Kitchen"}}
        grouped = self._grouped()
        with unittest.mock.patch.dict(self.server._NAMES, names, clear=True):
            areas, kinds = self.server._activity_narrow(grouped, q)
        return grouped, areas, kinds

    def test_a_room_keeps_only_what_is_in_it(self):
        grouped, areas, _ = self._narrow(area="Kitchen")
        self.assertEqual({e["entity_id"] for e in grouped["episodes"]},
                         {"light.kitchen", "binary_sensor.back_door"})
        # The facet is counted before the room filter.
        self.assertEqual({a["id"]: a["count"] for a in areas},
                         {"Kitchen": 2, "Lounge": 1, "-": 1})

    def test_no_room_finds_what_needs_one(self):
        grouped, _, _ = self._narrow(area="-")
        self.assertEqual([e["name"] for e in grouped["episodes"]], ["Home Assistant restarted"])

    def test_kind_and_words_combine(self):
        grouped, _, kinds = self._narrow(kind="lights", q="lounge")
        self.assertEqual([e["entity_id"] for e in grouped["episodes"]], ["light.lounge"])
        self.assertIn("lights", {k["id"] for k in kinds})

    def test_no_filter_touches_nothing(self):
        grouped, _, _ = self._narrow()
        self.assertEqual(len(grouped["episodes"]), 4)


if __name__ == "__main__":
    unittest.main()
