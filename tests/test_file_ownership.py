#!/usr/bin/env python3
"""brAIn never asks a person to fix file ownership.

Claude Code runs as the `claude` user and Home Assistant runs as root, and
Core's UI editors save automations.yaml, scripts.yaml and scenes.yaml by
writing a new file and renaming it over the old one — so a file handed to
`claude` at boot is root's again after the next save from the automation
editor. A run that met one said, in as many words, *"Run sudo chown claude
/config/scenes.yaml /config/scripts.yaml and I'll apply the rest."*

What answers that, and what each test here drives:

* `panel/ownership.py` — the one function that chowns, behind a
  loopback-only route, and the checks that keep a root process that chowns
  user-named paths from being a privilege escalation (`TestWhatMayBeHanded`,
  `TestTheRoute`);
* the scheduler's sweep of the top-level YAML (`TestTheSweep`);
* `atomic_write` giving a file root creates under /config the owner of the
  folder it lands in (`TestANewFileUnderConfig`);
* the edit hook, lifted out of `scripts/` and run as the process it is, with
  a PreToolUse payload against a stub panel — and against no panel at all
  (`TestTheEditHook`);
* `brain own` through the real dispatcher (`TestTheCli`);
* `run.sh`'s boot block, lifted by name and run over a temporary tree
  (`TestTheBootBlock`);
* the words a run is told (`TestWhatClaudeIsTold`).

Real chowns happen where the suite runs as root; elsewhere the chown is
patched and what it was asked to do is asserted instead.
"""
from __future__ import annotations

import asyncio
import contextlib
import http.server
import importlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import unittest.mock
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PANEL = BASE_DIR / "brain" / "panel"
SCRIPTS = BASE_DIR / "brain" / "scripts"
RUN_SH = BASE_DIR / "brain" / "run.sh"
sys.path.insert(0, str(PANEL))

import atomic_write  # noqa: E402
import ownership  # noqa: E402

ROOT = os.geteuid() == 0
# Somebody who is neither root nor anybody's real user. Root can chown to
# any number; nothing needs a passwd entry for it.
UID = GID = 4242
NOBODY = 65534


def _closed_port() -> int:
    """A port nothing is listening on: bound, read, released."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@contextlib.contextmanager
def chown_recorder():
    """Where the suite is not root, record what would have been chowned.

    `os.fchown` and `os.chown` are patched at the module level `ownership`
    and `atomic_write` call them through, and every call is answered as a
    success after recording its target's inode (an fd's or a path's)."""
    calls: list[tuple] = []

    def fchown(fd, uid, gid):
        calls.append(("fd", os.fstat(fd).st_ino, uid, gid))

    def chown(path, uid, gid, *, dir_fd=None, follow_symlinks=True):
        st = os.stat(path, dir_fd=dir_fd, follow_symlinks=follow_symlinks)
        calls.append(("path", st.st_ino, uid, gid, follow_symlinks))

    with unittest.mock.patch("os.fchown", fchown), \
            unittest.mock.patch("os.chown", chown), \
            unittest.mock.patch("os.geteuid", lambda: 0):
        yield calls


