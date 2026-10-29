"""The sidebar panel's registration (frontend.async_add_entry_panel and friends).

While an entry set up since Home Assistant started is enabled and has "Show in
the sidebar" on, one panel is in the sidebar for every user. Reloading an
entry keeps it; removing or disabling the entries, or turning the option off,
takes it away. These run against Home Assistant's real panel registry, so
what's asserted is what the sidebar would list.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.components import frontend as ha_frontend
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntryDisabler, ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.loader import async_get_integration
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.bruh_cooking import frontend
from custom_components.bruh_cooking.const import (
    CONF_ALLOW_UNTESTED_CONTROL,
    CONF_SHOW_SIDEBAR_PANEL,
    DOMAIN,
)
from custom_components.bruh_cooking.diagnostics import async_get_config_entry_diagnostics
from custom_components.bruh_cooking.frontend import (
    BUNDLE,
    PANEL_ELEMENT,
    PANEL_ICON,
    PANEL_URL_PATH,
    STATIC_URL,
    async_add_entry_panel,
    async_forget_entry_panel,
    async_remove_entry_panel,
)

from .common import flush

COMPONENT = Path(__file__).parent.parent / "custom_components" / DOMAIN
VERSION = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))["version"]
BUNDLE_TEXT = b"export {};\n"
BUNDLE_HASH = hashlib.sha256(BUNDLE_TEXT).hexdigest()[:8]
MODULE_URL = f"/bruh_cooking/bruh-cooking-panel.js?v={VERSION}-{BUNDLE_HASH}"


@pytest.fixture(autouse=True)
def bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A stand-in bundle, since the real one changes with every build."""
    folder = tmp_path / "frontend"
    folder.mkdir()
    (folder / BUNDLE).write_bytes(BUNDLE_TEXT)
    monkeypatch.setattr(frontend, "FRONTEND_DIR", folder)
    return folder


@pytest.fixture(autouse=True)
async def loaded_integration(hass: HomeAssistant) -> None:
    """Load the integration, as setup does, so the module URL carries its version."""
    await async_get_integration(hass, DOMAIN)


def _entry(hass: HomeAssistant, entry_id: str, brand: str = "breville", **options) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN, entry_id=entry_id, unique_id=entry_id, data={"brand": brand}, options=options
    )
    entry.add_to_hass(hass)
    return entry


def _sidebar(hass: HomeAssistant) -> dict[str, ha_frontend.Panel]:
    """The panels Home Assistant would list, by url path."""
    return dict(hass.data.get(ha_frontend.DATA_PANELS, {}))


async def test_the_panel_is_in_the_sidebar_by_default(hass: HomeAssistant) -> None:
    await async_add_entry_panel(hass, _entry(hass, "a"))

    sidebar = _sidebar(hass)
    assert list(sidebar) == [PANEL_URL_PATH] == ["bruh-cooking"]
    panel = sidebar[PANEL_URL_PATH]
    assert panel.sidebar_title == "BRUH Cooking"
    assert panel.sidebar_icon == PANEL_ICON == "mdi:pot-steam-outline"
    assert panel.component_name == "custom"
    # Every user sees it; only preset changes need an admin.
    assert panel.require_admin is False
    custom = panel.config["_panel_custom"]
    assert custom["name"] == PANEL_ELEMENT == "bruh-cooking-panel"
    # The version and the bundle's hash, so neither a release nor a test build is cached.
    assert custom["module_url"] == MODULE_URL


@pytest.mark.parametrize("brands", [["sage"], ["breville"], ["sage", "breville"]])
async def test_the_title_is_the_add_ons_name_for_every_brand(
    hass: HomeAssistant, brands: list[str]
) -> None:
    for index, brand in enumerate(brands):
        await async_add_entry_panel(hass, _entry(hass, f"e{index}", brand))
    assert _sidebar(hass)[PANEL_URL_PATH].sidebar_title == "BRUH Cooking"
    assert frontend.registered_title(hass) == "BRUH Cooking"


async def test_the_option_turns_the_panel_off_and_on(hass: HomeAssistant) -> None:
    entry = _entry(hass, "a", **{CONF_SHOW_SIDEBAR_PANEL: False})
    await async_add_entry_panel(hass, entry)
    assert _sidebar(hass) == {}

    # Options apply without a reload: the entry's update listener syncs.
    hass.config_entries.async_update_entry(entry, options={})
    frontend.async_entry_changed(hass)
    await hass.async_block_till_done()
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]

    hass.config_entries.async_update_entry(entry, options={CONF_SHOW_SIDEBAR_PANEL: False})
    frontend.async_entry_changed(hass)
    await hass.async_block_till_done()
    assert _sidebar(hass) == {}


