"""Insight category definitions and prompt construction for BRUH Insights.

Each category declares which slices of Home Assistant data it wants (domains,
device classes, whether it needs history / long-term statistics) and the
analytical focus Claude should take. ``build_prompt`` turns a collected data
bundle into the final generation prompt, and ``SYSTEM_PROMPT`` carries the
strict output contract plus the visualization design system the generated
HTML must follow.

This module is dependency-free so the test suite can import it directly.
"""
from __future__ import annotations

import json

# ---------------------------------------------------------------------------
# Categories
# ---------------------------------------------------------------------------
# domains / device_classes filter which entities are included in the bundle.
# history=True pulls recent state history for the matched numeric sensors;
# stats=True pulls long-term statistics (hourly mean/sum) instead — better
# for energy where the recorder keeps sums.

CATEGORIES: list[dict] = [
    {
        "id": "overview",
        "title": "Home Overview",
        "icon": "🏠",
        "description": "The big picture — what's on, who's home, and what deserves attention right now.",
        "domains": [],  # empty = all domains (slimmed)
        "device_classes": [],
        "history": False,
        "stats": False,
        "focus": (
            "Give a delightful executive summary of the whole home right now: counts of what is "
            "on/open/active by area, who is home, anything unusual or worth attention. Build a "
            "visualization that maps the state of the home at a glance — for example an area-by-area "
            "grid or a radial 'home at a glance' diagram with animated state dots."
        ),
    },
    {
        "id": "energy",
        "title": "Energy",
        "icon": "⚡",
        "description": "Consumption trends, top loads, and where the watts are going.",
        "domains": ["sensor"],
        "device_classes": ["energy", "power", "battery", "voltage", "current"],
        "history": False,
        "stats": True,
        "focus": (
            "Analyze energy and power usage: daily consumption trend, biggest consumers, baseline vs "
            "peaks, and anything anomalous. If per-device energy sensors exist, rank the top loads. "
            "Visualize the consumption story over the period — a trend chart plus a top-consumers "
            "breakdown works well."
        ),
    },
    {
        "id": "climate",
        "title": "Climate",
        "icon": "🌡️",
        "description": "Temperature, humidity, and HVAC behavior across the house.",
        "domains": ["climate", "weather", "fan", "humidifier"],
        "device_classes": ["temperature", "humidity", "carbon_dioxide", "pressure", "aqi"],
        "history": True,
        "stats": False,
        "focus": (
            "Analyze indoor climate: temperature and humidity per room vs outdoor conditions, HVAC "
            "setpoints vs actuals, rooms that run hot/cold, comfort assessment. Visualize room "
            "temperatures over time against the outdoor curve, or a comfort map of the house."
        ),
    },
    {
        "id": "lighting",
        "title": "Lighting",
        "icon": "💡",
        "description": "What's lit, usage patterns, and lights left on.",
        "domains": ["light", "switch", "sun"],
        "device_classes": ["illuminance"],
        "history": True,
        "stats": False,
        "focus": (
            "Analyze lighting: which lights are on now (and for how long, if history shows it), "
            "usage patterns by area and time of day relative to sunrise/sunset, lights possibly left "
            "on in empty rooms. Visualize the lighting state of the house and on-time patterns."
        ),
    },
    {
        "id": "security",
        "title": "Security",
        "icon": "🔒",
        "description": "Doors, windows, locks, motion, and anything open or unlocked.",
        "domains": ["lock", "alarm_control_panel", "cover", "camera"],
        "device_classes": [
            "door", "window", "garage_door", "motion", "occupancy", "opening",
            "lock", "smoke", "carbon_monoxide", "gas", "safety", "tamper",
        ],
        "history": True,
        "stats": False,
        "focus": (
            "Assess security posture: anything open or unlocked right now, recent motion and "
            "door/window activity, smoke/CO sensor health. Call out risks plainly. Visualize the "
            "perimeter state and an activity timeline of recent openings/motion."
        ),
    },
    {
        "id": "presence",
        "title": "Presence",
        "icon": "🧭",
        "description": "Who's home, arrivals and departures, and activity rhythms.",
        "domains": ["person", "device_tracker", "zone"],
        "device_classes": ["motion", "occupancy", "presence"],
        "history": True,
        "stats": False,
        "focus": (
            "Analyze presence and activity: who is home now, arrival/departure patterns over the "
            "period, and the home's activity rhythm from motion sensors. Visualize a presence "
            "timeline per person and/or an activity heat pattern by hour."
        ),
    },
    {
        "id": "media",
        "title": "Media",
        "icon": "🎵",
        "description": "What's playing, where, and listening/viewing habits.",
        "domains": ["media_player", "remote"],
        "device_classes": [],
        "history": True,
        "stats": False,
        "focus": (
            "Analyze media players: what is playing now and where, which rooms/devices get the most "
            "use, and habits by time of day. Visualize current playback and usage per device."
        ),
    },
    {
        "id": "health",
        "title": "Device Health",
        "icon": "🩺",
        "description": "Unavailable devices, weak batteries, and pending updates.",
        "domains": ["update", "button"],
        "device_classes": ["battery", "connectivity", "problem", "update"],
        "history": False,
        "stats": False,
        "include_unavailable": True,
        "focus": (
            "Audit device health: unavailable/unknown entities (grouped by likely device), batteries "
            "below 30%, pending firmware/software updates, and integrations that look broken. "
            "Prioritize what to fix first. Visualize a health scoreboard with the problem list."
        ),
    },
    {
        "id": "automations",
        "title": "Automations",
        "icon": "🤖",
        "description": "What ran, what never runs, and how the house automates itself.",
        "domains": ["automation", "script", "scene", "input_boolean", "timer", "schedule"],
        "device_classes": [],
        "history": True,
        "stats": False,
        "focus": (
            "Analyze automations and scripts: most/least recently triggered, disabled ones, likely "
            "dead automations (never fire), and coverage — which areas or times of day the "
            "automations serve. Suggest one or two concrete improvements. Visualize trigger recency "
            "and activity."
        ),
    },
]

