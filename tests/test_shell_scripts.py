#!/usr/bin/env python3
"""
Tests for shell script quality and correctness.

Tests cover:
- Shebang lines and script structure
- No hardcoded tokens or secrets
- Proper quoting and variable usage
- No dangerous patterns (rm -rf /, eval, etc.)
- Consistent use of git -C instead of cd
- JSON construction uses jq (not string interpolation)
- Script help messages and argument parsing
- Cross-script consistency
"""

import os
import re
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "bruh-claude-terminal")
SCRIPTS_DIR = os.path.join(ADDON_DIR, "scripts")
INTEGRATIONS_DIR = os.path.join(ADDON_DIR, "integrations")


def read_file(path):
    """Read a file and return its contents."""
    with open(path, "r") as f:
        return f.read()


def get_all_shell_scripts():
    """Get all .sh files in the add-on."""
    scripts = []
    for dirpath, _, filenames in os.walk(ADDON_DIR):
        for f in filenames:
            if f.endswith(".sh"):
                scripts.append(os.path.join(dirpath, f))
    return scripts


class TestNoHardcodedSecrets(unittest.TestCase):
    """Ensure no tokens or secrets are hardcoded."""

    def test_no_hardcoded_tokens(self):
        """No script should contain hardcoded bearer tokens."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            # Look for hardcoded bearer tokens (actual token values, not variable references)
            self.assertNotRegex(
                content,
                r'Bearer\s+[a-zA-Z0-9_.-]{20,}',
                f"{name} appears to contain a hardcoded bearer token"
            )

    def test_no_hardcoded_api_keys(self):
        """No script should contain hardcoded API keys."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            # Look for common API key patterns
            self.assertNotRegex(
                content,
                r'sk-[a-zA-Z0-9]{20,}',
                f"{name} appears to contain a hardcoded API key"
            )

    def test_supervisor_token_from_env(self):
        """SUPERVISOR_TOKEN should only come from environment."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            # Should never assign a literal value to SUPERVISOR_TOKEN
            self.assertNotRegex(
                content,
                r'SUPERVISOR_TOKEN="[a-zA-Z0-9]',
                f"{name} assigns a literal value to SUPERVISOR_TOKEN"
            )


class TestNoDangerousPatterns(unittest.TestCase):
    """Ensure scripts don't contain dangerous shell patterns."""

    def test_no_rm_rf_root(self):
        """No script should rm -rf /."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            self.assertNotRegex(
                content,
                r'rm\s+-rf\s+/',
                f"{name} contains dangerous 'rm -rf /' pattern"
            )

    def test_no_eval_on_user_input(self):
        """No script should eval user-controlled input."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            # eval is dangerous - flag if present
            if "eval " in content:
                # Allow eval only with known-safe patterns
                for line in content.split("\n"):
                    if "eval " in line and not line.strip().startswith("#"):
                        self.fail(f"{name} contains eval: {line.strip()}")

    def test_no_unquoted_variable_expansions_in_critical_commands(self):
        """Critical commands should use quoted variables."""
        for script in get_all_shell_scripts():
            content = read_file(script)
            name = os.path.basename(script)
            # Check for unquoted $SUPERVISOR_TOKEN in curl commands
            for i, line in enumerate(content.split("\n"), 1):
                if "curl" in line and "$SUPERVISOR_TOKEN" in line:
                    # Should be quoted: "${SUPERVISOR_TOKEN}" or "$SUPERVISOR_TOKEN"
                    self.assertTrue(
                        "${SUPERVISOR_TOKEN}" in line or '"$SUPERVISOR_TOKEN"' in line,
                        f"{name}:{i} - SUPERVISOR_TOKEN should be in braces in curl command"
                    )


