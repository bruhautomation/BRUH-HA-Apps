"""Constants shared by the bruh_bambu integration. No Home Assistant imports."""
from __future__ import annotations

from pathlib import Path

DOMAIN = "bruh_bambu"

# /data is invisible to Core, so everything Core reads is mirrored here.
SHARED = Path("/config/.bruh_bambu")
STATE_FILE = SHARED / "state.json"
REQUEST_DIR = SHARED / "requests"
RESPONSE_DIR = SHARED / "responses"

# A print whose file has to be sliced first is minutes of CPU; the panel
# waits up to 15 minutes for it and this waits a little longer, so a
# service never reports a failure about a print that is starting.
REQUEST_TIMEOUT = 1000
SCAN_INTERVAL_SECONDS = 5
# The panel rewrites the mirror at least once a minute. Older than this
# and the panel has stopped, so the sensors say so rather than serving the
# last reading as current.
STALE_AFTER_SECONDS = 180

SERVICE_STATUS = "get_status"
SERVICE_LIST_FILES = "list_files"
SERVICE_PRINTER_FILES = "printer_files"
SERVICE_PRINT_FILE = "print_file"
SERVICE_SLICE_FILE = "slice_file"
SERVICE_PAUSE = "pause_print"
SERVICE_RESUME = "resume_print"
SERVICE_STOP = "stop_print"
SERVICE_SPEED = "set_speed"
SERVICE_LIGHT = "set_light"
SERVICE_TEMPERATURE = "set_temperature"
SERVICE_GCODE = "send_gcode"
SERVICE_OPEN = "open_in_studio"
