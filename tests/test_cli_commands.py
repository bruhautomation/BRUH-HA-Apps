#!/usr/bin/env python3
"""The `brain` / `ha` dispatchers as an autocomplete list.

Claude Code announces its slash commands over the stream. The add-on's own
two CLIs are the other half of what anyone types into the chat box, and they
are not slash commands — so nothing offered them. They do announce
themselves, just not over a wire: `brain help` and `ha help` print the list.

Parsing that output is the point: a subcommand added to a dispatcher shows
up in the palette without anyone touching the panel, which a second
hardcoded copy of the list could never promise. So the test that matters is
that the parser handles the dispatchers *as they are actually written*.
"""

import importlib
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
sys.path.insert(0, str(PANEL))


class TestAgainstTheRealDispatchers(unittest.TestCase):
    """Run the shipped brain.sh / ha.sh and parse what they print."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        binaries = Path(cls.tmp.name)
        for name in ("brain", "ha"):
            target = binaries / name
            target.write_text((SCRIPTS / f"{name}.sh").read_text())
            target.chmod(target.stat().st_mode | stat.S_IEXEC)
        cls._path = os.environ["PATH"]
        os.environ["PATH"] = f"{binaries}{os.pathsep}{cls._path}"
        import cli_commands
        cls.mod = importlib.reload(cli_commands)
        cls.commands = cls.mod.listing()

    @classmethod
    def tearDownClass(cls):
        os.environ["PATH"] = cls._path
        cls.tmp.cleanup()

    def names(self):
        return [c["name"] for c in self.commands]

    def test_both_dispatchers_are_read(self):
        names = self.names()
        self.assertTrue(any(n.startswith("brain ") for n in names))
        self.assertTrue(any(n.startswith("ha ") for n in names))

    def test_top_level_commands_are_found(self):
        for expected in ("brain learn", "brain undo", "brain doctor",
                         "ha log", "ha reload", "ha entity"):
            self.assertIn(expected, self.names())

    def test_subcommands_are_attached_to_their_parent(self):
        """`brain memory add` is the useful entry — "memory" on its own is
        a family, not something you run."""
        for expected in ("brain memory add", "brain memory list",
                         "brain memory hypotheses", "brain memory consolidate"):
            self.assertIn(expected, self.names())

    def test_each_entry_carries_its_description_and_argument_hint(self):
        by_name = {c["name"]: c for c in self.commands}
        self.assertEqual(by_name["brain learn"]["hint"], "[topic]")
        self.assertIn("Study the home", by_name["brain learn"]["description"])
        self.assertEqual(by_name["brain memory add"]["hint"], '"<fact>"')
        self.assertIn("Teach it", by_name["brain memory add"]["description"])
        self.assertEqual(by_name["ha reload"]["hint"], "[domain]")

    def test_the_list_is_sorted_and_free_of_duplicates(self):
        names = self.names()
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), len(set(names)))

    def test_nothing_is_invented(self):
        """Every entry has to come from a dispatcher — the whole reason for
        parsing rather than hardcoding is that this list cannot drift."""
        for name in self.names():
            self.assertRegex(name, r"^(brain|ha|hass) ")


class TestWithoutTheDispatchers(unittest.TestCase):
    def test_a_dev_checkout_gets_an_empty_list_not_an_error(self):
        """The panel runs in environments where neither is installed — a
        dev checkout, or `enable_terminal: false`. The palette just has no
        CLI half."""
        import cli_commands
        mod = importlib.reload(cli_commands)
        old = os.environ["PATH"]
        os.environ["PATH"] = "/nonexistent"
        try:
            mod.reset_cache()
            self.assertEqual(mod.listing(), [])
        finally:
            os.environ["PATH"] = old
            mod.reset_cache()

    def test_the_answer_is_cached(self):
        """Shelling out twice per keystroke would be absurd, and the
        dispatchers are baked into the image so the answer cannot change
        under a running add-on."""
        import cli_commands
        mod = importlib.reload(cli_commands)
        mod._cache = [{"name": "brain sentinel", "hint": "", "description": ""}]
        self.assertEqual(mod.listing()[0]["name"], "brain sentinel")
        mod.reset_cache()


if __name__ == "__main__":
    unittest.main()