async def test_a_reload_keeps_the_panel_in_the_sidebar(hass: HomeAssistant) -> None:
    entry = _entry(hass, "a")
    await async_add_entry_panel(hass, entry)
    url = frontend.panel_module_url(hass)
    panels_updated = async_capture_events(hass, ha_frontend.EVENT_PANELS_UPDATED)
    await async_remove_entry_panel(hass, entry)
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]

    await async_add_entry_panel(hass, entry)
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]
    # Never removed and registered again: the same registration stays.
    assert panels_updated == []
    assert frontend.panel_module_url(hass) == url


async def test_entries_share_one_panel(hass: HomeAssistant) -> None:
    first, second = _entry(hass, "a"), _entry(hass, "b")
    hidden = _entry(hass, "c", **{CONF_SHOW_SIDEBAR_PANEL: False})
    for entry in (second, hidden, first):
        await async_add_entry_panel(hass, entry)
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]
    assert frontend.panel_entries(hass) == [first, second]

    await hass.config_entries.async_remove(first.entry_id)
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]
    assert frontend.panel_entries(hass) == [second]
    # An entry with the option off doesn't keep the panel.
    await hass.config_entries.async_remove(second.entry_id)
    assert _sidebar(hass) == {}
    assert frontend.panel_entries(hass) == []
    # Forgetting an entry again, or one never set up, is harmless.
    await async_forget_entry_panel(hass, second.entry_id)
    await async_forget_entry_panel(hass, "never-set-up")
    assert _sidebar(hass) == {}


def test_the_panel_does_not_sit_under_the_static_path() -> None:
    """A panel at /bruh_cooking would send a page reload to the static file
    handler that serves the bundle, instead of Home Assistant's frontend."""
    assert STATIC_URL == "/bruh_cooking"
    assert f"/{PANEL_URL_PATH}" != STATIC_URL
    assert not f"/{PANEL_URL_PATH}/".startswith(f"{STATIC_URL}/")


async def test_the_files_are_served_once_and_the_bundle_read_once(
    hass: HomeAssistant, bundle: Path
) -> None:
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    first, second = _entry(hass, "a"), _entry(hass, "b")
    with patch.object(frontend, "bundle_hash", wraps=frontend.bundle_hash) as read:
        await async_add_entry_panel(hass, first)
        await async_add_entry_panel(hass, second)
        for entry in (first, second):
            await async_forget_entry_panel(hass, entry.entry_id)
        assert _sidebar(hass) == {}
        await async_add_entry_panel(hass, first)
    hass.http.async_register_static_paths.assert_awaited_once_with(
        [StaticPathConfig("/bruh_cooking", str(bundle), cache_headers=True)]
    )
    read.assert_called_once_with(bundle / BUNDLE)
    assert _sidebar(hass)[PANEL_URL_PATH].config["_panel_custom"]["module_url"] == MODULE_URL


async def test_the_module_url_serves_the_bundle(hass: HomeAssistant, hass_client) -> None:
    assert await async_setup_component(hass, "http", {})
    await async_add_entry_panel(hass, _entry(hass, "a"))
    client = await hass_client()
    response = await client.get(MODULE_URL)
    assert response.status == 200
    assert await response.read() == BUNDLE_TEXT
    # Cached for good, since each build has its own URL.
    assert "max-age" in response.headers["Cache-Control"]


async def test_a_missing_bundle_leaves_the_panel_out(
    hass: HomeAssistant, bundle: Path, caplog: pytest.LogCaptureFixture
) -> None:
    (bundle / BUNDLE).unlink()
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    await async_add_entry_panel(hass, _entry(hass, "a"))
    assert _sidebar(hass) == {}
    hass.http.async_register_static_paths.assert_not_awaited()
    assert "Not showing the BRUH Cooking sidebar panel" in caplog.text
    assert frontend.panel_module_url(hass) is None


