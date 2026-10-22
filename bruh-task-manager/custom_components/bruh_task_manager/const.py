"""Constants for the bruh_task_manager integration. No Home Assistant imports."""
from __future__ import annotations

from pathlib import Path

DOMAIN = "bruh_task_manager"

# The add-on writes this; /data is invisible to Core, so it is mirrored here.
STATE_FILE = Path("/config/.bruh_task_manager/state.json")

SCAN_INTERVAL_SECONDS = 15
