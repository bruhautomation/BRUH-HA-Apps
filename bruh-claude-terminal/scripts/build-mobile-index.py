#!/usr/bin/env python3
"""Inject BRUH's mobile toolbar + iOS dictation diff-fix into ttyd's HTML.

Background (see PR discussion / CHANGELOG 1.17.1):

ttyd 1.7.4 on Alpine 3.19 embeds its *entire* frontend — JavaScript and CSS
— inline into a single gzipped HTML blob compiled into the binary as a C
byte array. `ttyd --index <path>` replaces that blob at `/` with a file we
supply, but ttyd does NOT serve separate `/main.js` / `/index.css` /
`favicon.png` paths; everything the browser needs is already in the HTML.

The two earlier attempts got this wrong:

- 1.16.0 hard-coded <script src="inline.js"> + <div id="terminal">. The
  script path didn't exist, the mount ID didn't match, React never
  rendered — black screen.
- 1.17.0 probed ttyd, extracted its <script> / <link> tags, and spliced
  them into our own template. The extracted "scripts" were really inline
  bundles (no src attribute) so referencing them gave us duplicate inline
  code, and React renders into `document.body` directly — wiping any
  DOM we staged. The toolbar vanished.

This version takes the opposite approach: treat ttyd's served HTML as
opaque and inject our stuff ALONGSIDE it, not INSTEAD of it.

  1. Start a scratch ttyd on a loopback-only port.
  2. GET `/` with Accept-Encoding: identity so ttyd hands back the
     uncompressed fully-inlined HTML.
  3. Splice `ttyd-assets/inject.html` in just before `</head>`. That
     position lets our WebSocket wrapper replace window.WebSocket BEFORE
     ttyd's inline bundle runs (inline scripts run in document order), so
     the toolbar can sendInput() through ttyd's own socket. Our script
     also registers a capture-phase `input` listener on `document` that
     runs before xterm's capture-phase listener on the textarea, which is
     where the iOS dictation diff-fix lives.
  4. Write the merged file for `ttyd --index` to serve.

If any step fails `run.sh` logs the reason and launches stock ttyd.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

INJECT_SNIPPET_PATH = Path("/opt/ttyd-assets/inject.html")
OUTPUT_PATH = Path("/opt/ttyd-assets/index.html")

PROBE_PORT = 17681
PROBE_HOST = "127.0.0.1"
PROBE_STARTUP_TRIES = 50
PROBE_STARTUP_DELAY_S = 0.2
PROBE_HTTP_TIMEOUT_S = 1.5


def probe_ttyd_html() -> tuple[str | None, str]:
    """Run a scratch ttyd on loopback, fetch its default HTML, kill it.

    Returns (html, error_detail). On success html is non-None; on failure
    error_detail is a short string describing what went wrong so the caller
    can surface it to the add-on log.
    """
    proc = subprocess.Popen(
        [
            "ttyd",
            "--port", str(PROBE_PORT),
            "--interface", PROBE_HOST,
            "sleep", "60",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        for _ in range(PROBE_STARTUP_TRIES):
            if proc.poll() is not None:
                _, err = proc.communicate(timeout=1)
                detail = err.decode(errors="replace").strip()[:500] or "(no stderr)"
                return None, f"ttyd exited early: {detail}"

            try:
                req = urllib.request.Request(
                    f"http://{PROBE_HOST}:{PROBE_PORT}/",
                    headers={"Accept-Encoding": "identity"},
                )
                with urllib.request.urlopen(req, timeout=PROBE_HTTP_TIMEOUT_S) as resp:
                    return resp.read().decode("utf-8", errors="replace"), ""
            except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
                time.sleep(PROBE_STARTUP_DELAY_S)

        return None, f"no response from ttyd after {PROBE_STARTUP_TRIES} tries"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            try:
                proc.wait(timeout=2)
            except Exception:
                pass


def build() -> int:
    if not INJECT_SNIPPET_PATH.exists():
        print(
            f"[bruh-mobile-ui] injection snippet missing at {INJECT_SNIPPET_PATH}",
            file=sys.stderr,
        )
        return 1

    html, err = probe_ttyd_html()
    if not html:
        print(f"[bruh-mobile-ui] probe failed: {err}", file=sys.stderr)
        return 1

    lower = html.lower()
    head_close = lower.rfind("</head>")
    if head_close < 0:
        print(
            f"[bruh-mobile-ui] probed HTML has no </head> "
            f"(len={len(html)}, preview={html[:120]!r})",
            file=sys.stderr,
        )
        return 1

    snippet = INJECT_SNIPPET_PATH.read_text()
    merged = html[:head_close] + snippet + html[head_close:]
    OUTPUT_PATH.write_text(merged)

    print(
        f"[bruh-mobile-ui] built {OUTPUT_PATH} "
        f"(ttyd base: {len(html)} bytes, injected: {len(snippet)} bytes)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(build())
