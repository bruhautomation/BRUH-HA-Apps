#!/usr/bin/env python3
"""What `tmp + rename` has to get right, measured rather than described.

Every assertion here is a failure that is silent when it happens: a lost
write reads as a store that forgot something, a narrowed mode reads as Home
Assistant losing the add-on, and a scratch file left readable is a partial
store somebody could read in the millisecond it exists.
"""
import os
import stat
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))

import bruh_print_env  # noqa: E402

(atomic_write,) = bruh_print_env.load("atomic_write")


class TestTheRaceItExistsFor(unittest.TestCase):
    def test_two_writers_do_not_share_a_scratch_name(self):
        """The bug: a scratch name derived from the target is the SAME name
        for every writer, so the loser's bytes go into a file the winner has
        already renamed away and one write is silently lost.

        Reproduced as the old recipe first, so the guard is measured against
        a demonstrated failure rather than a described one.
        """
        directory = Path(tempfile.mkdtemp())
        target = directory / "store.json"

        # The old recipe, run as two interleaved writers.
        losses = []

        def old_style(payload: bytes) -> None:
            tmp = target.with_suffix(".tmp")
            try:
                tmp.write_bytes(payload)
                tmp.replace(target)
            except FileNotFoundError:
                losses.append(payload)

        barrier = threading.Barrier(2)

        def racer(payload: bytes) -> None:
            barrier.wait()
            for _ in range(200):
                old_style(payload)

        threads = [threading.Thread(target=racer, args=(bytes([n]) * 64,))
                   for n in (1, 2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertTrue(
            losses,
            "the old recipe did not race here — the guard below is still "
            "right, but this test is no longer measuring anything")

        # The new one, same shape, no collisions possible.
        errors = []

        def new_style(payload: bytes) -> None:
            try:
                atomic_write.write_bytes(target, payload)
            except OSError as exc:
                errors.append(exc)

        def racer2(payload: bytes) -> None:
            barrier2.wait()
            for _ in range(200):
                new_style(payload)

        barrier2 = threading.Barrier(2)
        threads = [threading.Thread(target=racer2, args=(bytes([n]) * 64,))
                   for n in (3, 4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual([], errors)
        # Whoever won, the file is one writer's bytes whole — never a mix.
        final = target.read_bytes()
        self.assertIn(final, (bytes([3]) * 64, bytes([4]) * 64))

    def test_no_scratch_files_are_left_behind(self):
        directory = Path(tempfile.mkdtemp())
        atomic_write.write_json(directory / "a.json", {"x": 1})
        self.assertEqual(["a.json"], [p.name for p in directory.iterdir()])


class TestPermissions(unittest.TestCase):
    def test_a_new_file_follows_the_umask_not_a_literal(self):
        """A hardcoded 0o644 makes every file in /data world-readable when
        nothing outside the container reads them, and ignores a umask the
        operator set on purpose."""
        directory = Path(tempfile.mkdtemp())
        previous = os.umask(0o077)
        try:
            atomic_write.write_json(directory / "private.json", {"x": 1})
        finally:
            os.umask(previous)
        mode = stat.S_IMODE((directory / "private.json").stat().st_mode)
        self.assertEqual(0o600, mode)
        self.assertFalse(mode & 0o007, "world-readable under a 0o077 umask")

    def test_an_explicit_mode_wins(self):
        """Nothing in the panel passes one today — the mirror Home Assistant
        reads takes the umask's default like every other store — but the
        parameter is the escape hatch for the day one does, and a parameter
        that silently lost to the umask would be the worse surprise."""
        directory = Path(tempfile.mkdtemp())
        previous = os.umask(0o077)
        try:
            atomic_write.write_json(directory / "mirror.json", {"x": 1},
                                    mode=0o644)
        finally:
            os.umask(previous)
        self.assertEqual(
            0o644, stat.S_IMODE((directory / "mirror.json").stat().st_mode))

    def test_an_existing_file_keeps_the_mode_it_had(self):
        """os.replace swaps the inode, so without this a rewrite silently
        re-permissions a file somebody set deliberately."""
        directory = Path(tempfile.mkdtemp())
        path = directory / "kept.json"
        atomic_write.write_json(path, {"x": 1})
        # 0o600 rather than a mode carrying group or world bits: it is just
        # as distinct from the umask's default, and it proves the same thing
        # without the test itself being an example of the pattern the file
        # under test exists to remove.
        os.chmod(path, 0o600)
        atomic_write.write_json(path, {"x": 2})
        self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_the_scratch_file_is_never_world_readable(self):
        """A half-written store is nobody's business, and anything built on
        open(..., "w") leaves the partial file readable throughout."""
        self.assertEqual(0o600, atomic_write.SCRATCH_MODE)


class TestDurability(unittest.TestCase):
    def test_read_json_answers_the_default_rather_than_raising(self):
        """A store file hand-edited into nonsense must not stop the panel
        serving — the panel is the only way to fix it."""
        directory = Path(tempfile.mkdtemp())
        broken = directory / "broken.json"
        broken.write_text("{not json")
        self.assertEqual({"fallback": True},
                         atomic_write.read_json(broken, {"fallback": True}))
        self.assertIsNone(atomic_write.read_json(directory / "absent.json"))

    def test_a_failed_write_leaves_the_old_contents_alone(self):
        directory = Path(tempfile.mkdtemp())
        path = directory / "store.json"
        atomic_write.write_json(path, {"good": True})

        class Unserialisable:
            pass

        with self.assertRaises(TypeError):
            atomic_write.write_json(path, {"bad": Unserialisable()})
        self.assertIn("good", path.read_text())
        self.assertEqual(["store.json"], [p.name for p in directory.iterdir()])


if __name__ == "__main__":
    unittest.main()
