"""⚙ › Minecraft: the settings of brAIn's Minecraft faculty, and what it did.

The faculty itself runs in the integration (custom_components/brain/
minecraft.py), beside Home Assistant's event bus, because BRUH Minecraft's
game events arrive there and its services are called from there. This
module is the panel's half and the ONE writer of its settings
(`/config/.brain/minecraft/settings.json`): the on/off switch, the family
list and roles, bedtime, the budgets (0 = unlimited, the default), and the
model and effort for replies and for builds — "Default" resolved here
through `model_plan` (the jobs `minecraft_chat` and `minecraft_build`) and
written beside the choice, so the listener needs no copy of the plan.

What the companion did in the world is BRUH Minecraft's action log, read
through its `get_companion` service and undone through `undo_action`, so
the list in ⚙ and the add-on's own card agree, with Undo in both.

The rules (who is family, the settings' shapes, what it learned) are
`minecraft_rules`, loaded from the integration's folder beside this one.
"""
from __future__ import annotations

import importlib.util
import os
import sys
import time
from pathlib import Path
from typing import Any

import model_plan

SHARED_DIR = os.environ.get("BRAIN_SHARED_DIR", "/config/.brain")
INTEGRATION_DIR = os.environ.get(
    "BRAIN_INTEGRATION_DIR",
    str(Path(__file__).resolve().parent.parent / "custom_components" / "brain"))


