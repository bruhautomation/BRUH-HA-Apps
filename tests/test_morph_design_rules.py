#!/usr/bin/env python3
"""Morph's shipped frontend, held to the house design's checkable rules.

The design rules (``brain/morph/defaults/AGENTS.md``, "The design rules";
the numbers from ``docs/design/morph-ui.md`` §5 and
``docs/design/morph-vision.md``'s colour paragraph) are what brAIn holds
every change to Morph against, and the shipped code had drifted from one of
them unnoticed: four controls carried a hover ``title=`` (a light's name,
a white swatch, a meter's day bar, a camera's name), which rule 13 forbids
because a tooltip floats. This file reads the shipped modules on every
change, so the drift a grep can see is caught where it is made.

Covered here (mechanical):

  * rule 1, nothing floats: no ``position: fixed``, no ``<dialog>`` or
    ``showModal``, no ``popover`` attribute, no ``alert``/``confirm``/
    ``prompt``;
  * rule 3, no chrome, for the part a grep can prove: inside brAIn's shell
    Morph's bar carries no brand, no sidebar button, no settings gear and
    no Feed — brAIn's header owns them;
  * rule 13, no tooltips: no ``title=`` attribute and no ``.title =`` or
    ``setAttribute('title'`` on an element (an ``<iframe title>`` is the
    frame's accessible name, not hover text, and is the one exception);
  * the design's fixed numbers: the springs (K = 150, ζ = 0.82), the
    make-room-first delays (130 ms a section, 170 ms a tile), and the three
    themes' page and card colours, in ``styles.js`` and in ``boot.js``'s
    outline alike.

Judgement, and so not here (``measure-morph`` and review hold them): rule 2
(one grammar), the rest of rule 3 (what counts as a chevron or an
instruction row), 4 (one control, one place), 5 and 6 (scenes above
lights, Comfort), 7 to 10 (rows of one height, open in place, make room,
tap outside — measured in a browser by ``tests/manual/measure-morph.mjs``,
which also fails on any element carrying a ``title``), 11 (history in the
device's colour), 12 (one Now, one list of cases) and the empty-state half
of 13.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND = BASE_DIR / "brain/custom_components/brain/morph/frontend"


def sources() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(FRONTEND.glob("*.js"))}


def code_lines(text: str):
    """(line number, line) for every line that is not a // comment."""
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("//"):
            continue
        yield n, line


class TestRule13NoTooltips(unittest.TestCase):
    ATTR = re.compile(r"""<(?P<tag>[a-zA-Z][\w-]*)\b[^<>]*?\stitle=["'$]""")
    PROP = re.compile(r"""\.title\s*=(?!=)|setAttribute\(\s*['"]title['"]""")

    def test_no_element_carries_hover_text(self):
        found = []
        for name, text in sources().items():
            for n, line in code_lines(text):
                for m in self.ATTR.finditer(line):
                    if m.group("tag").lower() != "iframe":
                        found.append(f"{name}:{n}: <{m.group('tag')} title=…>")
                for m in self.PROP.finditer(line):
                    # `x.title = …` on data (a card's or a section's name)
                    # is not an element's; an element is `el`/`node`/`btn`.
                    before = line[:m.start()].rstrip()
                    if m.group(0).startswith("setAttribute") or re.search(
                            r"\b(el|node|btn|button|elem|element|tile)$", before):
                        found.append(f"{name}:{n}: {line.strip()[:80]}")
        self.assertEqual(found, [], "rule 13: no control carries a title= hover text")


class TestRule1NothingFloats(unittest.TestCase):
    FORBIDDEN = [
        (re.compile(r"position\s*:\s*fixed"), "position: fixed"),
        (re.compile(r"<dialog\b"), "<dialog>"),
        (re.compile(r"\.showModal\s*\("), "showModal()"),
        (re.compile(r"""\spopover(=|\s|>)"""), "a popover attribute"),
        (re.compile(r"(?<![\w.])(?:window\.)?(alert|confirm|prompt)\s*\("), "a browser dialog"),
    ]

    def test_no_overlay_construct(self):
        found = []
        for name, text in sources().items():
            for n, line in code_lines(text):
                # An invisible measuring probe off the page (snap.js's
                # default styles) is fixed so it never moves the layout;
                # it is never seen, so it floats over nothing.
                probe = "visibility:hidden" in line.replace(" ", "")
                for rx, what in self.FORBIDDEN:
                    if rx.search(line) and not (probe and what == "position: fixed"):
                        found.append(f"{name}:{n}: {what}")
        self.assertEqual(found, [], "rule 1: nothing floats over anything")


class TestRule3TheShellOwnsTheChrome(unittest.TestCase):
    def bar(self) -> str:
        text = (FRONTEND / "morph-panel.js").read_text(encoding="utf-8")
        start = text.index("  barHtml() {")
        end = text.index("\n  }\n", start)
        return "\n".join(line for _n, line in code_lines(text[start:end]))

    def test_brand_and_sidebar_button_are_left_out_in_the_shell(self):
        bar = self.bar()
        self.assertRegex(bar, r"const menu = [^;]*!this\._shell")
        self.assertRegex(bar, r"const brand = this\._shell \? ''")

    def test_the_bar_has_no_settings_gear_and_no_feed(self):
        bar = self.bar()
        for word in ("⚙", 'data-act="settings"', 'data-act="feed"', ">Feed<", "gear"):
            self.assertNotIn(word, bar, word)


class TestTheDesignsNumbers(unittest.TestCase):
    def test_the_springs(self):
        engine = (FRONTEND / "engine.js").read_text(encoding="utf-8")
        self.assertRegex(engine, r"\bconst K = 150;")
        self.assertRegex(engine, r"\bconst C = 2 \* 0\.82 \* Math\.sqrt\(K\);")

    def test_make_room_first(self):
        engine = (FRONTEND / "engine.js").read_text(encoding="utf-8")
        self.assertGreaterEqual(len(re.findall(r"\bsd = 130\b", engine)), 1)
        self.assertGreaterEqual(len(re.findall(r"\btd = 170\b", engine)), 1)

    THEMES = {"dark": ("#0A0C0E", "#15181B"), "medium": ("#2A2D31", "#34383D"),
              "light": ("#ECEBE6", "#FFFFFF")}

    def test_the_three_themes_backgrounds(self):
        styles = (FRONTEND / "styles.js").read_text(encoding="utf-8")
        for theme, (bg, surface) in self.THEMES.items():
            rule = re.search(r"\.t-" + theme + r"\{([^}]*)\}", styles)
            self.assertIsNotNone(rule, theme)
            self.assertIn(f"--bg:{bg};", rule.group(1), theme)
            self.assertIn(f"--surface:{surface};", rule.group(1), theme)

    def test_the_outline_paints_the_same_colours(self):
        boot = (FRONTEND / "boot.js").read_text(encoding="utf-8")
        for theme, (bg, surface) in self.THEMES.items():
            self.assertIn(f"{theme}: ['{bg}', '{surface}']", boot, theme)


if __name__ == "__main__":
    unittest.main()
