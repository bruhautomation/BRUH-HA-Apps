"""The splice, driven over generated files rather than described ones.

`tests/test_entry_edit.py` names the shapes somebody thought of.  This
one generates them: random well-formed `automations.yaml` files out of a
grammar of the things a person's file really holds — comments between
entries and inside them, blank lines, flow mappings, block scalars,
quoted and unquoted ids, an int id, CRLF, a leading `---`, a trailing
`...`, no trailing newline, an indented top-level sequence — and then
splices and removes every entry in each of them.

Two invariants, and they are the only two that matter:

* **Every byte outside the returned span is identical.** That is the
  whole promise of a byte splice, and it is what `remove_entry` gets
  asserted on: the file with the entry cut out has to equal the original
  with exactly those bytes removed.
* **What is left parses to the original list minus that entry.**  A
  splice can be byte-exact outside its span and still leave a hole, if
  the span itself was cut in the wrong place.

And the third outcome is always allowed: `locate` may answer `None`.  A
refusal is the design — nearly-right bytes are somebody's file with a
hole in it — so a shape this cannot delimit on a line boundary is a pass,
not a failure.  What is never allowed is a span that is returned and
wrong.
"""
from __future__ import annotations

import importlib
import os
import random
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import automation_writer as writer  # noqa: E402

import yaml  # noqa: E402

SEEDS = range(400)


def _entry_text(rng: random.Random, index: int, entry_id: str) -> str:
    """One sequence item, in one of the shapes a real file holds."""
    shape = rng.choice(("plain", "plain", "plain", "flow", "literal",
                        "folded", "dash_newline", "commented", "nested"))
    quoted = rng.choice((entry_id, f"'{entry_id}'", f'"{entry_id}"'))
    if shape == "flow":
        return f"- {{id: {quoted}, alias: A{index}, mode: single}}\n"
    if shape == "literal":
        return (f"- id: {quoted}\n  alias: A{index}\n"
                "  description: |\n    first line\n    second line\n")
    if shape == "folded":
        return (f"- id: {quoted}\n  alias: A{index}\n"
                "  description: >\n    folded text here\n")
    if shape == "dash_newline":
        return f"-\n  id: {quoted}\n  alias: A{index}\n"
    if shape == "commented":
        return (f"- id: {quoted}\n  # what this one is for\n"
                f"  alias: A{index}\n")
    if shape == "nested":
        return (f"- id: {quoted}\n  alias: A{index}\n"
                "  action:\n    - service: light.turn_on\n"
                "      target:\n        entity_id: light.a\n")
    return f"- id: {quoted}\n  alias: A{index}\n  mode: single\n"


def _document(rng: random.Random) -> tuple[str, list[str]]:
    """A whole file, and the ids in it."""
    count = rng.randint(1, 5)
    ids = []
    parts = []
    if rng.random() < 0.2:
        parts.append("---\n")
    if rng.random() < 0.3:
        parts.append("# somebody's own header\n")
    for i in range(count):
        entry_id = rng.choice((f"brain_{i}", f"{1700000000 + i}",
                               f"my-rule-{i}", f"a_{i}"))
        ids.append(entry_id)
        if rng.random() < 0.3:
            parts.append(f"# about {entry_id}\n")
        parts.append(_entry_text(rng, i, entry_id))
        if rng.random() < 0.3:
            parts.append("\n")
    if rng.random() < 0.2:
        parts.append("# a trailing note\n")
    if rng.random() < 0.15:
        parts.append("...\n")
    text = "".join(parts)
    if rng.random() < 0.15:
        text = text.replace("\n", "\r\n")
    if rng.random() < 0.15 and text.endswith("\n"):
        text = text.rstrip("\n").rstrip("\r")
    return text, ids


def _indent(rng: random.Random, text: str) -> str:
    """Sometimes the whole sequence sits indented, which is legal YAML."""
    if rng.random() >= 0.15:
        return text
    out = []
    for line in text.splitlines(keepends=True):
        out.append(line if not line.strip() or line.lstrip().startswith("---")
                   or line.lstrip().startswith("...") else "  " + line)
    return "".join(out)


