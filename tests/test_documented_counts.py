#!/usr/bin/env python3
"""The counts we advertise must match the counts we ship.

"36 native tools" and "65 registry-management services" are the two numbers
brAIn is sold on, and they were typed by hand into nine files across two
repositories. They have gone stale twice: the site said 56 Power Tools for
several releases after nine more shipped, and it said so in six places at
once, because nobody who added a service knew the prose existed.

So the numbers are derived here — from `TOOL_IMPLEMENTATIONS` and from the
`PowerTool(...)` registrations — and every sentence that states one is
checked against them. Adding a tool or a service now fails this test until
the prose catches up, which is the only mechanism that has ever worked.

Deliberately NOT normalised into a generated constant: the sentences read
better with the number in them ("36 native tools for reading and
controlling"), and a docs page that interpolates its own facts is a docs
page nobody proofreads. The number stays written down; the test stays
watching it.
"""

from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
INTEGRATION_DIR = BASE_DIR / "brain" / "custom_components" / "brain"

sys.path.insert(0, str(BASE_DIR / "brain" / "ha-mcp-server"))
import ha_mcp_server  # noqa: E402

# brAIn's own services, as distinct from the Power Tools catalog. Kept in
# step with tests/test_power_tools.py, which asserts services.yaml holds
# exactly these plus the catalog.
CORE_SERVICES = {
    "send_prompt", "run_task", "clear_conversation", "run_insight",
    "add_memory", "answer_question", "study",
}


def power_tool_count() -> int:
    """How many `PowerTool(...)` registrations power_tools.py actually makes."""
    source = (INTEGRATION_DIR / "power_tools.py").read_text()
    return sum(
        1 for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PowerTool"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    )


def mcp_tool_count() -> int:
    """How many tools the MCP server actually exposes."""
    return len(ha_mcp_server.TOOL_IMPLEMENTATIONS)


# Files in THIS repo that state either number in the present tense.
#
# The docs site (bruhautomation.com, a separate repository) states both
# numbers too — see the failure message below. It cannot be reached from
# here, which is exactly why drifting there went unnoticed for six releases.
DOCUMENTED_IN = [
    "README.md",
    "CLAUDE.md",
    "brain/README.md",
    "brain/DOCS.md",
    "brain/panel/docs.js",
    "brain/custom_components/brain/__init__.py",
]

SITE_FILES = """    bruhautomation3/apps/brain/index.mdx
    bruhautomation3/apps/brain/quickstart.mdx
    bruhautomation3/apps/brain/reference.md
    bruhautomation3/apps/brain/how-brain-controls-ha.mdx
    bruhautomation3/apps/brain/power-tools/index.mdx"""

# "65 registry-management services", "65 admin-gated ...", "65 Power Tools",
# "65 admin services", "65 services". The noun varies; the subject doesn't.
SERVICE_CLAIM = re.compile(
    r"\*{0,2}(\d+)\*{0,2}\s+(?:\[?[Pp]ower\s+[Tt]ools\]?|"
    r"(?:admin-gated\s+|admin\s+|registry-management\s+|registry\s+)+services?)")
# "36 native tools", "36 tools", "36 purpose-built MCP tools".
TOOL_CLAIM = re.compile(
    r"\*{0,2}(\d+)\*{0,2}\s+(?:native\s+|purpose-built\s+|MCP\s+)*tools?\b")

# A changelog is a record of what was true at the time, not a claim about
# now. Same for anything describing a past release.
SKIP_LINE = re.compile(r"^\s*(?:##\s*\d|\d+\.\d+\.\d+)")


class TestDocumentedCounts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.services = power_tool_count()
        cls.tools = mcp_tool_count()

    def test_the_catalog_is_the_size_we_think_it_is(self):
        """A sanity floor. If either of these collapses, every assertion
        below would 'pass' against a number nobody meant."""
        self.assertGreater(self.services, 50)
        self.assertGreater(self.tools, 20)

    def test_services_yaml_agrees_with_the_registrations(self):
        """The count is only meaningful if the two places that define it
        already agree — test_power_tools.py pins the names, this pins the
        arithmetic the prose is derived from."""
        import yaml
        with open(INTEGRATION_DIR / "services.yaml") as f:
            catalog = yaml.safe_load(f)
        self.assertEqual(len(set(catalog) - CORE_SERVICES), self.services)

    def test_every_stated_count_matches_what_ships(self):
        """Every present-tense claim in this repo, checked against source."""
        wrong = []
        for rel in DOCUMENTED_IN:
            path = BASE_DIR / rel
            self.assertTrue(path.exists(), f"{rel} is gone — update this list")
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if SKIP_LINE.match(line):
                    continue
                for claimed in SERVICE_CLAIM.findall(line):
                    if int(claimed) != self.services:
                        wrong.append(
                            f"{rel}:{n} says {claimed} services, ships {self.services}")
                for claimed in TOOL_CLAIM.findall(line):
                    if int(claimed) != self.tools:
                        wrong.append(
                            f"{rel}:{n} says {claimed} tools, ships {self.tools}")
        self.assertEqual(wrong, [], "\n".join([
            "",
            "Documented counts no longer match what the code ships:",
            *(f"  {w}" for w in wrong),
            "",
            f"Ships: {self.tools} MCP tools, {self.services} Power Tools.",
            "",
            "The docs site is a SEPARATE REPO and states both numbers too.",
            "This test cannot see it, so update these by hand in the same PR:",
            SITE_FILES,
            "",
        ]))

    def test_the_counts_are_actually_stated_somewhere(self):
        """A regex that matches nothing passes forever. If the prose is
        rewritten so no file states either number, this fails rather than
        quietly becoming a no-op."""
        blob = "\n".join(
            (BASE_DIR / rel).read_text() for rel in DOCUMENTED_IN)
        self.assertTrue(
            [c for c in SERVICE_CLAIM.findall(blob) if int(c) == self.services],
            "no file states the Power Tools count — the guard is now vacuous")
        self.assertTrue(
            [c for c in TOOL_CLAIM.findall(blob) if int(c) == self.tools],
            "no file states the MCP tool count — the guard is now vacuous")


if __name__ == "__main__":
    unittest.main()
