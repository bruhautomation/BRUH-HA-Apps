#!/usr/bin/env python3
"""Finding Bambu Lab printers on the network.

A printer is recognised by the certificate its MQTT port answers with:
issued by Bambu Lab's device CA, named for the printer's serial. The tests
mint that chain with openssl and serve it from a real TLS socket, because a
fake that returned a parsed certificate would test the fake's idea of one.
"""
import http.server
import ipaddress
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from test_bambu_panel import RouteTest, server, store  # noqa: E402

discover = server.discover
SERIAL = "01P00A123456789"


def _openssl(*args, cwd):
    subprocess.run(["openssl", *args], cwd=cwd, check=True, capture_output=True)


def make_chain(folder: Path, issuer_cn: str, subject_cn: str) -> tuple[Path, Path]:
    """A CA called `issuer_cn` signing a leaf called `subject_cn`: (cert, key)."""
    _openssl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
             "-subj", f"/CN={issuer_cn}", "-keyout", "ca.key", "-out", "ca.pem", cwd=folder)
    _openssl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={subject_cn}",
             "-keyout", "leaf.key", "-out", "leaf.csr", cwd=folder)
    _openssl("x509", "-req", "-in", "leaf.csr", "-CA", "ca.pem", "-CAkey", "ca.key",
             "-CAcreateserial", "-days", "2", "-out", "leaf.pem", cwd=folder)
    return folder / "leaf.pem", folder / "leaf.key"


class TlsServer:
    """One TLS listener on loopback, answering handshakes until closed."""

    def __init__(self, cert: Path, key: Path):
        self.context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.context.load_cert_chain(cert, key)
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            try:
                with self.context.wrap_socket(conn, server_side=True) as tls:
                    tls.recv(1)
            except (OSError, ssl.SSLError):
                pass  # a probe hangs up once it has the certificate; that is the whole visit

    def close(self):
        self.sock.close()


@unittest.skipUnless(shutil.which("openssl"), "openssl is needed to mint the certificates")
class TestAPrinterIsKnownByItsCertificate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        (root / "bambu").mkdir()
        (root / "router").mkdir()
        cls.printer = TlsServer(*make_chain(root / "bambu", "BBL Device CA N1-V2", SERIAL))
        cls.router = TlsServer(*make_chain(root / "router", "Acme Router CA", "router.local"))
        cls.der = ssl.PEM_cert_to_DER_cert((root / "bambu" / "leaf.pem").read_text())

    @classmethod
    def tearDownClass(cls):
        cls.printer.close()
        cls.router.close()
        cls.tmp.cleanup()

    def probe_on(self, port):
        with unittest.mock.patch.object(discover, "PORT", port):
            return discover.probe("127.0.0.1")

    def test_the_issuer_and_the_subject_are_read_in_order(self):
        self.assertEqual(discover.common_names(self.der), ["BBL Device CA N1-V2", SERIAL])

    def test_a_printer_answers_with_its_serial_and_model(self):
        self.assertEqual(self.probe_on(self.printer.port),
                         {"host": "127.0.0.1", "serial": SERIAL, "model": "P1S"})

    def test_anything_else_with_tls_is_not_a_printer(self):
        self.assertIsNone(self.probe_on(self.router.port))

    def test_nothing_listening_is_nothing_found(self):
        spare = socket.socket()
        spare.bind(("127.0.0.1", 0))
        port = spare.getsockname()[1]
        spare.close()
        self.assertIsNone(self.probe_on(port))

    def test_a_scan_finds_it_among_the_addresses(self):
        with unittest.mock.patch.object(discover, "PORT", self.printer.port):
            found = discover.scan([ipaddress.ip_network("127.0.0.0/30")])
        # Only 127.0.0.1 is listening; the other address in the /30 is nobody.
        self.assertEqual([(f["host"], f["serial"]) for f in found], [("127.0.0.1", SERIAL)])


