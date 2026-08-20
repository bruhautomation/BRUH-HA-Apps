"""Find the reference click track inside a phone-microphone recording.

The phone records the room while the media player plays the reference.
Where the clicks landed in the recording, versus when the play command was
issued, IS the output latency — the number no API reports and AirPlay
inflates by ~2 seconds.

Method: reduce the recording to an onset-strength envelope (energy rises,
at ~200Hz resolution), build the same-rate impulse train the reference
defines, and FFT cross-correlate. The reference's clicks are irregular on
purpose, so the correlation has one honest peak; its height against the
noise floor is reported as confidence, because a recording of a silent
room correlates with *something* and the wizard must not store that.
"""
from __future__ import annotations

import io
import wave

import numpy as np

from . import reference

# Envelope resolution: ~5ms bins. Latency answers are wanted to ~10ms;
# finer costs correlation length for nothing a phone mic can resolve. The
# NOMINAL rate — the true rate is sample_rate / hop and every timestamp is
# computed from that, because 44100/220 is 200.45Hz and the 0.23% stretch
# is 9ms of systematic error by the end of the click track.
ENV_RATE_HZ = 200


def env_hop(sample_rate: int) -> int:
    return max(1, round(sample_rate / ENV_RATE_HZ))


def wav_to_mono(data: bytes) -> tuple[np.ndarray, int]:
    """Parse a 16-bit PCM WAV (what the wizard page uploads) to floats."""
    with wave.open(io.BytesIO(data), "rb") as handle:
        channels = handle.getnchannels()
        width = handle.getsampwidth()
        rate = handle.getframerate()
        frames = handle.readframes(handle.getnframes())
    if width != 2:
        raise ValueError(f"expected 16-bit PCM, got {8 * width}-bit")
    samples = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, rate


def onset_envelope(samples: np.ndarray, sample_rate: int) -> np.ndarray:
    """Onset strength at ENV_RATE_HZ: per-bin energy, then positive rises.

    Rises rather than raw energy because the room, the music bed and the
    phone's own gain control all move slowly — a click is the thing that
    *jumps*.
    """
    hop = env_hop(sample_rate)
    usable = (len(samples) // hop) * hop
    if usable == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[:usable].reshape(-1, hop)
    energy = np.sqrt((frames * frames).mean(axis=1))
    rises = np.diff(energy, prepend=energy[:1])
    return np.clip(rises, 0.0, None).astype(np.float32)


def reference_impulses(length: int, rate_hz: float) -> np.ndarray:
    """The click pattern as an impulse train at the envelope's TRUE rate."""
    train = np.zeros(length, dtype=np.float32)
    for onset in reference.CLICK_TIMES_S:
        index = int(round(onset * rate_hz))
        if 0 <= index < length:
            train[index] = 1.0
    return train


def estimate_offset(recording: bytes) -> dict:
    """Where does the reference start inside this recording?

    Returns {"lag_s", "confidence"} — lag is seconds from recording start
    to the reference track's own t=0 (which precedes the first click by
    exactly reference.CLICK_TIMES_S[0]).
    """
    samples, rate = wav_to_mono(recording)
    if len(samples) < rate:  # under a second of audio answers nothing
        raise ValueError("recording too short")
    hop = env_hop(rate)
    rate_hz = rate / hop
    envelope = onset_envelope(samples, rate)
    if envelope.size == 0 or float(envelope.max()) <= 0.0:
        raise ValueError("recording is silent")
    envelope = envelope / envelope.max()
    train = reference_impulses(envelope.size, rate_hz)

    # FFT cross-correlation, positive lags only: the recording started
    # before the play command by construction, so the reference can only
    # appear at or after the recording's own t=0.
    size = 1
    while size < 2 * envelope.size:
        size *= 2
    spectrum = np.fft.rfft(envelope, size) * np.conj(np.fft.rfft(train, size))
    correlation = np.fft.irfft(spectrum, size)[:envelope.size]

    peak_index = int(np.argmax(correlation))
    peak = float(correlation[peak_index])

    # Confidence is a z-score against the rest of the correlation, the
    # peak's own neighbourhood excluded. The max of N noise values sits
    # near z≈4 by luck alone (that is just what maxima of N samples do),
    # so the threshold below clears it with margin while a real recording
    # scores in the tens.
    guard = max(1, int(0.25 * rate_hz))
    others = np.concatenate([correlation[:max(0, peak_index - guard)],
                             correlation[peak_index + guard:]])
    if others.size < 10:
        raise ValueError("recording too short")
    spread = float(others.std()) or 1e-9
    confidence = (peak - float(others.mean())) / spread

    return {
        "lag_s": peak_index / rate_hz,
        "confidence": round(confidence, 1),
        "recording_s": round(len(samples) / rate, 2),
    }


# Below this the peak is not distinguishable from the luck-of-the-maximum
# (z≈4 for noise), and storing the number would calibrate the show to it.
MIN_CONFIDENCE = 6.0
