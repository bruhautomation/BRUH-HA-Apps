"""How the panel draws each appliance (panel_spec) and the built-in presets (presets)."""

from __future__ import annotations

import pytest

from custom_components.bruh_cooking.appliance import (
    MODELS,
    OVEN_MODES,
    TASK_ENGINE_MODES,
    CookSettings,
    Kind,
    default_settings,
)
from custom_components.bruh_cooking.panel_spec import (
    OVEN_DRAWING,
    detect_finish,
    oven_mode_table,
)
from custom_components.bruh_cooking.presets import (
    BUILTIN_PRESETS,
    NOTE_RAW_SAFE_FISH,
    SEAFOOD_SAFE_C,
    Preset,
    PresetError,
    applied_settings,
    check_settings,
    clean_name,
    preset_fits,
    read_custom,
    settings_preset,
    short_enough,
)

SEAFOOD = {"salmon", "white_fish", "shrimp"}


@pytest.mark.parametrize(
    ("model", "item", "serial", "finish"),
    [
        ("CSJ100", "CS10001", "J123456", "white_polished"),
        ("BSV600", "BSV600PSS1BNA1", None, "white_polished"),
        ("BOV950", "BOV950BSS1BUS1", None, "brushed_stainless"),
        ("BOV950", "BOV950BST1BUS1", None, "black_stainless"),
        ("BOV950", "bov950bst", None, "black_stainless"),
        # The item number wins over the serial number.
        ("BOV950", "BOV950BSS1BUS1", "AB1UH01A123456789", "brushed_stainless"),
        # Else the serial number's fifth character: H is black stainless, A stainless.
        ("BOV950", None, "AB1UH01A123456789", "black_stainless"),
        ("BOV950", "", "AB1UA01A123456789", "brushed_stainless"),
        # A colour without a drawing, or a serial in another format.
        ("BOV950", None, "AB1UB01A123456789", "brushed_stainless"),
        ("BOV950", None, "A950123456", "brushed_stainless"),
        ("BOV950", None, None, "brushed_stainless"),
    ],
)
def test_the_finish_is_detected(model: str, item: str | None, serial: str | None, finish: str) -> None:
    assert detect_finish(model, item, serial) == finish


def test_the_mode_table_follows_the_oven_modes() -> None:
    table = {mode["id"]: mode for mode in oven_mode_table()}
    assert list(table)[: len(OVEN_MODES)] == list(OVEN_MODES)
    for option, mode in OVEN_MODES.items():
        entry = table[option]
        assert entry["remote"] is True
        assert entry["type"] == mode.type.value
        assert entry["preheat"] == mode.preheat
        assert entry["convection"] == list(mode.convection_allowed)
        assert entry["frozen"] == mode.frozen_default
        assert entry["keep_warm"] == mode.keep_warm_allowed
        assert entry["default_seconds"] == mode.default_seconds()
        if mode.rack is not None:
            assert entry["rack"] == mode.rack
        if mode.temp:
            assert entry["temperature_c"] == {
                "default": mode.temp[0], "min": mode.temp[1], "max": mode.temp[2], "step": mode.round_to
            }
        else:
            assert entry["temperature_c"] is None
            assert entry["default_level"] in entry["levels"]
    # Modes that can only be started on the oven are drawn too.
    for option in ("toast", "bagel", "keep_warm", "crispy_reheat"):
        assert table[option]["remote"] is False
        assert option in TASK_ENGINE_MODES.values()
    # Every mode the oven reports has a drawing, and nothing else does.
    oven_modes = {o for o in TASK_ENGINE_MODES.values() if o not in ("sous_vide", "turbo")}
    assert set(table) == oven_modes == set(OVEN_DRAWING)
    for entry in table.values():
        assert 1 <= entry["rack"] <= 8


@pytest.mark.parametrize("preset", BUILTIN_PRESETS, ids=lambda preset: preset.id)
def test_each_builtin_preset_passes_the_checks(preset: Preset) -> None:
    check_settings(preset.kind, preset.settings)
    assert short_enough(preset)
    assert any(preset_fits(preset, model) for model in MODELS)
    if preset.kind is Kind.OVEN and preset.settings.get("temperature_f") is not None:
        # Both units round, and say the same within the oven's 5 °C steps.
        celsius, fahrenheit = preset.settings["temperature_c"], preset.settings["temperature_f"]
        assert isinstance(celsius, int) and isinstance(fahrenheit, int)
        assert abs((fahrenheit - 32) * 5 / 9 - celsius) < 2.5
    if preset.kind is Kind.SOUS_VIDE:
        seafood = preset.id in SEAFOOD
        raw_safe = preset.settings["temperature_c"] < SEAFOOD_SAFE_C and seafood
        assert (preset.note == NOTE_RAW_SAFE_FISH) is raw_safe


def test_presets_fit_their_kind_and_limits() -> None:
    by_id = {preset.id: preset for preset in BUILTIN_PRESETS}
    assert preset_fits(by_id["vegetables"], "CSJ100")
    assert preset_fits(by_id["vegetables"], "BSV600")
    assert not preset_fits(by_id["vegetables"], "BOV950")
    assert not preset_fits(by_id["cake"], "CSJ100")
    hot = Preset("hot", Kind.SOUS_VIDE, {"temperature_c": 95, "duration_s": 3600}, name="Hot")
    assert preset_fits(hot, "CSJ100") and not preset_fits(hot, "BSV600")


