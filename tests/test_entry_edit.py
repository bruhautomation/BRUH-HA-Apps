"""Editing ONE entry in somebody's YAML, and leaving every other byte alone.

1.44.0's writer appends and never re-serialises, because `automations.yaml`
is somebody's file with their ordering, their comments and their quoting in
it. Two producers in 1.46.0 have to change an entry that is already there —
a condition added to an automation somebody keeps undoing, and a one-off
intent removed once it has fired — and re-serialising the list to do that
would hand back a diff nobody asked for on every press.

So the edit is a byte splice, and the load-bearing test is not "the file
still parses". It is that **every byte outside the span is identical**: a
writer that round-tripped through PyYAML would pass a parse test, keep the
data, and quietly delete the comments.

Each test names the mutation it catches:

  bytes outside the span     round-trip the list instead of splicing ->
                             comments, quoting and ordering are gone
  the leading `- `           start the span at the node -> the dash of the
                             replaced entry is left behind and the file no
                             longer parses
  a block node's end_mark    trust `end_mark` on a block mapping -> the
                             trailing comment after the last entry, and any
                             blank line after any entry, is swallowed
  a duplicate id             take the first -> the edit lands on whichever
                             one PyYAML happened to reach first
  not a top-level sequence   splice anyway -> a packages install has an
                             entry spliced into a mapping
  the snapshot comes first   snapshot after the write -> undo restores the
                             change it was undoing
  the protected refusal      drop it on replace -> the one option that has
                             to hold everywhere holds on append and not on
                             edit
  one writer                 let another module open automations.yaml ->
                             a second writer with none of the snapshotting
"""
from __future__ import annotations

import importlib
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

# Somebody's file: a header comment, single-quoted ids, a two-space list
# under `action`, a trailing comment, and a blank line between entries.
# Every one of those is a thing a re-serialise would take away.
EXISTING = '''\
# My automations. Do not reformat.
- id: '1699999999999'
  alias: Porch light at dusk
  description: ""
  trigger:
    - platform: sun
      event: sunset
  condition: []
  action:
    - service: light.turn_on
      target:
        entity_id: light.porch
  mode: single

- id: 'evening_lights'
  alias: Evening lights
  trigger:
    - platform: time
      at: "21:00:00"
  action:
    - service: light.turn_on
      target:
        entity_id: light.lounge
  mode: single
# The end of my automations.
'''

NEW = {
    "id": "evening_lights",
    "alias": "Evening lights",
    "trigger": [{"platform": "time", "at": "21:00:00"}],
    "condition": [{"condition": "time", "after": "23:00:00",
                   "before": "21:00:00"}],
    "action": [{"service": "light.turn_on",
                "target": {"entity_id": "light.lounge"}}],
    "mode": "single",
}


class EditCase(unittest.TestCase):
    """Real files in a real temporary directory posing as /config."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.config = root / "config"
        self.config.mkdir()
        self.journal = root / "edits"
        self._env = dict(os.environ)
        os.environ["BRAIN_EDIT_JOURNAL"] = str(self.journal)
        os.environ["BRAIN_CONFIG_DIR"] = str(self.config)
        os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)
        self.addCleanup(self._restore_env)
        sys.modules.pop("automation_writer", None)
        self.w = importlib.import_module("automation_writer")
        self.path = self.config / "automations.yaml"
        self.path.write_text(EXISTING, encoding="utf-8")

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env)
        sys.modules.pop("automation_writer", None)

    def text(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def rows(self):
        import yaml
        return yaml.safe_load(self.text())


class TestLocate(EditCase):

    def test_the_span_starts_at_the_dash_and_ends_on_a_line_boundary(self):
        start, end = self.w.locate(EXISTING, "evening_lights")
        chunk = EXISTING[start:end]
        self.assertTrue(chunk.startswith("- id: 'evening_lights'"), chunk[:40])
        self.assertTrue(chunk.endswith("mode: single\n"), chunk[-40:])
        self.assertEqual(EXISTING[:start] + chunk + EXISTING[end:], EXISTING)

    def test_the_trailing_comment_after_the_last_entry_is_outside_the_span(self):
        """PyYAML ends a BLOCK mapping at whatever token ended it, which for
        the last entry in a file is the end of the file — comment included.
        Trusting that would delete somebody's footer on every edit."""
        _start, end = self.w.locate(EXISTING, "evening_lights")
        self.assertIn("# The end of my automations.", EXISTING[end:])

    def test_the_blank_line_between_entries_is_outside_the_span(self):
        _start, end = self.w.locate(EXISTING, "1699999999999")
        self.assertEqual(EXISTING[end], "\n")

    def test_a_flow_style_entry_is_delimited_at_its_brace(self):
        text = "- {id: a, x: 1}\n- id: b\n  y: 2\n"
        start, end = self.w.locate(text, "a")
        self.assertEqual(text[start:end], "- {id: a, x: 1}\n")

    def test_an_entry_whose_dash_is_on_its_own_line(self):
        text = "-\n  id: a\n  x: 1\n- id: b\n"
        start, end = self.w.locate(text, "a")
        self.assertEqual(text[start:end], "-\n  id: a\n  x: 1\n")

    def test_an_indented_sequence_keeps_its_indent(self):
        text = "  - id: a\n    x: 1\n  - id: b\n    y: 2\n"
        start, end = self.w.locate(text, "a")
        self.assertEqual(text[start:end], "  - id: a\n    x: 1\n")

    def test_an_id_that_appears_twice_is_refused(self):
        text = "- id: a\n  x: 1\n- id: a\n  y: 2\n"
        self.assertIsNone(self.w.locate(text, "a"))

    def test_a_document_that_is_not_a_sequence_is_refused(self):
        self.assertIsNone(self.w.locate("automation:\n  - id: a\n", "a"))

    def test_an_id_that_is_not_there_is_refused(self):
        self.assertIsNone(self.w.locate(EXISTING, "nope"))

    def test_an_unparseable_document_is_refused_rather_than_raising(self):
        self.assertIsNone(self.w.locate("- id: 'a\n  x: [", "a"))

    def test_an_empty_id_is_refused(self):
        self.assertIsNone(self.w.locate(EXISTING, ""))