def _load_rules():
    name = "brain_minecraft_rules"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(INTEGRATION_DIR, "minecraft_rules.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rules = _load_rules()

MODEL_CHOICES = ("", "haiku", "sonnet", "opus")


def _path(name: str, shared_dir: str | None = None) -> str:
    return os.path.join(rules.folder(shared_dir or SHARED_DIR), name)


def _thinking() -> str:
    try:
        import settings_store  # noqa: PLC0415 — the panel's, not needed by the rules
        return str(settings_store.load().get("thinking") or model_plan.DEFAULT_THINKING)
    except Exception:  # noqa: BLE001 — the plan's default is a fine answer
        return model_plan.DEFAULT_THINKING


def _chat_agent_model() -> str:
    try:
        import settings_store  # noqa: PLC0415
        return str(settings_store.load().get("chat_model") or "")
    except Exception:  # noqa: BLE001
        return ""


def resolved_models() -> dict[str, dict[str, str]]:
    """What "Default" means today: a reply is the quick tier; a build is the
    chat agent's own model when one is chosen, else the middle tier."""
    thinking = _thinking()
    chat_model, chat_effort = model_plan.resolve("minecraft_chat", thinking)
    build_model, build_effort = model_plan.resolve("minecraft_build", thinking)
    agent = _chat_agent_model()
    return {"chat": {"model": chat_model, "effort": chat_effort},
            "build": {"model": agent or build_model, "effort": build_effort}}


def load(shared_dir: str | None = None) -> dict[str, Any]:
    return rules.effective_settings(shared_dir or SHARED_DIR)


def save(fields: dict, shared_dir: str | None = None) -> dict[str, Any]:
    """Keep the settings a person chose (any of them). Raises
    `rules.RulesError` with a sentence when one cannot be kept."""
    if not isinstance(fields, dict):
        raise rules.RulesError("Settings are an object.")
    cur = load(shared_dir)
    merged = dict(cur)
    for key in ("enabled", "greet"):
        if key in fields:
            if not isinstance(fields[key], bool):
                raise rules.RulesError(f"{key} is true or false.")
            merged[key] = fields[key]
    if "people" in fields:
        merged["people"] = rules.clean_people(fields["people"])
    if "bedtime_entity" in fields:
        merged["bedtime_entity"] = str(fields["bedtime_entity"] or "").strip()
    if "budgets" in fields:
        if not isinstance(fields["budgets"], dict):
            raise rules.RulesError("budgets is an object of numbers (0 is unlimited).")
        budgets = dict(cur["budgets"])
        for key, value in fields["budgets"].items():
            if key not in rules.BUDGETS:
                raise rules.RulesError(f"{key} is not a budget.")
            try:
                n = int(value)
            except (TypeError, ValueError):
                raise rules.RulesError(f"{key} is a number (0 is unlimited).") from None
            if n < 0:
                raise rules.RulesError(f"{key} is 0 (unlimited) or more.")
            budgets[key] = n
        merged["budgets"] = budgets
    for key in ("chat_model", "build_model"):
        if key in fields:
            value = str(fields[key] or "").strip()
            if value and value not in MODEL_CHOICES and not value.startswith("claude-"):
                raise rules.RulesError("A model is Default, haiku, sonnet, opus or a claude- id.")
            merged[key] = value
    for key in ("chat_effort", "build_effort"):
        if key in fields:
            value = str(fields[key] or "").strip().lower()
            if value and value not in rules.EFFORTS:
                raise rules.RulesError("Effort is Default, low, medium, high, xhigh or max.")
            merged[key] = value
    merged["models"] = resolved_models()
    merged["saved_at"] = int(time.time())
    clean = rules.clean_settings(merged, strict=True)
    rules.write_json(_path(rules.SETTINGS, shared_dir), clean)
    return clean


def publish(shared_dir: str | None = None) -> bool:
    """Write today's meaning of "Default" beside the settings, when it moved
    (the thinking level or the chat model changed). True when written."""
    path = _path(rules.SETTINGS, shared_dir)
    # Only for a house that has the faculty's files already (settings
    # saved, or the 1.17.7 handover): a house without BRUH Minecraft gets no
    # folder, and a missing shared folder is never made from here.
    if not (os.path.exists(path) or os.path.exists(_path(rules.HANDOVER, shared_dir))):
        return False
    raw = rules.read_json(path, {})
    want = resolved_models()
    if raw.get("models") == want:
        return False
    raw["models"] = want
    try:
        rules.write_json(path, raw)
    except OSError:
        return False
    return True


def view(shared_dir: str | None = None) -> dict[str, Any]:
    """What ⚙ › Minecraft shows, from brAIn's own files."""
    base = shared_dir or SHARED_DIR
    settings = load(base)
    state = rules.read_json(_path(rules.STATE, base), {})
    if state.get("day") != rules.day_of(time.time()):
        state = {"turns": 0, "actions": 0, "paused": state.get("paused", False)}
    talks = rules.read_json(_path(rules.TALKS, base), {}).get("talks") or []
    memory = rules.read_json(_path(rules.PEOPLE, base), {})
    handover = rules.read_json(_path(rules.HANDOVER, base), {})
    name = rules.persona_name(base)
    return {"settings": settings, "name": name, "wake_words": list(rules.wake_words(name)),
            "defaults": resolved_models(), "model_choices": list(MODEL_CHOICES),
            "efforts": list(rules.EFFORTS),
            "today": {"turns": state.get("turns", 0), "actions": state.get("actions", 0)},
            "paused": bool(state.get("paused")), "paused_by": state.get("paused_by") or "",
            "talks": talks[:20],
            "people": {p: {"sessions": r.get("sessions", 0), "seconds": r.get("seconds", 0),
                           "favourite_places": rules.favourites(r)}
                       for p, r in memory.items() if isinstance(r, dict)},
            "handed_over": bool(handover)}


def learned(shared_dir: str | None = None) -> list[dict[str, Any]] | None:
    """What the companion learned, as fixed-word lines per person and key,
    or None when its memory could not be read (nothing touched then)."""
    import json  # noqa: PLC0415
    path = _path(rules.PEOPLE, shared_dir)
    try:
        with open(path, encoding="utf-8") as fh:
            memory = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(memory, dict):
        return None
    return rules.learned_facts(memory, rules.persona_name(shared_dir or SHARED_DIR))


__all__ = ["load", "save", "publish", "view", "learned", "resolved_models", "rules"]
