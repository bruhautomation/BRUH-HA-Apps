"""Guards for the integration's translation files.

HA's frontend parses every translation string with an ICU message-format
parser: a literal brace (especially Jinja's double braces) makes the parse
throw and the whole config dialog render BLANK — which shipped in 3.0.0.
These tests make that class of bug impossible to reintroduce.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

COMPONENT_DIR = (
    Path(__file__).resolve().parent.parent
    / "bruh-claude-terminal" / "custom_components" / "bruh_claude"
)
FILES = [
    COMPONENT_DIR / "strings.json",
    COMPONENT_DIR / "translations" / "en.json",
]

# The only braces allowed are simple named placeholders like {version}
PLACEHOLDER = re.compile(r"\{[a-z0-9_]+\}")


def _walk_strings(node, path=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk_strings(value, f"{path}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _walk_strings(value, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_no_literal_braces_in_translation_strings(path):
    data = json.load(open(path))
    for key, text in _walk_strings(data):
        assert "{{" not in text, (
            f"{path.name}{key}: literal Jinja braces blank the HA dialog: {text[:80]!r}"
        )
        leftover = PLACEHOLDER.sub("", text)
        assert "{" not in leftover and "}" not in leftover, (
            f"{path.name}{key}: brace that isn't a simple placeholder: {text[:80]!r}"
        )


def test_strings_and_en_translation_identical():
    """Custom integrations serve translations/en.json; strings.json is the
    source of truth for contributors. They must never drift."""
    a = json.load(open(FILES[0]))
    b = json.load(open(FILES[1]))
    assert a == b


def test_menu_steps_have_labels():
    """Every async_show_menu step needs menu_options labels (defense in
    depth — the flow also passes labels inline)."""
    data = json.load(open(FILES[0]))
    user_step = data["config"]["step"]["user"]
    assert set(user_step["menu_options"]) == {"add_agent", "add_insight"}
