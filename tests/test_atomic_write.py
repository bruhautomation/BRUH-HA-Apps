#!/usr/bin/env python3
"""Tests for panel/atomic_write.py — and for the race it exists to end.

The old recipe (`path.with_suffix(".tmp")`, write, replace) is atomic
against a reader and exactly wrong against a second writer: the scratch
name is derived from the target, so every writer picks the same one. The
first `replace()` moves it and the second finds its own file gone —
raising, and losing the write that got there first.

`test_the_old_recipe_is_the_bug` pins that down by reproducing it directly,
so the fix is measured against a failure that is demonstrated rather than
described.
"""

from __future__ import annotations

import concurrent.futures
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "brain" / "panel"))

import atomic_write  # noqa: E402


def _umask() -> int:
    """The process umask, read the only way POSIX offers: by setting it."""
    current = os.umask(0o022)
    os.umask(current)
    return current


class AtomicWriteCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.path = self.dir / "store.json"

    def tearDown(self):
        self.tmp.cleanup()

    def _scratch(self):
        """Anything left in the directory that is not the target."""
        return [p.name for p in self.dir.iterdir() if p != self.path]


class TestBasics(AtomicWriteCase):
    def test_writes_and_replaces(self):
        atomic_write.write_text(self.path, "one")
        self.assertEqual(self.path.read_text(), "one")
        atomic_write.write_text(self.path, "two")
        self.assertEqual(self.path.read_text(), "two")

    def test_creates_parent_directories(self):
        deep = self.dir / "a" / "b" / "c.json"
        atomic_write.write_json(deep, {"x": 1})
        self.assertEqual(json.loads(deep.read_text()), {"x": 1})

    def test_json_and_lines_helpers(self):
        atomic_write.write_json(self.path, {"café": "naïve"})
        # ensure_ascii=False by default: these files hold friendly names, and
        # escaping them costs bytes and readability for nothing.
        self.assertIn("café", self.path.read_text())
        atomic_write.write_lines(self.path, [{"a": 1}, {"b": 2}])
        self.assertEqual(self.path.read_text(), '{"a": 1}\n{"b": 2}\n')

    def test_no_scratch_file_is_left_behind(self):
        atomic_write.write_text(self.path, "x")
        self.assertEqual(self._scratch(), [])

    def test_a_failed_write_leaves_nothing_and_keeps_the_old_contents(self):
        """A directory of orphaned scratch files is what a failed write
        looks like from outside, and the next reader would have to know to
        ignore them."""
        atomic_write.write_text(self.path, "original")

        # An object json.dumps cannot serialize fails mid-write.
        with self.assertRaises(TypeError):
            atomic_write.write_json(self.path, {"bad": object()})
        self.assertEqual(self.path.read_text(), "original")
        self.assertEqual(self._scratch(), [])


class TestPermissions(AtomicWriteCase):
    """mkstemp creates 0600; Path.write_text created 0644 under the add-on's
    umask. Several of these files are written by root and read by the
    `claude` user, so silently narrowing them would break the terminal, the
    listeners and the consolidator with an error nothing reports."""

    def test_a_new_file_gets_what_the_umask_allows(self):
        """Which is what Path.write_text produced, so every one of these
        files already carries it."""
        expect = 0o666 & ~_umask()
        self.assertEqual(atomic_write.DEFAULT_MODE, expect)
        atomic_write.write_text(self.path, "x")
        self.assertEqual(self.path.stat().st_mode & 0o777, expect)
        self.assertTrue(expect & 0o044,
                        "the `claude` user has to be able to read what root wrote")
        self.assertFalse(expect & 0o022, "nothing here should be group/world writable")

    def test_the_scratch_file_is_private_while_it_is_written(self):
        """A half-written store is nobody's business. Anything built on
        open(..., 'w') left the partial file readable for the whole write."""
        seen = []
        real_fsync = os.fsync

        def spy(fd):
            # Mid-write: the scratch file exists and holds partial contents.
            for entry in self.dir.iterdir():
                if entry != self.path:
                    seen.append(entry.stat().st_mode & 0o777)
            return real_fsync(fd)

        os.fsync = spy
        try:
            atomic_write.write_text(self.path, "secret in flight")
        finally:
            os.fsync = real_fsync
        self.assertEqual(seen, [atomic_write.SCRATCH_MODE])

    def test_an_existing_file_keeps_its_mode(self):
        self.path.write_text("old")
        os.chmod(self.path, 0o600)
        atomic_write.write_text(self.path, "new")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_an_explicit_mode_wins(self):
        """The handoff file is 0600 on purpose — the terminal needs it and
        nothing else does."""
        atomic_write.write_text(self.path, "secret", mode=0o600)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        # ...and stays 0600 when rewritten, without being asked again.
        atomic_write.write_text(self.path, "secret2")
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)


