#!/usr/bin/env python3
"""A leak sensor reading wet for a week is reported by a house check.

The safety lane files a card on a TRANSITION into the tripped state seen on
the event bus, so a detector that was already wet when the panel started —
or tripped while it was down — had only the Resident's first look between
it and a person, and on a real house that look said "no active leak" about
a moisture sensor that had read `on` for a week. `safety.tripped` is the
deterministic answer: any smoke, gas, CO or leak binary sensor whose state
is the tripped state NOW is a critical row, whatever saw it trip or did not.

Driven through the real `checks.run_all` over the suite's clean house.
"""

import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))
sys.path.insert(0, str(BASE_DIR / "tests"))

import checks  # noqa: E402
import checks.safety  # noqa: E402
from test_house_checks import NOW, by_source, house, iso  # noqa: E402

LEAK = "binary_sensor.utility_leak"
ID = "safety.tripped"


def with_detector(state: str = "on", klass: str = "moisture",
                  eid: str = LEAK, changed: float = 7 * 86400,
                  registry_class: bool = False) -> dict:
    snap = house()
    attrs = {"friendly_name": "Utility leak sensor"}
    if not registry_class:
        attrs["device_class"] = klass
    snap["states"][eid] = {"state": state, "attributes": attrs,
                           "last_changed": iso(changed),
                           "last_updated": iso(changed)}
    reg = {"entity_id": eid, "platform": "zha", "device_id": "dev-leak"}
    if registry_class:
        reg["original_device_class"] = klass
    snap["entities"].append(reg)
    return snap


class TestATrippedDetectorIsAFinding(unittest.TestCase):
    def test_the_check_is_in_the_catalog_and_not_in_shadow(self):
        self.assertIn(ID, checks.CHECK_IDS)
        self.assertNotIn(ID, checks.SHADOW)
        entry = checks.get_check(ID)
        self.assertIn("states", entry["needs"])

    def test_a_leak_sensor_wet_for_a_week_is_reported(self):
        rows = by_source(checks.run_all(with_detector(), NOW)).get(
            "check:" + ID) or []
        self.assertEqual(len(rows), 1, rows)
        row = rows[0]
        self.assertEqual(row["entity_id"], LEAK)
        self.assertEqual(row["severity"], "critical")
        self.assertIn("Utility leak sensor", row["text"])
        self.assertIn("leak", row["text"].lower())
        # Stable text: the time it has read wet lives in the detail.
        self.assertNotRegex(row["text"], r"\d")
        self.assertTrue(row["detail"])
        self.assertFalse(row.get("fixable", True))

    def test_every_hot_safety_class_and_its_tripped_words(self):
        for klass in ("moisture", "smoke", "gas", "carbon_monoxide"):
            for state in ("on", "detected", "wet", "unsafe"):
                rows = by_source(checks.run_all(
                    with_detector(state=state, klass=klass), NOW)).get(
                        "check:" + ID) or []
                self.assertEqual(len(rows), 1, (klass, state))

    def test_a_class_set_only_in_the_registry_still_counts(self):
        rows = by_source(checks.run_all(
            with_detector(registry_class=True), NOW)).get("check:" + ID) or []
        self.assertEqual(len(rows), 1)

    def test_a_dry_or_unavailable_or_ordinary_sensor_is_silent(self):
        for snap in (with_detector(state="off"),
                     with_detector(state="unavailable"),
                     with_detector(klass="door"),
                     with_detector(klass="motion")):
            self.assertEqual(by_source(checks.run_all(snap, NOW)).get(
                "check:" + ID), None)

    def test_the_clean_house_says_nothing(self):
        self.assertEqual(checks.run_all(house(), NOW)["findings"], [])

    def test_the_classes_and_states_are_the_lanes_own(self):
        import signals
        self.assertEqual(set(checks.safety.TRIPPED_CLASSES),
                         set(signals.HOT_SAFETY_CLASSES))
        self.assertEqual(set(checks.safety.TRIPPED_STATES),
                         set(signals.HOT_SAFETY_STATES))


class TestItIsTreatedAsSafety(unittest.TestCase):
    def test_it_is_a_safety_check_a_look_may_not_ignore(self):
        import signals
        self.assertIn(ID, signals.SAFETY_FLAG_CHECKS)
        sig = signals.from_finding({
            "ts": 1, "text": "Utility leak sensor is reporting a water leak",
            "source": "check:" + ID, "entity_id": LEAK,
            "severity": "critical"}, now=NOW)
        self.assertTrue(sig["safety"])
        import resident
        floor, _why = resident.never_ignore(sig)
        self.assertEqual(floor, "act")

    def test_it_escalates_and_cannot_be_muted(self):
        import cases
        import notify_router
        row = {"source": "check:" + ID, "severity": "critical"}
        self.assertEqual(notify_router.urgency_of(row), "now")
        self.assertTrue(notify_router.is_urgent(row))
        self.assertIn("check:" + ID, cases.UNMUTABLE_SOURCES)

    def test_no_wide_correction_covers_it(self):
        import corrections
        self.assertIn(ID, corrections.NEVER_CHECKS)

    def test_a_card_about_the_same_entity_does_not_fold_into_it(self):
        import findings_store
        self.assertIn(ID, findings_store.CHECK_FOLD_EXCLUDED)


if __name__ == "__main__":
    unittest.main()
