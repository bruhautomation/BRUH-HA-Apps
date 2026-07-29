"""Tests for insight_format.py (HA-free helpers) plus a compile check over
every integration module — the rest of the insight engine needs a running
HA core, so structural integrity is what CI can guarantee."""

from __future__ import annotations

import importlib.util
import py_compile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
COMPONENT_DIR = (
    REPO_ROOT / "brain" / "custom_components" / "brain"
)


def load_insight_format():
    spec = importlib.util.spec_from_file_location(
        "insight_format", COMPONENT_DIR / "insight_format.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_truncate_markdown_passthrough():
    mod = load_insight_format()
    assert mod.truncate_markdown("short report") == "short report"


def test_truncate_markdown_cuts_on_line_boundary():
    mod = load_insight_format()
    text = "\n".join(f"- finding number {i}" for i in range(2000))
    out = mod.truncate_markdown(text, limit=500)
    assert len(out) < 540
    assert out.endswith("*…truncated*")
    # No partial line before the marker
    body = out.rsplit("\n\n", 1)[0]
    assert body == text[: len(body)]
    assert text[len(body)] == "\n"


def test_build_card_yaml_references_entity():
    mod = load_insight_format()
    yaml_text = mod.build_card_yaml("sensor.morning_briefing_insight", "Morning Briefing")
    assert "type: markdown" in yaml_text
    assert "title: Morning Briefing" in yaml_text
    assert "state_attr('sensor.morning_briefing_insight', 'markdown')" in yaml_text


def test_templates_ship_and_are_substantive():
    mod = load_insight_format()
    expected = {"daily_briefing", "anomaly_watch", "battery_maintenance", "camera_check"}
    assert expected == set(mod.INSIGHT_TEMPLATES)
    for name, prompt in mod.INSIGHT_TEMPLATES.items():
        assert len(prompt) > 200, f"template {name} looks too thin"
    assert "get_camera_snapshot" in mod.INSIGHT_TEMPLATES["camera_check"]
    assert "get_history" in mod.INSIGHT_TEMPLATES["anomaly_watch"]


@pytest.mark.parametrize(
    "filename",
    [p.name for p in sorted(COMPONENT_DIR.glob("*.py"))],
)
def test_integration_modules_compile(filename):
    """Every integration module must at least be syntactically valid."""
    py_compile.compile(str(COMPONENT_DIR / filename), doraise=True)
