#!/usr/bin/env python3
"""Every row a check files says what to do about it.

Half the findings on a real house had an empty "what to do" (#342): the
card showed a problem and nothing under Fix, so the one question a person
reading it has went unanswered. Every check in the catalog writes a
concrete ``fix`` — an action brAIn offers, a place in Home Assistant, or,
where honestly so, that nothing needs doing.

The sweep is `test_finding_text_plain`'s: every catalogued check function
is wrapped, the check test modules that already plant each defect are run
(the plain-prose sweep's, and the ones that plant what it does not reach:
the thermal, closure, safety, access, override and baseline checks), and
every row any of them produced is read. A check no fixture makes fire is
not covered, so every check in the catalog must have produced a row.

The overnight log check (`sre.py`) files rows too, and its fix is the one
a run writes and the code then edits: a sentence about another problem is
taken out, and a fix that lost every sentence was filed empty. It is given
the record's own plain instruction instead.
"""

import io
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import checks  # noqa: E402
import sre  # noqa: E402
from test_finding_text_plain import SWEEP_MODULES, _Capture  # noqa: E402

# Fixtures that make the checks the plain-prose sweep never sees fire.
EXTRA_MODULES = (
    "test_thermal", "test_closures", "test_safety_tripped_check",
    "test_access_steward", "test_actions", "test_baselines",
    "test_dehumidifier_stopped",
)


class TestEveryRowSaysWhatToDo(unittest.TestCase):
    # The extra modules' own tests write these stores; point every one at a
    # scratch directory while they run here.
    STORES = (("baselines", "STORE"), ("closures", "STORE"),
              ("appliances", "STORE"), ("thermal", "STORE"),
              ("rhythm", "STORE"), ("schedule_store", "STORE"),
              ("journal", "JOURNAL_FILE"))

    def setUp(self):
        import importlib
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self._old = []
        for name, attr in self.STORES:
            mod = importlib.import_module(name)
            self._old.append((mod, attr, getattr(mod, attr)))
            setattr(mod, attr, f"{self.tmp.name}/{name}.json")

    def tearDown(self):
        for mod, attr, value in self._old:
            setattr(mod, attr, value)
        self.tmp.cleanup()

    def test_no_check_files_a_row_with_an_empty_fix(self):
        with _Capture() as cap:
            suite = unittest.defaultTestLoader.loadTestsFromNames(
                SWEEP_MODULES + EXTRA_MODULES)
            result = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful(),
                        [str(t) for t, _ in result.failures + result.errors])
        seen = {cid for cid, _r, _s in cap.rows}
        unseen = sorted(c["id"] for c in checks.CHECKS if c["id"] not in seen)
        self.assertEqual(unseen, [], "no fixture made these checks file a "
                         "row, so the sweep proves nothing about them")
        empty = sorted({f"{cid}: {row.get('text')!r}"
                        for cid, row, _snap in cap.rows
                        if not str(row.get("fix") or "").strip()})
        self.assertEqual(empty, [], "\n".join(empty))


LOG = {"id": "log:abc", "kind": "log", "level": "ERROR",
       "logger": "custom_components.bambu_lab.pybambu",
       "integration": "bambu_lab", "message": "MQTT disconnected",
       "count": 12, "entities": ["sensor.printer_status"]}


class TestAnOvernightCauseAlwaysSaysWhatToDo(unittest.TestCase):
    def dig(self):
        return {"records": [dict(LOG)],
                "names": {"sensor.printer_status": "Printer status",
                          "light.hall": "Hall lamp"},
                "device_names": {}, "entity_device": {},
                "entity_devices": {}, "area_names": [], "subjects": {}}

    def test_a_fix_whose_every_sentence_named_another_thing_is_not_empty(self):
        answer = {"causes": [{
            "title": "Printer status keeps dropping off",
            "detail": "The printer's connection drops overnight.",
            "fix": "Restart the Hall lamp.",
            "severity": "warning", "records": ["log:abc"],
            "entity_id": "sensor.printer_status"}]}
        [cause] = sre.parse_causes(answer, self.dig())["causes"]
        self.assertTrue(cause["fix"].strip())
        self.assertNotIn("Hall lamp", cause["fix"])

    def test_a_cause_the_run_gave_no_fix_is_given_one(self):
        answer = {"causes": [{
            "title": "Printer status keeps dropping off",
            "detail": "The printer's connection drops overnight.",
            "fix": "", "severity": "warning", "records": ["log:abc"]}]}
        [cause] = sre.parse_causes(answer, self.dig())["causes"]
        self.assertTrue(cause["fix"].strip())


if __name__ == "__main__":
    unittest.main()
