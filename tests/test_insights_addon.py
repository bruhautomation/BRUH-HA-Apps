#!/usr/bin/env python3
"""Tests for the BRUH Insights add-on.

Covers:
- config.yaml / build.yaml / Dockerfile validity and cross-file consistency
- category definitions and prompt building
- credential storage + classification (claude_client)
- insight JSON extraction from model replies
- headless claude invocation via a stub binary
- panel server routes (status, generate validation, insight storage)
"""

import asyncio
import importlib
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "bruh-insights"
PANEL_DIR = ADDON_DIR / "panel"

sys.path.insert(0, str(PANEL_DIR))

import categories  # noqa: E402
import claude_client  # noqa: E402
import prompt_store  # noqa: E402


class TestInsightsConfigYaml(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(ADDON_DIR / "config.yaml") as f:
            cls.config = yaml.safe_load(f)

    def test_required_fields(self):
        for field in ("name", "version", "slug", "arch", "startup"):
            self.assertIn(field, self.config)

    def test_slug_format(self):
        self.assertRegex(self.config["slug"], r"^[a-z][a-z0-9_]*$")

    def test_version_semver(self):
        parts = self.config["version"].split(".")
        self.assertEqual(len(parts), 3)
        for part in parts:
            self.assertTrue(part.isdigit())

    def test_ingress(self):
        self.assertTrue(self.config["ingress"])
        self.assertEqual(self.config["ingress_port"], 8099)
        self.assertTrue(self.config.get("panel_title"))
        self.assertTrue(str(self.config.get("panel_icon", "")).startswith("mdi:"))

    def test_api_access(self):
        self.assertTrue(self.config["hassio_api"])
        self.assertTrue(self.config["homeassistant_api"])

    def test_options_schema_parity(self):
        options = self.config.get("options", {})
        schema = self.config.get("schema", {})
        self.assertEqual(set(options), set(schema))

    def test_config_map_read_only(self):
        """The HA config mount must stay read-only for this add-on."""
        for entry in self.config.get("map", []):
            if isinstance(entry, dict) and entry.get("type") == "homeassistant_config":
                self.assertTrue(entry.get("read_only"))
                return
        self.fail("homeassistant_config mapping missing")

    def test_architectures(self):
        self.assertIn("amd64", self.config["arch"])
        self.assertIn("aarch64", self.config["arch"])


class TestInsightsBuildFiles(unittest.TestCase):
    def test_build_yaml(self):
        with open(ADDON_DIR / "build.yaml") as f:
            build = yaml.safe_load(f)
        self.assertIn("aarch64", build["build_from"])
        self.assertIn("amd64", build["build_from"])

    def test_dockerfile_references_exist(self):
        dockerfile = (ADDON_DIR / "Dockerfile").read_text()
        self.assertIn("COPY panel/ /opt/panel/", dockerfile)
        self.assertIn("COPY run.sh /run.sh", dockerfile)
        self.assertIn("@anthropic-ai/claude-code", dockerfile)
        for name in ("run.sh", "panel/server.py", "panel/index.html",
                     "panel/app.js", "panel/style.css", "panel/favicon.svg",
                     "panel/categories.py", "panel/ha_data.py",
                     "panel/claude_client.py", "icon.png", "logo.png",
                     "README.md", "DOCS.md", "CHANGELOG.md"):
            self.assertTrue((ADDON_DIR / name).exists(), f"missing {name}")

    def test_run_sh_shebang(self):
        first = (ADDON_DIR / "run.sh").read_text().splitlines()[0]
        self.assertEqual(first, "#!/usr/bin/with-contenv bashio")

    def test_changelog_mentions_current_version(self):
        with open(ADDON_DIR / "config.yaml") as f:
            version = yaml.safe_load(f)["version"]
        self.assertIn(version, (ADDON_DIR / "CHANGELOG.md").read_text())


class TestCategories(unittest.TestCase):
    def test_unique_ids_and_required_keys(self):
        ids = [c["id"] for c in categories.CATEGORIES]
        self.assertEqual(len(ids), len(set(ids)))
        for cat in categories.CATEGORIES:
            for key in ("id", "title", "icon", "description", "domains",
                        "device_classes", "history", "stats", "focus"):
                self.assertIn(key, cat, f"{cat.get('id')} missing {key}")

    def test_get_category(self):
        self.assertIsNotNone(categories.get_category("energy"))
        self.assertIsNone(categories.get_category("nope"))

    def test_system_prompt_contract(self):
        sp = categories.SYSTEM_PROMPT
        for needle in ('"title"', '"summary"', '"highlights"', '"html"',
                       "#2a78d6", "#1a1a19", "prefers-color-scheme",
                       "prefers-reduced-motion", "ONE y-axis"):
            self.assertIn(needle, sp)

    def test_build_prompt_category(self):
        bundle = {"meta": {"now": "2026-07-18T12:00:00"}, "entities": []}
        prompt = categories.build_prompt(categories.CATEGORIES[0], bundle)
        self.assertIn("INSIGHT CATEGORY", prompt)
        self.assertIn('"2026-07-18T12:00:00"', prompt)

    def test_build_prompt_question(self):
        prompt = categories.build_prompt(
            categories.CATEGORIES[0], {"entities": []}, question="How cold is it?")
        self.assertIn("QUESTION: How cold is it?", prompt)
        self.assertNotIn("INSIGHT CATEGORY", prompt)


class TestClaudeClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (claude_client.SECRETS_DIR, claude_client.AUTH_FILE,
                     claude_client.CLAUDE_HOME)
        claude_client.SECRETS_DIR = self.tmp.name
        claude_client.AUTH_FILE = os.path.join(self.tmp.name, "claude_auth.json")
        claude_client.CLAUDE_HOME = os.path.join(self.tmp.name, "home")

    def tearDown(self):
        (claude_client.SECRETS_DIR, claude_client.AUTH_FILE,
         claude_client.CLAUDE_HOME) = self._old
        self.tmp.cleanup()

    def _write_cli_credentials(self, token="sk-ant-oat01-" + "x" * 30):
        cred_dir = os.path.join(claude_client.CLAUDE_HOME, ".claude")
        os.makedirs(cred_dir, exist_ok=True)
        with open(os.path.join(cred_dir, ".credentials.json"), "w") as f:
            json.dump({"claudeAiOauth": {"accessToken": token}}, f)

    def test_classify(self):
        self.assertEqual(claude_client.classify_credential("sk-ant-oat01-abc"), "oauth_token")
        self.assertEqual(claude_client.classify_credential("sk-ant-api03-xyz"), "api_key")
        self.assertIsNone(claude_client.classify_credential("hunter2"))

    def test_save_get_clear_roundtrip(self):
        self.assertIsNone(claude_client.get_auth())
        claude_client.save_auth("sk-ant-oat01-" + "a" * 30)
        auth = claude_client.get_auth()
        self.assertEqual(auth["type"], "oauth_token")
        mode = stat.S_IMODE(os.stat(claude_client.AUTH_FILE).st_mode)
        self.assertEqual(mode, 0o600)
        claude_client.clear_auth()
        self.assertIsNone(claude_client.get_auth())

    def test_save_rejects_garbage(self):
        with self.assertRaises(ValueError):
            claude_client.save_auth("not-a-token")

    def test_extract_json_plain(self):
        obj = claude_client.extract_json('{"title": "T", "html": "<p>x</p>"}')
        self.assertEqual(obj["title"], "T")

    def test_extract_json_fenced(self):
        obj = claude_client.extract_json('```json\n{"title": "T"}\n```')
        self.assertEqual(obj["title"], "T")

    def test_extract_json_embedded(self):
        obj = claude_client.extract_json('Here you go:\n{"title": "T"}\nEnjoy!')
        self.assertEqual(obj["title"], "T")

    def test_extract_json_invalid(self):
        self.assertIsNone(claude_client.extract_json("no json here"))

    def test_extract_oauth_url_single_line(self):
        url = ("https://claude.ai/oauth/authorize?code=true&client_id=abc"
               "&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback"
               "&code_challenge=xyz")
        buf = f"Browse to the following URL:\n{url}\nPaste code here if prompted:"
        self.assertEqual(claude_client.extract_oauth_url(buf), url)

    def test_extract_oauth_url_stitches_wrapped_lines(self):
        """A pty hard-wraps the long authorize URL; fragments must be rejoined."""
        full = ("https://claude.ai/oauth/authorize?code=true&client_id=abcdef123456"
                "&response_type=code"
                "&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback"
                "&scope=org%3Acreate_api_key&code_challenge=AbCdEf&state=XyZ")
        wrapped = "\n".join([full[i:i + 60] for i in range(0, len(full), 60)])
        buf = f"Browse to the following URL:\n{wrapped}\n\nPaste code here if prompted:"
        self.assertEqual(claude_client.extract_oauth_url(buf), full)

    def test_extract_oauth_url_rejects_truncated(self):
        """A bare origin with no query string is a wrap artifact, not a link."""
        buf = "Browse to the following URL:\nhttps://claude.ai/oauth/authorize\n"
        self.assertEqual(claude_client.extract_oauth_url(buf), "")

    def test_extract_oauth_url_does_not_glue_prose(self):
        url = "https://claude.ai/oauth/authorize?code=true&client_id=abc&redirect_uri=x"
        buf = f"{url}\nPaste code here if prompted:"
        self.assertEqual(claude_client.extract_oauth_url(buf), url)

    def test_token_regex_accepts_future_prefixes(self):
        self.assertTrue(claude_client.OAUTH_TOKEN_RE.search("sk-ant-oat01-" + "a" * 24))
        self.assertTrue(claude_client.OAUTH_TOKEN_RE.search("sk-ant-oat05-" + "b" * 24))
        self.assertFalse(claude_client.OAUTH_TOKEN_RE.search("sk-ant-api03-" + "c" * 24))

    def test_setup_flow_retry_after_failed_exchange(self):
        """Failed code exchange: CLI prints 'OAuth error…Press Enter to retry.'
        and blocks; the flow must press Enter, loop to awaiting_code, and pick
        up the FRESH URL (new state) while ignoring the stale one."""
        flow = claude_client.SetupTokenFlow()
        read_fd, write_fd = os.pipe()
        try:
            old_url = ("https://claude.ai/oauth/authorize?code=true&client_id=a"
                       "&redirect_uri=r&state=OLD")
            new_url = ("https://claude.ai/oauth/authorize?code=true&client_id=a"
                       "&redirect_uri=r&state=NEWSTATE")
            buf = (f"Use the url below to sign in\n{old_url}\n"
                   "Paste code here if prompted >\n")
            flow.phase = "starting"
            flow._scan(buf)
            self.assertEqual(flow.phase, "awaiting_code")
            self.assertEqual(flow.url, old_url)

            # user submits a bad code (simulate the state transition)
            flow.phase = "working"
            flow._fd = write_fd
            flow._code_from = len(buf)
            flow._code_sent_at = 1.0
            buf += "OAuth error: Request failed with status code 400Press Enter to retry."
            flow.output = buf
            flow._scan(buf)
            self.assertEqual(flow.phase, "starting")
            self.assertIn("OAuth error", flow.error)
            self.assertIn("fresh sign-in link", flow.error)
            self.assertEqual(flow.url, "")
            self.assertEqual(os.read(read_fd, 10), b"\r")  # Enter was pressed

            # CLI mints a fresh URL; the stale one must not be re-surfaced
            buf += f"Retrying…\n{new_url}\nPaste code here if prompted >\n"
            flow.output = buf
            flow._scan(buf)
            self.assertEqual(flow.phase, "awaiting_code")
            self.assertEqual(flow.url, new_url)
        finally:
            os.close(read_fd)
            os.close(write_fd)
            flow._fd = None

    def test_cli_credentials_detected_as_auth(self):
        self.assertIsNone(claude_client.get_auth())
        self._write_cli_credentials()
        auth = claude_client.get_auth()
        self.assertEqual(auth["type"], "cli_login")
        # CLI-managed login must not inject env tokens
        env = claude_client._claude_env()
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        # logout must also forget the CLI credential
        claude_client.clear_auth()
        self.assertIsNone(claude_client.get_auth())

    def test_cli_credentials_ignores_bad_file(self):
        cred_dir = os.path.join(claude_client.CLAUDE_HOME, ".claude")
        os.makedirs(cred_dir, exist_ok=True)
        with open(os.path.join(cred_dir, ".credentials.json"), "w") as f:
            f.write("not json")
        self.assertIsNone(claude_client.get_auth())

    def test_setup_flow_credentials_file_completes_working_phase(self):
        """Some CLI versions save the credential without printing a token —
        the appearing credentials file must count as sign-in success."""
        flow = claude_client.SetupTokenFlow()
        flow.phase = "working"
        flow._code_from = 0
        self._write_cli_credentials()
        flow._scan("some output without a token or retry prompt")
        self.assertEqual(flow.phase, "done")

    def test_setup_flow_status_masks_token_in_detail(self):
        flow = claude_client.SetupTokenFlow()
        flow.output = "some line\nyour token: sk-ant-oat01-" + "z" * 30
        status = flow.status()
        self.assertIn("detail", status)
        self.assertNotIn("z" * 30, status["detail"])

    def test_setup_flow_watchdog_fires_on_silent_hang(self):
        """A code exchange that produces NO output must still time out —
        the watchdog runs on idle select ticks, not only when output arrives."""
        stub = Path(self.tmp.name) / "claude-hang"
        stub.write_text(
            "#!/bin/bash\n"
            "echo 'Use the url below to sign in'\n"
            "echo 'https://claude.ai/oauth/authorize?code=true&client_id=x&redirect_uri=y&state=z'\n"
            "echo 'Paste code here if prompted >'\n"
            "read -r line\n"
            "sleep 600\n"
        )
        stub.chmod(0o755)
        old_argv = claude_client._claude_argv
        old_timeout = claude_client.EXCHANGE_TIMEOUT
        old_nudges = claude_client.NUDGE_TIMES
        claude_client._claude_argv = lambda: [str(stub)]
        claude_client.EXCHANGE_TIMEOUT = 5
        claude_client.NUDGE_TIMES = (2, 3)
        flow = claude_client.SetupTokenFlow()
        try:
            flow.start()
            for _ in range(40):
                if flow.status()["phase"] == "awaiting_code":
                    break
                time.sleep(0.25)
            self.assertEqual(flow.status()["phase"], "awaiting_code")
            flow.submit_code("some-code#state")
            deadline = time.time() + 15
            while time.time() < deadline:
                if flow.status()["phase"] == "error":
                    break
                time.sleep(0.25)
            status = flow.status()
            self.assertEqual(status["phase"], "error", status)
            self.assertIn("Timed out exchanging the code", status["error"])
        finally:
            flow.cancel()
            claude_client._claude_argv = old_argv
            claude_client.EXCHANGE_TIMEOUT = old_timeout
            claude_client.NUDGE_TIMES = old_nudges

    def test_run_claude_with_stub(self):
        stub = Path(self.tmp.name) / "claude"
        envelope = {"type": "result", "result": '{"title":"T"}',
                    "is_error": False, "duration_ms": 12, "num_turns": 1}
        stub.write_text("#!/bin/sh\ncat > /dev/null\necho '%s'\n" % json.dumps(envelope))
        stub.chmod(0o755)
        orig = claude_client._claude_argv
        claude_client._claude_argv = lambda: [str(stub)]
        try:
            result = claude_client.run_claude("prompt", "system", timeout=20)
        finally:
            claude_client._claude_argv = orig
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], '{"title":"T"}')
        self.assertEqual(result["meta"]["duration_ms"], 12)

    def test_run_claude_error_envelope(self):
        stub = Path(self.tmp.name) / "claude"
        stub.write_text("#!/bin/sh\ncat > /dev/null\n"
                        "echo '{\"type\":\"result\",\"is_error\":true,\"result\":\"boom\"}'\n")
        stub.chmod(0o755)
        orig = claude_client._claude_argv
        claude_client._claude_argv = lambda: [str(stub)]
        try:
            result = claude_client.run_claude("p", "s", timeout=20)
        finally:
            claude_client._claude_argv = orig
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])


class TestPanelServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_dir = self.server.INSIGHTS_DIR
        self.server.INSIGHTS_DIR = Path(self.tmp.name)

    def tearDown(self):
        self.server.INSIGHTS_DIR = self._old_dir
        self.tmp.cleanup()

    def test_insight_path_rejects_traversal(self):
        from aiohttp import web
        for bad in ("../etc", "a/b", "UPPER", ".hidden", ""):
            with self.assertRaises(web.HTTPBadRequest):
                self.server._insight_path(bad)

    def test_save_and_load_insights(self):
        self.server.save_insight({
            "id": "energy", "category": "energy", "title": "T",
            "generated_at": "2026-07-18T10:00:00", "html": "<p></p>",
        })
        loaded = self.server.load_insights()
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], "energy")

    def test_custom_insight_cap(self):
        for i in range(self.server.MAX_CUSTOM_KEPT + 4):
            self.server.save_insight({
                "id": f"custom-{1000 + i}", "category": "custom", "title": "T",
                "generated_at": f"2026-07-18T10:00:{i:02d}", "html": "",
            })
        files = list(Path(self.tmp.name).glob("custom-*.json"))
        self.assertLessEqual(len(files), self.server.MAX_CUSTOM_KEPT)

    def test_http_routes(self):
        from aiohttp.test_utils import TestClient, TestServer

        async def run():
            app = self.server.make_app()
            client = TestClient(TestServer(app))
            await client.start_server()
            try:
                resp = await client.get("/api/status")
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertIn("categories", data)
                self.assertEqual(
                    [c["id"] for c in data["categories"]],
                    [c["id"] for c in categories.CATEGORIES],
                )

                resp = await client.post("/api/generate", json={"category": "bogus"})
                self.assertEqual(resp.status, 400)

                resp = await client.post("/api/generate", json={"question": "x" * 600})
                self.assertEqual(resp.status, 400)

                resp = await client.get("/api/insights")
                self.assertEqual(resp.status, 200)

                resp = await client.get("/")
                self.assertEqual(resp.status, 200)
                text = await resp.text()
                self.assertIn("BRUH", text)
                self.assertNotIn("{{VERSION}}", text)

                resp = await client.get("/api/health")
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())

    def test_generate_queue_dedup(self):
        async def run():
            # fresh queue for isolation
            self.server.QUEUE = asyncio.Queue()
            self.server.JOBS.clear()
            self.assertTrue(self.server._enqueue("energy"))
            self.assertFalse(self.server._enqueue("energy"))
            self.assertEqual(self.server.QUEUE.qsize(), 1)

        asyncio.run(run())
        self.server.JOBS.clear()


