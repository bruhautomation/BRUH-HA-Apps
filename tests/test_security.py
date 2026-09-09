#!/usr/bin/env python3
"""
Security-focused tests for the brAIn add-on.

Tests cover:
- No hardcoded tokens or secrets in any file
- No command injection vulnerabilities in shell scripts
- Shell metacharacter validation in user-facing scripts
- YAML checker uses safe file argument passing
- Proper quoting in shell scripts
- No eval usage
- Gitignore covers sensitive files
- File path sanitization
"""

import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "brain")
SCRIPTS_DIR = os.path.join(ADDON_DIR, "scripts")
INTEGRATIONS_DIR = os.path.join(ADDON_DIR, "integrations")


def read_file(path):
    with open(path, "r") as f:
        return f.read()


def get_all_shell_scripts():
    scripts = []
    for dirpath, _, filenames in os.walk(ADDON_DIR):
        for f in filenames:
            if f.endswith(".sh"):
                scripts.append(os.path.join(dirpath, f))
    return scripts


def get_all_python_files():
    files = []
    for dirpath, _, filenames in os.walk(ADDON_DIR):
        for f in filenames:
            if f.endswith(".py"):
                files.append(os.path.join(dirpath, f))
    return files


class TestNoHardcodedCredentials(unittest.TestCase):
    """Ensure no credentials are embedded in source files."""

    def test_no_hardcoded_tokens_in_scripts(self):
        """No shell script should embed token values."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            # Long alphanumeric strings after Bearer
            self.assertNotRegex(
                content, r'Bearer\s+[a-zA-Z0-9_.-]{20,}',
                f"{name} has hardcoded bearer token"
            )

    def test_no_hardcoded_tokens_in_python(self):
        """No Python file should embed token values."""
        for pyfile in get_all_python_files():
            content = read_file(pyfile)
            name = os.path.basename(pyfile)
            self.assertNotRegex(
                content, r'Bearer\s+[a-zA-Z0-9_.-]{20,}',
                f"{name} has hardcoded bearer token"
            )

    def test_no_api_keys_anywhere(self):
        """No file should contain API key patterns."""
        pattern = re.compile(r'sk-[a-zA-Z0-9]{20,}')
        all_files = get_all_shell_scripts() + get_all_python_files()
        for filepath in all_files:
            content = read_file(filepath)
            name = os.path.basename(filepath)
            self.assertIsNone(
                pattern.search(content),
                f"{name} contains an API key pattern"
            )

    def test_supervisor_token_never_assigned_literal(self):
        """SUPERVISOR_TOKEN should only come from environment variables."""
        # HA_TOKEN is derived from SUPERVISOR_TOKEN in run.sh, so re-deriving
        # SUPERVISOR_TOKEN from HA_TOKEN in an interactive-shell fallback is
        # semantically equivalent to reading from the environment.
        env_ref = re.compile(r'SUPERVISOR_TOKEN="\$\{?(SUPERVISOR_TOKEN|HA_TOKEN)')
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            for line in content.split("\n"):
                if "SUPERVISOR_TOKEN=" in line and not line.strip().startswith("#"):
                    if not env_ref.search(line):
                        self.fail(f"{name}: SUPERVISOR_TOKEN assigned non-env value: {line.strip()}")

    def test_mcp_config_no_embedded_token(self):
        """MCP config JSON should not embed SUPERVISOR_TOKEN."""
        run_sh = read_file(os.path.join(ADDON_DIR, "run.sh"))
        # Find the mcp_entry definition
        mcp_section = run_sh[run_sh.index("local mcp_entry='"):]
        mcp_section = mcp_section[:mcp_section.index("}'") + 2]
        self.assertNotIn("SUPERVISOR_TOKEN", mcp_section)
        self.assertNotIn("Bearer", mcp_section)


class TestNoCommandInjection(unittest.TestCase):
    """Test for command injection vulnerabilities."""

    def test_yaml_check_uses_sys_argv(self):
        """ha-yaml-check should pass filenames via sys.argv, not interpolation."""
        content = read_file(os.path.join(SCRIPTS_DIR, "ha-yaml-check.sh"))
        # After fix: should use sys.argv[1] instead of '$file' in Python code
        self.assertIn("sys.argv[1]", content)
        # Should NOT have open('$file'...) pattern (shell injection)
        python_section = content[content.index("python3 -c"):]
        python_section = python_section[:python_section.index('" "$file"')]
        self.assertNotIn("'$file'", python_section)

    def test_session_picker_validates_custom_args(self):
        """brain-menu should validate user input for shell metacharacters."""
        content = read_file(os.path.join(SCRIPTS_DIR, "brain-menu.sh"))
        # After fix: should check for dangerous characters
        self.assertIn("metacharacters", content.lower())

    def test_no_eval_in_scripts(self):
        """No script should use eval."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            for i, line in enumerate(content.split("\n"), 1):
                if "eval " in line and not line.strip().startswith("#"):
                    self.fail(f"{name}:{i} contains eval: {line.strip()}")

    def test_integration_listeners_use_jq_for_json(self):
        """Integration listeners should use jq for JSON construction."""
        for listener in ["assist-listener.sh", "automation-listener.sh"]:
            content = read_file(os.path.join(INTEGRATIONS_DIR, listener))
            self.assertIn("jq -n", content,
                          f"{listener} should use jq for JSON construction")

    def test_listeners_pipe_prompts_not_args(self):
        """Listeners should pipe prompts to claude via stdin, not as args."""
        # The actual pipe chain can include intermediate commands like
        # `timeout $CLAUDE_TIMEOUT` between the pipe and the claude binary,
        # so we check two things independently:
        #   1. The prompt is piped in via `printf '%s' "$var" |`
        #   2. The claude invocation (claude -p / ${CLAUDE_BIN} -p) appears
        #      without the prompt variable as an argument.
        pipe_pattern = re.compile(r"printf\s+'%s'\s+\"\$[A-Za-z_][A-Za-z0-9_]*\"\s*\|")
        claude_arg_pattern = re.compile(
            r"(?:claude|\$\{?CLAUDE_BIN\}?)\s+-p\b[^\n]*\"\$(?:prompt|text|user_message)\""
        )
        for listener in ["assist-listener.sh", "automation-listener.sh"]:
            content = read_file(os.path.join(INTEGRATIONS_DIR, listener))
            self.assertRegex(
                content, pipe_pattern,
                f"{listener} should pipe prompt via stdin (printf '%s' \"$var\" | ...)"
            )
            self.assertNotRegex(
                content, claude_arg_pattern,
                f"{listener} must not pass prompt to claude as a command-line argument"
            )


