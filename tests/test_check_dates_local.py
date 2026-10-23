#!/usr/bin/env python3
"""A date a check writes is the house's date, not Greenwich's.

#334: a battery reading that changed at 00:40Z on 21 Oct — 20:40 on 20
Oct in America/New_York — was filed as "as of 21 Oct". Every "as of",
"since" and "last" a check writes goes through `_util.when`, and a ban's
date through the same function; both read the house's timezone first.
"""

import datetime as dt
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import baselines  # noqa: E402
import checks  # noqa: E402
from test_house_checks import NOW, house  # noqa: E402

try:
    from zoneinfo import ZoneInfo
    NEW_YORK = ZoneInfo("America/New_York")
except Exception:  # noqa: BLE001 — no tz data: New York is UTC-4 on these dates
    NEW_YORK = dt.timezone(dt.timedelta(hours=-4))

CHANGED = "2026-10-21T00:40:00+00:00"


class TestADateIsTheHouses(unittest.TestCase):
    def setUp(self):
        self._old = baselines.house_timezone
        baselines.house_timezone = lambda *a, **k: (NEW_YORK,
                                                    "America/New_York")

    def tearDown(self):
        baselines.house_timezone = self._old

    def test_when_reads_the_house_clock(self):
        self.assertTrue(checks._util.when(CHANGED).startswith("20 Oct"))

    def test_a_low_battery_is_as_of_the_houses_day(self):
        snap = house()
        st = snap["states"]["sensor.back_door_battery"]
        st.update(state="5", last_updated=CHANGED, last_changed=CHANGED)
        [row] = checks.devices.battery_low(snap, NOW)
        self.assertIn("as of 20 Oct", row["detail"])
        self.assertNotIn("21 Oct", row["detail"])

    def test_a_ban_is_dated_on_the_houses_day(self):
        now = dt.datetime(2026, 10, 22, 12, tzinfo=dt.timezone.utc).timestamp()
        snap = house(ip_bans=[{"ip": "203.0.113.9", "banned_at": CHANGED}])
        [row] = checks.security.login_bans(snap, now)
        self.assertIn("(20 Oct", row["detail"])

    def test_no_check_formats_a_date_in_utc_itself(self):
        import re
        offenders = []
        for path in sorted((TESTS_DIR.parent / "brain" / "panel" / "checks")
                           .glob("*.py")):
            if path.name in ("snapshot.py", "_util.py"):
                continue
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r"strftime\(", line):
                    offenders.append(f"{path.name}:{n}")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