@unittest.skipUnless(os.geteuid() == 0, "handing a file over needs root")
class TestOwnership(AtomicWriteCase):
    """`os.replace` swaps in a new inode, so the file comes back owned by
    whoever wrote it.

    `run.sh` creates /data/run-sources.jsonl owned by the `claude` user
    precisely so both halves can write it — the panel is root, the
    consolidator and study watcher are `su-exec claude`, and root can write
    a claude-owned file but not the reverse. The old prune silently undid
    that every time it ran, and the failure is silent by design.
    """

    CLAUDE_UID = CLAUDE_GID = 1000

    def test_a_handed_over_file_stays_handed_over(self):
        self.path.write_text("old")
        os.chown(self.path, self.CLAUDE_UID, self.CLAUDE_GID)
        atomic_write.write_text(self.path, "new")
        st = self.path.stat()
        self.assertEqual((st.st_uid, st.st_gid),
                         (self.CLAUDE_UID, self.CLAUDE_GID))

    def test_the_old_recipe_took_it_back(self):
        """The behaviour this replaces, so the fix is measured against it."""
        self.path.write_text("old")
        os.chown(self.path, self.CLAUDE_UID, self.CLAUDE_GID)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text("new")
        tmp.replace(self.path)
        self.assertEqual(self.path.stat().st_uid, 0)


class TestConcurrency(AtomicWriteCase):
    WRITERS = 8
    ROUNDS = 40

    def test_the_old_recipe_is_the_bug(self):
        """Reproduce the failure this module exists to remove.

        Not a test of our code — a test of the claim about the code it
        replaced, so the fix below is measured against a demonstrated
        failure rather than a described one.
        """
        errors = []
        start = threading.Barrier(self.WRITERS)

        def old_recipe(n):
            start.wait()
            for i in range(self.ROUNDS):
                try:
                    tmp = self.path.with_suffix(".tmp")
                    tmp.write_text(f"writer {n} round {i}")
                    tmp.replace(self.path)
                except OSError as exc:
                    errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(self.WRITERS) as pool:
            list(pool.map(old_recipe, range(self.WRITERS)))
        self.assertTrue(
            errors,
            "the old recipe did not race here — if this ever stops failing, "
            "the concurrency test below has stopped proving anything")
        self.assertTrue(any(isinstance(e, FileNotFoundError) for e in errors))

    def test_concurrent_writers_never_collide(self):
        """The same load through the helper: no error, no lost target, no
        litter, and the file always holds one writer's complete bytes."""
        errors = []
        start = threading.Barrier(self.WRITERS)

        def writer(n):
            start.wait()
            for i in range(self.ROUNDS):
                try:
                    atomic_write.write_json(
                        self.path, {"writer": n, "round": i, "pad": "x" * 500})
                except OSError as exc:
                    errors.append(exc)

        with concurrent.futures.ThreadPoolExecutor(self.WRITERS) as pool:
            list(pool.map(writer, range(self.WRITERS)))
        self.assertEqual(errors, [])
        self.assertEqual(self._scratch(), [], "scratch files left behind")
        # Whole bytes from ONE writer — never two writers' output spliced.
        data = json.loads(self.path.read_text())
        self.assertIn(data["writer"], range(self.WRITERS))
        self.assertEqual(data["pad"], "x" * 500)

    def test_a_reader_never_sees_a_partial_file(self):
        """The property the old recipe did get right, kept."""
        atomic_write.write_json(self.path, {"n": 0, "pad": "y" * 2000})
        stop = threading.Event()
        bad = []

        def reader():
            while not stop.is_set():
                try:
                    obj = json.loads(self.path.read_text())
                except (OSError, ValueError) as exc:
                    bad.append(exc)
                    return
                if obj.get("pad") != "y" * 2000:
                    bad.append(obj)
                    return

        thread = threading.Thread(target=reader)
        thread.start()
        try:
            for i in range(200):
                atomic_write.write_json(self.path, {"n": i, "pad": "y" * 2000})
        finally:
            stop.set()
            thread.join(timeout=5)
        self.assertEqual(bad, [])


class TestEveryStoreUsesIt(unittest.TestCase):
    def test_no_module_derives_a_scratch_name_from_its_target(self):
        """The bug was a pattern, so the guard is against the pattern.

        A new store copying `path.with_suffix(".tmp")` from an old one is
        exactly how this comes back, and it comes back silent — a race that
        shows up as one failed CI run in three.
        """
        offenders = []
        for panel in (BASE_DIR / "brain" / "panel", BASE_DIR / "brigt" / "panel"):
            for path in sorted(panel.glob("*.py")):
                if path.name == "atomic_write.py":
                    continue  # the one file allowed to talk about scratch files
                text = path.read_text(encoding="utf-8")
                for lineno, line in enumerate(text.split("\n"), 1):
                    if 'with_suffix(".tmp")' in line or '.tmp"' in line:
                        offenders.append(f"{path.name}:{lineno}: {line.strip()}")
        self.assertEqual(offenders, [], "use atomic_write instead:\n"
                         + "\n".join(offenders))


if __name__ == "__main__":
    unittest.main()
