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
SERVICE_LOG_SPRAY = "log_spray"
SERVICE_QUEUE_SPRAY = "queue_spray"
SERVICE_ADJUST_INVENTORY = "adjust_inventory"
SERVICE_ADD_CROP = "add_crop"
SERVICE_ADD_VARIETY = "add_variety"
SERVICE_LOG_NOTE = "log_note"
SERVICE_GET_HARVESTS = "get_harvests"
SERVICE_REFRESH = "refresh"

# The add-on's action name for each service — written out as literals so the
# tests can read this table without importing Home Assistant.
ACTIONS = {
    "log_harvest": "log_harvest",
    "delete_harvest": "delete_harvest",
    "complete_queued_spray": "complete_queued_spray",
    "delete_queued_spray": "delete_queued_spray",
    "log_spray": "log_spray",
    "queue_spray": "queue_spray",
    "adjust_inventory": "adjust_inventory",
    "add_crop": "add_crop",
    "add_variety": "add_variety",
    "log_note": "log_note",
    "get_harvests": "get_harvests",
}

# The services that only read: they answer and change nothing, so they are
# response-only and ask for no refresh.
READ_ONLY = {"get_harvests"}


HARVEST_UNITS = ["lb", "oz", "kg", "g", "ct"]
