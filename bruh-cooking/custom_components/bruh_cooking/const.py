"""Constants for the Breville+ Cooking integration."""

from datetime import timedelta

DOMAIN = "bruh_cooking"

# The appliance list is refreshed this often; live state arrives over the
# websocket.
APPLIANCE_REFRESH_INTERVAL = timedelta(minutes=30)

# Websocket reconnect backoff, as the app: 5 s growing x1.8, capped here.
WS_RECONNECT_MIN = 5.0
WS_RECONNECT_FACTOR = 1.8
WS_RECONNECT_MAX = 300.0

# Brand of the account's app. Sage is the brand in the UK, Europe and the UAE;
# these are the countries of the Sage app's locales.
CONF_BRAND = "brand"
BRAND_BREVILLE = "breville"
BRAND_SAGE = "sage"
SAGE_COUNTRIES = frozenset(
    {"AE", "AT", "BE", "CH", "DE", "DK", "ES", "FI", "FR", "GB", "IE", "IT", "LU",
     "NL", "NO", "PL", "PT", "SE"}
)

# Option: allow starting and changing cooks on models nobody has tested.
CONF_ALLOW_UNTESTED_CONTROL = "allow_untested_control"
# Option: list the account's appliances in the sidebar panel. Saved only when
# off, so a missing key means on.
CONF_SHOW_SIDEBAR_PANEL = "show_sidebar_panel"
DEFAULT_SHOW_SIDEBAR_PANEL = True

# Recent websocket messages and cloud requests kept for diagnostics.
MESSAGE_LOG_SIZE = 50

SERVICE_START_COOK = "start_cook"
ATTR_TEMPERATURE = "temperature"
ATTR_DURATION = "duration"
ATTR_MODE = "mode"
ATTR_CONVECTION = "convection"
ATTR_LEVEL = "level"
ATTR_AUTO_START_TIMER = "auto_start_timer"
ATTR_KEEP_WARM = "keep_warm"
