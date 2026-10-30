"""The top bar's mark: brAIn's logo, the assistant's name, or the house's own.

Two panel settings (`header_brand`, `header_text`) and one picture
(`panel/header_brand.py`) kept in /config/.brain/ui, written atomically,
accepted by its magic bytes (PNG, JPEG, WebP; never SVG), served from one
fixed route with the type those bytes give. An install that never chose is
untouched: the name while Personality is on, else the logo.
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "brain" / "panel"))

import header_brand  # noqa: E402
import settings_store  # noqa: E402

from test_todo_list import PanelCase  # noqa: E402

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\0" * 32
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\0" * 32
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'


class TestSettings(PanelCase):
    def test_unset_is_the_default(self):
        s = settings_store.load()
        self.assertIsNone(s["header_brand"])
        self.assertEqual(s["header_text"], "")

    def test_good_values_round_trip(self):
        for mode in ("logo", "name", "custom"):
            self.assertEqual(settings_store.save({"header_brand": mode})["header_brand"], mode)
        self.assertIsNone(settings_store.save({"header_brand": None})["header_brand"])

    def test_bad_values_are_refused(self):
        for bad in ("svg", "", 3, ["logo"], True):
            with self.assertRaises(ValueError):
                settings_store.save({"header_brand": bad})
        with self.assertRaises(ValueError):
            settings_store.save({"header_text": 5})

    def test_text_is_one_line_and_capped(self):
        out = settings_store.save({"header_text": "  " + "x" * 80 + "\n"})
        self.assertEqual(out["header_text"], "x" * header_brand.TEXT_MAX)
        self.assertEqual(settings_store.load()["header_text"], "x" * 24)
        self.assertNotIn("\n", settings_store.save({"header_text": "a\nb"})["header_text"])

    def test_a_hand_edited_bad_file_reads_as_unset(self):
        Path(settings_store.SETTINGS_FILE).write_text('{"header_brand": "evil", "header_text": 4}')
        s = settings_store.load()
        self.assertIsNone(s["header_brand"])
        self.assertEqual(s["header_text"], "")


class TestPicture(PanelCase):
    def setUp(self):
        super().setUp()
        self.ui = tempfile.TemporaryDirectory()
        self._old = header_brand.UI_DIR
        header_brand.UI_DIR = Path(self.ui.name) / "ui"

    def tearDown(self):
        header_brand.UI_DIR = self._old
        self.ui.cleanup()
        super().tearDown()

    def put(self, data):
        async def body(client):
            res = await client.put("/api/header/logo", data=data)
            return res.status, await res.text()
        return self.drive(body)

    def test_sniffing(self):
        self.assertEqual(header_brand.sniff(PNG), "image/png")
        self.assertEqual(header_brand.sniff(JPEG), "image/jpeg")
        self.assertEqual(header_brand.sniff(WEBP), "image/webp")
        self.assertIsNone(header_brand.sniff(SVG))
        self.assertIsNone(header_brand.sniff(b"GIF89a"))

    def test_each_type_is_accepted_and_served_with_its_own_type(self):
        for data, ctype in ((PNG, "image/png"), (JPEG, "image/jpeg"), (WEBP, "image/webp")):
            status, _ = self.put(data)
            self.assertEqual(status, 200)

            async def body(client):
                res = await client.get("/header-logo")
                return res.status, res.headers["Content-Type"], await res.read(), res.headers
            status, got, raw, headers = self.drive(body)
            self.assertEqual((status, got, raw), (200, ctype, data))
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_svg_oversize_and_other_are_refused_and_nothing_is_written(self):
        for data in (SVG, b"GIF89a" + b"\0" * 20, b"", PNG + b"\0" * header_brand.MAX_BYTES):
            status, _ = self.put(data)
            self.assertEqual(status, 400)
        self.assertFalse((header_brand.UI_DIR / header_brand.FILE).exists())

    def test_the_write_is_atomic_and_leaves_no_scratch(self):
        self.put(PNG)
        self.put(JPEG)
        self.assertEqual(sorted(os.listdir(header_brand.UI_DIR)), [header_brand.FILE])

    def test_a_stored_file_that_stopped_being_an_image_is_not_served(self):
        self.put(PNG)
        (header_brand.UI_DIR / header_brand.FILE).write_bytes(SVG)
        self.assertIsNone(header_brand.read())

    def test_no_picture_is_a_404_and_delete_removes_it(self):
        async def get(client):
            return (await client.get("/header-logo")).status
        self.assertEqual(self.drive(get), 404)
        self.put(PNG)
        self.assertEqual(self.drive(get), 200)

        async def delete(client):
            return (await client.delete("/api/header/logo")).status
        self.assertEqual(self.drive(delete), 200)
        self.assertEqual(self.drive(get), 404)

    def test_the_version_changes_with_the_picture(self):
        self.put(PNG)
        a = header_brand.version()
        self.put(JPEG)
        self.assertNotEqual(a, header_brand.version())

    def test_the_settings_route_saves_the_choice_and_status_carries_it(self):
        async def body(client):
            res = await client.put("/api/settings", json={
                "header_brand": "custom", "header_text": "Casa"})
            self.assertEqual(res.status, 200)
            bad = await client.put("/api/settings", json={"header_brand": "svg"})
            self.assertEqual(bad.status, 400)
        self.drive(body)
        _auth, read = self.server._status_payload()
        self.assertEqual(read["header"]["brand"], "custom")
        self.assertEqual(read["header"]["text"], "Casa")
        self.assertIsNone(read["header"]["image"])
        self.put(PNG)
        _auth, read = self.server._status_payload()
        self.assertTrue(read["header"]["image"].startswith("header-logo?v="))


class TestThePageWiring(unittest.TestCase):
    """The default is the page's old behaviour: unset means the name while
    Personality is on, else the logo; the name option needs a name."""

    def test_headerMark_keeps_the_old_default(self):
        js = (ROOT / "brain" / "panel" / "app.js").read_text()
        body = js[js.index("function headerMark()"):js.index("function applyHeader()")]
        self.assertIn('h.brand || (named ? "name" : "logo")', body)
        self.assertIn('mode === "name" && !named', body)


if __name__ == "__main__":
    unittest.main()
