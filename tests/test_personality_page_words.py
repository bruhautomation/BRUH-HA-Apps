"""The page says the household's name the way the server does.

Three drifts between `personality.py` and the pages that draw it:

* `speakText` in app.js was a plain split/join, where `personality.speak`
  replaces `\\bbrAIn\\b`: "brAIns" became "Wrens".
* `applyName` re-spoke the page by replacing the OLD name with the new one,
  so a member of the household who shares the old name had their own words
  rewritten ("Wren arrived home" became "Robin arrived home"). The page now
  remembers what it rewrote and re-says only that.
* `PERS_TITLES` lacked the tagline keys `TAGLINE_KEYS` has, so "one line:"
  was the tagline in the ⚙ row and titled "One line" on the page.

And Morph's panel had a name fallback (`who()` reading `morph/personality`)
that nothing could reach, which would have ignored the switch had it been.

The functions are lifted out of the shipped files and run under node over a
small stand-in for the DOM, so these test the code the page runs.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_JS = ROOT / "brain" / "panel" / "app.js"
MORPH_PANEL = (ROOT / "brain" / "custom_components" / "brain" / "morph" / "frontend"
               / "morph-panel.js")
sys.path.insert(0, str(ROOT / "brain" / "panel"))

import personality  # noqa: E402


def _block(src: str, start: int) -> str:
    """From `start` to the brace that closes the first one after it."""
    depth = 0
    for i in range(src.index("{", start), len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError("no closing brace")


def function(src: str, name: str) -> str:
    m = re.search(rf"^function {name}\(", src, re.M)
    assert m, f"app.js no longer defines {name}"
    return _block(src, m.start())


def const(src: str, name: str) -> str:
    m = re.search(rf"^const {name} = .*?;$", src, re.M | re.S)
    assert m, f"app.js no longer defines {name}"
    return m.group(0)


# A stand-in for the few DOM calls the walk makes.
FAKE_DOM = r"""
class Text { constructor(v) { this.nodeType = 3; this.nodeValue = v; } }
class El {
  constructor(tag, kids = [], attrs = {}) {
    this.nodeType = 1; this.tagName = tag; this.childNodes = kids; this.attrs = attrs;
    this.isContentEditable = false;
  }
  getAttribute(a) { return a in this.attrs ? this.attrs[a] : null; }
  setAttribute(a, v) { this.attrs[a] = String(v); }
  closest() { return null; }
}
"""


def run_node(body: str):
    r = subprocess.run(["node", "-e", textwrap.dedent(body)], capture_output=True,
                       text=True, timeout=30)
    if r.returncode != 0:
        raise AssertionError(r.stderr or r.stdout)
    return json.loads(r.stdout.strip().splitlines()[-1])


class TestThePageSaysTheName(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        src = APP_JS.read_text(encoding="utf-8")
        cls.lifted = "\n".join([
            'let pageName = "brAIn";',
            const(src, "SPEAK_SKIP"), const(src, "SPEAK_ATTRS"),
            const(src, "BRAIN_WORD"), const(src, "SPOKEN"),
            function(src, "speakText"), function(src, "speakNode"),
            function(src, "speakAttr"), function(src, "speakAll"),
        ])

    def drive(self, script: str):
        return run_node(FAKE_DOM + self.lifted + "\n" + script)

    def test_only_the_word_brain_is_the_name(self):
        got = self.drive("""
            pageName = "Wren";
            console.log(JSON.stringify(["brAIn checked it.", "brAIn's look", "brAIns",
              "xbrAIn", "brain undo", "Ask brAIn"].map((s) => speakText(s))));
        """)
        self.assertEqual(got, ["Wren checked it.", "Wren's look", "brAIns", "xbrAIn",
                               "brain undo", "Ask Wren"])
        # The server's rule, the same answers.
        for s, want in (("brAIns", "brAIns"), ("Ask brAIn", "Ask Wren")):
            self.assertEqual(personality._WORD.sub("Wren", s), want)

    def test_a_name_with_a_dollar_sign_is_said_as_typed(self):
        got = self.drive("""
            pageName = "Mr $&";
            console.log(JSON.stringify(speakText("Ask brAIn")));
        """)
        self.assertEqual(got, "Ask Mr $&")

    def test_a_new_name_is_said_over_brains_words_and_never_over_a_persons(self):
        got = self.drive("""
            const ours = new Text("brAIn checked the porch.");
            const theirs = new Text("Wren arrived home.");
            const btn = new El("BUTTON", [], { "aria-label": "Ask brAIn", title: "Wren's room" });
            const box = new El("TEXTAREA", [new Text("brAIn, please")]);
            const body = new El("DIV", [ours, theirs, btn, box]);
            const seen = [];
            const snap = () => seen.push([ours.nodeValue, theirs.nodeValue,
              btn.getAttribute("aria-label"), btn.getAttribute("title"), box.childNodes[0].nodeValue]);
            pageName = "Wren"; speakAll(body); snap();
            pageName = "Robin"; speakAll(body); snap();
            pageName = "brAIn"; speakAll(body); snap();
            console.log(JSON.stringify(seen));
        """)
        self.assertEqual(got, [
            ["Wren checked the porch.", "Wren arrived home.", "Ask Wren", "Wren's room", "brAIn, please"],
            ["Robin checked the porch.", "Wren arrived home.", "Ask Robin", "Wren's room", "brAIn, please"],
            ["brAIn checked the porch.", "Wren arrived home.", "Ask brAIn", "Wren's room", "brAIn, please"],
        ])

    def test_text_the_page_redrew_is_said_afresh(self):
        got = self.drive("""
            const t = new Text("brAIn is ready.");
            const body = new El("DIV", [t]);
            pageName = "Wren"; speakAll(body);
            t.nodeValue = "Wren and brAIn";   // the page drew new words here
            speakAll(body);
            console.log(JSON.stringify(t.nodeValue));
        """)
        self.assertEqual(got, "Wren and Wren")

    def test_a_name_holding_the_word_does_not_say_itself_again(self):
        got = self.drive("""
            const t = new Text("Ask brAIn");
            const body = new El("DIV", [t]);
            pageName = "brAIn Two"; speakAll(body); speakNode(t); speakAll(body);
            console.log(JSON.stringify(t.nodeValue));
        """)
        self.assertEqual(got, "Ask brAIn Two")

    def test_apply_name_respeaks_without_the_old_name(self):
        src = APP_JS.read_text(encoding="utf-8")
        body = function(src, "applyName")
        self.assertIn("speakAll(document.body)", body)
        self.assertNotIn("speakAll(document.body, was)", body)


class TestTheTitlesMatchTheTagline(unittest.TestCase):
    def test_every_tagline_key_is_titled_tagline(self):
        src = APP_JS.read_text(encoding="utf-8")
        lifted = const(src, "PERS_TITLES") + "\n" + function(src, "personaTitle")
        got = run_node(lifted + f"\nconsole.log(JSON.stringify("
                       f"{json.dumps(list(personality.TAGLINE_KEYS))}.map(personaTitle)));")
        self.assertEqual(got, ["Tagline"] * len(personality.TAGLINE_KEYS))


class TestMorphNamesTheAssistantOffTheSwitches(unittest.TestCase):
    def who(self) -> str:
        src = MORPH_PANEL.read_text(encoding="utf-8")
        m = re.search(r"^  who\(\) \{", src, re.M)
        self.assertTrue(m, "morph-panel.js no longer defines who()")
        return _block(src, m.start()).strip()

    def test_the_name_is_the_switches_name_and_nothing_else(self):
        body = self.who()
        self.assertNotIn("persona", body)
        got = run_node("const o = { " + body + " };\n" + textwrap.dedent("""
            const call = (data) => o.who.call({ data, s: { persona: { personality: { name: "Old" } } } });
            console.log(JSON.stringify([
              call({ features: { name: "Wren" } }),
              call({ features: { name: "brAIn" } }),
              call(null),
              call({ error: "down" }),
            ]));
        """))
        self.assertEqual(got, ["Wren", "brAIn", "brAIn", "brAIn"])


if __name__ == "__main__":
    unittest.main()