class SpliceCase(unittest.TestCase):
    """Every case drives the real `remove_entry`/`replace_entry` against a
    real file, because the invariant is about what is on disk afterwards
    and `locate` is only half of getting there."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.file = root / "automations.yaml"
        self._env = dict(os.environ)
        os.environ["BRAIN_EDIT_JOURNAL"] = str(root / "edits")
        self.addCleanup(self._restore)
        sys.modules.pop("automation_writer", None)
        self.w = importlib.import_module("automation_writer")

    def _restore(self):
        os.environ.clear()
        os.environ.update(self._env)
        sys.modules.pop("automation_writer", None)

    def write(self, text: str) -> None:
        with open(self.file, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)

    def read(self) -> str:
        # `newline=""`: a CRLF file that came back as LF would pass every
        # byte comparison below while having rewritten the whole file.
        with open(self.file, encoding="utf-8", newline="") as handle:
            return handle.read()

    def documents(self):
        for seed in SEEDS:
            rng = random.Random(seed)
            text, ids = _document(rng)
            text = _indent(rng, text)
            try:
                rows = yaml.safe_load(text)
            except yaml.YAMLError:               # pragma: no cover
                continue                          # not a document at all
            if not isinstance(rows, list):
                continue
            yield seed, text, ids, rows


class TestTheSpliceOverGeneratedFiles(SpliceCase):

    def test_removing_an_entry_leaves_every_other_byte_where_it_was(self):
        checked = refused = 0
        for seed, text, ids, rows in self.documents():
            for entry_id in ids:
                self.write(text)
                out = self.w.remove_entry(self.file, entry_id)
                with self.subTest(seed=seed, id=entry_id):
                    if not out.get("ok"):
                        # A refusal is an answer, and the design: nearly
                        # right bytes are somebody's file with a hole in
                        # it. What it may never do is leave the file
                        # changed on its way to saying no.
                        self.assertEqual(self.read(), text)
                        refused += 1
                        continue
                    start, end = out["span"]
                    left = self.read()
                    self.assertEqual(left, text[:start] + text[end:],
                                     "bytes outside the span moved")
                    self.assertTrue(start == 0 or text[start - 1] == "\n",
                                    "span starts mid-line")
                    self.assertTrue(end == len(text) or text[end - 1] == "\n",
                                    "span ends mid-line")
                    want = [r for r in rows
                            if str(r.get("id")) != str(entry_id)]
                    self.assertEqual(yaml.safe_load(left) or [], want)
                    checked += 1
        self.assertGreater(checked, 300, "the generator stopped generating")
        self.assertGreater(refused, 0, "nothing exercised the refusal")

    def test_replacing_an_entry_touches_nothing_outside_its_span(self):
        checked = 0
        for seed, text, ids, rows in self.documents():
            for entry_id in ids:
                self.write(text)
                out = self.w.replace_entry(
                    self.file, entry_id,
                    {"id": entry_id, "alias": "replaced"})
                with self.subTest(seed=seed, id=entry_id):
                    if not out.get("ok"):
                        self.assertEqual(self.read(), text)
                        continue
                    start, end = out["span"]
                    spliced = self.read()
                    self.assertEqual(spliced[:start], text[:start])
                    tail = len(text) - end
                    self.assertEqual(spliced[len(spliced) - tail:]
                                     if tail else "", text[end:])
                    after = yaml.safe_load(spliced)
                    self.assertIsInstance(after, list)
                    self.assertEqual(len(after), len(rows))
                    swapped = [r for r in after
                               if str(r.get("id")) == str(entry_id)]
                    self.assertEqual(len(swapped), 1)
                    self.assertEqual(swapped[0]["alias"], "replaced")
                    checked += 1
        self.assertGreater(checked, 300)

    def test_an_id_that_is_not_there_is_never_located(self):
        for _seed, text, ids, _rows in self.documents():
            self.assertIsNone(writer.locate(text, "no_such_id"))
            self.assertIsNone(writer.locate(text, ""))
            for entry_id in ids:
                # A prefix or a suffix of a real id is a different id.
                self.assertIsNone(writer.locate(text, entry_id + "x"))


class TestTheShapesThatMustNotBeGuessedAt(unittest.TestCase):
    """The refusals, stated rather than sampled."""

    def test_two_entries_under_one_id(self):
        self.assertIsNone(writer.locate(
            "- id: a\n  alias: A\n- id: a\n  alias: B\n", "a"))

    def test_a_document_that_is_not_a_sequence(self):
        self.assertIsNone(writer.locate("automation:\n  - id: a\n", "a"))

    def test_an_item_sharing_its_dash_line_with_something_else(self):
        # `foo: - id: a` is not legal, but `- - id: a` (a nested sequence)
        # is, and its inner item's dash is not at a line start.
        self.assertIsNone(writer.locate("- - id: a\n    alias: A\n", "a"))

    def test_an_alias_pointing_at_one_item_from_two_places(self):
        self.assertIsNone(writer.locate(
            "- &base\n  id: a\n  alias: A\n- *base\n", "a"))


class TestABlockScalarIsStillWholeLines(unittest.TestCase):
    """PyYAML ends a block scalar at the next token, which is a line start.

    That is *already* a line boundary, so the span is cuttable — and
    refusing it means an automation whose `description:` is a `|` block
    can never be edited or removed, which is the shape Home Assistant's
    own YAML editor writes for anything multi-line. What the walk-back is
    for is the blank line between entries: the scalar's end mark runs on
    through it, and swallowing somebody's spacing into the span is the
    thing this whole module refuses to do.
    """

    def cut(self, text: str, entry_id: str) -> str:
        span = writer.locate(text, entry_id)
        self.assertIsNotNone(span, f"{entry_id} in {text!r}")
        start, end = span
        return text[:start] + text[end:]

    def test_an_entry_with_a_literal_block_can_be_removed(self):
        text = ("- id: a\n  alias: A\n  description: |\n    one\n    two\n"
                "- id: b\n  alias: B\n")
        self.assertEqual(self.cut(text, "a"), "- id: b\n  alias: B\n")

    def test_a_comment_after_the_block_stays_outside_the_span(self):
        text = ("- id: a\n  description: |\n    one\n"
                "# about b\n- id: b\n  alias: B\n")
        self.assertEqual(self.cut(text, "a"), "# about b\n- id: b\n  alias: B\n")

    def test_a_blank_line_after_the_block_stays_outside_the_span(self):
        text = ("- id: a\n  description: |\n    one\n\n"
                "- id: b\n  alias: B\n")
        self.assertEqual(self.cut(text, "a"), "\n- id: b\n  alias: B\n")

    def test_a_block_scalar_in_the_last_entry(self):
        text = ("- id: a\n  alias: A\n- id: b\n  description: >\n    folded\n")
        self.assertEqual(self.cut(text, "b"), "- id: a\n  alias: A\n")

    def test_the_file_still_parses_to_the_list_minus_the_entry(self):
        text = ("- id: a\n  alias: A\n  description: |\n    one\n    two\n"
                "- id: b\n  alias: B\n")
        self.assertEqual(yaml.safe_load(self.cut(text, "a")),
                         [{"id": "b", "alias": "B"}])


if __name__ == "__main__":
    unittest.main()
