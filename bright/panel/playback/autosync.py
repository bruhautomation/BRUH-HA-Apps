"""Sync by ear, with the phone doing the listening.

The manual nudge asks a person to be the measuring instrument: watch,
press, watch again. This is the same measurement made honestly — the
phone records a few seconds of the room, and where the song actually is
in that recording, versus where the show clock believed it was, IS the
sync error. One number, applied once.

Method: the same onset-envelope cross-correlation calibration uses
(`calibrate.correlate`), against a different reference — not the click
track, but a window of the playing song itself, decoded from the same
file the analyzer measured. The window spans the clock's claimed position
± MARGIN_S, so any drift inside ±MARGIN_S lands the recording somewhere
inside it and the correlation peak says where.

Music is a fuzzier reference than clicks on purpose-built silence, so the
confidence floor is its own constant and a quiet passage can honestly
answer "could not hear enough to tell" — which is a retry, not a failure.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from analyzer import decode
from calibrate import correlate

# How far out of tune a running show is allowed to be and still be found.
# Chromecast group re-buffering is the worst real case and sits inside a
# second; ±2s of search window costs one FFT nobody notices.
MARGIN_S = 2.0

# Measured, not guessed: on synthesized music (test_bright_autosync) a
# real match scores 16–29 even with a quiet mic in a noisy room, while
# pure noise reaches 3–5 by the luck of the maximum. 7.0 clears the
# noisiest noise with margin and is less than half the weakest real match.
MIN_CONFIDENCE = 7.0

# A recording shorter than this doesn't hold enough rhythm to match.
MIN_RECORDING_S = 2.0


def measure(recording: bytes, track_file: Path,
            expected_pos_s: float) -> dict:
    """Where is the room's audio, relative to where the clock thinks?

    Returns {"delta_s", "confidence", "recording_s", "heard_pos_s"}.
    `delta_s` > 0 means the audio is AHEAD of the show clock (the lights
    are late); < 0 means the audio is behind (the lights are early). The
    caller nudges by `delta_s` — nudge's own sign convention (positive =
    lights earlier) makes that the correction with no further arithmetic.

    Raises ValueError with a person-readable message on anything that
    should be read as "try again", not "broken".
    """
    samples, rate = correlate.wav_to_mono(recording)
    recording_s = len(samples) / rate
    if recording_s < MIN_RECORDING_S:
        raise ValueError("the recording was too short — hold the phone up "
                         "for a few seconds")
    mic_env = correlate.onset_envelope(samples, rate)
    if mic_env.size == 0 or float(mic_env.max()) <= 0.0:
        raise ValueError("the phone heard silence — is the music playing "
                         "near it?")
    mic_env = mic_env - mic_env.mean()

    # The reference: the song around where the clock says the room is.
    # The window has to cover the whole recording plus the search margin
    # on both sides, and the clamp at the track's start is folded into
    # `window_start` so the position arithmetic below stays honest.
    window_start = max(0.0, expected_pos_s - MARGIN_S)
    window_len = recording_s + (expected_pos_s - window_start) + MARGIN_S
    ref = decode.pcm_window(track_file, window_start, window_len)
    ref_env = correlate.onset_envelope(ref, decode.SAMPLE_RATE)
    if ref_env.size <= mic_env.size:
        raise ValueError("not enough of the song left to match against — "
                         "it may be about to end")
    ref_env = ref_env - ref_env.mean()

    # The envelopes run at fractionally different true rates (rate/hop per
    # source); over a few seconds the divergence is under the ~5ms bin, so
    # the mic envelope is used as-is and the ref's rate does the mapping.
    correlation = np.correlate(ref_env, mic_env, mode="valid")
    peak_index = int(np.argmax(correlation))
    peak = float(correlation[peak_index])

    ref_rate_hz = decode.SAMPLE_RATE / correlate.env_hop(decode.SAMPLE_RATE)
    guard = max(1, int(0.25 * ref_rate_hz))
    others = np.concatenate([correlation[:max(0, peak_index - guard)],
                             correlation[peak_index + guard:]])
    if others.size < 10:
        raise ValueError("the recording covered almost the whole search "
                         "window — try again")
    spread = float(others.std()) or 1e-9
    confidence = (peak - float(others.mean())) / spread

    heard_pos_s = window_start + peak_index / ref_rate_hz
    return {
        "delta_s": round(heard_pos_s - expected_pos_s, 3),
        "confidence": round(confidence, 1),
        "recording_s": round(recording_s, 2),
        "heard_pos_s": round(heard_pos_s, 2),
    }