async def test_a_registration_failure_is_retried_by_the_next_entry(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    entry = _entry(hass, "a")
    with patch.object(
        frontend.panel_custom, "async_register_panel", side_effect=ValueError("Overwriting panel")
    ):
        await async_add_entry_panel(hass, entry)
    assert _sidebar(hass) == {}
    assert "Could not add the BRUH Cooking panel to the sidebar" in caplog.text
    assert frontend.panel_module_url(hass) is None

    await async_add_entry_panel(hass, entry)
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]


async def test_the_panel_waits_until_its_files_are_served(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    hass.http = MagicMock(async_register_static_paths=AsyncMock(side_effect=[RuntimeError, None]))
    entry = _entry(hass, "a")
    await async_add_entry_panel(hass, entry)
    assert "Could not serve the BRUH Cooking sidebar panel's files" in caplog.text
    # It would only fail to load.
    assert _sidebar(hass) == {}

    await async_add_entry_panel(hass, entry)
    assert hass.http.async_register_static_paths.await_count == 2
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]


# ---- through the integration's own setup -------------------------------------


async def test_setting_up_an_entry_adds_the_panel(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["panel"] == {
        "enabled": True,
        "registered": True,
        "title": "BRUH Cooking",
        "module_url": MODULE_URL,
        "custom_presets": 0,
    }
    assert [a["finish"] for a in diagnostics["appliances"]] == ["white_polished", "brushed_stainless"]

    await hass.config_entries.async_remove(entry.entry_id)
    await hass.async_block_till_done()
    assert _sidebar(hass) == {}


async def test_a_reload_keeps_the_panel(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    panels_updated = async_capture_events(hass, ha_frontend.EVENT_PANELS_UPDATED)
    assert await hass.config_entries.async_reload(entry.entry_id)
    await flush(hass)
    assert entry.state is ConfigEntryState.LOADED
    # Never taken away and added again, which would send anyone looking at it elsewhere.
    assert panels_updated == []
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]


async def test_disabling_the_entry_takes_the_panel_away(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    await hass.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)
    await hass.async_block_till_done()
    assert _sidebar(hass) == {}

    await hass.config_entries.async_set_disabled_by(entry.entry_id, None)
    await flush(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]


async def test_an_entry_retrying_setup_keeps_the_panel_until_disabled(
    hass: HomeAssistant, entry: MockConfigEntry, client: MagicMock
) -> None:
    client.get_appliances.side_effect = TimeoutError
    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.SETUP_RETRY
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]

    # Disabling it now unloads nothing, but it takes the panel away all the same.
    await hass.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)
    await hass.async_block_till_done()
    assert _sidebar(hass) == {}


async def test_configure_turns_the_sidebar_panel_off_and_on(
    hass: HomeAssistant, entry: MockConfigEntry
) -> None:
    async def configure(show: bool | None) -> None:
        result = await hass.config_entries.options.async_init(entry.entry_id)
        user_input: dict = {CONF_ALLOW_UNTESTED_CONTROL: True}
        if show is not None:
            user_input[CONF_SHOW_SIDEBAR_PANEL] = show
        result = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        await hass.async_block_till_done()

    await configure(False)
    assert entry.state is ConfigEntryState.LOADED
    assert entry.options == {CONF_ALLOW_UNTESTED_CONTROL: True, CONF_SHOW_SIDEBAR_PANEL: False}
    assert _sidebar(hass) == {}
    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    assert diagnostics["panel"]["enabled"] is False
    assert diagnostics["panel"]["registered"] is False

    # Left as it was, the option stays off.
    await configure(None)
    assert _sidebar(hass) == {}

    await configure(True)
    assert entry.options == {CONF_ALLOW_UNTESTED_CONTROL: True}
    assert list(_sidebar(hass)) == [PANEL_URL_PATH]


async def test_a_sidebar_failure_never_fails_entry_setup(
    hass: HomeAssistant, entry: MockConfigEntry, caplog: pytest.LogCaptureFixture
) -> None:
    await hass.config_entries.async_set_disabled_by(entry.entry_id, ConfigEntryDisabler.USER)
    await hass.async_block_till_done()
    with patch.object(frontend.panel_custom, "async_register_panel", side_effect=ValueError):
        await hass.config_entries.async_set_disabled_by(entry.entry_id, None)
        await flush(hass)
    assert entry.state is ConfigEntryState.LOADED
    assert _sidebar(hass) == {}
    assert "Could not add the BRUH Cooking panel to the sidebar" in caplog.text
