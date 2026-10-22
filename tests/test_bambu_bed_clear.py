#!/usr/bin/env python3
"""A print starts without asking whether the bed is clear.

Report #371, the owner's words: "bambu print just prints without asking if the
print bed is clear. It can just assume that is if the printer isn't currently
printing". brAIn's brief told it to hold a print in `questions` while the
printer's state was "finish" or "failed" until the person said the plate was
clear. A printer that is idle, finished, failed or ready starts straight away;
one that is printing or paused is refused with the reason.
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_design_printing import PrintTest, designer, server  # noqa: E402

BRAIN_MCP = os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server",
                         "ha_mcp_server.py")


class TestBrainIsNotToldToAsk(unittest.TestCase):
    def test_the_brief_does_not_hold_a_print_for_a_clear_plate(self):
        brief = designer.brief()
        self.assertNotIn("has not said\nthe plate is clear", brief)
        self.assertNotIn("may still be on the plate", brief)
        self.assertIn("never ask whether the plate is clear", brief)

    def test_the_print_tool_says_not_to_ask_either(self):
        with open(BRAIN_MCP, encoding="utf-8") as handle:
            text = handle.read()
        start = text.index('"name": "bambu_print"')
        self.assertIn("never ask whether the plate is clear", text[start:start + 2500])


class TestAFinishedPrinterStartsAtOnce(PrintTest):
    def start(self):
        part = self.part()
        return server.start_design_print(self.panel, part["id"], printer="X1C",
                                         slots={"Cube": 1, "Logo": 0})

    def test_finished_failed_and_idle_printers_start(self):
        for state in ("finish", "failed", "idle"):
            self.client._summary.update(state=state, printing=False)
            job, _prepared, _sentence = self.start()
            self.assertNotEqual(job["state"], "failed", (state, job))
        self.wait_sent(3)

    def test_a_paused_printer_is_refused_with_the_reason(self):
        self.client._summary.update(state="pause", printing=True)
        with self.assertRaises(server.PrintRefused) as caught:
            self.start()
        self.assertIn("paused", str(caught.exception))
        self.assertEqual(self.sent, [])

    def test_a_printing_printer_is_refused(self):
        self.client._summary.update(state="running", printing=True)
        with self.assertRaises(server.PrintRefused) as caught:
            self.start()
        self.assertIn("already printing", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
