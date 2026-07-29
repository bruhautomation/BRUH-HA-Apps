#!/usr/bin/env python3
"""
Tests for the BRain custom Home Assistant integration Python files.

Tests cover:
- __init__.py: service registration patterns, schema validation
- config_flow.py: flow step definitions, discovery handling
- conversation.py: entity attributes, language support
- bridge.py: source code analysis for blocking I/O patterns
- manifest.json: required fields and consistency
- services.yaml: service definition completeness
- strings.json / translations: completeness and consistency
"""

import json
import os
import re
import unittest

import yaml

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
INTEGRATION_DIR = os.path.join(
    BASE_DIR, "brain", "custom_components", "brain"
)


def read_file(path):
    with open(path, "r") as f:
        return f.read()


class TestManifestJson(unittest.TestCase):
    """Test manifest.json correctness."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(INTEGRATION_DIR, "manifest.json")) as f:
            cls.manifest = json.load(f)

    def test_required_fields(self):
        """Manifest must have all required fields."""
        required = [
            "domain", "name", "config_flow", "documentation",
            "version", "codeowners"
        ]
        for field in required:
            self.assertIn(field, self.manifest, f"Missing field: {field}")

    def test_domain_format(self):
        """Domain should be lowercase with underscores."""
        self.assertRegex(self.manifest["domain"], r'^[a-z][a-z0-9_]*$')

    def test_domain_is_brain(self):
        """Domain should be 'brain'."""
        self.assertEqual(self.manifest["domain"], "brain")

    def test_config_flow_enabled(self):
        """config_flow should be True."""
        self.assertTrue(self.manifest["config_flow"])

    def test_has_conversation_dependency(self):
        """Should depend on conversation component."""
        deps = self.manifest.get("dependencies", [])
        self.assertIn("conversation", deps)

    def test_has_hassio_after_dependency(self):
        """Should have hassio as after_dependency for discovery."""
        after = self.manifest.get("after_dependencies", [])
        self.assertIn("hassio", after)

    def test_version_format(self):
        """Version should be semver-like."""
        version = self.manifest["version"]
        parts = version.split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.isdigit())

    def test_integration_type(self):
        """integration_type should be 'service'."""
        self.assertEqual(self.manifest.get("integration_type"), "service")

    def test_iot_class(self):
        """Should have a valid iot_class."""
        valid_classes = [
            "assumed_state", "calculated", "cloud_polling", "cloud_push",
            "local_polling", "local_push"
        ]
        self.assertIn(self.manifest.get("iot_class"), valid_classes)

    def test_codeowners_format(self):
        """Codeowners should be GitHub handles starting with @."""
        for owner in self.manifest.get("codeowners", []):
            self.assertTrue(owner.startswith("@"),
                            f"Codeowner {owner} should start with @")


class TestServicesYaml(unittest.TestCase):
    """Test services.yaml definitions."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(INTEGRATION_DIR, "services.yaml")) as f:
            cls.services = yaml.safe_load(f)

    def test_send_prompt_defined(self):
        """send_prompt service should be defined."""
        self.assertIn("send_prompt", self.services)

    def test_run_task_defined(self):
        """run_task service should be defined."""
        self.assertIn("run_task", self.services)

    def test_send_prompt_has_prompt_field(self):
        """send_prompt should have a required prompt field."""
        fields = self.services["send_prompt"]["fields"]
        self.assertIn("prompt", fields)
        self.assertTrue(fields["prompt"].get("required"))

    def test_send_prompt_has_timeout_field(self):
        """send_prompt should have an optional timeout field."""
        fields = self.services["send_prompt"]["fields"]
        self.assertIn("timeout", fields)

    def test_run_task_has_prompt_field(self):
        """run_task should have a required prompt field."""
        fields = self.services["run_task"]["fields"]
        self.assertIn("prompt", fields)
        self.assertTrue(fields["prompt"].get("required"))

    def test_run_task_has_notify_field(self):
        """run_task should have a notify field."""
        fields = self.services["run_task"]["fields"]
        self.assertIn("notify", fields)

    def test_run_task_has_notify_entity_field(self):
        """run_task should have a notify_entity field."""
        fields = self.services["run_task"]["fields"]
        self.assertIn("notify_entity", fields)

    def test_all_services_have_name_and_description(self):
        """Every service should have a name and description."""
        for svc_name, svc_def in self.services.items():
            self.assertIn("name", svc_def, f"{svc_name} missing 'name'")
            self.assertIn("description", svc_def, f"{svc_name} missing 'description'")

    def test_timeout_min_max(self):
        """Timeout should have min 10 and max 600."""
        for svc_name in ["send_prompt", "run_task"]:
            timeout = self.services[svc_name]["fields"]["timeout"]
            selector = timeout["selector"]["number"]
            self.assertEqual(selector["min"], 10)
            self.assertEqual(selector["max"], 600)