class TestReplace(EditCase):

    def test_every_byte_outside_the_span_is_identical(self):
        """The whole claim. Not "it still parses" — the header comment, the
        first entry's quoting, the blank line and the footer are all still
        exactly where they were, byte for byte."""
        start, end = self.w.locate(EXISTING, "evening_lights")
        out = self.w.replace_entry(self.path, "evening_lights", NEW)
        self.assertTrue(out["ok"], out.get("error"))
        after = self.text()
        self.assertEqual(after[:start], EXISTING[:start])
        self.assertEqual(after[len(after) - (len(EXISTING) - end):],
                         EXISTING[end:])

    def test_the_new_entry_is_what_is_there_now(self):
        self.assertTrue(
            self.w.replace_entry(self.path, "evening_lights", NEW)["ok"])
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["id"], "evening_lights")
        self.assertEqual(rows[1]["condition"], NEW["condition"])
        # And the entry that was not named is untouched, comments and all.
        self.assertEqual(rows[0]["alias"], "Porch light at dusk")

    def test_it_says_what_the_entity_will_be_called(self):
        out = self.w.replace_entry(self.path, "evening_lights", NEW)
        self.assertEqual(out["entity_id"], "automation.evening_lights")
        self.assertEqual(out["automation_id"], "evening_lights")

    def test_an_indented_entry_is_re_emitted_at_its_own_indent(self):
        text = "  - id: a\n    x: 1\n  - id: b\n    y: 2\n"
        self.path.write_text(text, encoding="utf-8")
        out = self.w.replace_entry(
            self.path, "a", {"id": "a", "trigger": [], "action": [],
                             "x": 2})
        self.assertTrue(out["ok"], out.get("error"))
        after = self.text()
        self.assertTrue(after.startswith("  - "), repr(after[:20]))
        self.assertTrue(after.endswith("  - id: b\n    y: 2\n"), repr(after))

    def test_a_protected_entity_in_the_NEW_config_is_refused(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "light.lounge"
        out = self.w.replace_entry(self.path, "evening_lights", NEW)
        self.assertFalse(out["ok"])
        self.assertIn("protected", out["error"])
        self.assertEqual(self.text(), EXISTING, "the file was written anyway")

    def test_an_area_target_in_the_NEW_config_is_refused(self):
        os.environ["BRAIN_PROTECTED_ENTITIES"] = "lock.front"
        config = dict(NEW)
        config["action"] = [{"service": "light.turn_on",
                             "target": {"area_id": "lounge"}}]
        out = self.w.replace_entry(self.path, "evening_lights", config)
        self.assertFalse(out["ok"])
        self.assertIn("area", out["error"])

    def test_an_id_that_is_not_there_leaves_the_file_alone(self):
        out = self.w.replace_entry(self.path, "nope", NEW)
        self.assertFalse(out["ok"])
        self.assertIn("nope", out["error"])
        self.assertEqual(self.text(), EXISTING)

    def test_a_file_that_is_not_a_sequence_is_refused(self):
        self.path.write_text("automation:\n  - id: a\n", encoding="utf-8")
        out = self.w.replace_entry(self.path, "a", NEW)
        self.assertFalse(out["ok"])
        self.assertIn("not a list", out["error"])

    def test_a_duplicate_id_is_refused_rather_than_guessed_at(self):
        self.path.write_text("- id: a\n  x: 1\n- id: a\n  y: 2\n",
                             encoding="utf-8")
        out = self.w.replace_entry(self.path, "a", {"id": "a", "z": 1})
        self.assertFalse(out["ok"])
        self.assertEqual(self.text(), "- id: a\n  x: 1\n- id: a\n  y: 2\n")

    def test_a_missing_file_is_refused_rather_than_created(self):
        self.path.unlink()
        out = self.w.replace_entry(self.path, "evening_lights", NEW)
        self.assertFalse(out["ok"])

    def test_the_snapshot_holds_the_file_as_it_was_before_the_write(self):
        out = self.w.replace_entry(self.path, "evening_lights", NEW)
        saved = (self.journal / "snapshots" / out["snapshot"]).read_text()
        self.assertEqual(saved, EXISTING)
        self.assertNotEqual(saved, self.text())

    def test_revert_puts_the_file_back_byte_for_byte(self):
        out = self.w.replace_entry(self.path, "evening_lights", NEW)
        back = self.w.revert(out, config_dir=str(self.config))
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(self.text(), EXISTING)

    def test_the_journal_line_is_one_brain_undo_can_read(self):
        self.w.replace_entry(self.path, "evening_lights", NEW)
        lines = [json.loads(x) for x in
                 (self.journal / "index.jsonl").read_text().splitlines()
                 if x.strip()]
        self.assertEqual(len(lines), 1)
        entry = lines[0]
        self.assertEqual(set(entry),
                         {"ts", "path", "tool", "snapshot", "existed"})
        self.assertEqual(entry["tool"], self.w.TOOL)
        self.assertTrue(entry["existed"])


class TestRemove(EditCase):

    def test_the_entry_is_gone_and_nothing_else_moved(self):
        start, end = self.w.locate(EXISTING, "evening_lights")
        out = self.w.remove_entry(self.path, "evening_lights")
        self.assertTrue(out["ok"], out.get("error"))
        self.assertEqual(self.text(), EXISTING[:start] + EXISTING[end:])
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "1699999999999")

    def test_removing_the_first_entry_leaves_the_header_comment(self):
        self.assertTrue(self.w.remove_entry(self.path, "1699999999999")["ok"])
        after = self.text()
        self.assertTrue(after.startswith("# My automations. Do not reformat."),
                        repr(after[:60]))
        self.assertIn("# The end of my automations.", after)

    def test_removing_the_only_entry_leaves_a_file_that_still_parses(self):
        self.path.write_text("- id: a\n  x: 1\n", encoding="utf-8")
        self.assertTrue(self.w.remove_entry(self.path, "a")["ok"])
        self.assertIsNone(self.rows())

    def test_an_id_that_is_not_there_leaves_the_file_alone(self):
        out = self.w.remove_entry(self.path, "nope")
        self.assertFalse(out["ok"])
        self.assertEqual(self.text(), EXISTING)

    def test_revert_puts_the_removed_entry_back(self):
        out = self.w.remove_entry(self.path, "evening_lights")
        self.assertTrue(self.w.revert(out, config_dir=str(self.config))["ok"])
        self.assertEqual(self.text(), EXISTING)


class TestOnlyOneModuleEditsThatFile(unittest.TestCase):
    """A second writer to somebody's automations would have none of the
    snapshotting the first one has, and nothing would notice until an undo
    could not put a file back."""

    def test_nothing_but_the_writer_opens_automations_yaml_for_writing(self):
        panel = BASE_DIR / "brain" / "panel"
        writers = re.compile(
            r"write_text\(|write_json\(|open\([^)]*[\"']w[\"']|\.unlink\(")
        offenders = []
        for path in sorted(panel.rglob("*.py")):
            if path.name in ("automation_writer.py", "atomic_write.py"):
                continue
            source = path.read_text(encoding="utf-8")
            if "automations.yaml" not in source and "AUTOMATIONS_FILE" \
                    not in source:
                continue
            for line in source.splitlines():
                if writers.search(line) and (
                        "automations.yaml" in line or "AUTOMATIONS_FILE"
                        in line):
                    offenders.append(f"{path.name}: {line.strip()}")
        self.assertEqual(offenders, [], "a second writer to automations.yaml")


if __name__ == "__main__":                    # pragma: no cover
    unittest.main()
