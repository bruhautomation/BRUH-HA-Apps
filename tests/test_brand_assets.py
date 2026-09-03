#!/usr/bin/env python3
"""The artwork Home Assistant reads, and the artwork we keep in spec.

An integration page gets its icon and wide logo from a `brand/` folder beside
the manifest (HA 2026.3.0+ serves these itself and prefers them over the CDN).
Nothing crashes when that folder is missing or wrong — HA falls back to printing
the raw domain next to the name, which is what "brain brAIn" was for a year
while the artwork sat staged in `brands/` for a submission that could not be
made. That is the failure this file exists to catch: silent, cosmetic, and
invisible to every other test in the suite.

`brands/` is no longer submittable (home-assistant/brands auto-closes new
custom_integrations PRs) but is still held to that repo's spec, because a
validator that passes is worth more than one that has never been run — and
because the two sets are the same four files. They must stay byte-identical:
which route resolves first is not ours to control, so a user's logo must not
depend on it.

Sizes come from the brands spec, whose logo rule bounds the *shortest* side
rather than the longest. That is the rule the staged 512x384 assets broke, so
it is asserted as a bound and not as an equality that happens to pass.
"""

import json
import os
import struct
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
BRANDS_DIR = os.path.join(BASE_DIR, "brands", "custom_integrations")

# (add-on directory, integration domain)
INTEGRATIONS = [
    ("brain", "brain"),
    ("bruh-minecraft-server", "bruh_minecraft"),
    ("bright", "bright"),
    ("bruh-print", "bruh_print"),
]

# The four files HA looks for, and the size each must be. Icons are exact
# squares; logos are given as (width, height) of the 4:3 plate.
EXPECTED = {
    "icon.png": (256, 256),
    "icon@2x.png": (512, 512),
    "logo.png": (341, 256),
    "logo@2x.png": (682, 512),
}

# brands' own bounds on a logo's shortest side, per resolution.
LOGO_SHORTEST_SIDE = {"logo.png": (128, 256), "logo@2x.png": (256, 512)}


