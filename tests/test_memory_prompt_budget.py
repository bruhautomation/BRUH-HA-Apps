#!/usr/bin/env python3
"""The insight bundle's memory budget, bound to the option that fills it.

`ha_data.MEMORY_CHARS` exists because memory and the CLAUDE.md excerpt used
to share 4 KB: any real document arrived truncated mid-fact and a full one
starved the house context. It was then sized off `memory_max_kb`'s DEFAULT
(32) while the schema allows 64 — so the one action the consolidator tells a
homeowner to take when the document is full ("raise memory_max_kb") brought
the original failure straight back, silently, because a truncated document
reads exactly like a shorter one.

The bound is read out of config.yaml here rather than written down again:
a number remembered in two files is a number that drifts the day one of
them moves, and this is the file that would notice.
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
PANEL_DIR = ADDON_DIR / "panel"

sys.path.insert(0, str(PANEL_DIR))

import ha_data  # noqa: E402


def schema_max_kb() -> int:
    """`memory_max_kb: "int(1,64)?"` → 64, off the shipped manifest."""
    with open(ADDON_DIR / "config.yaml", encoding="utf-8") as fh:
        schema = yaml.safe_load(fh)["schema"]
    spec = schema["memory_max_kb"]
    match = re.fullmatch(r"int\((\d+),(\d+)\)\??", str(spec))
    assert match, f"memory_max_kb schema is no longer a bounded int: {spec!r}"
    return int(match.group(2))


class TestTheBudgetIsBoundToTheSchema(unittest.TestCase):

    def test_the_ceiling_is_the_schema_s_own_bound(self):
        self.assertEqual(ha_data.MEMORY_MAX_KB_CEILING, schema_max_kb())

    def test_the_largest_allowed_document_arrives_whole(self):
        """The bug: sized for 32 KB, allowed to reach 64."""
        self.assertGreaterEqual(
            ha_data.MEMORY_CHARS, schema_max_kb() * 1024 + 1000,
            "a document at the cap would be cut mid-fact",
        )

    def test_the_old_constant_would_have_failed_this(self):
        """Reproduced rather than described: 34_000 is what shipped."""
        self.assertLess(34_000, schema_max_kb() * 1024)


class TestTheBudgetFollowsTheConfiguredCap(unittest.TestCase):
    """Read at call time, the way `insights_enabled()` is, so lowering the
    cap costs nothing and raising it does not need a restart."""

    def setUp(self):
        self._env = os.environ.get("BRAIN_MEMORY_MAX_KB")
        self.addCleanup(self._restore)

    def _restore(self):
        if self._env is None:
            os.environ.pop("BRAIN_MEMORY_MAX_KB", None)
        else:
            os.environ["BRAIN_MEMORY_MAX_KB"] = self._env

    def test_no_answer_is_the_ceiling(self):
        os.environ.pop("BRAIN_MEMORY_MAX_KB", None)
        self.assertEqual(ha_data.memory_budget(), ha_data.MEMORY_CHARS)

    def test_a_lowered_cap_lowers_the_budget(self):
        os.environ["BRAIN_MEMORY_MAX_KB"] = "8"
        self.assertEqual(ha_data.memory_budget(),
                         8 * 1024 + ha_data.MEMORY_SLACK_CHARS)

    def test_the_default_cap_still_fits_its_own_document(self):
        os.environ["BRAIN_MEMORY_MAX_KB"] = "32"
        self.assertGreaterEqual(ha_data.memory_budget(), 32 * 1024)

    def test_nonsense_and_out_of_range_fall_back_to_the_ceiling(self):
        """Not to the default: an over-generous budget costs characters,
        an under-generous one cuts a fact in half and says nothing."""
        for value in ("", "lots", "0", "-4", "999"):
            os.environ["BRAIN_MEMORY_MAX_KB"] = value
            self.assertEqual(ha_data.memory_budget(), ha_data.MEMORY_CHARS,
                             value)


class TestWhatActuallyReachesThePrompt(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(self.tmp, True))
        self._memory, self._context = ha_data.MEMORY_FILE, ha_data.CONTEXT_FILE
        ha_data.MEMORY_FILE = os.path.join(self.tmp, "memory.md")
        ha_data.CONTEXT_FILE = os.path.join(self.tmp, "CLAUDE.md")
        self.addCleanup(self._restore_paths)
        self._env = os.environ.pop("BRAIN_MEMORY_MAX_KB", None)
        self.addCleanup(self._restore_env)

    def _restore_paths(self):
        ha_data.MEMORY_FILE, ha_data.CONTEXT_FILE = self._memory, self._context

    def _restore_env(self):
        if self._env is not None:
            os.environ["BRAIN_MEMORY_MAX_KB"] = self._env

    def test_a_document_at_the_schema_s_cap_is_injected_whole(self):
        cap = schema_max_kb() * 1024
        facts, size = [], 0
        while size < cap:
            fact = f"- fact {len(facts)}: " + "x" * 60
            facts.append(fact)
            size += len(fact) + 1
        doc = "\n".join(facts)
        with open(ha_data.MEMORY_FILE, "w", encoding="utf-8") as fh:
            fh.write(doc)
        ctx = ha_data._read_context()
        self.assertIn(facts[-1], ctx, "the tail of a full document was cut")
        self.assertEqual(ctx.count("- fact "), len(facts))


if __name__ == "__main__":
    unittest.main()
