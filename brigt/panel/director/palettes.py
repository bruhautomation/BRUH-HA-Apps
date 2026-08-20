"""The shared vocabulary both director tiers write in and the compiler
reads: roles, palettes, motif types, and the per-role rules that keep a
show tasteful (candles never strobe; lasers only earn their moments).

Hues are degrees, saturations 0..1 — human units at the boundary; the
compiler converts to LIFX's u16 fields exactly once.
"""
from __future__ import annotations

# Role behavior: how bright a role may run relative to the scene, whether
# it may pulse on the beat, and whether it is a switch (on/off) rather
# than a color light.
ROLE_RULES = {
    "candle":    {"max_brightness": 0.45, "pulses": False, "switch": False},
    "downlight": {"max_brightness": 1.00, "pulses": True,  "switch": False},
    "lamp":      {"max_brightness": 1.00, "pulses": True,  "switch": False},
    "strip":     {"max_brightness": 1.00, "pulses": True,  "switch": False},
    "party":     {"max_brightness": 1.00, "pulses": False, "switch": True},
    "laser":     {"max_brightness": 1.00, "pulses": False, "switch": True},
}

# Palettes: (name, [(hue_deg, saturation), ...]). Ordered from warm/dark
# feels to cool/bright feels — pick_palette indexes by the track's
# brightness hint so a mellow acoustic track doesn't get neon.
PALETTES = [
    ("embers",   [(18, 0.95), (35, 0.85), (2, 0.9), (45, 0.7)]),
    ("sunset",   [(12, 0.9), (320, 0.75), (35, 0.8), (280, 0.6)]),
    ("velvet",   [(280, 0.8), (320, 0.85), (240, 0.7), (350, 0.75)]),
    ("lagoon",   [(190, 0.85), (160, 0.8), (220, 0.75), (140, 0.6)]),
    ("club",     [(210, 0.9), (275, 0.85), (180, 0.8), (330, 0.9)]),
    ("neon",     [(300, 1.0), (180, 1.0), (55, 0.95), (225, 0.95)]),
]

MOTIF_TYPES = ("beat_pulse", "sweep", "breathe", "aux_on")
FEATURE_TYPES = ("drop_hit", "lyric_moment")

# Scene intensity per section kind: (base_brightness, pulse_depth).
SECTION_LEVELS = {
    "intro": (0.30, 0.15),
    "quiet": (0.25, 0.10),
    "mid":   (0.55, 0.30),
    "peak":  (0.85, 0.45),
    "outro": (0.25, 0.10),
}


def pick_palette(brightness_hint: float, seed: int) -> tuple[str, list]:
    """Darker tracks warmer, brighter tracks cooler; the seed rotates
    among neighbours so two similar tracks don't wear the same colors."""
    index = int(round(brightness_hint * (len(PALETTES) - 1)))
    index = max(0, min(len(PALETTES) - 1, index + (seed % 3) - 1))
    return PALETTES[index]
