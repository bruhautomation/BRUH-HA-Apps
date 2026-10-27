"""brAIn's switches as the integration reads them. Pure (no Home Assistant
import), so the websocket commands and a test can read them alike."""
from __future__ import annotations

import json

from .const import FEATURES, PANEL_TITLE

NAME_MAX = 60


def read_features(path=FEATURES) -> dict:
    """brAIn's switches as its panel wrote them. Unreadable is every switch
    at its quiet default: the shell still opens brAIn, with no Home tab."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    name = " ".join(str(data.get("name") or "").split())[:NAME_MAX] if data.get("personality") is True else ""
    return {
        "morph": data.get("morph") is True,
        "personality": data.get("personality") is True,
        "learning_loop": data.get("learning_loop") is not False,
        "development_loop": data.get("development_loop") is True,
        "name": name or PANEL_TITLE,
    }
