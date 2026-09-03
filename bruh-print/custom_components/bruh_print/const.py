"""Constants shared by the bruh_print integration.

Nothing in here imports Home Assistant, deliberately: `card_url` below is a
pure function of a path, and a test can drive it in a checkout that has no
`homeassistant` installed — which is every checkout this repo's CI runs in.
"""
from __future__ import annotations

import hashlib
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

# How long the integration keeps looking for a card that is not there yet,
# and how often. Home Assistant may well set this entry up before the add-on
# has finished starting — a first install, or an add-on update while Core was
# already running — and giving up at that moment means no card until the next
# Core restart. Twenty minutes is longer than any start this add-on has, and
# bounded so a genuinely absent card (install_lovelace_card off) stops costing
# a timer.
CARD_RETRY_SECONDS = 30
CARD_RETRY_TRIES = 40
# hass.data[DOMAIN] is otherwise keyed by entry_id, which never looks like
# this.
CARD_RETRY_CANCEL = "card_retry_cancel"


def card_url(path: Path) -> str:
    """The URL to register the card at, with the file's own bytes on the end.

    Core serves everything under /local with `Cache-Control: public,
    max-age=2678400` — 31 days. The add-on rewrites the card in place on
    every start, so an update to it reaches a browser that has already
    cached one exactly never: people were still being shown the 0.1.0 card,
    with its roll dropdown and its lab placeholders, two releases later. A
    URL that changes when the file changes is what HACS does for the same
    reason, and it costs one hash of a small file at setup.

    It is a hash of the CONTENT and not of CARD_VERSION on purpose: the
    version is what somebody remembers to bump, and the hash is what
    changed. Twelve hex characters is 48 bits — this only has to differ
    between two versions of one file, not resist anybody.

    Reads the file, so call it in the executor.
    """
    digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    return f"{CARD_URL}?v={digest}"