class Tree(unittest.TestCase):
    """A config folder and an outside folder, side by side."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        base = Path(self.tmp.name)
        os.chmod(base, 0o755)
        self.config = base / "config"
        self.outside = base / "outside"
        self.config.mkdir()
        self.outside.mkdir()
        self._root = unittest.mock.patch.object(
            atomic_write, "CONFIG_DIR", str(self.config))
        self._root.start()
        self._owner = unittest.mock.patch.object(
            ownership, "owner", lambda: (UID, GID))
        self._owner.start()

    def tearDown(self):
        self._owner.stop()
        self._root.stop()
        self.tmp.cleanup()

    def file(self, rel: str, text: str = "x: 1\n", base: Path | None = None) -> Path:
        path = (base or self.config) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        return path

    def own(self, paths, recursive=False):
        """`ownership.own`, for real as root and recorded otherwise."""
        if ROOT:
            return ownership.own(paths, recursive), None
        with chown_recorder() as calls:
            return ownership.own(paths, recursive), calls

    def owned(self, path: Path, calls) -> bool:
        if calls is None:
            st = os.lstat(path)
            return (st.st_uid, st.st_gid) == (UID, GID)
        ino = os.lstat(path).st_ino
        return any(c[1] == ino for c in calls)


class TestWhatMayBeHanded(Tree):
    def test_a_root_owned_file_is_handed_to_claude(self):
        scenes = self.file("scenes.yaml")
        answer, calls = self.own([str(scenes)])
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(answer["results"][0]["changed"], 1)
        self.assertTrue(self.owned(scenes, calls))

    @unittest.skipUnless(ROOT, "a real second pass needs a real first chown")
    def test_asking_again_changes_nothing(self):
        scenes = self.file("scenes.yaml")
        ownership.own([str(scenes)])
        again = ownership.own([str(scenes)])
        self.assertTrue(again["ok"])
        self.assertEqual(again["results"][0]["changed"], 0)

    def test_a_path_outside_the_config_folder_is_refused(self):
        target = self.file("passwd", base=self.outside)
        answer, calls = self.own([str(target)])
        self.assertFalse(answer["ok"])
        self.assertIn("outside", answer["results"][0]["reason"])
        self.assertFalse(self.owned(target, calls))

    def test_dot_dot_cannot_climb_out(self):
        """`/config/../etc/passwd` is lexically under /config and is not in
        it."""
        target = self.file("passwd", base=self.outside)
        climb = f"{self.config}/../outside/passwd"
        self.assertTrue(climb.startswith(str(self.config)))
        answer, calls = self.own([climb])
        self.assertFalse(answer["ok"])
        self.assertIn("outside", answer["results"][0]["reason"])
        self.assertFalse(self.owned(target, calls))

    def test_a_symlink_is_refused_and_its_target_left_alone(self):
        target = self.file("shadow", base=self.outside)
        link = self.config / "scenes.yaml"
        link.symlink_to(target)
        answer, calls = self.own([str(link)])
        self.assertFalse(answer["ok"])
        self.assertIn("symbolic link", answer["results"][0]["reason"])
        self.assertFalse(self.owned(target, calls))

    def test_a_linked_folder_cannot_carry_a_file_out(self):
        """The last component is a plain file; the folder above it is a link
        out. Read back off the open descriptor, the file is outside."""
        target = self.file("victim.yaml", base=self.outside)
        (self.config / "packages").symlink_to(self.outside)
        answer, calls = self.own([str(self.config / "packages" / "victim.yaml")])
        self.assertFalse(answer["ok"])
        self.assertIn("outside", answer["results"][0]["reason"])
        self.assertFalse(self.owned(target, calls))

    def test_the_refused_paths_are_refused(self):
        refused = {
            ".storage/core.entity_registry": ".storage",
            ".storage": ".storage",
            ".cloud/auth": "Cloud",
            ".brain/secrets/claude_auth.json": "credentials",
            "secrets.yaml": "secrets.yaml",
            "esphome/secrets.yaml": "secrets.yaml",
            "home-assistant_v2.db": "recorder",
            "home-assistant_v2.db-wal": "recorder",
        }
        for rel, word in refused.items():
            with self.subTest(rel=rel):
                path = self.config / rel
                if rel == ".storage":
                    path.mkdir(exist_ok=True)
                else:
                    self.file(rel)
                answer, calls = self.own([str(path)])
                self.assertFalse(answer["ok"])
                self.assertIn(word, answer["results"][0]["reason"])
                self.assertFalse(self.owned(path, calls))

    def test_a_fifo_is_not_a_file_or_a_folder(self):
        fifo = self.config / "pipe.yaml"
        os.mkfifo(fifo)
        answer, _calls = self.own([str(fifo)])
        self.assertFalse(answer["ok"])
        self.assertIn("not a file or a folder", answer["results"][0]["reason"])

    def test_a_file_with_another_name_is_refused(self):
        original = self.file("automations.yaml")
        os.link(original, self.config / "also.yaml")
        answer, calls = self.own([str(original)])
        self.assertFalse(answer["ok"])
        self.assertIn("hard links", answer["results"][0]["reason"])
        self.assertFalse(self.owned(original, calls))

    def test_shapes_that_are_not_paths(self):
        for raw, word in ((None, "not a path"), ("", "not a path"),
                          ("scenes.yaml", "whole path"),
                          (str(self.config / "nope.yaml"), "nothing there"),
                          ("/config\x00/x", "not a path")):
            with self.subTest(raw=raw):
                answer, _ = self.own([raw])
                self.assertFalse(answer["results"][0]["ok"])
                self.assertIn(word, answer["results"][0]["reason"])

    def test_every_path_gets_its_own_answer(self):
        good = self.file("scripts.yaml")
        answer, _ = self.own([str(good), "/etc/passwd"])
        self.assertFalse(answer["ok"])
        self.assertEqual([r["ok"] for r in answer["results"]], [True, False])
        self.assertEqual(answer["user"], "claude")

    def test_recursive_hands_over_a_folder_and_steps_round_what_it_must(self):
        pkg = self.config / "packages"
        heating = self.file("packages/heating.yaml")
        nested = self.file("packages/rooms/lounge.yaml")
        secret = self.file("packages/secrets.yaml")
        victim = self.file("victim.yaml", base=self.outside)
        (pkg / "out").symlink_to(self.outside)
        (pkg / "victim.yaml").symlink_to(victim)
        answer, calls = self.own([str(pkg)], recursive=True)
        self.assertTrue(answer["ok"], answer)
        for path in (pkg, heating, nested, nested.parent):
            self.assertTrue(self.owned(path, calls), path)
        self.assertFalse(self.owned(secret, calls))
        self.assertFalse(self.owned(victim, calls))
        self.assertFalse(self.owned(self.outside, calls))
        self.assertEqual(answer["results"][0]["changed"], 4)

    def test_recursive_on_the_whole_config_folder_is_refused(self):
        answer, _ = self.own([str(self.config)], recursive=True)
        self.assertFalse(answer["ok"])
        self.assertIn("not the whole of it", answer["results"][0]["reason"])

    def test_a_request_that_cannot_be_honoured_at_all(self):
        with self.assertRaises(ownership.Refused):
            ownership.own([])
        with self.assertRaises(ownership.Refused):
            ownership.own(["/config/x"] * (ownership.MAX_PATHS + 1))
        with unittest.mock.patch("os.geteuid", lambda: 1000):
            with self.assertRaises(ownership.Refused) as ctx:
                ownership.own(["/config/x"])
            self.assertEqual(ctx.exception.status, 503)
        with unittest.mock.patch("os.geteuid", lambda: 0), \
                unittest.mock.patch.object(ownership, "owner", lambda: None):
            with self.assertRaises(ownership.Refused) as ctx:
                ownership.own(["/config/x"])
            self.assertEqual(ctx.exception.status, 503)


class TestLoopback(unittest.TestCase):
    def test_only_this_machine_is_loopback(self):
        yes = [("127.0.0.1", 1), ("::1", 1, 0, 0), ("::ffff:127.0.0.1", 1),
               ("127.0.0.53", 9)]
        no = [("172.30.32.2", 1), ("192.168.1.5", 2), ("::ffff:10.0.0.1", 3),
              "/run/panel.sock", None, (), (None, 1), ("localhost", 1)]
        for peer in yes:
            self.assertTrue(ownership.peer_is_loopback(peer), peer)
        for peer in no:
            self.assertFalse(ownership.peer_is_loopback(peer), peer)


class TestTheRoute(Tree):
    """`POST /api/own` through the panel's own handler, over a real socket,
    and the refusal of anything that did not arrive on loopback."""

    def setUp(self):
        super().setUp()
        tmp = Path(self.tmp.name)
        self._env = dict(os.environ)
        self.addCleanup(self._restore_env)
        for key, value in {
            "BRAIN_CONFIG_DIR": str(self.config),
            "BRAIN_DIR": str(tmp / "insights"),
            "BRAIN_SETTINGS_FILE": str(tmp / "settings.json"),
            "BRAIN_FINDINGS_FILE": str(tmp / "findings.json"),
            "BRAIN_FINDINGS_SETTLED": str(tmp / "settled.json"),
            "BRAIN_FINDINGS_STATE": str(tmp / "state.json"),
            "BRAIN_JOURNAL_FILE": str(tmp / "journal.jsonl"),
            "BRAIN_DIAGNOSTICS_FILE": str(tmp / "diag.json"),
        }.items():
            os.environ[key] = value
        import server
        self.server = importlib.reload(server)

    def _restore_env(self):
        """Put the environment back: a module another test reloads later
        must not read a config folder this test has already deleted."""
        os.environ.clear()
        os.environ.update(self._env)

    def test_the_app_registers_it(self):
        paths = {getattr(r, "canonical", "")
                 for r in self.server.make_app().router.resources()}
        self.assertIn("/api/own", paths)

    def test_over_loopback_it_hands_files_over(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        scenes = self.file("scenes.yaml")

        async def go():
            app = web.Application()
            app.router.add_post("/api/own", self.server.h_own)
            async with TestClient(TestServer(app, host="127.0.0.1")) as client:
                resp = await client.post("/api/own",
                                         json={"paths": [str(scenes)]})
                return resp.status, await resp.json()

        if ROOT:
            status, body = asyncio.run(go())
            self.assertTrue(self.owned(scenes, None))
        else:
            with chown_recorder() as calls:
                status, body = asyncio.run(go())
            self.assertTrue(self.owned(scenes, calls))
        self.assertEqual(status, 200, body)
        self.assertTrue(body["ok"])

    def test_a_bad_body_is_a_400_not_a_crash(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer

        async def go():
            app = web.Application()
            app.router.add_post("/api/own", self.server.h_own)
            async with TestClient(TestServer(app, host="127.0.0.1")) as client:
                resp = await client.post("/api/own", json={"paths": []})
                return resp.status, await resp.json()

        with unittest.mock.patch("os.geteuid", lambda: 0):
            status, body = asyncio.run(go())
        self.assertEqual(status, 400)
        self.assertIn("at least one path", body["error"])

    def test_anything_not_on_loopback_is_refused_before_it_is_read(self):
        from aiohttp.test_utils import make_mocked_request
        scenes = self.file("scenes.yaml")
        transport = unittest.mock.Mock()
        transport.get_extra_info.side_effect = (
            lambda key, default=None: ("172.30.32.2", 5555)
            if key == "peername" else default)
        request = make_mocked_request(
            "POST", "/api/own", transport=transport,
            headers={"X-Forwarded-For": "127.0.0.1"})
        with unittest.mock.patch.object(ownership, "own") as own:
            resp = asyncio.run(self.server.h_own(request))
        self.assertEqual(resp.status, 403)
        own.assert_not_called()
        self.assertFalse(self.owned(scenes, []) if not ROOT
                         else self.owned(scenes, None))


class TestTheSweep(Tree):
    def setUp(self):
        super().setUp()
        ownership._LAST_SWEEP.clear()

    def sweep(self):
        if ROOT:
            return ownership.sweep(), None
        with chown_recorder() as calls:
            return ownership.sweep(), calls

    def test_it_re_owns_the_top_level_yaml_and_nothing_else(self):
        autos = self.file("automations.yaml")
        scenes = self.file("scenes.yml")
        secrets = self.file("secrets.yaml")
        notes = self.file("notes.txt")
        deeper = self.file("packages/heating.yaml")
        victim = self.file("victim.yaml", base=self.outside)
        (self.config / "linked.yaml").symlink_to(victim)
        count, calls = self.sweep()
        self.assertEqual(count, 2)
        self.assertTrue(self.owned(autos, calls))
        self.assertTrue(self.owned(scenes, calls))
        for path in (secrets, notes, deeper, victim):
            self.assertFalse(self.owned(path, calls), path)

    def test_it_is_gated_and_never_raises(self):
        self.file("automations.yaml")
        with unittest.mock.patch.object(ownership, "sweep", return_value=1) as s:
            self.assertEqual(ownership.maybe_sweep(now=1000.0), 1)
            self.assertIsNone(ownership.maybe_sweep(now=1000.0 + 60))
            self.assertEqual(ownership.maybe_sweep(
                now=1000.0 + ownership.SWEEP_INTERVAL_S + 1), 1)
            self.assertEqual(s.call_count, 2)
        ownership._LAST_SWEEP.clear()
        with unittest.mock.patch.object(ownership, "sweep",
                                        side_effect=RuntimeError("boom")):
            self.assertEqual(ownership.maybe_sweep(now=5.0), 0)

    def test_not_root_or_no_claude_user_does_nothing(self):
        self.file("automations.yaml")
        with unittest.mock.patch("os.geteuid", lambda: 1000):
            self.assertEqual(ownership.sweep(), 0)
        with unittest.mock.patch("os.geteuid", lambda: 0), \
                unittest.mock.patch.object(ownership, "owner", lambda: None):
            self.assertEqual(ownership.sweep(), 0)

    def test_the_scheduler_tick_asks_for_it(self):
        """The sweep rides the scheduler's minute, before every gate — a
        switched-off insights face must not leave a file root's."""
        import server
        src = Path(server.__file__).read_text(encoding="utf-8")
        start = src.index("async def _scheduler()")
        body = src[start:src.index("\nasync def ", start + 10)]
        self.assertIn("ownership.maybe_sweep", body)
        self.assertLess(body.index("ownership.maybe_sweep"),
                        body.index("if not insights_enabled()"))


