"""Checks the brand images against Home Assistant's image rules.

See https://github.com/home-assistant/brands#image-specification. Home
Assistant 2026.3 and later serves these from the integration's brand folder.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

BRAND_DIR = Path(__file__).resolve().parent.parent / "custom_components" / "bruh_cooking" / "brand"
ALLOWED_NAMES = {
    f"{dark}{kind}{hdpi}.png" for dark in ("", "dark_") for kind in ("icon", "logo") for hdpi in ("", "@2x")
}


def test_only_known_images() -> None:
    names = {path.name for path in BRAND_DIR.iterdir()}
    assert "icon.png" in names
    assert names <= ALLOWED_NAMES


@pytest.mark.parametrize("path", sorted(BRAND_DIR.glob("*.png")), ids=lambda path: path.name)
def test_image_meets_spec(path: Path) -> None:
    hdpi = "@2x" in path.name
    with Image.open(path) as image:
        assert image.format == "PNG"
        if "icon" in path.name:
            assert image.size == ((512, 512) if hdpi else (256, 256))
        else:
            low, high = (256, 512) if hdpi else (128, 256)
            assert low <= min(image.size) <= high
        # Trimmed: the artwork reaches every edge.
        assert image.convert("RGBA").getchannel("A").getbbox() == (0, 0, *image.size)
