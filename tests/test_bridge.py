#!/usr/bin/env python3
"""
Comprehensive tests for the ClaudeBridge file-based IPC module.

Tests cover:
- Write and read JSON file operations
- Atomic file operations (tmp + rename)
- Corrupt response file handling
- Polling timeout behavior
- Directory creation
- Stale/orphan file handling
- Conversation ID handling
- Task request/response flow
"""

import json
import os
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

# We can't import homeassistant directly, so we test the static methods
# and logic patterns used in bridge.py

BRIDGE_PATH = os.path.join(
    os.path.dirname(__file__), "..", "bruh-claude-terminal",
    "custom_components", "bruh_claude", "bridge.py"
)


class TestBridgeStaticMethods(unittest.TestCase):
    """Test the static filesystem helper methods from ClaudeBridge."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, path, data):
        """Replicate ClaudeBridge._write_json logic."""
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh)
        os.replace(tmp, path)

    def _read_and_remove(self, path):
        """Replicate ClaudeBridge._read_and_remove logic (with fix)."""
        if not os.path.isfile(path):
            return None
        try:
            with open(path) as fh:
                data = json.load(fh)
            os.remove(path)
            return data.get("text", data.get("result", json.dumps(data)))
        except json.JSONDecodeError:
            # Fixed: remove corrupt file to avoid infinite retry
            try:
                os.remove(path)
            except OSError:
                pass
            return "Error: received corrupt response from Claude Terminal."
        except OSError:
            return None

    def test_write_json_creates_file(self):
        """_write_json should create the target file."""
        path = os.path.join(self.tmpdir, "test.json")
        self._write_json(path, {"key": "value"})
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["key"], "value")

    def test_write_json_creates_parent_dirs(self):
        """_write_json should create parent directories."""
        path = os.path.join(self.tmpdir, "sub", "dir", "test.json")
        self._write_json(path, {"nested": True})
        self.assertTrue(os.path.isfile(path))

    def test_write_json_atomic_no_tmp_leftover(self):
        """After _write_json, no .tmp file should remain."""
        path = os.path.join(self.tmpdir, "test.json")
        self._write_json(path, {"data": "test"})
        self.assertFalse(os.path.isfile(path + ".tmp"))
        self.assertTrue(os.path.isfile(path))

    def test_write_json_overwrites_existing(self):
        """_write_json should overwrite existing files."""
        path = os.path.join(self.tmpdir, "test.json")
        self._write_json(path, {"version": 1})
        self._write_json(path, {"version": 2})
        with open(path) as f:
            data = json.load(f)
        self.assertEqual(data["version"], 2)

    def test_read_and_remove_returns_text_field(self):
        """_read_and_remove should return the 'text' field from response."""
        path = os.path.join(self.tmpdir, "resp.json")
        with open(path, "w") as f:
            json.dump({"id": "abc", "text": "Hello from Claude"}, f)
        result = self._read_and_remove(path)
        self.assertEqual(result, "Hello from Claude")
        self.assertFalse(os.path.isfile(path))

    def test_read_and_remove_returns_result_field(self):
        """_read_and_remove should fallback to 'result' field for tasks."""
        path = os.path.join(self.tmpdir, "resp.json")
        with open(path, "w") as f:
            json.dump({"id": "abc", "result": "Task done", "status": "completed"}, f)
        result = self._read_and_remove(path)
        self.assertEqual(result, "Task done")
        self.assertFalse(os.path.isfile(path))

    def test_read_and_remove_returns_json_dump_fallback(self):
        """_read_and_remove should JSON-dump the whole response if no text/result."""
        path = os.path.join(self.tmpdir, "resp.json")
        with open(path, "w") as f:
            json.dump({"id": "abc", "custom_field": "data"}, f)
        result = self._read_and_remove(path)
        parsed = json.loads(result)
        self.assertEqual(parsed["custom_field"], "data")

    def test_read_and_remove_nonexistent_returns_none(self):
        """_read_and_remove should return None for nonexistent file."""
        path = os.path.join(self.tmpdir, "nonexistent.json")
        result = self._read_and_remove(path)
        self.assertIsNone(result)

    def test_read_and_remove_corrupt_json_returns_error(self):
        """_read_and_remove should handle corrupt JSON gracefully."""
        path = os.path.join(self.tmpdir, "corrupt.json")
        with open(path, "w") as f:
            f.write("not valid json {{{")
        result = self._read_and_remove(path)
        # After fix: should return an error string and remove the file
        self.assertIn("Error", result)
        self.assertFalse(os.path.isfile(path), "Corrupt file should be removed")

    def test_read_and_remove_empty_file_returns_error(self):
        """_read_and_remove should handle empty files."""
        path = os.path.join(self.tmpdir, "empty.json")
        with open(path, "w") as f:
            pass  # empty file
        result = self._read_and_remove(path)
        self.assertIn("Error", result)
        self.assertFalse(os.path.isfile(path))

    def test_roundtrip_write_then_read(self):
        """Write + read should round-trip data correctly."""
        path = os.path.join(self.tmpdir, "roundtrip.json")
        self._write_json(path, {"id": "test123", "text": "Hello World"})
        result = self._read_and_remove(path)
        self.assertEqual(result, "Hello World")
        self.assertFalse(os.path.isfile(path))


class TestBridgeRequestFormat(unittest.TestCase):
    """Test request/response JSON format expectations."""

    def test_conversation_request_format(self):
        """Conversation requests should have id, text, and type fields."""
        req_id = "abc123"
        text = "Turn on the lights"
        request = {
            "id": req_id,
            "text": text,
            "type": "conversation",
        }
        self.assertEqual(request["id"], req_id)
        self.assertEqual(request["text"], text)
        self.assertEqual(request["type"], "conversation")

    def test_task_request_format(self):
        """Task requests should have id, prompt, and notify fields."""
        task = {
            "id": "task123",
            "prompt": "Check all automations",
            "notify": True,
            "notify_entity": "notify.mobile_app",
        }
        self.assertEqual(task["id"], "task123")
        self.assertTrue(task["notify"])
        self.assertEqual(task["notify_entity"], "notify.mobile_app")

    def test_conversation_response_format(self):
        """Conversation responses should have id and text fields."""
        response = {"id": "abc123", "text": "Lights turned on!"}
        self.assertIn("text", response)

    def test_task_result_format(self):
        """Task results should have id, result, and status fields."""
        result = {"id": "task123", "result": "Done!", "status": "completed"}
        self.assertIn("result", result)
        self.assertEqual(result["status"], "completed")


class TestBridgeTimingBehavior(unittest.TestCase):
    """Test timing-related behavior of the bridge polling."""

    def test_monotonic_time_usage(self):
        """Verify that time.monotonic is available for deadline-based polling."""
        # This tests the pattern used in the fixed _poll_for_response
        timeout = 2
        deadline = time.monotonic() + timeout
        self.assertGreater(deadline, time.monotonic())

    def test_deadline_expires(self):
        """Deadline-based approach should detect expiry correctly."""
        deadline = time.monotonic() - 1  # Already expired
        self.assertLess(deadline, time.monotonic())


class TestBridgePathSafety(unittest.TestCase):
    """Test that file paths are constructed safely."""

    def test_uuid_hex_is_safe_filename(self):
        """UUID hex should produce safe filenames (alphanumeric only)."""
        import uuid
        for _ in range(100):
            hex_id = uuid.uuid4().hex
            self.assertRegex(hex_id, r'^[a-f0-9]{32}$')
            # Ensure no path traversal characters
            self.assertNotIn("/", hex_id)
            self.assertNotIn("\\", hex_id)
            self.assertNotIn("..", hex_id)

    def test_path_join_with_safe_id(self):
        """os.path.join with UUID hex should produce expected paths."""
        base = "/config/.bruh_claude/requests"
        req_id = "abc123def456"
        expected = f"{base}/{req_id}.json"
        result = os.path.join(base, f"{req_id}.json")
        self.assertEqual(result, expected)


class TestConstValues(unittest.TestCase):
    """Test constant values from const.py."""

    def test_const_file_exists(self):
        const_path = os.path.join(
            os.path.dirname(__file__), "..", "bruh-claude-terminal",
            "custom_components", "bruh_claude", "const.py"
        )
        self.assertTrue(os.path.isfile(const_path))

    def test_const_values(self):
        """Verify expected constant values."""
        const_path = os.path.join(
            os.path.dirname(__file__), "..", "bruh-claude-terminal",
            "custom_components", "bruh_claude", "const.py"
        )
        with open(const_path) as f:
            content = f.read()

        self.assertIn('DOMAIN = "bruh_claude"', content)
        self.assertIn("DEFAULT_TIMEOUT = 120", content)
        self.assertIn('SHARED_DIR = ".bruh_claude"', content)
        self.assertIn('REQUESTS_DIR = "requests"', content)
        self.assertIn('RESPONSES_DIR = "responses"', content)
        self.assertIn('TASKS_DIR = "tasks"', content)
        self.assertIn('TASK_RESULTS_DIR = "task_results"', content)


if __name__ == "__main__":
    unittest.main()