def test_an_oven_preset_starts_from_the_modes_defaults() -> None:
    current = CookSettings(temperature_c=100, mode="bake", auto_start_timer=True, keep_warm=True, frozen=True)
    by_id = {preset.id: preset for preset in BUILTIN_PRESETS}
    fries = applied_settings(by_id["frozen_fries"], "BOV950", current, fahrenheit=True)
    assert (fries.mode, round(fries.temperature_c, 2), fries.duration_s) == ("air_fry", 204.44, 1200)
    assert (fries.convection, fries.frozen, fries.auto_start_timer, fries.keep_warm) == ("super", None, True, True)
    cake = applied_settings(by_id["cake"], "BOV950", current, fahrenheit=False)
    assert (cake.temperature_c, cake.convection) == (175, "on")
    pot_roast = applied_settings(by_id["pot_roast"], "BOV950", current, fahrenheit=False)
    assert (pot_roast.level, pot_roast.duration_s) == (1, 8 * 3600)
    with pytest.raises(PresetError):
        applied_settings(by_id["cake"], "CSJ100", current, fahrenheit=False)


def test_a_sous_vide_preset_keeps_the_timer_choice() -> None:
    current = CookSettings(temperature_c=60, duration_s=None, auto_start_timer=True)
    rare = next(preset for preset in BUILTIN_PRESETS if preset.id == "steak_rare")
    settings = applied_settings(rare, "CSJ100", current, fahrenheit=True)
    assert (settings.temperature_c, settings.duration_s, settings.auto_start_timer) == (52, 5400, True)


@pytest.mark.parametrize(
    ("kind", "settings"),
    [
        (Kind.SOUS_VIDE, {"duration_s": 60}),
        (Kind.SOUS_VIDE, {"temperature_c": 10, "duration_s": 60}),
        (Kind.SOUS_VIDE, {"temperature_c": 60, "duration_s": -1}),
        (Kind.SOUS_VIDE, {"temperature_c": 60, "duration_s": 1.5}),
        (Kind.SOUS_VIDE, {"temperature_c": 60, "duration_s": 100 * 3600}),
        (Kind.OVEN, {"mode": "toast", "duration_s": 600}),
        (Kind.OVEN, {"mode": "bake", "duration_s": 600}),
        (Kind.OVEN, {"mode": "bake", "temperature_c": 300, "duration_s": 600}),
        (Kind.OVEN, {"mode": "bake", "temperature_c": 250, "duration_s": 5 * 3600}),
        (Kind.OVEN, {"mode": "broil", "level": "max", "duration_s": 600}),
        (Kind.OVEN, {"mode": "air_fry", "temperature_c": 200, "duration_s": 600, "convection": "off"}),
        (Kind.OVEN, {"mode": "bake", "temperature_c": 200, "duration_s": 600, "frozen": True}),
    ],
)
def test_invalid_settings_are_refused(kind: Kind, settings: dict) -> None:
    with pytest.raises(PresetError):
        check_settings(kind, settings)


def test_custom_presets_need_not_follow_the_safety_rule() -> None:
    """They're up to the admins who save them; only the limits apply."""
    check_settings(Kind.SOUS_VIDE, {"temperature_c": 52, "duration_s": 0})


def test_current_settings_make_a_preset() -> None:
    assert settings_preset("CSJ100", CookSettings(temperature_c=57.5)) == {
        "temperature_c": 57.5, "duration_s": 0
    }
    oven = default_settings("BOV950")
    assert settings_preset("BOV950", oven) == {
        "mode": "bake", "duration_s": 1800, "temperature_c": 165.0, "convection": "on"
    }
    broil = CookSettings(mode="broil", level=2, duration_s=300, convection="off")
    assert settings_preset("BOV950", broil) == {
        "mode": "broil", "duration_s": 300, "level": "medium", "convection": "off"
    }
    pizza = CookSettings(mode="pizza", temperature_c=230, duration_s=600, frozen=False)
    assert settings_preset("BOV950", pizza)["frozen"] is False


def test_names_are_trimmed_and_limited() -> None:
    assert clean_name("  Sunday \n roast ") == "Sunday roast"
    assert clean_name("x" * 40) == "x" * 40
    for bad in ("", "   ", None, 5, "x" * 41):
        with pytest.raises(PresetError):
            clean_name(bad)


def test_bad_stored_presets_are_skipped() -> None:
    assert read_custom(None) == []
    assert read_custom({"presets": "nope"}) == []
    good = {"id": "a", "kind": "sous_vide", "name": "Mine", "settings": {"temperature_c": 60, "duration_s": 0}}
    presets = read_custom({"presets": [good, {"id": "b"}, {**good, "kind": "grill"}, 3]})
    assert [preset.id for preset in presets] == ["a"]
    assert read_custom({"presets": [good] * 60}) == presets * 50
