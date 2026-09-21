#!/usr/bin/env python3
"""`brain.run_task`'s per-call tool scoping, driven end to end.

A task runs in /config with `/config/.claude/settings.local.json` behind
it, which grants Bash, Write, Edit, WebFetch, WebSearch and every MCP
tool — and until the `tools` field existed, every call got all of it
whatever it was asked to do. An automation that wanted a question answered
handed a model the same grant as one that wanted a config rewritten, and
the automation had no way to say so.

Three things are pinned here, and the first is the one that matters most:

  * `full` is the default and produces the argv that shipped, byte for
    byte — BRight's director drives the same tasks folder and depends on
    that grant;
  * `house` and `read_only` are DERIVED from `engine.ANALYST_TOOLS` /
    `ANALYST_DENIED` rather than copied, the way brain-learn.sh derives a
    study session's scope, so a new acting tool cannot quietly reach one;
  * a scoping that cannot be read REFUSES, and the refusal is answered
    rather than dropped — the bridge is already polling for a result file.

The shell is lifted out of the real listener and run, because the flags it
builds are the only thing standing between an unattended task and a shell.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
PANEL_DIR = ADDON_DIR / "panel"
INTEGRATION_DIR = ADDON_DIR / "custom_components" / "brain"
LISTENER = ADDON_DIR / "integrations" / "automation-listener.sh"

sys.path.insert(0, str(PANEL_DIR))

import engine  # noqa: E402


def lift(name: str) -> str:
    """The named function, out of the real listener."""
    src = LISTENER.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", src, re.S | re.M)
    assert match, f"automation-listener.sh no longer defines {name}"
    return match.group(0)


def flags_for(mode: str, panel_dir: Path | str | None = PANEL_DIR):
    """Drive `task_tool_flags` and hand back (rc, argv-as-list)."""
    harness = lift("task_tool_flags") + f'\ntask_tool_flags "{mode}"\n'
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    if panel_dir is not None:
        env["BRAIN_PANEL_DIR"] = str(panel_dir)
    result = subprocess.run(
        ["bash", "-c", harness], capture_output=True, text=True,
        check=False, env=env,
    )
    out = [line for line in result.stdout.splitlines() if line != ""]
    return result.returncode, out


class TestFullIsTheDefaultAndDoesNotChange(unittest.TestCase):
    """The rule the other two are added under."""

    def test_full_passes_no_tool_flags_at_all(self):
        rc, flags = flags_for("full")
        self.assertEqual(rc, 0)
        self.assertEqual(flags, [])

    def test_a_task_with_no_tools_key_is_full(self):
        """BRight's director writes the task file itself and has never
        written this key. An absent field must read as today's behaviour."""
        rc, flags = flags_for("")
        self.assertEqual(rc, 0)
        self.assertEqual(flags, [])

    def test_full_does_not_need_the_panel(self):
        """The default may not acquire a new way to fail."""
        rc, flags = flags_for("full", panel_dir="/nonexistent")
        self.assertEqual(rc, 0)
        self.assertEqual(flags, [])


class TestTheNarrowerScopes(unittest.TestCase):

    def _pairs(self, mode):
        rc, flags = flags_for(mode)
        self.assertEqual(rc, 0, f"{mode} was refused")
        self.assertEqual(flags[0], "--allowedTools")
        self.assertEqual(flags[2], "--disallowedTools")
        return flags[1].split(","), flags[3].split(",")

    def test_read_only_is_the_analysts_own_pair(self):
        allow, deny = self._pairs("read_only")
        self.assertEqual(allow, list(engine.ANALYST_TOOLS))
        self.assertEqual(deny, list(engine.ANALYST_DENIED))

    def test_read_only_cannot_reach_a_shell_or_a_file(self):
        allow, deny = self._pairs("read_only")
        for tool in ("Bash", "Write", "Edit", "WebFetch", "WebSearch"):
            self.assertIn(tool, deny)
            self.assertNotIn(tool, allow)

    def test_read_only_cannot_act_on_the_house(self):
        allow, deny = self._pairs("read_only")
        for tool in ("call_service", "control_lock", "control_light",
                     "fire_event", "run_script", "activate_scene"):
            self.assertIn(f"{engine.MCP}{tool}", deny)
            self.assertNotIn(f"{engine.MCP}{tool}", allow)

    def test_house_keeps_every_home_assistant_tool(self):
        """Every tool the MCP server registers is in exactly one of the two
        analyst lists, which is what makes their union the whole set."""
        allow, _ = self._pairs("house")
        registered = {t for t in list(engine.ANALYST_TOOLS)
                      + list(engine.ANALYST_DENIED)
                      if t.startswith(engine.MCP)}
        self.assertEqual(set(allow), registered)
        self.assertIn(f"{engine.MCP}call_service", allow)
        self.assertIn(f"{engine.MCP}control_light", allow)

    def test_house_drops_the_shell_the_files_and_the_web(self):
        allow, deny = self._pairs("house")
        for tool in ("Bash", "Write", "Edit", "NotebookEdit",
                     "WebFetch", "WebSearch"):
            self.assertIn(tool, deny)
            self.assertNotIn(tool, allow)

    def test_house_denies_nothing_it_also_allows(self):
        allow, deny = self._pairs("house")
        self.assertEqual(set(allow) & set(deny), set())

    def test_neither_list_is_ever_empty(self):
        for mode in ("house", "read_only"):
            allow, deny = self._pairs(mode)
            self.assertTrue(allow)
            self.assertTrue(deny)

    def test_the_lists_are_read_and_not_copied(self):
        """A second copy of 'what may an unattended run touch' is the drift
        that lets an acting tool reach one of them — so the listener holds
        no tool names of its own beyond the six non-MCP denials."""
        src = LISTENER.read_text(encoding="utf-8")
        code = "\n".join(line for line in src.splitlines()
                         if not line.lstrip().startswith("#"))
        self.assertNotIn(engine.MCP, code)
        self.assertIn("engine.ANALYST_TOOLS", code)
        self.assertIn("engine.ANALYST_DENIED", code)


