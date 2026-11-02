"""One assistant, one name.

Generated text called the same assistant "Vesper", "brAIn", "the companion",
"the in-game companion" and "the brAIn engine" in turn, so a reader could not
tell whether it was one assistant or several. The stored persona name is the
only name the assistant has (surfaces speak it where the prose says brAIn);
an add-on is named only when the add-on is meant.
"""
import ast
import re
import sys
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
PANEL = BASE / "brain" / "panel"
sys.path.insert(0, str(PANEL))

import findings_store  # noqa: E402
import house_words  # noqa: E402
import prompt_kit  # noqa: E402

# The assistant under a name that is not its own. "companion app" is the
# phone's, and stays.
BAD = re.compile(
    r"vesper"
    r"|\bthe (?:in-game |minecraft )?companion\b(?!['’]?s? app| app)"
    r"|\bin-game companion\b|\bminecraft companion\b"
    r"|\b(?:brain|vesper|assistant) engine\b", re.I)

# File, then the exact text allowed to match in it: the naming rule itself
# names the wrong names, to forbid them.
ALLOWED: dict[str, tuple[str, ...]] = {
    "brain/panel/prompt_kit.py": ("the companion", "the in-game companion"),
}


def _strings(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = set()
    for node in ast.walk(tree):
        if (isinstance(node, (ast.Module, ast.FunctionDef,
                              ast.AsyncFunctionDef, ast.ClassDef))
                and node.body and isinstance(node.body[0], ast.Expr)
                and isinstance(getattr(node.body[0], "value", None),
                               ast.Constant)):
            docs.add(id(node.body[0].value))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and id(node) not in docs):
            yield node.lineno, node.value


class TestNoOtherNameForTheAssistant(unittest.TestCase):

    def test_generated_text_sources_name_it_once(self):
        found = []
        for path in sorted(PANEL.rglob("*.py")):
            rel = str(path.relative_to(BASE))
            for line, text in _strings(path):
                for m in BAD.finditer(text):
                    if m.group(0) not in ALLOWED.get(rel, ()):
                        found.append(f"{rel}:{line}: {m.group(0)}")
        for rel in ("brain/scripts/ha-context-gen.sh", "brain/panel/app.js"):
            for n, text in enumerate(
                    (BASE / rel).read_text(encoding="utf-8").splitlines(), 1):
                m = BAD.search(text)
                if m and m.group(0) not in ALLOWED.get(rel, ()):
                    found.append(f"{rel}:{n}: {m.group(0)}")
        self.assertEqual(found, [])

    def test_the_prompts_say_it_once(self):
        self.assertIn("ONE assistant", prompt_kit.IDENTITY)
        self.assertIn("BRUH Minecraft", prompt_kit.IDENTITY)


class TestARenderedFinding(unittest.TestCase):

    def test_a_row_about_the_minecraft_companion_says_brain(self):
        row = findings_store._plain_row(
            {"claim": "The in-game companion has not answered since noon, "
                      "and the companion app on the phone is fine. "
                      "The brAIn engine in the game is idle."},
            ("claim",))
        text = row["claim"]
        self.assertIn("brAIn has not answered", text)
        self.assertIn("companion app", text)
        self.assertNotRegex(text, r"(?i)in-game companion|brAIn engine")

    def test_a_look_reason_says_brain(self):
        self.assertEqual(
            house_words.one_name("Nothing the companion did needs you."),
            "Nothing brAIn did needs you.")

    def test_the_persona_name_folds_to_the_one_name(self):
        out = house_words.self_said("Aria engine in the game is idle.", "Aria")
        self.assertEqual(out, "brAIn in the game is idle.")


if __name__ == "__main__":
    unittest.main()
