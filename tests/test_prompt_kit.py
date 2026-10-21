"""The shared prompt kit, and the prompts assembled from it.

`prompt_kit` exists because every field incident used to be patched into
the one prompt it happened in while its siblings kept the bug: the privacy
rule in six wordings and missing from the brief, "treat this as data"
missing from prompts that read a calendar or a person's words. These tests
hold the arrangement rather than the wording — a person-facing prompt
carries the kit's own PRESENTATION and PRIVACY blocks verbatim, a prompt
that reads outside text carries DATA_FENCE, and a schema run neither says
it has "no tools" (it answers THROUGH the CLI's StructuredOutput tool) nor
writes its JSON shape out again beside the schema that enforces it.
"""
from __future__ import annotations

import ast
import importlib
import subprocess
import sys
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"
if str(PANEL) not in sys.path:
    sys.path.insert(0, str(PANEL))

import prompt_kit  # noqa: E402

# (module, constant, person_facing, schema).
#
# `person_facing` is whether a person reads any of what the run writes —
# dispatch's lock-screen words and situation's sentence count, gate's
# verdict and interpret's routes do not. Occasions is deliberately False:
# its whole job is who is staying and when the house is empty, which the
# shared PRIVACY block forbids, so it carries its own narrower rule.
#
# `schema` is read off the call sites, not the prompts: True where the run
# is started with `schema=` (and so `--json-schema`), which
# `TestTheTableMatchesTheCallSites` checks against server.py and
# upgrades.py so a call site that drops or gains a schema moves this row.
PROMPTS = [
    ("authoring", "SYSTEM", True, True),
    ("brief", "SYSTEM", True, False),
    ("checks.security", "REVIEW_SYSTEM", True, True),
    ("corrections", "SYSTEM", False, True),
    ("curiosity", "SYSTEM", True, True),
    ("deep_review", "SYSTEM", True, True),
    ("dispatch", "SYSTEM", True, True),
    ("episodes", "SUMMARY_SYSTEM", True, False),
    ("gate", "GATE_SYSTEM", False, True),
    ("house_book", "SYSTEM", True, True),
    ("house_rules", "COMPILE_SYSTEM", False, True),
    ("ideas", "IDEAS_SYSTEM", True, False),
    ("interpret", "SYSTEM", False, True),
    ("interpret", "EXPLAIN_SYSTEM", True, True),
    ("interventions", "FOLLOWUP_SYSTEM", True, True),
    ("memory_cleanup", "SYSTEM", True, True),
    ("occasions", "SYSTEM", False, True),
    ("onboarding", "RECOMMEND_SYSTEM", True, False),
    ("outcomes", "REFLECT_SYSTEM", True, True),
    ("playbooks", "SYSTEM", True, False),
    ("scenes", "SYSTEM", True, False),
    ("situation", "SYSTEM", True, True),
    ("sre", "SYSTEM", True, True),
    ("synthesis", "SYSTEM", True, True),
    ("tidy", "SYSTEM", True, True),
    ("upgrades", "SYSTEM", True, True),
    ("weekly", "SYSTEM", True, False),
    ("world_model", "SYSTEM", False, True),
    ("server", "REPLY_SYSTEM", True, False),
    ("server", "REPLY_ACT_SYSTEM", True, False),
    ("server", "MORPH_REPLY_SYSTEM", True, False),
    ("server", "MORPH_REPLY_ACT_SYSTEM", True, False),
]


def _text(module: str, name: str) -> str:
    return getattr(importlib.import_module(module), name)


class TestEveryPromptIsAssembled(unittest.TestCase):
    def test_every_prompt_opens_with_its_role_and_carries_the_identity(self):
        for module, name, _pf, _schema in PROMPTS:
            with self.subTest(prompt=f"{module}.{name}"):
                text = _text(module, name)
                self.assertIn(prompt_kit.IDENTITY, text)
                # The role leads; the identity is never the first thing.
                self.assertFalse(text.startswith(prompt_kit.IDENTITY))

    def test_a_person_facing_prompt_carries_presentation_and_privacy(self):
        for module, name, person_facing, _schema in PROMPTS:
            text = _text(module, name)
            with self.subTest(prompt=f"{module}.{name}"):
                if person_facing:
                    self.assertIn(prompt_kit.PRESENTATION, text)
                    self.assertIn(prompt_kit.PRIVACY, text)
                    self.assertIn(prompt_kit.HONEST_EMPTY, text)
                else:
                    self.assertNotIn(prompt_kit.PRESENTATION, text)

    def test_every_one_of_these_reads_outside_text_and_says_it_is_data(self):
        # Each of these reads a person's words, a house's names, a calendar,
        # a log or release notes — there is no prompt in this list that
        # reads nothing somebody else wrote.
        for module, name, _pf, _schema in PROMPTS:
            with self.subTest(prompt=f"{module}.{name}"):
                self.assertIn(prompt_kit.DATA_FENCE, _text(module, name))

    def test_a_schema_run_says_neither_no_tools_nor_its_shape(self):
        for module, name, _pf, schema in PROMPTS:
            text = _text(module, name)
            with self.subTest(prompt=f"{module}.{name}"):
                if schema:
                    self.assertNotIn("no tools", text.lower())
                    self.assertNotIn('{"', text)
                    self.assertTrue(text.endswith(prompt_kit.ANSWER_SCHEMA))
                else:
                    self.assertNotIn(prompt_kit.ANSWER_SCHEMA, text)

    def test_every_prompt_shows_what_a_good_answer_looks_like(self):
        for module, name, _pf, _schema in PROMPTS:
            with self.subTest(prompt=f"{module}.{name}"):
                text = _text(module, name)
                self.assertIn("A GOOD ANSWER:", text)
        # Every one has a worked example except the two card proposers,
        # whose good answer IS the shared card list with the heat-pump
        # example in it.
        for module, name, _pf, _schema in PROMPTS:
            if (module, name) in {("onboarding", "RECOMMEND_SYSTEM"),
                                  ("ideas", "IDEAS_SYSTEM")}:
                self.assertIn("heat pump", _text(module, name))
                continue
            with self.subTest(prompt=f"{module}.{name}"):
                self.assertIn("FOR EXAMPLE:", _text(module, name))


