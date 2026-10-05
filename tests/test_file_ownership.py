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
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
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

    def test_a_link_out_is_refused_and_its_target_left_alone(self):
        target = self.file("shadow", base=self.outside)
        link = self.config / "scenes.yaml"
        link.symlink_to(target)
        answer, calls = self.own([str(link)])
        self.assertFalse(answer["ok"])
        row = answer["results"][0]
        self.assertEqual(row["path"], str(link))
        self.assertEqual(row["target"], str(target))
        self.assertIn(f"it is a link to {target}", row["reason"])
        self.assertIn("outside", row["reason"])
        self.assertFalse(self.owned(target, calls))

    def test_a_link_inside_is_answered_for_its_target(self):
        """`scenes.yaml` linked into a git-managed folder: the target is
        handed over exactly as if it had been named, and the answer says
        where the link led."""
        target = self.file("git/home/scenes.yaml")
        link = self.config / "scenes.yaml"
        link.symlink_to(target)
        answer, calls = self.own([str(link)])
        self.assertTrue(answer["ok"], answer)
        row = answer["results"][0]
        self.assertEqual((row["path"], row["target"], row["changed"]),
                         (str(link), str(target), 1))
        self.assertTrue(self.owned(target, calls))

    def test_a_link_to_a_refused_path_is_refused_as_that_path(self):
        """Following a link grants nothing naming its target would not: a
        link into .storage is .storage, and a hard-linked target is still
        a file with other names."""
        store = self.file(".storage/auth")
        twice = self.file("twice.yaml")
        os.link(twice, self.config / "twice-again.yaml")
        for name, target, word in (("a.yaml", store, ".storage"),
                                   ("b.yaml", twice, "hard links")):
            with self.subTest(name=name):
                (self.config / name).symlink_to(target)
                answer, calls = self.own([str(self.config / name)])
                self.assertFalse(answer["ok"])
                self.assertIn(word, answer["results"][0]["reason"])
                self.assertFalse(self.owned(target, calls))

    def test_a_read_only_file_is_given_its_owners_write_bit(self):
        """A chown alone leaves a 0444 file one its new owner still cannot
        write — and "handed over" about a file Claude cannot write is the
        edit failing with nothing left to try. The folder gets rwx."""
        scenes = self.file("scenes.yaml")
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(scenes, 0o444)
        folder = self.config / "packages"
        folder.mkdir()
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(folder, 0o555)
        try:
            answer, calls = self.own([str(scenes), str(folder)])
        finally:
            os.chmod(folder, os.stat(folder).st_mode | 0o700)
        self.assertTrue(answer["ok"], answer)
        self.assertEqual([r["changed"] for r in answer["results"]], [1, 1])
        self.assertEqual(os.stat(scenes).st_mode & 0o777, 0o644)
        self.assertTrue(self.owned(scenes, calls))

    @unittest.skipUnless(ROOT, "an already-owned file needs a real first chown")
    def test_already_owned_but_read_only_is_still_a_change(self):
        """`brain own` used to answer "already claude's" about a file Claude
        could not write."""
        scenes = self.file("scenes.yaml")
        os.chown(scenes, UID, GID)
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(scenes, 0o440)
        again = ownership.own([str(scenes)])
        self.assertEqual(again["results"][0]["changed"], 1)
        self.assertEqual(os.stat(scenes).st_mode & 0o777, 0o640)

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

    def test_recursive_makes_what_it_hands_over_writable(self):
        pkg = self.config / "packages"
        inner = self.file("packages/rooms/lounge.yaml")
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(inner, 0o444)
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(inner.parent, 0o555)
        try:
            answer, _calls = self.own([str(pkg)], recursive=True)
        finally:
            # codeql[py/overly-permissive-file] the test sets this mode on purpose
            os.chmod(inner.parent, 0o755)
        self.assertTrue(answer["ok"], answer)
        self.assertEqual(os.stat(inner).st_mode & 0o777, 0o644)

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


