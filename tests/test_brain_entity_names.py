"""What the brAIn integration's entities and devices are called in HA.

A walkthrough on a real house found the to-do list named "brAIn System
brAIn" (`todo.brain_system_brain`), the health verdict filed under the
"Usage Limits" device, every device modelled "Claude Terminal", and three
devices all called "brAIn". Names and devices move here; unique ids never
do, because the registry keys an entity's id and its history by them.

And `binary_sensor.brain_memory_waiting_on_you` was `on` while the panel
said nothing was waiting: it read every line still "open" on disk, which
counts a guess somebody dismissed (asleep until `snoozed_until`) and one
past its TTL that the panel has not retired yet. It reads what the panel
reads now — `hypotheses.awake()`.

The platform modules import Home Assistant at module level, so the
declarations are read off the source with `ast` rather than imported.
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import brain_ha_env as env  # noqa: E402

CC = HERE.parent / "brain" / "custom_components" / "brain"


def _class_attrs(module: str, cls: str) -> dict:
    """The class-level assignments of `cls` in `module`, as source text."""
    tree = ast.parse((CC / module).read_text())
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == cls:
            out = {}
            for item in node.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1:
                    target = item.targets[0]
                    if isinstance(target, ast.Name):
                        out[target.id] = item.value
            return out
    raise AssertionError(f"{cls} not in {module}")


def _device_of(module: str, value: ast.AST) -> dict:
    """A DeviceInfo(...) call (or a module-level name for one) as a dict."""
    if isinstance(value, ast.Name):
        tree = ast.parse((CC / module).read_text())
        for node in tree.body:
            if (isinstance(node, ast.Assign)
                    and isinstance(node.targets[0], ast.Name)
                    and node.targets[0].id == value.id):
                value = node.value
                break
    assert isinstance(value, ast.Call), ast.dump(value)
    return {kw.arg: ast.unparse(kw.value) for kw in value.keywords}


class TestNamesAndDevices(unittest.TestCase):

    def test_the_todo_list_is_not_named_after_its_device(self):
        # "brAIn to-do", whole: under the device's name it read "brAIn
        # System brAIn" and then "brAIn System To-do", in an app that
        # lists every list in the house by friendly name.
        attrs = _class_attrs("todo.py", "BrainTodoList")
        self.assertEqual(ast.literal_eval(attrs["_attr_name"]), "brAIn to-do")
        self.assertFalse(ast.literal_eval(attrs["_attr_has_entity_name"]))
        device = _device_of("todo.py", attrs["_attr_device_info"])
        self.assertEqual(device["name"], "'brAIn System'")

    def test_health_lives_on_the_system_device(self):
        attrs = _class_attrs("sensor.py", "BrainHealthSensor")
        device = _device_of("sensor.py", attrs["_attr_device_info"])
        self.assertIn("system_health", device["identifiers"])
        self.assertEqual(device["name"], "'brAIn System'")

    def test_no_device_is_modelled_claude_terminal(self):
        for path in CC.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "DeviceInfo"):
                    for kw in node.keywords:
                        if kw.arg == "model":
                            self.assertNotEqual(
                                ast.unparse(kw.value), "'Claude Terminal'",
                                f"{path.name} still models a device as the "
                                "add-on brAIn replaced")

    def test_fixed_device_names_are_distinct(self):
        """One identifier, one name — and no two identifiers share one."""
        names: dict[str, set] = {}
        for path in CC.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if not (isinstance(node, ast.Call)
                        and getattr(node.func, "id", "") == "DeviceInfo"):
                    continue
                kws = {kw.arg: kw.value for kw in node.keywords}
                name = kws.get("name")
                if not isinstance(name, ast.Constant):
                    continue          # a config entry's own title
                ident = ast.unparse(kws["identifiers"])
                names.setdefault(name.value, set()).add(ident)
        for name, idents in names.items():
            self.assertEqual(len(idents), 1,
                             f"{name!r} names {len(idents)} devices")
        self.assertNotIn("brAIn", names,
                         "a fixed device is called plain 'brAIn', the "
                         "conversation agent's default name")

    def test_unique_ids_did_not_move(self):
        """Renaming is free; re-keying loses an install's history."""
        want = {
            ("todo.py", "BrainTodoList"): "f'{DOMAIN}_work_list'",
            ("sensor.py", "BrainHealthSensor"): "f'{DOMAIN}_health'",
            ("sensor.py", "BrainHouseSensor"): "f'{DOMAIN}_house'",
        }
        for (module, cls), uid in want.items():
            tree = ast.parse((CC / module).read_text())
            src = next(ast.unparse(n) for n in tree.body
                       if isinstance(n, ast.ClassDef) and n.name == cls)
            self.assertIn(f"self._attr_unique_id = {uid}", src, cls)


class FakeConfig:
    def __init__(self, root: str):
        self.root = root

    def path(self, *parts: str) -> str:
        return str(Path(self.root, *parts))


class FakeHass:
    def __init__(self, root: str):
        self.config = FakeConfig(root)


class TestWaitingOnYouCountsWhatThePanelAsks(unittest.TestCase):

    def setUp(self):
        self.pkg = env.load_integration()
        self.learning = self.pkg.learning
        self.tmp = tempfile.TemporaryDirectory()
        self.hass = FakeHass(self.tmp.name)
        path = Path(self.learning.hypotheses_path(self.hass))
        path.parent.mkdir(parents=True, exist_ok=True)
        now = time.time()
        rows = [
            {"ts": int(now - 3600), "text": "Is the dehumidifier on "
             "continuous mode?", "status": "open",
             "snoozed_until": int(now + 86400)},              # dismissed
            {"ts": int(now - 20 * 86400), "text": "Does the garage "
             "door close itself?", "status": "open"},         # aged out
            {"ts": int(now - 60), "text": "Is the hall lamp on a "
             "timer?", "status": "open"},                      # being asked
            {"ts": int(now - 30 * 86400), "text": "Does the oven run on "
             "Sundays?", "status": "open",
             "snoozed_until": int(now - 3600)},               # woke today
            {"ts": int(now - 120), "text": "Settled already",
             "status": "confirmed"},
        ]
        path.write_text("".join(json.dumps(r) + "\n" for r in rows))

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_dismissed_or_aged_out_guess_is_not_waiting(self):
        got = [h["text"] for h in
               self.learning.read_open_hypotheses(self.hass)]
        self.assertEqual(got, ["Is the hall lamp on a timer?",
                               "Does the oven run on Sundays?"])

    def test_answering_by_id_still_reaches_a_sleeping_guess(self):
        got = [h["text"] for h in self.learning.read_open_hypotheses(
            self.hass, awake_only=False)]
        self.assertIn("Is the dehumidifier on continuous mode?", got)
        self.assertNotIn("Settled already", got)

    def test_the_ttl_matches_the_panel(self):
        src = (HERE.parent / "brain" / "panel" / "hypotheses.py").read_text()
        self.assertIn('"BRAIN_HYPOTHESIS_TTL_DAYS", "14"', src)
        self.assertEqual(self.learning.HYPOTHESIS_TTL_DAYS, 14)


if __name__ == "__main__":
    unittest.main()