class TestANewFileUnderConfig(Tree):
    """`atomic_write` keeps an existing file's owner. A NEW file had none
    to keep, so it was root's — and the claude user could never edit it in
    place. Under the config folder it takes the folder's owner now."""

    def write(self, path: Path, text="x"):
        if ROOT:
            atomic_write.write_text(path, text)
            return None
        with chown_recorder() as calls:
            atomic_write.write_text(path, text)
        return calls

    def give(self, path: Path):
        if ROOT:
            os.chown(path, UID, GID)

    def test_a_new_file_takes_its_folders_owner(self):
        self.give(self.config)
        target = self.config / "scenes.yaml"
        calls = self.write(target)
        if ROOT:
            st = target.stat()
            self.assertEqual((st.st_uid, st.st_gid), (UID, GID))
        else:
            folder = os.stat(self.config)
            self.assertIn((folder.st_uid, folder.st_gid),
                          [(c[2], c[3]) for c in calls])
        self.assertEqual(target.read_text(), "x")

    def test_new_folders_take_the_owner_of_the_folder_above(self):
        self.give(self.config)
        target = self.config / "www" / "brain" / "card.html"
        self.write(target)
        if ROOT:
            for path in (target.parent.parent, target.parent, target):
                self.assertEqual(path.stat().st_uid, UID, path)

    @unittest.skipUnless(ROOT, "the owner of a file is only observable as root")
    def test_outside_the_config_folder_nothing_changes(self):
        os.chown(self.outside, UID, GID)
        target = self.outside / "store.json"
        atomic_write.write_text(target, "x")
        self.assertEqual(target.stat().st_uid, 0)

    @unittest.skipUnless(ROOT, "the owner of a file is only observable as root")
    def test_dot_dot_out_of_config_is_outside(self):
        os.chown(self.outside, UID, GID)
        target = Path(f"{self.config}/../outside/store.json")
        atomic_write.write_text(target, "x")
        self.assertEqual((self.outside / "store.json").stat().st_uid, 0)

    @unittest.skipUnless(ROOT, "the owner of a file is only observable as root")
    def test_an_existing_file_keeps_its_own_owner(self):
        """The rule this module already had, untouched: a root-owned file in
        a claude-owned folder stays root's when root rewrites it."""
        os.chown(self.config, UID, GID)
        target = self.file("automations.yaml")
        self.assertEqual(target.stat().st_uid, 0)
        atomic_write.write_text(target, "new")
        self.assertEqual(target.stat().st_uid, 0)

    def test_only_root_hands_anything_over(self):
        with unittest.mock.patch("os.geteuid", lambda: 1000):
            self.assertEqual(atomic_write._inherited(self.config), (-1, -1))
        with unittest.mock.patch("os.geteuid", lambda: 0):
            self.assertEqual(atomic_write._inherited(self.outside), (-1, -1))
            st = os.stat(self.config)
            self.assertEqual(atomic_write._inherited(self.config),
                             (st.st_uid, st.st_gid))


