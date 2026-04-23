#!/usr/bin/env python3
"""Build a custom ttyd index.html with a mobile toolbar and iOS dictation fix.

ttyd's compiled frontend is an implementation detail. The bundle filename can
change between ttyd versions (plain `main.js`, hashed `main.[hash].js`,
`index.js`, or a `type="module"` entry). Instead of hard-coding the filename
and shipping something that breaks on the next ttyd bump, this script starts
ttyd on a scratch loopback port, fetches whatever HTML it serves at `/`, pulls
out its `<link>` / `<style>` / `<script>` tags, and splices them into our
mobile template so the React terminal mounts correctly.

If the probe fails for any reason, `run.sh` falls back to ttyd's stock UI.
"""

from __future__ import annotations

import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from bs4 import BeautifulSoup  # type: ignore[import-untyped]

TEMPLATE_PATH = Path("/opt/ttyd-assets/index.template.html")
OUTPUT_PATH = Path("/opt/ttyd-assets/index.html")
PROBE_PORT = 17681
PROBE_HOST = "127.0.0.1"
PROBE_STARTUP_TRIES = 25
PROBE_STARTUP_DELAY_S = 0.2


def probe_ttyd_default_html() -> str | None:
    """Start ttyd locally, fetch its default HTML, return it, kill ttyd."""
    proc = subprocess.Popen(
        [
            "ttyd",
            "--port", str(PROBE_PORT),
            "--interface", PROBE_HOST,
            "sleep", "60",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        for _ in range(PROBE_STARTUP_TRIES):
            try:
                with urllib.request.urlopen(
                    f"http://{PROBE_HOST}:{PROBE_PORT}/", timeout=1.0
                ) as resp:
                    return resp.read().decode("utf-8", errors="replace")
            except Exception:
                time.sleep(PROBE_STARTUP_DELAY_S)
        return None
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def build() -> int:
    if not TEMPLATE_PATH.exists():
        print(f"[bruh-mobile-ui] template missing at {TEMPLATE_PATH}", file=sys.stderr)
        return 1

    stock_html = probe_ttyd_default_html()
    if not stock_html:
        print("[bruh-mobile-ui] could not probe ttyd default HTML", file=sys.stderr)
        return 1

    soup = BeautifulSoup(stock_html, "html.parser")
    body_scripts = soup.body.find_all("script") if soup.body else []
    head_assets = soup.head.find_all(["link", "style"]) if soup.head else []

    if not body_scripts:
        print("[bruh-mobile-ui] no <script> tags in ttyd HTML body", file=sys.stderr)
        return 1

    head_html = "\n    ".join(str(t) for t in head_assets)
    body_html = "\n    ".join(str(t) for t in body_scripts)

    rendered = (
        TEMPLATE_PATH.read_text()
        .replace("__TTYD_HEAD_ASSETS__", head_html)
        .replace("__TTYD_BODY_SCRIPTS__", body_html)
    )
    OUTPUT_PATH.write_text(rendered)

    srcs = [s.get("src", "(inline)") for s in body_scripts]
    print(
        f"[bruh-mobile-ui] built {OUTPUT_PATH} "
        f"({len(body_scripts)} scripts: {srcs}, {len(head_assets)} head assets)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(build())
