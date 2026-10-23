#!/usr/bin/env python3
"""bambu_print tells brAIn a printer that is not busy is ready (report #371).

The owner's words: "bambu print just prints without asking if the print bed
is clear". BRUH Bambu Studio 0.2.4 stopped asking; the tool's description is
what brAIn reads before it calls, so it says the same.
"""
import os
import unittest

BRAIN_MCP = os.path.join(os.path.dirname(__file__), "..", "brain", "ha-mcp-server",
                         "ha_mcp_server.py")


class TestThePrintToolSaysNotToAsk(unittest.TestCase):
    def test_the_print_tool_says_not_to_ask_whether_the_plate_is_clear(self):
        with open(BRAIN_MCP, encoding="utf-8") as handle:
            text = handle.read()
        start = text.index('"name": "bambu_print"')
        self.assertIn("never ask whether the plate is clear", text[start:start + 2500])


if __name__ == "__main__":
    unittest.main()
