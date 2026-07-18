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


if __name__ == "__main__":
    unittest.main()
