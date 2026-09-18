"""Insight category definitions and prompt construction for brAIn.

Each category declares which slices of Home Assistant data it wants (domains,
device classes, whether it needs history / long-term statistics) and the
analytical focus Claude should take. ``build_prompt`` turns a collected data
bundle into the final generation prompt, and ``SYSTEM_PROMPT`` carries the
strict output contract plus the visualization design system the generated
HTML must follow.

This module is dependency-free so the test suite can import it directly.
"""
from __future__ import annotations

import re

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
            "device) if the data shows one. Where you can reach long-term statistics, anchor "
            "the story against a longer horizon — this week vs last week, or this month vs "
            "last month — using Home Assistant's own daily/monthly sums rather than "
            "extrapolating from a few days. Visualize ONE chart — the daily trend, the "
            "top-consumers ranking, or the period-over-period comparison, whichever carries "
            "this run's story."
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

# Which of brAIn's own measurements bear on each shipped card.
#
# Read by the refresh gate, not by the prompt: a card whose measurements
# have not moved has nothing new to say from them, and a card that reads
# none of them is not held up by one being rebuilt. Anything NOT named
# here — a user category, a typed question — reads every measurement,
# because it could be about any of them, which is the same conservatism
# `collect_bundle` applies to a question's entity slice.
CATEGORY_STORES: dict[str, tuple[str, ...]] = {
    "overview": ("rhythm", "baselines", "habits"),
    "energy": ("energy", "baselines", "appliances"),
    "climate": ("thermal", "baselines", "closures"),
    "lighting": ("rhythm", "habits"),
    "security": ("closures", "rhythm"),
    "presence": ("rhythm", "habits"),
    "automations": ("habits", "rhythm"),
    "devices": ("baselines", "appliances"),
    "maintenance": ("baselines", "appliances", "thermal"),
}


def stores_for(cat_id: str) -> tuple[str, ...] | None:
    """The measurements this card reads, or None for "all of them"."""
    return CATEGORY_STORES.get(cat_id)


def get_category(cat_id: str) -> dict | None:
    for c in CATEGORIES:
        if c["id"] == cat_id:
            return c
    return None


# ---------------------------------------------------------------------------
# What brAIn has already measured, as a block in a prompt
# ---------------------------------------------------------------------------
# The analyst used to be told about the house and never about brAIn: it
# was handed entities and history and no hint that seven measurements had
# already been made over the same data, so it re-derived "what is normal
# here" from a week of readings on every run and reached a different
# answer each time. This is the block that stops that.
#
# It is a BUDGET rather than a section: 2 KB, taken from nothing else.
# Memory has its own budget in the bundle (`ha_data.MEMORY_CHARS`) and the
# findings block has no cap at all, and this must not be able to push
# either of them out — the failure that argument comes from is the one
# where memory and the house context split 4 KB and both arrived
# truncated.
HOUSE_CHARS = 2_000

# What the brief and the weekly report get of the memory document. They
# are handed a couple of paragraphs each, not the 34 KB the insight
# bundle carries: what a lock-screen message needs from memory is the
# handful of standing preferences at the top of the document, and the
# rest is what makes it a report.
MEMORY_EXCERPT_CHARS = 2_000

_HOUSE_HEAD = (
    "WHAT brAIn HAS ALREADY MEASURED ABOUT THIS HOUSE. These are its own "
    "numbers, computed overnight from months of history — use them rather "
    "than re-deriving them from the data below, and do not report them "
    "back as discoveries. Each name is a measurement you can read in full "
    "with the get_house_model tool. A measurement that is NOT listed here "
    "has not been made yet, and its silence is not evidence that nothing "
    "is wrong:")


def house_block(snapshot: dict | None, limit: int = HOUSE_CHARS) -> str:
    """The measurements that have an answer, one sentence each.

    Only `ready` stores. A store that is still collecting, that this house
    cannot supply, or that has stopped being rebuilt has no number worth
    acting on, and a line saying so would spend the budget telling the
    analyst about brAIn rather than about the house — the drill-down is
    what `get_house_model` is for. Nothing ready means no block at all,
    which is a fresh install and is exactly the case where an empty
    heading would read as "measured, and nothing found".

    The sentence is the STORE's own (`progress()["summary"]`), never one
    composed here: every floor and every caveat in it belongs to the
    module that owns the measurement, and a second wording is a second
    answer to what a house is like.

    Whole lines are dropped to fit rather than the text being cut, because
    half a measurement reads exactly like a whole one.
    """
    stores = (snapshot or {}).get("stores") or {}
    lines: list[str] = []
    for name, entry in stores.items():
        if not isinstance(entry, dict) or entry.get("state") != "ready":
            continue
        said = " ".join(str(entry.get("summary") or "").split())
        if said:
            lines.append(f"- {name}: {said}")
    if not lines:
        return ""
    out = [_HOUSE_HEAD]
    used = len(_HOUSE_HEAD)
    for line in lines:
        if used + len(line) + 1 > limit:
            break
        out.append(line)
        used += len(line) + 1
    return "\n".join(out)


