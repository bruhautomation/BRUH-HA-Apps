"""Insight category definitions and prompt construction for BRain.

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
        "device_context": True,
        "focus": (
            "Surface the few numbers that describe the home right now: what's on/open/active "
            "(counts by area), who is home (corroborated by phone context, not just person "
            "state), and the single most attention-worthy anomaly if there is one. Visualize an "
            "at-a-glance area grid or radial home map with state dots — nothing more."
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
            "Pull the key energy numbers: today's consumption vs the period average, the top 3 "
            "loads by kWh, baseline draw, and one anomaly (a spike with its time and likely "
            "device) if the data shows one. Visualize ONE chart — the daily trend or the "
            "top-consumers ranking, whichever carries this run's story."
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
            "Pull the key climate numbers: warmest and coldest rooms right now (with degrees), "
            "any room off its HVAC setpoint by more than a degree, humidity outliers, and indoor "
            "vs outdoor delta. Visualize ONE chart — room temperatures against the outdoor "
            "curve, or a comfort map."
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
            "Pull the key lighting numbers: how many lights are on now and where, the longest-on "
            "light (name + hours), lights likely left on in empty rooms (cross-check motion), and "
            "one usage pattern vs sunset if history shows it. Visualize the current lighting map "
            "or the on-time pattern — one visual."
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
            "Pull the security facts: exactly what is open or unlocked right now (names), the "
            "last door/window/motion events with times, and any smoke/CO sensor that isn't "
            "reporting. Call risks plainly. Visualize the perimeter state or a recent-activity "
            "timeline — one visual."
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
        "device_context": True,
        "focus": (
            "Where is each person, stated as a conclusion with its evidence chain — use "
            "device_context (phone WiFi SSID, geocoded address, detected activity, "
            "battery/charging) plus arrival/departure history, not just person.state (e.g. "
            "\"Ben: at work — phone on OfficeNet, stationary since 9:12 AM\"). Add today's "
            "arrivals/departures with times and one deviation from the usual rhythm if real. "
            "Visualize a per-person presence timeline — one visual."
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
            "Pull the media facts: what is playing right now and where, the most-used player of "
            "the period (with hours), and one time-of-day habit if history shows it. Visualize "
            "usage per device or the daily pattern — one visual."
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
            "Pull the device-health facts: count of unavailable entities (grouped by likely "
            "device, worst named), batteries below 30% (name + %), pending updates, and the ONE "
            "thing to fix first. Visualize a compact health scoreboard — one visual."
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
            "Pull the automation facts: how many ran in the period (top 3 by count), likely dead "
            "ones (never fire — names), disabled ones, and ONE concrete improvement. Visualize "
            "trigger recency/activity — one visual."
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

SYSTEM_PROMPT = """You are BRain, the AI analyst inside a Home Assistant add-on. You receive a JSON snapshot of the user's smart home and produce ONE insight card: a handful of sharp, specific data points plus one compact self-contained visualization.

You have NO tools available. Never attempt to use tools. Respond with a single JSON object and absolutely nothing else — no markdown fences, no prose before or after.

THE CARD IS A GLANCE, NOT A REPORT. The homeowner reads it in ten seconds on a phone. The highlights ARE the product: concrete numbers with names and times. The summary is one or two short sentences that add the single most important conclusion the numbers alone don't say. Anything long-winded is a failed run.

