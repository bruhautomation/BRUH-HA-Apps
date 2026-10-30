#!/usr/bin/env python3
"""Every CI job has a time limit, so nothing can hang.

GitHub gives a job six hours by default. Twice on 2026-10-30, a pytest-xdist
worker died ("node down: Not properly terminated") and the "Python tests" job
sat waiting for it for 45 minutes, until it was cancelled by hand. On the
2026-10-18 run, the same failure took six hours. pytest-timeout fails any
single test past 60s, but it cannot see a worker that has died. So every job
in every workflow carries `timeout-minutes`, set at roughly three times its
normal run, and a job added without one fails here.
"""

import unittest
from pathlib import Path

import yaml

WORKFLOWS = Path(__file__).resolve().parent.parent / ".github" / "workflows"
CEILING = 60  # minutes; the slowest job (a cold aarch64 image build) is ~7


class TestEveryJobHasATimeLimit(unittest.TestCase):
    def test_every_job_in_every_workflow_has_timeout_minutes(self):
        files = sorted(WORKFLOWS.glob("*.yml")) + sorted(WORKFLOWS.glob("*.yaml"))
        self.assertTrue(files)
        missing, too_long = [], []
        for path in files:
            doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            for name, job in (doc.get("jobs") or {}).items():
                if "uses" in job:  # a reusable workflow's own jobs carry theirs
                    continue
                limit = job.get("timeout-minutes")
                if not isinstance(limit, int):
                    missing.append(f"{path.name}:{name}")
                elif limit > CEILING:
                    too_long.append(f"{path.name}:{name}={limit}")
        self.assertEqual(missing, [], "jobs with no timeout-minutes")
        self.assertEqual(too_long, [], f"jobs allowed more than {CEILING} minutes")

    def test_the_python_tests_job_fails_well_before_an_hour(self):
        doc = yaml.safe_load((WORKFLOWS / "ci.yml").read_text(encoding="utf-8"))
        self.assertLessEqual(doc["jobs"]["tests"]["timeout-minutes"], 20)


if __name__ == "__main__":
    unittest.main()
