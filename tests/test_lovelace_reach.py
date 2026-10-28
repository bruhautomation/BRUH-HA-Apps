#!/usr/bin/env python3
"""brAIn edits Lovelace dashboards from every face that may act.

The owner asked brAIn to change a Lovelace dashboard and was told it
"can't change config". The tools were there all along — `get_dashboard`
and `list_dashboards` read, `brain.update_dashboard` (backed up first,
`dry_run`, `take_control` for a never-saved default) and
`brain.restore_dashboard` write through `call_service` — so what refused
was the words around them: Morph's Ask bar told the house's agent "You
cannot change the dashboard", a Tell was told a dashboard is "never a
Lovelace dashboard", a whole-house voice agent was told it "cannot edit
files: for a change to ... configuration, say it needs the brAIn chat",
and nothing outside the terminal's CLAUDE.md said which service a
dashboard change is.

Two halves here. The first enumerates every surface's own tool lists —
the files run.sh writes, the engine's lists, a task's `house` scope, the
MCP server's tool list — and asks each one for the dashboard tools,
including where a surface is deliberately read-only (an unattended run)
or narrower (a voice-level agent), so a deliberate block reads as one.
The second holds the words: nothing a run is told says a Lovelace
dashboard cannot be changed.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON = BASE_DIR / "brain"
PANEL = ADDON / "panel"
sys.path.insert(0, str(PANEL))
sys.path.insert(0, str(ADDON / "ha-mcp-server"))
sys.path.insert(0, str(ADDON / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import engine  # noqa: E402
import ha_mcp_server as m  # noqa: E402
from test_security import _heredoc  # noqa: E402
from test_task_tool_scope import flags_for  # noqa: E402

MCP = "mcp__home-assistant__"
READS = ("list_dashboards", "get_dashboard")
# Every dashboard write the integration has, each a brain.* Power Tool
# reached through call_service.
WRITES = ("update_dashboard", "restore_dashboard", "reset_dashboard_config",
          "create_dashboard", "delete_dashboard", "add_dashboard_resource",
          "remove_dashboard_resource")
FRONTEND = ADDON / "custom_components" / "brain" / "morph" / "frontend"


def _run_sh_files() -> dict:
    run_sh = (ADDON / "run.sh").read_text()
    return {
        "chat+terminal": json.loads(_heredoc(
            run_sh, 'settings.local.json" << \'SETTINGS\'', "SETTINGS")),
        "headless": json.loads(_heredoc(
            run_sh, "headless_settings.json\" << 'HEADLESS'", "HEADLESS")),
        "voice-house": json.loads(_heredoc(
            run_sh, "assist_settings.json << 'SCOPE'", "SCOPE")),
    }


def _allows(rules, tool: str) -> bool:
    for rule in rules:
        if rule == tool or (rule.endswith("*") and tool.startswith(rule[:-1])):
            return True
    return False


def _gate_hook(doc) -> bool:
    for block in (doc.get("hooks") or {}).get("PreToolUse") or []:
        if re.fullmatch(block["matcher"], f"{MCP}call_service") and any(
                "brain-action-gate.py" in h["command"] for h in block["hooks"]):
            return True
    return False


class TestTheIntegrationHasEveryDashboardWrite(unittest.TestCase):

    def test_each_write_is_a_brain_service(self):
        services = yaml.safe_load(
            (ADDON / "custom_components" / "brain" / "services.yaml").read_text())
        for name in WRITES:
            self.assertIn(name, services, name)

    def test_the_mcp_server_lists_the_reads_and_the_route_to_the_writes(self):
        names = {t["name"] for t in m.TOOLS}
        for name in READS + ("call_service",):
            self.assertIn(name, names)
            self.assertIn(name, m.TOOL_IMPLEMENTATIONS)


class TestEverySurfaceReachesTheDashboards(unittest.TestCase):
    """One row per face, read off that face's own lists."""

    @classmethod
    def setUpClass(cls):
        cls.files = _run_sh_files()

    def test_chat_and_terminal_read_unasked_and_write_through_the_gate(self):
        """The project file pre-approves the analyst's reads (run.sh fills
        it from ANALYST_TOOLS) and denies nothing of the dashboards', so a
        write is asked on the approval card — or not at all under YOLO /
        "act without asking" — exactly as any other house write."""
        doc = self.files["chat+terminal"]
        filled = list(engine.ANALYST_TOOLS) + [f"{MCP}offer_resolutions"]
        for name in READS:
            self.assertIn(f"{MCP}{name}", filled, name)
        for tool in (f"{MCP}{n}" for n in READS + ("call_service",)):
            self.assertFalse(_allows(doc["permissions"]["deny"], tool), tool)
        self.assertNotIn(f"{MCP}call_service", filled,
                         "a write must be asked, not pre-approved")
        self.assertTrue(_gate_hook(doc))

    def test_unattended_acting_runs_have_them(self):
        """`run_agent` (Fix it, a reply with the switch on), a `full`
        task (brain.ask, Morph's Tell and Ask) and a full-admin agent."""
        doc = self.files["headless"]
        for tool in (f"{MCP}{n}" for n in READS + ("call_service",)):
            self.assertTrue(_allows(doc["permissions"]["allow"], tool), tool)
            self.assertFalse(_allows(doc["permissions"]["deny"], tool), tool)
        self.assertTrue(_gate_hook(doc))
        rc, flags = flags_for("full")
        self.assertEqual((rc, flags), (0, []), "a full task is not narrowed")

    def test_a_house_task_has_them(self):
        rc, flags = flags_for("house")
        self.assertEqual(rc, 0)
        allow = flags[flags.index("--allowedTools") + 1].split(",")
        deny = flags[flags.index("--disallowedTools") + 1].split(",")
        for tool in (f"{MCP}{n}" for n in READS + ("call_service",)):
            self.assertIn(tool, allow, tool)
            self.assertNotIn(tool, deny, tool)

    def test_a_whole_house_voice_agent_has_them(self):
        doc = self.files["voice-house"]
        for tool in (f"{MCP}{n}" for n in READS + ("call_service",)):
            self.assertTrue(_allows(doc["permissions"]["allow"], tool), tool)
            self.assertFalse(_allows(doc["permissions"]["deny"], tool), tool)

    def test_read_only_runs_read_them_and_write_nothing_by_design(self):
        """Cards, the Resident, a read_only task and a reply with the
        switch off: reading the dashboard yes, writing anything no."""
        for name in READS:
            self.assertIn(f"{MCP}{name}", engine.ANALYST_TOOLS)
        self.assertIn(f"{MCP}call_service", engine.ANALYST_DENIED)

    def test_a_voice_level_agent_is_refused_by_design_and_says_so(self):
        """Deliberate: the voice level reaches exposed entities only, and
        a dashboard is the whole house. The refusal names the remedy."""
        for name in READS:
            self.assertIn(name, m.VOICE_REFUSED_TOOLS)
        saved = m.EXPOSED_ONLY
        self.addCleanup(setattr, m, "EXPOSED_ONLY", saved)
        m.EXPOSED_ONLY = True
        why = m._voice_service_refusal(
            "brain", "update_dashboard", {"url_path": "default", "config": {}})
        self.assertTrue(why)


