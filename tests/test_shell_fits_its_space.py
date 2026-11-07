"""brAIn's sidebar panel fits the space Home Assistant gives it, and Morph's
room rail stays put while the tab row hides (#689, #690).

`tests/manual/measure-shell-fit.mjs` is the measure that drives both on
screen; these hold the shape of the code it measured.
"""
import re
import unittest
from pathlib import Path

FRONTEND = (Path(__file__).resolve().parent.parent / "brain" / "custom_components"
            / "brain" / "morph" / "frontend")


def shell() -> str:
    return (FRONTEND / "shell.js").read_text(encoding="utf-8")


class TestTheShellIsNotTheScreensHeight(unittest.TestCase):
    def test_the_host_subtracts_its_own_top(self):
        host = re.search(r":host\{([^}]*)\}", shell()).group(1)
        heights = re.findall(r"height:([^;]+);", host)
        self.assertTrue(heights)
        for h in heights:
            self.assertIn("--brain-shell-top", h, h)

    def test_outer_scrolls_are_held_while_connected_only(self):
        src = shell()
        connected = src[src.index("  connectedCallback() {"):src.index("  disconnectedCallback() {")]
        gone = src[src.index("  disconnectedCallback() {"):src.index("  draw() {")]
        self.assertIn("this.holdOuter()", connected)
        self.assertIn("this.releaseOuter()", gone)
        hold = src[src.index("  holdOuter() {"):src.index("  releaseOuter() {")]
        self.assertIn("passive: true", hold)
        # Through shadow roots to the page: a fragment's host is the next one up.
        walk = src[src.index("  ancestors() {"):src.index("  holdOuter() {")]
        self.assertIn("nodeType === 11", walk)
        self.assertIn(".host", walk)


class TestTheRailKeepsItsPlace(unittest.TestCase):
    def test_the_rail_is_sized_from_the_shown_header(self):
        styles = (FRONTEND / "styles.js").read_text(encoding="utf-8")
        rule = re.search(r"@media \(any-pointer:coarse\)\{[^@]*?\.srail\{([^}]*)\}", styles).group(1)
        self.assertIn("--morph-rail-h", rule)
        self.assertIn("--morph-rail-top", rule)
        src = shell()
        self.assertIn("--brain-shown-top", src)
        home = re.search(r"\n\.home\{([^}]*)\}", src).group(1)
        self.assertIn("--morph-rail-h:calc(100dvh - var(--brain-shell-top,0px) - var(--brain-shown-top,0px)", home)
        # It slides exactly as Home does, so the two cancel on screen.
        self.assertIn("--morph-rail-ease:top .22s ease", src)


if __name__ == "__main__":
    unittest.main()
