#!/usr/bin/env python3
"""Morph, the house reports of 2026-11-04 (#662 #664 #676 #677 #678 #679 #682 #683).

The browser half is `tests/manual/measure-morph.mjs` (the "reports" block);
this file pins what a grep can prove, so a change that undoes one of them
fails here first:

  * #662 Then mode is gone: no `then.js`, no `thenAt`, no `setThen`, the
    strip's past is zero;
  * #664 `topHtml` returns nothing when it has nothing, so its region hides;
  * #676 the story's "locked" and "at rest" wording is guarded by the open
    doors, windows and garage doors;
  * #677 the 16px floor on every field, handed to a card's own shadow root;
  * #678 a hosted card with nothing to draw says so, and the screenshot
    tool finds a header switch by its card id;
  * #679 a section label is mixed toward the text colour, not the quiet one;
  * #683 and #682 what brAIn is told when it builds a card.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FRONTEND = BASE / "brain/custom_components/brain/morph/frontend"
AGENTS = (BASE / "brain/morph/defaults/AGENTS.md").read_text(encoding="utf-8")


def src(name: str) -> str:
    return (FRONTEND / name).read_text(encoding="utf-8")


class TestThenModeIsGone(unittest.TestCase):
    def test_no_module_no_state_no_style(self):
        self.assertFalse((FRONTEND / "then.js").exists())
        for p in sorted(FRONTEND.glob("*.js")):
            text = p.read_text(encoding="utf-8")
            for word in ("thenAt", "setThen", "hassView", "prepareThen", "thenStates", "thenrule", "./then.js", "unknown_then"):
                self.assertNotIn(word, text, f"{p.name} still mentions {word}")
        self.assertNotIn("then.js", AGENTS)

    def test_the_strip_stops_at_now(self):
        self.assertRegex(src("upcoming.js"), r"export const PAST_MIN = 0;")


class TestTopSectionIsNothingWhenEmpty(unittest.TestCase):
    def test_top_html_returns_empty_string(self):
        text = src("morph-panel.js")
        self.assertRegex(text, r"if \(!inner\) return '';")


class TestStoryNeverClaimsAllShut(unittest.TestCase):
    def test_open_doors_guard_the_wording(self):
        text = src("morph-panel.js")
        self.assertIn("openClauses()", text)
        self.assertRegex(text, r"claimsAllShut && opens\.length")
        # The away line says "Everything is locked." only when nothing is open.
        self.assertRegex(text, r"openHtml \|\| '<span style=\"color:var\(--indigo\)\">Everything is locked\.")


class TestFieldFloor(unittest.TestCase):
    def test_every_field_is_16px_on_a_phone(self):
        css = src("styles.js")
        self.assertRegex(css, r"@media \(pointer:coarse\),\(max-width:700px\)\{\.morph input:[^}]*font-size:16px")
        self.assertIn("export const FIELD_FLOOR", css)

    def test_a_cards_own_shadow_root_gets_it(self):
        text = src("morph-panel.js")
        self.assertIn("FIELD_FLOOR", text)
        self.assertIn("adoptedStyleSheets", text)


class TestCardWithNothingToShow(unittest.TestCase):
    def test_says_so(self):
        text = src("morph-panel.js")
        self.assertIn("Nothing to show right now", text)
        self.assertIn("markEmptyCard", text)

    def test_the_screenshot_tool_finds_a_header_switch(self):
        self.assertIn('[data-card=', (BASE / "brain/panel/devloop/screens.py").read_text(encoding="utf-8"))
        self.assertIn('[data-card=', (BASE / "brain/panel/devloop/harness.py").read_text(encoding="utf-8"))


class TestLabelContrast(unittest.TestCase):
    def test_group_label_leans_on_text_not_quiet(self):
        text = src("morph-panel.js")
        self.assertIn("gl.style.color = mix(hue(sec.color), 55, 'var(--text)')", text)

    def test_light_and_medium_quiet_clear_4_5(self):
        css = src("styles.js")
        # Measured against the page, card and sunk colours of each theme.
        self.assertIn("--quiet:#5B636C", css)
        self.assertIn("--quiet:#9DA5AF", css)

    def test_auto_theme_falls_back_to_the_system_scheme(self):
        self.assertIn("prefers-color-scheme: light", src("morph-panel.js"))
        self.assertIn("prefers-color-scheme: light", src("shell.js"))


class TestWhatBrainIsToldWhenItBuildsACard(unittest.TestCase):
    def test_guidance_is_there(self):
        flat = re.sub(r"\s+", " ", AGENTS)
        for phrase in (
            "Say what the reading is, not what the card is usually",
            "outside its target, hold or comfort band is stated in the card's status line",
            "never \"Idle\", \"OK\" or \"Normal\"",
            "No empty space.",
            "Fields are 16px or larger.",
            "Every button shows an icon or words, and has a name.",
            "blank when its set is not loaded",
        ):
            self.assertIn(phrase, flat)


if __name__ == "__main__":
    unittest.main()