class StubPanel:
    """A panel that records what it was asked, or one that never answers."""

    def __init__(self, hang: bool = False):
        self.asked: list[dict] = []
        outer = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):  # noqa: N802 — the stdlib's name
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                outer.asked.append({"path": self.path, "body": body})
                if hang:
                    time.sleep(30)
                answer = {"ok": True, "user": "claude", "results": [
                    {"path": p, "ok": True, "changed": 1}
                    for p in body.get("paths", [])]}
                data = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.httpd.daemon_threads = True
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestTheEditHook(Tree):
    """`brain-edit-snapshot.py` is the PreToolUse hook on Write|Edit|
    MultiEdit|NotebookEdit. It is lifted into a scripts folder of its own and
    run as the process Claude Code starts — as an unprivileged user where
    the suite is root, since root can write anything and would never ask."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.scripts = base / "scripts"
        self.scripts.mkdir()
        shutil.copy(SCRIPTS / "brain_own.py", self.scripts / "brain_own.py")
        # The journal's watch root, repointed at the temporary config folder
        # the way test_brain_addon and test_fix_plan already do; nothing else
        # in the hook is touched.
        hook = (SCRIPTS / "brain-edit-snapshot.py").read_text()
        self.assertIn('WATCH_ROOTS = ("/config",)', hook)
        (self.scripts / "brain-edit-snapshot.py").write_text(hook.replace(
            'WATCH_ROOTS = ("/config",)', f'WATCH_ROOTS = ({str(self.config)!r},)'))
        self.journal = base / "edits"
        self.journal.mkdir()
        for path in (base, self.config, self.scripts, self.journal):
            os.chmod(path, 0o777 if path == self.journal else 0o755)
        if ROOT:
            # As in the add-on: the config folder is the claude user's
            # (run.sh hands it over at boot) and the files in it are not.
            os.chown(self.config, NOBODY, NOBODY)
        self.target = self.file("scenes.yaml", "- id: x\n")
        os.chmod(self.target, 0o444)    # nobody may write it, owner included

    def run_hook(self, panel_url: str, tool="Edit", journal_days="0",
                 timeout=20, payload=None):
        payload = payload or {"tool_name": tool, "tool_input": {
            "file_path": str(self.target), "old_string": "x",
            "new_string": "y"}}
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "BRAIN_PANEL_URL": panel_url,
               "BRAIN_CONFIG_DIR": str(self.config),
               "BRAIN_EDIT_JOURNAL": str(self.journal),
               "BRAIN_EDIT_JOURNAL_DAYS": journal_days,
               "BRAIN_OWN_HOOK_TIMEOUT": "1"}
        kwargs = {"user": NOBODY, "group": NOBODY} if ROOT else {}
        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(self.scripts / "brain-edit-snapshot.py")],
            input=json.dumps(payload), capture_output=True, text=True,
            env=env, timeout=timeout, **kwargs)
        return proc, time.monotonic() - start

    def test_it_asks_the_panel_for_a_file_it_cannot_write(self):
        panel = StubPanel()
        try:
            proc, _ = self.run_hook(panel.url)
        finally:
            panel.close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(panel.asked), 1, panel.asked)
        self.assertEqual(panel.asked[0]["path"], "/api/own")
        self.assertEqual(panel.asked[0]["body"]["paths"], [str(self.target)])

    def test_every_edit_tool_asks_and_notebooks_name_their_path(self):
        for tool, key in (("Write", "file_path"), ("MultiEdit", "file_path"),
                          ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                panel = StubPanel()
                try:
                    proc, _ = self.run_hook(panel.url, payload={
                        "tool_name": tool,
                        "tool_input": {key: str(self.target)}})
                finally:
                    panel.close()
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual([a["body"]["paths"] for a in panel.asked],
                                 [[str(self.target)]])

    def test_a_writable_file_asks_nothing(self):
        os.chmod(self.target, 0o666)
        panel = StubPanel()
        try:
            proc, _ = self.run_hook(panel.url)
        finally:
            panel.close()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(panel.asked, [])

    def test_a_file_outside_the_config_folder_asks_nothing(self):
        outside = self.file("x.yaml", base=self.outside)
        os.chmod(self.outside, 0o755)
        os.chmod(outside, 0o444)
        panel = StubPanel()
        try:
            proc, _ = self.run_hook(panel.url, payload={
                "tool_name": "Write",
                "tool_input": {"file_path": str(outside)}})
        finally:
            panel.close()
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(panel.asked, [])

    def test_a_new_file_in_a_folder_it_cannot_write_asks_for_the_folder(self):
        locked = self.config / "packages"
        locked.mkdir()
        os.chmod(locked, 0o555)
        panel = StubPanel()
        try:
            proc, _ = self.run_hook(panel.url, payload={
                "tool_name": "Write",
                "tool_input": {"file_path": str(locked / "new" / "x.yaml")}})
        finally:
            panel.close()
            os.chmod(locked, 0o755)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([a["body"]["paths"] for a in panel.asked],
                         [[str(locked)]])

    def test_a_panel_that_is_down_lets_the_edit_go_ahead(self):
        proc, took = self.run_hook(f"http://127.0.0.1:{_closed_port()}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertLess(took, 10)

    def test_a_panel_that_never_answers_costs_its_timeout_and_no_more(self):
        panel = StubPanel(hang=True)
        try:
            proc, took = self.run_hook(panel.url)
        finally:
            panel.close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertLess(took, 10)

    def test_the_snapshot_is_still_taken_after_asking(self):
        panel = StubPanel()
        try:
            proc, _ = self.run_hook(panel.url, journal_days="14")
        finally:
            panel.close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(panel.asked), 1)
        index = (self.journal / "index.jsonl").read_text().splitlines()
        self.assertEqual(json.loads(index[-1])["path"], str(self.target))

    def test_without_brain_own_the_hook_still_snapshots(self):
        """A missing module is a step skipped, never an edit blocked."""
        (self.scripts / "brain_own.py").unlink()
        proc, _ = self.run_hook(f"http://127.0.0.1:{_closed_port()}",
                                journal_days="14")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.journal / "index.jsonl").read_text().strip())

    def test_garbage_on_stdin_exits_zero(self):
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "BRAIN_PANEL_URL": f"http://127.0.0.1:{_closed_port()}"}
        proc = subprocess.run(
            [sys.executable, str(self.scripts / "brain-edit-snapshot.py")],
            input="not json", capture_output=True, text=True, env=env,
            timeout=20)
        self.assertEqual(proc.returncode, 0)


class TestEnsureWritable(Tree):
    """The hook's half of `brain_own`, in process, for the cases a
    subprocess cannot reach: root never asks, and nothing raises."""

    def setUp(self):
        super().setUp()
        sys.path.insert(0, str(SCRIPTS))
        import brain_own
        self.mod = importlib.reload(brain_own)
        self.mod.CONFIG_DIR = str(self.config)

    def tearDown(self):
        sys.path.remove(str(SCRIPTS))
        super().tearDown()

    def test_root_never_asks(self):
        target = self.file("scenes.yaml")
        with unittest.mock.patch("os.geteuid", lambda: 0), \
                unittest.mock.patch("os.access", lambda *a: False):
            self.assertEqual(self.mod.targets_for(target), [])

    def test_a_link_is_never_asked_about(self):
        victim = self.file("v.yaml", base=self.outside)
        link = self.config / "scenes.yaml"
        link.symlink_to(victim)
        with unittest.mock.patch("os.geteuid", lambda: 1000), \
                unittest.mock.patch("os.access", lambda *a: False):
            self.assertEqual(self.mod.targets_for(link), [])

    def test_it_never_raises(self):
        target = self.file("scenes.yaml")
        with unittest.mock.patch.object(self.mod, "targets_for",
                                        side_effect=RuntimeError("boom")):
            self.assertFalse(self.mod.ensure_writable(target))
        with unittest.mock.patch("os.geteuid", lambda: 1000), \
                unittest.mock.patch("os.access", lambda *a: False), \
                unittest.mock.patch.object(
                    self.mod, "PANEL_URL", f"http://127.0.0.1:{_closed_port()}"):
            self.assertFalse(self.mod.ensure_writable(target))


class TestTheCli(unittest.TestCase):
    def brain(self, *args, panel_url=None):
        env = {**os.environ, "BRAIN_SCRIPTS_DIR": str(SCRIPTS),
               "BRAIN_PANEL_URL": panel_url
               or f"http://127.0.0.1:{_closed_port()}"}
        return subprocess.run(["bash", str(SCRIPTS / "brain.sh"), *args],
                              capture_output=True, text=True, env=env,
                              timeout=30)

    def test_help_announces_it(self):
        """The chat palette parses `brain help`, so this line IS how the
        command is found."""
        proc = self.brain("help")
        self.assertEqual(proc.returncode, 0)
        line = next(ln for ln in proc.stdout.splitlines()
                    if ln.startswith("  brain own"))
        self.assertIn("<path...>", line)
        import cli_commands
        parsed = {c["name"]: c for c in cli_commands._parse("brain", proc.stdout)}
        self.assertIn("brain own", parsed)
        self.assertIn("writable", parsed["brain own"]["description"])

    def test_own_help_says_nobody_needs_sudo(self):
        proc = self.brain("own", "--help")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("Nobody needs to run sudo or chown", proc.stdout)

    def test_a_panel_that_is_down_is_said_so(self):
        proc = self.brain("own", "/config/scenes.yaml")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("not answering", proc.stderr)

    def test_it_sends_whole_paths_and_prints_each_answer(self):
        panel = StubPanel()
        try:
            with tempfile.TemporaryDirectory() as cwd:
                env = {**os.environ, "BRAIN_SCRIPTS_DIR": str(SCRIPTS),
                       "BRAIN_PANEL_URL": panel.url}
                proc = subprocess.run(
                    ["bash", str(SCRIPTS / "brain.sh"), "own", "-r",
                     "packages", "/config/scenes.yaml"],
                    capture_output=True, text=True, env=env, timeout=30,
                    cwd=cwd)
                real_cwd = os.path.realpath(cwd)
        finally:
            panel.close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        body = panel.asked[0]["body"]
        self.assertTrue(body["recursive"])
        self.assertEqual(body["paths"], [os.path.join(real_cwd, "packages"),
                                         "/config/scenes.yaml"])
        self.assertIn("✓ /config/scenes.yaml: 1 entry handed to claude",
                      proc.stdout)


def lift_run_sh(name: str) -> str:
    """A function out of the real run.sh, by name."""
    src = RUN_SH.read_text(encoding="utf-8")
    match = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", src, re.S | re.M)
    assert match, f"run.sh no longer defines {name}"
    return match.group(0)


class TestTheBootBlock(Tree):
    """`own_ha_config`, lifted out of run.sh and run over a temporary tree.

    As root the chown is real; otherwise a fake `chown` first on PATH
    records what it was handed, which is the same claim one step earlier.
    """

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        c = self.config
        self.expect_owned = [
            self.file("configuration.yaml",
                      "homeassistant:\n"
                      "  packages: !include_dir_named packages\n"
                      "automation split: !include_dir_merge_list 'custom_inc/'\n"
                      "evil: !include_dir_named ../outside\n"
                      "hidden: !include_dir_list .storage\n"
                      "absolute: !include_dir_list /etc\n"),
            self.file("automations.yaml"), self.file("scenes.yml"),
            self.file("packages/heating.yaml"), c / "packages",
            self.file("esphome/porch.yaml"), c / "esphome",
            self.file("custom_inc/a.yaml"), c / "custom_inc",
            self.file("blueprints/automation/motion.yaml"),
            c / "blueprints", c / "blueprints" / "automation",
        ]
        victim = self.file("target.yaml", base=self.outside)
        self.expect_untouched = [
            self.file("secrets.yaml"), self.file("notes.txt"),
            self.file("esphome/secrets.yaml"),
            self.file("esphome/.esphome/build/main.cpp"),
            self.file("packages/.git/config"),
            self.file(".storage/core.entity_registry"),
            self.file("www/card.js"), victim, self.outside,
        ]
        (c / "link.yaml").symlink_to(victim)
        (c / "packages" / "out").symlink_to(self.outside)
        (c / "themes").symlink_to(self.outside)
        self.fakebin = base / "bin"
        self.fakebin.mkdir()
        self.record = base / "chowned.txt"

    def run_block(self, max_entries=None):
        harness = "\n".join([
            'bashio::log.info() { echo "INFO $*"; }',
            'bashio::log.warning() { echo "WARN $*"; }',
            lift_run_sh("own_ha_config"),
            f'own_ha_config "{self.config}" "{UID}:{GID}"',
        ])
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        if max_entries is not None:
            env["BRAIN_OWN_MAX"] = str(max_entries)
        if not ROOT:
            fake = self.fakebin / "chown"
            fake.write_text(
                "#!/bin/sh\nshift 2\n"
                f'for f in "$@"; do printf "%s\\n" "$f" >> "{self.record}"; done\n')
            fake.chmod(0o755)
            env["PATH"] = f"{self.fakebin}{os.pathsep}{env['PATH']}"
        return subprocess.run(["bash", "-c", harness], capture_output=True,
                              text=True, env=env, timeout=60)

    def chowned(self) -> set[str]:
        if ROOT:
            return {str(p) for p in self.expect_owned + self.expect_untouched
                    if os.lstat(p).st_uid == UID}
        if not self.record.exists():
            return set()
        return set(self.record.read_text().splitlines())

    def test_it_hands_over_the_user_config_and_nothing_else(self):
        proc = self.run_block()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        chowned = self.chowned()
        for path in self.expect_owned:
            self.assertIn(str(path), chowned, path)
        for path in self.expect_untouched:
            self.assertNotIn(str(path), chowned, path)
        self.assertIn(f"INFO Config ownership: {len(self.expect_owned)} "
                      "file(s) and folder(s)", proc.stdout)
        if ROOT:
            # A link is never followed: the link itself, not its target.
            self.assertEqual(os.stat(self.outside / "target.yaml").st_uid, 0)

    @unittest.skipUnless(ROOT, "a second pass only sees a real first one")
    def test_a_second_boot_has_nothing_to_do(self):
        self.run_block()
        proc = self.run_block()
        self.assertIn("INFO Config ownership: 0 file(s)", proc.stdout)

    def test_the_cap_bounds_it_and_says_so(self):
        proc = self.run_block(max_entries=2)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("WARN Config ownership:", proc.stdout)
        self.assertEqual(len(self.chowned()), 2)

    def test_a_missing_config_folder_is_not_an_error(self):
        shutil.rmtree(self.config)
        proc = self.run_block()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")

    def test_setup_claude_user_calls_it(self):
        body = lift_run_sh("setup_claude_user")
        self.assertIn("own_ha_config /config claude:claude", body)


class TestWhatClaudeIsTold(unittest.TestCase):
    RULE = "Never ask the person to run sudo or chown"

    def test_the_chat_prompt_carries_the_rule(self):
        import server
        prompt = server._chat_system_prompt(None)
        self.assertIn("brain own <path>", prompt)
        self.assertIn(self.RULE, prompt)

    def test_the_fix_and_plan_runs_are_told_it_is_not_a_reason(self):
        import fixer
        self.assertIn("brain own", fixer.FIX_SYSTEM)
        self.assertIn("never set \"needs_you\" over file permissions",
                      fixer.FIX_SYSTEM)
        self.assertIn("Never put sudo or chown in the steps", fixer.PLAN_SYSTEM)

    def test_the_generated_claude_md_carries_it(self):
        """`/config/CLAUDE.md` is generated by `generate_context`; it is
        lifted out of the real script and run with the Home Assistant API
        stubbed to answer nothing."""
        script = (SCRIPTS / "ha-context-gen.sh").read_text(encoding="utf-8")

        def lift(name):
            m = re.search(rf"^{name}\(\) \{{\n.*?^\}}$", script, re.S | re.M)
            assert m, name
            return m.group(0)

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "CLAUDE.md"
            harness = "\n".join([
                'bashio::log.info() { :; }', 'bashio::log.warning() { :; }',
                'bashio::log.error() { :; }', 'api_get() { echo "[]"; }',
                f'OUTPUT_FILE="{out}"', lift("memory_excerpt"),
                lift("generate_context"), "generate_context"])
            proc = subprocess.run(
                ["bash", "-c", harness], capture_output=True, text=True,
                timeout=60, env={"PATH": os.environ.get("PATH", ""),
                                 "HOME": tmp})
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            text = out.read_text(encoding="utf-8")
        self.assertIn("`brain own [-r] <path...>`", text)
        self.assertIn("run `brain own <path>`", text)
        self.assertIn(self.RULE, text)


if __name__ == "__main__":
    unittest.main()
