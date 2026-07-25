"""Global runtime settings for BRUH Insights.

One JSON file (atomic tmp+replace, like insight storage) holds the settings
the panel's ⚙ dialog edits at runtime — no add-on restart needed:

  auto_enabled    — master switch. False pauses ALL scheduled generation
                    (manual "Generate"/"Refresh all" still work — clicking a
                    button is an explicit ask).
  plan            — the user's Claude subscription: "pro" | "max5" | "max20".
                    Used to estimate the 5-hour session token allowance when
                    real account utilization isn't available.
  budget_percent  — how much of each 5-hour session window Insights may
                    consume before auto-refresh pauses (5-100).

It also holds runtime overrides of the add-on's Configuration-tab options
(so they are editable from the panel without a restart). Each is None when
unset, meaning "use the add-on configuration value":

  refresh_hours      — default interval for cards without their own (0-168)
  history_days       — days of history/statistics per analysis (1-30)
  history_keep_runs  — past runs kept per category (0-200)
  history_keep_days  — days past runs are kept (0-365)
  model              — Claude model override ("" is treated as unset)
  timeout_minutes    — per-generation hard timeout (2-30)

File shape: {"auto_enabled": true, "plan": "pro", "budget_percent": 25,
"refresh_hours": 12, ...} — option keys may be absent or null (= unset).
Missing or corrupt files fall back to defaults, and unknown keys are ignored.

This module deliberately avoids aiohttp so the test suite can import it
without the add-on runtime.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

SETTINGS_FILE = os.environ.get("BRUH_INSIGHTS_SETTINGS_FILE", "/data/settings.json")

PLANS = ("pro", "max5", "max20")

# Runtime-overridable add-on options: name → allowed integer range.
# None (or absent) = use the value from the add-on's Configuration tab.
OPTION_RANGES = {
    "refresh_hours": (0, 168),
    "history_days": (1, 30),
    "history_keep_runs": (0, 200),
    "history_keep_days": (0, 365),
    "timeout_minutes": (2, 30),
}
MAX_MODEL_CHARS = 100

DEFAULTS = {
    "auto_enabled": True,
    "plan": "pro",
    "budget_percent": 25,
    "refresh_hours": None,
    "history_days": None,
    "history_keep_runs": None,
    "history_keep_days": None,
    "model": None,
    "timeout_minutes": None,
}

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")
MAX_SCHEDULE_TIMES = 6


def load() -> dict:
    """The effective settings — stored values over defaults."""
    out = dict(DEFAULTS)
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    if isinstance(data.get("auto_enabled"), bool):
        out["auto_enabled"] = data["auto_enabled"]
    if data.get("plan") in PLANS:
        out["plan"] = data["plan"]
    pct = data.get("budget_percent")
    if isinstance(pct, int) and not isinstance(pct, bool) and 5 <= pct <= 100:
        out["budget_percent"] = pct
    for name, (lo, hi) in OPTION_RANGES.items():
        val = data.get(name)
        if isinstance(val, int) and not isinstance(val, bool) and lo <= val <= hi:
            out[name] = val
    model = data.get("model")
    if isinstance(model, str) and model.strip():
        out["model"] = model.strip()[:MAX_MODEL_CHARS]
    return out


def save(fields: dict) -> dict:
    """Merge validated fields into the stored settings; returns the result.

    Raises ValueError on invalid input. Unknown keys are rejected so typos
    surface instead of silently doing nothing.
    """
    clean: dict = {}
    for key, value in fields.items():
        if key == "auto_enabled":
            if not isinstance(value, bool):
                raise ValueError("auto_enabled must be a boolean")
            clean[key] = value
        elif key == "plan":
            if value not in PLANS:
                raise ValueError(f"plan must be one of {', '.join(PLANS)}")
            clean[key] = value
        elif key == "budget_percent":
            if not isinstance(value, int) or isinstance(value, bool) \
                    or not 5 <= value <= 100:
                raise ValueError("budget_percent must be an integer 5-100")
            clean[key] = value
        elif key in OPTION_RANGES:
            lo, hi = OPTION_RANGES[key]
            if value is not None and (
                    not isinstance(value, int) or isinstance(value, bool)
                    or not lo <= value <= hi):
                raise ValueError(f"{key} must be an integer {lo}-{hi} or null")
            clean[key] = value
        elif key == "model":
            if value is not None and not isinstance(value, str):
                raise ValueError("model must be a string or null")
            value = (value or "").strip()[:MAX_MODEL_CHARS]
            clean[key] = value or None
        else:
            raise ValueError(f"unknown setting: {key}")
    merged = {**load(), **clean}
    path = Path(SETTINGS_FILE)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return merged


def clean_schedule(value) -> list[str] | None:
    """Validate a per-category run schedule: a list of "HH:MM" times.

    Returns a normalized, sorted, de-duplicated list ("7:30" → "07:30"),
    None for null/empty (= no schedule), and raises ValueError otherwise.
    Shared by prompt_store overrides and user_categories.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("schedule must be a list of HH:MM times or null")
    times: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("schedule times must be strings like \"07:30\"")
        m = _TIME_RE.match(item.strip())
        if not m:
            raise ValueError(f"bad schedule time {item!r} — use 24h HH:MM")
        norm = f"{int(m.group(1)):02d}:{m.group(2)}"
        if norm not in times:
            times.append(norm)
    if len(times) > MAX_SCHEDULE_TIMES:
        raise ValueError(f"at most {MAX_SCHEDULE_TIMES} schedule times")
    return sorted(times) or None
