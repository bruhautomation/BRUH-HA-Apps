"""The header clock says AM/PM and the date, and Header tabs reaches the mark's choice.

* `shellClockParts` is lifted out of app.js and run under node: a 12-hour
  preference keeps AM/PM, a 24-hour one has none, and a short date comes
  with it.
* ⚙ › Dashboard › Header tabs links to ⚙ › Personality › Header, where the
  top bar's mark is chosen.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
JS = (PANEL / "app.js").read_text(encoding="utf-8")


def _lift(name: str) -> str:
    m = re.search(r"^function " + re.escape(name) + r"\(.*?^\}\n", JS, re.S | re.M)
    assert m, name
    return m.group(0)


class TestTheClock(unittest.TestCase):
    def parts(self, clock):
        body = ("const d = new Date(2026, 9, 30, 19, 6);"
                "console.log(JSON.stringify(shellClockParts(d, %s)));" % json.dumps(clock))
        res = subprocess.run(["node", "-e", _lift("shellClockParts") + body],
                             capture_output=True, text=True, timeout=30,
                             env={**os.environ, "LANG": "en_US.UTF-8", "TZ": "UTC"})
        self.assertEqual(res.returncode, 0, res.stderr)
        return json.loads(res.stdout)

    def test_twelve_hour_keeps_the_day_period_and_has_a_date(self):
        p = self.parts(12)
        self.assertRegex(p["time"], r"^7:06\s?PM$")
        self.assertEqual(p["date"], "Fri, Oct 30")

    def test_twenty_four_hour_has_no_day_period(self):
        self.assertEqual(self.parts(24)["time"], "19:06")

    def test_the_element_holds_both_and_stacks_on_a_phone(self):
        html = (PANEL / "index.html").read_text(encoding="utf-8")
        self.assertRegex(html, r'id="shellClock"[^>]*>\s*<span class="shdate">')
        css = (PANEL / "style.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"max-width: 600px\)\s*\{\s*html\.in-shell \.shellclock[^}]*flex-direction: column")


class TestHeaderTabsReachTheMark(unittest.TestCase):
    def test_header_tabs_links_to_personality_header(self):
        sec = JS[JS.index('<h4 class="sethead">Header tabs</h4>'):]
        sec = sec[:sec.index("Learning loop")]
        self.assertIn('data-dash-act="header_mark"', sec)
        self.assertIn('act === "header_mark"', JS)
        self.assertRegex(JS, r'act === "header_mark"\) \{[^}]*showSettingsSection\("personality"\)')


if __name__ == "__main__":
    unittest.main()