def memory_excerpt(text: str | None, limit: int = MEMORY_EXCERPT_CHARS) -> str:
    """The head of the memory document, cut at a line boundary.

    The brief and the weekly report read no memory at all today, which is
    why both of them can say something the homeowner has already
    corrected. They get the top of the document — where the consolidator
    keeps the standing facts — and the cut is made between lines, since a
    fact truncated mid-sentence is a fact stated wrongly.
    """
    body = (text or "").strip()
    if not body:
        return ""
    if len(body) > limit:
        body = body[:limit].rsplit("\n", 1)[0].rstrip()
    if not body:
        return ""
    return ("WHAT IS ALREADY KNOWN ABOUT THIS HOME — the homeowner's own "
            "standing facts and preferences. Do not contradict them, and "
            "do not repeat them back:\n" + body)


# ---------------------------------------------------------------------------
# Output contract + design system (given to Claude as the system prompt)
# ---------------------------------------------------------------------------
# The palette and mark rules follow a validated, colorblind-safe data-viz
# design system: categorical hues assigned in fixed order (never cycled),
# one hue light→dark for magnitude, blue↔red for polarity, reserved status
# colors, one axis per chart, thin marks, legends for ≥2 series.

# The card contract — the output shape, the design system, the analysis
# rules — is one document with two preambles in front of it. How the data
# arrived (posted whole, or fetched by the model) changes the first two
# paragraphs and nothing else, and a second copy of a 10 KB contract is a
# second copy that drifts.
# The card's look, as a stylesheet rather than as prompt text.
#
# Until 2.0 the palette below rode inside `_CARD_CONTRACT` as ~1.5 KB of
# hex values and mark rules, re-sent on every card, milestone and
# onboarding run and re-typed by the model into every card's own CSS. It
# is CSS, so it is a stylesheet now: `inject_styles` prepends it to the
# HTML a run returns at the moment the card is saved, which keeps every
# card self-contained wherever it is rendered (the panel's frame, the
# dashboard mirror, a card kept in history) while the model is told only
# the variable names. A card from before 2.0 carries its own colours and
# is left exactly as it was.
CARD_STYLES = """:root{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--c1:#2a78d6;--c2:#008300;--c3:#e87ba4;--c4:#eda100;--c5:#1baf7a;--c6:#eb6834;--c7:#4a3aa7;--c8:#e34948;--other:#898781;
--seq-lo:#cde2fb;--seq-hi:#0d366b;--div-mid:#f0efec;
--good:#0ca30c;--warning:#fab219;--serious:#ec835a;--critical:#d03b3b;color-scheme:light dark}
@media (prefers-color-scheme: dark){:root{--bg:#1a1a19;--ink:#ffffff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--c1:#3987e5;--c2:#008300;--c3:#d55181;--c4:#c98500;--c5:#199e70;--c6:#d95926;--c7:#9085e9;--c8:#e66767;--div-mid:#383835}}
body{margin:0;background:var(--bg);color:var(--ink);font-family:system-ui,sans-serif}
.tabular{font-variant-numeric:tabular-nums}
@media (prefers-reduced-motion: reduce){*{animation:none!important;transition:none!important}}
"""

STYLE_TAG = '<style data-brain="card-styles">' + CARD_STYLES + '</style>'


def inject_styles(html: str) -> str:
    """The card's HTML with CARD_STYLES prepended, once.

    Goes just inside `<head>` when there is one, else at the top, so the
    card's own rules (which come later) still win where they disagree —
    the sheet supplies variables and a body default, never an override.
    Idempotent, because a card is re-saved by several routes.
    """
    text = str(html or "")
    if not text.strip() or 'data-brain="card-styles"' in text:
        return text
    match = re.search(r"<head[^>]*>", text, re.IGNORECASE)
    if match:
        return text[:match.end()] + STYLE_TAG + text[match.end():]
    return STYLE_TAG + text