class TestTheOtherTrees(Tree):
    """/addon_configs, /share, /media and /addons drift back the same way
    /config does, and run.sh hands them over when they are mapped — so
    every check is made against whichever tree a path is in, and a tree
    that is not mapped is outside."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.addons = base / "addon_configs"
        self.share = base / "share"
        self.addons.mkdir()
        self.share.mkdir()
        self._env = unittest.mock.patch.dict(os.environ, {
            "ADDON_CONFIG_DIR": str(self.addons),
            "SHARE_DIR": str(self.share)})
        self._env.start()
        os.environ.pop("MEDIA_DIR", None)
        os.environ.pop("ADDONS_DIR", None)

    def tearDown(self):
        self._env.stop()
        super().tearDown()

    def test_a_file_in_another_tree_is_handed_over(self):
        z2m = self.file("zigbee2mqtt/configuration.yaml", base=self.addons)
        shared = self.file("notes/list.txt", base=self.share)
        answer, calls = self.own([str(z2m), str(shared)])
        self.assertTrue(answer["ok"], answer)
        self.assertTrue(self.owned(z2m, calls))
        self.assertTrue(self.owned(shared, calls))

    def test_a_tree_that_is_not_mapped_is_outside(self):
        z2m = self.file("zigbee2mqtt/configuration.yaml", base=self.addons)
        os.environ.pop("ADDON_CONFIG_DIR")
        answer, calls = self.own([str(z2m)])
        self.assertFalse(answer["ok"])
        self.assertIn("outside", answer["results"][0]["reason"])
        self.assertFalse(self.owned(z2m, calls))

    def test_outside_every_tree_names_them_all(self):
        victim = self.file("passwd", base=self.outside)
        answer, calls = self.own([str(victim)])
        reason = answer["results"][0]["reason"]
        for tree in (self.config, self.addons, self.share):
            self.assertIn(str(tree), reason)
        self.assertFalse(self.owned(victim, calls))

    def test_the_same_checks_hold_in_every_tree(self):
        victim = self.file("passwd", base=self.outside)
        (self.share / "out.txt").symlink_to(victim)
        secrets = self.file("esphome/secrets.yaml", base=self.addons)
        for path, word in ((self.share / "out.txt", "outside"),
                           (secrets, "secrets.yaml")):
            with self.subTest(path=path):
                answer, calls = self.own([str(path)])
                self.assertFalse(answer["ok"])
                self.assertIn(word, answer["results"][0]["reason"])
        answer, _ = self.own([str(self.share)], recursive=True)
        self.assertIn("not the whole of it", answer["results"][0]["reason"])
        self.assertIn(str(self.share), answer["results"][0]["reason"])

    def test_config_s_refused_folders_are_the_config_folder_s_own(self):
        """`.storage` is Core's; a folder of that name inside an add-on's
        own config is that add-on's, and is handed over like the rest."""
        theirs = self.file("someaddon/.storage/state.json", base=self.addons)
        answer, calls = self.own([str(theirs)])
        self.assertTrue(answer["ok"], answer)
        self.assertTrue(self.owned(theirs, calls))

    def test_the_whole_filesystem_is_never_a_tree(self):
        victim = self.file("passwd", base=self.outside)
        with unittest.mock.patch.dict(os.environ, {"MEDIA_DIR": "/",
                                                   "ADDONS_DIR": "relative"}):
            self.assertNotIn("/", atomic_write.handover_roots())
            self.assertNotIn("relative", atomic_write.handover_roots())
            answer, calls = self.own([str(victim)])
        self.assertFalse(answer["ok"])
        self.assertFalse(self.owned(victim, calls))

    def test_the_hook_and_the_panel_read_the_same_trees(self):
        """`brain_own` runs as the claude user and cannot import the panel,
        so it spells the variables again; both are driven over one
        environment and compared."""
        sys.path.insert(0, str(SCRIPTS))
        try:
            import brain_own
            mod = importlib.reload(brain_own)
        finally:
            sys.path.remove(str(SCRIPTS))
        self.assertEqual(mod.ROOT_VARS, atomic_write.HANDOVER_ROOT_VARS)
        with unittest.mock.patch.dict(os.environ, {
                "MEDIA_DIR": "/media/", "ADDONS_DIR": "/"}), \
                unittest.mock.patch.object(mod, "CONFIG_DIR", str(self.config)):
            self.assertEqual(mod.roots(), atomic_write.handover_roots())
            self.assertEqual(atomic_write.handover_roots(),
                             [str(self.config), str(self.addons),
                              str(self.share), "/media"])

    @unittest.skipUnless(ROOT, "the owner of a file is only observable as root")
    def test_a_new_file_root_writes_in_another_tree_takes_its_folders_owner(self):
        os.chown(self.share, UID, GID)
        report = self.share / "brain" / "reports" / "r.txt"
        atomic_write.write_text(report, "x")
        for path in (report.parent.parent, report.parent, report):
            self.assertEqual(path.stat().st_uid, UID, path)


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

    def test_one_scheduler_tick_sweeps_before_any_gate(self):
        """One tick of the real `_scheduler` with the insights face switched
        off: the sweep still runs, because a face nobody uses must not
        leave a file root's."""
        server = self.server
        swept: list[int] = []

        async def one_tick():
            ticks = {"n": 0}

            async def sleep_once(_seconds):
                ticks["n"] += 1
                if ticks["n"] > 1:
                    raise asyncio.CancelledError

            with unittest.mock.patch.object(asyncio, "sleep", sleep_once), \
                    unittest.mock.patch.object(
                        server.ownership, "maybe_sweep",
                        lambda: swept.append(1)), \
                    unittest.mock.patch.object(
                        server.findings_store, "sweep_inbox", lambda *a: []), \
                    unittest.mock.patch.object(server, "_ingest_facts",
                                               lambda: None), \
                    unittest.mock.patch.object(
                        server.journal, "book_shell_rows", lambda *a: None):
                try:
                    await server._scheduler()
                except asyncio.CancelledError:
                    # The second sleep ends the loop; that is the exit.
                    pass

        with unittest.mock.patch.dict(os.environ,
                                      {"BRAIN_ENABLE_INSIGHTS": "false"}):
            asyncio.run(one_tick())
        self.assertEqual(swept, [1])
        self.assertEqual(server.AUTO_STATE["gate"], "insights_off")

    @unittest.skipUnless(ROOT, "the hook runs as another user, which needs root")
    def test_the_real_hook_against_the_real_route_leaves_it_writable(self):
        """End to end: the edit hook, as an unprivileged user, asks the real
        `h_own` over real loopback about a root-owned READ-ONLY scenes.yaml
        — and afterwards that user can write it. A chown alone answered
        ok and left it unwritable."""
        from aiohttp import web
        from aiohttp.test_utils import TestServer
        base = Path(self.tmp.name)
        scripts = base / "scripts"
        scripts.mkdir()
        shutil.copy(SCRIPTS / "brain_own.py", scripts / "brain_own.py")
        shutil.copy(SCRIPTS / "brain-edit-snapshot.py",
                    scripts / "brain-edit-snapshot.py")
        for path in (base, scripts):
            # codeql[py/overly-permissive-file] the test sets this mode on purpose
            os.chmod(path, 0o755)
        os.chown(self.config, NOBODY, NOBODY)
        scenes = self.file("scenes.yaml", "- id: x\n")
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(scenes, 0o444)

        def hook(url):
            payload = {"tool_name": "Edit", "tool_input": {
                "file_path": str(scenes), "old_string": "x",
                "new_string": "y"}}
            env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                   "BRAIN_PANEL_URL": url, "BRAIN_CONFIG_DIR": str(self.config),
                   "BRAIN_EDIT_JOURNAL_DAYS": "0"}
            return subprocess.run(
                [sys.executable, str(scripts / "brain-edit-snapshot.py")],
                input=json.dumps(payload), capture_output=True, text=True,
                env=env, timeout=30, user=NOBODY, group=NOBODY)

        async def go():
            app = web.Application()
            app.router.add_post("/api/own", self.server.h_own)
            site = TestServer(app, host="127.0.0.1")
            await site.start_server()
            try:
                return await asyncio.to_thread(
                    hook, f"http://127.0.0.1:{site.port}")
            finally:
                await site.close()

        with unittest.mock.patch.object(ownership, "owner",
                                        lambda: (NOBODY, NOBODY)):
            proc = asyncio.run(go())
        self.assertEqual(proc.returncode, 0, proc.stderr)
        st = os.stat(scenes)
        self.assertEqual(st.st_uid, NOBODY)
        can = subprocess.run(
            [sys.executable, "-c",
             "import os, sys; sys.exit(0 if os.access(sys.argv[1], os.W_OK) else 1)",
             str(scenes)], user=NOBODY, group=NOBODY, timeout=30)
        self.assertEqual(can.returncode, 0, oct(st.st_mode))

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

    def test_a_read_only_save_is_made_writable_too(self):
        """A file Home Assistant (or a restored backup) left 0444 is handed
        over with its owner's write bit, or the hand-over hands nothing."""
        scenes = self.file("scenes.yaml")
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(scenes, 0o444)
        count, calls = self.sweep()
        self.assertEqual(count, 1)
        self.assertTrue(self.owned(scenes, calls))
        self.assertEqual(os.stat(scenes).st_mode & 0o777, 0o644)

    def test_a_hard_linked_yaml_is_left_alone(self):
        autos = self.file("automations.yaml")
        os.link(autos, self.config / "packages.yml")
        count, calls = self.sweep()
        self.assertEqual(count, 0)
        self.assertFalse(self.owned(autos, calls))

    def test_each_add_on_folder_is_given_back(self):
        """The Supervisor makes a new add-on's /addon_configs folder root's,
        after boot handed the tree over; the sweep gives each folder back
        (the folder only), and only where that tree is mapped."""
        addons = Path(self.tmp.name) / "addon_configs"
        z2m = addons / "zigbee2mqtt"
        z2m.mkdir(parents=True)
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(z2m, 0o555)
        hidden = addons / ".cache"
        hidden.mkdir()
        (addons / "linked").symlink_to(self.outside)
        try:
            count, calls = self.sweep()
            self.assertFalse(self.owned(z2m, calls), "not mapped: untouched")
            with unittest.mock.patch.dict(os.environ,
                                          {"ADDON_CONFIG_DIR": str(addons)}):
                count, calls = self.sweep()
        finally:
            # codeql[py/overly-permissive-file] the test sets this mode on purpose
            os.chmod(z2m, 0o755)
        self.assertEqual(count, 1)
        self.assertTrue(self.owned(z2m, calls))
        for path in (hidden, self.outside, addons):
            self.assertFalse(self.owned(path, calls), path)

    def test_it_is_gated_and_never_raises(self):
        self.file("automations.yaml")
        with unittest.mock.patch.object(ownership, "sweep", return_value=1) as s:
            self.assertEqual(ownership.maybe_sweep(now=1000.0), 1)
            self.assertIsNone(ownership.maybe_sweep(now=1000.0 + 10))
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

    def test_every_tick_sweeps(self):
        """The scheduler ticks every 60 s and asyncio may wake a hair early,
        so a gate of exactly a minute would skip every other tick — and the
        window it leaves is the one a shell write into a just-saved
        scenes.yaml meets."""
        with unittest.mock.patch.object(ownership, "sweep", return_value=0) as s:
            ownership.maybe_sweep(now=10_000.0)
            ownership.maybe_sweep(now=10_000.0 + 59.99)
        self.assertEqual(s.call_count, 2)


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
        calls = self.write(target)
        if ROOT:
            for path in (target.parent.parent, target.parent, target):
                self.assertEqual(path.stat().st_uid, UID, path)
        else:
            # Recorded: each folder root made was handed to the owner of the
            # folder above it — which, in a tree it made itself, is the
            # config folder's owner all the way down.
            folder = os.stat(self.config)
            for path in (target.parent.parent, target.parent):
                ino = os.lstat(path).st_ino
                self.assertIn(("path", ino, folder.st_uid, folder.st_gid, False),
                              calls, path)

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
            # codeql[py/overly-permissive-file] the test sets this mode on purpose
            os.chmod(path, 0o777 if path == self.journal else 0o755)
        if ROOT:
            # As in the add-on: the config folder is the claude user's
            # (run.sh hands it over at boot) and the files in it are not.
            os.chown(self.config, NOBODY, NOBODY)
        self.target = self.file("scenes.yaml", "- id: x\n")
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
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
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
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
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(self.outside, 0o755)
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
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
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(locked, 0o555)
        panel = StubPanel()
        try:
            proc, _ = self.run_hook(panel.url, payload={
                "tool_name": "Write",
                "tool_input": {"file_path": str(locked / "new" / "x.yaml")}})
        finally:
            panel.close()
            # codeql[py/overly-permissive-file] the test sets this mode on purpose
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


