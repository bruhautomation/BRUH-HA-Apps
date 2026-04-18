"""Constants for the BRUH Minecraft integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "bruh_minecraft"
MANUFACTURER = "BRUH Automation"
MODEL = "BRUH Minecraft Server"

# Path to the add-on's shared state dir. The add-on writes stats.json,
# players.json, state.json here; we poll them from HA core.
SHARED_DIR = "/config/.bruh_minecraft"

# The add-on also writes the canonical copies under /data/panel/ — but we can't
# reach there from HA core. The add-on mirrors them into SHARED_DIR on boot.
STATS_FILE = f"{SHARED_DIR}/stats.json"
PLAYERS_FILE = f"{SHARED_DIR}/players.json"
STATE_FILE = f"{SHARED_DIR}/state.json"
COMMAND_REQ_DIR = f"{SHARED_DIR}/requests"
COMMAND_RES_DIR = f"{SHARED_DIR}/responses"

SCAN_INTERVAL = timedelta(seconds=15)

SIGNAL_UPDATE = f"{DOMAIN}_update"

SERVICE_COMMAND = "rcon_command"
SERVICE_SAY = "say"
SERVICE_GIVE = "give"
SERVICE_WEATHER = "set_weather"
SERVICE_TIME = "set_time"
SERVICE_BACKUP = "backup_now"
SERVICE_RESTART = "restart_server"
SERVICE_STOP = "stop_server"
SERVICE_OP = "op_player"
SERVICE_DEOP = "deop_player"
SERVICE_KICK = "kick_player"
SERVICE_BAN = "ban_player"
SERVICE_WHITELIST_ADD = "whitelist_add"
SERVICE_WHITELIST_REMOVE = "whitelist_remove"