CATEGORY_IDS = [c["id"] for c in CATEGORIES]


def get_category(cat_id: str) -> dict | None:
    for c in CATEGORIES:
        if c["id"] == cat_id:
            return c
    return None


# ---------------------------------------------------------------------------
# Output contract + design system (given to Claude as the system prompt)
# ---------------------------------------------------------------------------
# The palette and mark rules follow a validated, colorblind-safe data-viz
# design system: categorical hues assigned in fixed order (never cycled),
# one hue light→dark for magnitude, blue↔red for polarity, reserved status
# colors, one axis per chart, thin marks, legends for ≥2 series.

SYSTEM_PROMPT = """You are BRUH Insights, the AI analyst inside a Home Assistant add-on. You receive a JSON snapshot of the user's smart home and produce ONE insight card: sharp analysis plus a beautiful, self-contained interactive visualization.

You have NO tools available. Never attempt to use tools. Respond with a single JSON object and absolutely nothing else — no markdown fences, no prose before or after.

OUTPUT CONTRACT (strict JSON, all fields required):
{
  "title": "Short punchy card title (max 60 chars)",
  "summary": "2-4 plain sentences. Concrete, specific to THIS home, numbers included. No fluff.",
  "highlights": [ {"label": "Metric name", "value": "42 kWh", "delta": "+12% vs avg (optional)", "status": "good|warning|serious|critical (optional)"} ],
  "html": "<!DOCTYPE html>... one complete self-contained HTML document ..."
}
Provide 2-4 highlights. Escape the HTML correctly as a JSON string.

THE HTML DOCUMENT:
- Fully self-contained: inline CSS and JS only. NO external resources (no CDNs, fonts, images, fetch). It renders inside a sandboxed iframe with scripts enabled.
- Responsive: fill 100% width, size height to content (roughly 320-560px of content). No horizontal scrolling. body{margin:0}.
- Use system-ui sans everywhere. Use font-variant-numeric: tabular-nums only for aligned columns/ticks.
- Support BOTH light and dark mode via @media (prefers-color-scheme: dark), using the exact palette below. Default (light) first.
- Animate tastefully: draw-in/fade/count-up on load (≤800ms, ease-out), subtle idle motion only where meaningful (e.g. a gently pulsing "active" dot). Wrap all animation in @media (prefers-reduced-motion: no-preference).
- Interactive by default: hover tooltips on every chart mark (crosshair+tooltip for line/area, per-mark for bars/dots/cells), hit targets larger than the mark. Clickable legend toggles are welcome. Everything must also read fine without hovering.
- Build charts with inline SVG (or CSS grid for state maps). No canvas libraries.

DESIGN SYSTEM (follow exactly):
- Surfaces: light #fcfcfb, dark #1a1a19. Text: primary #0b0b0b/#ffffff, secondary #52514e/#c3c2b7, muted #898781. Gridlines (hairline) #e1e0d9/#2c2c2a. Axis/baseline #c3c2b7/#383835.
- Categorical series colors, ALWAYS assigned in this fixed order (light|dark): 1 blue #2a78d6|#3987e5, 2 green #008300|#008300, 3 magenta #e87ba4|#d55181, 4 yellow #eda100|#c98500, 5 aqua #1baf7a|#199e70, 6 orange #eb6834|#d95926, 7 violet #4a3aa7|#9085e9, 8 red #e34948|#e66767. More than ~6 series: fold the rest into a gray "Other".
- Sequential (magnitude): ONE hue, blue light→dark (#cde2fb → #0d366b). Diverging (above/below): blue↔red with a neutral gray midpoint (#f0efec/#383835). NEVER rainbow.
- Status colors (reserved, never used as series): good #0ca30c, warning #fab219, serious #ec835a, critical #d03b3b — always paired with an icon or label, never color alone.
- Marks: 2px lines; bars with 4px rounded top corners only (flat at the baseline); ≥8px hover markers; 2px surface-colored gap between stacked segments and adjacent bars; markers overlapping get a 2px surface ring.
- ONE y-axis per chart, always. Two measures of different scale → two small charts side by side, never a dual axis.
- Legend whenever ≥2 series (plus direct labels when ≤4); a single series needs no legend — the title names it. Label selectively (ends, peaks), never every point. Text is always ink-colored, never series-colored.
- Y-axis starts at zero for bars. Recessive grid, no chart junk, no drop shadows on marks.

ANALYSIS RULES:
- Be specific to this home: use real entity names (their friendly names), real areas, real numbers and times. Convert entity_ids to friendly names in all user-facing text.
- Find the STORY in the data — a trend, an outlier, a pattern, a risk — don't just restate states.
- If the data for the requested angle is thin, say so honestly in the summary and visualize what IS there.
- Times in the data are ISO timestamps in the home's local timezone unless suffixed Z. Present times in a friendly way (e.g. "6:42 PM").
- Never invent data. Every number shown must come from the snapshot."""


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def build_prompt(category: dict, bundle: dict, question: str | None = None) -> str:
    """Assemble the user prompt: analysis focus + the data bundle."""
    parts: list[str] = []
    if question:
        parts.append(
            "The user asked this question about their home — answer it as the insight card:\n"
            f"QUESTION: {question.strip()}\n"
        )
        parts.append(
            "Choose the most fitting visualization for the answer. If the question is not really "
            "about the smart home data, answer briefly and honestly in the summary and keep the "
            "visualization minimal."
        )
    else:
        parts.append(f"INSIGHT CATEGORY: {category['title']}")
        parts.append(f"ANALYSIS FOCUS: {category['focus']}")

    parts.append(
        "\nHOME DATA SNAPSHOT (JSON). Sections: meta (now, timezone, location name), areas, "
        "entities (e=entity_id, s=state, n=friendly name, a=area, u=unit, dc=device_class, "
        "lc=last_changed, x=extra attributes), history (per entity: h=[[time, value|state], ...] "
        "downsampled), statistics (per entity hourly sum/mean), context (optional notes about "
        "this home)."
    )
    parts.append(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
    parts.append(
        "\nNow produce the single JSON insight object per the contract. Remember: JSON only, "
        "no fences, no commentary."
    )
    return "\n".join(parts)
