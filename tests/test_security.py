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
import unittest

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


if __name__ == "__main__":
    unittest.main()
