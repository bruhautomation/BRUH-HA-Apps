"""The printer's camera, on the LAN, on demand.

Two kinds of camera, and the printer's model (or the `ipcam.rtsp_url` it
reports) says which:

* P1 and A1 send JPEG frames over TLS on port 6000. The session opens with
  one 80-byte packet — a 16-byte header, the user `bblp` and the access code,
  each padded to 32 bytes — and then every frame arrives as a 16-byte header
  whose first four bytes are the JPEG's length, followed by the JPEG.
* X1, P2S and H2 serve RTSPS on port 322 (`/streaming/live/1`), and only
  with "LAN mode live view" switched on in the printer's own settings.
  ffmpeg reads it and hands back JPEGs, two a second.

A frame is kept only when it is a whole JPEG (start and end markers both
there): a frame cut short decodes with its missing rows painted in, a green
or grey band across the picture. And a camera that encodes 1080 rows as
1088 and says so in the frame's header is told its real height (`fit`), so
the eight rows that are not the picture, a green bar along the bottom when
decoded, are cropped by the decoder rather than shown.

A camera is opened when somebody looks and closed when nobody has for
IDLE_S: a stream nobody watches is the printer's CPU and the LAN's
bandwidth for nothing. The newest frame is all that is kept.
"""
from __future__ import annotations

import os
import shutil
import socket
import ssl
import struct
import subprocess
import threading
import time
from pathlib import Path

JPEG_PORT = 6000
RTSP_PORT = 322
IDLE_S = 45
CONNECT_TIMEOUT = 8
FRAME_TIMEOUT = 15
MAX_FRAME = 4 * 1024 * 1024
RTSP_FPS = 2
SOI, EOI = b"\xff\xd8", b"\xff\xd9"


def auth_packet(access_code: str, user: str = "bblp") -> bytes:
    """The 80 bytes a P1/A1 camera wants before it sends a frame."""
    def pad(text: str) -> bytes:
        raw = str(text).encode("ascii", "replace")[:32]
        return raw + b"\x00" * (32 - len(raw))
    return struct.pack("<IIII", 0x40, 0x3000, 0, 0) + pad(user) + pad(access_code)


def read_exact(sock, n: int) -> bytes:
    chunks, got = [], 0
    while got < n:
        chunk = sock.recv(min(65536, n - got))
        if not chunk:
            raise ConnectionError("The camera closed the connection.")
        chunks.append(chunk)
        got += len(chunk)
    return b"".join(chunks)


def read_frame(sock) -> bytes:
    """One JPEG off a port-6000 stream."""
    header = read_exact(sock, 16)
    size = struct.unpack("<I", header[:4])[0]
    if not 0 < size <= MAX_FRAME:
        raise ConnectionError(f"The camera sent a frame header it cannot have meant ({size} bytes).")
    frame = read_exact(sock, size)
    if not frame.startswith(SOI):
        raise ConnectionError("The camera sent something that is not a JPEG.")
    return frame


def whole(frame: bytes) -> bool:
    """A JPEG with both its ends: the start marker, and the end marker
    (a camera may pad after it with zero bytes)."""
    return (isinstance(frame, (bytes, bytearray)) and frame.startswith(SOI)
            and bytes(frame).rstrip(b"\x00").endswith(EOI))


# Start-of-frame markers carry the picture's height and width; C4, C8 and
# CC share the range and are something else.
_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def fit(frame: bytes) -> bytes:
    """The frame with a padded height corrected: a 16:9 picture whose header
    says eight rows more than 16:9 (1920 x 1088) is a 1080-row picture in
    whole 16-row blocks, and its header is told 1080. Only the two height
    bytes change; anything else, or anything unreadable, is left as it was."""
    i = 2
    data = bytes(frame)
    while i + 9 <= len(data) and data[i] == 0xFF:
        marker = data[i + 1]
        if marker == 0xDA:  # start of scan: no frame header before it
            return frame
        length = struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in _SOF:
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            if height > 8 and (height - 8) * 16 == width * 9:
                return data[:i + 5] + struct.pack(">H", height - 8) + data[i + 7:]
            return frame
        if length < 2:
            return frame
        i += 2 + length
    return frame


def split_jpegs(buffer: bytearray) -> list[bytes]:
    """Whole JPEGs out of an MJPEG byte stream, removing them from the buffer."""
    out = []
    while True:
        start = buffer.find(SOI)
        if start < 0:
            buffer.clear()
            return out
        end = buffer.find(EOI, start + 2)
        if end < 0:
            del buffer[:start]
            return out
        out.append(bytes(buffer[start:end + 2]))
        del buffer[:end + 2]


def rtsp_url(host: str, access_code: str, reported: str | None = None) -> str:
    """The stream's address with the credentials in it."""
    path = "/streaming/live/1"
    if reported and reported.lower().startswith("rtsp"):
        tail = reported.split("://", 1)[-1]
        path = "/" + tail.split("/", 1)[1] if "/" in tail else path
    return f"rtsps://bblp:{access_code}@{host}:{RTSP_PORT}{path}"


