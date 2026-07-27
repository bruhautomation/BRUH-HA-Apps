#!/usr/bin/env python3
"""
Security-focused tests for the BRUH Claude Terminal add-on.

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
ADDON_DIR = os.path.join(BASE_DIR, "bruh-claude-terminal")
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
        """claude-session-picker should validate user input for shell metacharacters."""
        content = read_file(os.path.join(SCRIPTS_DIR, "claude-session-picker.sh"))
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


class TestGitignoreCoversSecrets(unittest.TestCase):
    """Test that gitignore templates cover sensitive files."""

    def _get_gitignore_entries(self, content):
        """Extract gitignore patterns from a script's heredoc."""
        entries = set()
        in_gitignore = False
        for line in content.split("\n"):
            if "GITIGNORE" in line and "<<" in line:
                in_gitignore = True
                continue
            if in_gitignore and line.strip() == "GITIGNORE":
                break
            if in_gitignore and line.strip() and not line.strip().startswith("#"):
                entries.add(line.strip())
        return entries

    # The only .storage files a gitignore may re-include: registries and
    # dashboards carry no credentials. Everything else in .storage —
    # notably core.config_entries, auth*, cloud — must stay excluded.
    SAFE_STORAGE_REINCLUDES = {
        "!.storage/core.area_registry",
        "!.storage/core.floor_registry",
        "!.storage/core.label_registry",
        "!.storage/core.device_registry",
        "!.storage/core.entity_registry",
        "!.storage/core.category_registry",
        "!.storage/lovelace*",
    }

    def _assert_storage_safely_excluded(self, entries, label):
        self.assertTrue(
            ".storage/" in entries or ".storage/*" in entries,
            f"{label} gitignore missing .storage exclusion",
        )
        reincludes = {e for e in entries if e.startswith("!.storage/")}
        self.assertLessEqual(
            reincludes,
            self.SAFE_STORAGE_REINCLUDES,
            f"{label} gitignore re-includes a secrets-bearing .storage file",
        )

    def test_run_sh_gitignore_covers_secrets(self):
        """run.sh gitignore should cover sensitive files."""
        content = read_file(os.path.join(ADDON_DIR, "run.sh"))
        entries = self._get_gitignore_entries(content)
        for req in ["secrets.yaml", ".mcp.json", ".bruh_claude/"]:
            self.assertIn(req, entries, f"run.sh gitignore missing: {req}")
        self._assert_storage_safely_excluded(entries, "run.sh")

    def test_backup_sh_gitignore_covers_secrets(self):
        """ha-backup.sh gitignore should cover sensitive files."""
        content = read_file(os.path.join(SCRIPTS_DIR, "ha-backup.sh"))
        entries = self._get_gitignore_entries(content)
        for req in ["secrets.yaml", ".mcp.json", ".bruh_claude/"]:
            self.assertIn(req, entries, f"ha-backup.sh gitignore missing: {req}")
        self._assert_storage_safely_excluded(entries, "ha-backup.sh")

    def test_gitignore_covers_databases(self):
        """Gitignore should exclude HA database files."""
        content = read_file(os.path.join(ADDON_DIR, "run.sh"))
        entries = self._get_gitignore_entries(content)
        db_patterns = ["*.db", "*.db-shm", "*.db-wal", "home-assistant_v2.db*"]
        for pattern in db_patterns:
            self.assertIn(pattern, entries, f"Missing db pattern: {pattern}")


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


class TestBackupWatcherUsesGitC(unittest.TestCase):
    """Test that ha-backup-watcher uses git -C instead of cd."""

    def test_no_cd_in_backup_watcher(self):
        """ha-backup-watcher should use git -C, not cd."""
        content = read_file(os.path.join(SCRIPTS_DIR, "ha-backup-watcher.sh"))
        # After fix: should not contain 'cd "$CONFIG_DIR"'
        self.assertNotIn('cd "$CONFIG_DIR"', content)
        # Should use git -C
        self.assertIn('git -C "$CONFIG_DIR"', content)


if __name__ == "__main__":
    unittest.main()
