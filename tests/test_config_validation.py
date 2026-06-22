#!/usr/bin/env python3
"""
Tests for validating the add-on configuration files.

Tests cover:
- config.yaml structure and schema validity
- build.yaml correctness
- repository.yaml format
- Dockerfile structure
- Script file permissions and shebangs
- Cross-file consistency (referenced files exist, etc.)
"""

import os
import yaml
import json
import unittest

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
ADDON_DIR = os.path.join(BASE_DIR, "bruh-claude-terminal")


class TestConfigYaml(unittest.TestCase):
    """Test config.yaml validity."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "config.yaml"), "r") as f:
            cls.config = yaml.safe_load(f)

    def test_required_fields_present(self):
        """config.yaml must have all required HA add-on fields."""
        required = ["name", "version", "slug", "arch", "startup"]
        for field in required:
            self.assertIn(field, self.config, f"Missing required field: {field}")

    def test_slug_format(self):
        """Slug should be lowercase with underscores."""
        slug = self.config["slug"]
        self.assertRegex(slug, r"^[a-z][a-z0-9_]*$", f"Invalid slug format: {slug}")

    def test_version_format(self):
        """Version should be semver-like."""
        version = self.config["version"]
        parts = version.split(".")
        self.assertEqual(len(parts), 3, f"Version should be x.y.z: {version}")
        for part in parts:
            self.assertTrue(part.isdigit(), f"Version part not numeric: {part}")

    def test_architectures(self):
        """Should support at least amd64 and aarch64."""
        arches = self.config["arch"]
        self.assertIn("amd64", arches)
        self.assertIn("aarch64", arches)

    def test_ingress_configuration(self):
        """Ingress must be properly configured."""
        self.assertTrue(self.config.get("ingress"))
        self.assertEqual(self.config.get("ingress_port"), 7681)

    def test_api_access(self):
        """API access flags should be set."""
        self.assertTrue(self.config.get("hassio_api"))
        self.assertTrue(self.config.get("homeassistant_api"))
        self.assertTrue(self.config.get("auth_api"))

    def test_options_have_schema(self):
        """Every option should have a corresponding schema entry."""
        options = self.config.get("options", {})
        schema = self.config.get("schema", {})

        for key in options:
            self.assertIn(key, schema, f"Option '{key}' missing from schema")

    def test_schema_has_options(self):
        """Every schema entry should have a corresponding option."""
        options = self.config.get("options", {})
        schema = self.config.get("schema", {})

        for key in schema:
            self.assertIn(key, options, f"Schema '{key}' missing from options")

    def test_panel_configuration(self):
        """Panel should be configured for admin."""
        self.assertTrue(self.config.get("panel_admin"))
        self.assertIsNotNone(self.config.get("panel_icon"))
        self.assertIsNotNone(self.config.get("panel_title"))

    def test_map_includes_config(self):
        """Volume map should include config:rw."""
        maps = self.config.get("map", [])
        self.assertIn("config:rw", maps)

    def test_startup_type(self):
        """Startup should be 'services'."""
        self.assertEqual(self.config.get("startup"), "services")

    def test_default_option_types(self):
        """Default option values should match their schema types."""
        options = self.config.get("options", {})

        bool_options = [
            "auto_launch_claude", "auto_backup", "auto_generate_context",
            "enable_ha_mcp_server", "enable_assist_integration",
            "enable_automation_integration", "enable_mobile_ui"
        ]
        for opt in bool_options:
            self.assertIsInstance(options.get(opt), bool, f"{opt} should be bool")

        self.assertIsInstance(options.get("backup_interval_minutes"), int)
        self.assertIsInstance(options.get("persistent_apk_packages"), list)
        self.assertIsInstance(options.get("persistent_pip_packages"), list)


class TestBuildYaml(unittest.TestCase):
    """Test build.yaml validity."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "build.yaml"), "r") as f:
            cls.build = yaml.safe_load(f)

    def test_build_from_present(self):
        """build_from must define base images."""
        self.assertIn("build_from", self.build)

    def test_architectures_match_config(self):
        """build.yaml architectures should match config.yaml."""
        with open(os.path.join(ADDON_DIR, "config.yaml"), "r") as f:
            config = yaml.safe_load(f)

        config_arches = set(config.get("arch", []))
        build_arches = set(self.build.get("build_from", {}).keys())

        self.assertEqual(config_arches, build_arches,
                         f"Architecture mismatch: config={config_arches}, build={build_arches}")

    def test_base_images_are_ha_images(self):
        """Base images should be official HA base images."""
        for arch, image in self.build.get("build_from", {}).items():
            self.assertIn("ghcr.io/home-assistant/", image,
                          f"Image for {arch} should be an official HA base image")

    def test_labels_present(self):
        """OCI labels should be present."""
        labels = self.build.get("labels", {})
        self.assertIn("org.opencontainers.image.title", labels)
        self.assertIn("org.opencontainers.image.description", labels)