# The reply as the CLI validates it (`--json-schema`). It is the OUTPUT
# CONTRACT below, enforced: a run that carries it cannot come back with
# a card missing its title or with `findings` as prose. The prose stays
# because a CLI without the flag still has to be told, and because the
# rules under each field are judgement the schema cannot hold.
CARD_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "delta": {"type": "string"},
                    "status": {"type": "string",
                               "enum": ["good", "warning", "serious", "critical"]},
                },
                "required": ["label", "value"],
                "additionalProperties": False,
            },
        },
        "hypotheses": {"type": "array", "items": {"type": "string"}},
        "learned": {"type": "array", "items": {"type": "string"}},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "detail": {"type": "string"},
                    "fix": {"type": "string"},
                    "severity": {"type": "string",
                                 "enum": ["info", "warning", "serious", "critical"]},
                    "fixable": {"type": "boolean"},
                    "entity_id": {"type": "string"},
                },
                "required": ["text", "severity"],
                "additionalProperties": False,
            },
        },
        "tags": {"type": "array", "items": {"type": "string"}},
        "live": {"type": "array", "items": {"type": "string"}},
        "html": {"type": "string"},
    },
    "required": ["title", "summary", "highlights", "html"],
    "additionalProperties": False,
}


_CARD_CONTRACT = """THE CARD IS A GLANCE, NOT A REPORT. The homeowner reads it in ten seconds on a phone. The highlights ARE the product: concrete numbers with names and times. The summary is one or two short sentences that add the single most important conclusion the numbers alone don't say. Anything long-winded is a failed run.

OUTPUT CONTRACT (strict JSON; title, summary, highlights and html are required):
{"title": "max 60 chars", "summary": "1-2 sentences, max ~220 chars — the ONE thing worth knowing, with its number",
 "highlights": [{"label": "Metric", "value": "42 kWh", "delta": "+12% vs avg (optional)", "status": "good|warning|serious|critical (optional)"}],
 "hypotheses": ["optional, usually none"], "learned": ["optional, max 3"],
 "findings": [{"text": "ONE sentence, under 120 chars", "detail": "the evidence", "fix": "the specific change", "severity": "info|warning|serious|critical", "fixable": true, "entity_id": "sensor.example (optional)"}],
 "tags": ["2-4 lowercase topic tags"], "live": ["optional entity_ids to keep current"], "html": "one complete self-contained HTML document"}

highlights: 3-6, each one specific, checkable data point with its unit, the entity/room/person it belongs to, and a time when relevant. "delta" compares against the period; "status" only when something genuinely deserves attention. Never pad with filler ("Overall status", "Things look normal") — fewer sharp highlights beat more dull ones. Escape the HTML correctly as a JSON string.
tags: what the card is actually ABOUT, not the category it was asked for — a lighting card that found a battery problem carries "batteries" too. Reuse plain common words.
hypotheses: usually ZERO, never more than the prompt's stated budget. Not an open question — something you actually BELIEVE, phrased so the homeowner can answer yes or no in one tap ("The garage fridge is meant to run 24/7 — right?"). Only when you believe it, the data cannot settle it, and knowing would change how you read this home; never one already answered in the memory document. A confirmed guess becomes a remembered fact; a rejected one is a dead end never revisited.
learned: durable NEW discoveries about this home (a pattern, a quirk, how something behaves — "The dryer draws about 3 kWh per cycle"), one plain factual sentence each, no advice, nothing broken. Never a KNOWN FACT restated, never the current snapshot ("3 lights are on" is a state).
findings: things that are BROKEN and have an owner — a dead battery, a sensor that stopped reporting, an unavailable device, an automation that can never fire, a setting that contradicts itself. A work list, not observations. Something is actually WRONG (a high reading is not a finding; a value unchanged for six days is); it names the entity, the number and when it started; "fix" is concrete enough to act on; "fixable" is true ONLY when software could make the change (editing a config, renaming, calling a service — never batteries, unplugging, re-pairing). severity: critical = safety or data loss; serious = not working; warning = degraded or will break soon; info = worth tidying. Most runs find nothing wrong and an empty list is the honest answer. Never repeat a finding the prompt lists as reported or dismissed.
live: max 12 entity_ids whose CURRENT state the visualization should keep up to date, ONLY when watching it change is part of the story (a door that is open, a machine running, a temperature being held). brAIn injects `window.brainLive(callback)` into the page: register once and you are handed {entity_id: {state, attributes, unit, name}} immediately and on every refresh — but the page must render correctly with NO live data at all, so draw the snapshot values first and let the callback update them. Never poll or fetch. Omit the field for a period that has ended, which is most cards.

THE HTML DOCUMENT:
- ONE focused visual that carries the story — a single chart, timeline or state map. No stat-tile rows duplicating the highlights, no second chart unless the story needs a pair, no prose inside the HTML.
- Self-contained: inline CSS and JS only, no external resources. It renders in a sandboxed iframe with scripts enabled. Fill 100% width, height to content (~220-420px), no horizontal scrolling. Inline SVG (or CSS grid for state maps); no canvas libraries.
- Interactive: hover tooltips on every mark, hit targets larger than the mark; everything must also read fine without hovering. Tasteful draw-in on load (≤800ms) inside @media (prefers-reduced-motion: no-preference).

DESIGN SYSTEM: brAIn prepends a stylesheet to your document, so use its variables and never hard-code a colour — both light and dark mode (prefers-color-scheme) then come for free. Surfaces and text: var(--bg), var(--ink), var(--ink2), var(--muted); gridlines var(--grid), axis var(--axis). Series colours in this fixed order: var(--c1) (blue, #2a78d6 in light) … var(--c8); past six series fold the rest into var(--other). Sequential: one hue from var(--seq-lo) to var(--seq-hi); diverging: --c1 ↔ --c8 through var(--div-mid); never rainbow. Status: var(--good), var(--warning), var(--serious), var(--critical) — reserved, never used as series, always paired with a label. Dark surface is #1a1a19. Marks: 2px lines; bars flat at the baseline with 4px rounded tops; ≥8px hover markers; a 2px surface gap between stacked segments. ONE y-axis per chart (two scales → two small charts). Legend when ≥2 series, direct labels when ≤4, label selectively; text is always ink-coloured. Bars start at zero. No chart junk, no drop shadows. Use class "tabular" for aligned numbers.

ANALYSIS RULES:
- RUTHLESSLY CONCISE. Every sentence carries a number, a name or a time; delete any that doesn't. No hedging, no methodology, no restating a highlight. Depth goes into WHICH data points you surface, never into word count.
- Be specific to this home: real friendly names, real areas, real numbers and times. Convert entity_ids to friendly names in all user-facing text.
- Find the STORY — a trend, an outlier, a pattern, a risk — then compress it to its data points.
- REASON LIKE A DETECTIVE, not a meter reader. Cross-reference related entities to reach conclusions no single sensor states outright, and cite the chain: a phone on "OfficeNet" near 5th & Main and stationary means at work, not "away"; tie HVAC runtime to room temps and weather, an energy spike to the device that turned on at that minute, a light left on to whether the room saw motion. Use the "device_context" section (entities on the same physical device as a presence tracker) as those clues.
- BUILD ON what you know: KNOWN FACTS and ANSWERED QUESTIONS in the prompt are established truth — use them, never rediscover or contradict them without new evidence, never re-ask.
- GO DEEPER each run: when the prompt shows your previous analysis, lead with what CHANGED and push one level deeper on what didn't — a repeat of the same headline is a failed run.
- If the data for the requested angle is thin, say so in the summary and visualize what IS there.
- Times in the data are ISO timestamps in the home's local timezone unless suffixed Z; present them in a friendly way ("6:42 PM").
- Never invent data. Every number shown must come from the data you were given or fetched."""