class TestAScopingThatCannotBeReadRefuses(unittest.TestCase):

    def test_an_unreadable_panel_refuses_rather_than_widening(self):
        for mode in ("house", "read_only"):
            rc, flags = flags_for(mode, panel_dir="/nonexistent")
            self.assertNotEqual(rc, 0, mode)
            self.assertEqual(flags, [], mode)

    def test_an_emptied_list_refuses_rather_than_widening(self):
        """An engine.py whose lists are empty is not an engine.py that
        permits everything."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        Path(tmp, "engine.py").write_text(
            "ANALYST_TOOLS = []\nANALYST_DENIED = []\n", encoding="utf-8")
        for mode in ("house", "read_only"):
            rc, _ = flags_for(mode, panel_dir=tmp)
            self.assertNotEqual(rc, 0, mode)

    def test_a_word_nobody_defined_refuses(self):
        for mode in ("readonly", "none", "all", "Full", "house "):
            rc, flags = flags_for(mode)
            self.assertNotEqual(rc, 0, mode)
            self.assertEqual(flags, [], mode)


class TestTheListenerCarriesTheFlagsToEveryInvocation(unittest.TestCase):
    """A run, its landing and its post-cleanup retry are one task: a scope
    that reached only the first would be widened by a retry."""

    def setUp(self):
        self.src = LISTENER.read_text(encoding="utf-8")
        self.calls = [line for line in self.src.splitlines()
                      if "${CLAUDE_BIN}" in line and "-p " in line]

    def test_every_claude_invocation_takes_them(self):
        self.assertGreaterEqual(len(self.calls), 3)
        for line in self.calls:
            self.assertIn('"${tool_flags[@]}"', line, line.strip())

    def test_the_field_is_read_off_the_task_file(self):
        self.assertIn("""task_tools=$(jq -r '.tools // empty'""", self.src)

    def test_a_refusal_writes_a_result_the_bridge_can_read(self):
        """A dropped task is a service call that times out with nothing to
        read, which is the one ending with no way back."""
        self.assertIn("write_task_result", self.src)
        refusal = self.src.split("if ! tool_flags_out=", 1)[1][:800]
        self.assertIn("write_task_result", refusal)
        self.assertIn("return", refusal)


class TestTheServiceAcceptsIt(unittest.TestCase):

    def test_the_schema_defaults_to_full(self):
        source = (INTEGRATION_DIR / "__init__.py").read_text(encoding="utf-8")
        self.assertIn('vol.Optional("tools", default=DEFAULT_TASK_TOOLS)',
                      source)
        self.assertIn('DEFAULT_TASK_TOOLS = "full"', source)
        self.assertIn('TASK_TOOLS = ("full", "house", "read_only")', source)

    def test_the_handler_passes_it_to_the_bridge(self):
        source = (INTEGRATION_DIR / "__init__.py").read_text(encoding="utf-8")
        handler = source.split("async def handle_run_task", 1)[1][:900]
        self.assertIn('call.data.get("tools"', handler)
        self.assertIn("tools=tools", handler)

    def test_the_documented_values_are_the_accepted_values(self):
        catalog = yaml.safe_load(
            (INTEGRATION_DIR / "services.yaml").read_text(encoding="utf-8"))
        field = catalog["run_task"]["fields"]["tools"]
        self.assertEqual(field["default"], "full")
        self.assertEqual(field["selector"]["select"]["options"],
                         ["full", "house", "read_only"])

    def test_the_field_is_in_strings_and_the_translation(self):
        for name in ("strings.json", "translations/en.json"):
            data = json.loads(
                (INTEGRATION_DIR / name).read_text(encoding="utf-8"))
            fields = data["services"]["run_task"]["fields"]
            self.assertIn("tools", fields, name)
            self.assertIn("name", fields["tools"], name)
            self.assertIn("description", fields["tools"], name)

    def test_it_is_documented(self):
        docs = (ADDON_DIR / "DOCS.md").read_text(encoding="utf-8")
        for word in ("read_only", "house", "`tools`"):
            self.assertIn(word, docs)


class TestTheBridgeWritesIt(unittest.TestCase):
    """The task file is the wire between two processes that cannot import
    each other, so the shape is driven rather than written down twice."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _task(self, **kw) -> dict:
        """What `async_send_task` would put on disk, minus the async."""
        source = (INTEGRATION_DIR / "bridge.py").read_text(encoding="utf-8")
        body = source.split("async def async_send_task", 1)[1]
        body = body.split("task_file = os.path.join", 1)[0]
        # the dict literal and the two conditional keys, run as-is
        start = body.index("task = {")
        snippet = body[start:]
        scope = {
            "task_id": "abc", "prompt": "p", "notify": False,
            "time": __import__("time"),
            "timeout": 300, "notify_entity": None,
            "model": None, "tools": None, "schema": None,
        }
        scope.update(kw)
        exec(compile(snippet.replace("\n        ", "\n"), "<bridge>", "exec"),
             {}, scope)
        return scope["task"]

    def test_the_default_puts_the_same_json_on_disk_it_always_did(self):
        self.assertNotIn("tools", self._task(tools="full"))
        self.assertNotIn("tools", self._task(tools=None))

    def test_a_narrower_scope_rides_in_the_file(self):
        self.assertEqual(self._task(tools="read_only")["tools"], "read_only")
        self.assertEqual(self._task(tools="house")["tools"], "house")

    def test_a_schema_rides_in_the_file_and_nothing_else_does(self):
        """`brain.ask`'s shape: an object goes on the task, anything that
        is not one is left off — the listener reads a missing key as a run
        with no `--json-schema`, which is what every task before it was."""
        shape = {"type": "object", "properties": {"rooms": {"type": "array"}}}
        self.assertEqual(self._task(schema=shape)["schema"], shape)
        self.assertNotIn("schema", self._task(schema=None))
        self.assertNotIn("schema", self._task(schema={}))
        self.assertNotIn("schema", self._task(schema="not a dict"))


class TestTheListenerAsksForTheShape(unittest.TestCase):
    """The schema reaches the CLI as `--json-schema`, and the validated
    object reaches the result file as `data` beside the text — driven out
    of the real listener's own functions, because the flag and the field
    are the wire between two processes that cannot import each other."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _run(self, script: str, env: dict | None = None):
        return subprocess.run(["bash", "-c", script], capture_output=True,
                              text=True, check=False,
                              env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                                   **(env or {})})

    def test_the_result_file_carries_the_validated_object(self):
        envelope = Path(self.tmp) / "out.json"
        envelope.write_text(json.dumps({
            "result": "Two rooms are cold.",
            "structured_output": {"rooms": ["Hall", "Study"]},
            "session_id": "abc"}), encoding="utf-8")
        script = (lift("write_task_result") + "\n" + lift("extract_claude_result")
                  + "\n" + lift("extract_claude_data")
                  + f'\nRESULTS_DIR="{self.tmp}"\n'
                  + f'text=$(extract_claude_result "{envelope}")\n'
                  + f'data=$(extract_claude_data "{envelope}")\n'
                  + 'write_task_result t1 "$text" "$data"\n')
        out = self._run(script)
        self.assertEqual(out.returncode, 0, out.stderr)
        written = json.loads((Path(self.tmp) / "t1.json").read_text())
        self.assertEqual(written["result"], "Two rooms are cold.")
        self.assertEqual(written["data"], {"rooms": ["Hall", "Study"]})
        self.assertEqual(written["status"], "completed")

    def test_a_run_with_no_object_writes_the_file_it_always_did(self):
        envelope = Path(self.tmp) / "out.json"
        envelope.write_text(json.dumps({"result": "plain text"}), encoding="utf-8")
        script = (lift("write_task_result") + "\n" + lift("extract_claude_result")
                  + "\n" + lift("extract_claude_data")
                  + f'\nRESULTS_DIR="{self.tmp}"\n'
                  + f'text=$(extract_claude_result "{envelope}")\n'
                  + f'data=$(extract_claude_data "{envelope}")\n'
                  + 'write_task_result t2 "$text" "$data"\n')
        out = self._run(script)
        self.assertEqual(out.returncode, 0, out.stderr)
        written = json.loads((Path(self.tmp) / "t2.json").read_text())
        self.assertEqual(set(written), {"id", "result", "status"})

    def test_the_schema_flag_is_only_passed_when_a_task_carries_one(self):
        src = LISTENER.read_text(encoding="utf-8")
        self.assertIn('schema_flags=(--json-schema "$task_schema")', src)
        self.assertIn('if [ -n "$task_schema" ]; then', src)
        # Every claude invocation the listener makes carries the array,
        # which is empty for a task with no schema.
        runs = [line for line in src.splitlines()
                if "${CLAUDE_BIN} -p --output-format json" in line]
        self.assertGreaterEqual(len(runs), 3)
        for line in runs:
            self.assertIn('"${schema_flags[@]}"', line)


if __name__ == "__main__":
    unittest.main()
