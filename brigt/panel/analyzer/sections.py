"""Song structure: where the sections are, how hard each one hits, and
where the drops land.

Boundaries come from novelty — how different the next stretch of music is
from the last — and the labels are honest energy tiers (`intro`, `quiet`,
`mid`, `peak`, `outro`), not guessed verse/chorus names. The director maps
tiers to scene intensity; a wrong guess at "chorus" would steer it harder
than a right answer about energy.
"""
from __future__ import annotations

import numpy as np

# Windows compared for novelty, seconds. Song sections run 8-30s; a 6s
# window sees enough context to call a change real.
WINDOW_S = 6.0
MIN_SECTION_S = 8.0

# A drop: the energy after the moment jumps this much over the stretch
# before it, from a bar that was already building or breaking down.
DROP_JUMP = 0.25


def _per_second(values: list[float], hop_s: float) -> np.ndarray:
    """Downsample a FEATURE_RATE track to one value per second."""
    if not values:
        return np.zeros(0, dtype=np.float32)
    per = max(1, int(round(1.0 / hop_s)))
    usable = (len(values) // per) * per
    if usable == 0:
        return np.asarray([np.mean(values)], dtype=np.float32)
    return np.asarray(values[:usable], dtype=np.float32).reshape(-1, per).mean(axis=1)


def find_sections(features: dict, duration_s: float) -> list[dict]:
    energy = _per_second(features["energy"], features["hop_s"])
    low = _per_second(features["low"], features["hop_s"])
    high = _per_second(features["high"], features["hop_s"])
    seconds = energy.size
    if seconds < MIN_SECTION_S * 2:
        return [{"start": 0.0, "end": round(duration_s, 2), "kind": "mid",
                 "energy": round(float(energy.mean()) if seconds else 0.0, 3)}]

    profile = np.stack([energy, low, high], axis=1)
    window = int(WINDOW_S)
    novelty = np.zeros(seconds, dtype=np.float32)
    for t in range(window, seconds - window):
        before = profile[t - window:t].mean(axis=0)
        after = profile[t:t + window].mean(axis=0)
        novelty[t] = float(np.linalg.norm(after - before))

    # Boundary = local novelty peak, spaced at least a section apart.
    threshold = novelty.mean() + novelty.std() * 0.8
    boundaries = [0]
    for t in range(window, seconds - window):
        if (novelty[t] >= threshold
                and novelty[t] == novelty[max(0, t - 3):t + 4].max()
                and t - boundaries[-1] >= MIN_SECTION_S):
            boundaries.append(t)
    boundaries.append(seconds)

    # Label by energy tier over the whole track's own distribution.
    quiet_cut, peak_cut = np.quantile(energy, [0.35, 0.75])
    sections = []
    for start, end in zip(boundaries, boundaries[1:]):
        mean_energy = float(energy[start:end].mean())
        if mean_energy >= peak_cut:
            kind = "peak"
        elif mean_energy <= quiet_cut:
            kind = "quiet"
        else:
            kind = "mid"
        sections.append({
            "start": float(start),
            "end": round(min(float(end), duration_s), 2),
            "kind": kind,
            "energy": round(mean_energy, 3),
        })
    if sections:
        sections[0]["kind"] = "intro" if sections[0]["kind"] != "peak" else "peak"
        if len(sections) > 1 and sections[-1]["kind"] == "quiet":
            sections[-1]["kind"] = "outro"
    return sections


def find_drops(features: dict) -> list[dict]:
    """The moments the whole room should hit: a sharp sustained energy jump
    out of a quieter stretch, led by the bass."""
    hop_s = features["hop_s"]
    energy = np.asarray(features["energy"], dtype=np.float32)
    low = np.asarray(features["low"], dtype=np.float32)
    if energy.size < int(8.0 / hop_s):
        return []
    span = int(round(2.0 / hop_s))  # compare 2s before vs 2s after
    drops = []
    last_t = -8.0
    for i in range(span, energy.size - span):
        before = float(energy[i - span:i].mean())
        after = float(energy[i:i + span].mean())
        bass_after = float(low[i:i + span].mean())
        jump = after - before
        t = i * hop_s
        if jump >= DROP_JUMP and bass_after > before and t - last_t >= 8.0:
            drops.append({"t": round(t, 2),
                          "strength": round(min(1.0, jump * 2), 2)})
            last_t = t
    return drops