class TestSharedAuth(unittest.TestCase):
    """Shared-credential fallback (written by the BRUH Terminal add-on)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (claude_client.SECRETS_DIR, claude_client.AUTH_FILE,
                     claude_client.CLAUDE_HOME, claude_client.SHARED_AUTH_FILE)
        claude_client.SECRETS_DIR = self.tmp.name
        claude_client.AUTH_FILE = os.path.join(self.tmp.name, "claude_auth.json")
        claude_client.CLAUDE_HOME = os.path.join(self.tmp.name, "home")
        claude_client.SHARED_AUTH_FILE = os.path.join(self.tmp.name, "shared_auth.json")

    def tearDown(self):
        (claude_client.SECRETS_DIR, claude_client.AUTH_FILE,
         claude_client.CLAUDE_HOME, claude_client.SHARED_AUTH_FILE) = self._old
        self.tmp.cleanup()

    def _write_shared(self, payload):
        with open(claude_client.SHARED_AUTH_FILE, "w") as f:
            if isinstance(payload, str):
                f.write(payload)
            else:
                json.dump(payload, f)

    def test_shared_auth_picked_up(self):
        token = "sk-ant-oat01-" + "s" * 30
        self._write_shared({"type": "oauth_token", "value": token, "saved_at": 1752000000})
        auth = claude_client.get_auth()
        self.assertEqual(auth["type"], "oauth_token")
        self.assertEqual(auth["value"], token)
        self.assertEqual(auth["source"], "shared")
        env = claude_client._claude_env()
        self.assertEqual(env.get("CLAUDE_CODE_OAUTH_TOKEN"), token)
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_shared_api_key_injected_as_api_key(self):
        key = "sk-ant-api03-" + "k" * 30
        self._write_shared({"type": "api_key", "value": key, "saved_at": 1752000000})
        env = claude_client._claude_env()
        self.assertEqual(env.get("ANTHROPIC_API_KEY"), key)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)

    def test_local_wins_over_shared(self):
        local = "sk-ant-oat01-" + "l" * 30
        claude_client.save_auth(local)
        self._write_shared({"type": "oauth_token", "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})
        auth = claude_client.get_auth()
        self.assertEqual(auth["value"], local)
        self.assertEqual(auth["source"], "local")

    def test_source_reported_for_local(self):
        claude_client.save_auth("sk-ant-oat01-" + "a" * 30)
        self.assertEqual(claude_client.get_auth()["source"], "local")

    def test_malformed_shared_tolerated(self):
        for payload in ("not json", ["a", "b"],
                        {"type": "weird", "value": "x"},
                        {"type": "oauth_token", "value": ""},
                        {"type": "oauth_token", "value": 42},
                        {"value": "sk-ant-oat01-zzz"}):
            self._write_shared(payload)
            self.assertIsNone(claude_client.get_auth(), payload)

    def test_missing_shared_tolerated(self):
        self.assertIsNone(claude_client.get_auth())

    def test_logout_leaves_shared_file_intact(self):
        claude_client.save_auth("sk-ant-oat01-" + "l" * 30)
        self._write_shared({"type": "oauth_token", "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})
        claude_client.clear_auth()
        self.assertTrue(os.path.exists(claude_client.SHARED_AUTH_FILE))
        # after logout, the shared credential takes over again
        auth = claude_client.get_auth()
        self.assertEqual(auth["source"], "shared")

    def test_status_reports_auth_source(self):
        from aiohttp.test_utils import TestClient, TestServer
        server = importlib.import_module("server")
        old_dir = server.INSIGHTS_DIR
        server.INSIGHTS_DIR = Path(self.tmp.name) / "insights"
        # fresh queue so the app worker never awaits a queue bound to a
        # previous test's event loop
        server.QUEUE = asyncio.Queue()
        # keep the startup auth check from invoking a real claude binary
        old_validate = claude_client.validate_auth
        claude_client.validate_auth = lambda timeout=120: {"ok": True, "error": ""}
        self._write_shared({"type": "oauth_token", "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})

        async def run():
            client = TestClient(TestServer(server.make_app()))
            await client.start_server()
            try:
                resp = await client.get("/api/status")
                data = await resp.json()
                self.assertTrue(data["authenticated"])
                self.assertEqual(data["auth_source"], "shared")
            finally:
                await client.close()

        try:
            asyncio.run(run())
        finally:
            server.INSIGHTS_DIR = old_dir
            claude_client.validate_auth = old_validate


class TestPromptStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = prompt_store.OVERRIDES_FILE
        prompt_store.OVERRIDES_FILE = os.path.join(self.tmp.name, "prompt_overrides.json")

    def tearDown(self):
        prompt_store.OVERRIDES_FILE = self._old
        self.tmp.cleanup()

    def test_defaults_without_overrides(self):
        eff = prompt_store.effective_category("energy")
        self.assertEqual(eff["focus"], categories.get_category("energy")["focus"])
        self.assertTrue(eff["enabled"])
        self.assertIsNone(eff["refresh_hours"])
        self.assertEqual(eff["overridden"], [])

    def test_merge_and_persist(self):
        prompt_store.save_override("energy", {"focus": "Watch the dryer", "refresh_hours": 3})
        eff = prompt_store.effective_category("energy")
        self.assertEqual(eff["focus"], "Watch the dryer")
        self.assertEqual(eff["refresh_hours"], 3)
        self.assertIn("focus", eff["overridden"])
        self.assertIn("refresh_hours", eff["overridden"])
        # non-overridden fields keep shipped values
        self.assertEqual(eff["domains"], categories.get_category("energy")["domains"])
        # persisted on disk, not just in memory
        with open(prompt_store.OVERRIDES_FILE) as f:
            stored = json.load(f)
        self.assertEqual(stored["categories"]["energy"]["focus"], "Watch the dryer")

    def test_none_clears_single_field(self):
        prompt_store.save_override("energy", {"focus": "X", "enabled": False})
        prompt_store.save_override("energy", {"focus": None})
        eff = prompt_store.effective_category("energy")
        self.assertEqual(eff["focus"], categories.get_category("energy")["focus"])
        self.assertFalse(eff["enabled"])

    def test_reset_override(self):
        prompt_store.save_override("energy", {"focus": "X", "enabled": False})
        prompt_store.reset_override("energy")
        eff = prompt_store.effective_category("energy")
        self.assertEqual(eff["overridden"], [])
        self.assertTrue(eff["enabled"])

    def test_unknown_category(self):
        self.assertIsNone(prompt_store.effective_category("nope"))

    def test_corrupt_file_tolerated(self):
        with open(prompt_store.OVERRIDES_FILE, "w") as f:
            f.write("not json")
        self.assertEqual(prompt_store.load_overrides(), {"categories": {}})
        self.assertTrue(prompt_store.effective_category("energy")["enabled"])


class InsightsServerCase(unittest.TestCase):
    """Shared fixture: isolated insight dir, overrides file, queue and jobs."""

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")
        cls.ha_data = importlib.import_module("ha_data")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_dir = self.server.INSIGHTS_DIR
        self._old_overrides = prompt_store.OVERRIDES_FILE
        self._old_inbox = self.server.MEMORY_INBOX_DIR
        self.server.INSIGHTS_DIR = Path(self.tmp.name)
        # NOT inside INSIGHTS_DIR — mirrors production (/data vs /data/insights)
        prompt_store.OVERRIDES_FILE = os.path.join(
            self.tmp.name, "overrides", "prompt_overrides.json")
        self.server.MEMORY_INBOX_DIR = Path(self.tmp.name) / "memory-inbox"
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        self.server.INSIGHTS_DIR = self._old_dir
        prompt_store.OVERRIDES_FILE = self._old_overrides
        self.server.MEMORY_INBOX_DIR = self._old_inbox
        self.server.JOBS.clear()
        self.tmp.cleanup()

    def _save(self, insight_id, generated_at, **extra):
        insight = {"id": insight_id, "category": insight_id, "title": f"T {generated_at}",
                   "generated_at": generated_at, "html": "<p>x</p>"}
        insight.update(extra)
        self.server.save_insight(insight)
        return insight

    def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        return TestClient(TestServer(self.server.make_app()))


class TestInsightHistory(InsightsServerCase):
    def test_history_copy_written_and_invisible_to_load(self):
        self._save("energy", "2026-07-18T10:00:00")
        run_file = Path(self.tmp.name) / "history" / "energy" / "2026-07-18T10-00-00.json"
        self.assertTrue(run_file.exists())
        # load_insights must not see the history subdir
        loaded = self.server.load_insights()
        self.assertEqual([i["id"] for i in loaded], ["energy"])

    def test_custom_cards_excluded_from_history(self):
        self._save("custom-1234", "2026-07-18T10:00:00", category="custom")
        self.assertFalse((Path(self.tmp.name) / "history" / "custom-1234").exists())

    def test_bad_stamp_skipped(self):
        self._save("energy", "garbage")
        self.assertFalse((Path(self.tmp.name) / "history" / "energy").exists())

    def test_history_disabled_by_zero(self):
        old = self.server.HISTORY_KEEP_RUNS
        self.server.HISTORY_KEEP_RUNS = 0
        try:
            self._save("energy", "2026-07-18T10:00:00")
        finally:
            self.server.HISTORY_KEEP_RUNS = old
        self.assertFalse((Path(self.tmp.name) / "history" / "energy").exists())

    def test_prune_keeps_newest_runs(self):
        old = self.server.HISTORY_KEEP_RUNS
        self.server.HISTORY_KEEP_RUNS = 3
        try:
            for i in range(6):
                self._save("energy", f"2026-07-18T10:00:{i:02d}")
        finally:
            self.server.HISTORY_KEEP_RUNS = old
        files = sorted(p.stem for p in
                       (Path(self.tmp.name) / "history" / "energy").glob("*.json"))
        self.assertEqual(files, ["2026-07-18T10-00-03", "2026-07-18T10-00-04",
                                 "2026-07-18T10-00-05"])

    def test_prune_drops_runs_older_than_keep_days(self):
        self._save("energy", "2020-01-01T00:00:00")
        self._save("energy", "2026-07-18T10:00:00")
        stems = [p.stem for p in
                 (Path(self.tmp.name) / "history" / "energy").glob("*.json")]
        self.assertEqual(stems, ["2026-07-18T10-00-00"])

    def test_history_endpoints(self):
        self._save("energy", "2026-07-18T09:00:00")
        self._save("energy", "2026-07-18T10:00:00")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.get("/api/insight/energy/history")
                self.assertEqual(resp.status, 200)
                runs = (await resp.json())["runs"]
                self.assertEqual([r["ts"] for r in runs],
                                 ["2026-07-18T10-00-00", "2026-07-18T09-00-00"])
                for r in runs:
                    self.assertNotIn("html", r)
                    self.assertTrue(r["title"])

                resp = await client.get("/api/insight/energy/history/2026-07-18T09-00-00")
                self.assertEqual(resp.status, 200)
                full = await resp.json()
                self.assertEqual(full["generated_at"], "2026-07-18T09:00:00")
                self.assertIn("html", full)

                # bad ids / stamps rejected before touching the filesystem
                resp = await client.get("/api/insight/UPPER/history")
                self.assertEqual(resp.status, 400)
                resp = await client.get("/api/insight/energy/history/..%2F..%2Fetc")
                self.assertEqual(resp.status, 400)
                resp = await client.get("/api/insight/energy/history/2026-07-18T99-99")
                self.assertEqual(resp.status, 400)
                resp = await client.get("/api/insight/energy/history/2026-01-01T00-00-00")
                self.assertEqual(resp.status, 404)

                resp = await client.delete("/api/insight/energy/history/2026-07-18T09-00-00")
                self.assertEqual(resp.status, 200)
                resp = await client.get("/api/insight/energy/history")
                runs = (await resp.json())["runs"]
                self.assertEqual([r["ts"] for r in runs], ["2026-07-18T10-00-00"])
                resp = await client.delete("/api/insight/energy/history/2026-07-18T09-00-00")
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())


class TestPromptEndpoints(InsightsServerCase):
    def test_prompts_roundtrip(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.get("/api/prompts")
                self.assertEqual(resp.status, 200)
                prompts = {p["id"]: p for p in (await resp.json())["prompts"]}
                self.assertEqual(prompts["energy"]["focus"],
                                 categories.get_category("energy")["focus"])
                self.assertEqual(prompts["energy"]["overridden"], [])

                resp = await client.put("/api/prompt/energy", json={
                    "focus": "Watch the dryer", "refresh_hours": 3})
                self.assertEqual(resp.status, 200)
                rec = await resp.json()
                self.assertEqual(rec["focus"], "Watch the dryer")
                self.assertEqual(rec["refresh_hours"], 3)
                self.assertIn("focus", rec["overridden"])

                # reflected in /api/status categories
                resp = await client.get("/api/status")
                cats = {c["id"]: c for c in (await resp.json())["categories"]}
                self.assertEqual(cats["energy"]["focus"], "Watch the dryer")
                self.assertTrue(cats["energy"]["focus_overridden"])
                self.assertEqual(cats["energy"]["default_focus"],
                                 categories.get_category("energy")["focus"])
                self.assertEqual(cats["energy"]["refresh_hours"], 3)

                # empty focus clears the focus override
                resp = await client.put("/api/prompt/energy", json={"focus": ""})
                rec = await resp.json()
                self.assertNotIn("focus", rec["overridden"])
                self.assertEqual(rec["refresh_hours"], 3)

                # validation
                resp = await client.put("/api/prompt/bogus", json={"focus": "x"})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/prompt/energy", json={"refresh_hours": 999})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/prompt/energy", json={"focus": 42})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/prompt/energy", json={"enabled": "yes"})
                self.assertEqual(resp.status, 400)

                # reset restores defaults
                resp = await client.delete("/api/prompt/energy")
                rec = await resp.json()
                self.assertEqual(rec["overridden"], [])
                self.assertIsNone(rec["refresh_hours"])
            finally:
                await client.close()

        asyncio.run(run())

    def test_generate_all_skips_disabled(self):
        prompt_store.save_override("energy", {"enabled": False})
        old_generate = self.server._generate

        async def noop_generate(insight_id):
            self.server._set_job(insight_id, state="done", error="")

        self.server._generate = noop_generate

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/generate_all")
                queued = (await resp.json())["queued"]
                self.assertNotIn("energy", queued)
                self.assertIn("climate", queued)
            finally:
                await client.close()

        try:
            asyncio.run(run())
        finally:
            self.server._generate = old_generate

    def test_refresh_due_logic(self):
        due = self.server._refresh_due
        now = time.mktime(time.strptime("2026-07-18T12:00:00", "%Y-%m-%dT%H:%M:%S"))
        base = {"enabled": True, "refresh_hours": None}
        # global default (6h in tests' env-free import) applies when no override
        self.assertFalse(due({**base, "enabled": False}, "", now))
        self.assertTrue(due({**base, "refresh_hours": 1}, "2026-07-18T10:00:00", now))
        self.assertFalse(due({**base, "refresh_hours": 6}, "2026-07-18T10:00:00", now))
        self.assertFalse(due({**base, "refresh_hours": 0}, "2020-01-01T00:00:00", now))
        # missing or unparseable timestamps count as ancient
        self.assertTrue(due({**base, "refresh_hours": 1}, "", now))
        self.assertTrue(due({**base, "refresh_hours": 1}, "garbage", now))


class TestGenerateFlow(InsightsServerCase):
    """_generate end-to-end with stubbed collection + Claude + HA services."""

    def setUp(self):
        super().setUp()
        self._old_collect = self.ha_data.collect_bundle
        self._old_run = claude_client.run_claude
        self._old_service = self.ha_data.call_service

        async def fake_bundle(cat, days, question=None):
            self.bundle_focus = cat.get("focus")
            return {"meta": {"now": "2026-07-18T12:00:00"}, "entities": []}

        self.ha_data.collect_bundle = fake_bundle
        self.reply = {
            "title": "Dryer watch", "summary": "S.",
            "highlights": [{"label": "Loads", "value": "3"}],
            "questions": ["Is the garage fridge meant to run overnight?", "  ", 42],
            "findings": ["Hall sensor drops offline at 2 AM", ""],
            "html": "<!DOCTYPE html><p>ok</p>",
        }
        claude_client.run_claude = lambda *a, **k: {
            "ok": True, "text": json.dumps(self.reply), "error": "",
            "meta": {"duration_ms": 5}}

    def tearDown(self):
        self.ha_data.collect_bundle = self._old_collect
        claude_client.run_claude = self._old_run
        self.ha_data.call_service = self._old_service
        super().tearDown()

    def _stored(self, insight_id="energy"):
        with open(Path(self.tmp.name) / f"{insight_id}.json") as f:
            return json.load(f)

    def test_generate_uses_override_and_persists_new_fields(self):
        prompt_store.save_override("energy", {"focus": "Watch the dryer"})
        calls = []

        async def ok_service(service, data):
            calls.append((service, data))

        self.ha_data.call_service = ok_service
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(self.server.JOBS["energy"]["state"],
                         "done", self.server.JOBS["energy"])
        self.assertEqual(self.bundle_focus, "Watch the dryer")
        stored = self._stored()
        self.assertEqual(stored["focus_used"], "Watch the dryer")
        self.assertEqual(stored["questions"],
                         ["Is the garage fridge meant to run overnight?"])
        self.assertEqual(stored["findings"], ["Hall sensor drops offline at 2 AM"])
        # findings handed to bruh_claude.add_memory
        self.assertEqual(calls, [("add_memory", {
            "fact": "Hall sensor drops offline at 2 AM",
            "source": "insights", "confidence": "medium"})])
        # no fallback writes when the service worked
        self.assertFalse(self.server.MEMORY_INBOX_DIR.exists())

    def test_findings_fall_back_to_share_inbox(self):
        async def broken_service(service, data):
            raise RuntimeError("integration not installed")

        self.ha_data.call_service = broken_service
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(self.server.JOBS["energy"]["state"], "done")
        files = list(self.server.MEMORY_INBOX_DIR.glob("*-insights.jsonl"))
        self.assertEqual(len(files), 1)
        lines = [json.loads(l) for l in files[0].read_text().splitlines()]
        self.assertEqual(lines[0]["fact"], "Hall sensor drops offline at 2 AM")
        self.assertEqual(lines[0]["source"], "insights")
        self.assertEqual(lines[0]["confidence"], "medium")
        self.assertIsInstance(lines[0]["ts"], int)

    def test_missing_optional_fields_default_empty(self):
        self.reply.pop("questions")
        self.reply.pop("findings")
        asyncio.run(self.server._generate("energy"))
        stored = self._stored()
        self.assertEqual(stored["questions"], [])
        self.assertEqual(stored["findings"], [])


class TestQuestionsEndpoints(InsightsServerCase):
    def setUp(self):
        super().setUp()
        self._old_service = self.ha_data.call_service
        self.calls = []

        async def ok_service(service, data):
            self.calls.append((service, data))

        self.ha_data.call_service = ok_service

    def tearDown(self):
        self.ha_data.call_service = self._old_service
        super().tearDown()

    def test_questions_listed_and_answered(self):
        self._save("energy", "2026-07-18T10:00:00",
                   category_title="Energy", questions=["Is X on purpose?"])

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.get("/api/questions")
                qs = (await resp.json())["questions"]
                self.assertEqual(qs, [{"insight_id": "energy",
                                       "category_title": "Energy",
                                       "question": "Is X on purpose?"}])

                resp = await client.post("/api/questions/answer", json={
                    "insight_id": "energy", "question": "Is X on purpose?",
                    "answer": "Yes, it runs the pond pump."})
                self.assertEqual(resp.status, 200)
                self.assertEqual(self.calls, [("answer_question", {
                    "question": "Is X on purpose?",
                    "answer": "Yes, it runs the pond pump.",
                    "source": "insights"})])

                # the question stops surfacing
                resp = await client.get("/api/questions")
                self.assertEqual((await resp.json())["questions"], [])
                with open(Path(self.tmp.name) / "energy.json") as f:
                    self.assertEqual(json.load(f)["questions"], [])

                # unknown question / insight and bad bodies
                resp = await client.post("/api/questions/answer", json={
                    "insight_id": "energy", "question": "Is X on purpose?",
                    "answer": "again"})
                self.assertEqual(resp.status, 404)
                resp = await client.post("/api/questions/answer", json={
                    "insight_id": "nope", "question": "q", "answer": "a"})
                self.assertEqual(resp.status, 404)
                resp = await client.post("/api/questions/answer", json={
                    "insight_id": "energy", "question": "", "answer": "a"})
                self.assertEqual(resp.status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_answer_falls_back_to_share_inbox(self):
        self._save("energy", "2026-07-18T10:00:00", questions=["Why cold?"])

        async def broken_service(service, data):
            raise RuntimeError("no integration")

        self.ha_data.call_service = broken_service

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/questions/answer", json={
                    "insight_id": "energy", "question": "Why cold?",
                    "answer": "Broken vent."})
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        files = list(self.server.MEMORY_INBOX_DIR.glob("*-insights.jsonl"))
        self.assertEqual(len(files), 1)
        fact = json.loads(files[0].read_text().splitlines()[0])["fact"]
        self.assertEqual(fact, "Q: Why cold? → A: Broken vent.")


class TestMemoryContext(unittest.TestCase):
    """memory.md feeds the bundle context and outlives raw entity rows."""

    @classmethod
    def setUpClass(cls):
        cls.ha_data = importlib.import_module("ha_data")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (self.ha_data.CONTEXT_FILE, self.ha_data.MEMORY_FILE)
        self.ha_data.CONTEXT_FILE = os.path.join(self.tmp.name, "CLAUDE.md")
        self.ha_data.MEMORY_FILE = os.path.join(self.tmp.name, "memory.md")

    def tearDown(self):
        (self.ha_data.CONTEXT_FILE, self.ha_data.MEMORY_FILE) = self._old
        self.tmp.cleanup()

    def _write(self, path, text):
        with open(path, "w") as f:
            f.write(text)

    def test_memory_prepended_before_claude_md(self):
        self._write(self.ha_data.MEMORY_FILE, "# Memory\nThe pond pump runs at night.")
        self._write(self.ha_data.CONTEXT_FILE, "# Home\nNaming conventions here.")
        ctx = self.ha_data._read_context()
        self.assertLess(ctx.index("pond pump"), ctx.index("Naming conventions"))

    def test_missing_memory_file_fine(self):
        self._write(self.ha_data.CONTEXT_FILE, "# Home\nJust CLAUDE.md.")
        self.assertIn("Just CLAUDE.md.", self.ha_data._read_context())

    def test_no_files_no_context(self):
        self.assertEqual(self.ha_data._read_context(), "")

    def test_total_budget_capped(self):
        self._write(self.ha_data.MEMORY_FILE, "m" * 10_000)
        self._write(self.ha_data.CONTEXT_FILE, "c" * 10_000)
        ctx = self.ha_data._read_context()
        self.assertLessEqual(len(ctx), self.ha_data.CONTEXT_CHARS + 2)

    def test_shrink_trims_entities_before_context(self):
        big = "n" * 3000
        bundle = {
            "entities": [{"e": f"sensor.x{i}", "n": big} for i in range(60)],
            "context": "learned facts",
        }
        out = self.ha_data._shrink_to_budget(bundle)
        self.assertEqual(out["context"], "learned facts")
        self.assertLess(len(out["entities"]), 50)

    def test_shrink_drops_context_only_as_last_resort(self):
        big = "n" * 3000
        bundle = {
            "entities": [{"e": f"sensor.x{i}", "n": big} for i in range(20)],
            "context": "c" * 70_000,
        }
        out = self.ha_data._shrink_to_budget(bundle)
        self.assertNotIn("context", out)
        self.assertEqual(len(out["entities"]), 20)


if __name__ == "__main__":
    unittest.main()
