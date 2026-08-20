"""What the music feels like, moment to moment: energy and frequency bands.

Everything is sampled on one shared 20Hz grid (`FEATURE_RATE_HZ`) so the
director can index any feature by time without unit gymnastics. Arrays of
rounded floats — a 4-minute track stays around 100KB of JSON.
"""
from __future__ import annotations

import numpy as np

FEATURE_RATE_HZ = 20

# Band edges: bass carries the kick and the drop, mids carry the song,
# highs carry the shimmer. Three numbers per instant is what a light show
# can actually spend.
LOW_HZ = 250.0
HIGH_HZ = 2000.0


def band_energies(pcm: np.ndarray, sample_rate: int) -> dict:
    """RMS energy overall + per band, at FEATURE_RATE_HZ."""
    hop = max(1, int(round(sample_rate / FEATURE_RATE_HZ)))
    frame = hop * 2
    usable = (len(pcm) - frame) // hop
    if usable <= 0:
        empty = []
        return {"hop_s": round(1.0 / FEATURE_RATE_HZ, 4), "energy": empty,
                "low": empty, "mid": empty, "high": empty}
    window = np.hanning(frame).astype(np.float32)
    frames = np.lib.stride_tricks.as_strided(
        pcm,
        shape=(usable, frame),
        strides=(pcm.strides[0] * hop, pcm.strides[0]),
    )
    spectra = np.abs(np.fft.rfft(frames * window, axis=1))
    freqs = np.fft.rfftfreq(frame, 1.0 / sample_rate)
    low_bins = freqs < LOW_HZ
    mid_bins = (freqs >= LOW_HZ) & (freqs < HIGH_HZ)
    high_bins = freqs >= HIGH_HZ

    def track(mask) -> np.ndarray:
        return np.sqrt((spectra[:, mask] ** 2).sum(axis=1))

    total = track(np.ones_like(low_bins, dtype=bool))
    peak = float(total.max()) or 1.0

    def normalized(values: np.ndarray) -> list[float]:
        return [round(float(v) / peak, 4) for v in values]

    return {
        "hop_s": round(1.0 / FEATURE_RATE_HZ, 4),
        "energy": normalized(total),
        "low": normalized(track(low_bins)),
        "mid": normalized(track(mid_bins)),
        "high": normalized(track(high_bins)),
    }


def brightness_hint(pcm: np.ndarray, sample_rate: int) -> float:
    """One number for the whole track: spectral centroid, 0..1. The
    palette picker maps darker tracks warmer and brighter tracks cooler."""
    spectrum = np.abs(np.fft.rfft(pcm[: sample_rate * 60]))  # first minute
    if spectrum.sum() <= 0:
        return 0.5
    freqs = np.fft.rfftfreq(len(pcm[: sample_rate * 60]), 1.0 / sample_rate)
    centroid = float((spectrum * freqs).sum() / spectrum.sum())
    # 200Hz..4kHz mapped to 0..1 on a log scale.
    value = (np.log10(max(centroid, 200.0)) - np.log10(200.0)) / (
        np.log10(4000.0) - np.log10(200.0))
    return round(float(np.clip(value, 0.0, 1.0)), 3)
