"""Global runtime settings for brAIn.

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
  terminal_ui     — which face the Terminal tab wears: "chat" (Claude Code
                    rendered as messages) or "classic" (ttyd + tmux, the
                    character grid). Both drive the same CLI with the same
                    permissions; the difference is entirely presentation.
  chat_max_sessions — how many chat conversations may hold a live Claude
                    Code process at once (1-8, default 3). Switching
                    between conversations stops nothing, so this is the
                    number of processes the box carries, not the number of
                    conversations you may have: past it, the least
                    recently active IDLE one is stopped and reopens with
                    --resume.
  capture         — whether every card run writes what the analyst was
                    sent and what it answered to /data/capture, so a
                    prompt change can be scored against real houses. OFF
                    by default: a house's entity names are a floor plan,
                    and nothing leaves the add-on until a person exports
                    one from ⚙ → Diagnostics.
  chat_model      — the chat terminal's own model, chosen from the chat
                    itself. None means "follow the global model option":
                    the chat is where a different model is most often
                    wanted for one conversation, and making that choice
                    global would silently change what every insight run
                    costs.

It can also hold the add-on's Configuration-tab options, but only as a
FALLBACK: those six settings normally live in the add-on's own options via
the Supervisor (see addon_options.py), so the panel and the Configuration
tab always agree. When the Supervisor isn't reachable the panel stores them
here instead; each is None when unset, meaning "use the startup value":

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

import atomic_write

SETTINGS_FILE = os.environ.get("BRAIN_SETTINGS_FILE", "/data/settings.json")

PLANS = ("pro", "max5", "max20")

# The Terminal tab's two faces. "chat" is the default because it is the
# one that works on the device most people open the panel on; the grid is
# still there, one press away, for everything a grid is actually for.
TERMINAL_UIS = ("chat", "classic")

# How a run gets its data. "search" is the default because posting five
# hundred entities to answer a question about one room is the expensive
# thing this add-on does; "snapshot" is the old single-turn path, kept as a
# setting AND as the automatic fallback when a search run fails.
GATHER_MODES = ("search", "snapshot")

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

# The chat's live-process cap. A range rather than a free integer for the
# same reason budget_percent has one: the low end has to leave the chat
# usable and the high end has to leave the box usable.
CHAT_SESSIONS_RANGE = (1, 8)
DEFAULT_CHAT_SESSIONS = 3

DEFAULTS = {
    # A fresh install has no cards and no schedule. brAIn studies the home
    # first, then proposes cards grounded in what it actually found — a
    # generic "Climate" card on an unknown house says nothing useful.
    "onboarded": False,
    "auto_enabled": True,
    # How an insight run gets its data.
    #   "search" — Claude is given a MAP of the home (domain counts, areas, a
    #              few anchors) plus read-only Home Assistant tools, and
    #              fetches what the question actually needs. Far cheaper on a
    #              targeted question, and the only path that can afford
    #              history on one.
    #   "snapshot" — the whole slimmed home is posted up front, one turn, no
    #              tools. Deterministic and the fallback whenever a search
    #              run fails, so nothing depends on the model behaving.
    "gather_mode": "search",
    "plan": "pro",
    "budget_percent": 25,
    "terminal_ui": "chat",
    "refresh_hours": None,
    "history_days": None,
    "history_keep_runs": None,
    "history_keep_days": None,
    "model": None,
    "timeout_minutes": None,
    "chat_model": None,
    "chat_max_sessions": DEFAULT_CHAT_SESSIONS,
    # See the module docstring. A settings key rather than a config.yaml
    # option because it is switched on while looking at the panel, for a
    # week, and then off again — a Configuration-tab option would cost a
    # restart at each end of that.
    "capture": False,
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
    if isinstance(data.get("onboarded"), bool):
        out["onboarded"] = data["onboarded"]
    if isinstance(data.get("auto_enabled"), bool):
        out["auto_enabled"] = data["auto_enabled"]
    if isinstance(data.get("capture"), bool):
        out["capture"] = data["capture"]
    if data.get("plan") in PLANS:
        out["plan"] = data["plan"]
    if data.get("terminal_ui") in TERMINAL_UIS:
        out["terminal_ui"] = data["terminal_ui"]
    if data.get("gather_mode") in GATHER_MODES:
        out["gather_mode"] = data["gather_mode"]
    pct = data.get("budget_percent")
    if isinstance(pct, int) and not isinstance(pct, bool) and 5 <= pct <= 100:
        out["budget_percent"] = pct
    for name, (lo, hi) in OPTION_RANGES.items():
        val = data.get(name)
        if isinstance(val, int) and not isinstance(val, bool) and lo <= val <= hi:
            out[name] = val
    lo, hi = CHAT_SESSIONS_RANGE
    sessions = data.get("chat_max_sessions")
    if isinstance(sessions, int) and not isinstance(sessions, bool) \
            and lo <= sessions <= hi:
        out["chat_max_sessions"] = sessions
    for key in ("model", "chat_model"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()[:MAX_MODEL_CHARS]
    return out


def clean_option(key: str, value):
    """Validate one Configuration-tab option; returns the stored form.

    None means "unset" for every option, and an empty/blank model string
    normalizes to None. Raises ValueError on anything else out of range.
    Shared with the add-on-options path so both surfaces enforce exactly
    the ranges declared in config.yaml's schema.
    """
    if key in OPTION_RANGES:
        lo, hi = OPTION_RANGES[key]
        if value is not None and (
                not isinstance(value, int) or isinstance(value, bool)
                or not lo <= value <= hi):
            raise ValueError(f"{key} must be an integer {lo}-{hi} or null")
        return value
    if key == "model":
        if value is not None and not isinstance(value, str):
            raise ValueError("model must be a string or null")
        return (value or "").strip()[:MAX_MODEL_CHARS] or None
    raise ValueError(f"unknown option: {key}")


def is_option(key: str) -> bool:
    """True for the settings that mirror an add-on Configuration option."""
    return key in OPTION_RANGES or key == "model"


def option_overrides() -> dict:
    """Stored option overrides that are actually set (for migration)."""
    stored = load()
    return {k: stored[k] for k in DEFAULTS
            if is_option(k) and stored.get(k) is not None}


def clear_option_overrides() -> None:
    """Drop every stored option override, keeping the panel-only settings.

    Called once the values have been promoted into the add-on's own
    options, so there is exactly one place they can come from.
    """
    merged = {k: v for k, v in load().items() if not is_option(k)}
    _write(merged)


def save(fields: dict) -> dict:
    """Merge validated fields into the stored settings; returns the result.

    Raises ValueError on invalid input. Unknown keys are rejected so typos
    surface instead of silently doing nothing.
    """
    clean: dict = {}
    for key, value in fields.items():
        if key == "onboarded":
            # Set by the first-run flow, not by the Settings dialog. It
            # gates whether this home has any cards at all.
            if not isinstance(value, bool):
                raise ValueError("onboarded must be a boolean")
            clean[key] = value
        elif key == "auto_enabled":
            if not isinstance(value, bool):
                raise ValueError("auto_enabled must be a boolean")
            clean[key] = value
        elif key == "capture":
            if not isinstance(value, bool):
                raise ValueError("capture must be a boolean")
            clean[key] = value
        elif key == "plan":
            if value not in PLANS:
                raise ValueError(f"plan must be one of {', '.join(PLANS)}")
            clean[key] = value
        elif key == "gather_mode":
            if value not in GATHER_MODES:
                raise ValueError(
                    f"gather_mode must be one of {', '.join(GATHER_MODES)}")
            clean[key] = value
        elif key == "terminal_ui":
            if value not in TERMINAL_UIS:
                raise ValueError(
                    f"terminal_ui must be one of {', '.join(TERMINAL_UIS)}")
            clean[key] = value
        elif key == "budget_percent":
            if not isinstance(value, int) or isinstance(value, bool) \
                    or not 5 <= value <= 100:
                raise ValueError("budget_percent must be an integer 5-100")
            clean[key] = value
        elif key == "chat_max_sessions":
            lo, hi = CHAT_SESSIONS_RANGE
            if not isinstance(value, int) or isinstance(value, bool) \
                    or not lo <= value <= hi:
                raise ValueError(
                    f"chat_max_sessions must be an integer {lo}-{hi}")
            clean[key] = value
        elif key == "chat_model":
            # A panel setting, not a Configuration-tab option: it never
            # reaches the add-on's options, so an empty chat picker cannot
            # blank the global model.
            if value is not None and not isinstance(value, str):
                raise ValueError("chat_model must be a string or null")
            clean[key] = (value or "").strip()[:MAX_MODEL_CHARS] or None
        elif is_option(key):
            clean[key] = clean_option(key, value)
        else:
            raise ValueError(f"unknown setting: {key}")
    merged = {**load(), **clean}
    _write(merged)
    return merged


def _write(merged: dict) -> None:
    """Persist the settings file atomically (tmp + replace)."""
    atomic_write.write_json(SETTINGS_FILE, merged)


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