class TestTheWritePassesTheChokepoint(unittest.TestCase):
    """What reaches Core from a chat or a whole-house agent."""

    def setUp(self):
        saved = {k: getattr(m, k) for k in ("DENIED_SERVICES", "PROTECTED_ENTITIES",
                                            "EXPOSED_ONLY")}
        self.addCleanup(lambda: [setattr(m, k, v) for k, v in saved.items()])
        m.DENIED_SERVICES, m.PROTECTED_ENTITIES, m.EXPOSED_ONLY = [], [], False
        self.calls = []

        def core(payload, timeout=15):
            self.calls.append(payload)
            return {"response": {"backup": "lovelace.bak.1"}}
        for p in (patch.object(m, "_ws_command", core),
                  patch.object(m, "record_action", lambda *a, **k: None),
                  patch.object(m, "yolo_mode", lambda: False)):
            p.start()
            self.addCleanup(p.stop)

    def test_update_and_restore_reach_core(self):
        for service, data in (
                ("update_dashboard", {"url_path": "dashboard-kitchen",
                                      "config": {"views": [{"title": "Kitchen"}]}}),
                ("restore_dashboard", {"url_path": "dashboard-kitchen"})):
            got = m.handle_tool_call("call_service", {
                "domain": "brain", "service": service, "data": data,
                "return_response": True})
            self.assertNotIn("error", got, (service, got))
        self.assertEqual([c["service"] for c in self.calls],
                         ["update_dashboard", "restore_dashboard"])

    def test_an_agent_that_blocks_brain_services_says_where_the_block_is(self):
        """A new agent is created with brain.* blocked — the owner's list,
        kept. The refusal has to say it is that list, so the answer is
        "your agent blocks it", never "brAIn can't change config"."""
        m.DENIED_SERVICES = ["brain.*"]
        got = m.handle_tool_call("call_service", {
            "domain": "brain", "service": "update_dashboard",
            "data": {"url_path": "default", "config": {"views": []}}})
        self.assertIn("not permitted for this assistant", got["error"])
        self.assertIn("Blocked services", got["error"])
        self.assertIn("brAIn chat", got["error"])
        self.assertEqual(self.calls, [])


