"""Constants shared by the integration's modules."""
from __future__ import annotations

from pathlib import Path

DOMAIN = "morph"
VERSION = "0.5.0"

PANEL_URL = "morph"
PANEL_TITLE = "Morph"
PANEL_ICON = "mdi:view-dashboard-variant"
ELEMENT = "morph-panel"

FRONTEND_DIR = Path(__file__).parent / "frontend"
STATIC_BASE = "/morph_static"
CARDS_URL = "/morph_cards"

CONFIG = Path("/config")
MORPH_DIR = CONFIG / "morph"
SHARED = CONFIG / ".morph"
BRAIN_SHARED = CONFIG / ".brain"

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