class TestWhichNetworksAreSearched(unittest.TestCase):
    def test_a_host_address_is_its_network_and_a_wide_one_its_24(self):
        self.assertEqual(str(discover.narrowed("192.168.1.10/24")), "192.168.1.0/24")
        self.assertEqual(str(discover.narrowed("10.0.5.7/16")), "10.0.5.0/24")
        self.assertEqual(str(discover.narrowed("10.0.4.7/22")), "10.0.4.0/22")

    def test_networks_that_hold_no_printer_are_never_searched(self):
        for address in ("172.30.32.1/23", "127.0.0.1/8", "169.254.3.4/16", "fd00::1/64",
                        "not an address", "192.168.1.1/32"):
            with self.subTest(address=address):
                self.assertIsNone(discover.narrowed(address))

    def test_the_supervisor_says_which_networks_home_assistant_is_on(self):
        answer = {"data": {"interfaces": [
            {"interface": "end0", "enabled": True, "connected": True,
             "ipv4": {"address": ["192.168.1.20/24"]}},
            {"interface": "wlan0", "enabled": True, "connected": False,
             "ipv4": {"address": ["192.168.9.4/24"]}},
            {"interface": "hassio", "enabled": True, "connected": True,
             "ipv4": {"address": ["172.30.32.1/23"]}}]}}

        class Handler(http.server.BaseHTTPRequestHandler):
            seen = []

            def log_message(self, *_):
                pass

            def do_GET(self):
                Handler.seen.append((self.path, self.headers.get("Authorization")))
                body = json.dumps(answer).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        supervisor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=supervisor.serve_forever, daemon=True).start()
        self.addCleanup(supervisor.shutdown)
        with unittest.mock.patch.object(discover, "SUPERVISOR", f"http://127.0.0.1:{supervisor.server_port}"), \
                unittest.mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "tok"}):
            nets = discover.lan_networks()
        self.assertEqual([str(n) for n in nets], ["192.168.1.0/24"])
        self.assertEqual(Handler.seen, [("/network/info", "Bearer tok")])

    def test_no_supervisor_is_no_networks(self):
        with unittest.mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(discover.lan_networks(), [])


class TestTheScanRoute(RouteTest):
    def found(self):
        return [{"host": "192.168.1.50", "serial": "AAAA11112222", "model": ""},
                {"host": "192.168.1.60", "serial": "01S00C123456789", "model": "P1P"}]

    def test_a_scan_says_what_is_new_and_what_has_moved(self):
        with unittest.mock.patch.object(discover, "lan_networks",
                                        return_value=[ipaddress.ip_network("192.168.1.0/24")]), \
                unittest.mock.patch.object(discover, "scan", return_value=self.found()):
            status, body = self.call("POST", "/api/printers/scan", json={"wait": 10})
        self.assertEqual(status, 200, body)
        rows = {r["serial"]: r for r in body["job"]["found"]}
        known = rows["AAAA11112222"]
        self.assertEqual((known["known"], known["moved"], known["saved_host"]),
                         ("aaaa11112222", True, "10.0.0.2"))
        self.assertNotIn("known", rows["01S00C123456789"])
        # The saved printer's own network is searched too.
        self.assertIn("10.0.0.0/24", body["job"]["networks"])

    def test_a_network_named_is_the_only_one_searched(self):
        with unittest.mock.patch.object(discover, "lan_networks") as lan, \
                unittest.mock.patch.object(discover, "scan", return_value=[]) as scan:
            _, body = self.call("POST", "/api/printers/scan",
                                json={"subnet": "192.168.7.0/24", "wait": 10})
        lan.assert_not_called()
        self.assertEqual(body["job"]["networks"], ["192.168.7.0/24"])
        self.assertEqual(scan.call_args[0][0], [ipaddress.ip_network("192.168.7.0/24")])

    def test_no_network_to_search_says_so(self):
        store.remove("aaaa11112222")
        with unittest.mock.patch.object(discover, "lan_networks", return_value=[]):
            _, body = self.call("POST", "/api/printers/scan", json={"wait": 10})
        self.assertFalse(body["ok"])
        self.assertIn("192.168.1.0/24", body["error"])

    def test_a_moved_printer_keeps_its_access_code(self):
        status, body = self.call("POST", "/api/printers", json={
            "name": "X1C", "host": "192.168.1.50", "serial": "AAAA11112222"})
        self.assertEqual(status, 200, body)
        self.assertEqual(store.load()[0]["host"], "192.168.1.50")
        self.assertEqual(store.codes()["aaaa11112222"], "abcd1234")


if __name__ == "__main__":
    unittest.main()