class TestStringsJson(unittest.TestCase):
    """Test strings.json and translations consistency."""

    @classmethod
    def setUpClass(cls):
        with open(os.path.join(INTEGRATION_DIR, "strings.json")) as f:
            cls.strings = json.load(f)
        with open(os.path.join(INTEGRATION_DIR, "translations", "en.json")) as f:
            cls.translations = json.load(f)

    def test_strings_has_config_steps(self):
        """strings.json should have config steps.

        The config flow uses `first_setup` for the initial agent and
        `add_agent` for subsequent agents, plus `hassio_confirm` for
        discovery.
        """
        steps = self.strings.get("config", {}).get("step", {})
        self.assertIn("first_setup", steps)
        self.assertIn("add_agent", steps)
        self.assertIn("hassio_confirm", steps)

    def test_strings_has_errors(self):
        """strings.json should have error messages."""
        errors = self.strings.get("config", {}).get("error", {})
        self.assertIn("addon_not_running", errors)

    def test_strings_has_abort(self):
        """strings.json should have abort messages."""
        abort = self.strings.get("config", {}).get("abort", {})
        self.assertIn("already_configured", abort)

    def test_translations_match_strings(self):
        """translations/en.json should match strings.json."""
        self.assertEqual(self.strings, self.translations)

    def test_add_agent_step_has_timeout_data(self):
        """The add_agent config step should have a timeout data label."""
        data = self.strings["config"]["step"]["add_agent"].get("data", {})
        self.assertIn("timeout", data)

    def test_has_options_strings(self):
        """strings.json should have options step definitions."""
        options = self.strings.get("options", {})
        self.assertIn("step", options)
        self.assertIn("init", options["step"])
        init_step = options["step"]["init"]
        self.assertIn("data", init_step)
        self.assertIn("system_prompt", init_step["data"])
        self.assertIn("timeout", init_step["data"])

    def test_has_issues_with_fix_flow(self):
        """Issues should use fix_flow (not a separate repairs key) for fixable issues."""
        issues = self.strings.get("issues", {})
        self.assertIn("restart_required", issues)
        restart = issues["restart_required"]
        self.assertIn("fix_flow", restart,
                       "Fixable issue should use 'fix_flow', not a separate 'repairs' key")
        self.assertNotIn("description", restart,
                         "Fixable issues use 'fix_flow', not 'description' (they are mutually exclusive)")
        # Verify fix_flow has the confirm step
        steps = restart["fix_flow"]["step"]
        self.assertIn("confirm", steps)
        self.assertIn("title", steps["confirm"])
        self.assertIn("description", steps["confirm"])

    def test_no_separate_repairs_key(self):
        """strings.json should NOT have a top-level 'repairs' key."""
        self.assertNotIn("repairs", self.strings,
                         "Repair flow strings should be under issues.fix_flow, not a separate 'repairs' key")


