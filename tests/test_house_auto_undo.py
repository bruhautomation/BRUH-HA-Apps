#!/usr/bin/env python3
"""The house layer undoes a bad change by itself (self-learning plan 3.3,
as decided in section 0: no person presses anything before brAIn changes
its own surfaces, so the page has to catch a bad change itself).

A version of `house.css`/`house.js` the page has not yet seen work is
judged by the page: `house-layer.js` reports `confirm` (kept as the last
good copy, under /data where a session cannot write) or `revert` (the last
good copy put back, or the file taken away when there is none, with why).
Only the version the page loaded is ever touched, so a stale tab cannot
undo a newer edit. Driven through `house_ui` and the real route, plus the
page's own check and the words every session is told.
"""
from __future__ import annotations

import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL_DIR = BASE_DIR / "brain" / "panel"
sys.path.insert(0, str(PANEL_DIR))

import house_ui  # noqa: E402

from test_todo_list import PanelCase  # noqa: E402

GOOD_JS = "// good\nwindow.__house = 1;\n"
BAD_JS = "// bad\nthrow new Error('boom');\n"


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._old = (house_ui.HOUSE_DIR, house_ui.STATE_DIR)
        house_ui.HOUSE_DIR = root / "ui"
        house_ui.STATE_DIR = root / "state"
        house_ui.HOUSE_DIR.mkdir()

    def tearDown(self):
        house_ui.HOUSE_DIR, house_ui.STATE_DIR = self._old
        self.tmp.cleanup()

    def put(self, name: str, text: str) -> str:
        path = house_ui.HOUSE_DIR / name
        path.write_text(text, encoding="utf-8")
        return next(r for r in house_ui.listing() if r["name"] == name)["v"]

    def text(self, name: str) -> str | None:
        path = house_ui.HOUSE_DIR / name
        return path.read_text(encoding="utf-8") if path.exists() else None


class TestConfirmAndRevert(StoreCase):
    def test_a_new_version_is_unconfirmed_until_the_page_says_so(self):
        v = self.put("house.js", GOOD_JS)
        [row] = house_ui.listing()
        self.assertFalse(row["good"])
        self.assertTrue(house_ui.confirm("house.js", v))
        [row] = house_ui.listing()
        self.assertTrue(row["good"])

    def test_a_broken_edit_goes_back_to_the_last_good_version(self):
        v = self.put("house.js", GOOD_JS)
        house_ui.confirm("house.js", v)
        bad = self.put("house.js", BAD_JS + "\n// longer, so the stamp moves\n")
        out = house_ui.revert("house.js", bad, "house.js threw while loading: boom")
        self.assertEqual((out["reverted"], out["restored"]), (True, "previous"))
        self.assertEqual(self.text("house.js"), GOOD_JS)
        # The restored copy is known good, so it is not judged again.
        [row] = house_ui.listing()
        self.assertTrue(row["good"])
        [entry] = house_ui.reverts()
        self.assertEqual(entry["why"], "house.js threw while loading: boom")
        self.assertTrue(Path(entry["kept"]).read_text().startswith("// bad"))
        self.assertEqual(house_ui.last_revert()["name"], "house.js")

    def test_with_no_good_version_the_file_is_taken_away(self):
        v = self.put("house.css", "body { display: none }\n")
        out = house_ui.revert("house.css", v, "the page is hidden")
        self.assertEqual((out["reverted"], out["restored"]), (True, "none"))
        self.assertIsNone(self.text("house.css"))

    def test_a_confirmed_version_that_breaks_later_is_taken_away(self):
        v = self.put("house.js", GOOD_JS)
        house_ui.confirm("house.js", v)
        out = house_ui.revert("house.js", v, "house.js threw while loading: x")
        self.assertEqual(out["restored"], "none")
        self.assertIsNone(self.text("house.js"))
        self.assertFalse((house_ui.STATE_DIR / "good" / "house.js").exists())

    def test_a_stale_tab_never_undoes_a_newer_edit(self):
        old = self.put("house.js", BAD_JS)
        self.put("house.js", GOOD_JS + "// a newer edit\n")
        out = house_ui.revert("house.js", old, "threw")
        self.assertFalse(out["reverted"])
        self.assertIn("newer edit", self.text("house.js"))
        self.assertFalse(house_ui.confirm("house.js", old))

    def test_the_page_and_diagnostics_are_told(self):
        v = self.put("house.css", "x{}\n")
        house_ui.revert("house.css", v, "header.topbar is hidden")
        block = house_ui.head_block()
        meta = re.search(r'content="([^"]*)"', block).group(1)
        import html as _h
        facts = json.loads(_h.unescape(meta))
        self.assertEqual(facts["reverted"]["why"], "header.topbar is hidden")
        self.assertEqual(house_ui.summary()["last_revert"]["name"], "house.css")
        self.assertNotIn("x{}", json.dumps(house_ui.summary()))

    def test_the_verdict_body_is_checked(self):
        for body in (None, {"name": "secrets.yaml", "v": "1", "outcome": "revert"},
                     {"name": "house.js", "v": "1", "outcome": "delete"},
                     {"name": "house.js", "v": "", "outcome": "confirm"}):
            with self.assertRaises(ValueError):
                house_ui.outcome(body)


