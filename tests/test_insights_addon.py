#!/usr/bin/env python3
"""Tests for the brAIn add-on.

Covers:
- config.yaml / build.yaml / Dockerfile validity and cross-file consistency
- category definitions and prompt building
- credential storage + classification (engine)
- insight JSON extraction from model replies
- headless claude invocation via a stub binary
- panel server routes (status, generate validation, insight storage)
"""

import asyncio
import datetime
import importlib
import json
import os
import stat
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON_DIR = BASE_DIR / "brain"
PANEL_DIR = ADDON_DIR / "panel"

sys.path.insert(0, str(PANEL_DIR))

import categories  # noqa: E402
import engine  # noqa: E402
import feedback_store  # noqa: E402
import hypotheses  # noqa: E402
import onboarding  # noqa: E402
import card_tags  # noqa: E402
import findings_store  # noqa: E402
import knowledge_store  # noqa: E402
import prompt_store  # noqa: E402
import settings_store  # noqa: E402
import usage_store  # noqa: E402
import user_categories  # noqa: E402


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

    def test_config_map_writable_for_memory(self):
        """/config is writable since 1.3.1 — solely so the panel's Memory
        editor can maintain /config/.brain/memory/memory.md. Server
        code must never write anywhere else under /config."""
        for entry in self.config.get("map", []):
            if isinstance(entry, dict) and entry.get("type") == "homeassistant_config":
                self.assertFalse(entry.get("read_only"))
                return
        self.fail("homeassistant_config mapping missing")

    def test_architectures(self):
        self.assertIn("amd64", self.config["arch"])
        self.assertIn("aarch64", self.config["arch"])

    def test_only_the_terminal_port_is_published(self):
        """Cards go through HA's own /local mirror, and the panel is reached
        via ingress — the single published port is ttyd, for direct access."""
        self.assertEqual(list(self.config["ports"]), ["7681/tcp"])
        self.assertIn("7681/tcp", self.config["ports_description"])


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
                     "panel/engine.py", "panel/prompt_store.py",
                     "panel/settings_store.py", "panel/addon_options.py",
                     "panel/user_categories.py", "panel/feedback_store.py",
                     "panel/knowledge_store.py",
                     "icon.png", "logo.png",
                     "README.md", "DOCS.md", "CHANGELOG.md"):
            self.assertTrue((ADDON_DIR / name).exists(), f"missing {name}")

    def test_run_sh_shebang(self):
        first = (ADDON_DIR / "run.sh").read_text().splitlines()[0]
        self.assertEqual(first, "#!/usr/bin/with-contenv bashio")

    def test_changelog_mentions_current_version(self):
        with open(ADDON_DIR / "config.yaml") as f:
            version = yaml.safe_load(f)["version"]
        self.assertIn(version, (ADDON_DIR / "CHANGELOG.md").read_text())


class TestModelChoices(unittest.TestCase):
    """The ⚙ dialog's model dropdown (1.8.0)."""

    def test_shape_and_uniqueness(self):
        ids = [m["id"] for m in engine.MODEL_CHOICES]
        self.assertEqual(len(ids), len(set(ids)), "duplicate model id")
        for choice in engine.MODEL_CHOICES:
            for key in ("id", "group", "label", "hint"):
                self.assertIn(key, choice, f"{choice.get('id')} missing {key}")
            self.assertTrue(choice["label"].strip())
            # ids go straight onto `claude --model`, and into an add-on
            # option capped at MAX_MODEL_CHARS
            self.assertLessEqual(len(choice["id"]), 100)
            self.assertEqual(choice["id"], choice["id"].strip())

    def test_default_choice_is_first_and_empty(self):
        """"" is what the dropdown lands on when no model is configured."""
        self.assertEqual(engine.MODEL_CHOICES[0]["id"], "")

    def test_groups_are_contiguous(self):
        """The panel opens a new <optgroup> whenever the group changes, so a
        group that reappears later would render twice."""
        seen = []
        for choice in engine.MODEL_CHOICES:
            if not seen or seen[-1] != choice["group"]:
                self.assertNotIn(choice["group"], seen, "group is split up")
                seen.append(choice["group"])

    def test_offers_a_current_model_per_tier(self):
        ids = {m["id"] for m in engine.MODEL_CHOICES}
        for expected in ("opus", "sonnet", "haiku", "claude-opus-5",
                         "claude-sonnet-5", "claude-haiku-4-5"):
            self.assertIn(expected, ids)


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

    def test_system_prompt_requests_tags(self):
        self.assertIn('"tags"', categories.SYSTEM_PROMPT)

    def test_build_prompt_feedback_injected(self):
        prompt = categories.build_prompt(
            categories.CATEGORIES[0], {"entities": []},
            feedback=["Show costs in dollars", "  ", ""])
        self.assertIn("HOMEOWNER FEEDBACK", prompt)
        self.assertIn("- Show costs in dollars", prompt)

    def test_build_prompt_no_feedback_block_when_empty(self):
        for feedback in (None, [], ["", "  "]):
            prompt = categories.build_prompt(
                categories.CATEGORIES[0], {"entities": []}, feedback=feedback)
            self.assertNotIn("HOMEOWNER FEEDBACK", prompt)