SYSTEM_PROMPT = """You are brAIn, the AI analyst inside a Home Assistant add-on. You receive a JSON snapshot of the user's smart home and produce ONE insight card: a handful of sharp, specific data points plus one compact self-contained visualization.

You have NO tools available. Never attempt to use tools. Respond with a single JSON object and absolutely nothing else — no markdown fences, no prose before or after.

""" + _CARD_CONTRACT


ANALYST_SYSTEM = """You are brAIn, the AI analyst inside a Home Assistant add-on. You produce ONE insight card: a handful of sharp, specific data points plus one compact self-contained visualization.

You do NOT receive the home up front. You receive a MAP of it — how many entities of each domain exist, which areas they sit in, and a few anchor entities — and you have read-only Home Assistant tools to go and fetch whatever the question actually needs. Work the way a person would: decide what you need, look it up, follow what you find.

HOW TO GATHER
1. Read the map and the question, and decide what data would answer it. Name it to yourself before you fetch anything.
2. Search, don't enumerate. `get_all_states` takes a `domain` and a `name_filter` substring — "hall", "battery", "dryer" — and returns matching entities with their states. Two or three targeted searches beat one broad sweep, and a broad sweep of a large home is truncated anyway.
3. Go deeper on the few that matter rather than shallow on hundreds. `get_entity_state` gives one entity in full; `get_history` and `get_statistics` give it over time; `get_logbook` says what happened around a moment; `get_automation_trace` says why an automation did what it did. Trend data is the thing a snapshot cannot give you — use it.
   Know which time tool answers which question. `get_history` is the recent fine grain and dies with the recorder's purge window (days). `get_statistics` is Home Assistant's long-term statistics — hourly/daily/weekly/monthly buckets, kept for months to years, surviving the purge — so it is THE tool for "compared to last week/month", seasonal patterns, and any energy total. Home Assistant already keeps those sums; fetch them rather than estimating from a few days, and never say "no long-term data" without having asked `get_statistics` with a `day` or `month` period and enough `days` back.
4. STOP when you can answer. Every extra call costs the homeowner part of their Claude usage window, and a card built on twelve well-chosen entities beats one built on four hundred. Fetching everything is the failure mode this design exists to avoid.
5. If a search comes back empty, try a different word before concluding the thing does not exist — homes name things unpredictably. If it genuinely is not there, say so in the summary rather than inventing it.

You can only READ. There is no tool here that changes anything in the house, by design — if answering seems to need a change, that is a finding, not something you do.

When you have what you need, respond with a single JSON object and absolutely nothing else — no markdown fences, no prose before or after.

""" + _CARD_CONTRACT


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


