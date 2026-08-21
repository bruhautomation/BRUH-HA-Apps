"""Audio in: ffmpeg to mono PCM, mutagen for tags.

ffmpeg because it reads everything anyone's music folder actually
contains; a subprocess because that is the supported way to use it and a
crash in a codec stays out of the panel's process.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

# Analysis rate. 22050 keeps everything the beat tracker needs (nothing
# rhythmic lives above 11kHz) at half the memory and FFT cost.
SAMPLE_RATE = 22050


def pcm(path: Path, sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """The whole track as float32 mono at `sample_rate`."""
    command = [
        "ffmpeg", "-v", "error",
        "-i", str(path),
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "s16le",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, timeout=300)
    if result.returncode != 0 or not result.stdout:
        tail = result.stderr.decode(errors="replace").strip().splitlines()
        raise ValueError(f"ffmpeg could not decode {path.name}: "
                         f"{tail[-1] if tail else 'no output'}")
    return np.frombuffer(result.stdout, dtype="<i2").astype(np.float32) / 32768.0


def pcm_window(path: Path, start_s: float, duration_s: float,
               sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """A slice of the track as float32 mono — what auto-sync compares the
    phone's recording against. `-ss` before `-i` is the fast seek, and with
    a re-encode (which raw PCM out is) ffmpeg decodes from the nearest
    point and trims to the exact time, so the slice starts where asked."""
    command = [
        "ffmpeg", "-v", "error",
        "-ss", f"{max(0.0, start_s):.3f}",
        "-t", f"{max(0.1, duration_s):.3f}",
        "-i", str(path),
        "-ac", "1",
        "-ar", str(sample_rate),
        "-f", "s16le",
        "-",
    ]
    result = subprocess.run(command, capture_output=True, timeout=60)
    if result.returncode != 0 or not result.stdout:
        tail = result.stderr.decode(errors="replace").strip().splitlines()
        raise ValueError(f"ffmpeg could not decode {path.name}: "
                         f"{tail[-1] if tail else 'no output'}")
    return np.frombuffer(result.stdout, dtype="<i2").astype(np.float32) / 32768.0


def tags(path: Path) -> dict:
    """title/artist/album/duration, best-effort — lyrics lookup wants them,
    nothing else depends on them."""
    info = {"title": path.stem, "artist": "", "album": "", "duration": None}
    try:
        import mutagen
        parsed = mutagen.File(str(path), easy=True)
        if parsed is not None:
            for key in ("title", "artist", "album"):
                values = parsed.tags.get(key) if parsed.tags else None
                if values:
                    info[key] = str(values[0])
            if parsed.info is not None and getattr(parsed.info, "length", None):
                info["duration"] = round(float(parsed.info.length), 2)
    except Exception:  # noqa: BLE001 — tags are decorative; the track is not
        pass
    return info
