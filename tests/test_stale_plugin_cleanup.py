#!/usr/bin/env python3
"""The boot's stale-plugin cleanup leaves nothing it would find again.

`run.sh` greps Claude Code's settings files for the retired Home Assistant
plugin and rewrites the ones it finds with a jq program. The program took
out `.plugins`, `.extensions`, the plugin's MCP server and its permission
lines, but not `enabledPlugins` — so the file kept matching the grep, and
every boot logged "Found stale reference" and then the health check's
"Broken plugin reference" for the same line (#636).

Driven here: the jq program is lifted out of the real script and run over
settings shaped the way Claude Code writes them; afterwards the grep the
boot runs must find nothing, and what is not stale must still be there.
"""

import json
import re
import subprocess
import unittest
from pathlib import Path

RUN_SH = Path(__file__).resolve().parent.parent / "brain" / "run.sh"
# The same alternation the boot's grep uses (`grep -q "a\|b\|c"`).
GREP = re.compile(r"claude-homeassistant-plugins|homeassistant-config|/api/mcp")


def cleanup_program() -> str:
    text = RUN_SH.read_text(encoding="utf-8")
    start = text.index('Found stale reference in: $config_file"')
    body = text[start:]
    match = re.search(r"if jq '(.*?)' \"\$config_file\"", body, re.S)
    assert match, "the cleanup's jq program could not be found in run.sh"
    return match.group(1)


def run(settings: dict) -> dict:
    out = subprocess.run(["jq", cleanup_program()], input=json.dumps(settings),
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


class TestNothingStaleSurvives(unittest.TestCase):
    SETTINGS = {
        "enabledPlugins": {
            "homeassistant-config@claude-homeassistant-plugins": True,
            "other-tool@somebody-else": True,
        },
        "extraKnownMarketplaces": {
            "claude-homeassistant-plugins": {"source": {"repo": "x/y"}},
            "kept-market": {"source": {"repo": "a/b"}},
        },
        "mcpServers": {
            "homeassistant-config": {"url": "http://supervisor/core/api/mcp"},
            "brain": {"command": "python3", "args": ["/opt/ha_mcp_server.py"]},
        },
        "permissions": {"allow": [
            "mcp__homeassistant-config__get_state", "Bash(ls:*)"]},
        "plugins": {"x": 1},
        "model": "sonnet",
    }

    def test_the_enabled_plugin_entry_goes(self):
        cleaned = run(self.SETTINGS)
        self.assertEqual(cleaned["enabledPlugins"],
                         {"other-tool@somebody-else": True})

    def test_the_boots_grep_finds_nothing_afterwards(self):
        cleaned = json.dumps(run(self.SETTINGS))
        self.assertIsNone(GREP.search(cleaned), cleaned)

    def test_what_is_not_stale_is_kept(self):
        cleaned = run(self.SETTINGS)
        self.assertEqual(cleaned["model"], "sonnet")
        self.assertIn("brain", cleaned["mcpServers"])
        self.assertEqual(cleaned["permissions"]["allow"], ["Bash(ls:*)"])
        self.assertIn("kept-market", cleaned["extraKnownMarketplaces"])
        self.assertNotIn("plugins", cleaned)

    def test_a_file_without_any_of_it_is_unchanged(self):
        clean = {"model": "opus", "permissions": {"allow": ["Read"]}}
        self.assertEqual(run(clean), clean)


if __name__ == "__main__":
    unittest.main()
