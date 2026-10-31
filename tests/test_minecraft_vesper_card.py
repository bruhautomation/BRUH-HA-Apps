#!/usr/bin/env python3
"""The Vesper card on BRUH Minecraft's panel Dashboard, read from the files.

The owner, looking at the first card: "What am I supposed to enter here?
Very unclear" — an unlabeled text box with only a placeholder, an
unlabeled number, and no way to set the family list at all (without it
Vesper does nothing). The card is now a setup flow, and these hold its
shape: every field has a visible label, the family editor, the places
form and the question form reach their routes, the pad pictures are ones
the engine accepts and that stay put on a fence post, the roles keep the
engine's stored values under the wording a parent reads, and the status
line explains an empty family (the sentence itself is the engine's,
tested in test_minecraft_vesper.TestTheHeadline). The real-browser
measure is tests/manual/measure-minecraft-vesper.mjs.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import unittest
from html.parser import HTMLParser
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PANEL = REPO / "bruh-minecraft-server" / "panel"
INDEX = (PANEL / "index.html").read_text()
APP = (PANEL / "app.js").read_text()


def _load_vesper():
    spec = importlib.util.spec_from_file_location("test_vesper_card_engine", PANEL / "vesper.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _vesper_block() -> str:
    start = APP.index("// Vesper in the game (vesper.py)")
    return APP[start:APP.index("// Quick chat / command", start)]


class _Card(HTMLParser):
    """The controls inside #vesper-card and the label `for`s there."""

    def __init__(self):
        super().__init__()
        self.depth = 0
        self.controls: list[dict] = []
        self.label_for: set[str] = set()
        self.ids: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self.depth == 0:
            if a.get("id") == "vesper-card":
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
        self.assertGreaterEqual(len(card.controls), 14)
        for c in card.controls:
            with self.subTest(control=c.get("id")):
                self.assertTrue(c.get("id") in card.label_for or c.get("aria-label"),
                                f"{c} has no <label for> and no aria-label")

    def test_no_field_is_explained_only_by_its_placeholder(self):
        # The bedtime box, the one in the complaint, says what it is for in words.
        self.assertIn('<label for="vesper-bedtime">Bedtime switch</label>', INDEX)
        self.assertIn("Vesper says goodnight and stops when this is on. Pick a toggle helper "
                      "or a door sensor. Leave empty for no bedtime.", INDEX)
        self.assertIn('<label for="vesper-bedtime-when">Bedtime is when it is</label>', INDEX)
        self.assertIn("so that a closed door means bedtime", INDEX)
        self.assertIn('<label for="vesper-daily">Most things Vesper may do in a day</label>', INDEX)
        self.assertIn("120 is plenty for an afternoon of play.", INDEX)

    def test_ids_are_unique_in_the_card(self):
        ids = _card().ids
        self.assertEqual(len(ids), len(set(ids)))

    def test_the_family_rows_label_every_field_they_make(self):
        js = _vesper_block()
        row = js[js.index("function renderFamily"):js.index("function familyHas")]
        made = re.findall(r'<(?:input|select)\s+id="([^"]+)"', row)
        self.assertEqual(sorted(made), ["vp-name-${i}", "vp-players-${i}", "vp-role-${i}"])
        for ident in made:
            self.assertIn(f'<label for="{ident}">', row)
        self.assertIn("Bedrock/iPad players start with a dot, e.g. .Kaz8044", row)

    def test_the_switch_is_a_labelled_switch(self):
        self.assertRegex(INDEX, r'<label class="vesper-switch" for="vesper-on">')
        self.assertIn('id="vesper-on" type="checkbox" role="switch"', INDEX)