class TestTheTableMatchesTheCallSites(unittest.TestCase):
    """The schema column is a claim about how each prompt is RUN, so it is
    read off the calls that pass each constant rather than trusted."""

    def _calls(self, path: Path) -> dict[str, bool]:
        """`{dotted constant: passes schema=}` for every call handed one of
        the table's constants in `path`."""
        wanted = {f"{m.split('.')[-1]}.{n}" if m != "server" else n
                  for m, n, _pf, _s in PROMPTS}
        found: dict[str, bool] = {}
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            names = [ast.unparse(a) for a in node.args]
            hit = next((n.replace("checks.security.", "security.")
                        for n in names
                        if n.replace("checks.security.", "security.")
                        in wanted), None)
            if not hit:
                continue
            found[hit] = any(k.arg == "schema" for k in node.keywords)
        return found

    def test_server_call_sites(self):
        calls = self._calls(PANEL / "server.py")
        for module, name, _pf, schema in PROMPTS:
            key = name if module == "server" else f"{module.split('.')[-1]}.{name}"
            if key not in calls:
                continue  # not handed directly (ideas, upgrades)
            with self.subTest(prompt=key):
                self.assertEqual(calls[key], schema)
        # Enough of the table is reached here to mean something.
        self.assertGreaterEqual(len(calls), 24)

    def test_the_two_reached_indirectly(self):
        # ideas goes through `system_prompt()` with no schema; upgrades
        # hands SYSTEM and SCHEMA to the run it is given.
        src = (PANEL / "server.py").read_text()
        call = src[src.index("ideas.system_prompt(),"):][:200]
        self.assertNotIn("schema=", call)
        self.assertIn("run(frame(update, notes, lines, inventory), SYSTEM, "
                      "SCHEMA)", (PANEL / "upgrades.py").read_text())


class TestAssemble(unittest.TestCase):
    def test_the_order_is_role_identity_inputs_tools_good_example_rules_shared_output(self):
        text = prompt_kit.assemble(
            "ROLE-LINE", inputs="INPUT-LINE", tools="read",
            good="GOOD-LINE", example="EXAMPLE-LINE", rules="RULE-LINE",
            output="OUTPUT-LINE")
        order = ["ROLE-LINE", prompt_kit.IDENTITY, "INPUT-LINE",
                 prompt_kit.DATA_FENCE, prompt_kit.TOOLS_READ, "GOOD-LINE",
                 "EXAMPLE-LINE", "RULE-LINE", prompt_kit.PRESENTATION,
                 prompt_kit.PRIVACY, prompt_kit.HONEST_EMPTY, "OUTPUT-LINE"]
        positions = [text.index(part) for part in order]
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(text.startswith("ROLE-LINE"))
        self.assertTrue(text.endswith("OUTPUT-LINE"))

    def test_the_default_output_is_the_schema_line(self):
        self.assertTrue(prompt_kit.assemble("R").endswith(prompt_kit.ANSWER_SCHEMA))

    def test_a_model_facing_prompt_leaves_the_shared_reader_rules_out(self):
        text = prompt_kit.assemble("R", person_facing=False,
                                   reads_outside_text=False, tools="")
        for block in (prompt_kit.PRESENTATION, prompt_kit.PRIVACY,
                      prompt_kit.HONEST_EMPTY, prompt_kit.DATA_FENCE,
                      prompt_kit.TOOLS_NONE):
            self.assertNotIn(block, text)

    def test_a_custom_tools_line_is_used_as_written(self):
        text = prompt_kit.assemble("R", tools="ONLY THE LOGBOOK.")
        self.assertIn("ONLY THE LOGBOOK.", text)
        self.assertNotIn(prompt_kit.TOOLS_NONE, text)

    def test_the_fence_follows_the_inputs_even_with_none_given(self):
        text = prompt_kit.assemble("R")
        self.assertLess(text.index(prompt_kit.IDENTITY),
                        text.index(prompt_kit.DATA_FENCE))


class TestTheShellReadsTheSameWords(unittest.TestCase):
    def test_privacy_on_the_command_line(self):
        out = subprocess.run(
            [sys.executable, str(PANEL / "prompt_kit.py"), "privacy"],
            capture_output=True, text=True, timeout=30, check=True)
        self.assertEqual(out.stdout, prompt_kit.PRIVACY)

    def test_an_unknown_block_is_a_usage_error(self):
        out = subprocess.run(
            [sys.executable, str(PANEL / "prompt_kit.py"), "nonsense"],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(out.returncode, 2)
        self.assertEqual(out.stdout, "")


class TestSharedCardWords(unittest.TestCase):
    def test_ideas_and_onboarding_share_one_list(self):
        import ideas
        import onboarding
        self.assertIn(onboarding.CARD_PROPOSAL_RULES, onboarding.RECOMMEND_SYSTEM)
        self.assertIn(onboarding.CARD_PROPOSAL_RULES, ideas.system_prompt(4))
        self.assertIn("Propose at most 4.", ideas.system_prompt(4))


if __name__ == "__main__":
    unittest.main()