class TestTheRoute(PanelCase):
    def setUp(self):
        super().setUp()
        self.ui = self.server.house_ui
        self.root = Path(self.tmp.name)
        self._old_dirs = (self.ui.HOUSE_DIR, self.ui.STATE_DIR)
        self.ui.HOUSE_DIR = self.root / "ui"
        self.ui.STATE_DIR = self.root / "house-state"
        self.ui.HOUSE_DIR.mkdir()

    def tearDown(self):
        self.ui.HOUSE_DIR, self.ui.STATE_DIR = self._old_dirs
        super().tearDown()

    def post(self, body) -> tuple[int, dict | str]:
        async def run(client):
            res = await client.post("/api/house/outcome", json=body)
            return res.status, (await res.json() if res.status == 200 else await res.text())
        return self.drive(run)

    def test_confirm_then_revert_through_the_route(self):
        (self.ui.HOUSE_DIR / "house.js").write_text(GOOD_JS)
        v = self.ui.listing()[0]["v"]
        self.assertEqual(self.post({"name": "house.js", "v": v, "outcome": "confirm"}),
                         (200, {"confirmed": True}))
        (self.ui.HOUSE_DIR / "house.js").write_text(BAD_JS + "// more\n")
        bad = self.ui.listing()[0]["v"]
        status, out = self.post({"name": "house.js", "v": bad, "outcome": "revert",
                                 "why": "house.js threw while loading: boom"})
        self.assertEqual(status, 200)
        self.assertTrue(out["reverted"])
        self.assertEqual((self.ui.HOUSE_DIR / "house.js").read_text(), GOOD_JS)

    def test_a_bad_body_is_refused(self):
        status, _ = self.post({"name": "app.js", "v": "1", "outcome": "revert"})
        self.assertEqual(status, 400)


class TestThePageChecksItself(unittest.TestCase):
    def test_the_loader_judges_new_versions_and_reports(self):
        js = (PANEL_DIR / "house-layer.js").read_text(encoding="utf-8")
        self.assertIn("api/house/outcome", js)
        self.assertIn("outcome: 'revert'", js)
        self.assertIn("outcome: 'confirm'", js)
        self.assertIn("!f.good", js)
        self.assertIn("sessionStorage", js, "one reload per broken version")

    def test_what_the_check_looks_for_is_on_the_page(self):
        """A renamed header would fail every house change's check."""
        js = (PANEL_DIR / "house-layer.js").read_text(encoding="utf-8")
        html = (PANEL_DIR / "index.html").read_text(encoding="utf-8")
        for sel in re.findall(r"'((?:header|nav|main)\.[a-z]+)'", js):
            tag, cls = sel.split(".")
            self.assertRegex(html, rf'<{tag} [^>]*class="[^"]*\b{cls}\b', sel)


class TestNothingDemandsAPressForBrainsOwnSurfaces(unittest.TestCase):
    """The owner chose: no human press on self-modification, YOLO or not."""

    PRESS = re.compile(r"(needs?|wait for|ask for|requires?) (a |the )?"
                       r"(person|human|press|approval)", re.I)

    def test_the_generated_context(self):
        text = (BASE_DIR / "brain" / "scripts" / "ha-context-gen.sh").read_text()
        own = text.split("## brAIn's own surfaces need nobody's press", 1)[1].split("\n## ", 1)[0]
        for surface in ("house layer", "/config/morph/", "LEARNED.md", "memory",
                        "personality notes"):
            self.assertIn(surface, own)
        layer = text.split("## brAIn's own page (the house layer)", 1)[1].split("\n## ", 1)[0]
        self.assertIn("undone\nautomatically", layer)
        self.assertNotRegex(layer, self.PRESS)
        # The YOLO wording is kept.
        self.assertIn("something needs a human first", text)

    def test_the_chat_identity(self):
        server = (PANEL_DIR / "server.py").read_text(encoding="utf-8")
        ident = server.split('CHAT_IDENTITY = """', 1)[1].split('"""', 1)[0]
        self.assertIn("without waiting for a press", ident)
        self.assertIn("undone automatically", ident)
        self.assertIn("LEARNED.md", ident)


if __name__ == "__main__":
    unittest.main()
