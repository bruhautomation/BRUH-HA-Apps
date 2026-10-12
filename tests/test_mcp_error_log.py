"""`get_error_log` is read by a model, not a terminal.

A house reported it returning raw colour codes (``\\u001b[33m…\\u001b[0m``)
and the newest 100 raw lines, so two warnings repeated once a minute — a
retry message and a websocket disconnect — filled the whole window and hid
every other error. These drive the real tool with the Supervisor answering
the way the journal does: colour codes stripped, a repeat folded into one
line with its count and its first and last time, filters by minimum level
and by logger or message, and the cap spent AFTER folding so the flood
cannot push the error out. The result stays a text string.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "brain", "ha-mcp-server"))

import ha_mcp_server as m  # noqa: E402

YELLOW, RED, RESET = "\x1b[33m", "\x1b[31m", "\x1b[0m"


def line(clock, level, logger, message, thread="MainThread", colour=YELLOW):
    return (f"{colour}2026-10-12 {clock}.123 {level} ({thread}) "
            f"[{logger}] {message}{RESET}")


def flood(minutes=120):
    """Two warnings once a minute for two hours, the house's shape."""
    out = []
    for i in range(minutes):
        hh, mm = divmod(i, 60)
        clock = f"{8 + hh:02d}:{mm:02d}:00"
        out.append(line(clock, "WARNING", "homeassistant.components.mqtt",
                        "Disconnected from MQTT server, retrying in 60 s",
                        thread=f"Thread-{i % 7}"))
        out.append(line(clock.replace(":00", ":30"), "WARNING",
                        "homeassistant.components.websocket_api.http.connection",
                        "Disconnected: Did not receive auth message within 10 seconds"))
    return out


def run(text, **kwargs):
    with patch.object(m, "ha_api_request", return_value=text):
        return m.get_error_log(**kwargs)


class TestColourCodesAreStripped(unittest.TestCase):
    def test_no_escape_reaches_the_model(self):
        out = run("\n".join([
            line("08:00:00", "WARNING", "homeassistant.components.mqtt", "slow"),
            line("08:00:01", "ERROR", "custom_components.foo", "broke", colour=RED),
            "\x1b[1;32ms6-rc: info: service legacy-services successfully started\x1b[0m",
        ]))
        self.assertIsInstance(out, str)
        self.assertNotIn("\x1b", out)
        self.assertNotIn("[33m", out)
        self.assertIn("ERROR (MainThread) [custom_components.foo] broke", out)
        self.assertIn("s6-rc: info: service legacy-services successfully started", out)


class TestRepeatsAreFolded(unittest.TestCase):
    def test_a_repeat_is_one_line_with_its_count_and_times(self):
        out = run("\n".join(flood(3)))
        lines = out.splitlines()
        mqtt = [x for x in lines if "MQTT server" in x]
        self.assertEqual(len(mqtt), 1, out)
        self.assertIn("repeated 3 times, first 08:00:00, last 08:02:00", mqtt[0])
        # The line shown is the newest occurrence, timestamp included.
        self.assertTrue(mqtt[0].startswith("2026-10-12 08:02:00"))
        self.assertIn("4 repeated line(s) folded", lines[0])

    def test_the_thread_name_does_not_split_a_repeat(self):
        out = run("\n".join(flood(10)))
        self.assertEqual(sum("MQTT server" in x for x in out.splitlines()), 1)

    def test_different_messages_are_not_folded(self):
        out = run("\n".join([
            line("08:00:00", "ERROR", "a", "one"),
            line("08:00:01", "ERROR", "a", "two"),
            line("08:00:02", "ERROR", "b", "one"),
        ]))
        self.assertNotIn("repeated", out)
        self.assertEqual(len(out.splitlines()), 3)

    def test_a_traceback_rides_with_its_entry(self):
        tb = [line("08:00:00", "ERROR", "homeassistant.core", "Error doing job"),
              "Traceback (most recent call last):",
              '  File "/usr/src/homeassistant/core.py", line 1, in run',
              "    raise ValueError('x')",
              "ValueError: x"]
        out = run("\n".join(tb + tb))
        self.assertEqual(out.count("Traceback"), 1, out)
        self.assertEqual(out.count("ValueError: x"), 1, out)
        self.assertIn("repeated 2 times", out)


