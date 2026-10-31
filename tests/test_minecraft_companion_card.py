#!/usr/bin/env python3
"""BRUH Minecraft's panel: the Companion card and the header (#593, #594).

Read from the files. The card is brAIn's companion's: hidden entirely
without brAIn (one line says why), named as brAIn names it, with the two
things that belong to the world (protected places, a question on the pads)
and everything it did with Undo. The family list, bedtime, limits and model
are brAIn's (⚙ › Minecraft) and are not on this card any more.

The header carries the version and a changelog link at every width
(#594): it opens the release notes in the panel, newest first, and an
"Updated since you last looked" marker stays after an update until they are
opened. The real-browser measure is tests/manual/measure-minecraft-companion.mjs.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ADDON = REPO / "bruh-minecraft-server"
PANEL = ADDON / "panel"
INDEX = (PANEL / "index.html").read_text()
APP = (PANEL / "app.js").read_text()
CSS = (PANEL / "style.css").read_text()


def _load_companion():
    spec = importlib.util.spec_from_file_location("test_card_companion", PANEL / "companion.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _card_js() -> str:
    start = APP.index("// The companion (companion.py)")
    return APP[start:APP.index("// Quick chat / command", start)]


class _Card(HTMLParser):
    """The controls inside #companion-card and the label `for`s there."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.controls: list[dict] = []
        self.label_for: set[str] = set()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.depth == 0:
            if a.get("id") == "companion-card":
                self.depth = 1
            return
        if tag not in ("input", "br", "img", "meta", "link"):
            self.depth += 1
        if a.get("id"):
            self.ids.append(a["id"])
        if tag in ("input", "select", "textarea"):
            self.controls.append(dict(a, tag=tag))
        if tag == "label" and a.get("for"):
            self.label_for.add(a["for"])

    def handle_endtag(self, tag):
        if self.depth and tag not in ("input", "br", "img", "meta", "link"):
            self.depth -= 1


def _card() -> _Card:
    card = _Card()
    card.feed(INDEX)
    return card


class TestEveryFieldIsLabelled(unittest.TestCase):
    def test_every_control_in_the_card_has_a_label(self):
        card = _card()
        self.assertGreater(len(card.controls), 5)
        for c in card.controls:
            with self.subTest(control=c.get("id")):
                self.assertIn(c.get("id"), card.label_for)

    def test_no_field_is_explained_only_by_its_placeholder(self):
        for c in _card().controls:
            if c.get("placeholder"):
                self.assertIn(c.get("id"), _card().label_for)

    def test_ids_are_unique_in_the_card(self):
        ids = _card().ids
        self.assertEqual(len(ids), len(set(ids)))


class TestWithoutBrainThereIsNoCompanion(unittest.TestCase):
    def test_the_card_starts_hidden_and_one_line_says_why(self):
        self.assertRegex(INDEX, r'<div class="card wide companion" id="companion-card" hidden>')
        self.assertIn('id="companion-absent"', INDEX)
        self.assertIn("Install brAIn to have a companion play in the world.", INDEX)
        js = _card_js()
        self.assertIn("$('#companion-card').hidden = !head.show;", js)
        self.assertIn("$('#companion-absent').hidden = !!head.show;", js)

    def test_the_family_and_its_limits_are_not_this_cards(self):
        for gone in ("companion-family", "companion-bedtime", "companion-daily", "companion-on"):
            self.assertNotIn(f'id="{gone}"', INDEX)
        self.assertIn("⚙ › Minecraft", INDEX)

    def test_the_card_is_named_as_brain_names_it(self):
        js = _card_js()
        self.assertIn("$('#companion-title').textContent = ident.name || 'Companion';", js)


class TestTheFormsReachTheirRoutes(unittest.TestCase):
    def test_places_questions_and_undo(self):
        js = _card_js()
        self.assertIn("cSend('api/companion/zones', 'POST'", js)
        self.assertIn("cSend(`api/companion/zones/${encodeURIComponent(", js)
        self.assertIn("cSend('api/companion/ask', 'POST'", js)
        self.assertIn("/undo`, 'POST')", js)
        self.assertIn("cSend('api/companion', 'GET')", js)


