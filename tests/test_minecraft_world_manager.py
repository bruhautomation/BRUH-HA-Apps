#!/usr/bin/env python3
"""Behaviour tests for scripts/world-manager.sh and the ensure_worlds_layout
migration in run.sh.

1.3.0 introduces switchable server profiles. Each profile is a full server
root at /config/minecraft-worlds/<name>/, and /config/minecraft is a
symlink to the active profile. These tests lock in:

* `list` enumerates profiles with size + active flag.
* `create` validates the name, refuses duplicates, stages an empty
  skeleton + eula.txt + server.properties + plugins/ + mods/ + the
  per-profile backup dir.
* `active` reads the symlink target.
* `delete` refuses the active profile, removes both the profile dir
  AND its backup tree otherwise.
* The run.sh `ensure_worlds_layout` function migrates a legacy
  /config/minecraft (plain dir) into /config/minecraft-worlds/<active>
  and relinks the symlink, so existing 1.2.x installs keep their world.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON = BASE_DIR / "bruh-minecraft-server"
WORLD_MANAGER = ADDON / "scripts" / "world-manager.sh"
RUN_SH = ADDON / "run.sh"


def _run_manager(root: Path, *args: str, env_extra: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "MC_WORLDS_DIR": str(root / "minecraft-worlds"),
        "MC_BACKUPS_ROOT": str(root / "minecraft-backups"),
        # Default to a non-existent options file so `active` is deterministic
        # regardless of any real /data/options.json on the host running tests.
        "MC_OPTIONS_FILE": str(root / "options.json"),
    }
    if env_extra:
        env.update(env_extra)
    # Override /config/minecraft link location by symlinking inside `root` —
    # world-manager.sh uses /config/minecraft directly, so we can't override
    # that path via env. For `active`, the script falls back to 'default'
    # when no symlink exists, which is fine for tests that don't need a
    # specific active world set.
    return subprocess.run(
        ["bash", str(WORLD_MANAGER), *args],
        env=env, capture_output=True, text=True, check=False, timeout=30,
    )


class TestWorldManagerCreate(unittest.TestCase):
    def test_create_stages_full_skeleton(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = _run_manager(root, "create", "survival")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            wdir = root / "minecraft-worlds" / "survival"
            self.assertTrue(wdir.is_dir())
            self.assertTrue((wdir / "plugins").is_dir())
            self.assertTrue((wdir / "mods").is_dir())
            self.assertTrue((wdir / "server.properties").is_file())
            self.assertTrue((wdir / "eula.txt").is_file())
            self.assertTrue((root / "minecraft-backups" / "survival").is_dir())

    def test_create_rejects_invalid_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for bad in ("", "has spaces", "dot.name", "a" * 33, "bad/slash"):
                proc = _run_manager(root, "create", bad)
                self.assertNotEqual(proc.returncode, 0, f"accepted bad name: {bad!r}")

    def test_create_rejects_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = _run_manager(root, "create", "pvp")
            self.assertEqual(first.returncode, 0, first.stderr)
            dup = _run_manager(root, "create", "pvp")
            self.assertNotEqual(dup.returncode, 0)
            self.assertIn("already exists", dup.stderr)

    def test_create_with_seed_writes_seed_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = _run_manager(root, "create", "seeded", "12345")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            props = (root / "minecraft-worlds" / "seeded" / "server.properties").read_text()
            self.assertIn("level-seed=12345", props)


class TestWorldManagerList(unittest.TestCase):
    def test_list_enumerates_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run_manager(root, "create", "alpha")
            _run_manager(root, "create", "beta")
            proc = _run_manager(root, "list")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            names = sorted(line.split("\t")[0] for line in proc.stdout.strip().splitlines() if line)
            self.assertEqual(names, ["alpha", "beta"])

    def test_list_reports_active_flag(self):
        """When /config/minecraft points at a profile, list should flag it."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run_manager(root, "create", "alpha")
            _run_manager(root, "create", "beta")
            proc = _run_manager(root, "list")
            # Without a symlink set up, the script defaults to 'default'
            # as active, which isn't in our list. All entries should
            # therefore show active=false.
            for line in proc.stdout.strip().splitlines():
                parts = line.split("\t")
                self.assertEqual(parts[2], "false")


