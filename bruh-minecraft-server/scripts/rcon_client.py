#!/usr/bin/env python3
"""Thread-safe RCON client for Minecraft.

Replaces the `mcrcon` PyPI package. `mcrcon` implements its connect-timeout
with `signal.SIGALRM`, which raises ``ValueError: signal only works in main
thread of the main interpreter`` when invoked from an asyncio worker thread
(`asyncio.to_thread(...)`), which is exactly how the ingress panel dispatches
RCON commands.

This client relies only on `socket.settimeout()` for timeouts and therefore
works safely from any thread. The wire format implements the full Source RCON
protocol (https://wiki.vg/RCON) including the Mojang-style two-packet trick
to detect the end of a fragmented response.
"""
from __future__ import annotations

import socket
import struct
from types import TracebackType
from typing import Optional, Type

# Packet types
SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0


class RconError(RuntimeError):
    """Transport, framing, or protocol-level RCON failure."""


class RconAuthError(RconError):
    """RCON refused the supplied password."""


class Rcon:
    """Synchronous, thread-safe RCON client.

    Usage::

        with Rcon("127.0.0.1", "password") as r:
            reply = r.command("list")
    """

    def __init__(
        self,
        host: str,
        password: str,
        port: int = 25575,
        timeout: float = 5.0,
    ) -> None:
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock: Optional[socket.socket] = None
        self._next_rid = 0

    def __enter__(self) -> "Rcon":
        self.connect()
        return self

    def __exit__(
        self,
        _exc_type: Optional[Type[BaseException]],
        _exc: Optional[BaseException],
        _tb: Optional[TracebackType],
    ) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def connect(self) -> None:
        if self._sock is not None:
            return
        # create_connection(..., timeout=...) uses socket.settimeout internally
        # (NOT signal.SIGALRM), so this is safe from worker threads.
        self._sock = socket.create_connection(
            (self.host, self.port), timeout=self.timeout,
        )
        # Enforce per-recv timeouts too so a hung server can't wedge the caller.
        self._sock.settimeout(self.timeout)
        self._authenticate()

    def close(self) -> None:
        if self._sock is None:
            return
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self._sock.close()
        finally:
            self._sock = None

    # ------------------------------------------------------------------
    # High-level API
    # ------------------------------------------------------------------
    def command(self, cmd: str) -> str:
        """Run a single server command and return the concatenated reply."""
        if self._sock is None:
            raise RconError("not connected")
        cmd_id = self._send(SERVERDATA_EXECCOMMAND, cmd)
        # Send a sentinel; the server echoes an empty packet with this id to
        # mark end-of-response. This handles multi-packet replies (e.g. very
        # long /list output) cleanly.
        end_id = self._send(SERVERDATA_RESPONSE_VALUE, "")
        parts: list[str] = []
        while True:
            resp_id, _resp_type, body = self._recv_packet()
            if resp_id == end_id:
                return "".join(parts)
            if resp_id == cmd_id:
                parts.append(body)
            # Unknown ids are ignored (server-side implementation quirks).

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _authenticate(self) -> None:
        auth_id = self._send(SERVERDATA_AUTH, self.password)
        resp_id, resp_type, _body = self._recv_packet()
        # Some servers emit an empty SERVERDATA_RESPONSE_VALUE packet before
        # the real auth response. Skip it.
        if resp_type == SERVERDATA_RESPONSE_VALUE:
            resp_id, resp_type, _body = self._recv_packet()
        if resp_type != SERVERDATA_AUTH_RESPONSE:
            raise RconError(f"unexpected auth response type {resp_type}")
        if resp_id == -1 or resp_id != auth_id:
            raise RconAuthError("RCON authentication failed (bad password?)")

    def _new_rid(self) -> int:
        self._next_rid = (self._next_rid + 1) & 0x7FFFFFFF
        return self._next_rid

    def _send(self, ptype: int, payload: str) -> int:
        assert self._sock is not None
        rid = self._new_rid()
        body = payload.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<ii", rid, ptype) + body
        header = struct.pack("<i", len(packet))
        self._sock.sendall(header + packet)
        return rid

    def _recvall(self, n: int) -> bytes:
        assert self._sock is not None
        data = bytearray()
        while len(data) < n:
            chunk = self._sock.recv(n - len(data))
            if not chunk:
                raise RconError("connection closed by server")
            data.extend(chunk)
        return bytes(data)

    def _recv_packet(self) -> tuple[int, int, str]:
        length = struct.unpack("<i", self._recvall(4))[0]
        # Minecraft caps response packets at ~4 KiB; give generous slack so
        # modded / plugin-heavy replies still fit.
        if length < 10 or length > 65536:
            raise RconError(f"invalid packet length {length}")
        body = self._recvall(length)
        rid, ptype = struct.unpack("<ii", body[:8])
        payload = body[8:-2].decode("utf-8", errors="replace")
        return rid, ptype, payload


__all__ = ["Rcon", "RconError", "RconAuthError"]
