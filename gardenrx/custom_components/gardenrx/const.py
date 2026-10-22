"""Constants for the GardenRX integration."""

DOMAIN = "gardenrx"
VERSION = "0.1.2"

CONF_HOST = "host"
CONF_PORT = "port"
DEFAULT_PORT = 8101

# The add-on writes this token and the integration sends it as a bearer token.
# Both sides read /config, so nothing about it crosses a network to arrive.
TOKEN_PATH = ".gardenrx/api_token"

SCAN_INTERVAL_S = 60
REQUEST_TIMEOUT_S = 20

# The card file the integration serves to the frontend. The version is in the
# URL so an update is a new URL, and no browser keeps last release's card.
CARDS_FILE = "gardenrx-cards.js"
CARDS_URL_BASE = "/gardenrx_static"

ATTR_KIND = "gardenrx"

SERVICE_LOG_HARVEST = "log_harvest"
SERVICE_DELETE_HARVEST = "delete_harvest"
SERVICE_COMPLETE_QUEUED_SPRAY = "complete_queued_spray"
SERVICE_DELETE_QUEUED_SPRAY = "delete_queued_spray"
SERVICE_REFRESH = "refresh"

# The add-on's action name for each service — written out as literals so the
# tests can read this table without importing Home Assistant.
ACTIONS = {
    "log_harvest": "log_harvest",
    "delete_harvest": "delete_harvest",
    "complete_queued_spray": "complete_queued_spray",
    "delete_queued_spray": "delete_queued_spray",
}

HARVEST_UNITS = ["lb", "oz", "kg", "g", "ct"]
