#!/usr/bin/env python3
"""What a check says carries no developer string, and one state per finding.

A real house's findings showed file paths with line numbers, hex error
codes, tool and protocol names, and device-health titles ("struggling")
that disagreed with their own detail. `house_words.technical` already takes
those out of a model-written row; a check's rows are left as their rule
wrote them (`test_technical_details`), so the rule itself has to be
clean. This sweeps every check the way `test_finding_text_plain` does and
fails the one that is not:

* a path, a line number, a hex code, one of brAIn's tool names or a
  protocol term in `text`, `detail` or `fix`;
* a finding whose title, detail and fix do not name the same device state
  (`house_words.states_named`): "the signal looked fine" over a fix that
  moves the router, or an offline title over a battery fix.
"""

import io
import re
import sys
import unittest
from pathlib import Path

TESTS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS_DIR.parent / "brain" / "panel"))
sys.path.insert(0, str(TESTS_DIR))

import house_words  # noqa: E402
from test_finding_text_plain import MAC_ALLOWED, SWEEP_MODULES, _Capture  # noqa: E402

DEVELOPER = re.compile(
    r"(?<![\w/.])/(?:config|data|opt|usr|etc|var|share|ssl)(?:/[\w.\-]+)+"
    r"|\bline \d+\b|\b0x[0-9a-f]+\b|\bmcp__"
    r"|\b(?:RSSI|LQI|ZCL|APS|NWK|ICMP|mDNS|DHCP|SSDP|UDP|TCP|ARP)\b"
    r"|-build\.\d+|\+g[0-9a-f]{7}")


def developer_words(row: dict) -> list[str]:
    tools = house_words.tool_names()
    out = []
    for field in ("text", "detail", "fix"):
        prose = str(row.get(field) or "")
        out += [m.group(0) for m in DEVELOPER.finditer(prose)]
        out += [t for t in tools if re.search(rf"(?<![\w.]){t}(?!\w)", prose)]
    return out


class TestEveryCheckIsFreeOfDeveloperWords(unittest.TestCase):
    def test_sweep(self):
        with _Capture() as cap:
            suite = unittest.defaultTestLoader.loadTestsFromNames(
                SWEEP_MODULES)
            result = unittest.TextTestRunner(
                stream=io.StringIO(), verbosity=0).run(suite)
        self.assertTrue(result.wasSuccessful())
        self.assertGreater(len(cap.rows), 20)
        bad = sorted({f"{cid}: {developer_words(row)}"
                      for cid, row, _s in cap.rows
                      if cid not in MAC_ALLOWED and developer_words(row)})
        self.assertEqual(bad, [], "\n".join(bad))
        incoherent = sorted({
            f"{cid}: {row.get('text')!r} / {row.get('fix')!r}"
            for cid, row, _s in cap.rows
            if house_words.states_disagree(
                row.get("text"), row.get("detail"), row.get("fix"))})
        self.assertEqual(incoherent, [], "\n".join(incoherent))
