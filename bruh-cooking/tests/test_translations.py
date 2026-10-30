"""Checks the translations against the English strings."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from homeassistant.core import HomeAssistant
from homeassistant.helpers.translation import async_get_translations

from custom_components.bruh_cooking.const import DOMAIN

TRANSLATIONS = Path(__file__).resolve().parent.parent / "custom_components" / "bruh_cooking" / "translations"
LANGUAGES = sorted(path.stem for path in TRANSLATIONS.glob("*.json") if path.stem != "en")
PLACEHOLDER = re.compile(r"\{\w+\}")


def flatten(node: dict, prefix: str = "") -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        out.update(flatten(value, path) if isinstance(value, dict) else {path: value})
    return out


ENGLISH = flatten(json.loads((TRANSLATIONS / "en.json").read_text()))


def test_languages() -> None:
    assert LANGUAGES == ["de", "es", "fr", "it", "nl", "pl", "sv", "zh-Hans"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_translation_matches_english(language: str) -> None:
    """Same keys as English, nothing empty, and the same {placeholders}."""
    strings = flatten(json.loads((TRANSLATIONS / f"{language}.json").read_text()))
    assert strings.keys() == ENGLISH.keys()
    for key, text in strings.items():
        assert text.strip(), key
        assert sorted(PLACEHOLDER.findall(text)) == sorted(PLACEHOLDER.findall(ENGLISH[key])), key


@pytest.mark.parametrize(
    ("language", "expected"), [("de", "Garen"), ("fr", "Cuisson en cours"), ("zh-Hans", "烹饪中")]
)
async def test_home_assistant_loads_translations(
    hass: HomeAssistant, language: str, expected: str
) -> None:
    translations = await async_get_translations(hass, language, "entity", {DOMAIN})
    assert translations[f"component.{DOMAIN}.entity.sensor.status.state.cooking"] == expected


@pytest.mark.parametrize(
    ("language", "expected"), [("en", "Add account"), ("de", "Konto hinzufügen")]
)
async def test_add_button_label(hass: HomeAssistant, language: str, expected: str) -> None:
    """The integration page's add button shows config.initiate_flow.user instead of "Add hub"."""
    translations = await async_get_translations(hass, language, "config", {DOMAIN})
    assert translations[f"component.{DOMAIN}.config.initiate_flow.user"] == expected
