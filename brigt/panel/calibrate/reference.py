"""The calibration reference track.

Eight sharp clicks at IRREGULAR offsets. Irregular is the load-bearing
word: a regular click train correlates equally well at every multiple of
its period, and a calibration that can be off by exactly one period is a
show that is confidently wrong. The uneven pattern has one alignment.

The track is deterministic — same bytes every time — because the analyzer
correlates against the pattern *as specified here*, never against a file
that might have been regenerated differently.

Deterministic is also what makes `ensure()` cheap. Rendering the file is
half a million samples through a Python loop — 1.6s on a laptop, several
times that on the Pi this add-on mostly runs on — and the calibration
wizard used to pay it on *every* press of Play, inside the request. Same
constants in, same bytes out, so a file that is already the right length is
already the right file.
"""
from __future__ import annotations

import array
import io
import math
import sys
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


def wav_bytes(sample_rate: int = SAMPLE_RATE) -> bytes:
    """The track as a complete 16-bit mono WAV, in memory.

    `array` rather than `struct.pack` per sample: same int16s, same bytes
    (`test_the_two_packings_agree`), a fraction of the time. The byteswap is
    for a big-endian host — `array('h')` is native-endian and WAV is not.
    """
    samples = render_samples(sample_rate)
    pcm = array.array("h", (int(max(-1.0, min(1.0, s)) * 32767) for s in samples))
    if sys.byteorder == "big":
        pcm.byteswap()
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return buffer.getvalue()


def write_wav(path: Path, sample_rate: int = SAMPLE_RATE) -> Path:
    """16-bit mono WAV at `path`. Parents created; idempotent content.

    Raises OSError if the folder cannot be made or the file cannot be
    written — which is the interesting case on a real install, where /media
    belongs to root and the panel does not.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(wav_bytes(sample_rate))
    return path


# A canonical PCM WAV header is 44 bytes — RIFF (12) + fmt (24) + the data
# chunk's own header (8) — which is what `wave` writes for a file carrying
# no extra chunks. `expected_size` exists so `ensure` can answer "is this
# already the track?" with a stat instead of a render, and
# `test_the_expected_size_is_the_size_written` measures the arithmetic
# against a real file rather than trusting it.
WAV_HEADER_BYTES = 44


def expected_size(sample_rate: int = SAMPLE_RATE) -> int:
    """How many bytes a complete file measures."""
    return WAV_HEADER_BYTES + 2 * int(DURATION_S * sample_rate)


def ensure(path: Path, sample_rate: int = SAMPLE_RATE) -> Path:
    """`write_wav`, skipped when the file on disk is already this track.

    Length is the whole test, and it is enough: the content is a pure
    function of the constants above, so the only ways to hold a wrong file
    are to hold no file or a short one — a write cut off by a restart or a
    full disk. Both are a different length, and both are healed by
    rewriting, which is what the caller wanted anyway.
    """
    path = Path(path)
    try:
        if path.stat().st_size == expected_size(sample_rate):
            return path
    except OSError:
        pass
    return write_wav(path, sample_rate)


def describe() -> dict:
    return {
        "click_times_s": list(CLICK_TIMES_S),
        "duration_s": DURATION_S,
        "sample_rate": SAMPLE_RATE,
    }