class TestClaudeClient(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (engine.SECRETS_DIR, engine.AUTH_FILE,
                     engine.CLAUDE_HOME)
        engine.SECRETS_DIR = self.tmp.name
        engine.AUTH_FILE = os.path.join(self.tmp.name, "claude_auth.json")
        engine.CLAUDE_HOME = os.path.join(self.tmp.name, "home")

    def tearDown(self):
        (engine.SECRETS_DIR, engine.AUTH_FILE,
         engine.CLAUDE_HOME) = self._old
        self.tmp.cleanup()

    def _write_cli_credentials(self, token="sk-ant-oat01-" + "x" * 30):
        cred_dir = os.path.join(engine.CLAUDE_HOME, ".claude")
        os.makedirs(cred_dir, exist_ok=True)
        with open(os.path.join(cred_dir, ".credentials.json"), "w") as f:
            json.dump({"claudeAiOauth": {"accessToken": token}}, f)

    def test_classify(self):
        self.assertEqual(engine.classify_credential("sk-ant-oat01-abc"), "oauth_token")
        self.assertEqual(engine.classify_credential("sk-ant-api03-xyz"), "api_key")
        self.assertIsNone(engine.classify_credential("hunter2"))

    def test_save_get_clear_roundtrip(self):
        self.assertIsNone(engine.get_auth())
        engine.save_auth("sk-ant-oat01-" + "a" * 30)
        auth = engine.get_auth()
        self.assertEqual(auth["type"], "oauth_token")
        mode = stat.S_IMODE(os.stat(engine.AUTH_FILE).st_mode)
        self.assertEqual(mode, 0o600)
        engine.clear_auth()
        self.assertIsNone(engine.get_auth())

    def test_save_rejects_garbage(self):
        with self.assertRaises(ValueError):
            engine.save_auth("not-a-token")

    def test_extract_json_plain(self):
        obj = engine.extract_json('{"title": "T", "html": "<p>x</p>"}')
        self.assertEqual(obj["title"], "T")

    def test_extract_json_fenced(self):
        obj = engine.extract_json('```json\n{"title": "T"}\n```')
        self.assertEqual(obj["title"], "T")

    def test_extract_json_embedded(self):
        obj = engine.extract_json('Here you go:\n{"title": "T"}\nEnjoy!')
        self.assertEqual(obj["title"], "T")

    def test_extract_json_invalid(self):
        self.assertIsNone(engine.extract_json("no json here"))

    def test_extract_oauth_url_single_line(self):
        url = ("https://claude.ai/oauth/authorize?code=true&client_id=abc"
               "&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback"
               "&code_challenge=xyz")
        buf = f"Browse to the following URL:\n{url}\nPaste code here if prompted:"
        self.assertEqual(engine.extract_oauth_url(buf), url)

    def test_extract_oauth_url_stitches_wrapped_lines(self):
        """A pty hard-wraps the long authorize URL; fragments must be rejoined."""
        full = ("https://claude.ai/oauth/authorize?code=true&client_id=abcdef123456"
                "&response_type=code"
                "&redirect_uri=https%3A%2F%2Fconsole.anthropic.com%2Foauth%2Fcode%2Fcallback"
                "&scope=org%3Acreate_api_key&code_challenge=AbCdEf&state=XyZ")
        wrapped = "\n".join([full[i:i + 60] for i in range(0, len(full), 60)])
        buf = f"Browse to the following URL:\n{wrapped}\n\nPaste code here if prompted:"
        self.assertEqual(engine.extract_oauth_url(buf), full)

    def test_extract_oauth_url_rejects_truncated(self):
        """A bare origin with no query string is a wrap artifact, not a link."""
        buf = "Browse to the following URL:\nhttps://claude.ai/oauth/authorize\n"
        self.assertEqual(engine.extract_oauth_url(buf), "")

    def test_extract_oauth_url_does_not_glue_prose(self):
        url = "https://claude.ai/oauth/authorize?code=true&client_id=abc&redirect_uri=x"
        buf = f"{url}\nPaste code here if prompted:"
        self.assertEqual(engine.extract_oauth_url(buf), url)

    def test_token_regex_accepts_future_prefixes(self):
        self.assertTrue(engine.OAUTH_TOKEN_RE.search("sk-ant-oat01-" + "a" * 24))
        self.assertTrue(engine.OAUTH_TOKEN_RE.search("sk-ant-oat05-" + "b" * 24))
        self.assertFalse(engine.OAUTH_TOKEN_RE.search("sk-ant-api03-" + "c" * 24))

    def test_setup_flow_retry_after_failed_exchange(self):
        """Failed code exchange: CLI prints 'OAuth error…Press Enter to retry.'
        and blocks; the flow must press Enter, loop to awaiting_code, and pick
        up the FRESH URL (new state) while ignoring the stale one."""
        flow = engine.SetupTokenFlow()
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
        self.assertIsNone(engine.get_auth())
        self._write_cli_credentials()
        auth = engine.get_auth()
        self.assertEqual(auth["type"], "cli_login")
        # CLI-managed login must not inject env tokens
        env = engine._claude_env()
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        # logout must also forget the CLI credential
        engine.clear_auth()
        self.assertIsNone(engine.get_auth())

    def test_cli_credentials_ignores_bad_file(self):
        cred_dir = os.path.join(engine.CLAUDE_HOME, ".claude")
        os.makedirs(cred_dir, exist_ok=True)
        with open(os.path.join(cred_dir, ".credentials.json"), "w") as f:
            f.write("not json")
        self.assertIsNone(engine.get_auth())

    def test_setup_flow_credentials_file_completes_working_phase(self):
        """Some CLI versions save the credential without printing a token —
        the appearing credentials file must count as sign-in success."""
        flow = engine.SetupTokenFlow()
        flow.phase = "working"
        flow._code_from = 0
        self._write_cli_credentials()
        flow._scan("some output without a token or retry prompt")
        self.assertEqual(flow.phase, "done")

    def test_setup_flow_status_masks_token_in_detail(self):
        flow = engine.SetupTokenFlow()
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
        old_argv = engine._claude_argv
        old_timeout = engine.EXCHANGE_TIMEOUT
        old_nudges = engine.NUDGE_TIMES
        engine._claude_argv = lambda: [str(stub)]
        engine.EXCHANGE_TIMEOUT = 5
        engine.NUDGE_TIMES = (2, 3)
        flow = engine.SetupTokenFlow()
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
            engine._claude_argv = old_argv
            engine.EXCHANGE_TIMEOUT = old_timeout
            engine.NUDGE_TIMES = old_nudges

    def test_run_claude_with_stub(self):
        stub = Path(self.tmp.name) / "claude"
        envelope = {"type": "result", "result": '{"title":"T"}',
                    "is_error": False, "duration_ms": 12, "num_turns": 1}
        stub.write_text("#!/bin/sh\ncat > /dev/null\necho '%s'\n" % json.dumps(envelope))
        stub.chmod(0o755)
        orig = engine._claude_argv
        engine._claude_argv = lambda: [str(stub)]
        try:
            result = engine.run_claude("prompt", "system", timeout=20)
        finally:
            engine._claude_argv = orig
        self.assertTrue(result["ok"])
        self.assertEqual(result["text"], '{"title":"T"}')
        self.assertEqual(result["meta"]["duration_ms"], 12)

    def test_run_claude_error_envelope(self):
        stub = Path(self.tmp.name) / "claude"
        stub.write_text("#!/bin/sh\ncat > /dev/null\n"
                        "echo '{\"type\":\"result\",\"is_error\":true,\"result\":\"boom\"}'\n")
        stub.chmod(0o755)
        orig = engine._claude_argv
        engine._claude_argv = lambda: [str(stub)]
        try:
            result = engine.run_claude("p", "s", timeout=20)
        finally:
            engine._claude_argv = orig
        self.assertFalse(result["ok"])
        self.assertIn("boom", result["error"])

    def test_a_sourced_run_claims_its_session_id_before_running(self):
        """Card and fix runs claim their transcripts the way every other
        background caller does: a minted --session-id, recorded in
        run_sources before the run — so a run that times out or crashes
        still left a transcript labelled as the run it was."""
        import run_sources
        log = Path(self.tmp.name) / "argv.log"
        stub = Path(self.tmp.name) / "claude"
        stub.write_text(
            "#!/bin/sh\necho \"$@\" >> '%s'\ncat > /dev/null\n"
            "echo '{\"type\":\"result\",\"result\":\"ok\",\"is_error\":false}'\n"
            % log)
        stub.chmod(0o755)
        old_argv, old_ledger = engine._claude_argv, run_sources.LEDGER
        engine._claude_argv = lambda: [str(stub)]
        run_sources.LEDGER = Path(self.tmp.name) / "run-sources.jsonl"
        try:
            result = engine.run_claude("p", "s", timeout=20, source="card")
            self.assertTrue(result["ok"])
            argv = log.read_text().split()
            self.assertIn("--session-id", argv)
            session_id = argv[argv.index("--session-id") + 1]
            self.assertEqual(run_sources.lookup([session_id]),
                             {session_id: "card"})
        finally:
            engine._claude_argv = old_argv
            run_sources.LEDGER = old_ledger

    def test_a_cli_that_rejects_session_id_still_runs(self):
        """The label is optional; the run is not — same contract as the
        consolidator's fallback. A CLI from before --session-id names the
        flag on stderr and dies; the run is retried without it."""
        import run_sources
        log = Path(self.tmp.name) / "argv.log"
        stub = Path(self.tmp.name) / "claude"
        stub.write_text(
            "#!/bin/sh\necho \"$@\" >> '%s'\n"
            "case \"$*\" in *--session-id*)\n"
            "  echo \"error: unknown option '--session-id'\" >&2; exit 2;;\n"
            "esac\ncat > /dev/null\n"
            "echo '{\"type\":\"result\",\"result\":\"ok\",\"is_error\":false}'\n"
            % log)
        stub.chmod(0o755)
        old_argv, old_ledger = engine._claude_argv, run_sources.LEDGER
        engine._claude_argv = lambda: [str(stub)]
        run_sources.LEDGER = Path(self.tmp.name) / "run-sources.jsonl"
        try:
            result = engine.run_claude("p", "s", timeout=20, source="card")
            self.assertTrue(result["ok"], result)
            invocations = log.read_text().splitlines()
            self.assertEqual(len(invocations), 2)
            self.assertIn("--session-id", invocations[0])
            self.assertNotIn("--session-id", invocations[1])
        finally:
            engine._claude_argv = old_argv
            run_sources.LEDGER = old_ledger


class TestPanelServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_dir = self.server.INSIGHTS_DIR
        self._old_settings = settings_store.SETTINGS_FILE
        self.server.INSIGHTS_DIR = Path(self.tmp.name)
        # A fresh install has no cards by design, so these tests describe a
        # home that has been through onboarding.
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        settings_store.save({"onboarded": True})

    def tearDown(self):
        self.server.INSIGHTS_DIR = self._old_dir
        settings_store.SETTINGS_FILE = self._old_settings
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
                # The scheduler's readback: why auto-refresh is idle (the
                # gate) and when each category will next regenerate.
                self.assertIn("auto", data)
                self.assertIn("gate", data["auto"])
                for cat in data["categories"]:
                    self.assertIn("next_due", cat)

                resp = await client.post("/api/generate", json={"category": "bogus"})
                self.assertEqual(resp.status, 400)

                resp = await client.post("/api/generate", json={"question": "x" * 600})
                self.assertEqual(resp.status, 400)

                resp = await client.get("/api/insights")
                self.assertEqual(resp.status, 200)

                resp = await client.get("/")
                self.assertEqual(resp.status, 200)
                text = await resp.text()
                self.assertIn("brAIn", text)
                self.assertNotIn("{{VERSION}}", text)

                resp = await client.get("/api/health")
                self.assertEqual(resp.status, 200)
                health = await resp.json()
                # Liveness for the watchdog first: ok is the panel
                # answering, never a judgement about sibling daemons.
                self.assertTrue(health["ok"])
                # The roll-call rides along for `brain doctor` — every
                # known daemon gets a row with a boolean, and on this test
                # machine none of them are running, which is a fact, not a
                # failure.
                daemons = health.get("daemons", {})
                for name in self.server.DAEMON_MARKS:
                    self.assertIn(name, daemons)
                    self.assertIsInstance(daemons[name]["running"], bool)
            finally:
                await client.close()

        asyncio.run(run())

    def test_health_survives_a_broken_rollcall(self):
        """The watchdog restarts the add-on when /api/health fails, so the
        informational half must never be able to take liveness down."""
        from aiohttp.test_utils import TestClient, TestServer

        def boom():
            raise RuntimeError("proc scan exploded")

        original = self.server._daemon_rollcall
        self.server._daemon_rollcall = boom
        try:
            async def run():
                client = TestClient(TestServer(self.server.make_app()))
                await client.start_server()
                try:
                    resp = await client.get("/api/health")
                    self.assertEqual(resp.status, 200)
                    body = await resp.json()
                    self.assertTrue(body["ok"])
                    self.assertNotIn("daemons", body)
                finally:
                    await client.close()

            asyncio.run(run())
        finally:
            self.server._daemon_rollcall = original

    def test_next_due_mirrors_refresh_due(self):
        """_next_due is _refresh_due asked "when" instead of "now?" — the
        two must agree, or the card foot lies about the scheduler."""
        import time as _t
        now = _t.time()
        stamp = lambda offset: _t.strftime(  # noqa: E731
            "%Y-%m-%dT%H:%M:%S", _t.localtime(now + offset))

        # disabled and manual-only categories are never due
        self.assertIsNone(self.server._next_due(
            {"enabled": False, "refresh_hours": 6}, stamp(-7200), now))
        self.assertIsNone(self.server._next_due(
            {"enabled": True, "refresh_hours": 0}, stamp(-7200), now))

        # a fresh card regenerates at gen + interval...
        eff = {"enabled": True, "refresh_hours": 6}
        nxt = self.server._next_due(eff, stamp(-3600), now)
        self.assertAlmostEqual(nxt, now - 3600 + 6 * 3600, delta=2)
        self.assertFalse(self.server._refresh_due(eff, stamp(-3600), now))

        # ...an overdue one is due now, and _refresh_due agrees
        nxt = self.server._next_due(eff, stamp(-7 * 3600), now)
        self.assertAlmostEqual(nxt, now, delta=2)
        self.assertTrue(self.server._refresh_due(eff, stamp(-7 * 3600), now))

        # a schedule points at the next future occurrence
        lt = _t.localtime(now + 2 * 3600)
        eff = {"enabled": True, "schedule": [f"{lt.tm_hour:02d}:{lt.tm_min:02d}"]}
        nxt = self.server._next_due(eff, stamp(-60), now)
        self.assertIsNotNone(nxt)
        self.assertGreater(nxt, now)
        self.assertLessEqual(nxt - now, 2 * 3600 + 120)

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
    """Shared-credential fallback (written by the brAIn add-on)."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = (engine.SECRETS_DIR, engine.AUTH_FILE,
                     engine.CLAUDE_HOME, engine.SHARED_AUTH_FILE)
        engine.SECRETS_DIR = self.tmp.name
        engine.AUTH_FILE = os.path.join(self.tmp.name, "claude_auth.json")
        engine.CLAUDE_HOME = os.path.join(self.tmp.name, "home")
        engine.SHARED_AUTH_FILE = os.path.join(self.tmp.name, "shared_auth.json")

    def tearDown(self):
        (engine.SECRETS_DIR, engine.AUTH_FILE,
         engine.CLAUDE_HOME, engine.SHARED_AUTH_FILE) = self._old
        self.tmp.cleanup()

    def _write_shared(self, payload):
        with open(engine.SHARED_AUTH_FILE, "w") as f:
            if isinstance(payload, str):
                f.write(payload)
            else:
                json.dump(payload, f)

    def test_shared_auth_picked_up(self):
        token = "sk-ant-oat01-" + "s" * 30
        self._write_shared({"type": "oauth_token", "value": token, "saved_at": 1752000000})
        auth = engine.get_auth()
        self.assertEqual(auth["type"], "oauth_token")
        self.assertEqual(auth["value"], token)
        self.assertEqual(auth["source"], "shared")
        env = engine._claude_env()
        self.assertEqual(env.get("CLAUDE_CODE_OAUTH_TOKEN"), token)
        self.assertNotIn("ANTHROPIC_API_KEY", env)

    def test_shared_api_key_injected_as_api_key(self):
        key = "sk-ant-api03-" + "k" * 30
        self._write_shared({"type": "api_key", "value": key, "saved_at": 1752000000})
        env = engine._claude_env()
        self.assertEqual(env.get("ANTHROPIC_API_KEY"), key)
        self.assertNotIn("CLAUDE_CODE_OAUTH_TOKEN", env)

    def test_local_wins_over_shared(self):
        local = "sk-ant-oat01-" + "l" * 30
        engine.save_auth(local)
        self._write_shared({"type": "oauth_token", "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})
        auth = engine.get_auth()
        self.assertEqual(auth["value"], local)
        self.assertEqual(auth["source"], "local")

    def test_source_reported_for_local(self):
        engine.save_auth("sk-ant-oat01-" + "a" * 30)
        self.assertEqual(engine.get_auth()["source"], "local")

    def test_saved_at_is_the_shape_both_stores_document(self):
        """Epoch seconds, matching `ha-share-login`'s half of the contract.

        `_read_shared_auth` documents `"saved_at": <epoch int>` for both
        credential files, and the shell half writes an int and greps for
        one (`"saved_at":[ ]*[0-9]+`). The panel wrote an ISO string, so
        one documented shape covered two formats — latent only because each
        reader happens to read the file it wrote, which is not a property
        worth relying on. The shell side has had this assertion since it was
        written (test_share_login_token_mode_writes_contract_file); this is
        the half that was missing, which is why it drifted.
        """
        before = int(time.time())
        engine.save_auth("sk-ant-oat01-" + "a" * 30)
        with open(engine.AUTH_FILE) as fh:
            saved = json.load(fh)
        self.assertIsInstance(saved["saved_at"], int)
        self.assertGreaterEqual(saved["saved_at"], before)

    def test_malformed_shared_tolerated(self):
        for payload in ("not json", ["a", "b"],
                        {"type": "weird", "value": "x"},
                        {"type": "oauth_token", "value": ""},
                        {"type": "oauth_token", "value": 42},
                        {"value": "sk-ant-oat01-zzz"}):
            self._write_shared(payload)
            self.assertIsNone(engine.get_auth(), payload)

    def test_missing_shared_tolerated(self):
        self.assertIsNone(engine.get_auth())

    def test_logout_leaves_shared_file_intact(self):
        """The DEFAULT still spares the shared file, and must.

        It may have been published from a terminal by somebody else, and it
        is the one credential of the three that other add-ons read — so
        deleting it is a decision, never a side effect of signing out here.
        What the test below adds is the other half: that sparing it is also
        what makes an unqualified sign-out a no-op, which is why the panel
        asks rather than picking either behaviour silently.
        """
        engine.save_auth("sk-ant-oat01-" + "l" * 30)
        self._write_shared({"type": "oauth_token", "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})
        engine.clear_auth()
        self.assertTrue(os.path.exists(engine.SHARED_AUTH_FILE))
        # after logout, the shared credential takes over again
        auth = engine.get_auth()
        self.assertEqual(auth["source"], "shared")

    def test_signing_out_while_shared_leaves_you_signed_in(self):
        """The failure the dialog's ticked box exists to answer.

        `get_auth` reads the shared file two branches below its own store,
        so a sign-out that spares it hands the very next call the credential
        it just removed — from the panel that is a Sign out button that
        visibly does nothing. Demonstrated here rather than described,
        because the fix is a parameter and a parameter with no failing case
        behind it is a parameter somebody will default the other way.
        """
        for include_shared in (False, True):
            with self.subTest(include_shared=include_shared):
                engine.save_auth("sk-ant-oat01-" + "l" * 30)
                self._write_shared({"type": "oauth_token",
                                    "value": "sk-ant-oat01-" + "s" * 30,
                                    "saved_at": 1752000000})
                self.assertTrue(engine.get_auth())
                engine.clear_auth(include_shared=include_shared)
                if include_shared:
                    self.assertIsNone(engine.get_auth(),
                                      "sign out did not sign out")
                else:
                    self.assertEqual(engine.get_auth()["source"], "shared")

    def test_sharing_publishes_the_panels_login_where_addons_read_it(self):
        """The half the panel could not do at all.

        Writing that file was `ha login`'s alone, so somebody who signed in
        through the panel had no route to sharing but a command they had to
        already know about — and `ha login --status` answered them "not set
        up", because it read only the file it writes itself.
        """
        token = "sk-ant-oat01-" + "p" * 30
        engine.save_auth(token)
        self.assertFalse(os.path.exists(engine.SHARED_AUTH_FILE))

        self.assertEqual(engine.share_auth(), {"shared": True, "reason": "ok"})
        with open(engine.SHARED_AUTH_FILE) as fh:
            published = json.load(fh)
        # The same shape contract `_read_shared_auth` documents and the
        # shell half greps for — an epoch int, not an ISO string.
        self.assertEqual(published["type"], "oauth_token")
        self.assertEqual(published["value"], token)
        self.assertIsInstance(published["saved_at"], int)
        # A credential is 0600 from the open, never a chmod afterwards.
        self.assertEqual(stat.S_IMODE(os.stat(engine.SHARED_AUTH_FILE).st_mode), 0o600)
        # And it must survive the round trip through the reader other
        # add-ons actually use, or "shared" is a file nothing can read.
        engine.clear_auth()
        self.assertEqual(engine.get_auth()["source"], "shared")

        self.assertTrue(engine.unshare_auth())
        self.assertFalse(os.path.exists(engine.SHARED_AUTH_FILE))
        self.assertFalse(engine.unshare_auth(), "a second withdraw removed nothing")

    def test_claude_codes_own_session_token_is_never_published(self):
        """The refusal that is the feature.

        `.credentials.json` holds a SESSION token the CLI refreshes for
        itself. The shared file records no refresh token and no reader knows
        how to use one, so a copy works for a few hours and then breaks
        every add-on reading it — silently, with nothing to say why. It is
        also the store most likely to be the only one present, which is
        exactly when somebody would reach for the button.
        """
        cli = Path(engine.CLAUDE_HOME) / ".claude"
        cli.mkdir(parents=True, exist_ok=True)
        (cli / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "sk-ant-" + "x" * 40,
            "expiresAt": int((time.time() + 9000) * 1000)}}))

        # Signed in — this is not a "no credential" case.
        self.assertEqual(engine.get_auth()["type"], "cli_login")
        self.assertEqual(engine.share_auth(),
                         {"shared": False, "reason": "cli_login_cannot_be_shared"})
        self.assertFalse(os.path.exists(engine.SHARED_AUTH_FILE))
        # And the overview says so, so the button is absent rather than
        # present-and-failing.
        self.assertFalse(engine.auth_overview()["can_share"])

    def test_the_overview_reports_every_store_not_only_its_own(self):
        """"Signed in" and "signed in AND shared" are different states.

        A surface that can see only its own file answers the second with the
        first one's words, which is what `ha login --status` did to somebody
        who had signed in through the panel perfectly well.
        """
        blank = engine.auth_overview()
        self.assertFalse(blank["authenticated"])
        self.assertEqual({k: v["present"] for k, v in blank["stores"].items()},
                         {"local": False, "cli": False, "shared": False})

        engine.save_auth("sk-ant-oat01-" + "p" * 30)
        self._write_shared({"type": "oauth_token", "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})
        both = engine.auth_overview()
        self.assertTrue(both["stores"]["local"]["present"])
        self.assertTrue(both["stores"]["shared"]["present"])
        # `source` names which one actually answered — the field that makes
        # "the terminal works and the panel doesn't" diagnosable at all.
        self.assertEqual(both["source"], "local")
        self.assertTrue(both["can_share"])
        # Nothing here may carry a credential: this payload is rendered in a
        # dialog and read out of bug reports.
        self.assertNotIn("sk-ant", json.dumps(both))

    def test_an_expired_cli_login_is_not_reported_as_a_login(self):
        """The one store that records an expiry is the one store where
        "there is a credential here" and "there is a working credential
        here" are separable — and reporting a dead token as a login is what
        sent people to redo a sign-in that was already fine."""
        cli = Path(engine.CLAUDE_HOME) / ".claude"
        cli.mkdir(parents=True, exist_ok=True)
        creds = cli / ".credentials.json"
        for offset, expected in ((9000, True), (-3600, False)):
            creds.write_text(json.dumps({"claudeAiOauth": {
                "accessToken": "sk-ant-" + "x" * 40,
                "expiresAt": int((time.time() + offset) * 1000)}}))
            with self.subTest(offset=offset):
                self.assertEqual(
                    engine.auth_overview()["stores"]["cli"]["present"], expected)

    # -- the routes the ⚙ dialog's Claude account section drives ----------
    # Driven through a real client rather than by calling the handlers, for
    # the reason `build_app is not main` records elsewhere in this repo: a
    # route that is never registered is a route every direct-call test passes
    # against. /api/auth in particular is new, and a handler nobody can reach
    # is exactly the failure the section exists to end.

    def _drive(self, steps):
        """Run `steps(client)` against a real panel."""
        from aiohttp.test_utils import TestClient, TestServer
        server = importlib.import_module("server")
        old_dir = server.INSIGHTS_DIR
        server.INSIGHTS_DIR = Path(self.tmp.name) / "insights"
        server.QUEUE = asyncio.Queue()
        old_validate = engine.validate_auth
        old_check = dict(server.AUTH_CHECK)
        # A real verification is a `claude -p` turn; these tests are about
        # the routes, so it is stubbed and its having run is not asserted.
        engine.validate_auth = lambda timeout=120: {"ok": True, "error": ""}

        async def run():
            client = TestClient(TestServer(server.make_app()))
            await client.start_server()
            try:
                await self._settle_startup_check(server)
                return await steps(client)
            finally:
                await client.close()

        try:
            return asyncio.run(run())
        finally:
            server.INSIGHTS_DIR = old_dir
            engine.validate_auth = old_validate
            server.AUTH_CHECK.clear()
            server.AUTH_CHECK.update(old_check)

    def test_the_account_routes_share_and_withdraw_a_login(self):
        token = "sk-ant-oat01-" + "p" * 30
        engine.save_auth(token)

        async def steps(client):
            before = await (await client.get("/api/auth")).json()
            self.assertTrue(before["authenticated"])
            self.assertFalse(before["stores"]["shared"]["present"])
            self.assertTrue(before["can_share"])

            after = await (await client.post("/api/auth/share")).json()
            self.assertTrue(after["stores"]["shared"]["present"])

            gone = await (await client.post("/api/auth/unshare")).json()
            self.assertTrue(gone["removed"])
            self.assertFalse(gone["stores"]["shared"]["present"])
            return after

        shared = self._drive(steps)
        # The route wrote the real file, not just a payload saying it had.
        self.assertNotIn("sk-ant", json.dumps(shared))

    def test_sharing_a_session_login_is_refused_with_a_sentence(self):
        """A 409 carrying the reason, never a silent success.

        Publishing Claude Code's own session token would work for a few
        hours and then break every add-on reading it, so the refusal is the
        feature — and it has to arrive as something a person can read,
        because from the outside "signed in" is exactly what they see.
        """
        cli = Path(engine.CLAUDE_HOME) / ".claude"
        cli.mkdir(parents=True, exist_ok=True)
        (cli / ".credentials.json").write_text(json.dumps({"claudeAiOauth": {
            "accessToken": "sk-ant-" + "x" * 40,
            "expiresAt": int((time.time() + 9000) * 1000)}}))

        async def steps(client):
            resp = await client.post("/api/auth/share")
            self.assertEqual(resp.status, 409)
            return await resp.text()

        body = self._drive(steps)
        self.assertIn("refresh", body.lower())
        self.assertIn("ha login", body)
        self.assertFalse(os.path.exists(engine.SHARED_AUTH_FILE))

    def test_logout_over_the_wire_can_take_the_shared_copy_with_it(self):
        """Both shapes, because the old one still has to work.

        A body-less POST is what a panel served before this update sends,
        and it must not fail on the parse — it simply means the default.
        """
        async def steps(client):
            out = []
            for body in (None, {"shared": False}, {"shared": True}):
                engine.save_auth("sk-ant-oat01-" + "l" * 30)
                self._write_shared({"type": "oauth_token",
                                    "value": "sk-ant-oat01-" + "s" * 30,
                                    "saved_at": 1752000000})
                kwargs = {} if body is None else {"json": body}
                resp = await client.post("/api/auth/logout", **kwargs)
                self.assertEqual(resp.status, 200)
                out.append(os.path.exists(engine.SHARED_AUTH_FILE))
            return out

        kept_none, kept_false, kept_true = self._drive(steps)
        self.assertTrue(kept_none, "a body-less logout must keep the default")
        self.assertTrue(kept_false)
        self.assertFalse(kept_true, "the ticked box did not remove the shared copy")

    async def _settle_startup_check(self, server):
        """Wait out the check make_app() fires on startup.

        It runs because a credential exists, which is correct and is not
        what these two tests are measuring — so they take their baseline
        after it, rather than pretending it does not happen.
        """
        for _ in range(200):
            if server.AUTH_CHECK["state"] != "checking":
                return
            await asyncio.sleep(0.01)
        self.fail("the startup auth check never settled")

    def test_a_stale_verdict_is_re_earned_by_a_status_poll(self):
        """The wiring, not the constant.

        A staleness rule nothing calls is the bug with better paperwork, so
        this drives the real endpoint: a verdict older than the interval has
        to cost one verification, and a poll arriving while that one is
        still in flight has to cost none.
        """
        from aiohttp.test_utils import TestClient, TestServer
        server = importlib.import_module("server")
        old_dir = server.INSIGHTS_DIR
        server.INSIGHTS_DIR = Path(self.tmp.name) / "insights"
        server.QUEUE = asyncio.Queue()
        old_validate = engine.validate_auth
        old_check = dict(server.AUTH_CHECK)

        calls = []
        block = threading.Event()
        release = threading.Event()

        def validate(timeout=120):
            calls.append(timeout)
            if block.is_set():
                release.wait(5)
            return {"ok": True, "error": ""}

        engine.validate_auth = validate
        self._write_shared({"type": "oauth_token",
                            "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})

        async def run():
            client = TestClient(TestServer(server.make_app()))
            await client.start_server()
            try:
                await self._settle_startup_check(server)
                calls.clear()
                block.set()

                # A verdict older than the interval: one poll, one check.
                server.AUTH_CHECK.update(
                    state="ok", error="",
                    checked_at=time.time() - server.AUTH_RECHECK_S - 1)
                resp = await client.get("/api/status")
                # `running` is the synchronous half of the guard, so it is
                # true the moment the request returns; the call itself is on
                # a worker thread, so give it a beat to actually land.
                self.assertTrue(server.AUTH_CHECK["running"])
                # And a re-verification nobody asked for stays quiet: the
                # standing verdict is served until a new one replaces it,
                # rather than flashing "Verifying Claude…" into the top bar
                # every six hours while somebody is reading a card.
                self.assertEqual((await resp.json())["auth_check"]["state"], "ok")
                for _ in range(200):
                    if calls:
                        break
                    await asyncio.sleep(0.01)
                self.assertEqual(len(calls), 1)

                # Two more polls while it is still running: still one check.
                await client.get("/api/status")
                await client.get("/api/status")
                await asyncio.sleep(0.05)
                self.assertEqual(len(calls), 1)
            finally:
                release.set()
                await client.close()

        try:
            asyncio.run(run())
        finally:
            release.set()
            server.INSIGHTS_DIR = old_dir
            engine.validate_auth = old_validate
            server.AUTH_CHECK.clear()
            server.AUTH_CHECK.update(old_check)

    def test_a_fresh_verdict_costs_a_status_poll_nothing(self):
        """The other half — a poll must not spend a turn per request."""
        from aiohttp.test_utils import TestClient, TestServer
        server = importlib.import_module("server")
        old_dir = server.INSIGHTS_DIR
        server.INSIGHTS_DIR = Path(self.tmp.name) / "insights"
        server.QUEUE = asyncio.Queue()
        old_validate = engine.validate_auth
        old_check = dict(server.AUTH_CHECK)

        calls = []

        def counted(timeout=120):
            calls.append(timeout)
            return {"ok": True, "error": ""}

        engine.validate_auth = counted
        self._write_shared({"type": "oauth_token",
                            "value": "sk-ant-oat01-" + "s" * 30,
                            "saved_at": 1752000000})

        async def run():
            client = TestClient(TestServer(server.make_app()))
            await client.start_server()
            try:
                await self._settle_startup_check(server)
                calls.clear()
                server.AUTH_CHECK.update(
                    state="ok", error="", checked_at=time.time())
                for _ in range(3):
                    await client.get("/api/status")
                self.assertEqual(calls, [])
            finally:
                await client.close()

        try:
            asyncio.run(run())
        finally:
            server.INSIGHTS_DIR = old_dir
            engine.validate_auth = old_validate
            server.AUTH_CHECK.clear()
            server.AUTH_CHECK.update(old_check)

    def test_status_reports_auth_source(self):
        from aiohttp.test_utils import TestClient, TestServer
        server = importlib.import_module("server")
        old_dir = server.INSIGHTS_DIR
        server.INSIGHTS_DIR = Path(self.tmp.name) / "insights"
        # fresh queue so the app worker never awaits a queue bound to a
        # previous test's event loop
        server.QUEUE = asyncio.Queue()
        # keep the startup auth check from invoking a real claude binary
        old_validate = engine.validate_auth
        engine.validate_auth = lambda timeout=120: {"ok": True, "error": ""}
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
            engine.validate_auth = old_validate


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

    def test_title_and_icon_override(self):
        prompt_store.save_override("energy", {"title": "Power bill", "icon": "🔌"})
        eff = prompt_store.effective_category("energy")
        self.assertEqual(eff["title"], "Power bill")
        self.assertEqual(eff["icon"], "🔌")
        self.assertIn("title", eff["overridden"])
        self.assertIn("icon", eff["overridden"])
        # clearing goes back to the shipped name
        prompt_store.save_override("energy", {"title": None, "icon": None})
        eff = prompt_store.effective_category("energy")
        self.assertEqual(eff["title"], categories.get_category("energy")["title"])
        self.assertEqual(eff["icon"], categories.get_category("energy")["icon"])

    def test_title_and_icon_are_trimmed(self):
        prompt_store.save_override(
            "energy", {"title": "  " + "x" * 200, "icon": "🔌🔌🔌🔌🔌"})
        eff = prompt_store.effective_category("energy")
        self.assertEqual(len(eff["title"]), prompt_store.MAX_TITLE)
        self.assertEqual(len(eff["icon"]), prompt_store.MAX_ICON)

    def test_hidden_removes_from_visible_list(self):
        self.assertFalse(prompt_store.is_hidden("energy"))
        prompt_store.save_override("energy", {"hidden": True})
        self.assertTrue(prompt_store.is_hidden("energy"))
        self.assertTrue(prompt_store.effective_category("energy")["hidden"])
        ids = [c["id"] for c in prompt_store.visible_categories()]
        self.assertNotIn("energy", ids)
        # every other shipped card is untouched, in shipped order
        self.assertEqual(
            ids, [c["id"] for c in categories.CATEGORIES if c["id"] != "energy"])

    def test_there_is_no_restore_list(self):
        """Hiding is the mechanism, not an offer. brAIn proposes the cards a
        given home should have; keeping a graveyard of shipped ones to
        resurrect is the opposite of that idea, so the listing that fed the
        ⚙ dialog's restore list is gone rather than merely unused."""
        self.assertFalse(hasattr(prompt_store, "hidden_categories"))

    def test_restore_makes_it_visible_again(self):
        prompt_store.save_override("energy", {"hidden": True})
        prompt_store.save_override("energy", {"hidden": None})
        self.assertFalse(prompt_store.is_hidden("energy"))
        self.assertIn("energy", [c["id"] for c in prompt_store.visible_categories()])

    def test_reset_override_unhides(self):
        prompt_store.save_override("energy", {"hidden": True, "title": "X"})
        prompt_store.reset_override("energy")
        self.assertFalse(prompt_store.is_hidden("energy"))
        self.assertEqual(prompt_store.effective_category("energy")["title"],
                         categories.get_category("energy")["title"])

    def test_unknown_category(self):
        self.assertIsNone(prompt_store.effective_category("nope"))

    def test_corrupt_file_tolerated(self):
        with open(prompt_store.OVERRIDES_FILE, "w") as f:
            f.write("not json")
        self.assertEqual(prompt_store.load_overrides(), {"categories": {}})
        self.assertTrue(prompt_store.effective_category("energy")["enabled"])


class TestFeedbackStore(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = feedback_store.FEEDBACK_FILE
        feedback_store.FEEDBACK_FILE = os.path.join(self.tmp.name, "feedback.json")

    def tearDown(self):
        feedback_store.FEEDBACK_FILE = self._old
        self.tmp.cleanup()

    def test_add_list_remove_roundtrip(self):
        self.assertEqual(feedback_store.list_feedback("energy"), [])
        entry = feedback_store.add_feedback("energy", "  Show costs in dollars  ")
        self.assertEqual(entry["text"], "Show costs in dollars")
        listed = feedback_store.list_feedback("energy")
        self.assertEqual([e["text"] for e in listed], ["Show costs in dollars"])
        self.assertTrue(feedback_store.remove_feedback("energy", entry["ts"]))
        self.assertEqual(feedback_store.list_feedback("energy"), [])
        self.assertFalse(feedback_store.remove_feedback("energy", entry["ts"]))

    def test_entries_get_unique_ts(self):
        a = feedback_store.add_feedback("energy", "one")
        b = feedback_store.add_feedback("energy", "two")
        self.assertNotEqual(a["ts"], b["ts"])
        feedback_store.remove_feedback("energy", a["ts"])
        self.assertEqual([e["text"] for e in feedback_store.list_feedback("energy")],
                         ["two"])

    def test_validation(self):
        with self.assertRaises(ValueError):
            feedback_store.add_feedback("energy", "   ")
        with self.assertRaises(ValueError):
            feedback_store.add_feedback("energy", "x" * 501)

    def test_cap_keeps_newest(self):
        for i in range(feedback_store.MAX_PER_CATEGORY + 3):
            feedback_store.add_feedback("energy", f"note {i}")
        listed = feedback_store.list_feedback("energy")
        self.assertEqual(len(listed), feedback_store.MAX_PER_CATEGORY)
        self.assertEqual(listed[-1]["text"],
                         f"note {feedback_store.MAX_PER_CATEGORY + 2}")

    def test_corrupt_file_tolerated(self):
        with open(feedback_store.FEEDBACK_FILE, "w") as f:
            f.write("not json")
        self.assertEqual(feedback_store.list_feedback("energy"), [])
        feedback_store.add_feedback("energy", "works anyway")
        self.assertEqual(len(feedback_store.list_feedback("energy")), 1)


class TestUserCategories(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old = user_categories.USER_CATS_FILE
        user_categories.USER_CATS_FILE = os.path.join(self.tmp.name, "user_cats.json")

    def tearDown(self):
        user_categories.USER_CATS_FILE = self._old
        self.tmp.cleanup()

    def test_create_and_shape(self):
        cat = user_categories.create({
            "title": "Garage fridge watch", "focus": "Track the fridge",
            "icon": "🧊", "refresh_hours": 12})
        self.assertTrue(cat["id"].startswith("user-"))
        self.assertTrue(cat["user"])
        self.assertEqual(cat["refresh_hours"], 12)
        # category shape usable by collect_bundle/build_prompt
        for key in ("domains", "device_classes", "history", "stats", "focus"):
            self.assertIn(key, cat)
        self.assertEqual(user_categories.get(cat["id"])["title"],
                         "Garage fridge watch")

    def test_ids_unique_within_a_second(self):
        a = user_categories.create({"title": "A", "focus": "fa"})
        b = user_categories.create({"title": "B", "focus": "fb"})
        self.assertNotEqual(a["id"], b["id"])

    def test_validation(self):
        for bad in ({"title": "", "focus": "x"},
                    {"title": "x", "focus": " "},
                    {"title": "x", "focus": "y", "refresh_hours": 999},
                    {"title": "x", "focus": "y", "refresh_hours": "soon"}):
            with self.assertRaises(ValueError):
                user_categories.create(bad)

    def test_update_partial(self):
        cat = user_categories.create({"title": "A", "focus": "fa"})
        updated = user_categories.update(cat["id"], {"refresh_hours": 3,
                                                     "enabled": False})
        self.assertEqual(updated["refresh_hours"], 3)
        self.assertFalse(updated["enabled"])
        self.assertEqual(updated["title"], "A")
        self.assertIsNone(user_categories.update("user-nope", {"title": "X"}))

    def test_delete(self):
        cat = user_categories.create({"title": "A", "focus": "fa"})
        self.assertTrue(user_categories.delete(cat["id"]))
        self.assertFalse(user_categories.delete(cat["id"]))
        self.assertIsNone(user_categories.get(cat["id"]))

    def test_limit_enforced(self):
        for i in range(user_categories.MAX_USER_CATEGORIES):
            user_categories.create({"title": f"T{i}", "focus": "f"})
        with self.assertRaises(ValueError):
            user_categories.create({"title": "one too many", "focus": "f"})

    def test_corrupt_file_tolerated(self):
        with open(user_categories.USER_CATS_FILE, "w") as f:
            f.write("not json")
        self.assertEqual(user_categories.load(), [])
        user_categories.create({"title": "A", "focus": "fa"})
        self.assertEqual(len(user_categories.load()), 1)


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
        self._old_feedback = feedback_store.FEEDBACK_FILE
        self._old_user_cats = user_categories.USER_CATS_FILE
        self._old_card_token = self.server.CARD_TOKEN_FILE
        self._old_knowledge = knowledge_store.KNOWLEDGE_FILE
        self._old_shared_mem = self.server.SHARED_MEMORY_FILE
        knowledge_store.KNOWLEDGE_FILE = os.path.join(self.tmp.name, "knowledge.json")
        hypotheses.HYPOTHESES_FILE = Path(self.tmp.name) / "hypotheses.jsonl"
        # These exercise a home that has finished onboarding. A fresh
        # install deliberately has NO cards, so without this every
        # category-facing test would see an empty dashboard.
        settings_store.SETTINGS_FILE = os.path.join(self.tmp.name, "settings.json")
        onboarding.STATE_FILE = Path(self.tmp.name) / "onboarding.json"
        settings_store.save({"onboarded": True})
        self.server.SHARED_MEMORY_FILE = Path(self.tmp.name) / "memory.md"
        self.server.INSIGHTS_DIR = Path(self.tmp.name)
        # NOT inside INSIGHTS_DIR — mirrors production (/data vs /data/insights)
        prompt_store.OVERRIDES_FILE = os.path.join(
            self.tmp.name, "overrides", "prompt_overrides.json")
        self.server.MEMORY_INBOX_DIR = Path(self.tmp.name) / "memory-inbox"
        feedback_store.FEEDBACK_FILE = os.path.join(self.tmp.name, "feedback.json")
        user_categories.USER_CATS_FILE = os.path.join(
            self.tmp.name, "user_categories.json")
        self.server.CARD_TOKEN_FILE = Path(self.tmp.name) / "secrets" / "card_token"
        self._old_findings = (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR)
        self._old_tags = card_tags.TAGS_FILE
        findings_store.FINDINGS_FILE = Path(self.tmp.name) / "findings.json"
        findings_store.INBOX_DIR = Path(self.tmp.name) / "findings-inbox"
        card_tags.TAGS_FILE = Path(self.tmp.name) / "card_tags.json"
        # Every generation books its tokens against the run ledger, so the
        # ledger is part of the fixture — without this a test run writes to
        # the real /data/usage.json and every case sees the last one's spend.
        self._old_usage = usage_store.USAGE_FILE
        usage_store.USAGE_FILE = os.path.join(self.tmp.name, "usage.json")
        self._old_www = self.server.WWW_CARD_DIR
        self.server.WWW_CARD_DIR = Path(self.tmp.name) / "www" / "bruh_insights"
        self.server.JOBS.clear()
        self.server.QUEUE = asyncio.Queue()

    def tearDown(self):
        self.server.INSIGHTS_DIR = self._old_dir
        prompt_store.OVERRIDES_FILE = self._old_overrides
        self.server.MEMORY_INBOX_DIR = self._old_inbox
        (findings_store.FINDINGS_FILE, findings_store.INBOX_DIR) = self._old_findings
        card_tags.TAGS_FILE = self._old_tags
        feedback_store.FEEDBACK_FILE = self._old_feedback
        user_categories.USER_CATS_FILE = self._old_user_cats
        self.server.CARD_TOKEN_FILE = self._old_card_token
        knowledge_store.KNOWLEDGE_FILE = self._old_knowledge
        self.server.SHARED_MEMORY_FILE = self._old_shared_mem
        usage_store.USAGE_FILE = self._old_usage
        self.server.WWW_CARD_DIR = self._old_www
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


# History fixtures are stamped *yesterday*, computed at import. The prune
# measures a run's age against the wall clock (`eff_keep_days`, default 30),
# so a literal date in these tests is a lit fuse: the hard-coded stamps this
# replaced went red the morning they turned 31 days old, on a PR whose diff
# had nothing to do with history. Yesterday is always inside the window, and
# localtime because that is the clock the prune itself reads.
FRESH_DAY = time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400))


class TestInsightHistory(InsightsServerCase):
    def test_history_copy_written_and_invisible_to_load(self):
        self._save("energy", f"{FRESH_DAY}T10:00:00")
        run_file = Path(self.tmp.name) / "history" / "energy" / f"{FRESH_DAY}T10-00-00.json"
        self.assertTrue(run_file.exists())
        # load_insights must not see the history subdir
        loaded = self.server.load_insights()
        self.assertEqual([i["id"] for i in loaded], ["energy"])

    def test_custom_cards_excluded_from_history(self):
        self._save("custom-1234", f"{FRESH_DAY}T10:00:00", category="custom")
        self.assertFalse((Path(self.tmp.name) / "history" / "custom-1234").exists())

    def test_bad_stamp_skipped(self):
        self._save("energy", "garbage")
        self.assertFalse((Path(self.tmp.name) / "history" / "energy").exists())

    def test_history_disabled_by_zero(self):
        old = self.server.HISTORY_KEEP_RUNS
        self.server.HISTORY_KEEP_RUNS = 0
        try:
            self._save("energy", f"{FRESH_DAY}T10:00:00")
        finally:
            self.server.HISTORY_KEEP_RUNS = old
        self.assertFalse((Path(self.tmp.name) / "history" / "energy").exists())

    def test_prune_keeps_newest_runs(self):
        old = self.server.HISTORY_KEEP_RUNS
        self.server.HISTORY_KEEP_RUNS = 3
        try:
            for i in range(6):
                self._save("energy", f"{FRESH_DAY}T10:00:{i:02d}")
        finally:
            self.server.HISTORY_KEEP_RUNS = old
        files = sorted(p.stem for p in
                       (Path(self.tmp.name) / "history" / "energy").glob("*.json"))
        self.assertEqual(files, [f"{FRESH_DAY}T10-00-03", f"{FRESH_DAY}T10-00-04",
                                 f"{FRESH_DAY}T10-00-05"])

    def test_prune_drops_runs_older_than_keep_days(self):
        self._save("energy", "2020-01-01T00:00:00")
        self._save("energy", f"{FRESH_DAY}T10:00:00")
        stems = [p.stem for p in
                 (Path(self.tmp.name) / "history" / "energy").glob("*.json")]
        self.assertEqual(stems, [f"{FRESH_DAY}T10-00-00"])

    def test_history_endpoints(self):
        self._save("energy", f"{FRESH_DAY}T09:00:00")
        self._save("energy", f"{FRESH_DAY}T10:00:00")

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.get("/api/insight/energy/history")
                self.assertEqual(resp.status, 200)
                runs = (await resp.json())["runs"]
                self.assertEqual([r["ts"] for r in runs],
                                 [f"{FRESH_DAY}T10-00-00", f"{FRESH_DAY}T09-00-00"])
                for r in runs:
                    self.assertNotIn("html", r)
                    self.assertTrue(r["title"])

                resp = await client.get(
                    f"/api/insight/energy/history/{FRESH_DAY}T09-00-00")
                self.assertEqual(resp.status, 200)
                full = await resp.json()
                self.assertEqual(full["generated_at"], f"{FRESH_DAY}T09:00:00")
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

                resp = await client.delete(
                    f"/api/insight/energy/history/{FRESH_DAY}T09-00-00")
                self.assertEqual(resp.status, 200)
                resp = await client.get("/api/insight/energy/history")
                runs = (await resp.json())["runs"]
                self.assertEqual([r["ts"] for r in runs], [f"{FRESH_DAY}T10-00-00"])
                resp = await client.delete(
                    f"/api/insight/energy/history/{FRESH_DAY}T09-00-00")
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
        self._old_orientation = getattr(self.ha_data, "collect_orientation", None)
        self._old_analyst = engine.run_analyst
        self._old_run = engine.run_claude
        self._old_service = self.ha_data.call_service

        async def fake_bundle(cat, days, question=None):
            self.bundle_focus = cat.get("focus")
            return {"meta": {"now": "2026-07-18T12:00:00"}, "entities": []}

        self.ha_data.collect_bundle = fake_bundle
        self.reply = {
            "title": "Dryer watch", "summary": "S.",
            "highlights": [{"label": "Loads", "value": "3"}],
            "hypotheses": ["The garage fridge is meant to run 24/7 — right?", "  ", 42],
            "learned": ["Hall sensor drops offline at 2 AM", ""],
            "findings": [{"text": "Back Door battery is dead",
                          "detail": "sensor.back_door_battery has read 0% since Jul 12",
                          "fix": "Replace the CR2032", "severity": "serious",
                          "fixable": False, "entity_id": "sensor.back_door_battery"}],
            "html": "<!DOCTYPE html><p>ok</p>",
        }
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": json.dumps(self.reply), "error": "",
            "meta": {"duration_ms": 5}}

    def tearDown(self):
        self.ha_data.collect_bundle = self._old_collect
        engine.run_claude = self._old_run
        engine.run_analyst = self._old_analyst
        self.ha_data.call_service = self._old_service
        if self._old_orientation is None:
            self.ha_data.__dict__.pop("collect_orientation", None)
        else:
            self.ha_data.collect_orientation = self._old_orientation
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
        # Hypotheses go to the queue, never onto the card: they are decisions,
        # and decisions are shown in exactly one place (the Findings tab).
        self.assertNotIn("questions", stored)
        self.assertEqual([h["text"] for h in hypotheses.list_all("open")],
                         ["The garage fridge is meant to run 24/7 — right?"])
        self.assertEqual(stored["learned"], ["Hall sensor drops offline at 2 AM"])
        # A finding is a work-list item, not part of the card: it lands in
        # the findings store, and the card stores NOTHING about it. A copy on
        # the card would be a snapshot guaranteed to go stale the moment the
        # finding is fixed or dismissed.
        self.assertNotIn("findings", stored)
        listed = findings_store.list_all()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["text"], "Back Door battery is dead")
        self.assertEqual(listed[0]["status"], "open")
        self.assertEqual(listed[0]["severity"], "serious")
        self.assertFalse(listed[0]["fixable"], "a dead battery needs hands")
        self.assertEqual(listed[0]["source"], "energy")
        # Only what was LEARNED is queued for the consolidator, and it goes
        # through a file rather than a service: the consolidator lives in
        # this container now.
        self.assertEqual(calls, [])
        queued = self._queued_facts()
        self.assertEqual(len(queued), 1)
        self.assertEqual(queued[0]["fact"], "Hall sensor drops offline at 2 AM")

    def test_a_finding_is_never_reported_twice(self):
        """The same problem must not pile up when two cards both notice it —
        the store is the one place that decides, so the second run's report
        is dropped rather than filed again."""
        asyncio.run(self.server._generate("energy"))
        self.server.JOBS.clear()
        asyncio.run(self.server._generate("climate"))
        self.assertEqual(len(findings_store.list_all()), 1)

    def test_a_dismissed_finding_goes_back_into_the_prompt(self):
        """Dismissing is only worth a button if it sticks across runs."""
        asyncio.run(self.server._generate("energy"))
        ts = findings_store.list_all()[0]["ts"]
        findings_store.set_status(ts, "ignored")
        block = findings_store.prompt_block()
        self.assertIn("SAID WERE WRONG", block)
        self.assertIn("Back Door battery is dead", block)

    def _queued_facts(self):
        facts = []
        for f in sorted(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    facts.append(json.loads(line))
        return facts

    def test_findings_are_queued_even_with_no_integration(self):
        """The hand-off is a local file write, so an absent integration
        cannot lose a learned fact."""
        async def broken_service(service, data):
            raise RuntimeError("integration not installed")

        self.ha_data.call_service = broken_service
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(self.server.JOBS["energy"]["state"], "done")
        files = list(self.server.MEMORY_INBOX_DIR.glob("*.jsonl"))
        self.assertEqual(len(files), 1)
        lines = [json.loads(l) for l in files[0].read_text().splitlines()]
        self.assertEqual(lines[0]["fact"], "Hall sensor drops offline at 2 AM")
        self.assertEqual(lines[0]["source"], "insights")
        self.assertEqual(lines[0]["confidence"], "medium")
        self.assertIsInstance(lines[0]["ts"], int)

    def test_missing_optional_fields_default_empty(self):
        self.reply.pop("hypotheses")
        self.reply.pop("findings")
        self.reply.pop("learned")
        asyncio.run(self.server._generate("energy"))
        stored = self._stored()
        self.assertNotIn("questions", stored)
        self.assertEqual(hypotheses.list_all("open"), [])
        self.assertEqual(stored["learned"], [])
        self.assertEqual(stored["tags"], [])
        self.assertEqual(findings_store.list_all(), [])

    def test_feedback_injected_and_tags_stored(self):
        feedback_store.add_feedback("energy", "No pie charts")
        self.reply["tags"] = ["Energy ", "#anomaly", "energy", 42]
        prompts = []

        def capture(prompt, *a, **k):
            prompts.append(prompt)
            return {"ok": True, "text": json.dumps(self.reply), "error": "",
                    "meta": {"duration_ms": 5}}

        engine.run_claude = capture
        asyncio.run(self.server._generate("energy"))
        stored = self._stored()
        self.assertEqual(stored["tags"], ["energy", "anomaly"])
        self.assertIn("HOMEOWNER FEEDBACK", prompts[0])
        self.assertIn("- No pie charts", prompts[0])

    def test_question_generation_skips_feedback(self):
        feedback_store.add_feedback("energy", "No pie charts")
        prompts = []

        def capture(prompt, *a, **k):
            prompts.append(prompt)
            return {"ok": True, "text": json.dumps(self.reply), "error": "",
                    "meta": {"duration_ms": 5}}

        engine.run_claude = capture
        self.server._set_job("custom-77", state="queued", question="Why cold?")
        asyncio.run(self.server._generate("custom-77"))
        self.assertNotIn("HOMEOWNER FEEDBACK", prompts[0])

    def test_generate_user_category(self):
        cat = user_categories.create({
            "title": "Fridge", "focus": "Watch the fridge", "icon": "🧊"})
        asyncio.run(self.server._generate(cat["id"]))
        self.assertEqual(self.server.JOBS[cat["id"]]["state"], "done",
                         self.server.JOBS[cat["id"]])
        self.assertEqual(self.bundle_focus, "Watch the fridge")
        stored = self._stored(cat["id"])
        self.assertEqual(stored["category"], cat["id"])
        self.assertEqual(stored["category_title"], "Fridge")
        self.assertEqual(stored["icon"], "🧊")
        # user categories keep run history like shipped ones
        self.assertTrue((Path(self.tmp.name) / "history" / cat["id"]).exists())

    def test_a_run_reports_what_it_cost(self):
        """A card carries the price of the run that made it.

        The token counts were always in the result envelope and the card
        always stored the envelope — but only the stopwatch was ever
        rendered, so an expensive card and a cheap one looked identical and
        the only evidence either way was a percentage in the top bar
        attributable to nothing.
        """
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": json.dumps(self.reply), "error": "",
            "meta": {"duration_ms": 5,
                     "usage": {"input_tokens": 30_000, "output_tokens": 8_000,
                               "cache_creation_input_tokens": 1_000,
                               "cache_read_input_tokens": 12_000}}}
        asyncio.run(self.server._generate("energy"))
        cost = self._stored()["meta"]["cost"]
        self.assertEqual(cost, {"input": 31_000, "output": 8_000,
                                "cached": 12_000, "total": 39_000})
        # The card and the budget read one number, derived once, server-side.
        self.assertEqual(cost["total"], usage_store.window_tokens())
        self.assertEqual(usage_store.window_breakdown()[0]["id"], "energy")

    def test_a_running_job_says_what_it_is_sending(self):
        """The size of the prompt is knowable before the answer is.

        A generation is minutes of spinner; carrying the prompt size on the
        job is what lets the card say how much of the home it just posted
        while it is still waiting to hear back.
        """
        seen = {}

        def capture(prompt, *a, **k):
            seen["job"] = dict(self.server.JOBS["energy"])
            seen["prompt"] = prompt
            return {"ok": True, "text": json.dumps(self.reply), "error": "",
                    "meta": {"duration_ms": 5}}

        engine.run_claude = capture
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(seen["job"]["state"], "generating")
        self.assertEqual(seen["job"]["prompt_chars"], len(seen["prompt"]))
        self.assertIn("entities", seen["job"])

    # -- the searching path -----------------------------------------------

    def _stub_search(self, result=None, orientation=None, boom=False):
        """Make both gather paths observable, and neither reach a real CLI."""
        self.calls = []

        async def fake_orientation(question=None):
            if boom:
                raise RuntimeError("HA is not answering")
            return orientation or {"entity_count": 512, "domains": {"sensor": 300},
                                   "areas": {"Hall": 12}, "anchors": []}

        self.ha_data.collect_orientation = fake_orientation

        def analyst(prompt, system, *a, **k):
            self.calls.append(("analyst", prompt, system))
            return result if result is not None else {
                "ok": True, "text": json.dumps(self.reply), "error": "",
                "meta": {"duration_ms": 4}}

        def snapshot(prompt, system, *a, **k):
            self.calls.append(("snapshot", prompt, system))
            return {"ok": True, "text": json.dumps(self.reply), "error": "",
                    "meta": {"duration_ms": 5}}

        engine.run_analyst = analyst
        engine.run_claude = snapshot

    def test_a_question_searches_instead_of_being_posted_the_whole_home(self):
        """The map is the prompt, not the territory.

        Posting 500 entities to answer a question about one room is the
        expensive thing this add-on does. The searching path sends what the
        home CONTAINS and lets Claude fetch the rows it decides it needs.
        """
        self._stub_search()
        self.server._set_job("custom-77", state="queued", question="Why cold?")
        asyncio.run(self.server._generate("custom-77"))
        self.assertEqual([c[0] for c in self.calls], ["analyst"])
        prompt = self.calls[0][1]
        self.assertIn("MAP OF THIS HOME", prompt)
        self.assertNotIn("HOME DATA SNAPSHOT", prompt)
        self.assertIn("QUESTION: Why cold?", prompt)
        # The framing every run gets does not depend on how the data arrives.
        self.assertIn("HYPOTHESIS BUDGET", prompt)
        self.assertEqual(self.server.JOBS["custom-77"]["state"], "done")
        # `entities` is what the run was GIVEN, and a search run is given none
        # — claiming a count here would mean something the snapshot path
        # means literally.
        self.assertEqual(self.server.JOBS["custom-77"]["entities"], 0)

    def test_a_failed_search_still_produces_a_card(self):
        """The snapshot path is the floor, not a mode.

        A search run depends on tools resolving and on the model choosing to
        stop. Neither is guaranteed, and a card must appear anyway.
        """
        self._stub_search(result={"ok": False, "text": "", "meta": {},
                                  "error": "max number of turns"})
        self.server._set_job("custom-78", state="queued", question="Why cold?")
        asyncio.run(self.server._generate("custom-78"))
        self.assertEqual([c[0] for c in self.calls], ["analyst", "snapshot"])
        self.assertIn("HOME DATA SNAPSHOT", self.calls[1][1])
        self.assertEqual(self.server.JOBS["custom-78"]["state"], "done")
        self.assertTrue(self._stored("custom-78")["title"])

    def test_a_map_that_cannot_be_collected_falls_back_too(self):
        """Not every failure is the model's. HA may simply not answer."""
        self._stub_search(boom=True)
        self.server._set_job("custom-79", state="queued", question="Why cold?")
        asyncio.run(self.server._generate("custom-79"))
        self.assertEqual([c[0] for c in self.calls], ["snapshot"])
        self.assertEqual(self.server.JOBS["custom-79"]["state"], "done")

    def test_snapshot_mode_never_searches(self):
        """The setting is honoured, not merely preferred."""
        settings_store.save({"gather_mode": "snapshot"})
        self._stub_search()
        self.server._set_job("custom-80", state="queued", question="Why cold?")
        asyncio.run(self.server._generate("custom-80"))
        self.assertEqual([c[0] for c in self.calls], ["snapshot"])

    def test_the_two_paths_share_one_card_contract(self):
        """Two preambles, one contract — a second 10 KB copy would drift."""
        self._stub_search()
        self.server._set_job("custom-81", state="queued", question="Why cold?")
        asyncio.run(self.server._generate("custom-81"))
        analyst_system = self.calls[0][2]
        self.assertIn("OUTPUT CONTRACT", analyst_system)
        self.assertIn("DESIGN SYSTEM", analyst_system)
        # ...and the analyst is NOT told it has no tools, which is the whole
        # difference between the two preambles.
        self.assertNotIn("NO tools available", analyst_system)
        self.assertIn("NO tools available", categories.SYSTEM_PROMPT)

    def test_a_run_with_no_usage_block_still_finishes(self):
        """Accounting never breaks the run it is accounting for."""
        engine.run_claude = lambda *a, **k: {
            "ok": True, "text": json.dumps(self.reply), "error": "", "meta": {}}
        asyncio.run(self.server._generate("energy"))
        self.assertEqual(self.server.JOBS["energy"]["state"], "done")
        self.assertEqual(self._stored()["meta"]["cost"]["total"], 0)
        self.assertEqual(usage_store.window_tokens(), 0)


