"""Constants shared by Morph's half of the brAIn integration.

Morph was an add-on and an integration of its own until brAIn 4.0; it is a
part of brAIn now (docs/design/brain-morph-merge.md). The websocket command
names (`morph/*`), the static paths and the folders under /config kept their
names, so a house's dashboard, its history and its cards are where they were.
"""
from __future__ import annotations

import json
from pathlib import Path

# The key under hass.data: brAIn's own `brain` key holds the integration's
# entries, and Morph's watcher and subscriptions are kept apart from it.
DOMAIN = "brain_morph"


def _version() -> str:
    try:
        with open(Path(__file__).resolve().parent.parent / "manifest.json", encoding="utf-8") as f:
            return str(json.load(f).get("version") or "0")
    except (OSError, ValueError):
        return "0"


# brAIn's version: the panel's modules are served under it.
VERSION = _version()

# The one sidebar entry: brAIn's shell, which holds Morph (the Home tab) and
# brAIn's own page (shell.js).
PANEL_URL = "brain"
PANEL_TITLE = "brAIn"
PANEL_ICON = "mdi:brain"
ELEMENT = "brain-shell"

FRONTEND_DIR = Path(__file__).parent / "frontend"
STATIC_BASE = "/morph_static"
CARDS_URL = "/morph_cards"

CONFIG = Path("/config")
MORPH_DIR = CONFIG / "morph"
SHARED = CONFIG / ".morph"
BRAIN_SHARED = CONFIG / ".brain"
# brAIn's switches (panel/features.py, the one writer): whether the Morph
# dashboard is on, and the assistant's name while Personality is.
FEATURES = BRAIN_SHARED / "features.json"
# Where brAIn's own page is (written by brAIn's panel off the Supervisor), so
# the shell can open it in its frame.
INGRESS = BRAIN_SHARED / "ingress.json"
# Written while the shell panel is registered and rewritten every few
# minutes: brAIn hides its own ingress sidebar entry only while this is
# fresh, so a Home Assistant that did not load this integration never leaves
# a house without a way in.
SHELL_MARK = BRAIN_SHARED / "shell.json"
SHELL_BEAT_S = 240

REQUEST_DIR = SHARED / "requests"
RESPONSE_DIR = SHARED / "responses"
MIRROR = SHARED / "dashboard.json"
STATE = SHARED / "state.json"
TELLS = SHARED / "tells"
SHOTS = SHARED / "shots"
USAGE = SHARED / "usage.jsonl"
ERRORS = SHARED / "errors.jsonl"
DASHBOARD = MORPH_DIR / "dashboard.yaml"
CARDS_DIR = MORPH_DIR / "cards"
# This house's changes to Morph's own panel modules, and the add-on's
# verdict on which of them are in use (the add-on's morphcode.py).
CODE_DIR = MORPH_DIR / "frontend"
CODE_STATE = SHARED / "code.json"

REQUEST_TIMEOUT = 45
WATCH_SECONDS = 2