class Camera:
    """One printer's camera: a thread while somebody is looking."""

    def __init__(self, host: str, access_code: str, kind: str, rtsp: str | None = None,
                 mirror: Path | None = None, mirror_wanted=None):
        self.host, self.code, self.kind, self.rtsp = host, access_code, kind, rtsp
        self.frame: bytes | None = None
        self.frame_at = 0.0
        self.error = ""
        self.wanted_at = 0.0
        self.mirror, self.mirror_wanted = mirror, mirror_wanted
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None

    # -- the panel's half --------------------------------------------------
    def want(self) -> None:
        """Somebody is looking: keep (or start) the stream."""
        self.wanted_at = time.time()
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, daemon=True,
                                                name=f"camera-{self.host}")
                self._thread.start()

    def latest(self, wait: float = 0.0) -> bytes | None:
        self.want()
        deadline = time.time() + wait
        while self.frame is None and time.time() < deadline and not self.error:
            time.sleep(0.1)
        return self.frame

    def state(self) -> dict:
        age = time.time() - self.frame_at if self.frame_at else None
        return {"kind": self.kind, "streaming": bool(self._thread and self._thread.is_alive()),
                "frame_age_s": round(age, 1) if age is not None else None, "error": self.error}

    def stop(self) -> None:
        self.wanted_at = 0.0
        proc = self._proc
        if proc is not None and proc.poll() is None:
            proc.kill()

    # -- the thread --------------------------------------------------------
    def _idle(self) -> bool:
        if time.time() - self.wanted_at < IDLE_S:
            return False
        return not (self.mirror_wanted and self.mirror_wanted())

    def _got(self, frame: bytes) -> None:
        # A frame cut short is dropped and the last whole one stays.
        if not whole(frame):
            return
        frame = fit(frame)
        self.frame, self.frame_at, self.error = frame, time.time(), ""
        if self.mirror is not None and self.mirror_wanted and self.mirror_wanted():
            try:
                self.mirror.parent.mkdir(parents=True, exist_ok=True)
                scratch = self.mirror.with_name(self.mirror.name + ".tmp")
                scratch.write_bytes(frame)
                os.replace(scratch, self.mirror)
            except OSError:
                pass  # Home Assistant's copy is a convenience; the panel still has the frame

    def _run(self) -> None:
        backoff = 2.0
        while not self._idle():
            try:
                if self.kind == "disabled":
                    self.error = ("The camera is off for the LAN: turn on LAN mode live view in "
                                  "the printer's own settings (Settings, LAN Only Liveview).")
                    return
                if self.kind == "rtsp":
                    self._rtsp()
                else:
                    self._jpeg()
                backoff = 2.0
            except (OSError, ssl.SSLError, ConnectionError, ValueError) as exc:
                self.error = self._explain(exc)
            if self._idle():
                break
            time.sleep(backoff)
            backoff = min(backoff * 2, 30)

    def _explain(self, exc: Exception) -> str:
        text = str(exc) or exc.__class__.__name__
        if isinstance(exc, ConnectionRefusedError):
            port = RTSP_PORT if self.kind == "rtsp" else JPEG_PORT
            return (f"The printer refused the camera connection on port {port}. "
                    + ("Turn on LAN mode live view in the printer's settings."
                       if self.kind == "rtsp" else "Is the printer in LAN mode?"))
        if isinstance(exc, socket.timeout):
            return "The camera did not send a picture in time."
        return f"The camera stopped: {text}"

    def _jpeg(self) -> None:
        context = ssl.create_default_context()
        context.minimum_version = ssl.TLSVersion.TLSv1_2
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        raw = socket.create_connection((self.host, JPEG_PORT), timeout=CONNECT_TIMEOUT)
        with context.wrap_socket(raw, server_hostname=self.host) as sock:
            sock.settimeout(FRAME_TIMEOUT)
            sock.sendall(auth_packet(self.code))
            while not self._idle():
                self._got(read_frame(sock))

    def _rtsp(self) -> None:
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            raise ValueError("ffmpeg is not installed, so an RTSP camera cannot be read.")
        url = rtsp_url(self.host, self.code, self.rtsp)
        proc = subprocess.Popen(
            [ffmpeg, "-nostdin", "-loglevel", "error", "-rtsp_transport", "tcp",
             "-i", url, "-an", "-vf", f"fps={RTSP_FPS},scale='min(1280,iw)':-2",
             "-f", "image2pipe", "-c:v", "mjpeg", "-q:v", "6", "pipe:1"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL)
        self._proc = proc
        buffer = bytearray()
        last = time.time()
        try:
            while not self._idle():
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(65536)
                if not chunk:
                    break
                buffer.extend(chunk)
                if len(buffer) > 2 * MAX_FRAME:
                    buffer.clear()
                for frame in split_jpegs(buffer):
                    self._got(frame)
                    last = time.time()
                if time.time() - last > FRAME_TIMEOUT:
                    raise ConnectionError("The camera stream stopped sending pictures.")
        finally:
            if proc.poll() is None:
                proc.kill()
            try:
                err = proc.stderr.read().decode(errors="replace").strip().splitlines()
            except (OSError, ValueError):
                err = []
            proc.wait(timeout=5)
            self._proc = None
        if not self._idle():
            reason = err[-1][:200].replace(self.code, "****") if err else "it ended"
            raise ConnectionError(f"ffmpeg could not read the stream: {reason}")