class TestCardsDoNotAsk(InsightsServerCase):
    """A card reports; it does not ask.

    Runs used to store every hypothesis they raised on the card and render
    yes/no under the chart, while the Memory tab listed the same claims and
    the Findings badge counted neither. Three surfaces, one decision, and
    answering it on one left the other two looking unanswered. The queue is
    the only place a guess lives now, and the Findings tab is the only place
    it is answered. What a run does with its guesses is asserted in
    TestGenerateFlow, which is where a run is actually driven.
    """

    def test_the_card_question_endpoints_are_gone(self):
        """They were the card's half of a decision that now has one home.
        Left routed, they would be a second way to settle a guess — and the
        one that does not tell the Findings tab anything happened."""

        async def run():
            client = self._client()
            await client.start_server()
            try:
                for path in ("/api/questions",):
                    self.assertEqual((await client.get(path)).status, 404)
                for path in ("/api/questions/answer", "/api/questions/dismiss"):
                    resp = await client.post(path, json={
                        "insight_id": "energy", "question": "q", "answer": "a"})
                    self.assertEqual(resp.status, 404, path)
            finally:
                await client.close()

        asyncio.run(run())


class TestUserCategoryEndpoints(InsightsServerCase):
    def test_crud_and_status(self):
        old_generate = self.server._generate

        async def noop_generate(insight_id):
            self.server._set_job(insight_id, state="done", error="")

        self.server._generate = noop_generate

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/user_category", json={
                    "title": "Garage fridge", "focus": "Watch it", "icon": "🧊",
                    "refresh_hours": 6})
                self.assertEqual(resp.status, 200)
                cat = await resp.json()
                self.assertTrue(cat["id"].startswith("user-"))
                # creating queues an immediate first generation by default
                self.assertIn(self.server.JOBS.get(cat["id"], {}).get("state"),
                              ("queued", "done"))

                # visible in /api/status categories, flagged as user-defined
                resp = await client.get("/api/status")
                cats = {c["id"]: c for c in (await resp.json())["categories"]}
                self.assertIn(cat["id"], cats)
                self.assertTrue(cats[cat["id"]].get("user"))
                self.assertEqual(cats[cat["id"]]["refresh_hours"], 6)

                # /api/generate accepts the user id
                self.server.JOBS.clear()
                resp = await client.post("/api/generate",
                                         json={"category": cat["id"]})
                self.assertEqual(resp.status, 200)
                self.assertEqual((await resp.json())["queued"], [cat["id"]])

                # edit
                resp = await client.put(f"/api/user_category/{cat['id']}", json={
                    "title": "Fridge watch", "refresh_hours": None})
                self.assertEqual(resp.status, 200)
                rec = await resp.json()
                self.assertEqual(rec["title"], "Fridge watch")
                self.assertIsNone(rec["refresh_hours"])

                # validation
                resp = await client.post("/api/user_category", json={"title": ""})
                self.assertEqual(resp.status, 400)
                resp = await client.put(f"/api/user_category/{cat['id']}",
                                        json={"refresh_hours": 999})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/user_category/user-nope",
                                        json={"title": "X"})
                self.assertEqual(resp.status, 404)

                # generate_all includes enabled user categories
                self.server.JOBS.clear()
                resp = await client.post("/api/generate_all")
                self.assertIn(cat["id"], (await resp.json())["queued"])

                # delete cleans up definition, insight, history, feedback.
                # A fresh stamp, or the prune empties history first and the
                # "history removed" assert below passes without testing it.
                self._save(cat["id"], f"{FRESH_DAY}T10:00:00")
                feedback_store.add_feedback(cat["id"], "note")
                resp = await client.delete(f"/api/user_category/{cat['id']}")
                self.assertEqual(resp.status, 200)
                self.assertFalse(
                    (Path(self.tmp.name) / f"{cat['id']}.json").exists())
                self.assertFalse(
                    (Path(self.tmp.name) / "history" / cat["id"]).exists())
                self.assertEqual(feedback_store.list_feedback(cat["id"]), [])
                resp = await client.delete(f"/api/user_category/{cat['id']}")
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        try:
            asyncio.run(run())
        finally:
            self.server._generate = old_generate

    def test_scheduler_sees_user_categories(self):
        cat = user_categories.create(
            {"title": "T", "focus": "F", "refresh_hours": 1})
        eff = self.server.resolve_category(cat["id"])
        now = time.mktime(time.strptime("2026-07-18T12:00:00", "%Y-%m-%dT%H:%M:%S"))
        self.assertTrue(self.server._refresh_due(eff, "2026-07-18T10:00:00", now))
        self.assertFalse(self.server._refresh_due(eff, "2026-07-18T11:30:00", now))
        user_categories.update(cat["id"], {"enabled": False})
        eff = self.server.resolve_category(cat["id"])
        self.assertFalse(self.server._refresh_due(eff, "2026-07-18T10:00:00", now))

    def test_load_insights_orders_user_after_builtin(self):
        cat = user_categories.create({"title": "U", "focus": "f"})
        self._save("custom-99", "2026-07-18T12:00:00", category="custom")
        self._save(cat["id"], "2026-07-18T10:00:00")
        self._save("energy", "2026-07-18T09:00:00")
        ids = [i["id"] for i in self.server.load_insights()]
        self.assertEqual(ids, ["energy", cat["id"], "custom-99"])

    def test_orphaned_user_insight_hidden(self):
        self._save("user-123", "2026-07-18T10:00:00")
        self.assertEqual(self.server.load_insights(), [])