class TestWorldManagerActive(unittest.TestCase):
    """1.7.0: `active` reads the add-on option (the source of truth run.sh
    boots from) before falling back to the symlink — fixing a stale-state
    bug where a legacy install (no symlink yet) always reported 'default'
    even after the operator switched profiles."""

    def test_active_reads_options_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opts = root / "options.json"
            opts.write_text('{"active_world": "creative", "eula": true}')
            proc = _run_manager(
                root, "active",
                env_extra={"MC_OPTIONS_FILE": str(opts)},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "creative")

    def test_active_falls_back_to_default_without_option(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = _run_manager(
                root, "active",
                env_extra={"MC_OPTIONS_FILE": str(root / "missing.json")},
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(proc.stdout.strip(), "default")

    def test_active_ignores_invalid_option_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            opts = root / "options.json"
            opts.write_text('{"active_world": "bad name/with slash"}')
            proc = _run_manager(
                root, "active",
                env_extra={"MC_OPTIONS_FILE": str(opts)},
            )
            self.assertEqual(proc.stdout.strip(), "default")


class TestWorldManagerDelete(unittest.TestCase):
    def test_delete_removes_profile_and_backups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _run_manager(root, "create", "tmpworld")
            wdir = root / "minecraft-worlds" / "tmpworld"
            bdir = root / "minecraft-backups" / "tmpworld"
            self.assertTrue(wdir.exists())
            self.assertTrue(bdir.exists())
            proc = _run_manager(root, "delete", "tmpworld")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertFalse(wdir.exists())
            self.assertFalse(bdir.exists())

    def test_delete_refuses_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = _run_manager(root, "delete", "nope")
            self.assertNotEqual(proc.returncode, 0)

    def test_delete_rejects_invalid_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proc = _run_manager(root, "delete", "../evil")
            self.assertNotEqual(proc.returncode, 0)


class TestWorldManagerSwitch(unittest.TestCase):
    """Regression for 1.2.8: `world-manager.sh switch` used to POST a
    bare {"options": {"active_world": "<name>"}} to the Supervisor. The
    Supervisor replaces the options object wholesale and validates the
    full schema, so every other required field appeared missing and the
    request was rejected with
        "Missing option 'allow_nether' in root in BRUH Minecraft Server …"
    The fix: GET /addons/self/info, merge the existing options with the
    new active_world, then POST the merged object.
    """

    def _start_mock_supervisor(self):
        """Start a tiny HTTP server that impersonates the Supervisor's
        /addons/self/info + /addons/self/options endpoints. Records every
        POST body so the test can assert the merged payload."""
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import json
        import threading

        state = {
            "existing_options": {
                "eula": True,
                "allow_nether": True,
                "difficulty": "normal",
                "active_world": "default",
            },
            "posts": [],
        }

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_args, **_kwargs):  # silence
                pass

            def do_GET(self):
                if self.path == "/addons/self/info":
                    body = json.dumps({
                        "result": "ok",
                        "data": {"options": state["existing_options"]},
                    }).encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_POST(self):
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length)
                try:
                    parsed = json.loads(raw.decode())
                except Exception:
                    parsed = raw.decode(errors="replace")
                state["posts"].append({"path": self.path, "body": parsed})

                if self.path == "/addons/self/options":
                    opts = parsed.get("options") if isinstance(parsed, dict) else None
                    if not isinstance(opts, dict):
                        self._err("invalid options")
                        return
                    if "allow_nether" not in opts:
                        self._err("Missing option 'allow_nether' in root")
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    body = b'{"result":"ok"}'
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()

            def _err(self, msg):
                body = json.dumps({"result": "error", "message": msg}).encode()
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        return httpd, state

    def test_switch_merges_existing_options_before_post(self):
        httpd, state = self._start_mock_supervisor()
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "minecraft-worlds" / "survival").mkdir(parents=True)
                proc = _run_manager(
                    root, "switch", "survival",
                    env_extra={
                        "SUPERVISOR_TOKEN": "fake-token",
                        "SUPERVISOR_API_URL": base,
                    },
                )
            self.assertEqual(proc.returncode, 0, proc.stderr)

            # One info GET, one options POST.
            posts = state["posts"]
            self.assertEqual(len(posts), 1, posts)
            self.assertEqual(posts[0]["path"], "/addons/self/options")

            merged = posts[0]["body"]["options"]
            # The new value must land…
            self.assertEqual(merged["active_world"], "survival")
            # …without stripping any of the required / existing keys.
            self.assertTrue(merged["eula"])
            self.assertTrue(merged["allow_nether"])
            self.assertEqual(merged["difficulty"], "normal")
        finally:
            httpd.shutdown()

    def test_switch_reports_supervisor_error_body(self):
        httpd, state = self._start_mock_supervisor()
        # Remove allow_nether from existing options so the mock Supervisor
        # returns the same 400 the user saw in production — guaranteeing
        # the error path surfaces the Supervisor message.
        state["existing_options"].pop("allow_nether")
        try:
            host, port = httpd.server_address
            base = f"http://{host}:{port}"
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                (root / "minecraft-worlds" / "survival").mkdir(parents=True)
                proc = _run_manager(
                    root, "switch", "survival",
                    env_extra={
                        "SUPERVISOR_TOKEN": "fake-token",
                        "SUPERVISOR_API_URL": base,
                    },
                )
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("Missing option 'allow_nether'", proc.stderr)
        finally:
            httpd.shutdown()