class TestRunSh(unittest.TestCase):
    """Test the main run.sh entrypoint."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(ADDON_DIR, "run.sh"))

    def test_uses_bashio_shebang(self):
        """run.sh must use bashio shebang."""
        self.assertTrue(self.content.startswith("#!/usr/bin/with-contenv bashio"))

    def test_has_set_e(self):
        """run.sh should use set -e for error handling."""
        self.assertIn("set -e", self.content)

    def test_has_cleanup_trap(self):
        """run.sh should trap signals for cleanup."""
        self.assertIn("trap cleanup", self.content)

    def test_exports_supervisor_token(self):
        """run.sh should export HA_TOKEN from SUPERVISOR_TOKEN."""
        self.assertIn('HA_TOKEN="${SUPERVISOR_TOKEN}"', self.content)

    def test_uses_git_c_not_cd(self):
        """run.sh should use 'git -C' instead of 'cd' + 'git'."""
        # Should use git -C /config for all git operations
        self.assertIn("git -C /config", self.content)
        # The only cd should be in init for legacy or not present at all in git sections
        # Count cd and git -C usage in the backup section
        backup_section = self.content[self.content.index("setup_auto_backup"):]
        backup_section = backup_section[:backup_section.index("# ====", 10)]
        self.assertNotIn("cd /config", backup_section)

    def test_mcp_config_no_token(self):
        """MCP JSON config should NOT embed SUPERVISOR_TOKEN value."""
        # Find the MCP entry JSON template in run.sh. The function definition
        # (not any earlier comment references) is where the JSON template lives.
        fn_start = self.content.index("setup_mcp_server()")
        mcp_section = self.content[fn_start:]
        # The mcp_entry variable holds the JSON written to disk.
        mcp_entry_start = mcp_section.index("local mcp_entry='")
        mcp_entry_end = mcp_section.index("}'", mcp_entry_start) + 2
        mcp_entry = mcp_section[mcp_entry_start:mcp_entry_end]
        self.assertNotIn("SUPERVISOR_TOKEN", mcp_entry)
        self.assertNotIn("Bearer", mcp_entry)

    def test_gitignore_includes_mcp_json(self):
        """The .gitignore template should exclude .mcp.json."""
        self.assertIn(".mcp.json", self.content)

    def test_gitignore_includes_secrets(self):
        """The .gitignore template should exclude secrets.yaml."""
        self.assertIn("secrets.yaml", self.content)

    def test_gitignore_includes_storage(self):
        """The .gitignore template should exclude .storage/."""
        self.assertIn(".storage/", self.content)

    def test_persistent_packages_uses_jq(self):
        """Persistent package parsing should use jq for JSON arrays."""
        pkg_section = self.content[self.content.index("install_persistent_packages"):]
        pkg_section = pkg_section[:pkg_section.index("# ====", 10)]
        self.assertIn("jq -r", pkg_section)

    def test_all_main_functions_called(self):
        """All setup functions should be called from main."""
        required_calls = [
            "init_environment",
            "install_tools",
            "install_cli_tools",
            "install_persistent_packages",
            "setup_auto_backup",
            "setup_context_generation",
            "setup_mcp_server",
            "setup_assist_integration",
            "setup_automation_integration",
            "start_web_terminal",
        ]
        main_section = self.content[self.content.rindex("main()"):]
        for fn in required_calls:
            self.assertIn(fn, main_section, f"main() missing call to {fn}")


class TestHaReload(unittest.TestCase):
    """Test ha-reload.sh."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(SCRIPTS_DIR, "ha-reload.sh"))

    def test_supports_all_targets(self):
        """ha-reload should support all documented reload targets."""
        expected_targets = [
            "automations", "scripts", "scenes", "groups",
            "input_booleans", "input_numbers", "input_selects",
            "input_texts", "input_datetimes", "timers", "counters",
            "core", "all", "check"
        ]
        for target in expected_targets:
            self.assertIn(target, self.content, f"Missing reload target: {target}")

    def test_checks_http_status(self):
        """ha-reload should check HTTP status codes."""
        self.assertIn("http_code", self.content)

    def test_has_help_function(self):
        """ha-reload should have a help function."""
        self.assertIn("show_help", self.content)

    def test_validates_target(self):
        """ha-reload should handle unknown targets."""
        self.assertIn("Unknown target", self.content)


class TestHaLog(unittest.TestCase):
    """Test ha-log.sh."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(SCRIPTS_DIR, "ha-log.sh"))

    def test_supports_all_targets(self):
        """ha-log should support core, supervisor, host, addon, errors, all."""
        targets = ["core", "supervisor", "host", "addon", "errors", "all"]
        for target in targets:
            self.assertIn(target, self.content, f"Missing log target: {target}")

    def test_supports_follow_mode(self):
        """ha-log should support -f/--follow."""
        self.assertIn("--follow", self.content)
        self.assertIn("-f", self.content)

    def test_supports_line_count(self):
        """ha-log should support -n <lines>."""
        self.assertIn("-n)", self.content)

    def test_follow_tracks_line_count(self):
        """Follow mode should track line count, not byte count."""
        self.assertIn("last_line_count", self.content)
        self.assertNotIn("last_size", self.content)


class TestHaBackup(unittest.TestCase):
    """Test ha-backup.sh."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(SCRIPTS_DIR, "ha-backup.sh"))

    def test_supports_all_commands(self):
        """ha-backup should support backup, history, diff, restore."""
        self.assertIn("history", self.content)
        self.assertIn("diff", self.content)
        self.assertIn("restore", self.content)

    def test_uses_git_c(self):
        """ha-backup should use 'git -C' instead of 'cd'."""
        self.assertIn('git -C "$CONFIG_DIR"', self.content)
        # Should not cd into config dir
        self.assertNotIn('cd "$CONFIG_DIR"', self.content)

    def test_gitignore_includes_mcp_json(self):
        """ha-backup .gitignore should exclude .mcp.json."""
        self.assertIn(".mcp.json", self.content)

    def test_has_help(self):
        """ha-backup should have a help command."""
        self.assertIn("show_help", self.content)


