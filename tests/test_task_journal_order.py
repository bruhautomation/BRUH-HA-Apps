"""A refused task's journal shows the refusal before the answer.

A task a safety check refused is tried once more on another model, and both
runs are journaled: the refused first run as a row of its own, the retry as
the row that answers the task. Both rows were written by `journal_task` in
the background (brain/integrations/automation-listener.sh), and nothing
ordered the two writers — so on a loaded machine (a CI runner, a busy
house) the answer's row could land in the journal before the refusal's,
and anything reading "the last row for this task" read the refusal as the
ending.

Driven through the REAL `process_task` against the fake CLI
(tests/test_task_failures.ListenerCase), with one substitution: the journal
writer is a wrapper around the real `brain_run_journal.py` that takes its
time over the refused run's row — the slow write a loaded machine makes.
"""
from __future__ import annotations

import json
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# The module, not its class: a base class imported by name is collected
# here and its tests run twice.
import test_task_failures  # noqa: E402

if str(test_task_failures.PANEL_DIR) not in sys.path:
    sys.path.append(str(test_task_failures.PANEL_DIR))
import model_plan  # noqa: E402  (the panel's)

# Sleeps over an `error` row, then runs the real writer as itself.
SLOW_WRITER = '''\
import os, runpy, sys, time
if len(sys.argv) > 3 and sys.argv[3] == "error":
    time.sleep(float(os.environ.get("SLOW_JOURNAL_S", "1.5")))
real = os.path.join(os.environ["REAL_SCRIPTS_DIR"], "brain_run_journal.py")
sys.argv[0] = real
runpy.run_path(real, run_name="__main__")
'''


class TestTheRefusalIsJournaledFirst(test_task_failures.ListenerCase):
    def setUp(self):
        super().setUp()
        slow = self.tmp / "slow_scripts"
        slow.mkdir()
        (slow / "brain_run_journal.py").write_text(SLOW_WRITER)
        extra = {"FAKE_ONCE_FILE": str(self.tmp / "once"),
                 "BRAIN_REFUSAL_FALLBACK":
                     model_plan.env_exports()["BRAIN_REFUSAL_FALLBACK"],
                 "BRAIN_SCRIPTS_DIR": str(slow),
                 "REAL_SCRIPTS_DIR": str(test_task_failures.SCRIPTS_DIR)}
        real = test_task_failures.subprocess.run

        def run(*args, env=None, **kw):
            return real(*args, env={**(env or {}), **extra}, **kw)
        patch = unittest.mock.patch.object(test_task_failures.subprocess, "run", run)
        patch.start()
        self.addCleanup(patch.stop)

    def test_a_slow_refusal_row_still_lands_before_the_answer(self):
        result = self.run_task({"model": "sonnet"}, fake_mode="refused_then_ok")
        self.assertEqual(result["status"], "completed", result)
        rows = self.journal_rows()
        self.assertEqual(len(rows), 2, rows)
        self.assertEqual([r.get("outcome") for r in rows], ["error", "ok"], rows)
        self.assertIn("safety check", rows[0].get("error") or json.dumps(rows[0]))


if __name__ == "__main__":
    unittest.main()
