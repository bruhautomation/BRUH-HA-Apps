"""The development loop's streams and schedules are the owner's to change,
and sending is one choice (#710, #711).

"Report everything without asking" (`autopilot`) overlapped "Ask before
sending each new report" (`review`) and was a reading laid over the stored
streams and schedule: while it was on, the stream switches were greyed and a
schedule chosen in the drop-down was saved and then read over, so the
drop-down never held a choice. The switch is gone; an install that still has
it stored reads as before until the owner changes anything it decided, and
that change sticks. Each drop-down marks a recommended schedule.
"""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE / "brain" / "panel"))

import devloop  # noqa: E402

PANEL = BASE / "brain" / "panel"


class Case(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        old = devloop.DATA_DIR
        self.addCleanup(setattr, devloop, "DATA_DIR", old)
        devloop.DATA_DIR = Path(self.tmp.name) / "devloop"
        devloop.DATA_DIR.mkdir(parents=True)

    def store(self, data: dict) -> None:
        devloop.settings_file().write_text(json.dumps(data), encoding="utf-8")


class TestAStoredAutopilotNoLongerLocksAnything(Case):
    def test_a_schedule_chosen_under_it_is_the_schedule_read_back(self):
        self.store({"enabled": True, "autopilot": True, "review": True,
                    "streams": {"gaps": False}, "schedule": {"gaps": 24}})
        out = devloop.save_settings({"schedule": {"faults": 6}})
        self.assertEqual(out["schedule"]["faults"], 6)
        self.assertEqual(devloop.load_settings()["schedule"]["faults"], 6)

    def test_the_rest_of_what_it_decided_is_kept_as_it_read(self):
        self.store({"enabled": True, "autopilot": True, "review": True,
                    "streams": {"gaps": False}, "schedule": {"gaps": 24}})
        before = devloop.load_settings()
        out = devloop.save_settings({"streams": {"ideas": False}})
        self.assertFalse(out["streams"]["ideas"])
        # Everything else is what the owner was looking at, not what was
        # stored under the reading.
        self.assertTrue(out["streams"]["gaps"])
        self.assertFalse(out["review"])
        self.assertEqual(out["schedule"], before["schedule"])
        self.assertFalse(devloop._raw_settings()["autopilot"])

    def test_a_stream_switched_off_under_it_stays_off(self):
        self.store({"enabled": True, "autopilot": True})
        devloop.save_settings({"streams": {"design": False}})
        self.assertFalse(devloop.load_settings()["streams"]["design"])

    def test_turning_ask_before_sending_on_is_kept(self):
        self.store({"enabled": True, "autopilot": True, "review": False})
        devloop.save_settings({"review": True})
        self.assertTrue(devloop.load_settings()["review"])

    def test_without_it_nothing_is_rewritten(self):
        self.store({"enabled": True, "review": True, "streams": {"gaps": False}})
        out = devloop.save_settings({"schedule": {"faults": 3}})
        self.assertFalse(out["streams"]["gaps"])
        self.assertTrue(out["review"])


def shell_rule(path: Path) -> bool:
    """ha-context-gen.sh's own heredoc, lifted out and run on a file."""
    import subprocess
    src = (BASE / "brain" / "scripts" / "ha-context-gen.sh").read_text(encoding="utf-8")
    block = src[src.index('settings.json" 2>/dev/null <<\'PYEOF\'\n'):]
    block = block[block.index("\n") + 1:block.index("\nPYEOF")]
    return subprocess.run([sys.executable, "-c", block, str(path)]).returncode == 0


class TestDevelopmentModeIsWhereItWas(Case):
    """Development mode (sessions filing report_bug unasked) is true exactly
    where it was before autopilot stopped being a switch, and nowhere new."""

    def both(self) -> list[bool]:
        return [devloop.development_mode(), shell_rule(devloop.settings_file())]

    def test_never_autopilot_with_review_off_is_not(self):
        self.store({"enabled": True, "review": False})
        self.assertEqual(self.both(), [False, False])
        devloop.save_settings({"schedule": {"faults": 3}, "streams": {"gaps": True}})
        self.assertEqual(self.both(), [False, False])

    def test_an_autopilot_install_still_is_before_and_after_its_first_change(self):
        self.store({"enabled": True, "autopilot": True, "review": True})
        self.assertEqual(self.both(), [True, True])
        devloop.save_settings({"schedule": {"faults": 6}})
        raw = devloop._raw_settings()
        self.assertFalse(raw["autopilot"])
        self.assertTrue(raw["autopilot_migrated"])
        self.assertEqual(self.both(), [True, True])
        devloop.save_settings({"streams": {"ideas": False}})
        self.assertEqual(self.both(), [True, True])

    def test_asking_before_sending_ends_it_as_turning_autopilot_off_did(self):
        self.store({"enabled": True, "autopilot": True})
        devloop.save_settings({"review": True})
        self.assertEqual(self.both(), [False, False])

    def test_the_loop_off_is_never_development_mode(self):
        self.store({"enabled": False, "autopilot": True})
        self.assertEqual(self.both(), [False, False])

    def test_the_migration_mark_is_not_settable_from_the_wire(self):
        with self.assertRaises(ValueError):
            devloop.save_settings({"autopilot_migrated": True})


class TestRecommendedSchedules(unittest.TestCase):
    def test_every_stream_has_one_from_the_choices(self):
        self.assertEqual(set(devloop.RECOMMENDED_HOURS), set(devloop.STREAMS))
        for name, hours in devloop.RECOMMENDED_HOURS.items():
            self.assertIn(hours, devloop.HOURS_CHOICES, name)


class TestThePageHasOneSendChoice(unittest.TestCase):
    def test_no_autopilot_switch_and_nothing_greyed_by_it(self):
        html = (PANEL / "index.html").read_text(encoding="utf-8")
        js = (PANEL / "app.js").read_text(encoding="utf-8")
        self.assertNotIn("setDevAutopilot", html + js)
        self.assertNotIn("Report everything without asking", html)
        self.assertIn('id="setDevReview"', html)
        paint = js[js.index("function paintDevloop("):js.index("\nfunction devEfficacy(")]
        self.assertNotRegex(paint, r"\.disabled\s*=\s*s\.")
        self.assertNotRegex(paint, r'" disabled"')
        self.assertIn("(recommended)", paint)

    def test_the_put_no_longer_takes_it(self):
        server = (PANEL / "server.py").read_text(encoding="utf-8")
        put = server[server.index("async def h_devloop_put"):]
        put = put[:put.index("\nasync def ")]
        self.assertNotRegex(put, re.compile(r'"autopilot"'))


if __name__ == "__main__":
    unittest.main()