class TestInitPy(unittest.TestCase):
    """Test __init__.py patterns."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(INTEGRATION_DIR, "__init__.py"))

    def test_has_async_setup_entry(self):
        """Should define async_setup_entry."""
        self.assertIn("async def async_setup_entry", self.content)

    def test_has_async_unload_entry(self):
        """Should define async_unload_entry."""
        self.assertIn("async def async_unload_entry", self.content)

    def test_registers_services(self):
        """Should register send_prompt and run_task services."""
        self.assertIn('"send_prompt"', self.content)
        self.assertIn('"run_task"', self.content)

    def test_uses_domain_constant(self):
        """Should import and use DOMAIN from const."""
        self.assertIn("from .const import", self.content)
        self.assertIn("DOMAIN", self.content)

    def test_conversation_platform(self):
        """Should forward to CONVERSATION platform."""
        self.assertIn("Platform.CONVERSATION", self.content)

    def test_service_guard_prevents_double_registration(self):
        """Services should only be registered once."""
        self.assertIn("has_service(DOMAIN", self.content)

    def test_schema_validates_timeout_range(self):
        """Timeout schema should enforce min 10 max 600."""
        self.assertIn("vol.Range(min=10, max=600)", self.content)

    def test_handles_timeout_error(self):
        """Service handlers should catch TimeoutError."""
        self.assertIn("except TimeoutError", self.content)

    def test_loaded_version_captured_at_import_time(self):
        """_LOADED_VERSION should be set at module level, not read from disk later."""
        self.assertIn("_LOADED_VERSION", self.content)
        # Should NOT read manifest from disk inside _check_restart_required
        self.assertNotIn(
            'await hass.async_add_executor_job(_read_json, manifest_path)',
            self.content,
            "_check_restart_required should use _LOADED_VERSION, not re-read manifest from disk"
        )

    def test_uses_loaded_version_for_comparison(self):
        """_check_restart_required should compare against _LOADED_VERSION."""
        # Find the _check_restart_required function and verify it uses _LOADED_VERSION
        self.assertIn("loaded_version = _LOADED_VERSION", self.content)

    def test_has_options_update_listener(self):
        """async_setup_entry should register an options update listener."""
        self.assertIn("add_update_listener", self.content)
        self.assertIn("_async_options_updated", self.content)

    def test_options_merged_with_data(self):
        """Entry options should be merged with entry.data for timeout."""
        self.assertIn("{**entry.data, **entry.options}", self.content)


class TestConfigFlowPy(unittest.TestCase):
    """Test config_flow.py patterns."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(INTEGRATION_DIR, "config_flow.py"))

    def test_has_user_step(self):
        """Should have async_step_user."""
        self.assertIn("async_step_user", self.content)

    def test_has_hassio_step(self):
        """Should have async_step_hassio for discovery."""
        self.assertIn("async_step_hassio", self.content)

    def test_has_hassio_confirm_step(self):
        """Should have async_step_hassio_confirm."""
        self.assertIn("async_step_hassio_confirm", self.content)

    def test_sets_unique_id(self):
        """Should call async_set_unique_id to prevent duplicates."""
        self.assertIn("async_set_unique_id", self.content)

    def test_abort_if_configured(self):
        """Should abort if already configured."""
        self.assertIn("_abort_if_unique_id_configured", self.content)

    def test_no_blocking_isdir(self):
        """os.path.isdir should use async_add_executor_job (after fix)."""
        # Find os.path.isdir calls that are NOT wrapped in executor
        # The call may span multiple lines (e.g., async_add_executor_job(\n os.path.isdir, ...))
        lines = self.content.split("\n")
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if "os.path.isdir" in stripped and "async_add_executor_job" not in stripped:
                # Check surrounding context for multi-line executor call
                context_start = max(0, i - 3)
                prev_context = "\n".join(lines[context_start:i])
                if "async_add_executor_job" in prev_context:
                    continue  # Part of a multi-line executor call, safe

                # This is only a problem if it's inside an async function
                for j in range(i - 1, max(0, i - 20), -1):
                    if "async def" in lines[j - 1]:
                        self.fail(
                            f"Line {i}: os.path.isdir used directly in async "
                            f"function without async_add_executor_job"
                        )
                        break
                    elif "def " in lines[j - 1] and "async" not in lines[j - 1]:
                        break  # In a sync function, that's fine

    def test_handles_hassio_service_info(self):
        """Should handle both dict and HassioServiceInfo discovery info."""
        self.assertIn("HassioServiceInfo", self.content)
        self.assertIn("isinstance(discovery_info", self.content)

    def test_has_options_flow_handler(self):
        """Should define an OptionsFlow handler class."""
        self.assertIn("class BruhClaudeOptionsFlowHandler", self.content)

    def test_options_flow_registered(self):
        """ConfigFlow should register the options flow via async_get_options_flow."""
        self.assertIn("async_get_options_flow", self.content)
        self.assertIn("BruhClaudeOptionsFlowHandler", self.content)

    def test_options_flow_has_init_step(self):
        """Options flow should have async_step_init."""
        self.assertIn("async_step_init", self.content)

    def test_options_flow_merges_data_and_options(self):
        """Options flow should merge entry.data with entry.options for defaults."""
        self.assertIn("{**self._config_entry.data, **self._config_entry.options}", self.content)


