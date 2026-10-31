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
# What is going on in the world (panel/mcworld.py): players and where they
# are, time, weather, the feed, saves, backups and the companion's builds.
WORLD_FILE = f"{SHARED_DIR}/world.json"
# The add-on rewrites stats.json every 15 s and world.json every few
# seconds (a minute when nobody is on). Older than this, the add-on is not
# running and what the file says is not true any more.
STALE_AFTER = 180
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
SERVICE_PARDON = "pardon_player"
SERVICE_TELEPORT = "teleport"
SERVICE_GAMEMODE = "set_gamemode"
SERVICE_STATUS = "get_status"

GAMEMODES = ("survival", "creative", "adventure", "spectator")

# A player argument is a name the server knows, or one of the selectors a
# person would say out loud ("everyone", "the nearest player"). Java names
# are 3–16 of [A-Za-z0-9_]; a Bedrock player through Floodgate carries a
# one-character prefix (`.` by default), so 17 is the real ceiling. `*` is
# in the class because some Floodgate configs use it as the prefix.
PLAYER_PATTERN = r"^(@[aprs]|[A-Za-z0-9_.*]{1,17})$"
SERVICE_WORLD = "get_world"
SERVICE_BUILDS = "list_builds"
SERVICE_BUILD_SAVE = "save_build"
SERVICE_BUILD_DELETE = "delete_build"
BUILD_STATUSES = ("queued", "building", "done", "failed")
SERVICE_ADDONS = "list_addons"
SERVICE_ADDON_SEARCH = "search_addons"
SERVICE_ADDON_INSTALL = "install_addon"
SERVICE_ADDON_REMOVE = "remove_addon"
ADDON_KINDS = ("plugin", "datapack", "mod", "resourcepack")
# The companion's hands (panel/companion.py): mechanics a companion — brAIn's
# Minecraft faculty, or anybody's automation — drives. The add-on decides
# nothing with them; the speaker's name and colour come from the caller.
SERVICE_COMPANION = "get_companion"
SERVICE_SET_COMPANION = "set_companion"
SERVICE_COMPANION_SAY = "companion_say"
SERVICE_COMPANION_APPEAR = "companion_appear"
SERVICE_ASK_CHOICE = "ask_choice"
SERVICE_COMPANION_BUILD = "companion_build"
SERVICE_UNDO_ACTION = "undo_action"
SERVICE_SET_ZONE = "set_zone"
SERVICE_COMPANION_HANDOVER = "companion_handover"
SERVICE_RENAME_WORLD = "rename_world"
# Fired by the add-on for every game happening it reads, whether or not
# anything listens: neutral facts, no scores, caps or persona (DOCS.md, "The
# companion contract"). `answer` is a choice pad being answered.
GAME_EVENTS = ("chat", "join", "leave", "death", "advancement", "place", "answer")
EVENT_PREFIX = "bruh_minecraft_"
