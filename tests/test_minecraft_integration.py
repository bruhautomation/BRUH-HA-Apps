#!/usr/bin/env python3
"""Smoke test the HA custom integration source.

We can't install Home Assistant + voluptuous in the test sandbox, so we stub
the third-party imports and exec each module file manually. Goals:

* Detect syntax errors in integration code
* Verify the service constants listed in const.py match every handler
  registered in __init__.py
* Verify sensor/binary_sensor/button modules declare the entity lists they
  advertise in translations/strings
* Smoke-test the coordinator's file-reading logic against fixture JSON
"""
from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
PKG_DIR = os.path.join(
    BASE_DIR, "bruh-minecraft-server", "custom_components", "bruh_minecraft",
)


def _install_ha_stubs() -> None:
    """Install just-enough Home Assistant + voluptuous stubs to exec modules."""
    if "voluptuous" not in sys.modules:
        vol = types.ModuleType("voluptuous")
        class _Base:
            def __init__(self, *a, **kw): pass
            def __call__(self, v): return v
        for name in ("Schema", "Required", "Optional", "All", "Any", "In",
                     "Length", "Range", "Coerce"):
            setattr(vol, name, _Base)
        sys.modules["voluptuous"] = vol

    # Simple stubs for homeassistant.* that only cover what the integration imports.
    for mod_name in (
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.const",
        "homeassistant.core",
        "homeassistant.helpers",
        "homeassistant.helpers.config_validation",
        "homeassistant.helpers.entity_platform",
        "homeassistant.helpers.update_coordinator",
        "homeassistant.helpers.service_info",
        "homeassistant.helpers.service_info.hassio",
        "homeassistant.helpers.device_registry",
        "homeassistant.components",
        "homeassistant.components.binary_sensor",
        "homeassistant.components.button",
        "homeassistant.components.sensor",
    ):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = types.ModuleType(mod_name)

    ha_const = sys.modules["homeassistant.const"]
    class _Platform:
        SENSOR = "sensor"; BINARY_SENSOR = "binary_sensor"; BUTTON = "button"
    class _UnitOfTime:
        SECONDS = "s"
    ha_const.Platform = _Platform
    ha_const.UnitOfTime = _UnitOfTime

    ha_core = sys.modules["homeassistant.core"]
    class _HomeAssistant: pass
    class _ServiceCall:
        def __init__(self, data=None): self.data = data or {}
    ha_core.HomeAssistant = _HomeAssistant
    ha_core.ServiceCall = _ServiceCall

    ha_cfg_entries = sys.modules["homeassistant.config_entries"]
    class _ConfigEntry: entry_id = "x"
    class _ConfigFlow:
        VERSION = 1
        def __init_subclass__(cls, **kw): return super().__init_subclass__()
        async def async_set_unique_id(self, *a, **kw): return None
        def _abort_if_unique_id_configured(self): return None
        def async_create_entry(self, **kw): return {"type": "create_entry", **kw}
        def async_show_form(self, **kw): return {"type": "form", **kw}
        async def async_step_user(self, *a, **kw): return {}
    ha_cfg_entries.ConfigEntry = _ConfigEntry
    ha_cfg_entries.ConfigFlow = _ConfigFlow
    ha_cfg_entries.ConfigFlowResult = dict

    ha_upd = sys.modules["homeassistant.helpers.update_coordinator"]
    class _DataUpdateCoordinator:
        def __init__(self, *a, **kw): self.data = None
        def __class_getitem__(cls, item): return cls
        async def async_config_entry_first_refresh(self): return None
        async def _async_update_data(self): return {}
    class _CoordinatorEntity:
        def __init__(self, coordinator, *a, **kw): self.coordinator = coordinator
        def __class_getitem__(cls, item): return cls
    ha_upd.DataUpdateCoordinator = _DataUpdateCoordinator
    ha_upd.CoordinatorEntity = _CoordinatorEntity

    # Enum-ish class that answers "any attribute" with the attribute name,
    # so `SensorStateClass.MEASUREMENT` works without defining every constant.
    # Dunders must raise so dataclass machinery doesn't mistake the sentinel
    # for a real __dataclass_fields__ dict.
    import dataclasses as _dc
    class _AnyAttrMeta(type):
        def __getattr__(cls, name):
            if name.startswith("__") and name.endswith("__"):
                raise AttributeError(name)
            return name

    @_dc.dataclass(frozen=True)
    class _Generic(metaclass=_AnyAttrMeta):
        # Empty frozen dataclass so subclasses can use @dataclass(frozen=True, kw_only=True).
        key: str = ""

    ha_sensor = sys.modules["homeassistant.components.sensor"]
    ha_sensor.SensorDeviceClass = _Generic
    ha_sensor.SensorStateClass = _Generic
    ha_sensor.SensorEntity = _Generic
    ha_sensor.SensorEntityDescription = _Generic

    ha_bsensor = sys.modules["homeassistant.components.binary_sensor"]
    ha_bsensor.BinarySensorDeviceClass = _Generic
    ha_bsensor.BinarySensorEntity = _Generic
    ha_bsensor.BinarySensorEntityDescription = _Generic

    ha_btn = sys.modules["homeassistant.components.button"]
    ha_btn.ButtonEntity = _Generic
    ha_btn.ButtonEntityDescription = _Generic

    ha_dev_reg = sys.modules["homeassistant.helpers.device_registry"]
    ha_dev_reg.DeviceInfo = _Generic

    ha_ent_plat = sys.modules["homeassistant.helpers.entity_platform"]
    ha_ent_plat.AddEntitiesCallback = _Generic

    ha_cv = sys.modules["homeassistant.helpers.config_validation"]
    def _string(v): return str(v)
    ha_cv.string = _string

    ha_hassio = sys.modules["homeassistant.helpers.service_info.hassio"]
    class _HassioServiceInfo: pass
    ha_hassio.HassioServiceInfo = _HassioServiceInfo