class TestConversationPy(unittest.TestCase):
    """Test conversation.py patterns."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(INTEGRATION_DIR, "conversation.py"))

    def test_has_conversation_entity(self):
        """Should define a ConversationEntity subclass."""
        self.assertIn("class BruhClaudeConversationEntity(ConversationEntity)", self.content)

    def test_has_async_process(self):
        """Should implement async_process."""
        self.assertIn("async def async_process", self.content)

    def test_supported_languages_wildcard(self):
        """Should support all languages with '*'."""
        self.assertIn('return "*"', self.content)

    def test_has_unique_id(self):
        """Entity should set unique_id."""
        self.assertIn("_attr_unique_id", self.content)

    def test_handles_timeout(self):
        """Should handle TimeoutError gracefully."""
        self.assertIn("except TimeoutError", self.content)

    def test_handles_generic_exception(self):
        """Should handle unexpected exceptions."""
        self.assertIn("except Exception", self.content)

    def test_returns_conversation_result(self):
        """Should return ConversationResult."""
        self.assertIn("return ConversationResult", self.content)

    def test_no_double_conversion_of_conversation_id(self):
        """conversation_id should not be converted empty->None redundantly."""
        # After fix: should use user_input.conversation_id directly
        self.assertNotIn('conversation_id or ""', self.content)

    def test_reads_system_prompt_from_options(self):
        """Conversation entity should merge entry.options with entry.data for system_prompt."""
        self.assertIn("{**config_entry.data, **config_entry.options}", self.content)


class TestSensorPy(unittest.TestCase):
    """Test sensor.py patterns."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(INTEGRATION_DIR, "sensor.py"))

    def test_dispatcher_handler_is_callback(self):
        """The insight sensor's dispatcher handler must be a @callback.

        async_dispatcher_connect schedules an undecorated sync target as an
        executor job (HassJobType.Executor), so async_write_ha_state() would
        run off the event loop and trip HA's thread-safety guard. Decorating
        the handler with @callback keeps it on the loop.
        """
        # @callback must immediately precede the dispatcher handler def
        self.assertRegex(
            self.content,
            r"@callback\s+def _handle_update",
            "sensor._handle_update must be decorated with @callback",
        )

    def test_imports_callback(self):
        """callback must be imported from homeassistant.core."""
        self.assertRegex(
            self.content,
            r"from homeassistant\.core import [^\n]*\bcallback\b",
        )


class TestBridgePy(unittest.TestCase):
    """Test bridge.py patterns."""

    @classmethod
    def setUpClass(cls):
        cls.content = read_file(os.path.join(INTEGRATION_DIR, "bridge.py"))

    def test_uses_monotonic_clock(self):
        """Polling should use monotonic clock for timeout accuracy."""
        self.assertIn("time.monotonic", self.content)

    def test_atomic_write_pattern(self):
        """Should use tmp + os.replace for atomic writes."""
        self.assertIn("os.replace(tmp, path)", self.content)

    def test_handles_corrupt_json(self):
        """Should handle JSONDecodeError separately from OSError."""
        self.assertIn("except json.JSONDecodeError", self.content)

    def test_removes_corrupt_files(self):
        """Corrupt response files should be removed to prevent infinite retry."""
        # After fix, the JSONDecodeError handler should remove the file
        json_decode_section = self.content[
            self.content.index("except json.JSONDecodeError"):
            self.content.index("except OSError", self.content.index("except json.JSONDecodeError"))
        ]
        self.assertIn("os.remove(path)", json_decode_section)

    def test_poll_interval_defined(self):
        """POLL_INTERVAL should be defined."""
        self.assertIn("POLL_INTERVAL", self.content)

    def test_uses_async_add_executor_job(self):
        """File I/O should use async_add_executor_job."""
        self.assertIn("async_add_executor_job", self.content)

    def test_available_property_exists(self):
        """Bridge should have an 'available' property."""
        self.assertIn("def available", self.content)


class TestManifestConfigVersionSync(unittest.TestCase):
    """Test version consistency between manifest.json and config.yaml."""

    def test_versions_match(self):
        """manifest.json version should match config.yaml version."""
        with open(os.path.join(INTEGRATION_DIR, "manifest.json")) as f:
            manifest = json.load(f)

        config_path = os.path.join(
            os.path.dirname(__file__), "..", "brain", "config.yaml"
        )
        with open(config_path) as f:
            config = yaml.safe_load(f)

        self.assertEqual(
            manifest["version"], config["version"],
            "manifest.json and config.yaml versions should match"
        )


if __name__ == "__main__":
    unittest.main()
