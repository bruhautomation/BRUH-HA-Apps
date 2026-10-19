"""Morph's own service reaches its own fault ledger.

The request loop, the watcher and the tick each caught their exceptions
and logged them, and the ledger (`devloop.py`) held only what the PANEL
reported: a card that threw, an overlap. A request loop failing on every
poll was in the add-on log and nowhere brAIn's development loop could
read. `note_exception` is the row, and `morphd`'s four handlers call it.
"""
from __future__ import annotations

import unittest
from pathlib import Path

from morph_env import MorphEnv

MORPHD = Path(__file__).resolve().parent.parent / "morph" / "service" / "morphd.py"


def _raise_inside_service(env):
    # Raised from inside a service module, so the frame named is Morph's own.
    try:
        env.paths.read_json(None)  # AttributeError, inside paths.py
    except Exception as exc:  # noqa: BLE001
        return exc
    raise AssertionError("expected read_json to raise")


class TestAServiceExceptionIsAFault(unittest.TestCase):
    def test_the_row_names_the_type_the_frame_and_carries_the_traceback(self):
        with MorphEnv() as env:
            env.settings.update({"report_code_issues": True})
            exc = _raise_inside_service(env)
            env.devloop.note_exception("Tick", exc, now=1_700_000_000.0)
            [row] = env.devloop.rows(now=1_700_000_000.0)
            self.assertEqual(row["where"], "Morph · Tick")
            self.assertRegex(row["what"], r"^TypeError in paths\.py:\d+: ")
            self.assertIn("Traceback", row["body"])
            self.assertEqual(row["impact"]["times"], 1)

    def test_the_same_fault_on_another_line_is_one_row(self):
        with MorphEnv() as env:
            env.settings.update({"report_code_issues": True})
            exc = _raise_inside_service(env)
            env.devloop.note_exception("Tick", exc, now=1_700_000_000.0)
            env.devloop.note_exception("Tick", exc, now=1_700_000_100.0)
            [row] = env.devloop.rows(now=1_700_000_100.0)
            self.assertEqual(row["impact"]["times"], 2)

    def test_every_loop_in_morphd_files_what_it_catches(self):
        text = MORPHD.read_text(encoding="utf-8")
        for loop in ("request loop", "watch loop", "tick loop"):
            block = text[text.index(f'log.exception("{loop}")'):][:200]
            self.assertIn("devloop.note_exception(", block, loop)
        self.assertRegex(text, r'log\.exception\("request %s failed".*?\n\s+devloop\.note_exception',
                         )

    def test_nothing_leaves_while_reporting_is_off(self):
        with MorphEnv() as env:
            env.settings.update({"report_code_issues": False})
            env.devloop.note_exception("Tick", _raise_inside_service(env))
            self.assertEqual(env.devloop.publish("1.0.4")["rows"], [])


if __name__ == "__main__":
    unittest.main()
