#!/usr/bin/env python3
"""Boot the real BRight panel against a seeded house, on loopback.

Everything the panel reads is env-var driven, so this points every path at
a scratch directory, fills it with a plausible light map and a plausible
analyzed track, and runs the real `server.py`. No LIFX bulb is ever
contacted (the device registry is seeded from a file, and nothing here
presses Discover) and no Home Assistant is needed.

    python3 tests/manual/bright_demo_panel.py /tmp/bright-demo   # serves :8095
    node tests/manual/measure-effects.mjs                        # drives it

It exists for the same reason brAIn's demo_panel.py does: a UI claim you
have not seen a browser make is a UI claim.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent / "bright" / "panel"
DEMO = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/bright-demo")
PORT = os.environ.get("DEMO_PORT", "8095")

DEMO.mkdir(parents=True, exist_ok=True)
(DEMO / "shows").mkdir(exist_ok=True)
(DEMO / "cache").mkdir(exist_ok=True)

MEDIA = DEMO / "media"
MUSIC = MEDIA / "music"
MUSIC.mkdir(parents=True, exist_ok=True)

os.environ.update({
    "BRIGHT_STATE": str(DEMO),
    "BRIGHT_PANEL_PORT": PORT,
    "BRIGHT_SHARED": str(DEMO / "shared"),
    "BRIGHT_MEDIA": str(MEDIA),
    "BRIGHT_MUSIC_FOLDER": str(MUSIC),
    "ADDON_VERSION": "demo",
})

SERIALS = [f"d073d500{i:04d}" for i in range(1, 9)]
NAMES = ["Sofa left", "Sofa right", "Bookshelf", "Kitchen bar",
         "Hall down", "Stair strip", "Mantel candle", "Corner lamp"]
ROLES = ["lamp", "lamp", "lamp", "downlight", "downlight", "strip",
         "candle", "lamp"]

# The registry's own shape — {"devices": [...]} — not a serial-keyed map.
# A demo that seeds a shape the engine does not read is a demo that boots
# with no bulbs and a show compiled for nobody.
(DEMO / "lifx-devices.json").write_text(json.dumps({
    "devices": [
        {"serial": serial, "ip": f"192.168.1.{20 + i}", "label": name,
         "port": 56700,
         "rtt": {"p50_ms": 5.0 + i, "p95_ms": 9.0, "loss": 0.0}}
        for i, (serial, name) in enumerate(zip(SERIALS, NAMES))
    ],
}))

(DEMO / "light-map.json").write_text(json.dumps({
    "version": 1,
    "fixtures": [
        {"id": f"lifx-{serial}", "kind": "lifx", "serial": serial,
         "label": name, "role": role, "zone": "lounge" if i < 4 else "hall",
         "x": round(0.08 + i * 0.12, 2), "y": 0.3 + (i % 3) * 0.2}
        for i, (serial, name, role) in enumerate(zip(SERIALS, NAMES, ROLES))
    ] + [
        {"id": "switch.party_lights", "kind": "ha",
         "entity_id": "switch.party_lights", "label": "Party lights",
         "role": "party", "zone": "lounge", "x": 0.5, "y": 0.92},
    ],
}))

# One analyzed track, so the Shows tab and the "put it in a show" picker
# have something real to work on.
#
# The file is real and the hash is computed from it rather than made up:
# track identity is a content hash everywhere in this add-on, so a seeded
# analysis under an invented hash would be an analysis the library scan
# never finds — which is exactly the shape of bug a demo should not have.
TRACK_FILE = MUSIC / "demo.mp3"
TRACK_FILE.write_bytes(b"BRight demo track, not actually audio\n" * 512)

sys.path.insert(0, str(ROOT))
from analyzer import library  # noqa: E402

BPM = 124.0
BEATS = [round(60.0 / BPM * i, 3) for i in range(1, 380)]
TRACK_HASH = library.track_hash(TRACK_FILE)
track_dir = DEMO / "shows" / TRACK_HASH
track_dir.mkdir(parents=True, exist_ok=True)
duration = BEATS[-1] + 4
(track_dir / "analysis.json").write_text(json.dumps({
    "version": 1, "hash": TRACK_HASH, "bpm": BPM, "beats": BEATS,
    "downbeats": BEATS[::4], "onsets": BEATS, "brightness": 0.7,
    "file": str(TRACK_FILE),
    "tags": {"title": "Demo Track", "artist": "BRUH", "duration": duration},
    "sections": [
        {"start": 0.0, "end": 30.0, "kind": "intro", "energy": 0.2},
        {"start": 30.0, "end": 70.0, "kind": "mid", "energy": 0.55},
        {"start": 70.0, "end": 130.0, "kind": "peak", "energy": 0.95},
        {"start": 130.0, "end": duration, "kind": "outro", "energy": 0.2},
    ],
    "drops": [{"t": 70.0, "strength": 0.9}],
    "lyrics": {"synced": False, "lines": []},
    # The waveform, seeded rather than decoded. This demo has no ffmpeg and
    # its "track" is a few bytes on disk, so the panel's on-demand decode
    # path cannot run here — and it should not have to: every other field
    # in this analysis is fabricated too. The shape follows the sections
    # above (quiet intro, loud peak) so what is drawn agrees with what the
    # rest of the seeded analysis claims about the song.
    "envelope": [
        round(min(1.0, level * (0.55 + 0.45 * ((index * 37) % 11) / 10)), 3)
        for index, level in enumerate(
            [0.18] * 170 + [0.55] * 230 + [0.95] * 340 + [0.22] * 160)
    ],
}))

import server  # noqa: E402
from director import build as director_build  # noqa: E402

# Compile one show up front, so the editor has a script to open.
director_build.build_show(TRACK_HASH, server.ENGINE.devices,
                          server.ENGINE.source, "algorithmic")

if __name__ == "__main__":
    print(f"BRight demo panel on http://127.0.0.1:{PORT} (state in {DEMO})",
          flush=True)
    time.sleep(0)
    server.main()
