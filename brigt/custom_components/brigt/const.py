"""Constants for the BRigt integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "brigt"
MANUFACTURER = "BRUH Automation"
MODEL = "BRigt Light Show Director"

# The add-on's shared state dir. The canonical state lives under the
# add-on's /data, which HA Core cannot see; the add-on mirrors what the
# integration needs into /config/.brigt.
SHARED_DIR = "/config/.brigt"
STATE_FILE = f"{SHARED_DIR}/state.json"
COMMAND_REQ_DIR = f"{SHARED_DIR}/requests"
COMMAND_RES_DIR = f"{SHARED_DIR}/responses"

SCAN_INTERVAL = timedelta(seconds=15)

SERVICE_PARTY_MODE = "party_mode"
SERVICE_START_SHOW = "start_show"
SERVICE_STOP_SHOW = "stop_show"