class TestThePictures(unittest.TestCase):
    def test_every_picture_is_one_the_add_on_accepts_and_stays_on_a_post(self):
        companion = _load_companion()
        js = _card_js()
        table = js[js.index("const PAD_PICTURES"):js.index("];", js.index("const PAD_PICTURES"))]
        ids = re.findall(r"\['(minecraft:[a-z_]+)'", table)
        self.assertGreaterEqual(len(ids), 12)
        self.assertIn("['', ", table)          # the pad's own colour, the default
        for ident in ids:
            with self.subTest(picture=ident):
                self.assertEqual(companion.block_id(ident), ident)
                self.assertNotRegex(ident, r"sand|gravel|powder|leaves|flower|poppy|sapling|"
                                           r"carpet|torch|cake|bed|door|_egg|pig|horse|boat")


class TestTheHeaderSaysWhatChanged(unittest.TestCase):
    """#594: the version and a changelog link in the header at 390px and
    1200px; it opens the notes in the panel; the marker after an update."""

    def test_the_link_is_in_the_header_not_only_the_footer(self):
        header = INDEX[INDEX.index('<header class="topbar">'):INDEX.index("</header>")]
        self.assertIn('id="version-link"', header)
        self.assertIn("v__VERSION__ · changelog", header)
        self.assertIn("bruh-minecraft-server/CHANGELOG.md", header)
        self.assertIn('id="version-new"', header)
        self.assertIn("Updated since you last looked", header)

    def test_nothing_hides_it_at_any_width(self):
        self.assertNotRegex(CSS, r"\.brand-version\s*\{[^}]*display:\s*none")
        for media in re.findall(r"@media[^{]*\{(?:[^{}]*\{[^}]*\})*[^}]*\}", CSS):
            self.assertNotRegex(media, r"\.(brand-version|version-link)[^{]*\{[^}]*display:\s*none")

    def test_it_opens_the_notes_in_the_panel_and_remembers_what_was_read(self):
        self.assertIn("api('api/changelog')", APP)
        self.assertIn("ev.preventDefault();\n    openChangelog();", APP)
        self.assertIn("'bruh-minecraft.changelog.seen'", APP)
        self.assertIn("seenSet(releases[0].version);", APP)
        self.assertIn("$('#version-new').hidden = !fresh;", APP)
        self.assertIn('<dialog id="changelog-dialog"', INDEX)

    def test_the_image_carries_the_changelog(self):
        docker = (ADDON / "Dockerfile").read_text()
        self.assertIn("COPY CHANGELOG.md /opt/bruh-mc/CHANGELOG.md", docker)


def _lum(hexcol: str) -> float:
    h = hexcol.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))

    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)


def _ratio(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


class TestContrast(unittest.TestCase):
    """#594: the Stop button was 3.98:1 and the green "healthy" and TPS
    values 3.07:1. Every one is 4.5:1 or more now, in both themes."""

    def _tokens(self):
        dark = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", CSS[:CSS.index("@media")]))
        light_block = CSS[CSS.index("@media (prefers-color-scheme: light)"):]
        light_block = light_block[:light_block.index("}\n}") + 1]
        light = dict(dark, **dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-fA-F]{6})", light_block)))
        return dark, light

    def test_the_stop_button(self):
        self.assertIn(".btn-danger { background: var(--danger-btn); color: #fff;", CSS)
        for theme in self._tokens():
            self.assertGreaterEqual(_ratio("#ffffff", theme["danger-btn"]), 4.5)

    def test_healthy_and_tps_figures(self):
        for cls in ("tps-good", "tps-warn", "tps-bad"):
            rules = re.findall(rf"\.{cls}\s*\{{[^}}]*\}}", CSS)
            self.assertTrue(rules, cls)
            for rule in rules:
                self.assertRegex(rule, r"color: var\(--(accent|warn|danger)-ink\)")
        for theme in self._tokens():
            for ink in ("accent-ink", "warn-ink", "danger-ink"):
                with self.subTest(ink=ink, bg=theme["bg-card"]):
                    self.assertGreaterEqual(_ratio(theme[ink], theme["bg-card"]), 4.5)
                    self.assertGreaterEqual(_ratio(theme[ink], theme["bg"]), 4.5)


if __name__ == "__main__":
    unittest.main()