class TestNothingSaysADashboardCannotBeChanged(unittest.TestCase):

    def test_every_mcp_process_is_told_how_a_dashboard_is_changed(self):
        """The voice workers and the engine's runs never read the
        terminal's CLAUDE.md; the server's own instructions reach all."""
        for name in ("get_dashboard", "brain.update_dashboard",
                     "brain.restore_dashboard"):
            self.assertIn(name, m.INSTRUCTIONS)

    def test_a_whole_house_agent_is_told_it_can(self):
        import brain_exposed
        self.assertIn("brain.update_dashboard", brain_exposed.TOOLS_HA)
        self.assertIn("get_dashboard", brain_exposed.TOOLS_HA)

    def test_a_read_only_reply_does_not_say_it_cannot_be_done(self):
        tree = ast.parse((PANEL / "server.py").read_text())
        value = None
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(
                    getattr(t, "id", "") == "READ_ONLY_TOOLS" for t in node.targets):
                value = ast.literal_eval(node.value)
        self.assertIsNotNone(value)
        self.assertIn("brAIn chat", value)
        self.assertIn("never say it cannot be done", value)

    def test_a_tell_that_names_a_lovelace_dashboard_changes_it(self):
        from morph_env import MorphEnv
        with MorphEnv() as env:
            target = {"kind": "dashboard"}
            text = env.tell.build_prompt(
                target, "Add a weather card to my Lovelace dashboard",
                env.tell.target_yaml(target))
        self.assertNotIn("never a Lovelace dashboard", text)
        self.assertIn("brain.update_dashboard", text)

    def test_morphs_ask_bar_does_not_tell_the_agent_it_cannot(self):
        phrases = ["Add a weather card to my Lovelace dashboard",
                   "change the energy view on the lovelace dashboard",
                   "Move the kitchen card up"]
        script = textwrap.dedent(f"""
            import {{ isDashChange, ASK_CONTEXT }} from {json.dumps((FRONTEND / 'util.js').as_uri())};
            console.log(JSON.stringify({{ got: {json.dumps(phrases)}.map(isDashChange), ctx: ASK_CONTEXT }}));
        """)
        r = subprocess.run(["node", "--input-type=module", "-e", script],
                           capture_output=True, text=True, timeout=30,
                           env={**os.environ})
        self.assertEqual(0, r.returncode, r.stderr)
        out = json.loads(r.stdout)
        # A Lovelace request is the house's, not a Tell about Morph's page.
        self.assertEqual([False, False, True], out["got"])
        self.assertNotIn("You cannot change the dashboard", out["ctx"])
        self.assertIn("brain.update_dashboard", out["ctx"])


if __name__ == "__main__":
    unittest.main()
