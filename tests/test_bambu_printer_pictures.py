#!/usr/bin/env python3
"""A file on the printer shows its plate picture, and a read that went wrong
is never remembered as "this file has no picture".

The On the printer list showed cards with no pictures. What is held here:

* A read that came back short (the printer closed the data channel early)
  is a read error, not a smaller file: zipfile read the hole as "not a zip"
  and the file was cached as pictureless for ever.
* After a transfer is cut on purpose the printer's answer may never come:
  that wait is bounded, and the next read opens a fresh session rather
  than the picture failing.
* A printer serves one storage session at a time well, and a list of jobs
  asks for every picture at once: the reads for one printer queue.
* Pictures cached as "none" by a release that could not tell those apart
  are not trusted.
"""
import ftplib
import os
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

ftps, thumbs = bambu_env.load("bambu.ftps", "thumbs")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x01" * 400


def job(path: Path) -> bytes:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("Metadata/plate_1.gcode", "G28\n" * 40000)
        z.writestr("Metadata/plate_1.png", PNG)
    return path.read_bytes()


class Storage:
    """read_range over bytes, the way the printer's server answers."""

    open_now = 0
    most_open = 0
    lock = threading.Lock()

    def __init__(self, data: bytes, short: bool = False, delay: float = 0.0):
        self.data, self.short, self.delay = data, short, delay

    def __enter__(self):
        with Storage.lock:
            Storage.open_now += 1
            Storage.most_open = max(Storage.most_open, Storage.open_now)
        return self

    def __exit__(self, *exc):
        with Storage.lock:
            Storage.open_now -= 1
        return False

    def read_range(self, _name, offset, length):
        time.sleep(self.delay)
        chunk = self.data[offset:offset + length]
        return chunk[:len(chunk) // 2] if self.short else chunk


class TestPictures(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        patch = mock.patch.object(thumbs, "CACHE", self.tmp / "cache")
        patch.start()
        self.addCleanup(patch.stop)
        self.data = job(self.tmp / "rotor.gcode.3mf")

    def test_a_short_read_is_an_error_and_is_not_remembered_as_no_picture(self):
        with self.assertRaises(OSError):
            thumbs.printer("SER", "rotor.gcode.3mf", len(self.data), lambda: Storage(self.data, short=True))
        self.assertEqual(thumbs.printer("SER", "rotor.gcode.3mf", len(self.data),
                                        lambda: Storage(self.data)), PNG)

    def test_reads_for_one_printer_queue_rather_than_open_together(self):
        Storage.most_open = 0
        names = [f"job{i}.gcode.3mf" for i in range(4)]
        got = {}

        def read(name):
            got[name] = thumbs.printer("SER2", name, len(self.data), lambda: Storage(self.data, delay=0.01))

        threads = [threading.Thread(target=read, args=(n,)) for n in names]
        for t in threads:
            t.start()
        for t in threads:
            t.join(10)
        self.assertEqual(Storage.most_open, 1)
        self.assertEqual(set(got.values()), {PNG})

    def test_a_none_cached_by_an_older_release_is_not_trusted(self):
        old = thumbs.CACHE / "printer" / thumbs._key("SER3") / f"{thumbs._key('rotor.gcode.3mf', len(self.data))}.png"
        old.parent.mkdir(parents=True)
        old.write_bytes(b"")
        self.assertEqual(thumbs.printer("SER3", "rotor.gcode.3mf", len(self.data),
                                        lambda: Storage(self.data)), PNG)


class FakeFTP:
    """The control channel: the answer to a cut transfer may never come."""

    def __init__(self, data: bytes, silent: bool):
        self.data, self.silent, self.closed = data, silent, False
        self.sock = mock.Mock()

    def voidcmd(self, cmd):
        return "200"

    def transfercmd(self, cmd, rest=None):
        start = rest or 0
        conn = mock.Mock()
        rest_of_file = [self.data[start:]]

        def recv(n):
            piece, rest_of_file[0] = rest_of_file[0][:n], rest_of_file[0][n:]
            return piece

        conn.recv.side_effect = recv
        return conn

    def voidresp(self):
        if self.silent:
            raise TimeoutError("timed out")
        return "226"

    def quit(self):
        self.closed = True

    def close(self):
        self.closed = True


class TestACutTransfer(unittest.TestCase):
    def test_a_silent_answer_does_not_lose_the_bytes_and_the_next_read_reconnects(self):
        data = bytes(range(256)) * 8
        storage = ftps.Storage("10.0.0.2", "code")
        first = FakeFTP(data, silent=True)
        second = FakeFTP(data, silent=False)
        storage.ftp = first
        with mock.patch.object(ftps.Storage, "_connect", return_value=second) as connect:
            self.assertEqual(storage.read_range("a.3mf", 0, 512), data[:512])
            self.assertTrue(first.closed)
            self.assertEqual(storage.read_range("a.3mf", 512, 256), data[512:768])
        connect.assert_called_once()
        self.assertIs(storage.ftp, second)

    def test_an_answer_that_refuses_is_still_read_off_the_control_channel(self):
        data = b"x" * 4096
        storage = ftps.Storage("10.0.0.2", "code")
        ftp = FakeFTP(data, silent=False)
        ftp.voidresp = mock.Mock(side_effect=ftplib.error_temp("426 cut"))
        storage.ftp = ftp
        self.assertEqual(storage.read_range("a.3mf", 0, 100), data[:100])
        self.assertFalse(ftp.closed)


if __name__ == "__main__":
    unittest.main()
