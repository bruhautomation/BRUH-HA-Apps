#!/usr/bin/env python3
"""`brain doctor --json` — the self-test as one JSON object.

The report block (recording, printing, the emitter) is lifted out of the
real script and driven in a shell, the way test_memory_learning drives
``consolidator_lock_check``: a grep for a line is not a test of what the
line does.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "brain" / "scripts" / "ha-selftest.sh"


def report_block() -> str:
    src = SCRIPT.read_text(encoding="utf-8")
    match = re.search(r"^JSON_MODE=0\n.*?^PYEMIT\n\}\n", src, re.M | re.S)
    assert match, "ha-selftest.sh no longer defines the JSON report block"
    return match.group(0)


def run(args: str, body: str) -> subprocess.CompletedProcess:
    script = (
        "set -u\n"
        + report_block()
        + "\n" + body
        + '\nif [ "$JSON_MODE" = "1" ]; then emit_json; rm -f "$RECORDS"; exit 0; fi\n'
        + 'rm -f "$RECORDS"\n'
    )
    return subprocess.run(["bash", "-c", script, "doctor"] + args.split(),
                          capture_output=True, text=True, timeout=30)


BODY = '''
hdr "Environment & Home Assistant API"
pass "token present"
info "a detail, with \\"quotes\\" and a | pipe"
hdr "Background listeners"
warn "study watcher not running"
fail "Panel not answering (:8099/api/health)"
'''


class TestJsonMode(unittest.TestCase):
    def test_json_mode_prints_one_object_and_nothing_else(self):
        proc = run("--json", BODY)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        data = json.loads(proc.stdout)  # the whole of stdout parses
        self.assertFalse(data["ok"])
        self.assertEqual((data["passed"], data["failed"], data["warnings"]), (1, 1, 1))
        kinds = [c["kind"] for c in data["checks"]]
        self.assertEqual(kinds, ["pass", "info", "warn", "fail"])
        self.assertEqual(data["checks"][0]["section"], "Environment & Home Assistant API")
        self.assertEqual(data["checks"][3]["section"], "Background listeners")
        self.assertIn('"quotes"', data["checks"][1]["text"])
        self.assertIn("|", data["checks"][1]["text"])

    def test_text_mode_is_unchanged(self):
        proc = run("", BODY)
        self.assertIn("✓ token present", proc.stdout)
        self.assertIn("✗ Panel not answering", proc.stdout)
        self.assertIn("! study watcher", proc.stdout)
        self.assertNotIn("{", proc.stdout)

    def test_the_real_script_routes_the_flag_and_the_dispatcher_offers_it(self):
        src = SCRIPT.read_text(encoding="utf-8")
        self.assertIn('if [ "$JSON_MODE" = "1" ]; then\n    emit_json', src)
        dispatcher = (REPO / "brain" / "scripts" / "brain.sh").read_text(encoding="utf-8")
        self.assertIn("brain doctor [--json]", dispatcher)
        self.assertIn("check)      delegate brain-check.sh", dispatcher)
        self.assertIn("report)     delegate brain-report.sh", dispatcher)


class TestReportScript(unittest.TestCase):
    """`brain report` redacts every file, whether or not it thinks it needs to."""

    def test_redaction_covers_the_credential_shapes(self):
        src = (REPO / "brain" / "scripts" / "brain-report.sh").read_text(encoding="utf-8")
        match = re.search(r"^redact\(\) \{\n.*?^\}\n", src, re.M | re.S)
        assert match, "brain-report.sh no longer defines redact()"
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp, "sample.json")
            path.write_text(
                'token sk-ant-oat01-ABCDEFGHIJKLMNOPQRSTUVWXYZ here\n'
                'Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123\n'
                '{"access_token": "0123456789abcdef", "value": "sk-ant-api03-zzzzzzzzzzzz"}\n'
                'jwt eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV\n'
                'sensor.kitchen_temperature is fine\n')
            proc = subprocess.run(
                ["bash", "-c", match.group(0) + f'\nredact "{path}"\n'],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            out = path.read_text()
        self.assertNotIn("sk-ant-", out)
        self.assertNotIn("abcdefghijklmnopqrstuvwxyz0123", out)
        self.assertNotIn("0123456789abcdef", out)
        self.assertNotIn("eyJhbGci", out)
        self.assertIn("sensor.kitchen_temperature", out)
        self.assertGreaterEqual(out.count("[redacted]"), 5)


if __name__ == "__main__":
    unittest.main()
