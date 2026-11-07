"""Insights says how a card differs from the Home tab once, above its title
(#695).

A house's own layer had added the same explainer above the title while the
shipped one sat under it, so the owner read it twice and asked for the top
one only. The shipped line is the top one now: right under the needs strip,
above the Insights title, naming the Home tab by the label the tab row gives
it, at least a 40px target, and saying what each place is for.
`measure-shell` drives it on screen.
"""
import re
import unittest
from pathlib import Path

PANEL = Path(__file__).resolve().parent.parent / "brain" / "panel"


def dash_section() -> str:
    html = (PANEL / "index.html").read_text(encoding="utf-8")
    start = html.index('<section id="dash"')
    return html[start:html.index("</section>", html.index('id="grid"', start))]


def about_function() -> str:
    js = (PANEL / "app.js").read_text(encoding="utf-8")
    start = js.index("function renderAboutCards()")
    return js[start:js.index("\n}\n", start)]


class TestTheExplainerIsAboveTheTitle(unittest.TestCase):
    def test_one_explainer_between_the_needs_strip_and_the_title(self):
        dash = dash_section()
        self.assertEqual(dash.count('id="aboutCardsBtn"'), 1)
        strip = dash.index('id="needsStrip"')
        about = dash.index('class="aboutcards"')
        title = dash.index('<h1 class="panetitle">Insights</h1>')
        self.assertLess(strip, about)
        self.assertLess(about, title)

    def test_the_target_is_at_least_forty_pixels_at_every_width(self):
        css = (PANEL / "style.css").read_text(encoding="utf-8")
        rule = re.search(r"\.aboutline \{(.*?)\}", css, re.S).group(1)
        height = int(re.search(r"min-height:\s*(\d+)px", rule).group(1))
        self.assertGreaterEqual(height, 40)


class TestItNamesTheHomeTabAndSaysWhatGoesWhere(unittest.TestCase):
    def test_the_line_names_the_home_tab_by_its_label(self):
        fn = about_function()
        self.assertIn('tabWords("home").label', fn)
        # The button's own words are set from it, not left as "the dashboard".
        self.assertRegex(fn, r"btn\.textContent\s*=\s*on\s*\?\s*`[^`]*\$\{home\}")

    def test_what_it_opens_to(self):
        fn = about_function()
        for words in ("live and in control", "days of history", "one question per card",
                      "never controls anything", "Needs you", 'tabWords("memory")'):
            self.assertIn(words, fn)


if __name__ == "__main__":
    unittest.main()
