"""Constants shared by the bruh_print integration."""
from __future__ import annotations

from pathlib import Path

DOMAIN = "bruh_print"

# The add-on and Home Assistant share this folder. /data is invisible to
# Core, so everything Core needs to read is mirrored here by the panel.
SHARED = Path("/config/.bruh_print")
STATE_FILE = SHARED / "state.json"
REQUEST_DIR = SHARED / "requests"
RESPONSE_DIR = SHARED / "responses"

SERVICE_PRINT_TEXT = "print_text"
SERVICE_PRINT_TEMPLATE = "print_template"
SERVICE_PRINT_LABEL = "print_label"
SERVICE_REPRINT = "reprint"
SERVICE_SET_ROLL = "set_roll"
SERVICE_PRINT_TEST = "print_test"

# How long to wait for the add-on to answer a request. Longer than the
# bridge's own forward timeout on purpose: a print that is slow because the
# printer is chewing through 200 copies is still going to succeed, and a
# service that gives up first would report a failure about labels that are
# coming out of the printer as it says so.
REQUEST_TIMEOUT = 150

# The card and the sensors both read the mirror. 5s rather than 30: the whole
# point of the roll sensors is that they are right when somebody is standing
# at the printer, and reading one small JSON file is nothing.
SCAN_INTERVAL_SECONDS = 5

# Where run.sh puts the card, and the URL Core serves it from.
CARD_URL = "/local/bruh_print/bruh-print-card.js"
CARD_FILE = Path("/config/www/bruh_print/bruh-print-card.js")