OUTPUT CONTRACT (strict JSON; title, summary, highlights, and html are required):
{
  "title": "Short punchy card title (max 60 chars)",
  "summary": "1-2 short sentences, max ~220 chars. The ONE thing worth knowing, with its number. No scene-setting, no restating the highlights, no fluff.",
  "highlights": [ {"label": "Metric name", "value": "42 kWh", "delta": "+12% vs avg (optional)", "status": "good|warning|serious|critical (optional)"} ],
  "hypotheses": [ "Optional: something you believe about this home, phrased so it can be answered yes or no" ],
  "learned": [ "Optional: durable facts about this home worth remembering" ],
  "findings": [ {"text": "Short statement of what is broken", "detail": "Evidence: the entity, the number, when it started", "fix": "The specific change that would resolve it", "severity": "info|warning|serious|critical", "fixable": true, "entity_id": "sensor.example (optional)"} ],
  "tags": [ "2-4 short lowercase topic tags" ],
  "html": "<!DOCTYPE html>... one complete self-contained HTML document ..."
}
Provide 3-6 highlights — they are the main content. Each is one specific, checkable data point: a real value with its unit, the entity/room/person it belongs to, and a time when relevant ("Dryer", "3.1 kWh", "+40% vs weekday avg"). Use "delta" for comparison against the period and "status" only when something genuinely deserves attention. Never pad with vague or derived filler ("Overall status", "Things look normal") — fewer sharp highlights beat more dull ones. Escape the HTML correctly as a JSON string.
"tags" (2-4): short lowercase topic tags describing what this card is actually about — single words or hyphenated (e.g. "energy", "anomaly", "batteries", "left-on", "comfort"). Tag by CONTENT, not by the requested category: a lighting card that found a battery problem should carry "batteries" too. The dashboard uses tags to group related cards, so reuse plain common words over inventive ones.
"hypotheses" (optional — usually ZERO, and never more than the prompt's stated budget allows): do NOT ask open questions. Instead, state what you actually BELIEVE, phrased so the homeowner can answer yes or no in one tap: "The garage fridge is meant to run 24/7 — right?" rather than "What is the garage fridge for?".

The bar is high. Propose one only when (a) you genuinely believe it, (b) the data cannot settle it on its own, and (c) knowing would change how you read this home in future. If you would not change your analysis either way, say nothing. Never propose one to seem thorough, never one whose answer is already in the memory document, and never a vague catch-all ("anything else I should know?").

A guess the homeowner confirms becomes a plain remembered fact; one they reject is recorded as a dead end and never revisited. Omitting the field entirely is the normal, expected case.
"learned" (optional, max 3): durable NEW discoveries about this home worth remembering for future analyses — recurring patterns, quirks, how something behaves (e.g. "The dryer draws about 3 kWh per cycle"). One plain factual sentence each, no advice, nothing broken (that is a finding, below). It must be genuinely new: never restate a KNOWN FACT from the prompt, and never restate the current snapshot ("3 lights are on" is a state, not a discovery). Omit when nothing new was learned.
"findings" (optional, max 3): things that are BROKEN and have an owner — a dead battery, a sensor that stopped reporting, a device that is unavailable, an automation that can never fire, a setting that contradicts itself. This is a work list the homeowner acts on, not an observation. The bar:
- Something is actually WRONG. A high reading is not a finding; a sensor that has read exactly the same value for six days is.
- It is specific and checkable: name the entity, the number, and when it started. "Some batteries are low" is not a finding.
- "fix" says what would resolve it, concretely enough to act on ("Replace the CR2032 in the Back Door sensor", "Remove the duplicate 7 AM trigger from automation.morning_lights").
- "fixable" is true ONLY when the fix is a change to Home Assistant that software could make — editing a config or automation, renaming an entity, calling a service. Anything needing hands in the physical world (batteries, unplugging, re-pairing) is false.
- "severity": critical = safety or data loss; serious = something is not working; warning = degraded or will break soon; info = worth tidying.
Do not pad. Most runs find nothing wrong, and an empty list is the honest, expected answer. Never repeat a finding the prompt already lists as reported or dismissed.

THE HTML DOCUMENT:
- ONE focused visual that carries the story — a single chart, timeline, or state map. Not a dashboard: no stat-tile rows duplicating the highlights, no second or third chart unless the story truly needs a side-by-side pair, no prose paragraphs inside the HTML.
- Fully self-contained: inline CSS and JS only. NO external resources (no CDNs, fonts, images, fetch). It renders inside a sandboxed iframe with scripts enabled.
- Responsive: fill 100% width, size height to content (compact — roughly 220-420px). No horizontal scrolling. body{margin:0}.
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
- RUTHLESSLY CONCISE OUTPUT. Every sentence must carry a number, a name, or a time; delete any that doesn't. No hedging ("it appears", "generally"), no methodology talk, no restating what a highlight already says. Depth goes into WHICH data points you surface, never into word count.
- Be specific to this home: use real entity names (their friendly names), real areas, real numbers and times. Convert entity_ids to friendly names in all user-facing text.
- Find the STORY in the data — a trend, an outlier, a pattern, a risk — don't just restate states. Then compress it to its data points.
- REASON LIKE A DETECTIVE, not a meter reader. Cross-reference related entities to reach conclusions no single sensor states outright, and cite the evidence chain. Presence is the canonical example: person.state says "not_home", but the phone's WiFi SSID names the network they're on, the geocoded-address sensor says where, detected activity says whether they're driving or still, and battery/charging state hints at context — combine them ("Ben's phone is on 'OfficeNet' near 5th & Main, stationary, so he's at work") instead of parroting "away". Apply the same rigor everywhere: tie HVAC runtime to room temps and outdoor weather, energy spikes to which device turned on at that minute, lights left on to whether the room saw motion.
- Use the "device_context" section when present: entities that live on the SAME physical device as a presence tracker (d = device name, usually someone's phone). These are your context clues — SSID, geocoded address, activity, battery — group them per device/person.
- BUILD ON what you already know. The prompt may include KNOWN FACTS and ANSWERED QUESTIONS — treat them as established truth: use them to interpret the data, don't rediscover or contradict them without new evidence, and never re-ask what's answered.
- GO DEEPER each run, don't repeat. When the prompt shows your previous analysis of this card, lead with what CHANGED since then and push one level deeper on what didn't — a repeat reading of the same headline is a failed run.
- If the data for the requested angle is thin, say so honestly in the summary and visualize what IS there.
- Times in the data are ISO timestamps in the home's local timezone unless suffixed Z. Present times in a friendly way (e.g. "6:42 PM").
- Never invent data. Every number shown must come from the snapshot."""


# ---------------------------------------------------------------------------
# Prompt assembly
# ---------------------------------------------------------------------------

def _previous_block(previous: dict) -> str:
    """Compact rendering of the last run of this card for the prompt."""
    lines = [
        "YOUR PREVIOUS ANALYSIS of this card"
        + (f" (generated {previous['generated_at']})" if previous.get("generated_at") else "")
        + " — do NOT repeat it. Lead with what changed since then; where nothing "
        "changed, dig one level deeper instead of restating:",
    ]
    if previous.get("title"):
        lines.append(f"- Title: {previous['title']}")
    if previous.get("summary"):
        lines.append(f"- Summary: {previous['summary']}")
    hls = [
        f"{h.get('label')}: {h.get('value')}"
        for h in (previous.get("highlights") or [])
        if isinstance(h, dict) and h.get("label")
    ]
    if hls:
        lines.append(f"- Highlights: {'; '.join(hls)}")
    for f in previous.get("learned") or []:
        if isinstance(f, str) and f.strip():
            lines.append(f"- Already learned: {f.strip()}")
    return "\n".join(lines)


def build_prompt(
    category: dict,
    bundle: dict,
    question: str | None = None,
    feedback: list[str] | None = None,
    knowledge: str | None = None,
    previous: dict | None = None,
    hypothesis_budget: int = 0,
    findings: str | None = None,
) -> str:
    """Assemble the user prompt: analysis focus + the data bundle.

    ``feedback`` is the homeowner's standing feedback on earlier versions of
    this card — injected as instructions the new insight must honor.
    ``knowledge`` is the rendered knowledge-store block (rejected lines of
    inquiry only — facts live in the memory document and are injected from
    there). ``hypothesis_budget`` is how many guesses the analyst may still
    propose; at zero it is told to propose none, which is what keeps the
    queue from growing into the wall of open questions this replaced.
    ``previous`` is the last stored run of this card, injected so the
    analyst advances the story instead of regenerating it.
    ``findings`` is the rendered findings block: what is already on the work
    list, and what the homeowner dismissed as not a problem here.
    """
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

    cleaned_feedback = [f.strip() for f in (feedback or []) if f and f.strip()]
    if cleaned_feedback:
        parts.append(
            "\nHOMEOWNER FEEDBACK on earlier versions of this card — standing "
            "instructions you MUST honor in this run (adjust the analysis, "
            "wording, and visualization accordingly):\n"
            + "\n".join(f"- {f}" for f in cleaned_feedback)
        )

    if knowledge and knowledge.strip():
        parts.append("\n" + knowledge.strip())

    if findings and findings.strip():
        parts.append("\n" + findings.strip())

    # The budget is stated explicitly rather than left implicit: a model told
    # only "usually zero" still proposes one most runs, and three cards each
    # proposing one is how the old question list grew without bound.
    if hypothesis_budget <= 0:
        parts.append(
            "\nHYPOTHESIS BUDGET: 0. The homeowner already has guesses waiting on them. "
            "Propose NONE this run — omit the \"hypotheses\" field entirely."
        )
    else:
        parts.append(
            f"\nHYPOTHESIS BUDGET: {hypothesis_budget}. You may propose at most "
            f"{hypothesis_budget}, and only if one genuinely clears the bar. Zero is "
            "still the expected outcome for most runs."
        )

    if previous:
        parts.append("\n" + _previous_block(previous))

    parts.append(
        "\nHOME DATA SNAPSHOT (JSON). Sections: meta (now, timezone, location name), areas, "
        "entities (e=entity_id, s=state, n=friendly name, a=area, u=unit, dc=device_class, "
        "lc=last_changed, x=extra attributes), device_context (entities sharing a physical "
        "device with a presence tracker — phone SSID/geocoded address/activity/battery; "
        "d=device name), history (per entity: h=[[time, value|state], ...] downsampled), "
        "statistics (per entity hourly sum/mean), context (optional notes about this home)."
    )
    parts.append(json.dumps(bundle, ensure_ascii=False, separators=(",", ":")))
    parts.append(
        "\nNow produce the single JSON insight object per the contract. Remember: JSON only, "
        "no fences, no commentary."
    )
    return "\n".join(parts)