class TestRepositoryYaml(unittest.TestCase):
    """Test repository.yaml validity."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(BASE_DIR, "repository.yaml"), "r") as f:
            cls.repo = yaml.safe_load(f)

    def test_required_fields(self):
        """Repository must have name, url, maintainer."""
        self.assertIn("name", self.repo)
        self.assertIn("url", self.repo)
        self.assertIn("maintainer", self.repo)

    def test_url_format(self):
        """URL should start with https://."""
        url = self.repo.get("url", "")
        self.assertTrue(url.startswith("https://"), f"URL should use HTTPS: {url}")


class TestDockerfile(unittest.TestCase):
    """Test Dockerfile structure."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "Dockerfile"), "r") as f:
            cls.content = f.read()
            cls.lines = cls.content.strip().split("\n")

    def test_starts_with_arg_build_from(self):
        """Dockerfile should start with ARG BUILD_FROM."""
        self.assertTrue(self.lines[0].startswith("ARG BUILD_FROM"))

    def test_uses_build_from(self):
        """Dockerfile should use BUILD_FROM as base."""
        self.assertIn("FROM ${BUILD_FROM}", self.content)

    def test_installs_required_packages(self):
        """Required system packages should be installed."""
        required_packages = ["bash", "curl", "nodejs", "npm", "python3", "git", "jq", "tmux", "ttyd"]
        for pkg in required_packages:
            self.assertIn(pkg, self.content, f"Missing required package: {pkg}")

    def test_installs_claude_cli(self):
        """Claude CLI should be installed.

        The Dockerfile installs Claude Code via npm; the package ships a
        native musl binary that needs posix_getdents (musl 1.2.6), which is
        why the base image is Alpine 3.24+.
        """
        self.assertIn("@anthropic-ai/claude-code", self.content)
        self.assertIn("npm install -g", self.content)

    def test_copies_run_sh(self):
        """run.sh should be copied."""
        self.assertIn("COPY run.sh /run.sh", self.content)

    def test_copies_scripts(self):
        """Scripts should be copied."""
        self.assertIn("COPY scripts/ /opt/scripts/", self.content)

    def test_copies_mcp_server(self):
        """MCP server should be copied."""
        self.assertIn("COPY ha-mcp-server/ /opt/ha-mcp-server/", self.content)

    def test_copies_integrations(self):
        """Integrations should be copied."""
        self.assertIn("COPY integrations/ /opt/integrations/", self.content)

    def test_sets_permissions(self):
        """Scripts should be made executable."""
        self.assertIn("chmod +x /run.sh", self.content)

    def test_cmd_is_run_sh(self):
        """CMD should be run.sh in exec form."""
        self.assertIn('CMD ["/run.sh"]', self.content)

    def test_workdir_is_config(self):
        """WORKDIR should be /config."""
        self.assertIn("WORKDIR /config", self.content)

    def test_no_expose_instruction(self):
        """EXPOSE is not needed for HA add-ons (managed by config.yaml)."""
        for line in self.lines:
            stripped = line.strip()
            self.assertFalse(
                stripped.startswith("EXPOSE"),
                "HA add-ons should not use EXPOSE (port managed by config.yaml)"
            )


class TestFileExistence(unittest.TestCase):
    """Test that all referenced files actually exist."""

    def test_addon_files_exist(self):
        """Core add-on files should exist."""
        required_files = [
            "config.yaml",
            "build.yaml",
            "Dockerfile",
            "run.sh",
            "README.md",
            "CHANGELOG.md",
            "DOCS.md",
        ]
        for f in required_files:
            path = os.path.join(ADDON_DIR, f)
            self.assertTrue(os.path.isfile(path), f"Missing file: {f}")

    def test_script_files_exist(self):
        """All script files should exist."""
        expected_scripts = [
            "claude-auth-helper.sh",
            "claude-session-picker.sh",
            "ha-api-examples.sh",
            "ha-backup.sh",
            "ha-backup-watcher.sh",
            "ha-context-gen.sh",
            "ha-log.sh",
            "ha-reload.sh",
            "ha-yaml-check.sh",
            "health-check.sh",
            "persist-install.sh",
            "tmux.conf",
        ]
        scripts_dir = os.path.join(ADDON_DIR, "scripts")
        for script in expected_scripts:
            path = os.path.join(scripts_dir, script)
            self.assertTrue(os.path.isfile(path), f"Missing script: {script}")

    def test_mcp_server_exists(self):
        """MCP server file should exist."""
        path = os.path.join(ADDON_DIR, "ha-mcp-server", "ha_mcp_server.py")
        self.assertTrue(os.path.isfile(path))

    def test_integration_files_exist(self):
        """Integration files should exist."""
        expected = ["assist-listener.sh", "automation-listener.sh"]
        integrations_dir = os.path.join(ADDON_DIR, "integrations")
        for f in expected:
            path = os.path.join(integrations_dir, f)
            self.assertTrue(os.path.isfile(path), f"Missing integration: {f}")

    def test_repo_root_files_exist(self):
        """Root repository files should exist."""
        expected = [
            "repository.yaml",
            ".gitignore",
            "LICENSE",
            "README.md",
            "CLAUDE.md",
        ]
        for f in expected:
            path = os.path.join(BASE_DIR, f)
            self.assertTrue(os.path.isfile(path), f"Missing root file: {f}")


class TestScriptShebangs(unittest.TestCase):
    """Test that shell scripts have correct shebangs."""

    def _get_shell_scripts(self):
        """Get all .sh files in the add-on."""
        scripts = []
        for dirpath, _, filenames in os.walk(ADDON_DIR):
            for f in filenames:
                if f.endswith(".sh"):
                    scripts.append(os.path.join(dirpath, f))
        return scripts

    def test_all_scripts_have_shebangs(self):
        """Every .sh file should start with a shebang line."""
        for script in self._get_shell_scripts():
            with open(script, "r") as f:
                first_line = f.readline().strip()
            self.assertTrue(
                first_line.startswith("#!"),
                f"Missing shebang in {os.path.basename(script)}: got '{first_line}'"
            )

    def test_shebangs_are_valid(self):
        """Shebangs should use valid interpreters."""
        valid_shebangs = [
            "#!/bin/bash",
            "#!/usr/bin/env bash",
            "#!/usr/bin/with-contenv bashio",
            "#!/usr/bin/env python3",
        ]
        for script in self._get_shell_scripts():
            with open(script, "r") as f:
                first_line = f.readline().strip()
            self.assertIn(
                first_line, valid_shebangs,
                f"Invalid shebang in {os.path.basename(script)}: '{first_line}'"
            )

    def test_run_sh_uses_bashio(self):
        """run.sh must use bashio shebang."""
        with open(os.path.join(ADDON_DIR, "run.sh"), "r") as f:
            first_line = f.readline().strip()
        self.assertEqual(first_line, "#!/usr/bin/with-contenv bashio")


class TestMCPServerPython(unittest.TestCase):
    """Test MCP server Python file quality."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(ADDON_DIR, "ha-mcp-server", "ha_mcp_server.py"), "r") as f:
            cls.content = f.read()

    def test_no_unused_imports(self):
        """Check for commonly unused imports."""
        # asyncio was previously unused - verify it's removed
        import_lines = [l for l in self.content.split("\n") if l.startswith("import ")]
        import_names = [l.split()[-1] for l in import_lines]
        self.assertNotIn("asyncio", import_names, "asyncio import is unused")

    def test_has_main_guard(self):
        """Should have if __name__ == '__main__' guard."""
        self.assertIn('if __name__ == "__main__":', self.content)

    def test_handles_all_tool_names(self):
        """Every defined tool must be registered in TOOL_IMPLEMENTATIONS."""
        import re
        # Get tool names from TOOLS list only (between TOOLS = [ and the registry)
        tools_section = self.content[self.content.index("TOOLS = ["):self.content.index("TOOL_IMPLEMENTATIONS = {")]
        tool_names = re.findall(r'"name":\s*"([^"]+)"', tools_section)
        self.assertGreater(len(tool_names), 0)
        # Get the registry mapping
        registry_start = self.content.index("TOOL_IMPLEMENTATIONS = {")
        registry_section = self.content[registry_start:self.content.index("}", registry_start)]
        for name in tool_names:
            self.assertIn(
                f'"{name}":',
                registry_section,
                f"Tool '{name}' not registered in TOOL_IMPLEMENTATIONS"
            )