def _framing(
    category: dict,
    question: str | None,
    feedback: list[str] | None,
    knowledge: str | None,
    findings: str | None,
    hypothesis_budget: int,
    previous: dict | None,
    house: str | None = None,
) -> list[str]:
    """Everything the analyst is told before it is told about the data.

    Shared by both prompt builders on purpose: what the card is for, what the
    homeowner has said about it, what is already known, what is already on
    the work list and how many guesses are left do not depend on whether the
    data was posted whole or fetched by the model. Only the section after
    this differs, and keeping one copy is what stops the searching path
    quietly losing a rule the single-shot path enforces.
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

    # What brAIn measured, before what brAIn was told and before what is
    # already on the work list: a reading is only unusual against a
    # baseline, and a card that reports one without checking is the
    # commonest thing a homeowner marks Wrong.
    if house and house.strip():
        parts.append("\n" + house.strip())

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

    return parts


def build_prompt(
    category: dict,
    bundle: dict,
    question: str | None = None,
    feedback: list[str] | None = None,
    knowledge: str | None = None,
    previous: dict | None = None,
    hypothesis_budget: int = 0,
    findings: str | None = None,
    house: str | None = None,
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
    parts = _framing(category, question, feedback, knowledge, findings,
                     hypothesis_budget, previous, house)
    parts.append(
        "\nHOME DATA SNAPSHOT (JSON). Sections: meta (now, timezone, location name), areas, "
        "entities (e=entity_id, s=state, n=friendly name — ABSENT when it is just the "
        "entity_id prettified, so read the id in that case, a=area, u=unit, dc=device_class, "
        "lc=MINUTES since it last changed, x=extra attributes; an unavailable or unknown "
        "entity carries only e/s/a because it has no reading to describe), device_context "
        "(entities sharing a physical "
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


def build_orientation_prompt(
    category: dict,
    orientation: dict,
    question: str | None = None,
    feedback: list[str] | None = None,
    knowledge: str | None = None,
    previous: dict | None = None,
    hypothesis_budget: int = 0,
    findings: str | None = None,
    house: str | None = None,
) -> str:
    """The searching path's prompt: the map, not the territory.

    Every framing block is the same as ``build_prompt`` — the question, the
    homeowner's feedback, what is already known, what is already on the work
    list, the previous run — because none of that depends on how the data
    arrives. What changes is the last section: a map of the home and an
    instruction to go and get what answering it needs.
    """
    parts = _framing(category, question, feedback, knowledge, findings,
                     hypothesis_budget, previous, house)
    parts.append(
        "\nMAP OF THIS HOME (JSON). NOT the data — the shape of it. Sections: meta (now, "
        "timezone, location name), entity_count (how many entities exist in total), "
        "unavailable_count, domains (domain -> how many entities of it exist), areas "
        "(area name -> how many entities are in it), anchors (the few people/climate/"
        "weather/alarm entities named in full, because nearly every question touches "
        "them; same field shorthand as a snapshot row — e=entity_id, s=state, n=friendly "
        "name when it is not just the id prettified, a=area, u=unit, dc=device_class, "
        "lc=MINUTES since it last changed, x=extra attributes), context (optional notes "
        "about this home)."
    )
    parts.append(json.dumps(orientation, ensure_ascii=False, separators=(",", ":")))
    parts.append(
        "\nUse your Home Assistant tools to fetch what answering this actually needs — "
        "search by domain and by name, then go deep on the few entities that matter, "
        "including their history. Then produce the single JSON insight object per the "
        "contract. Remember: JSON only, no fences, no commentary."
    )
    return "\n".join(parts)
