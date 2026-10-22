#!/usr/bin/env python3
"""`arecord`, for a container whose microphone is somebody's phone.

Installed as /usr/local/bin/arecord. Claude Code's `/voice` records with
`arecord -f S16_LE -r 16000 -c 1 -t raw -q -` when there is no sound card
(read off the 2.1.307 bundle), reads raw PCM from stdout, and stops the
recording with SIGTERM. This answers the same three calls:

* ``arecord --version`` — the CLI's "is it installed" check;
* ``arecord ... /dev/null`` — its probe, which only asks that the command
  runs; it exits 0 at once;
* ``arecord ... -`` — the recording: the panel's loopback-only
  ``/api/voice/listen`` stream, which carries what the terminal page's
  mic button is sending, written to stdout until the page stops or the
  CLI sends SIGTERM.

Any other format is refused rather than resampled: the page sends 16 kHz
mono S16LE and nothing else, and audio played back at the wrong rate is a
transcript of noise that reads like a fault in the model.
"""

from __future__ import annotations

import os
import signal
import sys
import urllib.error
import urllib.request

PANEL_URL = os.environ.get("BRAIN_PANEL_URL", "http://127.0.0.1:8099")
VERSION = "arecord: brAIn microphone bridge (the phone's mic, from the terminal page)"
CHUNK = 3200  # 100 ms of 16 kHz mono S16LE

FLAGS_WITH_VALUE = {
    "-f", "--format", "-r", "--rate", "-c", "--channels", "-t", "--file-type",
    "-D", "--device", "-d", "--duration", "-B", "--buffer-time",
    "-F", "--period-time", "--buffer-size", "--period-size", "-s",
    "--samples",
}
WANTED = {"format": "S16_LE", "rate": "16000", "channels": "1", "type": "raw"}
ALIASES = {
    "-f": "format", "--format": "format", "-r": "rate", "--rate": "rate",
    "-c": "channels", "--channels": "channels", "-t": "type",
    "--file-type": "type",
}


def parse(argv: list[str]) -> tuple[dict, list[str]]:
    opts: dict[str, str] = {}
    files: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if "=" in arg and arg.startswith("--"):
            name, value = arg.split("=", 1)
            if name in ALIASES:
                opts[ALIASES[name]] = value
            i += 1
            continue
        if arg in FLAGS_WITH_VALUE:
            value = argv[i + 1] if i + 1 < len(argv) else ""
            if arg in ALIASES:
                opts[ALIASES[arg]] = value
            i += 2
            continue
        if arg == "-" or not arg.startswith("-"):
            files.append(arg)
        i += 1
    return opts, files


def wrong_format(opts: dict) -> str | None:
    for key, want in WANTED.items():
        got = opts.get(key)
        if got is not None and got.upper() != want.upper():
            return (f"arecord: only {WANTED['rate']} Hz mono {WANTED['format']} "
                    f"raw is available here (asked for {key} {got})")
    return None


def record(out) -> int:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        resp = opener.open(f"{PANEL_URL}/api/voice/listen", timeout=15)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        print(f"arecord: {body or exc}", file=sys.stderr)
        return 1
    except OSError as exc:
        print(f"arecord: the brAIn panel is not answering ({exc})",
              file=sys.stderr)
        return 1
    with resp:
        while True:
            chunk = resp.read1(CHUNK) if hasattr(resp, "read1") else resp.read(CHUNK)
            if not chunk:
                return 0
            try:
                out.write(chunk)
                out.flush()
            except BrokenPipeError:
                return 0


def main(argv: list[str]) -> int:
    if any(a in ("--version", "-V") for a in argv):
        print(VERSION)
        return 0
    if any(a in ("-l", "--list-devices", "-L", "--list-pcms") for a in argv):
        return 0
    opts, files = parse(argv)
    problem = wrong_format(opts)
    if problem:
        print(problem, file=sys.stderr)
        return 1
    target = files[-1] if files else "-"
    if target != "-":
        # The CLI's probe records to /dev/null and only asks that it runs.
        return 0
    # SIGTERM is how the CLI ends a recording, and ending is not a failure.
    signal.signal(signal.SIGTERM, lambda *_: os._exit(0))
    signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    return record(sys.stdout.buffer)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