class TestCrossFileConsistency(unittest.TestCase):
    """Test consistency between files."""

    def test_dockerfile_copies_match_directories(self):
        """Directories copied in Dockerfile should exist."""
        dirs_to_check = [
            ("scripts/", os.path.join(ADDON_DIR, "scripts")),
            ("ha-mcp-server/", os.path.join(ADDON_DIR, "ha-mcp-server")),
            ("integrations/", os.path.join(ADDON_DIR, "integrations")),
        ]
        for copy_path, actual_path in dirs_to_check:
            self.assertTrue(
                os.path.isdir(actual_path),
                f"Dockerfile copies {copy_path} but directory doesn't exist"
            )

    def test_run_sh_references_existing_scripts(self):
        """Scripts referenced in run.sh should exist."""
        with open(os.path.join(ADDON_DIR, "run.sh"), "r") as f:
            content = f.read()

        scripts_dir = os.path.join(ADDON_DIR, "scripts")
        # Find /opt/scripts/ references
        import re
        refs = re.findall(r'/opt/scripts/([a-zA-Z0-9_.-]+\.sh)', content)
        for ref in refs:
            path = os.path.join(scripts_dir, ref)
            self.assertTrue(os.path.isfile(path), f"run.sh references {ref} but it doesn't exist")

    def test_config_version_matches_changelog(self):
        """Version in config.yaml should appear in CHANGELOG.md."""
        with open(os.path.join(ADDON_DIR, "config.yaml"), "r") as f:
            config = yaml.safe_load(f)
        version = config["version"]

        with open(os.path.join(ADDON_DIR, "CHANGELOG.md"), "r") as f:
            changelog = f.read()

        self.assertIn(version, changelog,
                      f"Version {version} not found in CHANGELOG.md")


if __name__ == "__main__":
    unittest.main()
