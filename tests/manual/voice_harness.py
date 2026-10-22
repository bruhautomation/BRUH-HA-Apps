"""A stand-in for brAIn's panel and for Claude Code, for measure-terminal-voice.mjs.

It serves the real voice routes (brain/panel/voice_mic.py) and a terminal
page carrying the real inject.html, and it plays Claude Code's part the way
Claude Code plays it in voice mode's tap setting: a space typed into the
terminal starts the real `scripts/brain-arecord.py` with the CLI's own argv,
and the next space SIGTERMs it. Whatever that stand-in wrote to stdout is
what Claude Code would have sent to its transcriber, and `/test/result`
hands it back for the browser test to measure.

    python3 tests/manual/voice_harness.py <port> <claude-config-dir>
"""

from __future__ import annotations

import array
import math
import os
import subprocess
import sys
import threading
from pathlib import Path

from aiohttp import web

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "brain" / "panel"))

import voice_mic  # noqa: E402

ARECORD = ROOT / "brain" / "scripts" / "brain-arecord.py"
CLI_ARGV = ["-f", "S16_LE", "-r", "16000", "-c", "1", "-t", "raw", "-q", "-"]
INJECT = (ROOT / "brain" / "ttyd-assets" / "inject.html").read_text()

# The ttyd socket, faked in-page: what the terminal page types reaches
# /test/typed. Any other socket (the mic's) is a real WebSocket.
FRAME = """<!doctype html><html><head>
<meta name="viewport" content="width=device-width,initial-scale=1">
<script>
window.__typed = [];
var RealWS = window.WebSocket;
function FakeWS(url, p) {
  if (String(url).indexOf('/api/') !== -1) return p === undefined ? new RealWS(url) : new RealWS(url, p);
  this.url = url; this.readyState = 1;
}
FakeWS.prototype.send = function (buf) {
  var s = new TextDecoder().decode(buf);
  if (s[0] !== '0') return;
  window.__typed.push(s.slice(1));
  fetch('/test/typed', { method: 'POST', body: s.slice(1) });
};
FakeWS.prototype.addEventListener = function () {};
FakeWS.CONNECTING = 0; FakeWS.OPEN = 1; FakeWS.CLOSING = 2; FakeWS.CLOSED = 3;
window.WebSocket = FakeWS;
</script>
%INJECT%
<style>html,body{margin:0;height:100%} #terminal-container{height:100%}
.terminal{height:calc(100% - 10px);background:#111}
.xterm-helper-textarea{position:absolute;left:-9999px;top:0;width:10px;height:10px}</style>
</head><body><div id="terminal-container"><div class="terminal xterm">
<textarea class="xterm-helper-textarea"></textarea><div class="xterm-viewport"></div></div></div>
<script>new WebSocket('ws://' + location.host + '/terminal/ws');</script>
</body></html>"""


class Cli:
    """Claude Code in tap mode: space starts arecord, space stops it."""

    def __init__(self, url: str) -> None:
        self.url = url
        self.proc: subprocess.Popen | None = None
        self.out = b""
        self.spaces = 0

    def space(self) -> None:
        self.spaces += 1
        if self.proc is None:
            env = dict(os.environ, BRAIN_PANEL_URL=self.url)
            self.proc = subprocess.Popen(
                [sys.executable, str(ARECORD), *CLI_ARGV],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)
            # Read as it arrives, the way the CLI does. Left in the pipe,
            # 64 KB (two seconds) fills it and arecord blocks on write.
            self.chunks = []
            self.reader = threading.Thread(target=self._read, args=(self.proc,),
                                           daemon=True)
            self.reader.start()
        else:
            self.proc.terminate()
            self.proc.wait(timeout=10)
            self.reader.join(timeout=10)
            self.out = b"".join(self.chunks)
            self.code = self.proc.returncode
            self.proc = None

    def _read(self, proc):
        while True:
            chunk = proc.stdout.read1(4096)
            if not chunk:
                return
            self.chunks.append(chunk)

    def result(self) -> dict:
        samples = array.array("h")
        samples.frombytes(self.out[: len(self.out) // 2 * 2])
        rms = math.sqrt(sum(s * s for s in samples) / len(samples)) if samples else 0.0
        return {"bytes": len(self.out), "seconds": len(samples) / 16000,
                "rms": rms, "spaces": self.spaces,
                "running": self.proc is not None,
                "code": getattr(self, "code", None)}


def main() -> None:
    port = int(sys.argv[1])
    os.environ["CLAUDE_CONFIG_DIR"] = sys.argv[2]
    cli = Cli(f"http://127.0.0.1:{port}")
    app = web.Application()
    voice_mic.setup(app)
    hub = app[voice_mic.HUB_KEY]
    fed = {"bytes": 0}
    original_feed = hub.feed

    def feed(chunk):
        fed["bytes"] += len(chunk)
        original_feed(chunk)

    hub.feed = feed

    async def frame(_request):
        return web.Response(text=FRAME.replace("%INJECT%", INJECT),
                            content_type="text/html")

    async def typed(request):
        text = await request.text()
        if text == " ":
            cli.space()
        return web.Response(text="ok")

    async def result(_request):
        # What the page sent, beside what the CLI read: a gap between the
        # two is audio lost in the middle rather than never captured.
        return web.json_response(dict(cli.result(), page_seconds=fed["bytes"] / 32000))

    app.router.add_get("/terminal/", frame)
    app.router.add_post("/test/typed", typed)
    app.router.add_get("/test/result", result)
    web.run_app(app, host="127.0.0.1", port=port, print=lambda *_: print("ready", flush=True))


if __name__ == "__main__":
    main()
