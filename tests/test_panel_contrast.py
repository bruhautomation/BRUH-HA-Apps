"""Every colour the panel reads text in reaches 4.5:1, in both schemes.

`tests/manual/measure-tokens.mjs` measures what a browser painted, pane by
pane; this holds the tokens underneath it, so a screen the measure does not
open (Diagnostics' bad values, a status word in a dialog) is still covered by
the colour it is drawn in. On a real house a muted grey, a white label on the
brand azure and a status colour used as text each measured under 3:1.
"""
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
PANEL = os.path.join(HERE, "..", "brain", "panel")
sys.path.insert(0, PANEL)

import categories  # noqa: E402

AA = 4.5


def _lum(hexcode):
    h = hexcode.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def ratio(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tokens(block):
    return dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", block))


def _resolve(tokens, name):
    value = tokens[name].strip()
    for _ in range(8):
        m = re.fullmatch(r"var\((--[\w-]+)\)", value)
        if not m:
            return value
        value = tokens[m.group(1)].strip()
    return value


def panel_schemes():
    css = open(os.path.join(PANEL, "style.css"), encoding="utf-8").read()
    root = re.search(r"^:root\s*\{(.*?)^\}", css, re.S | re.M).group(1)
    light = re.search(r"@media \(prefers-color-scheme: light\)\s*\{\s*:root\s*\{(.*?)\}",
                      css, re.S).group(1)
    dark = _tokens(root)
    return {"dark": dark, "light": {**dark, **_tokens(light)}}, css


TEXT = ("--ink", "--ink-2", "--ink-3", "--accent-ink",
        "--good-ink", "--warning-ink", "--serious-ink", "--critical-ink")
SURFACES = ("--plane", "--surface", "--surface-2")
FILLS = (("--on-accent", "--accent-fill"), ("--btn-primary-ink", "--btn-primary-bg"))


class TestThePanelsTokens(unittest.TestCase):
    def test_every_text_colour_reads_on_every_surface(self):
        schemes, _ = panel_schemes()
        for scheme, tokens in schemes.items():
            for fg in TEXT:
                for bg in SURFACES:
                    a, b = _resolve(tokens, fg), _resolve(tokens, bg)
                    with self.subTest(scheme=scheme, fg=fg, bg=bg):
                        self.assertGreaterEqual(ratio(a, b), AA, f"{a} on {b}")

    def test_white_on_a_fill_reads(self):
        schemes, _ = panel_schemes()
        for scheme, tokens in schemes.items():
            for fg, bg in FILLS:
                a, b = _resolve(tokens, fg), _resolve(tokens, bg)
                with self.subTest(scheme=scheme, fg=fg, bg=bg):
                    self.assertGreaterEqual(ratio(a, b), AA, f"{a} on {b}")

    def test_a_status_colour_is_never_a_texts_colour(self):
        """`--critical` is a dot; a word is `--critical-ink`. The fill
        shades fail as text (#fab219 on white is 1.8:1)."""
        _, css = panel_schemes()
        bare = re.findall(r"(?<![-\w])color:\s*var\(--(good|warning|serious|critical|accent)\)", css)
        self.assertEqual(bare, [])

    def test_a_count_badge_and_a_primary_button_take_the_deeper_azure(self):
        _, css = panel_schemes()
        self.assertNotRegex(css, r"background:\s*var\(--accent\);\s*color:\s*var\(--on-accent\)")


class TestTheCardDesignSystem(unittest.TestCase):
    def test_card_text_reads_on_the_cards_own_surface(self):
        css = categories.CARD_STYLES
        light = _tokens(re.search(r"^:root\{(.*?)\}", css, re.S).group(1))
        dark = {**light, **_tokens(re.search(r"dark\)\{:root\{(.*?)\}", css, re.S).group(1))}
        for scheme, tokens in (("light", light), ("dark", dark)):
            for fg in ("--ink", "--ink2", "--muted"):
                with self.subTest(scheme=scheme, fg=fg):
                    self.assertGreaterEqual(ratio(tokens[fg], tokens["--bg"]), AA,
                                            f"{tokens[fg]} on {tokens['--bg']}")


if __name__ == "__main__":
    unittest.main()