def png_size(path):
    """Width and height from the IHDR chunk, and a check that it is a PNG."""
    with open(path, "rb") as handle:
        header = handle.read(24)
    if header[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError(f"not a PNG: {path}")
    if header[12:16] != b"IHDR":
        raise ValueError(f"PNG without a leading IHDR chunk: {path}")
    return struct.unpack(">II", header[16:24])


def brand_dir(addon, domain):
    return os.path.join(BASE_DIR, addon, "custom_components", domain, "brand")


class TestBrandFolders(unittest.TestCase):
    """What ships beside the manifest."""

    def test_brand_folder_exists(self):
        for addon, domain in INTEGRATIONS:
            with self.subTest(domain=domain):
                self.assertTrue(
                    os.path.isdir(brand_dir(addon, domain)),
                    f"{domain} ships no brand/ folder, so its integration page "
                    f"will show the raw domain instead of a logo",
                )

    def test_brand_folder_sits_beside_the_manifest(self):
        # HA finds the folder relative to the integration it is loading, so a
        # brand/ one level out is invisible rather than wrong.
        for addon, domain in INTEGRATIONS:
            with self.subTest(domain=domain):
                manifest = os.path.join(
                    BASE_DIR, addon, "custom_components", domain, "manifest.json"
                )
                self.assertTrue(os.path.isfile(manifest), f"no manifest for {domain}")
                with open(manifest) as handle:
                    declared = json.load(handle)["domain"]
                self.assertEqual(
                    declared,
                    domain,
                    "the folder name must equal the manifest domain, or HA "
                    "resolves the brand against a domain nobody installs",
                )

    def test_every_expected_file_is_present_and_sized(self):
        for addon, domain in INTEGRATIONS:
            for name, (want_w, want_h) in EXPECTED.items():
                with self.subTest(domain=domain, file=name):
                    path = os.path.join(brand_dir(addon, domain), name)
                    self.assertTrue(os.path.isfile(path), f"missing {domain}/{name}")
                    self.assertEqual(
                        png_size(path),
                        (want_w, want_h),
                        f"{domain}/{name} is the wrong size",
                    )

    def test_no_extra_files_in_brand_folder(self):
        # An unrecognised name is dead weight that reads as artwork.
        allowed = set(EXPECTED) | {
            "dark_icon.png",
            "dark_icon@2x.png",
            "dark_logo.png",
            "dark_logo@2x.png",
        }
        for addon, domain in INTEGRATIONS:
            with self.subTest(domain=domain):
                found = set(os.listdir(brand_dir(addon, domain)))
                self.assertEqual(
                    found - allowed,
                    set(),
                    f"{domain}/brand/ holds files HA does not read",
                )

    def test_bare_integration_icon_is_gone(self):
        # custom_components/<domain>/icon.png was never read by anything. It
        # looked load-bearing beside a manifest, which is why it is asserted
        # absent rather than merely deleted.
        for addon, domain in INTEGRATIONS:
            with self.subTest(domain=domain):
                stray = os.path.join(
                    BASE_DIR, addon, "custom_components", domain, "icon.png"
                )
                self.assertFalse(
                    os.path.exists(stray),
                    f"{domain}/icon.png is back; HA reads brand/icon.png, not this",
                )


class TestBrandsSpec(unittest.TestCase):
    """The staged set, still held to home-assistant/brands' rules."""

    def test_logo_shortest_side_is_within_bounds(self):
        # The rule bounds the shortest side, which is what 512x384 broke: its
        # longest side was legal and its shortest was 128px over.
        for _, domain in INTEGRATIONS:
            for name, (low, high) in LOGO_SHORTEST_SIDE.items():
                with self.subTest(domain=domain, file=name):
                    path = os.path.join(BRANDS_DIR, domain, name)
                    width, height = png_size(path)
                    shortest = min(width, height)
                    self.assertGreaterEqual(
                        shortest, low, f"{domain}/{name} shortest side under {low}px"
                    )
                    self.assertLessEqual(
                        shortest, high, f"{domain}/{name} shortest side over {high}px"
                    )

    def test_icon_is_square(self):
        for _, domain in INTEGRATIONS:
            for name in ("icon.png", "icon@2x.png"):
                with self.subTest(domain=domain, file=name):
                    width, height = png_size(os.path.join(BRANDS_DIR, domain, name))
                    self.assertEqual(width, height, f"{domain}/{name} is not square")

    def test_hdpi_is_exactly_twice_its_base(self):
        # brands serves the @2x as the same image at twice the scale; an odd
        # ratio means one of the pair was regenerated and the other was not.
        for _, domain in INTEGRATIONS:
            for base, hdpi in (("icon.png", "icon@2x.png"), ("logo.png", "logo@2x.png")):
                with self.subTest(domain=domain, file=hdpi):
                    bw, bh = png_size(os.path.join(BRANDS_DIR, domain, base))
                    hw, hh = png_size(os.path.join(BRANDS_DIR, domain, hdpi))
                    self.assertEqual((hw, hh), (bw * 2, bh * 2), f"{domain}/{hdpi}")

    def test_icon_and_logo_are_not_the_same_file(self):
        # brands rejects a logo identical to its icon — the icon is served as
        # the logo's fallback, so shipping both is a file that says nothing.
        for _, domain in INTEGRATIONS:
            for icon, logo in (("icon.png", "logo.png"), ("icon@2x.png", "logo@2x.png")):
                with self.subTest(domain=domain, pair=logo):
                    with open(os.path.join(BRANDS_DIR, domain, icon), "rb") as handle:
                        icon_bytes = handle.read()
                    with open(os.path.join(BRANDS_DIR, domain, logo), "rb") as handle:
                        logo_bytes = handle.read()
                    self.assertNotEqual(icon_bytes, logo_bytes, f"{domain}/{logo}")


class TestTheTwoSetsAgree(unittest.TestCase):
    def test_shipped_and_staged_are_byte_identical(self):
        # render.mjs writes both from one SVG. If these ever differ, one path
        # was regenerated and the other was not, and which logo a user sees
        # depends on which route resolved first.
        for addon, domain in INTEGRATIONS:
            for name in EXPECTED:
                with self.subTest(domain=domain, file=name):
                    with open(os.path.join(brand_dir(addon, domain), name), "rb") as h:
                        shipped = h.read()
                    with open(os.path.join(BRANDS_DIR, domain, name), "rb") as h:
                        staged = h.read()
                    self.assertEqual(
                        shipped,
                        staged,
                        f"{domain}/{name} differs between brand/ and brands/; "
                        f"re-run `node branding/render.mjs`",
                    )


class TestRenderScriptWritesThem(unittest.TestCase):
    def test_render_script_names_every_shipped_path(self):
        # The PNGs are build output. If a path is dropped from render.mjs the
        # files linger and go stale silently, which is the same invisible
        # failure one level up.
        with open(os.path.join(BASE_DIR, "branding", "render.mjs")) as handle:
            source = handle.read()
        for addon, domain in INTEGRATIONS:
            for name in EXPECTED:
                with self.subTest(domain=domain, file=name):
                    path = f"{addon}/custom_components/{domain}/brand/{name}"
                    self.assertIn(
                        path, source, f"render.mjs no longer writes {path}"
                    )


if __name__ == "__main__":
    unittest.main()
