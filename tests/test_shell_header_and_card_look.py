"""The shell's header and the insight cards' look (#539), the server half.

* An insight card follows the dashboard's theme inside brAIn's shell: the
  card stylesheet restates its colours for `data-theme` dark, medium and
  light with Morph's surfaces and hues, and a card saved under an older
  copy of the sheet is served with this one (`refresh_styles`).
* ⚙ › Dashboard › Header tabs is one of Morph's settings: a label and an
  icon per header tab, cleaned on the way in.
* Diagnostics names a background job by what it does (#557), and a
  rehearsal row by what was planted.

The panel halves are measured in the browser: `measure-shell`,
`measure-settings`.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain" / "panel"))

import categories  # noqa: E402
import health  # noqa: E402
import rehearsal  # noqa: E402

from morph_env import MorphEnv  # noqa: E402

# Morph's surfaces and first hue (styles.js: --surface, --sky).
MORPH = {"dark": ("#15181b", "#9cc2f5"), "medium": ("#34383d", "#a7c8f2"),
         "light": ("#ffffff", "#3b78c9")}


def _block(css: str, theme: str) -> dict:
    m = re.search(r':root\[data-theme="%s"\]\{(.*?)\}' % theme, css, re.S)
    assert m, theme
    return dict(re.findall(r"(--[\w-]+):\s*([^;]+);", m.group(1) + ";"))


class TestTheCardLooksLikeTheDashboard(unittest.TestCase):
    def test_each_theme_restates_the_palette_in_morphs_colours(self):
        css = categories.CARD_STYLES
        for theme, (bg, c1) in MORPH.items():
            with self.subTest(theme=theme):
                tokens = _block(css, theme)
                self.assertEqual(tokens["--bg"].lower(), bg)
                self.assertEqual(tokens["--c1"].lower(), c1)
                for key in ("--ink", "--ink2", "--muted", "--grid", "--axis",
                            "--c8", "--other", "--seq-lo", "--seq-hi", "--div-mid"):
                    self.assertIn(key, tokens)
        self.assertIn("Manrope", css)

    def test_the_prompt_defaults_to_the_dashboards_look(self):
        contract = categories._CARD_CONTRACT
        self.assertIn("the dashboard's look unless the person asked for another", contract)

    def test_an_older_sheet_is_served_as_this_one(self):
        old = ('<!doctype html><html><head><style data-brain="card-styles">'
               ':root{--bg:#000}</style></head><body></body></html>')
        new = categories.refresh_styles(old)
        self.assertIn(categories.STYLE_TAG, new)
        self.assertNotIn("--bg:#000}", new)
        self.assertEqual(new.count('data-brain="card-styles"'), 1)
        self.assertEqual(categories.refresh_styles(new), new)

    def test_a_card_from_before_the_sheet_is_left_alone(self):
        bare = "<html><head><style>body{color:red}</style></head></html>"
        self.assertEqual(categories.refresh_styles(bare), bare)
        self.assertEqual(categories.refresh_styles(""), "")


class TestHeaderTabsAreADashboardSetting(unittest.TestCase):
    def test_a_label_and_an_icon_per_tab_cleaned_on_the_way_in(self):
        with MorphEnv() as env:
            out = env.settings.update({"header_tabs": {
                "home": {"label": "  The   house ", "icon": "home"},
                "insights": {"label": "", "icon": "nope"},
                "ask": "not a row",
                "elsewhere": {"label": "x"},
                "memory": {"label": "M" * 60, "icon": "brain"},
            }})
            tabs = out["header_tabs"]
            self.assertEqual(tabs["home"], {"label": "The house", "icon": "home"})
            self.assertNotIn("insights", tabs)
            self.assertNotIn("ask", tabs)
            self.assertNotIn("elsewhere", tabs)
            self.assertEqual(len(tabs["memory"]["label"]), env.settings.TAB_LABEL_MAX)
            self.assertEqual(env.settings.load()["header_tabs"], tabs)

    def test_nothing_set_is_every_tab_its_own(self):
        with MorphEnv() as env:
            self.assertEqual(env.settings.load()["header_tabs"], {})


class TestDiagnosticsInPlainWords(unittest.TestCase):
    def test_a_background_job_is_named_by_what_it_does(self):
        self.assertEqual(health.daemon_words("usage_tracker"), "the usage tracker")
        self.assertEqual(health.daemon_words("assist_listener"), "the voice listener")
        self.assertEqual(health.daemon_words("something_new"), "something new")
        for name in health.DAEMONS:
            self.assertNotIn("_", health.daemon_words(name), name)

    def test_the_roll_call_carries_the_words(self):
        import importlib
        server = importlib.import_module("server")
        rows = server._annotate_daemons({"ttyd": {"running": False},
                                         "usage_tracker": {"running": True}},
                                        {"enable_terminal": False})
        self.assertEqual(rows["ttyd"]["what"], "the terminal")
        self.assertEqual(rows["usage_tracker"]["what"], "the usage tracker")

    def test_every_planted_thing_has_a_name_without_ids(self):
        for row in rehearsal.PLAN:
            with self.subTest(row=row["id"]):
                self.assertTrue(row.get("name"))
                self.assertNotIn(rehearsal.PREFIX, row["name"])
                self.assertNotIn("_", row["name"])


if __name__ == "__main__":
    unittest.main()