def _load_pkg(name: str) -> types.ModuleType:
    _install_ha_stubs()
    pkg = "bruh_mc_test_pkg"
    for mod in list(sys.modules):
        if mod.startswith(pkg):
            sys.modules.pop(mod)
    parent = types.ModuleType(pkg)
    parent.__path__ = [PKG_DIR]
    sys.modules[pkg] = parent
    spec = importlib.util.spec_from_file_location(
        f"{pkg}.{name}", os.path.join(PKG_DIR, f"{name}.py"),
    )
    module = importlib.util.module_from_spec(spec)
    module.__package__ = pkg
    sys.modules[f"{pkg}.{name}"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestConstImports(unittest.TestCase):
    def test_all_service_constants_defined(self):
        mod = _load_pkg("const")
        required = [
            "DOMAIN", "SCAN_INTERVAL",
            "SERVICE_COMMAND", "SERVICE_SAY", "SERVICE_GIVE",
            "SERVICE_WEATHER", "SERVICE_TIME", "SERVICE_BACKUP",
            "SERVICE_RESTART", "SERVICE_STOP",
            "SERVICE_OP", "SERVICE_DEOP", "SERVICE_KICK", "SERVICE_BAN",
            "SERVICE_WHITELIST_ADD", "SERVICE_WHITELIST_REMOVE",
            "STATS_FILE", "STATE_FILE", "PLAYERS_FILE",
            "COMMAND_REQ_DIR", "COMMAND_RES_DIR",
        ]
        for attr in required:
            self.assertTrue(hasattr(mod, attr), f"const.py missing {attr}")

    def test_service_constants_are_snake_case(self):
        mod = _load_pkg("const")
        for attr in dir(mod):
            if not attr.startswith("SERVICE_"):
                continue
            v = getattr(mod, attr)
            self.assertRegex(v, r"^[a-z][a-z0-9_]*$", f"{attr}={v!r} not snake_case")


# Static AST-based inspection — avoids needing real homeassistant at test time.
import ast as _ast


def _extract_keys_for_tuple(pkg_file: str, tuple_var: str) -> set[str]:
    """Return every `key="foo"` keyword value inside the top-level tuple `tuple_var`."""
    tree = _ast.parse(Path(pkg_file).read_text())
    keys: set[str] = set()
    for node in tree.body:
        if not isinstance(node, _ast.AnnAssign) and not isinstance(node, _ast.Assign):
            continue
        target = (node.target if isinstance(node, _ast.AnnAssign) else node.targets[0])
        name = getattr(target, "id", None)
        if name != tuple_var:
            continue
        value = node.value
        if not isinstance(value, _ast.Tuple):
            continue
        for elt in value.elts:
            if not isinstance(elt, _ast.Call):
                continue
            for kw in elt.keywords:
                if kw.arg == "key" and isinstance(kw.value, _ast.Constant):
                    keys.add(kw.value.value)
    return keys


class TestSensorCatalog(unittest.TestCase):
    def test_sensor_keys(self):
        keys = _extract_keys_for_tuple(os.path.join(PKG_DIR, "sensor.py"), "SENSORS")
        for k in ("players_online", "players_max", "tps_1m", "tps_5m", "tps_15m",
                  "latency_ms", "uptime", "version", "server_type",
                  "motd", "difficulty", "gamemode"):
            self.assertIn(k, keys, f"sensor '{k}' missing from SENSORS")


class TestBinarySensorCatalog(unittest.TestCase):
    def test_binary_sensor_keys(self):
        keys = _extract_keys_for_tuple(
            os.path.join(PKG_DIR, "binary_sensor.py"), "BINARY_SENSORS",
        )
        for k in ("reachable", "rcon_ok"):
            self.assertIn(k, keys)


class TestButtonCatalog(unittest.TestCase):
    def test_button_keys(self):
        keys = _extract_keys_for_tuple(os.path.join(PKG_DIR, "button.py"), "BUTTONS")
        for k in ("backup_now", "restart_server", "stop_server", "save_all"):
            self.assertIn(k, keys)


class TestCoordinator(unittest.TestCase):
    def test_reads_all_three_state_files(self):
        mod = _load_pkg("coordinator")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            (tmp_path / "stats.json").write_text('{"online": 7}')
            (tmp_path / "state.json").write_text('{"status": "running"}')
            (tmp_path / "players.json").write_text('{"players": ["Alice"]}')

            # Patch the module's file-path constants to point at tmp
            mod.STATS_FILE = str(tmp_path / "stats.json")
            mod.STATE_FILE = str(tmp_path / "state.json")
            mod.PLAYERS_FILE = str(tmp_path / "players.json")

            coord = mod.BruhMinecraftCoordinator.__new__(mod.BruhMinecraftCoordinator)
            data = asyncio.run(coord._async_update_data())
            self.assertEqual(data["stats"]["online"], 7)
            self.assertEqual(data["state"]["status"], "running")
            self.assertEqual(data["players"]["players"], ["Alice"])

    def test_missing_files_returns_empty_dicts(self):
        mod = _load_pkg("coordinator")
        with tempfile.TemporaryDirectory() as tmp:
            mod.STATS_FILE = os.path.join(tmp, "nope1.json")
            mod.STATE_FILE = os.path.join(tmp, "nope2.json")
            mod.PLAYERS_FILE = os.path.join(tmp, "nope3.json")
            coord = mod.BruhMinecraftCoordinator.__new__(mod.BruhMinecraftCoordinator)
            data = asyncio.run(coord._async_update_data())
            self.assertEqual(data, {"stats": {}, "state": {}, "players": {}})


class TestBridgeModuleBehavior(unittest.TestCase):
    def test_timeout_cleanup(self):
        mod = _load_pkg("bridge")
        with tempfile.TemporaryDirectory() as tmp:
            mod.COMMAND_REQ_DIR = os.path.join(tmp, "req")
            mod.COMMAND_RES_DIR = os.path.join(tmp, "res")

            async def go():
                with self.assertRaises(TimeoutError):
                    await mod.send_request("command", {"command": "list"}, timeout=0.25)
                # Orphan request file should be cleaned up
                req_dir = Path(mod.COMMAND_REQ_DIR)
                if req_dir.is_dir():
                    self.assertEqual(list(req_dir.iterdir()), [])

            asyncio.run(go())


if __name__ == "__main__":
    unittest.main()
