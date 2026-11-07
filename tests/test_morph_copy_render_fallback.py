"""A house copy of Morph's panel that loads and then throws as it draws is
replaced by Morph's own, never left blank (#706).

boot.js fell back only when the import failed. A Tell removed an import and
left a reference to it, the module imported fine, and every render threw.
Now boot.js watches the first render of a panel that came from this house's
code and swaps in Morph's own (`shipped/`) under another element name, with
the reason where the panel says it. It needs to know whether any copy is in
use, which static.py writes in (`COPIES`). `measure-morph-copy-fallback`
drives it in a browser.
"""
import json
import unittest

import test_morph_own_code as base

FRONTEND = base.COMPONENT / "frontend"


class TestBootIsToldTheCopiesInUse(unittest.TestCase):
    setUpClass = classmethod(base.TestTheIntegrationServesTheCopy.setUpClass.__func__)
    setUp = base.TestTheIntegrationServesTheCopy.setUp
    kw = base.TestTheIntegrationServesTheCopy.kw
    say = base.TestTheIntegrationServesTheCopy.say

    def boot(self):
        (self.frontend / "boot.js").write_text(
            "const STAMP = '';\nconst MODULES = [];\nconst COPIES = [];\n")
        return self.static.boot_source(**self.kw())

    def test_an_active_copy_is_written_in(self):
        self.say(("morph-panel.js", "active"), ("styles.js", "paused"))
        self.assertIn('const COPIES = ["morph-panel.js"];', self.boot())

    def test_none_in_use_is_none(self):
        self.assertIn("const COPIES = [];", self.boot())

    def test_a_copy_of_a_fixed_file_is_never_one(self):
        self.state.write_text(json.dumps({"files": [{"name": "boot.js", "status": "active"}]}))
        self.assertIn("const COPIES = [];", self.boot())


class TestBootFallsBackOnAFirstRenderThatThrows(unittest.TestCase):
    def test_the_loader_watches_and_swaps(self):
        boot = (FRONTEND / "boot.js").read_text(encoding="utf-8")
        self.assertIn("const COPIES = [];", boot)
        mount = boot[boot.index("  mount() {"):boot.index("  ready() {")]
        for word in ("this.watch()", "'error'", "'unhandledrejection'", "loadShipped()",
                     "window.__morphFallback = why"):
            self.assertIn(word, mount)
        self.assertIn("morph-panel-shipped", boot)

    def test_the_shell_finds_the_panel_under_either_name(self):
        shell = (FRONTEND / "shell.js").read_text(encoding="utf-8")
        self.assertIn("querySelector('morph-panel, morph-panel-shipped')", shell)


if __name__ == "__main__":
    unittest.main()
