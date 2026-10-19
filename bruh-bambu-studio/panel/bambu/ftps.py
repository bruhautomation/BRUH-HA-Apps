"""The printer's storage, over implicit FTPS on port 990.

Bambu printers serve their SD card (or internal storage) as FTP wrapped in
TLS from the first byte — IMPLICIT FTPS — with the user `bblp` and the
access code as the password. Python's ftplib only speaks the explicit kind
(plain FTP, then AUTH TLS), so the control socket is wrapped here as it is
connected.

Two details are the difference between this working and hanging:

* The data channel must RESUME the control channel's TLS session. The
  printer's server refuses a data connection that negotiates a new one,
  which ftplib does by default — `ntransfercmd` passes the session through.
* An upload must not `unwrap()` the data socket at the end. ftplib's own
  `storbinary` does, and the printer never answers the close_notify, so a
  finished upload hangs until the timeout. `upload` closes the socket
  instead and then reads the server's 226.

The printer's certificate is self-signed per device, so it is not verified
— the access code is what authenticates the session, the same arrangement
Bambu Studio itself makes on a LAN.
"""
from __future__ import annotations

import ftplib
import os
import posixpath
import re
import socket
import ssl

PORT = 990
USER = "bblp"
TIMEOUT = 30
CHUNK = 64 * 1024

# A name on the printer's storage. Plain, flat and short: the printer's
# own file list and its screen both choke on anything clever.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._()+-]{0,120}$")


def _context() -> ssl.SSLContext:
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


class ImplicitFTPS(ftplib.FTP_TLS):
    """FTP_TLS that wraps the control socket on connect."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, context=_context(), **kwargs)
        self._sock = None

    @property
    def sock(self):
        return self._sock

    @sock.setter
    def sock(self, value):
        if value is not None and not isinstance(value, ssl.SSLSocket):
            value = self.context.wrap_socket(value, server_hostname=self.host)
        self._sock = value

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn, server_hostname=self.host, session=self.sock.session)
        return conn, size


def safe_name(name: str) -> str:
    base = posixpath.basename(str(name or "").replace("\\", "/"))
    if not SAFE_NAME.match(base) or base in (".", ".."):
        raise ValueError(
            f"{base!r} is not a name the printer can store. Use letters, "
            f"digits, spaces, dots, dashes and underscores.")
    return base


class Storage:
    """One session against one printer's storage."""

    def __init__(self, host: str, access_code: str, *, port: int = PORT,
                 timeout: int = TIMEOUT):
        self.host, self.code, self.port, self.timeout = host, access_code, port, timeout
        self.ftp: ImplicitFTPS | None = None

    def __enter__(self) -> "Storage":
        ftp = ImplicitFTPS(timeout=self.timeout)
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login(USER, self.code)
        ftp.prot_p()
        self.ftp = ftp
        return self

    def __exit__(self, *exc):
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except (OSError, EOFError, ftplib.Error):
                self.ftp.close()
        self.ftp = None

    def listing(self, path: str = "/") -> list[dict]:
        rows: list[str] = []
        self.ftp.retrlines(f"LIST {path}", rows.append)
        out = []
        for row in rows:
            parts = row.split(None, 8)
            if len(parts) < 9:
                continue
            name = parts[8]
            if name in (".", ".."):
                continue
            out.append({"name": name, "dir": row.startswith("d"),
                        "size": int(parts[4]) if parts[4].isdigit() else None})
        return out

    def upload(self, local_path: str, name: str, progress=None) -> int:
        name = safe_name(name)
        total = os.path.getsize(local_path)
        sent = 0
        self.ftp.voidcmd("TYPE I")
        conn = self.ftp.transfercmd(f"STOR {name}")
        try:
            with open(local_path, "rb") as handle:
                while True:
                    block = handle.read(CHUNK)
                    if not block:
                        break
                    conn.sendall(block)
                    sent += len(block)
                    if progress:
                        progress(sent, total)
        finally:
            # No unwrap(): the printer never answers a close_notify.
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass  # already closed by the far end
            conn.close()
        self.ftp.voidresp()
        return sent

    def delete(self, name: str) -> None:
        self.ftp.delete(safe_name(name))
