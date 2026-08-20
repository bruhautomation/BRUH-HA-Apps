"""The calibration reference track.

Eight sharp clicks at IRREGULAR offsets. Irregular is the load-bearing
word: a regular click train correlates equally well at every multiple of
its period, and a calibration that can be off by exactly one period is a
show that is confidently wrong. The uneven pattern has one alignment.

The track is deterministic — same bytes every time — because the analyzer
correlates against the pattern *as specified here*, never against a file
that might have been regenerated differently.
"""
from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

SAMPLE_RATE = 44100
DURATION_S = 13.0

# Click onsets, seconds from file start. Irregular by design (no common
# period), leading second of silence so the first click survives any
# player fade-in.
CLICK_TIMES_S = (1.00, 2.30, 3.90, 5.00, 6.80, 8.10, 9.70, 10.60)

# Each click: a short burst of tone with a hard attack and fast decay —
# sharp enough to localize, tonal enough to survive a phone microphone's
# processing.
CLICK_FREQ_HZ = 2000.0
CLICK_LENGTH_S = 0.02
CLICK_DECAY = 220.0


def render_samples(sample_rate: int = SAMPLE_RATE) -> list[float]:
    """The track as floats in [-1, 1]. Pure function of the constants."""
    total = int(DURATION_S * sample_rate)
    samples = [0.0] * total
    click_len = int(CLICK_LENGTH_S * sample_rate)
    for onset in CLICK_TIMES_S:
        start = int(onset * sample_rate)
        for i in range(click_len):
            t = i / sample_rate
            value = math.sin(2 * math.pi * CLICK_FREQ_HZ * t) * math.exp(-CLICK_DECAY * t)
            index = start + i
            if index < total:
                samples[index] += 0.9 * value
    return samples


def write_wav(path: Path, sample_rate: int = SAMPLE_RATE) -> Path:
    """16-bit mono WAV at `path`. Parents created; idempotent content."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    samples = render_samples(sample_rate)
    frames = b"".join(
        struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767))
        for s in samples
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(frames)
    return path


def describe() -> dict:
    return {
        "click_times_s": list(CLICK_TIMES_S),
        "duration_s": DURATION_S,
        "sample_rate": SAMPLE_RATE,
    }