class TestTheFloodCannotHideTheRest(unittest.TestCase):
    def test_an_error_before_two_hours_of_warnings_survives(self):
        raw = [line("07:59:00", "ERROR", "homeassistant.components.zwave_js",
                     "Failed to connect to Z-Wave JS server", colour=RED)]
        raw += flood(120)
        raw.append(line("10:05:00", "INFO", "homeassistant.components.http",
                        "Serving on port 8123"))
        self.assertGreater(len(raw), 200)
        out = run("\n".join(raw))
        self.assertIn("Failed to connect to Z-Wave JS server", out)
        self.assertIn("Serving on port 8123", out)
        self.assertLessEqual(len(out.splitlines()), m.MAX_ERROR_LOG_LINES)
        # The shipped tool took the last 100 raw lines: proof of what it lost.
        old = "\n".join("\n".join(raw).split("\n")[-100:])
        self.assertNotIn("Z-Wave JS server", old)

    def test_the_cap_is_on_distinct_lines_and_says_what_it_left(self):
        raw = [line(f"08:{i // 60:02d}:{i % 60:02d}", "ERROR", "x", f"error {i}")
               for i in range(150)]
        out = run("\n".join(raw))
        lines = out.splitlines()
        self.assertEqual(len(lines), m.MAX_ERROR_LOG_LINES)
        # 99 entries and the note: the note takes a line of the budget.
        self.assertEqual(lines[0], "(51 older distinct entries not shown)")
        self.assertIn("error 149", lines[-1])

    def test_one_huge_traceback_is_still_capped(self):
        raw = [line("08:00:00", "ERROR", "x", "boom"),
               "Traceback (most recent call last):"]
        raw += [f'  File "f{i}.py", line {i}, in g' for i in range(300)]
        out = run("\n".join(raw))
        self.assertLessEqual(len(out.splitlines()), m.MAX_ERROR_LOG_LINES)


class TestFilters(unittest.TestCase):
    RAW = "\n".join([
        line("08:00:00", "DEBUG", "homeassistant.core", "tick"),
        line("08:00:01", "INFO", "homeassistant.components.http", "ready"),
        line("08:00:02", "WARNING", "homeassistant.components.mqtt", "slow broker"),
        line("08:00:03", "ERROR", "homeassistant.components.zwave_js", "node 5 dead"),
        line("08:00:04", "CRITICAL", "homeassistant.bootstrap", "safe mode"),
        "s6-rc: info: service legacy-services successfully started",
    ])

    def test_a_minimum_level(self):
        out = run(self.RAW, level="error")
        self.assertIn("node 5 dead", out)
        self.assertIn("safe mode", out)
        for gone in ("tick", "ready", "slow broker", "s6-rc"):
            self.assertNotIn(gone, out)
        out = run(self.RAW, level="WARNING")
        self.assertIn("slow broker", out)
        self.assertNotIn("ready", out)

    def test_a_logger_or_message_substring(self):
        out = run(self.RAW, match="ZWAVE_JS")
        self.assertEqual(out.splitlines(),
                         ["2026-10-12 08:00:03.123 ERROR (MainThread) "
                          "[homeassistant.components.zwave_js] node 5 dead"])
        self.assertIn("slow broker", run(self.RAW, match="broker"))

    def test_both_together_and_nothing_left(self):
        self.assertIn("node 5 dead", run(self.RAW, level="ERROR", match="zwave"))
        out = run(self.RAW, level="ERROR", match="mqtt")
        self.assertIsInstance(out, str)
        self.assertIn("No log lines at ERROR or above matching 'mqtt'", out)

    def test_an_unknown_level_is_refused_before_asking(self):
        with patch.object(m, "ha_api_request") as api:
            out = m.get_error_log(level="LOUD")
        self.assertIn("error", out)
        api.assert_not_called()

    def test_the_schema_offers_both_and_the_dispatcher_passes_them(self):
        spec = next(t for t in m.TOOLS if t["name"] == "get_error_log")
        props = spec["inputSchema"]["properties"]
        self.assertEqual(set(props), {"level", "match"})
        self.assertEqual(props["level"]["enum"], list(m.LOG_LEVELS))
        self.assertNotIn("required", spec["inputSchema"])
        with patch.object(m, "ha_api_request", return_value=self.RAW):
            out = m.handle_tool_call("get_error_log", {"level": "CRITICAL"})
        self.assertEqual(out.splitlines(),
                         ["2026-10-12 08:00:04.123 CRITICAL (MainThread) "
                          "[homeassistant.bootstrap] safe mode"])

    def test_the_fallback_endpoint_is_formatted_too(self):
        calls = []

        def api(path, **kw):
            calls.append(path)
            if path == "/core/logs":
                return {"error": "nope"}
            return self.RAW.replace("08:00", "\x1b[31m08:00")

        with patch.object(m, "ha_api_request", side_effect=api):
            out = m.get_error_log(level="CRITICAL")
        self.assertEqual(calls, ["/core/logs", "/api/error_log"])
        self.assertNotIn("\x1b", out)
        self.assertIn("safe mode", out)


if __name__ == "__main__":
    unittest.main()
