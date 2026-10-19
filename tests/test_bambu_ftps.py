#!/usr/bin/env python3
"""The printer's storage over implicit FTPS: the two details that decide
whether an upload works or hangs.

* The data channel resumes the control channel's TLS session — the
  printer refuses a data connection that negotiates a new one.
* An upload closes the data socket without `unwrap()` — the printer never
  answers close_notify, so ftplib's own `storbinary` hangs to its timeout.
"""
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import bambu_env  # noqa: E402

ftps, = bambu_env.load("bambu.ftps")


class FakeSock:
    def __init__(self):
        self.sent, self.closed, self.unwrapped = b"", False, False
        self.session = "control-session"

    def sendall(self, data):
        self.sent += data

    def shutdown(self, how):
        pass

    def close(self):
        self.closed = True

    def unwrap(self):
        self.unwrapped = True


class TestImplicitFTPS(unittest.TestCase):
    def test_the_data_channel_resumes_the_control_session(self):
        ftp = ftps.ImplicitFTPS()
        ftp._sock = FakeSock()
        ftp.host = "10.0.0.2"
        ftp._prot_p = True
        raw = object()
        with mock.patch.object(ftps.ftplib.FTP, "ntransfercmd", return_value=(raw, None)), \
                mock.patch.object(ftp.context, "wrap_socket", return_value="wrapped") as wrap:
            conn, _ = ftp.ntransfercmd("STOR x")
        self.assertEqual(conn, "wrapped")
        self.assertEqual(wrap.call_args.kwargs["session"], "control-session")

    def test_the_certificate_is_not_verified_because_the_access_code_authenticates(self):
        context = ftps._context()
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, ftps.ssl.CERT_NONE)


class TestUpload(unittest.TestCase):
    def test_an_upload_closes_without_unwrap_and_reads_the_226(self):
        data = FakeSock()
        ftp = mock.Mock()
        ftp.transfercmd.return_value = data
        storage = ftps.Storage("10.0.0.2", "abcd1234")
        storage.ftp = ftp
        with tempfile.NamedTemporaryFile(delete=False) as tmp:
            tmp.write(b"x" * 200_000)
        self.addCleanup(os.unlink, tmp.name)
        seen = []
        sent = storage.upload(tmp.name, "benchy.gcode.3mf",
                              progress=lambda s, t: seen.append((s, t)))
        self.assertEqual(sent, 200_000)
        self.assertEqual(data.sent, b"x" * 200_000)
        ftp.transfercmd.assert_called_with("STOR benchy.gcode.3mf")
        self.assertTrue(data.closed)
        self.assertFalse(data.unwrapped)
        ftp.voidresp.assert_called_once()
        self.assertEqual(seen[-1], (200_000, 200_000))

    def test_a_name_the_printer_cannot_store_is_refused(self):
        self.assertEqual(ftps.safe_name("/a/b/benchy.3mf"), "benchy.3mf")
        for bad in ("..", "", "a;b|c.3mf", "x" * 200):
            with self.subTest(bad=bad[:10]), self.assertRaises(ValueError):
                ftps.safe_name(bad)

    def test_a_listing_is_read_off_the_list_lines(self):
        storage = ftps.Storage("h", "c")
        storage.ftp = mock.Mock()
        storage.ftp.retrlines.side_effect = lambda cmd, cb: [cb(line) for line in (
            "drwxr-xr-x 1 0 0 0 Jan 1 00:00 timelapse",
            "-rw-r--r-- 1 0 0 1048576 Jan 1 00:00 benchy.gcode.3mf",
            "garbage")]
        self.assertEqual(storage.listing(), [
            {"name": "timelapse", "dir": True, "size": 0},
            {"name": "benchy.gcode.3mf", "dir": False, "size": 1048576}])


if __name__ == "__main__":
    unittest.main()