class TestTheShellHook(Tree):
    """`brain-protect-hook.py` already reads every Bash command before it
    runs, so it is where a shell write is caught: the Edit tool writes a new
    file and renames it (which the claude user's own /config allows), while
    a redirect, a `tee` or `open(path, "w")` writes in place into a file
    Home Assistant's editor last saved as root. Lifted beside `brain_own.py`
    and run as the process Claude Code starts, as an unprivileged user
    where the suite is root."""

    def setUp(self):
        super().setUp()
        base = Path(self.tmp.name)
        self.scripts = base / "scripts"
        self.scripts.mkdir()
        for name in ("brain_own.py", "brain-protect-hook.py"):
            shutil.copy(SCRIPTS / name, self.scripts / name)
        for path in (base, self.config, self.scripts):
            # codeql[py/overly-permissive-file] the test sets this mode on purpose
            os.chmod(path, 0o755)
        if ROOT:
            os.chown(self.config, NOBODY, NOBODY)
        self.target = self.file("scenes.yaml", "- id: x\n")
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(self.target, 0o444)
        self.mine = self.file("notes.yaml")
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(self.mine, 0o666)

    def run_hook(self, panel_url: str, command: str, protected: str = "",
                 tool: str = "Bash"):
        payload = {"tool_name": tool, "tool_input": {"command": command}}
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
               "BRAIN_PANEL_URL": panel_url,
               "BRAIN_CONFIG_DIR": str(self.config),
               "BRAIN_PROTECTED_ENTITIES": protected,
               "BRAIN_OWN_HOOK_TIMEOUT": "1"}
        kwargs = {"user": NOBODY, "group": NOBODY} if ROOT else {}
        start = time.monotonic()
        proc = subprocess.run(
            [sys.executable, str(self.scripts / "brain-protect-hook.py")],
            input=json.dumps(payload), capture_output=True, text=True,
            env=env, timeout=20, **kwargs)
        return proc, time.monotonic() - start

    def asked(self, command: str, **kw):
        panel = StubPanel()
        try:
            proc, _ = self.run_hook(panel.url, command, **kw)
        finally:
            panel.close()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc, [a["body"]["paths"] for a in panel.asked]

    def test_a_redirect_into_a_file_it_cannot_write_asks_first(self):
        for command in (f"cat > {self.target} <<'EOF'\n- id: y\nEOF",
                        f"echo '- id: z' >>{self.target}",
                        f"python3 -c \"open('{self.target}', 'w').write('x')\"",
                        f"sed -i s/x/y/ {self.target}"):
            with self.subTest(command=command[:30]):
                proc, asked = self.asked(command)
                self.assertEqual(proc.stdout, "", "allowed, not refused")
                self.assertEqual(asked, [[str(self.target)]])

    def test_one_request_for_every_path_and_none_for_writable_ones(self):
        locked = self.config / "packages"
        locked.mkdir()
        # codeql[py/overly-permissive-file] the test sets this mode on purpose
        os.chmod(locked, 0o555)
        try:
            _, asked = self.asked(
                f"cp {self.mine} {locked}/new.yaml && tee {self.target} "
                f"< {self.mine}; ls /etc {self.outside}")
        finally:
            # codeql[py/overly-permissive-file] the test sets this mode on purpose
            os.chmod(locked, 0o755)
        self.assertEqual(asked, [[str(locked), str(self.target)]])

    def test_a_command_it_refuses_asks_nothing(self):
        proc, asked = self.asked(
            f"ha service call lock.unlock && cat > {self.target}",
            protected="lock.front_door")
        decision = json.loads(proc.stdout)
        self.assertEqual(
            decision["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(asked, [])

    def test_an_edit_is_the_edit_hook_s_and_asks_nothing_here(self):
        _, asked = self.asked(str(self.target), tool="Write")
        self.assertEqual(asked, [])

    def test_a_panel_that_is_down_lets_the_command_run(self):
        proc, took = self.run_hook(f"http://127.0.0.1:{_closed_port()}",
                                   f"cat > {self.target}")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "")
        self.assertLess(took, 10)

    def test_without_brain_own_it_still_refuses_what_it_refuses(self):
        (self.scripts / "brain_own.py").unlink()
        proc, _ = self.run_hook(f"http://127.0.0.1:{_closed_port()}",
                                f"cat > {self.target}")
        self.assertEqual((proc.returncode, proc.stdout), (0, ""))
        proc, _ = self.run_hook(f"http://127.0.0.1:{_closed_port()}",
                                "ha service call lock.unlock",
                                protected="lock.front_door")
        self.assertIn("deny", proc.stdout)


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

    def test_a_link_out_is_never_asked_about(self):
        victim = self.file("v.yaml", base=self.outside)
        link = self.config / "scenes.yaml"
        link.symlink_to(victim)
        with unittest.mock.patch("os.geteuid", lambda: 1000), \
                unittest.mock.patch("os.access", lambda *a: False):
            self.assertEqual(self.mod.targets_for(link), [])

    def test_a_link_inside_asks_about_what_it_points_at(self):
        """The target is what a write lands in and what the panel checks."""
        real = self.file("git/scenes.yaml")
        link = self.config / "scenes.yaml"
        link.symlink_to(real)
        with unittest.mock.patch("os.geteuid", lambda: 1000), \
                unittest.mock.patch(
                    "os.access", lambda p, m: os.path.realpath(p) != str(real)):
            self.assertEqual(self.mod.targets_for(link), [str(real)])

    def test_the_paths_a_command_names(self):
        c = str(self.config)
        cases = {
            f"cat > {c}/scenes.yaml <<EOF": [f"{c}/scenes.yaml"],
            f"python3 -c \"open('{c}/a.yaml','w')\"": [f"{c}/a.yaml"],
            f"X={c}/a.yaml:{c}/b.yaml": [f"{c}/a.yaml", f"{c}/b.yaml"],
            f"sed -i s/a/b/ {c}/x.yaml,": [f"{c}/x.yaml"],
            f"ls /else{c}/x {c}uration.yaml": [],
            f"cp a {c}/": [c],
            f"cat {c}/.storage/core.config_entries {c}/.git/config": [],
            f"ls {c}/../etc/passwd": [],
            "": [],
        }
        for command, want in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.mod.command_paths(command), want)
        many = " ".join(f"{c}/f{i}.yaml" for i in range(40))
        self.assertEqual(len(self.mod.command_paths(many)),
                         self.mod.MAX_COMMAND_PATHS)

    def test_ok_about_a_file_still_unwritable_is_not_ok(self):
        """The panel's answer is read back off the file: an `ok` that left
        it read-only is reported as the failure it is."""
        target = self.file("scenes.yaml")
        with unittest.mock.patch("os.geteuid", lambda: 1000), \
                unittest.mock.patch("os.access", lambda *a: False), \
                unittest.mock.patch.object(self.mod, "request_own",
                                           return_value={"ok": True}):
            self.assertFalse(self.mod.ensure_writable(target))
        state = {"handed": False}

        def request_own(paths, **kw):
            state["handed"] = True
            return {"ok": True}

        with unittest.mock.patch("os.geteuid", lambda: 1000), \
                unittest.mock.patch("os.access",
                                    lambda *a: state["handed"]), \
                unittest.mock.patch.object(self.mod, "request_own",
                                           request_own):
            self.assertTrue(self.mod.ensure_writable(target))

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
    """`own_ha_config`, lifted out of run.sh and run over a temporary tree,
    under the shell options run.sh and bashio run it under.

    As root the chown is real; otherwise a fake `chown` first on PATH
    records what it was handed, which is the same claim one step earlier —
    and, since it changes nothing, is also a chown the log line has to
    report as not having worked.
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

    def run_block(self, max_entries=None, failing_chown=False):
        harness = "\n".join([
            "set -o errexit -o errtrace -o nounset -o pipefail",
            'bashio::log.info() { echo "INFO $*"; }',
            'bashio::log.warning() { echo "WARN $*"; }',
            lift_run_sh("own_ha_config"),
            f'own_ha_config "{self.config}" "{UID}:{GID}"',
            'echo "EXIT $?"',
        ])
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
        if max_entries is not None:
            env["BRAIN_OWN_MAX"] = str(max_entries)
        if failing_chown:
            # A filesystem that refuses chown: the command runs and fails.
            fake = self.fakebin / "chown"
            fake.write_text("#!/bin/sh\nexit 1\n")
            fake.chmod(0o755)
            env["PATH"] = f"{self.fakebin}{os.pathsep}{env['PATH']}"
        elif not ROOT:
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
        self.assertIn("EXIT 0", proc.stdout)
        chowned = self.chowned()
        for path in self.expect_owned:
            self.assertIn(str(path), chowned, path)
        for path in self.expect_untouched:
            self.assertNotIn(str(path), chowned, path)
        n = len(self.expect_owned)
        if ROOT:
            self.assertIn(f"INFO Config ownership: {n} file(s) and folder(s)",
                          proc.stdout)
            # A link is never followed: the link itself, not its target.
            self.assertEqual(os.stat(self.outside / "target.yaml").st_uid, 0)
        else:
            # The recording chown changes nothing, and the count is read
            # back afterwards rather than taken from what was asked for.
            self.assertIn(f"WARN Config ownership: handed 0 of {n} ",
                          proc.stdout)

    def test_a_chown_that_fails_is_not_reported_as_done(self):
        """`xargs ... || true` swallows the failure, so the count has to be
        read back: never report a hand-over by the number asked for."""
        proc = self.run_block(failing_chown=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("EXIT 0", proc.stdout)
        n = len(self.expect_owned)
        self.assertIn(f"WARN Config ownership: handed 0 of {n} file(s) and "
                      f"folder(s) under {self.config} to {UID}; {n} could not "
                      "be changed", proc.stdout)
        self.assertNotIn("INFO Config ownership", proc.stdout)
        if ROOT:
            self.assertEqual(os.stat(self.config / "automations.yaml").st_uid, 0)

    def test_a_file_with_other_names_is_left_alone(self):
        """The route refuses a hard-linked file and the sweep skips it; the
        boot block follows the same rule, or one of the names (here one in
        .storage) is handed over through the other."""
        store = self.file(".storage/auth")
        os.chmod(store, 0o600)
        os.link(store, self.config / "packages" / "x.yaml")
        proc = self.run_block()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        chowned = self.chowned()
        self.assertNotIn(str(self.config / "packages" / "x.yaml"), chowned)
        self.assertNotIn(str(store), chowned)
        self.assertEqual(os.stat(store).st_uid, os.getuid())

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
        if ROOT:
            self.assertIn("INFO Config ownership: 2 file(s)", proc.stdout)

    def test_a_missing_config_folder_is_not_an_error(self):
        shutil.rmtree(self.config)
        proc = self.run_block()
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout, "EXIT 0\n")

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
        self.assertIn("Never put sudo, chown or `brain own` in the steps",
                      fixer.PLAN_SYSTEM)

    def test_the_approved_plan_does_not_turn_a_permission_into_a_stop(self):
        """`plan_block` says "do exactly these steps and nothing else" and
        "STOP" when a step goes wrong; without this, a fix run meeting a
        root-owned file could read `brain own` as a substitute step and
        report a failed fix over a permission."""
        import fixer
        block = fixer.plan_block({"steps": ["Edit /config/scenes.yaml"]})
        self.assertIn("run `brain own <path>` and carry on", block)
        self.assertIn("never a substitute step and never a reason to stop",
                      block)
        self.assertLess(block.index("STOP"), block.index("brain own"))

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