class TestCardDeletionAndRenaming(InsightsServerCase):
    """Every card can be deleted and renamed — /api/card/{id} is the one ✕."""

    def test_deleting_a_builtin_card_leaves_nothing_behind(self):
        """Deleted means deleted, for every kind of card. A shipped card's
        definition lives in the code so it can only be hidden — but that is
        the mechanism, not an offer, and the panel no longer keeps a
        graveyard to restore from."""
        async def run():
            client = self._client()
            await client.start_server()
            try:
                self._save("energy", "2026-07-18T10:00:00")
                feedback_store.add_feedback("energy", "note")
                card_tags.set_tags("energy", {"id": "energy", "category": "energy",
                                              "tags": ["dryer"]}, ["dryer"])

                resp = await client.delete("/api/card/energy")
                self.assertEqual(resp.status, 200)

                # gone from the dashboard, the scheduler, and manual generation
                resp = await client.get("/api/status")
                status = await resp.json()
                self.assertNotIn("energy", [c["id"] for c in status["categories"]])
                self.assertNotIn("removed_categories", status)
                resp = await client.post("/api/generate", json={"category": "energy"})
                self.assertEqual(resp.status, 400)
                resp = await client.post("/api/generate_all")
                self.assertNotIn("energy", (await resp.json())["queued"])

                # and its stored data really is gone — no ghost card either,
                # and no tag edits waiting to be inherited by a later card
                self.assertFalse((Path(self.tmp.name) / "energy.json").exists())
                self.assertFalse((Path(self.tmp.name) / "history" / "energy").exists())
                self.assertEqual(feedback_store.list_feedback("energy"), [])
                self.assertEqual(self.server.load_insights(), [])
                self.assertEqual(
                    card_tags.effective_tags(
                        {"id": "energy", "category": "energy", "tags": ["dryer"]}),
                    ["energy", "dryer"])
            finally:
                await client.close()

        asyncio.run(run())

    def test_removed_builtin_insight_file_is_not_a_ghost_card(self):
        """A leftover file for a removed card must not resurface as an Ask."""
        self._save("energy", "2026-07-18T10:00:00")
        prompt_store.save_override("energy", {"hidden": True})
        self.assertEqual(self.server.load_insights(), [])

    def test_user_and_adhoc_cards_are_deleted_outright(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                cat = user_categories.create({"title": "Fridge", "focus": "watch"})
                self._save(cat["id"], "2026-07-18T10:00:00")
                self._save("custom-1", "2026-07-18T11:00:00", category="custom")

                resp = await client.delete(f"/api/card/{cat['id']}")
                self.assertEqual(resp.status, 200)
                self.assertIsNone(user_categories.get(cat["id"]))
                self.assertFalse((Path(self.tmp.name) / f"{cat['id']}.json").exists())

                resp = await client.delete("/api/card/custom-1")
                self.assertEqual(resp.status, 200)
                self.assertFalse((Path(self.tmp.name) / "custom-1.json").exists())

                resp = await client.delete("/api/card/custom-1")
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())

    def test_failed_ask_with_no_insight_can_be_cleared(self):
        """A card that only exists as a failed job was undeletable before."""
        async def run():
            client = self._client()
            await client.start_server()
            try:
                self.server._set_job("custom-42", state="error", error="boom")
                resp = await client.delete("/api/card/custom-42")
                self.assertEqual(resp.status, 200)
                self.assertNotIn("custom-42", self.server.JOBS)
            finally:
                await client.close()

        asyncio.run(run())

    def test_builtin_card_can_be_renamed(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.put("/api/prompt/energy",
                                        json={"title": "Power bill", "icon": "🔌"})
                self.assertEqual(resp.status, 200)
                rec = await resp.json()
                self.assertEqual(rec["title"], "Power bill")
                self.assertEqual(rec["icon"], "🔌")
                self.assertEqual(rec["default_title"],
                                 categories.get_category("energy")["title"])

                resp = await client.get("/api/status")
                cat = {c["id"]: c for c in (await resp.json())["categories"]}["energy"]
                self.assertEqual(cat["title"], "Power bill")
                self.assertEqual(cat["icon"], "🔌")
                self.assertTrue(cat["renamed"])

                # the name reaches generation, so new insights carry it
                eff = self.server.resolve_category("energy")
                self.assertEqual(eff["title"], "Power bill")

                # blanking restores the shipped name
                resp = await client.put("/api/prompt/energy",
                                        json={"title": "", "icon": ""})
                rec = await resp.json()
                self.assertEqual(rec["title"],
                                 categories.get_category("energy")["title"])
                self.assertEqual(rec["overridden"], [])

                resp = await client.put("/api/prompt/energy", json={"title": 5})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/prompt/energy", json={"hidden": "yes"})
                self.assertEqual(resp.status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_adhoc_card_can_be_renamed(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                self._save("custom-7", "2026-07-18T10:00:00", category="custom",
                           category_title="Custom", icon="✨")
                resp = await client.put("/api/insight/custom-7",
                                        json={"name": "Fridge answer", "icon": "🧊"})
                self.assertEqual(resp.status, 200)
                self.assertEqual((await resp.json())["name"], "Fridge answer")

                stored = json.loads(
                    (Path(self.tmp.name) / "custom-7.json").read_text())
                self.assertEqual(stored["category_title"], "Fridge answer")
                self.assertEqual(stored["icon"], "🧊")
                # the rest of the card survives the patch untouched
                self.assertEqual(stored["html"], "<p>x</p>")

                # an empty icon falls back rather than blanking the card
                resp = await client.put("/api/insight/custom-7", json={"icon": ""})
                self.assertEqual((await resp.json())["icon"], "✨")

                resp = await client.put("/api/insight/custom-7", json={"name": " "})
                self.assertEqual(resp.status, 400)
                resp = await client.put("/api/insight/custom-nope", json={"name": "X"})
                self.assertEqual(resp.status, 404)
            finally:
                await client.close()

        asyncio.run(run())


class TestFeedbackEndpoints(InsightsServerCase):
    def _queued_facts(self):
        facts = []
        for f in sorted(self.server.MEMORY_INBOX_DIR.glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    facts.append(json.loads(line))
        return facts

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

    def test_feedback_roundtrip_and_memory_handoff(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post("/api/insight/energy/feedback",
                                         json={"feedback": "Show cost in dollars"})
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                self.assertEqual(
                    [e["text"] for e in data["feedback"]], ["Show cost in dollars"])
                ts = data["added"]["ts"]
                # queued to the home's memory as a durable preference
                self.assertEqual(self.calls, [])
                queued = self._queued_facts()
                self.assertTrue(any('"Energy" insight card: Show cost in dollars'
                                    in f["fact"] for f in queued), queued)

                resp = await client.get("/api/insight/energy/feedback")
                self.assertEqual(
                    [e["text"] for e in (await resp.json())["feedback"]],
                    ["Show cost in dollars"])

                resp = await client.delete(f"/api/insight/energy/feedback/{ts}")
                self.assertEqual(resp.status, 200)
                resp = await client.delete(f"/api/insight/energy/feedback/{ts}")
                self.assertEqual(resp.status, 404)

                # validation: empty text, ad-hoc ids, malformed ts
                resp = await client.post("/api/insight/energy/feedback",
                                         json={"feedback": ""})
                self.assertEqual(resp.status, 400)
                resp = await client.post("/api/insight/custom-1/feedback",
                                         json={"feedback": "x"})
                self.assertEqual(resp.status, 400)
                resp = await client.delete("/api/insight/energy/feedback/abc")
                self.assertEqual(resp.status, 400)
            finally:
                await client.close()

        asyncio.run(run())

    def test_feedback_works_for_user_categories(self):
        cat = user_categories.create({"title": "Fridge", "focus": "watch"})

        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.post(f"/api/insight/{cat['id']}/feedback",
                                         json={"feedback": "Celsius please"})
                self.assertEqual(resp.status, 200)
            finally:
                await client.close()

        asyncio.run(run())
        self.assertIn('"Fridge" insight card: Celsius please',
                      self._queued_facts()[0]["fact"])


class TestCardServer(InsightsServerCase):
    def test_token_created_and_stable(self):
        t1 = self.server.get_card_token()
        t2 = self.server.get_card_token()
        self.assertEqual(t1, t2)
        self.assertGreaterEqual(len(t1), 16)

    def test_card_info_endpoint(self):
        async def run():
            client = self._client()
            await client.start_server()
            try:
                resp = await client.get("/api/card_info")
                self.assertEqual(resp.status, 200)
                data = await resp.json()
                # /local mirror enabled (dir created) and addressable
                self.assertTrue(data["www_cards"])
                self.assertEqual(data["local_dir"], "/local/bruh_insights")
                self.assertEqual(
                    data["local_suffix"],
                    f"-{self.server.get_card_token()}.html")
            finally:
                await client.close()

        asyncio.run(run())
        self.assertTrue(self.server.WWW_CARD_DIR.is_dir())

    def test_card_mirror_lifecycle(self):
        """card_info syncs the /local mirror; save/delete keep it fresh."""
        self._save("energy", "2026-07-18T10:00:00")
        token = self.server.get_card_token()
        mirror = self.server.WWW_CARD_DIR / f"energy-{token}.html"

        async def run():
            client = self._client()
            await client.start_server()
            try:
                # first ▦ open: mirror dir created and backfilled
                await client.get("/api/card_info")
                self.assertTrue(mirror.exists())
                text = mirror.read_text()
                self.assertIn("<p>x</p>", text)
                self.assertIn("location.reload", text)

                # a regenerated insight refreshes its mirror on save
                self._save("energy", "2026-07-18T11:00:00", html="<p>y</p>")
                self.assertIn("<p>y</p>", mirror.read_text())

                # stale files (old token / deleted insight) are swept on sync
                stale = self.server.WWW_CARD_DIR / "energy-oldtoken.html"
                stale.write_text("old")
                await client.get("/api/card_info")
                self.assertFalse(stale.exists())

                # deleting the insight removes its mirror
                resp = await client.delete("/api/insight/energy")
                self.assertEqual(resp.status, 200)
                self.assertFalse(mirror.exists())
            finally:
                await client.close()

        asyncio.run(run())

    def test_mirror_noop_until_first_use(self):
        """No writes anywhere near /config/www before the ▦ dialog is used."""
        self._save("energy", "2026-07-18T10:00:00")
        self.assertFalse(self.server.WWW_CARD_DIR.exists())


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
        self._write(self.ha_data.MEMORY_FILE, "m" * 100_000)
        self._write(self.ha_data.CONTEXT_FILE, "c" * 100_000)
        ctx = self.ha_data._read_context()
        self.assertLessEqual(
            len(ctx), self.ha_data.MEMORY_CHARS + self.ha_data.CONTEXT_CHARS + 2)

    def test_memory_has_its_own_budget(self):
        """A memory document larger than the CLAUDE.md excerpt's budget is
        injected whole, and does not eat the excerpt's share on its way.

        The two used to share CONTEXT_CHARS, memory first, which truncated
        any memory.md over 4 KB mid-fact *and* starved the house context
        whenever memory filled the budget. memory_max_kb defaults to 32."""
        self._write(self.ha_data.MEMORY_FILE, "m" * 20_000)
        self._write(self.ha_data.CONTEXT_FILE, "c" * 3_000)
        ctx = self.ha_data._read_context()
        self.assertEqual(ctx.count("m"), 20_000)
        self.assertEqual(ctx.count("c"), 3_000)

    def test_a_full_memory_document_survives_injection(self):
        """The budget is sized off memory_max_kb — the largest document the
        consolidator is allowed to write must arrive intact, or the cap and
        the injection disagree about what "the memory" is."""
        self.assertGreaterEqual(self.ha_data.MEMORY_CHARS, 32 * 1024)

    def test_shrink_trims_entities_before_context(self):
        big = "n" * 3000
        bundle = {
            "entities": [{"e": f"sensor.x{i}", "n": big} for i in range(60)],
            "context": "learned facts",
        }
        out = self.ha_data._shrink_to_budget(bundle)
        self.assertEqual(out["context"], "learned facts")
        self.assertLess(len(out["entities"]), 50)

    def test_shrink_trims_context_before_dropping_it(self):
        """Now that a whole memory document fits in `context`, popping it is
        no longer a proportionate response to being slightly over budget:
        that trades everything brAIn has learned for a few hundred bytes."""
        big = "n" * 3000
        bundle = {
            "entities": [{"e": f"sensor.x{i}", "n": big} for i in range(20)],
            "context": "c" * 70_000,
        }
        out = self.ha_data._shrink_to_budget(bundle)
        self.assertIn("context", out)
        self.assertLess(len(out["context"]), 70_000)
        self.assertEqual(len(out["entities"]), 20)

    def test_shrink_still_drops_context_when_trimming_cannot_fit(self):
        """Last resort is still last resort: when the rest of the bundle
        fills the budget on its own, a trimmed context is no more shippable
        than a whole one."""
        big = "n" * 6000
        bundle = {
            "entities": [{"e": f"sensor.x{i}", "n": big} for i in range(20)],
            "context": "c" * 70_000,
        }
        out = self.ha_data._shrink_to_budget(bundle)
        self.assertNotIn("context", out)
        self.assertEqual(len(out["entities"]), 20)


class TestWhyTheNumberIsAnEstimate(unittest.TestCase):
    """When the tracker fails, the pill must say so rather than freeze.

    The fallback estimate counts brAIn's own insight runs against a rough
    plan allowance. On a home that mostly uses the terminal and the chat
    that is 0%, forever, with the weekly window simply gone — which is
    exactly what "the usage sensor is unresponsive" looks like from the
    panel. Worse, the only thing the popover had to say about it was "sign
    in with your Claude subscription", i.e. telling somebody who is signed
    in to redo the one thing that was working.

    So `budget_state` carries the tracker's own reason whenever it is not
    reporting the account's numbers, and carries nothing extra when it is.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old_usage = usage_store.USAGE_FILE
        self._old_limits = usage_store.LIMITS_FILE
        usage_store.USAGE_FILE = os.path.join(self.tmp.name, "usage.json")
        usage_store.LIMITS_FILE = os.path.join(self.tmp.name, "limits.json")

        def restore():
            usage_store.USAGE_FILE = self._old_usage
            usage_store.LIMITS_FILE = self._old_limits

        self.addCleanup(restore)

    def _limits(self, payload):
        with open(usage_store.LIMITS_FILE, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def _stamp(self, minutes_ago=0):
        when = (datetime.datetime.now(datetime.timezone.utc)
                - datetime.timedelta(minutes=minutes_ago))
        return when.isoformat()

    def test_a_working_tracker_carries_no_excuse(self):
        self._limits({
            "updated_at": self._stamp(),
            "five_hour": {"utilization": 41, "resets_at": self._stamp()},
            "seven_day": {"utilization": 12, "resets_at": self._stamp()},
        })
        state = usage_store.budget_state({})
        self.assertEqual(state["source"], "account")
        self.assertEqual(state["used_percent"], 41.0)
        self.assertNotIn("limits", state)

    def test_no_file_at_all_says_the_tracker_never_reported(self):
        state = usage_store.budget_state({})
        self.assertEqual(state["source"], "estimate")
        self.assertEqual(state["limits"]["code"], "not_running")

    def test_a_rate_limit_travels_with_the_estimate(self):
        """The case that produced the complaint: a 429 backoff runs longer
        than the two-hour staleness window on purpose, so the reading always
        ages out — and the reason the tracker recorded beside it is the one
        thing that makes that survivable."""
        self._limits({
            "updated_at": self._stamp(minutes_ago=200),
            "five_hour": {"utilization": 41},
            "last_error": "http_429",
            "last_error_detail": "Anthropic rate-limited the usage endpoint",
            "next_attempt_at": self._stamp(minutes_ago=-90),
        })
        state = usage_store.budget_state({})
        self.assertEqual(state["source"], "estimate")
        self.assertEqual(state["limits"]["code"], "http_429")
        self.assertIn("rate-limited", state["limits"]["detail"])
        self.assertGreater(state["limits"]["next_attempt"], time.time())

    def test_a_settled_auth_fact_is_reported_as_itself(self):
        self._limits({"updated_at": self._stamp(),
                      "error": "api_key_has_no_usage_limits"})
        state = usage_store.budget_state({})
        self.assertEqual(state["limits"]["code"], "api_key_has_no_usage_limits")

    def test_stale_with_no_recorded_reason_is_stale(self):
        self._limits({"updated_at": self._stamp(minutes_ago=200),
                      "five_hour": {"utilization": 41}})
        self.assertEqual(usage_store.budget_state({})["limits"]["code"], "stale")

    def test_a_reading_with_no_timestamp_is_never_fresh(self):
        """The staleness test used to be skipped whenever `updated_at` was
        missing, so a file holding numbers and no stamp read as current
        forever — a reading that can never go stale is a reading nothing
        can correct."""
        self._limits({"five_hour": {"utilization": 41}})
        state = usage_store.budget_state({})
        self.assertEqual(state["source"], "estimate")
        self.assertEqual(state["limits"]["code"], "stale")


class TestAuthVerdictIsReEarned(unittest.TestCase):
    """A settled auth verdict has to age out, and one check at a time.

    `_check_auth_bg` used to run at startup, after a credential was saved,
    and after the guided sign-in — never again. So a credential that died
    mid-week was reported by nothing: /api/status went on serving the
    startup verdict, the chip stayed hidden because a working login is not
    news, and the first real symptom was voice and automations failing off
    one store while the terminal worked off another. Same shape as the
    usage tracker's: a reading nothing re-earns is a reading nothing can
    correct.
    """

    @classmethod
    def setUpClass(cls):
        cls.server = importlib.import_module("server")

    def setUp(self):
        self._old = dict(self.server.AUTH_CHECK)
        self._old_interval = self.server.AUTH_RECHECK_S
        self.addCleanup(self._restore)

    def _restore(self):
        self.server.AUTH_CHECK.clear()
        self.server.AUTH_CHECK.update(self._old)
        self.server.AUTH_RECHECK_S = self._old_interval

    def _verdict(self, state, age_s):
        self.server.AUTH_CHECK.update(
            state=state, error="", checked_at=time.time() - age_s,
            running=False)

    def test_a_fresh_verdict_is_left_alone(self):
        self._verdict("ok", 60)
        self.assertFalse(self.server._auth_verdict_is_stale())

    def test_an_old_pass_is_re_earned(self):
        """The whole point: "ok" from days ago is not evidence of anything."""
        self._verdict("ok", self.server.AUTH_RECHECK_S + 1)
        self.assertTrue(self.server._auth_verdict_is_stale())

    def test_an_old_failure_is_re_earned_too(self):
        """Somebody who fixes their login in the terminal must not have to
        restart the add-on for the panel to notice."""
        self._verdict("failed", self.server.AUTH_RECHECK_S + 1)
        self.assertTrue(self.server._auth_verdict_is_stale())

    def test_unchecked_and_in_flight_are_not_stale(self):
        """Neither has a verdict to age: one has none, one is earning it."""
        for state in ("unchecked", "checking"):
            self.server.AUTH_CHECK.update(
                state=state, checked_at=0, running=False)
            with self.subTest(state=state):
                self.assertFalse(self.server._auth_verdict_is_stale())

    def test_a_silent_check_in_flight_is_not_stale_either(self):
        """The case the state alone cannot see. An unannounced re-check
        leaves the verdict reading "ok", so without consulting `running`
        every subsequent poll would find it stale and try to start another
        one — the guard returning False each time, but only after asking."""
        self.server.AUTH_CHECK.update(
            state="ok", error="", checked_at=0, running=True)
        self.assertFalse(self.server._auth_verdict_is_stale())

    def test_two_callers_in_one_tick_start_one_check(self):
        """The guard has to flip the state synchronously.

        `asyncio.create_task` only schedules — nothing inside the coroutine
        runs until the loop yields — so a guard reading a state its own
        task has not set yet is no guard at all. That was reachable before
        this: `h_setup_status` is polled, and /api/status is polled harder.
        Two real `claude -p` calls for one question is the cheap half of
        what goes wrong; the expensive half is the second one landing on a
        credential the first is still deciding about.
        """
        async def drive():
            self.server.AUTH_CHECK.update(state="ok", error="", checked_at=0)
            started = [self.server.start_auth_check() for _ in range(3)]
            tasks = [t for t in asyncio.all_tasks()
                     if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            return started

        started = asyncio.run(drive())
        self.assertEqual(started, [True, False, False])
        self.assertEqual(self.server.AUTH_CHECK["state"], "checking")

    def test_a_check_nobody_asked_for_does_not_announce_itself(self):
        """A six-hourly re-verification is not news.

        "Verifying Claude…" answers what a person just did; a chip appearing
        unbidden in the top bar — and shifting its layout — while somebody
        reads a card is the "a permanently green chip does not belong there"
        rule with the timing changed. The standing verdict stays up until
        there is a new one, which is also the more honest answer.
        """
        async def drive():
            self.server.AUTH_CHECK.update(
                state="ok", error="", checked_at=0, running=False)
            started = self.server.start_auth_check(announce=False)
            for task in asyncio.all_tasks():
                if task is not asyncio.current_task():
                    task.cancel()
            return started

        self.assertTrue(asyncio.run(drive()))
        self.assertEqual(self.server.AUTH_CHECK["state"], "ok")
        self.assertTrue(self.server.AUTH_CHECK["running"])


class TestBriefReadsTheHealthVerdict(unittest.TestCase):
    """`_send_brief` awaited `_diagnostics_payload()` — a plain function
    returning a dict — so every call raised inside a `try` that logged at
    info and carried on with an empty verdict. The health trigger in
    `brief.worth_saying` could therefore never fire. Driven, not grepped."""

    def test_a_degraded_verdict_reaches_worth_saying(self):
        server = importlib.import_module("server")
        brief = importlib.import_module("brief")
        seen = {}
        saved = (server._diagnostics_payload, server._brief_overnight,
                 server.findings_store.list_all, brief.worth_saying)
        try:
            server._diagnostics_payload = lambda: {
                "health": {"state": "degraded", "reason": "listener down"}}

            async def overnight(now):
                return {}
            server._brief_overnight = overnight
            server.findings_store.list_all = lambda: []

            def worth(state):
                seen.update(state)
                return []
            brief.worth_saying = worth
            asyncio.run(server._send_brief(1_800_000_000.0))
        finally:
            (server._diagnostics_payload, server._brief_overnight,
             server.findings_store.list_all, brief.worth_saying) = saved
        self.assertEqual(seen.get("health", {}).get("state"), "degraded")


if __name__ == "__main__":
    unittest.main()
