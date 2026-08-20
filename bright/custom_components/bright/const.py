"""Constants for the BRight integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "bright"
MANUFACTURER = "BRUH Automation"
MODEL = "BRight Light Show Director"

# The add-on's shared state dir. The canonical state lives under the
# add-on's /data, which HA Core cannot see; the add-on mirrors what the
# integration needs into /config/.bright.
SHARED_DIR = "/config/.bright"
STATE_FILE = f"{SHARED_DIR}/state.json"
COMMAND_REQ_DIR = f"{SHARED_DIR}/requests"
COMMAND_RES_DIR = f"{SHARED_DIR}/responses"

SCAN_INTERVAL = timedelta(seconds=15)

SERVICE_PARTY_MODE = "party_mode"
SERVICE_START_PARTY = "start_party"
SERVICE_START_SHOW = "start_show"
SERVICE_STOP_SHOW = "stop_show"

# The add-on mirrors the names of the saved parties here, because /data is
# invisible to Core and "which parties exist" is a question a dashboard
# asks. Derived and never written by this side.
PARTIES_FILE = f"{SHARED_DIR}/parties.json"
