"""Seven days after a fix is installed, the house says whether it held (plan 1.3/1.4).

The house already said "Held: not seen since …" two days after a fault
stopped. This is the measured version the cloud counts: once per fix, a
``brain-held`` block — ``held: true`` when the fault stayed silent for
seven days after the house first ran the release, ``held: false`` the
pass it is seen again inside them — and the efficacy figures ⚙ shows,
counted from those records.
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "tests"))
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

from test_devloop import NAMES, DevloopCase, diagnostics, upstream  # noqa: E402

import devloop.blocks as blocks  # noqa: E402

HOUR = 3600
DAY = 86400


def _iso(epoch: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


class _Case(DevloopCase):
    def setUp(self):
        super().setUp()
        self.switch_on()
        self.rows = self.rows[:1]
        self.t = time.time() - 30 * DAY

    def pass_(self, now: float, version: str):
        upstream.sweep(diagnostics(version=version), NAMES, now=now)
        upstream.send_due(now=now)

    def fix(self, fixed_in: str = "2.17.1"):
        """Filed, then closed fixed by the cloud with its usual comment."""
        self.pass_(self.t, "2.17.0")
        self.gh.judge(1, "devloop:fixed")
        self.gh.issues[0]["closed_at"] = _iso(self.t + HOUR)
        self.gh.comments.append((1, f"Fixed in brAIn {fixed_in} (#99)."))
        self.keep, self.rows = self.rows, []
        # The fault stops on the old release; the verdict is read back.
        self.pass_(self.t + 2 * HOUR, "2.17.0")

    def held_blocks(self):
        return [blocks.parse_block("held", b) for n, b in self.gh.comments
                if n == 1 and blocks.parse_block("held", b)]


class TestHeld(_Case):
    def test_silent_for_seven_days_after_the_install_is_held_once(self):
        self.fix()
        install = self.t + 3 * HOUR
        self.pass_(install, "2.17.1")          # the house runs the fix
        self.pass_(install + 3 * DAY, "2.17.1")
        self.assertEqual(self.held_blocks(), [], "not before seven days")
        self.pass_(install + 7 * DAY + HOUR, "2.17.1")
        [obj] = self.held_blocks()
        self.assertEqual({k: obj[k] for k in ("v", "release", "held_days", "held")},
                         {"v": 1, "release": "2.17.1", "held_days": 7, "held": True})
        self.assertEqual(obj["installed_at"], _iso(install))
        self.pass_(install + 9 * DAY, "2.17.1")
        self.assertEqual(len(self.held_blocks()), 1, "said once")
        eff = upstream.efficacy()
        self.assertEqual(eff["held_7d"], {"held": 1, "of": 1, "rate": 100.0})
        self.assertEqual(eff["came_back"]["count"], 0)

    def test_seen_again_inside_the_seven_days_is_not_held(self):
        self.fix()
        install = self.t + 3 * HOUR
        self.pass_(install, "2.17.1")
        self.rows = self.keep
        self.pass_(install + 2 * DAY, "2.17.1")
        [obj] = self.held_blocks()
        self.assertFalse(obj["held"])
        eff = upstream.efficacy()
        self.assertEqual(eff["held_7d"], {"held": 0, "of": 1, "rate": 0.0})
        self.assertEqual(eff["came_back"], {"count": 1, "of": 1, "rate": 100.0})

    def test_a_fix_not_installed_is_waiting_and_not_held(self):
        self.fix(fixed_in="2.18.0")
        self.pass_(self.t + 10 * DAY, "2.17.1")
        self.assertEqual(self.held_blocks(), [])
        eff = upstream.efficacy()
        self.assertEqual(eff["awaiting_update"], 1)
        self.assertEqual(eff["held_7d"]["of"], 0)
        self.assertIsNone(eff["held_7d"]["rate"], "nothing decided is no rate")

    def test_nobody_looking_is_not_held(self):
        import devloop
        self.fix()
        install = self.t + 3 * HOUR
        self.pass_(install, "2.17.1")
        devloop.save_settings({"streams": {"faults": False}})
        self.pass_(install + 8 * DAY, "2.17.1")
        self.assertEqual(self.held_blocks(), [])


if __name__ == "__main__":
    unittest.main()
