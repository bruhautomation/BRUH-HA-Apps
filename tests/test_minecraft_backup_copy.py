#!/usr/bin/env python3
"""scripts/backup.sh must save the world, and say so when it could not.

#570: the image had no rsync, backup.sh called it anyway, the snapshot held
only config files, and the backup still reported done. These tests drive the
real script against a temp world: with rsync missing it must fail loudly, and
with a copy tool it must hold level.dat and the region files.
"""
from __future__ import annotations

import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ADDON = BASE_DIR / "bruh-minecraft-server"
BACKUP = ADDON / "scripts" / "backup.sh"

# Everything backup.sh needs except rsync, linked into a private bin dir so
# "rsync is not installed" is true whatever the host has.
TOOLS = ("bash", "git", "python3", "grep", "cut", "head", "date", "mkdir", "cp",
         "sleep", "du", "awk", "tar", "ls", "rm", "dirname", "basename", "cat",
         "printf", "sed", "tr", "env", "stat", "mv", "wc", "sort", "find", "ln", "gzip")

FAKE_RSYNC = """#!/bin/bash
# Minimal rsync stand-in: rsync -a --delete [--exclude=..] SRC/ DST/
args=()
for a in "$@"; do case "$a" in -*) ;; *) args+=("$a") ;; esac; done
src="${args[0]}"; dst="${args[1]}"
mkdir -p "$dst" && cp -a "$src." "$dst"
"""


def _bin_dir(root: Path, with_rsync: bool, rsync_body: str = FAKE_RSYNC) -> Path:
    b = root / "bin"
    b.mkdir()
    for t in TOOLS:
        found = shutil.which(t)
        if found:
            (b / t).symlink_to(found)
    if with_rsync:
        r = b / "rsync"
        r.write_text(rsync_body)
        r.chmod(r.stat().st_mode | stat.S_IEXEC)
    return b


def _world(root: Path, nether: bool = True) -> Path:
    server = root / "server"
    (server / "world" / "region").mkdir(parents=True)
    (server / "world" / "level.dat").write_bytes(b"LEVEL")
    (server / "world" / "region" / "r.0.0.mca").write_bytes(b"REGION")
    if nether:
        (server / "world_nether" / "DIM-1" / "region").mkdir(parents=True)
        (server / "world_nether" / "DIM-1" / "region" / "r.0.0.mca").write_bytes(b"NETHER")
    (server / "server.properties").write_text("level-name=world\n")
    return server


def _scripts(root: Path) -> Path:
    """A copy of scripts/ whose rcon.py answers at once (the real one retries
    for 20 s per call against a server that is not there)."""
    dst = root / "scripts"
    if not dst.exists():
        shutil.copytree(ADDON / "scripts", dst)
        (dst / "rcon.py").write_text(
            "import os, sys\n"
            "log = os.environ.get('RCON_LOG')\n"
            "if log:\n    open(log, 'a').write(sys.argv[1] + '\\n')\n")
    return dst


def _run(root: Path, server: Path, bindir: Path, *args: str, git: bool = True):
    env = {
        "PATH": str(bindir),
        "MC_SERVER_DIR": str(server),
        "MC_BACKUP_DIR": str(root / "backups"),
        "BACKUP_USE_GIT": "true" if git else "false",
        "MC_PANEL_STATE": str(root / "panel"),
        "RCON_PASSWORD": "x",
        "RCON_PORT": "1",
        "HOME": str(root),
    }
    env["RCON_LOG"] = str(root / "rcon.log")
    return subprocess.run(["bash", str(_scripts(root) / "backup.sh"), *args], env=env,
                          capture_output=True, text=True, timeout=60)


class TestBackupCopiesTheWorld(unittest.TestCase):
    def test_without_rsync_it_fails_and_says_why(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = _world(root)
            proc = _run(root, server, _bin_dir(root, with_rsync=False))
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("rsync", proc.stdout + proc.stderr)
            self.assertIn("not installed", proc.stdout + proc.stderr)

    def test_with_rsync_the_snapshot_holds_the_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = _world(root)
            proc = _run(root, server, _bin_dir(root, with_rsync=True))
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            repo = root / "backups" / "git"
            self.assertEqual((repo / "world" / "level.dat").read_bytes(), b"LEVEL")
            self.assertTrue((repo / "world" / "region" / "r.0.0.mca").is_file())
            self.assertTrue((repo / "world_nether" / "DIM-1" / "region" / "r.0.0.mca").is_file())
            tracked = subprocess.run(["git", "-C", str(repo), "ls-files"],
                                     capture_output=True, text=True).stdout
            self.assertIn("world/level.dat", tracked)
            self.assertIn("world/region/r.0.0.mca", tracked)

    def test_a_failed_copy_step_fails_the_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = _world(root)
            bad = "#!/bin/bash\necho 'rsync: disk full' >&2\nexit 11\n"
            proc = _run(root, server, _bin_dir(root, with_rsync=True, rsync_body=bad))
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn("copy", (proc.stdout + proc.stderr).lower())

    def test_no_world_folder_is_a_failure_not_a_done(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = root / "server"
            server.mkdir()
            (server / "server.properties").write_text("level-name=world\n")
            proc = _run(root, server, _bin_dir(root, with_rsync=True))
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)

    def test_tar_mode_holds_the_world_and_checks_tar(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = _world(root)
            proc = _run(root, server, _bin_dir(root, with_rsync=False), git=False)
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            archives = list((root / "backups" / "archives").glob("world-*.tar.gz"))
            self.assertEqual(len(archives), 1)
            listing = subprocess.run(["tar", "-tzf", str(archives[0])],
                                     capture_output=True, text=True).stdout
            self.assertIn("world/level.dat", listing)

    def test_flush_is_resumed_even_when_the_copy_fails(self):
        # save-off must never be left on: the script ends with save-on.
        text = BACKUP.read_text()
        self.assertIn("rcon_resume", text)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = _world(root)
            bad = "#!/bin/bash\nexit 23\n"
            proc = _run(root, server, _bin_dir(root, with_rsync=True, rsync_body=bad))
            self.assertNotEqual(proc.returncode, 0)
            calls = (root / "rcon.log").read_text().split("\n")
            self.assertIn("save-off", calls)
            self.assertIn("save-on", calls)


class TestBackupSelfCheck(unittest.TestCase):
    def test_check_flag_reports_the_copy_tool_plainly(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = _world(root)
            bad = _run(root, server, _bin_dir(root, with_rsync=False), "--check")
            self.assertNotEqual(bad.returncode, 0)
            self.assertIn("rsync is not installed", bad.stdout + bad.stderr)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            server = _world(root)
            good = _run(root, server, _bin_dir(root, with_rsync=True), "--check")
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)

    def test_the_image_installs_rsync_and_run_sh_runs_the_check(self):
        self.assertRegex((ADDON / "Dockerfile").read_text(), r"(?m)^\s+rsync\s*\\?$")
        self.assertIn("backup.sh\" --check", (ADDON / "run.sh").read_text())


if __name__ == "__main__":
    unittest.main()
