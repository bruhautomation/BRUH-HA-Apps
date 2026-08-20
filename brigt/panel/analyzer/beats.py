"""Tempo, the beat grid, downbeats and onsets.

Pure numpy on purpose: librosa drags in numba (painful on musl), and the
aubio python binding isn't packaged for the base image. For the music this
add-on exists for — party tracks with a steady pulse — a spectral-flux
envelope, an autocorrelation tempo and a phase-searched grid get within a
few milliseconds of anything fancier, and every dependency it needs is
already in the image. The `method` field in the result names the tracker
so a future, better one can coexist with cached analyses.

Everything here returns TIMES IN SECONDS against the decoded PCM, which is
the same timeline the show compiler emits cues on.
"""
from __future__ import annotations

import numpy as np

FRAME = 1024
HOP = 512

BPM_MIN = 60.0
BPM_MAX = 200.0


def onset_strength(pcm: np.ndarray, sample_rate: int) -> tuple[np.ndarray, float]:
    """Positive spectral flux per frame — the 'something just hit' signal.

    Returns (envelope, envelope_rate_hz). Log-magnitude flux so a hi-hat
    over a loud bed still registers.
    """
    usable = (len(pcm) - FRAME) // HOP
    if usable <= 2:
        return np.zeros(0, dtype=np.float32), sample_rate / HOP
    window = np.hanning(FRAME).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(
        pcm,
        shape=(usable, FRAME),
        strides=(pcm.strides[0] * HOP, pcm.strides[0]),
    )
    spectra = np.abs(np.fft.rfft(frames * window, axis=1))
    logspec = np.log1p(10.0 * spectra)
    flux = np.diff(logspec, axis=0)
    envelope = np.clip(flux, 0.0, None).sum(axis=1)
    envelope -= envelope.min()
    if envelope.max() > 0:
        envelope /= envelope.max()
    # Align the envelope with AUDIO time. A hit at sample s first raises
    # the frame whose window reaches back to it, so flux peaks FRAME/HOP
    # bins before the hit's own time (measured, not theorized: exactly 2
    # bins for this FRAME/HOP). Padding the front makes envelope[i] answer
    # for time i/rate, so every consumer — grid, snapping, onsets,
    # downbeats — reads the true timeline and cue times land on the music.
    envelope = np.concatenate([
        np.zeros(FRAME // HOP, dtype=np.float32), envelope.astype(np.float32)])
    return envelope, sample_rate / HOP


def estimate_bpm(envelope: np.ndarray, env_rate: float) -> float:
    """Autocorrelation over the musical tempo range, octave-corrected.

    A grid at 60 BPM also matches a 120 BPM track (every other beat), so
    after picking the strongest lag, halves and doubles inside the range
    are compared and the one that explains the envelope best — weighted
    gently toward the 90–180 danceable octave — wins.
    """
    if envelope.size < env_rate * 4:
        return 120.0
    centered = envelope - envelope.mean()
    spectrum = np.fft.rfft(centered, 2 * len(centered))
    autocorr = np.fft.irfft(spectrum * np.conj(spectrum))[:len(centered)]
    lag_min = int(env_rate * 60.0 / BPM_MAX)
    lag_max = int(env_rate * 60.0 / BPM_MIN)
    if lag_max <= lag_min + 2 or lag_max >= len(autocorr):
        return 120.0
    window = autocorr[lag_min:lag_max]
    base_lag = lag_min + int(np.argmax(window))

    def strength(lag: float) -> float:
        index = int(round(lag))
        if not lag_min <= index < lag_max + lag_min:
            return -np.inf
        bpm = 60.0 * env_rate / lag
        preference = 1.0 if 90.0 <= bpm <= 180.0 else 0.92
        return float(autocorr[index]) * preference

    candidates = [base_lag, base_lag / 2.0, base_lag * 2.0]
    best = max(candidates, key=strength)
    return round(60.0 * env_rate / best, 2)


def beat_grid(envelope: np.ndarray, env_rate: float,
              bpm: float) -> tuple[list[float], float]:
    """The grid that collects the most onset strength.

    Searches phase exhaustively and tempo within ±3% — enough to absorb an
    estimate that is right but coarse, without ever wandering off to a
    different tempo than the one it was handed.
    """
    duration = envelope.size / env_rate
    best = (-1.0, [], bpm)
    for factor in np.linspace(0.97, 1.03, 13):
        candidate_bpm = bpm * factor
        period = 60.0 / candidate_bpm
        phases = np.arange(0.0, period, 0.01)
        for phase in phases:
            times = np.arange(phase, duration, period)
            indices = np.clip((times * env_rate).astype(int), 0,
                              envelope.size - 1)
            score = float(envelope[indices].sum())
            if score > best[0]:
                best = (score, times.tolist(), candidate_bpm)
    _, times, fitted_bpm = best
    return [round(t, 4) for t in times], round(fitted_bpm, 2)


def snap_to_peaks(times: list[float], envelope: np.ndarray, env_rate: float,
                  radius_s: float = 0.06) -> list[float]:
    """Move each grid beat onto the nearest onset peak within ±radius.

    The exhaustive grid is quantized (tempo steps × phase steps) and a
    half-percent tempo error compounds to tens of milliseconds by a
    track's end. The actual hits are sitting right there in the envelope,
    so each grid point that has a real onset near it snaps to the onset;
    one with nothing near it (a rest, a breakdown bar) keeps the grid's
    answer, which is what a musician would clap there too.
    """
    radius = max(1, int(radius_s * env_rate))
    snapped = []
    for t in times:
        center = int(round(t * env_rate))
        lo = max(0, center - radius)
        hi = min(envelope.size, center + radius + 1)
        if hi <= lo:
            snapped.append(round(t, 4))
            continue
        window = envelope[lo:hi]
        peak = int(np.argmax(window))
        # Snap only to a real hit — a flat window means a rest.
        if window[peak] > max(0.05, float(window.mean()) * 1.5):
            snapped.append(round((lo + peak) / env_rate, 4))
        else:
            snapped.append(round(t, 4))
    return snapped


def pick_downbeats(beats: list[float], envelope: np.ndarray,
                   env_rate: float) -> list[float]:
    """Every 4th beat, phased where the accents actually are."""
    if len(beats) < 8:
        return beats[:1]
    scores = []
    for start in range(4):
        indices = np.clip(
            (np.asarray(beats[start::4]) * env_rate).astype(int),
            0, envelope.size - 1)
        scores.append(float(envelope[indices].mean()))
    best_start = int(np.argmax(scores))
    return [round(b, 4) for b in beats[best_start::4]]


def detect_onsets(envelope: np.ndarray, env_rate: float) -> list[float]:
    """Discrete hits — local maxima well above the local level. The
    director uses these for accents between beats (snare fills, stabs)."""
    if envelope.size < 8:
        return []
    kernel = max(3, int(env_rate * 0.35))
    padded = np.pad(envelope, kernel, mode="edge")
    local_mean = np.convolve(padded, np.ones(2 * kernel + 1) / (2 * kernel + 1),
                             mode="valid")
    threshold = local_mean + 0.12
    onsets = []
    last = -1.0
    for i in range(1, envelope.size - 1):
        if (envelope[i] > threshold[i]
                and envelope[i] >= envelope[i - 1]
                and envelope[i] > envelope[i + 1]):
            t = i / env_rate
            if t - last >= 0.09:  # two "hits" 90ms apart are one hit
                onsets.append(round(t, 4))
                last = t
    return onsets


def analyze_beats(pcm: np.ndarray, sample_rate: int) -> dict:
    envelope, env_rate = onset_strength(pcm, sample_rate)
    if envelope.size == 0:
        return {"bpm": 0.0, "beats": [], "downbeats": [], "onsets": [],
                "method": "numpy"}
    bpm = estimate_bpm(envelope, env_rate)
    grid, fitted_bpm = beat_grid(envelope, env_rate, bpm)
    beats = snap_to_peaks(grid, envelope, env_rate)
    return {
        "bpm": fitted_bpm,
        "beats": beats,
        "downbeats": pick_downbeats(beats, envelope, env_rate),
        "onsets": detect_onsets(envelope, env_rate),
        "method": "numpy",
    }