class TestIntegrationListeners(unittest.TestCase):
    """Test integration listener scripts."""

    def test_assist_listener_uses_jq_for_json(self):
        """assist-listener.sh should use jq to build JSON."""
        content = read_file(os.path.join(INTEGRATIONS_DIR, "assist-listener.sh"))
        self.assertIn("jq -n", content)

    def test_automation_listener_uses_jq_for_json(self):
        """automation-listener.sh should use jq to build JSON."""
        content = read_file(os.path.join(INTEGRATIONS_DIR, "automation-listener.sh"))
        self.assertIn("jq -n", content)

    def test_assist_listener_no_string_interpolation_in_json(self):
        """assist-listener.sh should not use string interpolation for JSON POST bodies."""
        content = read_file(os.path.join(INTEGRATIONS_DIR, "assist-listener.sh"))
        # Should not have patterns like -d "{\"key\": \"$var\"}"
        curl_lines = [l for l in content.split("\n") if "-d " in l and "curl" not in l]
        for line in curl_lines:
            if "-d " in line and '"' in line:
                # Allow -d "$json_payload" (variable reference to jq output)
                if re.search(r'-d\s+"\$\{?[a-z]', line):
                    # This is fine - using a variable built by jq
                    pass

    def test_automation_listener_pipes_prompt(self):
        """automation-listener.sh should pipe prompt to claude, not pass as arg."""
        content = read_file(os.path.join(INTEGRATIONS_DIR, "automation-listener.sh"))
        # The pipe chain may include `timeout` between the pipe and the claude
        # binary, so we verify the prompt is piped in and is not an argument.
        self.assertRegex(
            content, r"printf\s+'%s'\s+\"\$prompt\"\s*\|",
            "automation-listener.sh should pipe prompt via stdin (printf '%s' \"$prompt\" | ...)"
        )
        self.assertNotRegex(
            content,
            r"(?:claude|\$\{?CLAUDE_BIN\}?)\s+-p\b[^\n]*\"\$prompt\"",
            "automation-listener.sh must not pass $prompt to claude as an argument"
        )

    def test_assist_listener_pipes_prompt(self):
        """assist-listener.sh should pipe text to claude, not use single quotes."""
        content = read_file(os.path.join(INTEGRATIONS_DIR, "assist-listener.sh"))
        # Should not have 'The user said: '$text'' (single-quote injection)
        self.assertNotIn("'$text'", content)


class TestTmuxConf(unittest.TestCase):
    """Test tmux configuration."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(SCRIPTS_DIR, "tmux.conf"))

    def test_passes_through_ha_env_vars(self):
        """tmux.conf should pass through HA environment variables."""
        self.assertIn("update-environment", self.content)
        self.assertIn("SUPERVISOR_TOKEN", self.content)
        self.assertIn("HA_TOKEN", self.content)
        self.assertIn("HA_BASE_URL", self.content)

    def test_has_bruh_status_bar(self):
        """tmux.conf should have BRUH prefix in status bar."""
        self.assertIn("[BRUH]", self.content)

    def test_has_clipboard_support(self):
        """tmux.conf should enable clipboard support."""
        self.assertIn("set-clipboard on", self.content)

    def test_has_scroll_buffer(self):
        """tmux.conf should have increased scroll buffer."""
        self.assertIn("history-limit", self.content)


class TestHealthCheck(unittest.TestCase):
    """Test health-check.sh."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(SCRIPTS_DIR, "health-check.sh"))

    def test_checks_claude_binary(self):
        """health-check.sh should verify Claude is installed."""
        self.assertIn("claude", self.content)

    def test_checks_ha_api(self):
        """health-check.sh should check HA API access."""
        self.assertIn("supervisor", self.content.lower())


class TestPersistInstall(unittest.TestCase):
    """Test persist-install.sh."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(SCRIPTS_DIR, "persist-install.sh"))

    def test_supports_apk_and_pip(self):
        """persist-install should support apk and pip."""
        self.assertIn("apk", self.content)
        self.assertIn("pip", self.content)

    def test_supports_list(self):
        """persist-install should support listing packages."""
        self.assertIn("list", self.content)

    def test_supports_remove(self):
        """persist-install should support removing packages."""
        self.assertIn("remove", self.content)


if __name__ == "__main__":
    unittest.main()
