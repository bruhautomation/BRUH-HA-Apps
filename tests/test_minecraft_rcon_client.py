#!/usr/bin/env python3
"""Behaviour tests for the thread-safe RCON client at scripts/rcon_client.py.

The old `mcrcon` package used `signal.SIGALRM` for its connect-timeout, which
raised ``ValueError: signal only works in main thread of the main interpreter``
when called from a worker thread (exactly how the ingress panel uses it via
`asyncio.to_thread`). These tests lock in:

* Clean auth + command round-trip against a tiny in-process RCON server.
* Multi-packet command replies are reassembled in order.
* Bad password raises ``RconAuthError``.
* The whole flow still works when invoked from a non-main thread — that's
  the regression fix.
"""
from __future__ import annotations

import importlib.util
import os
import socket
import struct
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

BASE_DIR = os.path.join(os.path.dirname(__file__), "..")
SCRIPTS_DIR = os.path.join(BASE_DIR, "bruh-minecraft-server", "scripts")


def _load_rcon_client():
    spec = importlib.util.spec_from_file_location(
        "rcon_client", os.path.join(SCRIPTS_DIR, "rcon_client.py"),
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return module


rcon_client = _load_rcon_client()


# ---------------------------------------------------------------------------
# Minimal in-process RCON server for round-trip tests
# ---------------------------------------------------------------------------
SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


def _pack(rid: int, ptype: int, body: str) -> bytes:
    payload = body.encode("utf-8") + b"\x00\x00"
    packet = struct.pack("<ii", rid, ptype) + payload
    return struct.pack("<i", len(packet)) + packet


def _recv_packet(sock: socket.socket) -> tuple[int, int, str]:
    hdr = b""
    while len(hdr) < 4:
        chunk = sock.recv(4 - len(hdr))
        if not chunk:
            raise ConnectionError("closed")
        hdr += chunk
    (length,) = struct.unpack("<i", hdr)
    body = b""
    while len(body) < length:
        chunk = sock.recv(length - len(body))
        if not chunk:
            raise ConnectionError("closed")
        body += chunk
    rid, ptype = struct.unpack("<ii", body[:8])
    payload = body[8:-2].decode("utf-8", "replace")
    return rid, ptype, payload


class FakeRconServer:
    """One-shot in-process RCON server that speaks the Source protocol."""

    def __init__(self, password: str = "pw", replies: dict[str, list[str]] | None = None) -> None:
        self.password = password
        # Map command -> list of response body chunks. None means unknown.
        self.replies: dict[str, list[str]] = replies or {}
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(1)
        self.port: int = self._sock.getsockname()[1]
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            client, _ = self._sock.accept()
        except OSError:
            return
        try:
            client.settimeout(5.0)
            # --- auth ---
            auth_rid, auth_type, auth_body = _recv_packet(client)
            assert auth_type == SERVERDATA_AUTH
            if auth_body == self.password:
                client.sendall(_pack(auth_rid, SERVERDATA_AUTH_RESPONSE, ""))
            else:
                # -1 signals auth failure per the protocol spec
                client.sendall(_pack(-1, SERVERDATA_AUTH_RESPONSE, ""))
                return
            # --- command loop ---
            while True:
                try:
                    rid, _ptype, cmd = _recv_packet(client)
                except (ConnectionError, OSError):
                    return
                if cmd == "":
                    # Sentinel — echo it back so the client knows the
                    # previous command's response is complete.
                    client.sendall(_pack(rid, SERVERDATA_RESPONSE_VALUE, ""))
                    continue
                parts = self.replies.get(cmd, ["unknown command"])
                for chunk in parts:
                    client.sendall(_pack(rid, SERVERDATA_RESPONSE_VALUE, chunk))
        finally:
            try:
                client.close()
            except Exception:
                # The fake server is shutting down — a client socket that is already
                # closed needs nothing.
                pass
            self._sock.close()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
class TestRconClient(unittest.TestCase):
    def _server(self, replies: dict[str, list[str]], password: str = "pw") -> FakeRconServer:
        srv = FakeRconServer(password=password, replies=replies)
        srv.start()
        self.addCleanup(lambda: None)  # sockets are daemons; nothing to tear down
        return srv

    def test_auth_and_single_packet_reply(self):
        srv = self._server({"list": ["There are 0 of a max of 20 players online: "]})
        with rcon_client.Rcon("127.0.0.1", "pw", port=srv.port, timeout=2.0) as r:
            reply = r.command("list")
        self.assertIn("players online", reply)

    def test_multi_packet_reply_is_reassembled(self):
        srv = self._server({"tellraw": ["chunk-A|", "chunk-B|", "chunk-C"]})
        with rcon_client.Rcon("127.0.0.1", "pw", port=srv.port, timeout=2.0) as r:
            reply = r.command("tellraw")
        self.assertEqual(reply, "chunk-A|chunk-B|chunk-C")

    def test_wrong_password_raises_auth_error(self):
        srv = self._server({}, password="correct-pw")
        with self.assertRaises(rcon_client.RconAuthError):
            with rcon_client.Rcon("127.0.0.1", "WRONG", port=srv.port, timeout=2.0) as r:
                r.command("list")

    def test_works_from_worker_thread(self):
        # This is THE regression guard. Calling into mcrcon from a worker
        # thread (as `asyncio.to_thread` does) crashed with
        # "signal only works in main thread of the main interpreter" because
        # mcrcon used signal.SIGALRM for timeouts. Our replacement must
        # succeed here — a missing regression guard would let the bug
        # silently reappear in a dependency upgrade.
        srv = self._server({"say hi": ["OK"]})

        def run_command() -> str:
            with rcon_client.Rcon("127.0.0.1", "pw", port=srv.port, timeout=2.0) as r:
                return r.command("say hi")

        with ThreadPoolExecutor(max_workers=1) as ex:
            reply = ex.submit(run_command).result(timeout=5.0)
        self.assertEqual(reply, "OK")


if __name__ == "__main__":
    unittest.main()
