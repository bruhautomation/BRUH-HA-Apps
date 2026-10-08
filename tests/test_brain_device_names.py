"""Every device the brAIn integration declares is called "brAIn <Word>",
and no two are called the same thing.

A real house's device list read "brAIn System", "brAIn Usage Limits",
"brAIn memory", "brAIn findings", "brAIn House" — two capitalisations of
one naming pattern — and then two devices called just "brAIn": the
conversation agent (named after its config entry, whose default name is
"brAIn") and the add-on's own device, which the Supervisor names after the
add-on. A device picker that shows two identical rows is a picker nobody
can use.

Names may move; identifiers never do (they key every entity an install
already has), so this test also pins the identifiers it saw.

The platform modules import Home Assistant at module level, so the
declarations are read off the source with `ast`, and `const.py` (which has
no imports) is loaded on its own.
"""
from __future__ import annotations

import ast
import importlib.util
import re
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CC = HERE.parent / "brain" / "custom_components" / "brain"

# "brAIn" followed by one or more capitalised words.
PATTERN = re.compile(r"^brAIn( [A-Z][A-Za-z-]*)+$")

# What the Supervisor calls the add-on's own device (config.yaml's name),
# which the integration does not declare but shares a device list with.
ADDON_DEVICE_NAME = "brAIn"

# Every fixed identifier the integration declares, as of this change. A
# rename is free; re-keying one orphans every entity under it.
IDENTIFIERS = {
    "usage_limits", "system_health", "brain_house", "brain_memory",
    "brain_findings",
}


def _const():
    spec = importlib.util.spec_from_file_location(
        "brain_const_device_names", CC / "const.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve(tree: ast.Module, value: ast.AST) -> ast.AST:
    """A module-level name for a DeviceInfo(...) call, resolved to the call."""
    if isinstance(value, ast.Name):
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == value.id):
                return node.value
    return value


def device_infos():
    """(module, identifiers source, name node) for every DeviceInfo call."""
    out = []
    for path in sorted(CC.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "DeviceInfo"):
                continue
            kws = {kw.arg: kw.value for kw in node.keywords}
            out.append((path.name, ast.unparse(kws["identifiers"]),
                        kws.get("name")))
    return out


class TestDeviceNames(unittest.TestCase):

    def test_there_are_device_infos_to_check(self):
        modules = {m for m, _i, _n in device_infos()}
        for module in ("sensor.py", "binary_sensor.py", "button.py",
                       "todo.py", "conversation.py", "ai_task.py"):
            self.assertIn(module, modules)

    def test_every_fixed_name_is_brain_and_a_capitalised_word(self):
        for module, ident, name in device_infos():
            if not isinstance(name, ast.Constant):
                continue
            self.assertRegex(
                name.value, PATTERN,
                f"{module}: device {ident} is called {name.value!r}, not "
                "'brAIn <Word>'")

    def test_no_two_devices_share_a_name(self):
        by_name: dict[str, set] = {}
        for _module, ident, name in device_infos():
            if isinstance(name, ast.Constant):
                by_name.setdefault(name.value, set()).add(ident)
        for name, idents in by_name.items():
            self.assertEqual(len(idents), 1,
                             f"{name!r} names {len(idents)} devices")
        self.assertNotIn(ADDON_DEVICE_NAME, by_name)

    def test_one_identifier_one_name(self):
        by_ident: dict[str, set] = {}
        for _module, ident, name in device_infos():
            if isinstance(name, ast.Constant):
                by_ident.setdefault(ident, set()).add(name.value)
        for ident, names in by_ident.items():
            self.assertEqual(len(names), 1,
                             f"{ident} is declared under {sorted(names)}")

    def test_the_fixed_identifiers_did_not_move(self):
        seen = set()
        for _module, ident, _name in device_infos():
            for found in re.findall(r"\(DOMAIN, '([a-z_]+)'\)", ident):
                seen.add(found)
        self.assertEqual(seen, IDENTIFIERS)

    def test_the_agent_device_is_named_by_agent_device_name(self):
        tree = ast.parse((CC / "conversation.py").read_text())
        calls = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Call)
                 and getattr(node.func, "id", "") == "DeviceInfo"]
        self.assertEqual(len(calls), 1)
        kws = {kw.arg: kw.value for kw in calls[0].keywords}
        self.assertIn("agent_", ast.unparse(kws["identifiers"]))
        self.assertIn("agent_device_name", ast.unparse(kws["name"]))

    def test_an_agent_device_cannot_take_another_devices_name(self):
        const = _const()
        fixed = {name.value for _m, _i, name in device_infos()
                 if isinstance(name, ast.Constant)}
        fixed.add(ADDON_DEVICE_NAME)
        for typed in (const.DEFAULT_NAME, "", "  ", None, "brAIn System",
                      "brAIn Usage Limits", "brAIn Memory", "brAIn House",
                      "brAIn Findings", "Kitchen"):
            got = const.agent_device_name(typed)
            self.assertNotIn(got, fixed, f"{typed!r} -> {got!r}")
        self.assertEqual(const.agent_device_name(const.DEFAULT_NAME),
                         "brAIn Agent")
        self.assertEqual(const.agent_device_name(None), "brAIn Agent")
        self.assertEqual(const.agent_device_name("Kitchen"), "Kitchen Agent")
        # Already says what it is: not "Kitchen agent Agent".
        self.assertEqual(const.agent_device_name("Kitchen agent"),
                         "Kitchen agent")

    def test_the_agent_entity_takes_the_device_name(self):
        """The friendly name stays "brAIn Agent", not "brAIn Agent Agent"."""
        tree = ast.parse((CC / "conversation.py").read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
                   and n.name == "BruhClaudeConversationEntity")
        src = ast.unparse(cls)
        self.assertIn("self._attr_name = None", src)
        # And the unique id stays where every install's registry has it.
        self.assertIn("self._attr_unique_id = "
                      "f'{config_entry.entry_id}_conversation'", src)


if __name__ == "__main__":
    unittest.main()