class TestRunShMigration(unittest.TestCase):
    """Run just the ensure_worlds_layout function from run.sh against a
    tempdir that simulates a legacy (pre-1.3.0) install. The function
    should move /config/minecraft -> /config/minecraft-worlds/default
    and create the symlink."""

    def _run_migration(self, config_root: Path, active: str = "default") -> subprocess.CompletedProcess:
        source = RUN_SH.read_text()
        start = source.index("ensure_worlds_layout() {")
        # Match the first top-level closing brace at column 0
        remaining = source[start:]
        brace = 0
        body = ""
        for i, ch in enumerate(remaining):
            if ch == "{": brace += 1
            elif ch == "}":
                brace -= 1
                if brace == 0:
                    body = remaining[: i + 1]
                    break
        wrapper = textwrap.dedent(f"""
            set -o pipefail
            export MC_WORLDS_DIR={str(config_root / "minecraft-worlds")!r}
            export MC_BACKUPS_ROOT={str(config_root / "minecraft-backups")!r}
            # Redefine the absolute /config/minecraft paths the function
            # hard-codes by chrooting the whole tree: we can't actually
            # chroot in tests, so instead rewrite the function to take
            # these as env. The real install uses /config directly.
            bashio() {{ return 0; }}
            # Fake bashio::log.* to plain echo
            for fn in bashio::log.info bashio::log.warning bashio::log.error bashio::log.notice bashio::log.debug; do
                eval "${{fn}}() {{ printf '[%s] %s\\n' \\"$fn\\" \\"$*\\" >&2; }}"
            done
            export ACTIVE_WORLD={active!r}
        """)
        # Substitute /config/minecraft with our tmp dir inside the body
        patched = body.replace('"/config/minecraft"', f'"{config_root}/minecraft"')
        patched = patched.replace('"/config/minecraft-backups"', f'"{config_root}/minecraft-backups"')
        # MC_SERVER_LINK / MC_BACKUPS_ROOT references live in other places;
        # the function uses hardcoded "/config/minecraft" + "/config/minecraft-backups"
        # for the symlink targets. Matched above.
        patched = patched.replace(
            '"/config/minecraft:${world_dir}" "/config/minecraft-backups:${backup_dir}"',
            f'"{config_root}/minecraft:${{world_dir}}" "{config_root}/minecraft-backups:${{backup_dir}}"',
        )
        script = wrapper + patched + "\nensure_worlds_layout\n"
        return subprocess.run(
            ["bash", "-c", script],
            capture_output=True, text=True, check=False, timeout=30,
        )

    def test_migrates_legacy_directory_to_default_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            legacy = root / "minecraft"
            legacy.mkdir()
            (legacy / "world").mkdir()
            (legacy / "server.properties").write_text("motd=legacy\n")
            # No profile dirs yet
            self.assertFalse((root / "minecraft-worlds").exists())

            proc = self._run_migration(root)
            self.assertEqual(proc.returncode, 0, proc.stderr)

            # Legacy contents now live under default
            default_dir = root / "minecraft-worlds" / "default"
            self.assertTrue((default_dir / "server.properties").is_file())
            self.assertTrue((default_dir / "world").is_dir())
            # And /config/minecraft (our tmp equivalent) is a symlink
            link = root / "minecraft"
            self.assertTrue(link.is_symlink())
            self.assertEqual(os.readlink(link), str(default_dir))

    def test_relinks_when_active_world_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Set up two profiles up front and link to "first"
            (root / "minecraft-worlds" / "first").mkdir(parents=True)
            (root / "minecraft-worlds" / "second").mkdir(parents=True)
            (root / "minecraft" ).symlink_to(root / "minecraft-worlds" / "first")

            proc = self._run_migration(root, active="second")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(
                os.readlink(root / "minecraft"),
                str(root / "minecraft-worlds" / "second"),
            )

    def test_leaves_already_correct_symlink_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "minecraft-worlds" / "default").mkdir(parents=True)
            (root / "minecraft-backups" / "default").mkdir(parents=True)
            (root / "minecraft").symlink_to(root / "minecraft-worlds" / "default")
            (root / "minecraft-backups_tmp_ignore").mkdir()  # noise

            proc = self._run_migration(root, active="default")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue((root / "minecraft").is_symlink())


if __name__ == "__main__":
    unittest.main()