class TestTheFormsReachTheirRoutes(unittest.TestCase):
    def test_the_family_editor_puts_the_roster(self):
        js = _vesper_block()
        save = js[js.index("$('#vesper-family-save')"):js.index("// -- 2.")]
        self.assertIn("vSend('api/vesper/family', 'PUT', { people })", save)
        self.assertIn(".split(',')", save)

    def test_seen_players_are_one_tap_rows(self):
        js = _vesper_block()
        self.assertIn("vs.world.last_seen", js)
        self.assertIn("data-seen=", js)
        self.assertIn("Add ${esc(x.name)}", js)

    def test_the_places_form_posts_and_remove_deletes(self):
        js = _vesper_block()
        self.assertIn("vSend('api/vesper/zones', 'POST', {", js)
        self.assertIn("vSend(`api/vesper/zones/${encodeURIComponent(b.dataset.zoneDel)}`, 'DELETE')", js)
        self.assertIn("Use ${esc(p.name)}’s spot", js)
        self.assertIn("press F3 (Java) or turn on Show Coordinates (Bedrock)", INDEX)

    def test_the_question_form_posts_and_says_why_it_cannot(self):
        js = _vesper_block()
        self.assertIn("vSend('api/vesper/ask', 'POST', {", js)
        self.assertIn("$('#vesper-ask-go').disabled = !!why", js)
        self.assertIn("is not in the game right now", js)

    def test_settings_post_the_bedtime_rule_without_typing_equals(self):
        js = _vesper_block()
        self.assertIn("when === 'on' ? entity : `${entity}=${when}`", js)
        self.assertIn("vSend('api/vesper/entities', 'GET')", js)
        self.assertIn('list="vesper-entities"', INDEX)

    def test_saves_say_what_happened(self):
        js = _vesper_block()
        self.assertNotIn("alert(", js)
        for msg in ("#vesper-family-msg", "#vesper-settings-msg", "#vesper-zone-msg",
                    "#vesper-ask-msg", "#vesper-did-msg"):
            self.assertIn(f"vSay('{msg}', r.error, false)", js)


class TestStatusAndWording(unittest.TestCase):
    def test_the_status_line_is_the_engines_headline(self):
        js = _vesper_block()
        self.assertIn("status.textContent = head.text", js)
        self.assertIn('id="vesper-status"', INDEX)
        # The empty family is a state the stylesheet marks, not only a sentence.
        self.assertIn('[data-code="no_family"]', (PANEL / "style.css").read_text())

    def test_roles_keep_the_stored_values(self):
        js = _vesper_block()
        self.assertIn("['child', 'Child — Vesper plays with them and asks them questions with pads']", js)
        self.assertIn("['reader', 'Grown-up — Vesper plays with them too, and they can talk to it "
                      "and give it commands in chat']", js)

    def test_vesper_is_not_worded_as_only_for_children(self):
        card = INDEX[INDEX.index('id="vesper-card"'):INDEX.index("<!-- Console -->")]
        self.assertIn("Vesper plays in the world with your family", card)
        self.assertIn("next time someone from the family joins", _vesper_block())
        self.assertNotIn("for the children", card)

    def test_empty_states_guide(self):
        js = _vesper_block()
        self.assertIn("Nothing yet — Vesper will say hello here", js)
        self.assertIn("No questions yet. Ask one above", js)
        self.assertIn("No protected places yet.", js)


class TestThePictures(unittest.TestCase):
    def test_every_picture_is_one_the_engine_accepts_and_stays_on_a_post(self):
        vesper = _load_vesper()
        js = _vesper_block()
        table = js[js.index("const VESPER_PICTURES"):js.index("];", js.index("const VESPER_PICTURES"))]
        ids = re.findall(r"\['(minecraft:[a-z_]+)'", table)
        self.assertGreaterEqual(len(ids), 12)
        self.assertIn("['', ", table)          # the pad's own colour, the engine's default
        for ident in ids:
            with self.subTest(picture=ident):
                self.assertEqual(vesper.block_id(ident), ident)
                self.assertNotRegex(ident, r"sand|gravel|powder|leaves|flower|poppy|sapling|"
                                           r"carpet|torch|cake|bed|door|_egg|pig|horse|boat")


if __name__ == "__main__":
    unittest.main()