class TestNoRmRfDangerous(unittest.TestCase):
    """Ensure no dangerous rm commands."""

    def test_no_rm_rf_root(self):
        """No script should rm -rf /."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            self.assertNotRegex(
                content, r'rm\s+-rf\s+[/]\s',
                f"{name} contains dangerous rm -rf / pattern"
            )

    def test_no_rm_rf_config_unquoted(self):
        """rm -rf on config paths should use quoted variables."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            # Flag rm -rf with unquoted variables
            for i, line in enumerate(content.split("\n"), 1):
                if re.search(r'rm\s+-rf\s+\$[A-Z]', line) and not line.strip().startswith("#"):
                    # Check it's quoted
                    if not re.search(r'rm\s+-rf\s+"\$', line):
                        self.fail(
                            f"{name}:{i} has unquoted rm -rf: {line.strip()}"
                        )


class TestProperQuoting(unittest.TestCase):
    """Test proper variable quoting in critical contexts."""

    def test_supervisor_token_quoted_in_curl(self):
        """SUPERVISOR_TOKEN should be in braces in curl commands."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            for i, line in enumerate(content.split("\n"), 1):
                if "curl" in line and "SUPERVISOR_TOKEN" in line:
                    if "$SUPERVISOR_TOKEN" in line:
                        self.assertTrue(
                            "${SUPERVISOR_TOKEN}" in line,
                            f"{name}:{i} SUPERVISOR_TOKEN not in braces"
                        )


class TestAnalystCanOnlyRead(unittest.TestCase):
    """Insight generation runs unattended. It must not be able to act.

    Three Claude paths exist in the panel and only one may change the house:
    ``run_agent``, behind the Findings "Fix it" button, which a person
    presses. ``run_claude`` holds no tools at all. ``run_analyst`` sits in
    between — it has Home Assistant tools so it can go and read what a
    question needs — and it runs on a schedule and on any typed question,
    with nobody watching. So its tool set is asserted here rather than left
    to a flag's semantics.
    """

    # Tools that change something, act on the house, or cost real money.
    # `fire_event` and `remember_fact` are the trap: both are shaped like
    # reads and are not, so a rule sorted by name prefix would pass them.
    MUST_BE_DENIED = (
        "call_service", "fire_event", "remember_fact", "send_notification",
        "activate_scene", "run_script", "reload_config", "render_template",
        "get_camera_snapshot", "control_light", "control_climate",
        "control_media_player", "control_cover", "control_fan",
        "control_switch", "control_lock", "control_alarm", "control_vacuum",
    )

    def setUp(self):
        import sys
        sys.path.insert(0, os.path.join(ADDON_DIR, "panel"))
        import engine
        self.engine = engine

    def test_no_write_tool_is_in_the_allow_list(self):
        for name in self.MUST_BE_DENIED:
            self.assertNotIn(f"{self.engine.MCP}{name}", self.engine.ANALYST_TOOLS,
                             f"{name} would let an unattended run act")

    def test_every_write_tool_is_named_in_the_deny_list(self):
        """Allow-listing is not enough on its own.

        ``--allowedTools`` governs what runs WITHOUT a prompt, and a headless
        run cannot be prompted — so an un-listed tool fails rather than being
        forbidden, and those are not the same guarantee with a real house on
        the other side of it.
        """
        for name in self.MUST_BE_DENIED:
            self.assertIn(f"{self.engine.MCP}{name}", self.engine.ANALYST_DENIED,
                          f"{name} is not explicitly denied to the analyst")

    def test_shell_and_file_tools_are_denied(self):
        for name in ("Bash", "Write", "Edit", "NotebookEdit"):
            self.assertIn(name, self.engine.ANALYST_DENIED)

    def test_a_new_mcp_write_tool_cannot_be_missed(self):
        """The deny list is checked against the MCP server's actual tools.

        Adding a `control_*` or `set_*` tool to the MCP server and forgetting
        this list is exactly the drift that would hand an unattended run the
        ability to act, so it fails here rather than in somebody's house.
        """
        src = read_file(os.path.join(ADDON_DIR, "ha-mcp-server", "ha_mcp_server.py"))
        declared = set(re.findall(r'"name":\s*"([a-z_0-9]+)"', src))
        acting = {n for n in declared if re.match(
            r"^(call_service|control_|send_|activate_|run_script|reload_|set_|"
            r"create_|delete_|update_|render_template|fire_event|remember_)", n)}
        self.assertTrue(acting, "no acting tools found — did the regex rot?")
        missing = sorted(
            n for n in acting
            if f"{self.engine.MCP}{n}" not in self.engine.ANALYST_DENIED)
        self.assertEqual(missing, [], f"acting MCP tools not denied: {missing}")

    def test_every_mcp_tool_is_in_exactly_one_list(self):
        """The partition, driven off the server's own tool table.

        The prefix regex above catches an acting tool that was forgotten;
        it says nothing about a READ tool in neither list, and a tool in
        neither is not forbidden — it fails when the analyst reaches for it,
        which from a card reads as a broken tool rather than a policy. So
        every name the server registers has to be allowed or denied, and
        never both: a tool on both lists is a policy nobody can read.
        """
        import sys
        sys.path.insert(0, os.path.join(ADDON_DIR, "ha-mcp-server"))
        import ha_mcp_server
        registered = set(ha_mcp_server.TOOL_IMPLEMENTATIONS)
        self.assertGreater(len(registered), 30, "did the tool table move?")
        prefix = self.engine.MCP
        allowed = {n[len(prefix):] for n in self.engine.ANALYST_TOOLS
                   if n.startswith(prefix)}
        denied = {n[len(prefix):] for n in self.engine.ANALYST_DENIED
                  if n.startswith(prefix)}
        self.assertEqual(sorted(allowed & denied), [],
                         "a tool cannot be both allowed and denied")
        self.assertEqual(sorted(registered - allowed - denied), [],
                         "MCP tools in neither list: neither allowed nor "
                         "forbidden, so the analyst's call fails instead")
        self.assertEqual(sorted((allowed | denied) - registered), [],
                         "the analyst lists name tools the server does not have")
        # And the three the analyst leans on for "unusual" and "why" are on
        # the reading side — a rename there would silently blind every card.
        for name in ("get_baseline", "get_activity", "explain_change"):
            self.assertIn(name, allowed, name)

    def test_the_analyst_is_not_told_it_has_no_tools(self):
        """The two preambles differ in exactly this, and share the rest."""
        import categories
        self.assertNotIn("NO tools available", categories.ANALYST_SYSTEM)
        self.assertIn("NO tools available", categories.SYSTEM_PROMPT)
        self.assertIn("only READ", categories.ANALYST_SYSTEM)
        # One contract, two preambles — not two copies of a 10 KB document.
        for shared in ("OUTPUT CONTRACT", "DESIGN SYSTEM", "ANALYSIS RULES"):
            self.assertIn(shared, categories.ANALYST_SYSTEM)
            self.assertIn(shared, categories.SYSTEM_PROMPT)


class TestTheFacesThatCanBypassTheChokepointAreToldTheList(unittest.TestCase):
    """`protected_entities` is enforced in the MCP server and nowhere else.

    That is right for every path whose only route to the house is a tool
    call: `call_service` is the chokepoint every `control_*` routes
    through, and it refuses. Two faces are not like that. The fixer holds
    Bash, Write and Edit; the terminal and the chat hold the same. `ha
    service light.turn_on`, a line added to automations.yaml, a script
    written and reloaded — none of those passes the chokepoint, and none
    of them can be refused by it.

    Telling them is weaker than enforcing, and it is not offered as a
    substitute: it is the only thing available on the paths enforcement
    cannot reach, and a rule the model was never told is one it cannot
    keep. What is asserted here is that the list actually arrives.
    """

    def setUp(self):
        import sys
        sys.path.insert(0, os.path.join(ADDON_DIR, "panel"))
        import fixer
        self.fixer = fixer

    def test_the_fix_prompt_carries_the_homeowners_list(self):
        prompt = self.fixer.build_prompt(
            {"text": "the porch light is stuck"},
            protected=["lock.front_door", "alarm_control_panel.*"])
        self.assertIn("lock.front_door", prompt)
        self.assertIn("alarm_control_panel.*", prompt)
        self.assertIn("PROTECTED ENTITIES", prompt)

    def test_an_empty_list_produces_no_heading(self):
        """A heading over nothing reads as "nothing is protected here" —
        which is true, and is also what a list that failed to load looks
        like."""
        for empty in (None, [], ["", "  "]):
            with self.subTest(repr(empty)):
                prompt = self.fixer.build_prompt(
                    {"text": "x"}, protected=empty)
                self.assertNotIn("PROTECTED ENTITIES", prompt)

    def test_the_block_says_reading_is_still_allowed(self):
        """Read-only tools are untouched by the chokepoint too: a
        protected entity can be looked at, not acted on. A rule stated as
        "do not touch" would stop the fixer confirming the problem."""
        block = self.fixer.protected_block(["lock.front_door"])
        self.assertIn("Read them freely", block)

    def test_the_system_prompt_names_the_two_paths_that_are_not_checked(self):
        """The hard rule is static and the list is runtime, so the rule
        has to point at the list rather than repeat it."""
        self.assertIn("PROTECTED ENTITY", self.fixer.FIX_SYSTEM)
        self.assertIn("shell and file edits", self.fixer.FIX_SYSTEM)

    def test_the_fixer_reads_the_same_option_the_mcp_server_does(self):
        """One parse, one answer. A second reading of the same option is
        a second answer to "is this entity protected"."""
        import automation_writer
        os.environ["BRAIN_PROTECTED_ENTITIES"] = " lock.Front_Door , light.* "
        try:
            self.assertEqual(automation_writer.protected_patterns(),
                             ["lock.front_door", "light.*"])
        finally:
            os.environ.pop("BRAIN_PROTECTED_ENTITIES", None)

    def test_the_generated_context_file_carries_the_list(self):
        """`/config/CLAUDE.md` is the project context Claude Code reads,
        which makes it the only route the terminal and the chat have to
        the list. The block is lifted out of the real script and driven,
        rather than grepped for — a grep for a line is not a test of what
        the line does.
        """
        import subprocess
        script = os.path.join(ADDON_DIR, "scripts", "ha-context-gen.sh")
        with open(script, encoding="utf-8") as f:
            source = f.read()
        start = source.index("        protected_rows=$(printf")
        end = source.index("\n", source.index("| sed 's/^/- `/;", start))
        recipe = source[start:end].strip()
        out = subprocess.run(
            ["bash", "-c",
             'BRAIN_PROTECTED_ENTITIES="lock.front_door, alarm_control_panel.*"\n'
             + recipe.replace("        ", "") + '\nprintf "%s" "$protected_rows"'],
            capture_output=True, text=True, check=True)
        self.assertEqual(out.stdout,
                         "- `lock.front_door`\n- `alarm_control_panel.*`")

    def test_the_context_file_says_nothing_when_the_list_is_empty(self):
        """Same rule as the fix prompt: an empty heading is a claim."""
        with open(os.path.join(ADDON_DIR, "scripts", "ha-context-gen.sh"),
                  encoding="utf-8") as f:
            text = f.read()
        self.assertIn('if [ -n "${BRAIN_PROTECTED_ENTITIES:-}" ]; then', text)
        self.assertIn("${protected_section}", text)


if __name__ == "__main__":
    unittest.main()


class TestAStudySessionIsScopedLikeTheAnalyst(unittest.TestCase):
    """A study reads the house; this script writes what it found.

    Every fact a study session produces is filed by `brain-learn.sh`
    itself, out of the JSON the model returned — the model never needs a
    tool that writes. It nonetheless ran with whatever
    `/config/.claude/settings.local.json` pre-approves, which is Bash,
    Write and Edit, on a path reachable from an automation
    (`brain.study`). It runs with the analyst's own lists now, read out
    of `engine.py` so there is one answer to "what may an unattended run
    touch", and it REFUSES rather than running unscoped when it cannot
    read them.
    """

    SCRIPT = Path(BASE_DIR) / "brain" / "scripts" / "brain-learn.sh"

    def _run(self, panel_dir, claude_log):
        """Drive the real script against a fake claude, return its argv."""
        env = dict(os.environ)
        env.update({
            "BRAIN_CLAUDE_BIN": str(claude_log.parent / "fake-claude"),
            "BRAIN_MEMORY_DIR": str(claude_log.parent / "memory"),
            "BRAIN_FINDINGS_INBOX": str(claude_log.parent / "findings"),
            "BRAIN_CURRICULUM_FILE": str(claude_log.parent / "curriculum.json"),
            "BRAIN_LEARN_TIMEOUT": "20",
            "FAKE_CLAUDE_ARGV_LOG": str(claude_log),
            "BRAIN_PANEL_DIR": str(panel_dir),
        })
        return subprocess.run(
            ["bash", str(self.SCRIPT), "naming"],
            capture_output=True, text=True, timeout=60, env=env)

    def test_the_lists_come_from_engine_and_are_not_copied_here(self):
        src = self.SCRIPT.read_text()
        self.assertIn("engine.ANALYST_TOOLS", src)
        self.assertIn("engine.ANALYST_DENIED", src)
        self.assertIn("--allowedTools", src)
        self.assertIn("--disallowedTools", src)
        # The deny list must not be spelled out a second time in the
        # shell: that is the copy that goes stale when a tool is added.
        for acting in ("call_service", "fire_event", "run_script"):
            self.assertNotIn(f"mcp__home-assistant__{acting}", src,
                             "the shell keeps its own copy of the deny list")

    def test_it_refuses_rather_than_running_with_no_restriction(self):
        """The failure mode that matters: unreadable lists must not mean
        an unscoped run, because that is the state this fixes."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log = root / "argv.log"
            (root / "fake-claude").write_text("#!/bin/sh\nexit 0\n")
            (root / "fake-claude").chmod(0o755)
            # A panel directory with no engine.py in it.
            empty = root / "nopanel"
            empty.mkdir()
            proc = self._run(empty, log)
        self.assertNotEqual(proc.returncode, 0,
                            "an unscopeable study session still ran")
        self.assertIn("refusing", (proc.stderr or "").lower())
        self.assertFalse(log.exists(), "claude was invoked anyway")
